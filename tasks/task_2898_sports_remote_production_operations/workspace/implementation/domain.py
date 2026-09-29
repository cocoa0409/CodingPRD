"""Domain layer: constants, serializers, calculations and the production-stage derivation."""

from decimal import Decimal

import store
from core import (
    ceil_div,
    fmt_dt,
    minutes_later,
    money,
    rhu,
    now_utc,
    two_dp,
    whole_minutes,
)

# ---------------------------------------------------------------------------
# constants (SCAFFOLD calculations.*.constants)
# ---------------------------------------------------------------------------
LOSS_DB_PER_100FT = Decimal("1.35")
MAX_SIGNAL_LOSS_BUDGET_DB = Decimal("10.13")

MAX_SURVEY_REVISIONS = 3
MAX_TEST_ATTEMPTS = 3
MAX_FEED_LATENCY_MS = 250

TURNAROUND_MINUTES = 600
STRAIGHT_MINUTES_CAP = 600
DOUBLE_TIME_MINUTES_CAP = 720
OT_MULTIPLIER = Decimal("1.5")
DT_MULTIPLIER = Decimal("2.0")
MEAL_WINDOW_MINUTES = 360
MEAL_PENALTY_INCREMENT_MINUTES = 30
MEAL_PENALTY_UNIT_CENTS = 3500
MEAL_PENALTY_UNIT_CAP = 4
TIER_1_PENALTY_MULTIPLIER = Decimal("1.5")

SURVEY_WEIGHT = 40
TRANSMISSION_WEIGHT = 25
SYSTEMS_WEIGHT = 20
CREW_WEIGHT = 15

REQUIRED_CREW_POSITIONS = {"TIER_1": 12, "TIER_2": 4, "TIER_3": 2}
REQUIRED_VALIDATED_PREPS = {"TIER_1": 3, "TIER_2": 2, "TIER_3": 1}
TIER_ORDER = {"TIER_1": 1, "TIER_2": 2, "TIER_3": 3}

OVERRUN_BRACKET_MID = 500000
OVERRUN_BRACKET_HIGH = 2000000
OVERRUN_RATE_LOW = 1200
OVERRUN_RATE_MID = 1800
OVERRUN_RATE_HIGH = 2400

TRAVEL_IN_HOURS = 24
TEARDOWN_OUT_HOURS = 12
TRAVEL_HOURS_PER_EVENT = 8
SETUP_TEARDOWN_HOURS = 4

MAX_TECHNICAL_DOWNTIME_MINUTES = 20

ACTIVE_BOOKING_STATUSES = ("RESERVED", "TEST_SCHEDULED", "TEST_FAILED", "CONFIRMED", "PROMOTED")
OPEN_SURVEY_STATUSES = ("DRAFT", "SUBMITTED", "CHANGES_REQUESTED")
LIVE_CALL_STATUSES = ("OFFERED", "ACCEPTED", "RELEASED")
CLOSED_PRODUCTION_STATUSES = ("ON_AIR", "WRAPPED", "SETTLED")

# enum vocabularies
EVENT_TIERS = ("TIER_1", "TIER_2", "TIER_3")
ROOF_TYPES = ("OPEN", "DOMED", "RETRACTABLE")
PRODUCTION_STATUSES = (
    "PLANNED",
    "SURVEYED",
    "PROVISIONED",
    "REHEARSED",
    "ON_AIR",
    "WRAPPED",
    "SETTLED",
)
TRUCK_STATUSES = ("AVAILABLE", "ASSIGNED", "IN_TRANSIT", "IN_MAINTENANCE")
SURVEY_STATUSES = ("DRAFT", "SUBMITTED", "CHANGES_REQUESTED", "APPROVED", "SUPERSEDED")
POSITION_TYPES = ("HARD", "HANDHELD", "ROBO", "AERIAL")
OPERATOR_POSITION_TYPES = ("HARD", "HANDHELD", "AERIAL")
PATH_TYPES = ("SATELLITE", "FIBER")
REDUNDANCY_CLASSES = ("PRIMARY_ELIGIBLE", "BACKUP_ONLY")
BOOKING_ROLES = ("PRIMARY", "BACKUP")
BOOKING_STATUSES = (
    "RESERVED",
    "TEST_SCHEDULED",
    "TEST_FAILED",
    "CONFIRMED",
    "FAILED_OVER",
    "PROMOTED",
    "RELEASED",
)
CREW_POSITIONS = ("TD", "EIC", "A1", "CAM_OP", "REPLAY_OP", "GRAPHICS_OP", "STATS_OP", "UTILITY")
EMPLOYMENT_TYPES = ("STAFF", "FREELANCE")
CALL_STATUSES = ("OFFERED", "ACCEPTED", "DECLINED", "RELEASED", "CANCELLED")
FEED_KINDS = ("LIVE_STATS", "OFFICIAL_SCORING", "PLAYER_TRACKING")
FEED_STATUSES = ("ACTIVE", "SUSPENDED")
SYSTEM_KINDS = ("GRAPHICS", "STATS", "REPLAY")
PREP_STATUSES = ("PENDING", "VALIDATED", "FAILED")
REHEARSAL_STATUSES = ("SCHEDULED", "COMPLETED", "ABORTED")
AIR_STATUSES = ("PRE_SHOW", "ON_AIR", "IN_EXTENDED_PLAY", "OFF_AIR")
SIGNAL_STATUSES = ("NOMINAL", "ON_BACKUP", "LOST")
INCIDENT_KINDS = ("WEATHER_HOLD", "TECHNICAL_FAILURE", "EXTENDED_PLAY", "PATH_LOSS")
SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")


# ---------------------------------------------------------------------------
# serializers
# ---------------------------------------------------------------------------
def _common(row, out):
    out["id"] = row["id"]
    out["created_at"] = fmt_dt(row["_created"])
    if "version" in row:
        out["updated_at"] = fmt_dt(row["_updated"])
        out["version"] = row["version"]
    return out


def _num(value):
    """Emit an integral number as int and anything else as float."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def truck_json(row):
    return _common(
        row,
        {
            "truck_code": row["truck_code"],
            "tier_rating": row["tier_rating"],
            "camera_channel_capacity": row["camera_channel_capacity"],
            "power_draw_amps": row["power_draw_amps"],
            "home_base_code": row["home_base_code"],
            "engine_hours_since_service": _num(row["engine_hours_since_service"]),
            "service_interval_hours": row["service_interval_hours"],
            "hours_to_service": _num(row["hours_to_service"]),
            "last_service_completed_at": fmt_dt(row["last_service_completed_at"]),
            "status": row["status"],
        },
    )


def production_json(row):
    return _common(
        row,
        {
            "event_tier": row["event_tier"],
            "league_code": row["league_code"],
            "venue_name": row["venue_name"],
            "venue_power_capacity_amps": row["venue_power_capacity_amps"],
            "venue_roof_type": row["venue_roof_type"],
            "venue_curfew_utc": fmt_dt(row["venue_curfew_utc"]),
            "scheduled_start_utc": fmt_dt(row["scheduled_start_utc"]),
            "scheduled_end_utc": fmt_dt(row["scheduled_end_utc"]),
            "truck_id": row["truck_id"],
            "labor_budget_total_cents": row["labor_budget_total_cents"],
            "labor_committed_cents": row["labor_committed_cents"],
            "labor_available_cents": row["labor_available_cents"],
            "labor_variance_cents": row["labor_variance_cents"],
            "readiness_score_preflight": row["readiness_score_preflight"],
            "readiness_score_certified": row["readiness_score_certified"],
            "required_crew_positions": row["required_crew_positions"],
            "required_validated_preps": row["required_validated_preps"],
            "settlement_total_cents": row["settlement_total_cents"],
            "overrun_fee_cents": row["overrun_fee_cents"],
            "wrapped_by_user_id": row["wrapped_by_user_id"],
            "status": row["status"],
        },
    )


def survey_json(row):
    return _common(
        row,
        {
            "production_id": row["production_id"],
            "surveyor_name": row["surveyor_name"],
            "fiber_drops_required": row["fiber_drops_required"],
            "revision": row["revision"],
            "submitted_by_user_id": row["submitted_by_user_id"],
            "reviewed_by_user_id": row["reviewed_by_user_id"],
            "camera_position_count": row["camera_position_count"],
            "total_cable_run_feet": row["total_cable_run_feet"],
            "total_signal_loss_db": row["total_signal_loss_db"],
            "total_power_draw_amps": row["total_power_draw_amps"],
            "power_headroom_amps": row["power_headroom_amps"],
            "status": row["status"],
        },
    )


def camera_position_json(row):
    return _common(
        row,
        {
            "survey_id": row["survey_id"],
            "label": row["label"],
            "position_type": row["position_type"],
            "cable_run_feet": row["cable_run_feet"],
            "power_draw_amps": row["power_draw_amps"],
            "signal_loss_db": row["signal_loss_db"],
            "requires_operator": row["requires_operator"],
        },
    )


def path_json(row):
    return _common(
        row,
        {
            "path_code": row["path_code"],
            "path_type": row["path_type"],
            "carrier_code": row["carrier_code"],
            "capacity_mbps": row["capacity_mbps"],
            "guard_band_minutes": row["guard_band_minutes"],
            "redundancy_class": row["redundancy_class"],
            "committed_mbps_total": row["committed_mbps_total"],
            "active_booking_count": row["active_booking_count"],
        },
    )


def booking_json(row):
    return _common(
        row,
        {
            "production_id": row["production_id"],
            "path_id": row["path_id"],
            "booking_role": row["booking_role"],
            "window_start_utc": fmt_dt(row["window_start_utc"]),
            "window_end_utc": fmt_dt(row["window_end_utc"]),
            "requested_mbps": row["requested_mbps"],
            "test_window_start_utc": fmt_dt(row["test_window_start_utc"]),
            "test_window_end_utc": fmt_dt(row["test_window_end_utc"]),
            "test_attempt_count": row["test_attempt_count"],
            "status": row["status"],
        },
    )


def crew_member_json(row):
    return _common(
        row,
        {
            "full_name": row["full_name"],
            "position": row["position"],
            "employment_type": row["employment_type"],
            "union_local": row["union_local"],
            "certified_tiers": list(row["certified_tiers"]),
            "hourly_rate_cents": row["hourly_rate_cents"],
            "home_base_code": row["home_base_code"],
            "lifetime_meal_penalty_units": row["lifetime_meal_penalty_units"],
        },
    )


def crew_call_json(row):
    return _common(
        row,
        {
            "production_id": row["production_id"],
            "crew_member_id": row["crew_member_id"],
            "call_time_utc": fmt_dt(row["call_time_utc"]),
            "scheduled_release_utc": fmt_dt(row["scheduled_release_utc"]),
            "offer_rate_cents": row["offer_rate_cents"],
            "effective_rate_cents": row["effective_rate_cents"],
            "actual_release_utc": fmt_dt(row["actual_release_utc"]),
            "meal_break_start_utc": fmt_dt(row["meal_break_start_utc"]),
            "turnaround_minutes_before_call": row["turnaround_minutes_before_call"],
            "meal_penalty_units": row["meal_penalty_units"],
            "provisional_total_cents": row["provisional_total_cents"],
            "settled_total_cents": row["settled_total_cents"],
            "status": row["status"],
        },
    )


def feed_json(row):
    return _common(
        row,
        {
            "provider_code": row["provider_code"],
            "feed_kind": row["feed_kind"],
            "latency_ms": row["latency_ms"],
            "contract_expiry_utc": fmt_dt(row["contract_expiry_utc"]),
            "max_concurrent_consumers": row["max_concurrent_consumers"],
            "active_consumer_count": row["active_consumer_count"],
            "status": row["status"],
        },
    )


def prep_json(row):
    return _common(
        row,
        {
            "production_id": row["production_id"],
            "data_feed_id": row["data_feed_id"],
            "system_kind": row["system_kind"],
            "replay_channel_count": row["replay_channel_count"],
            "feed_validated_at": fmt_dt(row["feed_validated_at"]),
            "status": row["status"],
        },
    )


def rehearsal_json(row):
    return _common(
        row,
        {
            "production_id": row["production_id"],
            "scheduled_start_utc": fmt_dt(row["scheduled_start_utc"]),
            "camera_blocking_positions_cleared": row["camera_blocking_positions_cleared"],
            "venue_signoff": row["venue_signoff"],
            "league_ops_signoff": row["league_ops_signoff"],
            "outcome_notes": row["outcome_notes"],
            "status": row["status"],
        },
    )


def show_json(row):
    return _common(
        row,
        {
            "production_id": row["production_id"],
            "air_status": row["air_status"],
            "signal_status": row["signal_status"],
            "readiness_hold": row["readiness_hold"],
            "weather_hold_minutes": row["weather_hold_minutes"],
            "extended_play_minutes": row["extended_play_minutes"],
            "technical_downtime_minutes": row["technical_downtime_minutes"],
            "on_air_at_utc": fmt_dt(row["on_air_at_utc"]),
            "off_air_at_utc": fmt_dt(row["off_air_at_utc"]),
            "air_minutes_total": row["air_minutes_total"],
        },
    )


def incident_json(row):
    return _common(
        row,
        {
            "show_execution_id": row["show_execution_id"],
            "kind": row["kind"],
            "started_at_utc": fmt_dt(row["started_at_utc"]),
            "duration_minutes": row["duration_minutes"],
            "severity": row["severity"],
            "note": row["note"],
        },
    )


# ---------------------------------------------------------------------------
# aggregate maintenance
# ---------------------------------------------------------------------------
def recompute_path_aggregates(path):
    """path.committed_mbps_total / active_booking_count over the five ACTIVE statuses."""
    total = 0
    count = 0
    for booking in store.ordered(store.BOOKINGS):
        if booking["path_id"] == path["id"] and booking["status"] in ACTIVE_BOOKING_STATUSES:
            total += booking["requested_mbps"]
            count += 1
    store.set_fields(path, committed_mbps_total=total, active_booking_count=count)


def recompute_feed_consumers(feed):
    count = 0
    for prep in store.ordered(store.PREPS):
        if prep["data_feed_id"] == feed["id"] and prep["status"] == "VALIDATED":
            count += 1
    store.set_fields(feed, active_consumer_count=count)


def position_signal_loss(cable_run_feet):
    return two_dp(Decimal(cable_run_feet) * LOSS_DB_PER_100FT / Decimal(100))


def recompute_survey_aggregates(survey):
    """PINNED ORDER: per-position 2dp values are summed, then the sum is re-rounded to 2dp."""
    positions = [
        row
        for row in store.ordered(store.CAMERA_POSITIONS)
        if row["survey_id"] == survey["id"]
    ]
    count = len(positions)
    cable = sum(row["cable_run_feet"] for row in positions)
    amps = sum(row["power_draw_amps"] for row in positions)
    loss = Decimal("0")
    for row in positions:
        loss += Decimal(str(row["signal_loss_db"]))
    production = store.PRODUCTIONS.get(survey["production_id"])
    capacity = production["venue_power_capacity_amps"] if production else 0
    store.set_fields(
        survey,
        camera_position_count=count,
        total_cable_run_feet=cable,
        total_power_draw_amps=amps,
        total_signal_loss_db=two_dp(rhu(loss, 2)),
        power_headroom_amps=capacity - amps,
    )


def survey_total_loss_decimal(survey):
    return Decimal(str(survey["total_signal_loss_db"]))


# ---------------------------------------------------------------------------
# crew_call_labor_cost (calculations.crew_call_labor_cost)
# ---------------------------------------------------------------------------
def _band_cents(rate, minutes, multiplier=None):
    amount = Decimal(rate) * Decimal(minutes)
    if multiplier is not None:
        amount = amount * multiplier
    return money(amount / Decimal(60))


def _meal_units_from_worked(worked_minutes):
    if worked_minutes <= MEAL_WINDOW_MINUTES:
        return 0
    units = ceil_div(worked_minutes - MEAL_WINDOW_MINUTES, MEAL_PENALTY_INCREMENT_MINUTES)
    return min(units, MEAL_PENALTY_UNIT_CAP)


def _meal_units_from_break(call_time, break_start):
    delay = whole_minutes(call_time, break_start) - MEAL_WINDOW_MINUTES
    if delay <= 0:
        return 0
    return min(ceil_div(delay, MEAL_PENALTY_INCREMENT_MINUTES), MEAL_PENALTY_UNIT_CAP)


def call_cost(call, production, release_reference, settled=False):
    """Returns (total_cents, meal_penalty_units) for the requested variant."""
    rate = call["effective_rate_cents"]
    worked = whole_minutes(call["call_time_utc"], release_reference)
    if worked < 0:
        worked = 0

    straight = min(worked, STRAIGHT_MINUTES_CAP)
    overtime = max(0, min(worked, DOUBLE_TIME_MINUTES_CAP) - STRAIGHT_MINUTES_CAP)
    double = max(0, worked - DOUBLE_TIME_MINUTES_CAP)

    # ROUNDING ORDER PINNED: each band is rounded to whole cents first, then summed.
    labor_cents = (
        _band_cents(rate, straight)
        + _band_cents(rate, overtime, OT_MULTIPLIER)
        + _band_cents(rate, double, DT_MULTIPLIER)
    )

    if settled and call["meal_break_start_utc"] is not None:
        units = _meal_units_from_break(call["call_time_utc"], call["meal_break_start_utc"])
    else:
        units = _meal_units_from_worked(worked)

    multiplier = (
        TIER_1_PENALTY_MULTIPLIER if production["event_tier"] == "TIER_1" else Decimal("1")
    )
    penalty_cents = money(Decimal(units) * Decimal(MEAL_PENALTY_UNIT_CENTS) * multiplier)
    return labor_cents + penalty_cents, units


def provisional_cost(call, production):
    return call_cost(call, production, call["scheduled_release_utc"], settled=False)


def settled_cost(call, production):
    return call_cost(call, production, call["actual_release_utc"], settled=True)


# ---------------------------------------------------------------------------
# crew_turnaround_reference
# ---------------------------------------------------------------------------
def reference_release(call):
    if call["status"] == "RELEASED" and call["actual_release_utc"] is not None:
        return call["actual_release_utc"]
    return call["scheduled_release_utc"]


def prior_call_for_member(member_id, exclude_call_id=None):
    """Latest-releasing candidate; ties broken by created_at ASC (never by id)."""
    best = None
    best_key = None
    for call in store.ordered(store.CREW_CALLS):
        if call["crew_member_id"] != member_id or call["status"] not in LIVE_CALL_STATUSES:
            continue
        if exclude_call_id is not None and call["id"] == exclude_call_id:
            continue
        key = reference_release(call)
        if best is None or key > best_key:
            best = call
            best_key = key
    return best


# ---------------------------------------------------------------------------
# per-production row views
# ---------------------------------------------------------------------------
def production_surveys(production):
    return [r for r in store.ordered(store.SURVEYS) if r["production_id"] == production["id"]]


def production_bookings(production):
    return [r for r in store.ordered(store.BOOKINGS) if r["production_id"] == production["id"]]


def production_preps(production):
    return [r for r in store.ordered(store.PREPS) if r["production_id"] == production["id"]]


def production_calls(production):
    return [r for r in store.ordered(store.CREW_CALLS) if r["production_id"] == production["id"]]


def production_rehearsals(production):
    return [r for r in store.ordered(store.REHEARSALS) if r["production_id"] == production["id"]]


def production_shows(production):
    return [r for r in store.ordered(store.SHOWS) if r["production_id"] == production["id"]]


def approved_survey(production):
    for row in production_surveys(production):
        if row["status"] == "APPROVED":
            return row
    return None


def production_show(production):
    """The show record that carries the air history of this production."""
    rows = production_shows(production)
    if not rows:
        return None
    for row in rows:
        if row["air_status"] == "OFF_AIR":
            return row
    for row in rows:
        if row["on_air_at_utc"] is not None:
            return row
    return rows[0]


# ---------------------------------------------------------------------------
# production_labor_commitment + production_readiness_score
# ---------------------------------------------------------------------------
def labor_committed(production):
    total = 0
    for call in production_calls(production):
        if call["status"] in ("OFFERED", "ACCEPTED"):
            total += call["provisional_total_cents"]
        elif call["status"] == "RELEASED":
            total += call["settled_total_cents"] or 0
    return total


def _readiness(production, transmission_statuses, prep_statuses, call_statuses):
    survey_component = SURVEY_WEIGHT if approved_survey(production) is not None else 0

    transmission_component = 0
    for booking in production_bookings(production):
        if booking["booking_role"] == "PRIMARY" and booking["status"] in transmission_statuses:
            transmission_component = TRANSMISSION_WEIGHT
            break

    prep_count = sum(1 for p in production_preps(production) if p["status"] in prep_statuses)
    systems_component = (
        SYSTEMS_WEIGHT if prep_count >= production["required_validated_preps"] else 0
    )

    crew_count = sum(1 for c in production_calls(production) if c["status"] in call_statuses)
    required = production["required_crew_positions"]
    capped = min(crew_count, required)
    crew_component = rhu(Decimal(CREW_WEIGHT * capped) / Decimal(required), 2)

    total = rhu(
        Decimal(survey_component + transmission_component + systems_component) + crew_component,
        2,
    )
    return two_dp(total)


def readiness_preflight(production):
    return _readiness(
        production,
        ("RESERVED", "TEST_SCHEDULED", "CONFIRMED", "PROMOTED"),
        ("PENDING", "VALIDATED"),
        ("OFFERED", "ACCEPTED"),
    )


def readiness_certified(production):
    return _readiness(
        production,
        ("CONFIRMED", "PROMOTED"),
        ("VALIDATED",),
        ("ACCEPTED",),
    )


def provisioning_conditions(production):
    if production["truck_id"] is None:
        return False
    primary_ok = False
    for booking in production_bookings(production):
        if booking["booking_role"] == "PRIMARY" and booking["status"] in ("CONFIRMED", "PROMOTED"):
            primary_ok = True
            break
    if not primary_ok:
        return False
    validated = sum(1 for p in production_preps(production) if p["status"] == "VALIDATED")
    return validated >= production["required_validated_preps"]


# ---------------------------------------------------------------------------
# cascades
# ---------------------------------------------------------------------------
def abort_scheduled_rehearsals(production):
    for rehearsal in production_rehearsals(production):
        if rehearsal["status"] == "SCHEDULED":
            store.set_fields(rehearsal, status="ABORTED", outcome_notes=None)


def set_readiness_hold(production, value):
    for show in production_shows(production):
        if show["air_status"] == "PRE_SHOW":
            store.set_fields(show, readiness_hold=value)


# ---------------------------------------------------------------------------
# recompute_production_stage  (PRD 2.9 / SCAFFOLD 1.2 shared procedure)
# ---------------------------------------------------------------------------
def recompute_production_scalars(production):
    committed = labor_committed(production)
    store.set_fields(
        production,
        required_crew_positions=REQUIRED_CREW_POSITIONS[production["event_tier"]],
        required_validated_preps=REQUIRED_VALIDATED_PREPS[production["event_tier"]],
    )
    store.set_fields(
        production,
        labor_committed_cents=committed,
        labor_available_cents=production["labor_budget_total_cents"] - committed,
    )
    store.set_fields(
        production,
        readiness_score_preflight=readiness_preflight(production),
        readiness_score_certified=readiness_certified(production),
    )


def recompute_production_stage(production):
    # step 1
    recompute_production_scalars(production)
    # step 6
    if production["status"] in CLOSED_PRODUCTION_STATUSES:
        return
    # step 2
    conditions = provisioning_conditions(production)
    status = production["status"]
    # step 3
    if status in ("PROVISIONED", "REHEARSED") and not conditions:
        store.set_fields(production, status="SURVEYED")
        abort_scheduled_rehearsals(production)
        set_readiness_hold(production, True)
    # step 4
    elif status == "REHEARSED" and production["readiness_score_certified"] < 100:
        store.set_fields(production, status="PROVISIONED")
        set_readiness_hold(production, True)
    # step 5
    elif status == "SURVEYED" and conditions:
        store.set_fields(production, status="PROVISIONED")


# ---------------------------------------------------------------------------
# truck_travel_occupation_window / truck_service_accrual
# ---------------------------------------------------------------------------
def occupation_window(production):
    start = production["scheduled_start_utc"] - _hours(TRAVEL_IN_HOURS)
    end = production["scheduled_end_utc"] + _hours(TEARDOWN_OUT_HOURS)
    return start, end


def _hours(count):
    from datetime import timedelta

    return timedelta(hours=count)


def travel_window_conflict(production, truck):
    new_start, new_end = occupation_window(production)
    for other in store.ordered(store.PRODUCTIONS):
        if other["id"] == production["id"] or other["truck_id"] != truck["id"]:
            continue
        if other["status"] in ("WRAPPED", "SETTLED"):
            continue
        other_start, other_end = occupation_window(other)
        if new_start < other_end and other_start < new_end:
            return True
    return False


def accrue_truck_hours(truck, air_minutes_total):
    accrued = TRAVEL_HOURS_PER_EVENT + SETUP_TEARDOWN_HOURS + ceil_div(air_minutes_total, 60)
    hours = truck["engine_hours_since_service"] + accrued
    store.set_fields(
        truck,
        engine_hours_since_service=hours,
        hours_to_service=truck["service_interval_hours"] - hours,
    )


# ---------------------------------------------------------------------------
# production_settlement
# ---------------------------------------------------------------------------
def overrun_rate(labor_subtotal_cents):
    if labor_subtotal_cents < OVERRUN_BRACKET_MID:
        return OVERRUN_RATE_LOW
    if labor_subtotal_cents < OVERRUN_BRACKET_HIGH:
        return OVERRUN_RATE_MID
    return OVERRUN_RATE_HIGH


def air_minutes(show):
    if show is None:
        return 0
    if show["on_air_at_utc"] is None or show["off_air_at_utc"] is None:
        return 0
    return whole_minutes(show["on_air_at_utc"], show["off_air_at_utc"])
