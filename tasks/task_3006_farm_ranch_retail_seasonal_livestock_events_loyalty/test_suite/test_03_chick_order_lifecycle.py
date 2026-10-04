"""Chick order cyclic brooder-verification state machine and OCC."""

import pytest

from test_helpers import (
    ApiErrorId,
    brooder_verify,
    create_account,
    create_chick_order_payload,
    make_customer_headers,
    place_chick_order,
    post_care_log,
    set_clock,
    setup_reserved_order,
    setup_spring_store,
    TEST_USERS,
    ts_iso,
    validate_error,
    validate_success,
)

RA = TEST_USERS["regional_admin_headers"]
MGR = TEST_USERS["store_manager_headers"]
ASSOC = TEST_USERS["store_associate_headers"]


def test_brooder_verification_expires_after_72h_and_reverts_to_reserved(api):
    """PRD §3.4: "if the logical now is more than 72 hours past `brooder_verified_at`, the order reverts `BROODER_VERIFIED → RESERVED`, `brooder_verified_at` is cleared to null, and the call fails with `ERR_BROODER_VERIFICATION_EXPIRED`."

    Design: Difficulty/non_linear_state_machine/chick_order_brooder_verification_reverify_cycle
    """
    ctx = setup_reserved_order()
    brooder_verify(ctx["order"]["id"])
    post_care_log(ctx["lot"]["id"], "FEEDING")

    # 73 hours past the 2026-03-10T10:00:00Z verification.
    set_clock("2026-03-13T11:00:00Z")
    resp = api.fulfill_chick_order(ctx["order"]["id"], ASSOC)
    validate_error(resp, ApiErrorId.ERR_BROODER_VERIFICATION_EXPIRED)

    order = validate_success(api.get_chick_order(ctx["order"]["id"], MGR))
    assert order["status"] == "RESERVED"
    assert order["brooder_verified_at"] is None


def test_brooder_reverify_after_reversion_completes_cycle_and_fulfills(api):
    """PRD §3.4: "A `StoreAssociate` runs brooder verification on a `RESERVED` order (any other state fails with `ERR_ORDER_NOT_RESERVED`), submitting three flags — `heat_lamp_ok`, `thermometer_ok`, and `bedding_ok`."
    PRD §3.4: "A successful verification moves the order `RESERVED → BROODER_VERIFIED` and stamps `brooder_verified_at` with the logical now."
    PRD §3.4: "A successful fulfillment stamps `fulfilled_at`, adds the order's quantity to the lot's `quantity_sold`, and leaves `quantity_on_hand` unchanged, because the reservation simply converts to a sale."

    Design: Difficulty/non_linear_state_machine/chick_order_brooder_verification_reverify_cycle
    """
    ctx = setup_reserved_order()
    brooder_verify(ctx["order"]["id"])
    post_care_log(ctx["lot"]["id"], "FEEDING")

    set_clock("2026-03-13T11:00:00Z")
    validate_error(
        api.fulfill_chick_order(ctx["order"]["id"], ASSOC),
        ApiErrorId.ERR_BROODER_VERIFICATION_EXPIRED,
    )

    # Cycle hop 2: re-verify the reverted order and fulfill it the second time.
    post_care_log(ctx["lot"]["id"], "WATER")
    verified = brooder_verify(ctx["order"]["id"])
    assert verified["status"] == "BROODER_VERIFIED"
    assert verified["brooder_verified_at"] == ts_iso("2026-03-13T11:00:00Z")

    fulfilled = validate_success(api.fulfill_chick_order(ctx["order"]["id"], ASSOC))
    assert fulfilled["status"] == "FULFILLED"
    assert fulfilled["fulfilled_at"] == ts_iso("2026-03-13T11:00:00Z")

    lot = validate_success(api.get_livestock_lot(ctx["lot"]["id"], MGR))
    assert lot["quantity_sold"] == 6
    assert lot["quantity_on_hand"] == 94


def test_chick_min_purchase_below_minimum_rejected(api):
    """PRD §3.4: "The `quantity` must meet the schedule's `min_purchase_qty` (otherwise `ERR_MIN_PURCHASE_NOT_MET`)"

    Design: Difficulty/boundary_precision_check/chick_min_purchase_exactly_at_minimum
    """
    ctx = setup_spring_store()
    account = create_account()
    resp = api.create_chick_order(
        create_chick_order_payload(
            ctx["store"]["id"], ctx["lot"]["id"], account["id"],
            ctx["lot_version"], quantity=5,
        ),
        make_customer_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MIN_PURCHASE_NOT_MET)


def test_chick_min_purchase_exactly_at_minimum_accepted(api):
    """PRD §3.4: "The `quantity` must meet the schedule's `min_purchase_qty` (otherwise `ERR_MIN_PURCHASE_NOT_MET`)"
    PRD §3.4: "The bracket keys on quantity: no discount — `discount_pct` 0.00 — for 24 birds or fewer"

    Design: Difficulty/boundary_precision_check/chick_min_purchase_exactly_at_minimum
    """
    ctx = setup_spring_store()
    account = create_account()
    order = place_chick_order(
        ctx["store"], ctx["lot"], account, quantity=6,
        lot_version=ctx["lot_version"],
    )
    assert order["status"] == "RESERVED"
    assert order["discount_pct"] == 0.0
    assert order["total_cents"] == 2094  # 6 x 349, no discount
