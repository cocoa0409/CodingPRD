"""Entity assertions, instant helpers and domain invariant checkers."""
import math
import re
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    BPS_SCALE,
    CREDIBILITY_CEILING_BPS,
    CREDIBILITY_FLOOR_BPS,
    MILLICENTS_PER_CENT,
    TIER_A_DISCOUNT_BPS,
    TIER_A_FLOOR_CENTS,
    TIER_B_DISCOUNT_BPS,
    TIER_B_FLOOR_CENTS,
)

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

PETITION_STATUSES = [
    "DRAFT", "FORMAT_REVIEW", "FORMAT_REJECTED", "TITLE_PENDING", "CLEARED",
    "SIGNATURES_FILED", "SAMPLE_VERIFICATION", "FULL_CHECK", "CURE_PERIOD",
    "PENDING_CERTIFICATION", "PENDING_FAILURE", "CERTIFIED", "FAILED",
]
CHALLENGE_DIMENSIONS = [
    "NONE", "CHALLENGE_FILED", "COURT_REVIEW", "COURT_AFFIRMED", "COURT_REVERSED",
]
BATCH_STATUSES = [
    "RECEIVED", "AFFIDAVIT_VERIFIED", "SAMPLED", "FULLY_CHECKED",
    "REJECTED_FORMAT", "INVALIDATED",
]
LINE_STATUSES = [
    "PENDING", "VALID", "INVALID_NOT_REGISTERED", "INVALID_DUPLICATE",
    "INVALID_SIGNATURE_MISMATCH", "INVALID_WRONG_COUNTY",
    "INVALID_FORMAT_DEFECT", "VOIDED",
]


# --- instant helpers ------------------------------------------------------

def parse_instant(value):
    """Parse an ISO 8601 UTC instant into an aware datetime."""
    assert isinstance(value, str) and value, f"expected an instant string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def instants_equal(left, right):
    """Compare two ISO 8601 UTC instants by value, ignoring fractional-digit
    width and offset spelling."""
    return parse_instant(left) == parse_instant(right)


def assert_instants_equal(actual, expected, label="instant"):
    assert instants_equal(actual, expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def plus_days(instant, days):
    """Return the instant advanced by whole days, formatted with three
    fractional digits and a trailing Z."""
    moved = parse_instant(instant) + timedelta(days=days)
    return moved.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moved.microsecond // 1000:03d}Z"


def minus_days(instant, days):
    return plus_days(instant, -days)


def plus_seconds(instant, seconds):
    moved = parse_instant(instant) + timedelta(seconds=seconds)
    return moved.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moved.microsecond // 1000:03d}Z"


def assert_millisecond_instant(value, label="timestamp"):
    """Server-stamped instants are ISO 8601 UTC with three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", value), (
        f"{label} must be an ISO 8601 UTC instant with three fractional digits, "
        f"got {value!r}"
    )


# --- arithmetic helpers (integer only) ------------------------------------

def ceil_div(numerator, denominator):
    return -((-numerator) // denominator)


def floor_div(numerator, denominator):
    return numerator // denominator


def round_half_up(numerator, denominator):
    return math.floor((numerator * 2 + denominator) / (denominator * 2))


def expected_batch_cost_cents(checked_signature_count, rate_millicents):
    return round_half_up(checked_signature_count * rate_millicents, MILLICENTS_PER_CENT)


def expected_invoice(gross_cents, county_surcharge_bps):
    """Return the whole invoice breakdown for a gross, per the tiered rule."""
    if gross_cents >= TIER_B_FLOOR_CENTS:
        tier, discount_bps = "TIER_B", TIER_B_DISCOUNT_BPS
    elif gross_cents >= TIER_A_FLOOR_CENTS:
        tier, discount_bps = "TIER_A", TIER_A_DISCOUNT_BPS
    else:
        tier, discount_bps = "TIER_NONE", 0
    discount_cents = floor_div(gross_cents * discount_bps, BPS_SCALE)
    subtotal_cents = gross_cents - discount_cents
    surcharge_cents = ceil_div(subtotal_cents * county_surcharge_bps, BPS_SCALE)
    return {
        "gross_cents": gross_cents,
        "tier": tier,
        "discount_bps": discount_bps,
        "discount_cents": discount_cents,
        "subtotal_cents": subtotal_cents,
        "surcharge_cents": surcharge_cents,
        "total_cents": subtotal_cents + surcharge_cents,
    }


# --- generic field-shape assertions --------------------------------------

def assert_uuid_id(data):
    assert is_valid_uuid(data.get("id", "")) or _UUID_RE.match(str(data.get("id"))), (
        f"id must be a UUID with no type prefix, got {data.get('id')!r}"
    )


def assert_config_resource_shape(data, label):
    """The three configuration resources carry only id and created_at; neither
    updated_at nor version exists on them."""
    assert_uuid_id(data)
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 instant, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, (
        f"{label} must not carry updated_at — the field is absent from the resource"
    )
    assert "version" not in data, (
        f"{label} must not carry version — the field is absent from the resource"
    )


def assert_managed_resource_shape(data, label):
    """Resources carrying the full set of system-managed properties."""
    assert_uuid_id(data)
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 instant"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 instant"
    )
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version must start at or above 1"


# --- per-entity assertions ------------------------------------------------

def assert_verification_standard(data):
    assert_config_resource_shape(data, "VerificationStandard")
    assert isinstance(data["jurisdiction_code"], str)
    assert 2 <= len(data["jurisdiction_code"]) <= 8
    for field in (
        "gubernatorial_vote_total", "signature_pct_bps", "sample_pct_bps",
        "sample_min_count", "sufficiency_upper_bps", "sufficiency_lower_bps",
        "county_distribution_pct_bps", "required_qualifying_counties",
        "cure_window_days", "cure_eligibility_floor_bps", "circulation_window_days",
        "verification_rate_millicents_per_signature", "county_surcharge_bps",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["stratification_mode"] in ("POOLED", "STRATIFIED")
    assert isinstance(data["cure_allowed"], bool)


def assert_county(data):
    assert_config_resource_shape(data, "County")
    assert isinstance(data["county_code"], str) and 2 <= len(data["county_code"]) <= 12
    assert isinstance(data["name"], str)
    assert isinstance(data["registered_voter_count"], int)
    assert data["registered_voter_count"] >= 1


def assert_voter_record(data):
    assert_config_resource_shape(data, "VoterRecord")
    assert isinstance(data["county_id"], str)
    assert isinstance(data["voter_id_number"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["signature_on_file_hash"], str)
    assert data["registration_status"] in ("ACTIVE", "INACTIVE", "CANCELLED", "PENDING")
    assert is_iso8601_timestamp(data["registration_date"])


def assert_petition(data):
    assert_managed_resource_shape(data, "Petition")
    assert isinstance(data["standard_id"], str)
    assert isinstance(data["proponent_user_id"], str)
    assert isinstance(data["proponent_name"], str)
    assert isinstance(data["submitted_title"], str)
    assert isinstance(data["measure_subject_codes"], list)
    assert 1 <= len(data["measure_subject_codes"]) <= 5
    assert data["status"] in PETITION_STATUSES
    assert data["challenge_status"] in CHALLENGE_DIMENSIONS
    for field in (
        "format_review_round", "required_valid_signatures", "raw_signature_count",
        "accepted_raw_total", "projected_valid_count", "verified_valid_count",
        "qualifying_county_count", "verification_cost_accrued_cents",
        "voided_signature_count", "cure_period_count",
    ):
        assert isinstance(data[field], int), f"Petition.{field} must be an integer"
        assert data[field] >= 0, f"Petition.{field} must never be negative"


def assert_circulator(data):
    assert_managed_resource_shape(data, "Circulator")
    assert isinstance(data["full_name"], str)
    assert isinstance(data["residency_state_code"], str)
    assert len(data["residency_state_code"]) == 2
    assert isinstance(data["is_paid"], bool)
    assert isinstance(data["paid_disclosure_on_file"], bool)
    assert data["registration_status"] in (
        "PENDING_TRAINING", "TRAINED", "REGISTERED", "SUSPENDED", "REVOKED"
    )
    assert isinstance(data["misconduct_strike_count"], int)
    assert isinstance(data["credibility_score_bps"], int)
    assert CREDIBILITY_FLOOR_BPS <= data["credibility_score_bps"] <= CREDIBILITY_CEILING_BPS, (
        "credibility_score_bps must be clamped into the inclusive range "
        f"{CREDIBILITY_FLOOR_BPS}..{CREDIBILITY_CEILING_BPS}, got "
        f"{data['credibility_score_bps']}"
    )


def assert_circulation_assignment(data):
    assert_managed_resource_shape(data, "CirculationAssignment")
    assert isinstance(data["petition_id"], str)
    assert isinstance(data["circulator_id"], str)
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert parse_instant(data["effective_to"]) > parse_instant(data["effective_from"])
    assert isinstance(data["assigned_county_codes"], list)
    assert 1 <= len(data["assigned_county_codes"]) <= 10
    assert len(set(data["assigned_county_codes"])) == len(data["assigned_county_codes"])
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["paid_disclosure_ack"], bool)


def assert_signature_batch(data):
    assert_managed_resource_shape(data, "SignatureBatch")
    assert isinstance(data["petition_id"], str)
    assert isinstance(data["circulator_id"], str)
    assert isinstance(data["county_id"], str)
    assert isinstance(data["is_supplemental"], bool)
    assert isinstance(data["affidavit_signed"], bool)
    assert is_iso8601_timestamp(data["filed_at"])
    for field in (
        "raw_count", "accepted_raw_count", "format_defect_count",
        "checked_signature_count", "verification_cost_cents",
    ):
        assert isinstance(data[field], int), f"SignatureBatch.{field} must be an integer"
        assert data[field] >= 0
    assert data["status"] in BATCH_STATUSES
    if data["status_before_invalidation"] is not None:
        assert data["status_before_invalidation"] in BATCH_STATUSES


def assert_signature_record(data):
    assert_managed_resource_shape(data, "SignatureRecord")
    assert isinstance(data["batch_id"], str)
    assert isinstance(data["line_number"], int) and data["line_number"] >= 1
    assert isinstance(data["signer_name"], str)
    assert isinstance(data["claimed_voter_id_number"], str)
    assert is_iso8601_timestamp(data["signed_on"])
    assert isinstance(data["signature_hash"], str)
    assert isinstance(data["in_sample"], bool)
    assert data["validation_status"] in LINE_STATUSES
    assert isinstance(data["manual_match_override_applied"], bool)
    if data["void_reason"] is not None:
        assert data["void_reason"] in (
            "BATCH_INVALIDATED", "CIRCULATOR_REVOKED", "FRAUD_SUBSTANTIATED"
        )


def assert_verification_round(data):
    assert_managed_resource_shape(data, "VerificationRound")
    assert isinstance(data["petition_id"], str)
    assert data["round_type"] in ("RANDOM_SAMPLE", "FULL_CHECK", "CURE_RECHECK")
    assert isinstance(data["round_index"], int) and data["round_index"] >= 1
    assert data["status"] in ("OPEN", "CLOSED", "VOIDED")
    for field in (
        "eligible_pool_size", "sample_size", "sampled_valid_count",
        "validity_rate_bps", "projected_valid_count", "accrued_cost_cents",
    ):
        assert isinstance(data[field], int), f"VerificationRound.{field} must be an integer"
    assert data["determination"] in (
        "PENDING", "SUFFICIENT", "INSUFFICIENT", "FULL_CHECK_REQUIRED"
    )


def assert_cure_period(data):
    assert_managed_resource_shape(data, "CurePeriod")
    assert isinstance(data["petition_id"], str)
    assert is_iso8601_timestamp(data["opened_at"])
    assert is_iso8601_timestamp(data["deadline_at"])
    for field in (
        "shortfall_at_open", "assumed_validity_rate_bps",
        "cure_target_raw_signatures", "supplemental_raw_count",
    ):
        assert isinstance(data[field], int), f"CurePeriod.{field} must be an integer"
        assert data[field] >= 0
    assert data["status"] in (
        "OPEN", "CLOSED_SUFFICIENT", "CLOSED_INSUFFICIENT", "EXPIRED"
    )


def assert_challenge(data):
    assert_managed_resource_shape(data, "Challenge")
    assert isinstance(data["petition_id"], str)
    assert isinstance(data["challenger_user_id"], str)
    assert isinstance(data["challenger_name"], str)
    assert data["grounds"] in (
        "COUNT_ERROR", "FORGERY", "CIRCULATOR_INELIGIBLE", "FORMAT_DEFECT"
    )
    assert isinstance(data["statement"], str)
    assert is_iso8601_timestamp(data["filed_at"])
    assert is_iso8601_timestamp(data["review_deadline_at"])
    assert data["status"] in ("FILED", "COURT_REVIEW", "UPHELD", "DISMISSED")
    if data["ruling"] is not None:
        assert data["ruling"] in ("AFFIRM", "REVERSE")


def assert_fraud_referral(data):
    assert_managed_resource_shape(data, "FraudReferral")
    assert isinstance(data["petition_id"], str)
    assert isinstance(data["circulator_id"], str)
    assert data["referral_type"] in (
        "FORGED_SIGNATURES", "CIRCULATOR_MISCONDUCT", "FALSE_AFFIDAVIT"
    )
    assert isinstance(data["narrative"], str)
    assert isinstance(data["opened_by_examiner_id"], str)
    assert isinstance(data["referred_to_ag"], bool)
    assert isinstance(data["voided_signature_count"], int)
    assert data["status"] in (
        "OPENED", "REFERRED_TO_AG", "SUBSTANTIATED", "UNSUBSTANTIATED"
    )
    if data["finding"] is not None:
        assert data["finding"] in ("SUBSTANTIATED", "UNSUBSTANTIATED")


# --- domain invariant checkers -------------------------------------------

def assert_petition_counters_non_negative(data):
    for field in (
        "raw_signature_count", "accepted_raw_total", "projected_valid_count",
        "verified_valid_count", "qualifying_county_count",
        "verification_cost_accrued_cents", "voided_signature_count",
        "cure_period_count",
    ):
        assert data[field] >= 0, f"Petition.{field} must never go negative"


def assert_signature_ledger_restored(before, after):
    """Invalidating a batch and then reinstating it must return the signature
    ledger to the identical values it held before the invalidation."""
    for field in (
        "accepted_raw_total", "verified_valid_count", "projected_valid_count",
        "voided_signature_count", "qualifying_county_count",
    ):
        assert after[field] == before[field], (
            f"Petition.{field} must be restored byte-identically: "
            f"before={before[field]}, after={after[field]}"
        )


def assert_cost_ledger_restored(before, after):
    assert after["verification_cost_accrued_cents"] == before["verification_cost_accrued_cents"], (
        "Petition.verification_cost_accrued_cents must be restored to the "
        f"identical value: before={before['verification_cost_accrued_cents']}, "
        f"after={after['verification_cost_accrued_cents']}"
    )


def assert_version_advanced(before, after, by=1):
    assert after["version"] == before["version"] + by, (
        f"version must advance by {by}: before={before['version']}, "
        f"after={after['version']}"
    )


def assert_invoice_breakdown(data, gross_cents, county_surcharge_bps):
    expected = expected_invoice(gross_cents, county_surcharge_bps)
    for field, want in expected.items():
        assert data[field] == want, (
            f"invoice.{field}: expected {want}, got {data[field]} "
            f"(gross {gross_cents}, surcharge {county_surcharge_bps} bps)"
        )
