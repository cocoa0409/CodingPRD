"""Entity assertions, money/timestamp helpers and domain invariant checkers."""
from datetime import date, datetime, timedelta

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

MONEY_TOLERANCE = 0.005


# --------------------------------------------------------------- primitives
def assert_money(value, expected, label="amount"):
    """Compares two monetary figures at two-decimal-place tolerance."""
    assert value is not None, f"{label} must be present"
    assert abs(float(value) - float(expected)) <= MONEY_TOLERANCE, (
        f"Expected {label} {expected}, got {value}"
    )


def assert_ratio(value, expected, label="ratio"):
    """Compares two four-decimal-place figures."""
    assert value is not None, f"{label} must be present"
    assert abs(float(value) - float(expected)) <= 0.00005, (
        f"Expected {label} {expected}, got {value}"
    )


def canonical_instant(value):
    """Normalises an ISO 8601 UTC instant so sub-second widths never matter."""
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(microsecond=0).isoformat() + "+00:00"
    return parsed.astimezone(tz=parsed.tzinfo).replace(microsecond=0).isoformat()


def assert_same_instant(actual, expected, label="instant"):
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"Expected {label} {expected}, got {actual}"
    )


def assert_calendar_date(value, label="date"):
    assert isinstance(value, str) and len(value) == 10, (
        f"{label} must be a YYYY-MM-DD calendar date, got {value!r}"
    )
    date.fromisoformat(value)


def days_after(iso_date: str, days: int) -> str:
    return (date.fromisoformat(iso_date) + timedelta(days=days)).isoformat()


def assert_audit_block(data: dict, label="record"):
    """Every record carries a UUID id and an ISO 8601 created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 instant"
    )


def assert_versioned_block(data: dict, label="record"):
    """Records outside the append-only posting also carry updated_at + version."""
    assert_audit_block(data, label)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 instant"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1"
    )


# ------------------------------------------------------------------ entities
def assert_specialty_class(data: dict):
    assert_versioned_block(data, "specialty class")
    assert data["specialty_code"] in [
        "NEUROSURGERY", "OBSTETRICS_GYNECOLOGY", "ORTHOPEDIC_SURGERY",
        "EMERGENCY_MEDICINE", "FAMILY_MEDICINE",
    ]
    assert data["base_class_code"] in [f"CLASS_{n}" for n in range(1, 9)]
    assert float(data["base_rate_per_million"]) > 0
    assert_cost_precision(data["base_rate_per_million"])
    assert 1.0 <= float(data["hazard_index"]) <= 10.0
    assert float(data["benchmark_severity"]) > 0
    assert isinstance(data["rate_revision_index"], int)


def assert_insured(data: dict):
    assert_versioned_block(data, "insured")
    assert data["entity_type"] in ["PHYSICIAN", "FACILITY"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert is_valid_uuid(data["specialty_class_id"])
    assert data["venue_code"] in [
        "COOK_IL", "MIAMI_DADE_FL", "KINGS_NY", "TRAVIS_TX", "MARICOPA_AZ",
    ]
    assert 0 <= float(data["high_severity_procedure_pct"]) <= 100
    assert data["status"] in ["PROSPECT", "ACTIVE", "SUSPENDED"]
    assert data["credentialing_status"] in [
        "PENDING", "PROVISIONAL", "CREDENTIALED", "LAPSED", "DENIED",
    ]
    assert data["risk_class_code"] in ["R1", "R2", "R3", "R4"]
    assert float(data["risk_class_score"]) >= 0
    assert int(data["closed_paid_claim_count"]) >= 0
    assert int(data["open_claim_count"]) >= 0


def assert_enrollment(data: dict):
    assert_versioned_block(data, "enrollment")
    assert is_valid_uuid(data["insured_id"])
    assert data["program_code"] in [
        "CME_RISK_101", "SIM_LAB", "CHART_AUDIT", "TEAMSTEPPS", "EHR_SAFETY",
    ]
    assert_calendar_date(data["enrolled_on"], "enrolled_on")
    assert data["status"] in ["ENROLLED", "COMPLETED", "EXPIRED"]


def assert_peer_review_case(data: dict):
    assert_versioned_block(data, "peer review case")
    assert is_valid_uuid(data["insured_id"])
    assert data["trigger_source"] in [
        "CLAIM_INTAKE", "CREDENTIALING_REVIEW", "SENTINEL_EVENT", "COMPLAINT",
    ]
    assert data["status"] in ["REFERRED", "IN_REVIEW", "REVIEWS_COMPLETE", "CLOSED"]


def assert_policy(data: dict):
    assert_versioned_block(data, "policy")
    assert is_valid_uuid(data["insured_id"])
    assert data["policy_number"].startswith("MPL-")
    assert len(data["policy_number"]) == 10, (
        f"policy_number must be MPL- plus six digits, got {data['policy_number']}"
    )
    assert data["coverage_form"] in ["CLAIMS_MADE", "OCCURRENCE"]
    assert float(data["limit_per_claim"]) in [
        1000000.00, 2000000.00, 3000000.00, 5000000.00,
    ]
    assert float(data["limit_aggregate"]) > 0
    assert data["consent_to_settle_clause"] in ["ABSOLUTE", "HAMMER", "NONE"]
    assert data["status"] in ["QUOTED", "ACTIVE", "CANCELLED", "EXPIRED"]
    assert_cost_precision(data["quoted_premium_total"])
    assert_cost_precision(data["written_premium_net_total"])


def assert_policy_term(data: dict):
    assert_versioned_block(data, "policy term")
    assert is_valid_uuid(data["policy_id"])
    assert int(data["term_index"]) >= 1
    assert_calendar_date(data["effective_date"], "effective_date")
    assert_calendar_date(data["expiration_date"], "expiration_date")
    assert data["expiration_date"] > data["effective_date"]
    assert 1 <= int(data["claims_made_step_year"]) <= 5
    assert data["rating_variant"] in ["UNDERWRITING_SNAPSHOT", "RENEWAL_PROSPECTIVE"]
    assert data["rated_risk_class_code"] in ["R1", "R2", "R3", "R4"]
    assert data["status"] in [
        "DRAFT", "ISSUED", "IN_FORCE", "EXPIRED",
        "CANCELLED_FLAT", "CANCELLED_PRO_RATA",
    ]
    for money_field in (
        "premium_manual", "premium_net", "administrative_fee",
        "guaranty_fund_assessment", "term_total", "return_premium",
        "aggregate_limit_remaining",
    ):
        assert_cost_precision(data[money_field])


def assert_tail_endorsement(data: dict):
    assert_versioned_block(data, "tail endorsement")
    assert is_valid_uuid(data["policy_id"])
    assert is_valid_uuid(data["triggering_term_id"])
    assert data["tail_type"] in [
        "ERP_5YR", "ERP_UNLIMITED", "DEATH_DISABILITY_RETIREMENT",
    ]
    assert data["trigger_reason"] in [
        "RETIREMENT", "DISABILITY", "DEATH", "CARRIER_CHANGE", "PRACTICE_CLOSURE",
    ]
    assert_calendar_date(data["effective_date"], "effective_date")
    assert_calendar_date(data["reporting_window_end"], "reporting_window_end")
    assert data["status"] in ["QUOTED", "ISSUED", "VOID"]
    assert_cost_precision(data["mature_premium_basis"])
    assert_cost_precision(data["tail_premium"])


def assert_claim(data: dict):
    assert_versioned_block(data, "claim")
    assert is_valid_uuid(data["insured_id"])
    assert_calendar_date(data["incident_date"], "incident_date")
    assert_calendar_date(data["report_date"], "report_date")
    assert data["claim_status"] in [
        "INTAKE", "INVESTIGATION", "LITIGATION", "RESOLVED", "CLOSED",
    ]
    assert data["coverage_status"] in [
        "UNDER_REVIEW", "COVERED", "RESERVED_RIGHTS", "DENIED",
    ]
    assert data["severity_band"] in ["BAND_1", "BAND_2", "BAND_3", "BAND_4"]
    assert isinstance(data["excluded_counsel_firm_ids"], list)
    assert isinstance(data["counsel_reassignment_required"], bool)
    for money_field in (
        "demand_amount", "indemnity_reserve", "expense_reserve", "paid_indemnity",
        "paid_expense", "case_incurred", "actuarial_incurred",
        "insured_share_receivable",
    ):
        assert_cost_precision(data[money_field])


def assert_reserve_entry(data: dict):
    """A reserve posting is append-only: no updated_at, no version."""
    assert_audit_block(data, "reserve entry")
    assert "updated_at" not in data, (
        "a reserve entry carries only id and created_at; updated_at must be absent"
    )
    assert "version" not in data, (
        "a reserve entry carries only id and created_at; version must be absent"
    )
    assert is_valid_uuid(data["claim_id"])
    assert data["method"] in ["CASE_BASIS", "FORMULA_BASIS"]
    assert_cost_precision(data["computed_indemnity_amount"])
    assert_cost_precision(data["computed_expense_amount"])


def assert_counsel_firm(data: dict):
    assert_versioned_block(data, "counsel firm")
    assert isinstance(data["firm_name"], str) and data["firm_name"]
    assert isinstance(data["admitted_venue_codes"], list) and data["admitted_venue_codes"]
    assert isinstance(data["allegation_specialties"], list) and data["allegation_specialties"]
    assert float(data["blended_hourly_rate"]) > 0
    assert 0 <= int(data["quality_score"]) <= 100
    assert int(data["max_concurrent_assignments"]) >= 1
    assert data["panel_status"] in ["ACTIVE", "PROBATION", "REMOVED"]
    assert int(data["open_assignment_count"]) >= 0


def assert_counsel_assignment(data: dict):
    assert_versioned_block(data, "counsel assignment")
    assert is_valid_uuid(data["claim_id"])
    assert is_valid_uuid(data["counsel_firm_id"])
    assert data["assignment_status"] in ["ASSIGNED", "DECLINED", "REPLACED", "CLOSED"]
    assert int(data["selection_rank_snapshot"]) >= 1
    assert int(data["candidate_pool_size"]) >= 1


def assert_settlement_negotiation(data: dict):
    assert_versioned_block(data, "settlement negotiation")
    assert is_valid_uuid(data["claim_id"])
    assert int(data["round_index"]) >= 1
    assert data["status"] in [
        "AUTHORITY_REQUESTED", "AUTHORITY_GRANTED", "AUTHORITY_DENIED",
        "CONSENT_REQUESTED", "CONSENT_GRANTED", "VETOED", "HAMMER_INVOKED",
        "PAID", "ABANDONED",
    ]
    assert data["consent_clause_applied"] in ["ABSOLUTE", "HAMMER", "NONE"]
    assert isinstance(data["hammer_invoked"], bool)
    for money_field in (
        "proposed_amount", "authority_requested", "hammer_exposure_estimate",
        "insured_share_amount", "carrier_share_amount",
    ):
        assert_cost_precision(data[money_field])


def assert_npdb_report(data: dict):
    assert_versioned_block(data, "data bank report")
    assert is_valid_uuid(data["claim_id"])
    assert is_valid_uuid(data["insured_id"])
    assert isinstance(data["reportable"], bool)
    assert data["report_status"] in ["PENDING", "SUBMITTED", "VOID"]
    assert_calendar_date(data["payment_date"], "payment_date")
    assert_calendar_date(data["due_date"], "due_date")
    assert_cost_precision(data["payment_amount"])


def assert_rate_filing(data: dict):
    assert_versioned_block(data, "rate filing")
    assert is_valid_uuid(data["specialty_class_id"])
    assert data["filing_number"].startswith("RF-")
    assert len(data["filing_number"]) == 9, (
        f"filing_number must be RF- plus six digits, got {data['filing_number']}"
    )
    assert data["indication_method"] in ["LOSS_RATIO_METHOD", "PURE_PREMIUM_METHOD"]
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "WITHDRAWN",
    ]
    assert data["adequacy_flag"] in [
        "DEFICIENT", "ADEQUATE", "REDUNDANT", "NOT_EVALUABLE",
    ]


# --------------------------------------------------------------- invariants
def assert_fee_ladder(term: dict):
    """The fee ladder keys the flat fee on premium_net and the assessment on
    premium_net plus that fee, never on term_total."""
    premium_net = float(term["premium_net"])
    fee = float(term["administrative_fee"])
    if premium_net < 25000.00:
        expected_fee = 250.00
    elif premium_net < 100000.00:
        expected_fee = 500.00
    else:
        expected_fee = 900.00
    assert_money(fee, expected_fee, "administrative_fee")
    assert_money(
        term["guaranty_fund_assessment"],
        round((premium_net + fee) * 0.0125 + 1e-9, 2),
        "guaranty_fund_assessment",
    )
    assert_money(
        term["term_total"],
        round(premium_net + fee + float(term["guaranty_fund_assessment"]) + 1e-9, 2),
        "term_total",
    )


def assert_incurred_relationship(claim: dict):
    """The actuarial figure is always greater than or equal to the case figure."""
    assert float(claim["actuarial_incurred"]) >= float(claim["case_incurred"]) - 0.005, (
        "actuarial_incurred must not fall below case_incurred"
    )


def assert_reserve_entry_absent_audit_fields(data: dict):
    assert "updated_at" not in data and "version" not in data, (
        "reserve postings expose neither updated_at nor version"
    )
