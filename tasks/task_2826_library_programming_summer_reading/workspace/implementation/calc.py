"""The thirteen calculations of PRD section 3, and their constants."""

from datetime import timedelta

from core import (
    add_days,
    clock,
    date_of,
    floor_div_rate,
    pct_one_dp,
    rate_cents,
)

# ---------------------------------------------------------------- constants
MILEAGE_FREE_MILES = 20
MILEAGE_TIER1_LIMIT_MILES = 60
MILEAGE_TIER1_RATE_CENTS = 65
MILEAGE_TIER2_RATE_CENTS = 45
MINORS_ESCORT_FEE_CENTS = 4000
INSURANCE_RIDER_FEE_CENTS = 2500
INSURANCE_RIDER_WINDOW_DAYS = 30
WEEKEND_PREMIUM_RATE = "0.10"
PROGRAM_FEE_CAP_CENTS = 250000
WEATHER_KILL_FEE_RATE = "0.50"
WEATHER_KILL_FEE_WINDOW_HOURS = 48
LIBRARY_CANCEL_LATE_WINDOW_DAYS = 14
LIBRARY_CANCEL_EARLY_RATE = "0.25"
PRESENTER_TRAVEL_BUFFER_MINUTES = 90
SCREENING_VALIDITY_DAYS_NAME_CHECK = 365
SCREENING_VALIDITY_DAYS_FINGERPRINT = 730
ACCESSIBLE_SETUP_MINUTES = 30
WHEELCHAIR_LAYOUT_SEAT_LOSS_RATE = "0.15"
WHEELCHAIR_LAYOUT_REMAINING_RATE = "0.85"
CROSS_BRANCH_SURCHARGE_RATE = "0.08"
MATERIALS_CONTINGENCY_LOW_RATE = "0.10"
MATERIALS_CONTINGENCY_HIGH_RATE = "0.05"
MATERIALS_CONTINGENCY_THRESHOLD_CENTS = 20000
DAILY_LOG_CAP_MINUTES = 300
DAILY_LOG_CAP_BOOKS = 10
DAILY_LOG_CAP_ACTIVITIES = 5
MAX_NEGOTIATION_ROUNDS = 3

MINOR_AGE_GROUPS = ("EARLY_CHILDHOOD", "SCHOOL_AGE", "TEEN", "ALL_AGES")

DAILY_CAPS = {
    "MINUTES": DAILY_LOG_CAP_MINUTES,
    "BOOKS": DAILY_LOG_CAP_BOOKS,
    "ACTIVITIES": DAILY_LOG_CAP_ACTIVITIES,
}

ACCESSIBILITY_ROOM_REQUIREMENT = {
    "WHEELCHAIR_LAYOUT": "WHEELCHAIR_ACCESSIBLE",
    "ASL_INTERPRETER": "HEARING_LOOP",
    "SENSORY_QUIET_HOUR": "QUIET_ZONE",
}


# ------------------------------------------------------------ 1. serves_minors
def serves_minors(age_group):
    return age_group in MINOR_AGE_GROUPS


# --------------------------------------------- 2. room_effective_capacity
def room_effective_capacity(capacity_seats, accommodations):
    """Wheelchair layouts lose seats, and the loss is FLOORED."""
    if "WHEELCHAIR_LAYOUT" in (accommodations or []):
        return floor_div_rate(capacity_seats, WHEELCHAIR_LAYOUT_REMAINING_RATE)
    return int(capacity_seats)


# ------------------------------------------- 3. room_occupancy_interval
def occupancy_interval(start_utc, end_utc, setup_minutes, teardown_minutes):
    return (
        start_utc - timedelta(minutes=int(setup_minutes)),
        end_utc + timedelta(minutes=int(teardown_minutes)),
    )


def intervals_overlap_half_open(a_start, a_end, b_start, b_end):
    """Half-open [start, end): touching at a single instant is NOT a conflict."""
    return a_start < b_end and b_start < a_end


def intervals_overlap_closed(a_start, a_end, b_start, b_end):
    """Closed [start, end]: touching at a single instant IS a conflict."""
    return a_start <= b_end and b_start <= a_end


# ------------------------------------------------ 4. required setup floor
def required_setup_minutes(room, accommodations):
    floor_minutes = int(room["min_setup_minutes"])
    if accommodations:
        floor_minutes = max(floor_minutes, ACCESSIBLE_SETUP_MINUTES)
    return floor_minutes


# ------------------------------------------------------ 5. presenter window
def presenter_engagement_window(program):
    buffer_delta = timedelta(minutes=PRESENTER_TRAVEL_BUFFER_MINUTES)
    return (program["start_utc"] - buffer_delta, program["end_utc"] + buffer_delta)


# ----------------------------------------------------- 6. contract_total_fee
def travel_fee_cents(round_trip_miles):
    miles = int(round_trip_miles)
    band1 = min(miles, MILEAGE_TIER1_LIMIT_MILES) - MILEAGE_FREE_MILES
    if band1 < 0:
        band1 = 0
    band2 = miles - MILEAGE_TIER1_LIMIT_MILES
    if band2 < 0:
        band2 = 0
    return band1 * MILEAGE_TIER1_RATE_CENTS + band2 * MILEAGE_TIER2_RATE_CENTS


def contract_total_fee(contract, program, presenter):
    """Ordered pricing sequence; the premium sits on the whole subtotal."""
    base = int(contract.get("offered_fee_cents") or 0)
    travel = travel_fee_cents(contract["round_trip_miles"])
    escort = MINORS_ESCORT_FEE_CENTS if program["serves_minors"] else 0

    program_end_date = date_of(program["end_utc"])
    rider_limit = add_days(program_end_date, INSURANCE_RIDER_WINDOW_DAYS)
    rider = 0
    if presenter["insurance_certificate_expires_on"] < rider_limit:
        rider = INSURANCE_RIDER_FEE_CENTS

    subtotal = base + travel + escort + rider

    weekend = 0
    if program["start_utc"].weekday() in (5, 6):
        weekend = rate_cents(subtotal, WEEKEND_PREMIUM_RATE)

    return {
        "agreed_fee_cents": base,
        "travel_fee_cents": travel,
        "escort_fee_cents": escort,
        "insurance_rider_fee_cents": rider,
        "weekend_premium_cents": weekend,
        "total_fee_cents": subtotal + weekend,
    }


def fee_cap_cents(branch):
    return min(PROGRAM_FEE_CAP_CENTS, int(branch["per_program_fee_cap_cents"]))


# ------------------------------------------- 7. contract_cancellation_fee
def weather_kill_fee_cents(total_fee_cents_value, program):
    total = int(total_fee_cents_value or 0)
    if total == 0:
        return 0
    notice_hours = (program["start_utc"] - clock.now()).total_seconds() / 3600.0
    if notice_hours <= WEATHER_KILL_FEE_WINDOW_HOURS:
        return rate_cents(total, WEATHER_KILL_FEE_RATE)
    return 0


def library_kill_fee_cents(total_fee_cents_value, program):
    total = int(total_fee_cents_value or 0)
    if total == 0:
        return 0
    notice_days = (date_of(program["start_utc"]) - clock.today()).days
    if notice_days < LIBRARY_CANCEL_LATE_WINDOW_DAYS:
        return total
    return rate_cents(total, LIBRARY_CANCEL_EARLY_RATE)


# -------------------------------------------- 8. screening_validity_window
def screening_valid_until(decided_on, screening_tier):
    days = (
        SCREENING_VALIDITY_DAYS_FINGERPRINT
        if screening_tier == "FINGERPRINT"
        else SCREENING_VALIDITY_DAYS_NAME_CHECK
    )
    return add_days(decided_on, days)


def screening_status(presenter):
    decision = presenter.get("screening_decision") or "NONE"
    if decision == "NONE":
        return "NONE"
    if decision == "PENDING":
        return "PENDING"
    if decision == "FLAGGED":
        return "PENDING_ADJUDICATION"
    if decision == "DENIED":
        return "BLOCKED"
    valid_until = presenter.get("screening_valid_until")
    if valid_until is None:
        return "EXPIRED"
    if clock.today() <= valid_until:
        return "ACTIVE"
    return "EXPIRED"


# ------------------------------------------------- 9. materials contingency
def materials_contingency_cents(draw_subtotal_cents):
    rate = (
        MATERIALS_CONTINGENCY_LOW_RATE
        if draw_subtotal_cents < MATERIALS_CONTINGENCY_THRESHOLD_CENTS
        else MATERIALS_CONTINGENCY_HIGH_RATE
    )
    return rate_cents(draw_subtotal_cents, rate)


def materials_commitment_cents(draw_subtotal_cents):
    return draw_subtotal_cents + materials_contingency_cents(draw_subtotal_cents)


def cross_branch_surcharge_cents(base_cents, lot_branch_id, home_branch_id):
    if lot_branch_id == home_branch_id:
        return 0
    return rate_cents(base_cents, CROSS_BRANCH_SURCHARGE_RATE)


# ------------------------------------- 10. program_attendance_attainment
def attendance_outcomes(program, verified, drop_in, surveys):
    gross = verified + drop_in
    no_show = program["registered_count"] - verified
    if no_show < 0:
        no_show = 0
    survey_rate = pct_one_dp(surveys, gross) if gross else 0.0
    funder = pct_one_dp(gross, program["attendance_target"])
    internal_denominator = program["confirmed_room_capacity"]
    if not internal_denominator:
        internal_denominator = program["attendance_target"]
    internal = pct_one_dp(gross, internal_denominator)
    return {
        "gross_attendance": gross,
        "no_show_count": no_show,
        "survey_response_rate_pct": survey_rate,
        "attendance_attainment_funder_pct": funder,
        "attendance_attainment_internal_pct": internal,
    }
