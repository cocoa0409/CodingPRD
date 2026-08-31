"""Compensating cascades: the five-hop suspension unwind, the four-hop dock
no-show unwind, and the conservation invariants they must preserve."""

from test_helpers import (
    CLOCK_BASE,
    HUB,
    assert_product_availability,
    book_appointment,
    create_dock_slot,
    create_listed_product,
    onboard_active_producer,
    read_allocation,
    read_dock_appointment,
    read_dock_slot,
    read_order,
    read_order_line,
    read_producer,
    read_product,
    read_route,
    set_clock,
    setup_scenario,
    validate_success,
)


class TestProducerSuspensionCascade:
    def test_suspension_delists_the_catalog_and_reverses_the_reservation(self, api):
        """PRD 3.2: "**Hop 1**: the producer's `suspension_count` is incremented
        by 1."
        PRD 3.2: "**Hop 2**, caused by hop 1: every catalog item of that
        producer currently `LISTED` becomes `DELISTED` and its
        `quantity_offered` is set to 0, which drives its available pool to 0."
        PRD 3.2: "**Hop 3**, caused by hop 2: every allocation still `RESERVED`
        that draws on one of those delisted items, and whose order sits in
        either `AGGREGATED` or `SCHEDULED`, moves `RESERVED → REVERSED`, and the
        item's `quantity_committed` is decremented by that allocation's
        quantity."

        Design: Difficulty/transitive_cascade/producer_suspension_five_hop_delist_reverse_reprice_detach_cascade
        """
        scenario = setup_scenario(stage="scheduled")

        validate_success(
            api.review_producer(
                scenario["producer_id"],
                {"decision": "SUSPEND", "note": "failed unannounced audit"},
                HUB,
            )
        )

        producer = read_producer(scenario["producer_id"])
        assert producer["onboarding_status"] == "SUSPENDED"
        assert producer["suspension_count"] == 1

        product = read_product(scenario["product_id"])
        assert product["status"] == "DELISTED"
        assert product["quantity_offered"] == 0
        assert product["quantity_committed"] == 0
        assert product["quantity_available"] == 0
        assert_product_availability(product)

        assert read_allocation(scenario["allocation_id"])["status"] == "REVERSED"

    def test_suspension_reprices_the_order_and_detaches_it_from_the_route(self, api):
        """PRD 3.2: "**Hop 4**, caused by hop 3: every demand line touched by
        those reversals recomputes its allocated quantity — a line left with
        nothing allocated returns to `PENDING`, and a line left with some but
        not all of its requested quantity becomes `SHORT`."
        PRD 3.2: "**Hop 5**, caused by hop 4: every order touched by those lines
        re-prices under the provisional valuation described in §3.5, and an
        order whose lines have all fallen back to `PENDING` returns to `DRAFT`,
        is detached from its route by clearing `route_id`, `route_sequence_no`,
        `planned_arrival_at` and `service_minutes`, and the route it left
        recomputes its `stop_count` and `pallets_loaded`."

        Design: Difficulty/transitive_cascade/producer_suspension_five_hop_delist_reverse_reprice_detach_cascade
        """
        scenario = setup_scenario(stage="scheduled")

        validate_success(
            api.review_producer(
                scenario["producer_id"],
                {"decision": "SUSPEND", "note": "failed unannounced audit"},
                HUB,
            )
        )

        line = read_order_line(scenario["order_id"], scenario["line_id"])
        assert line["status"] == "PENDING"
        assert line["quantity_allocated"] == 0
        assert line["line_total_cents"] == 0

        order = read_order(scenario["order_id"])
        assert order["fulfillment_status"] == "DRAFT"
        assert order["route_id"] is None
        assert order["route_sequence_no"] is None
        assert order["order_total_cents"] == 0
        assert order["hub_margin_cents"] == 0
        assert order["margin_tier_bp"] == 0

        route = read_route(scenario["route_id"])
        assert route["stop_count"] == 0
        assert route["pallets_loaded"] == 0

    def test_the_suspension_cascade_is_visible_in_the_same_response_and_on_read(
        self, api
    ):
        """PRD 3.2: "**Hop 1**: the producer's `suspension_count` is incremented
        by 1."
        PRD 3.2: "**Hop 2**, caused by hop 1: every catalog item of that
        producer currently `LISTED` becomes `DELISTED` and its
        `quantity_offered` is set to 0, which drives its available pool to 0."

        Design: Corner/consistency_model/suspension_cascade_is_visible_in_the_same_response_and_immediately_on_read
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        pid = onboarded["producer_id"]
        product = create_listed_product(pid, quantity_offered=100)

        data = validate_success(
            api.review_producer(
                pid,
                {"decision": "SUSPEND", "note": "immediate visibility probe"},
                HUB,
            )
        )
        assert data["onboarding_status"] == "SUSPENDED"
        assert data["suspension_count"] == 1

        product_now = validate_success(api.get_product(product["id"], HUB))
        assert product_now["status"] == "DELISTED"
        assert product_now["quantity_offered"] == 0


class TestDockNoShowCascade:
    def test_a_no_show_releases_the_door_and_reverses_the_reservation(self, api):
        """PRD 3.6: "**Hop 1**: the door's `pallets_booked` is recomputed
        without this appointment and its derived status refreshed, releasing the
        space."
        PRD 3.6: "**Hop 2**, caused by hop 1 releasing that drop: every
        allocation still `RESERVED` whose catalog item belongs to this
        appointment's producer, and whose order sits in either `AGGREGATED` or
        `SCHEDULED`, moves `RESERVED → REVERSED`, with the item's
        `quantity_committed` decremented by the allocation's quantity and its
        available pool re-derived."

        Design: Difficulty/transitive_cascade/dock_no_show_four_hop_release_reprice_detach_cascade
        """
        scenario = setup_scenario(stage="booked")

        validate_success(
            api.close_appointment(
                scenario["appointment_id"], {"outcome": "NO_SHOW"}, HUB
            )
        )

        assert read_dock_appointment(scenario["appointment_id"])["status"] == "NO_SHOW"
        slot = read_dock_slot(scenario["dock_slot_id"])
        assert slot["pallets_booked"] == 0
        assert slot["status"] == "OPEN"

        assert read_allocation(scenario["allocation_id"])["status"] == "REVERSED"
        product = read_product(scenario["product_id"])
        assert product["status"] == "LISTED", (
            "a no-show never delists the catalog item"
        )
        assert product["quantity_offered"] == 100
        assert product["quantity_committed"] == 0
        assert product["quantity_available"] == 100

    def test_a_no_show_returns_the_order_to_draft_and_frees_the_route(self, api):
        """PRD 3.6: "**Hop 3**, caused by hop 2: each affected demand line
        recomputes its allocated quantity and moves `ALLOCATED → SHORT` when
        some units survive, or `ALLOCATED → PENDING` or `SHORT → PENDING` when
        none do."
        PRD 3.6: "**Hop 4**, caused by hop 3: each affected order re-prices
        under the provisional valuation, and an order left with no allocated
        units at all falls back `AGGREGATED → DRAFT`, is detached from its route
        by clearing `route_id`, `route_sequence_no`, `planned_arrival_at` and
        `service_minutes`, and the route recomputes its `stop_count` and
        `pallets_loaded`."

        Design: Difficulty/transitive_cascade/dock_no_show_four_hop_release_reprice_detach_cascade
        """
        scenario = setup_scenario(stage="booked")

        validate_success(
            api.close_appointment(
                scenario["appointment_id"], {"outcome": "NO_SHOW"}, HUB
            )
        )

        line = read_order_line(scenario["order_id"], scenario["line_id"])
        assert line["status"] == "PENDING"
        assert line["quantity_allocated"] == 0

        order = read_order(scenario["order_id"])
        assert order["fulfillment_status"] == "DRAFT"
        assert order["route_id"] is None

        route = read_route(scenario["route_id"])
        assert route["stop_count"] == 0
        assert route["pallets_loaded"] == 0


class TestUnitConservation:
    def _aggregated_order_with_a_booked_drop(self):
        scenario = setup_scenario(stage="aggregated")
        slot = create_dock_slot(pallet_capacity=12, sanitation_buffer_minutes=45)
        appointment = book_appointment(slot["id"], scenario["producer_id"], pallets=2)
        scenario["dock_slot_id"] = slot["id"]
        scenario["appointment_id"] = appointment["id"]
        return scenario

    def test_the_no_show_reversal_restores_the_available_pool_exactly(self, api):
        """PRD 3.3: "`quantity_offered` is what the producer published.
        `quantity_committed` is what allocations currently hold — specifically,
        the summed quantity of every allocation of this item in `RESERVED`,
        `STAGED` or `DELIVERED`. `quantity_available` is the offered quantity
        minus the committed quantity, floored at zero, and it is the pool the
        allocation waterfall draws from."
        PRD 3.6: "**Hop 2**, caused by hop 1 releasing that drop: every
        allocation still `RESERVED` whose catalog item belongs to this
        appointment's producer, and whose order sits in either `AGGREGATED` or
        `SCHEDULED`, moves `RESERVED → REVERSED`, with the item's
        `quantity_committed` decremented by the allocation's quantity and its
        available pool re-derived."

        Design: Difficulty/compensating_invariant/no_show_reversal_conserves_product_physical_units
        """
        scenario = self._aggregated_order_with_a_booked_drop()
        before = read_product(scenario["product_id"])
        assert before["quantity_committed"] == 60
        assert before["quantity_available"] == 40

        validate_success(
            api.close_appointment(
                scenario["appointment_id"], {"outcome": "NO_SHOW"}, HUB
            )
        )

        after = read_product(scenario["product_id"])
        assert after["quantity_offered"] == 100
        assert after["quantity_committed"] == 0
        assert after["quantity_available"] == 100
        assert after["status"] == "LISTED"
        assert_product_availability(after)

    def test_the_reversal_leaves_no_drift_in_the_offered_unit_identity(self, api):
        """PRD 2.10: "In every case the rule is the same: each record the
        cascade touches has its `updated_at` refreshed and its `version`
        incremented by 1, and every derived quantity and money field on every
        touched record is recomputed from the surviving rows rather than patched
        incrementally. A cascade never leaves a parent's rollup disagreeing with
        the children it was computed from."
        PRD 3.3: "`quantity_available` is the offered quantity minus the
        committed quantity, floored at zero, and it is the pool the allocation
        waterfall draws from."

        Design: Difficulty/compensating_invariant/no_show_reversal_conserves_product_physical_units
        """
        scenario = self._aggregated_order_with_a_booked_drop()
        committed_total = scenario["order"]["order_total_cents"]
        assert committed_total == 124200
        assert_product_availability(read_product(scenario["product_id"]))

        validate_success(
            api.close_appointment(
                scenario["appointment_id"], {"outcome": "NO_SHOW"}, HUB
            )
        )

        product = read_product(scenario["product_id"])
        assert (
            product["quantity_offered"]
            == product["quantity_available"] + product["quantity_committed"]
        ), "offered units must equal available plus committed after the unwind"

        allocation = read_allocation(scenario["allocation_id"])
        assert allocation["status"] == "REVERSED"
        assert allocation["quantity"] == 60
        assert (
            read_order_line(scenario["order_id"], scenario["line_id"])[
                "quantity_allocated"
            ]
            == 0
        )
        assert read_order(scenario["order_id"])["order_total_cents"] == 0
