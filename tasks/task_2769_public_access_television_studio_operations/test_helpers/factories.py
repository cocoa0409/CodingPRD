"""Request-payload builders with valid defaults.

Every builder returns a payload that satisfies the PRD's schema constraints for
its endpoint, and accepts keyword overrides so a test can vary exactly the one
field its rule is about. Money is always whole cents as a JSON integer; the
only field the PRD emits as a JSON number is the community impact index, which
is computed by the server and never supplied by a client.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    CURRENT_STATEMENT_VERSION,
    TEST_DEFAULTS,
)

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A short suffix so natural keys inside one test never collide."""
    return "{:04d}".format(next(_counter))


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not _OMIT}


class _Omit(object):
    def __repr__(self):
        return "<omit>"


_OMIT = _Omit()
OMIT = _OMIT


# --------------------------------------------------------------- producers
def producer_payload(**overrides: Any) -> Dict[str, Any]:
    suffix = unique_suffix()
    return _merge(
        {
            "legal_name": "Ada Rivers",
            "email": "ada.rivers.{}@patv.example".format(suffix),
        },
        overrides,
    )


def residency_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"document_reference": "UTIL-2026-{}".format(unique_suffix())}, overrides)


def reinstate_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"suspension_points_credited": 1, "reason": "Damage charge settled in full"}, overrides
    )


def revoke_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"revocation_reason": "Repeated equipment abuse"}, overrides)


# --------------------------------------------------------- training courses
def training_course_payload(**overrides: Any) -> Dict[str, Any]:
    suffix = unique_suffix()
    return _merge(
        {
            "course_code": "TV-{}".format(suffix),
            "title": "Studio Basics",
            "tier": "BASIC",
            "grants_competency_codes": ["STUDIO_FLOOR", "EDIT_SUITE"],
            "seat_capacity": TEST_DEFAULTS["SEAT_CAPACITY"],
            "session_start_at": "2026-08-05T17:00:00Z",
            "session_end_at": "2026-08-05T21:00:00Z",
        },
        overrides,
    )


def enrollment_payload(producer_id: str, course_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"producer_id": producer_id, "course_id": course_id}, overrides)


def attendance_payload(attended: bool = True, **overrides: Any) -> Dict[str, Any]:
    return _merge({"attended": attended}, overrides)


def grade_payload(practical_score: int = 88, **overrides: Any) -> Dict[str, Any]:
    return _merge({"practical_score": practical_score}, overrides)


# ------------------------------------------------------------------ series
def series_payload(producer_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "producer_id": producer_id,
            "title": "Riverside Weekly",
            "cadence": "WEEKLY",
            "first_air_date": "2026-08-20T00:00:00Z",
            "predecessor_series_id": None,
        },
        overrides,
    )


def hold_plan_payload(expected_series_version: int, slots: int = 4, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "expected_series_version": expected_series_version,
            "hold_plan_slots_granted": slots,
        },
        overrides,
    )


# ---------------------------------------------------------------- programs
def program_payload(producer_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "producer_id": producer_id,
            "title": "Riverside Council Recap",
            "runtime_seconds": TEST_DEFAULTS["PROGRAM_RUNTIME_SECONDS"],
            "is_live": False,
            "required_crew_roles": [],
        },
        overrides,
    )


def attestation_payload(
    producer_id: str, attestation_kind: str = "CONTENT_POLICY", **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "signed_by_producer_id": producer_id,
            "attestation_kind": attestation_kind,
            "statement_version": CURRENT_STATEMENT_VERSION,
            "third_party_material": False,
        },
        overrides,
    )


def review_decision_payload(decision: str = "APPROVE", **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def request_changes_payload(
    finding_category: str = "TECHNICAL_STANDARDS_FAILURE",
    finding_notes: str = "Audio levels clip in reel one",
    **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "decision": "REQUEST_CHANGES",
            "finding_category": finding_category,
            "finding_notes": finding_notes,
        },
        overrides,
    )


def program_withdraw_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"withdrawn_reason": "Producer pulled the episode for re-editing"}, overrides
    )


# ---------------------------------------------------------------- channels
def channel_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "call_sign": "PATV{}".format(unique_suffix()),
            "tier": "PUBLIC",
            "daily_window_start_minute": TEST_DEFAULTS["CHANNEL_WINDOW_START_MINUTE"],
            "daily_window_end_minute": TEST_DEFAULTS["CHANNEL_WINDOW_END_MINUTE"],
            "inter_program_buffer_seconds": TEST_DEFAULTS["CHANNEL_BUFFER_SECONDS"],
        },
        overrides,
    )


# ----------------------------------------------------------- playback slots
def playback_slot_payload(
    channel_id: str, program_id: str, start_at: str = "2026-08-20T18:00:00Z", **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"channel_id": channel_id, "program_id": program_id, "start_at": start_at}, overrides
    )


def air_payload(measured_households: int = 640, **overrides: Any) -> Dict[str, Any]:
    return _merge({"measured_households": measured_households}, overrides)


def slot_cancel_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"cancellation_reason": "Coordinator freed the window"}, overrides)


# --------------------------------------------------------- crew assignments
def crew_assignment_payload(
    slot_id: str, volunteer_producer_id: str, crew_role: str = "CAMERA", **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "slot_id": slot_id,
            "volunteer_producer_id": volunteer_producer_id,
            "crew_role": crew_role,
        },
        overrides,
    )


def crew_release_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"release_reason": "Volunteer withdrew from the shift"}, overrides)


# --------------------------------------------------------- studio resources
def studio_resource_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "resource_code": "STUDIO-{}".format(unique_suffix()),
            "resource_class": "STUDIO_A",
            "required_competency_code": "STUDIO_FLOOR",
            "capacity_slots": 1,
            "turnaround_minutes": 0,
            "base_deposit_cents": TEST_DEFAULTS["BASE_DEPOSIT_CENTS"],
            "replacement_value_cents": TEST_DEFAULTS["REPLACEMENT_VALUE_CENTS"],
        },
        overrides,
    )


def resource_status_payload(status: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"status": status, "status_reason": "Annual service window"}, overrides)


# ------------------------------------------------------------ reservations
def reservation_payload(
    producer_id: str,
    resource_id: str,
    start_at: str = "2026-08-08T10:00:00Z",
    end_at: str = "2026-08-08T12:00:00Z",
    **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "producer_id": producer_id,
            "resource_id": resource_id,
            "start_at": start_at,
            "end_at": end_at,
        },
        overrides,
    )


def reservation_cancel_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"cancellation_reason": "Producer rescheduled the shoot"}, overrides)


def checkout_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"condition_notes": "Handed over clean and complete"}, overrides)


def clean_return_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"damage_observed": False, "condition_notes": "No damage observed"}, overrides
    )


def damaged_return_payload(
    severity: str = "MINOR", repair_estimate_cents: int = 40000, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "damage_observed": True,
            "severity": severity,
            "repair_estimate_cents": repair_estimate_cents,
            "damage_notes": "Pedestal column bent",
        },
        overrides,
    )


def waiver_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"waiver_reason": "Bend predated the checkout per archived condition photos"},
        overrides,
    )


# ---------------------------------------------------------- funding periods
def funding_period_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "fiscal_year": 2026,
            "quarter": 3,
            "basis": "ACCRUAL",
            "gross_franchise_fee_cents": 5200000,
            "service_period_earned_cents": 5000000,
            "remittance_received_cents": 4800000,
            "capital_grant_cents": 100000,
        },
        overrides,
    )


def revise_funding_payload(expected_version: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"expected_funding_period_version": expected_version}, overrides)


def report_decision_payload(decision: str = "ACCEPT", **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


# ----------------------------------------------------------- archive assets
def publish_payload(retention_class: str = "STANDARD_24M", **overrides: Any) -> Dict[str, Any]:
    return _merge({"retention_class": retention_class}, overrides)


def record_views_payload(on_demand_views: int = 250, **overrides: Any) -> Dict[str, Any]:
    return _merge({"on_demand_views": on_demand_views}, overrides)


# --------------------------------------------------------------- utilities
def competency_course_payload(tier: str, codes: List[str], **overrides: Any) -> Dict[str, Any]:
    """A course of a given tier granting a given competency set."""
    return training_course_payload(tier=tier, grants_competency_codes=codes, **overrides)


def crew_roles(*roles: str) -> List[str]:
    return list(roles)


def optional(value: Optional[Any]) -> Any:
    """Return ``OMIT`` for ``None`` so a builder leaves the key out entirely."""
    return _OMIT if value is None else value
