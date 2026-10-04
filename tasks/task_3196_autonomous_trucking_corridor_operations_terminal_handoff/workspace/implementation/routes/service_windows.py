"""Terminal service windows and apron geometry — PRD §2.7, §3.9,
endpoints 90-95.

Approving a requested window has four conditions; the apron geometry is the
half-open interval with the adjacency rule that touching windows do not occupy.
"""

from decimal import Decimal

import db
import core
import services
import calculations as calc
from core import ApiError, D, now_iso
from response import ok, page_of
from http_util import pagination, must_get, must_resolve, get_or_none, body, coerce_int, arg
from routes._common import route
from models import create

SERVICE_TYPES = ("HANDOFF_INBOUND", "HANDOFF_OUTBOUND", "YARD_TRANSFER",
                 "MAINTENANCE_STAGING")


def register(app):

    @route(app, "/api/terminals/<tid>/service-windows", ["POST"], ["TerminalManager"])
    def create_window(tid):
        terminal = must_get("Terminal", tid)
        raw = body()
        allowed = {"run_plan_id", "service_type", "window_start_minute",
                   "window_end_minute", "handoff_duration_minutes",
                   "buffer_minutes", "yield_to_transit"}
        for key in raw:
            if key not in allowed:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        for key in ("run_plan_id", "service_type", "window_start_minute",
                    "window_end_minute"):
            if key not in raw:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Required field '%s' is missing." % key)
        if raw["service_type"] not in SERVICE_TYPES:
            raise ApiError("ERR_INVALID_REQUEST", "Unknown service_type.")
        run = get_or_none("RunPlan", raw["run_plan_id"])
        if run is None:
            raise ApiError("ERR_RUN_PLAN_NOT_FOUND")
        start = coerce_int(raw["window_start_minute"])
        end = coerce_int(raw["window_end_minute"])
        if not start < end:
            raise ApiError("ERR_INVALID_REQUEST",
                           "window_start_minute must be strictly less than window_end_minute.")
        row = create("TerminalServiceWindow", {
            "terminal_id": terminal["id"],
            "run_plan_id": run["id"],
            "service_type": raw["service_type"],
            "window_start_minute": start,
            "window_end_minute": end,
            "handoff_duration_minutes": int(raw.get("handoff_duration_minutes", 0) or 0),
            "buffer_minutes": int(raw.get("buffer_minutes", 0) or 0),
            "yield_to_transit": bool(raw.get("yield_to_transit", False)),
        })
        row["window_status"] = "REQUESTED"
        services.mark(row, "buffer_seconds",
                      calc.buffer_seconds(row["service_type"],
                                          calc.window_length_minutes(row)))
        services.flush(row)
        return ok(row, 201)

    @route(app, "/api/terminals/<tid>/service-windows", ["GET"], ["Any"])
    def list_windows(tid):
        must_get("Terminal", tid)
        limit, offset = pagination()
        return page_of(db.sort_created(db.by("terminal_service_windows", "terminal_id", tid)),
                       limit, offset)

    @route(app, "/api/terminals/<tid>/service-windows/<wid>", ["GET"], ["Any"])
    def get_window(tid, wid):
        must_get("Terminal", tid)
        window = db.get("terminal_service_windows", wid)
        if window is None or window.get("terminal_id") != tid:
            raise ApiError("ERR_REFERENCE_NOT_FOUND")
        return ok(window)

    @route(app, "/api/terminal-service-windows/<rid>/approve", ["POST"], ["TerminalManager"])
    def approve_window(rid):
        """§3.9: four conditions — the run must be DISPATCH_READY or IN_TRANSIT,
        the minute range must be well formed, occupancy must not exceed capacity,
        and the occupation must not share a single minute with an approved block."""
        window = must_get("TerminalServiceWindow", rid)
        raw = body()
        for key in raw:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field '%s' is not declared for this endpoint." % key)
        if window.get("window_status") != "REQUESTED":
            raise ApiError("ERR_INVALID_STATE", "Only a requested window can be approved.")
        run = db.get("run_plans", window.get("run_plan_id"))
        if run is None:
            raise ApiError("ERR_RUN_PLAN_NOT_FOUND")
        if run.get("run_status") not in ("DISPATCH_READY", "IN_TRANSIT"):
            raise ApiError("ERR_INVALID_STATE",
                           "The referenced run is not DISPATCH_READY or IN_TRANSIT.")
        start = int(window.get("window_start_minute") or 0)
        end = int(window.get("window_end_minute") or 0)
        if not start < end:
            raise ApiError("ERR_INVALID_STATE", "The window minute range is not well formed.")
        terminal = db.get("terminals", window.get("terminal_id"))
        if terminal is None:
            raise ApiError("ERR_TERMINAL_NOT_FOUND")

        # Priority 22 (apron collision) is evaluated before the capacity ceiling
        # so that a colliding block is reported as ERR_APRON_OVERLAP.
        buffered_end = end + int(window.get("buffer_minutes") or 0)
        if calc.apron_overlaps(terminal["id"], start, buffered_end, exclude_id=window["id"]):
            raise ApiError("ERR_APRON_OVERLAP",
                           "The window shares a minute with an approved block.")
        length_hours = calc.rhu(Decimal(calc.window_length_minutes(window)) / Decimal(60), 2)
        projected = D(terminal.get("reserved_apron_units", 0)) + length_hours
        if projected > D(terminal.get("apron_capacity", 0)):
            raise ApiError("ERR_APRON_CAPACITY_EXCEEDED",
                           "The approval would push apron occupancy past capacity.")

        services.mark(window, "window_status", "APPROVED")
        services.flush(window)
        services.recompute_terminal(terminal)
        services.flush(terminal)
        return ok(window)

    @route(app, "/api/terminal-service-windows/<rid>/cancel", ["POST"], ["TerminalManager"])
    def cancel_window(rid):
        """§3.9: a cancelled window must have been APPROVED to begin with."""
        window = must_get("TerminalServiceWindow", rid)
        raw = body()
        for key in raw:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field '%s' is not declared for this endpoint." % key)
        if window.get("window_status") != "APPROVED":
            raise ApiError("ERR_INVALID_STATE", "Only an approved window can be cancelled.")
        services.mark(window, "window_status", "CANCELLED")
        services.flush(window)
        services.recompute_terminal_for_window(window)
        return ok(window)

    @route(app, "/api/terminal-service-windows/<rid>/complete-handoff", ["POST"],
           ["TerminalManager"])
    def complete_handoff(rid):
        """§3.9: the window may complete from IN_SERVICE, provided the referenced
        run is IN_TRANSIT or is READINESS_PENDING after a safe stop."""
        window = must_get("TerminalServiceWindow", rid)
        raw = body()
        for key in raw:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field '%s' is not declared for this endpoint." % key)
        if window.get("window_status") != "IN_SERVICE":
            raise ApiError("ERR_INVALID_STATE", "Only an IN_SERVICE window can complete.")
        run = db.get("run_plans", window.get("run_plan_id"))
        if run is None:
            raise ApiError("ERR_RUN_PLAN_NOT_FOUND")
        if run.get("run_status") not in ("IN_TRANSIT", "READINESS_PENDING"):
            raise ApiError("ERR_INVALID_STATE",
                           "The referenced run is not on the highway segment.")
        services.mark(window, "window_status", "COMPLETED")
        services.flush(window)
        services.recompute_terminal_for_window(window)
        return ok(window)