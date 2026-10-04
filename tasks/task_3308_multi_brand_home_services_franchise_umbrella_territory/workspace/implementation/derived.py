"""Derived-field recomputation (PRD 2.7, 2.8, 2.9).

Every field the scaffold marks `source: computed` is maintained by the write
paths that the scaffold's side effects prescribe, and is additionally
re-derived here so that a reading always reconciles with the rows beneath it.
`refresh()` never touches `version` or `updated_at` -- a read is not a mutation.
"""
from store import db, now_iso, now_dt, add_months, parse_instant, hours_from, iso_of
from config import (
    AGREEMENT_LIVE,
    AUDIT_REOPEN_HOURS,
    CERT_RANK,
    HOUSEHOLD_CAP,
    MULTI_BRAND_MIN,
    REMEDIATION_OPEN_SET,
    STANDARDS_RANK,
    TERRITORY_HOLDING_STATUSES,
    VALUE_UNIT_CENTS,
    ALLOCATION_HOLD_HOURS,
)
from money import dec, round_tenth, round_ten_thousandth, as_number

_PUBLISHED = ("PUBLISHED", "SUPERSEDED")


# ---------------------------------------------------------------------------
# generic lookups
# ---------------------------------------------------------------------------
def rows(table):
    return list(table.values())


def brand_of(brand_id):
    return db.brands.get(brand_id)


def agreement_of(agreement_id):
    return db.agreements.get(agreement_id)


def franchisee_of(franchisee_id):
    return db.franchisees.get(franchisee_id)


def agreements_of(franchisee_id):
    return [a for a in db.agreements.values() if a.get("franchisee_id") == franchisee_id]


def audits_of(agreement_id):
    return [a for a in db.audits.values() if a.get("agreement_id") == agreement_id]


def work_orders_of_account(account_id):
    return [w for w in db.work_orders.values() if w.get("national_account_id") == account_id]


# ---------------------------------------------------------------------------
# ordering helpers (PRD 2.3 tie-breaks)
# ---------------------------------------------------------------------------
def _instant_key(value):
    parsed = parse_instant(value) if isinstance(value, str) else None
    return parsed.isoformat() if parsed else ""


def ordered_by_created(records, human_key=None):
    """created_at ascending, then the entity's human-readable key ascending."""
    def sort_key(r):
        return (_instant_key(r.get("created_at")), str(r.get(human_key) or "") if human_key else "")
    return sorted(records, key=sort_key)


# ---------------------------------------------------------------------------
# territory
# ---------------------------------------------------------------------------
def postal_overlap(brand_id, postal_codes, exclude_id=None):
    """True when any code is already claimed by a non-reclaimed territory of
    the same brand (PRD 2.6)."""
    wanted = set(postal_codes or [])
    if not wanted:
        return False
    for t in db.territories.values():
        if t["id"] == exclude_id:
            continue
        if t.get("brand_id") != brand_id:
            continue
        if t.get("status") == "RECLAIMED":
            continue
        shared = wanted.intersection(t.get("postal_codes") or [])
        if shared:
            return True
    return False


def territory_holds_households(territory):
    return territory.get("status") in TERRITORY_HOLDING_STATUSES


def held_households(franchisee_id, exclude_territory_id=None):
    total = 0
    for t in db.territories.values():
        if exclude_territory_id is not None and t["id"] == exclude_territory_id:
            continue
        if t.get("franchisee_id") != franchisee_id:
            continue
        if t.get("status") in TERRITORY_HOLDING_STATUSES:
            total += int(t.get("household_count") or 0)
    return total


def award_would_exceed_cap(franchisee_id, territory):
    """PRD 3.2 cap test: already-held + this territory's count <= 250000."""
    held = held_households(franchisee_id, exclude_territory_id=territory["id"])
    return held + int(territory.get("household_count") or 0) > HOUSEHOLD_CAP


def refresh_territory(territory):
    if territory.get("status") in TERRITORY_HOLDING_STATUSES:
        territory["allocated_households"] = int(territory.get("household_count") or 0)
    else:
        territory["allocated_households"] = 0
    return territory


# ---------------------------------------------------------------------------
# child territory cascade lookup
# ---------------------------------------------------------------------------
def children_of_territory(territory_id):
    return [
        t for t in db.territories.values()
        if t.get("parent_territory_id") == territory_id
        or t.get("source_of_reallocation_id") == territory_id
    ]


# ---------------------------------------------------------------------------
# franchise agreement
# ---------------------------------------------------------------------------
def effective_royalty_rate(agreement):
    override = agreement.get("royalty_rate_override")
    if override is not None:
        return dec(override)
    brand = brand_of(agreement.get("brand_id"))
    return dec(brand.get("royalty_rate") if brand else 0)


def compute_expires_on(agreement):
    signed = agreement.get("signed_on")
    if not isinstance(signed, str):
        return None
    parsed = parse_instant(signed)
    if parsed is None:
        return None
    return iso_of(add_months(parsed, agreement.get("initial_term_months") or 0))


def latest_audit_for(agreement_id):
    """Latest audit by conducted_iso, then insertion order."""
    candidates = audits_of(agreement_id)
    if not candidates:
        return None

    def key(a):
        return (_instant_key(a.get("conducted_iso")), a.get("_seq") or 0)
    return sorted(candidates, key=key)[-1]


def audit_due_for(agreement):
    """conducted_iso of the latest PUBLISHED|SUPERSEDED audit + brand cycle."""
    brand = brand_of(agreement.get("brand_id"))
    cycle = int(brand.get("audit_cycle_months") or 0) if brand else 0
    published = [a for a in audits_of(agreement["id"]) if a.get("audit_status") in _PUBLISHED]
    if not published:
        return None

    def key(a):
        return (_instant_key(a.get("conducted_iso")), a.get("_seq") or 0)
    newest = sorted(published, key=key)[-1]
    conducted = parse_instant(newest.get("conducted_iso"))
    if conducted is None:
        return None
    from calendar import monthrange
    total = conducted.month - 1 + cycle
    year = conducted.year + total // 12
    month = total % 12 + 1
    day = min(conducted.day, monthrange(year, month)[1])
    return iso_of(conducted.replace(year=year, month=month, day=day))


def open_remediation_count(agreement_id):
    return len([
        a for a in audits_of(agreement_id)
        if a.get("remediation_status") in REMEDIATION_OPEN_SET
    ])


def agreement_standards_status(agreement_id):
    """PRD 2.7: worst posture, ranked COMPLIANT < WATCH < REMEDIATION_REQUIRED < DEFAULT."""
    audits = audits_of(agreement_id)
    if any(a.get("remediation_status") == "DEFAULTED" for a in audits):
        return "DEFAULT"
    if any(a.get("remediation_status") in REMEDIATION_OPEN_SET for a in audits):
        return "REMEDIATION_REQUIRED"
    if any(a.get("audit_status") == "PUBLISHED" and a.get("outcome") == "FAIL" for a in audits):
        return "REMEDIATION_REQUIRED"
    latest = None
    for a in audits:
        if a.get("audit_status") != "PUBLISHED":
            continue
        if latest is None or (_instant_key(a.get("conducted_iso")), a.get("_seq") or 0) > \
                (_instant_key(latest.get("conducted_iso")), latest.get("_seq") or 0):
            latest = a
    if latest is not None and latest.get("outcome") == "WATCH":
        return "WATCH"
    return "COMPLIANT"


def cumulative_royalty_for(agreement_id):
    return sum(
        int(s.get("royalty_cents") or 0)
        for s in db.statements.values()
        if s.get("agreement_id") == agreement_id and s.get("status") in ("ISSUED", "PAID")
    )


def cumulative_referral_net_for(agreement_id):
    total = 0
    for r in db.referrals.values():
        if r.get("status") != "SETTLED":
            continue
        fee = int(r.get("referral_fee_cents") or 0)
        if r.get("originating_agreement_id") == agreement_id:
            total += fee
        if r.get("receiving_agreement_id") == agreement_id:
            total -= fee
    return total


def refresh_agreement(agreement):
    agreement["effective_royalty_rate"] = as_number(effective_royalty_rate(agreement))
    agreement["expires_on"] = compute_expires_on(agreement)
    agreement["open_remediation_count"] = open_remediation_count(agreement["id"])
    agreement["standards_status"] = agreement_standards_status(agreement["id"])
    agreement["audit_due_iso"] = audit_due_for(agreement)
    agreement["cumulative_royalty_cents"] = cumulative_royalty_for(agreement["id"])
    agreement["cumulative_referral_net_cents"] = cumulative_referral_net_for(agreement["id"])
    return agreement


# ---------------------------------------------------------------------------
# franchisee
# ---------------------------------------------------------------------------
def franchisee_live_agreements(franchisee_id):
    return [a for a in agreements_of(franchisee_id) if a.get("lifecycle_status") in AGREEMENT_LIVE]


def refresh_franchisee(franchisee):
    live = franchisee_live_agreements(franchisee["id"])
    franchisee["active_agreement_count"] = len(live)
    franchisee["active_brand_count"] = len({a.get("brand_id") for a in live})
    franchisee["allocated_households"] = held_households(franchisee["id"])
    franchisee["lead_cost_balance_cents"] = sum(
        int(l.get("lead_cost_cents") or 0)
        for l in db.leads.values()
        if l.get("status") == "ALLOCATED"
        and (agreement_of(l.get("allocated_agreement_id")) or {}).get("franchisee_id") == franchisee["id"]
    )
    score, basis = franchisee_standards(franchisee)
    franchisee["standards_score"] = score
    franchisee["standards_score_basis"] = basis
    return franchisee


def franchisee_standards(franchisee):
    """Trailing brand standards score; the variant that produced it is recorded.

    Interpretation (the scaffold names the variants but supplies no arithmetic):
      AUDIT_BASED   -- exactly one agreement held: that agreement's latest
                       published audit score.
      TRAILING_WINDOW -- otherwise: the mean of each held agreement's latest
                       published audit score, over the agreements that have one.
    Both are reported to one decimal place, and 0 when no audit exists.
    """
    held = agreements_of(franchisee["id"])
    basis = "AUDIT_BASED" if len(held) == 1 else "TRAILING_WINDOW"
    if not held:
        return 0, basis
    scores = []
    if basis == "AUDIT_BASED":
        latest = latest_audit_for(held[0]["id"])
        if latest is not None and latest.get("audit_status") in _PUBLISHED:
            scores.append(dec(latest.get("weighted_score")))
    else:
        for agreement in held:
            best = None
            for a in audits_of(agreement["id"]):
                if a.get("audit_status") not in _PUBLISHED:
                    continue
                if best is None or (_instant_key(a.get("conducted_iso")), a.get("_seq") or 0) > \
                        (_instant_key(best.get("conducted_iso")), best.get("_seq") or 0):
                    best = a
            if best is not None:
                scores.append(dec(best.get("weighted_score")))
    if not scores:
        return 0, basis
    mean = sum(scores) / dec(len(scores))
    return as_number(round_tenth(mean)), basis


# ---------------------------------------------------------------------------
# national account
# ---------------------------------------------------------------------------
def refresh_account(account):
    orders = work_orders_of_account(account["id"])
    breached = [w for w in orders if w.get("status") == "SLA_BREACHED"]
    account["open_breach_count"] = len(breached)
    account["sla_credit_accrued_cents"] = (
        len(breached) * int(account.get("sla_credit_per_breach_cents") or 0)
    )
    account["accumulated_revenue_cents"] = sum(
        int(w.get("revenue_cents") or 0)
        for w in orders if w.get("status") in ("COMPLETED", "SLA_BREACHED")
    )
    commitment = int(account.get("annual_commitment_cents") or 0)
    if commitment <= 0:
        account["commitment_attainment_pct"] = 0
    else:
        pct = dec(account["accumulated_revenue_cents"]) / dec(commitment)
        account["commitment_attainment_pct"] = as_number(round_ten_thousandth(pct))
    # PRD 3.4: crossing the tolerance suspends the program as a derived reading of
    # the breach counter, so the cascade in cascades.breach_cascade() reaches the
    # same verdict. Only the crossing is derived; a program the franchisor has
    # deliberately closed is never revived by a read.
    if account["open_breach_count"] > int(account.get("breach_tolerance") or 0):
        account["status"] = "SUSPENDED"
    return account


# ---------------------------------------------------------------------------
# lead
# ---------------------------------------------------------------------------
def refresh_lead(lead):
    allocated = lead.get("allocated_clock_iso")
    if allocated and lead.get("status") in ("ALLOCATED", "CONVERTED", "RELEASED"):
        lead["allocation_hold_until_iso"] = iso_of(hours_from(parse_instant(allocated),
                                                              ALLOCATION_HOLD_HOURS))
    else:
        lead["allocation_hold_until_iso"] = None
    return lead


def value_units_of(lead):
    from money import ceil_div
    return ceil_div(int(lead.get("estimated_value_cents") or 0), VALUE_UNIT_CENTS)


# ---------------------------------------------------------------------------
# work order
# ---------------------------------------------------------------------------
def refresh_work_order(work_order):
    return work_order


# ---------------------------------------------------------------------------
# territory assignment
# ---------------------------------------------------------------------------
def refresh_assignment(assignment):
    assignment["active"] = assignment.get("released_on") is None
    return assignment


# ---------------------------------------------------------------------------
# dispatcher
# ---------------------------------------------------------------------------
_REFRESHERS = {
    "Territory": refresh_territory,
    "FranchiseAgreement": refresh_agreement,
    "Franchisee": refresh_franchisee,
    "NationalAccount": refresh_account,
    "Lead": refresh_lead,
    "TerritoryAssignment": refresh_assignment,
    "WorkOrder": refresh_work_order,
}


def refresh(record):
    """Re-derive a record's computed fields in place (no version bump)."""
    if not isinstance(record, dict):
        return record
    fn = _REFRESHERS.get(record.get("_kind"))
    if fn is not None:
        fn(record)
    return record


def refresh_all():
    """Re-derive every entity's computed fields (used before a sweep report)."""
    for table in (db.territories, db.agreements, db.franchisees, db.national_accounts,
                  db.leads, db.territory_assignments, db.work_orders):
        for record in table.values():
            refresh(record)


def standards_worst(statuses):
    worst = "COMPLIANT"
    for s in statuses:
        if STANDARDS_RANK.get(s, 0) > STANDARDS_RANK[worst]:
            worst = s
    return worst


def cert_at_least(held, required):
    return CERT_RANK.get(held, -1) >= CERT_RANK.get(required, 99)