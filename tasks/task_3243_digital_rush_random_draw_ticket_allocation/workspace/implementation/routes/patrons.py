"""Patrons: registration, reading, standing and draw reinstatement."""

from flask import Blueprint

from clock import CLOCK
from db import DB
from errors import ApiError
from lookup import market_by_code
from response import ok, public
from routes import actor, payload
from services import calc, engine

bp = Blueprint("patrons", __name__)


@bp.post("/patrons/registrations")
def register_patron():
    """The only operation requiring no identity headers at all."""
    body = payload()
    email = body.get("email")
    if email is None or not str(email).strip():
        raise ApiError("ERR_INVALID_STATE")
    folded = str(email).strip().casefold()
    for existing in DB.all("patron"):
        if str(existing.get("email") or "").casefold() == folded:
            raise ApiError("ERR_INVALID_STATE")
    market = market_by_code(body.get("market_code"))
    patron = {
        "email": email,
        "display_name": body.get("display_name"),
        "market_code": market["market_code"],
        "draw_violation_count": 0,
        "status": "ACTIVE",
    }
    DB.insert("patron", patron)
    return ok(public(patron), 201)


@bp.get("/patrons/<patron_id>")
def read_patron(patron_id):
    actor(["Patron", "CustomerService", "PlatformAdmin"])
    patron = DB.get("patron", patron_id)
    if patron is None:
        raise ApiError("ERR_PATRON_NOT_FOUND")
    return ok(public(patron))


@bp.post("/patrons/<patron_id>/status-transitions")
def patron_transition(patron_id):
    actor(["CustomerService", "PlatformAdmin"])
    body = payload()
    patron = DB.get("patron", patron_id)
    if patron is None:
        raise ApiError("ERR_PATRON_NOT_FOUND")
    from guards_helpers import require_occ

    require_occ(body, "expected_patron_version", patron)
    to_status = body.get("to_status")
    if to_status == "BLOCKED" and patron["status"] == "ACTIVE":
        # PRD §3.8: the running figure is recomputed from the patron's entry
        # states, so a win whose claim deadline has already been reached counts
        # as a recorded violation even before the sweep forfeits it.
        patron["draw_violation_count"] = calc.redemption_lifecycle_cost(patron_id)
        if int(patron.get("draw_violation_count") or 0) < 1:
            raise ApiError("ERR_INVALID_STATE")
        patron["status"] = "BLOCKED"
        for position in DB.all("queue_position"):
            if position["patron_id"] != patron_id:
                continue
            if position["status"] in ("WAITING", "ADMITTED"):
                position["status"] = "ABANDONED"
                DB.touch("queue_position", position)
        engine.cancel_entries_for_patron(patron_id)
    elif to_status == "ACTIVE" and patron["status"] == "BLOCKED":
        patron["status"] = "ACTIVE"
    else:
        raise ApiError("ERR_INVALID_STATE")
    return ok(public(DB.touch("patron", patron)))


@bp.post("/patrons/<patron_id>/draw-reinstatements")
def reinstate_draw(patron_id):
    """Reinstate one forfeited win, once, and restart the claim window."""
    actor(["CustomerService"])
    body = payload()
    patron = DB.get("patron", patron_id)
    if patron is None:
        raise ApiError("ERR_PATRON_NOT_FOUND")
    entry_id = body.get("draw_entry_id")
    entry = DB.get("draw_entry", entry_id)
    if entry is None:
        raise ApiError("ERR_DRAW_ENTRY_NOT_FOUND")
    if entry["patron_id"] != patron_id:
        raise ApiError("ERR_DRAW_ENTRY_NOT_FOUND")

    expected = body.get("expected_draw_entry_version")
    if expected is not None and str(expected) != str(entry.get("version")):
        raise ApiError("ERR_STALE_VERSION")
    if entry["status"] != "FORFEITED":
        raise ApiError("ERR_INVALID_STATE")
    if int(entry.get("reinstatement_count") or 0) >= 1:
        raise ApiError("ERR_INVALID_STATE")
    if patron["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")

    allocation = DB.get("allocation", entry["allocation_id"])
    window = int(allocation.get("claim_window_minutes") or 0) if allocation else 0
    entry["status"] = "WINNER"
    entry["notified_at"] = CLOCK.stamp()
    entry["claim_deadline_at"] = CLOCK.plus_minutes(window)
    entry["reinstatement_count"] = int(entry.get("reinstatement_count") or 0) + 1
    DB.touch("draw_entry", entry)

    patron["draw_violation_count"] = calc.redemption_lifecycle_cost(patron_id)
    DB.touch("patron", patron)
    return ok(public(entry))