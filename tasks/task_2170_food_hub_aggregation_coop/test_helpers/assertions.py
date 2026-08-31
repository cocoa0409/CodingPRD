"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import THRESHOLDS


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1"
    )


def assert_producer(data: dict):
    _assert_common_fields(data, "Producer")
    assert isinstance(data["legal_name"], str) and data["legal_name"].strip()
    assert isinstance(data["region_code"], str)
    assert "@" in data["contact_email"]
    assert data["onboarding_status"] in [
        "DRAFT",
        "SUBMITTED",
        "UNDER_REVIEW",
        "CHANGES_REQUESTED",
        "ACTIVE",
        "SUSPENDED",
        "TERMINATED",
    ]
    assert data["food_safety_tier"] in ["TIER_NONE", "TIER_BASIC", "TIER_AUDITED"]
    assert isinstance(data["compliance_ok"], bool)
    for field in (
        "review_cycles",
        "suspension_count",
        "paid_in_capital_cents",
        "voting_shares",
        "patronage_volume_cents",
        "shrink_charge_cents",
        "retained_patronage_cents",
    ):
        assert isinstance(data[field], int), f"Producer.{field} must be an integer"
        assert data[field] >= 0, f"Producer.{field} must not be negative"
    assert data["voting_shares"] <= THRESHOLDS["MAX_VOTING_SHARES"]


def assert_producer_document(data: dict):
    _assert_common_fields(data, "ProducerDocument")
    assert is_valid_uuid(data["producer_id"])
    assert data["doc_type"] in [
        "GAP_AUDIT",
        "LIABILITY_INSURANCE",
        "HACCP_PLAN",
        "ORGANIC_CERT",
        "WATER_TEST",
    ]
    assert is_iso8601_timestamp(data["issued_on"])
    assert is_iso8601_timestamp(data["expires_on"])
    assert data["status"] in [
        "SUBMITTED",
        "VERIFIED",
        "REJECTED",
        "EXPIRED",
        "SUPERSEDED",
    ]


def assert_product(data: dict):
    _assert_common_fields(data, "Product")
    assert is_valid_uuid(data["producer_id"])
    assert isinstance(data["commodity_code"], str) and data["commodity_code"]
    assert data["unit_of_measure"] in ["CASE", "LB", "EACH"]
    assert data["storage_class"] in ["AMBIENT", "CHILL", "FROZEN"]
    assert data["pack_weight_lb"] > 0
    assert data["units_per_pallet"] >= 1
    assert data["producer_unit_price_cents"] >= 1
    assert data["status"] in ["DRAFT", "LISTED", "DELISTED"]
    assert_product_availability(data)


def assert_product_availability(data: dict):
    """quantity_available is the offered quantity minus the committed quantity,
    floored at zero."""
    expected = max(0, data["quantity_offered"] - data["quantity_committed"])
    assert data["quantity_available"] == expected, (
        f"quantity_available should be max(0, {data['quantity_offered']} - "
        f"{data['quantity_committed']}) == {expected}, got {data['quantity_available']}"
    )


def assert_buyer(data: dict):
    _assert_common_fields(data, "Buyer")
    assert isinstance(data["legal_name"], str) and data["legal_name"].strip()
    assert data["buyer_type"] in [
        "SCHOOL_DISTRICT",
        "HOSPITAL",
        "UNIVERSITY",
        "CORRECTIONS",
    ]
    assert data["payment_terms_days"] in (15, 30, 45)
    assert data["credit_limit_cents"] >= 0
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_buyer_order(data: dict):
    _assert_common_fields(data, "BuyerOrder")
    assert is_valid_uuid(data["buyer_id"])
    assert data["fulfillment_status"] in [
        "DRAFT",
        "AGGREGATED",
        "SCHEDULED",
        "IN_TRANSIT",
        "DELIVERED",
        "CLOSED",
    ]
    assert data["settlement_status"] in [
        "UNBILLED",
        "INVOICED",
        "PARTIALLY_PAID",
        "PAID",
        "WRITTEN_OFF",
    ]
    for field in (
        "producer_subtotal_cents",
        "hub_margin_cents",
        "order_total_cents",
        "margin_tier_bp",
        "invoiced_total_cents",
        "paid_total_cents",
        "credit_memo_cents",
        "order_pallets",
    ):
        assert isinstance(data[field], int), f"BuyerOrder.{field} must be an integer"
    assert_order_total_identity(data)


def assert_order_total_identity(data: dict):
    """order_total_cents is producer_subtotal_cents plus hub_margin_cents."""
    assert (
        data["order_total_cents"]
        == data["producer_subtotal_cents"] + data["hub_margin_cents"]
    ), (
        "order_total_cents must equal producer_subtotal_cents + hub_margin_cents, "
        f"got {data['order_total_cents']} vs "
        f"{data['producer_subtotal_cents']} + {data['hub_margin_cents']}"
    )


def assert_order_line(data: dict):
    _assert_common_fields(data, "OrderLine")
    assert is_valid_uuid(data["order_id"])
    assert data["storage_class"] in ["AMBIENT", "CHILL", "FROZEN"]
    assert data["unit_of_measure"] in ["CASE", "LB", "EACH"]
    assert data["quantity_requested"] >= 1
    assert data["max_unit_price_cents"] >= 1
    assert data["status"] in ["PENDING", "ALLOCATED", "SHORT", "DELIVERED", "SETTLED"]
    assert (
        data["line_total_cents"]
        == data["line_producer_cents"] + data["line_margin_cents"]
    ), "line_total_cents must equal line_producer_cents + line_margin_cents"


def assert_allocation(data: dict):
    _assert_common_fields(data, "Allocation")
    assert is_valid_uuid(data["order_line_id"])
    assert is_valid_uuid(data["product_id"])
    assert data["quantity"] >= 1
    assert data["producer_unit_price_cents"] >= 1
    assert data["status"] in [
        "RESERVED",
        "STAGED",
        "DELIVERED",
        "SHORT_CLOSED",
        "REVERSED",
    ]
    assert isinstance(data["temp_excursion"], bool)
    assert_allocation_money_split(data)


def assert_allocation_money_split(data: dict):
    """buyer_amount_cents is the producer amount plus the hub margin."""
    assert (
        data["buyer_amount_cents"]
        == data["producer_amount_cents"] + data["hub_margin_cents"]
    ), (
        "buyer_amount_cents must equal producer_amount_cents + hub_margin_cents, "
        f"got {data['buyer_amount_cents']} vs "
        f"{data['producer_amount_cents']} + {data['hub_margin_cents']}"
    )


def assert_dock_slot(data: dict):
    _assert_common_fields(data, "DockSlot")
    assert data["storage_class"] in ["AMBIENT", "CHILL", "FROZEN"]
    assert data["pallet_capacity"] >= 1
    assert data["sanitation_buffer_minutes"] >= 0
    assert data["status"] in ["OPEN", "FULL", "CLOSED"]
    assert isinstance(data["pallets_booked"], int) and data["pallets_booked"] >= 0


def assert_dock_appointment(data: dict):
    _assert_common_fields(data, "DockAppointment")
    assert is_valid_uuid(data["dock_slot_id"])
    assert is_valid_uuid(data["producer_id"])
    assert data["pallets"] >= 1
    assert data["risk_class"] in ["RAW_ANIMAL", "PRODUCE", "READY_TO_EAT"]
    assert data["status"] in ["BOOKED", "RECEIVED", "NO_SHOW", "CANCELLED"]


def assert_delivery_route(data: dict):
    _assert_common_fields(data, "DeliveryRoute")
    assert data["storage_class"] in ["AMBIENT", "CHILL", "FROZEN"]
    assert data["pallet_capacity"] >= 1
    assert data["status"] in ["PLANNED", "LOADED", "DISPATCHED", "COMPLETED"]
    assert data["stop_count"] >= 0
    assert data["pallets_loaded"] >= 0


def assert_rejection_claim(data: dict):
    _assert_common_fields(data, "RejectionClaim")
    assert is_valid_uuid(data["allocation_id"])
    assert data["quantity_rejected"] >= 1
    assert data["reason_code"] in [
        "TEMP_ABUSE",
        "DAMAGE",
        "SPEC_MISMATCH",
        "SHORT_COUNT",
        "LATE_DELIVERY",
    ]
    assert data["status"] in ["FILED", "APPROVED", "DENIED", "WITHDRAWN"]
    assert isinstance(data["filed_by_user_id"], str) and data["filed_by_user_id"]


def assert_shrink_split_conserved(data: dict):
    """The producer's charge and the hub's absorption always add back to the
    buyer credit exactly."""
    assert (
        data["producer_charge_cents"] + data["hub_absorbed_cents"]
        == data["buyer_credit_cents"]
    ), (
        "producer_charge_cents + hub_absorbed_cents must equal buyer_credit_cents, "
        f"got {data['producer_charge_cents']} + {data['hub_absorbed_cents']} "
        f"!= {data['buyer_credit_cents']}"
    )


def assert_patronage_cycle(data: dict):
    _assert_common_fields(data, "PatronageCycle")
    assert 2000 <= data["fiscal_year"] <= 2100
    assert data["distributable_pool_cents"] >= 1
    assert data["status"] in ["PROPOSED", "RATIFIED", "DISTRIBUTED", "CANCELLED"]
    assert isinstance(data["proposed_by_user_id"], str)


def assert_pool_conserved(data: dict):
    """distributed_total_cents and remainder_cents always add back to
    distributable_pool_cents exactly."""
    assert (
        data["distributed_total_cents"] + data["remainder_cents"]
        == data["distributable_pool_cents"]
    ), (
        "distributed_total_cents + remainder_cents must equal "
        f"distributable_pool_cents, got {data['distributed_total_cents']} + "
        f"{data['remainder_cents']} != {data['distributable_pool_cents']}"
    )


def assert_receivable_identity(order: dict, buyer: dict):
    """The buyer's outstanding balance tracks invoiced total less cash applied
    less credit memos issued."""
    expected = (
        order["invoiced_total_cents"]
        - order["paid_total_cents"]
        - order["credit_memo_cents"]
    )
    assert buyer["outstanding_balance_cents"] == expected, (
        "outstanding_balance_cents must equal invoiced_total_cents - "
        f"paid_total_cents - credit_memo_cents == {expected}, got "
        f"{buyer['outstanding_balance_cents']}"
    )


__all__ = [
    "assert_producer",
    "assert_producer_document",
    "assert_product",
    "assert_product_availability",
    "assert_buyer",
    "assert_buyer_order",
    "assert_order_total_identity",
    "assert_order_line",
    "assert_allocation",
    "assert_allocation_money_split",
    "assert_dock_slot",
    "assert_dock_appointment",
    "assert_delivery_route",
    "assert_rejection_claim",
    "assert_shrink_split_conserved",
    "assert_patronage_cycle",
    "assert_pool_conserved",
    "assert_receivable_identity",
]
