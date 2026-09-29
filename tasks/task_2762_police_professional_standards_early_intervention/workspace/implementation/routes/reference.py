"""Units, hearing rooms, officers, activity events, EIS profile, logical clock."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import svc
from core import (
    ApiError,
    D,
    add_days,
    body,
    db,
    dump,
    endpoint,
    f_bool,
    f_dt,
    f_enum,
    f_int,
    f_str,
    fmt_dt,
    new_row,
    paginate,
    q_bool,
    q_enum,
    q_str,
    respond_object,
    sort_created,
    touch,
)

bp = Blueprint("reference", __name__)


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------
@bp.post("/units")
@endpoint("SystemAdmin")
def create_unit():
    payload = body()
    name = f_str(payload, "name")
    unit_role = f_enum(payload, "unit_role", calc.UNIT_ROLES)
    command_code = f_str(payload, "command_code")
    peer_group_code = f_str(payload, "peer_group_code")
    sworn_headcount = f_int(payload, "sworn_headcount", minimum=1)
    intake_enabled = f_bool(payload, "intake_enabled", required=False, default=True)
    unit = new_row(
        "Unit",
        audited=False,
        name=name,
        unit_role=unit_role,
        command_code=command_code,
        peer_group_code=peer_group_code,
        sworn_headcount=sworn_headcount,
        intake_enabled=intake_enabled,
    )
    db.units[unit["id"]] = unit
    return respond_object(dump(unit), 201)


@bp.get("/units/<unit_id>")
@endpoint("SystemAdmin", "IACommander", "Supervisor", "Investigator", "RecordsCustodian")
def read_unit(unit_id):
    return respond_object(dump(svc.need_unit(unit_id)))


@bp.get("/units")
@endpoint("SystemAdmin", "IACommander", "Supervisor", "Investigator", "RecordsCustodian")
def list_units():
    unit_role = q_enum("unit_role", calc.UNIT_ROLES)
    peer_group_code = q_str("peer_group_code")
    rows = sort_created(list(db.units.values()))
    if unit_role is not None:
        rows = [r for r in rows if r["unit_role"] == unit_role]
    if peer_group_code is not None:
        rows = [r for r in rows if r["peer_group_code"] == peer_group_code]
    return paginate(rows)


# ---------------------------------------------------------------------------
# Hearing rooms
# ---------------------------------------------------------------------------
@bp.post("/hearing-rooms")
@endpoint("SystemAdmin")
def create_room():
    payload = body()
    facility_code = f_str(payload, "facility_code")
    room_name = f_str(payload, "room_name")
    concurrent_capacity = f_int(payload, "concurrent_capacity", minimum=1)
    recording_enabled = f_bool(payload, "recording_enabled", required=False, default=True)
    room = new_row(
        "HearingRoom",
        audited=False,
        facility_code=facility_code,
        room_name=room_name,
        concurrent_capacity=concurrent_capacity,
        recording_enabled=recording_enabled,
    )
    db.rooms[room["id"]] = room
    return respond_object(dump(room), 201)


@bp.get("/hearing-rooms/<room_id>")
@endpoint("SystemAdmin", "IACommander", "Investigator", "OfficerRepresentative")
def read_room(room_id):
    return respond_object(dump(svc.need_room(room_id)))


@bp.get("/hearing-rooms")
@endpoint("SystemAdmin", "IACommander", "Investigator", "OfficerRepresentative")
def list_rooms():
    facility_code = q_str("facility_code")
    rows = sort_created(list(db.rooms.values()))
    if facility_code is not None:
        rows = [r for r in rows if r["facility_code"] == facility_code]
    return paginate(rows)


# ---------------------------------------------------------------------------
# Officers
# ---------------------------------------------------------------------------
@bp.post("/officers")
@endpoint("SystemAdmin")
def create_officer():
    payload = body()
    unit_id = f_str(payload, "unit_id")
    badge_number = f_str(payload, "badge_number")
    full_name = f_str(payload, "full_name")
    rank = f_enum(payload, "rank", calc.RANKS)
    assignment_type = f_enum(payload, "assignment_type", calc.ASSIGNMENT_TYPES)
    annual_salary_cents = f_int(payload, "annual_salary_cents", minimum=0)
    demographic_code = f_enum(payload, "demographic_code", calc.DEMOGRAPHIC_CODES)
    hire_date = f_dt(payload, "hire_date")
    is_investigator = f_bool(payload, "is_investigator", required=False, default=False)
    certification_level = f_int(
        payload, "certification_level", required=False, default=0, minimum=0, maximum=3
    )
    max_case_load = f_int(payload, "max_case_load", required=False, default=5, minimum=0)
    # tier 5 -- body reference existence
    svc.need_unit(unit_id)
    # tier 12 -- business constraint
    if any(o["badge_number"] == badge_number for o in db.officers.values()):
        raise ApiError("ERR_BADGE_NUMBER_DUPLICATE")
    officer = new_row(
        "Officer",
        unit_id=unit_id,
        badge_number=badge_number,
        full_name=full_name,
        rank=rank,
        assignment_type=assignment_type,
        is_investigator=is_investigator,
        certification_level=certification_level,
        max_case_load=max_case_load,
        annual_salary_cents=annual_salary_cents,
        demographic_code=demographic_code,
        hire_date=hire_date,
        employment_status="ACTIVE",
        eis_score=Decimal("0.00"),
        eis_alert_level="NONE",
        open_case_load=0,
        imposed_suspension_days_total=0,
        open_alert_count=0,
        intervention_escalation_count=0,
        credibility_disclosure_active=False,
        suspension_end_date=None,
    )
    db.officers[officer["id"]] = officer
    return respond_object(dump(officer), 201)


@bp.get("/officers/<officer_id>")
@endpoint(
    "SystemAdmin",
    "IACommander",
    "Supervisor",
    "Investigator",
    "AppealsOfficer",
    "RecordsCustodian",
    "OfficerRepresentative",
)
def read_officer(officer_id):
    return respond_object(dump(svc.need_officer(officer_id)))


@bp.get("/officers")
@endpoint(
    "SystemAdmin",
    "IACommander",
    "Supervisor",
    "Investigator",
    "AppealsOfficer",
    "RecordsCustodian",
)
def list_officers():
    unit_id = q_str("unit_id")
    is_investigator = q_bool("is_investigator")
    employment_status = q_enum("employment_status", calc.EMPLOYMENT_STATUSES)
    eis_alert_level = q_enum("eis_alert_level", calc.OFFICER_ALERT_LEVELS)
    credibility = q_bool("credibility_disclosure_active")
    rows = sort_created(list(db.officers.values()))
    if unit_id is not None:
        rows = [r for r in rows if r["unit_id"] == unit_id]
    if is_investigator is not None:
        rows = [r for r in rows if r["is_investigator"] == is_investigator]
    if employment_status is not None:
        rows = [r for r in rows if r["employment_status"] == employment_status]
    if eis_alert_level is not None:
        rows = [r for r in rows if r["eis_alert_level"] == eis_alert_level]
    if credibility is not None:
        rows = [r for r in rows if r["credibility_disclosure_active"] == credibility]
    return paginate(rows)


@bp.post("/officers/<officer_id>/employment-status")
@endpoint("SystemAdmin")
def write_employment_status(officer_id):
    officer = svc.need_officer(officer_id)
    payload = body()
    new_status = f_enum(payload, "employment_status", calc.EMPLOYMENT_STATUSES)
    f_str(payload, "reason", required=False)
    # tier 8 -- SEPARATED is terminal; every further write is refused
    if officer["employment_status"] == "SEPARATED":
        raise ApiError("ERR_OFFICER_SEPARATED")
    officer["employment_status"] = new_status
    if new_status == "ACTIVE":
        officer["suspension_end_date"] = None
    touch(officer)
    return respond_object(dump(officer))


# ---------------------------------------------------------------------------
# Officer activity events
# ---------------------------------------------------------------------------
@bp.post("/officers/<officer_id>/activity-events")
@endpoint("Supervisor", "SystemAdmin")
def create_activity_event(officer_id):
    officer = svc.need_officer(officer_id)
    payload = body()
    event_type = f_enum(payload, "event_type", calc.EVENT_TYPES)
    severity_code = f_enum(
        payload, "severity_code", calc.SEVERITY_CODES, required=False, default="NA"
    )
    occurred_at = f_dt(payload, "occurred_at")
    source_reference = f_str(payload, "source_reference", required=False)
    # tier 11 -- temporal
    if occurred_at > db.clock:
        raise ApiError("ERR_EVENT_IN_FUTURE")
    event = svc.append_activity_event(
        officer["id"],
        event_type,
        severity_code,
        occurred_at,
        source_reference,
        system_generated=False,
    )
    profile = svc.recompute_officer_eis(officer)
    if profile["alert_level"] != "NONE" and svc.open_alert_for(officer["id"]) is None:
        svc.create_alert(officer, profile, "EVENT_INGEST")
    return respond_object(dump(event), 201)


@bp.get("/officers/<officer_id>/activity-events")
@endpoint("SystemAdmin", "IACommander", "Supervisor", "Investigator", "RecordsCustodian")
def list_activity_events(officer_id):
    svc.need_officer(officer_id)
    event_type = q_enum("event_type", calc.EVENT_TYPES)
    rows = [e for e in db.events.values() if e["officer_id"] == officer_id]
    if event_type is not None:
        rows = [r for r in rows if r["event_type"] == event_type]
    rows.sort(key=lambda e: (e["occurred_at"], e["created_at"], e["_seq"]))
    return paginate(rows)


@bp.get("/officers/<officer_id>/eis-profile")
@endpoint("SystemAdmin", "IACommander", "Supervisor")
def read_eis_profile(officer_id):
    officer = svc.need_officer(officer_id)
    variant = q_enum("variant", calc.SCORE_VARIANTS, default="ROLLING_12M")
    profile = calc.profile_for(officer, variant)
    return respond_object(svc.dump_profile(officer, profile))


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
@endpoint("SystemAdmin")
def set_clock():
    payload = body()
    current_utc = f_dt(payload, "current_utc")
    previous = db.clock
    db.clock = current_utc
    return respond_object(
        {"current_utc": fmt_dt(db.clock), "previous_utc": fmt_dt(previous)}
    )
