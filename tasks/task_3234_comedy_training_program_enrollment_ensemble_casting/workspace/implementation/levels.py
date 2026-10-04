"""CurriculumLevel routes."""
from flask import Blueprint
from store import store, fresh, stamp
from middleware import auth, json_body, require_fields, pagination_params
from response import success_obj, success_list
from errors import not_found, invalid_request
from services import check_cycle

bp = Blueprint("levels", __name__)

ROLES_READ = ["ProgramDirector", "PlacementOfficer", "Registrar", "CastingDirector", "Student", "FinanceOfficer"]
TRACKS = {"IMPROV", "SKETCH", "STANDUP", "CONSERVATORY"}


@bp.post("/curriculum-levels")
def create_level():
    auth(["ProgramDirector"])
    body = json_body()
    require_fields(body, ["code", "title", "sequence_index"])
    if not isinstance(body.get("code"), str) or not body["code"]:
        invalid_request("code must be a non-empty string")
    track = body.get("track", "IMPROV")
    if track not in TRACKS:
        invalid_request("invalid track")
    if not isinstance(body.get("sequence_index"), int) or isinstance(body.get("sequence_index"), bool):
        invalid_request("sequence_index must be an integer")
    requires = body.get("requires_level_code")
    if requires is not None and not isinstance(requires, str):
        invalid_request("requires_level_code must be a string or null")
    level = fresh({
        "code": body["code"],
        "title": body["title"],
        "track": track,
        "sequence_index": body["sequence_index"],
        "requires_level_code": requires,
        "allows_placement_bypass": bool(body.get("allows_placement_bypass", False)),
        "showcase_required": bool(body.get("showcase_required", False)),
        "status": "ACTIVE",
    })
    store.levels[level["id"]] = level
    check_cycle(level["id"], requires)
    return success_obj(level, 201)


@bp.get("/curriculum-levels")
def list_levels():
    auth(ROLES_READ)
    limit, offset = pagination_params()
    items = list(store.levels.values())
    track = None
    from flask import request
    track = request.args.get("track")
    if track:
        items = [x for x in items if x["track"] == track]
    req = request.args.get("requires_level_code")
    if req is not None:
        items = [x for x in items if x.get("requires_level_code") == req]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.get("/curriculum-levels/<levelId>")
def get_level(levelId):
    auth(ROLES_READ)
    level = store.levels.get(levelId)
    if not level:
        not_found("curriculum level not found")
    return success_obj(level)
