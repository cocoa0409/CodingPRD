"""PayoutLoan, LoanAmortizationEntry, forgiveness and discharge (PRD 3.2)."""

from datetime import timedelta

from db import (advisors, clock_dt, clock_is_set, iso_now, loan_amortization_entries,
                new_id, next_created_seq, parse_date, payout_loans,
                payout_periods, revenue_entries)
from errors import dec, fail, round_half_up
from services import advisors as advisor_service
from services import calc, common


def serialize(row):
    return {key: value for key, value in row.items() if not key.startswith("_")}


def find_loan_or_fail(loan_id):
    row = payout_loans.get(loan_id)
    if row is None:
        fail("ERR_NOT_FOUND")
    return row


def amortization_entries_of(loan_id):
    return [row for row in loan_amortization_entries.values() if row["payout_loan_id"] == loan_id]


def create(data):
    advisor_code = common.require_field(data, "advisor_code")
    principal = common.require_field(data, "principal_cents")
    rate = common.require_field(data, "amortization_rate_bps")
    milestone = common.require_field(data, "forgiveness_milestone_pct")
    advisor = advisor_service.get_by_code_or_fail(advisor_code)
    if int(principal) <= 0 or int(principal) > calc.LPL_PARITY_PRINCIPAL_CAP_CENTS:
        fail("ERR_INVALID_REQUEST",
             "principal_cents must be strictly positive and at most the parity principal cap.")
    if int(rate) <= 0:
        fail("ERR_INVALID_REQUEST", "amortization_rate_bps must be strictly positive.")
    if int(milestone) < 0 or int(milestone) > 100:
        fail("ERR_INVALID_REQUEST", "forgiveness_milestone_pct must be between 0 and 100.")
    row = {
        "id": new_id(),
        "created_at": iso_now(),
        "updated_at": iso_now(),
        "version": 1,
        "_seq": next_created_seq(),
        "advisor_code": advisor_code,
        "principal_cents": int(principal),
        "amortization_rate_bps": int(rate),
        "forgiveness_milestone_pct": int(milestone),
        "remaining_balance_cents": int(principal),
        "milestone_progress_cents": 0,
        "status": "REQUESTED",
    }
    payout_loans[row["id"]] = row
    advisor_service.derive(advisor)
    return row


# ---------------------------------------------------------------------------
# Milestone arithmetic
# ---------------------------------------------------------------------------

def _milestone_window(advisor):
    """[first released entry for the loan, +12 months] measured over production."""
    released = [row for row in revenue_entries.values()
                if row["advisor_code"] == advisor["advisor_code"]
                and row["status"] in ("RELEASED", "TRUE_UP_APPLIED")]
    if not released:
        return None
    first = min(released, key=lambda row: (parse_date(row["production_date"]), row.get("_seq", 0)))
    start = parse_date(first["production_date"])
    return start, start + timedelta(days=365)


def _window_entries(advisor):
    window = _milestone_window(advisor)
    if window is None:
        return []
    start, end = window
    now = clock_dt()
    out = []
    for row in revenue_entries.values():
        if row["advisor_code"] != advisor["advisor_code"]:
            continue
        if row["status"] not in ("RELEASED", "TRUE_UP_APPLIED"):
            continue
        when = parse_date(row["production_date"])
        if start <= when <= end and when <= now:
            out.append(row)
    return out


def milestone_sum_cents(advisor):
    return sum(int(row["gross_commission_cents"]) for row in _window_entries(advisor))


def milestone_progress_cents(loan, advisor):
    threshold = calc.milestone_threshold_cents(loan["principal_cents"],
                                               loan["forgiveness_milestone_pct"])
    return min(milestone_sum_cents(advisor), threshold)


def refresh_loan(loan):
    advisor = advisor_service.get_by_code_or_fail(loan["advisor_code"])
    loan["milestone_progress_cents"] = milestone_progress_cents(loan, advisor)
    advisor_service.derive(advisor)
    return loan


# ---------------------------------------------------------------------------
# POST /payout-loans/{id}/amortize  (AdvisorOps, BranchManager)
# ---------------------------------------------------------------------------

def amortize(loan, data):
    period_id = common.require_field(data, "payout_period_id")
    period = payout_periods.get(period_id)
    if period is None:
        fail("ERR_NOT_FOUND")
    if loan["status"] not in ("ACTIVE", "AMORTIZING"):
        fail("ERR_INVALID_STATE")
    advisor = advisor_service.get_by_code_or_fail(loan["advisor_code"])
    release_amount = 0
    for line in advisor_service.lines_of(advisor["advisor_code"]):
        if line["payout_period_id"] == period_id and line["status"] in ("RELEASED", "TRUE_UP_APPLIED"):
            release_amount += int(line.get("release_amount_cents") or 0)
    draw = round_half_up(dec(release_amount) * dec(loan["amortization_rate_bps"]) / dec(10000))
    draw = min(draw, int(loan["remaining_balance_cents"] or 0))
    entry = {
        "id": new_id(),
        "created_at": iso_now(),
        "updated_at": iso_now(),
        "version": 1,
        "_seq": next_created_seq(),
        "payout_loan_id": loan["id"],
        "payout_period_id": period_id,
        "amortization_amount_cents": draw,
        "forgiveness_amount_cents": 0,
        "status": "POSTED",
    }
    loan_amortization_entries[entry["id"]] = entry
    loan["remaining_balance_cents"] = int(loan["remaining_balance_cents"] or 0) - draw
    loan["status"] = "AMORTIZING"
    common.touch(loan)
    # An amortization draw recomputes the advisor's outstanding balance but does
    # not advance the advisor's version (SCAFFOLD section 1.5).
    advisor_service.derive(advisor)
    refresh_loan(loan)
    return loan


# ---------------------------------------------------------------------------
# POST /payout-loans/{id}/forgive  (AdvisorOps, PlatformAdmin)
# ---------------------------------------------------------------------------

def forgive(loan, data):
    if not common_has_clock():
        fail("ERR_CLOCK_NOT_SET")
    if "expected_advisor_version" in data and data["expected_advisor_version"] is not None:
        advisor = advisor_service.get_by_code_or_fail(loan["advisor_code"])
        common.check_occ(advisor, "expected_advisor_version", data.get("expected_advisor_version"))
    if loan["status"] not in ("ACTIVE", "AMORTIZING", "REQUESTED"):
        fail("ERR_INVALID_STATE")
    advisor = advisor_service.get_by_code_or_fail(loan["advisor_code"])
    refresh_loan(loan)
    threshold = calc.milestone_threshold_cents(loan["principal_cents"],
                                               loan["forgiveness_milestone_pct"])
    if loan["milestone_progress_cents"] < threshold:
        fail("ERR_INVALID_STATE", "The forgiveness milestone has not matured.")
    forgiveness = calc.milestone_forgiveness_cents(loan["principal_cents"],
                                                   loan["forgiveness_milestone_pct"])
    forgiveness = min(forgiveness, int(loan["remaining_balance_cents"] or 0))
    entry = {
        "id": new_id(),
        "created_at": iso_now(),
        "updated_at": iso_now(),
        "version": 1,
        "_seq": next_created_seq(),
        "payout_loan_id": loan["id"],
        "payout_period_id": None,
        "amortization_amount_cents": 0,
        "forgiveness_amount_cents": forgiveness,
        "status": "POSTED",
    }
    loan_amortization_entries[entry["id"]] = entry
    loan["remaining_balance_cents"] = int(loan["remaining_balance_cents"] or 0) - forgiveness
    loan["status"] = "FORGIVEN"
    common.touch(loan)
    advisor_service.derive(advisor)
    return loan


def common_has_clock():
    return clock_is_set()


# ---------------------------------------------------------------------------
# GET /payout-loans/{id}/forgiveness-audit
# ---------------------------------------------------------------------------

def forgiveness_audit(loan):
    advisor = advisor_service.get_by_code_or_fail(loan["advisor_code"])
    threshold = calc.milestone_threshold_cents(loan["principal_cents"],
                                               loan["forgiveness_milestone_pct"])
    progress = milestone_progress_cents(loan, advisor)
    return {
        "loan_id": loan["id"],
        "principal_cents": loan["principal_cents"],
        "remaining_balance_cents": loan["remaining_balance_cents"],
        "milestone_progress_cents": progress,
        "milestone_threshold_cents": threshold,
        "configured_forgiveness_milestone_pct": loan["forgiveness_milestone_pct"],
        "gross_commission_sum_cents": milestone_sum_cents(advisor),
        "milestone_matured": progress >= threshold,
        "status": loan["status"],
    }


# ---------------------------------------------------------------------------
# GET /payout-loans/{id}/amortization-schedule
# ---------------------------------------------------------------------------

def amortization_schedule(loan):
    posted = amortization_entries_of(loan["id"])
    amortization_total = sum(int(row.get("amortization_amount_cents") or 0)
                             for row in posted if row["status"] == "POSTED")
    forgiveness_applied = sum(int(row.get("forgiveness_amount_cents") or 0)
                              for row in posted if row["status"] == "POSTED")
    return {
        "amortization_total_cents": amortization_total,
        "milestone_forgiveness_applied_cents": forgiveness_applied,
        "remaining_balance_cents": loan["remaining_balance_cents"],
    }