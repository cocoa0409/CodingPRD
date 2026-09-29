"""Qualified equity investments: issuance, void, annual tests, cures, unwind opening."""
from decimal import Decimal

from flask import Blueprint, g

import clock
import validators as v
from db import db, new_id
from errors import fail
from middleware import (ALL_ROLES, by_created_desc, by_field_asc, endpoint,
                        filter_str, force_bump)
from services import calc, derive

bp = Blueprint("qeis", __name__)


def load_qei(qei_id):
    qei = db.qeis.get(qei_id)
    if qei is None:
        fail("ERR_QEI_NOT_FOUND")
    return qei


def require_qei_owner(qei):
    award = derive.award_of_qei(qei)
    if g.user_id != award["cde_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")
    return award


@bp.route("/nmtc/qeis", methods=["POST"])
@endpoint(["CDESponsor"], mutating=True, status=201)
def issue_qei():
    data = v.body()
    allocation_award_id = v.req_str(data, "allocation_award_id")
    investment_fund_id = v.req_str(data, "investment_fund_id")
    qei_amount_cents = v.req_int(data, "qei_amount_cents", 10000000)
    expected_version = v.req_int(data, "expected_allocation_award_version")

    award = db.awards.get(allocation_award_id)
    if award is None:
        fail("ERR_ALLOCATION_AWARD_NOT_FOUND")
    fund = db.funds.get(investment_fund_id)
    if fund is None:
        fail("ERR_INVESTMENT_FUND_NOT_FOUND")

    if g.user_id != award["cde_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")
    if expected_version != award["version"]:
        fail("ERR_STALE_AWARD_VERSION")

    cde = derive.cde_of_award(award)
    if cde["certification_status"] != "CERTIFIED":
        fail("ERR_CDE_NOT_CERTIFIED")
    if award["lifecycle_status"] != "ACTIVE":
        fail("ERR_AWARD_NOT_ACTIVE")
    if award["compliance_posture"] in ("RESTRICTED", "FROZEN"):
        fail("ERR_AWARD_POSTURE_RESTRICTED")
    if fund["status"] != "FUNDED":
        fail("ERR_FUND_NOT_FUNDED")
    if (qei_amount_cents > award["remaining_authority_cents"]
            or qei_amount_cents > fund["capital_available_cents"]):
        fail("ERR_INSUFFICIENT_ALLOCATION_AUTHORITY")

    now = clock.now()
    reserve_bps = calc.reserve_bps_for(qei_amount_cents)
    permitted_fees = calc.cents_from_bps(qei_amount_cents, reserve_bps)
    net_deployable = qei_amount_cents - permitted_fees
    row = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "allocation_award_id": award["id"],
        "investment_fund_id": fund["id"],
        "qei_amount_cents": qei_amount_cents,
        "issued_at": now,
        "issued_by_user_id": g.user_id,
        "reserve_bps": reserve_bps,
        "permitted_fees_cents": permitted_fees,
        "net_deployable_cents": net_deployable,
        "uninvested_cash_cents": net_deployable,
        "deployment_deadline_at": clock.plus_days(now, calc.YEAR_DAYS),
        "deployment_status": "ISSUED",
        "compliance_status": "COMPLIANT",
        "substantially_all_pct_direct": calc.ZERO,
        "substantially_all_pct_aggregate": calc.ZERO,
        "compliance_years_completed": 0,
        "cure_deadline_at": None,
        "accrued_unpaid_fee_cents": 0,
        "recapture_trigger_type": "NONE",
        "recapture_exposure_cents": 0,
        "voided_at": None,
        "_seq": db.next_seq(),
    }
    db.qeis[row["id"]] = row
    force_bump(award)
    force_bump(fund)
    return row, 201


@bp.route("/nmtc/qeis", methods=["GET"])
@endpoint(ALL_ROLES)
def list_qeis():
    rows = list(db.qeis.values())
    rows = filter_str(rows, "allocation_award_id")
    rows = filter_str(rows, "investment_fund_id")
    rows = filter_str(rows, "deployment_status")
    rows = filter_str(rows, "compliance_status")
    return by_created_desc(rows)


@bp.route("/nmtc/qeis/<qei_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_qei(qei_id):
    return load_qei(qei_id)


@bp.route("/nmtc/qeis/<qei_id>/void", methods=["POST"])
@endpoint(["CDESponsor"], mutating=True)
def void_qei(qei_id):
    data = v.body()
    void_reason = v.req_str(data, "void_reason", 1)
    qei = load_qei(qei_id)
    award = require_qei_owner(qei)
    if (qei["deployment_status"] != "ISSUED"
            or qei["compliance_years_completed"] != 0
            or derive.qlicis_of_qei(qei["id"])):
        fail("ERR_INVALID_STATE_TRANSITION")

    qei["deployment_status"] = "VOIDED"
    qei["voided_at"] = clock.now()
    qei["uninvested_cash_cents"] = 0
    qei["permitted_fees_cents"] = 0
    qei["net_deployable_cents"] = 0
    force_bump(award)
    force_bump(db.funds[qei["investment_fund_id"]])
    return qei


# --- annual compliance tests (PRD 3.8) -----------------------------------

@bp.route("/nmtc/qeis/<qei_id>/annual-tests", methods=["GET"])
@endpoint(ALL_ROLES)
def list_annual_tests(qei_id):
    load_qei(qei_id)
    rows = [t for t in db.annual_tests.values() if t["qei_id"] == qei_id]
    rows = filter_str(rows, "result")
    return by_field_asc(rows, "compliance_year")


def _latest_eligibility_reviewers(qei_id):
    reviewers = []
    for qalicb in derive.qalicbs_funded_by(qei_id):
        tests = [t for t in db.eligibility_tests.values() if t["qalicb_id"] == qalicb["id"]]
        if not tests:
            continue
        latest = sorted(tests, key=lambda t: (t["performed_at"], t["_seq"]))[-1]
        reviewers.append(latest["performed_by_user_id"])
    return reviewers


@bp.route("/nmtc/qeis/<qei_id>/annual-tests", methods=["POST"])
@endpoint(["ComplianceReviewer"], mutating=True, status=201)
def run_annual_test(qei_id):
    data = v.body()
    compliance_year = v.req_int(data, "compliance_year")
    qei = load_qei(qei_id)
    award = derive.award_of_qei(qei)

    if g.user_id in _latest_eligibility_reviewers(qei["id"]):
        fail("ERR_SEGREGATION_OF_DUTIES")

    if compliance_year < 1 or compliance_year > 7:
        fail("ERR_TEST_SEQUENCE_INVALID")
    if compliance_year > qei["compliance_years_completed"] + 1:
        fail("ERR_TEST_SEQUENCE_INVALID")

    window_start_at, window_end_at = calc.compliance_window(qei["issued_at"], compliance_year)
    window_days = calc.YEAR_DAYS
    for existing in db.annual_tests.values():
        if existing["qei_id"] != qei["id"]:
            continue
        if (window_start_at < existing["window_end_at"]
                and existing["window_start_at"] < window_end_at):
            fail("ERR_TEST_WINDOW_OVERLAP")

    now = clock.now()

    # Sweep one: reinvestment obligations past their deadline.
    breached_obligation_count = 0
    for obligation in derive.obligations_of_qei(qei["id"]):
        if obligation["status"] == "OPEN" and now > obligation["reinvest_by_at"]:
            obligation["status"] = "BREACHED"
            obligation["breached_at"] = now
            breached_obligation_count += 1

    # Sweep two: stale certifications on businesses funded by qualifying rows.
    recertification_swept = 0
    for qalicb in derive.qalicbs_funded_by(qei["id"], derive.QUALIFYING_QLICI_STATUSES):
        if qalicb["eligibility_status"] != "CERTIFIED":
            continue
        certified_at = qalicb["last_certified_at"]
        if certified_at is None:
            continue
        if now > clock.plus_days(certified_at, calc.YEAR_DAYS):
            qalicb["eligibility_status"] = "RECERTIFICATION_DUE"
            recertification_swept += 1

    # Sweep three: lapsed option windows.
    for unwind in derive.unwinds_of_qei(qei["id"]):
        if unwind["status"] == "OPTION_WINDOW_OPEN" and now >= unwind["option_window_close_at"]:
            unwind["status"] = "EXPIRED"

    measured_direct = derive.pct_direct(qei)
    measured_aggregate = derive.pct_aggregate(qei, window_start_at, window_end_at, window_days)
    governing_method = award["substantially_all_method"]
    governing_pct = (measured_direct if governing_method == "DIRECT_TRACING"
                     else measured_aggregate)
    result = ("PASS"
              if governing_pct >= calc.SUBSTANTIALLY_ALL_THRESHOLD
              and breached_obligation_count == 0
              else "FAIL")

    # The year's CDE asset-management fee waterfall.
    fee_total = calc.cents_from_bps(qei["qei_amount_cents"], calc.CDE_ASSET_MANAGEMENT_FEE_BPS)
    targets = sorted(
        [q for q in derive.qlicis_of_qei(qei["id"])
         if q["status"] in derive.QUALIFYING_QLICI_STATUSES],
        key=lambda q: (q["created_at"], q["_seq"]),
    )
    shares, basis = calc.fee_allocation(fee_total, targets)
    if not shares:
        qei["accrued_unpaid_fee_cents"] = qei["accrued_unpaid_fee_cents"] + fee_total
    else:
        for target in targets:
            target["allocated_fee_cents"] = target["allocated_fee_cents"] + shares[target["id"]]

    qei["substantially_all_pct_direct"] = measured_direct
    qei["substantially_all_pct_aggregate"] = measured_aggregate
    # Order pin: the completed-year counter moves before any recapture arithmetic.
    qei["compliance_years_completed"] = compliance_year

    recapture_triggered = False
    if result == "PASS":
        if qei["compliance_status"] == "AT_RISK":
            qei["compliance_status"] = "COMPLIANT"
            qei["cure_deadline_at"] = None
    else:
        if qei["compliance_status"] == "COMPLIANT":
            qei["compliance_status"] = "AT_RISK"
            qei["cure_deadline_at"] = clock.plus_days(now, calc.CURE_WINDOW_DAYS)
        elif (qei["compliance_status"] == "AT_RISK"
              and qei["cure_deadline_at"] is not None
              and now > qei["cure_deadline_at"]):
            trigger = ("REINVESTMENT_BREACH" if breached_obligation_count > 0
                       else "SUBSTANTIALLY_ALL_FAILURE")
            derive.recapture(qei, trigger)
            recapture_triggered = True

    row = {
        "id": new_id(),
        "created_at": now,
        "qei_id": qei["id"],
        "compliance_year": compliance_year,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "window_days": window_days,
        "measured_pct_direct": measured_direct,
        "measured_pct_aggregate": measured_aggregate,
        "governing_method": governing_method,
        "governing_pct": governing_pct,
        "result": result,
        "breached_obligation_count": breached_obligation_count,
        "fee_allocation_total_cents": fee_total,
        "recapture_triggered": recapture_triggered,
        "recertification_swept_qalicb_count": recertification_swept,
        "performed_by_user_id": g.user_id,
        "performed_at": now,
        "_seq": db.next_seq(),
    }
    db.annual_tests[row["id"]] = row
    force_bump(qei)
    force_bump(award)
    return row, 201


# --- cures (PRD 3.8) ------------------------------------------------------

@bp.route("/nmtc/qeis/<qei_id>/cures", methods=["POST"])
@endpoint(["CDESponsor"], mutating=True)
def cure_qei(qei_id):
    data = v.body()
    qalicb_id = v.req_str(data, "qalicb_id")
    principal_cents = v.req_int(data, "principal_cents", 1)

    qei = load_qei(qei_id)
    qalicb = db.qalicbs.get(qalicb_id)
    if qalicb is None:
        fail("ERR_QALICB_NOT_FOUND")
    award = require_qei_owner(qei)

    if qei["compliance_status"] == "RECAPTURED":
        fail("ERR_QEI_RECAPTURED")
    if qei["compliance_status"] != "AT_RISK":
        fail("ERR_INVALID_STATE_TRANSITION")
    if qei["cure_deadline_at"] is not None and clock.now() > qei["cure_deadline_at"]:
        fail("ERR_INVALID_STATE_TRANSITION")
    if qalicb["eligibility_status"] == "DISQUALIFIED":
        fail("ERR_QALICB_DISQUALIFIED")
    if principal_cents > qei["uninvested_cash_cents"]:
        fail("ERR_INSUFFICIENT_UNINVESTED_CASH")

    now = clock.now()
    qlici = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "qei_id": qei["id"],
        "qalicb_id": qalicb["id"],
        "loan_class": "A",
        "principal_cents": principal_cents,
        "outstanding_principal_cents": principal_cents,
        "total_repaid_cents": 0,
        "deployed_at": now,
        "status": "DEPLOYED",
        "non_qualifying_since_at": None,
        "allocated_fee_cents": 0,
        "created_by_cure": True,
        "_seq": db.next_seq(),
    }
    db.qlicis[qlici["id"]] = qlici
    qei["uninvested_cash_cents"] = qei["uninvested_cash_cents"] - principal_cents
    qei["substantially_all_pct_direct"] = derive.pct_direct(qei)
    derive.return_to_compliant_if_cured(qei)
    force_bump(qei)
    force_bump(award)
    return qei


# --- opening the option window (PRD 3.9) ---------------------------------

@bp.route("/nmtc/qeis/<qei_id>/unwind-transactions", methods=["GET"])
@endpoint(ALL_ROLES)
def list_qei_unwinds(qei_id):
    load_qei(qei_id)
    rows = [u for u in db.unwinds.values() if u["qei_id"] == qei_id]
    rows = filter_str(rows, "status")
    return by_field_asc(rows, "created_at")


@bp.route("/nmtc/qeis/<qei_id>/unwind-transactions", methods=["POST"])
@endpoint(["CDESponsor"], mutating=True, status=201)
def open_unwind(qei_id):
    data = v.body()
    call_holder_user_id = v.req_str(data, "call_holder_user_id", 1, 64)
    qei = load_qei(qei_id)
    require_qei_owner(qei)

    if qei["compliance_status"] == "RECAPTURED":
        fail("ERR_QEI_RECAPTURED")
    for existing in derive.unwinds_of_qei(qei["id"]):
        if existing["status"] != "EXPIRED":
            fail("ERR_UNWIND_ALREADY_OPEN")
    if qei["compliance_years_completed"] != 7:
        fail("ERR_COMPLIANCE_PERIOD_NOT_COMPLETE")

    fund = db.funds[qei["investment_fund_id"]]
    receivable = sum(
        q["outstanding_principal_cents"] for q in derive.qlicis_of_qei(qei["id"])
        if q["status"] in derive.RECEIVABLE_QLICI_STATUSES)
    residual = (qei["uninvested_cash_cents"] + receivable
                - fund["leverage_loan_outstanding_cents"])

    now = clock.now()
    open_at = clock.plus_days(qei["issued_at"], calc.COMPLIANCE_PERIOD_DAYS)
    row = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "qei_id": qei["id"],
        "call_holder_user_id": call_holder_user_id,
        "put_holder_user_id": fund["investor_user_id"],
        "option_window_open_at": open_at,
        "option_window_close_at": clock.plus_days(open_at, calc.OPTION_WINDOW_DAYS),
        "fund_residual_value_cents": residual,
        "put_price_cents": calc.PUT_PRICE_CENTS,
        "call_price_cents": calc.call_price_cents(residual, qei["accrued_unpaid_fee_cents"]),
        "exercised_option_type": None,
        "exercised_at": None,
        "settlement_amount_cents": 0,
        "settlement_reference": None,
        "settled_at": None,
        "status": "OPTION_WINDOW_OPEN",
        "_seq": db.next_seq(),
    }
    db.unwinds[row["id"]] = row
    return row, 201
