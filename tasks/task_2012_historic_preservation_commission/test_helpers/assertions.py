"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AppealStatus,
    ApplicationStatus,
    CertificateStatus,
    CommentStance,
    CompliancePosture,
    ContributingStatus,
    DemolitionDelayStatus,
    DistrictStatus,
    GuidelineSetStatus,
    HardshipReviewStatus,
    HearingStatus,
    ListingStatus,
    PreservationPosture,
    ReviewTrack,
    SignificanceTier,
    ViolationStatus,
)


def _enum_values(enum_cls):
    return [e.value for e in enum_cls]


def _assert_common_fields(data: dict):
    """Fields every primary resource carries (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_money(data: dict, field: str, allow_none: bool = False):
    """Money is integer cents; there are no fractional cents (PRD §2.6)."""
    value = data.get(field)
    if value is None and allow_none:
        return
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be integer cents, got {value!r}"
    )


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 instant (accepts a trailing Z)."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_instant_equal(actual, expected_iso: str, label: str = "instant"):
    """Two ISO 8601 strings denote the same instant, regardless of formatting
    (fractional digits, Z vs +00:00)."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected {expected_iso}, got {actual}"
    )


def assert_district(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["significance_tier"] in _enum_values(SignificanceTier)
    assert data["status"] in _enum_values(DistrictStatus)
    assert isinstance(data["contributing_count"], int)
    assert isinstance(data["total_inventory_count"], int)
    assert data["preservation_posture"] in _enum_values(PreservationPosture)


def assert_guideline_set(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["sections"], list)
    assert isinstance(data["version_no"], int)
    assert data["status"] in _enum_values(GuidelineSetStatus)
    if data.get("adopted_at") is not None:
        assert is_iso8601_timestamp(data["adopted_at"])


def assert_owner(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["mailing_address"], str)


def assert_property(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["address"], str) and data["address"]
    assert isinstance(data["parcel_number"], str) and data["parcel_number"]
    assert data["contributing_status"] in _enum_values(ContributingStatus)
    assert data["listing_status"] in _enum_values(ListingStatus)
    assert isinstance(data["construction_year"], int)
    _assert_money(data, "assessed_value_cents")
    assert isinstance(data["open_violation_count"], int)
    assert data["compliance_posture"] in _enum_values(CompliancePosture)


def assert_application(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _enum_values(ApplicationStatus)
    assert isinstance(data["work_items"], list)
    _assert_money(data, "declared_cost_cents")
    _assert_money(data, "provisional_fee_cents")
    _assert_money(data, "verified_cost_cents", allow_none=True)
    _assert_money(data, "assessed_fee_cents", allow_none=True)
    _assert_money(data, "paid_fee_cents")
    _assert_money(data, "refunded_fee_cents")
    _assert_money(data, "fee_balance_cents")
    if data.get("review_track") is not None:
        assert data["review_track"] in _enum_values(ReviewTrack)
    assert isinstance(data["resubmission_count"], int)


def assert_meeting(data: dict):
    _assert_common_fields(data)
    assert is_iso8601_timestamp(data["meeting_date"])
    assert isinstance(data["agenda_capacity"], int)
    assert isinstance(data["scheduled_hearing_count"], int)


def assert_hearing(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _enum_values(HearingStatus)
    assert is_iso8601_timestamp(data["notice_posted_at"])


def assert_public_comment(data: dict):
    """A public comment is immutable testimony: it carries id and created_at
    but never updated_at or version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 timestamp"
    )
    assert "updated_at" not in data, "a public comment carries no updated_at"
    assert "version" not in data, "a public comment carries no version"
    assert data["stance"] in _enum_values(CommentStance)


def assert_appeal(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _enum_values(AppealStatus)
    assert is_iso8601_timestamp(data["filed_at"])


def assert_violation(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _enum_values(ViolationStatus)
    _assert_money(data, "demand_letter_amount_cents", allow_none=True)
    _assert_money(data, "final_penalty_cents", allow_none=True)


def assert_demolition_delay(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _enum_values(DemolitionDelayStatus)
    assert isinstance(data["base_delay_days"], int)
    assert isinstance(data["postponement_count"], int)
    assert is_iso8601_timestamp(data["delay_start_at"])
    assert is_iso8601_timestamp(data["provisional_delay_end"])
    if data.get("final_delay_end") is not None:
        assert is_iso8601_timestamp(data["final_delay_end"])


def assert_hardship_review(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _enum_values(HardshipReviewStatus)
    assert is_iso8601_timestamp(data["filed_at"])
    _assert_money(data, "appraisal_basis_cents")


def assert_certificate(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _enum_values(CertificateStatus)
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["work_commence_deadline"])
    assert isinstance(data["conditions"], list)
    assert isinstance(data["conditions_met_count"], int)


def assert_district_census(data: dict, contributing: int, total: int, posture: str):
    """The census counters always equal a full recount (PRD §2.9)."""
    assert data["contributing_count"] == contributing, (
        f"contributing_count: expected {contributing}, got {data['contributing_count']}"
    )
    assert data["total_inventory_count"] == total, (
        f"total_inventory_count: expected {total}, got {data['total_inventory_count']}"
    )
    assert data["preservation_posture"] == posture, (
        f"preservation_posture: expected {posture}, got {data['preservation_posture']}"
    )
