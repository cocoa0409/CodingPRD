"""Supervisory control: telemetry, decommissioning and the fault-event lifecycle."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import calc
import enums
import svc
from auth import ALL_ROLES, authenticate
from envelope import created, listing, ok
from errors import ApiError
from ladder import gate, invalid_state, path_row
from store import DB
from validate import F, parse

bp = Blueprint("control", __name__)


def _rule_for_code(fault_code):
    for rule in DB.all("fault_code_rules"):
        if rule["fault_code"] == fault_code:
            return rule
    raise ApiError(
        "ERR_REFERENCE_NOT_FOUND", "No fault code rule is registered for %s." % fault_code
    )


# ------------------------------------------------------------------ scada sync
@bp.post("/turbines/<turbine_id>/scada-sync")
def scada_sync(turbine_id):
    authenticate(["ControlRoomOperator"])
    vals = parse(
        [
            F("operating_hours_delta", "number", minv=0),
            F("actual_energy_kwh", "number", minv=0),
            F("potential_energy_kwh", "number", minv=0),
        ]
    )
    turbine = path_row("turbines", turbine_id)
    gate(
        turbine["availability_state"] == "DECOMMISSIONED",
        "ERR_TURBINE_DECOMMISSIONED",
        "The turbine has been decommissioned.",
    )
    gate(
        svc.farm_in_settlement(turbine["wind_farm_id"]),
        "ERR_AGREEMENT_IN_SETTLEMENT",
        "A service agreement on this farm is in settlement; telemetry is frozen.",
    )
    turbine["operating_hours"] = (
        Decimal(turbine["operating_hours"]) + vals["operating_hours_delta"]
    )
    turbine["period_actual_energy_kwh"] = (
        Decimal(turbine["period_actual_energy_kwh"]) + vals["actual_energy_kwh"]
    )
    turbine["period_potential_energy_kwh"] = (
        Decimal(turbine["period_potential_energy_kwh"]) + vals["potential_energy_kwh"]
    )
    svc.recompute_service_figures(turbine)
    DB.touch(turbine)
    svc.live_projection(turbine["wind_farm_id"])
    return ok(turbine)


# --------------------------------------------------------------- decommission
@bp.post("/turbines/<turbine_id>/decommission")
def decommission(turbine_id):
    authenticate(["SiteAdmin"])
    parse([F("decommission_reason", "string", minlen=1, nonblank=True)])
    turbine = path_row("turbines", turbine_id)
    if turbine["availability_state"] != "ONLINE":
        invalid_state(
            "A turbine may only be decommissioned from ONLINE; it is %s."
            % turbine["availability_state"]
        )
    blocking = ("SUBMITTED", "REVISION_REQUESTED", "SCHEDULED", "IN_PROGRESS")
    for wo in DB.all("work_orders"):
        if wo["turbine_id"] == turbine["id"] and wo["state"] in blocking:
            invalid_state("An open work order still references this turbine.")

    for order in DB.all("curtailment_orders"):
        if order["turbine_id"] != turbine["id"]:
            continue
        if order["state"] == "PENDING":
            order["state"] = "CANCELLED"
            DB.touch(order)
        elif order["state"] == "ACTIVE":
            order["state"] = "RELEASED"
            DB.touch(order)

    turbine["availability_state"] = "DECOMMISSIONED"
    turbine["curtailment_state"] = "UNCONSTRAINED"
    turbine["active_curtailment_count"] = 0
    DB.touch(turbine)

    farm = svc.farm_of_turbine(turbine)
    svc.recompute_farm_capacity(farm)
    DB.touch(farm)
    return ok(turbine)


# ---------------------------------------------------------------- fault events
@bp.post("/turbines/<turbine_id>/fault-events")
def raise_fault(turbine_id):
    authenticate(["ControlRoomOperator"])
    vals = parse(
        [
            F("fault_code", "string", minlen=1, maxlen=24, nonblank=True),
            F("raised_at", "datetime"),
        ]
    )
    turbine = path_row("turbines", turbine_id)
    rule = _rule_for_code(vals["fault_code"])
    gate(
        turbine["availability_state"] == "DECOMMISSIONED",
        "ERR_TURBINE_DECOMMISSIONED",
        "The turbine has been decommissioned.",
    )
    if turbine["availability_state"] != "ONLINE":
        invalid_state(
            "A fault may only be raised on an ONLINE turbine; it is %s."
            % turbine["availability_state"]
        )
    event = DB.new_row(
        turbine_id=turbine["id"],
        fault_code_rule_id=rule["id"],
        fault_code=rule["fault_code"],
        raised_at=vals["raised_at"],
        cleared_at=None,
        triage_state="RAISED",
        severity_class_pinned=rule["severity_class"],
        max_remote_resets_pinned=rule["max_remote_resets_per_24h"],
        requires_dispatch_pinned=rule["requires_dispatch"],
        contractual_exclusion_pinned=rule["contractual_exclusion"],
        fault_code_rule_version_pinned=rule["version"],
        reset_attempt_count=0,
        downtime_hours=None,
        lost_energy_kwh=None,
    )
    DB.insert("fault_events", event)
    turbine["active_fault_code"] = rule["fault_code"]
    turbine["availability_state"] = "FAULTED"
    DB.touch(turbine)
    return created(event)


@bp.get("/fault-events/<row_id>")
def get_fault_event(row_id):
    authenticate(ALL_ROLES)
    return ok(path_row("fault_events", row_id))


@bp.get("/fault-events")
def list_fault_events():
    authenticate(ALL_ROLES)
    return listing(
        DB.all("fault_events"),
        request.args,
        [
            ("turbine_id", "turbine_id", "string", None),
            ("fault_code_rule_id", "fault_code_rule_id", "string", None),
            ("triage_state", "triage_state", "enum", enums.TRIAGE_STATES),
        ],
    )


@bp.post("/fault-events/<row_id>/triage")
def triage(row_id):
    authenticate(["ControlRoomOperator"])
    vals = parse([F("disposition", "enum", members=enums.DISPOSITIONS)])
    event = path_row("fault_events", row_id)
    disposition = vals["disposition"]
    if disposition == "REMOTE_RESET":
        if event["triage_state"] != "RAISED":
            raise ApiError(
                "ERR_FAULT_EVENT_INVALID_STATE",
                "A remote reset may only be dispositioned from RAISED; the event is %s."
                % event["triage_state"],
            )
        gate(
            event["severity_class_pinned"] != "RESETTABLE"
            or bool(event["requires_dispatch_pinned"]),
            "ERR_RESET_NOT_PERMITTED",
            "This fault code is not remotely resettable.",
        )
        event["triage_state"] = "RESET_PENDING"
    else:
        if event["triage_state"] not in ("RAISED", "RESET_PENDING"):
            raise ApiError(
                "ERR_FAULT_EVENT_INVALID_STATE",
                "A dispatch may only be dispositioned from RAISED or RESET_PENDING; "
                "the event is %s." % event["triage_state"],
            )
        event["triage_state"] = "DISPATCH_REQUIRED"
    DB.touch(event)
    return ok(event)


@bp.post("/fault-events/<row_id>/remote-reset")
def remote_reset(row_id):
    authenticate(["ControlRoomOperator"])
    vals = parse([F("reset_outcome", "enum", members=enums.RESET_OUTCOMES)])
    event = path_row("fault_events", row_id)
    if event["triage_state"] != "RESET_PENDING":
        raise ApiError(
            "ERR_FAULT_EVENT_INVALID_STATE",
            "A remote reset may only be attempted from RESET_PENDING; the event is %s."
            % event["triage_state"],
        )
    turbine = DB.get("turbines", event["turbine_id"])
    gate(
        turbine["curtailment_state"] == "FORCED_STOP",
        "ERR_TURBINE_FORCE_STOPPED",
        "A force-stopped turbine may not be remotely reset.",
    )
    gate(
        event["severity_class_pinned"] != "RESETTABLE",
        "ERR_RESET_NOT_PERMITTED",
        "This fault code is not remotely resettable.",
    )
    gate(
        int(event["reset_attempt_count"]) >= int(event["max_remote_resets_pinned"]),
        "ERR_RESET_QUOTA_EXHAUSTED",
        "The remote reset quota for this fault event is exhausted.",
    )

    now = DB.now()
    start = turbine["reset_window_start_utc"]
    if start is None or now >= start + timedelta(hours=calc.RESET_WINDOW_HOURS):
        turbine["reset_window_start_utc"] = now
        turbine["remote_reset_count_24h"] = 0
    event["reset_attempt_count"] = int(event["reset_attempt_count"]) + 1
    turbine["remote_reset_count_24h"] = int(turbine["remote_reset_count_24h"]) + 1

    if vals["reset_outcome"] == "SUCCEEDED":
        event["triage_state"] = "CLEARED"
        event["cleared_at"] = now
        turbine["active_fault_code"] = None
        if turbine["availability_state"] == "FAULTED":
            turbine["availability_state"] = "ONLINE"
    DB.touch(event)
    DB.touch(turbine)
    return ok(event)


@bp.post("/fault-events/<row_id>/close")
def close_fault(row_id):
    authenticate(["ReliabilityEngineer"])
    parse([])
    event = path_row("fault_events", row_id)
    if event["triage_state"] != "CLEARED":
        raise ApiError(
            "ERR_FAULT_EVENT_INVALID_STATE",
            "Only a CLEARED fault event may be closed; the event is %s."
            % event["triage_state"],
        )
    turbine = DB.get("turbines", event["turbine_id"])
    svc.close_fault_event(event, turbine)
    return ok(event)
