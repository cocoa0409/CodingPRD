"""Entity assertions and domain invariant helpers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_appetite_rule(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("keyword"), str) and data["keyword"]
    assert isinstance(data.get("class_code"), str) and data["class_code"]
    assert data.get("disposition") in ("ADMIT", "REFER", "DECLINE")
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert is_iso8601_timestamp(data.get("effective_to", ""))
    assert isinstance(data.get("is_enabled"), bool)
    assert isinstance(data.get("priority_rank"), int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("version"), int)


def assert_class_code(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("code"), str) and data["code"]
    assert isinstance(data.get("eligible_lines"), list) and data["eligible_lines"]
    assert isinstance(data.get("base_rates_cents"), dict)
    assert isinstance(data.get("risk_factor"), (int, float))
    assert isinstance(data.get("appetite_active"), bool)
    assert isinstance(data.get("version"), int)


def assert_business_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert isinstance(data.get("contact_email"), str) and data["contact_email"]
    assert data.get("channel") in ("DIRECT", "AGENT", "PARTNER")
    assert isinstance(data.get("account_credit_cents"), int)
    assert isinstance(data.get("open_claim_count"), int)
    assert isinstance(data.get("claims_free_flag"), bool)
    assert isinstance(data.get("version"), int)


def assert_quote(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("business_account_id"), str)
    assert isinstance(data.get("selected_lines"), list)
    assert isinstance(data.get("exposure_units"), int)
    assert isinstance(data.get("risk_score"), int)
    assert 0 <= data["risk_score"] <= 100
    assert data.get("status") in (
        "CLASSIFYING", "QUOTED", "REFERRED", "DECLINED",
        "EXPIRED", "BOUND", "SUPERSEDED",
    )
    assert isinstance(data.get("version"), int)


def assert_policy(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("quote_id"), str)
    assert isinstance(data.get("business_account_id"), str)
    assert isinstance(data.get("term_start"), str)
    assert isinstance(data.get("term_end"), str)
    assert data.get("term_day_count") == 365
    assert isinstance(data.get("exposure_units"), int)
    assert isinstance(data.get("base_annual_premium_cents"), int)
    assert isinstance(data.get("earned_premium_cents"), int)
    assert isinstance(data.get("open_claim_count"), int)
    assert data.get("status") in (
        "BOUND", "ACTIVE", "CANCELLED", "EXPIRED",
        "NON_RENEWAL_PENDING", "NON_RENEWED", "RENEWED",
    )
    assert isinstance(data.get("version"), int)


def assert_endorsement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("policy_id"), str)
    assert data.get("endorsement_type") in (
        "COVERAGE_ADJUST", "ADDITIONAL_INSURED", "LIMIT_CHANGE", "CLASS_RECODE",
    )
    assert data.get("status") in ("DRAFT", "EFFECTIVE", "VOID")
    assert isinstance(data.get("premium_delta_cents"), int)
    assert isinstance(data.get("version"), int)


def assert_certificate(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("policy_id"), str)
    assert isinstance(data.get("endorsement_id"), str)
    assert isinstance(data.get("holder_name"), str) and data["holder_name"]
    assert isinstance(data.get("certificate_no"), str) and data["certificate_no"]
    assert data.get("status") in ("ISSUED", "VOIDED")
    assert isinstance(data.get("version"), int)


def assert_claim(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("policy_id"), str)
    assert isinstance(data.get("reported_by"), str)
    assert isinstance(data.get("claim_amount_cents"), int)
    assert data.get("triage_tier") in ("FAST_TRACK", "STANDARD", "COMPLEX")
    assert isinstance(data.get("evidence_count"), int)
    assert data.get("status") in (
        "SUBMITTED", "IN_REVIEW", "APPROVED", "PAID", "DENIED", "CLOSED",
    )
    assert isinstance(data.get("version"), int)


def assert_claim_evidence(data: dict):
    """ClaimEvidence is append-only: id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("claim_id"), str)
    assert isinstance(data.get("photo_ref"), str)
    assert isinstance(data.get("file_size_bytes"), int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "version" not in data, "ClaimEvidence must not carry a version field"
    assert "updated_at" not in data, "ClaimEvidence must not carry updated_at"


def assert_non_renewal_notice(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("policy_id"), str)
    assert data.get("reason_code") in (
        "APPETITE_CHANGE", "RISK_ESCALATION", "CARRIER_WITHDRAWAL",
    )
    assert isinstance(data.get("days_before_term_end"), int)
    assert isinstance(data.get("version"), int)


def assert_referral(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("status") in ("OPEN", "RESOLVED")
    assert data.get("decision") in ("PENDING", "APPROVED", "DECLINED")
    assert isinstance(data.get("version"), int)
