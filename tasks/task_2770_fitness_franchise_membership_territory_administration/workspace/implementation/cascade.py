"""Derived counters, the dues-ledger projection and the franchisee compliance chain.

Nothing here is incremented on faith: every figure is recomputed from the
records that define it, inside the request that disturbed them (PRD 2.10).
"""
from decimal import Decimal

import config
from calc import half_up  # noqa: F401  (kept for symmetry with calc users)
from store import db, clock_date, parse_date, days_between, touch, ledger_fields

DELINQUENT_SET = set(config.DELINQUENT_DUES_STATES)


# --------------------------------------------------------------------------
# ledger helpers
# --------------------------------------------------------------------------
def ledger_of(agreement_id):
    rows = [e for e in db.billing_events.values() if e["agreement_id"] == agreement_id]
    return sorted(rows, key=lambda e: (e["occurred_on"], e["created_at"], e["_seq"]))


def charges_of(rows):
    charges = [e for e in rows if e["event_type"] in ("DUES_POSTED", "TRANSFER_FEE_POSTED")]
    return sorted(charges, key=lambda e: (e["due_on"] or "", e["created_at"], e["_seq"]))


def project(agreement):
    """The full projection over an agreement's ledger (PRD 3.4)."""
    rows = ledger_of(agreement["id"])
    payments = sum(e["amount_cents"] for e in rows if e["event_type"] == "PAYMENT_RECEIVED")
    write_offs = sum(e["amount_cents"] for e in rows if e["event_type"] == "WRITE_OFF")
    charges = charges_of(rows)
    charge_total = sum(e["amount_cents"] for e in charges)
    outstanding = charge_total - payments - write_offs

    credit = payments + write_offs
    earliest_unsatisfied = None
    for charge in charges:
        if credit >= charge["amount_cents"]:
            credit -= charge["amount_cents"]
        else:
            earliest_unsatisfied = charge
            break

    if outstanding <= 0 or earliest_unsatisfied is None:
        delinquency_days = 0
    else:
        aged = days_between(clock_date(), parse_date(earliest_unsatisfied["due_on"]))
        delinquency_days = max(0, aged)

    return {
        "dues_paid_cents": payments,
        "write_off_cents": write_offs,
        "outstanding_balance_cents": outstanding,
        "delinquency_days": delinquency_days,
        "payment_count": sum(1 for e in rows if e["event_type"] == "PAYMENT_RECEIVED"
                             and e["amount_cents"] > 0),
    }


def resolve_dues_status(prior, outstanding, delinquency_days):
    if outstanding <= 0:
        return "CURRENT"
    if prior in ("IN_COLLECTIONS", "WRITTEN_OFF"):
        return prior
    if delinquency_days >= config.DELINQUENCY_DAYS_THRESHOLD:
        return "DELINQUENT"
    if delinquency_days >= 1:
        return "PAST_DUE"
    return "CURRENT"


def apply_projection(agreement, write_off_applied=False):
    """Re-runs the projection and resolves the collections dimension.

    Returns (prior_dues_status, new_dues_status).
    """
    figures = project(agreement)
    prior = agreement["dues_status"]
    agreement["dues_paid_cents"] = figures["dues_paid_cents"]
    agreement["outstanding_balance_cents"] = figures["outstanding_balance_cents"]
    agreement["delinquency_days"] = figures["delinquency_days"]
    new_status = resolve_dues_status(prior, figures["outstanding_balance_cents"],
                                    figures["delinquency_days"])
    if write_off_applied and figures["outstanding_balance_cents"] > 0:
        new_status = "WRITTEN_OFF"
    agreement["dues_status"] = new_status
    return prior, new_status


def append_system_event(agreement, event_type, amount_cents, occurred_on, due_on=None):
    """Appends a SYSTEM-sourced ledger row; the caller re-runs the projection."""
    row = ledger_fields()
    row.update({
        "agreement_id": agreement["id"],
        "event_type": event_type,
        "amount_cents": amount_cents,
        "occurred_on": occurred_on,
        "due_on": due_on,
        "source": "SYSTEM",
        "resulting_outstanding_balance_cents": 0,
    })
    db.billing_events[row["id"]] = row
    return row


# --------------------------------------------------------------------------
# club counters (PRD 3.4)
# --------------------------------------------------------------------------
def club_counters(club):
    live = [a for a in db.agreements.values()
            if a["home_club_id"] == club["id"]
            and a["agreement_status"] in config.LIVE_AGREEMENT_STATES]
    denominator = len(live)
    numerator = sum(1 for a in live if a["dues_status"] in DELINQUENT_SET)
    watch = denominator > 0 and (Decimal(numerator) / Decimal(denominator)
                                 > config.COLLECTIONS_WATCH_SHARE)
    return denominator, numerator, watch


def recompute_club(club, bump="if_changed"):
    before = (club["active_agreement_count"], club["delinquent_member_count"],
              club["collections_watch"])
    active, delinquent, watch = club_counters(club)
    club["active_agreement_count"] = active
    club["delinquent_member_count"] = delinquent
    club["collections_watch"] = watch
    after = (active, delinquent, watch)
    if bump == "always" or (bump == "if_changed" and before != after):
        touch(club)
        return True
    return False


# --------------------------------------------------------------------------
# franchisee standing (PRD 3.9)
# --------------------------------------------------------------------------
SCORED_INSPECTION_STATES = ("SCORED", "REMEDIATION_REQUIRED", "REMEDIATION_WAIVED", "CLOSED")


def inspection_fail_streak(franchisee_id):
    club_ids = {c["id"] for c in db.clubs.values() if c["franchisee_id"] == franchisee_id}
    rows = [i for i in db.inspections.values()
            if i["club_id"] in club_ids
            and i["status"] in SCORED_INSPECTION_STATES
            and i["score"] is not None]
    rows.sort(key=lambda i: (i["inspection_date"], i["created_at"], i["_seq"]))
    streak = 0
    for row in rows:
        if row["score"] < config.PROBATION_SCORE_THRESHOLD:
            streak += 1
        else:
            streak = 0
    return streak


def withdraw_approved_promotions(franchisee_id):
    for promo in db.promotions.values():
        if promo["franchisee_id"] == franchisee_id and promo["status"] == "APPROVED":
            promo["status"] = "WITHDRAWN_BY_BRAND"
            promo["withdrawn_reason"] = "FRANCHISEE_PROBATION"
            touch(promo)


def recompute_franchisee(franchisee, bump="if_changed"):
    if franchisee is None:
        return False
    before = (franchisee["inspection_fail_streak"], franchisee["collections_watch_club_count"],
              franchisee["disputed_royalty_count"], franchisee["compliance_score"],
              franchisee["status"])

    streak = inspection_fail_streak(franchisee["id"])
    watch_clubs = sum(1 for c in db.clubs.values()
                      if c["franchisee_id"] == franchisee["id"] and c["collections_watch"])
    disputed = sum(1 for r in db.royalty_reports.values()
                   if r["franchisee_id"] == franchisee["id"] and r["status"] == "DISPUTED")

    score = 100
    score -= config.INSPECTION_FAIL_PENALTY * streak
    if watch_clubs > 0:
        score -= config.COLLECTIONS_WATCH_PENALTY
    score -= config.DISPUTED_ROYALTY_PENALTY * disputed
    score = max(0, min(100, score))

    franchisee["inspection_fail_streak"] = streak
    franchisee["collections_watch_club_count"] = watch_clubs
    franchisee["disputed_royalty_count"] = disputed
    franchisee["compliance_score"] = score

    if franchisee["status"] == "ACTIVE" and score < config.PROBATION_SCORE_THRESHOLD:
        franchisee["status"] = "PROBATION"
        withdraw_approved_promotions(franchisee["id"])

    after = (streak, watch_clubs, disputed, score, franchisee["status"])
    if bump == "always" or (bump == "if_changed" and before != after):
        touch(franchisee)
        return True
    return False


def franchisee_of_club(club):
    return db.franchisees.get(club["franchisee_id"])


# --------------------------------------------------------------------------
# corporate enrolment (PRD 3.3 / 3.8)
# --------------------------------------------------------------------------
def recompute_corporate_enrolment(account):
    if account is None:
        return
    account["enrolled_agreement_count"] = sum(
        1 for a in db.agreements.values()
        if a.get("corporate_account_id") == account["id"]
        and a["agreement_status"] in config.ENROLLED_AGREEMENT_STATES)


def corporate_of(agreement):
    cid = agreement.get("corporate_account_id")
    return db.corporate_accounts.get(cid) if cid else None


# --------------------------------------------------------------------------
# member standing (PRD 3.3)
# --------------------------------------------------------------------------
def member_agreement_count(member_id):
    return sum(1 for a in db.agreements.values()
               if a["member_id"] == member_id
               and a["agreement_status"] in config.HELD_AGREEMENT_STATES)


def recompute_member(member, bump=True):
    member["agreement_count"] = member_agreement_count(member["id"])
    if member["agreement_count"] == 0 and member["status"] == "ACTIVE":
        member["status"] = "INACTIVE"
    if bump:
        touch(member)
