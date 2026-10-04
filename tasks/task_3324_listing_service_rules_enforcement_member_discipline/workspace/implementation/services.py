"""Business-logic services: cascades, clock evaluation, citations, member
suspension/reinstatement/termination chains."""

from datetime import timedelta

import calcs
from db import store, now, _parse_iso
from helpers import new_id, now_iso_str, touch, mint_common


# ---------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------

def create_citation(association_id, member_id, rule_code, source,
                    listing_id=None):
    """Look up fine, mint citation in OPEN status."""
    assessed = now()
    row = calcs.lookup_fine(association_id, rule_code, assessed)
    cit = {
        "association_id": association_id,
        "member_id": member_id,
        "listing_id": listing_id,
        "rule_code": rule_code,
        "source": source,
        "fine_schedule_key": calcs.fine_schedule_key(rule_code, assessed),
        "fine_amount_cents": row["fine_amount_cents"],
        "hearing_requested": False,
        "assessed_at": now_iso_str(),
        "status": "OPEN",
    }
    mint_common(cit)
    store.citations[cit["id"]] = cit
    return cit


def listing_unflag_chain(citation):
    """If the citation references a FLAGGED listing and no other
    OPEN/HEARING_PENDING citation references that listing, clear the flag."""
    listing_id = citation.get("listing_id")
    if not listing_id:
        return
    listing = store.listings.get(listing_id)
    if listing is None or listing["accuracy_flag"] != "FLAGGED":
        return
    for c in store.citations.values():
        if c["id"] == citation["id"]:
            continue
        if c.get("listing_id") == listing_id and c["status"] in ("OPEN", "HEARING_PENDING"):
            return
    listing["accuracy_flag"] = "CLEAN"
    touch(listing)


def credit_member_for_paid_citation(member, citation):
    """Accrue fine_amount_cents to member's credit balance with cap check.
    Caller must have already verified the cap. Returns nothing."""
    member["sanction_credit_balance_cents"] += citation["fine_amount_cents"]
    touch(member)
    calcs.recompute_strikes(member)
    listing_unflag_chain(citation)


# ---------------------------------------------------------------------------
# Member suspension / reinstatement / termination
# ---------------------------------------------------------------------------

def suspend_member(member, trigger_grace_end_date=None):
    """ACTIVE -> SUSPENDED with cascades (office suspension included)."""
    if member["membership_state"] != "ACTIVE":
        return
    member["membership_state"] = "SUSPENDED"
    member["mls_access_state"] = "DISABLED"
    store.suspensions[member["id"]] = {
        "suspended_at": now(),
        "trigger_grace_end_date": trigger_grace_end_date,
    }
    touch(member)
    # broker suspension suspends the office
    for office in store.offices.values():
        if office["broker_member_id"] == member["id"] and office["status"] == "ACTIVE":
            office["status"] = "SUSPENDED"
            touch(office)


def reinstate_member(member):
    """SUSPENDED -> ACTIVE chain: mls access ENABLED, record reinstatement
    instant, recompute strikes, restore office."""
    if member["membership_state"] != "SUSPENDED":
        return
    member["membership_state"] = "ACTIVE"
    member["mls_access_state"] = "ENABLED"
    store.reinstatements.setdefault(member["id"], []).append(now())
    store.suspensions.pop(member["id"], None)
    calcs.recompute_strikes(member)
    touch(member)
    for office in store.offices.values():
        if office["broker_member_id"] == member["id"] and office["status"] == "SUSPENDED":
            office["status"] = "ACTIVE"
            touch(office)


def maybe_reinstate_after_settlement(member):
    """If the member now holds zero PENDING invoices and is SUSPENDED, run the
    reinstatement chain."""
    if member["membership_state"] != "SUSPENDED":
        return
    pending = [i for i in store.dues_invoices.values()
               if i["member_id"] == member["id"] and i["status"] == "PENDING"]
    if not pending:
        reinstate_member(member)


def terminate_member(member):
    """SUSPENDED -> TERMINATED: listings in ACTIVE -> WITHDRAWN cascade."""
    member["membership_state"] = "TERMINATED"
    member["mls_access_state"] = "DISABLED"
    touch(member)
    for listing in store.listings.values():
        if listing["listing_member_id"] == member["id"] and listing["status"] == "ACTIVE":
            record_status_change(listing, "ACTIVE", "WITHDRAWN",
                                 business_effective_at=now_iso_str(),
                                 audit=False)
            listing["status"] = "WITHDRAWN"
            listing["status_changed_at"] = now_iso_str()
            touch(listing)


# ---------------------------------------------------------------------------
# Status changes
# ---------------------------------------------------------------------------

def record_status_change(listing, from_status, to_status, business_effective_at,
                         audit=True):
    """Append a StatusChange audit record; run the lateness audit for
    transitions into PENDING/SOLD when audit=True."""
    recorded = now()
    late_by_hours = 0
    auto_citation_id = None
    if audit and to_status in ("PENDING", "SOLD"):
        late_by_hours = calcs.compute_late_by_hours(recorded, business_effective_at)
    sc = {
        "listing_id": listing["id"],
        "from_status": from_status,
        "to_status": to_status,
        "business_effective_at": business_effective_at,
        "recorded_at": now_iso_str(),
        "late_by_hours": late_by_hours,
        "auto_citation_id": None,
    }
    mint_common(sc)
    if late_by_hours > 0:
        office = store.offices.get(listing["office_id"])
        cit = create_citation(office["association_id"],
                              listing["listing_member_id"],
                              "LATE_STATUS", "AUTO_LATE_STATUS",
                              listing_id=listing["id"])
        auto_citation_id = cit["id"]
        sc["auto_citation_id"] = auto_citation_id
        listing["accuracy_flag"] = "FLAGGED"
    store.status_changes[sc["id"]] = sc
    return sc


# ---------------------------------------------------------------------------
# Clock evaluation (advance_day / set_current_utc)
# ---------------------------------------------------------------------------

def evaluate_clock_triggers():
    """On clock changes: policy revision activations, dues suspensions,
    listing expiry (>365 days ACTIVE)."""
    current = now()

    # 1. PolicyRevision activations: SCHEDULED with effective_at <= now.
    #    Newest-effective_at-wins: process in effective_at ascending order so
    #    the newest ends ACTIVE; each activation supersedes earlier ACTIVEs.
    scheduled = [r for r in store.policy_revisions.values()
                 if r["status"] == "SCHEDULED"
                 and _parse_iso(r["effective_at"]) <= current]
    scheduled.sort(key=lambda r: _parse_iso(r["effective_at"]))
    for rev in scheduled:
        activate_policy_revision(rev)

    # 2. Dues suspensions: crossing grace_end_date with PENDING invoice.
    for invoice in list(store.dues_invoices.values()):
        if invoice["status"] != "PENDING":
            continue
        period = store.dues_periods.get(invoice["dues_period_id"])
        if period is None:
            continue
        grace_end = _parse_iso(period["grace_end_date"])
        # suspension fires at 00:00:00.000Z on grace_end_date + 1 day
        suspension_instant = (grace_end + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0)
        if current >= suspension_instant:
            member = store.members.get(invoice["member_id"])
            if member is not None and member["membership_state"] == "ACTIVE":
                suspend_member(member, trigger_grace_end_date=grace_end)

    # 3. Listing expiry is driven exclusively by the compliance checkpoint
    #    (PRD §3.10): "The checkpoint expires every listing that has been
    #    `ACTIVE` for more than 365 days" — clock changes alone do not expire.


def activate_policy_revision(rev):
    """SCHEDULED -> ACTIVE; supersede every other ACTIVE revision of the same
    association with effective_at < this.effective_at."""
    for other in store.policy_revisions.values():
        if other["id"] == rev["id"]:
            continue
        if other["association_id"] != rev["association_id"]:
            continue
        if other["status"] == "ACTIVE" and \
           _parse_iso(other["effective_at"]) < _parse_iso(rev["effective_at"]):
            other["status"] = "SUPERSEDED"
            touch(other)
    rev["status"] = "ACTIVE"
    touch(rev)


def expire_stale_listings():
    """ACTIVE listings with activated_at more than 365 days ago -> EXPIRED."""
    current = now()
    count = 0
    for listing in list(store.listings.values()):
        if listing["status"] != "ACTIVE":
            continue
        if not listing.get("activated_at"):
            continue
        activated = _parse_iso(listing["activated_at"])
        if current - activated > timedelta(days=365):
            record_status_change(listing, "ACTIVE", "EXPIRED",
                                 business_effective_at=now_iso_str(),
                                 audit=False)
            listing["status"] = "EXPIRED"
            listing["status_changed_at"] = now_iso_str()
            touch(listing)
            count += 1
    return count
