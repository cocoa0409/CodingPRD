"""Design projects, play areas, renderings, compliance and pledges under a project."""

from flask import Blueprint

import calc
import cascades
import validate as v
from auth import READ_ROLES, authenticate
from envelope import list_response, object_response
from errors import ApiError
from store import public, public_list, store

bp = Blueprint("projects", __name__)

CANCELLABLE_DESIGN_STATUSES = (
    "DRAFT",
    "CONSULTATION",
    "RENDERED",
    "COMMUNITY_REVIEW",
    "REVISION_REQUESTED",
    "DESIGN_APPROVED",
    "CERTIFIED",
    "ORDERED",
)
UNFUNDABLE_DESIGN_STATUSES = ("CANCELLED", "INSTALLED", "AUDITED")

PLEDGE_ROLES = ["ClientRepresentative", "DesignConsultant"]
PLEDGE_READ_ROLES = [
    "ManufacturerAdmin",
    "ComplianceOfficer",
    "DesignConsultant",
    "ClientRepresentative",
]


def require_editable(project):
    """PRD section 3.2: design content is editable in two statuses only."""
    if project["design_status"] not in calc.DESIGN_EDITABLE_STATUSES:
        raise ApiError("ERR_PROJECT_NOT_EDITABLE")


# -------------------------------------------------------------------- projects

@bp.route("/playground/projects", methods=["POST"])
def create_project():
    caller = authenticate(["DesignConsultant"])
    body = v.raw_body()
    client_name = v.string(body, "client_name", min_len=1, max_len=120)
    site_length = v.integer(body, "site_length_cm", minimum=1, maximum=100000)
    site_width = v.integer(body, "site_width_cm", minimum=1, maximum=100000)
    soil = v.enum(body, "site_soil_type", calc.SOIL_TYPES)
    budget = v.integer(body, "budget_cents", minimum=1)
    deadline = v.date_field(body, "fundraising_deadline")
    bands = v.enum_array(body, "required_age_groups", calc.AGE_GROUPS, 1, 3)
    accessible = v.boolean(body, "accessible_route_required", default=True)

    row = store.insert("project", {
        "client_name": client_name,
        "consultant_user_id": caller.user_id,
        "site_length_cm": site_length,
        "site_width_cm": site_width,
        "site_soil_type": soil,
        "budget_cents": budget,
        "fundraising_deadline": deadline.isoformat(),
        "required_age_groups": bands,
        "accessible_route_required": accessible,
        "design_status": "DRAFT",
        "compliance_status": "NOT_ASSESSED",
        "revision_rounds": 0,
        "installed_on": None,
        "funds_collected_cents": 0,
        "alloc_permit_freight_cents": 0,
        "alloc_surfacing_cents": 0,
        "alloc_structure_cents": 0,
        "alloc_contingency_cents": 0,
    })
    return object_response(public(row), 201)


@bp.route("/playground/projects", methods=["GET"])
def list_projects():
    authenticate(READ_ROLES)
    limit, offset = v.pagination()
    rows = v.apply_filters(store.all("project"), {
        "design_status": "design_status",
        "compliance_status": "compliance_status",
    })
    page, total = v.paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


@bp.route("/playground/projects/<project_id>", methods=["GET"])
def get_project(project_id):
    authenticate(READ_ROLES)
    return object_response(public(store.require("project", project_id)))


@bp.route("/playground/projects/<project_id>/start-consultation", methods=["POST"])
def start_consultation(project_id):
    authenticate(["DesignConsultant"])
    project = store.require("project", project_id)
    if project["design_status"] != "DRAFT":
        raise ApiError("ERR_PROJECT_INVALID_STATE")
    if store.active_standard() is None:
        raise ApiError("ERR_NO_ACTIVE_STANDARD")
    project["design_status"] = "CONSULTATION"
    store.touch(project)
    return object_response(public(project))


# ------------------------------------------------------------------ play areas

@bp.route("/playground/projects/<project_id>/play-areas", methods=["POST"])
def create_play_area(project_id):
    authenticate(["DesignConsultant"])
    project = store.require("project", project_id)
    body = v.raw_body()
    age_group = v.enum(body, "age_group", calc.AGE_GROUPS)
    origin = v.integer(body, "axis_origin_cm", minimum=0)
    length = v.integer(body, "axis_length_cm", minimum=1)
    material = v.enum(body, "surfacing_material", calc.SURFACING_MATERIALS)
    depth = v.integer(body, "surfacing_depth_cm", minimum=0, maximum=120)
    if origin + length > project["site_length_cm"]:
        raise v.bad_request(
            "axis_origin_cm plus axis_length_cm must not exceed the project's site_length_cm."
        )
    for existing in store.project_areas(project_id):
        if existing["age_group"] == age_group:
            raise v.bad_request(
                "This project already has a play area for age group '{}'.".format(age_group)
            )

    require_editable(project)

    row = store.insert("area", {
        "project_id": project_id,
        "age_group": age_group,
        "axis_origin_cm": origin,
        "axis_length_cm": length,
        "surfacing_material": material,
        "surfacing_depth_cm": depth,
        "critical_fall_height_cm": 0,
        "required_surfacing_depth_cm": calc.MIN_SURFACING_DEPTH_CM,
        "status": "PLANNED",
    })
    store.touch(project)
    return object_response(public(row), 201)


@bp.route("/playground/projects/<project_id>/play-areas", methods=["GET"])
def list_project_play_areas(project_id):
    authenticate(READ_ROLES)
    store.require("project", project_id)
    limit, offset = v.pagination()
    rows = v.apply_filters(store.project_areas(project_id), {
        "age_group": "age_group",
        "status": "status",
    })
    page, total = v.paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


# ------------------------------------------------------------------ renderings

@bp.route("/playground/projects/<project_id>/renderings", methods=["POST"])
def issue_rendering(project_id):
    authenticate(["DesignConsultant"])
    project = store.require("project", project_id)
    body = v.raw_body()
    resolved = v.resolve_fks(body, [("pinned_standard_id", "standard", True)])
    v.string(body, "pinned_standard_id", min_len=1)
    pinned = resolved["pinned_standard_id"]

    if project["design_status"] not in calc.DESIGN_EDITABLE_STATUSES:
        raise ApiError("ERR_PROJECT_INVALID_STATE")

    active = store.active_standard()
    if active is None:
        raise ApiError("ERR_NO_ACTIVE_STANDARD")
    if pinned["id"] != active["id"]:
        raise ApiError("ERR_STANDARD_NOT_ACTIVE")

    areas = store.project_areas(project_id)
    covered = set(a["age_group"] for a in areas)
    for band in project["required_age_groups"]:
        if band not in covered:
            raise ApiError("ERR_AGE_GROUP_COVERAGE_INCOMPLETE")

    for area in areas:
        live = [p for p in store.area_placements(area["id"])
                if p["status"] in ("DRAFT", "VALIDATED")]
        if not live:
            raise ApiError("ERR_PLAY_AREA_EMPTY")

    if calc.accessible_route_demanded(project, active):
        if not calc.accessible_route_satisfied(project):
            raise ApiError("ERR_ACCESSIBLE_ROUTE_MISSING")

    highest = 0
    for existing in store.project_renderings(project_id):
        if existing["round_number"] > highest:
            highest = existing["round_number"]

    snapshot = {}
    for area in areas:
        snapshot[area["id"]] = {
            "critical_fall_height_cm": area["critical_fall_height_cm"],
            "required_surfacing_depth_cm": area["required_surfacing_depth_cm"],
            "surfacing_depth_cm": area["surfacing_depth_cm"],
            "placement_count": len(store.area_placements(area["id"])),
        }

    row = store.insert("rendering", {
        "project_id": project_id,
        "pinned_standard_id": pinned["id"],
        "round_number": highest + 1,
        "use_zone_snapshot": snapshot,
        "yes_votes": 0,
        "no_votes": 0,
        "community_approval_pct": 0.0,
        "status": "ISSUED",
    })

    for existing in store.project_renderings(project_id):
        if existing["id"] == row["id"]:
            continue
        if existing["status"] == "ISSUED":
            existing["status"] = "SUPERSEDED"
            store.touch(existing)

    project["design_status"] = "RENDERED"
    store.touch(project)
    return object_response(public(row), 201)


@bp.route("/playground/projects/<project_id>/renderings", methods=["GET"])
def list_project_renderings(project_id):
    authenticate(READ_ROLES)
    store.require("project", project_id)
    limit, offset = v.pagination()
    rows = v.apply_filters(store.project_renderings(project_id), {
        "pinned_standard_id": "pinned_standard_id",
        "status": "status",
    })
    page, total = v.paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


# ------------------------------------------------------- compliance and cancel

@bp.route("/playground/projects/<project_id>/certify-compliance", methods=["POST"])
def certify_compliance(project_id):
    caller = authenticate(["ComplianceOfficer"])
    project = store.require("project", project_id)
    if caller.user_id == project["consultant_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if project["design_status"] != "DESIGN_APPROVED":
        raise ApiError("ERR_PROJECT_INVALID_STATE")

    issued = [r for r in store.project_renderings(project_id) if r["status"] == "ISSUED"]
    pinned = None
    if issued:
        pinned = store.get("standard", issued[-1]["pinned_standard_id"])
    if pinned is None or pinned["status"] != "ACTIVE":
        raise ApiError("ERR_STANDARD_NOT_ACTIVE")

    for placement in store.project_placements(project_id):
        if placement["status"] != "VALIDATED":
            raise ApiError("ERR_PLACEMENTS_NOT_VALIDATED")

    for area in store.project_areas(project_id):
        if area["surfacing_depth_cm"] < area["required_surfacing_depth_cm"]:
            raise ApiError("ERR_SURFACING_DEPTH_INSUFFICIENT")

    if calc.accessible_route_demanded(project, pinned):
        if not calc.accessible_route_satisfied(project):
            raise ApiError("ERR_ACCESSIBLE_ROUTE_MISSING")

    project["design_status"] = "CERTIFIED"
    project["compliance_status"] = "COMPLIANT"
    store.touch(project)
    return object_response(public(project))


@bp.route("/playground/projects/<project_id>/cancel", methods=["POST"])
def cancel_project(project_id):
    authenticate(["DesignConsultant"])
    project = store.require("project", project_id)
    if project["design_status"] not in CANCELLABLE_DESIGN_STATUSES:
        raise ApiError("ERR_PROJECT_NOT_CANCELLABLE")
    cascades.cancel_project(project)
    return object_response(public(project))


# --------------------------------------------------------------------- pledges

@bp.route("/playground/projects/<project_id>/pledges", methods=["POST"])
def create_pledge(project_id):
    authenticate(PLEDGE_ROLES)
    project = store.require("project", project_id)
    body = v.raw_body()
    amount = v.integer(body, "amount_cents", minimum=1)
    pledged_at = v.date_field(body, "pledged_at")
    if pledged_at > store.clock.today():
        raise v.bad_request("pledged_at must not be later than the current logical date.")
    if project["design_status"] in UNFUNDABLE_DESIGN_STATUSES:
        raise ApiError("ERR_PROJECT_NOT_FUNDABLE")
    row = store.insert("pledge", {
        "project_id": project_id,
        "amount_cents": amount,
        "pledged_at": pledged_at.isoformat(),
        "status": "PLEDGED",
    })
    return object_response(public(row), 201)


@bp.route("/playground/projects/<project_id>/pledges", methods=["GET"])
def list_project_pledges(project_id):
    authenticate(PLEDGE_READ_ROLES)
    store.require("project", project_id)
    limit, offset = v.pagination()
    rows = v.apply_filters(store.project_pledges(project_id), {"status": "status"})
    page, total = v.paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)
