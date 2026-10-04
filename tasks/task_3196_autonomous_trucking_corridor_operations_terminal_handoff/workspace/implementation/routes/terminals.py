"""Terminals — PRD §3.1 (commissioning), §3.9 and endpoints 7-10, 90-92, 153-157."""

import db
import services
from core import ApiError
from response import ok, page_of
from http_util import bind, pagination, must_get, body, coerce_int
from routes._common import route
from models import create

PUBLIC = ["terminal_code", "terminal_name", "state_code", "apron_capacity"]


def register(app):

    @route(app, "/api/terminals", ["POST"], ["TerminalManager"])
    def create_terminal():
        payload = bind("Terminal", PUBLIC)
        payload = _validate(payload)
        row = create("Terminal", payload)
        services.recompute_terminal(row)
        services.flush(row)
        return ok(row, 201)

    @route(app, "/api/terminals", ["GET"], ["Any"])
    def list_terminals():
        limit, offset = pagination()
        return page_of(db.sort_created(db.all_rows("terminals")), limit, offset)

    @route(app, "/api/terminals/<rid>", ["GET"], ["Any"])
    def get_terminal(rid):
        return ok(must_get("Terminal", rid))

    @route(app, "/api/terminals/<rid>/operate", ["POST"], ["TerminalManager"])
    def operate_terminal(rid):
        """§3.1: moving the hub into service transitions terminal_state to
        OPERATIONAL, the state the launch gate demands of both of a corridor's
        terminals."""
        row = must_get("Terminal", rid)
        if row.get("terminal_state") not in ("COMMISSIONING", "DEGRADED"):
            raise ApiError("ERR_INVALID_STATE",
                           "The terminal cannot be moved into service from its current state.")
        row["terminal_state"] = "OPERATIONAL"
        services.recompute_terminal(row)
        services.flush(row)
        return ok(row)

    @route(app, "/api/terminals/<rid>/corridors", ["GET"], ["Any"])
    def terminal_corridors(rid):
        must_get("Terminal", rid)
        limit, offset = pagination()
        rows = [c for c in db.all_rows("corridors")
                if c.get("origin_terminal_id") == rid or c.get("destination_terminal_id") == rid]
        return page_of(db.sort_created(rows), limit, offset)

    @route(app, "/api/terminals/<rid>/driver-prospects", ["GET"], ["Any"])
    def terminal_prospects(rid):
        must_get("Terminal", rid)
        limit, offset = pagination()
        return page_of(db.sort_created(db.by("driver_prospects", "home_terminal_id", rid)),
                       limit, offset)

    @route(app, "/api/terminals/<rid>/run-plans", ["GET"], ["Any"])
    def terminal_run_plans(rid):
        must_get("Terminal", rid)
        limit, offset = pagination()
        rows = [r for r in db.all_rows("run_plans")
                if r.get("origin_terminal_id") == rid or r.get("destination_terminal_id") == rid]
        return page_of(db.sort_created(rows), limit, offset)

    @route(app, "/api/terminals/<rid>/fleet-units", ["GET"], ["Any"])
    def terminal_fleet_units(rid):
        must_get("Terminal", rid)
        limit, offset = pagination()
        return page_of(db.sort_created(db.by("fleet_units", "home_terminal_id", rid)),
                       limit, offset)

    @route(app, "/api/terminals/<rid>/security-records", ["GET"], ["Any"])
    def terminal_security_records(rid):
        must_get("Terminal", rid)
        limit, offset = pagination()
        return page_of(db.sort_created(db.by("security_records", "origin_terminal_id", rid)),
                       limit, offset)

    @route(app, "/api/terminals/<rid>/driver-transitions", ["GET"], ["Any"])
    def terminal_transitions(rid):
        must_get("Terminal", rid)
        limit, offset = pagination()
        return page_of(db.sort_created(db.by("driver_transitions", "terminal_id", rid)),
                       limit, offset)


def _validate(payload):
    payload["apron_capacity"] = coerce_int(payload.get("apron_capacity"))
    for key in ("terminal_code", "terminal_name", "state_code"):
        if not isinstance(payload.get(key), str) or not str(payload.get(key)).strip():
            raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string." % key)
    return payload