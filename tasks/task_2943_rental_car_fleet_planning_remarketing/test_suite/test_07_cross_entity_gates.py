"""Preconditions that live on a row the request never names.

One gate sits two generations up the ownership chain, on the plan behind the
allocation behind the car; the other runs sideways to the destination market of
a haul, a row the acting operator does not even scope.
"""

from test_helpers import (
    AllocationStatus,
    ApiErrorId,
    FleetStatus,
    MarketStatus,
    OrderStatus,
    PlanStatus,
    factories,
    fixtures,
    make_market_operator_headers,
    validate_error,
    validate_success,
)
from test_helpers.assertions import assert_no_version_bump


def _plan_one_car_short_of_closing(client, world):
    """A three-unit plan with two cars in service and a third mid-preparation."""
    plan = fixtures.setup_locked_plan(
        client, world, market_code="ATL", planned_unit_count=3
    )
    first_allocation = fixtures.add_allocation(
        client,
        plan["id"],
        world.program_id("PGM"),
        world.segment_id("MIDSIZE"),
        2,
        plan["version"],
    )
    second_allocation = fixtures.add_allocation(
        client,
        plan["id"],
        world.program_id("PGM"),
        world.segment_id("MIDSIZE"),
        2,
        fixtures.read_plan(client, plan["id"])["version"],
    )
    vehicle_a = fixtures.mint_vehicle(
        client, first_allocation["id"], factories.vin("GA1"), world.market_id("ATL")
    )
    vehicle_b = fixtures.mint_vehicle(
        client, first_allocation["id"], factories.vin("GB1"), world.market_id("ATL")
    )
    vehicle_c = fixtures.mint_vehicle(
        client, second_allocation["id"], factories.vin("GC1"), world.market_id("ATL")
    )
    vehicle_d = fixtures.mint_vehicle(
        client, second_allocation["id"], factories.vin("GD1"), world.market_id("ATL")
    )

    fixtures.bring_to_in_service(
        client, world, vehicle_a["id"], market_code="ATL", prep_date="2026-01-07"
    )
    fixtures.bring_to_in_service(
        client, world, vehicle_c["id"], market_code="ATL", prep_date="2026-01-09"
    )

    fixtures.in_fleet(client, world, vehicle_b["id"], "ATL")
    registration = fixtures.schedule_task(
        client, world, vehicle_b["id"], factories.registration_task_payload(), "ATL"
    )
    fixtures.complete_task(client, world, registration["id"], "ATL")
    licensing = fixtures.schedule_task(
        client, world, vehicle_b["id"], factories.licensing_task_payload(), "ATL"
    )
    fixtures.complete_task(client, world, licensing["id"], "ATL")
    preparation = fixtures.schedule_task(
        client,
        world,
        vehicle_b["id"],
        factories.preparation_task_payload(
            bay_code="B1",
            window_start="2026-01-08T08:00:00.000Z",
            window_end="2026-01-08T10:00:00.000Z",
        ),
        "ATL",
    )
    return {
        "plan_id": plan["id"],
        "first_allocation_id": first_allocation["id"],
        "second_allocation_id": second_allocation["id"],
        "closing_task_id": preparation["id"],
        "untouched_vehicle_id": vehicle_d["id"],
    }


class TestInFleetGrandparentPlanGate:
    """In-fleeting reads the plan two levels up, not the immediate allocation."""

    def test_the_same_call_succeeds_while_the_grandparent_plan_is_still_locked(
        self, client, world
    ):
        """Before the cascade closes the plan, the identical request is accepted.

        PRD 3.4: "In-fleeting begins when the branch takes delivery. A
        `MarketOperator` moves the unit `ON_ORDER → IN_FLEETING`, and four things
        are checked beyond the operator's market scope: the unit's `fleet_status`
        must be `ON_ORDER`; its allocation must be in `ORDERED` or
        `PARTIALLY_INFLEETED`; the **grandparent** plan — the plan that owns the
        allocation that produced this car — must be in `LOCKED`, which is the
        cross-generation guard that makes `ERR_PLAN_NOT_LOCKED` (HTTP 409)
        reachable from a vehicle operation; and the unit's current market must be
        `ACTIVE`, or the attempt fails with `ERR_MARKET_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/vehicle_in_fleet_blocked_by_grandparent_plan_not_locked
        """
        built = _plan_one_car_short_of_closing(client, world)

        plan = fixtures.read_plan(client, built["plan_id"])
        assert plan["status"] == PlanStatus.LOCKED
        assert plan["in_fleeted_unit_count"] == 2

        moved = fixtures.in_fleet(
            client, world, built["untouched_vehicle_id"], "ATL"
        )
        assert moved["fleet_status"] == FleetStatus.IN_FLEETING

    def test_the_plan_closing_two_levels_up_blocks_the_next_in_fleet(
        self, client, world
    ):
        """A cascade the client never requested turns the same call into a 409.

        PRD 3.4: "Note carefully that the gate is the plan's state, not the
        allocation's."
        PRD 3.3: "A plan moves `LOCKED → CLOSED` when an allocation beneath it
        has just reached `INFLEETED` and the plan's recomputed
        `in_fleeted_unit_count` is greater than or equal to its
        `planned_unit_count`."

        Design: Difficulty/cross_entity_state_dependency/vehicle_in_fleet_blocked_by_grandparent_plan_not_locked
        """
        built = _plan_one_car_short_of_closing(client, world)

        fixtures.complete_task(client, world, built["closing_task_id"], "ATL")

        closed = fixtures.read_plan(client, built["plan_id"])
        assert closed["status"] == PlanStatus.CLOSED
        assert closed["in_fleeted_unit_count"] == 3
        assert (
            fixtures.read_allocation(client, built["first_allocation_id"])["status"]
            == AllocationStatus.INFLEETED
        )

        validate_error(
            client.in_fleet_vehicle(
                built["untouched_vehicle_id"],
                make_market_operator_headers(world.market_id("ATL")),
            ),
            ApiErrorId.PLAN_NOT_LOCKED,
        )

    def test_every_check_other_than_the_grandparents_is_satisfied_at_the_refusal(
        self, client, world
    ):
        """The car, its allocation and its market are all in permitted states.

        PRD 3.3: "From `ORDERED` an allocation moves to `PARTIALLY_INFLEETED`
        when a child vehicle enters service and the recomputed `in_fleeted_count`
        is greater than 0 but strictly less than the allocation's `unit_count`;
        the move recomputes `in_fleeted_count` and increments the allocation's
        `version` by 1."
        PRD 3.4: "The transition increments the vehicle's `version` by 1 and
        nothing else."

        Design: Difficulty/cross_entity_state_dependency/vehicle_in_fleet_blocked_by_grandparent_plan_not_locked
        """
        built = _plan_one_car_short_of_closing(client, world)
        fixtures.complete_task(client, world, built["closing_task_id"], "ATL")

        before = fixtures.read_vehicle(client, built["untouched_vehicle_id"])
        assert before["fleet_status"] == FleetStatus.ON_ORDER
        assert (
            fixtures.read_allocation(client, built["second_allocation_id"])["status"]
            == AllocationStatus.PARTIALLY_INFLEETED
        )
        assert fixtures.read_market(client, world.market_id("ATL"))["status"] == (
            MarketStatus.ACTIVE
        )

        validate_error(
            client.in_fleet_vehicle(
                built["untouched_vehicle_id"],
                make_market_operator_headers(world.market_id("ATL")),
            ),
            ApiErrorId.PLAN_NOT_LOCKED,
        )

        after = fixtures.read_vehicle(client, built["untouched_vehicle_id"])
        assert after["fleet_status"] == FleetStatus.ON_ORDER
        assert_no_version_bump(before, after)
        assert fixtures.census(client, world.market_id("ATL")) == 3


def _two_authorized_hauls_to_two_cities(client, world):
    """One car at ATL with disjoint authorized windows to DFW and to ORD."""
    built = fixtures.setup_in_service_vehicle(
        client, world, market_code="ATL", program_key="PGM"
    )
    vehicle_id = built["vehicle"]["id"]
    to_dallas = fixtures.setup_authorized_order(
        client,
        world,
        vehicle_id,
        destination_code="DFW",
        distance_km=200,
        planned_depart_at="2026-04-05T00:00:00.000Z",
        planned_receive_at="2026-04-07T00:00:00.000Z",
    )
    to_chicago = fixtures.setup_authorized_order(
        client,
        world,
        vehicle_id,
        destination_code="ORD",
        distance_km=200,
        planned_depart_at="2026-04-10T00:00:00.000Z",
        planned_receive_at="2026-04-12T00:00:00.000Z",
    )
    return {
        "vehicle_id": vehicle_id,
        "dallas_order_id": to_dallas["id"],
        "chicago_order_id": to_chicago["id"],
    }


class TestDepartDestinationMarketGate:
    """Dispatch re-reads the destination market it was authorized against."""

    def test_a_destination_suspended_after_authorization_stops_the_haul(
        self, client, world
    ):
        """The market went down between authorize and depart and dispatch refuses.

        PRD 3.6: "A `MarketOperator` whose identifier equals the order's
        `origin_market_id` moves the order `AUTHORIZED → IN_TRANSIT`, provided the
        order is `AUTHORIZED`, the vehicle is `IN_SERVICE`, and the destination
        market is still `ACTIVE` — a market suspended between authorization and
        dispatch stops the haul."
        PRD 3.1: "A `SUSPENDED` market can no longer host new fleet plans, cannot
        be the market a vehicle is in-fleeted at, and cannot be the destination of
        a transfer, each of those refusals carrying `ERR_MARKET_SUSPENDED` (HTTP
        422)."

        Design: Difficulty/cross_entity_state_dependency/redistribution_depart_blocked_by_suspended_destination_market
        """
        built = _two_authorized_hauls_to_two_cities(client, world)
        fixtures.suspend_market(client, world.market_id("DFW"))

        before = fixtures.read_order(client, built["dallas_order_id"])
        assert before["status"] == OrderStatus.AUTHORIZED
        assert before["authorized_by_user_id"] is not None
        assert before["depart_at"] is None

        validate_error(
            client.depart_order(
                built["dallas_order_id"],
                make_market_operator_headers(world.market_id("ATL")),
            ),
            ApiErrorId.MARKET_SUSPENDED,
        )

        after = fixtures.read_order(client, built["dallas_order_id"])
        assert after["status"] == OrderStatus.AUTHORIZED
        assert after["depart_at"] is None
        assert_no_version_bump(before, after)
        assert fixtures.census(client, world.market_id("ATL")) == 1

    def test_the_sibling_haul_to_a_live_destination_departs_in_the_same_world(
        self, client, world
    ):
        """Only the suspended row blocks: the parallel order dispatches normally.

        PRD 3.6: "Departure stamps `depart_at` from the logical clock, drives the
        vehicle `IN_SERVICE → IN_TRANSIT`, **decrements** the origin market's
        `in_service_unit_count` by 1, and increments both the order's and the
        vehicle's `version` by 1."
        PRD 3.6: "Because that interval is half-open, back-to-back hauls are
        legal: one order's `planned_receive_at` may be exactly the next order's
        `planned_depart_at`."

        Design: Difficulty/cross_entity_state_dependency/redistribution_depart_blocked_by_suspended_destination_market
        """
        built = _two_authorized_hauls_to_two_cities(client, world)
        fixtures.suspend_market(client, world.market_id("DFW"))

        validate_error(
            client.depart_order(
                built["dallas_order_id"],
                make_market_operator_headers(world.market_id("ATL")),
            ),
            ApiErrorId.MARKET_SUSPENDED,
        )

        departed = validate_success(
            client.depart_order(
                built["chicago_order_id"],
                make_market_operator_headers(world.market_id("ATL")),
            )
        )
        assert departed["status"] == OrderStatus.IN_TRANSIT
        assert departed["depart_at"] is not None
        assert (
            fixtures.read_vehicle(client, built["vehicle_id"])["fleet_status"]
            == FleetStatus.IN_TRANSIT
        )
        assert fixtures.census(client, world.market_id("ATL")) == 0

    def test_the_destination_and_not_the_origin_is_the_blocking_row(
        self, client, world
    ):
        """The origin is ACTIVE and scopes the operator identically for both calls.

        PRD 3.6: "The order's `origin_market_id` is copied from the vehicle's
        `current_market_id` at creation and never changes afterwards, even though
        the vehicle itself will be rehomed."
        PRD 2.1: "The comparison field depends on the operation, and there are
        eight operations under this scope: in-fleeting a vehicle, posting usage on
        a vehicle, scheduling an in-fleeting task for a vehicle and reporting
        damage on a vehicle all compare against that vehicle's
        `current_market_id`; completing an in-fleeting task compares against the
        task's `market_id`; revising a damage estimate compares against the damage
        event's `market_id`; dispatching a redistribution order compares against
        the order's `origin_market_id`; and receiving a redistribution order
        compares against the order's `destination_market_id`, because the
        receiving branch is the one that signs for the haul."

        Design: Difficulty/cross_entity_state_dependency/redistribution_depart_blocked_by_suspended_destination_market
        """
        built = _two_authorized_hauls_to_two_cities(client, world)

        dallas = fixtures.read_order(client, built["dallas_order_id"])
        chicago = fixtures.read_order(client, built["chicago_order_id"])
        assert dallas["origin_market_id"] == world.market_id("ATL")
        assert chicago["origin_market_id"] == world.market_id("ATL")
        assert dallas["destination_market_id"] == world.market_id("DFW")

        fixtures.suspend_market(client, world.market_id("DFW"))
        assert fixtures.read_market(client, world.market_id("DFW"))["status"] == (
            MarketStatus.SUSPENDED
        )
        assert fixtures.read_market(client, world.market_id("ORD"))["status"] == (
            MarketStatus.ACTIVE
        )
        assert fixtures.read_market(client, world.market_id("ATL"))["status"] == (
            MarketStatus.ACTIVE
        )

        validate_error(
            client.depart_order(
                built["dallas_order_id"],
                make_market_operator_headers(world.market_id("ATL")),
            ),
            ApiErrorId.MARKET_SUSPENDED,
        )
        validate_success(
            client.depart_order(
                built["chicago_order_id"],
                make_market_operator_headers(world.market_id("ATL")),
            )
        )
