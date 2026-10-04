"""Business calculations, selectors and recomputations (PRD section 2 and 3).

Every function here is a pure recomputation over the store; none of them
mints rows or seeds data.  All arithmetic is integer arithmetic, floored
exactly where the PRD says it floors.
"""

import math

from db import store

# ─── readiness doctrine (PRD 2.5) ─────────────────────────────────────────

MIN_BATTERY_PCT = 80
MIN_CLEANLINESS_SCORE = 70

# ─── depot posture (PRD 2.6) ──────────────────────────────────────────────

CONGESTION_THRESHOLD_PCT = 80

# ─── territory posture (PRD 2.7) ──────────────────────────────────────────

RESTRICTED_ZONE_COUNT = 3
SUSPENDED_ZONE_COUNT = 5
MAPPED_PCT_GATE = 95
VALIDATION_HOURS_GATE = 100

# ─── wave allocation (PRD 3.3) ────────────────────────────────────────────

RESERVE_TARGET = 6

# ─── credit arithmetic (PRD 2.10) ─────────────────────────────────────────

CREDIT_NUMERATOR = 5_000_000
FIXED_DENOMINATOR = 500
OPEN_MULTIPLIER = 10
RESTRICTED_MULTIPLIER = 5

# ─── incident retention (PRD 3.5) ─────────────────────────────────────────

CRASH_RETENTION_DAYS = 365
STANDARD_RETENTION_DAYS = 180
SECONDS_PER_DAY = 86_400

# ─── operational cadence (PRD 3.2, 3.6, 3.7) ──────────────────────────────

CYCLE_SLA_OPS_RUNS = 2
ROADSIDE_SLA_OPS_RUNS = 4
MAX_DISPATCHED_PER_TEAM = 2
ACK_TIMEOUT_OPS_RUNS = 3
MAX_SESSION_ATTEMPTS = 3

WINDOW_CODES = ("MORNING_PEAK", "MIDDAY", "EVENING_PEAK", "OVERNIGHT")
PEAK_WINDOWS = ("MORNING_PEAK", "EVENING_PEAK")
KIND_CHARGE = "CHARGE"
KIND_CLEAN = "CLEAN"
KIND_CALIBRATION = "CALIBRATION"
KIND_SOFTWARE = "SOFTWARE"
SERVICE_KINDS = (KIND_CHARGE, KIND_CLEAN, KIND_CALIBRATION, KIND_SOFTWARE)


# =========================================================================
# vehicle_service_status (PRD 2.5)
# =========================================================================


def is_service_ready(vehicle):
    """All four readiness predicates, inclusive on both numeric boundaries."""
    return (
        vehicle["battery_pct"] >= MIN_BATTERY_PCT
        and vehicle["cleanliness_score"] >= MIN_CLEANLINESS_SCORE
        and vehicle["calib_valid"] is True
        and vehicle["software_version"] == vehicle["target_software_version"]
    )


def compute_service_status(vehicle):
    """The verdict, assigned in the PRD's fixed evaluation order."""
    if vehicle["is_roadside_blocked"]:
        return "DISPATCHED"
    if vehicle["status"] == "IN_SERVICE":
        return "DISPATCHED"
    if vehicle["status"] == "AT_DEPOT":
        return "AVAILABLE" if is_service_ready(vehicle) else "UNAVAILABLE"
    return "UNAVAILABLE"


def recompute_service_status(vehicle, bump=True):
    """Recompute the verdict and record the mutation exactly once.

    PRD 2.4 makes a derived-field write a mutation, so this always refreshes
    `updated_at` and advances `version` — but callers that have already
    recorded their own field change on the same row in the same request pass
    `bump=False` so the row advances exactly once per endpoint.
    """
    verdict = compute_service_status(vehicle)
    vehicle["service_status"] = verdict
    if bump:
        store.touch(vehicle)
    return verdict


# =========================================================================
# depot_posture (PRD 2.6)
# =========================================================================


def compute_depot_state(depot):
    """(occupancy_pct, posture) for a depot at the logical clock."""
    reference = store.now()
    occupied_pairs = set()
    for slot in store.bay_slots.values():
        if slot["depot_id"] != depot["id"]:
            continue
        if slot["status"] not in ("RESERVED", "ACTIVE"):
            continue
        start = _instant(slot["start_utc"])
        end = _instant(slot["end_utc"])
        if start <= reference < end:  # half-open [start_utc, end_utc)
            occupied_pairs.add((slot["service_type"], slot["bay_index"]))

    occupied = len(occupied_pairs)
    total = (
        depot["charge_positions"]
        + depot["cleaning_positions"]
        + depot["calib_positions"]
        + depot["software_positions"]
    )
    if total <= 0:
        occupancy = 100 if occupied > 0 else 0
    else:
        occupancy = min(100, math.floor(100 * occupied / total))

    if occupancy == 100:
        posture = "LOCKDOWN"
    elif occupancy >= CONGESTION_THRESHOLD_PCT:
        posture = "CONGESTED"
    else:
        posture = "OPEN"
    return occupancy, posture


def recompute_depot(depot, bump=True):
    """Recompute a depot's occupancy and posture; record the mutation once."""
    occupancy, posture = compute_depot_state(depot)
    depot["occupancy_pct"] = occupancy
    depot["posture"] = posture
    if bump:
        store.touch(depot)
    return depot


def recompute_depot_and_territory(depot):
    """A bay-slot change never alters territory posture, but its own does."""
    recompute_depot(depot)


# =========================================================================
# territory_posture (PRD 2.7)
# =========================================================================


def active_zone_count(territory_id):
    return sum(
        1
        for zone in store.exclusion_zones.values()
        if zone["territory_id"] == territory_id and zone["status"] == "ACTIVE"
    )


def compute_territory_posture(territory):
    """The zone gates are evaluated first; mapping gates only below three."""
    zones = active_zone_count(territory["id"])
    if zones >= SUSPENDED_ZONE_COUNT:
        return "SUSPENDED"
    if zones >= RESTRICTED_ZONE_COUNT:
        return "RESTRICTED"
    if territory["mapped_pct"] >= MAPPED_PCT_GATE and territory["validation_hours"] >= VALIDATION_HOURS_GATE:
        return "ACTIVE"
    if territory["mapped_pct"] >= MAPPED_PCT_GATE:
        return "VALIDATING"
    if territory["mapped_pct"] > 0:
        return "MAPPING"
    return "PENDING"


def recompute_territory(territory, bump=True):
    """Recompute active_zone_count and posture; record the mutation once."""
    zones = active_zone_count(territory["id"])
    territory["active_zone_count"] = zones
    territory["posture"] = compute_territory_posture(territory)
    if bump:
        store.touch(territory)
    return territory


# =========================================================================
# territory_total_credit (PRD 2.10)
# =========================================================================


def effective_demand(projected_rides, manual_only_rides):
    """max(0, projected_rides - manual_only_rides)."""
    return max(0, projected_rides - manual_only_rides)


def credit_provision(effective, posture):
    """10 * demand, halved to 5 * demand when the territory is RESTRICTED."""
    multiplier = RESTRICTED_MULTIPLIER if posture == "RESTRICTED" else OPEN_MULTIPLIER
    return multiplier * effective


def credit_per_ride(effective, posture):
    """floor(5,000,000 / (provision + 500))."""
    provision = credit_provision(effective, posture)
    return CREDIT_NUMERATOR // (provision + FIXED_DENOMINATOR)


def total_credit_cents(effective, posture):
    """floor(5,000,000 * provision / (provision + 500))."""
    provision = credit_provision(effective, posture)
    return (CREDIT_NUMERATOR * provision) // (provision + FIXED_DENOMINATOR)


def demand_signal_for(territory_id, window_code):
    for signal in store.demand_signals.values():
        if signal["territory_id"] == territory_id and signal["window_code"] == window_code:
            return signal
    return None


def recompute_territory_credit(territory, window_code):
    """Re-provision the territory pool from its curve for a service window."""
    signal = demand_signal_for(territory["id"], window_code)
    effective = signal["effective_demand"] if signal else 0
    pool = total_credit_cents(effective, territory["posture"])
    if territory["total_credit_cents"] != pool:
        territory["total_credit_cents"] = pool
        store.touch(territory)
    return credit_per_ride(effective, territory["posture"])


# =========================================================================
# territory_total_severe_incidents (PRD 3.5)
# =========================================================================


def recompute_total_severe_incidents(territory, vehicle_id):
    """Aggregate non-VOIDED SEVERE reports for one vehicle onto the territory."""
    count = sum(
        1
        for report in store.incident_reports.values()
        if report["vehicle_id"] == vehicle_id
        and report["severity"] == "SEVERE"
        and report["status"] != "VOIDED"
    )
    if territory["total_severe_incidents"] != count:
        territory["total_severe_incidents"] = count
        store.touch(territory)
    return count


# =========================================================================
# wave_vehicle_selection (PRD 3.3)
# =========================================================================


def reserve_floor(planned_vehicle_count):
    """6 divided by the wave budget, rounded up once per wave."""
    return int(math.ceil(RESERVE_TARGET / float(planned_vehicle_count)))


def wave_allocation_cap(planned_vehicle_count, available_candidates):
    """min(budget, candidates - reserve_floor), floored at zero."""
    return max(
        0,
        min(planned_vehicle_count, available_candidates - reserve_floor(planned_vehicle_count)),
    )


def _created_instant(value):
    """Comparable key for a created_at literal (tolerates the format variants)."""
    from db import _parse_utc

    try:
        return _parse_utc(value)
    except (TypeError, ValueError):
        return store.now()


def rank_key(row):
    """Ordering key shared by the vehicle selector and the wave allocator:
    battery_pct descending, then created_at ascending (never the id, because
    `id` is a random UUID and must not break a creation-order tie).
    """
    return (-row["battery_pct"], _created_instant(row["created_at"]))


def wave_candidates(territory_id):
    """Staged, unblocked, service-ready vehicles of the territory."""
    rows = [
        vehicle
        for vehicle in store.vehicles.values()
        if vehicle["territory_id"] == territory_id
        and vehicle["status"] == "AT_DEPOT"
        and vehicle["is_roadside_blocked"] is False
        and vehicle["service_status"] == "AVAILABLE"
    ]
    rows.sort(key=rank_key)
    return rows


# =========================================================================
# vehicle_selector (PRD 3.4)
# =========================================================================


def vehicle_candidates(territory_id):
    """In-service, unblocked vehicles of the territory, ranked for dispatch."""
    rows = [
        vehicle
        for vehicle in store.vehicles.values()
        if vehicle["territory_id"] == territory_id
        and vehicle["status"] == "IN_SERVICE"
        and vehicle["is_roadside_blocked"] is False
    ]
    rows.sort(key=rank_key)
    return rows


# =========================================================================
# roadside team selection (PRD 3.6)
# =========================================================================


def roadside_team_candidates(territory_id, road_class):
    """AVAILABLE/ON_CASE teams, widened for FREEWAY cases."""
    rows = [
        team
        for team in store.roadside_teams.values()
        if team["territory_id"] == territory_id
        and team["status"] in ("AVAILABLE", "ON_CASE")
    ]
    if road_class == "FREEWAY":
        rows = [team for team in rows if team["road_class"] in ("FREEWAY", "ARTERIAL")]
    else:
        rows = [team for team in rows if team["road_class"] == road_class]
    rows.sort(key=lambda row: (row["team_code"], row["id"]))
    return rows


def dispatched_case_count(team_id):
    return sum(
        1
        for case in store.roadside_cases.values()
        if case["team_id"] == team_id and case["status"] == "RESPONSE_DISPATCHED"
    )


def release_team_if_idle(team_id):
    """A team returns to AVAILABLE when it holds no dispatched case."""
    team = store.roadside_teams.get(team_id)
    if team is None:
        return
    if dispatched_case_count(team_id) == 0 and team["status"] != "OFF_SHIFT":
        if team["status"] != "AVAILABLE":
            team["status"] = "AVAILABLE"
            store.touch(team)


# =========================================================================
# route-class and exclusion gates (PRD 2.8, 3.7)
# =========================================================================


def route_class_allowed(territory_id, route_class):
    """True when an APPROVED rule in the territory permits the class."""
    for rule in store.area_rules.values():
        if (
            rule["territory_id"] == territory_id
            and rule["route_class"] == route_class
            and rule["status"] == "APPROVED"
            and rule["allowed"] is True
        ):
            return True
    return False


def exclusion_zone_covers(territory_id, route_class):
    """True when an ACTIVE zone covers the class at the logical clock."""
    if route_class is None:
        return False
    reference = store.now()
    for zone in store.exclusion_zones.values():
        if zone["territory_id"] != territory_id:
            continue
        if zone["status"] != "ACTIVE":
            continue
        if zone["route_class"] != route_class:
            continue
        # closed, inclusive at both edges
        if _instant(zone["start_utc"]) <= reference <= _instant(zone["end_utc"]):
            return True
    return False


def curb_permitted(territory_id, curb_access, sub_service_type):
    """An ACTIVE CurbRule clearing this access class for the service type."""
    for rule in store.curb_rules.values():
        if (
            rule["territory_id"] == territory_id
            and rule["curb_access"] == curb_access
            and rule["sub_service_type"] == sub_service_type
            and rule["status"] == "ACTIVE"
        ):
            return rule["allowed"] is True
    return False


# =========================================================================
# helper
# =========================================================================


def _instant(value):
    from db import _parse_utc

    return _parse_utc(value)