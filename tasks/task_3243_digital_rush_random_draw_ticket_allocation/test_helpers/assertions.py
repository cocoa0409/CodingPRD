"""Per-resource assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """Every resource carries the full common property set."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an integer of at least 1"


def assert_production(data: dict):
    assert_common_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["producer_org"], str) and data["producer_org"]
    assert data["status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "CLOSED"]
    assert isinstance(data["refund_window_hours"], int) and data["refund_window_hours"] >= 0
    assert isinstance(data["exchange_fee_cents"], int) and data["exchange_fee_cents"] >= 0
    assert isinstance(data["exchange_allowed"], bool)


def assert_market(data: dict):
    assert_common_fields(data)
    assert isinstance(data["market_code"], str) and data["market_code"]
    assert isinstance(data["city"], str) and data["city"]
    assert data["handoff_model"] in ["MOBILE_PUSH", "CONCIERGE_DESK", "HYBRID"]


def assert_performance(data: dict):
    assert_common_fields(data)
    assert isinstance(data["market_code"], str) and data["market_code"]
    assert isinstance(data["venue_name"], str) and data["venue_name"]
    assert is_iso8601_timestamp(data["starts_at"])
    assert isinstance(data["face_value_cents"], int) and data["face_value_cents"] > 0
    assert isinstance(data["total_seat_capacity"], int) and data["total_seat_capacity"] > 0
    assert data["status"] in ["SCHEDULED", "ONSALE", "CLOSED", "CANCELLED"]


def assert_allocation(data: dict):
    assert_common_fields(data)
    assert data["ticket_type"] in ["RUSH", "RUSH_PREMIUM", "DRAW", "STANDARD"]
    assert isinstance(data["daily_quantity"], int) and data["daily_quantity"] > 0
    assert 0 <= float(data["discount_pct"]) <= 1
    assert isinstance(data["release_time_local"], str)
    assert isinstance(data["refundable"], bool)
    assert isinstance(data["quantity_released_today"], int)
    assert isinstance(data["quantity_sold_today"], int)
    assert isinstance(data["quantity_carried_forward"], int)
    assert isinstance(data["daily_release_cap"], int)
    assert data["status"] in ["DRAFT", "SCHEDULED", "RELEASED", "EXHAUSTED",
                              "SUSPENDED", "CLOSED"]
    assert data["reconciliation_status"] in ["NOT_SUBMITTED", "RECONCILED", "MISMATCH"]


def assert_draw_entry(data: dict):
    assert_common_fields(data)
    assert isinstance(data["patron_id"], str) and data["patron_id"]
    assert data["status"] in ["ENTERED", "WINNER", "WAITLISTED", "LOSER",
                              "PURCHASED", "FORFEITED", "CANCELLED"]
    assert is_iso8601_timestamp(data["entered_at"])
    assert isinstance(data["reinstatement_count"], int)
    assert data["reinstatement_count"] in (0, 1)


def assert_purchase(data: dict):
    assert_common_fields(data)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["surge_multiplier_bp"], int)
    assert isinstance(data["subtotal_cents"], int) and data["subtotal_cents"] >= 0
    assert data["payment_status"] in ["PENDING", "AUTHORIZED", "SETTLED",
                                      "REFUNDED", "PARTIALLY_REFUNDED", "VOIDED"]
    assert data["logistics_status"] in ["AWAITING_HANDOFF", "DELIVERED",
                                        "COLLECTED", "REVOKED"]
    assert data["handoff_status"] in ["NOT_REQUIRED", "PENDING_CONCIERGE",
                                      "VERIFIED", "FAILED"]
    assert isinstance(data["seat_labels"], list) and data["seat_labels"]
    assert isinstance(data["refunded_cents"], int) and data["refunded_cents"] >= 0


def assert_seat_hold(data: dict):
    assert_common_fields(data)
    assert isinstance(data["seat_label"], str) and data["seat_label"]
    assert data["hold_kind"] in ["BOX_OFFICE", "HOUSE", "COMP", "ALLOCATION"]
    assert data["status"] in ["HELD", "RELEASED", "CONSUMED", "ORPHANED", "EXPIRED"]
    assert is_iso8601_timestamp(data["effective_from"])


def assert_queue_position(data: dict):
    assert_common_fields(data)
    assert isinstance(data["patron_id"], str) and data["patron_id"]
    assert data["status"] in ["WAITING", "ADMITTED", "PURCHASED", "EXPIRED",
                              "ABANDONED"]
    assert is_iso8601_timestamp(data["joined_at"])


def assert_desk(data: dict):
    assert_common_fields(data)
    assert isinstance(data["desk_code"], str) and data["desk_code"]
    assert isinstance(data["daily_capacity"], int) and data["daily_capacity"] > 0
    assert isinstance(data["handoffs_today"], int)
    assert data["status"] in ["OPEN", "SATURATED", "CLOSED"]


def assert_refund_request(data: dict):
    assert_common_fields(data)
    assert data["reason_code"] in ["PATRON_REQUEST", "PERFORMANCE_CANCELLED",
                                   "PLATFORM_FAULT", "DESK_FAILURE"]
    assert data["status"] in ["REQUESTED", "PROCESSING", "SETTLED", "REJECTED",
                              "COMPENSATED"]
    assert isinstance(data["refunded_amount_cents"], int)
    assert data["refunded_amount_cents"] >= 0


def assert_exchange_request(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["REQUESTED", "QUOTED", "APPROVED", "APPLIED",
                              "REJECTED", "COMPENSATED"]
    assert isinstance(data["original_amount_cents"], int)


def assert_patron(data: dict):
    assert_common_fields(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["status"] in ["ACTIVE", "BLOCKED"]
    assert isinstance(data["draw_violation_count"], (int, float))
    assert data["draw_violation_count"] >= 0


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------

def assert_no_fractional_cents(data: dict, fields):
    """No monetary field is ever reported at a precision finer than a whole cent."""
    for field in fields:
        value = data.get(field)
        if value is None:
            continue
        assert float(value) == int(value), \
            f"{field} must be a whole number of cents, got {value}"


def assert_purchase_money_whole_cents(data: dict):
    assert_no_fractional_cents(
        data,
        ["unit_price_cents", "subtotal_cents", "quoted_total_cents",
         "refunded_cents"],
    )


def assert_dispensed_seats_conserved(allocation: dict, expected_released: int,
                                     expected_sold: int):
    """The seat bookkeeping after a fully compensated cycle carries no drift."""
    assert allocation["quantity_released_today"] == expected_released, \
        f"released expected {expected_released}, got {allocation['quantity_released_today']}"
    assert allocation["quantity_sold_today"] == expected_sold, \
        f"sold expected {expected_sold}, got {allocation['quantity_sold_today']}"


def assert_unset_until_event(data: dict, fields):
    """Derived instants are null until the event that stamps them occurs."""
    for field in fields:
        assert data.get(field) is None, f"{field} should still be null"