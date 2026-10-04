"""LoanApplication endpoints: creation, the underwriting pipeline and the waiver track."""

from flask import Blueprint, request

from db import db, parse_iso, clock_dt, LOCK_BUFFER_DAYS, QUALIFY_SCORE_FLOOR, DTI_QUALIFY_CEILING_BPS
from errors import fail
from response import ok, ok_list, paginate
from checks import (
    authenticate, body, require_fields, int_field, string_field, enum_field,
    get_contract, get_application, check_buyer_ownership, require_state,
)
from services import common, calc, cascades
from services import lock_flows

bp = Blueprint("applications", __name__)

READ_ROLES = [
    "PlatformAdmin",
    "MortgageBanker",
    "ClosingOfficer",
    "ComplianceOfficer",
    "Buyer",
]
LOCK_LIST_ROLES = ["PlatformAdmin", "MortgageBanker", "ClosingOfficer", "ComplianceOfficer"]

WAIVER_TRANSITIONS = {
    ("NOT_REQUESTED", "REQUESTED"): {"SUBMITTED", "QUALIFIED", "EXPIRED"},
    ("REQUESTED", "GRANTED"): {"QUALIFIED"},
    ("REQUESTED", "REFUSED"): {"SUBMITTED", "DENIED"},
    ("GRANTED", "REQUESTED"): {"EXPIRED"},
}
WAIVER_TARGETS = ["NOT_REQUESTED", "REQUESTED", "GRANTED", "REFUSED"]


@bp.post("/housing/contracts/<contract_id>/loan-applications")
def create_application(contract_id):
    authenticate(["MortgageBanker", "SalesCounselor"])
    contract = get_contract(contract_id)
    payload = body()
    require_fields(
        payload,
        ["lender_entity_code", "application_number", "qualifying_income_cents", "monthly_debt_cents"],
    )
    lender = enum_field(payload, "lender_entity_code", ["AFFILIATED_LENDER", "THIRD_PARTY_LENDER"])
    number = string_field(payload, "application_number")
    income = int_field(payload, "qualifying_income_cents", minimum=1)
    debt = int_field(payload, "monthly_debt_cents", minimum=0)

    # Priority 5
    if contract.get("contract_status") not in ("PENDING", "LOCKED"):
        fail("ERR_HOME_SITE_NOT_AVAILABLE", "the contract is not PENDING or LOCKED")
    for existing in db.loan_applications.values():
        if existing.get("application_number") == number:
            fail("ERR_INVALID_ENUM_VALUE", "application_number must be unique")
    # Priority 7: no incentive may be conditioned on lender choice.
    if lender == "AFFILIATED_LENDER":
        carries_buydown = any(
            a.get("bucket") == "RATE_BUYDOWN"
            and a.get("allocation_status") in ("RESERVED", "APPLIED")
            for a in common.allocations_of_contract(contract_id)
        )
        if carries_buydown and not common.has_acknowledged_disclosure(
            contract_id, "STEERING_PROHIBITION"
        ):
            fail(
                "ERR_STEERING_PROHIBITED",
                "an affiliated-lender application may not be conditioned on a rate buydown",
            )

    score, dti_bps = calc.mortgage_qualification_score(income, debt)
    home_site = db.home_sites.get(contract.get("home_site_id"))
    lock_required_days = 0
    if home_site is not None and home_site.get("estimated_completion_iso"):
        completion = parse_iso(home_site["estimated_completion_iso"])
        if completion is not None:
            lock_required_days = max(0, (completion - clock_dt()).days) + LOCK_BUFFER_DAYS

    row = {
        "id": db.new_id(),
        "contract_id": contract_id,
        "lender_entity_code": lender,
        "application_number": number,
        "qualification_score": score,
        "qualifying_income_cents": income,
        "monthly_debt_cents": debt,
        "dti_bps": dti_bps,
        "lock_required_days": lock_required_days,
        "drift_flag": False,
        "application_status": "SUBMITTED",
        "lock_waiver_status": "NOT_REQUESTED",
        "uw_precedence": "SUBMITTED_NOT_REQUESTED",
        "qualified_at": None,
        "application_expired_at": None,
    }
    common.stamp_new(row)
    db.loan_applications[row["id"]] = row
    lock_flows.recompute_drift(row)

    if lender == "AFFILIATED_LENDER":
        buyer = cascades.buyer_of_contract(contract)
        if buyer is not None:
            buyer["affiliated_lender_selected"] = True
            common.touch(buyer)
    return ok(common.dump(row), 201)


@bp.get("/housing/loan-applications/<application_id>")
def get_application_detail(application_id):
    authenticate(READ_ROLES)
    application = get_application(application_id)
    check_buyer_ownership({"buyer_id": _owner_of(application)}, "buyer_id")
    return ok(common.dump(application), 200)


def _owner_of(application):
    contract = db.contracts.get(application.get("contract_id"))
    return contract.get("buyer_id") if contract else None


@bp.post("/housing/loan-applications/<application_id>/qualify")
def qualify_application(application_id):
    authenticate(["MortgageBanker"])
    application = get_application(application_id)
    require_state(application, "application_status", {"SUBMITTED"})
    score, dti_bps = calc.mortgage_qualification_score(
        application.get("qualifying_income_cents"), application.get("monthly_debt_cents")
    )
    application["qualification_score"] = score
    if dti_bps > DTI_QUALIFY_CEILING_BPS:
        fail("ERR_DTI_CEILING_EXCEEDED", "the debt-to-income ratio exceeds the qualifying ceiling")
    if score < QUALIFY_SCORE_FLOOR:
        fail("ERR_QUALIFICATION_SCORE_BELOW_FLOOR", "the qualification score is below the floor")

    application["application_status"] = "QUALIFIED"
    application["dti_bps"] = dti_bps  # final variant, frozen here
    application["qualified_at"] = db.clock
    common.touch(application)

    contract = db.contracts.get(application.get("contract_id"))
    if contract is not None:
        common.recompute_incentive_budget(contract)
        common.touch(contract)
    buyer = cascades.buyer_of_contract(contract) if contract is not None else None
    if buyer is not None:
        cascades.set_buyer_status(buyer, "CONTRACTED")
        cascades.refresh_buyer(buyer)
    return ok(common.dump(application), 200)


@bp.post("/housing/loan-applications/<application_id>/deny")
def deny_application(application_id):
    authenticate(["MortgageBanker"])
    application = get_application(application_id)
    require_state(application, "application_status", {"SUBMITTED"})
    if application.get("lock_waiver_status") not in ("NOT_REQUESTED", "REQUESTED", "REFUSED"):
        fail("ERR_INVALID_STATE", "the waiver track blocks a denial from this state")
    lock_flows.deny_application(application)
    return ok(common.dump(application), 200)


@bp.post("/housing/loan-applications/<application_id>/relock")
def relock_application(application_id):
    authenticate(["MortgageBanker"])
    application = get_application(application_id)
    require_state(application, "application_status", {"EXPIRED"})
    if application.get("drift_flag"):
        fail("ERR_APPLICATION_DRIFT_EXCLUDED", "the application is excluded by drift")
    score, _ = calc.mortgage_qualification_score(
        application.get("qualifying_income_cents"), application.get("monthly_debt_cents")
    )
    if score < QUALIFY_SCORE_FLOOR:
        fail("ERR_QUALIFICATION_SCORE_BELOW_FLOOR", "the qualification score is below the floor")

    application["application_status"] = "QUALIFIED"
    application["qualification_score"] = score
    application["qualified_at"] = db.clock
    lock_flows.recompute_drift(application)
    common.touch(application)

    contract = db.contracts.get(application.get("contract_id"))
    if contract is not None:
        buyer = cascades.buyer_of_contract(contract)
        if buyer is not None:
            cascades.refresh_buyer(buyer)
    return ok(common.dump(application), 200)


@bp.post("/housing/loan-applications/<application_id>/lock-waiver")
def set_lock_waiver(application_id):
    authenticate(["SalesCounselor", "MortgageBanker"])
    application = get_application(application_id)
    payload = body()
    require_fields(payload, ["target_waiver_status"])
    target = enum_field(payload, "target_waiver_status", WAIVER_TARGETS)
    current = application.get("lock_waiver_status")
    allowed_states = WAIVER_TRANSITIONS.get((current, target))
    if allowed_states is None:
        fail("ERR_INVALID_STATE", "no waiver transition is declared from the current state")
    if application.get("application_status") not in allowed_states:
        fail("ERR_INVALID_STATE", "the underwriting dimension blocks this waiver move")
    application["lock_waiver_status"] = target
    application["uw_precedence"] = "%s_%s" % (
        application.get("application_status"),
        target,
    )
    common.touch(application)
    return ok(common.dump(application), 200)


@bp.get("/housing/loan-applications/<application_id>/rate-locks")
def list_application_locks(application_id):
    authenticate(LOCK_LIST_ROLES)
    get_application(application_id)
    rows = lock_flows.locks_of_application(application_id)
    window, pagination = paginate(
        common.sort_rows(rows), request.args.get("limit"), request.args.get("offset")
    )
    return ok_list(common.dump_all(window), 200, pagination)