"""Docks, stops, vessels, inspections and crew — PRD 3.1."""

from datetime import timedelta

from flask import Blueprint

import calc
import serialize
import validation as v
from auth import require
from envelope import (created, ok, ok_list, read_pagination, paginate, enum_param)
from errors import ApiError
from store import store, date_str

bp = Blueprint("estate", __name__)


def find_dock(dock_id):
    row = store.docks.get(dock_id)
    if row is None:
        raise ApiError("ERR_DOCK_NOT_FOUND", "No dock with id %s." % dock_id)
    return row


def find_vessel(vessel_id):
    row = store.vessels.get(vessel_id)
    if row is None:
        raise ApiError("ERR_VESSEL_NOT_FOUND", "No vessel with id %s." % vessel_id)
    return row


def find_crew(crew_id):
    row = store.crew.get(crew_id)
    if row is None:
        raise ApiError("ERR_CREW_NOT_FOUND", "No crew member with id %s." % crew_id)
    return row


# ------------------------------------------------------------------ docks

@bp.post("/harbor/docks")
def create_dock():
    require("HarborAdmin")
    body = v.body()
    name = v.get_string(body, "name", min_len=1, max_len=80)
    berth_count = v.get_integer(body, "berth_count", minimum=1)
    turnaround = v.get_integer(body, "min_turnaround_minutes", required=False,
                               default=15, minimum=0)
    landing_fee = v.get_integer(body, "landing_fee_per_pax_cents", minimum=0)
    berth_rate = v.get_integer(body, "berth_minute_rate_cents", minimum=0)
    cap = v.get_integer(body, "monthly_fee_cap_cents", minimum=1)
    shared = v.get_integer(body, "shared_operator_count", required=False,
                           default=1, minimum=1)

    row = store.new_row()
    row.update({
        "name": name,
        "berth_count": berth_count,
        "min_turnaround_minutes": turnaround,
        "landing_fee_per_pax_cents": landing_fee,
        "berth_minute_rate_cents": berth_rate,
        "monthly_fee_cap_cents": cap,
        "shared_operator_count": shared,
        "accrued_fee_cents": 0,
        "fee_status": "ACCRUING",
    })
    store.docks[row["id"]] = row
    return created(serialize.dock(row))


@bp.get("/harbor/docks/<dock_id>")
def read_dock(dock_id):
    require("HarborAdmin", "Dispatcher", "VesselMaster", "MarineInspector", "FareAuditor")
    return ok(serialize.dock(find_dock(dock_id)))


@bp.post("/harbor/docks/<dock_id>/stops")
def create_stop(dock_id):
    require("HarborAdmin")
    dock = find_dock(dock_id)
    body = v.body()
    name = v.get_string(body, "name", min_len=1, max_len=80)
    zone_index = v.get_integer(body, "zone_index", minimum=1, maximum=6)
    depth = v.get_number(body, "charted_depth_m", minimum=0)

    row = store.new_row()
    row.update({
        "dock_id": dock["id"],
        "name": name,
        "zone_index": zone_index,
        "charted_depth_m": depth,
    })
    store.stops[row["id"]] = row
    return created(serialize.stop(row))


@bp.get("/harbor/docks/<dock_id>/stops")
def list_stops(dock_id):
    require("HarborAdmin", "Dispatcher", "VesselMaster", "Rider", "FareAuditor")
    dock = find_dock(dock_id)
    limit, offset = read_pagination()
    rows = store.ordered([r for r in store.stops.values() if r["dock_id"] == dock["id"]])
    window = paginate(rows, limit, offset)
    return ok_list([serialize.stop(r) for r in window], limit, offset, len(rows))


# ---------------------------------------------------------------- vessels

@bp.post("/harbor/vessels")
def create_vessel():
    require("HarborAdmin")
    body = v.body()
    name = v.get_string(body, "name", min_len=1, max_len=80)
    seat_capacity = v.get_integer(body, "seat_capacity", minimum=1)
    draft = v.get_number(body, "draft_m", exclusive_minimum=0)
    hull_class = v.get_enum(body, "hull_class", ("HARBOR", "OFFSHORE"))
    endorsement = v.get_enum(body, "required_endorsement", ("MASTER_25T", "MASTER_100T"))
    layup_start_raw, layup_start = v.get_calendar_date(
        body, "layup_start_date", required=False, default=None, nullable=True)
    layup_end_raw, layup_end = v.get_calendar_date(
        body, "layup_end_date", required=False, default=None, nullable=True)

    # rung 7 — time windows
    if layup_start is not None and layup_end is not None and layup_end < layup_start:
        raise ApiError("ERR_INVALID_TIME_WINDOW",
                       "layup_end_date may not be earlier than layup_start_date.")

    row = store.new_row()
    row.update({
        "name": name,
        "seat_capacity": seat_capacity,
        "draft_m": draft,
        "hull_class": hull_class,
        "required_endorsement": endorsement,
        "layup_start_date": layup_start_raw,
        "layup_end_date": layup_end_raw,
    })
    store.vessels[row["id"]] = row
    return created(serialize.vessel(row))


@bp.get("/harbor/vessels/<vessel_id>")
def read_vessel(vessel_id):
    require("HarborAdmin", "Dispatcher", "VesselMaster", "MarineInspector")
    return ok(serialize.vessel(find_vessel(vessel_id)))


@bp.post("/harbor/vessels/<vessel_id>/inspections")
def create_inspection(vessel_id):
    actor = require("MarineInspector")
    vessel = find_vessel(vessel_id)
    body = v.body()
    inspection_type = v.get_enum(body, "inspection_type", ("ANNUAL", "PRE_DEPARTURE"))
    result = v.get_enum(body, "result", ("PASS", "PASS_WITH_DEFICIENCIES", "FAIL"))
    deficiency_count = v.get_integer(body, "deficiency_count", required=False,
                                     default=0, minimum=0)
    performed_raw, performed_on = v.get_calendar_date(body, "performed_on")

    expires_on = None
    if inspection_type == "ANNUAL":
        expires_on = date_str(performed_on + timedelta(days=calc.ANNUAL_INSPECTION_VALID_DAYS))

    row = store.new_row(versioned=False)
    row.update({
        "vessel_id": vessel["id"],
        "inspection_type": inspection_type,
        "result": result,
        "deficiency_count": deficiency_count,
        "performed_on": performed_raw,
        "expires_on": expires_on,
        "inspector_user_id": actor.user_id,
    })
    store.inspections[row["id"]] = row
    store.touch(vessel)
    return created(serialize.inspection(row))


@bp.get("/harbor/vessels/<vessel_id>/inspections")
def list_inspections(vessel_id):
    require("HarborAdmin", "Dispatcher", "VesselMaster", "MarineInspector")
    vessel = find_vessel(vessel_id)
    limit, offset = read_pagination()
    type_filter = enum_param("inspection_type", ("ANNUAL", "PRE_DEPARTURE"))
    rows = [r for r in store.inspections.values() if r["vessel_id"] == vessel["id"]]
    if type_filter is not None:
        rows = [r for r in rows if r["inspection_type"] == type_filter]
    rows.sort(key=lambda r: (r["performed_on"], r["_seq"]), reverse=True)
    window = paginate(rows, limit, offset)
    return ok_list([serialize.inspection(r) for r in window], limit, offset, len(rows))


# ------------------------------------------------------------------- crew

@bp.post("/harbor/crew-members")
def create_crew_member():
    require("HarborAdmin")
    body = v.body()
    name = v.get_string(body, "name", min_len=1, max_len=80)
    endorsement = v.get_enum(body, "endorsement_class", ("MASTER_25T", "MASTER_100T"))
    cert_raw, _cert = v.get_calendar_date(body, "cert_expires_on")
    medical_raw, _medical = v.get_calendar_date(body, "medical_expires_on")
    status = v.get_enum(body, "status", ("ACTIVE", "SUSPENDED"),
                        required=False, default="ACTIVE")

    row = store.new_row()
    row.update({
        "name": name,
        "endorsement_class": endorsement,
        "cert_expires_on": cert_raw,
        "medical_expires_on": medical_raw,
        "status": status,
        "trips_mastered_count": 0,
    })
    store.crew[row["id"]] = row
    return created(serialize.crew_member(row))


@bp.get("/harbor/crew-members/<crew_id>")
def read_crew_member(crew_id):
    require("HarborAdmin", "Dispatcher", "VesselMaster")
    return ok(serialize.crew_member(find_crew(crew_id)))
