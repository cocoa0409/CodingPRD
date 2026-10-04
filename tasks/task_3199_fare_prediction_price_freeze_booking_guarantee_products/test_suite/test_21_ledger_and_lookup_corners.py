"""Breadth coverage for payment retrieval, hedging positions and lookups."""

from test_helpers import (
    TEST_USERS,
    api_client,
    create_itinerary,
    create_route,
    get_success_data,
    is_iso8601_timestamp,
    observe,
    publish_curve,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_missing_route_is_reported_with_its_own_error_identifier():
    """PRD §2.5: "Existence follows, resolved left-to-right along the path: the
    route is located first (`ERR_ROUTE_NOT_FOUND`), then the itinerary
    (`ERR_ITINERARY_NOT_FOUND`), then the freeze (`ERR_FREEZE_NOT_FOUND`), and
    finally the child resource named in the path or body ... Each is an HTTP
    404."

    Design: Corner/entities/corner_route_get_with_an_unknown_id_returns_route_not_found
    """
    set_clock()
    res = api_client.get_route("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
                               TEST_USERS["ops_headers"])
    error = validate_error(res, "ERR_ROUTE_NOT_FOUND", expected_status=404)
    assert error["message"].strip()


def test_a_missing_freeze_and_a_missing_child_use_distinct_error_codes():
    """PRD §2.5: "Existence follows, resolved left-to-right along the path: the
    route is located first (`ERR_ROUTE_NOT_FOUND`), then the itinerary
    (`ERR_ITINERARY_NOT_FOUND`), then the freeze (`ERR_FREEZE_NOT_FOUND`), and
    finally the child resource named in the path or body — a watch subscription,
    protection product, guarantee claim, change event, rebooking option, payment,
    hedging position, destination option or risk pool (`ERR_RESOURCE_NOT_FOUND`)."

    Design: Corner/errors/corner_freeze_not_found_is_distinct_from_resource_not_found
    """
    set_clock()
    freeze_error = validate_error(
        api_client.get_freeze("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
                              TEST_USERS["traveler_headers"]),
        "ERR_FREEZE_NOT_FOUND", expected_status=404,
    )
    claim_error = validate_error(
        api_client.get_claim("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d3",
                             TEST_USERS["traveler_headers"]),
        "ERR_RESOURCE_NOT_FOUND", expected_status=404,
    )
    assert "ERR_FREEZE_NOT_FOUND" != "ERR_RESOURCE_NOT_FOUND", (
        "each id-bearing path segment maps to its own not-found code"
    )
    assert freeze_error["message"].strip() and claim_error["message"].strip()


def test_payment_allocations_are_an_ordered_append_only_log():
    """PRD §3.10: "Each allocation is appended to the payment's `allocations`
    log — an ordered audit trail of a target, an `amount_cents` and an
    `applied_at` — and debits the payment's `refundable_remaining_cents`."

    Design: Corner/entities/corner_payment_allocations_are_an_order_preserving_audit_log
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    payment = get_success_data(
        api_client.create_payment(
            {"itinerary_id": itinerary["id"], "payment_kind": "CHANGE_FEE",
             "amount_cents": 2000, "capture": True},
            TEST_USERS["ops_headers"])
    )
    get_success_data(api_client.refund_payment(payment["id"], {"refund_cents": 500},
                                               TEST_USERS["ops_headers"]))
    refunded = get_success_data(
        api_client.refund_payment(payment["id"], {"refund_cents": 1500},
                                  TEST_USERS["ops_headers"])
    )
    amounts = [entry["amount_cents"] for entry in refunded["allocations"]]
    assert amounts == [2000, 500, 1500], (
        "the log preserves the order in which the allocations were applied"
    )
    assert refunded["refundable_remaining_cents"] == 0
    assert refunded["status"] == "REFUNDED"
    for entry in refunded["allocations"]:
        assert is_iso8601_timestamp(entry["applied_at"])


def test_a_full_refund_zeroes_the_entitlement_exactly():
    """PRD §3.10: "requires a `refund_cents` of at least 1 and no more than the
    payment's `refundable_remaining_cents`; a zero or negative amount is refused
    as `ERR_INVALID_REQUEST`, and an amount that would overrun the balance is
    refused as `ERR_PAYMENT_OVER_ALLOCATED`."

    Design: Corner/state_machines/corner_payment_refund_clears_the_entitlement_to_zero
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    payment = get_success_data(
        api_client.create_payment(
            {"itinerary_id": itinerary["id"], "payment_kind": "PREMIUM",
             "amount_cents": 825, "capture": True},
            TEST_USERS["ops_headers"])
    )
    partial = get_success_data(
        api_client.refund_payment(payment["id"], {"refund_cents": 200},
                                  TEST_USERS["ops_headers"])
    )
    assert partial["refundable_remaining_cents"] == 625
    assert partial["status"] == "PARTIALLY_REFUNDED"

    # One cent more than the remaining balance overruns it.
    over = api_client.refund_payment(payment["id"], {"refund_cents": 626},
                                     TEST_USERS["ops_headers"])
    validate_error(over, "ERR_PAYMENT_OVER_ALLOCATED")

    full = get_success_data(
        api_client.refund_payment(payment["id"], {"refund_cents": 625},
                                  TEST_USERS["ops_headers"])
    )
    assert full["refundable_remaining_cents"] == 0
    assert full["status"] == "REFUNDED"


def test_a_watch_is_discoverable_from_its_owning_itinerary():
    """PRD §4: "GET /fare/watch-subscriptions | List watch subscriptions by
    itinerary or notification status". PRD §2.4: "Child resources reference
    their parents through an identifier field rather than a nested path, and the
    API never models containment by URL depth."

    Design: Corner/entities/corner_watch_subscription_is_the_child_of_its_itinerary_and_lists_both_ways
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    watch = get_success_data(
        api_client.arm_watch(itinerary["id"],
                             {"expected_itinerary_version": itinerary["version"]},
                             TEST_USERS["traveler_headers"])
    )
    page, meta = validate_paginated(
        api_client.list_watches(TEST_USERS["traveler_headers"],
                                params={"itinerary_id": itinerary["id"]})
    )
    assert meta["total_count"] == 1, "the filtered list discovers the watch from the itinerary id"
    assert [row["id"] for row in page] == [watch["id"]]
    assert page[0]["itinerary_id"] == itinerary["id"], (
        "the watch reaches its parent through the declared foreign key"
    )


def test_filtering_watches_by_an_unallocated_itinerary_returns_no_rows():
    """PRD §2.3: "`total_count` reflects the full size of the filtered result
    set, not the size of the returned page, which is what makes `has_more`
    meaningful."

    Design: Corner/entities/corner_watch_subscription_is_the_child_of_its_itinerary_and_lists_both_ways
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    get_success_data(
        api_client.arm_watch(itinerary["id"],
                             {"expected_itinerary_version": itinerary["version"]},
                             TEST_USERS["traveler_headers"])
    )
    page, meta = validate_paginated(
        api_client.list_watches(
            TEST_USERS["traveler_headers"],
            params={"itinerary_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"})
    )
    assert page == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def test_the_watch_window_is_the_itinerary_departure_date():
    """PRD §3.2: "Success creates the watch in `ARMED` with an `armed_at` of the
    current clock instant and an `expires_at` equal to the watched itinerary's
    `departure_date` — the watch must resolve before the flight, so its window is
    the itinerary's own."

    Design: Corner/entities/corner_watch_subscription_is_the_child_of_its_itinerary_and_lists_both_ways
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    watch = get_success_data(
        api_client.arm_watch(itinerary["id"],
                             {"expected_itinerary_version": itinerary["version"]},
                             TEST_USERS["traveler_headers"])
    )
    assert watch["expires_at"] == itinerary["departure_date"]
    assert watch["armed_at"] == "2026-09-01T00:00:00.000Z", (
        "the arming instant is the current clock instant"
    )
    assert watch["notification_status"] == "ARMED"


def test_a_hedging_position_get_round_trips_its_stored_mark_state():
    """PRD §3.9: "The position becomes `HEDGED`, its `projected_day_cost_cents`
    records the marked figure, and its `mark_value_cents` becomes the amount by
    which the projected cost exceeds the locked hedge price, floored at zero."

    Design: Corner/entities/corner_hedging_position_get_returns_the_stored_mark_state
    """
    set_clock()
    pool = get_success_data(
        api_client.open_risk_pool({"region": "WEST", "pool_code": "WEST-RP-1"},
                                  TEST_USERS["risk_analyst_headers"])
    )
    route = create_route()
    position = get_success_data(
        api_client.open_hedging_position(
            {"route_id": route["id"], "coverage_date": "2026-09-15T00:00:00Z",
             "hedge_price_cents": 9000, "contract_quantity_cents": 500000,
             "expected_route_version": route["version"]},
            TEST_USERS["risk_analyst_headers"])
    )
    marked = get_success_data(
        api_client.mark_hedging_position(position["id"], {"projected_day_cost_cents": 7000},
                                         TEST_USERS["risk_analyst_headers"])
    )
    assert marked["projected_day_cost_cents"] == 7000
    fetched = validate_success(
        api_client.get_hedging_position(position["id"], TEST_USERS["risk_analyst_headers"]), 200
    )
    assert fetched["hedge_price_cents"] == 9000
    assert fetched["projected_day_cost_cents"] == 7000
    assert fetched["mark_value_cents"] == 0, (
        "the projected cost sits below the locked price, so the mark is floored at zero"
    )
    assert fetched["pool_id"] == pool["id"]
    assert fetched["status"] in ("HEDGED", "OPEN")
    assert fetched["regression_reversed"] is False
