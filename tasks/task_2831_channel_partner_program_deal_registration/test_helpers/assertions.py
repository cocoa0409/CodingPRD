"""Entity assertions and program invariant checkers for the channel partner program."""

from typing import Optional

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

PARTNER_TYPES = ["DISTRIBUTOR", "RESELLER"]
PARTNER_TIERS = ["REGISTERED", "SILVER", "GOLD", "PLATINUM"]
TIER_STATUSES = ["COMPLIANT", "PROBATION", "SUSPENDED"]
ENTITLEMENT_LEVELS = ["BASIC", "STANDARD", "PREMIUM", "ELITE"]
CERT_TRACKS = ["SALES_PRO", "TECH_ASSOCIATE", "TECH_EXPERT"]
CERT_STATUSES = ["ACTIVE", "EXPIRED"]
REGION_CODES = ["NA", "EMEA", "APAC"]
COVERAGE_STATES = ["OPEN_CHANNEL", "CHANNEL_PROTECTED", "NAMED_DIRECT", "DIRECT_LOCKED"]
PRODUCT_LINES = ["PLATFORM_SUITE", "ANALYTICS_ADDON", "SUPPORT_SERVICES"]
EXCLUSIVITY_SCOPES = ["FULL", "PRODUCT_LINE"]
MAPPING_STATUSES = ["PROPOSED", "COUNTERED", "ACTIVE", "TERMINATED", "EXPIRED"]
REGISTRATION_STATUSES = [
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "CHANGES_REQUESTED",
    "APPROVED",
    "CONFLICT_HELD",
    "REJECTED",
    "EXPIRED",
    "SUPERSEDED",
    "CONVERTED",
]
CONFLICT_TYPES = ["PARTNER_VS_PARTNER", "PARTNER_VS_DIRECT"]
CONFLICT_STATUSES = [
    "OPEN",
    "ESCALATED_TIER1",
    "ESCALATED_TIER2",
    "RESOLVED_PARTNER",
    "RESOLVED_DIRECT",
    "RESOLVED_SPLIT",
]
RECOMMENDATION_LABELS = ["GRANT_SUBJECT", "GRANT_COUNTER", "RELEASE_TO_DIRECT", "DISMISS"]
APPLIED_VARIANTS = ["REGISTRATION_FIRST", "COVERAGE_FIRST"]
SPR_STATUSES = ["SUBMITTED", "APPROVED", "PARTIALLY_APPROVED", "DENIED", "SUPERSEDED"]
ALLOCATION_STATUSES = ["OPEN", "CLOSED"]
ACTIVITY_TYPES = ["EVENT", "DIGITAL_CAMPAIGN", "CONTENT_SYNDICATION"]
VALIDATION_STATES = ["SUBMITTED", "PROOF_REQUESTED", "VALIDATED", "REJECTED"]
SETTLEMENT_STATES = ["UNPAID", "APPROVED_FOR_PAYMENT", "PAID", "WRITTEN_OFF"]
PROOF_DOC_TYPES = ["INVOICE", "ATTENDEE_LIST", "SCREENSHOT", "LEAD_REPORT"]
ORDER_TYPES = ["STOCKING", "DROP_SHIP"]
VOLUME_BANDS = ["NONE", "MID", "HIGH"]
INVOICE_STATUSES = ["PENDING", "INVOICED", "CREDITED"]
REVIEW_STATUSES = ["PREPARED", "FINDINGS_OPEN", "REMEDIATED", "APPROVED", "REJECTED"]


# ---------------------------------------------------------------- shared shape


def assert_common_fields(data: dict, entity_label: str = "resource") -> None:
    """Every resource type exposes a bare UUID id, ISO-8601 timestamps and an integer version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a bare UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_label}.created_at must be an ISO-8601 UTC instant"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_label}.updated_at must be an ISO-8601 UTC instant"
    assert isinstance(data.get("version"), int), f"{entity_label}.version must be an integer"
    assert data["version"] >= 1, f"{entity_label}.version starts at 1"


def assert_nullable_instant(value, field_label: str) -> None:
    if value is not None:
        assert is_iso8601_timestamp(value), f"{field_label} must be an ISO-8601 UTC instant"


# ---------------------------------------------------------------- per entity


def assert_partner(data: dict) -> None:
    assert_common_fields(data, "Partner")
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert data["partner_type"] in PARTNER_TYPES
    assert data["tier"] in PARTNER_TIERS
    assert data["tier_status"] in TIER_STATUSES
    assert isinstance(data["marketing_commitment_cents"], int)
    assert data["marketing_commitment_cents"] >= 0
    assert isinstance(data["cert_credit_total"], int) and data["cert_credit_total"] >= 0
    assert isinstance(data["trailing_revenue_cents"], int) and data["trailing_revenue_cents"] >= 0
    assert isinstance(data["marketing_qualified_spend_cents"], int)
    assert data["marketing_qualified_spend_cents"] >= 0
    assert isinstance(data["marketing_attainment_pct"], (int, float))
    assert 0.0 <= data["marketing_attainment_pct"] <= 1.0
    assert data["portal_entitlement_level"] in ENTITLEMENT_LEVELS
    assert isinstance(data["open_conflict_count"], int) and data["open_conflict_count"] >= 0


def assert_certification_record(data: dict) -> None:
    assert_common_fields(data, "CertificationRecord")
    assert is_valid_uuid(data["partner_id"])
    assert isinstance(data["engineer_name"], str) and data["engineer_name"]
    assert data["track"] in CERT_TRACKS
    assert isinstance(data["credit_weight"], int) and data["credit_weight"] >= 1
    assert data["status"] in CERT_STATUSES
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["expires_at"])


def assert_account(data: dict) -> None:
    assert_common_fields(data, "Account")
    assert isinstance(data["account_name"], str) and data["account_name"]
    assert data["region_code"] in REGION_CODES
    assert data["coverage_state"] in COVERAGE_STATES
    assert_nullable_instant(data.get("protected_until"), "Account.protected_until")
    assert_nullable_instant(
        data.get("direct_pursuit_declared_at"), "Account.direct_pursuit_declared_at"
    )
    if data.get("protected_product_line") is not None:
        assert data["protected_product_line"] in PRODUCT_LINES


def assert_account_mapping(data: dict) -> None:
    assert_common_fields(data, "AccountMapping")
    assert is_valid_uuid(data["partner_id"])
    assert is_valid_uuid(data["account_id"])
    assert data["product_line"] in PRODUCT_LINES
    assert data["exclusivity_scope"] in EXCLUSIVITY_SCOPES
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_until"])
    assert data["mapping_status"] in MAPPING_STATUSES
    assert isinstance(data["counter_round"], int) and data["counter_round"] >= 0
    assert_nullable_instant(data.get("activated_at"), "AccountMapping.activated_at")


def assert_deal_registration(data: dict) -> None:
    assert_common_fields(data, "DealRegistration")
    assert is_valid_uuid(data["partner_id"])
    assert is_valid_uuid(data["account_id"])
    assert data["product_line"] in PRODUCT_LINES
    assert isinstance(data["expected_amount_cents"], int) and data["expected_amount_cents"] > 0
    assert is_iso8601_timestamp(data["expected_close_date"])
    assert data["status"] in REGISTRATION_STATUSES
    assert_nullable_instant(data.get("submitted_at"), "DealRegistration.submitted_at")
    assert_nullable_instant(data.get("approved_at"), "DealRegistration.approved_at")
    assert_nullable_instant(
        data.get("exclusivity_start_at"), "DealRegistration.exclusivity_start_at"
    )
    assert_nullable_instant(data.get("exclusivity_end_at"), "DealRegistration.exclusivity_end_at")
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    assert isinstance(data["registration_margin_uplift_pct"], (int, float))


def assert_conflict_case(data: dict) -> None:
    assert_common_fields(data, "ConflictCase")
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["subject_registration_id"])
    assert data["conflict_type"] in CONFLICT_TYPES
    assert data["status"] in CONFLICT_STATUSES
    assert is_iso8601_timestamp(data["detected_at"])
    assert isinstance(data["escalation_level"], int) and 0 <= data["escalation_level"] <= 2
    assert data["applied_variant"] in APPLIED_VARIANTS
    assert data["recommended_resolution"] in RECOMMENDATION_LABELS
    assert data["recommended_resolution_registration_first"] in RECOMMENDATION_LABELS
    assert data["recommended_resolution_coverage_first"] in RECOMMENDATION_LABELS


def assert_special_pricing_request(data: dict) -> None:
    assert_common_fields(data, "SpecialPricingRequest")
    assert is_valid_uuid(data["registration_id"])
    assert isinstance(data["requested_extra_margin_pct"], (int, float))
    assert isinstance(data["justification"], str) and data["justification"]
    assert data["status"] in SPR_STATUSES
    assert is_iso8601_timestamp(data["expires_at"])


def assert_mdf_allocation(data: dict) -> None:
    assert_common_fields(data, "MdfAllocation")
    assert is_valid_uuid(data["partner_id"])
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    for money_field in (
        "basis_revenue_cents",
        "allocated_cents",
        "committed_cents",
        "paid_cents",
        "expired_cents",
        "available_cents",
    ):
        assert isinstance(data[money_field], int), f"MdfAllocation.{money_field} must be cents"
        assert data[money_field] >= 0, f"MdfAllocation.{money_field} must not go negative"
    assert data["status"] in ALLOCATION_STATUSES
    assert_nullable_instant(data.get("closed_at"), "MdfAllocation.closed_at")
    assert_mdf_fund_conservation(data)


def assert_mdf_claim(data: dict) -> None:
    assert_common_fields(data, "MdfClaim")
    assert is_valid_uuid(data["allocation_id"])
    assert data["activity_type"] in ACTIVITY_TYPES
    assert isinstance(data["requested_cents"], int) and data["requested_cents"] > 0
    assert data["validation_state"] in VALIDATION_STATES
    assert data["settlement_state"] in SETTLEMENT_STATES
    assert isinstance(data["proof_round"], int) and 0 <= data["proof_round"] <= 2
    if data.get("matched_total_cents") is not None:
        assert isinstance(data["matched_total_cents"], int)
    if data.get("approved_cents") is not None:
        assert isinstance(data["approved_cents"], int)


def assert_proof_of_performance(data: dict) -> None:
    assert_common_fields(data, "ProofOfPerformance")
    assert is_valid_uuid(data["claim_id"])
    assert data["doc_type"] in PROOF_DOC_TYPES
    assert isinstance(data["spend_amount_cents"], int) and data["spend_amount_cents"] > 0
    assert isinstance(data["verified"], bool)
    assert_nullable_instant(data.get("verified_at"), "ProofOfPerformance.verified_at")


def assert_order_invoice(data: dict) -> None:
    assert_common_fields(data, "OrderInvoice")
    assert is_valid_uuid(data["partner_id"])
    assert data["order_type"] in ORDER_TYPES
    assert isinstance(data["list_amount_cents"], int) and data["list_amount_cents"] > 0
    assert isinstance(data["margin_pct"], (int, float))
    assert data["volume_band"] in VOLUME_BANDS
    assert isinstance(data["invoice_amount_cents"], int)
    assert isinstance(data["margin_value_cents"], int)
    assert isinstance(data["credit_memo_cents"], int) and data["credit_memo_cents"] >= 0
    assert data["status"] in INVOICE_STATUSES
    assert_nullable_instant(data.get("invoiced_at"), "OrderInvoice.invoiced_at")
    assert_order_invoice_margin_conservation(data)


def assert_performance_review(data: dict) -> None:
    assert_common_fields(data, "PerformanceReview")
    assert is_valid_uuid(data["partner_id"])
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert isinstance(data["findings_count"], int) and data["findings_count"] >= 0
    assert_nullable_instant(data.get("remediation_due_at"), "PerformanceReview.remediation_due_at")
    assert isinstance(data["provisional_cert_credit"], int)
    assert isinstance(data["provisional_revenue_cents"], int)
    assert isinstance(data["provisional_score"], (int, float))
    assert data["recommended_tier"] in PARTNER_TIERS
    assert data["status"] in REVIEW_STATUSES
    if data.get("approved_tier") is not None:
        assert data["approved_tier"] in PARTNER_TIERS


# ---------------------------------------------------------------- invariants


def assert_mdf_fund_conservation(allocation: dict) -> None:
    """allocated_cents == committed_cents + paid_cents + expired_cents + available_cents."""
    total = (
        allocation["committed_cents"]
        + allocation["paid_cents"]
        + allocation["expired_cents"]
        + allocation["available_cents"]
    )
    assert allocation["allocated_cents"] == total, (
        "fund buckets must sum to allocated_cents: "
        f"{allocation['allocated_cents']} != {total}"
    )


def assert_order_invoice_margin_conservation(invoice: dict) -> None:
    """list_amount_cents == invoice_amount_cents + margin_value_cents."""
    total = invoice["invoice_amount_cents"] + invoice["margin_value_cents"]
    assert invoice["list_amount_cents"] == total, (
        "invoice decomposition must hold exactly: "
        f"{invoice['list_amount_cents']} != {invoice['invoice_amount_cents']} "
        f"+ {invoice['margin_value_cents']}"
    )


def assert_rate_precision(value: float, decimal_places: int = 4) -> None:
    """Margin and attainment fractions are carried to a fixed number of decimal places."""
    assert round(value, decimal_places) == pytest.approx(value, abs=1e-9), (
        f"rate {value} carries more than {decimal_places} decimal places"
    )


def assert_score_precision(value: float) -> None:
    """Weighted program scores are rounded once to two decimal places."""
    assert round(value, 2) == pytest.approx(value, abs=1e-9), (
        f"score {value} carries more than two decimal places"
    )


def assert_exclusivity_window(
    registration: dict, expected_start: str, expected_end: str, expected_days: int
) -> None:
    assert registration["exclusivity_start_at"] == expected_start
    assert registration["exclusivity_end_at"] == expected_end
    assert registration["protection_days"] == expected_days


def assert_account_unprotected(account: dict) -> None:
    """A released account carries no protection fields at all."""
    assert account["protected_until"] is None
    assert account["protected_partner_id"] is None
    assert account["protected_product_line"] is None


def assert_paging_meta(meta: dict, limit: int, offset: int, total_count: int, has_more: bool) -> None:
    assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, f"expected has_more {has_more}, got {meta['has_more']}"


def assert_created_at_ascending(rows: list) -> None:
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows must be ordered by created_at ascending: {stamps}"
