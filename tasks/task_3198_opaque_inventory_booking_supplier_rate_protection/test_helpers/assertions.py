"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

VALID_SUPPLIER_STATUSES = ["ACTIVE", "SUSPENDED", "TERMINATED"]
VALID_RATE_WINDOW_STATUSES = ["OPEN", "EXHAUSTED", "CLOSED"]
VALID_FRAUD_STATUSES = ["CLEAR", "WATCH", "BLOCKED"]
VALID_OFFER_MODES = ["BID", "FIXED"]
VALID_BID_STATUSES = ["PENDING", "ACCEPTED", "REJECTED", "EXPIRED", "WITHDRAWN"]
VALID_PAYMENT_STATUSES = ["CAPTURED", "REFUNDED", "PARTIALLY_REFUNDED"]
VALID_FULFILLMENT_STATUSES = ["CONFIRMED", "SERVICE_FAILED", "SETTLED"]
VALID_COMPLAINT_CATEGORIES = [
    "PROPERTY_MISREPRESENTED", "SERVICE_FAILURE", "DISSATISFIED_REVEAL", "OTHER",
]
VALID_COMPLAINT_RESOLUTIONS = ["NONE", "GOODWILL_CREDIT", "FULL_REFUND"]
VALID_COMPLAINT_STATUSES = ["OPEN", "UNDER_REVIEW", "RESOLVED", "REJECTED"]
VALID_BATCH_STATUSES = ["DRAFT", "APPROVED", "PAID", "VOIDED"]
VALID_FRAUD_REASON_CODES = ["ARBITRAGE_PATTERN", "REPEAT_WIN_RATE", "MANUAL_REVIEW"]
VALID_FRAUD_FLAG_STATUSES = ["OPEN", "UPHELD", "DISMISSED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be >= 1"


def assert_supplier(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["opaque_commission_pct"], (int, float))
    assert isinstance(data["parity_protection_enabled"], bool)
    assert isinstance(data["concealment_discount_min_pct"], (int, float))
    assert data["status"] in VALID_SUPPLIER_STATUSES


def assert_property(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("supplier_id", "")), "supplier_id must be a UUID"
    assert isinstance(data["brand_name"], str) and len(data["brand_name"]) > 0
    assert isinstance(data["star_rating"], int) and 1 <= data["star_rating"] <= 5
    assert isinstance(data["neighborhood_code"], str) and len(data["neighborhood_code"]) > 0
    assert isinstance(data["amenity_codes"], list)
    assert isinstance(data["published_rate_cents"], int) and data["published_rate_cents"] > 0


def assert_rate_window(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("property_id", "")), "property_id must be a UUID"
    assert isinstance(data["opaque_rate_cents"], int) and data["opaque_rate_cents"] > 0
    assert isinstance(data["rooms_allocated"], int) and data["rooms_allocated"] >= 1
    assert isinstance(data["rooms_sold"], int) and data["rooms_sold"] >= 0
    assert data["status"] in VALID_RATE_WINDOW_STATUSES


def assert_disclosure_zone(data: dict):
    _assert_common(data)
    assert isinstance(data["neighborhood_code"], str) and len(data["neighborhood_code"]) > 0
    assert isinstance(data["min_star_rating"], int)
    assert isinstance(data["revealed_amenity_codes"], list)


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["fraud_score"], int) and data["fraud_score"] >= 0
    assert data["fraud_status"] in VALID_FRAUD_STATUSES
    assert isinstance(data["opaque_win_count_30d"], int) and data["opaque_win_count_30d"] >= 0


def assert_opaque_bid(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert isinstance(data["neighborhood_code"], str)
    assert isinstance(data["min_star_rating"], int)
    assert data["offer_mode"] in VALID_OFFER_MODES
    assert data["status"] in VALID_BID_STATUSES


def assert_booking(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("opaque_bid_id", "")), "opaque_bid_id must be a UUID"
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert is_valid_uuid(data.get("property_id", "")), "property_id must be a UUID"
    assert is_valid_uuid(data.get("supplier_id", "")), "supplier_id must be a UUID"
    assert is_valid_uuid(data.get("rate_window_id", "")), "rate_window_id must be a UUID"
    assert isinstance(data["charged_price_cents"], int) and data["charged_price_cents"] > 0
    assert isinstance(data["supplier_remittance_cents"], int)
    assert isinstance(data["platform_commission_cents"], int)
    assert data["payment_status"] in VALID_PAYMENT_STATUSES
    assert data["fulfillment_status"] in VALID_FULFILLMENT_STATUSES


def assert_complaint_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("booking_id", "")), "booking_id must be a UUID"
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert data["category"] in VALID_COMPLAINT_CATEGORIES
    assert data["resolution"] in VALID_COMPLAINT_RESOLUTIONS
    assert data["status"] in VALID_COMPLAINT_STATUSES


def assert_settlement_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("supplier_id", "")), "supplier_id must be a UUID"
    assert isinstance(data["booking_ids"], list)
    assert isinstance(data["gross_remittance_cents"], int)
    assert isinstance(data["goodwill_deduction_cents"], int)
    assert isinstance(data["net_remittance_cents"], int)
    assert data["status"] in VALID_BATCH_STATUSES


def assert_fraud_flag(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert data["reason_code"] in VALID_FRAUD_REASON_CODES
    assert isinstance(data["score_delta"], int) and data["score_delta"] > 0
    assert data["status"] in VALID_FRAUD_FLAG_STATUSES


def assert_booking_remittance_sums(data: dict):
    """Remittance and commission always sum exactly to the charge (PRD §3.4)."""
    assert (
        data["supplier_remittance_cents"] + data["platform_commission_cents"]
        == data["charged_price_cents"]
    ), "supplier_remittance_cents + platform_commission_cents must equal charged_price_cents"
