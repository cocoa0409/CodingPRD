"""Cross-entity helpers: ledger recomputation, interval predicates and the
ordered cascades of PRD 2.10."""
from datetime import timedelta

import calc
from money import add_days, fmt_date, parse_date
from store import db, insert, iso, now, touch

LIVE_PLAN_STATES = ("SUBMITTED", "RETURNED", "APPROVED")
LIVE_IMPROVEMENT_STATES = ("PROPOSED", "RETURNED", "APPROVED")
LIVE_REPORT_STATES = ("SUBMITTED", "ACCEPTED", "RESTATED")
OPEN_AUDIT_STATES = ("OPENED", "FIELDWORK", "FINDINGS_ISSUED", "CONTESTED")


# --- interval predicates ---------------------------------------------------
def half_open_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def closed_overlap(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


def half_open_inside_closed(h_start, h_end, c_start, c_end):
    """A half-open [h_start, h_end) is covered by a closed [c_start, c_end]."""
    return h_start >= c_start and add_days(h_end, -1) <= c_end


# --- row lookups -----------------------------------------------------------
def by_lease(collection, lease_id):
    return [r for r in collection.values() if r.get("lease_id") == lease_id]


def lease_of(row):
    return db.leases.get(row.get("lease_id"))


def bond_of(lease):
    return db.bonds.get(lease.get("performance_bond_id"))


def park_of(lease):
    return db.parks.get(lease.get("park_id"))


def owner_of_lease(lease):
    return lease.get("offeror_id")


def ordered(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# --- park closure bookkeeping ---------------------------------------------
def bump_closure_count(park, delta):
    if park is None:
        return
    park["open_closure_window_count"] = park["open_closure_window_count"] + delta
    touch(park)


# --- lease ledger ---------------------------------------------------------
def recompute_outstanding(lease):
    total = 0
    for row in db.reconciliations.values():
        if row["lease_id"] == lease["id"] and row["status"] == "PENDING_PAYMENT":
            total = total + row["additional_fee_due_cents"]
    if lease["outstanding_fee_balance_cents"] != total:
        lease["outstanding_fee_balance_cents"] = total
        touch(lease)
    return total


def period_set(lease_id, ly_start, ly_end):
    """ACCEPTED/RESTATED reports whose half-open period lies inside the closed
    lease year, ordered by period_start then created_at."""
    limit = add_days(ly_end, 1)
    rows = []
    for row in db.reports.values():
        if row["lease_id"] != lease_id or row["status"] not in ("ACCEPTED", "RESTATED"):
            continue
        start = parse_date(row["period_start"])
        end = parse_date(row["period_end"])
        if start >= ly_start and end <= limit:
            rows.append(row)
    rows.sort(key=lambda r: (r["period_start"], r["created_at"], r["_seq"]))
    return rows


def covering_plan(lease_id, period_start, period_end):
    """The single APPROVED season whose closed window covers the half-open
    reporting period."""
    for plan in ordered([p for p in db.plans.values()
                         if p["lease_id"] == lease_id and p["status"] == "APPROVED"]):
        season_start = parse_date(plan["season_start"])
        season_end = parse_date(plan["season_end"])
        if half_open_inside_closed(period_start, period_end, season_start, season_end):
            return plan
    return None


# --- reconciliation minting ----------------------------------------------
def build_reconciliation(lease, ly_start, ly_end, audit=None, gross_override=None,
                         penalty_source_due_date=None):
    """Creates a FeeReconciliation row from the annual_fee_reconciliation rule."""
    term_start = parse_date(lease["term_start"])
    reports = period_set(lease["id"], ly_start, ly_end)
    if gross_override is None:
        annual_gross = sum(calc.report_receipts(r) for r in reports)
    else:
        annual_gross = gross_override
    tiered = calc.tiered_annual_fee(annual_gross, lease["base_fee_pct"])
    mag = calc.mag_applied(lease, ly_start, ly_end, term_start)
    annual_fee_due = max(tiered, mag)
    remitted = sum((r["remittance_received_cents"] or 0) for r in reports)
    base_delta = annual_fee_due - remitted
    penalty = 0
    interest = 0
    if audit is not None:
        penalty = calc.penalty_amount(base_delta, bool(audit["penalty_applies"]))
        if penalty_source_due_date is not None:
            interest = calc.interest_amount(base_delta, penalty_source_due_date, now().date())
    additional = base_delta + penalty + interest
    row = {
        "lease_id": lease["id"],
        "audit_engagement_id": audit["id"] if audit is not None else None,
        "superseded_by_id": None,
        "lease_year_number": calc.lease_year_number(term_start, lease["term_years"], ly_start),
        "lease_year_start": fmt_date(ly_start),
        "lease_year_end": fmt_date(ly_end),
        "annual_gross_receipts_cents": annual_gross,
        "annual_fee_due_cents": annual_fee_due,
        "mag_applied_cents": mag,
        "remitted_total_cents": remitted,
        "base_delta_cents": base_delta,
        "penalty_cents": penalty,
        "interest_cents": interest,
        "additional_fee_due_cents": additional,
        "payment_amount_cents": None,
        "due_date": fmt_date(add_days(ly_end, calc.RECONCILIATION_GRACE_DAYS)),
        "status": "PENDING_PAYMENT" if additional > 0 else "CREDIT_ISSUED",
    }
    return insert(db.reconciliations, row)


def supersede_pending(lease_id, lease_year_start, replacement_id):
    for row in ordered(list(db.reconciliations.values())):
        if (row["lease_id"] == lease_id
                and row["status"] == "PENDING_PAYMENT"
                and row["lease_year_start"] == lease_year_start
                and row["id"] != replacement_id):
            row["status"] = "SUPERSEDED"
            row["superseded_by_id"] = replacement_id
            touch(row)


# --- compliance -----------------------------------------------------------
def has_open_notice(lease_id, exclude_id=None):
    for row in db.compliance_actions.values():
        if row["lease_id"] != lease_id or row["status"] != "NOTICE_ISSUED":
            continue
        if exclude_id is not None and row["id"] == exclude_id:
            continue
        return True
    return False


def clear_deficiency(lease, exclude_action_id=None):
    """Conditional cascade: DEFICIENT -> COMPLIANT only when no notice remains."""
    if lease["compliance_status"] != "DEFICIENT":
        return
    if has_open_notice(lease["id"], exclude_action_id):
        return
    lease["compliance_status"] = "COMPLIANT"
    touch(lease)


# --- default and expiry cascades -----------------------------------------
def unwind_live_children(lease):
    """Live plans are SUPERSEDED, live improvements WITHDRAWN, with the park's
    closure counter decremented once per formerly APPROVED improvement."""
    for plan in ordered(by_lease(db.plans, lease["id"])):
        if plan["status"] in LIVE_PLAN_STATES:
            plan["status"] = "SUPERSEDED"
            touch(plan)
    park = park_of(lease)
    for improvement in ordered(by_lease(db.improvements, lease["id"])):
        if improvement["status"] in LIVE_IMPROVEMENT_STATES:
            was_approved = improvement["status"] == "APPROVED"
            improvement["status"] = "WITHDRAWN"
            touch(improvement)
            if was_approved:
                bump_closure_count(park, -1)


def expire_cascade(lease):
    """Ordered exactly as PRD 3.9 states, identical from ACTIVE and HOLDOVER."""
    term_end_date = parse_date(lease["term_end"])
    park = park_of(lease)
    improvements = ordered(by_lease(db.improvements, lease["id"]))
    for improvement in improvements:
        if improvement["status"] != "COMPLETED":
            continue
        improvement["unamortized_value_cents"] = calc.unamortized_value(
            improvement["approved_cost_cents"],
            parse_date(improvement["in_service_date"]),
            term_end_date,
            improvement["useful_life_years"],
        )
        if improvement["ownership_at_expiration"] == "AGENCY":
            improvement["status"] = "VESTED_IN_AGENCY"
        else:
            improvement["status"] = "COMPENSABLE"
        touch(improvement)
    for improvement in improvements:
        if improvement["status"] in LIVE_IMPROVEMENT_STATES:
            was_approved = improvement["status"] == "APPROVED"
            improvement["status"] = "WITHDRAWN"
            touch(improvement)
            if was_approved:
                bump_closure_count(park, -1)
    for plan in ordered(by_lease(db.plans, lease["id"])):
        if plan["status"] in LIVE_PLAN_STATES:
            plan["status"] = "SUPERSEDED"
            touch(plan)
    lease["possessory_interest_value_cents"] = compensable_total(lease["id"])


def compensable_total(lease_id):
    total = 0
    for improvement in db.improvements.values():
        if improvement["lease_id"] == lease_id and improvement["status"] == "COMPENSABLE":
            total = total + (improvement["unamortized_value_cents"] or 0)
    return total


def cure_deadline_from_clock():
    return iso(now() + timedelta(days=calc.CURE_PERIOD_DAYS))
