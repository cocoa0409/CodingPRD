"""Cross-sell eligibility and compliance decision routes."""

from flask import Blueprint

from db import DB
from errors import ERR_INVALID_STATE, ApiError
from middleware import as_bool, as_enum, as_string, auth, raw_body, reject_unknown, require_fields
from response import ok_object
from routes.common import fetch, fetch_member, list_response, mk
from services import serialize, workflows

BP = Blueprint("crosssell", __name__)

PRODUCT_LINES = ("LENDING", "BANKING", "INVESTING", "CAREER")
OUTCOMES = ("CLEARED", "BLOCKED", "REUSE_PROHIBITED")
CREATE_ALLOWED = {"member_id", "target_product_line", "consent_recorded"}
DECIDE_ALLOWED = {"outcome"}


@BP.route("/benefits/cross-sell-checks", methods=["POST"])
def open_check():
    auth(("BenefitsAdmin",))
    payload = raw_body()
    reject_unknown(payload, CREATE_ALLOWED)
    require_fields(payload, ("member_id", "target_product_line"))
    member_id = as_string(payload, "member_id")
    fetch_member(member_id)
    target_product_line = as_enum(payload, "target_product_line", PRODUCT_LINES)
    consent_recorded = as_bool(payload, "consent_recorded", default=False)

    check = mk(
        "checks",
        member_id=member_id,
        target_product_line=target_product_line,
        consent_recorded=consent_recorded,
        underwriting_reuse_permitted=False,
        conditioning_blocked=False,
        status="PENDING",
        decided_at=None,
        decided_by=None,
    )
    workflows.refresh_check_derived(check)
    return ok_object(serialize.check(check)), 201


@BP.route("/benefits/cross-sell-checks", methods=["GET"])
def list_checks():
    auth(("PlatformAdmin", "ComplianceOfficer", "BenefitsAdmin"))
    items = list(DB.checks.values())
    filters = {
        "member_id": "member_id",
        "target_product_line": "target_product_line",
        "status": "status",
    }
    return list_response(items, serialize.check, filters)


@BP.route("/benefits/cross-sell-checks/<check_id>", methods=["GET"])
def get_check(check_id):
    auth(("PlatformAdmin", "ComplianceOfficer", "BenefitsAdmin"))
    check = fetch("checks", check_id)
    return ok_object(serialize.check(check))


@BP.route("/benefits/cross-sell-checks/<check_id>/decide", methods=["POST"])
def decide_check(check_id):
    user_id, role = auth(("ComplianceOfficer",))
    del role
    check = fetch("checks", check_id)
    if check["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE)
    payload = raw_body()
    reject_unknown(payload, DECIDE_ALLOWED)
    require_fields(payload, ("outcome",))
    outcome = as_enum(payload, "outcome", OUTCOMES)
    workflows.refresh_check_derived(check)
    workflows.decide_check(check, outcome, user_id)
    return ok_object(serialize.check(check))