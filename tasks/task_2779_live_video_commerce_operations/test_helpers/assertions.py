"""Entity assertions and the domain invariant checkers the PRD names."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict, entity_name: str = "resource"):
    """Every one of the thirteen resources carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a bare UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_name}.created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_name}.updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), f"{entity_name}.version must be an integer"
    assert data["version"] >= 1, f"{entity_name}.version starts at 1"


def assert_host(data: dict):
    assert_common_fields(data, "Host")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["handle"], str) and 3 <= len(data["handle"]) <= 30
    assert 0.0 <= data["commission_pct"] <= 0.30
    assert data["certification_status"] in ("UNCERTIFIED", "CERTIFIED", "EXPIRED")


def assert_product(data: dict):
    assert_common_fields(data, "Product")
    assert isinstance(data["sku"], str) and data["sku"]
    assert 100 <= data["base_price_cents"] <= 5_000_000
    assert 0 <= data["unit_cost_cents"] < data["base_price_cents"]
    assert data["claim_substantiation_status"] in (
        "UNSUBSTANTIATED",
        "SUBSTANTIATED",
        "REJECTED",
    )
    assert_inventory_pool_conserved(data)


def assert_viewer(data: dict):
    assert_common_fields(data, "Viewer")
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert "@" in data["email"]
    assert data["chat_status"] in ("ACTIVE", "MUTED")
    assert isinstance(data["strike_count"], int) and data["strike_count"] >= 0


def assert_show(data: dict):
    assert_common_fields(data, "Show")
    assert data["status"] in ("DRAFT", "READY", "LIVE", "ENDED", "SETTLED")
    assert data["scheduled_end_at"] > data["scheduled_start_at"]
    assert 0 <= data["simulcast_readiness_index"] <= 100
    assert isinstance(data["abandoned_cart_count"], int)
    assert isinstance(data["abandonment_rate_bp"], int)


def assert_stream_channel(data: dict):
    assert_common_fields(data, "StreamChannel")
    assert data["platform"] in ("FLAGSHIP_APP", "SOCIAL_A", "SOCIAL_B", "PARTNER_APP")
    assert 500 <= data["target_latency_ms"] <= 8000
    assert data["status"] in ("DRAFT", "PROVISIONED", "LIVE", "FAILED", "ENDED")
    assert 0 <= data["readiness_index"] <= 100
    assert 0.0 <= data["dropped_frame_pct"] <= 1.0
    assert isinstance(data["is_primary"], bool)


def assert_host_booking(data: dict):
    assert_common_fields(data, "HostBooking")
    assert data["role"] in ("PRIMARY", "GUEST")
    assert data["status"] in ("PENDING", "CONFIRMED", "CANCELLED", "COMPLETED")
    assert data["release_time_at"] > data["call_time_at"]
    assert data["fee_cents"] >= 0


def assert_lineup_slot(data: dict):
    assert_common_fields(data, "LineupSlot")
    assert data["slot_sequence"] >= 1
    assert data["planned_end_at"] > data["planned_start_at"]
    assert data["planned_qty"] >= 1
    assert data["replay_marker_status"] in ("NONE", "DRAFT", "PUBLISHED")
    assert isinstance(data["unit_cost_snapshot_cents"], int)


def assert_flash_offer(data: dict):
    assert_common_fields(data, "FlashOffer")
    assert data["status"] in (
        "SCHEDULED",
        "ACTIVE",
        "EXHAUSTED",
        "EXPIRED",
        "CANCELLED",
        "SUPERSEDED",
    )
    assert 1 <= data["max_qty"] <= 100_000
    assert data["offer_price_cents"] >= 1
    assert data["window_end_at"] > data["window_start_at"]
    assert_offer_allotment_conserved(data)


def assert_disclosure_record(data: dict):
    assert_common_fields(data, "DisclosureRecord")
    assert data["disclosure_type"] in (
        "PAID_ENDORSEMENT",
        "MATERIAL_CONNECTION",
        "FREE_PRODUCT",
    )
    assert data["status"] in ("PENDING", "ACKNOWLEDGED", "VOIDED")
    assert isinstance(data["acknowledged_late"], bool)


def assert_cart(data: dict):
    assert_common_fields(data, "Cart")
    assert data["status"] in ("OPEN", "ABANDONED", "CHECKED_OUT", "EXPIRED")
    assert data["bundle_discount_pct"] in (0.0, 0.05, 0.10)
    assert data["pre_discount_subtotal_cents"] >= 0
    assert data["held_item_count"] >= 0
    assert data["recovered_count"] >= 0


def assert_cart_item(data: dict):
    assert_common_fields(data, "CartItem")
    assert data["state"] in ("HELD", "COMMITTED", "RELEASED")
    assert 1 <= data["qty"] <= 20
    assert data["line_gross_cents"] == data["effective_unit_price_cents"] * data["qty"], (
        "line_gross_cents is the already-rounded effective unit price times qty"
    )
    if data["state"] == "HELD":
        assert data["released_reason"] is None
        assert data["released_at"] is None


def assert_order(data: dict):
    assert_common_fields(data, "Order")
    assert data["payment_state"] in ("AUTHORIZED", "CAPTURED", "VOIDED", "REFUNDED")
    assert data["fulfillment_state"] in ("PENDING", "ALLOCATED", "CANCELLED")
    for field in ("merchandise_cents", "tax_cents", "shipping_cents", "total_cents"):
        assert isinstance(data[field], int), f"Order.{field} must be integer cents"
    assert (
        data["total_cents"]
        == data["merchandise_cents"] + data["tax_cents"] + data["shipping_cents"]
    ), "total_cents is merchandise plus tax plus shipping"


def assert_interaction(data: dict):
    assert_common_fields(data, "Interaction")
    assert data["kind"] in ("CHAT", "QUESTION", "POLL")
    assert isinstance(data["body"], str)
    if data["kind"] == "POLL" and data.get("tallies") is not None:
        assert data["vote_count"] == sum(data["tallies"].values()), (
            "vote_count is always the sum of the values in tallies"
        )


def assert_inventory_pool_conserved(product: dict):
    """A product's on_hand_qty always equals available plus reserved plus committed."""
    assert (
        product["on_hand_qty"]
        == product["available_qty"] + product["reserved_qty"] + product["committed_qty"]
    ), (
        "on_hand_qty {on_hand_qty} != available_qty {available_qty} + reserved_qty "
        "{reserved_qty} + committed_qty {committed_qty}".format(**product)
    )


def assert_offer_allotment_conserved(offer: dict):
    """An offer's max_qty always equals remaining plus held plus sold."""
    assert (
        offer["max_qty"] == offer["remaining_qty"] + offer["held_qty"] + offer["sold_qty"]
    ), (
        "max_qty {max_qty} != remaining_qty {remaining_qty} + held_qty {held_qty} + "
        "sold_qty {sold_qty}".format(**offer)
    )


def assert_both_ledgers_conserved(product: dict, offer: dict):
    assert_inventory_pool_conserved(product)
    assert_offer_allotment_conserved(offer)


def assert_no_pagination_meta(meta: dict):
    """Single-resource reads and write responses carry meta without the four
    pagination fields."""
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field not in meta, f"meta must not carry {field} on a single-resource read"


def assert_request_envelope_meta(meta: dict):
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        "api_request_id starts with req_"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", ""))


def canonical_instant(value):
    """Normalise an ISO 8601 UTC instant to second precision for comparison.

    The PRD renders stored instants with exactly three fractional-second digits
    while the instants supplied in request bodies may be second-precision, so a
    test comparing the two must not fail on the fractional width alone.
    """
    if value is None:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text[10:]:
        text = text[: text.index("+", 10)]
    if "." in text:
        text = text[: text.index(".")]
    return text


def assert_instant(actual, expected, label: str = "instant"):
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )
