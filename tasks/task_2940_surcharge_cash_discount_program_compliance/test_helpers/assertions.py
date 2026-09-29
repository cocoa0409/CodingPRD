"""Entity assertions and domain invariant checkers."""
import re
from datetime import datetime, timezone

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
)

_THREE_DIGIT_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant into a timezone-aware datetime."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_three_fractional_digits(value: str, field: str = "timestamp"):
    """Every persisted instant is rendered with exactly three fractional-second
    digits and a trailing Z."""
    assert _THREE_DIGIT_UTC.match(value or ""), (
        f"{field} must be an ISO 8601 UTC instant with exactly three fractional digits, got {value!r}"
    )


def assert_instant_equals(actual: str, expected: str, field: str = "timestamp"):
    """Assert a rendered instant both carries the mandated rendering and denotes
    the expected point in time."""
    assert_three_fractional_digits(actual, field)
    assert parse_instant(actual) == parse_instant(expected), (
        f"Expected {field} {expected}, got {actual}"
    )


def assert_days_apart(later: str, earlier: str, days: int, field: str = "interval"):
    """Day arithmetic in this service is exact multiples of 24 hours."""
    delta = parse_instant(later) - parse_instant(earlier)
    assert delta.total_seconds() == days * 86_400, (
        f"Expected {field} of exactly {days} days ({days * 86400} seconds), got {delta}"
    )


def assert_common_fields(data: dict, entity: str = "resource"):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert_three_fractional_digits(data.get("created_at", ""), f"{entity}.created_at")
    assert_three_fractional_digits(data.get("updated_at", ""), f"{entity}.updated_at")
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version starts at 1, got {data['version']}"


def assert_pct_precision(value, field: str = "percentage"):
    """Percentages are carried to four decimal places."""
    assert isinstance(value, (int, float)), f"{field} must be numeric, got {value!r}"
    assert round(float(value), 4) == float(value), (
        f"{field} must carry at most four decimal places, got {value!r}"
    )


def assert_score_precision(value, field: str = "exposure score"):
    """Exposure scores are carried to two decimal places and capped at 100."""
    assert isinstance(value, (int, float)), f"{field} must be numeric, got {value!r}"
    assert round(float(value), 2) == float(value), (
        f"{field} must carry at most two decimal places, got {value!r}"
    )
    assert 0 <= float(value) <= 100, f"{field} must lie within 0..100, got {value!r}"


def assert_jurisdiction(data: dict):
    assert_common_fields(data, "Jurisdiction")
    assert re.match(r"^[A-Z]{2}$", data["state_code"]), "state_code is exactly two uppercase letters"
    assert isinstance(data["surcharge_permitted"], bool)
    if data["surcharge_permitted"]:
        assert data["surcharge_cap_pct"] is not None, (
            "surcharge_cap_pct is non-null whenever surcharge_permitted is true"
        )
        assert_pct_precision(data["surcharge_cap_pct"], "surcharge_cap_pct")
    else:
        assert data["surcharge_cap_pct"] is None, (
            "surcharge_cap_pct is null whenever surcharge_permitted is false"
        )
    assert isinstance(data["cash_discount_permitted"], bool)
    assert isinstance(data["price_posting_required"], bool)
    assert isinstance(data["disclosure_signage_required"], bool)
    assert isinstance(data["receipt_line_item_required"], bool)
    assert data["ag_enforcement_posture"] in ("PERMISSIVE", "MONITORED", "RESTRICTIVE")
    assert isinstance(data["law_change_count"], int) and data["law_change_count"] >= 0


def assert_merchant(data: dict):
    assert_common_fields(data, "Merchant")
    assert is_valid_uuid(data["jurisdiction_id"])
    assert 1 <= len(data["legal_name"]) <= 200
    assert re.match(r"^\d{4}$", str(data["mcc"])), "mcc is a four-digit code"
    for field in (
        "gross_surcharge_collected_cents",
        "net_surcharge_collected_cents",
        "enforcing_terminal_count",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents or an integer count"
        assert data[field] >= 0, f"{field} must be non-negative"


def assert_money_invariant(merchant: dict, issued_refund_total_cents: int):
    """For every merchant, the sum of net_surcharge_collected_cents and the total
    of that merchant's issued refunds equals gross_surcharge_collected_cents."""
    assert (
        merchant["net_surcharge_collected_cents"] + issued_refund_total_cents
        == merchant["gross_surcharge_collected_cents"]
    ), (
        "net_surcharge_collected_cents plus issued refunds must equal "
        f"gross_surcharge_collected_cents: {merchant}"
    )


def assert_cost_documentation(data: dict):
    assert_common_fields(data, "CostDocumentation")
    assert is_valid_uuid(data["merchant_id"])
    assert_pct_precision(data["base_mdr_pct"], "base_mdr_pct")
    assert_pct_precision(data["assessment_pct"], "assessment_pct")
    assert_pct_precision(data["documented_cost_pct"], "documented_cost_pct")
    assert isinstance(data["per_item_fee_cents"], int)
    assert isinstance(data["average_ticket_cents"], int)
    assert data["state"] in ("ACTIVE", "SUPERSEDED")
    assert_three_fractional_digits(data["effective_from"], "effective_from")


def assert_program(data: dict):
    assert_common_fields(data, "SurchargeProgram")
    assert is_valid_uuid(data["merchant_id"])
    assert is_valid_uuid(data["jurisdiction_id"])
    assert is_valid_uuid(data["cost_documentation_id"])
    assert data["program_type"] in ("SURCHARGE", "CASH_DISCOUNT")
    assert data["consistency_scope"] in ("BRAND_LEVEL", "PRODUCT_LEVEL")
    assert data["status"] in (
        "DRAFT",
        "PENDING_REGISTRATION",
        "ACTIVE",
        "SUSPENDED",
        "REMEDIATION",
        "DISABLED",
        "WITHDRAWN",
    )
    assert data["disable_reason"] in (
        "NONE",
        "JURISDICTION_PROHIBITION",
        "REGISTRATION_REVOKED",
        "REMEDIATION_ORDER",
        "OPERATOR_SUSPENSION",
    )
    assert_pct_precision(data["effective_cap_pct"], "effective_cap_pct")
    assert isinstance(data["disclosure_ready"], bool)
    assert_score_precision(data["network_exposure_score"], "network_exposure_score")
    assert_score_precision(data["ag_exposure_score"], "ag_exposure_score")
    if data["status"] == "ACTIVE":
        assert data["disable_reason"] == "NONE", (
            "every transition back into ACTIVE resets disable_reason to NONE"
        )


def assert_rate_rule(data: dict):
    assert_common_fields(data, "BrandRateRule")
    assert is_valid_uuid(data["program_id"])
    assert data["brand"] in ("VISA", "MASTERCARD", "DISCOVER", "AMEX")
    assert data["product_tier"] in ("ALL", "CONSUMER_CREDIT", "COMMERCIAL_CREDIT", "REWARDS_CREDIT")
    assert_pct_precision(data["rate_pct"], "rate_pct")
    assert 0 < float(data["rate_pct"]) <= 100
    assert parse_instant(data["effective_to"]) > parse_instant(data["effective_from"])


def assert_network_registration(data: dict):
    assert_common_fields(data, "NetworkRegistration")
    assert is_valid_uuid(data["program_id"])
    assert data["network"] in ("VISA", "MASTERCARD", "DISCOVER", "AMEX")
    assert 1 <= len(data["registration_ref"]) <= 64
    assert data["state"] in ("SUBMITTED", "ACKNOWLEDGED", "EFFECTIVE", "REJECTED", "REVOKED")
    assert isinstance(data["notice_days"], int)
    assert_three_fractional_digits(data["submitted_at"], "submitted_at")
    assert_three_fractional_digits(data["earliest_effective_at"], "earliest_effective_at")


def assert_disclosure_artifact(data: dict):
    assert_common_fields(data, "DisclosureArtifact")
    assert is_valid_uuid(data["program_id"])
    assert data["artifact_type"] in (
        "ENTRY_SIGNAGE",
        "POS_SIGNAGE",
        "RECEIPT_TEMPLATE",
        "PRICE_LIST_POSTING",
    )
    assert re.match(r"^[0-9a-f]{64}$", data["content_hash"]), (
        "content_hash must be exactly 64 lowercase hexadecimal characters"
    )
    assert data["state"] in ("DRAFT", "ATTESTED", "EXPIRED")
    assert data["expired_reason"] in ("NONE", "REMEDIATION_ORDER", "PROGRAM_WITHDRAWN")


def assert_terminal(data: dict):
    assert_common_fields(data, "Terminal")
    assert is_valid_uuid(data["merchant_id"])
    assert 1 <= len(data["serial_number"]) <= 40
    assert data["state"] in ("PROVISIONED", "CONFIGURED", "ENFORCING", "QUARANTINED", "DISABLED")
    assert isinstance(data["debit_exclusion_enabled"], bool)
    assert data["quarantine_reason"] in (
        "NONE",
        "OPERATOR_ACTION",
        "PROGRAM_SUSPENDED",
        "PROGRAM_DISABLED",
        "DISCLOSURE_EXPIRED",
    )


def assert_transaction(data: dict):
    """A captured sale carries id and created_at only: both updated_at and
    version are absent from its representation entirely."""
    assert is_valid_uuid(data.get("id", "")), "Transaction.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "Transaction.created_at must be ISO 8601"
    assert "updated_at" not in data, "Transaction must not carry updated_at"
    assert "version" not in data, "Transaction must not carry version"
    assert data["card_brand"] in ("VISA", "MASTERCARD", "DISCOVER", "AMEX")
    assert data["card_funding"] in ("CREDIT", "DEBIT", "PREPAID")
    assert data["product_tier"] in (
        "CONSUMER_CREDIT",
        "COMMERCIAL_CREDIT",
        "REWARDS_CREDIT",
        "NOT_APPLICABLE",
    )
    assert data["outcome"] in (
        "APPROVED_WITH_SURCHARGE",
        "APPROVED_NO_SURCHARGE",
        "APPROVED_CASH_DISCOUNT",
    )
    for field in (
        "base_amount_cents",
        "surcharge_amount_cents",
        "cash_discount_amount_cents",
        "cash_price_cents",
        "total_amount_cents",
        "refunded_surcharge_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be a whole number of cents"
    assert_three_fractional_digits(data["occurred_at"], "occurred_at")


def assert_complaint_case(data: dict):
    assert_common_fields(data, "ComplaintCase")
    assert is_valid_uuid(data["program_id"])
    assert data["source"] in ("NETWORK", "ATTORNEY_GENERAL", "CARDHOLDER")
    assert data["allegation_type"] in (
        "UNDISCLOSED_SURCHARGE",
        "DEBIT_SURCHARGED",
        "CAP_EXCEEDED",
        "MISSING_RECEIPT_LINE",
        "PROHIBITED_JURISDICTION",
        "PRICE_POSTING_MISSING",
    )
    assert data["investigation_state"] in ("OPEN", "UNDER_REVIEW", "SUBSTANTIATED", "DISMISSED")
    assert data["remediation_state"] in (
        "NONE",
        "PLAN_REQUIRED",
        "PLAN_SUBMITTED",
        "PLAN_ACCEPTED",
        "CLOSED",
    )
    assert isinstance(data["refund_total_cents"], int)
    assert_three_fractional_digits(data["received_at"], "received_at")
    assert_three_fractional_digits(data["response_due_at"], "response_due_at")


def assert_refund(data: dict):
    assert_common_fields(data, "RemediationRefund")
    assert is_valid_uuid(data["complaint_case_id"])
    assert is_valid_uuid(data["transaction_id"])
    assert isinstance(data["refund_amount_cents"], int) and data["refund_amount_cents"] >= 1
    assert data["state"] in ("PENDING", "ISSUED", "VOIDED")


def assert_terminal_census(merchant: dict, enforcing_terminals: int):
    """A merchant's enforcing_terminal_count always equals the number of that
    merchant's terminals currently in state ENFORCING."""
    assert merchant["enforcing_terminal_count"] == enforcing_terminals, (
        f"Expected enforcing_terminal_count {enforcing_terminals}, "
        f"got {merchant['enforcing_terminal_count']}"
    )


# --------------------------------------------------------------------------
# List-envelope helpers
# --------------------------------------------------------------------------
def list_page(response):
    """Validate a paginated list envelope and return the (items, meta) pair."""
    return validate_paginated(response)


def list_items(response) -> list:
    """The rows of one page of a list response."""
    items, _meta = validate_paginated(response)
    return items


def list_total(response) -> int:
    """The number of rows matching the filter before pagination is applied."""
    _items, meta = validate_paginated(response)
    return meta["total_count"]
