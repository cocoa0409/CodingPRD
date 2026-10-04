"""WishTeam create (with OCC + supersede) and reads."""

from flask import Blueprint, request

from auth import require_roles
from cascade import disband_active_team
from db import STORE, new_entity, touch
from errors import ApiError
from resp import ok, created, list_resp
from serialize import ser_team
from util import body_json, req_str, req_int, pagination, paginate

bp = Blueprint("teams", __name__)


@bp.post("/wish-grant/wish-teams")
@require_roles("WishCoordinator")
def create_team():
    body = body_json()
    wish_id = req_str(body, "wish_id")
    lead_id = req_str(body, "lead_volunteer_id")
    second_id = req_str(body, "second_volunteer_id")
    expected = req_int(body, "expected_wish_version")

    wish = STORE["wishes"].get(wish_id)
    if wish is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Wish not found")
    lead = STORE["volunteers"].get(lead_id)
    if lead is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Lead volunteer not found")
    second = STORE["volunteers"].get(second_id)
    if second is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Second volunteer not found")

    if wish["status"] not in ("CREATED", "DETERMINATION_PENDING"):
        raise ApiError(
            "ERR_INVALID_WISH_STATE", 409,
            "Wish %s does not accept team creation" % wish["status"],
        )
    if expected != wish["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", 412,
            "expected_wish_version does not match the wish version",
        )
    if lead_id == second_id:
        raise ApiError(
            "ERR_TEAM_DUPLICATE_MEMBER", 422,
            "lead_volunteer_id and second_volunteer_id must differ",
        )
    if lead["status"] != "ACTIVE" or second["status"] != "ACTIVE":
        raise ApiError(
            "ERR_VOLUNTEER_NOT_ACTIVE", 409,
            "Both team volunteers must be ACTIVE",
        )
    if (
        lead["chapter_id"] != wish["chapter_id"]
        or second["chapter_id"] != wish["chapter_id"]
    ):
        raise ApiError(
            "ERR_TEAM_CHAPTER_MISMATCH", 422,
            "Both volunteers must belong to the wish's chapter",
        )

    if wish["status"] == "DETERMINATION_PENDING":
        disband_active_team(wish["id"])

    team = new_entity(
        wish_id=wish["id"],
        lead_volunteer_id=lead_id,
        second_volunteer_id=second_id,
        status="ACTIVE",
    )
    STORE["teams"][team["id"]] = team
    wish["status"] = "DETERMINATION_PENDING"
    touch(wish)
    return created(ser_team(team))


@bp.get("/wish-grant/wish-teams")
@require_roles("WishCoordinator", "ChapterDirector", "Volunteer")
def list_teams():
    limit, offset = pagination()
    items = sorted(STORE["teams"].values(), key=lambda e: e["created_at"])
    wish_id = request.args.get("wish_id")
    lead_id = request.args.get("lead_volunteer_id")
    second_id = request.args.get("second_volunteer_id")
    status = request.args.get("status")
    if wish_id is not None:
        items = [t for t in items if t["wish_id"] == wish_id]
    if lead_id is not None:
        items = [t for t in items if t["lead_volunteer_id"] == lead_id]
    if second_id is not None:
        items = [t for t in items if t["second_volunteer_id"] == second_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, total, has_more = paginate(items, limit, offset)
    return list_resp([ser_team(t) for t in page], total, limit, offset, has_more)


@bp.get("/wish-grant/wish-teams/<tid>")
@require_roles("WishCoordinator", "ChapterDirector", "Volunteer")
def get_team(tid):
    t = STORE["teams"].get(tid)
    if t is None:
        raise ApiError("ERR_NOT_FOUND", 404, "WishTeam not found")
    return ok(ser_team(t))
