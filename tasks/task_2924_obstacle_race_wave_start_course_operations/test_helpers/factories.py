"""Request-payload builders.

Every builder returns a plain dict that satisfies the PRD's schema rung for
that endpoint, and accepts keyword overrides. Two conventions matter:

* Money is always an integer number of whole cents (PRD §2.9) — never a string.
* Every timestamp field is a full ISO-8601 UTC instant (PRD §2.4), never a
  date-only string.

Optional fields whose presence is itself load-bearing (`paired_obstacle_id`,
`obstacle_id`, `team_code`, `medical_flags`, notes) are omitted unless supplied.
"""

from itertools import count
from typing import Any, Dict, Optional

from .constants import (
    ASSIGNMENT_CONFIRMED,  # noqa: F401  (re-exported for symmetry)
    BYPASS_MODE_NONE,
    BYPASS_POLICY_ALLOWED_WITH_PENALTY,
    CERT_ADVANCED,
    DIVISION_OPEN,
    SCORING_GUN_TIME,
    SERVICE_BAG_CHECK,
    SETTLEMENT_PROGRESSIVE,
    STAFF_ROLE_MARSHAL,
    STAFF_PERSON_1,
    TASK_TYPE_RESEED,
    TERRAIN_QUARRY,
    WATER_ACCESS_POND,
)

_seq = count(1)


def next_seq() -> int:
    """A process-unique integer, for fields the PRD requires to be unique."""
    return next(_seq)


# ─── Canonical race-day instants ────────────────────────────────────────
#
# The logical clock reads 2026-08-01T00:00:00Z until a test moves it, so every
# default below sits in the future relative to that reading.

RACE_DAY = "2026-09-12"
GUN_UTC = "2026-09-12T08:00:00.000Z"
PERMIT_VALID_UNTIL_UTC = "2026-09-15T00:00:00.000Z"
RESTORATION_DEADLINE_UTC = "2026-09-20T00:00:00.000Z"
SHIFT_START_UTC = "2026-09-12T07:00:00.000Z"
SHIFT_END_UTC = "2026-09-12T11:00:00.000Z"


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides, and let an override of `None` delete a default key."""
    merged = dict(base)
    for key, value in overrides.items():
        if value is _OMIT:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


class _Omit:
    def __repr__(self) -> str:  # pragma: no cover
        return "<OMIT>"


#: Pass `field=OMIT` to drop a field the builder supplies by default.
OMIT = _Omit()
_OMIT = OMIT


# ─── Venue and permit (PRD §3.1) ────────────────────────────────────────


def venue_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": "Ridgeline Quarry",
            "terrain_type": TERRAIN_QUARRY,
            "water_access": WATER_ACCESS_POND,
            "land_use_zone": "AG-2",
            "protected_acreage_sqm": 1000,
            "restoration_bond_cents": 1000000,
        },
        overrides,
    )


def permit_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "permit_number": f"LUP-{next_seq():05d}",
            "water_use_allowed": True,
            "max_disturbed_area_sqm": 10000,
            "quiet_hours_start_hour_utc": 22,
            "quiet_hours_end_hour_utc": 6,
            "valid_until_utc": PERMIT_VALID_UNTIL_UTC,
            "restoration_deadline_utc": RESTORATION_DEADLINE_UTC,
        },
        overrides,
    )


def decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


# ─── Course and obstacles (PRD §3.2) ────────────────────────────────────


def course_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": "Quarry Gauntlet",
            "total_distance_m": 5000,
            "corral_release_rate_per_min": 20.00,
            "corral_throughput_capacity": 200,
        },
        overrides,
    )


def obstacle_payload(
    station_index: int = 1, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "name": f"Station {station_index}",
            "station_index": station_index,
            "difficulty_rating": 5,
            "lane_count": 4,
            "service_rate_per_min": 3.00,
            "marshals_required": 2,
            "footprint_sqm": 1300,
            "water_contact": False,
            "bypass_mode": BYPASS_MODE_NONE,
            "penalty_seconds": 60,
        },
        overrides,
    )


# ─── Staffing (PRD §3.3) ────────────────────────────────────────────────


def staff_payload(
    staff_role: str = STAFF_ROLE_MARSHAL,
    obstacle_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "staff_person_id": STAFF_PERSON_1,
        "staff_role": staff_role,
        "certification_level": CERT_ADVANCED,
        "shift_start_utc": SHIFT_START_UTC,
        "shift_end_utc": SHIFT_END_UTC,
    }
    if obstacle_id is not None:
        payload["obstacle_id"] = obstacle_id
    return _merge(payload, overrides)


def vacate_payload(reason: str = "Called away to the medical tent") -> Dict[str, Any]:
    return {"reason": reason}


# ─── Divisions and heats (PRD §3.4) ─────────────────────────────────────


def division_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": "Open Wave",
            "division_type": DIVISION_OPEN,
            "bypass_policy": BYPASS_POLICY_ALLOWED_WITH_PENALTY,
            "scoring_mode": SCORING_GUN_TIME,
            "min_age": 18,
            "team_size_min": 1,
            "team_size_max": 1,
        },
        overrides,
    )


def wave_payload(division_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "division_id": division_id,
            "wave_code": f"A{next_seq()}",
            "scheduled_start_utc": GUN_UTC,
            "capacity": 50,
        },
        overrides,
    )


def hold_payload(held: bool, **overrides: Any) -> Dict[str, Any]:
    return _merge({"held": held}, overrides)


# ─── Participants and entries (PRD §3.5) ────────────────────────────────


def participant_payload(**overrides: Any) -> Dict[str, Any]:
    serial = next_seq()
    return _merge(
        {
            "full_name": f"Runner {serial}",
            "birth_year": 1990,
            "email": f"runner{serial}@example.com",
            "chip_id": f"CHIP-{serial:06d}",
        },
        overrides,
    )


def waiver_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"signature_name": "Runner Signature"}, overrides)


def entry_payload(participant_id: str, bib_number: int = 1, **overrides: Any):
    return _merge(
        {"participant_id": participant_id, "bib_number": bib_number}, overrides
    )


def check_in_payload(
    chip_start_offset_seconds: int = 0, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "bag_tag_code": f"BAG-{next_seq():05d}",
            "chip_start_offset_seconds": chip_start_offset_seconds,
        },
        overrides,
    )


def reassign_payload(target_wave_id: str) -> Dict[str, Any]:
    return {"target_wave_id": target_wave_id}


# ─── Attempts, protests and adjudications (PRD §3.7, §3.8) ──────────────


def attempt_payload(obstacle_id: str, outcome: str, **overrides: Any):
    return _merge({"obstacle_id": obstacle_id, "outcome": outcome}, overrides)


def protest_payload(disputed_attempt_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "disputed_attempt_id": disputed_attempt_id,
            "reason": "The marshal recorded a bypass I never took.",
        },
        overrides,
    )


def adjudication_payload(
    outcome: str, expected_entry_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"outcome": outcome, "expected_entry_version": expected_entry_version},
        overrides,
    )


# ─── Festival area, restoration and the bond (PRD §3.9) ─────────────────


def festival_service_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "service_type": SERVICE_BAG_CHECK,
            "footprint_sqm": 600,
            "capacity": 400,
            "water_draw_lpm": 0,
        },
        overrides,
    )


def restoration_task_payload(area_sqm: int = 1500, **overrides: Any) -> Dict[str, Any]:
    return _merge({"task_type": TASK_TYPE_RESEED, "area_sqm": area_sqm}, overrides)


def inspection_payload(outcome: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"outcome": outcome}, overrides)


def bond_release_payload(
    expected_venue_version: int,
    settlement_type: str = SETTLEMENT_PROGRESSIVE,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "settlement_type": settlement_type,
            "expected_venue_version": expected_venue_version,
        },
        overrides,
    )
