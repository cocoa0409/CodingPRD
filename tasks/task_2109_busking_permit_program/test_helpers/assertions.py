"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .constants import SEASON_MINUTES_CAP


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp, tolerating a trailing Z, an explicit
    +00:00 offset and an optional fractional-second part."""
    assert isinstance(value, str) and value, "expected an ISO 8601 timestamp"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str, label: str = "timestamp"):
    """Compare two ISO 8601 UTC timestamps as instants, so a difference in how
    many fractional digits are rendered never decides the test."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected the instant {expected}, got {actual}")


def _assert_common_fields(data: dict, label: str):
    """id / created_at / updated_at / version — PRD section 2.4."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{label}.version must be an integer starting at 1"


def _assert_immutable_fields(data: dict, label: str):
    """id + created_at only — PRD section 2.4 immutable resources."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    assert "version" not in data, f"{label} must not carry a version field"
    assert "updated_at" not in data, f"{label} must not carry an updated_at field"


def assert_zone(data: dict):
    _assert_common_fields(data, "Zone")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["code"], str) and 1 <= len(data["code"]) <= 16
    assert 55 <= data["base_noise_cap_db"] <= 100
    assert 0 <= data["weekend_noise_bonus_db"] <= 10
    assert 0 <= data["evening_start_minute"] <= 1439
    assert 0 <= data["evening_penalty_db"] <= 20
    assert 0 <= data["quiet_hours_start_minute"] <= 1439
    assert 0 <= data["quiet_hours_end_minute"] <= 1439
    assert 1 <= data["max_concurrent_closures"] <= 5
    assert data["active_closure_count"] >= 0


def assert_pitch(data: dict):
    _assert_common_fields(data, "Pitch")
    assert is_valid_uuid(data["zone_id"])
    assert isinstance(data["code"], str) and 1 <= len(data["code"]) <= 16
    assert data["tier"] in ("PREMIUM", "STANDARD")
    assert isinstance(data["amplification_allowed"], bool)
    assert 55 <= data["noise_cap_db"] <= 100
    assert 15 <= data["max_session_minutes"] <= 240
    assert 1 <= data["daily_session_cap"] <= 12
    assert 1 <= data["premium_slots_per_draw"] <= 5
    assert data["availability_status"] in ("OPEN", "CLOSED")


def assert_performer(data: dict):
    _assert_common_fields(data, "Performer")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["stage_name"], str) and data["stage_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["act_type"] in (
        "ACOUSTIC_MUSIC", "AMPLIFIED_MUSIC", "STREET_THEATRE",
        "VISUAL_ART", "CIRCUS_SKILL")
    assert 0 <= data["conduct_score"] <= 100
    assert 0 <= data["renewal_conduct_score"] <= 100
    assert data["standing"] in ("GOOD", "WATCH", "BARRED")
    assert data["upheld_complaint_count"] >= 0
    assert data["premium_wins_this_season"] >= 0
    assert_standing_matches_conduct_score(data)


def assert_standing_matches_conduct_score(performer: dict):
    """PRD section 3.8 derives standing from the live conduct score alone."""
    score = performer["conduct_score"]
    expected = "GOOD" if score >= 80 else ("WATCH" if score >= 60 else "BARRED")
    assert performer["standing"] == expected, (
        f"conduct_score {score} must derive standing {expected}, "
        f"got {performer['standing']}")


def assert_application(data: dict):
    _assert_common_fields(data, "PermitApplication")
    assert is_valid_uuid(data["performer_id"])
    assert is_valid_uuid(data["requested_zone_id"])
    assert 2025 <= data["season_year"] <= 2035
    assert data["requested_act_type"] in (
        "ACOUSTIC_MUSIC", "AMPLIFIED_MUSIC", "STREET_THEATRE",
        "VISUAL_ART", "CIRCUS_SKILL")
    assert isinstance(data["amplification_requested"], bool)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "AUDITION_REQUIRED",
        "AUDITION_SCHEDULED", "AUDITION_PASSED", "AUDITION_FAILED",
        "CHANGES_REQUESTED", "APPROVED", "REJECTED")
    assert isinstance(data["requires_audition"], bool)
    assert 0 <= data["revision_count"] <= 2
    assert data["assessed_fee_cents"] >= 0


def assert_audition(data: dict):
    _assert_common_fields(data, "Audition")
    assert is_valid_uuid(data["application_id"])
    assert data["status"] in ("SCHEDULED", "PASSED", "FAILED", "CANCELLED")
    assert data["score_count"] >= 0
    if data["panel_score"] is not None:
        assert 0.0 <= float(data["panel_score"]) <= 10.0


def assert_audition_score(data: dict):
    _assert_immutable_fields(data, "AuditionScore")
    assert is_valid_uuid(data["audition_id"])
    assert isinstance(data["panelist_user_id"], str) and data["panelist_user_id"]
    for field in ("technical_score", "suitability_score", "safety_score"):
        assert 0 <= data[field] <= 10, f"{field} must sit between 0 and 10"
    assert 0.0 <= float(data["composite_score"]) <= 10.0


def assert_permit(data: dict):
    _assert_common_fields(data, "Permit")
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["performer_id"])
    assert isinstance(data["permit_number"], str) and data["permit_number"]
    assert data["lifecycle_status"] in (
        "PENDING_FEE", "ACTIVE", "RENEWAL_PENDING", "EXPIRED", "REVOKED")
    assert data["compliance_status"] in ("CLEAR", "WARNED", "SUSPENDED")
    assert isinstance(data["amplification_endorsed"], bool)
    assert data["season_minutes_used"] >= 0
    assert data["season_minutes_used"] <= SEASON_MINUTES_CAP
    assert data["closure_credit_minutes"] >= 0
    assert data["noise_violation_count"] >= 0


def assert_permit_number_format(permit: dict, season_year: int, sequence: int):
    """PRD section 3.4: `BP-`, the season year, and a zero-padded four-digit
    sequence number."""
    expected = f"BP-{season_year}-{sequence:04d}"
    assert permit["permit_number"] == expected, (
        f"Expected permit_number {expected}, got {permit['permit_number']}")


def assert_fee_invoice(data: dict):
    _assert_common_fields(data, "FeeInvoice")
    assert is_valid_uuid(data["permit_id"])
    assert data["invoice_kind"] in ("INITIAL", "RENEWAL")
    assert data["fee_variant"] in ("FULL_SEASON", "PRORATED")
    assert data["status"] in ("PENDING", "PAID", "PAST_DUE", "REFUNDED", "VOID")
    assert 1 <= data["coverage_start_month"] <= 12
    assert 1 <= data["months_covered"] <= 12
    for field in ("gross_fee_cents", "discount_cents", "admin_fee_cents",
                  "amount_due_cents", "amount_paid_cents", "refunded_cents"):
        assert isinstance(data[field], int), f"{field} must be whole cents"
        assert data[field] >= 0


def assert_lottery_draw(data: dict):
    _assert_common_fields(data, "LotteryDraw")
    assert is_valid_uuid(data["pitch_id"])
    assert 2026 <= data["season_year"] <= 2035
    assert data["status"] in ("OPEN", "DRAWN", "VOID")
    assert 1 <= data["winner_slots"] <= 5
    assert data["entry_count"] >= 0
    assert data["winner_count"] >= 0


def assert_lottery_entry(data: dict):
    _assert_common_fields(data, "LotteryEntry")
    assert is_valid_uuid(data["draw_id"])
    assert is_valid_uuid(data["permit_id"])
    assert data["status"] in ("SUBMITTED", "WON", "LOST", "FORFEITED")
    if data["priority_band"] is not None:
        assert 1 <= data["priority_band"] <= 3
    if data["rank_position"] is not None:
        assert data["rank_position"] >= 1


def assert_session_booking(data: dict):
    _assert_common_fields(data, "SessionBooking")
    assert is_valid_uuid(data["permit_id"])
    assert is_valid_uuid(data["pitch_id"])
    assert data["duration_minutes"] > 0
    assert isinstance(data["amplification_planned"], bool)
    assert data["origin"] in ("DIRECT", "LOTTERY")
    assert data["effective_noise_cap_db"] >= 55
    assert data["noise_violation_count"] >= 0
    assert data["status"] in (
        "RESERVED", "RELOCATED", "COMPLETED", "CANCELLED_BY_PERFORMER",
        "CANCELLED_BY_CLOSURE", "CANCELLED_BY_SUSPENSION",
        "CANCELLED_BY_REVOCATION", "CANCELLED_BY_EXPIRY")


def assert_noise_reading(data: dict):
    _assert_immutable_fields(data, "NoiseReading")
    assert is_valid_uuid(data["booking_id"])
    assert isinstance(data["inspector_user_id"], str) and data["inspector_user_id"]
    assert 0 <= data["reading_db"] <= 140
    assert data["effective_cap_db"] >= 55
    assert data["verdict"] in ("COMPLIANT", "VIOLATION")
    expected = "COMPLIANT" if data["reading_db"] <= data["effective_cap_db"] else "VIOLATION"
    assert data["verdict"] == expected, (
        f"reading_db {data['reading_db']} against cap {data['effective_cap_db']} "
        f"must be {expected}")


def assert_complaint(data: dict):
    _assert_common_fields(data, "Complaint")
    assert is_valid_uuid(data["permit_id"])
    assert data["category"] in (
        "NOISE", "OBSTRUCTION", "CONDUCT", "UNPERMITTED_AMPLIFICATION")
    assert isinstance(data["description"], str)
    assert data["status"] in ("OPEN", "TRIAGED", "MEDIATION", "UPHELD", "DISMISSED")
    if data["severity"] is not None:
        assert data["severity"] in ("MINOR", "MODERATE", "MAJOR")
    if data["route"] is not None:
        assert data["route"] in ("DIRECT", "MEDIATION")
    assert data["conduct_deduction"] >= 0


def assert_closure_order(data: dict):
    _assert_common_fields(data, "ClosureOrder")
    assert is_valid_uuid(data["zone_id"])
    assert data["reason"] in ("SPECIAL_EVENT", "CONSTRUCTION", "EMERGENCY", "PARADE")
    assert data["status"] in ("DRAFT", "ACTIVE", "LIFTED")
    assert data["affected_booking_count"] >= 0
    assert data["relocated_booking_count"] >= 0
    assert data["cancelled_booking_count"] >= 0
    assert data["affected_booking_count"] == (
        data["relocated_booking_count"] + data["cancelled_booking_count"]), (
        "affected_booking_count is the total of the relocated and cancelled counts")


def assert_epoch_report(data: dict):
    assert is_iso8601_timestamp(data.get("processed_at", ""))
    for counter in ("closures_lifted_count", "invoices_past_due_count",
                    "permits_expired_count", "bookings_completed_count",
                    "performers_rescored_count"):
        assert isinstance(data.get(counter), int) and data[counter] >= 0, \
            f"epoch report must carry a non-negative {counter}"


# ---------------------------------------------------------------------------
# Ledger invariants (PRD section 2.9)
# ---------------------------------------------------------------------------
MINUTE_LEDGER_STATUSES = ("RESERVED", "RELOCATED", "COMPLETED")


def assert_minute_ledger_invariant(permit: dict, bookings: list):
    """season_minutes_used equals the sum of duration_minutes over the permit's
    RESERVED, RELOCATED and COMPLETED sessions."""
    expected = sum(b["duration_minutes"] for b in bookings
                   if b["status"] in MINUTE_LEDGER_STATUSES)
    assert permit["season_minutes_used"] == expected, (
        f"season_minutes_used {permit['season_minutes_used']} must equal the "
        f"recomputed {expected}")


def assert_money_ledger_invariant(permit: dict, invoices: list):
    """net_fees_paid_cents equals the sum of amount_paid_cents minus the sum of
    refunded_cents over every invoice of the permit."""
    expected = (sum(i["amount_paid_cents"] for i in invoices)
                - sum(i["refunded_cents"] for i in invoices))
    assert permit["net_fees_paid_cents"] == expected, (
        f"net_fees_paid_cents {permit['net_fees_paid_cents']} must equal the "
        f"recomputed {expected}")
