"""Risk zones, assessments, fire incidents and the zone outcome summary."""

from flask import Blueprint, g

import db
import domain
import response
import util
import validation
from db import store, touch
from errors import ApiError
from middleware import ALL_ROLES, endpoint
from services import reports as report_service
from services import zones as zone_service

bp = Blueprint("zones", __name__)


def load_zone(zone_id):
    zone = store.zones.get(zone_id)
    if zone is None:
        raise ApiError("ERR_ZONE_NOT_FOUND")
    return zone


@bp.post("/crr/zones")
@endpoint("RiskAnalyst")
def create_zone():
    body = validation.json_body()
    validation.reject_unexpected_version(body)
    zone_code = validation.req_str(body, "zone_code")
    name = validation.req_str(body, "name")
    occupied_units = validation.req_int(body, "occupied_units", minimum=1)
    structure_fire_count_5yr = validation.req_int(
        body, "structure_fire_count_5yr", minimum=0
    )
    fire_injury_count_5yr = validation.req_int(body, "fire_injury_count_5yr", minimum=0)
    pre_1980_unit_pct = validation.req_num(body, "pre_1980_unit_pct", minimum=0, maximum=100)
    senior_household_pct = validation.req_num(
        body, "senior_household_pct", minimum=0, maximum=100
    )
    under5_household_pct = validation.req_num(
        body, "under5_household_pct", minimum=0, maximum=100
    )
    disability_household_pct = validation.req_num(
        body, "disability_household_pct", minimum=0, maximum=100
    )
    assumed_alarm_absence_pct = validation.req_num(
        body, "assumed_alarm_absence_pct", minimum=0, maximum=100
    )
    daily_visit_cap = validation.req_int(body, "daily_visit_cap", minimum=1)
    parent_zone_id = validation.opt_str(body, "parent_zone_id", non_empty=True)

    parent = None
    if parent_zone_id is not None:
        parent = store.zones.get(parent_zone_id)
        if parent is None:
            raise ApiError("ERR_ZONE_NOT_FOUND")

    for existing in store.zones.values():
        if existing["zone_code"] == zone_code:
            raise ApiError("ERR_ZONE_CODE_TAKEN")

    if parent is not None and parent["parent_zone_id"] is not None:
        raise ApiError("ERR_ZONE_NESTING_DEPTH")

    row = db.stamp_new({})
    zone = {
        "id": row["id"],
        "zone_code": zone_code,
        "name": name,
        "parent_zone_id": parent_zone_id,
        "zone_kind": "LEAF",
        "occupied_units": occupied_units,
        "structure_fire_count_5yr": structure_fire_count_5yr,
        "fire_injury_count_5yr": fire_injury_count_5yr,
        "pre_1980_unit_pct": pre_1980_unit_pct,
        "senior_household_pct": senior_household_pct,
        "under5_household_pct": under5_household_pct,
        "disability_household_pct": disability_household_pct,
        "assumed_alarm_absence_pct": assumed_alarm_absence_pct,
        "daily_visit_cap": daily_visit_cap,
        "assessment_status": "UNASSESSED",
        "risk_score": None,
        "risk_tier": None,
        "assessment_basis": None,
        "current_assessment_id": None,
        "surveyed_units": 0,
        "surveyed_units_without_alarm": 0,
        "post_service_alarm_loss_units": 0,
        "served_household_count": 0,
        "service_start_date": None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "_seq": row["_seq"],
    }
    store.zones[zone["id"]] = zone

    if parent is not None:
        # PRD 3.1: creation mutates the parent - kind flips, rollup re-runs,
        # version increments by 1.
        parent["zone_kind"] = "DISTRICT"
        zone_service.apply_rollup(parent)
        touch(parent)
    return response.ok_row(zone, 201)


@bp.get("/crr/zones")
@endpoint(*ALL_ROLES)
def list_zones():
    limit, offset = validation.pagination()
    rows = db.by_created_at(list(store.zones.values()))
    for name in (
        "parent_zone_id",
        "current_assessment_id",
        "risk_tier",
        "zone_kind",
        "assessment_status",
    ):
        wanted = validation.filter_value(name)
        if wanted is not None:
            rows = [r for r in rows if r[name] == wanted]
    page, total = validation.paginate(rows, limit, offset)
    return response.ok_list(page, limit, offset, total)


@bp.get("/crr/zones/<zone_id>")
@endpoint(*ALL_ROLES)
def get_zone(zone_id):
    return response.ok_row(load_zone(zone_id))


@bp.post("/crr/zones/<zone_id>/assessments")
@endpoint("RiskAnalyst")
def create_assessment(zone_id):
    zone = load_zone(zone_id)
    body = validation.json_body()
    validation.reject_unexpected_version(body, allowed="expected_zone_version")
    basis = validation.req_enum(body, "basis", domain.ASSESSMENT_BASES)
    expected_zone_version = validation.req_int(body, "expected_zone_version")
    analyst_note = validation.opt_str(body, "analyst_note")

    # Ladder step 8 - optimistic concurrency (PRD 2.10).
    if expected_zone_version != zone["version"]:
        raise ApiError("ERR_STALE_ZONE_VERSION")

    # Ladder step 9 - only LEAF zones are assessed directly (PRD 2.5).
    if zone["zone_kind"] != "LEAF":
        raise ApiError("ERR_ZONE_NOT_ASSESSABLE")

    # Ladder step 35 - the TARGETED re-run does not impose the floor (PRD 3.2).
    if basis == "VALIDATED" and zone["assessment_status"] != "TARGETED":
        if zone["surveyed_units"] < 1:
            raise ApiError("ERR_INSUFFICIENT_FIELD_DATA")

    row = zone_service.run_assessment(zone, basis, analyst_note, g.user_id)
    return response.ok_row(row, 201)


@bp.get("/crr/zones/<zone_id>/assessments")
@endpoint("ProgramAdmin", "RiskAnalyst", "GrantOfficer")
def list_assessments(zone_id):
    load_zone(zone_id)
    limit, offset = validation.pagination()
    rows = zone_service.assessments_of(zone_id)
    page, total = validation.paginate(rows, limit, offset)
    return response.ok_list(page, limit, offset, total)


@bp.post("/crr/zones/<zone_id>/fire-incidents")
@endpoint("RiskAnalyst")
def create_fire_incident(zone_id):
    zone = load_zone(zone_id)
    body = validation.json_body()
    validation.reject_unexpected_version(body)
    incident_number = validation.req_str(body, "incident_number")
    occurred_at = validation.req_instant(body, "occurred_at")
    working_alarm_present = validation.req_bool(body, "working_alarm_present")
    injuries = validation.opt_int(body, "injuries", default=0, minimum=0)
    fatalities = validation.opt_int(body, "fatalities", default=0, minimum=0)

    for existing in store.fire_incidents.values():
        if existing["incident_number"] == incident_number:
            raise ApiError("ERR_INCIDENT_NUMBER_TAKEN")

    row = db.stamp_event({})
    incident = {
        "id": row["id"],
        "zone_id": zone["id"],
        "incident_number": incident_number,
        "occurred_at": occurred_at,
        "working_alarm_present": working_alarm_present,
        "injuries": injuries,
        "fatalities": fatalities,
        "created_at": row["created_at"],
        "_seq": row["_seq"],
    }
    store.fire_incidents[incident["id"]] = incident
    # PRD 3.1: recording an incident has no side effects beyond the append.
    return response.ok_row(incident, 201)


@bp.get("/crr/zones/<zone_id>/fire-incidents")
@endpoint("ProgramAdmin", "RiskAnalyst")
def list_fire_incidents(zone_id):
    load_zone(zone_id)
    limit, offset = validation.pagination()
    rows = [i for i in store.fire_incidents.values() if i["zone_id"] == zone_id]
    rows.sort(key=lambda r: (r["occurred_at"], r["created_at"], r["_seq"]))
    page, total = validation.paginate(rows, limit, offset)
    return response.ok_list(page, limit, offset, total)


@bp.get("/crr/zones/<zone_id>/outcome-summary")
@endpoint("ProgramAdmin", "RiskAnalyst", "GrantOfficer", "PartnerLiaison")
def get_outcome_summary(zone_id):
    zone = load_zone(zone_id)
    return response.ok(report_service.outcome_summary(zone))
