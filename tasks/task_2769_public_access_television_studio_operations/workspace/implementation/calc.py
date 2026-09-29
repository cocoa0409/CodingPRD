"""The eleven calculation rules of PRD section 3.

Every one of them is pure: it reads rows out of the store and returns values.
Nothing here mutates state.
"""

from decimal import Decimal

import constants
import db
from util import (
    add_months,
    apply_bp,
    ceil_div,
    clip_fraction,
    decimal_to_number,
    minutes_after_midnight,
    quantize2,
    seconds_after_midnight,
)


# --------------------------------------------------------------------------- #
# 1. producer certification level and competency codes (PRD 3.1)
# --------------------------------------------------------------------------- #
def passed_enrollments(producer_id):
    rows = [
        row
        for row in db.all_rows("course_enrollments")
        if row["producer_id"] == producer_id and row["status"] == "PASSED"
    ]
    # ordered by the graded_at of the enrollment that granted each code
    indexed = list(enumerate(rows))
    indexed.sort(key=lambda pair: (pair[1]["graded_at"] or pair[1]["created_at"], pair[0]))
    return [pair[1] for pair in indexed]


def competency_codes(producer):
    codes = []
    for enrollment in passed_enrollments(producer["id"]):
        course = db.get("training_courses", enrollment["course_id"])
        if course is None:
            continue
        for code in course["grants_competency_codes"]:
            if code not in codes:
                codes.append(code)
    return codes


def certification_level(producer):
    """Gated by membership status before anything else (PRD 3.1)."""
    if producer["status"] != "ACTIVE":
        return "NONE"
    tiers = set()
    for enrollment in passed_enrollments(producer["id"]):
        course = db.get("training_courses", enrollment["course_id"])
        if course is not None:
            tiers.add(course["tier"])
    if {"BASIC", "ADVANCED", "LIVE"}.issubset(tiers):
        return "LIVE"
    if {"BASIC", "ADVANCED"}.issubset(tiers):
        return "ADVANCED"
    if "BASIC" in tiers:
        return "BASIC"
    return "NONE"


# --------------------------------------------------------------------------- #
# 2. series seniority (PRD 3.2)
# --------------------------------------------------------------------------- #
def series_seniority_at(series):
    seniority = series["first_air_date"]
    visited = {series["id"]}
    cursor = series.get("predecessor_series_id")
    while cursor:
        if cursor in visited:
            break
        predecessor = db.get("series", cursor)
        if predecessor is None:
            break
        if predecessor["status"] == "RETIRED":
            break
        visited.add(predecessor["id"])
        if predecessor["first_air_date"] < seniority:
            seniority = predecessor["first_air_date"]
        cursor = predecessor.get("predecessor_series_id")
    return seniority


# --------------------------------------------------------------------------- #
# 3. playback window fit (PRD 3.4)
# --------------------------------------------------------------------------- #
def window_fit(channel, start_at, occupied_seconds):
    start_minute = minutes_after_midnight(start_at)
    if start_minute < channel["daily_window_start_minute"]:
        return False
    start_seconds = start_minute * 60 + start_at.second
    if start_seconds + occupied_seconds > channel["daily_window_end_minute"] * 60:
        return False
    return True


def slot_end_at(start_at, occupied_seconds):
    from util import add_seconds

    return add_seconds(start_at, occupied_seconds)


def intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end): touching intervals do not overlap."""
    return a_start < b_end and b_start < a_end


# --------------------------------------------------------------------------- #
# 5. reservation deposit hold (PRD 3.6)
# --------------------------------------------------------------------------- #
def risk_bp(producer):
    product = producer["suspension_points"] * constants.RISK_BP_PER_SUSPENSION_POINT
    return min(product, constants.RISK_BP_CAP)


def duration_bp(start_at, end_at):
    seconds = int((end_at - start_at).total_seconds())
    started_hours = ceil_div(max(seconds, 0), 3600)
    return max(started_hours - 1, 0) * constants.HOURLY_DEPOSIT_RATE_BP


def live_bp(reservation):
    slot_id = reservation.get("linked_slot_id")
    if not slot_id:
        return 0
    slot = db.get("playback_slots", slot_id)
    if slot is None:
        return 0
    program = db.get("programs", slot["program_id"])
    if program is None:
        return 0
    return constants.LIVE_LINK_SURCHARGE_BP if program["is_live"] else 0


def deposit_hold(producer, resource, reservation):
    """Three independently rounded lines, summed, then clamped."""
    base = resource["base_deposit_cents"]
    risk = risk_bp(producer)
    duration = duration_bp(reservation["start_at"], reservation["end_at"])
    live = live_bp(reservation)
    risk_line = apply_bp(base, 10000 + risk)
    duration_line = apply_bp(base, duration)
    live_line = apply_bp(base, live)
    total = risk_line + duration_line + live_line
    hold = min(total, resource["replacement_value_cents"])
    return risk, hold


# --------------------------------------------------------------------------- #
# 6. reservation final settlement (PRD 3.7)
# --------------------------------------------------------------------------- #
def late_fee(resource, reservation, returned_at):
    late_seconds = int((returned_at - reservation["end_at"]).total_seconds())
    if late_seconds < 0:
        late_seconds = 0
    started_late_hours = ceil_div(late_seconds, 3600)
    per_hour = apply_bp(resource["base_deposit_cents"], constants.LATE_FEE_BP_PER_HOUR)
    return per_hour * started_late_hours


def settlement(reservation, assessed_repair_cents):
    """Steps three through six of the waterfall."""
    hold = reservation["deposit_hold_cents"]
    charges = reservation["late_fee_cents"] + assessed_repair_cents
    forfeited = min(hold, charges)
    refunded = hold - forfeited
    uncovered = max(charges - hold, 0)
    return {
        "deposit_forfeited_cents": forfeited,
        "deposit_refunded_cents": refunded,
        "uncovered_liability_cents": uncovered,
    }


# --------------------------------------------------------------------------- #
# 7. damage penalty assessment (PRD 3.7)
# --------------------------------------------------------------------------- #
def damage_penalty(assessment, resource):
    assessed = min(assessment["repair_estimate_cents"], resource["replacement_value_cents"])
    points = constants.SUSPENSION_POINTS_BY_SEVERITY[assessment["severity"]]
    if assessed >= constants.REPAIR_ESCALATION_CENTS:
        points += 1
    return assessed, points


# --------------------------------------------------------------------------- #
# 8. crew staffing readiness (PRD 3.5)
# --------------------------------------------------------------------------- #
def staffing_status(slot):
    required = slot["required_crew_roles"] or []
    if not required:
        return "NOT_REQUIRED"
    covered = set()
    for assignment in db.all_rows("crew_assignments"):
        if assignment["slot_id"] != slot["id"]:
            continue
        if assignment["status"] in ("CONFIRMED", "COMPLETED"):
            covered.add(assignment["crew_role"])
    for role in required:
        if role not in covered:
            return "UNDERSTAFFED"
    return "READY"


def credited_hours_tenths(slot):
    return ceil_div(slot["occupied_seconds"], constants.SECONDS_PER_TENTH_HOUR)


# --------------------------------------------------------------------------- #
# 9. franchise fee allocation (PRD 3.8)
# --------------------------------------------------------------------------- #
def allocable_base(period, basis=None):
    effective = basis or period["basis"]
    if effective == "ACCRUAL":
        return period["service_period_earned_cents"]
    return period["remittance_received_cents"]


def franchise_allocation(period):
    base = allocable_base(period)
    rate = (
        constants.ADMIN_RESERVE_BP_HIGH
        if base >= constants.HIGH_TIER_THRESHOLD_CENTS
        else constants.ADMIN_RESERVE_BP_BASE
    )
    admin_reserve = apply_bp(base, rate)
    distributable = base - admin_reserve
    capital_share = apply_bp(distributable, constants.CAPITAL_RATE_BP)
    capital_allocation = capital_share + period["capital_grant_cents"]
    operating_allocation = distributable - capital_share
    total = base + period["capital_grant_cents"]
    return {
        "allocable_base_cents": base,
        "admin_reserve_cents": admin_reserve,
        "capital_allocation_cents": capital_allocation,
        "operating_allocation_cents": operating_allocation,
        "total_program_funds_cents": total,
    }


# --------------------------------------------------------------------------- #
# 10. community impact index (PRD 3.9)
# --------------------------------------------------------------------------- #
def community_impact_index(measured_households, on_demand_views, volunteer_hours_tenths, variant):
    if variant == "PROVISIONAL":
        on_demand_views = 0
        volunteer_hours_tenths = 0
    reach = clip_fraction(measured_households or 0, constants.HOUSEHOLD_NORM)
    demand = clip_fraction(on_demand_views or 0, constants.VIEW_NORM)
    volunteer = clip_fraction(volunteer_hours_tenths or 0, constants.VOLUNTEER_TENTHS_NORM)
    weighted = (
        reach * Decimal(constants.WEIGHT_REACH)
        + demand * Decimal(constants.WEIGHT_DEMAND)
        + volunteer * Decimal(constants.WEIGHT_VOLUNTEER)
    )
    return decimal_to_number(quantize2(Decimal(100) * weighted))


# --------------------------------------------------------------------------- #
# 11. archive retention deadline (PRD 3.9)
# --------------------------------------------------------------------------- #
def retain_until(published_at, retention_class):
    months = constants.RETENTION_MONTHS.get(retention_class)
    if months is None:
        return None
    return add_months(published_at, months)


__all__ = [
    "allocable_base",
    "certification_level",
    "community_impact_index",
    "competency_codes",
    "credited_hours_tenths",
    "damage_penalty",
    "deposit_hold",
    "duration_bp",
    "franchise_allocation",
    "intervals_overlap",
    "late_fee",
    "live_bp",
    "retain_until",
    "risk_bp",
    "seconds_after_midnight",
    "series_seniority_at",
    "settlement",
    "slot_end_at",
    "staffing_status",
    "window_fit",
]
