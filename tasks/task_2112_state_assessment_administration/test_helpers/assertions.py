"""Entity assertions and domain invariant checkers."""
import math

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict, entity_name: str = "resource") -> None:
    """id / created_at / updated_at / version, per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a bare UUID, got {data.get('id')!r}")
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('created_at')!r}")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('updated_at')!r}")
    assert isinstance(data.get("version"), int), (
        f"{entity_name}.version must be an integer, got {data.get('version')!r}")


def assert_district(data: dict) -> None:
    assert_common_fields(data, "District")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["district_code"], str)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    for field in ("replacement_charge_total_cents", "security_assessment_cents",
                  "open_discrepancy_count"):
        assert isinstance(data[field], int), f"District.{field} must be an integer"
        assert data[field] >= 0, f"District.{field} must never be negative"


def assert_school(data: dict) -> None:
    assert_common_fields(data, "School")
    assert is_valid_uuid(data["district_id"])
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["school_code"], str)
    assert 1 <= data["max_concurrent_seats"] <= 500


def assert_test_window(data: dict) -> None:
    assert_common_fields(data, "TestWindow")
    assert data["subject"] in ("ELA", "MATH", "SCIENCE", "SOCIAL_STUDIES")
    assert data["grade_band"] in ("G3_5", "G6_8", "G9_12")
    assert data["status"] in ("PLANNED", "OPEN", "MAKEUP", "SCORING", "RELEASED",
                              "FINALIZED", "CANCELLED")
    assert 1 <= data["appeal_window_days"] <= 45
    assert 0.0 <= data["min_participation_pct"] <= 100.0
    assert isinstance(data["security_hold"], bool)
    assert isinstance(data["open_breach_count"], int) and data["open_breach_count"] >= 0
    assert data["security_hold"] == (data["open_breach_count"] > 0), (
        "security_hold must be true exactly when open_breach_count is greater than zero")
    for field in ("window_start", "window_end", "makeup_start", "makeup_end"):
        assert is_iso8601_timestamp(data[field]), f"TestWindow.{field} must be ISO 8601"


def assert_proctor(data: dict) -> None:
    assert_common_fields(data, "Proctor")
    assert is_valid_uuid(data["school_id"])
    assert data["training_status"] in ("NOT_TRAINED", "FAILED", "PASSED")
    assert data["certification_status"] in ("NOT_CERTIFIED", "CERTIFIED",
                                            "EXPIRED", "REVOKED")
    assert isinstance(data["strike_count"], int) and data["strike_count"] >= 0
    assert "@" in data["email"]


def assert_security_affidavit(data: dict) -> None:
    assert_common_fields(data, "SecurityAffidavit")
    assert is_valid_uuid(data["proctor_id"])
    assert is_valid_uuid(data["window_id"])
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "REVOKED")
    assert is_iso8601_timestamp(data["signed_at"])
    assert isinstance(data["signer_user_id"], str) and data["signer_user_id"]


def assert_session(data: dict) -> None:
    assert_common_fields(data, "Session")
    assert is_valid_uuid(data["window_id"])
    assert is_valid_uuid(data["school_id"])
    assert data["status"] in ("DRAFT", "SCHEDULED", "ACTIVE", "CLOSED",
                              "CANCELLED", "INVALIDATED")
    assert data["session_type"] in ("INITIAL", "MAKEUP")
    assert 1 <= data["seat_capacity"] <= 400
    for field in ("seats_consumed", "effective_seat_capacity",
                  "separate_setting_count", "materials_checked_out",
                  "materials_checked_in"):
        assert isinstance(data[field], int), f"Session.{field} must be an integer"
        assert data[field] >= 0, f"Session.{field} must never be negative"


def assert_registration(data: dict) -> None:
    assert_common_fields(data, "Registration")
    assert is_valid_uuid(data["session_id"])
    assert data["attendance_status"] in ("PENDING", "PRESENT", "ABSENT",
                                         "EXCUSED", "WITHDRAWN")
    assert data["accommodation_status"] in ("NONE", "REQUESTED", "APPROVED",
                                            "REJECTED")
    assert data["score_status"] in ("NOT_SCORED", "SCORED", "RELEASED",
                                    "UNDER_APPEAL", "CORRECTED", "INVALIDATED",
                                    "FINAL")
    assert data["report_delivery_status"] in ("NOT_QUEUED", "DELIVERED", "SUPPRESSED")
    assert isinstance(data["accommodation_codes"], list)
    assert len(data["accommodation_codes"]) <= 5
    assert len(set(data["accommodation_codes"])) == len(data["accommodation_codes"])
    assert 3 <= data["grade"] <= 12
    assert isinstance(data["seats_required"], int) and data["seats_required"] >= 1


def assert_material_lot(data: dict) -> None:
    assert_common_fields(data, "MaterialLot")
    assert is_valid_uuid(data["window_id"])
    assert is_valid_uuid(data["district_id"])
    assert data["status"] in ("SHIPPED", "RECEIVED", "IN_DISTRIBUTION",
                              "RETURNED_PENDING", "RECONCILED", "DISCREPANT")
    assert 1 <= data["quantity_shipped"] <= 5000
    assert data["seal_range_end"] - data["seal_range_start"] + 1 == \
        data["quantity_shipped"], "seal range must tally with quantity_shipped"
    assert isinstance(data["charge_reversed"], bool)
    assert_lot_conservation(data)


def assert_lot_conservation(lot: dict) -> None:
    """The four custody buckets always sum to quantity_shipped (PRD §3.5).

    Before the lot's first custody entry every bucket is still 0, which is the
    one state in which the sum is legitimately below quantity_shipped.
    """
    buckets = (lot["quantity_at_district"] + lot["quantity_at_school"] +
               lot["quantity_in_sessions"] + lot["quantity_destroyed"])
    for field in ("quantity_at_district", "quantity_at_school",
                  "quantity_in_sessions", "quantity_destroyed"):
        assert lot[field] >= 0, f"MaterialLot.{field} must never be negative"
    if buckets != 0:
        assert buckets == lot["quantity_shipped"], (
            f"booklet conservation broken: buckets sum to {buckets} but the lot "
            f"shipped {lot['quantity_shipped']}")
    assert lot["chain_accounted_count"] == (
        lot["quantity_at_district"] + lot["quantity_destroyed"]), (
        "chain_accounted_count must be the district bucket plus the destroyed bucket")


def assert_custody_event(data: dict) -> None:
    """Custody entries carry only id and created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "CustodyEvent.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "CustodyEvent.created_at must be an ISO 8601 UTC timestamp")
    assert "updated_at" not in data, (
        "CustodyEvent must not expose an updated_at property")
    assert "version" not in data, "CustodyEvent must not expose a version property"
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert data["event_type"] in ("RECEIPT", "TRANSFER_TO_SCHOOL", "SESSION_CHECKOUT",
                                  "SESSION_CHECKIN", "RETURN_TO_DISTRICT",
                                  "DESTRUCTION")
    assert data["from_holder_type"] in ("STATE", "DISTRICT", "SCHOOL", "SESSION")
    assert data["to_holder_type"] in ("DISTRICT", "SCHOOL", "SESSION", "DESTROYED")
    assert data["quantity"] >= 1
    assert 0 <= data["sealed_count"] <= data["quantity"]
    assert is_iso8601_timestamp(data["occurred_at"])


def assert_irregularity_report(data: dict) -> None:
    assert_common_fields(data, "IrregularityReport")
    assert data["status"] in ("DRAFT", "SUBMITTED", "UNDER_REVIEW",
                              "RETURNED_FOR_INFO", "ADJUDICATED", "WITHDRAWN")
    assert data["category"] in ("ADMIN_ERROR", "SECURITY_BREACH", "TECH_FAILURE",
                                "STUDENT_MISCONDUCT")
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH")
    assert isinstance(data["system_generated"], bool)
    assert isinstance(data["return_count"], int) and 0 <= data["return_count"] <= 2
    assert 1 <= len(data["narrative"]) <= 2000


def assert_score_appeal(data: dict) -> None:
    assert_common_fields(data, "ScoreAppeal")
    assert is_valid_uuid(data["registration_id"])
    assert data["status"] in ("FILED", "UPHELD", "DENIED")
    assert data["reason_code"] in ("SCORING_ERROR", "ROSTER_ERROR",
                                   "ACCOMMODATION_NOT_PROVIDED",
                                   "IRREGULARITY_IMPACT")
    assert data["filed_by_role"] in ("SchoolTestCoordinator", "DistrictTestCoordinator")
    assert is_iso8601_timestamp(data["filed_at"])


# ─── Domain arithmetic helpers ────────────────────────────────────────────

def expected_effective_seat_capacity(seat_capacity, school_max_seats,
                                     separate_setting_count) -> int:
    """The supply side of the seat-pressure rule described in PRD §3.4."""
    penalty = max(0, math.ceil((separate_setting_count - 2) / 3)) * 4
    return max(0, min(seat_capacity, school_max_seats) - penalty)


def assert_participation_precision(value) -> None:
    """Participation percentages are reported to exactly one decimal place."""
    assert isinstance(value, (int, float)), (
        f"participation rate must be numeric, got {value!r}")
    assert round(float(value), 1) == float(value), (
        f"participation rate {value} carries more than one decimal place")
