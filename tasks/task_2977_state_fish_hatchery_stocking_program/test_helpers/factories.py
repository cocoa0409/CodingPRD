"""
Request-payload builders for the State Fish Hatchery Stocking Program API.

Each builder returns a body that satisfies every declared constraint in the PRD
by default, so a test only has to override the one field it is about. Numeric
fields are emitted as JSON numbers — acre-feet, pounds, temperatures and rates as
floats, counts and cents as integers — never as strings. Every instant is a full
ISO 8601 UTC timestamp with three fractional digits, as PRD 2.4 requires, never a
date-only value. Strings satisfy the patterns the PRD declares: a `station_code`
is exactly four characters drawn from uppercase letters and digits.
"""

import itertools
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from .constants import (
    ACCESS_PUBLIC_BOAT,
    INSPECTION_TYPE_PRE_TRANSFER,
    MODE_PRIORITY_WATERFALL,
    RESULT_NEGATIVE,
    SIZE_CLASS_YEARLING,
    SPECIES_RAINBOW_TROUT,
    STAGE_FRY,
    TREATMENT_CODE_FORMALIN,
    WATER_CLASS_COLDWATER_LAKE,
    WATER_SOURCE_SPRING,
)

_OMIT = object()

_STATION_CODE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_station_code_counter = itertools.count()


# ─── Instant helpers ──────────────────────────────────

def instant(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
    millisecond: int = 0,
) -> str:
    """Build an ISO 8601 UTC instant with three fractional digits."""
    return (
        f"{year:04d}-{month:02d}-{day:02d}T"
        f"{hour:02d}:{minute:02d}:{second:02d}.{millisecond:03d}Z"
    )


def shift_instant(
    value: str,
    days: int = 0,
    hours: int = 0,
    minutes: int = 0,
    seconds: int = 0,
    milliseconds: int = 0,
) -> str:
    """
    Return the instant `value` moved by the given offset, in the same
    three-fractional-digit ISO 8601 UTC form. Used for boundary cases such as one
    second past a certificate expiry, or exactly 48 hours after a release.
    """
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1]
    parsed = datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
    moved = parsed + timedelta(
        days=days,
        hours=hours,
        minutes=minutes,
        seconds=seconds,
        milliseconds=milliseconds,
    )
    return (
        f"{moved.year:04d}-{moved.month:02d}-{moved.day:02d}T"
        f"{moved.hour:02d}:{moved.minute:02d}:{moved.second:02d}"
        f".{moved.microsecond // 1000:03d}Z"
    )


def unique_station_code() -> str:
    """
    A fresh four-character code drawn only from uppercase letters and digits, as
    PRD 3.1 requires of `station_code`.
    """
    n = next(_station_code_counter)
    base = len(_STATION_CODE_ALPHABET)
    digits = []
    for _ in range(3):
        digits.append(_STATION_CODE_ALPHABET[n % base])
        n //= base
    return "S" + "".join(reversed(digits))


def _apply(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in overrides.items():
        if value is _OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ─── Logical clock ────────────────────────────────────

def clock_payload(current_utc: str) -> Dict[str, Any]:
    return {"current_utc": current_utc}


# ─── Hatcheries and discharge monitoring ──────────────

def hatchery_payload(**overrides: Any) -> Dict[str, Any]:
    """A station registration body. Ledger figures are all server-derived."""
    payload: Dict[str, Any] = {
        "name": "Silver Creek Hatchery",
        "station_code": unique_station_code(),
        "water_source_type": WATER_SOURCE_SPRING,
        "annual_water_right_af": 120.0,
        "rearing_capacity_lbs": 2000.0,
        "oxygen_supply_lpm": 6.0,
        "effluent_permit_number": "CO-0044821",
        "tss_permit_limit_mg_l": 20.0,
        "annual_budget_cents": 50000000,
    }
    return _apply(payload, overrides)


def effluent_reading_payload(hatchery_id: str, **overrides: Any) -> Dict[str, Any]:
    """A compliant discharge sample well inside a 20.0 mg/L permit limit."""
    payload: Dict[str, Any] = {
        "hatchery_id": hatchery_id,
        "sampled_at": instant(2026, 7, 31, 6),
        "tss_mg_l": 10.0,
        "total_phosphorus_mg_l": 0.05,
        "flow_af": 1.0,
    }
    return _apply(payload, overrides)


# ─── Waters ───────────────────────────────────────────

def water_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": "Blue Mesa Reservoir",
        "county": "Gunnison",
        "water_class": WATER_CLASS_COLDWATER_LAKE,
        "habitat_suitability_score": 80,
        "angler_demand_index": 90,
        "plan_species": SPECIES_RAINBOW_TROUT,
        "plan_target_count": 2000,
        "access_type": ACCESS_PUBLIC_BOAT,
    }
    return _apply(payload, overrides)


# ─── Brood groups ─────────────────────────────────────

def brood_stock_payload(hatchery_id: str, **overrides: Any) -> Dict[str, Any]:
    """
    A brood group whose spawning window contains the default clock of
    2026-08-01T00:00:00Z, so it can be opened without moving the clock.
    """
    payload: Dict[str, Any] = {
        "hatchery_id": hatchery_id,
        "species": SPECIES_RAINBOW_TROUT,
        "strain": "Hofer",
        "female_count": 400,
        "male_count": 200,
        "expected_fecundity_per_female": 3000,
        "spawning_window_start": instant(2026, 8, 1),
        "spawning_window_end": instant(2026, 10, 31),
        "egg_take_target": 120000,
    }
    return _apply(payload, overrides)


# ─── Egg takes ────────────────────────────────────────

def spawn_event_payload(brood_stock_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "brood_stock_id": brood_stock_id,
        "planned_take_date": instant(2026, 8, 10),
        "females_spawned": 20,
        "target_release_count": 15000,
    }
    return _apply(payload, overrides)


def record_take_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "eggs_taken": 20000,
        "taken_at": instant(2026, 8, 10),
    }
    return _apply(payload, overrides)


# ─── Rearing ──────────────────────────────────────────

def feeding_payload(
    fed_at: str,
    feed_lbs: float,
    avg_weight_g_after: float,
    mortality_count: Any = _OMIT,
) -> Dict[str, Any]:
    """
    A feeding period. `mortality_count` is optional in the PRD and is left out of
    the body entirely unless a value is supplied, so the default of zero is
    exercised rather than assumed.
    """
    payload: Dict[str, Any] = {
        "fed_at": fed_at,
        "feed_lbs": feed_lbs,
        "avg_weight_g_after": avg_weight_g_after,
    }
    if mortality_count is not _OMIT:
        payload["mortality_count"] = mortality_count
    return payload


def advance_stage_payload(to_stage: str = STAGE_FRY) -> Dict[str, Any]:
    return {"to_stage": to_stage}


# ─── Fish health ──────────────────────────────────────

def health_inspection_payload(lot_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "lot_id": lot_id,
        "inspection_type": INSPECTION_TYPE_PRE_TRANSFER,
        "sample_size": 60,
        "sampled_at": instant(2026, 8, 1),
    }
    return _apply(payload, overrides)


def record_result_payload(
    result: str = RESULT_NEGATIVE, pathogen_code: Any = _OMIT
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"result": result}
    if pathogen_code is not _OMIT:
        payload["pathogen_code"] = pathogen_code
    return payload


def record_treatment_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "treatment_code": TREATMENT_CODE_FORMALIN,
        "withdrawal_days": 5,
        "treatment_completed_at": instant(2026, 8, 25),
    }
    return _apply(payload, overrides)


# ─── Demand intake ────────────────────────────────────

def stocking_request_payload(water_id: str, **overrides: Any) -> Dict[str, Any]:
    """
    A request body. `requester_kind` is deliberately absent: PRD 3.6 states it is
    never accepted from the body and is derived from the acting role.
    """
    payload: Dict[str, Any] = {
        "water_id": water_id,
        "species": SPECIES_RAINBOW_TROUT,
        "requested_count": 2400,
        "size_class": SIZE_CLASS_YEARLING,
        "justification": "Opening-day put-and-take fishery on Blue Mesa",
    }
    return _apply(payload, overrides)


# ─── Allocation ───────────────────────────────────────

def allocation_plan_payload(hatchery_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "hatchery_id": hatchery_id,
        "fiscal_year": 2027,
        "species": SPECIES_RAINBOW_TROUT,
        "size_class": SIZE_CLASS_YEARLING,
        "available_count": 5000,
        "public_request_cap_pct": 0.20,
        "allocation_mode": MODE_PRIORITY_WATERFALL,
    }
    return _apply(payload, overrides)


def attach_to_plan_payload(
    allocation_plan_id: str, expected_plan_version: int
) -> Dict[str, Any]:
    return {
        "allocation_plan_id": allocation_plan_id,
        "expected_plan_version": expected_plan_version,
    }


def run_plan_payload(expected_plan_version: int) -> Dict[str, Any]:
    return {"expected_plan_version": expected_plan_version}


# ─── Fleet and trips ──────────────────────────────────

def transport_unit_payload(hatchery_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "hatchery_id": hatchery_id,
        "unit_code": "TRK-01",
        "tank_gallons": 500.0,
        "max_load_lbs": 300.0,
        "oxygen_lpm": 12.0,
        "certification_expires_at": instant(2027, 1, 1),
    }
    return _apply(payload, overrides)


def stocking_event_payload(
    stocking_request_id: str,
    lot_id: str,
    transport_unit_id: str,
    expected_lot_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    A trip body. The three identifiers are declared in the PRD's order —
    `stocking_request_id`, then `lot_id`, then `transport_unit_id` — because body
    keys are resolved strictly left to right. `mark_type` and `marked_count` are
    optional and are omitted unless a test supplies them.
    """
    payload: Dict[str, Any] = {
        "stocking_request_id": stocking_request_id,
        "lot_id": lot_id,
        "transport_unit_id": transport_unit_id,
        "fish_count": 2400,
        "scheduled_depart_at": instant(2026, 9, 1, 8),
        "scheduled_return_at": instant(2026, 9, 1, 14),
        "expected_lot_version": expected_lot_version,
    }
    return _apply(payload, overrides)


def load_payload(
    loaded_at: str,
    load_water_temp_c: float,
    measured_load_lbs: Any = _OMIT,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "loaded_at": loaded_at,
        "load_water_temp_c": load_water_temp_c,
    }
    if measured_load_lbs is not _OMIT:
        payload["measured_load_lbs"] = measured_load_lbs
    return payload


def release_payload(
    arrived_at: str,
    site_water_temp_c: float,
    tempering_minutes: int,
    transport_mortality_count: Any = _OMIT,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "arrived_at": arrived_at,
        "site_water_temp_c": site_water_temp_c,
        "tempering_minutes": tempering_minutes,
    }
    if transport_mortality_count is not _OMIT:
        payload["transport_mortality_count"] = transport_mortality_count
    return payload


def recoveries_payload(
    recovered_count: int, creel_sample_fraction: float
) -> Dict[str, Any]:
    return {
        "recovered_count": recovered_count,
        "creel_sample_fraction": creel_sample_fraction,
    }


OMIT: Any = _OMIT
