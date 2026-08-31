"""Entity assertions and domain invariant checkers."""
import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_UUID_LEN = 36


def assert_common_fields(data: dict, entity: str) -> None:
    """The four common properties every resource in this service carries."""
    resource_id = data.get("id", "")
    assert is_valid_uuid(resource_id), f"{entity}.id must be a UUID, got {resource_id!r}"
    assert len(resource_id) == _UUID_LEN, (
        f"{entity}.id must be a bare UUID with no type prefix, got {resource_id!r}")
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1")


def assert_instant_equals(actual, expected, field: str) -> None:
    """Compare an ISO 8601 UTC instant carried to three fractional digits."""
    assert actual == expected, f"Expected {field} == {expected}, got {actual}"


def assert_money_2dp(value, field: str) -> None:
    assert value == pytest.approx(round(float(value) + 0.0, 2), abs=1e-9), (
        f"{field} must be carried to 2 decimal places, got {value}")


# ─── Per-entity assertions ────────────────────────────────────────────────

def assert_business_unit(data: dict) -> None:
    assert_common_fields(data, "BusinessUnit")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["market_code"], str) and data["market_code"]
    assert 0 <= data["market_share_bps"] <= 10000
    assert data["interaction_point_count"] >= 0
    assert 0 <= data["competitor_overlap_pct"] <= 100
    assert data["exposure_budget_points"] > 0
    assert data["review_minutes_budget"] > 0
    assert data["exposure_points"] >= 0, "the exposure ledger is floored at 0.00"
    assert data["review_minutes_consumed"] >= 0
    assert data["document_violation_count"] >= 0
    assert data["risk_band"] in ("LOW", "MODERATE", "HIGH", "SEVERE")
    assert data["posture"] in ("OPEN", "RESTRICTED", "FROZEN")


def assert_employee(data: dict) -> None:
    assert_common_fields(data, "EmployeeProfile")
    assert is_valid_uuid(data["business_unit_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["role_category"] in ("SALES", "PRICING", "LEGAL", "OTHER")
    assert data["clearance_status"] in ("NONE", "GRANTED", "SUSPENDED", "REVOKED")
    assert data["training_status"] in ("NONE", "CURRENT", "EXPIRED")


def assert_curriculum(data: dict) -> None:
    assert_common_fields(data, "TrainingCurriculum")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["target_role_categories"], list)
    assert data["target_role_categories"], "target_role_categories is non-empty"
    assert data["duration_minutes"] > 0
    assert data["validity_days"] > 0
    assert isinstance(data["is_mandatory"], bool)


def assert_training_assignment(data: dict) -> None:
    assert_common_fields(data, "TrainingAssignment")
    assert is_valid_uuid(data["employee_id"])
    assert is_valid_uuid(data["curriculum_id"])
    assert data["status"] in (
        "ASSIGNED", "IN_PROGRESS", "COMPLETED", "EXPIRED", "WAIVED")


def assert_association(data: dict) -> None:
    assert_common_fields(data, "TradeAssociation")
    assert isinstance(data["name"], str) and data["name"]
    assert data["approval_tier"] in ("TIER_1_LOW", "TIER_2_MEDIUM", "TIER_3_HIGH")
    assert 0 <= data["competitor_density_pct"] <= 100
    assert data["status"] in ("PROPOSED", "APPROVED", "PROHIBITED")


def assert_participation(data: dict) -> None:
    assert_common_fields(data, "AssociationParticipation")
    assert is_valid_uuid(data["business_unit_id"])
    assert is_valid_uuid(data["association_id"])
    assert is_valid_uuid(data["employee_id"])
    assert data["status"] in (
        "DRAFT", "APPROVAL_PENDING", "PARTIALLY_APPROVED", "ACTIVE",
        "SUSPENDED", "UNDER_REVIEW", "REJECTED", "TERMINATED")
    assert isinstance(data["legal_cleared"], bool)
    assert isinstance(data["business_justified"], bool)
    assert data["review_load_minutes"] >= 0
    assert data["review_minutes_reserved"] >= 0


def assert_meeting(data: dict) -> None:
    assert_common_fields(data, "AssociationMeeting")
    assert is_valid_uuid(data["association_id"])
    assert data["meeting_type"] in ("BOARD", "COMMITTEE", "STANDARDS", "SOCIAL")
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["scheduled_end"] > data["scheduled_start"]
    assert isinstance(data["agenda_received"], bool)


def assert_attendance(data: dict) -> None:
    assert_common_fields(data, "MeetingAttendance")
    assert is_valid_uuid(data["meeting_id"])
    assert is_valid_uuid(data["participation_id"])
    assert data["status"] in (
        "PLANNED", "ATTENDED", "MINUTES_SUBMITTED", "MINUTES_REVIEWED",
        "FLAGGED", "CANCELLED")
    assert is_iso8601_timestamp(data["occupied_start"])
    assert is_iso8601_timestamp(data["occupied_end"])
    assert data["exposure_points_assessed"] >= 0


def assert_contact(data: dict) -> None:
    assert_common_fields(data, "CompetitorContact")
    assert is_valid_uuid(data["business_unit_id"])
    assert is_valid_uuid(data["employee_id"])
    assert isinstance(data["competitor_name"], str) and data["competitor_name"]
    assert data["contact_channel"] in (
        "IN_PERSON_UNSTRUCTURED", "TRADE_SHOW", "PHONE", "EMAIL", "WRITTEN_FORMAL")
    assert isinstance(data["topic_tags"], list)
    assert isinstance(data["pricing_topic"], bool)
    assert data["status"] in (
        "LOGGED", "UNDER_REVIEW", "REMEDIATION_REQUIRED", "CLEARED", "ESCALATED")
    assert data["exposure_points_charged"] >= 0
    assert data["band_multiplier_applied"] in (1.0, 1.25, 1.5, 2.0)


def assert_transaction(data: dict) -> None:
    assert_common_fields(data, "Transaction")
    assert is_valid_uuid(data["business_unit_id"])
    assert isinstance(data["target_name"], str) and data["target_name"]
    for cents_field in ("deal_value_cents", "assumed_liabilities_cents",
                        "market_valuation_cents", "acquirer_total_assets_cents",
                        "target_total_assets_cents"):
        assert isinstance(data[cents_field], int), (
            f"{cents_field} is carried in integer cents")
    assert data["exemption_code"] in (
        "NONE", "ORDINARY_COURSE", "FOREIGN_ASSETS", "INVESTMENT_ONLY")
    assert data["status"] in ("DRAFT", "ANALYZED", "EXEMPT", "FILED", "CLEARED")


def assert_hsr_analysis(data: dict) -> None:
    assert_common_fields(data, "HsrAnalysis")
    assert is_valid_uuid(data["transaction_id"])
    assert data["valuation_variant"] in ("SIGNED_DEAL", "MARKET_VALUE")
    assert isinstance(data["size_of_transaction_cents"], int), (
        "size_of_transaction_cents is stored as integer cents with no rounding")
    assert isinstance(data["filing_required"], bool)
    assert data["determination"] in (
        "EXEMPT", "BELOW_THRESHOLD", "SIZE_OF_PERSON_NOT_MET", "FILING_REQUIRED")
    assert data["status"] in ("ACTIVE", "SUPERSEDED")


def assert_site(data: dict) -> None:
    assert_common_fields(data, "Site")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    assert data["concurrent_drill_capacity"] >= 1
    assert data["readiness_score"] >= 0


def assert_drill(data: dict) -> None:
    assert_common_fields(data, "ReadinessDrill")
    assert is_valid_uuid(data["site_id"])
    assert data["drill_type"] in ("DAWN_RAID", "DOCUMENT_HOLD", "INTERVIEW")
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["window_end"] > data["window_start"]
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "ABORTED")


def assert_document_audit(data: dict) -> None:
    assert_common_fields(data, "DocumentAudit")
    assert is_valid_uuid(data["business_unit_id"])
    assert data["sample_size"] > 0
    assert isinstance(data["scope_note"], str) and data["scope_note"]
    assert data["status"] in ("OPEN", "COMPLETED")


def assert_leniency_application(data: dict) -> None:
    assert_common_fields(data, "LeniencyApplication")
    assert is_valid_uuid(data["business_unit_id"])
    assert isinstance(data["cartel_code"], str) and data["cartel_code"]
    assert isinstance(data["affected_years"], list) and data["affected_years"]
    for entry in data["affected_years"]:
        assert "year" in entry and "affected_commerce_cents" in entry
    assert data["marker_status"] in (
        "NONE", "MARKER_REQUESTED", "MARKER_GRANTED", "MARKER_DENIED",
        "MARKER_EXPIRED", "PERFECTED")
    assert data["disclosure_status"] in (
        "DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED", "WITHDRAWN")


def assert_risk_assessment(data: dict) -> None:
    assert_common_fields(data, "RiskAssessment")
    assert is_valid_uuid(data["business_unit_id"])
    assert data["variant"] in ("BASELINE", "INCIDENT_ADJUSTED")
    assert 0.00 <= data["market_risk_index"] <= 100.00
    assert data["risk_band"] in ("LOW", "MODERATE", "HIGH", "SEVERE")
    assert data["status"] in ("ACTIVE", "SUPERSEDED")
    assert data["incident_load"] >= 0
    assert data["escalated_contact_count"] >= 0
    assert data["flagged_attendance_count"] >= 0
    assert data["document_violation_count"] >= 0


# ─── Domain invariants ────────────────────────────────────────────────────

def assert_exposure_ledger_identity(unit: dict, contacts, attendances) -> None:
    """The ledger is the sum of the three declared terms, floored at 0.00.

    `contacts` and `attendances` are the unit's full contact and attendance
    rows; only the statuses the ledger declares contribute.
    """
    charged = sum(
        c["exposure_points_charged"] for c in contacts
        if c["status"] in ("LOGGED", "UNDER_REVIEW", "REMEDIATION_REQUIRED",
                           "ESCALATED"))
    assessed = sum(
        a["exposure_points_assessed"] for a in attendances
        if a["status"] in ("MINUTES_REVIEWED", "FLAGGED"))
    expected = max(0.00, round(
        charged + assessed + unit["manual_exposure_adjustment_points"], 2))
    assert unit["exposure_points"] == pytest.approx(expected, abs=0.005), (
        f"exposure_points {unit['exposure_points']} should equal the ledger "
        f"identity {expected}")


def assert_review_minutes_identity(unit: dict, participations) -> None:
    """Consumed minutes are the sum of reservations held by live participations."""
    expected = sum(
        p["review_minutes_reserved"] for p in participations
        if p["status"] in ("PARTIALLY_APPROVED", "ACTIVE", "SUSPENDED",
                           "UNDER_REVIEW"))
    assert unit["review_minutes_consumed"] == expected, (
        f"review_minutes_consumed {unit['review_minutes_consumed']} should equal "
        f"the sum of live reservations {expected}")
    assert unit["review_minutes_consumed"] <= unit["review_minutes_budget"]


def assert_posture_for(unit: dict, expected: str) -> None:
    assert unit["posture"] == expected, (
        f"Expected posture {expected}, got {unit['posture']} at exposure_points "
        f"{unit['exposure_points']} and risk_band {unit['risk_band']}")
