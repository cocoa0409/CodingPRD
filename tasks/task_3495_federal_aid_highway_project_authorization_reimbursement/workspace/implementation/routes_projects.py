"""Project nomination, estimate maintenance (PATCH + OCC), and eligibility
determination (PRD §3.3)."""
from decimal import Decimal

from flask import Blueprint, request

from calculations import (
    ACTIVITY_CODES,
    adjusted_full_share,
    provisional_estimate_cents,
    statutory_base_share,
)
from db import STORE, new_id, now_bookkeeping, touch
from errors import err
from helpers import (
    as_bool,
    as_enum,
    as_int,
    as_number,
    as_str,
    get_body,
    paginate,
    req_field,
    resolve_body_fk,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from routes_stips import _reopen_for_amendment
from serializers import serialize_project

bp = Blueprint("projects", __name__)


def _resolve_project(pid):
    project = STORE["projects"].get(pid)
    if project is None:
        raise err("ERR_NOT_FOUND", "Project not found")
    return project


def _validate_dbe_goal(value):
    d = Decimal(str(value))
    if d < 0 or d > 1:
        raise err("ERR_INVALID_REQUEST", "dbe_goal_pct must be between 0 and 1 inclusive")


@bp.route("/federal-aid/projects", methods=["POST"])
@require_roles("StateDOTPlanner")
def create_project(user_id, user_role):
    body = get_body()
    # Body FKs resolve before body well-formedness on plain creates (PRD §2.9).
    if "stip_id" in body and body["stip_id"] is not None:
        resolve_body_fk("stips", body["stip_id"], "stip_id")
    if "funding_program_id" in body and body["funding_program_id"] is not None:
        resolve_body_fk("funding_programs", body["funding_program_id"], "funding_program_id")
    stip_id = as_str(req_field(body, "stip_id"), "stip_id")
    funding_program_id = as_str(
        req_field(body, "funding_program_id"), "funding_program_id"
    )
    stip = STORE["stips"][stip_id]
    program = STORE["funding_programs"][funding_program_id]
    route_name = as_str(req_field(body, "route_name"), "route_name")
    description = as_str(req_field(body, "description"), "description")
    activity_code = as_enum(
        req_field(body, "activity_code"), "activity_code", ACTIVITY_CODES
    )
    is_interstate = as_bool(
        req_field(body, "is_interstate_system"), "is_interstate_system"
    )
    dbe_goal = as_number(req_field(body, "dbe_goal_pct"), "dbe_goal_pct")
    _validate_dbe_goal(dbe_goal)
    total_cost = as_int(
        req_field(body, "total_estimated_cost_cents"), "total_estimated_cost_cents"
    )
    if total_cost <= 0:
        raise err(
            "ERR_INVALID_REQUEST", "total_estimated_cost_cents must be greater than 0"
        )
    share = statutory_base_share(program)
    now = now_bookkeeping()
    rec = {
        "id": new_id(),
        "stip_id": stip_id,
        "funding_program_id": funding_program_id,
        "route_name": route_name,
        "description": description,
        "activity_code": activity_code,
        "is_interstate_system": is_interstate,
        "dbe_goal_pct": dbe_goal,
        "total_estimated_cost_cents": total_cost,
        "_provisional_share_dec": share,
        "provisional_federal_estimate_cents": provisional_estimate_cents(
            total_cost, share
        ),
        "_determined_share_dec": None,
        "status": "NOMINATED",
        "advertised_on_date": None,
        "_advertised_dt": None,
        "awarded_bid_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE["projects"][rec["id"]] = rec
    # Nomination into an APPROVED STIP cascades the amendment reopening.
    if stip["status"] == "APPROVED":
        _reopen_for_amendment(stip)
    return success_object(serialize_project(rec), status=201)


@bp.route("/federal-aid/projects/<pid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_project(pid, user_id, user_role):
    return success_object(serialize_project(_resolve_project(pid)))


@bp.route("/federal-aid/projects", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_projects(user_id, user_role):
    stip_id = request.args.get("stip_id")
    fp_id = request.args.get("funding_program_id")
    status = request.args.get("status")
    items = list(STORE["projects"].values())
    if stip_id is not None:
        items = [p for p in items if p["stip_id"] == stip_id]
    if fp_id is not None:
        items = [p for p in items if p["funding_program_id"] == fp_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda p: p["created_at"])
    page, total, limit, offset = paginate(items)
    return success_list([serialize_project(p) for p in page], total, limit, offset)


@bp.route("/federal-aid/projects/<pid>", methods=["PATCH"])
@require_roles("StateDOTPlanner")
def patch_project(pid, user_id, user_role):
    project = _resolve_project(pid)
    body = get_body()
    # Body well-formedness (priority 4) precedes the OCC check (priority 5).
    expected = as_int(
        req_field(body, "expected_project_version"), "expected_project_version"
    )
    if "description" in body and body["description"] is not None:
        as_str(body["description"], "description")
    if "total_estimated_cost_cents" in body and body["total_estimated_cost_cents"] is not None:
        new_cost = as_int(body["total_estimated_cost_cents"], "total_estimated_cost_cents")
        if new_cost <= 0:
            raise err(
                "ERR_INVALID_REQUEST",
                "total_estimated_cost_cents must be greater than 0",
            )
    if "dbe_goal_pct" in body and body["dbe_goal_pct"] is not None:
        _validate_dbe_goal(as_number(body["dbe_goal_pct"], "dbe_goal_pct"))
    # OCC (priority 5) precedes the state gate (priority 6).
    if expected != project["version"]:
        raise err(
            "ERR_STALE_VERSION",
            "expected_project_version does not match the Project's current version",
        )
    if project["status"] not in ("NOMINATED", "ELIGIBLE"):
        raise err(
            "ERR_INVALID_STATE",
            "Projects may only be patched while NOMINATED or ELIGIBLE",
        )
    if "description" in body and body["description"] is not None:
        project["description"] = body["description"]
    if "dbe_goal_pct" in body and body["dbe_goal_pct"] is not None:
        project["dbe_goal_pct"] = body["dbe_goal_pct"]
    if "total_estimated_cost_cents" in body and body["total_estimated_cost_cents"] is not None:
        project["total_estimated_cost_cents"] = body["total_estimated_cost_cents"]
        # Cost change recomputes the provisional estimate (statutory_base only).
        project["provisional_federal_estimate_cents"] = provisional_estimate_cents(
            project["total_estimated_cost_cents"], project["_provisional_share_dec"]
        )
    touch(project)
    return success_object(serialize_project(project))


@bp.route("/federal-aid/projects/<pid>/determine-eligibility", methods=["POST"])
@require_roles("FHWADivisionAdmin")
def determine_eligibility(pid, user_id, user_role):
    project = _resolve_project(pid)
    body = get_body()
    determination = as_enum(
        req_field(body, "determination"), "determination", ("ELIGIBLE", "INELIGIBLE")
    )
    if project["status"] != "NOMINATED":
        raise err("ERR_INVALID_STATE", "Project is not in NOMINATED")
    stip = STORE["stips"][project["stip_id"]]
    if stip["status"] != "APPROVED":
        raise err("ERR_STIP_NOT_APPROVED", "The owning STIP is not APPROVED")
    if determination == "INELIGIBLE":
        project["status"] = "INELIGIBLE"
        touch(project)
        return success_object(serialize_project(project))
    program = STORE["funding_programs"][project["funding_program_id"]]
    if project["activity_code"] not in program["eligible_activity_codes"]:
        raise err(
            "ERR_INELIGIBLE_ACTIVITY",
            "activity_code is not in the funding program's eligible set",
        )
    project["_determined_share_dec"] = adjusted_full_share(program, project, stip)
    project["status"] = "ELIGIBLE"
    touch(project)
    return success_object(serialize_project(project))
