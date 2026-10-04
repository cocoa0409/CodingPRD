"""Season windows: nested + flat endpoints, suspend/close transitions."""

from flask import Blueprint, request

import db
from common import (
    new_entity,
    get_or_404,
    body,
    require_field,
    require_date,
    touch,
    parse_date,
)
from errors import ApiError
from middleware import require_role, require_any_authenticated
from response import ok, paginate
from routes.routes import _get_route_or_404, _suspend_window

bp = Blueprint("season_windows", __name__)


def _get_window_or_404(window_id):
    return get_or_404(
        db.season_windows, window_id, "ERR_WINDOW_NOT_FOUND", "SeasonWindow"
    )


@bp.route("/routes/<route_id>/season-windows", methods=["POST"])
def create_window(route_id):
    require_role("NetworkPlanner")
    route = _get_route_or_404(route_id)
    data = body()
    label = require_field(data, "season_label", str)
    start = require_date(data, "window_start_date")
    end = require_date(data, "window_end_date")
    if parse_date(end) < parse_date(start):
        raise ApiError(
            "ERR_VALIDATION",
            "window_end_date must be on or after window_start_date",
            422,
        )
    ent = new_entity(
        {
            "route_id": route_id,
            "season_label": label,
            "window_start_date": start,
            "window_end_date": end,
            "window_status": "OPEN",
            "suspension_reason": data.get("suspension_reason"),
        }
    )
    db.season_windows[ent["id"]] = ent
    return ok(ent, 201)


@bp.route("/routes/<route_id>/season-windows", methods=["GET"])
def list_windows_for_route(route_id):
    require_any_authenticated()
    _get_route_or_404(route_id)
    items = [w for w in db.season_windows.values() if w["route_id"] == route_id]
    status = request.args.get("window_status")
    if status:
        items = [w for w in items if w["window_status"] == status]
    items.sort(key=lambda w: (w["created_at"], w["id"]))
    page, meta = paginate(items)
    return ok(page, 200, pagination=meta)


@bp.route("/routes/<route_id>/season-windows/<window_id>", methods=["GET"])
def get_window_nested(route_id, window_id):
    require_any_authenticated()
    _get_route_or_404(route_id)
    window = _get_window_or_404(window_id)
    if window["route_id"] != route_id:
        raise ApiError("ERR_WINDOW_NOT_FOUND", "SeasonWindow id does not exist", 404)
    return ok(window)


@bp.route("/routes/<route_id>/season-windows/<window_id>/suspend", methods=["POST"])
def suspend_window(route_id, window_id):
    require_role("NetworkPlanner")
    _get_route_or_404(route_id)
    window = _get_window_or_404(window_id)
    if window["route_id"] != route_id:
        raise ApiError("ERR_WINDOW_NOT_FOUND", "SeasonWindow id does not exist", 404)
    if window["window_status"] != "OPEN":
        raise ApiError(
            "ERR_WINDOW_NOT_OPEN", "Operation requires OPEN window", 409
        )
    data = body()
    reason = data.get("suspension_reason")
    _suspend_window(window, reason)
    return ok(window)


@bp.route("/routes/<route_id>/season-windows/<window_id>/close", methods=["POST"])
def close_window(route_id, window_id):
    require_role("NetworkPlanner")
    _get_route_or_404(route_id)
    window = _get_window_or_404(window_id)
    if window["route_id"] != route_id:
        raise ApiError("ERR_WINDOW_NOT_FOUND", "SeasonWindow id does not exist", 404)
    if window["window_status"] == "CLOSED":
        raise ApiError(
            "ERR_WINDOW_NOT_SUSPENDED",
            "Operation requires SUSPENDED window",
            409,
        )
    if window["window_status"] not in ("OPEN", "SUSPENDED"):
        raise ApiError(
            "ERR_WINDOW_NOT_SUSPENDED",
            "Operation requires SUSPENDED window",
            409,
        )
    live_pubs = [
        p
        for p in db.schedule_publications.values()
        if p["season_window_id"] == window_id and p["publication_status"] == "PUBLISHED"
    ]
    if live_pubs:
        raise ApiError(
            "ERR_PUBLICATIONS_STILL_LIVE",
            "Window close blocked: PUBLISHED publications remain",
            409,
        )
    window["window_status"] = "CLOSED"
    touch(window)
    return ok(window)


@bp.route("/season-windows", methods=["GET"])
def list_windows_flat():
    require_any_authenticated()
    items = list(db.season_windows.values())
    rid = request.args.get("route_id")
    if rid:
        items = [w for w in items if w["route_id"] == rid]
    status = request.args.get("window_status")
    if status:
        items = [w for w in items if w["window_status"] == status]
    items.sort(key=lambda w: (w["created_at"], w["id"]))
    page, meta = paginate(items)
    return ok(page, 200, pagination=meta)


@bp.route("/season-windows/<window_id>", methods=["GET"])
def get_window_flat(window_id):
    require_any_authenticated()
    window = _get_window_or_404(window_id)
    return ok(window)
