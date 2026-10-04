"""Direct-deposit enrolment routes."""

from flask import Blueprint

from db import DB
from errors import ERR_INVALID_STATE, ApiError
from middleware import as_int, as_string, auth, raw_body, reject_unknown, require_fields
from response import ok_object
from routes.common import fetch, fetch_member, guard_member_view, list_response, mk
from services import recompute, serialize, workflows

BP = Blueprint("deposits", __name__)

CREATE_ALLOWED = {"member_id", "required_monthly_amount_cents"}


@BP.route("/benefits/deposit-enrollments", methods=["POST"])
def open_enrollment():
    auth(("PlatformAdmin", "BenefitsAdmin"))
    payload = raw_body()
    reject_unknown(payload, CREATE_ALLOWED)
    require_fields(payload, ("member_id", "required_monthly_amount_cents"))
    member_id = as_string(payload, "member_id")
    fetch_member(member_id)
    required = as_int(payload, "required_monthly_amount_cents", minimum=0)
    enr = mk(
        "enrollments",
        member_id=member_id,
        required_monthly_amount_cents=required,
        status="PENDING_VERIFICATION",
        qualified_at=None,
        last_deposit_at=None,
        consecutive_qualifying_months=0,
        requalification_due_at=None,
        grace_deadline_at=None,
        missed_cycle_count=0,
        _lapsed_at=None,
    )
    return ok_object(serialize.enrollment(enr)), 201


@BP.route("/benefits/deposit-enrollments", methods=["GET"])
def list_enrollments():
    auth(("PlatformAdmin", "BenefitsAdmin", "ComplianceOfficer"))
    items = list(DB.enrollments.values())
    filters = {"member_id": "member_id", "status": "status"}
    return list_response(items, serialize.enrollment, filters)


@BP.route("/benefits/deposit-enrollments/<enrollment_id>", methods=["GET"])
def get_enrollment(enrollment_id):
    user_id, role = auth(("Member", "PlatformAdmin", "BenefitsAdmin", "ComplianceOfficer"))
    enr = fetch("enrollments", enrollment_id)
    guard_member_view(user_id, role, enr["member_id"])
    return ok_object(serialize.enrollment(enr))


@BP.route("/benefits/deposit-enrollments/<enrollment_id>/activate", methods=["POST"])
def activate_enrollment(enrollment_id):
    auth(("PlatformAdmin",))
    enr = fetch("enrollments", enrollment_id)
    if enr["status"] not in ("PENDING_VERIFICATION", "LAPSED"):
        raise ApiError(ERR_INVALID_STATE)
    workflows.activate_enrollment(enr)
    return ok_object(serialize.enrollment(enr))


@BP.route("/benefits/deposit-enrollments/<enrollment_id>/lapse", methods=["POST"])
def lapse_enrollment(enrollment_id):
    auth(("PlatformAdmin",))
    enr = fetch("enrollments", enrollment_id)
    if enr["status"] not in ("ACTIVE", "GRACE"):
        raise ApiError(ERR_INVALID_STATE)
    workflows.lapse_enrollment(enr)
    recompute.refresh_member_derived(enr["member_id"])
    return ok_object(serialize.enrollment(enr))