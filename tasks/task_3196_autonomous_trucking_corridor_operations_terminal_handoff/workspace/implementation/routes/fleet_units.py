"""Fleet units, operational hours and carrier settlement — PRD §3.11,
endpoints 130-135.
"""

from decimal import Decimal

import db
import core
import services
import calculations as calc
from core import ApiError, D, now_iso, parse_iso, to_iso
from response import ok, page_of
from http_util import pagination, must_get, get_or_none, body, coerce_int, arg
from routes._common import route
from models import create


def register(app):

    @route(app, "/api/fleet-units", ["POST"], ["FleetMaintenanceTech"])
    def create_unit():
        """§3.11: registration leaves the unit ACTIVE with maint_charges of 0 and
        remain_hours equal to weather_clearance_hours."""
        raw = body()
        allowed = {"unit_id", "fleet_name", "home_terminal_id", "curated_at",
                   "inspection_anchor_at", "weather_clearance_hours", "is_watch_squad"}
        for key in raw:
            if key not in allowed:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        for key in ("unit_id", "fleet_name", "home_terminal_id", "curated_at",
                    "inspection_anchor_at", "weather_clearance_hours"):
            if key not in raw:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Required field '%s' is missing." % key)
        terminal = get_or_none("Terminal", raw["home_terminal_id"])
        if terminal is None:
            raise ApiError("ERR_REFERENCE_NOT_FOUND")
        _assert_unique_unit_id(raw["unit_id"])
        curated = parse_iso(raw["curated_at"])
        anchor = parse_iso(raw["inspection_anchor_at"])
        if curated is None or anchor is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "curated_at and inspection_anchor_at must be ISO 8601 UTC.")
        clearance = coerce_int(raw["weather_clearance_hours"])
        if clearance < 1:
            raise ApiError("ERR_INVALID_REQUEST",
                           "weather_clearance_hours must be at least 1.")
        row = create("FleetUnit", {
            "unit_id": raw["unit_id"],
            "fleet_name": raw["fleet_name"],
            "home_terminal_id": terminal["id"],
            "curated_at": to_iso(curated),
            "inspection_anchor_at": to_iso(anchor),
            "weather_clearance_hours": clearance,
            "is_watch_squad": bool(raw.get("is_watch_squad", False)),
        })
        row["unit_status"] = "ACTIVE"
        row["hours_posted_total"] = 0
        row["_weather_profile"] = _corridor_profile_for(terminal)
        services.mark(row, "maint_charges", 0)
        services.mark(row, "remain_hours", clearance)
        services.recompute_fleet_unit(row)
        services.flush(row)
        services.recompute_terminal(terminal)
        services.flush(terminal)
        return ok(row, 201)

    @route(app, "/api/fleet-units", ["GET"], ["Any"])
    def list_units():
        limit, offset = pagination()
        rows = db.all_rows("fleet_units")
        unit_id = arg("unit_id")
        if unit_id:
            rows = [u for u in rows if u.get("unit_id") == unit_id]
        return page_of(db.sort_created(rows), limit, offset)

    @route(app, "/api/fleet-units/<rid>", ["GET"], ["Any"])
    def get_unit(rid):
        return ok(must_get("FleetUnit", rid))

    @route(app, "/api/fleet-units/<rid>/post-operational-hours", ["POST"],
           ["FleetMaintenanceTech"])
    def post_hours(rid):
        """§3.11: the request must match the unit's current version or it is
        refused with ERR_STALE_VERSION at HTTP 412."""
        unit = must_get("FleetUnit", rid)
        raw = body()
        allowed = {"hours_logged", "expected_fleet_unit_version"}
        for key in raw:
            if key not in allowed:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        if "hours_logged" not in raw or "expected_fleet_unit_version" not in raw:
            raise ApiError("ERR_INVALID_REQUEST",
                           "hours_logged and expected_fleet_unit_version are required.")
        if raw["expected_fleet_unit_version"] is not None:
            if int(raw["expected_fleet_unit_version"]) != int(unit.get("version", 1)):
                raise ApiError("ERR_STALE_VERSION",
                               "The fleet unit version has advanced since it was read.")
        hours = coerce_int(raw["hours_logged"])
        unit["hours_posted_total"] = int(unit.get("hours_posted_total") or 0) + hours
        services.recompute_fleet_unit(unit)
        db.touch(unit, now_iso())
        return ok(unit)

    @route(app, "/api/fleet-units/<rid>/route-driven-operational-hours", ["POST"],
           ["FleetMaintenanceTech"])
    def route_driven_hours(rid):
        """§3.11: posting route-driven hours names a corridor_id and recomputes
        route_driven_hours_cents from that corridor's mileage, recording the
        double-shift reading for a watch-squad unit."""
        unit = must_get("FleetUnit", rid)
        raw = body()
        for key in raw:
            if key != "corridor_id":
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        if "corridor_id" not in raw:
            raise ApiError("ERR_INVALID_REQUEST", "corridor_id is required.")
        corridor = get_or_none("Corridor", raw["corridor_id"])
        if corridor is None:
            raise ApiError("ERR_CORRIDOR_NOT_FOUND")
        unit["_weather_profile"] = corridor.get("weather_profile")
        services.mark(unit, "route_driven_hours_cents",
                      calc.route_driven_hours_cents(unit.get("is_watch_squad")))
        services.recompute_fleet_unit(unit)
        db.touch(unit, now_iso())
        return ok(unit)

    @route(app, "/api/fleet-units/<rid>/clear-watch-squad", ["POST"],
           ["FleetMaintenanceTech"])
    def clear_watch_squad(rid):
        unit = must_get("FleetUnit", rid)
        raw = body()
        _reject_unknown(raw)
        services.mark(unit, "is_watch_squad", False)
        services.recompute_fleet_unit(unit)
        db.touch(unit, now_iso())
        return ok(unit)


def _reject_unknown(raw):
    for key in raw:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field '%s' is not declared for this endpoint." % key)


def _assert_unique_unit_id(unit_id):
    for u in db.all_rows("fleet_units"):
        if u.get("unit_id") == unit_id:
            raise ApiError("ERR_INVALID_REQUEST",
                           "The fleet unit identifier is already registered.")


def _corridor_profile_for(terminal):
    for c in db.all_rows("corridors"):
        if terminal["id"] in (c.get("origin_terminal_id"), c.get("destination_terminal_id")):
            return c.get("weather_profile")
    return None