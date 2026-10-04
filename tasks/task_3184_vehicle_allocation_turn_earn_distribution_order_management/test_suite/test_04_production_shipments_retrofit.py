"""Production lifecycle: scheduling, building, shipments, retrofit, cascades (PRD §3.7, §3.8, §3.13)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    config_with,
    create_accepted_order,
    create_aged_inventory_program,
    create_built_order,
    create_carrier,
    create_delivered_order,
    create_scheduled_order,
    create_shipment_payload,
    get_accrual,
    get_dealer_model_line,
    get_success_data,
    make_dealer_headers,
    setup_dealer_run,
    setup_restricted_line,
    validate_error,
    validate_paginated,
    validate_success,
)

ALLOC = TEST_USERS["allocator_headers"]
SCHED = TEST_USERS["scheduler_headers"]
LOGIS = TEST_USERS["logistics_headers"]
COMM = TEST_USERS["commodity_manager_headers"]


class TestShipmentGating:
    def test_shipment_create_requires_built_order(self, api):
        """PRD §3.8: "Once an order is `BUILT`, the coordinator assigns it to a carrier by creating a `Shipment`".
        PRD §2.5: "Target resource is in a state from which the requested transition exists — otherwise `ERR_INVALID_STATE` (409)."

        Design: Difficulty/cross_entity_state_dependency/shipment_pickup_gated_by_order_built_state
        """
        fx = setup_dealer_run(num_dealers=1, base_units=5)
        dealer = fx["dealers"][0]
        order = create_accepted_order(dealer["id"], fx["model_line"]["id"], fx["run"]["id"])
        assert order["state"] == "ACCEPTED"
        carrier = create_carrier(weekly_capacity=3)
        resp = api.create_shipment(
            create_shipment_payload(order["id"], carrier["id"], pickup_week="2026-W36"), LOGIS
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_pickup_before_pickup_week_rejected(self, api):
        """PRD §3.8: "A `PLANNED` shipment can be picked up once the current logical week has reached or passed the `pickup_week`; pickup stamps `picked_up_at` and transitions the shipment `PLANNED → PICKED_UP`. Picking up before the `pickup_week` is `ERR_WINDOW_CLOSED`."

        Design: Difficulty/cross_entity_state_dependency/shipment_pickup_gated_by_order_built_state
        """
        fx = setup_dealer_run(num_dealers=1, base_units=5)
        dealer = fx["dealers"][0]
        # Default logical clock is 2026-09-01 (ISO week 2026-W36); schedule W37, pickup W37.
        order = create_built_order(dealer["id"], fx["model_line"]["id"], fx["run"]["id"],
                                   build_week="2026-W37")
        carrier = create_carrier(weekly_capacity=3)
        shipment = get_success_data(api.create_shipment(
            create_shipment_payload(order["id"], carrier["id"], pickup_week="2026-W37"), LOGIS
        ))
        assert shipment["state"] == "PLANNED"
        resp = api.pickup_shipment(shipment["id"], LOGIS)
        validate_error(resp, ApiErrorId.ERR_WINDOW_CLOSED, 422)


class TestCarrierCapacity:
    def test_at_capacity_week_rejects_second_shipment(self, api):
        """PRD §3.8: "A shipment may be assigned to a carrier for a given `pickup_week` only when the count of that carrier's shipments in `PLANNED` or `PICKED_UP` state with the same `pickup_week` is strictly less than the carrier's `weekly_capacity`. An at-capacity week rejects the assignment with `ERR_CARRIER_CAPACITY`."

        Design: Difficulty/boundary_precision_check/carrier_capacity_strict_less_than_boundary
        """
        fx = setup_dealer_run(num_dealers=1, base_units=5)
        dealer = fx["dealers"][0]
        line = fx["model_line"]
        run = fx["run"]
        order1 = create_built_order(dealer["id"], line["id"], run["id"], build_week="2026-W36")
        order2 = create_built_order(dealer["id"], line["id"], run["id"], build_week="2026-W36")
        carrier = create_carrier(weekly_capacity=1)
        first = api.create_shipment(
            create_shipment_payload(order1["id"], carrier["id"], pickup_week="2026-W36"), LOGIS
        )
        validate_success(first, 201)
        second = api.create_shipment(
            create_shipment_payload(order2["id"], carrier["id"], pickup_week="2026-W36"), LOGIS
        )
        validate_error(second, ApiErrorId.ERR_CARRIER_CAPACITY, 422)

    def test_adjacent_week_bucket_does_not_collide(self, api):
        """PRD §3.8: "A shipment may be assigned to a carrier for a given `pickup_week` only when the count of that carrier's shipments in `PLANNED` or `PICKED_UP` state with the same `pickup_week` is strictly less than the carrier's `weekly_capacity`."

        Design: Difficulty/resource_temporal_overlap/carrier_weekly_bucket_capacity_not_interval
        """
        fx = setup_dealer_run(num_dealers=1, base_units=5)
        dealer = fx["dealers"][0]
        line = fx["model_line"]
        run = fx["run"]
        order1 = create_built_order(dealer["id"], line["id"], run["id"], build_week="2026-W36")
        order2 = create_built_order(dealer["id"], line["id"], run["id"], build_week="2026-W37")
        carrier = create_carrier(weekly_capacity=1)
        validate_success(api.create_shipment(
            create_shipment_payload(order1["id"], carrier["id"], pickup_week="2026-W36"), LOGIS
        ), 201)
        # Adjacent week is a separate bucket: succeeds despite W36 being at capacity.
        validate_success(api.create_shipment(
            create_shipment_payload(order2["id"], carrier["id"], pickup_week="2026-W37"), LOGIS
        ), 201)

    def test_same_week_bucket_at_capacity_rejects(self, api):
        """PRD §3.8: "A shipment may be assigned to a carrier for a given `pickup_week` only when the count of that carrier's shipments in `PLANNED` or `PICKED_UP` state with the same `pickup_week` is strictly less than the carrier's `weekly_capacity`. An at-capacity week rejects the assignment with `ERR_CARRIER_CAPACITY`."

        Design: Difficulty/resource_temporal_overlap/carrier_weekly_bucket_capacity_not_interval
        """
        fx = setup_dealer_run(num_dealers=1, base_units=5)
        dealer = fx["dealers"][0]
        line = fx["model_line"]
        run = fx["run"]
        order1 = create_built_order(dealer["id"], line["id"], run["id"], build_week="2026-W36")
        order2 = create_built_order(dealer["id"], line["id"], run["id"], build_week="2026-W36")
        carrier = create_carrier(weekly_capacity=1)
        validate_success(api.create_shipment(
            create_shipment_payload(order1["id"], carrier["id"], pickup_week="2026-W36"), LOGIS
        ), 201)
        resp = api.create_shipment(
            create_shipment_payload(order2["id"], carrier["id"], pickup_week="2026-W36"), LOGIS
        )
        validate_error(resp, ApiErrorId.ERR_CARRIER_CAPACITY, 422)


class TestDeliveryCascade:
    def test_deliver_cascades_order_and_sales_credit(self, api):
        """PRD §3.8: "A `PICKED_UP` shipment can be marked delivered; delivery stamps `delivered_at` and cascades the linked order `BUILT → DELIVERED`, setting the order's `delivered_at` to the shipment's `delivered_at`. The cascade recomputes the dealer's `reported_sales_units` for the line (chronological inclusion by `delivered_at`)".

        Design: Difficulty/transitive_cascade/shipment_deliver_cascades_order_sales_credit_incentive
        """
        fx = setup_dealer_run(num_dealers=1, base_units=5)
        dealer = fx["dealers"][0]
        line = fx["model_line"]
        order, shipment, _carrier = create_delivered_order(
            dealer["id"], line["id"], fx["run"]["id"], build_week="2026-W36"
        )
        assert shipment["state"] == "DELIVERED"
        assert order["state"] == "DELIVERED"
        assert order["delivered_at"] == shipment["delivered_at"]
        dml = get_dealer_model_line(dealer["id"], line["id"])
        assert dml["reported_sales_units"] == 1

    def test_delivered_order_cannot_be_cancelled(self, api):
        """PRD §3.6: "Cancelling from any other state is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/order_cancel_from_delivered_returns_invalid_state
        """
        fx = setup_dealer_run(num_dealers=1, base_units=3)
        dealer = fx["dealers"][0]
        order, _shipment, _carrier = create_delivered_order(
            dealer["id"], fx["model_line"]["id"], fx["run"]["id"], build_week="2026-W36"
        )
        assert order["state"] == "DELIVERED"
        resp = api.cancel_order(order["id"], make_dealer_headers(dealer["id"]),
                                {"cancel_reason": "too late"})
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        after = get_success_data(api.get_order(order["id"], ALLOC))
        assert after["state"] == "DELIVERED"


class TestParallelBuildState:
    def test_delivered_order_can_still_be_pending_retrofit(self, api):
        """PRD §3.7: "On a successful `WITHOUT_FEATURE` build, the order's `build_state` transitions to `PENDING_RETROFIT` and the commodity code is dropped from the built configuration."
        PRD §3.8: "A `PICKED_UP` shipment can be marked delivered; delivery stamps `delivered_at` and cascades the linked order `BUILT → DELIVERED`".

        Design: Difficulty/non_linear_state_machine/vehicle_order_parallel_build_state_dimension
        """
        fx = setup_restricted_line(install_rate_pct=50, allow_partial_build=True, base_units=4)
        dealer = fx["dealer"]
        line = fx["model_line"]
        run = fx["run"]
        code = fx["commodity"]["code"]
        create_accepted_order(dealer["id"], line["id"], run["id"], configuration=config_with([]))
        order = create_scheduled_order(
            dealer["id"], line["id"], run["id"], configuration=config_with([code])
        )
        built = validate_success(
            api.build_order(order["id"], {"build_mode": "WITHOUT_FEATURE"}, SCHED), 200
        )
        assert built["state"] == "BUILT"
        assert built["build_state"] == "PENDING_RETROFIT"
        # Deliver the unit while it is still pending retrofit.
        carrier = create_carrier()
        shipment = get_success_data(api.create_shipment(
            create_shipment_payload(order["id"], carrier["id"], pickup_week="2026-W36"), LOGIS
        ))
        get_success_data(api.pickup_shipment(shipment["id"], LOGIS))
        get_success_data(api.deliver_shipment(shipment["id"], LOGIS))
        after = get_success_data(api.get_order(order["id"], ALLOC))
        assert after["state"] == "DELIVERED"
        assert after["build_state"] == "PENDING_RETROFIT"

    def test_retrofit_blocked_then_completes_after_resolve(self, api):
        """PRD §3.7: "A retrofit attempted while the omitting restriction is still `ACTIVE` is rejected with `ERR_RETROFIT_BLOCKED`."
        PRD §3.7: "Completing the retrofit transitions the order's `build_state` to `RETROFITTED` and creates a child `VehicleOrder` row whose `retrofit_of_order_id` points back to the original; the child is immediately `ACCEPTED` but does not consume allocation pool (its `consumed_units` is 0)."

        Design: Difficulty/non_linear_state_machine/vehicle_order_parallel_build_state_dimension
        """
        fx = setup_restricted_line(install_rate_pct=50, allow_partial_build=True, base_units=4)
        dealer = fx["dealer"]
        line = fx["model_line"]
        run = fx["run"]
        code = fx["commodity"]["code"]
        create_accepted_order(dealer["id"], line["id"], run["id"], configuration=config_with([]))
        order = create_scheduled_order(
            dealer["id"], line["id"], run["id"], configuration=config_with([code])
        )
        get_success_data(api.build_order(order["id"], {"build_mode": "WITHOUT_FEATURE"}, SCHED))
        blocked = api.retrofit_order(order["id"], SCHED)
        validate_error(blocked, ApiErrorId.ERR_RETROFIT_BLOCKED, 409)
        get_success_data(api.resolve_commodity(fx["commodity"]["id"], COMM))
        done = validate_success(api.retrofit_order(order["id"], SCHED), 200)
        assert done["build_state"] == "RETROFITTED"
        children, _meta = validate_paginated(
            api.list_orders(ALLOC, params={"retrofit_of_order_id": order["id"]})
        )
        assert len(children) == 1
        assert children[0]["retrofit_of_order_id"] == order["id"]
        assert children[0]["state"] == "ACCEPTED"
        assert children[0]["consumed_units"] == 0


class TestCommodityResolveCascade:
    def test_resolve_expires_active_restrictions(self, api):
        """PRD §3.2: "resolving cascades every `ACTIVE` restriction on that commodity to `EXPIRED`."

        Design: Difficulty/transitive_cascade/commodity_resolve_cascades_restriction_expiry_and_unblocks_retrofit
        """
        fx = setup_restricted_line(install_rate_pct=50, allow_partial_build=True, base_units=4)
        resolved = validate_success(api.resolve_commodity(fx["commodity"]["id"], COMM), 200)
        assert resolved["status"] == "RESOLVED"
        restriction = get_success_data(
            api.get_commodity_restriction(fx["restriction"]["id"], COMM)
        )
        assert restriction["status"] == "EXPIRED"

    def test_resolve_unblocks_pending_retrofit(self, api):
        """PRD §3.7: "A `ProductionScheduler` completes the retrofit once the omitting restriction is no longer `ACTIVE` — either because the commodity was resolved, or because the logical clock has moved past the restriction's `effective_to`, or because the restriction has been superseded by one whose window has not yet started."

        Design: Difficulty/transitive_cascade/commodity_resolve_cascades_restriction_expiry_and_unblocks_retrofit
        """
        fx = setup_restricted_line(install_rate_pct=50, allow_partial_build=True, base_units=4)
        dealer = fx["dealer"]
        line = fx["model_line"]
        run = fx["run"]
        code = fx["commodity"]["code"]
        create_accepted_order(dealer["id"], line["id"], run["id"], configuration=config_with([]))
        order = create_scheduled_order(
            dealer["id"], line["id"], run["id"], configuration=config_with([code])
        )
        get_success_data(api.build_order(order["id"], {"build_mode": "WITHOUT_FEATURE"}, SCHED))
        validate_error(api.retrofit_order(order["id"], SCHED), ApiErrorId.ERR_RETROFIT_BLOCKED, 409)
        get_success_data(api.resolve_commodity(fx["commodity"]["id"], COMM))
        done = validate_success(api.retrofit_order(order["id"], SCHED), 200)
        assert done["build_state"] == "RETROFITTED"


class TestDeliveryCascadeIncentives:
    def test_delivery_recomputes_provisional_accrual(self, api):
        """PRD §3.8: "The cascade recomputes the dealer's `reported_sales_units` for the line (chronological inclusion by `delivered_at`), recomputes the dealer's `avg_inventory_units`, and recomputes the provisional incentive accrual."
        PRD §3.12: "The provisional variant runs on every order `DELIVERED` event and is readable through the program's per-dealer accruals listing".

        Design: Difficulty/transitive_cascade/shipment_deliver_cascades_order_sales_credit_incentive
        """
        fx = setup_dealer_run(num_dealers=1, base_units=5)
        dealer = fx["dealers"][0]
        line = fx["model_line"]
        prog = create_aged_inventory_program(line["id"], age_threshold_days=45,
                                             credit_per_unit_cents=10000,
                                             tier2_age_days=60,
                                             tier2_credit_per_unit_cents=25000)
        before = get_accrual(prog["id"], dealer["id"])
        assert before["amount_cents"] == 0
        order, _shipment, _carrier = create_delivered_order(
            dealer["id"], line["id"], fx["run"]["id"], build_week="2026-W36"
        )
        after = get_accrual(prog["id"], dealer["id"])
        # Scheduled 2026-W36 and delivered within days: age_days < 45 pays 0,
        # but the provisional variant must have been recomputed for this dealer.
        assert after["amount_cents"] == 0
        assert after["variant"] == "provisional"
        assert order["state"] == "DELIVERED"


class TestCarrierCapacityBoundary:
    def test_first_assignment_succeeds_when_count_below_capacity(self, api):
        """PRD §3.8: "A shipment may be assigned to a carrier for a given `pickup_week` only when the count of that carrier's shipments in `PLANNED` or `PICKED_UP` state with the same `pickup_week` is strictly less than the carrier's `weekly_capacity`."

        Design: Difficulty/boundary_precision_check/carrier_capacity_strict_less_than_boundary
        """
        fx = setup_dealer_run(num_dealers=1, base_units=5)
        dealer = fx["dealers"][0]
        order = create_built_order(dealer["id"], fx["model_line"]["id"], fx["run"]["id"],
                                   build_week="2026-W36")
        carrier = create_carrier(weekly_capacity=1)
        # count 0 < capacity 1: the boundary's admissible side.
        shipment = validate_success(api.create_shipment(
            create_shipment_payload(order["id"], carrier["id"], pickup_week="2026-W36"), LOGIS
        ), 201)
        assert shipment["state"] == "PLANNED"
