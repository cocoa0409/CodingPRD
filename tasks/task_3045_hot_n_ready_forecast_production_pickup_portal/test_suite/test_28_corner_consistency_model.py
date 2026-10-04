"""Corner coverage of the immediate consistency model."""

from test_helpers import (
    fixtures,
    make_manager_headers,
    validate_success,
)


def test_mark_ready_response_reflects_all_side_effects_immediately(client):
    """The mark-ready response itself carries the code, expiry, and slot, and a
    same-instant read shows the slot OCCUPIED for this order.

    "The order receives a `pickup_code`, a 6-digit code minted to be unique
    among codes in the same store day whose `code_expires_at` has not yet
    passed, and a `code_expires_at` set 45 minutes after readiness; `ready_at`
    is stamped."
    "it flips to `OCCUPIED` with `current_order_id` set and `occupied_at`
    stamped."

    Design: Corner/consistency_model/mark_ready_response_reflects_all_side_effects_immediately
    """
    day = fixtures.open_store_day_with_active_daypart(
        client, "2026-11-12", "2026-11-12T11:00:00Z"
    )
    slot = fixtures.create_locker_slot(client, day.store_day["id"], slot_number=1)
    product = fixtures.create_product(client)
    order = fixtures.paid_portal_order(
        client, day.store_day["id"], day.daypart["id"], "cust-e5", product["id"]
    )
    fixtures.start_preparation(client, order["id"])

    ready = fixtures.mark_ready(client, order["id"])
    assert ready["fulfillment_status"] == "READY"
    assert ready.get("pickup_code"), "pickup_code minted in the response"
    assert ready.get("code_expires_at"), "code_expires_at minted in the response"
    assert ready["locker_slot_id"] == slot["id"]
    assert ready.get("ready_at"), "ready_at stamped"
    code = ready["pickup_code"]
    assert code.isdigit() and len(code) == 6, "a 6-digit code"
    # code_expires_at is 45 minutes after the 11:00Z readiness.
    assert "11:45" in ready["code_expires_at"]

    slot_after = validate_success(
        client.get_locker_slot(slot["id"], make_manager_headers()), 200
    )
    assert slot_after["status"] == "OCCUPIED"
    assert slot_after["current_order_id"] == order["id"]
