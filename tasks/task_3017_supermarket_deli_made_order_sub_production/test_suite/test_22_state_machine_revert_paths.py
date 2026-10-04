"""Revert edges and terminal-state lockdown across the promotion and bread chain."""

from test_helpers import (
    ApiErrorId,
    api_client,
    clerk_headers,
    create_catering_order_payload,
    coordinator_headers,
    create_promotion_payload,
    get_success_data,
    manager_headers,
    platform_admin_headers,
    set_clock,
    setup_deli_master_data,
    setup_promo_bread_chain,
    validate_error,
    validate_success,
)


def test_cancelled_is_a_dead_end_for_the_promotion():
    """PRD §3.5: "A promotion may be cancelled from `ACTIVE` or from `SETTLED`,
    and only when no bread supply order with status `SUBMITTED`, `CONFIRMED` or
    `DELIVERED` references it; the cancellation takes the promotion to
    `CANCELLED` and moves every bread supply order referencing it to
    `RECONCILED`."

    Design: Corner/state_machines/terminal_cancelled_promotion_has_no_successor
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=240, store_number="102", store_name="Store Two",
                                    slicer_count=0)
    promotion = get_success_data(
        api_client.create_promotion(
            create_promotion_payload(
                promo_code="FEAT-0914", deli_item_id=master.j1["id"],
                week_start_date="2026-09-07T00:00:00Z", week_end_date="2026-09-14T00:00:00Z",
                forecast_uplift_pct=0.2, trailing_baseline_units=600,
            ),
            platform_admin_headers(),
        )
    )

    # PRD §3.5: cancellation is available from ACTIVE or SETTLED, so the
    # promotion must first be activated inside its week.
    set_clock("2026-09-07T00:00:00Z")
    validate_success(
        api_client.activate_promotion(promotion["id"], manager_headers(master.a2["id"]))
    )
    cancelled = validate_success(
        api_client.cancel_promotion(promotion["id"], manager_headers(master.a2["id"]))
    )
    assert cancelled["status"] == "CANCELLED"

    for action, name in (
        (api_client.activate_promotion, "activate"),
        (api_client.settle_promotion, "settle"),
        (api_client.reopen_promotion, "reopen"),
    ):
        response = action(promotion["id"], manager_headers(master.a2["id"]))
        assert response.status_code >= 400, f"{name} must not succeed on a cancelled promotion"

    store = validate_success(api_client.get_store(master.s, platform_admin_headers()))
    assert store["targeted_promo_id"] is None, "a CANCELLED promotion is never ranked"


def test_a_delivered_bread_order_reopens_through_submitted_and_can_land_short():
    """PRD §3.5: "A delivery that is rejected at receiving may be reopened, which
    returns the order from `DELIVERED` to `SUBMITTED` for a second bakery
    commitment rather than reverting the delivered row."
    PRD §3.5: "When `delivered_units` is less than nine tenths of `required_units`,
    the order's post-delivery status is `SHORT` rather than `DELIVERED`, and the
    referenced promotion is pushed to `DEGRADED` by that shortfall."

    Design: Corner/state_machines/delivered_bread_order_reopen_path_through_submitted
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=240, store_number="102", store_name="Store Two",
                                    slicer_count=0)
    promotion, order = setup_promo_bread_chain(
        master.s, master.b1["id"], master.j1["id"], forecast_uplift_pct=0.1,
        trailing_baseline_units=600, committed_units=720, delivered_units=720,
        coordinator_id=master.a3["id"],
    )
    assert order["status"] == "DELIVERED"

    reopened = validate_success(
        api_client.reopen_bread_order(
            order["id"], "load rejected at receiving", manager_headers(master.a2["id"])
        )
    )
    assert reopened["status"] == "SUBMITTED", (
        "the DELIVERED row takes the reopen edge instead of terminating"
    )

    # PRD §3.5: a second bakery commitment is confirmed from SUBMITTED, and
    # delivery is made from CONFIRMED.
    promotion_version = validate_success(
        api_client.get_promotion(promotion["id"], platform_admin_headers())
    )["version"]
    validate_success(
        api_client.confirm_bread_order(
            order["id"], promotion_version, manager_headers(master.a2["id"])
        )
    )

    # PRD §3.5: a delivery below nine tenths of `required_units` lands SHORT.
    short = validate_success(
        api_client.deliver_bread_order(order["id"], 600, coordinator_headers(master.a3["id"]))
    )
    assert short["status"] == "SHORT", "600 is below nine tenths of the required units"

    promotion_now = validate_success(api_client.get_promotion(promotion["id"], platform_admin_headers()))
    assert promotion_now["status"] == "DEGRADED", (
        "the shortfall pushes the referenced promotion to DEGRADED"
    )


def test_revising_a_confirmed_catering_order_returns_it_to_inquiry():
    """PRD §3.7: "Revising a confirmed order returns it to `INQUIRY` for
    re-confirmation and accepts an optional revised `platter_count`, `headcount`,
    `pickup_window_start` or `pickup_window_end`."
    PRD §3.7: "Revising a confirmed order returns it to `INQUIRY` for
    re-confirmation"

    Design: Corner/state_machines/catering_confirm_revert_to_inquiry_for_revision
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=240, store_number="102", store_name="Store Two",
                                    slicer_count=0)
    order = get_success_data(
        api_client.create_catering_order(
            create_catering_order_payload(
                store_id=master.s, platter_deli_item_id=master.p1["id"],
                certified_planner_associate_id=master.a1["id"], request_id="REQ-K1",
            ),
            clerk_headers(master.a1["id"]),
        )
    )
    confirmed = validate_success(api_client.confirm_catering_order(order["id"], clerk_headers(master.a1["id"])))
    assert confirmed["status"] == "CONFIRMED"

    revised = validate_success(
        api_client.revise_catering_order(order["id"], {"platter_count": 5}, clerk_headers(master.a1["id"]))
    )
    assert revised["status"] == "INQUIRY", (
        "the revert edge fired rather than a replacement order being created"
    )
    assert revised["platter_count"] == 5

    reconfirmed = validate_success(
        api_client.confirm_catering_order(order["id"], clerk_headers(master.a1["id"]))
    )
    assert reconfirmed["status"] == "CONFIRMED"
    assert reconfirmed["quote_total_cents"] == 8250, (
        "five platters take the 1650 cent tier at a 30 hour lead time with no rush fee"
    )


def test_cancellation_is_reachable_from_the_non_terminal_catering_states():
    """PRD §3.7: "Cancellation is available from `IN_PRODUCTION` and from `READY`
    for a manager-level caller."
    PRD §3.7: "A confirmed order that has not yet entered production may also be
    cancelled, which decreases the bucket accumulator; an inquiry may be
    cancelled freely with no accumulator effect."

    Design: Corner/state_machines/catering_order_cancelled_from_four_non_terminal_states
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=240, store_number="102", store_name="Store Two",
                                    slicer_count=0)

    def inquiry(request_id, window_start, window_end, count=3):
        return get_success_data(
            api_client.create_catering_order(
                create_catering_order_payload(
                    store_id=master.s, platter_deli_item_id=master.p1["id"],
                    customer_name=f"Party {request_id}", platter_count=count, headcount=8,
                    lead_time_hours=30, pickup_window_start=window_start,
                    pickup_window_end=window_end, certified_planner_associate_id=master.a1["id"],
                    request_id=request_id,
                ),
                clerk_headers(master.a1["id"]),
            )
        )

    first = inquiry("REQ-K1", "2026-09-03T15:00:00Z", "2026-09-03T15:45:00Z")
    second = inquiry("REQ-K2", "2026-09-03T16:00:00Z", "2026-09-03T16:45:00Z")
    third = inquiry("REQ-K3", "2026-09-03T17:00:00Z", "2026-09-03T17:45:00Z")
    validate_success(api_client.confirm_catering_order(second["id"], clerk_headers(master.a1["id"])))
    validate_success(api_client.confirm_catering_order(third["id"], clerk_headers(master.a1["id"])))
    validate_success(api_client.start_catering_production(third["id"], clerk_headers(master.a1["id"])))

    from_inquiry = validate_success(
        api_client.cancel_catering_order(first["id"], "customer withdrew", clerk_headers(master.a1["id"]))
    )
    from_confirmed = validate_success(
        api_client.cancel_catering_order(second["id"], "customer withdrew", clerk_headers(master.a1["id"]))
    )
    from_in_production = validate_success(
        api_client.cancel_catering_order(third["id"], "kitchen closure", manager_headers(master.a2["id"]))
    )
    assert from_inquiry["status"] == "CANCELLED"
    assert from_confirmed["status"] == "CANCELLED"
    assert from_in_production["status"] == "CANCELLED"

    # CANCELLED is terminal (PRD 3.7's state set), so a second attempt on it is
    # a state violation rather than an authorization question.
    terminal = api_client.cancel_catering_order(
        third["id"], "second attempt", clerk_headers(master.a1["id"])
    )
    validate_error(terminal, ApiErrorId.ERR_INVALID_STATE)

    # PRD §3.7: a cancellation from IN_PRODUCTION or READY is a manager-level
    # reversal, so a clerk is refused on a fresh order in those states.
    fourth = inquiry("REQ-K4", "2026-09-03T18:00:00Z", "2026-09-03T18:45:00Z")
    validate_success(api_client.confirm_catering_order(fourth["id"], clerk_headers(master.a1["id"])))
    validate_success(api_client.start_catering_production(fourth["id"], clerk_headers(master.a1["id"])))
    unauthorized = api_client.cancel_catering_order(
        fourth["id"], "clerk attempt", clerk_headers(master.a1["id"])
    )
    validate_error(unauthorized, ApiErrorId.ERR_UNAUTHORIZED)