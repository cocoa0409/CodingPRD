"""Payload factories — one per entity, input fields only.

Every money field is an integer count of cents and is emitted as a JSON number,
never a string.  Every instant field is a full ISO-8601 UTC instant
(``YYYY-MM-DDTHH:MM:SSZ``); only the fields the PRD declares as calendar dates
(``season_start_date``, ``arrival_date``, ``birth_date``, ``signed_on``,
``observed_on``, ``hired_on``, ``contract_end_date``) are date-only.
"""
from typing import Any, Dict, List, Optional

from .constants import (
    ARRIVAL_DATE,
    DEPARTURE_DATE,
    SEASON_ARRIVAL_WEEKDAY,
    SEASON_BUYOUT_PREMIUM_PCT,
    SEASON_DEPOSIT_PCT,
    SEASON_DINING_SEAT_CAPACITY,
    SEASON_END_DATE,
    SEASON_MAX_STAY_NIGHTS,
    SEASON_MIN_STAY_NIGHTS,
    SEASON_NAME,
    SEASON_NO_SHOW_PENALTY_CENTS,
    SEASON_RETENTION_BONUS_CENTS,
    SEASON_START_DATE,
    SLOT_ENDS_AT,
    SLOT_STARTS_AT,
    TIER_CLASSIC,
)


def create_season_payload(**overrides: Any) -> Dict[str, Any]:
    """Season creation payload with the canonical weekly-package cadence."""
    payload: Dict[str, Any] = {
        "name": SEASON_NAME,
        "arrival_weekday": SEASON_ARRIVAL_WEEKDAY,
        "season_start_date": SEASON_START_DATE,
        "season_end_date": SEASON_END_DATE,
        "min_stay_nights": SEASON_MIN_STAY_NIGHTS,
        "max_stay_nights": SEASON_MAX_STAY_NIGHTS,
        "deposit_pct": SEASON_DEPOSIT_PCT,
        "buyout_premium_pct": SEASON_BUYOUT_PREMIUM_PCT,
        "no_show_penalty_cents": SEASON_NO_SHOW_PENALTY_CENTS,
        "retention_bonus_cents": SEASON_RETENTION_BONUS_CENTS,
        "dining_seat_capacity": SEASON_DINING_SEAT_CAPACITY,
        "package_tiers": [dict(TIER_CLASSIC)],
    }
    payload.update(overrides)
    return payload


def create_cabin_payload(name: str = "Aspen", bed_capacity: int = 4, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"name": name, "bed_capacity": bed_capacity}
    payload.update(overrides)
    return payload


def create_guest_payload(
    full_name: str = "Ann Adult",
    birth_date: str = "1985-04-02",
    weight_lb: float = 165,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "birth_date": birth_date,
        "weight_lb": weight_lb,
    }
    payload.update(overrides)
    return payload


def waiver_signature_payload(
    signed_on: str = "2026-08-01",
    equine_statute_ack: bool = True,
    guardian_guest_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "signed_on": signed_on,
        "equine_statute_ack": equine_statute_ack,
    }
    if guardian_guest_id is not None:
        payload["waiver_signed_by_guardian_guest_id"] = guardian_guest_id
    payload.update(overrides)
    return payload


def rider_assessment_payload(
    requested_ability: str = "BEGINNER",
    expected_guest_version: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "requested_ability": requested_ability,
        "expected_guest_version": expected_guest_version,
    }
    payload.update(overrides)
    return payload


def evaluate_assessment_payload(
    assessed_ability: str = "BEGINNER",
    assessed_by_note: str = "walk-trot in arena",
    evaluated_at: str = "2026-08-01T12:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "assessed_ability": assessed_ability,
        "assessed_by_note": assessed_by_note,
        "evaluated_at": evaluated_at,
    }
    payload.update(overrides)
    return payload


def party_member(
    guest_id: str,
    member_type: str = "ADULT",
    dietary_restrictions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "guest_id": guest_id,
        "member_type": member_type,
        "dietary_restrictions": list(dietary_restrictions or ["NONE"]),
    }


def create_booking_payload(
    season_id: str,
    cabin_id: str,
    lead_guest_id: str,
    party_members: List[Dict[str, Any]],
    package_tier_code: str = "CLASSIC",
    arrival_date: str = ARRIVAL_DATE,
    departure_date: str = DEPARTURE_DATE,
    is_buyout: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "season_id": season_id,
        "cabin_id": cabin_id,
        "lead_guest_id": lead_guest_id,
        "package_tier_code": package_tier_code,
        "arrival_date": arrival_date,
        "departure_date": departure_date,
        "party_members": party_members,
    }
    if is_buyout is not None:
        payload["is_buyout"] = is_buyout
    payload.update(overrides)
    return payload


def payment_payload(amount_cents: int, kind: str = "DEPOSIT", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"kind": kind, "amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def check_in_payload(dietary_briefing_ack: bool = True, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"dietary_briefing_ack": dietary_briefing_ack}
    payload.update(overrides)
    return payload


def check_out_payload(settle_payment_cents: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"settle_payment_cents": settle_payment_cents}
    payload.update(overrides)
    return payload


def folio_adjustment_payload(
    amount_cents: int,
    memo: str,
    expected_booking_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "amount_cents": amount_cents,
        "memo": memo,
        "expected_booking_version": expected_booking_version,
    }
    payload.update(overrides)
    return payload


def create_horse_payload(
    name: str = "Comet",
    min_rider_ability: str = "BEGINNER",
    max_rider_ability: str = "ADVANCED",
    weight_limit_lb: float = 240,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name,
        "min_rider_ability": min_rider_ability,
        "max_rider_ability": max_rider_ability,
        "weight_limit_lb": weight_limit_lb,
    }
    payload.update(overrides)
    return payload


def health_event_payload(
    event_type: str,
    observed_on: str = "2026-10-11",
    note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"event_type": event_type, "observed_on": observed_on}
    if note is not None:
        payload["note"] = note
    payload.update(overrides)
    return payload


def create_activity_slot_payload(
    activity_type: str = "TRAIL_RIDE",
    starts_at: str = SLOT_STARTS_AT,
    ends_at: str = SLOT_ENDS_AT,
    terrain_grade: str = "MEADOW",
    min_ability_rank: str = "BEGINNER",
    capacity: int = 4,
    rider_surcharge_cents: int = 20000,
    mount_required: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "activity_type": activity_type,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "terrain_grade": terrain_grade,
        "min_ability_rank": min_ability_rank,
        "capacity": capacity,
        "rider_surcharge_cents": rider_surcharge_cents,
        "mount_required": mount_required,
    }
    payload.update(overrides)
    return payload


def guide_assignment_payload(
    staff_member_id: str, guide_role: str = "LEAD", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "staff_member_id": staff_member_id,
        "guide_role": guide_role,
    }
    payload.update(overrides)
    return payload


def reservation_payload(
    booking_id: str, guest_id: str, expected_slot_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "booking_id": booking_id,
        "guest_id": guest_id,
        "expected_slot_version": expected_slot_version,
    }
    payload.update(overrides)
    return payload


def mount_assignment_payload(
    horse_id: str, expected_horse_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "horse_id": horse_id,
        "expected_horse_version": expected_horse_version,
    }
    payload.update(overrides)
    return payload


def complete_slot_payload(actual_duration_hours: float = 2.0, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"actual_duration_hours": actual_duration_hours}
    payload.update(overrides)
    return payload


def create_staff_member_payload(
    full_name: str = "Gus Guide",
    role_type: str = "GUIDE",
    certifications: Optional[List[str]] = None,
    hired_on: str = "2026-08-01",
    contract_end_date: str = "2026-11-15",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "role_type": role_type,
        "certifications": list(
            certifications
            if certifications is not None
            else ["EQUINE_HANDLER", "WILDERNESS_FIRST_AID"]
        ),
        "hired_on": hired_on,
        "contract_end_date": contract_end_date,
    }
    payload.update(overrides)
    return payload


def onboard_payload(
    housing_unit_code: str = "BUNKHOUSE-A",
    housing_bunk_number: int = 3,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "housing_unit_code": housing_unit_code,
        "housing_bunk_number": housing_bunk_number,
    }
    payload.update(overrides)
    return payload


def incident_report_payload(
    severity: str = "MINOR",
    equine_activity_statute_notice_given: bool = True,
    narrative: str = "rider slipped dismounting at the corral",
    occurred_at: str = "2026-10-12T16:00:00Z",
    horse_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "severity": severity,
        "equine_activity_statute_notice_given": equine_activity_statute_notice_given,
        "narrative": narrative,
        "occurred_at": occurred_at,
    }
    if horse_id is not None:
        payload["horse_id"] = horse_id
    payload.update(overrides)
    return payload


def dispose_payload(
    disposition: str = "CLEARED",
    disposition_note: str = "no equipment defect found",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "disposition": disposition,
        "disposition_note": disposition_note,
    }
    payload.update(overrides)
    return payload


def close_incident_payload(remediation_completed: bool = False, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"remediation_completed": remediation_completed}
    payload.update(overrides)
    return payload


def maintenance_hold_payload(
    season_id: str,
    maintenance_project_code: str = "ROOF-2026",
    maintenance_capital_cost_cents: int = 100000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "season_id": season_id,
        "maintenance_project_code": maintenance_project_code,
        "maintenance_capital_cost_cents": maintenance_capital_cost_cents,
    }
    payload.update(overrides)
    return payload
