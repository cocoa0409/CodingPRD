"""DisplayReset endpoints (PRD 3.7)."""
from flask import Blueprint, request

from auth import get_body, require_roles
from db import bump, store
from envelope import ok, paginate
from errors import api_error
from services import maybe_retire_line
from util import iso3, parse_dt

bp = Blueprint("resets", __name__)

READ_ROLES = ("FieldServiceRep", "ProgramManager", "PlatformAdmin")

RESET_ROLE_PINS = {
    "SCHEDULED": "FieldServiceRep",
    "COMPLETE": "FieldServiceRep",
    "WAIVED": "ProgramManager",
}

RESET_EDGES = {
    "PLANNED": {"SCHEDULED", "COMPLETE", "WAIVED"},
    "SCHEDULED": {"COMPLETE", "WAIVED"},
}


def serialize(reset):
    return dict(reset)


@bp.route("/cabinet/display-resets/<reset_id>", methods=["GET"])
def get_reset(reset_id):
    require_roles(*READ_ROLES)
    reset = store.resets.get(reset_id)
    if reset is None:
        raise api_error("ERR_NOT_FOUND", "display reset not found")
    return ok(serialize(reset))


@bp.route("/cabinet/display-resets", methods=["GET"])
def list_resets():
    require_roles(*READ_ROLES)
    program_id = request.args.get("program_id")
    line_id = request.args.get("line_id")
    store_code = request.args.get("store_code")
    status = request.args.get("status")
    items = [r for r in store.resets.values()
             if (program_id is None or r["program_id"] == program_id)
             and (line_id is None or r["line_id"] == line_id)
             and (store_code is None or r["store_code"] == store_code)
             and (status is None or r["status"] == status)]
    items = sorted(items, key=lambda r: r["created_at"])
    page, meta = paginate([serialize(r) for r in items])
    return ok(page, 200, meta)


@bp.route("/cabinet/display-resets/<reset_id>/transition", methods=["POST"])
def transition_reset(reset_id):
    _, role = require_roles("FieldServiceRep", "ProgramManager")
    reset = store.resets.get(reset_id)
    if reset is None:
        raise api_error("ERR_NOT_FOUND", "display reset not found")
    body = get_body()
    to_status = body.get("to_status")
    if to_status is None:
        raise api_error("ERR_INVALID_REQUEST", "to_status is required")
    if to_status in RESET_ROLE_PINS and role != RESET_ROLE_PINS[to_status]:
        raise api_error("ERR_FORBIDDEN",
                        "role {} may not drive the {} transition".format(role, to_status))
    current = reset["status"]
    if to_status not in RESET_EDGES.get(current, set()):
        raise api_error("ERR_INVALID_STATE",
                        "cannot move display reset from {} to {}".format(current, to_status))

    if to_status == "SCHEDULED":
        scheduled_date = body.get("scheduled_date")
        if scheduled_date is None:
            raise api_error("ERR_INVALID_REQUEST",
                            "scheduled_date is required when scheduling a reset")
        if parse_dt(scheduled_date) is None:
            raise api_error("ERR_INVALID_REQUEST",
                            "scheduled_date must be an ISO 8601 datetime")
        reset["scheduled_date"] = scheduled_date
    elif to_status == "COMPLETE":
        reset["completed_at"] = iso3(store.clock)
        program = store.programs[reset["program_id"]]
        deadline = program.get("display_reset_deadline")
        reset["completed_late"] = bool(deadline) and store.clock > parse_dt(deadline)

    reset["status"] = to_status
    bump(reset)
    if to_status in ("COMPLETE", "WAIVED"):
        # Terminal resets may earn the sunsetting line its retirement (PRD 3.7).
        line = store.lines.get(reset["line_id"])
        if line is not None:
            maybe_retire_line(line)
    return ok(serialize(reset))
