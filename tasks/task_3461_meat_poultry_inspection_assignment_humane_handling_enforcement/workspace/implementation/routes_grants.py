"""Grant of inspection applications (PRD §3.1)."""
from flask import Blueprint, request

import store
from authz import require_ownership, require_roles
from envelope import get_body, pagination_params, sort_and_page, success_list, success_object
from errors import raise_err, ERR_GRANT_APPLICATION_NOT_FOUND, ERR_GRANT_DECISION_BLOCKED, ERR_INVALID_STATE
from guards import entity_or_404, establishment_or_404, require_not_withdrawn
from store import insert, stamp_new, touch
from validate import require_enum, require_string

bp = Blueprint("grant_applications", __name__)

READ_ROLES = ("EstablishmentManager", "Inspector", "SupervisoryReviewer", "DistrictManager", "ProgramAdministrator")

_FINDING_FIELD = {
    "FACILITY": "facility_finding",
    "SANITATION": "sanitation_finding",
    "HACCP": "haccp_finding",
}


def _app_or_404(app_id):
    return entity_or_404("grant_applications", app_id, ERR_GRANT_APPLICATION_NOT_FOUND)


@bp.post("/inspection/grant-applications")
def create_grant_application():
    user_id, _ = require_roles("EstablishmentManager")
    body = get_body()
    establishment_id = require_string(body, "establishment_id")
    facility_doc_ref = require_string(body, "facility_doc_ref")
    sanitation_plan_ref = require_string(body, "sanitation_plan_ref")
    haccp_plan_ref = require_string(body, "haccp_plan_ref")
    # Ownership pinning (tier 2): X-User-ID must equal establishment_id.
    require_ownership(user_id, establishment_id)
    establishment = establishment_or_404(establishment_id)
    require_not_withdrawn(establishment)

    application = {
        "establishment_id": establishment_id,
        "facility_doc_ref": facility_doc_ref,
        "sanitation_plan_ref": sanitation_plan_ref,
        "haccp_plan_ref": haccp_plan_ref,
        "facility_finding": "PENDING",
        "sanitation_finding": "PENDING",
        "haccp_finding": "PENDING",
        "status": "SUBMITTED",
        "revision_count": 0,
        "decided_at": None,
    }
    stamp_new(application)
    insert("grant_applications", application)
    return success_object(application, status=201)


@bp.get("/inspection/establishments/<est_id>/grant-applications")
def list_grant_applications(est_id):
    require_roles(*READ_ROLES)
    establishment_or_404(est_id)
    status_filter = request.args.get("status")
    rows = [a for a in store.all_of("grant_applications") if a["establishment_id"] == est_id]
    if status_filter is not None:
        rows = [a for a in rows if a["status"] == status_filter]
    limit, offset = pagination_params()
    page, total = sort_and_page(rows, limit, offset)
    return success_list(page, limit, offset, total)


@bp.post("/inspection/grant-applications/<app_id>/begin-review")
def begin_review(app_id):
    require_roles("DistrictManager")
    application = _app_or_404(app_id)
    require_not_withdrawn(establishment_or_404(application["establishment_id"]))
    if application["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "begin-review requires status SUBMITTED")
    application["status"] = "UNDER_REVIEW"
    touch(application)
    return success_object(application)


@bp.post("/inspection/grant-applications/<app_id>/record-adequacy")
def record_adequacy(app_id):
    require_roles("DistrictManager")
    application = _app_or_404(app_id)
    require_not_withdrawn(establishment_or_404(application["establishment_id"]))
    if application["status"] != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, "record-adequacy requires status UNDER_REVIEW")
    body = get_body()
    dimension = require_enum(body, "dimension", ("FACILITY", "SANITATION", "HACCP"))
    finding = require_enum(body, "finding", ("ADEQUATE", "DEFICIENT"))
    # Self-loop on UNDER_REVIEW: sets exactly one finding; may overwrite a
    # prior finding on the same dimension.
    application[_FINDING_FIELD[dimension]] = finding
    touch(application)
    return success_object(application)


@bp.post("/inspection/grant-applications/<app_id>/decide")
def decide(app_id):
    require_roles("DistrictManager")
    application = _app_or_404(app_id)
    establishment = establishment_or_404(application["establishment_id"])
    require_not_withdrawn(establishment)
    # State legality outranks the findings check (PRD §3.1).
    if application["status"] != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, "decide requires status UNDER_REVIEW")
    body = get_body()
    decision = require_enum(body, "decision", ("GRANT", "DENY"))

    if decision == "GRANT":
        if not (
            application["facility_finding"] == "ADEQUATE"
            and application["sanitation_finding"] == "ADEQUATE"
            and application["haccp_finding"] == "ADEQUATE"
        ):
            raise_err(ERR_GRANT_DECISION_BLOCKED, "all three findings must be ADEQUATE to grant")
        application["status"] = "GRANTED"
        application["decided_at"] = store.clock_now()
        touch(application)
        # Same-request cascade: establishment GRANTED x ACTIVE, version +1.
        establishment["grant_status"] = "GRANTED"
        establishment["inspection_status"] = "ACTIVE"
        touch(establishment)
    else:  # DENY
        application["status"] = "DENIED"
        application["decided_at"] = store.clock_now()
        touch(application)
    return success_object(application)


@bp.post("/inspection/grant-applications/<app_id>/resubmit")
def resubmit(app_id):
    user_id, _ = require_roles("EstablishmentManager")
    application = _app_or_404(app_id)
    require_ownership(user_id, application["establishment_id"])
    require_not_withdrawn(establishment_or_404(application["establishment_id"]))
    if application["status"] != "DENIED":
        raise_err(ERR_INVALID_STATE, "resubmit requires status DENIED")
    body = get_body()
    facility_doc_ref = require_string(body, "facility_doc_ref")
    sanitation_plan_ref = require_string(body, "sanitation_plan_ref")
    haccp_plan_ref = require_string(body, "haccp_plan_ref")

    application["facility_doc_ref"] = facility_doc_ref
    application["sanitation_plan_ref"] = sanitation_plan_ref
    application["haccp_plan_ref"] = haccp_plan_ref
    application["facility_finding"] = "PENDING"
    application["sanitation_finding"] = "PENDING"
    application["haccp_finding"] = "PENDING"
    application["status"] = "SUBMITTED"
    application["revision_count"] += 1
    touch(application)
    return success_object(application)


@bp.post("/inspection/grant-applications/<app_id>/withdraw")
def withdraw(app_id):
    user_id, _ = require_roles("EstablishmentManager")
    application = _app_or_404(app_id)
    require_ownership(user_id, application["establishment_id"])
    require_not_withdrawn(establishment_or_404(application["establishment_id"]))
    if application["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
        raise_err(ERR_INVALID_STATE, "withdraw requires status SUBMITTED or UNDER_REVIEW")
    application["status"] = "WITHDRAWN"
    touch(application)
    return success_object(application)
