"""Domain assertions and expected-value calculators for the mountain
operations API.

Two kinds of helper live here. The first kind asserts the structural contract
every row of a family must satisfy — identity, timestamps, versioning and the
stored precision of each derived quantity. The second kind recomputes a derived
quantity the way the specification words it, so a test can state the rule once
and let the helper produce the figure.
"""

from decimal import ROUND_HALF_UP, Decimal
from math import floor
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    BLACK_CLASS_FACTOR,
    CAT_SWATH_ACRES_PER_PASS,
    CCC_UTILIZATION_FACTOR,
    COVERAGE_PCT_CAP,
    CROWDING_DENSITY_THRESHOLD,
    CROWDING_REDUCTION_FACTOR,
    DEMAND_SURCHARGE_MULTIPLIER,
    EXPOSURE_FREE_FEATURES,
    EXPOSURE_STEP,
    FEATURE_BASE_WEIGHT,
    FEATURE_SIZE_MULTIPLIER,
    GALLONS_PER_ACRE_FOOT,
    NON_SEASON_POOL_SHARE,
    NO_CROWDING_FACTOR,
    PARK_RISK_SCORE_CAP,
    SNOW_YIELD_GOOD,
    SNOW_YIELD_IDEAL,
    SNOW_YIELD_MARGINAL,
    WET_BULB_GOOD_F,
    WET_BULB_MARGINAL_F,
    WET_BULB_MAX_F,
    WINCH_EFFICIENCY_FACTOR,
)

# ─── Field inventories ────────────────────────────────

SEASON_FIELDS = (
    "id",
    "created_at",
    "updated_at",
    "version",
    "season_label",
    "water_right_seasonal_af",
    "plant_max_gpm",
    "snowmaking_kwh_per_af",
    "energy_windows",
    "base_depth_policy",
    "min_patrollers_per_open_area",
    "groom_freshness_hours",
    "season_state",
    "water_reserved_af",
    "water_used_af",
    "snow_produced_swe_af",
    "open_area_count",
)

LIFT_FIELDS = (
    "id",
    "created_at",
    "updated_at",
    "version",
    "season_id",
    "lift_code",
    "name",
    "lift_type",
    "wind_hold_threshold_mph",
    "hourly_capacity_pph",
    "required_operator_count",
    "service_status",
    "mechanical_status",
    "last_inspection_at",
    "last_inspection_result",
    "inspection_valid_until",
    "staffed_operator_count",
    "wind_hold_since",
)

STAFF_ASSIGNMENT_FIELDS = (
    "id",
    "created_at",
    "updated_at",
    "version",
    "lift_id",
    "operator_code",
    "role_on_lift",
    "shift_start",
    "shift_end",
    "state",
    "released_at",
)

TERRAIN_AREA_FIELDS = (
    "id",
    "created_at",
    "updated_at",
    "version",
    "season_id",
    "serving_lift_id",
    "trail_code",
    "name",
    "terrain_class",
    "acres",
    "min_open_base_depth_in",
    "avalanche_terrain",
    "opening_state",
    "park_state",
    "park_feature_count",
    "park_risk_score",
    "park_built_by_user_id",
    "park_inspected_by_user_id",
    "base_depth_in",
    "base_depth_stake_count",
    "last_groomed_at",
    "groom_coverage_pct",
    "groom_ready",
    "mitigation_clearance_expires_at",
    "assigned_patroller_count",
    "machine_swe_af",
)

SNOW_DEPTH_READING_FIELDS = (
    "id",
    "created_at",
    "terrain_area_id",
    "stake_code",
    "depth_in",
    "density_pct",
    "measured_at",
    "source",
)

PUMP_HOUSE_FIELDS = (
    "id",
    "created_at",
    "updated_at",
    "version",
    "season_id",
    "pump_house_code",
    "name",
    "max_gpm",
    "gun_count",
    "status",
    "peak_committed_gpm",
    "active_session_count",
)

SESSION_FIELDS = (
    "id",
    "created_at",
    "updated_at",
    "version",
    "terrain_area_id",
    "pump_house_id",
    "window_start",
    "window_end",
    "planned_minutes",
    "gun_count",
    "gpm",
    "state",
    "wet_bulb_f",
    "started_at",
    "last_running_since",
    "ended_at",
    "accumulated_run_minutes",
    "water_af_reserved",
    "water_af_actual",
    "snow_yield_factor",
    "snow_swe_af",
    "energy_kwh",
    "energy_cost_usd",
    "demand_surcharge_applied",
    "abort_reason",
)

GROOMING_TASK_FIELDS = (
    "id",
    "created_at",
    "updated_at",
    "version",
    "terrain_area_id",
    "cat_route_code",
    "sequence_index",
    "snowcat_unit_code",
    "winch_required",
    "winch_anchor_code",
    "window_start",
    "window_end",
    "state",
    "passes_completed",
    "coverage_pct",
    "dispatched_at",
    "completed_at",
)

PATROLLER_FIELDS = (
    "id",
    "created_at",
    "updated_at",
    "version",
    "season_id",
    "assigned_terrain_area_id",
    "patroller_code",
    "full_name",
    "cert_level",
    "blaster_certified",
    "on_duty",
    "status",
)

MISSION_FIELDS = (
    "id",
    "created_at",
    "updated_at",
    "version",
    "terrain_area_id",
    "route_code",
    "method",
    "planned_charges",
    "hazard_rating_pre",
    "hazard_rating_post",
    "state",
    "charges_used",
    "clearance_valid_hours",
    "road_closure_minutes",
    "executed_by_patroller_id",
    "cleared_by_patroller_id",
    "executed_at",
    "cleared_at",
)

INCIDENT_FIELDS = (
    "id",
    "created_at",
    "updated_at",
    "version",
    "terrain_area_id",
    "reporter_code",
    "severity",
    "location_note",
    "state",
    "responder_patroller_id",
    "transport_mode",
    "disposition",
    "reported_at",
    "dispatched_at",
    "transport_ordered_at",
    "closed_at",
    "response_minutes",
)

DAY_PLAN_FIELDS = (
    "id",
    "created_at",
    "updated_at",
    "version",
    "season_id",
    "operating_date",
    "parking_stalls_total",
    "posture",
    "wind_speed_mph",
    "wet_bulb_f",
    "new_snow_in",
    "open_terrain_count",
    "terrain_open_acres",
    "open_lift_capacity_pph",
    "raw_ccc",
    "guest_capacity",
    "non_season_pool",
    "admitted_guest_count",
    "non_season_admitted_count",
    "waitlisted_guest_count",
    "parking_stalls_used",
    "weather_updated_at",
    "published_at",
    "closed_at",
)

RESERVATION_FIELDS = (
    "id",
    "created_at",
    "updated_at",
    "version",
    "day_plan_id",
    "party_code",
    "pass_type",
    "party_size",
    "vehicle_count",
    "state",
    "allocated_stalls",
    "waitlist_reason",
    "confirmed_at",
    "checked_in_at",
    "released_at",
)

SNOW_ACCOUNTING_FIELDS = (
    "season_id",
    "water_right_seasonal_af",
    "water_used_af",
    "water_reserved_af",
    "water_right_remaining_af",
    "snow_produced_swe_af",
    "energy_cost_total_usd",
    "completed_session_count",
    "aborted_session_count",
    "open_area_count",
    "open_acres",
    "openable_acres",
    "terrain_open_pct",
)

OPENING_REPORT_FIELDS = (
    "day_plan_id",
    "operating_date",
    "posture",
    "wind_speed_mph",
    "wet_bulb_f",
    "open_terrain_count",
    "terrain_open_acres",
    "openable_acres",
    "terrain_open_pct",
    "open_lift_capacity_pph",
    "raw_ccc",
    "guest_capacity",
    "non_season_pool",
    "admitted_guest_count",
    "non_season_admitted_count",
    "waitlisted_guest_count",
    "parking_stalls_total",
    "parking_stalls_used",
    "held_area_count",
    "wind_held_lift_count",
    "mech_held_lift_count",
)


# ─── Numeric and temporal comparison ──────────────────

def round_half_up(value: Any, places: int = 0) -> float:
    """Round half away from zero at the named number of decimal places."""
    quantum = Decimal(1).scaleb(-places)
    result = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    return float(result)


def floor_to_int(value: Any) -> int:
    """Reduce a product to a whole number by truncation toward zero."""
    return int(floor(float(value)))


def as_number(value: Any) -> float:
    """Coerce a JSON numeric to float, rejecting a value delivered as a string."""
    assert not isinstance(value, str), (
        f"Numeric field delivered as a string: {value!r}"
    )
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"Expected a number, got {type(value).__name__}: {value!r}"
    )
    return float(value)


def assert_number_equals(actual: Any, expected: float, places: int = 6) -> None:
    """Assert a numeric field equals the expected figure at stored precision."""
    got = as_number(actual)
    assert round(got, places) == round(float(expected), places), (
        f"Expected {expected}, got {got}"
    )


def assert_decimal_places(value: Any, places: int) -> None:
    """Assert a stored figure carries no more precision than the rule allows."""
    got = as_number(value)
    assert round_half_up(got, places) == round(got, 9), (
        f"Value {got} carries more than {places} decimal places"
    )


def assert_water_af(value: Any, expected: Optional[float] = None) -> None:
    """Water volumes in acre-feet are 3 decimal places."""
    assert_decimal_places(value, 3)
    if expected is not None:
        assert_number_equals(value, expected, places=3)


def assert_energy_kwh(value: Any, expected: Optional[float] = None) -> None:
    """Energy is 3 decimal places for kilowatt-hours."""
    assert_decimal_places(value, 3)
    if expected is not None:
        assert_number_equals(value, expected, places=3)


def assert_usd(value: Any, expected: Optional[float] = None) -> None:
    """Currency is 2 decimal places."""
    assert_decimal_places(value, 2)
    if expected is not None:
        assert_number_equals(value, expected, places=2)


def assert_one_decimal(value: Any, expected: Optional[float] = None) -> None:
    """Depths, percentages, acreages and scores are 1 decimal place."""
    assert_decimal_places(value, 1)
    if expected is not None:
        assert_number_equals(value, expected, places=1)


def assert_integer(value: Any, expected: Optional[int] = None) -> None:
    """Counts, capacities, stalls, gallons per minute and minutes are integers."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"Expected an integer, got {type(value).__name__}: {value!r}"
    )
    if expected is not None:
        assert value == expected, f"Expected {expected}, got {value}"


def canonical_instant(value: str) -> str:
    """Normalise an ISO 8601 UTC instant so widths of the fractional part
    compare equal: both 2026-08-01T00:00:00Z and 2026-08-01T00:00:00.000Z
    denote the same instant."""
    assert isinstance(value, str), f"Expected a timestamp string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text[10:]:
        text = text[: 10 + text[10:].index("+")]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = text, "000"
    return f"{head}.{frac}Z"


def assert_instant_equals(actual: Any, expected: str) -> None:
    """Assert two instants denote the same moment on the logical clock."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"Expected instant {expected}, got {actual}"
    )


def assert_instant_field(value: Any) -> None:
    """Assert a stamped instant is an ISO 8601 UTC timestamp."""
    assert is_iso8601_timestamp(value), f"Not an ISO 8601 UTC instant: {value!r}"


# ─── Structural row assertions ────────────────────────

def assert_fields_present(row: Dict[str, Any], fields: Iterable[str]) -> None:
    """Assert every declared field of a family appears in the representation."""
    missing = [name for name in fields if name not in row]
    assert not missing, f"Representation is missing declared fields: {missing}"


def assert_versioned_row(row: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Identity, timestamps and version of a row that carries all four."""
    assert is_valid_uuid(row["id"]), f"id is not a bare UUID string: {row['id']!r}"
    assert_instant_field(row["created_at"])
    assert_instant_field(row["updated_at"])
    assert_integer(row["version"])
    assert row["version"] >= 1, "version starts at 1 on creation"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"Expected version {expected_version}, got {row['version']}"
        )


def assert_immutable_observation(row: Dict[str, Any]) -> None:
    """A snow stake reading carries only id and created_at: it has no
    updated_at and no version field at all, and neither field appears in its
    representation."""
    assert is_valid_uuid(row["id"]), f"id is not a bare UUID string: {row['id']!r}"
    assert_instant_field(row["created_at"])
    assert "updated_at" not in row, "a stake reading must not expose updated_at"
    assert "version" not in row, "a stake reading must not expose version"


def assert_success_envelope_meta(body: Dict[str, Any]) -> None:
    """The request identifier convention of the success envelope."""
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_: {meta['api_request_id']!r}"
    )
    assert_instant_field(meta["api_request_timestamp"])


def assert_pagination_meta(
    meta: Dict[str, Any], limit: int, offset: int, total_count: int, has_more: bool
) -> None:
    """The four pagination fields a list response carries inside meta."""
    assert_integer(meta["limit"], limit)
    assert_integer(meta["offset"], offset)
    assert_integer(meta["total_count"], total_count)
    assert meta["has_more"] is has_more, (
        f"Expected has_more {has_more}, got {meta['has_more']!r}"
    )


def assert_created_at_ascending(rows: Sequence[Dict[str, Any]]) -> None:
    """List results are sorted by created_at in ascending order."""
    stamps = [canonical_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), f"Rows are not in ascending created_at order: {stamps}"


# ─── Instant arithmetic on the logical clock ──────────

from datetime import datetime, timedelta, timezone  # noqa: E402


def parse_instant(value: str) -> datetime:
    """Read an ISO 8601 UTC instant into an aware datetime."""
    return datetime.strptime(canonical_instant(value), "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )


def format_instant(moment: datetime) -> str:
    """Render an aware datetime as an ISO 8601 UTC instant with three
    fractional digits."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{moment.microsecond // 1000:03d}Z"
    )


def shift_instant(
    value: str, hours: float = 0, minutes: float = 0, seconds: float = 0, days: float = 0
) -> str:
    """Return the instant a given offset away from another instant."""
    moved = parse_instant(value) + timedelta(
        days=days, hours=hours, minutes=minutes, seconds=seconds
    )
    return format_instant(moved)


def whole_minutes_between(start: str, end: str) -> int:
    """The number of whole minutes between two instants, partials discarded."""
    delta = parse_instant(end) - parse_instant(start)
    return int(delta.total_seconds() // 60)


# ─── Derived quantity calculators ─────────────────────

def expected_base_depth(depths: Sequence[float], policy: str) -> float:
    """Base depth under the season's stake policy: the mean of the surviving
    depths under MEAN_OF_STAKES, the smallest under MIN_OF_STAKES, rounded half
    up to one decimal place. No surviving stake gives 0.0."""
    if not depths:
        return 0.0
    if policy == "MIN_OF_STAKES":
        return round_half_up(min(depths), 1)
    return round_half_up(sum(depths) / len(depths), 1)


def expected_coverage_pct(
    passes_completed: int,
    acres: float,
    winch_required: bool = False,
    terrain_class: str = "BLUE",
) -> float:
    """Coverage as the groomed acreage expressed as a percentage of the area's
    acreage, rounded half up to one decimal place and then capped at 100.0."""
    groomed = passes_completed * CAT_SWATH_ACRES_PER_PASS
    groomed *= WINCH_EFFICIENCY_FACTOR if winch_required else 1.0
    groomed *= BLACK_CLASS_FACTOR if terrain_class == "BLACK" else 1.0
    pct = round_half_up(groomed / acres * 100, 1)
    return min(pct, COVERAGE_PCT_CAP)


def expected_park_risk_score(features: Sequence[Dict[str, str]]) -> float:
    """Feature weights summed, multiplied by the exposure factor, rounded half
    up to one decimal place and then capped at 100.0."""
    raw = sum(
        FEATURE_BASE_WEIGHT[feature["feature_type"]]
        * FEATURE_SIZE_MULTIPLIER[feature["size_class"]]
        for feature in features
    )
    extra = max(0, len(features) - EXPOSURE_FREE_FEATURES)
    factor = 1.0 + extra * EXPOSURE_STEP
    score = round_half_up(raw * factor, 1)
    return min(score, PARK_RISK_SCORE_CAP)


def expected_exposure_factor(feature_count: int) -> float:
    """The first five features are free; each one beyond the fifth adds one
    tenth to a factor that starts at 1.0."""
    return 1.0 + max(0, feature_count - EXPOSURE_FREE_FEATURES) * EXPOSURE_STEP


def expected_water_af(gpm: int, minutes: int) -> float:
    """Gallons per minute multiplied by minutes, divided by the gallons in one
    acre-foot, rounded half up to three decimal places."""
    return round_half_up(Decimal(gpm * minutes) / Decimal(GALLONS_PER_ACRE_FOOT), 3)


def expected_snow_yield_factor(wet_bulb_f: float) -> Optional[float]:
    """The yield factor the wet-bulb band selects, or None when the reading is
    too warm to make snow at all. Every band test is strictly greater-than."""
    if wet_bulb_f > WET_BULB_MAX_F:
        return None
    if wet_bulb_f > WET_BULB_MARGINAL_F:
        return SNOW_YIELD_MARGINAL
    if wet_bulb_f > WET_BULB_GOOD_F:
        return SNOW_YIELD_GOOD
    return SNOW_YIELD_IDEAL


def expected_snow_swe_af(water_af_actual: float, snow_yield_factor: float) -> float:
    """Metered water multiplied by the yield factor, rounded half up to three
    decimal places."""
    return round_half_up(
        Decimal(str(water_af_actual)) * Decimal(str(snow_yield_factor)), 3
    )


def expected_energy_kwh(water_af_actual: float, kwh_per_af: float) -> float:
    """Metered water multiplied by the season's energy intensity, rounded half
    up to three decimal places."""
    return round_half_up(Decimal(str(water_af_actual)) * Decimal(str(kwh_per_af)), 3)


def expected_window_energy_cost(
    total_kwh: float,
    window_minutes: int,
    accumulated_run_minutes: int,
    price_usd_per_kwh: float,
) -> Tuple[float, float]:
    """One window's share of consumption and its cost: the share rounded half
    up to three decimal places, the cost rounded half up to two."""
    share = round_half_up(
        Decimal(str(total_kwh))
        * Decimal(window_minutes)
        / Decimal(accumulated_run_minutes),
        3,
    )
    cost = round_half_up(Decimal(str(share)) * Decimal(str(price_usd_per_kwh)), 2)
    return share, cost


def expected_base_energy_cost(per_window_costs: Sequence[float]) -> float:
    """The base cost is the sum of the already-rounded per-window costs."""
    return round_half_up(sum(Decimal(str(cost)) for cost in per_window_costs), 2)


def expected_surcharged_cost(base_cost: float) -> float:
    """The base cost multiplied by the surcharge multiplier, rounded half up to
    two decimal places — applied to the summed base cost."""
    return round_half_up(
        Decimal(str(base_cost)) * Decimal(str(DEMAND_SURCHARGE_MULTIPLIER)), 2
    )


def expected_capacity(open_lift_capacity_pph: int, terrain_open_acres: float) -> Dict[str, Any]:
    """The single-pass carrying capacity computation: raw_ccc from uphill
    capacity, the crowding density from raw_ccc, the density factor from that
    density, then guest_capacity and non_season_pool."""
    raw_ccc = floor_to_int(open_lift_capacity_pph * CCC_UTILIZATION_FACTOR)
    density = (
        round(raw_ccc / terrain_open_acres, 10) if terrain_open_acres else 0.0
    )
    factor = (
        CROWDING_REDUCTION_FACTOR
        if density > CROWDING_DENSITY_THRESHOLD
        else NO_CROWDING_FACTOR
    )
    guest_capacity = floor_to_int(raw_ccc * factor)
    non_season_pool = floor_to_int(guest_capacity * NON_SEASON_POOL_SHARE)
    return {
        "open_lift_capacity_pph": open_lift_capacity_pph,
        "raw_ccc": raw_ccc,
        "crowding_density": density,
        "density_factor": factor,
        "guest_capacity": guest_capacity,
        "non_season_pool": non_season_pool,
    }


def expected_response_minutes(elapsed_seconds: float) -> int:
    """Whole seconds elapsed divided by 60 and rounded half up to a whole
    number of minutes."""
    return int(round_half_up(Decimal(int(elapsed_seconds)) / Decimal(60), 0))


def expected_road_closure_minutes(charges_used: int) -> int:
    """Twenty minutes of road closure for each charge actually used."""
    return 20 * charges_used


# ─── Invariant assertions ─────────────────────────────

def assert_water_ledger_identity(
    season: Dict[str, Any], water_right_remaining_af: Optional[float] = None
) -> None:
    """Water drawn plus water reserved plus water remaining equals the
    seasonal water right."""
    used = as_number(season["water_used_af"])
    reserved = as_number(season["water_reserved_af"])
    right = as_number(season["water_right_seasonal_af"])
    remaining = (
        as_number(water_right_remaining_af)
        if water_right_remaining_af is not None
        else right - used - reserved
    )
    total = round_half_up(
        Decimal(str(used)) + Decimal(str(reserved)) + Decimal(str(remaining)), 3
    )
    assert total == round_half_up(right, 3), (
        f"Ledger identity broken: {used} used + {reserved} reserved + "
        f"{remaining} remaining != {right} seasonal right"
    )


def assert_accounting_identity(rollup: Dict[str, Any]) -> None:
    """The same identity as reported by the season accounting rollup."""
    assert_water_ledger_identity(rollup, rollup["water_right_remaining_af"])


def assert_admission_counters(
    day_plan: Dict[str, Any], reservations: Sequence[Dict[str, Any]]
) -> None:
    """The four admission counters recomputed from the reservation set: only
    CONFIRMED and CHECKED_IN rows consume seats and stalls."""
    seat_states = ("CONFIRMED", "CHECKED_IN")
    admitted = sum(
        row["party_size"] for row in reservations if row["state"] in seat_states
    )
    non_season = sum(
        row["party_size"]
        for row in reservations
        if row["state"] in seat_states and row["pass_type"] in ("DAY_TICKET", "RECIPROCAL")
    )
    waitlisted = sum(
        row["party_size"] for row in reservations if row["state"] == "WAITLISTED"
    )
    stalls = sum(
        row["allocated_stalls"] for row in reservations if row["state"] in seat_states
    )
    assert_integer(day_plan["admitted_guest_count"], admitted)
    assert_integer(day_plan["non_season_admitted_count"], non_season)
    assert_integer(day_plan["waitlisted_guest_count"], waitlisted)
    assert_integer(day_plan["parking_stalls_used"], stalls)


def assert_versions_advanced(
    before: Dict[str, Any], after: Dict[str, Any], by: int = 1
) -> None:
    """A row the request mutated has its version incremented by exactly the
    stated amount and its updated_at refreshed."""
    assert after["version"] == before["version"] + by, (
        f"Expected version {before['version'] + by}, got {after['version']}"
    )


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    """A row the request did not touch keeps its version."""
    assert after["version"] == before["version"], (
        f"version moved from {before['version']} to {after['version']} on a row "
        "the request should not have touched"
    )


def find_row(rows: Sequence[Dict[str, Any]], **match: Any) -> Dict[str, Any]:
    """Return the single row of a list response matching every named field."""
    hits = [
        row for row in rows if all(row.get(key) == value for key, value in match.items())
    ]
    assert len(hits) == 1, f"Expected exactly one row matching {match}, got {len(hits)}"
    return hits[0]


def ids_of(rows: Sequence[Dict[str, Any]]) -> List[str]:
    """The id of every row of a list response, in the order returned."""
    return [row["id"] for row in rows]
