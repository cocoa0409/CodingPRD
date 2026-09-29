"""Officers, flight schedule entries and time bands."""

from datetime import timedelta

from flask import Blueprint

import calc
import cascade
import consts
import derive
import envelope
import req
import serial
import store
from errors import bad_request, fail
from util import dec

bp = Blueprint("staff", __name__)


# ---------------------------------------------------------------------------
# officers
# ---------------------------------------------------------------------------
OFFICER_SPEC = [
    {"name": "badge_number", "kind": "string", "required": True, "max_len": 16},
    {"name": "full_name", "kind": "string", "required": True, "max_len": 80},
    {
        "name": "certifications",
        "kind": "enum_array",
        "required": True,
        "values": consts.CERTIFICATIONS,
    },
    {"name": "base_rate_cents_per_minute", "kind": "integer", "required": True, "min": 1},
    {"name": "weekly_regular_minutes_cap", "kind": "integer", "required": True, "min": 1},
    {"name": "weekly_overtime_minutes_cap", "kind": "integer", "required": True, "min": 0},
]


@bp.post("/officers")
def create_officer():
    req.actor(["PlatformAdmin"])
    values = req.parse_body(OFFICER_SPEC)
    for officer in store.rows("officers"):
        if officer["badge_number"] == values["badge_number"]:
            fail("ERR_DUPLICATE_BADGE_NUMBER", "badge_number is already registered")
    row = store.base()
    row.update(
        {
            "badge_number": values["badge_number"],
            "full_name": values["full_name"],
            "certifications": values["certifications"],
            "base_rate_cents_per_minute": values["base_rate_cents_per_minute"],
            "weekly_regular_minutes_cap": values["weekly_regular_minutes_cap"],
            "weekly_overtime_minutes_cap": values["weekly_overtime_minutes_cap"],
            "duty_status": "OFF_DUTY",
            "committed_duty_minutes": 0,
            "approved_detail_minutes": 0,
        }
    )
    store.add("officers", row)
    return envelope.obj(serial.officer(row), 201)


@bp.get("/officers/<officer_id>")
def read_officer(officer_id):
    req.actor(req.READ_ROLES)
    row = req.load("officer", officer_id)
    return envelope.obj(serial.officer(row))


DUTY_STATUS_SPEC = [
    {"name": "duty_status", "kind": "enum", "required": True, "values": consts.DUTY_STATUSES}
]


@bp.post("/officers/<officer_id>/duty-status")
def set_duty_status(officer_id):
    req.actor(["PlatformAdmin", "CheckpointManager"])
    values = req.parse_body(DUTY_STATUS_SPEC)
    officer = req.load("officer", officer_id)
    target = values["duty_status"]
    current = officer["duty_status"]
    legal = (current, target) in (
        ("OFF_DUTY", "ON_DUTY"),
        ("ON_DUTY", "OFF_DUTY"),
        ("OFF_DUTY", "SEPARATED"),
    )
    if not legal:
        fail("ERR_INVALID_STATE_TRANSITION", "%s cannot move to %s" % (current, target))
    assignments = derive.officer_assignments(officer["id"])
    if target == "OFF_DUTY":
        for assignment in assignments:
            if assignment["assignment_state"] in ("CHECKED_IN", "REASSIGN_PENDING"):
                fail("ERR_INVALID_STATE_TRANSITION", "the officer still holds a live position")
    if target == "SEPARATED":
        for assignment in assignments:
            if assignment["assignment_state"] in (
                "SCHEDULED",
                "CHECKED_IN",
                "REASSIGN_PENDING",
            ):
                fail("ERR_INVALID_STATE_TRANSITION", "the officer still holds an assignment")
        for detail in derive.officer_details(officer["id"]):
            if detail["state"] in ("REQUESTED", "APPROVED"):
                fail("ERR_INVALID_STATE_TRANSITION", "the officer still holds a surge detail")
    officer["duty_status"] = target
    cascade.bump_officer(officer)
    return envelope.obj(serial.officer(officer))


@bp.get("/officers/<officer_id>/duty-ledger")
def read_duty_ledger(officer_id):
    req.actor(
        [
            "PlatformAdmin",
            "CheckpointManager",
            "StaffingPlanner",
            "DutyManager",
            "SupervisoryOfficer",
        ]
    )
    officer = req.load("officer", officer_id)
    variant = req.query_enum("variant", consts.LEDGER_VARIANTS) or "FORWARD_LOOKING_PLANNED"
    derive.evaluate_all_breaks()
    return envelope.obj(store.render(calc.officer_duty_ledger(officer, variant)))


# ---------------------------------------------------------------------------
# flight schedule entries
# ---------------------------------------------------------------------------
FLIGHT_SPEC = [
    {
        "name": "checkpoint_id",
        "kind": "string",
        "required": True,
        "fk": "checkpoint",
        "collection": "checkpoints",
    },
    {
        "name": "show_up_curve_id",
        "kind": "string",
        "required": True,
        "fk": "show_up_curve",
        "collection": "show_up_curves",
    },
    {
        "name": "flight_number",
        "kind": "string",
        "required": True,
        "max_len": 8,
        "upper_alnum": True,
    },
    {"name": "scheduled_departure_utc", "kind": "datetime", "required": True},
    {"name": "seats_sold", "kind": "integer", "required": True, "min": 0},
    {"name": "load_factor_pct", "kind": "number", "required": True, "min": 0, "max": 100},
    {"name": "carrier_type", "kind": "enum", "required": True, "values": consts.CARRIER_TYPES},
]


@bp.post("/flight-schedule-entries")
def create_flight():
    req.actor(["PlatformAdmin", "StaffingPlanner"])
    values = req.parse_body(FLIGHT_SPEC)
    parents = req.resolve_fks(values, FLIGHT_SPEC)
    row = store.base()
    row.update(
        {
            "checkpoint_id": parents["checkpoint_id"]["id"],
            "show_up_curve_id": parents["show_up_curve_id"]["id"],
            "flight_number": values["flight_number"],
            "scheduled_departure_utc": values["scheduled_departure_utc"],
            "seats_sold": values["seats_sold"],
            "load_factor_pct": values["load_factor_pct"],
            "carrier_type": values["carrier_type"],
            "status": "SCHEDULED",
            "projected_pax_count": 0,
        }
    )
    row["projected_pax_count"] = calc.projected_pax(row)
    store.add("flight_schedule_entries", row)
    return envelope.obj(serial.flight_schedule_entry(row), 201)


@bp.get("/flight-schedule-entries/<flight_schedule_entry_id>")
def read_flight(flight_schedule_entry_id):
    req.actor(req.READ_ROLES)
    row = req.load("flight_schedule_entry", flight_schedule_entry_id)
    return envelope.obj(serial.flight_schedule_entry(row))


@bp.get("/flight-schedule-entries")
def list_flights():
    req.actor(req.READ_ROLES)
    limit, offset = req.pagination()
    status = req.query_enum("status", ("SCHEDULED", "CANCELLED"))
    rows = req.filter_rows(
        store.rows("flight_schedule_entries"),
        {
            "checkpoint_id": req.query_value("checkpoint_id"),
            "show_up_curve_id": req.query_value("show_up_curve_id"),
            "status": status,
        },
    )
    rows.sort(key=lambda f: (f["scheduled_departure_utc"], f["flight_number"], f["_seq"]))
    page, total = req.paginate(rows, limit, offset)
    return envelope.listing(
        serial.many(serial.flight_schedule_entry, page), limit, offset, total
    )


@bp.post("/flight-schedule-entries/<flight_schedule_entry_id>/cancel")
def cancel_flight(flight_schedule_entry_id):
    req.actor(["PlatformAdmin", "StaffingPlanner"])
    row = req.load("flight_schedule_entry", flight_schedule_entry_id)
    if row["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE_TRANSITION", "the flight is already cancelled")
    row["status"] = "CANCELLED"
    store.touch(row)
    return envelope.obj(serial.flight_schedule_entry(row))


# ---------------------------------------------------------------------------
# time bands
# ---------------------------------------------------------------------------
TIME_BAND_SPEC = [
    {
        "name": "checkpoint_id",
        "kind": "string",
        "required": True,
        "fk": "checkpoint",
        "collection": "checkpoints",
    },
    {"name": "band_start_utc", "kind": "datetime", "required": True},
    {"name": "expedited_share_pct", "kind": "integer", "required": True, "min": 0, "max": 100},
    {"name": "seasonal_multiplier", "kind": "number", "min": "0.50", "max": "3.00"},
]


@bp.post("/time-bands")
def create_time_band():
    req.actor(["PlatformAdmin", "StaffingPlanner"])
    values = req.parse_body(TIME_BAND_SPEC)
    start = values["band_start_utc"]
    if start.minute not in (0, 30) or start.second != 0 or start.microsecond != 0:
        bad_request("band_start_utc must be aligned to :00 or :30 with zero seconds")
    parents = req.resolve_fks(values, TIME_BAND_SPEC)
    checkpoint = parents["checkpoint_id"]
    for band in store.rows("time_bands"):
        if band["checkpoint_id"] == checkpoint["id"] and band["band_start_utc"] == start:
            fail("ERR_DUPLICATE_TIME_BAND", "a band already starts at that instant")
    row = store.base()
    row.update(
        {
            "checkpoint_id": checkpoint["id"],
            "band_start_utc": start,
            "band_end_utc": start + timedelta(minutes=consts.BAND_MINUTES),
            "expedited_share_pct": values["expedited_share_pct"],
            "seasonal_multiplier": values.get("seasonal_multiplier", dec("1.00")),
            "forecast_variant": None,
            "forecast_pax_count": None,
            "forecast_computed_at_utc": None,
            "required_standard_lanes": None,
            "required_expedited_lanes": None,
            "unmet_standard_demand": None,
            "unmet_expedited_demand": None,
        }
    )
    store.add("time_bands", row)
    return envelope.obj(serial.time_band(row), 201)


@bp.get("/time-bands/<time_band_id>")
def read_time_band(time_band_id):
    req.actor(req.READ_ROLES)
    row = req.load("time_band", time_band_id)
    return envelope.obj(serial.time_band(row))


@bp.get("/time-bands")
def list_time_bands():
    req.actor(req.READ_ROLES)
    limit, offset = req.pagination()
    variant = req.query_enum("forecast_variant", consts.FORECAST_VARIANTS)
    from_utc = req.query_instant("from_utc")
    to_utc = req.query_instant("to_utc")
    rows = req.filter_rows(
        store.rows("time_bands"),
        {
            "checkpoint_id": req.query_value("checkpoint_id"),
            "forecast_variant": variant,
        },
    )
    if from_utc is not None:
        rows = [b for b in rows if b["band_start_utc"] >= from_utc]
    if to_utc is not None:
        rows = [b for b in rows if b["band_start_utc"] < to_utc]
    rows.sort(key=lambda b: (b["band_start_utc"], b["created_at"], b["_seq"]))
    page, total = req.paginate(rows, limit, offset)
    return envelope.listing(serial.many(serial.time_band, page), limit, offset, total)


FORECAST_SPEC = [
    {"name": "variant", "kind": "enum", "required": True, "values": consts.FORECAST_VARIANTS}
]


@bp.post("/time-bands/<time_band_id>/forecast")
def forecast_time_band(time_band_id):
    req.actor(["PlatformAdmin", "StaffingPlanner", "DutyManager"])
    values = req.parse_body(FORECAST_SPEC)
    band = req.load("time_band", time_band_id)
    variant = values["variant"]
    band["forecast_pax_count"] = calc.time_band_pax_forecast(band, variant)
    band["forecast_variant"] = variant
    band["forecast_computed_at_utc"] = store.now()
    band.update(calc.lane_requirement(band))
    store.touch(band)
    return envelope.obj(serial.time_band(band))
