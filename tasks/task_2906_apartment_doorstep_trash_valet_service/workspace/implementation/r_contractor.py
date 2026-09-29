"""ValetContractor endpoints (PRD s3.3)."""

from flask import Blueprint

import shape
from authz import admit, get_contractor
from calc import compute_classification, recompute_assigned_unit_coverage, routes_of_contractor
from envelope import array_response, object_response
from errors import ApiError
from serializers import contractor_out
from shape import pagination, paginate, q
from store import OPEN_ROUTE_STATUSES, db, sort_rows, stamp_new, touch

bp = Blueprint("contractor", __name__)

TERMINAL_ONBOARDING = ("REJECTED", "DEACTIVATED")


@bp.route("/valet/contractors", methods=["POST"])
def create_contractor():
    actor = admit(("PlatformAdmin", "ValetOpsManager"))
    body = shape.body()
    legal_name = shape.req_str(body, "legal_name", min_len=1, max_len=120, non_blank=True)
    equipment = shape.req_bool(body, "equipment_provided_by_company")
    own_schedule = shape.req_bool(body, "sets_own_schedule")
    exclusive = shape.req_bool(body, "works_exclusively")
    hours = shape.req_int(body, "weekly_committed_hours", lo=0, hi=80)

    row = {
        "legal_name": legal_name,
        "equipment_provided_by_company": equipment,
        "sets_own_schedule": own_schedule,
        "works_exclusively": exclusive,
        "weekly_committed_hours": hours,
        "tax_form_type": None,
        "direct_deposit_on_file": False,
        "onboarding_status": "APPLIED",
        "classification": "UNCLASSIFIED",
        "classification_basis": None,
        "control_score": 0,
        "observed_weekly_hours": 0,
        "background_checked_by_user_id": None,
        "created_by_user_id": actor.user_id,
        "deactivation_reason": None,
    }
    stamp_new(row)
    db.contractors[row["id"]] = row
    return object_response(contractor_out(row), 201)


@bp.route("/valet/contractors/<contractor_id>", methods=["GET"])
def read_contractor(contractor_id):
    admit(("PlatformAdmin", "ValetOpsManager", "ComplianceOfficer", "Valet"))
    row = get_contractor(contractor_id)
    return object_response(contractor_out(row))


@bp.route("/valet/contractors", methods=["GET"])
def list_contractors():
    admit(("PlatformAdmin", "ValetOpsManager", "ComplianceOfficer"))
    limit, offset = pagination()
    f_onboarding = q("onboarding_status")
    f_classification = q("classification")
    rows = sort_rows(list(db.contractors.values()))
    if f_onboarding is not None:
        rows = [r for r in rows if r["onboarding_status"] == f_onboarding]
    if f_classification is not None:
        rows = [r for r in rows if r["classification"] == f_classification]
    page, total, has_more = paginate(rows, limit, offset)
    return array_response([contractor_out(r) for r in page], limit, offset, total, has_more)


@bp.route("/valet/contractors/<contractor_id>/documents", methods=["POST"])
def contractor_documents(contractor_id):
    admit(("PlatformAdmin", "ValetOpsManager"))
    contractor = get_contractor(contractor_id)
    body = shape.body()
    tax_form_type = shape.req_enum(body, "tax_form_type", ("W9", "W4"))
    deposit = shape.req_bool(body, "direct_deposit_on_file")

    if contractor["onboarding_status"] in TERMINAL_ONBOARDING:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if contractor["onboarding_status"] != "APPLIED":
        raise ApiError("ERR_INVALID_STATE")

    contractor["tax_form_type"] = tax_form_type
    contractor["direct_deposit_on_file"] = deposit
    contractor["onboarding_status"] = "BACKGROUND_PENDING"
    touch(contractor)
    return object_response(contractor_out(contractor))


@bp.route("/valet/contractors/<contractor_id>/background-check", methods=["POST"])
def contractor_background_check(contractor_id):
    actor = admit(("ComplianceOfficer",))
    contractor = get_contractor(contractor_id)
    body = shape.body()
    result = shape.req_enum(body, "result", ("CLEAR", "FAIL"))

    if contractor["onboarding_status"] in TERMINAL_ONBOARDING:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if contractor["onboarding_status"] != "BACKGROUND_PENDING":
        raise ApiError("ERR_INVALID_STATE")

    contractor["onboarding_status"] = "CLEARED" if result == "CLEAR" else "REJECTED"
    contractor["background_checked_by_user_id"] = actor.user_id
    touch(contractor)
    return object_response(contractor_out(contractor))


@bp.route("/valet/contractors/<contractor_id>/classification", methods=["POST"])
def contractor_classification(contractor_id):
    actor = admit(("ComplianceOfficer",))
    contractor = get_contractor(contractor_id)
    body = shape.body()
    basis = shape.req_enum(body, "basis", ("DECLARED", "OBSERVED"))

    # rung 8
    if contractor["onboarding_status"] in TERMINAL_ONBOARDING:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if contractor["onboarding_status"] != "CLEARED":
        raise ApiError("ERR_INVALID_STATE")

    # rung 13 -- OBSERVED only; a DECLARED run carries no audit-independence rule
    if basis == "OBSERVED" and actor.user_id == contractor.get("background_checked_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    outcome = compute_classification(contractor, basis)
    contractor["control_score"] = outcome["control_score"]
    contractor["classification"] = outcome["classification"]
    contractor["classification_basis"] = basis
    if basis == "OBSERVED":
        contractor["observed_weekly_hours"] = outcome["observed_weekly_hours"]
    touch(contractor)
    return object_response(contractor_out(contractor))


@bp.route("/valet/contractors/<contractor_id>/deactivate", methods=["POST"])
def contractor_deactivate(contractor_id):
    admit(("PlatformAdmin", "ValetOpsManager"))
    contractor = get_contractor(contractor_id)
    body = shape.body()
    reason = shape.req_str(body, "reason", min_len=1, max_len=500, non_blank=True)

    if contractor["onboarding_status"] in TERMINAL_ONBOARDING:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if contractor["onboarding_status"] != "CLEARED":
        raise ApiError("ERR_INVALID_STATE")
    live = [r for r in routes_of_contractor(contractor["id"]) if r["status"] in OPEN_ROUTE_STATUSES]
    if live:
        raise ApiError("ERR_INVALID_STATE")

    contractor["onboarding_status"] = "DEACTIVATED"
    contractor["deactivation_reason"] = reason
    touch(contractor)

    # defensive: any route still live leaves the night's conserved coverage sum
    for route in live:
        route["status"] = "ABANDONED"
        route["abandon_reason"] = "CONTRACTOR_DEACTIVATED"
        touch(route)
        night = db.nights.get(route["service_night_id"])
        if night is not None:
            recompute_assigned_unit_coverage(night)
            touch(night)
    return object_response(contractor_out(contractor))
