"""StateProgram (STIP) lifecycle and PublicComment endpoints (PRD §3.2)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from calculations import (
    MIN_PUBLIC_COMMENTS,
    STIP_COMMENT_PERIOD_DAYS,
    STIP_DURATION_YEARS,
    fiscal_constraint_ok,
)
from db import STORE, clock, new_id, now_bookkeeping, touch
from errors import err
from helpers import (
    as_enum,
    as_int,
    as_number,
    as_str,
    get_body,
    paginate,
    req_field,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from serializers import serialize_comment, serialize_stip

bp = Blueprint("stips", __name__)


def _resolve_stip(sid):
    stip = STORE["stips"].get(sid)
    if stip is None:
        raise err("ERR_NOT_FOUND", "STIP not found")
    return stip


def _reopen_for_amendment(stip):
    """APPROVED -> PUBLIC_INVOLVEMENT: fresh comment window, amendment_count + 1."""
    stip["status"] = "PUBLIC_INVOLVEMENT"
    stip["comment_period_opened_at"] = clock.raw
    stip["_opened_dt"] = clock.dt
    stip["amendment_count"] += 1
    touch(stip)


@bp.route("/federal-aid/stips", methods=["POST"])
@require_roles("StateDOTPlanner")
def create_stip(user_id, user_role):
    body = get_body()
    state_code = as_str(req_field(body, "state_code"), "state_code")
    land = as_number(req_field(body, "state_federal_land_pct"), "state_federal_land_pct")
    land_dec = Decimal(str(land))
    if land_dec < 0 or land_dec > 1:
        raise err(
            "ERR_INVALID_REQUEST",
            "state_federal_land_pct must be between 0 and 1 inclusive",
        )
    start_ffy = as_int(
        req_field(body, "start_federal_fiscal_year"), "start_federal_fiscal_year"
    )
    description = as_str(req_field(body, "description"), "description")
    end_ffy = start_ffy + STIP_DURATION_YEARS - 1
    # Closed-interval coverage windows for the same state_code may not
    # intersect; a shared boundary fiscal year IS an overlap.
    for s in STORE["stips"].values():
        if s["state_code"] != state_code:
            continue
        if start_ffy <= s["end_federal_fiscal_year"] and s["start_federal_fiscal_year"] <= end_ffy:
            raise err(
                "ERR_STIP_PERIOD_OVERLAP",
                "STIP coverage window intersects an existing STIP for this state",
            )
    now = now_bookkeeping()
    rec = {
        "id": new_id(),
        "state_code": state_code,
        "state_federal_land_pct": land,
        "start_federal_fiscal_year": start_ffy,
        "end_federal_fiscal_year": end_ffy,
        "description": description,
        "status": "PUBLIC_INVOLVEMENT",
        "comment_period_opened_at": clock.raw,
        "_opened_dt": clock.dt,
        "amendment_count": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE["stips"][rec["id"]] = rec
    return success_object(serialize_stip(rec), status=201)


@bp.route("/federal-aid/stips/<sid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_stip(sid, user_id, user_role):
    return success_object(serialize_stip(_resolve_stip(sid)))


@bp.route("/federal-aid/stips/<sid>/submit", methods=["POST"])
@require_roles("StateDOTPlanner")
def submit_stip(sid, user_id, user_role):
    stip = _resolve_stip(sid)
    get_body()  # tolerate an optional empty body
    if stip["status"] != "PUBLIC_INVOLVEMENT":
        raise err("ERR_INVALID_STATE", "STIP is not in PUBLIC_INVOLVEMENT")
    # Priority 15 (participation) outranks priority 16 (window): a too-early
    # submission with too few comments reports ERR_PUBLIC_INVOLVEMENT_INCOMPLETE.
    comment_count = sum(
        1
        for c in STORE["comments"].values()
        if c["stip_id"] == sid and c["_created_dt"] >= stip["_opened_dt"]
    )
    if comment_count < MIN_PUBLIC_COMMENTS:
        raise err(
            "ERR_PUBLIC_INVOLVEMENT_INCOMPLETE",
            "No public comment recorded in the current comment window",
        )
    if clock.dt < stip["_opened_dt"] + timedelta(days=STIP_COMMENT_PERIOD_DAYS):
        raise err(
            "ERR_COMMENT_PERIOD_OPEN",
            "The 30-day public comment window has not elapsed",
        )
    stip["status"] = "SUBMITTED"
    touch(stip)
    return success_object(serialize_stip(stip))


@bp.route("/federal-aid/stips/<sid>/decide", methods=["POST"])
@require_roles("FHWADivisionAdmin")
def decide_stip(sid, user_id, user_role):
    stip = _resolve_stip(sid)
    body = get_body()
    decision = as_enum(req_field(body, "decision"), "decision", ("APPROVE", "REJECT"))
    if stip["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "STIP is not in SUBMITTED")
    if decision == "REJECT":
        # Window is NOT reset and comments are preserved; amendment_count is
        # not incremented on the reject path.
        stip["status"] = "PUBLIC_INVOLVEMENT"
        touch(stip)
        return success_object(serialize_stip(stip))
    # APPROVE: forward-looking fiscal constraint, per program, equality passes.
    if not fiscal_constraint_ok(
        stip, list(STORE["projects"].values()), list(STORE["apportionments"].values())
    ):
        raise err(
            "ERR_FISCAL_CONSTRAINT_VIOLATED",
            "Programmed federal estimates exceed the program's remaining capacity",
        )
    stip["status"] = "APPROVED"
    touch(stip)
    return success_object(serialize_stip(stip))


@bp.route("/federal-aid/stips/<sid>/open-amendment", methods=["POST"])
@require_roles("StateDOTPlanner")
def open_amendment(sid, user_id, user_role):
    stip = _resolve_stip(sid)
    get_body()
    if stip["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "STIP is not in APPROVED")
    _reopen_for_amendment(stip)
    return success_object(serialize_stip(stip))


@bp.route("/federal-aid/stips/<sid>/comments", methods=["POST"])
@require_roles(*ALL_ROLES)
def create_comment(sid, user_id, user_role):
    stip = _resolve_stip(sid)
    body = get_body()
    author_name = as_str(req_field(body, "author_name"), "author_name")
    comment_text = as_str(req_field(body, "comment_text"), "comment_text")
    if stip["status"] != "PUBLIC_INVOLVEMENT":
        raise err(
            "ERR_INVALID_STATE",
            "Comments are only accepted while the STIP is in PUBLIC_INVOLVEMENT",
        )
    rec = {
        "id": new_id(),
        "stip_id": sid,
        "author_name": author_name,
        "comment_text": comment_text,
        "created_at": now_bookkeeping(),
        "_created_dt": clock.dt,
    }
    STORE["comments"][rec["id"]] = rec
    return success_object(serialize_comment(rec), status=201)


@bp.route("/federal-aid/stips/<sid>/comments", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_comments(sid, user_id, user_role):
    _resolve_stip(sid)
    items = [c for c in STORE["comments"].values() if c["stip_id"] == sid]
    items.sort(key=lambda c: c["created_at"])  # stable sort, created_at asc
    page, total, limit, offset = paginate(items)
    return success_list([serialize_comment(c) for c in page], total, limit, offset)
