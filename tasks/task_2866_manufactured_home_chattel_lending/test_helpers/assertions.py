"""Entity assertions and domain invariant checkers.

Every resource carries a server-minted ``id`` formatted as a UUID with no type
prefix and a ``created_at`` ISO 8601 UTC instant.  Most resources also carry
``updated_at`` and ``version``; a BookValueGuide and a PaymentTransaction do
not, and asserting their absence is part of the contract.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant, instants_equal


# ─── Shared audit-field helpers ───────────────────────

def assert_identity_fields(data: Dict[str, Any], entity_name: str) -> None:
    """id is a UUID with no type prefix, created_at is an ISO 8601 UTC instant."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a UUID with no type prefix, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be an ISO 8601 UTC instant, "
        f"got {data.get('created_at')!r}"
    )


def assert_versioned_fields(data: Dict[str, Any], entity_name: str) -> None:
    """updated_at and a version that starts at 1 and increments by one."""
    assert_identity_fields(data, entity_name)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be an ISO 8601 UTC instant, "
        f"got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"{entity_name}.version must be an integer, got {data.get('version')!r}"
    )
    assert data["version"] >= 1, (
        f"{entity_name}.version starts at 1, got {data['version']}"
    )


def assert_immutable_entity_fields(data: Dict[str, Any], entity_name: str) -> None:
    """An immutable resource carries only id and created_at — no updated_at, no version."""
    assert_identity_fields(data, entity_name)
    assert "updated_at" not in data, (
        f"{entity_name} is never mutated in place and must carry no updated_at field"
    )
    assert "version" not in data, (
        f"{entity_name} is never mutated in place and must carry no version field"
    )


def assert_integer_cents(data: Dict[str, Any], *field_names: str) -> None:
    """Every named monetary field is a JSON integer, never a decimal or a string."""
    for field in field_names:
        value = data.get(field)
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{field} must be an integer number of cents, got {value!r}"
        )


def assert_instant_equals(actual: Optional[str], expected: Optional[str], label: str) -> None:
    """Compare two ISO 8601 UTC instants without depending on fractional width."""
    assert instants_equal(actual, expected), (
        f"{label}: expected instant {expected!r}, got {actual!r} "
        f"(canonical {canonical_instant(actual)!r})"
    )


# ─── Per-entity assertions ────────────────────────────

def assert_book_value_guide(data: Dict[str, Any]) -> None:
    assert_immutable_entity_fields(data, "BookValueGuide")
    assert isinstance(data["guide_edition"], str) and data["guide_edition"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert is_iso8601_timestamp(data["effective_date"])
    assert data["base_value_per_sqft_cents"] > 0
    assert data["single_wide_multiplier_bps"] > 0
    assert data["multi_wide_multiplier_bps"] > 0
    assert 0 <= data["annual_depreciation_bps"] <= 1000


def assert_borrower(data: Dict[str, Any]) -> None:
    assert_versioned_fields(data, "Borrower")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert 300 <= data["credit_score"] <= 850
    assert data["monthly_income_cents"] >= 0
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert_integer_cents(data, "monthly_income_cents", "total_outstanding_principal_cents")
    assert data["units_under_recovery_hold_count"] >= 0
    # status is SUSPENDED whenever units_under_recovery_hold_count is above zero
    expected_status = "SUSPENDED" if data["units_under_recovery_hold_count"] > 0 else "ACTIVE"
    assert data["status"] == expected_status, (
        f"Borrower.status must be {expected_status} with "
        f"units_under_recovery_hold_count {data['units_under_recovery_hold_count']}, "
        f"got {data['status']}"
    )


def assert_community(data: Dict[str, Any]) -> None:
    assert_versioned_fields(data, "Community")
    assert isinstance(data["name"], str) and data["name"]
    assert len(data["state_code"]) == 2
    assert data["lot_count"] > 0
    assert data["monthly_lot_rent_cents"] >= 0
    assert 0 <= data["sales_commission_bps"] <= 500
    assert data["operator_agreement_status"] in (
        "NONE",
        "PENDING",
        "EXECUTED",
        "TERMINATED",
    )
    assert isinstance(data["lender_access_rights"], bool)
    if data["operator_agreement_status"] == "EXECUTED":
        assert data["lender_access_rights"] is True
        assert is_iso8601_timestamp(data["agreement_executed_at"] or "")


def assert_manufactured_unit(data: Dict[str, Any]) -> None:
    assert_versioned_fields(data, "ManufacturedUnit")
    assert isinstance(data["hud_label_number"], str) and data["hud_label_number"]
    assert data["width_class"] in ("SINGLE_WIDE", "MULTI_WIDE")
    assert data["square_feet"] > 0
    assert data["condition_grade"] in ("EXCELLENT", "GOOD", "FAIR", "POOR")
    assert data["installation_type"] in ("PIER_AND_ANCHOR", "PERMANENT_FOUNDATION")
    assert data["wind_zone"] in (1, 2, 3)
    assert data["placement_type"] in ("COMMUNITY", "PRIVATE_LAND")
    assert data["classification"] in (
        "PERSONAL_PROPERTY",
        "CONVERSION_PENDING",
        "REAL_PROPERTY",
    )
    assert data["title_status"] in (
        "ACTIVE_TITLE",
        "TITLE_ENCUMBERED",
        "TITLE_SURRENDERED",
    )
    assert isinstance(data["recovery_hold"], bool)
    assert isinstance(data["deed_recorded"], bool)
    assert isinstance(data["affixation_affidavit_recorded"], bool)
    if data["placement_type"] == "COMMUNITY":
        assert data["community_id"] is not None
        assert data["land_owner_borrower_id"] is None
    else:
        assert data["land_owner_borrower_id"] is not None
        assert data["community_id"] is None


def assert_valuation(data: Dict[str, Any]) -> None:
    assert_versioned_fields(data, "Valuation")
    assert data["variant"] in ("ORIGINATION", "RECOVERY_LIQUIDATION")
    assert data["status"] in ("DRAFT", "CERTIFIED", "SUPERSEDED")
    assert data["location_key"] in (
        "COMMUNITY_WITH_AGREEMENT",
        "COMMUNITY_WITHOUT_AGREEMENT",
        "PRIVATE_LAND",
    )
    assert isinstance(data["valuation_year"], int)
    assert_integer_cents(
        data,
        "book_base_cents",
        "condition_adjustment_cents",
        "location_adjustment_cents",
        "installation_adjustment_cents",
        "forced_sale_discount_cents",
        "detach_and_move_cost_cents",
        "certified_value_cents",
    )
    assert data["certified_value_cents"] >= 0, (
        "certified_value_cents is floored at zero"
    )
    if data["status"] == "DRAFT":
        assert data["certified_by_user_id"] is None
        assert data["certified_at"] is None


def assert_loan(data: Dict[str, Any]) -> None:
    assert_versioned_fields(data, "Loan")
    assert data["underwriting_state"] in (
        "DRAFT",
        "UNDERWRITING",
        "APPROVED",
        "FUNDED",
        "DECLINED",
    )
    assert data["servicing_state"] in (
        "NOT_SERVICING",
        "CURRENT",
        "DELINQUENT",
        "DEFAULT",
        "RECOVERY",
        "PAID_OFF",
        "CHARGED_OFF",
    )
    assert data["perfection_state"] in (
        "UNPERFECTED",
        "FILING_SUBMITTED",
        "PERFECTED",
        "RE_PERFECTION_REQUIRED",
        "RELEASED",
    )
    assert data["insurance_compliance"] in ("UNKNOWN", "COMPLIANT", "NON_COMPLIANT")
    assert data["collateral_classification"] in ("PERSONAL_PROPERTY", "REAL_PROPERTY")
    assert data["placement_type"] in ("COMMUNITY", "PRIVATE_LAND")
    assert data["principal_cents"] > 0
    assert data["requested_term_months"] > 0
    assert_integer_cents(
        data,
        "principal_cents",
        "principal_balance_cents",
        "interest_accrued_unpaid_cents",
        "fees_outstanding_cents",
        "force_placed_premium_outstanding_cents",
        "escrow_balance_cents",
        "escrow_target_cents",
    )
    assert data["lot_rent_state"] in ("CURRENT", "DELINQUENT", "EVICTION_FILED")
    assert data["lot_rent_months_delinquent"] >= 0
    assert data["delinquent_days"] >= 0


def assert_lien_filing(data: Dict[str, Any]) -> None:
    assert_versioned_fields(data, "LienFiling")
    assert data["filing_type"] in ("TITLE_LIEN", "LAND_HOME_DEED_OF_TRUST")
    assert data["status"] in ("SUBMITTED", "RECORDED", "REJECTED", "RELEASED")
    assert isinstance(data["submitted_documents"], list)
    assert isinstance(data["missing_documents"], list)
    assert data["attempt_number"] >= 1
    assert is_valid_uuid(data["loan_id"])
    assert is_valid_uuid(data["unit_id"])
    if data["rejection_code"] is not None:
        assert data["rejection_code"] in (
            "MISSING_DOCUMENT",
            "NAME_MISMATCH",
            "FEE_SHORTFALL",
        )


def assert_insurance_policy(data: Dict[str, Any]) -> None:
    assert_versioned_fields(data, "InsurancePolicy")
    assert data["source"] in ("BORROWER_PROVIDED", "FORCE_PLACED")
    assert data["status"] in ("ACTIVE", "LAPSED", "CANCELLED", "SUPERSEDED")
    assert data["compliance_state"] in (
        "COMPLIANT",
        "DEFICIENT_WIND",
        "DEFICIENT_COVERAGE",
    )
    assert isinstance(data["wind_endorsement"], bool)
    assert_integer_cents(
        data,
        "dwelling_coverage_cents",
        "wind_deductible_cents",
        "required_coverage_cents",
        "premium_cents",
        "unearned_premium_refund_cents",
    )
    assert data["coverage_days"] > 0, (
        "expiry_date must be strictly after effective_date, so coverage_days is positive"
    )
    assert is_iso8601_timestamp(data["effective_date"])
    assert is_iso8601_timestamp(data["expiry_date"])


def assert_payment_transaction(data: Dict[str, Any]) -> None:
    """A payment row is an accounting row: only id and created_at, never versioned."""
    assert_immutable_entity_fields(data, "PaymentTransaction")
    assert data["payment_kind"] in ("SCHEDULED", "PARTIAL", "PAYOFF", "REVERSAL")
    assert data["allocation_variant"] in (
        "CHATTEL_CONTRACT_ORDER",
        "REAL_PROPERTY_ESCROW_FIRST",
    )
    assert isinstance(data["reversed"], bool)
    assert_integer_cents(
        data,
        "amount_cents",
        "accrued_interest_at_posting_cents",
        "to_interest_cents",
        "to_fees_cents",
        "to_force_placed_cents",
        "to_escrow_cents",
        "to_principal_cents",
    )
    assert isinstance(data["accrual_days"], int)
    assert is_iso8601_timestamp(data["posted_at"])


def assert_recovery_case(data: Dict[str, Any]) -> None:
    assert_versioned_fields(data, "RecoveryCase")
    assert data["path"] in ("REPOSSESSION", "FORECLOSURE")
    assert data["status"] in (
        "OPENED",
        "REPO_NOTICE_ISSUED",
        "REDEMPTION_WINDOW",
        "POSSESSION_OBTAINED",
        "REFURBISHING",
        "REMARKETING",
        "CLOSED_REDEEMED",
        "CLOSED_DEFICIENCY",
        "CLOSED_SURPLUS",
        "CLOSED_SETTLED",
    )
    assert is_valid_uuid(data["loan_id"])
    assert isinstance(data["refurbishment_line_items"], list)
    assert_integer_cents(data, "recovery_expense_cents", "refurbishment_cost_cents")


# ─── Domain invariants ────────────────────────────────

def assert_allocation_sums_to_amount(payment: Dict[str, Any]) -> None:
    """The five allocation buckets account for the whole posted amount."""
    allocated = (
        payment["to_interest_cents"]
        + payment["to_fees_cents"]
        + payment["to_force_placed_cents"]
        + payment["to_escrow_cents"]
        + payment["to_principal_cents"]
    )
    assert allocated == payment["amount_cents"], (
        f"allocation buckets sum to {allocated} but amount_cents is "
        f"{payment['amount_cents']}"
    )


def assert_reversal_negates(original: Dict[str, Any], reversal: Dict[str, Any]) -> None:
    """A reversal row's five allocation fields are the exact negatives of the original."""
    assert reversal["payment_kind"] == "REVERSAL"
    assert reversal["reverses_payment_id"] == original["id"]
    assert reversal["amount_cents"] == -original["amount_cents"]
    for field in (
        "to_interest_cents",
        "to_fees_cents",
        "to_force_placed_cents",
        "to_escrow_cents",
        "to_principal_cents",
    ):
        assert reversal[field] == -original[field], (
            f"reversal {field} must be {-original[field]}, got {reversal[field]}"
        )


def total_obligation_cents(loan: Dict[str, Any]) -> int:
    """principal + interest + fees + force-placed premium, less escrow held."""
    return (
        loan["principal_balance_cents"]
        + loan["interest_accrued_unpaid_cents"]
        + loan["fees_outstanding_cents"]
        + loan["force_placed_premium_outstanding_cents"]
        - loan["escrow_balance_cents"]
    )


def assert_obligation_buckets_zeroed(loan: Dict[str, Any]) -> None:
    """All four obligation buckets are zero."""
    for field in (
        "principal_balance_cents",
        "interest_accrued_unpaid_cents",
        "fees_outstanding_cents",
        "force_placed_premium_outstanding_cents",
    ):
        assert loan[field] == 0, f"{field} must be zeroed, got {loan[field]}"


def assert_valuation_breakdown(
    valuation: Dict[str, Any],
    book_base_cents: int,
    condition_adjustment_cents: int,
    location_adjustment_cents: int,
    installation_adjustment_cents: int,
    forced_sale_discount_cents: int,
    detach_and_move_cost_cents: int,
    certified_value_cents: int,
) -> None:
    """Assert every pinned figure of the guide walk on one valuation row."""
    assert valuation["book_base_cents"] == book_base_cents, (
        f"book_base_cents expected {book_base_cents}, got {valuation['book_base_cents']}"
    )
    assert valuation["condition_adjustment_cents"] == condition_adjustment_cents
    assert valuation["location_adjustment_cents"] == location_adjustment_cents
    assert valuation["installation_adjustment_cents"] == installation_adjustment_cents
    assert valuation["forced_sale_discount_cents"] == forced_sale_discount_cents
    assert valuation["detach_and_move_cost_cents"] == detach_and_move_cost_cents
    assert valuation["certified_value_cents"] == certified_value_cents, (
        f"certified_value_cents expected {certified_value_cents}, "
        f"got {valuation['certified_value_cents']}"
    )
