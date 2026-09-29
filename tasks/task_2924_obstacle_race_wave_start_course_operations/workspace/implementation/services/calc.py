"""Calculation rules (PRD 2.9, 3.2, 3.3, 3.4, 3.7, 3.8, 3.9 / scaffold 1.3).

Every function here is a pure computation or a pure field-setter.  Version bumps
are the caller's responsibility (db.mutation / db.forced_mutation), so a single
operation never double-bumps a row.
"""

import math
from decimal import ROUND_HALF_UP, Decimal

import db

# --- constants -------------------------------------------------------------

BYPASS_RELIEF_FACTOR = Decimal("0.50")
BYPASS_RELIEF_CAP_PER_MIN = Decimal("8.00")
PARTIAL_STAFFING_FACTOR = Decimal("0.60")
FULL_STAFFING_FACTOR = Decimal("1.00")
ZERO_STAFFING_FACTOR = Decimal("0.00")

WAVE_INTERVAL_MINUTES = 15
MIN_OBSTACLES = 3
MIN_PROGRESSION_SCORE = Decimal("0.50")
MAX_REGRESSION = 2
MEDIC_PARTICIPANTS_PER_MEDIC = 250
WATER_SAFETY_PER_WATER_OBSTACLE = 2
CORRAL_OCCUPANCY_MINUTES = 6
STAFF_TRAVEL_BUFFER_MINUTES = 15
HOLDBACK_WINDOW_MINUTES = 45
MAX_PROTEST_ROUNDS = 2
LATE_PENALTY_PER_DAY_CENTS = 25000

RELIEF_BYPASS_MODES = ("PENALTY_LOOP", "TIMED_PENALTY")
NO_RELIEF_BYPASS_MODES = ("NONE", "MANDATORY")

CORRAL_OCCUPYING_RELEASE_STATUSES = ("SCHEDULED", "HELD", "RELEASED", "STARTED")
SCHEDULED_CAPACITY_RELEASE_STATUSES = ("SCHEDULED", "HELD", "RELEASED", "STARTED")

TWO_PLACES = Decimal("0.01")
WHOLE = Decimal("1")


# --- numeric helpers -------------------------------------------------------


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round2(value):
    """Two decimal places, rounded half up (PRD 2.9)."""
    return dec(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def round_cents(value):
    """Whole cents, rounded half up (PRD 2.9)."""
    return int(dec(value).quantize(WHOLE, rounding=ROUND_HALF_UP))


def floor_int(value):
    """Discard any fractional part (PRD 2.9 capacity regime)."""
    return int(dec(value).to_integral_value(rounding="ROUND_FLOOR"))


def ceil_div(numerator, denominator):
    return int(math.ceil(dec(numerator) / dec(denominator)))


# --- collection helpers ----------------------------------------------------


def course_of(row):
    return db.get("courses", row["course_id"])


def venue_of_course(course):
    return db.get("venues", course["venue_id"])


def obstacles_of_course(course_id):
    return db.where("obstacles", course_id=course_id)


def primary_obstacles(course_id):
    return [o for o in obstacles_of_course(course_id) if o.get("paired_obstacle_id") is None]


def waves_of_course(course_id):
    return db.where("waves", course_id=course_id)


def entries_of_wave(wave_id):
    return db.where("entries", wave_id=wave_id)


def attempts_of_entry(entry_id):
    rows = db.where("attempts", entry_id=entry_id)
    return sorted(rows, key=lambda a: (a["recorded_at"], a["created_at"], a["_seq"]))


def governing_permit(venue_id):
    """The single APPROVED application on the parcel, or None (PRD 3.1)."""
    approved = [p for p in db.where("permits", venue_id=venue_id) if p["status"] == "APPROVED"]
    if len(approved) == 1:
        return approved[0]
    return None


# --- obstacle clearance rates (PRD 3.2 / 3.3) ------------------------------


def design_clearance_rate(obstacle, course):
    lane_rate = dec(obstacle["lane_count"]) * dec(obstacle["service_rate_per_min"])
    if obstacle["bypass_mode"] in NO_RELIEF_BYPASS_MODES:
        relief = Decimal("0.00")
    else:
        relief = min(lane_rate * BYPASS_RELIEF_FACTOR, BYPASS_RELIEF_CAP_PER_MIN)
    corral = dec(course["corral_release_rate_per_min"])
    return round2(min(lane_rate + relief, corral))


def staffing_factor(obstacle):
    confirmed = int(obstacle["confirmed_marshal_count"])
    required = int(obstacle["marshals_required"])
    if confirmed >= required:
        return FULL_STAFFING_FACTOR
    half_required = int(math.ceil(required / 2.0))
    if confirmed >= half_required and confirmed >= 1:
        return PARTIAL_STAFFING_FACTOR
    return ZERO_STAFFING_FACTOR


def effective_clearance_rate(obstacle, course):
    factor = staffing_factor(obstacle)
    staffed_lane_rate = (
        dec(obstacle["lane_count"]) * dec(obstacle["service_rate_per_min"]) * factor
    )
    if obstacle["bypass_mode"] in NO_RELIEF_BYPASS_MODES:
        relief = Decimal("0.00")
    else:
        relief = min(staffed_lane_rate * BYPASS_RELIEF_FACTOR, BYPASS_RELIEF_CAP_PER_MIN)
    corral = dec(course["corral_release_rate_per_min"])
    return round2(min(staffed_lane_rate + relief, corral))


def staffing_state_for(confirmed, required):
    if confirmed == 0:
        return "UNSTAFFED"
    if confirmed < required:
        return "PARTIAL"
    return "MARSHALED"


def apply_obstacle_rates(obstacle, course=None):
    course = course or course_of(obstacle)
    obstacle["design_clearance_rate_per_min"] = design_clearance_rate(obstacle, course)
    obstacle["effective_clearance_rate_per_min"] = effective_clearance_rate(obstacle, course)


def apply_obstacle_staffing(obstacle, course=None):
    """Recount CONFIRMED marshals and recompute staffing state + live rate."""
    course = course or course_of(obstacle)
    confirmed = len(
        [
            a
            for a in db.where("staff_assignments", obstacle_id=obstacle["id"])
            if a["staff_role"] == "MARSHAL" and a["status"] == "CONFIRMED"
        ]
    )
    obstacle["confirmed_marshal_count"] = confirmed
    obstacle["staffing_state"] = staffing_state_for(confirmed, int(obstacle["marshals_required"]))
    obstacle["effective_clearance_rate_per_min"] = effective_clearance_rate(obstacle, course)


# --- course aggregates (PRD 3.2 / 3.3 / 3.4) -------------------------------


def design_capacity_pph(course):
    primaries = primary_obstacles(course["id"])
    if not primaries:
        return 0
    slowest = min(dec(o["design_clearance_rate_per_min"]) for o in primaries)
    return floor_int(Decimal("60") * slowest)


def bottleneck_capacity_pph(course):
    primaries = primary_obstacles(course["id"])
    if not primaries:
        return 0
    slowest = min(dec(o["effective_clearance_rate_per_min"]) for o in primaries)
    return floor_int(Decimal("60") * slowest)


def progression(course):
    """Returns (score rounded to 2dp, regression count)."""
    primaries = sorted(primary_obstacles(course["id"]), key=lambda o: o["station_index"])
    ratings = [int(o["difficulty_rating"]) for o in primaries]
    n = len(ratings)
    regressions = 0
    for i in range(n - 1):
        if ratings[i + 1] < ratings[i] - MAX_REGRESSION:
            regressions += 1
    if n < 2:
        return Decimal("0.00"), regressions
    rises = sum(max(0, ratings[i + 1] - ratings[i]) for i in range(n - 1))
    score = round2(dec(rises) / dec(n - 1))
    return score, regressions


def medics_required(course):
    return ceil_div(course["scheduled_capacity_total"], MEDIC_PARTICIPANTS_PER_MEDIC)


def water_obstacle_count(course):
    return len([o for o in obstacles_of_course(course["id"]) if o["water_contact"]])


def water_safety_required(course):
    return WATER_SAFETY_PER_WATER_OBSTACLE * water_obstacle_count(course)


def scheduled_capacity_total(course):
    return sum(
        int(w["capacity"])
        for w in waves_of_course(course["id"])
        if w["release_status"] in SCHEDULED_CAPACITY_RELEASE_STATUSES
    )


def confirmed_role_headcount(course_id, staff_role):
    return len(
        [
            a
            for a in db.where("staff_assignments", course_id=course_id)
            if a["staff_role"] == staff_role and a["status"] == "CONFIRMED"
        ]
    )


def apply_course_design_fields(course):
    """obstacle_count, difficulty_progression_score, design_capacity_pph."""
    course["obstacle_count"] = len(obstacles_of_course(course["id"]))
    score, _ = progression(course)
    course["difficulty_progression_score"] = score
    course["design_capacity_pph"] = design_capacity_pph(course)


def apply_course_staffing_fields(course):
    """medic_headcount, water_safety_headcount, bottleneck_capacity_pph."""
    course["medic_headcount"] = confirmed_role_headcount(course["id"], "MEDIC")
    course["water_safety_headcount"] = confirmed_role_headcount(course["id"], "WATER_SAFETY")
    course["bottleneck_capacity_pph"] = bottleneck_capacity_pph(course)


def apply_bottleneck(course):
    course["bottleneck_capacity_pph"] = bottleneck_capacity_pph(course)


def apply_scheduled_capacity(course):
    course["scheduled_capacity_total"] = scheduled_capacity_total(course)


def readiness_for(course):
    """PRD 3.3: FROZEN, else RESTRICTED, else OPEN."""
    venue = venue_of_course(course)
    if venue is None or venue["site_posture"] != "OPEN":
        return "FROZEN"
    if governing_permit(course["venue_id"]) is None:
        return "FROZEN"
    if course["medic_headcount"] < medics_required(course):
        return "RESTRICTED"
    if course["water_safety_headcount"] < water_safety_required(course):
        return "RESTRICTED"
    for obstacle in obstacles_of_course(course["id"]):
        if obstacle["staffing_state"] == "UNSTAFFED":
            return "RESTRICTED"
    return "OPEN"


def apply_readiness(course):
    course["readiness_posture"] = readiness_for(course)


# --- venue aggregates (PRD 3.1) -------------------------------------------


def disturbed_area(venue):
    total = 0
    for course in db.where("courses", venue_id=venue["id"]):
        for obstacle in obstacles_of_course(course["id"]):
            total += int(obstacle["footprint_sqm"])
    for service in db.where("festival_services", venue_id=venue["id"]):
        total += int(service["footprint_sqm"])
    return total


def apply_disturbed_area(venue):
    venue["disturbed_area_sqm"] = disturbed_area(venue)


def apply_bond_held(venue):
    venue["bond_held_cents"] = (
        int(venue["restoration_bond_cents"])
        - int(venue["bond_released_cents"])
        - int(venue["bond_forfeited_cents"])
    )


# --- capacity ceilings (PRD 3.4 / 3.6) ------------------------------------


def max_wave_capacity_design(course):
    return floor_int(dec(course["design_capacity_pph"]) * WAVE_INTERVAL_MINUTES / dec(60))


def max_wave_capacity_live(course):
    return floor_int(dec(course["bottleneck_capacity_pph"]) * WAVE_INTERVAL_MINUTES / dec(60))


# --- interval geometry (PRD 3.3 / 3.4) ------------------------------------


def corral_occupancy_load(course, scheduled_start_utc):
    """Aggregate capacity of overlapping half-open 6-minute corral windows."""
    cand_start = scheduled_start_utc
    cand_end = db.plus_minutes(cand_start, CORRAL_OCCUPANCY_MINUTES)
    load = 0
    for peer in waves_of_course(course["id"]):
        if peer["release_status"] not in CORRAL_OCCUPYING_RELEASE_STATUSES:
            continue
        peer_start = peer["scheduled_start_utc"]
        peer_end = db.plus_minutes(peer_start, CORRAL_OCCUPANCY_MINUTES)
        if peer_start < cand_end and cand_start < peer_end:
            load += int(peer["capacity"])
    return load


def has_shift_conflict(staff_person_id, shift_start_utc, shift_end_utc):
    """Pairwise closed intervals inflated by the travel buffer on both sides."""
    buffer_minutes = STAFF_TRAVEL_BUFFER_MINUTES
    for peer in db.where("staff_assignments", staff_person_id=staff_person_id):
        if peer["status"] != "CONFIRMED":
            continue
        peer_start = peer["shift_start_utc"]
        peer_end = peer["shift_end_utc"]
        if shift_start_utc < db.plus_minutes(peer_end, buffer_minutes) and peer_start < db.plus_minutes(
            shift_end_utc, buffer_minutes
        ):
            return True
    return False


def in_quiet_window(hour, start_hour, end_hour):
    """Half-open [start, end), wrapping past midnight when start > end."""
    if start_hour == end_hour:
        return False
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def age_at_wave(participant, wave):
    return wave["scheduled_start_utc"].year - int(participant["birth_year"])
