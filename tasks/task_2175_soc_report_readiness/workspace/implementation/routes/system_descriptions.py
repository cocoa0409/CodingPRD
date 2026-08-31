from flask import Blueprint, request

import auth
import services
import store
import validators as v
from auth import ALL_ROLES
from envelope import ok, ok_page
from errors import ApiError
from store import DB

bp = Blueprint("system_descriptions", __name__)

ACTIONS = ("SUBMIT_REVIEW", "RETURN_TO_DRAFT", "APPROVE", "WITHDRAW")

ACTION_ROLES = {
    "SUBMIT_REVIEW": {"ComplianceLead"},
    "WITHDRAW": {"ComplianceLead"},
    "RETURN_TO_DRAFT": {"Auditor"},
    "APPROVE": {"Auditor"},
}

EDGES = {
    ("DRAFT", "SUBMIT_REVIEW"): "IN_REVIEW",
    ("IN_REVIEW", "RETURN_TO_DRAFT"): "DRAFT",
    ("IN_REVIEW", "APPROVE"): "APPROVED",
    ("DRAFT", "WITHDRAW"): "WITHDRAWN",
    ("IN_REVIEW", "WITHDRAW"): "WITHDRAWN",
}


@bp.post("/soc/system-descriptions")
def create_system_description():
    user_id, _role = auth.authenticate({"ComplianceLead"})
    body = auth.body()
    engagement = v.fk(body, "engagement_id", "engagements")
    v.req_id(body, "engagement_id")
    version_label = v.req_str(body, "version_label", 1, 40)
    narrative = v.req_str(body, "boundary_narrative", 1, 5000)
    expected = v.req_int(body, "expected_engagement_version")

    if expected != engagement["version"]:
        raise ApiError("ERR_STALE_ENGAGEMENT_VERSION")

    for sd in DB["system_descriptions"].values():
        if sd["engagement_id"] == engagement["id"] and sd["version_label"] == version_label:
            raise ApiError("ERR_DUPLICATE_RESOURCE")

    row = store.new_row(
        "system_descriptions",
        {
            "engagement_id": engagement["id"],
            "version_label": version_label,
            "boundary_narrative": narrative,
            "authored_by_user_id": user_id,
            "status": "DRAFT",
            "review_round": 0,
            "boundary_locked": False,
            "supersedes_system_description_id": None,
            "in_scope_component_count": 0,
            "carved_out_component_count": 0,
            "approved_at": None,
        },
    )
    services.bump_engagement_version(engagement)
    services.refresh_engagement(engagement)
    return ok(store.public(row), 201)


@bp.get("/soc/system-descriptions/<system_description_id>")
def read_system_description(system_description_id):
    auth.authenticate(ALL_ROLES)
    row = store.get_or_404("system_descriptions", system_description_id)
    return ok(store.public(row))


@bp.get("/soc/system-descriptions")
def list_system_descriptions():
    auth.authenticate(ALL_ROLES)
    limit, offset = auth.pagination()
    items = store.rows("system_descriptions")
    for key in ("engagement_id", "status", "supersedes_system_description_id"):
        value = request.args.get(key)
        if value is not None:
            items = [r for r in items if r[key] == value]
    page, total = auth.paginate(items, limit, offset)
    return ok_page([store.public(r) for r in page], limit, offset, total)


@bp.post("/soc/system-descriptions/<system_description_id>/transitions")
def transition_system_description(system_description_id):
    user_id, role = auth.authenticate({"ComplianceLead", "Auditor"})
    body = auth.body()
    auth.check_action_role(role, body.get("action"), ACTION_ROLES)
    row = store.get_or_404("system_descriptions", system_description_id)
    action = v.req_enum(body, "action", ACTIONS)
    v.opt_str(body, "reason", 0, 2000)

    engagement = DB["engagements"][row["engagement_id"]]
    target = EDGES.get((row["status"], action))
    if target is None:
        raise ApiError("ERR_TRANSITION_NOT_ALLOWED")

    if action == "SUBMIT_REVIEW":
        services.refresh_component_counts(row)
        if row["in_scope_component_count"] < 1:
            raise ApiError("ERR_INVALID_STATE")
        if engagement["status"] != "SCOPING":
            raise ApiError("ERR_INVALID_STATE")
    elif action == "RETURN_TO_DRAFT":
        if row["boundary_locked"]:
            raise ApiError("ERR_INVALID_STATE")
    elif action == "APPROVE":
        if engagement["status"] != "SCOPING":
            raise ApiError("ERR_INVALID_STATE")
        if user_id == row["authored_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        for comp in DB["boundary_components"].values():
            if comp["system_description_id"] != row["id"]:
                continue
            if comp["scope_status"] != "CARVED_OUT":
                continue
            org = DB["subservice_organizations"].get(comp["subservice_organization_id"])
            if org is None or org["method"] != "CARVE_OUT":
                raise ApiError("ERR_CSOC_NOT_ARTICULATED")

    row["status"] = target
    if action == "RETURN_TO_DRAFT":
        row["review_round"] = row["review_round"] + 1
    store.touch(row)

    if action == "APPROVE":
        row["approved_at"] = store.now_iso()
        previous = None
        for sd in store.rows("system_descriptions"):
            if sd["id"] == row["id"]:
                continue
            if sd["engagement_id"] == engagement["id"] and sd["status"] == "APPROVED":
                previous = sd
                break
        if previous is not None:
            previous["status"] = "SUPERSEDED"
            store.touch(previous)
            row["supersedes_system_description_id"] = previous["id"]
        engagement["approved_system_description_id"] = row["id"]
        engagement["boundary_locked"] = row["boundary_locked"]
        services.bump_engagement_version(engagement)
        services.refresh_engagement(engagement)

    return ok(store.public(row))


@bp.post("/soc/system-descriptions/<system_description_id>/lock-boundary")
def lock_boundary(system_description_id):
    auth.authenticate({"ComplianceLead"})
    row = store.get_or_404("system_descriptions", system_description_id)
    if row["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE")
    engagement = DB["engagements"][row["engagement_id"]]
    row["boundary_locked"] = True
    store.touch(row)
    engagement["boundary_locked"] = True
    services.bump_engagement_version(engagement)
    services.refresh_engagement(engagement)
    return ok(store.public(row))
