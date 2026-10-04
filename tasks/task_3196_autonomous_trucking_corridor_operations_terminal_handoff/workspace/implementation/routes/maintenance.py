"""Autonomous hardware inspection programmes — PRD §3.7, endpoints 110-117, 158."""

from datetime import timedelta

import db
import core
import services
from core import ApiError, now_iso, parse_iso, to_iso
from response import ok, page_of
from http_util import pagination, must_get, must_resolve, get_or_none, body, coerce_int, arg
from routes._common import route
from models import create


def register(app):

    @route(app, "/api/maintenance-programs", ["POST"], ["FleetMaintenanceTech"])
    def create_program():
        """§3.7: 0 selects the default programme length of 3 days, 1 through 365 are
        accepted verbatim, and every value below 1 other than 0, or above 365, is
        refused with ERR_INVALID_INSPECTION_INTERVAL."""
        raw = body()
        allowed = {"program_name", "fleet_unit_id", "state_code",
                   "inspection_interval_days", "inspection_odometer_miles",
                   "inspection_anchor_at"}
        for key in raw:
            if key not in allowed:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        for key in ("program_name", "fleet_unit_id", "state_code",
                    "inspection_interval_days", "inspection_anchor_at"):
            if key not in raw:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Required field '%s' is missing." % key)
        unit = must_resolve("FleetUnit", raw["fleet_unit_id"])
        interval = coerce_int(raw["inspection_interval_days"],
                              "ERR_INVALID_INSPECTION_INTERVAL")
        if interval != 0 and not (1 <= interval <= 365):
            raise ApiError("ERR_INVALID_INSPECTION_INTERVAL",
                           "inspection_interval_days must be 0 or between 1 and 365.")
        anchor = parse_iso(raw["inspection_anchor_at"])
        if anchor is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "inspection_anchor_at must be ISO 8601 UTC.")
        odometer = coerce_int(raw.get("inspection_odometer_miles", 0) or 0)
        if odometer < 0:
            raise ApiError("ERR_INVALID_REQUEST",
                           "inspection_odometer_miles must be at least 0.")
        row = create("MaintenanceProgram", {
            "program_name": raw["program_name"],
            "fleet_unit_id": unit["id"],
            "state_code": raw["state_code"],
            "inspection_interval_days": interval,
            "inspection_odometer_miles": odometer,
            "_anchor_at": to_iso(anchor),
        })
        row["program_status"] = "DRAFT"
        row["last_inspection_at"] = None
        services.recompute_program(row)
        services.flush(row)
        return ok(row, 201)

    @route(app, "/api/maintenance-programs", ["GET"], ["Any"])
    def list_programs():
        limit, offset = pagination()
        rows = db.all_rows("maintenance_programs")
        for field in ("fleet_unit_id", "state_code", "program_status"):
            value = arg(field)
            if value:
                rows = [r for r in rows if r.get(field) == value]
        return page_of(db.sort_created(rows), limit, offset)

    @route(app, "/api/maintenance-programs/<rid>", ["GET"], ["Any"])
    def get_program(rid):
        return ok(must_get("MaintenanceProgram", rid))

    @route(app, "/api/fleet-units/<uid>/maintenance-programs", ["GET"], ["Any"])
    def unit_programs(uid):
        must_get("FleetUnit", uid)
        limit, offset = pagination()
        return page_of(db.sort_created(db.by("maintenance_programs", "fleet_unit_id", uid)),
                       limit, offset)

    @route(app, "/api/maintenance-programs/<rid>/schedule", ["POST"],
           ["FleetMaintenanceTech"])
    def schedule(rid):
        """§3.7: scheduling requires the resolved interval to be 0 or in 1 through
        365 and the computed due date to parse as a valid date on or after the
        ledger clock."""
        program = must_get("MaintenanceProgram", rid)
        raw = body()
        _reject_unknown(raw)
        if program.get("program_status") not in ("DRAFT", "SCHEDULED"):
            raise ApiError("ERR_INVALID_STATE",
                           "Only a draft or rescheduled programme can be scheduled.")
        interval = int(program.get("inspection_interval_days") or 0)
        if interval != 0 and not (1 <= interval <= 365):
            raise ApiError("ERR_INVALID_INSPECTION_INTERVAL",
                           "inspection_interval_days must be 0 or between 1 and 365.")
        due = parse_iso(program.get("standard_inspection_due_date"))
        if due is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "The computed due date is not a valid date.")
        if due < core.now():
            raise ApiError("ERR_INVALID_STATE",
                           "The computed due date falls before the ledger clock.")
        services.mark(program, "program_status", "SCHEDULED")
        services.recompute_program(program)
        services.flush(program)
        return ok(program)

    @route(app, "/api/maintenance-programs/<rid>/record-inspection", ["POST"],
           ["FleetMaintenanceTech"])
    def record_inspection(rid):
        """§3.7: requires inspection_odometer_miles of at least 0 and the ledger
        clock to be on or after the scheduled anchor; moves any corridor whose gate
        was being held down by this unit's overdue status from LIMITED to ACTIVE."""
        program = must_get("MaintenanceProgram", rid)
        raw = body()
        for key in raw:
            if key != "inspection_odometer_miles":
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        if "inspection_odometer_miles" not in raw:
            raise ApiError("ERR_INVALID_REQUEST",
                           "inspection_odometer_miles is required.")
        if program.get("program_status") != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE",
                           "Only a scheduled programme can record an inspection.")
        odometer = coerce_int(raw["inspection_odometer_miles"])
        if odometer < 0:
            raise ApiError("ERR_INVALID_REQUEST",
                           "inspection_odometer_miles must be at least 0.")
        anchor = parse_iso(program.get("_anchor_at"))
        if anchor is not None and core.now() < anchor:
            raise ApiError("ERR_INVALID_STATE",
                           "The ledger clock is before the scheduled inspection anchor.")
        services.mark(program, "inspection_odometer_miles", odometer)
        services.mark(program, "last_inspection_at", now_iso())
        services.mark(program, "program_status", "INSPECTED")
        services.recompute_program(program)
        services.flush(program)
        _bubble_corridors_for(program)
        return ok(program)

    @route(app, "/api/maintenance-programs/<rid>/reschedule", ["POST"],
           ["FleetMaintenanceTech"])
    def reschedule(rid):
        program = must_get("MaintenanceProgram", rid)
        raw = body()
        _reject_unknown(raw)
        if program.get("program_status") != "INSPECTED":
            raise ApiError("ERR_INVALID_STATE",
                           "Only an inspected programme can be rescheduled.")
        interval = int(program.get("inspection_interval_days") or 0)
        if interval != 0 and not (1 <= interval <= 365):
            raise ApiError("ERR_INVALID_INSPECTION_INTERVAL",
                           "inspection_interval_days must be 0 or between 1 and 365.")
        # Roll standard_inspection_due_date forward by the interval.
        resolved = services.resolved_interval(interval) or 0
        current = parse_iso(program.get("standard_inspection_due_date"))
        if current is not None:
            services.mark(program, "standard_inspection_due_date",
                          core.midnight_iso(to_iso(current + timedelta(days=resolved))))
        services.mark(program, "program_status", "SCHEDULED")
        services.recompute_program(program)
        services.flush(program)
        return ok(program)

    @route(app, "/api/maintenance-programs/<rid>/void", ["POST"], ["FleetMaintenanceTech"])
    def void(rid):
        """§3.7: voidable only when inspection_programs_status is not COMPLIANT for
        the current epoch; moves every corridor carrying that unit's programme from
        ACTIVE to LIMITED."""
        program = must_get("MaintenanceProgram", rid)
        raw = body()
        _reject_unknown(raw)
        if program.get("program_status") != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", "Only a scheduled programme can be voided.")
        if program.get("inspection_programs_status") == "COMPLIANT":
            raise ApiError("ERR_INVALID_STATE",
                           "A compliant programme cannot be voided for the current epoch.")
        services.mark(program, "program_status", "VOIDED")
        services.mark(program, "inspection_programs_status", "UNFILLED")
        services.flush(program)
        for corridor in _corridors_for(program):
            if corridor.get("corridor_status") == "ACTIVE":
                services.limit_corridor(corridor)
        return ok(program)

    @route(app, "/api/maintenance-programs/<rid>/close", ["POST"], ["ComplianceOfficer"])
    def close(rid):
        program = must_get("MaintenanceProgram", rid)
        raw = body()
        _reject_unknown(raw)
        if program.get("program_status") != "INSPECTED":
            raise ApiError("ERR_INVALID_STATE", "Only an inspected programme can be closed.")
        services.mark(program, "program_status", "CLOSED")
        services.mark(program, "inspection_programs_status", "UNFILLED")
        services.flush(program)
        return ok(program)


def _reject_unknown(raw):
    for key in raw:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field '%s' is not declared for this endpoint." % key)


def _corridors_for(program):
    return [c for c in db.all_rows("corridors") if program in services.corridor_programs(c)]


def _bubble_corridors_for(program):
    for corridor in _corridors_for(program):
        if corridor.get("corridor_status") == "LIMITED":
            services.maybe_recover_limited(corridor)