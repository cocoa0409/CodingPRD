"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import READINESS_CEILING

COMMON_FIELDS = ("id", "created_at", "updated_at", "version")


def assert_same_instant(actual: str, expected: str, label: str = "timestamp") -> None:
    """Compare two ISO 8601 timestamps by instant, not by byte formatting.

    PRD §2.2/§2.5 pin the three-fractional-digit notation for the server-managed
    `api_request_timestamp`, `created_at` and `updated_at` only. For every other
    timestamp field the PRD fixes the instant (a region's `term_start_date`, a
    support record's `session_start`, an application's `offer_expires_at`), never
    the notation, so a conforming server may render `...T15:00:00Z` either as
    written or in its own house format `...T15:00:00.000Z`.
    """

    def _parse(value: str) -> datetime:
        raw = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    assert isinstance(actual, str), f"{label} must be a string, got {actual!r}"
    assert _parse(actual) == _parse(expected), (
        f"{label} {actual!r} is not the instant {expected!r}"
    )


def _assert_common_fields(data: dict) -> None:
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer starting at 1, got {data.get('version')!r}"
    )


def _assert_no_extra_terminal_keys(data: dict, keys) -> None:
    for key in keys:
        assert key in data, f"missing field {key!r}"


# ─── Per-entity assertions ────────────────────────────

def assert_region(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert len(data["state_code"]) == 2 and data["state_code"].isupper(), (
        "state_code must be exactly two uppercase letters"
    )
    assert is_iso8601_timestamp(data["term_start_date"])
    assert isinstance(data["base_placement_fee_cents"], int)
    assert isinstance(data["max_corps_members"], int) and data["max_corps_members"] >= 1


def assert_partner_district(data: dict) -> None:
    _assert_common_fields(data)
    assert data["agreement_status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED")
    for field in (
        "hiring_commitment_slots",
        "placement_fee_per_member_cents",
        "unfilled_slot_penalty_cents",
        "fee_budget_cents",
        "committed_placement_count",
        "invoice_amount_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["committed_placement_count"] >= 0
    assert data["invoice_amount_cents"] >= 0


def assert_partner_school(data: dict) -> None:
    _assert_common_fields(data)
    assert data["grade_band"] in ("ELEMENTARY", "MIDDLE", "HIGH")
    assert isinstance(data["subject_needs"], list) and len(data["subject_needs"]) >= 1
    assert isinstance(data["classroom_capacity"], int) and data["classroom_capacity"] >= 1
    assert isinstance(data["occupied_classrooms"], int)


def assert_applicant(data: dict) -> None:
    _assert_common_fields(data)
    assert data["campus_tier"] in ("PRIORITY", "STANDARD", "DEVELOPING")
    assert isinstance(data["graduation_year"], int) and data["graduation_year"] >= 2000
    assert 0 <= data["leadership_score"] <= 100
    assert 0 <= data["achievement_score"] <= 100
    assert 0.0 <= data["gpa"] <= 4.0


def assert_application(data: dict) -> None:
    _assert_common_fields(data)
    assert data["status"] in (
        "SUBMITTED",
        "UNDER_REVIEW",
        "RETURNED_FOR_REVISION",
        "SELECTED",
        "REJECTED",
        "OFFER_EXTENDED",
        "ACCEPTED",
        "DECLINED",
    )
    assert data["subject_area"] in ("MATH", "SCIENCE", "ENGLISH", "HISTORY", "SPED", "BILINGUAL")
    assert data["grade_preference"] in ("ELEMENTARY", "MIDDLE", "HIGH")
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert isinstance(data["selection_score"], (int, float))
    assert isinstance(data["final_selection_score"], (int, float))


def assert_certification_pathway(data: dict) -> None:
    _assert_common_fields(data)
    assert data["certification_track"] in ("STANDARD", "ALTERNATIVE_EMERGENCY", "PROVISIONAL")
    assert isinstance(data["required_coursework_hours"], int) and data["required_coursework_hours"] >= 1
    assert isinstance(data["required_practice_hours"], int) and data["required_practice_hours"] >= 1
    assert isinstance(data["deadline_days_before_term"], int) and data["deadline_days_before_term"] >= 0
    assert isinstance(data["coursework_fee_cents"], int) and data["coursework_fee_cents"] >= 0


def assert_corps_member(data: dict) -> None:
    _assert_common_fields(data)
    assert data["institute_status"] in ("ENROLLED", "IN_TRAINING", "COMPLETED")
    assert data["service_status"] in ("ACTIVE", "ON_LEAVE", "EXITED")
    for field in (
        "practice_teaching_hours",
        "coursework_hours_completed",
        "certification_hours_verified",
        "institute_stipend_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0, f"{field} must not be negative"
    assert isinstance(data["readiness_score"], (int, float))
    assert 0.0 <= data["readiness_score"] <= READINESS_CEILING


def assert_placement(data: dict) -> None:
    _assert_common_fields(data)
    assert data["status"] in ("MATCHED", "CONFIRMED", "ACTIVE", "EXITED_EARLY", "COMPLETED")
    assert isinstance(data["employment_eligible"], bool)
    assert isinstance(data["placement_fee_cents"], int) and data["placement_fee_cents"] >= 0
    assert is_iso8601_timestamp(data["term_start_date"])
    assert is_iso8601_timestamp(data["term_end_date"])


def assert_certification_milestone(data: dict) -> None:
    _assert_common_fields(data)
    assert data["milestone_type"] in ("COURSEWORK", "PRACTICUM", "EXAM", "ORIENTATION")
    assert data["progress_status"] in ("PENDING", "IN_PROGRESS", "COMPLETED")
    assert data["verification_status"] in ("UNVERIFIED", "VERIFIED", "REJECTED")
    assert data["deadline_status"] in ("OVERDUE", "AT_RISK", "ON_TRACK", "SATISFIED")
    assert isinstance(data["required_hours"], int) and data["required_hours"] >= 0
    assert isinstance(data["days_remaining"], int)


def assert_support_record(data: dict) -> None:
    _assert_common_fields(data)
    assert data["record_type"] in ("COACHING", "EVALUATION")
    assert isinstance(data["coach_user_id"], str) and data["coach_user_id"]
    assert isinstance(data["effectiveness_score"], int) and 1 <= data["effectiveness_score"] <= 5
    assert is_iso8601_timestamp(data["session_start"])
    assert is_iso8601_timestamp(data["session_end"])


# ─── Domain invariants ────────────────────────────────

def assert_district_invoice_matches_counters(district: dict, filled: int) -> None:
    """The stored invoice is filled*fee + max(0, slots-filled)*penalty (PRD §3.6)."""
    unfilled = max(0, district["hiring_commitment_slots"] - filled)
    expected = (
        filled * district["placement_fee_per_member_cents"]
        + unfilled * district["unfilled_slot_penalty_cents"]
    )
    assert district["invoice_amount_cents"] == expected, (
        f"invoice_amount_cents {district['invoice_amount_cents']} != {expected} "
        f"for filled={filled}, slots={district['hiring_commitment_slots']}"
    )


def assert_forward_looking_invoice(district: dict) -> None:
    """The forward-looking projection charges every committed slot, no penalty."""
    expected = district["hiring_commitment_slots"] * district["placement_fee_per_member_cents"]
    assert district["invoice_amount_cents"] == expected, (
        f"forward-looking invoice {district['invoice_amount_cents']} != {expected}"
    )


def assert_verified_hours_sum(member: dict, milestones: list) -> None:
    """certification_hours_verified sums COMPLETED and VERIFIED milestones only."""
    expected = sum(
        m["required_hours"]
        for m in milestones
        if m["progress_status"] == "COMPLETED" and m["verification_status"] == "VERIFIED"
    )
    assert member["certification_hours_verified"] == expected, (
        f"certification_hours_verified {member['certification_hours_verified']} != {expected}"
    )


def assert_coursework_hours_sum(member: dict, milestones: list) -> None:
    """coursework_hours_completed sums COMPLETED COURSEWORK and ORIENTATION rows."""
    expected = sum(
        m["required_hours"]
        for m in milestones
        if m["milestone_type"] in ("COURSEWORK", "ORIENTATION")
        and m["progress_status"] == "COMPLETED"
    )
    assert member["coursework_hours_completed"] == expected, (
        f"coursework_hours_completed {member['coursework_hours_completed']} != {expected}"
    )


def assert_readiness_matches_formula(
    member: dict, milestones: list, pathway: dict, tolerance: float = 0.01
) -> None:
    """Recompute readiness_score from its three ratios and the credit table."""
    certified = sum(
        m["required_hours"]
        for m in milestones
        if m["progress_status"] == "COMPLETED" and m["verification_status"] == "VERIFIED"
    )
    total_required = sum(m["required_hours"] for m in milestones)
    certified_ratio = 1.0 if total_required == 0 else min(1.0, certified / total_required)
    practice_ratio = min(1.0, member["practice_teaching_hours"] / pathway["required_practice_hours"])
    coursework_ratio = min(
        1.0, member["coursework_hours_completed"] / pathway["required_coursework_hours"]
    )
    subtotal = round(100.0 * (0.5 * certified_ratio + 0.3 * practice_ratio + 0.2 * coursework_ratio), 2)
    if subtotal >= 80.00:
        credit = 3.0
    elif subtotal >= 50.00:
        credit = 1.5
    else:
        credit = 0.0
    expected = min(100.0, round(subtotal + credit, 2))
    assert member["readiness_score"] == pytest.approx(expected, abs=tolerance), (
        f"readiness_score {member['readiness_score']} != {expected} "
        f"(subtotal {subtotal}, credit {credit})"
    )


def assert_employment_eligibility(
    placement: dict, member: dict, milestones: list, pathway: dict
) -> None:
    """The five-condition eligibility rule (PRD §3.5)."""
    overdue = [m for m in milestones if m["deadline_status"] == "OVERDUE"]
    required = pathway["required_practice_hours"] + pathway["required_coursework_hours"]
    expected = (
        placement["status"] in ("CONFIRMED", "ACTIVE")
        and member["service_status"] == "ACTIVE"
        and member["institute_status"] == "COMPLETED"
        and len(overdue) == 0
        and member["certification_hours_verified"] >= required
    )
    assert placement["employment_eligible"] is expected, (
        f"employment_eligible {placement['employment_eligible']} != {expected}"
    )
