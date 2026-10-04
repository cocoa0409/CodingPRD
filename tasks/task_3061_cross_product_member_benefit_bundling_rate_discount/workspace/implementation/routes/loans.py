"""Loan account routes and the discount-application surface."""

from flask import Blueprint

from db import DB
from errors import (
    ERR_DUPLICATE_DISCOUNT_APPLICATION,
    ERR_ENROLLMENT_NOT_ACTIVE,
    ERR_HOLDING_NOT_ADOPTED,
    ERR_INVALID_STATE,
    ERR_STACK_CAP_EXCEEDED,
    ERR_STALE_VERSION,
    ApiError,
)
from middleware import (
    as_enum,
    as_int,
    as_string,
    auth,
    query_filter,
    raw_body,
    reject_unknown,
    require_fields,
    require_owner,
    request_version,
)
from response import ok_array, ok_object
from routes.common import fetch, fetch_member, guard_member_view, list_response, mk
from services import calc, recompute, serialize, workflows

BP = Blueprint("loans", __name__)

LOAN_TYPES = ("PERSONAL", "STUDENT", "AUTO", "REFINANCE")
LOAN_CREATE_ALLOWED = {
    "member_id",
    "holding_id",
    "loan_type",
    "principal_cents",
    "base_apr_bps",
}
APPLICATION_CREATE_ALLOWED = {"rule_id", "expected_loan_account_version", "accept_cap"}


@BP.route("/benefits/loan-accounts", methods=["POST"])
def originate_loan():
    auth(("Underwriter", "PlatformAdmin"))
    payload = raw_body()
    reject_unknown(payload, LOAN_CREATE_ALLOWED)
    require_fields(payload, ("member_id", "holding_id", "loan_type", "principal_cents",
                             "base_apr_bps"))
    member_id = as_string(payload, "member_id")
    fetch_member(member_id)
    holding = fetch("holdings", as_string(payload, "holding_id"))
    if holding["member_id"] != member_id:
        raise ApiError(ERR_INVALID_STATE)
    if holding["product_line"] != "LENDING" or holding["adoption_status"] != "ADOPTED":
        raise ApiError(ERR_HOLDING_NOT_ADOPTED)
    loan_type = as_enum(payload, "loan_type", LOAN_TYPES)
    principal_cents = as_int(payload, "principal_cents", minimum=0)
    base_apr_bps = as_int(payload, "base_apr_bps", minimum=0)

    now = DB.clock()
    from timeutil import fmt_ts

    loan = mk(
        "loan_accounts",
        member_id=member_id,
        holding_id=holding["id"],
        loan_type=loan_type,
        principal_cents=principal_cents,
        base_apr_bps=base_apr_bps,
        autopay_status="NOT_ENROLLED",
        pricing_status="PROVISIONAL",
        discount_stack_bps=0,
        effective_apr_bps=base_apr_bps,
        last_priced_at=fmt_ts(now),
    )
    recompute.materialise_live_applications(member_id)
    recompute.reprice_loan(loan["id"])
    recompute.recompute_holding(holding["id"], bump=False)
    return ok_object(serialize.loan(loan)), 201


@BP.route("/benefits/loan-accounts", methods=["GET"])
def list_loans():
    auth(("PlatformAdmin", "BenefitsAdmin", "Underwriter", "ComplianceOfficer"))
    items = list(DB.loan_accounts.values())
    filters = {
        "member_id": "member_id",
        "holding_id": "holding_id",
        "pricing_status": "pricing_status",
        "autopay_status": "autopay_status",
    }
    return list_response(items, serialize.loan, filters)


@BP.route("/benefits/loan-accounts/<loan_account_id>", methods=["GET"])
def get_loan(loan_account_id):
    user_id, role = auth(
        ("Member", "PlatformAdmin", "Underwriter", "BenefitsAdmin", "ComplianceOfficer")
    )
    loan = fetch("loan_accounts", loan_account_id)
    guard_member_view(user_id, role, loan["member_id"])
    return ok_object(serialize.loan(loan))


@BP.route("/benefits/loan-accounts/<loan_account_id>/autopay-enrollment", methods=["POST"])
def autopay_enrollment(loan_account_id):
    user_id, role = auth(("Member",))
    del role
    loan = fetch("loan_accounts", loan_account_id)
    require_owner(user_id, loan["member_id"])
    if loan["autopay_status"] not in ("NOT_ENROLLED", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE)
    loan["autopay_status"] = "ENROLLED"
    recompute.reprice_loan(loan["id"])
    return ok_object(serialize.loan(loan))


@BP.route("/benefits/loan-accounts/<loan_account_id>/autopay-suspend", methods=["POST"])
def autopay_suspend(loan_account_id):
    auth(("PlatformAdmin",))
    loan = fetch("loan_accounts", loan_account_id)
    if loan["autopay_status"] != "ENROLLED":
        raise ApiError(ERR_INVALID_STATE)
    if loan["pricing_status"] == "STEPPED_DOWN":
        raise ApiError(ERR_INVALID_STATE)
    loan["autopay_status"] = "SUSPENDED"
    recompute.reprice_loan(loan["id"])
    return ok_object(serialize.loan(loan))


@BP.route("/benefits/loan-accounts/<loan_account_id>/finalize-pricing", methods=["POST"])
def finalize_pricing(loan_account_id):
    auth(("Underwriter",))
    loan = fetch("loan_accounts", loan_account_id)
    if loan["pricing_status"] != "PROVISIONAL":
        raise ApiError(ERR_INVALID_STATE)
    workflows.finalize_pricing(loan)
    return ok_object(serialize.loan(loan))


@BP.route("/benefits/loan-accounts/<loan_account_id>/applications", methods=["POST"])
def attach_application(loan_account_id):
    auth(("BenefitsAdmin",))
    loan = fetch("loan_accounts", loan_account_id)
    payload = raw_body()
    reject_unknown(payload, APPLICATION_CREATE_ALLOWED)
    require_fields(payload, ("rule_id",))
    rule_id = as_string(payload, "rule_id")

    expected = request_version("expected_loan_account_version")
    if expected is not None and expected != int(loan["version"]):
        raise ApiError(ERR_STALE_VERSION)

    rule = fetch("rules", rule_id)
    holding = DB.holdings.get(loan["holding_id"])
    if holding is None or holding["adoption_status"] != "ADOPTED":
        raise ApiError(ERR_HOLDING_NOT_ADOPTED)

    for app in calc.applications_of(loan["id"]):
        if app["rule_id"] != rule_id or app["application_state"] != "APPLIED":
            continue
        if app.get("_auto"):
            # the waterfall already priced this rule against the loan, so the
            # caller's attach adopts that priced row instead of duplicating it
            app["_auto"] = False
            return ok_object(serialize.application(app)), 201
        raise ApiError(ERR_DUPLICATE_DISCOUNT_APPLICATION)

    enr = calc.enrollment_of(loan["member_id"])
    if rule.get("requires_direct_deposit") and not (enr and enr["status"] == "ACTIVE"):
        raise ApiError(ERR_ENROLLMENT_NOT_ACTIVE)

    if payload.get("accept_cap") is False:
        projected = calc.uncapped_stack_bps(loan) + int(rule["discount_bps"])
        raise ApiError(ERR_STACK_CAP_EXCEEDED) if projected > calc.STACK_CAP_BPS else None

    created = workflows.attach_application(loan, rule, [])
    recompute.recompute_holding(holding["id"])
    return ok_object(serialize.application(created)), 201


@BP.route("/benefits/loan-accounts/<loan_account_id>/applications", methods=["GET"])
def list_loan_applications(loan_account_id):
    user_id, role = auth(("PlatformAdmin", "BenefitsAdmin", "Underwriter", "Member"))
    loan = fetch("loan_accounts", loan_account_id)
    guard_member_view(user_id, role, loan["member_id"])
    items = calc.applications_of(loan_account_id)
    items.sort(key=lambda a: (a.get("created_at") or "", a["id"]))
    page, limit, offset, total = _paginate(items)
    return ok_array([serialize.application(a) for a in page], limit, offset, total)


def _paginate(items):
    from middleware import paginate

    return paginate(items)


@BP.route("/benefits/loan-accounts/<loan_account_id>/pricing-breakdown", methods=["GET"])
def pricing_breakdown(loan_account_id):
    user_id, role = auth(("PlatformAdmin", "BenefitsAdmin", "Underwriter", "Member"))
    loan = fetch("loan_accounts", loan_account_id)
    guard_member_view(user_id, role, loan["member_id"])
    applied = [
        a for a in calc.applications_of(loan_account_id) if a["application_state"] == "APPLIED"
    ]
    return ok_object(
        {
            "stored_bps": int(loan["discount_stack_bps"]),
            "uncapped_bps": calc.uncapped_stack_bps(loan),
            "effective_apr_bps": int(loan["effective_apr_bps"]),
            "floor_bps": calc.APR_FLOOR_BPS,
            "applied_application_count": len(applied),
        }
    )


@BP.route("/benefits/applications", methods=["GET"])
def list_applications():
    auth(("PlatformAdmin", "BenefitsAdmin", "Underwriter", "ComplianceOfficer"))
    items = list(DB.applications.values())
    filters = {
        "loan_account_id": "loan_account_id",
        "rule_id": "rule_id",
        "application_state": "application_state",
    }
    return list_response(items, serialize.application, filters)


@BP.route("/benefits/applications/<application_id>", methods=["GET"])
def get_application(application_id):
    auth(("PlatformAdmin", "BenefitsAdmin", "Underwriter", "ComplianceOfficer"))
    app = fetch("applications", application_id)
    return ok_object(serialize.application(app))


@BP.route("/benefits/applications/<application_id>/rollback", methods=["POST"])
def rollback_application(application_id):
    auth(("BenefitsAdmin",))
    app = fetch("applications", application_id)
    if app["application_state"] != "APPLIED":
        raise ApiError(ERR_INVALID_STATE)
    workflows.rollback_application(app)
    return ok_object(serialize.application(app))
