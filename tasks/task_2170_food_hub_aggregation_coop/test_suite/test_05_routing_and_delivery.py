"""Loading the truck: exclusive route stop windows, vehicle capacity, staging
before dispatch, delivery recording and route completion."""

from test_helpers import (
    CLOCK_BASE,
    HUB,
    ApiErrorId,
    add_order_line,
    allocations_for_line,
    api_client,
    assert_delivery_route,
    book_appointment,
    close_appointment,
    create_buyer,
    create_draft_order,
    create_dock_slot,
    create_listed_product,
    create_route,
    create_route_stop_payload,
    onboard_active_producer,
    read_allocation,
    read_order,
    read_order_line,
    read_route,
    route_version,
    set_clock,
    setup_scenario,
    validate_error,
    validate_success,
)


def _two_aggregated_orders(offered=200, requested=60):
    """One ACTIVE producer with enough supply for two CHILL orders, each of
    which aggregates to two pallets."""
    set_clock(CLOCK_BASE)
    onboarded = onboard_active_producer()
    create_listed_product(onboarded["producer_id"], quantity_offered=offered)
    buyer = create_buyer()
    orders = []
    for _ in range(2):
        order = create_draft_order(buyer["id"])
        add_order_line(order["id"], buyer["id"], quantity_requested=requested)
        validate_success(api_client.aggregate_order(order["id"], HUB))
        orders.append(read_order(order["id"]))
    return onboarded["producer_id"], buyer, orders


class TestRouteStopWindows:
    def test_a_stop_overlapping_an_existing_stop_is_refused(self, api):
        """PRD 3.7: "The service interval, which runs from `planned_arrival_at`
        inclusive to that instant plus `service_minutes` exclusive, must last at
        least one minute — a zero-length stop is refused with
        `ERR_INVALID_WINDOW` — and must not overlap the interval of any other
        stop already on this route, since the vehicle can only be at one dock at
        a time; an overlap is refused with `ERR_STOP_WINDOW_OVERLAP`, while two
        stops arranged back-to-back, where one begins exactly as the other ends,
        are perfectly legal."

        Design: Difficulty/resource_temporal_overlap/route_stop_exclusive_window_allows_adjacency_rejects_zero_length
        """
        _pid, _buyer, orders = _two_aggregated_orders()
        route = create_route(pallet_capacity=20)
        validate_success(
            api.create_route_stop(
                route["id"],
                create_route_stop_payload(orders[0]["id"], route["version"]),
                HUB,
            ),
            201,
        )

        resp = api.create_route_stop(
            route["id"],
            create_route_stop_payload(
                orders[1]["id"],
                route_version(route["id"]),
                sequence_no=2,
                planned_arrival_at="2026-09-15T10:30:00Z",
                service_minutes=60,
            ),
            HUB,
        )
        validate_error(resp, ApiErrorId.ERR_STOP_WINDOW_OVERLAP.value, 409)

        route_now = read_route(route["id"])
        assert route_now["stop_count"] == 1
        assert route_now["pallets_loaded"] == 2

    def test_a_zero_length_service_window_is_refused(self, api):
        """PRD 3.7: "The service interval, which runs from `planned_arrival_at`
        inclusive to that instant plus `service_minutes` exclusive, must last at
        least one minute — a zero-length stop is refused with
        `ERR_INVALID_WINDOW` — and must not overlap the interval of any other
        stop already on this route, since the vehicle can only be at one dock at
        a time; an overlap is refused with `ERR_STOP_WINDOW_OVERLAP`, while two
        stops arranged back-to-back, where one begins exactly as the other ends,
        are perfectly legal."

        Design: Difficulty/resource_temporal_overlap/route_stop_exclusive_window_allows_adjacency_rejects_zero_length
        """
        _pid, _buyer, orders = _two_aggregated_orders()
        route = create_route(pallet_capacity=20)
        validate_success(
            api.create_route_stop(
                route["id"],
                create_route_stop_payload(orders[0]["id"], route["version"]),
                HUB,
            ),
            201,
        )

        resp = api.create_route_stop(
            route["id"],
            create_route_stop_payload(
                orders[1]["id"],
                route_version(route["id"]),
                sequence_no=2,
                planned_arrival_at="2026-09-15T11:00:00Z",
                service_minutes=0,
            ),
            HUB,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value, 422)

        route_now = read_route(route["id"])
        assert route_now["stop_count"] == 1
        assert read_order(orders[1]["id"])["fulfillment_status"] == "AGGREGATED"

    def test_two_back_to_back_stops_are_both_legal(self, api):
        """PRD 3.7: "The service interval, which runs from `planned_arrival_at`
        inclusive to that instant plus `service_minutes` exclusive, must last at
        least one minute — a zero-length stop is refused with
        `ERR_INVALID_WINDOW` — and must not overlap the interval of any other
        stop already on this route, since the vehicle can only be at one dock at
        a time; an overlap is refused with `ERR_STOP_WINDOW_OVERLAP`, while two
        stops arranged back-to-back, where one begins exactly as the other ends,
        are perfectly legal."
        PRD 3.7: "A successful assignment writes `route_id`,
        `route_sequence_no`, `planned_arrival_at` and `service_minutes` onto the
        order and moves it `AGGREGATED → SCHEDULED`."

        Design: Difficulty/resource_temporal_overlap/route_stop_exclusive_window_allows_adjacency_rejects_zero_length
        """
        _pid, _buyer, orders = _two_aggregated_orders()
        route = create_route(pallet_capacity=20)
        validate_success(
            api.create_route_stop(
                route["id"],
                create_route_stop_payload(orders[0]["id"], route["version"]),
                HUB,
            ),
            201,
        )

        data = validate_success(
            api.create_route_stop(
                route["id"],
                create_route_stop_payload(
                    orders[1]["id"],
                    route_version(route["id"]),
                    sequence_no=2,
                    planned_arrival_at="2026-09-15T11:00:00Z",
                    service_minutes=60,
                ),
                HUB,
            ),
            201,
        )
        assert data["fulfillment_status"] == "SCHEDULED"
        assert data["route_sequence_no"] == 2

        order_now = read_order(orders[1]["id"])
        assert order_now["planned_arrival_at"] == "2026-09-15T11:00:00.000Z"
        assert order_now["service_minutes"] == 60

        route_now = read_route(route["id"])
        assert route_now["stop_count"] == 2
        assert route_now["pallets_loaded"] == 4
        assert route_now["status"] == "PLANNED"
        assert_delivery_route(route_now)

    def test_a_stop_on_a_route_at_a_different_temperature_is_refused(self, api):
        """PRD 3.7: "Every one of the order's demand lines must carry the same
        `storage_class` as the route, since one vehicle runs at one temperature
        — a mismatch anywhere on the order is refused with
        `ERR_STORAGE_CLASS_MISMATCH`."

        Design: Corner/validations/route_stop_rejects_an_order_whose_storage_class_differs
        """
        scenario = setup_scenario(stage="aggregated")
        route = create_route(storage_class="FROZEN", pallet_capacity=20)

        resp = api.create_route_stop(
            route["id"],
            create_route_stop_payload(scenario["order_id"], route["version"]),
            HUB,
        )
        validate_error(resp, ApiErrorId.ERR_STORAGE_CLASS_MISMATCH.value, 422)

        order_now = read_order(scenario["order_id"])
        assert order_now["fulfillment_status"] == "AGGREGATED"
        assert order_now["route_id"] is None
        route_now = read_route(route["id"])
        assert route_now["stop_count"] == 0
        assert route_now["pallets_loaded"] == 0

    def test_a_stop_beyond_the_vehicle_pallet_capacity_is_refused(self, api):
        """PRD 3.7: "And the vehicle must have room: the route's current
        `pallets_loaded` plus the order's `order_pallets` must not exceed the
        route's `pallet_capacity`, else `ERR_ROUTE_CAPACITY_EXCEEDED`."

        Design: Corner/validations/route_stop_rejects_an_order_that_exceeds_remaining_pallet_capacity
        """
        scenario = setup_scenario(stage="aggregated")
        route = create_route(pallet_capacity=1)

        resp = api.create_route_stop(
            route["id"],
            create_route_stop_payload(scenario["order_id"], route["version"]),
            HUB,
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED.value, 409)

        assert read_order(scenario["order_id"])["order_pallets"] == 2
        assert read_route(route["id"])["stop_count"] == 0

    def test_adding_a_stop_against_a_stale_route_version_is_rejected(self, api):
        """PRD 2.7: "Adding a stop to a route — the write at `POST
        /delivery-routes/{id}/stops` — requires `expected_route_version`,
        carrying the `version` of the route as the client last observed it. A
        mismatch with the route's current `version` is rejected with
        `ERR_STALE_ROUTE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_route_version_on_a_second_stop_is_rejected
        """
        _pid, _buyer, orders = _two_aggregated_orders()
        route = create_route(pallet_capacity=20)
        stale_version = route["version"]
        validate_success(
            api.create_route_stop(
                route["id"],
                create_route_stop_payload(orders[0]["id"], stale_version),
                HUB,
            ),
            201,
        )

        resp = api.create_route_stop(
            route["id"],
            create_route_stop_payload(
                orders[1]["id"],
                stale_version,
                sequence_no=2,
                planned_arrival_at="2026-09-15T11:00:00Z",
                service_minutes=60,
            ),
            HUB,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_ROUTE_VERSION.value, 412)

        route_now = read_route(route["id"])
        assert route_now["stop_count"] == 1
        assert route_now["pallets_loaded"] == 2
        order_now = read_order(orders[1]["id"])
        assert order_now["fulfillment_status"] == "AGGREGATED"
        assert order_now["route_id"] is None


class TestDispatchDependsOnStaging:
    def test_dispatch_is_refused_while_an_allocation_is_still_reserved(self, api):
        """PRD 3.7: "Dispatch is then a hub administrator's act, and it requires
        the route to be `LOADED`: dispatching a route in any other status is
        refused with `ERR_INVALID_ROUTE_STATE`, and specifically, a route still
        sitting in `PLANNED` because at least one allocation on it remains
        `RESERVED` is refused with `ERR_ALLOCATIONS_NOT_STAGED`."

        Design: Difficulty/cross_entity_state_dependency/route_dispatch_depends_on_allocation_staging_state
        """
        scenario = setup_scenario(stage="booked")

        resp = api.dispatch_route(scenario["route_id"], HUB)
        validate_error(resp, ApiErrorId.ERR_ALLOCATIONS_NOT_STAGED.value, 409)

        assert read_route(scenario["route_id"])["status"] == "PLANNED"
        assert read_allocation(scenario["allocation_id"])["status"] == "RESERVED"
        assert read_order(scenario["order_id"])["fulfillment_status"] == "SCHEDULED"

    def test_the_route_loads_after_the_receipt_and_dispatch_moves_orders_in_transit(
        self, api
    ):
        """PRD 3.7: "It reaches `LOADED` on its own, as §3.6 describes, once it
        has at least one stop and no order on it holds an allocation still
        `RESERVED`."
        PRD 3.7: "On success the route moves `LOADED → DISPATCHED` and every
        order assigned to it moves `SCHEDULED → IN_TRANSIT`."
        PRD 3.6: "Each staged allocation copies the appointment's
        `recorded_temp_c` into its own `staged_temp_c`, and its `temp_excursion`
        flag is set to true exactly when that staged temperature is **greater
        than** the door's `temp_setpoint_c` plus the cold-chain tolerance of 2.0
        degrees Celsius — a reading exactly at setpoint plus tolerance is within
        tolerance and does not flag."

        Design: Difficulty/cross_entity_state_dependency/route_dispatch_depends_on_allocation_staging_state
        """
        scenario = setup_scenario(stage="booked")

        appointment = close_appointment(
            scenario["appointment_id"], "RECEIVED",
            received_pallets=2, recorded_temp_c=1.5,
        )
        assert appointment["status"] == "RECEIVED"
        assert read_route(scenario["route_id"])["status"] == "LOADED"

        route = validate_success(api.dispatch_route(scenario["route_id"], HUB))
        assert route["status"] == "DISPATCHED"

        allocation = read_allocation(scenario["allocation_id"])
        assert allocation["status"] == "STAGED"
        assert allocation["staged_temp_c"] == 1.5
        assert allocation["temp_excursion"] is False
        assert read_order(scenario["order_id"])["fulfillment_status"] == "IN_TRANSIT"

    def test_dispatching_an_already_dispatched_route_is_refused(self, api):
        """PRD 3.7: "Dispatch is then a hub administrator's act, and it requires
        the route to be `LOADED`: dispatching a route in any other status is
        refused with `ERR_INVALID_ROUTE_STATE`, and specifically, a route still
        sitting in `PLANNED` because at least one allocation on it remains
        `RESERVED` is refused with `ERR_ALLOCATIONS_NOT_STAGED`."

        Design: Corner/errors/dispatching_an_already_dispatched_route_returns_invalid_route_state
        """
        scenario = setup_scenario(stage="in_transit")

        resp = api.dispatch_route(scenario["route_id"], HUB)
        validate_error(resp, ApiErrorId.ERR_INVALID_ROUTE_STATE.value, 409)

        assert read_route(scenario["route_id"])["status"] == "DISPATCHED"
        assert read_order(scenario["order_id"])["fulfillment_status"] == "IN_TRANSIT"


class TestDeliveryRecording:
    def test_a_delivery_record_naming_another_orders_allocation_is_refused(self, api):
        """PRD 3.7: "The order must be `IN_TRANSIT`, else
        `ERR_INVALID_ORDER_STATE`; every referenced allocation must belong to a
        demand line of the order named in the request path, else
        `ERR_ALLOCATION_NOT_FOUND`; and each `delivered_quantity` must lie
        between 0 and the referenced allocation's reserved `quantity` inclusive,
        else `ERR_INVALID_REQUEST`."

        Design: Corner/endpoints/delivery_record_rejects_an_allocation_from_another_order
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        pid = onboarded["producer_id"]
        create_listed_product(pid, quantity_offered=200)
        buyer = create_buyer()

        first_order = create_draft_order(buyer["id"])
        first_line = add_order_line(
            first_order["id"], buyer["id"], quantity_requested=60
        )
        validate_success(api.aggregate_order(first_order["id"], HUB))
        first_allocation = allocations_for_line(first_line["id"])[0]

        second_order = create_draft_order(buyer["id"])
        second_line = add_order_line(
            second_order["id"], buyer["id"], quantity_requested=30
        )
        validate_success(api.aggregate_order(second_order["id"], HUB))
        second_allocation = allocations_for_line(second_line["id"])[0]

        route = create_route(pallet_capacity=20)
        validate_success(
            api.create_route_stop(
                route["id"],
                create_route_stop_payload(first_order["id"], route["version"]),
                HUB,
            ),
            201,
        )
        slot = create_dock_slot(pallet_capacity=12, sanitation_buffer_minutes=45)
        appointment = book_appointment(slot["id"], pid, pallets=2)
        close_appointment(
            appointment["id"], "RECEIVED", received_pallets=2, recorded_temp_c=1.5
        )
        validate_success(api.dispatch_route(route["id"], HUB))

        resp = api.record_delivery(
            first_order["id"],
            {
                "line_receipts": [
                    {"allocation_id": second_allocation["id"], "delivered_quantity": 30}
                ]
            },
            HUB,
        )
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_NOT_FOUND.value, 404)

        assert read_order(first_order["id"])["fulfillment_status"] == "IN_TRANSIT"
        untouched = read_allocation(second_allocation["id"])
        assert untouched["delivered_quantity"] == 0
        assert untouched["status"] == "RESERVED"
        assert read_allocation(first_allocation["id"])["status"] == "STAGED"

    def test_the_route_completes_once_every_assigned_order_is_delivered(self, api):
        """PRD 3.7: "Finally, when every order assigned to the route has reached
        `DELIVERED`, the route advances `DISPATCHED → COMPLETED` without anyone
        asking it to."
        PRD 3.7: "Each demand line then recomputes `quantity_delivered` from its
        allocations, and a line with any delivered units at all moves
        `ALLOCATED → DELIVERED` or `SHORT → DELIVERED` according to where it
        stood."

        Design: Corner/state_machines/route_auto_completes_when_every_assigned_order_is_delivered
        """
        scenario = setup_scenario(stage="in_transit")

        data = validate_success(
            api.record_delivery(
                scenario["order_id"],
                {
                    "line_receipts": [
                        {
                            "allocation_id": scenario["allocation_id"],
                            "delivered_quantity": 60,
                        }
                    ]
                },
                HUB,
            )
        )
        assert data["fulfillment_status"] == "DELIVERED"
        assert read_route(scenario["route_id"])["status"] == "COMPLETED"

        allocation = read_allocation(scenario["allocation_id"])
        assert allocation["status"] == "DELIVERED"
        assert allocation["delivered_quantity"] == 60
        line = read_order_line(scenario["order_id"], scenario["line_id"])
        assert line["status"] == "DELIVERED"
        assert line["quantity_delivered"] == 60
