"""Compensating actions that must return a running total to its opening value.

A withdrawn consignment hands back its reconditioning spend by appending a
negative row rather than deleting the positive one, and a recalled haul gives the
origin branch back exactly the one unit it took.
"""

from test_helpers import (
    ApiErrorId,
    ConditionStatus,
    ConsignmentStatus,
    EntryType,
    FleetStatus,
    OrderStatus,
    SourceEntityType,
    fixtures,
    make_remarketing_manager_headers,
    validate_error,
)
from test_helpers.assertions import (
    assert_instant_equals,
    entries_of_type,
    sum_amount,
)


def _reconditioned_car_held_for_sale(client, world):
    """A risk car whose consignment booked a spend that rounds half up."""
    built = fixtures.setup_earning_vehicle(
        client,
        world,
        market_code="ATL",
        program_key="RSK",
        odometer_km=47000,
        in_service_clock="2026-01-15T00:00:00Z",
    )
    fixtures.set_clock(client, "2026-09-15T00:00:00Z")
    consignment = fixtures.setup_reconditioned_consignment(
        client,
        world,
        built["vehicle"]["id"],
        recondition_authorized_cents=90000,
        recondition_actual_cents=45500,
    )
    return {"vehicle_id": built["vehicle"]["id"], "consignment": consignment}


class TestReconditionReversal:
    """The reversal is an appended negative row, and it lands exactly once."""

    def test_the_booked_spend_rounds_half_up_before_the_reversal_is_owed(
        self, client, world
    ):
        """Forty-five thousand five hundred cents loads to a half-cent boundary.

        PRD 3.8: "Booking the spend computes `recondition_loaded_cents` as
        `recondition_actual_cents` multiplied by 1.075, rounded half up — a 7.5
        percent overhead loading for shop administration — posts a ledger line of
        `entry_type` `RECONDITION_COST` for a positive `amount_cents` equal to
        `recondition_loaded_cents` with `source_entity_type` `Consignment`,
        recomputes the vehicle's `total_recondition_cents`, drives the vehicle's
        condition `RECONDITIONING → RECONDITIONED`, and increments both versions
        by 1."
        PRD 2.6: "Wherever a monetary result is derived from a multiplication
        involving a fractional rate or factor, the result is rounded to the
        nearest whole cent using **round half up** — a residue of exactly half a
        cent rounds away from zero, upward in magnitude."

        Design: Difficulty/compensating_invariant/recondition_ledger_returns_to_zero_after_consignment_withdrawal
        """
        built = _reconditioned_car_held_for_sale(client, world)
        consignment = built["consignment"]

        assert consignment["status"] == ConsignmentStatus.RECONDITION_PENDING
        assert consignment["recondition_actual_cents"] == 45500
        assert consignment["recondition_loaded_cents"] == 48913
        assert consignment["floor_price_cents"] == 1425000

        vehicle = fixtures.read_vehicle(client, built["vehicle_id"])
        assert vehicle["fleet_status"] == FleetStatus.HELD_FOR_SALE
        assert vehicle["condition_status"] == ConditionStatus.RECONDITIONED
        assert vehicle["net_book_value_at_hold_cents"] == 1900000
        assert vehicle["total_recondition_cents"] == 48913
        assert fixtures.census(client, world.market_id("ATL")) == 0

        rows = fixtures.read_ledger(client, built["vehicle_id"])
        assert len(rows) == 5
        assert sum_amount(entries_of_type(rows, EntryType.CAPITALIZATION)) == 2800000
        assert sum_amount(entries_of_type(rows, EntryType.PREP_COST)) == 44000
        assert sum_amount(entries_of_type(rows, EntryType.RECONDITION_COST)) == 48913

    def test_withdrawal_appends_a_negative_row_instead_of_deleting_the_cost(
        self, client, world
    ):
        """Six rows remain and the two recondition lines cancel to zero.

        PRD 3.8: "When the consignment's `recondition_loaded_cents` is not null, a
        compensating ledger line of `entry_type` `RECONDITION_REVERSAL` is posted
        for a **negative** `amount_cents` equal to `recondition_loaded_cents` with
        `source_entity_type` `Consignment`, so the vehicle's recomputed
        `total_recondition_cents` returns to its pre-consignment value of zero;
        withdrawing from `DRAFT`, where no spend was ever booked, posts nothing."
        PRD 2.10: "When a cost has to be undone — the reconditioning spend on a
        withdrawn consignment is the canonical case — the system posts a new,
        oppositely signed line rather than deleting or amending the original, so
        that the arithmetic sum of the stream always equals the unit's current
        cost basis."

        Design: Difficulty/compensating_invariant/recondition_ledger_returns_to_zero_after_consignment_withdrawal
        """
        built = _reconditioned_car_held_for_sale(client, world)

        withdrawn = fixtures.withdraw_consignment(
            client, built["consignment"]["id"]
        )
        assert withdrawn["status"] == ConsignmentStatus.WITHDRAWN

        rows = fixtures.read_ledger(client, built["vehicle_id"])
        assert len(rows) == 6
        cost = entries_of_type(rows, EntryType.RECONDITION_COST)
        reversal = entries_of_type(rows, EntryType.RECONDITION_REVERSAL)
        assert len(cost) == 1
        assert len(reversal) == 1
        assert reversal[0]["amount_cents"] == -48913
        assert reversal[0]["source_entity_type"] == SourceEntityType.CONSIGNMENT
        assert sum_amount(cost + reversal) == 0

        assert (
            fixtures.read_vehicle(client, built["vehicle_id"])[
                "total_recondition_cents"
            ]
            == 0
        )

    def test_withdrawal_restores_the_vehicle_and_the_rentable_census(
        self, client, world
    ):
        """The car is sound and rentable again and the market's count is restored.

        PRD 3.8: "Withdrawal drives the vehicle `HELD_FOR_SALE → IN_SERVICE`,
        clearing both `held_for_sale_at` and `net_book_value_at_hold_cents` back to
        null — which restarts the holding clock of §3.5 — and increments the
        vehicle's current market's `in_service_unit_count` by 1, exactly undoing
        the decrement the consignment applied."
        PRD 3.8: "And when the vehicle's `condition_status` is `RECONDITIONING` or
        `RECONDITIONED`, it is set back to `SOUND`; a car withdrawn mid-repair is
        treated as sound again, since the consignment that authorized the work no
        longer exists."

        Design: Difficulty/compensating_invariant/recondition_ledger_returns_to_zero_after_consignment_withdrawal
        """
        built = _reconditioned_car_held_for_sale(client, world)
        before = fixtures.read_valuation(client, built["vehicle_id"])
        assert before["net_book_value_cents"] == 1900000

        fixtures.withdraw_consignment(client, built["consignment"]["id"])

        vehicle = fixtures.read_vehicle(client, built["vehicle_id"])
        assert vehicle["fleet_status"] == FleetStatus.IN_SERVICE
        assert vehicle["condition_status"] == ConditionStatus.SOUND
        assert vehicle["held_for_sale_at"] is None
        assert vehicle["net_book_value_at_hold_cents"] is None
        assert fixtures.census(client, world.market_id("ATL")) == 1

        after = fixtures.read_valuation(client, built["vehicle_id"])
        assert after["net_book_value_cents"] == 1900000

    def test_the_compensation_is_applied_exactly_once(self, client, world):
        """A second withdrawal is refused and never overshoots the reversal.

        PRD 3.8: "Withdrawal is the compensating action, available to a
        `RemarketingManager` from `DRAFT`, from `RECONDITION_PENDING` and from
        `LISTED`; a consignment in `SOLD_PENDING_SETTLEMENT` or `SETTLED` may
        **not** be withdrawn, and the attempt is refused with
        `ERR_CONSIGNMENT_INVALID_STATE`."
        PRD 3.8: "Both the vehicle's and the consignment's `version` are
        incremented by 1, and `WITHDRAWN` is terminal."

        Design: Difficulty/compensating_invariant/recondition_ledger_returns_to_zero_after_consignment_withdrawal
        """
        built = _reconditioned_car_held_for_sale(client, world)
        fixtures.withdraw_consignment(client, built["consignment"]["id"])

        validate_error(
            client.withdraw_consignment(
                built["consignment"]["id"], make_remarketing_manager_headers()
            ),
            ApiErrorId.CONSIGNMENT_INVALID_STATE,
        )

        rows = fixtures.read_ledger(client, built["vehicle_id"])
        assert len(rows) == 6
        assert sum_amount(entries_of_type(rows, EntryType.RECONDITION_REVERSAL)) == -48913
        assert (
            fixtures.read_vehicle(client, built["vehicle_id"])[
                "total_recondition_cents"
            ]
            == 0
        )


def _haul_in_flight(client, world):
    """A car dispatched from ATL towards DFW, still between the two cities."""
    built = fixtures.setup_in_service_vehicle(
        client, world, market_code="ATL", program_key="PGM"
    )
    vehicle_id = built["vehicle"]["id"]
    order = fixtures.setup_authorized_order(
        client,
        world,
        vehicle_id,
        destination_code="DFW",
        distance_km=200,
        planned_depart_at="2026-03-01T00:00:00.000Z",
        planned_receive_at="2026-03-05T00:00:00.000Z",
    )
    fixtures.set_clock(client, "2026-03-01T06:00:00Z")
    fixtures.depart_order(client, world, order["id"], "ATL")
    return {"vehicle_id": vehicle_id, "order_id": order["id"]}


class TestTransitCancellationCensus:
    """The census pair sums to one at every observation point."""

    def _pair(self, client, world):
        return (
            fixtures.census(client, world.market_id("ATL")),
            fixtures.census(client, world.market_id("DFW")),
        )

    def test_a_unit_in_flight_belongs_to_no_markets_rentable_census(
        self, client, world
    ):
        """Neither end counts the car while it is on the truck.

        PRD 3.6: "Between departure and arrival the unit belongs to no market's
        rentable census, which is exactly the census hole §2.12 describes."
        PRD 3.6: "Departure stamps `depart_at` from the logical clock, drives the
        vehicle `IN_SERVICE → IN_TRANSIT`, **decrements** the origin market's
        `in_service_unit_count` by 1, and increments both the order's and the
        vehicle's `version` by 1."

        Design: Difficulty/compensating_invariant/market_in_service_census_restored_after_transit_cancellation
        """
        built = _haul_in_flight(client, world)

        order = fixtures.read_order(client, built["order_id"])
        assert order["status"] == OrderStatus.IN_TRANSIT
        assert_instant_equals(order["depart_at"], "2026-03-01T06:00:00.000Z")
        assert order["estimated_transport_cost_cents"] == 61500

        assert (
            fixtures.read_vehicle(client, built["vehicle_id"])["fleet_status"]
            == FleetStatus.IN_TRANSIT
        )
        assert self._pair(client, world) == (0, 0)

    def test_the_recall_gives_the_origin_back_exactly_the_unit_it_took(
        self, client, world
    ):
        """One, not zero and not two, and the destination is never touched.

        PRD 3.6: "From `IN_TRANSIT` it is a genuine **compensating action**: the
        order must be `IN_TRANSIT` and the vehicle must be `IN_TRANSIT`, and the
        cancellation drives the vehicle `IN_TRANSIT → IN_SERVICE` while **leaving
        `current_market_id` unchanged at the origin**, increments the origin
        market's `in_service_unit_count` by 1 so the census returns to exactly its
        pre-departure value, posts **no** `TRANSPORT_COST` ledger line at all —
        the haul was recalled, so no invoice exists — and increments both versions
        by 1."

        Design: Difficulty/compensating_invariant/market_in_service_census_restored_after_transit_cancellation
        """
        built = _haul_in_flight(client, world)

        cancelled = fixtures.cancel_order(client, built["order_id"])
        assert cancelled["status"] == OrderStatus.CANCELLED
        assert cancelled["receive_at"] is None
        assert cancelled["actual_transport_cost_cents"] is None

        vehicle = fixtures.read_vehicle(client, built["vehicle_id"])
        assert vehicle["fleet_status"] == FleetStatus.IN_SERVICE
        assert vehicle["current_market_id"] == world.market_id("ATL")
        assert vehicle["odometer_km"] == 0
        assert self._pair(client, world) == (1, 0)

    def test_the_recalled_haul_books_nothing_at_all(self, client, world):
        """The opening four rows are still the whole ledger after the abort.

        PRD 2.10: "The sign convention is fixed and uniform: a **positive**
        `amount_cents` is a cost debited to the unit's fleet cost basis, and a
        **negative** `amount_cents` is a credit, a recovery or sale proceeds."
        PRD 3.6: "The invoiced figure is what hits the ledger — the estimate
        frozen at draft time is a gate, not a booking."

        Design: Difficulty/compensating_invariant/market_in_service_census_restored_after_transit_cancellation
        """
        built = _haul_in_flight(client, world)
        fixtures.cancel_order(client, built["order_id"])

        rows = fixtures.read_ledger(client, built["vehicle_id"])
        assert len(rows) == 4
        assert entries_of_type(rows, EntryType.TRANSPORT_COST) == []

    def test_a_completed_follow_on_haul_moves_the_pair_rather_than_duplicating_it(
        self, client, world
    ):
        """Five observations, and the two counters always sum to one.

        PRD 3.6: "Receipt stamps `receive_at` from the logical clock, stores
        `actual_transport_cost_cents`, rewrites the vehicle's `current_market_id`
        to the order's `destination_market_id`, replaces the vehicle's
        `odometer_km` with the submitted cumulative reading under the
        anti-regression rule, drives the vehicle `IN_TRANSIT → IN_SERVICE`,
        **increments** the destination market's `in_service_unit_count` by 1, posts
        a ledger line of `entry_type` `TRANSPORT_COST` for a positive
        `amount_cents` equal to `actual_transport_cost_cents` with
        `source_entity_type` `RedistributionOrder`, and increments both the
        order's and the vehicle's `version` by 1."
        PRD 2.12: "A unit in `IN_TRANSIT` is counted by neither its origin nor its
        destination — it deliberately falls out of both censuses for the duration
        of the haul, and reappears at whichever market ends up holding it."

        Design: Difficulty/compensating_invariant/market_in_service_census_restored_after_transit_cancellation
        """
        built = _haul_in_flight(client, world)
        observed = [self._pair(client, world)]

        fixtures.cancel_order(client, built["order_id"])
        observed.append(self._pair(client, world))

        follow_on = fixtures.setup_authorized_order(
            client,
            world,
            built["vehicle_id"],
            destination_code="DFW",
            distance_km=200,
            planned_depart_at="2026-03-10T00:00:00.000Z",
            planned_receive_at="2026-03-14T00:00:00.000Z",
        )
        observed.append(self._pair(client, world))

        fixtures.depart_order(client, world, follow_on["id"], "ATL")
        observed.append(self._pair(client, world))

        received = fixtures.receive_order(
            client,
            world,
            follow_on["id"],
            "DFW",
            actual_transport_cost_cents=61500,
            odometer_km=12000,
        )
        observed.append(self._pair(client, world))

        assert received["status"] == OrderStatus.RECEIVED
        assert observed == [(0, 0), (1, 0), (1, 0), (0, 0), (0, 1)]
        for origin, destination in observed:
            assert origin + destination <= 1

        vehicle = fixtures.read_vehicle(client, built["vehicle_id"])
        assert vehicle["current_market_id"] == world.market_id("DFW")
        assert vehicle["odometer_km"] == 12000

        rows = fixtures.read_ledger(client, built["vehicle_id"])
        assert len(rows) == 5
        transport = entries_of_type(rows, EntryType.TRANSPORT_COST)
        assert len(transport) == 1
        assert transport[0]["amount_cents"] == 61500
        assert transport[0]["source_entity_type"] == SourceEntityType.REDISTRIBUTION_ORDER
