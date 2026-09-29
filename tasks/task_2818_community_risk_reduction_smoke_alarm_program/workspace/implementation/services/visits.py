"""Visit demand arithmetic, the buffered crew calendar and the compound
status projection (PRD 3.5)."""

from datetime import timedelta
from decimal import Decimal

import db
import domain
import util
from db import store, touch
from errors import ApiError
from services import households as household_service

TIER_MULTIPLIERS = {"TIER_1": Decimal("1.25"), "TIER_2": Decimal("1.10")}


def demand_minutes(household, zone):
    """PRD 3.5 time demand: max (not sum) of the two vulnerability allowances,
    a tier multiplier, then a five-minute grid snapped upward, floored and capped."""
    base = (
        domain.VISIT_BASE_MINUTES
        + 5 * (household["sleeping_areas_count"] - 1)
        + 5 * (household["storeys"] - 1)
    )
    accessibility = (
        15
        if (
            household["mobility_impaired_occupants"] > 0
            or household["hearing_impaired_occupants"] > 0
        )
        else 0
    )
    age = 0
    if household["children_under5"] > 0:
        age += 10
    if household["adults_65plus"] > 0:
        age += 10
    subtotal = base + max(accessibility, age)
    tier = zone["risk_tier"] if zone is not None else None
    multiplier = TIER_MULTIPLIERS.get(tier, Decimal("1.00"))
    raw = util.to_decimal(subtotal) * multiplier
    snapped = util.ceil_to_multiple(raw, domain.VISIT_GRID_MINUTES)
    return min(domain.VISIT_MAX_MINUTES, max(domain.VISIT_MIN_MINUTES, snapped))


def project_status(visit):
    """The six-step projection of PRD 3.5, first match wins."""
    if visit["cancelled_at"] is not None:
        return "CANCELLED"
    install = visit["install_status"]
    education = visit["education_status"]
    if install in domain.INSTALL_TERMINAL and education in domain.EDUCATION_TERMINAL:
        return "COMPLETED"
    if install in domain.INSTALL_TERMINAL and education == "PENDING":
        return "AWAITING_EDUCATION"
    if install == "SURVEYED" and education in domain.EDUCATION_TERMINAL:
        return "AWAITING_INSTALL_OUTCOME"
    if install == "SURVEYED":
        return "IN_PROGRESS"
    return "SCHEDULED"


def refresh_status(visit):
    visit["visit_status"] = project_status(visit)
    return visit["visit_status"]


def route_of(visit):
    return store.routes.get(visit["route_id"])


def visits_of_route(route_id):
    rows = [v for v in store.visits.values() if v["route_id"] == route_id]
    return db.by_created_at(rows)


def visits_of_household(household_id):
    rows = [v for v in store.visits.values() if v["household_id"] == household_id]
    return db.by_created_at(rows)


def occupations_for(candidate_route, exclude_visit_id=None):
    """Every visit occupying the candidate crew's calendar on that service date
    (PRD 3.5), excluding the visit being rescheduled."""
    result = []
    for visit in store.visits.values():
        if exclude_visit_id is not None and visit["id"] == exclude_visit_id:
            continue
        if not visit["occupies_crew_calendar"]:
            continue
        if project_status(visit) == "CANCELLED":
            continue
        route = route_of(visit)
        if route is None:
            continue
        if route["crew_id"] != candidate_route["crew_id"]:
            continue
        if route["service_date"] != candidate_route["service_date"]:
            continue
        result.append(visit)
    return db.by_created_at(result)


def check_window(route, start, end):
    """PRD 3.5 route window containment; travel buffers are deliberately excluded."""
    if start < route["window_start_utc"] or end > route["window_end_utc"]:
        raise ApiError("ERR_VISIT_OUTSIDE_ROUTE_WINDOW")


def check_interval(candidate_route, start, end, occupations):
    """PRD 3.5 buffered crew calendar; touching exactly at the buffer edge is
    not a conflict."""
    for existing in occupations:
        minutes = (
            domain.SAME_ROUTE_BUFFER_MINUTES
            if existing["route_id"] == candidate_route["id"]
            else domain.CROSS_ROUTE_BUFFER_MINUTES
        )
        buffer = timedelta(minutes=minutes)
        existing_start = existing["scheduled_start_utc"]
        existing_end = existing["scheduled_end_utc"]
        if start < existing_end + buffer and existing_start < end + buffer:
            raise ApiError("ERR_CREW_INTERVAL_CONFLICT")


def check_daily_minutes(crew, occupations, candidate_minutes):
    total = sum(v["demand_minutes"] for v in occupations) + candidate_minutes
    if total > crew["max_daily_minutes"]:
        raise ApiError("ERR_CREW_DAILY_MINUTES_EXCEEDED")


def has_open_visit(household_id, exclude_visit_id=None):
    for visit in visits_of_household(household_id):
        if exclude_visit_id is not None and visit["id"] == exclude_visit_id:
            continue
        if project_status(visit) in domain.VISIT_OPEN_STATUSES:
            return True
    return False


def cancel(visit, cancel_reason):
    """The full cancellation effect set of PRD 3.5, shared by the cancel
    endpoint and the route-closure cascade."""
    from services import installations as installation_service

    visit["cancelled_at"] = util.clock.now()
    visit["cancel_reason"] = cancel_reason
    visit["occupies_crew_calendar"] = False
    route = route_of(visit)
    if route is not None:
        route["booked_slot_count"] = route["booked_slot_count"] - 1
        touch(route)
    installation_service.void_reserved_of_visit(visit, "DATA_ENTRY_ERROR")
    refresh_status(visit)
    touch(visit)
    household = store.households.get(visit["household_id"])
    if household is not None:
        household_service.apply_cancel_branch(household, cancel_reason)


def cancel_for_route_closure(visit):
    """Route closure cancels a visit without touching the route's own slot
    accounting twice: the route row is bumped exactly once by the closure."""
    from services import installations as installation_service

    visit["cancelled_at"] = util.clock.now()
    visit["cancel_reason"] = "ROUTE_CLOSED"
    visit["occupies_crew_calendar"] = False
    route = route_of(visit)
    if route is not None:
        route["booked_slot_count"] = route["booked_slot_count"] - 1
    installation_service.void_reserved_of_visit(visit, "DATA_ENTRY_ERROR")
    refresh_status(visit)
    touch(visit)
    household = store.households.get(visit["household_id"])
    if household is not None:
        household_service.apply_cancel_branch(household, "ROUTE_CLOSED")
