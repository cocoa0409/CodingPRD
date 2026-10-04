"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

MERCHANT_STATES = ["ONBOARDING", "ACTIVE", "SUSPENDED"]
STORE_STATES = ["ACTIVE", "CLOSED"]
POLICY_STATES = ["DRAFT", "ACTIVE", "ARCHIVED"]
OVERRIDE_EFFECTS = ["ALLOW", "DENY"]
QUOTE_STATES = ["ACTIVE", "CONSUMED", "EXPIRED"]
FULFILLMENT_STATES = [
    "QUOTED", "ACCEPTED", "READY_FOR_PICKUP", "PICKED_UP", "IN_TRANSIT",
    "DELIVERED", "UNDELIVERABLE", "RETURN_IN_PROGRESS", "RETURNED_TO_STORE",
    "DISPOSAL_PENDING", "DISPOSED", "CANCELLED",
]
BILLING_STATES = ["PENDING", "AUTHORIZED", "SETTLED", "REFUNDED", "VOIDED"]
COURIER_STATES = ["ACTIVE", "SUSPENDED"]
BATCH_STATES = ["COURIER_ASSIGNED", "DISPATCHED", "COMPLETED", "FAILED"]
TRACKING_EVENT_TYPES = [
    "ORDER_ACCEPTED", "COURIER_ASSIGNED", "PICKED_UP", "IN_TRANSIT",
    "DELIVERED", "UNDELIVERABLE", "RETURN_IN_PROGRESS", "RETURNED_TO_STORE",
    "DISPOSED", "CANCELLED", "NOTE",
]
TRACKING_VISIBILITIES = ["MERCHANT_VISIBLE", "INTERNAL_ONLY"]
DISPOSITION_RESOLUTIONS = ["RETURN_TO_STORE", "DISPOSE"]
DISPOSITION_STATES = ["PENDING", "COMPLETED"]
UNDELIVERABLE_REASONS = ["CUSTOMER_UNAVAILABLE", "ADDRESS_ISSUE", "DAMAGED_IN_TRANSIT"]
FAULT_CODES = [
    "COURIER_DELAY", "PLATFORM_OUTAGE", "MERCHANT_FULFILLMENT",
    "CUSTOMER_UNAVAILABLE", "ADDRESS_ISSUE",
]
CLAIM_STATES = [
    "FILED", "UNDER_REVIEW", "APPROVED", "DENIED", "APPEALED", "SETTLED", "REVERSED",
]
SLA_REPORT_STATES = ["OPEN", "FINALIZED"]
SERVICE_CREDIT_STATES = ["ACCRUED", "APPLIED", "VOIDED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_merchant(data: dict):
    _assert_common(data)
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("status") in MERCHANT_STATES
    assert isinstance(data.get("billing_balance_cents"), int)
    assert isinstance(data.get("credit_balance_cents"), int)
    assert isinstance(data.get("default_refund_split_merchant_pct"), int)
    assert 0 <= data["default_refund_split_merchant_pct"] <= 100
    assert isinstance(data.get("late_credit_enabled"), bool)


def assert_store(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("merchant_id", "")), "merchant_id must be a UUID"
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("address_text"), str)
    assert isinstance(data.get("lat"), (int, float))
    assert isinstance(data.get("lng"), (int, float))
    assert isinstance(data.get("delivery_radius_m"), int)
    assert isinstance(data.get("timezone"), str) and data["timezone"]
    assert data.get("status") in STORE_STATES


def assert_pricing_policy(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("merchant_id", "")), "merchant_id must be a UUID"
    assert isinstance(data.get("distance_bands"), list)
    assert isinstance(data.get("value_tiers"), list)
    assert isinstance(data.get("peak_windows"), list)
    assert isinstance(data.get("peak_uplift_pct"), (int, float))
    assert isinstance(data.get("surge_passthrough_pct"), (int, float))
    assert isinstance(data.get("effective_from"), str)
    assert isinstance(data.get("effective_until"), str)
    assert data.get("status") in POLICY_STATES


def assert_serviceability_override(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be a UUID"
    assert isinstance(data.get("address_pattern"), str)
    assert data.get("effect") in OVERRIDE_EFFECTS


def assert_quote(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("merchant_id", "")), "merchant_id must be a UUID"
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be a UUID"
    assert isinstance(data.get("order_value_cents"), int)
    assert isinstance(data.get("distance_m"), int)
    assert isinstance(data.get("band_fee_cents"), int)
    assert isinstance(data.get("value_surcharge_cents"), int)
    assert isinstance(data.get("peak_uplift_cents"), int)
    assert isinstance(data.get("surge_component_cents"), int)
    assert isinstance(data.get("quoted_fee_cents"), int)
    assert data.get("quoted_fee_cents") == (
        data["band_fee_cents"]
        + data["value_surcharge_cents"]
        + data["peak_uplift_cents"]
        + data["surge_component_cents"]
    ), "quoted_fee_cents must equal the sum of its four components"
    assert isinstance(data.get("quoted_surge_multiplier"), (int, float))
    assert isinstance(data.get("valid_until"), str)
    assert data.get("status") in QUOTE_STATES


def assert_delivery_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("quote_id", "")), "quote_id must be a UUID"
    assert is_valid_uuid(data.get("merchant_id", "")), "merchant_id must be a UUID"
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be a UUID"
    assert isinstance(data.get("customer_reference"), str)
    assert isinstance(data.get("idempotency_key"), str)
    assert data.get("fulfillment_status") in FULFILLMENT_STATES
    assert data.get("billing_status") in BILLING_STATES
    assert isinstance(data.get("quoted_fee_cents"), int)
    assert isinstance(data.get("late_credit_cents"), int)


def assert_courier(data: dict):
    _assert_common(data)
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("status") in COURIER_STATES
    assert isinstance(data.get("max_active_deliveries"), int)


def assert_delivery_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be a UUID"
    assert is_valid_uuid(data.get("courier_id", "")), "courier_id must be a UUID"
    assert isinstance(data.get("order_ids"), list)
    assert isinstance(data.get("dispatch_window_start"), str)
    assert isinstance(data.get("dispatch_window_end"), str)
    assert isinstance(data.get("courier_cost_cents"), int)
    assert data.get("status") in BATCH_STATES


def assert_tracking_event(data: dict):
    # Append-only: id + created_at; no updated_at / version fields at all.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only tracking event must not carry updated_at"
    assert "version" not in data, "append-only tracking event must not carry version"
    assert is_valid_uuid(data.get("delivery_order_id", "")), "delivery_order_id must be a UUID"
    assert data.get("event_type") in TRACKING_EVENT_TYPES
    assert data.get("visibility") in TRACKING_VISIBILITIES
    assert isinstance(data.get("occurred_at"), str)


def assert_disposition(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("delivery_order_id", "")), "delivery_order_id must be a UUID"
    assert data.get("resolution") in DISPOSITION_RESOLUTIONS
    assert isinstance(data.get("return_fee_cents"), int)
    assert data.get("status") in DISPOSITION_STATES


def assert_refund_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("delivery_order_id", "")), "delivery_order_id must be a UUID"
    assert is_valid_uuid(data.get("merchant_id", "")), "merchant_id must be a UUID"
    assert data.get("fault_code") in FAULT_CODES
    assert isinstance(data.get("claimed_amount_cents"), int)
    assert isinstance(data.get("appeal_count"), int)
    assert data.get("status") in CLAIM_STATES


def assert_sla_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("merchant_id", "")), "merchant_id must be a UUID"
    assert isinstance(data.get("period_start"), str)
    assert isinstance(data.get("period_end"), str)
    assert data.get("status") in SLA_REPORT_STATES


def assert_service_credit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("merchant_id", "")), "merchant_id must be a UUID"
    assert is_valid_uuid(data.get("sla_report_id", "")), "sla_report_id must be a UUID"
    assert is_valid_uuid(data.get("delivery_order_id", "")), "delivery_order_id must be a UUID"
    assert isinstance(data.get("amount_cents"), int)
    assert data.get("reason") == "LATE_DELIVERY"
    assert data.get("status") in SERVICE_CREDIT_STATES


def assert_claim_share_invariant(claim: dict):
    """The two liability shares always sum exactly to the claimed amount."""
    if claim.get("merchant_share_cents") is not None:
        assert claim["merchant_share_cents"] + claim["platform_share_cents"] == (
            claim["claimed_amount_cents"]
        ), "merchant_share + platform_share must equal claimed_amount_cents"
