"""Home safety visits: booking, rescheduling, cancellation and field work."""

from datetime import timedelta

from flask import Blueprint, g

import db
import domain
import response
import util
import validation
from db import store, touch
from errors import ApiError
from middleware import endpoint
from services import households as household_service
from services import installations as installation_service
from services import visits as visit_service
from services import zones as zone_service

bp = Blueprint("visits", __name__)

READ_ROLES = ("ProgramAdmin", "CanvassCoordinator", "CrrTechnician")


def load_visit(visit_id):
    visit = store.visits.get(visit_id)
    if visit is None:
        raise ApiError("ERR_VISIT_NOT_FOUND")
    return visit


def require_assigned_crew(visit):
    """Ladder step 6 - entity-backed identity ownership (PRD 2.1)."""
    route = visit_service.route_of(visit)
    if route is None or route["crew_id"] != g.user_id:
        raise ApiError("ERR_CREW_NOT_ASSIGNED")
    return route


@bp.post("/crr/visits")
@endpoint("CanvassCoordinator")
def create_visit():
    body = validation.json_body()
    validation.reject_unexpected_version(body)
    household_id = validation.req_str(body, "household_id")
    route_id = validation.req_str(body, "route_id")
    scheduled_start_utc = validation.req_instant(body, "scheduled_start_utc")
    appointment_option = validation.req_enum(
        body, "appointment_option", domain.APPOINTMENT_OPTIONS
    )
    contact_channel = validation.opt_enum(
        body, "contact_channel", domain.CONTACT_CHANNELS, default="PHONE"
    )

    household = store.households.get(household_id)
    if household is None:
        raise ApiError("ERR_HOUSEHOLD_NOT_FOUND")
    route = store.routes.get(route_id)
    if route is None:
        raise ApiError("ERR_ROUTE_NOT_FOUND")

    if household["status"] not in ("INTAKE_QUEUED", "REVISIT_REQUIRED"):
        raise ApiError("ERR_INVALID_HOUSEHOLD_STATE")
    if route["status"] not in domain.ROUTE_OPEN_STATUSES:
        raise ApiError("ERR_ROUTE_NOT_OPEN")

    zone = store.zones.get(route["zone_id"])
    minutes = visit_service.demand_minutes(household, zone)
    end = scheduled_start_utc + timedelta(minutes=minutes)
    occupies = appointment_option != "VIRTUAL_ASSESSMENT"
    crew = store.crews.get(route["crew_id"])
    occupations = visit_service.occupations_for(route) if occupies else []

    if occupies:
        visit_service.check_interval(route, scheduled_start_utc, end, occupations)
    visit_service.check_window(route, scheduled_start_utc, end)
    if route["booked_slot_count"] >= route["planned_slots"]:
        raise ApiError("ERR_ROUTE_SLOTS_EXHAUSTED")
    if occupies and crew is not None:
        visit_service.check_daily_minutes(crew, occupations, minutes)
    if visit_service.has_open_visit(household_id):
        raise ApiError("ERR_HOUSEHOLD_HAS_OPEN_VISIT")
    if route["zone_id"] != household["zone_id"]:
        raise ApiError("ERR_ROUTE_ZONE_MISMATCH")

    row = db.stamp_new({})
    visit = {
        "id": row["id"],
        "household_id": household_id,
        "route_id": route_id,
        "scheduled_start_utc": scheduled_start_utc,
        "scheduled_end_utc": end,
        "demand_minutes": minutes,
        "appointment_option": appointment_option,
        "contact_channel": contact_channel,
        "occupies_crew_calendar": occupies,
        "visit_status": "SCHEDULED",
        "install_status": "NOT_STARTED",
        "education_status": "PENDING",
        "pre_existing_working_smoke_alarms": None,
        "pre_existing_working_co_alarms": None,
        "occupant_present": None,
        "education_topics": None,
        "escape_plan_walkthrough": None,
        "occupant_signature_name": None,
        "deferral_reason": None,
        "cancel_reason": None,
        "cancelled_at": None,
        "completed_at": None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "_seq": row["_seq"],
    }
    store.visits[visit["id"]] = visit

    route["booked_slot_count"] = route["booked_slot_count"] + 1
    touch(route)
    household["status"] = "APPOINTMENT_SCHEDULED"
    household["canvass_attempt_count"] = household["canvass_attempt_count"] + 1
    touch(household)
    return response.ok_row(visit, 201)


@bp.get("/crr/visits")
@endpoint(*READ_ROLES)
def list_visits():
    limit, offset = validation.pagination()
    rows = db.by_created_at(list(store.visits.values()))
    for name in ("household_id", "route_id", "visit_status", "install_status"):
        wanted = validation.filter_value(name)
        if wanted is not None:
            rows = [r for r in rows if r[name] == wanted]
    page, total = validation.paginate(rows, limit, offset)
    return response.ok_list(page, limit, offset, total)


@bp.get("/crr/visits/<visit_id>")
@endpoint(*READ_ROLES)
def get_visit(visit_id):
    return response.ok_row(load_visit(visit_id))


@bp.post("/crr/visits/<visit_id>/reschedule")
@endpoint("CanvassCoordinator")
def reschedule_visit(visit_id):
    visit = load_visit(visit_id)
    body = validation.json_body()
    validation.reject_unexpected_version(body)
    route_id = validation.req_str(body, "route_id")
    scheduled_start_utc = validation.req_instant(body, "scheduled_start_utc")

    route = store.routes.get(route_id)
    if route is None:
        raise ApiError("ERR_ROUTE_NOT_FOUND")

    # PRD 3.5: permitted only while the crew has not arrived.
    if visit["cancelled_at"] is not None or visit["install_status"] != "NOT_STARTED":
        raise ApiError("ERR_INVALID_VISIT_STATE")
    if route["status"] not in domain.ROUTE_OPEN_STATUSES:
        raise ApiError("ERR_ROUTE_NOT_OPEN")

    household = store.households.get(visit["household_id"])
    old_route = visit_service.route_of(visit)
    zone = store.zones.get(route["zone_id"])
    minutes = visit_service.demand_minutes(household, zone)
    end = scheduled_start_utc + timedelta(minutes=minutes)
    occupies = visit["occupies_crew_calendar"]
    crew = store.crews.get(route["crew_id"])
    occupations = (
        visit_service.occupations_for(route, exclude_visit_id=visit["id"])
        if occupies
        else []
    )
    route_changed = old_route is None or old_route["id"] != route["id"]

    if occupies:
        visit_service.check_interval(route, scheduled_start_utc, end, occupations)
    visit_service.check_window(route, scheduled_start_utc, end)
    if route_changed and route["booked_slot_count"] >= route["planned_slots"]:
        raise ApiError("ERR_ROUTE_SLOTS_EXHAUSTED")
    if occupies and crew is not None:
        visit_service.check_daily_minutes(crew, occupations, minutes)
    if household is not None and route["zone_id"] != household["zone_id"]:
        raise ApiError("ERR_ROUTE_ZONE_MISMATCH")

    visit["route_id"] = route["id"]
    visit["scheduled_start_utc"] = scheduled_start_utc
    visit["scheduled_end_utc"] = end
    visit["demand_minutes"] = minutes
    visit_service.refresh_status(visit)
    touch(visit)

    if route_changed:
        if old_route is not None:
            old_route["booked_slot_count"] = old_route["booked_slot_count"] - 1
            touch(old_route)
        route["booked_slot_count"] = route["booked_slot_count"] + 1
        touch(route)
    return response.ok_row(visit)


@bp.post("/crr/visits/<visit_id>/cancel")
@endpoint("CanvassCoordinator")
def cancel_visit(visit_id):
    visit = load_visit(visit_id)
    body = validation.json_body()
    validation.reject_unexpected_version(body)
    cancel_reason = validation.req_enum(body, "cancel_reason", domain.CANCEL_REASONS)

    if visit["cancelled_at"] is not None or visit["install_status"] not in (
        "NOT_STARTED",
        "SURVEYED",
    ):
        raise ApiError("ERR_INVALID_VISIT_STATE")

    visit_service.cancel(visit, cancel_reason)
    return response.ok_row(visit)


@bp.post("/crr/visits/<visit_id>/arrive")
@endpoint("CrrTechnician")
def arrive_visit(visit_id):
    visit = load_visit(visit_id)
    body = validation.json_body()
    validation.reject_unexpected_version(body)
    occupant_present = validation.req_bool(body, "occupant_present")
    pre_smoke = validation.req_int(body, "pre_existing_working_smoke_alarms", minimum=0)
    pre_co = validation.req_int(body, "pre_existing_working_co_alarms", minimum=0)

    route = require_assigned_crew(visit)

    if visit["cancelled_at"] is not None or visit["install_status"] != "NOT_STARTED":
        raise ApiError("ERR_INVALID_VISIT_STATE")
    if not occupant_present:
        # PRD 3.6: a crew that finds nobody home does not survey the house.
        raise ApiError("ERR_INVALID_VISIT_STATE")
    if route["status"] not in domain.ROUTE_OPEN_STATUSES:
        raise ApiError("ERR_ROUTE_NOT_OPEN")

    visit["occupant_present"] = occupant_present
    visit["pre_existing_working_smoke_alarms"] = pre_smoke
    visit["pre_existing_working_co_alarms"] = pre_co
    visit["install_status"] = "SURVEYED"
    visit_service.refresh_status(visit)
    touch(visit)

    if route["status"] == "PUBLISHED":
        route["status"] = "IN_PROGRESS"
        touch(route)
    return response.ok_row(visit)


@bp.post("/crr/visits/<visit_id>/education")
@endpoint("CrrTechnician")
def educate_visit(visit_id):
    visit = load_visit(visit_id)
    body = validation.json_body()
    validation.reject_unexpected_version(body)
    education_outcome = validation.req_enum(
        body, "education_outcome", domain.EDUCATION_OUTCOMES
    )
    if education_outcome == "DELIVERED":
        # PRD 3.6: DELIVERED requires a non-empty topics array.
        topics_covered = validation.req_str_list(body, "topics_covered")
    else:
        topics_covered = validation.opt_str_list(body, "topics_covered")
    escape_plan_walkthrough = validation.opt_bool(body, "escape_plan_walkthrough")

    require_assigned_crew(visit)

    if (
        visit["cancelled_at"] is not None
        or visit["install_status"] == "NOT_STARTED"
        or visit["education_status"] != "PENDING"
    ):
        raise ApiError("ERR_INVALID_VISIT_STATE")

    if education_outcome == "DELIVERED":
        visit["education_topics"] = topics_covered
        visit["escape_plan_walkthrough"] = escape_plan_walkthrough
        visit["education_status"] = "DELIVERED"
    else:
        # PRD 3.6: DECLINED ignores whatever topics were sent.
        visit["education_status"] = "DECLINED"
    visit_service.refresh_status(visit)
    touch(visit)
    return response.ok_row(visit)


@bp.post("/crr/visits/<visit_id>/complete")
@endpoint("CrrTechnician")
def complete_visit(visit_id):
    visit = load_visit(visit_id)
    body = validation.json_body()
    validation.reject_unexpected_version(body)
    install_outcome = validation.req_enum(
        body, "install_outcome", domain.INSTALL_OUTCOMES
    )
    occupant_signature_name = validation.opt_str(body, "occupant_signature_name")
    if install_outcome == "DEFERRED":
        # PRD 3.6: the deferral branch requires a reason.
        deferral_reason = validation.req_enum(
            body, "deferral_reason", domain.DEFERRAL_REASONS
        )
    else:
        deferral_reason = validation.opt_enum(
            body, "deferral_reason", domain.DEFERRAL_REASONS
        )

    require_assigned_crew(visit)

    if visit["cancelled_at"] is not None or visit["install_status"] != "SURVEYED":
        raise ApiError("ERR_INVALID_VISIT_STATE")

    household = store.households.get(visit["household_id"])

    if install_outcome == "COMPLETE":
        smoke, carbon, strobe = installation_service.coverage_counts(visit)
        if (
            occupant_signature_name is None
            or occupant_signature_name.strip() == ""
            or household is None
            or smoke < household["required_smoke_devices"]
            or carbon < household["required_co_devices"]
            or strobe < household["required_strobe_devices"]
        ):
            raise ApiError("ERR_PLACEMENT_STANDARD_NOT_MET")

    visit["install_status"] = (
        "INSTALL_COMPLETE" if install_outcome == "COMPLETE" else "INSTALL_DEFERRED"
    )
    if occupant_signature_name is not None:
        visit["occupant_signature_name"] = occupant_signature_name
    if install_outcome == "DEFERRED":
        visit["deferral_reason"] = deferral_reason
    visit["completed_at"] = util.clock.now()
    visit_service.refresh_status(visit)
    touch(visit)

    if install_outcome == "COMPLETE":
        # PRD 3.6 hops one to four.
        for installation in installation_service.installations_of_visit(visit["id"]):
            if installation["status"] == "RESERVED":
                installation_service.commit(installation)
    else:
        installation_service.void_reserved_of_visit(visit, "DATA_ENTRY_ERROR")

    if household is not None:
        household_service.on_visit_completed(visit, household)
    return response.ok_row(visit)
