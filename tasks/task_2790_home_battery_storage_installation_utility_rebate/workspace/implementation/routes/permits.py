"""Permits: opening, submission, jurisdiction review and field inspections."""

from flask import Blueprint, request

import cascades
import shape
import store
from common import JURISDICTIONS, PERMIT_MAX_CORRECTION_ROUNDS
from envelope import collection, created, ok
from errors import ApiError, invalid
from rules import clock_before
from security import guard, path_ref, ref

bp = Blueprint("permits", __name__)

READ_ROLES = (
    "CertifiedInstaller",
    "Homeowner",
    "AuthorityHavingJurisdiction",
    "UtilityInterconnectionReviewer",
)


def _permit_state_error(permit, action):
    return ApiError(
        "ERR_PERMIT_STATE_INVALID",
        "A permit in %s cannot be %s." % (permit["status"], action),
    )


@bp.route("/permits", methods=["POST"])
@guard("CertifiedInstaller")
def create_permit(actor):
    payload = shape.body()
    system_id = payload.fk("battery_system_id")
    system = ref("battery_system", system_id)
    jurisdiction_code = payload.enum("jurisdiction_code", JURISDICTIONS)
    plan_set_ref = payload.str_("plan_set_ref")

    for existing in store.rows("permits"):
        if existing["battery_system_id"] == system["id"]:
            raise ApiError(
                "ERR_DUPLICATE_PERMIT", "The system already carries a permit."
            )

    record = store.insert(
        "permits",
        {
            "battery_system_id": system_id,
            "jurisdiction_code": jurisdiction_code,
            "plan_set_ref": plan_set_ref,
            "status": "DRAFT",
            "correction_round_count": 0,
            "issued_at": None,
            "expires_on": None,
            "inspection_findings": None,
        },
    )
    return created(store.view(record))


@bp.route("/permits/<permit_id>", methods=["GET"])
@guard(*READ_ROLES)
def read_permit(actor, permit_id):
    record = path_ref(actor, "permit", permit_id)
    return ok(store.view(record))


@bp.route("/permits", methods=["GET"])
@guard(*READ_ROLES)
def list_permits(actor):
    records = store.where(
        "permits",
        battery_system_id=request.args.get("battery_system_id"),
        jurisdiction_code=request.args.get("jurisdiction_code"),
        status=request.args.get("status"),
    )
    return collection(records)


@bp.route("/permits/<permit_id>/submit", methods=["POST"])
@guard("CertifiedInstaller")
def submit_permit(actor, permit_id):
    permit = path_ref(actor, "permit", permit_id)
    payload = shape.body()
    plan_set_ref = payload.str_("plan_set_ref", required=False)

    if permit["status"] not in ("DRAFT", "CORRECTIONS_REQUIRED"):
        raise _permit_state_error(permit, "submitted")
    if permit["status"] == "DRAFT":
        system = store.get("battery_systems", permit["battery_system_id"])
        if system is None or system["build_status"] not in ("DESIGN_LOCKED", "INSTALLED"):
            raise ApiError(
                "ERR_SYSTEM_BUILD_STATE_INVALID",
                "The bank must be design-locked or installed to submit its permit.",
            )

    if plan_set_ref is not None:
        permit["plan_set_ref"] = plan_set_ref
    permit["status"] = "SUBMITTED"
    store.touch(permit)
    return ok(store.view(permit))


@bp.route("/permits/<permit_id>/review", methods=["POST"])
@guard("AuthorityHavingJurisdiction")
def review_permit(actor, permit_id):
    permit = path_ref(actor, "permit", permit_id)
    payload = shape.body()
    decision = payload.enum("decision", ("ISSUE", "REQUEST_CORRECTIONS"))
    expires_on = payload.iso("expires_on", required=False)
    findings = payload.str_("inspection_findings", required=False, allow_empty=True)
    if decision == "ISSUE":
        if expires_on is None:
            raise invalid("'expires_on' is required when issuing a permit.")
        if not clock_before(expires_on):
            raise invalid("'expires_on' must be strictly after the current instant.")

    if permit["status"] != "SUBMITTED":
        raise _permit_state_error(permit, "reviewed")

    if decision == "REQUEST_CORRECTIONS":
        if permit["correction_round_count"] >= PERMIT_MAX_CORRECTION_ROUNDS:
            raise ApiError(
                "ERR_PERMIT_CORRECTION_LIMIT",
                "The permit has exhausted its correction rounds.",
            )
        permit["status"] = "CORRECTIONS_REQUIRED"
        permit["correction_round_count"] += 1
    else:
        permit["status"] = "ISSUED"
        permit["issued_at"] = store.now()
        permit["expires_on"] = expires_on
    if findings is not None:
        permit["inspection_findings"] = findings
    store.touch(permit)
    return ok(store.view(permit))


@bp.route("/permits/<permit_id>/inspection-result", methods=["POST"])
@guard("AuthorityHavingJurisdiction")
def record_inspection(actor, permit_id):
    permit = path_ref(actor, "permit", permit_id)
    payload = shape.body()
    result = payload.enum("result", ("PASS", "FAIL"))
    findings = payload.str_("inspection_findings", required=False, allow_empty=True)

    if result == "PASS":
        allowed = ("ISSUED", "INSPECTION_FAILED")
    else:
        allowed = ("ISSUED", "INSPECTION_PASSED")
    if permit["status"] not in allowed:
        raise _permit_state_error(permit, "inspected with result %s" % result)
    if permit["expires_on"] is None or not clock_before(permit["expires_on"]):
        raise ApiError("ERR_PERMIT_EXPIRED", "The permit validity window has lapsed.")

    revocation = result == "FAIL" and permit["status"] == "INSPECTION_PASSED"
    permit["status"] = "INSPECTION_PASSED" if result == "PASS" else "INSPECTION_FAILED"
    permit["inspection_findings"] = findings
    store.touch(permit)

    if revocation:
        cascades.cascade_a(permit)
    return ok(store.view(permit))
