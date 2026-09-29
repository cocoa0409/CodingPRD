"""Payload factories — one per write endpoint, input fields only.

Money is always an integer number of cents sent as a JSON number, never a
string. Every field the PRD declares as an ISO 8601 UTC instant is sent as a
full instant, never as a date-only literal; `show_date` and `birth_date` are
the only calendar dates in the API and are sent in year-month-day form.
"""

from typing import Any, Dict, List, Optional

from .constants import DOG_NAMES, DOG_REGISTRATION_NUMBERS, TEST_DEFAULTS


def create_club_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": TEST_DEFAULTS["CLUB_NAME"],
        "club_code": TEST_DEFAULTS["CLUB_CODE"],
        "region_code": TEST_DEFAULTS["REGION_CODE"],
        "annual_event_allowance": 2,
    }
    payload.update(overrides)
    return payload


def create_judge_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "judge_number": TEST_DEFAULTS["JUDGE_NUMBER"],
        "full_name": TEST_DEFAULTS["JUDGE_NAME"],
        "approved_breed_group_codes": ["SPORTING"],
        "approved_performance_disciplines": ["OBEDIENCE"],
        "home_region_code": TEST_DEFAULTS["REGION_CODE"],
        "max_daily_dog_count": 175,
    }
    payload.update(overrides)
    return payload


def create_handler_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "handler_name": TEST_DEFAULTS["HANDLER_NAME"],
        "member_number": TEST_DEFAULTS["MEMBER_NUMBER"],
        "region_code": TEST_DEFAULTS["REGION_CODE"],
    }
    payload.update(overrides)
    return payload


def create_show_payload(club_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "club_id": club_id,
        "show_name": TEST_DEFAULTS["SHOW_NAME"],
        "show_date": TEST_DEFAULTS["SHOW_DATE"],
        "show_type": "CONFORMATION",
        "venue_name": TEST_DEFAULTS["VENUE_NAME"],
        "outdoor_venue": False,
        "entry_open_at": TEST_DEFAULTS["ENTRY_OPEN_AT"],
        "entry_close_at": TEST_DEFAULTS["ENTRY_CLOSE_AT"],
        "max_total_entries": TEST_DEFAULTS["MAX_TOTAL_ENTRIES"],
        "championship_points_scale": "SCALE_A",
    }
    payload.update(overrides)
    return payload


def create_panel_slot_payload(
    show_id: str, judge_id: str, expected_judge_version: int, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "show_id": show_id,
        "judge_id": judge_id,
        "panel_role": "BREED_JUDGE",
        "expected_judge_version": expected_judge_version,
    }
    payload.update(overrides)
    return payload


def respond_to_slot_payload(decision: str = "ACCEPT", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def create_breed_class_payload(show_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "show_id": show_id,
        "class_code": "B1",
        "class_level": "BREED",
        "breed_code": TEST_DEFAULTS["BREED_CODE"],
        "group_code": TEST_DEFAULTS["GROUP_CODE"],
        "entry_limit": TEST_DEFAULTS["ENTRY_LIMIT"],
    }
    payload.update(overrides)
    return payload


def create_group_class_payload(show_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "show_id": show_id,
        "class_code": "G1",
        "class_level": "GROUP",
        "group_code": TEST_DEFAULTS["GROUP_CODE"],
        "entry_limit": TEST_DEFAULTS["ENTRY_LIMIT"],
    }
    payload.update(overrides)
    return payload


def create_best_in_show_class_payload(show_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "show_id": show_id,
        "class_code": "BIS1",
        "class_level": "BEST_IN_SHOW",
        "entry_limit": TEST_DEFAULTS["ENTRY_LIMIT"],
    }
    payload.update(overrides)
    return payload


def create_performance_class_payload(
    show_id: str, discipline: str = "OBEDIENCE", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "show_id": show_id,
        "class_code": "P1",
        "class_level": "PERFORMANCE",
        "discipline": discipline,
        "entry_limit": TEST_DEFAULTS["ENTRY_LIMIT"],
    }
    if discipline == "AGILITY":
        payload["jump_height_cm"] = 30
    payload.update(overrides)
    return payload


def assign_judge_payload(slot_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"slot_id": slot_id}
    payload.update(overrides)
    return payload


def create_dog_payload(owner_handler_id: str, index: int = 0, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "registration_number": DOG_REGISTRATION_NUMBERS[index % len(DOG_REGISTRATION_NUMBERS)],
        "call_name": DOG_NAMES[index % len(DOG_NAMES)],
        "breed_code": TEST_DEFAULTS["BREED_CODE"],
        "group_code": TEST_DEFAULTS["GROUP_CODE"],
        "sex": "DOG",
        "birth_date": TEST_DEFAULTS["BIRTH_DATE"],
        "owner_handler_id": owner_handler_id,
    }
    payload.update(overrides)
    return payload


def measurement_payload(
    measured_height_cm: float, card_type: str = "TEMP_CARD", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "measured_height_cm": measured_height_cm,
        "card_type": card_type,
    }
    payload.update(overrides)
    return payload


def create_entry_payload(
    show_id: str, class_id: str, dog_id: str, handler_id: str, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "show_id": show_id,
        "class_id": class_id,
        "dog_id": dog_id,
        "handler_id": handler_id,
    }
    payload.update(overrides)
    return payload


def check_in_payload(attendance: str = "PRESENT", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"attendance": attendance}
    payload.update(overrides)
    return payload


def temperature_reading_payload(
    recorded_temp_c: float, relative_humidity_pct: int, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "recorded_temp_c": recorded_temp_c,
        "relative_humidity_pct": relative_humidity_pct,
    }
    payload.update(overrides)
    return payload


def create_ring_block_payload(
    show_id: str,
    class_id: str,
    slot_id: str,
    expected_show_version: int,
    ring_number: int = 1,
    block_start_at: str = "2026-09-12T09:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "show_id": show_id,
        "class_id": class_id,
        "slot_id": slot_id,
        "ring_number": ring_number,
        "block_start_at": block_start_at,
        "expected_show_version": expected_show_version,
    }
    payload.update(overrides)
    return payload


def reschedule_ring_block_payload(
    block_start_at: str, expected_show_version: int, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "block_start_at": block_start_at,
        "expected_show_version": expected_show_version,
    }
    payload.update(overrides)
    return payload


def complete_class_payload(placements: List[str], **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"placements": list(placements)}
    payload.update(overrides)
    return payload


def create_performance_run_payload(
    entry_id: str,
    course_yardage_m: float,
    standard_course_time_s: float,
    actual_time_s: float,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "entry_id": entry_id,
        "course_yardage_m": course_yardage_m,
        "standard_course_time_s": standard_course_time_s,
        "actual_time_s": actual_time_s,
    }
    payload.update(overrides)
    return payload


def create_protest_payload(
    show_id: str,
    entry_id: str,
    filed_by_handler_id: str,
    protest_type: str = "MEASUREMENT",
    statement: str = "Winner appears over height.",
    deposit_cents: int = 5000,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "show_id": show_id,
        "entry_id": entry_id,
        "filed_by_handler_id": filed_by_handler_id,
        "protest_type": protest_type,
        "statement": statement,
        "deposit_cents": deposit_cents,
    }
    payload.update(overrides)
    return payload


def request_evidence_payload(evidence_request: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"evidence_request": evidence_request}
    payload.update(overrides)
    return payload


def resubmit_evidence_payload(evidence_note: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"evidence_note": evidence_note}
    payload.update(overrides)
    return payload


def decide_protest_payload(
    decision: str, resolution_code: str, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": decision,
        "resolution_code": resolution_code,
    }
    payload.update(overrides)
    return payload


def create_registry_filing_payload(show_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"show_id": show_id}
    payload.update(overrides)
    return payload


def adjudicate_filing_payload(
    decision: str, reject_reason: Optional[str] = None, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if reject_reason is not None:
        payload["reject_reason"] = reject_reason
    payload.update(overrides)
    return payload


def return_show_payload(return_reason: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"return_reason": return_reason}
    payload.update(overrides)
    return payload
