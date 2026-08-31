"""Fund, employer, participant, trustee, clock and collections-run endpoints."""
from datetime import datetime, timedelta
from decimal import Decimal

from flask import Blueprint, g, request

import calc
import serialize
import validate as v
from authz import endpoint
from envelope import created, ok
from errors import ApiError
from store import (
    date_from_iso,
    db,
    iso_ts,
    new_row,
    plan_year_end_date,
    touch,
    UTC,
)

bp = Blueprint("core", __name__)

FUND_FIELDS = [
    "name",
    "ein",
    "fund_role",
    "plan_year_start_month",
    "interest_rate_annual_bps",
    "ld_rate_bps",
    "ld_floor_cents",
    "grace_days",
    "hours_per_coverage_month",
    "bank_cap_hours",
    "max_advance_coverage_months",
    "eligibility_lag_months",
    "accrual_method",
    "total_uvb_cents",
    "pool_prior_year_contributions_cents",
]


@bp.post("/funds")
@endpoint(["FundAdministrator"])
def create_fund():
    data = v.body()
    v.check_keys(data, FUND_FIELDS)
    row = {
        "name": v.as_string(data, "name"),
        "ein": v.as_string(data, "ein"),
        "fund_role": v.as_enum(data, "fund_role", ("HOME", "SISTER"), required=False, default="HOME"),
        "plan_year_start_month": v.as_int(
            data, "plan_year_start_month", required=False, default=1, minimum=1, maximum=12
        ),
        "interest_rate_annual_bps": v.as_int(data, "interest_rate_annual_bps", minimum=0),
        "ld_rate_bps": v.as_int(data, "ld_rate_bps", minimum=0),
        "ld_floor_cents": v.as_int(data, "ld_floor_cents", minimum=0),
        "grace_days": v.as_int(data, "grace_days", minimum=0),
        "hours_per_coverage_month": v.as_int(data, "hours_per_coverage_month", minimum=1),
        "bank_cap_hours": v.as_hours(data, "bank_cap_hours"),
        "max_advance_coverage_months": v.as_int(data, "max_advance_coverage_months", minimum=1),
        "eligibility_lag_months": v.as_int(data, "eligibility_lag_months", minimum=0),
        "accrual_method": v.as_enum(data, "accrual_method", ("HOURS_BASED", "ELAPSED_TIME")),
        "total_uvb_cents": v.as_int(data, "total_uvb_cents", required=False, default=0, minimum=0),
        "pool_prior_year_contributions_cents": v.as_int_array5(
            data, "pool_prior_year_contributions_cents"
        ),
        "allocated_uvb_cents": 0,
        "unallocated_uvb_cents": 0,
        "reciprocity_agreement_status": "NONE",
        "active_union_trustees": 0,
        "active_employer_trustees": 0,
        "governance_posture": "FROZEN",
        "suspended_employer_count": 0,
        "reciprocal_receipts_cents": 0,
        "collections_run_index": 0,
    }
    fund = new_row(db.funds, row)
    fund["unallocated_uvb_cents"] = fund["total_uvb_cents"]
    return created(serialize.fund(fund))


EMPLOYER_FIELDS = [
    "fund_id",
    "legal_name",
    "ein",
    "contribution_rate_millicents_per_hour",
    "controlled_group_parent_employer_id",
    "prior_year_contributions_cents",
    "prior_year_base_units",
]


@bp.post("/employers")
@endpoint(["FundAdministrator"])
def create_employer():
    data = v.body()
    v.body_ref(data, "fund_id", db.funds, "ERR_FUND_NOT_FOUND")
    v.body_ref(data, "controlled_group_parent_employer_id", db.employers, "ERR_EMPLOYER_NOT_FOUND")
    v.check_keys(data, EMPLOYER_FIELDS)
    row = {
        "fund_id": v.as_string(data, "fund_id"),
        "legal_name": v.as_string(data, "legal_name"),
        "ein": v.as_string(data, "ein"),
        "contribution_rate_millicents_per_hour": v.as_int(
            data, "contribution_rate_millicents_per_hour", minimum=1
        ),
        "controlled_group_parent_employer_id": v.as_string(
            data, "controlled_group_parent_employer_id", required=False, default=None
        ),
        "prior_year_contributions_cents": v.as_int_array5(data, "prior_year_contributions_cents"),
        "prior_year_base_units": v.as_int_array5(data, "prior_year_base_units"),
        "status": "ACTIVE",
        "delinquency_strikes": 0,
        "cumulative_delinquent_cents": 0,
    }
    emp = new_row(db.employers, row)
    return created(serialize.employer(emp))


@bp.post("/participants")
@endpoint(["FundAdministrator"])
def create_participant():
    data = v.body()
    v.body_ref(data, "fund_id", db.funds, "ERR_FUND_NOT_FOUND")
    v.check_keys(data, ["fund_id", "full_name", "ssn_last4"])
    ssn = v.as_string(data, "ssn_last4")
    if len(ssn) != 4 or not ssn.isdigit():
        v.bad("Field 'ssn_last4' must be exactly four digits.")
    row = {
        "fund_id": v.as_string(data, "fund_id"),
        "full_name": v.as_string(data, "full_name"),
        "ssn_last4": ssn,
        "credited_hours_total": Decimal("0.00"),
        "reciprocal_hours_total": Decimal("0.00"),
        "hour_bank_hours": Decimal("0.00"),
        "forfeited_hours_total": Decimal("0.00"),
        "coverage_through_month": None,
        "vesting_service_years": 0,
        "total_pension_credits": Decimal("0.00"),
        "vested": False,
        "consecutive_break_years": 0,
        "status": "ACTIVE",
    }
    p = new_row(db.participants, row)
    return created(serialize.participant(p))


@bp.post("/trustees")
@endpoint(["FundAdministrator"])
def create_trustee():
    data = v.body()
    v.body_ref(data, "fund_id", db.funds, "ERR_FUND_NOT_FOUND")
    v.check_keys(data, ["fund_id", "full_name", "appointing_party", "term_expires_on", "seat_status"])
    row = {
        "fund_id": v.as_string(data, "fund_id"),
        "full_name": v.as_string(data, "full_name"),
        "appointing_party": v.as_enum(data, "appointing_party", ("UNION", "EMPLOYER")),
        "term_expires_on": v.as_iso_date(data, "term_expires_on"),
        "seat_status": v.as_enum(
            data, "seat_status", ("ACTIVE", "RESIGNED"), required=False, default="ACTIVE"
        ),
    }
    trustee = new_row(db.trustees, row)
    fund = db.funds[trustee["fund_id"]]
    calc.recompute_fund_derived(fund)
    touch(fund)
    return created(serialize.trustee(trustee))


@bp.post("/_clock/set_current_utc")
@endpoint(["FundAdministrator"])
def set_clock():
    data = v.body()
    v.check_keys(data, ["to_iso8601"])
    raw = v.as_string(data, "to_iso8601")
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        v.bad("Field 'to_iso8601' must be an ISO 8601 instant.")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    db.clock = moment.astimezone(UTC)
    return ok({"current_utc": iso_ts(db.clock)})


def _report_sweep_key(r):
    return (r["due_date"], r["created_at"], r["_seq"])


def _installment_sweep_key(i):
    return (i["due_date"], i["created_at"], i["_seq"])


@bp.post("/funds/<fund_id>/run-collections")
@endpoint(["FundAdministrator"])
def run_collections(fund_id):
    fund = v.get_fund(fund_id)
    v.check_keys(v.body(), [])
    clock_date = db.today

    employer_ids = set(e["id"] for e in db.employers.values() if e["fund_id"] == fund["id"])
    touched_employers = set()
    reports_marked_delinquent = 0
    installments_marked_missed = 0
    installments_defaulted = 0
    employers_suspended = 0
    accruals_finalized = 0

    # ---- sweep 1: delinquency identification --------------------------
    candidates = [
        r
        for r in db.reports.values()
        if r["employer_id"] in employer_ids
        and r["payment_status"] in ("UNPAID", "PARTIAL")
        and r["filing_status"] != "SUPERSEDED"
        and clock_date > date_from_iso(r["due_date"]) + timedelta(days=fund["grace_days"])
    ]
    for report in sorted(candidates, key=_report_sweep_key):
        report["payment_status"] = "DELINQUENT"
        touch(report)
        reports_marked_delinquent += 1
        emp = db.employers[report["employer_id"]]
        emp["delinquency_strikes"] = emp["delinquency_strikes"] + 1
        calc.recompute_employer_ledger(emp)
        if emp["delinquency_strikes"] >= calc.DELINQUENCY_STRIKE_LIMIT and emp["status"] == "ACTIVE":
            emp["status"] = "SUSPENDED"
            employers_suspended += 1
        touch(emp)
        touched_employers.add(emp["id"])
    if reports_marked_delinquent:
        calc.recompute_suspended_employer_count(fund)

    # ---- sweep 2: ageing the withdrawal installments ------------------
    def owned(inst):
        assessment = db.withdrawals.get(inst["assessment_id"])
        return assessment is not None and assessment["employer_id"] in employer_ids

    pass_a = [
        i
        for i in db.installments.values()
        if owned(i) and i["status"] == "SCHEDULED" and clock_date > date_from_iso(i["due_date"])
    ]
    for inst in sorted(pass_a, key=_installment_sweep_key):
        inst["status"] = "MISSED"
        touch(inst)
        installments_marked_missed += 1

    pass_b = [
        i
        for i in db.installments.values()
        if owned(i)
        and i["status"] == "MISSED"
        and clock_date > date_from_iso(i["due_date"]) + timedelta(days=calc.CURE_DAYS)
    ]
    for inst in sorted(pass_b, key=_installment_sweep_key):
        inst["status"] = "DEFAULTED"
        touch(inst)
        installments_defaulted += 1
        assessment = db.withdrawals[inst["assessment_id"]]
        if assessment["status"] in ("DEMANDED", "PAYMENT_ACTIVE"):
            assessment["status"] = "ACCELERATED"
            assessment["accelerated_balance_cents"] = sum(
                x["amount_cents"]
                for x in db.installments.values()
                if x["assessment_id"] == assessment["id"]
                and x["status"] in ("SCHEDULED", "MISSED", "DEFAULTED")
            )
            touch(assessment)
            emp = db.employers.get(assessment["employer_id"])
            if emp is not None:
                if emp["status"] != "SUSPENDED":
                    emp["status"] = "SUSPENDED"
                    employers_suspended += 1
                    touch(emp)
                touched_employers.add(emp["id"])
    if installments_defaulted:
        calc.recompute_suspended_employer_count(fund)

    # ---- sweep 3: plan-year close-out and breaks in service -----------
    participant_ids = set(p["id"] for p in db.participants.values() if p["fund_id"] == fund["id"])
    pym = fund["plan_year_start_month"]
    open_rows = [
        a
        for a in db.accruals.values()
        if a["participant_id"] in participant_ids and a["accrual_status"] == "OPEN"
    ]
    for row in sorted(open_rows, key=lambda a: (a["plan_year"], a["_seq"])):
        if clock_date > plan_year_end_date(row["plan_year"], pym):
            row["accrual_status"] = "FINALIZED"
            touch(row)
            accruals_finalized += 1

    for pid in sorted(participant_ids):
        p = db.participants[pid]
        before = (p["status"], p["consecutive_break_years"], p["vesting_service_years"])
        calc.recompute_consecutive_break_years(p)
        if (
            p["consecutive_break_years"] >= calc.BREAK_YEARS_LIMIT
            and not p["vested"]
            and p["status"] == "ACTIVE"
        ):
            p["status"] = "BROKEN_SERVICE"
            calc.erase_accrued_benefit(p)
        elif p["status"] == "BROKEN_SERVICE":
            finalized = [
                a
                for a in calc.participant_accruals(pid)
                if a["accrual_status"] == "FINALIZED"
            ]
            if finalized and not finalized[-1]["break_in_service"]:
                p["status"] = "ACTIVE"
                p["consecutive_break_years"] = 0
        after = (p["status"], p["consecutive_break_years"], p["vesting_service_years"])
        if before != after:
            touch(p)

    # ---- close: employer ledgers consistent with what this run produced
    for emp_id in touched_employers:
        emp = db.employers[emp_id]
        before_ledger = emp["cumulative_delinquent_cents"]
        # The run never lifts a suspension; only a remittance, a settlement or a
        # carried waiver motion clears the strike counter (PRD 3.6 / 3.10).
        calc.recompute_employer_ledger(emp)
        if emp["cumulative_delinquent_cents"] != before_ledger:
            touch(emp)
    calc.recompute_suspended_employer_count(fund)

    fund["collections_run_index"] = fund["collections_run_index"] + 1
    touch(fund)

    return ok(
        {
            "reports_marked_delinquent": reports_marked_delinquent,
            "installments_marked_missed": installments_marked_missed,
            "installments_defaulted": installments_defaulted,
            "employers_suspended": employers_suspended,
            "accruals_finalized": accruals_finalized,
            "collections_run_index": fund["collections_run_index"],
        }
    )
