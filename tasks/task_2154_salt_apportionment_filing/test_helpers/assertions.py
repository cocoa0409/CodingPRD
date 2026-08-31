"""Entity assertions and domain invariant checkers."""

import re

import pytest
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

# ISO 8601 UTC with exactly three fractional digits, PRD Section 2.4.
_ISO_MILLIS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

MONEY_TOLERANCE = 0.005
RATIO_TOLERANCE = 5e-7


def assert_money(actual, expected, label="amount"):
    """Assert a monetary figure matches to the cent."""
    assert actual is not None, f"{label} must be present"
    assert actual == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"Expected {label} {expected}, got {actual}"
    )


def assert_ratio(actual, expected, label="ratio"):
    """Assert an apportionment quantity matches at 6 decimal places."""
    assert actual is not None, f"{label} must be present"
    assert actual == pytest.approx(expected, abs=RATIO_TOLERANCE), (
        f"Expected {label} {expected:.6f}, got {actual}"
    )


def assert_instant(actual, expected, label="instant"):
    """Assert a datetime field equals an expected UTC instant.

    Compares the second-resolution prefix so that a value carrying the three
    fractional digits of PRD Section 2.4 matches an expected whole-second
    instant.
    """
    assert actual is not None, f"{label} must be present, got null"
    normalized_actual = str(actual).replace(".000Z", "Z")
    normalized_expected = str(expected).replace(".000Z", "Z")
    assert normalized_actual == normalized_expected, (
        f"Expected {label} {expected}, got {actual}"
    )


def assert_millisecond_timestamp(value, label="timestamp"):
    """Assert an ISO 8601 UTC timestamp carrying exactly three fractional digits."""
    assert _ISO_MILLIS_RE.match(str(value)), (
        f"{label} must be ISO 8601 UTC with three fractional digits, got {value!r}"
    )


def assert_common_fields(data: dict, label="resource"):
    """Assert the id / created_at / updated_at / version quartet of PRD Section 2.4."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a bare UUID with no type prefix, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer of at least 1, got {data.get('version')!r}"
    )


# ─── Per-entity assertions ────────────────────────────────────────────────────

def assert_taxpayer_group(data: dict):
    assert_common_fields(data, "TaxpayerGroup")
    assert isinstance(data["name"], str) and data["name"]
    assert re.match(r"^[A-Z]{2}$", data["base_state_code"])
    assert 1 <= data["fiscal_year_end_month"] <= 12
    assert data["everywhere_sales"] >= 0
    assert data["everywhere_property"] >= 0
    assert data["everywhere_payroll"] >= 0
    assert isinstance(data["open_registration_obligations"], int)
    assert data["open_registration_obligations"] >= 0
    assert data["compliance_posture"] in ("COMPLIANT", "EXPOSED", "DELINQUENT")
    assert data["nowhere_sales_pool"] >= 0


def assert_legal_entity(data: dict):
    assert_common_fields(data, "LegalEntity")
    assert is_valid_uuid(data["group_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert data["entity_type"] in ("CORP", "LLC", "PARTNERSHIP", "DISREGARDED")
    assert re.match(r"^[A-Z]{2}$", data["incorporation_state_code"])
    assert isinstance(data["is_unitary_member"], bool)


def assert_state_registration(data: dict):
    assert_common_fields(data, "StateRegistration")
    assert is_valid_uuid(data["group_id"])
    assert re.match(r"^[A-Z]{2}$", data["state_code"])
    assert data["factor_formula"] in (
        "EQUAL_WEIGHTED_THREE", "DOUBLE_WEIGHTED_SALES", "SINGLE_SALES_FACTOR",
    )
    assert 0 <= data["tax_rate"] <= 1
    assert data["throwback_rule"] in ("THROWBACK", "THROWOUT", "NONE")
    assert data["service_sourcing_rule"] in ("MARKET_BASED", "COST_OF_PERFORMANCE")
    assert data["nexus_status"] in (
        "NONE", "PROTECTED_PL86272", "ECONOMIC", "PHYSICAL", "VOLUNTARY",
    )
    assert data["registration_status"] in (
        "NOT_REQUIRED", "REGISTRATION_REQUIRED", "REGISTERED", "WITHDRAWN",
    )
    assert 1 <= data["due_month"] <= 12
    assert 1 <= data["due_day"] <= 28
    assert 0 <= data["extension_months"] <= 12
    assert 1 <= data["estimated_installment_count"] <= 4
    assert data["safe_harbor_basis"] in (
        "PRIOR_YEAR_100", "PRIOR_YEAR_110", "CURRENT_YEAR_90",
    )
    assert_cost_precision(data["total_payments_received"])
    assert_cost_precision(data["unapplied_payment_balance"])


def assert_activity_record(data: dict):
    """An activity record is immutable and carries only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), "ActivityRecord.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "ActivityRecord.created_at must be ISO 8601 UTC"
    )
    assert "updated_at" not in data, (
        "ActivityRecord must not expose updated_at — it is never updated"
    )
    assert "version" not in data, (
        "ActivityRecord must not expose version — it is never re-versioned"
    )
    assert is_valid_uuid(data["registration_id"])
    assert is_valid_uuid(data["legal_entity_id"])
    assert isinstance(data["tax_year"], int)


def assert_filing_election(data: dict):
    assert_common_fields(data, "FilingElection")
    assert is_valid_uuid(data["registration_id"])
    assert data["election_basis"] in (
        "COMBINED_UNITARY", "SEPARATE_ENTITY", "CONSOLIDATED",
    )
    assert data["binding_years"] >= 1
    assert data["status"] in ("ELECTED", "REVOKED", "EXPIRED")
    assert data["expires_after_tax_year"] == (
        data["effective_tax_year"] + data["binding_years"] - 1
    ), "expires_after_tax_year must be effective_tax_year + binding_years - 1"
    assert isinstance(data["reinstatement_count"], int)


def assert_state_filing(data: dict):
    assert_common_fields(data, "StateFiling")
    assert is_valid_uuid(data["registration_id"])
    assert isinstance(data["tax_year"], int)
    assert data["filing_basis"] in (
        "COMBINED_UNITARY", "SEPARATE_ENTITY", "CONSOLIDATED",
    )
    assert data["preparation_status"] in (
        "DRAFT", "FACTORS_LOCKED", "IN_REVIEW", "APPROVED", "FILED", "AMENDED",
    )
    assert data["payment_status"] in (
        "UNPAID", "PARTIALLY_PAID", "PAID", "OVERPAID", "REFUND_CLAIMED",
    )
    assert data["apportionment_variant"] in (None, "JOYCE", "FINNIGAN")
    assert is_iso8601_timestamp(data["original_due_date"])
    for money_field in (
        "modification_total", "state_taxable_income", "tax_before_credits",
        "credits_applied_total", "estimated_credits_applied",
        "assessment_added_total", "balance_due",
    ):
        assert_cost_precision(data[money_field])
    assert isinstance(data["amendment_count"], int)


def assert_apportionment_factor(data: dict):
    assert_common_fields(data, "ApportionmentFactor")
    assert is_valid_uuid(data["filing_id"])
    assert data["factor_type"] in ("SALES", "PROPERTY", "PAYROLL")
    assert isinstance(data["included"], bool)
    assert data["numerator"] >= 0
    assert data["denominator"] >= 0


def assert_modification(data: dict):
    assert_common_fields(data, "Modification")
    assert is_valid_uuid(data["filing_id"])
    assert data["direction"] in ("ADDITION", "SUBTRACTION")
    assert data["raw_amount"] >= 0
    assert 0 <= data["allocation_ratio"] <= 1
    assert data["sequence_number"] >= 1
    assert_cost_precision(data["line_amount"])


def assert_credit_claim(data: dict):
    assert_common_fields(data, "CreditClaim")
    assert is_valid_uuid(data["filing_id"])
    assert data["granted_amount"] > 0
    assert data["priority_order"] >= 1
    assert isinstance(data["refundable"], bool)
    assert data["status"] in (
        "PENDING", "PARTIALLY_APPLIED", "FULLY_APPLIED", "CARRIED_FORWARD", "EXPIRED",
    )
    assert_credit_pool_conserved(data)


def assert_estimated_payment(data: dict):
    assert_common_fields(data, "EstimatedPayment")
    assert is_valid_uuid(data["registration_id"])
    assert 1 <= data["installment_number"] <= 4
    assert data["amount"] > 0
    assert isinstance(data["is_timely"], bool)
    assert data["status"] in ("RECEIVED", "APPLIED", "UNAPPLIED", "REFUNDED")
    assert_cost_precision(data["safe_harbor_required_amount"])
    assert_cost_precision(data["underpayment_amount"])
    assert_cost_precision(data["underpayment_penalty"])
    assert data["underpayment_amount"] >= 0


def assert_extension_request(data: dict):
    assert_common_fields(data, "ExtensionRequest")
    assert is_valid_uuid(data["filing_id"])
    assert data["estimated_tax_paid"] >= 0
    assert data["status"] in ("REQUESTED", "GRANTED", "DENIED")
    assert_cost_precision(data["required_prepayment"])


def assert_notice(data: dict):
    assert_common_fields(data, "Notice")
    assert is_valid_uuid(data["filing_id"])
    assert data["notice_type"] in (
        "MATH_ERROR", "NEXUS_INQUIRY", "PROPOSED_ASSESSMENT", "FINAL_ASSESSMENT",
    )
    assert data["assessed_tax"] >= 0
    assert data["status"] in (
        "OPEN", "RESPONDED", "INFO_REQUESTED", "APPEAL_FILED",
        "APPEAL_SUSTAINED", "APPEAL_DENIED", "CLOSED",
    )
    assert isinstance(data["response_round"], int)
    for money_field in (
        "penalty_amount", "interest_amount", "assessment_final_amount",
    ):
        assert_cost_precision(data[money_field])


def assert_vda_agreement(data: dict):
    assert_common_fields(data, "VDAAgreement")
    assert is_valid_uuid(data["registration_id"])
    assert is_valid_uuid(data["legal_entity_id"])
    assert data["exposure_variant"] in ("LOOKBACK_LIMITED", "FULL_EXPOSURE")
    assert data["status"] in ("DRAFT", "SUBMITTED", "EXECUTED", "WITHDRAWN")
    assert data["lookback_end_year"] == data["anchor_tax_year"], (
        "lookback_end_year always equals anchor_tax_year"
    )
    assert data["lookback_start_year"] == (
        data["anchor_tax_year"] - data["effective_lookback_years"] + 1
    )
    assert_cost_precision(data["computed_exposure_tax"])


# ─── Domain invariants ────────────────────────────────────────────────────────

def assert_credit_pool_conserved(claim: dict):
    """granted_amount == applied_amount + carryforward_amount + expired_amount."""
    total = round(
        claim["applied_amount"] + claim["carryforward_amount"] + claim["expired_amount"],
        2,
    )
    assert total == pytest.approx(claim["granted_amount"], abs=MONEY_TOLERANCE), (
        f"Credit pool not conserved on claim {claim.get('credit_code')}: "
        f"granted {claim['granted_amount']} != applied {claim['applied_amount']} "
        f"+ carryforward {claim['carryforward_amount']} "
        f"+ expired {claim['expired_amount']}"
    )


def assert_obligation_counter_matches(group: dict, registrations: list):
    """open_registration_obligations equals the count of REGISTRATION_REQUIRED rows."""
    expected = sum(
        1 for r in registrations if r["registration_status"] == "REGISTRATION_REQUIRED"
    )
    assert group["open_registration_obligations"] == expected, (
        f"open_registration_obligations {group['open_registration_obligations']} "
        f"does not equal the {expected} REGISTRATION_REQUIRED registrations of the group"
    )


def assert_balance_due_identity(filing: dict):
    """balance_due == tax_before_credits - credits - estimated + assessments."""
    expected = round(
        filing["tax_before_credits"]
        - filing["credits_applied_total"]
        - filing["estimated_credits_applied"]
        + filing["assessment_added_total"],
        2,
    )
    assert filing["balance_due"] == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"balance_due {filing['balance_due']} does not match the derived {expected}"
    )


def factor_by_type(factor_rows: list, factor_type: str) -> dict:
    """Pick one apportionment factor row out of a factors listing."""
    matches = [row for row in factor_rows if row["factor_type"] == factor_type]
    assert len(matches) == 1, (
        f"Expected exactly one {factor_type} factor row, got {len(matches)}"
    )
    return matches[0]
