"""Withdrawal liability: allocation, certification, demand, review, installments."""
from datetime import timedelta

from flask import Blueprint, g

import calc
import serialize
import validate as v
from authz import endpoint, require_owner_employer
from envelope import created, ok
from errors import ApiError
from store import date_from_iso, db, new_row, sorted_rows, touch

bp = Blueprint("withdrawals", __name__)


def assessment_installments(assessment_id):
    rows = [i for i in db.installments.values() if i["assessment_id"] == assessment_id]
    return sorted(rows, key=lambda i: i["installment_number"])


@bp.post("/withdrawal-assessments")
@endpoint(["FundAdministrator"])
def open_withdrawal():
    data = v.body()
    v.body_ref(data, "employer_id", db.employers, "ERR_EMPLOYER_NOT_FOUND")
    v.check_keys(data, ["employer_id", "withdrawal_date", "method", "expected_fund_version"])
    employer_id = v.as_string(data, "employer_id")
    withdrawal_date = v.as_iso_date(data, "withdrawal_date")
    method = v.as_enum(data, "method", ("PRESUMPTIVE", "ROLLING_FIVE"))
    expected_fund_version = v.as_int(data, "expected_fund_version", minimum=0)

    employer = db.employers[employer_id]
    fund = db.funds[employer["fund_id"]]
    calc.recompute_fund_derived(fund)

    if expected_fund_version != fund["version"]:
        raise ApiError("ERR_STALE_FUND_VERSION")
    if employer["status"] == "WITHDRAWN":
        raise ApiError("ERR_EMPLOYER_WITHDRAWN")

    pool = fund["total_uvb_cents"] - fund["allocated_uvb_cents"]
    if pool <= 0:
        raise ApiError("ERR_UVB_POOL_EXHAUSTED")

    draft = {"method": method}
    calc.compute_allocation(draft, employer, fund, pool)
    annual = calc.compute_schedule(draft, employer)
    if annual == 0:
        raise ApiError("ERR_NO_PAYMENT_BASE")

    assessment = new_row(
        db.withdrawals,
        {
            "employer_id": employer_id,
            "withdrawal_date": withdrawal_date,
            "method": method,
            "employer_share_fraction": draft["employer_share_fraction"],
            "raw_allocation_cents": draft["raw_allocation_cents"],
            "de_minimis_reduction_cents": draft["de_minimis_reduction_cents"],
            "net_liability_cents": draft["net_liability_cents"],
            "annual_payment_cents": draft["annual_payment_cents"],
            "schedule_years": draft["schedule_years"],
            "twenty_year_cap_applied": draft["twenty_year_cap_applied"],
            "capped_liability_cents": draft["capped_liability_cents"],
            "accelerated_balance_cents": None,
            "certified_by_user_id": None,
            "demanded_on": None,
            "review_grounds": None,
            "status": "DRAFT",
        },
    )
    employer["status"] = "WITHDRAWN"
    touch(employer)
    calc.recompute_suspended_employer_count(fund)
    calc.recompute_fund_derived(fund)
    touch(fund)
    return created(serialize.withdrawal(assessment))


@bp.post("/withdrawal-assessments/<assessment_id>/certify")
@endpoint(["Actuary"])
def certify(assessment_id):
    assessment = v.get_withdrawal(assessment_id)
    v.check_keys(v.body(), [])
    if assessment["status"] != "DRAFT":
        raise ApiError("ERR_WITHDRAWAL_INVALID_STATE")
    employer = db.employers[assessment["employer_id"]]
    fund = db.funds[employer["fund_id"]]

    assessment["certified_by_user_id"] = g.user_id
    assessment["status"] = "CERTIFIED"
    touch(assessment)

    fund["allocated_uvb_cents"] = fund["allocated_uvb_cents"] + assessment["net_liability_cents"]
    calc.recompute_fund_derived(fund)
    touch(fund)
    return ok(serialize.withdrawal(assessment))


@bp.post("/withdrawal-assessments/<assessment_id>/demand")
@endpoint(["FundAdministrator"])
def demand(assessment_id):
    assessment = v.get_withdrawal(assessment_id)
    v.check_keys(v.body(), [])
    employer = db.employers[assessment["employer_id"]]
    fund = db.funds[employer["fund_id"]]
    calc.recompute_fund_derived(fund)

    if assessment["status"] != "CERTIFIED":
        raise ApiError("ERR_WITHDRAWAL_INVALID_STATE")
    if fund["governance_posture"] == "FROZEN":
        raise ApiError("ERR_FUND_GOVERNANCE_FROZEN")
    if assessment["certified_by_user_id"] is not None and g.user_id == assessment["certified_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if assessment["annual_payment_cents"] <= 0:
        raise ApiError("ERR_NO_PAYMENT_BASE")

    demanded_on = db.today
    assessment["demanded_on"] = demanded_on.isoformat()
    assessment["status"] = "DEMANDED"
    touch(assessment)

    for k in range(1, assessment["schedule_years"] + 1):
        due = demanded_on + timedelta(
            days=calc.INSTALLMENT_FIRST_OFFSET_DAYS + (k - 1) * calc.INSTALLMENT_INTERVAL_DAYS
        )
        new_row(
            db.installments,
            {
                "assessment_id": assessment["id"],
                "installment_number": k,
                "due_date": due.isoformat(),
                "amount_cents": calc.installment_amount(assessment, k),
                "status": "SCHEDULED",
                "paid_on": None,
            },
        )
    return ok(serialize.withdrawal(assessment))


@bp.post("/withdrawal-assessments/<assessment_id>/review-request")
@endpoint(["ContributingEmployer"])
def review_request(assessment_id):
    assessment = db.withdrawals.get(assessment_id)
    if assessment is not None:
        require_owner_employer(assessment["employer_id"])
    assessment = v.get_withdrawal(assessment_id)
    data = v.body()
    v.check_keys(data, ["grounds"])
    grounds = v.as_string(data, "grounds")

    if assessment["status"] != "DEMANDED":
        raise ApiError("ERR_WITHDRAWAL_INVALID_STATE")
    assessment["review_grounds"] = grounds
    assessment["status"] = "REVIEW_REQUESTED"
    touch(assessment)
    return ok(serialize.withdrawal(assessment))


@bp.post("/withdrawal-assessments/<assessment_id>/review-decision")
@endpoint(["FundAdministrator"])
def review_decision(assessment_id):
    assessment = v.get_withdrawal(assessment_id)
    data = v.body()
    v.check_keys(data, ["decision", "revised_total_uvb_cents"])
    decision = v.as_enum(data, "decision", ("UPHELD", "REVISED"))

    if assessment["status"] != "REVIEW_REQUESTED":
        raise ApiError("ERR_WITHDRAWAL_INVALID_STATE")

    if decision == "UPHELD":
        assessment["status"] = "PAYMENT_ACTIVE"
        touch(assessment)
        return ok(serialize.withdrawal(assessment))

    revised = v.as_int(data, "revised_total_uvb_cents", minimum=0)
    employer = db.employers[assessment["employer_id"]]
    fund = db.funds[employer["fund_id"]]

    fund["allocated_uvb_cents"] = fund["allocated_uvb_cents"] - assessment["net_liability_cents"]
    fund["total_uvb_cents"] = revised
    calc.recompute_fund_derived(fund)

    pool = fund["total_uvb_cents"] - fund["allocated_uvb_cents"]
    calc.compute_allocation(assessment, employer, fund, pool)
    calc.compute_schedule(assessment, employer)

    fund["allocated_uvb_cents"] = fund["allocated_uvb_cents"] + assessment["net_liability_cents"]
    calc.recompute_fund_derived(fund)
    touch(fund)

    for inst in assessment_installments(assessment["id"]):
        if inst["status"] == "SCHEDULED":
            del db.installments[inst["id"]]
    assessment["demanded_on"] = None
    assessment["status"] = "CERTIFIED"
    touch(assessment)
    return ok(serialize.withdrawal(assessment))


@bp.post("/payment-installments/<installment_id>/pay")
@endpoint(["ContributingEmployer"])
def pay_installment(installment_id):
    inst = db.installments.get(installment_id)
    if inst is not None:
        assessment = db.withdrawals.get(inst["assessment_id"])
        if assessment is not None:
            require_owner_employer(assessment["employer_id"])
    inst = v.get_installment(installment_id)
    data = v.body()
    v.check_keys(data, ["amount_cents"])
    amount = v.as_int(data, "amount_cents", minimum=0)
    assessment = db.withdrawals[inst["assessment_id"]]

    if inst["status"] in ("PAID", "DEFAULTED"):
        raise ApiError("ERR_INSTALLMENT_NOT_PAYABLE")
    if inst["status"] == "MISSED":
        if db.today > date_from_iso(inst["due_date"]) + timedelta(days=calc.CURE_DAYS):
            raise ApiError("ERR_INSTALLMENT_NOT_PAYABLE")
    if assessment["status"] not in ("DEMANDED", "PAYMENT_ACTIVE"):
        raise ApiError("ERR_WITHDRAWAL_INVALID_STATE")
    if amount != inst["amount_cents"]:
        raise ApiError("ERR_INSTALLMENT_AMOUNT_MISMATCH")

    inst["paid_on"] = db.today.isoformat()
    inst["status"] = "PAID"
    touch(inst)

    if assessment["status"] == "DEMANDED":
        assessment["status"] = "PAYMENT_ACTIVE"
        touch(assessment)
    siblings = assessment_installments(assessment["id"])
    if siblings and all(x["status"] == "PAID" for x in siblings):
        assessment["status"] = "SATISFIED"
        touch(assessment)
    return ok(serialize.installment(inst))
