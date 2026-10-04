"""Entity assertions and domain invariant checkers.

Every assertion inspects only fields the PRD's prose commits to returning;
system-managed fields (`id`, `created_at`, `updated_at`, `version`) are checked
for shape, not values.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: Dict[str, Any], entity: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an int"


def assert_retailer(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Retailer")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["store_type"] in ("BRICK_AND_MORTAR", "ONLINE", "HYBRID")
    assert data["storefront_proof_status"] in ("PENDING", "CONFIRMED", "REJECTED")
    assert data["resale_cert_status"] in ("PENDING", "CONFIRMED", "REJECTED")
    assert data["verification_status"] in (
        "PENDING", "MORE_INFO_REQUESTED", "VERIFIED", "REJECTED", "SUSPENDED",
    )
    assert isinstance(data["verification_resubmission_count"], int)
    assert isinstance(data["return_rate"], (int, float))
    assert 0 <= data["return_rate"] <= 1


def assert_brand(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Brand")
    assert isinstance(data["name"], str) and data["name"]
    assert data["onboarding_status"] in ("DRAFT", "ACTIVE", "SUSPENDED")
    assert isinstance(data["min_order_value_cents"], int)
    assert isinstance(data["default_case_pack_size"], int)
    assert isinstance(data["lead_time_days"], int)
    assert isinstance(data["payout_delay_days"], int)
    assert isinstance(data["referral_code"], str)
    assert isinstance(data["payout_balance_cents"], int)
    assert isinstance(data["abuse_flags"], int)


def assert_credit_account(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "CreditAccount")
    assert is_valid_uuid(data["retailer_id"])
    assert isinstance(data["limit_cents"], int)
    assert isinstance(data["available_cents"], int)
    assert data["status"] in ("ACTIVE", "FROZEN", "CLOSED")


def assert_order(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Order")
    assert is_valid_uuid(data["retailer_id"])
    assert is_valid_uuid(data["brand_id"])
    assert data["attribution"] in ("MARKETPLACE", "BRAND_REFERRED")
    assert isinstance(data["order_seq"], int) and data["order_seq"] >= 1
    assert isinstance(data["subtotal_cents"], int)
    assert data["status"] in (
        "PLACED", "SHIPPED", "DELIVERED", "PARTIALLY_RETURNED", "RETURNED",
        "CANCELLED",
    )


def assert_order_line(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "OrderLine")
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["sku"], str)
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["qty"], int)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["net_sold_qty"], int)


def assert_invoice(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Invoice")
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["amount_due_cents"], int)
    assert data["amount_due_cents"] >= 0
    assert is_iso8601_timestamp(data["due_date"])
    assert isinstance(data["paid_amount_cents"], int)
    assert isinstance(data["balance_cents"], int)
    assert data["status"] in ("OPEN", "PAID", "OVERDUE", "WRITTEN_OFF")


def assert_invoice_invariants(data: Dict[str, Any]) -> None:
    """balance_cents == amount_due_cents - paid_amount_cents always holds."""
    assert data["balance_cents"] == data["amount_due_cents"] - data["paid_amount_cents"], (
        f"invoice balance invariant violated: {data['balance_cents']} != "
        f"{data['amount_due_cents']} - {data['paid_amount_cents']}"
    )


def assert_payment(data: Dict[str, Any]) -> None:
    assert is_valid_uuid(data.get("id", "")), "Payment.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "Payment.created_at must be ISO 8601"
    )
    assert is_valid_uuid(data["invoice_id"])
    assert isinstance(data["amount_cents"], int)
    assert is_iso8601_timestamp(data["paid_at"])
    # Payment is the one resource that carries neither updated_at nor version.
    assert "updated_at" not in data, "Payment must not carry updated_at"
    assert "version" not in data, "Payment must not carry version"


def assert_return_authorization(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "ReturnAuthorization")
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["is_opening_order"], bool)
    assert isinstance(data["return_fee_cents"], int)
    assert isinstance(data["credit_cents"], int)
    assert data["status"] in ("REQUESTED", "APPROVED", "REJECTED", "RECEIVED")


def assert_return_line(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "ReturnLine")
    assert is_valid_uuid(data["return_auth_id"])
    assert is_valid_uuid(data["order_line_id"])
    assert isinstance(data["qty"], int)


def assert_payout(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Payout")
    assert is_valid_uuid(data["brand_id"])
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["commission_bps"], int)
    assert isinstance(data["commission_cents"], int)
    assert isinstance(data["net_cents"], int)
    assert data["net_cents"] == data["gross_cents"] - data["commission_cents"], (
        "net_cents must equal gross_cents - commission_cents"
    )
    assert is_iso8601_timestamp(data["scheduled_date"])
    assert data["status"] in ("SCHEDULED", "PROCESSING", "PAID", "FAILED")


def assert_exclusivity_grant(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "ExclusivityGrant")
    assert is_valid_uuid(data["brand_id"])
    assert is_valid_uuid(data["retailer_id"])
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert data["status"] in ("ACTIVE", "REVOKED", "EXPIRED")


def assert_fraud_flag(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "FraudFlag")
    assert is_valid_uuid(data["retailer_id"])
    assert data["flag_type"] in (
        "STRAW_STOREFRONT", "CONSUMER_RESELLER", "RETURN_ABUSE",
    )
    assert data["status"] in ("OPEN", "CONFIRMED", "DISMISSED")
