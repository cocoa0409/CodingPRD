"""Multi-term money formulas whose term order is part of the contract.

The disposal net-proceeds calculation rounds each cost line before adding them,
and the redistribution estimate picks its fuel-surcharge tier off the base haul
before the surcharge and the handling flat are added.
"""

from test_helpers import (
    ChannelCode,
    ConsignmentStatus,
    OrderStatus,
    estimated_transport_cost,
    factories,
    fixtures,
    make_fleet_planner_headers,
    make_remarketing_manager_headers,
    validate_success,
)
from test_helpers.assertions import assert_consignment, assert_redistribution_order


def _sold_program_car(client, world):
    """A guaranteed car reconditioned and published on the auction channel."""
    built = fixtures.setup_earning_vehicle(
        client,
        world,
        market_code="ATL",
        program_key="PGM",
        odometer_km=47000,
        rented_days=180,
        available_days=243,
        revenue_cents=1320000,
        in_service_clock="2026-01-15T00:00:00Z",
    )
    fixtures.set_clock(client, "2026-09-15T00:00:00Z")
    consignment = fixtures.consign(
        client, world, built["vehicle"]["id"], channel_code=ChannelCode.AUCTION
    )
    fixtures.authorize_recondition(client, consignment["id"], 50000)
    fixtures.complete_recondition(client, consignment["id"], 45555)
    fixtures.publish_consignment(client, consignment["id"])
    return {"vehicle_id": built["vehicle"]["id"], "consignment_id": consignment["id"]}


class TestConsignmentNetProceeds:
    """Three independently rounded cost lines, then one subtraction."""

    def test_each_cost_line_is_rounded_on_its_own_before_the_summation(
        self, client, world
    ):
        """Fee, hub haul and loaded reconditioning each round to whole cents.

        PRD 3.8: "Three cost lines are then each computed and **rounded
        independently to whole cents before any of them are added together**;
        summing the unrounded lines and rounding once is a different and
        forbidden order that can differ by a cent or more."
        PRD 3.8: "Line one, `channel_fee_cents`, is `gross_proceeds_cents`
        multiplied by the channel's `fee_pct`, rounded half up, plus the
        channel's `fixed_fee_cents`."
        PRD 3.8: "Line two, `transport_to_channel_cents`, is the **vehicle's
        current market's** `transport_hub_distance_km` multiplied by that
        market's `transfer_cost_per_km_cents` multiplied by 1.15, rounded half
        up; the market is read at sale time, so a redistribution completed
        before the car was held for sale genuinely changes this line."

        Design: Difficulty/combinatorial_formula/consignment_net_proceeds_per_line_rounding_before_summation
        """
        built = _sold_program_car(client, world)

        sold = validate_success(
            client.record_sale(
                built["consignment_id"],
                factories.record_sale_payload(2410833),
                make_remarketing_manager_headers(),
            )
        )
        assert_consignment(
            sold,
            {
                "channel_fee_cents": 169650,
                "transport_to_channel_cents": 6613,
                "recondition_loaded_cents": 48972,
                "status": ConsignmentStatus.SOLD_PENDING_SETTLEMENT,
            },
        )
        rounded_line_sum = (
            sold["channel_fee_cents"]
            + sold["transport_to_channel_cents"]
            + sold["recondition_loaded_cents"]
        )
        assert rounded_line_sum == 225235
        assert 2410833 - sold["net_proceeds_cents"] == rounded_line_sum, (
            "the net must be the gross less the sum of the already-rounded lines"
        )

    def test_net_proceeds_and_gain_loss_are_measured_against_the_frozen_hold_value(
        self, client, world
    ):
        """The reserve and the gain both read the value frozen at consignment.

        PRD 3.8: "`net_proceeds_cents` is `gross_proceeds_cents` minus the sum
        of those three rounded lines, and `gain_loss_cents` is
        `net_proceeds_cents` minus the vehicle's frozen
        `net_book_value_at_hold_cents`."
        PRD 3.8: "`floor_price_cents` is the vehicle's
        `net_book_value_at_hold_cents` multiplied by 0.75, rounded half up."
        PRD 3.8: "Recording the sale posts **no** ledger lines whatsoever — the
        four disposal rows post at settlement — and increments the
        consignment's `version` by 1."

        Design: Difficulty/combinatorial_formula/consignment_net_proceeds_per_line_rounding_before_summation
        """
        built = _sold_program_car(client, world)

        held = fixtures.read_vehicle(client, built["vehicle_id"])
        assert held["net_book_value_at_hold_cents"] == 2236000

        sold = validate_success(
            client.record_sale(
                built["consignment_id"],
                factories.record_sale_payload(2410833),
                make_remarketing_manager_headers(),
            )
        )
        assert sold["floor_price_cents"] == 1677000
        assert sold["net_proceeds_cents"] == 2185598
        assert sold["gain_loss_cents"] == -50402
        assert sold["net_proceeds_cents"] != 2185599, (
            "a single rounding of the summed unrounded lines is the forbidden order"
        )

    def test_loaded_reconditioning_carries_the_shop_overhead_factor(
        self, client, world
    ):
        """The booked spend is loaded by 7.5 percent and lands on the ledger.

        PRD 3.8: "Booking the spend computes `recondition_loaded_cents` as
        `recondition_actual_cents` multiplied by 1.075, rounded half up — a 7.5
        percent overhead loading for shop administration — posts a ledger line
        of `entry_type` `RECONDITION_COST` for a positive `amount_cents` equal
        to `recondition_loaded_cents` with `source_entity_type` `Consignment`,
        recomputes the vehicle's `total_recondition_cents`, drives the vehicle's
        condition `RECONDITIONING → RECONDITIONED`, and increments both versions
        by 1."

        Design: Difficulty/combinatorial_formula/consignment_net_proceeds_per_line_rounding_before_summation
        """
        built = _sold_program_car(client, world)

        consignment = fixtures.read_consignment(client, built["consignment_id"])
        assert consignment["recondition_actual_cents"] == 45555
        assert consignment["recondition_loaded_cents"] == 48972

        vehicle = fixtures.read_vehicle(client, built["vehicle_id"])
        assert vehicle["total_recondition_cents"] == 48972


class TestRedistributionSurchargeTier:
    """The tier is a function of the base haul, so the cost curve is not monotonic."""

    def _car_at_atlanta(self, client, world):
        built = fixtures.setup_in_service_vehicle(
            client, world, market_code="ATL", program_key="PGM"
        )
        return built["vehicle"]["id"]

    def test_three_hauls_price_the_surcharge_off_the_base_haul_alone(
        self, client, world
    ):
        """A 199 km haul costs more than a 200 km haul on the same rate.

        PRD 3.6: "The fuel surcharge percentage is then selected **from the base
        haul alone, before anything is added to it**: strictly below fifty
        thousand cents of base haul the rate is 0.12; from fifty thousand cents
        up to but not including one hundred fifty thousand cents it is 0.08; at
        one hundred fifty thousand cents or above it is 0.05."
        PRD 3.6: "`estimated_transport_cost_cents` is the sum of the base haul,
        the surcharge and the handling flat."

        Design: Difficulty/combinatorial_formula/redistribution_surcharge_tier_selected_on_base_haul_not_total
        """
        vehicle_id = self._car_at_atlanta(client, world)
        destination = world.market_id("DFW")

        long_haul = fixtures.draft_order(
            client,
            vehicle_id,
            destination,
            distance_km=596,
            planned_depart_at="2026-02-01T00:00:00.000Z",
            planned_receive_at="2026-02-03T00:00:00.000Z",
        )
        two_hundred = fixtures.draft_order(
            client,
            vehicle_id,
            destination,
            distance_km=200,
            planned_depart_at="2026-02-05T00:00:00.000Z",
            planned_receive_at="2026-02-06T00:00:00.000Z",
        )
        one_ninety_nine = fixtures.draft_order(
            client,
            vehicle_id,
            destination,
            distance_km=199,
            planned_depart_at="2026-02-08T00:00:00.000Z",
            planned_receive_at="2026-02-09T00:00:00.000Z",
        )

        assert long_haul["estimated_transport_cost_cents"] == 168420
        assert two_hundred["estimated_transport_cost_cents"] == 61500
        assert one_ninety_nine["estimated_transport_cost_cents"] == 63220
        assert (
            one_ninety_nine["estimated_transport_cost_cents"]
            > two_hundred["estimated_transport_cost_cents"]
        ), "the shorter haul is dearer because its base haul sits in the 0.12 tier"
        for order in (long_haul, two_hundred, one_ninety_nine):
            assert_redistribution_order(order, {"status": OrderStatus.DRAFT})

    def test_tier_is_not_selected_from_the_total_and_the_origin_rate_is_used(
        self, client, world
    ):
        """Neither the handling flat nor the destination rate touches the tier.

        PRD 3.6: "Selecting the tier from that final total instead — the
        circular reading that a surcharge tier "depends on the total cost"
        invites — is a different and forbidden computation, because a haul whose
        base sits just under a ceiling can be pushed over it by its own
        surcharge and handling."
        PRD 3.6: "The base haul is the order's `distance_km` multiplied by the
        **origin** market's `transfer_cost_per_km_cents`; the destination
        market's rate is never read, so hauling from a cheap city to an
        expensive one costs the cheap city's rate."

        Design: Difficulty/combinatorial_formula/redistribution_surcharge_tier_selected_on_base_haul_not_total
        """
        vehicle_id = self._car_at_atlanta(client, world)

        order = fixtures.draft_order(
            client,
            vehicle_id,
            world.market_id("DFW"),
            distance_km=596,
            planned_depart_at="2026-02-01T00:00:00.000Z",
            planned_receive_at="2026-02-03T00:00:00.000Z",
        )

        assert order["origin_market_id"] == world.market_id("ATL")
        assert order["estimated_transport_cost_cents"] == estimated_transport_cost(596, 250)
        assert order["estimated_transport_cost_cents"] != estimated_transport_cost(596, 300), (
            "the destination market's dearer rate must never be read"
        )
        assert order["estimated_transport_cost_cents"] != 163950, (
            "adding the handling flat before the tier lookup drops the haul into 0.05"
        )

    def test_frozen_estimate_survives_the_reads_that_follow_creation(
        self, client, world
    ):
        """The estimate is computed once at draft time and never recomputed.

        PRD 3.6: "`estimated_transport_cost_cents` is computed once, at draft
        time, and never recomputed."
        PRD 3.6: "The surcharge itself is the base haul multiplied by the
        selected rate, rounded half up; the base haul and the flat handling
        charge of seven thousand five hundred cents are exact integers and are
        never rounded."

        Design: Difficulty/combinatorial_formula/redistribution_surcharge_tier_selected_on_base_haul_not_total
        """
        vehicle_id = self._car_at_atlanta(client, world)

        order = fixtures.draft_order(
            client,
            vehicle_id,
            world.market_id("DFW"),
            distance_km=199,
            planned_depart_at="2026-02-08T00:00:00.000Z",
            planned_receive_at="2026-02-09T00:00:00.000Z",
        )
        fixtures.propose_order(client, order["id"])
        proposed = validate_success(
            client.get_redistribution_order(order["id"], make_fleet_planner_headers())
        )

        assert proposed["estimated_transport_cost_cents"] == 63220
        assert proposed["status"] == OrderStatus.PROPOSED
