"""Entity assertions, envelope checks and domain invariant checkers."""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .api_client import canonical_instant


# ---------------------------------------------------------------------------
# Envelope / common-field helpers
# ---------------------------------------------------------------------------
def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """PRD §2.2: api_request_id "starts with `req_`" and api_request_timestamp
    is "a server-generated ISO 8601 UTC timestamp with three fractional
    digits"."""
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str), "meta.api_request_id must be a string"
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}")
    assert_three_fractional_digits(meta["api_request_timestamp"])


def assert_three_fractional_digits(value: str) -> None:
    """PRD §2.4: timestamps are "rendered with exactly three
    fractional-second digits"."""
    assert isinstance(value, str), f"expected an ISO timestamp string, got {value!r}"
    assert is_iso8601_timestamp(value), f"not an ISO 8601 timestamp: {value!r}"
    assert value.endswith("Z"), f"timestamp must be UTC and end with Z: {value!r}"
    assert "." in value, f"timestamp must carry fractional seconds: {value!r}"
    fraction = value.split(".")[1].rstrip("Z")
    assert len(fraction) == 3, (
        f"timestamp must carry exactly three fractional digits: {value!r}")


def assert_instant_equals(actual: Any, expected: Any, label: str = "instant") -> None:
    """Compare two ISO-8601 UTC instants independent of fractional width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}")


def assert_common_fields(data: Dict[str, Any], expected_version: Optional[int] = None):
    """PRD §2.4: every resource carries id, created_at, updated_at and version;
    "all thirteen resource types carry the full set"."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID: {data.get('id')!r}"
    assert_three_fractional_digits(data["created_at"])
    assert_three_fractional_digits(data["updated_at"])
    assert isinstance(data["version"], int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1 for a freshly created row"
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"expected version {expected_version}, got {data['version']}")


def assert_list_meta(meta: Dict[str, Any], limit: int, offset: int,
                     total_count: int, has_more: bool) -> None:
    """PRD §2.3: limit and offset "echo the effective values used for the
    page", total_count counts matches "across the whole collection" and
    has_more "is true exactly when rows remain beyond the current page"."""
    assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"expected total_count {total_count}, got {meta['total_count']}")
    assert meta["has_more"] is has_more, (
        f"expected has_more {has_more}, got {meta['has_more']}")


def assert_ratio_precision(value: Any, label: str = "ratio") -> None:
    """PRD §2.10: "Ratios are carried to four decimal places"."""
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    assert round(float(value), 4) == float(value), (
        f"{label} must be rounded to four decimals, got {value!r}")


def assert_whole_cents(value: Any, label: str = "amount") -> None:
    """PRD §2.10: "Monetary quantities are carried in whole cents as
    integers"."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}")


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_program(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 3 <= len(data["name"]) <= 120
    assert isinstance(data["region_code"], str) and len(data["region_code"]) == 2
    assert data["region_code"].isupper()
    assert data["compliance_posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    for counter in ("certified_coach_count", "credential_denominator_count",
                    "expired_credential_count", "unresolved_urgent_referral_count",
                    "active_athlete_count", "program_practice_minutes",
                    "sweep_epoch"):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"{counter} must be a non-negative integer, got {data[counter]!r}")
    for ledger in ("recognized_support_cents", "pledged_support_cents",
                   "family_engagement_credit_cents"):
        assert_whole_cents(data[ledger], ledger)
    assert_ratio_precision(data["expired_credential_ratio"],
                           "expired_credential_ratio")
    assert data["last_sweep_at"] is None or isinstance(data["last_sweep_at"], str)


def assert_athlete(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["legal_name"], str) and 2 <= len(data["legal_name"]) <= 120
    assert data["sport"] in ("ATHLETICS", "BOCCE", "BASKETBALL", "SWIMMING")
    assert isinstance(data["down_syndrome_flag"], bool)
    assert data["registration_status"] in (
        "PENDING_MEDICAL", "ACTIVE", "LAPSED", "WITHDRAWN")
    assert data["medical_status"] in (
        "NONE", "PENDING_REVIEW", "CLEARED", "RESTRICTED", "HOLD")
    assert isinstance(data["cumulative_practice_minutes"], int)
    assert isinstance(data["counted_session_count"], int)


def assert_medical_form(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["athlete_id"])
    assert data["status"] in (
        "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED", "EXPIRED")
    assert isinstance(data["attestation_cardiac_clearance"], bool)
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert isinstance(data["expires_on"], str)


def assert_volunteer(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert "@" in data["email"], "email must contain an @ character"
    assert data["volunteer_class"] in (
        "COACH", "UNIFIED_PARTNER", "GENERAL_VOLUNTEER")
    assert isinstance(data["is_minor"], bool)
    assert data["status"] in ("PROSPECT", "CREDENTIALED", "INACTIVE")


def assert_credential(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["volunteer_id"])
    assert data["role_class"] in ("COACH", "UNIFIED_PARTNER", "GENERAL_VOLUNTEER")
    assert data["status"] in (
        "INITIATED", "SCREENING_CLEARED", "TRAINING_COMPLETE", "READY_TO_CERTIFY",
        "CERTIFIED", "DENIED", "EXPIRED", "RENEWAL_IN_PROGRESS")
    if data["screening_result"] is not None:
        assert data["screening_result"] in ("CLEAR", "FLAGGED", "DISQUALIFYING")


def assert_season(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert data["sport"] in ("ATHLETICS", "BOCCE", "BASKETBALL", "SWIMMING")
    assert data["games_level"] in ("LOCAL", "STATE", "NATIONAL")
    assert data["status"] in (
        "PLANNING", "PRACTICE_OPEN", "DIVISIONED", "ENTRIES_LOCKED", "COMPLETED")
    assert data["registration_deadline"] < data["divisioning_date"] < \
        data["competition_date"], "milestone dates must be strictly increasing"
    for counter in ("divisioning_run_count", "entry_count", "divisioned_entry_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0


def assert_practice_session(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["season_id"])
    assert is_valid_uuid(data["coach_credential_id"])
    assert_three_fractional_digits(data["scheduled_start"])
    assert_three_fractional_digits(data["scheduled_end"])
    assert 30 <= data["duration_minutes"] <= 240
    assert 1 <= data["capacity_slots"] <= 60
    assert isinstance(data["counts_toward_minimum"], bool)
    assert data["status"] in ("SCHEDULED", "HELD", "VOIDED")
    assert isinstance(data["recorded_attendance_count"], int)


def assert_attendance_record(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["session_id"])
    assert is_valid_uuid(data["season_id"])
    assert is_valid_uuid(data["athlete_id"])
    assert data["status"] in ("COUNTED", "NOT_COUNTED", "VOIDED")
    assert isinstance(data["required_minutes"], int)
    assert isinstance(data["counted_minutes"], int)


def assert_unified_team(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["season_id"])
    assert data["roster_status"] in ("FORMING", "COMPLIANT", "NON_COMPLIANT")
    assert isinstance(data["athlete_ids"], list)
    assert isinstance(data["partner_volunteer_ids"], list)
    assert data["athlete_count"] == len(data["athlete_ids"])
    assert data["partner_count"] == len(data["partner_volunteer_ids"])
    assert isinstance(data["age_span_years"], int)


def assert_competition_entry(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["season_id"])
    assert data["participant_type"] in ("ATHLETE", "UNIFIED_TEAM")
    assert data["status"] in (
        "SUBMITTED", "DIVISIONED", "LOCKED", "RESULTED", "ADVANCED",
        "DISQUALIFIED", "VOIDED")
    assert data["age_group"] in (
        "U12", "AGE_12_15", "AGE_16_21", "AGE_22_29", "AGE_30_PLUS")
    assert data["advancement_status"] in (
        "NOT_ADVANCED", "ADVANCED_STATE", "ADVANCED_NATIONAL", "INELIGIBLE_MAXING")
    assert data["skill_score"] > 0, "skill_score must be strictly greater than zero"
    if data["performance_ratio"] is not None:
        assert_ratio_precision(data["performance_ratio"], "performance_ratio")


def assert_division(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["season_id"])
    assert data["status"] in ("DRAFT", "VALID", "UNDERSIZED", "VOIDED")
    assert data["age_group"] in (
        "U12", "AGE_12_15", "AGE_16_21", "AGE_22_29", "AGE_30_PLUS")
    assert isinstance(data["entry_count"], int)
    if data["ability_spread_ratio"] is not None:
        assert_ratio_precision(data["ability_spread_ratio"], "ability_spread_ratio")


def assert_health_screening(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["athlete_id"])
    assert data["discipline"] in (
        "FUNFITNESS", "OPENING_EYES", "HEALTHY_HEARING", "SPECIAL_SMILES",
        "STRONG_MINDS")
    assert data["finding_severity"] in ("ROUTINE", "ADVISORY", "URGENT")
    assert data["referral_status"] in (
        "NOT_REQUIRED", "REFERRED", "FOLLOW_UP_LOGGED", "ESCALATED", "RESOLVED")
    assert isinstance(data["followup_count"], int)


def assert_contribution(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert data["contribution_type"] in (
        "CASH_PLEDGE", "CASH_RECEIPT", "IN_KIND_GOODS", "IN_KIND_SERVICES",
        "VOLUNTEER_HOURS")
    assert data["designation"] in (
        "GENERAL", "COMPETITION", "HEALTH_SCREENING", "FAMILY_ENGAGEMENT")
    assert data["status"] in ("PLEDGED", "RECEIVED", "VOID")
    assert_whole_cents(data["recognized_value_cents"], "recognized_value_cents")
    assert_whole_cents(data["match_credit_cents"], "match_credit_cents")


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_posture_derivation(program: Dict[str, Any]) -> None:
    """PRD §2.7: the ratio is "the expired credential count divided by the
    credential denominator count, rounded half up to four decimal places — and
    exactly 0.0000 when the denominator is zero"; FROZEN when the certified
    coach count is zero or the ratio is at least 0.50, RESTRICTED when the
    ratio is at least 0.20 or an unresolved urgent referral exists, otherwise
    OPEN."""
    denominator = program["credential_denominator_count"]
    expired = program["expired_credential_count"]
    if denominator == 0:
        expected_ratio = 0.0
    else:
        expected_ratio = round(expired / denominator + 1e-12, 4)
    assert abs(program["expired_credential_ratio"] - expected_ratio) < 1e-9, (
        f"expired_credential_ratio should be {expected_ratio}, "
        f"got {program['expired_credential_ratio']}")
    ratio = program["expired_credential_ratio"]
    if program["certified_coach_count"] == 0 or ratio >= 0.50:
        expected = "FROZEN"
    elif ratio >= 0.20 or program["unresolved_urgent_referral_count"] >= 1:
        expected = "RESTRICTED"
    else:
        expected = "OPEN"
    assert program["compliance_posture"] == expected, (
        f"posture should be {expected}, got {program['compliance_posture']}")


def assert_practice_minute_ledger(program: Dict[str, Any],
                                  athletes: List[Dict[str, Any]]) -> None:
    """PRD §2.10: program_practice_minutes "must at all times equal ... the sum
    of `cumulative_practice_minutes` across the program's athletes"."""
    total = sum(a["cumulative_practice_minutes"] for a in athletes)
    assert program["program_practice_minutes"] == total, (
        f"program_practice_minutes {program['program_practice_minutes']} must "
        f"equal the sum of athlete cumulative_practice_minutes {total}")


def assert_support_ledgers(program: Dict[str, Any],
                           contributions: List[Dict[str, Any]]) -> None:
    """PRD §2.10: recognized_support_cents and pledged_support_cents "must at
    all times equal the sums of `recognized_value_cents` over that program's
    contributions in `RECEIVED` and `PLEDGED` status respectively", and
    family_engagement_credit_cents "must equal the sum of the per-row
    `match_credit_cents` values actually stored on the program's received
    contributions"."""
    received = sum(c["recognized_value_cents"] for c in contributions
                   if c["status"] == "RECEIVED")
    pledged = sum(c["recognized_value_cents"] for c in contributions
                  if c["status"] == "PLEDGED")
    match = sum(c["match_credit_cents"] for c in contributions
                if c["status"] == "RECEIVED")
    assert program["recognized_support_cents"] == received, (
        f"recognized_support_cents {program['recognized_support_cents']} != {received}")
    assert program["pledged_support_cents"] == pledged, (
        f"pledged_support_cents {program['pledged_support_cents']} != {pledged}")
    assert program["family_engagement_credit_cents"] == match, (
        f"family_engagement_credit_cents "
        f"{program['family_engagement_credit_cents']} != {match}")
