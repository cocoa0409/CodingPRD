"""Two interval-collision rules that deliberately disagree about adjacency.

A vehicle's transfer calendar is a half-open interval, so touching windows are
legal; a preparation bay is a closed interval widened by an hour at each end, so
touching windows collide. Both refusals are 409 and only the identifier differs.
"""

from test_helpers import (
    ApiErrorId,
    OrderStatus,
    TaskType,
    factories,
    fixtures,
    make_fleet_planner_headers,
    make_market_operator_headers,
    validate_error,
    validate_success,
)
from test_helpers.assertions import list_rows, total_count


class TestVehicleTransferWindowAdjacency:
    """The interval runs from planned_depart_at inclusive to planned_receive_at
    exclusive, so an order may start exactly when its predecessor ends."""

    INCUMBENT = {
        "planned_depart_at": "2026-03-01T00:00:00.000Z",
        "planned_receive_at": "2026-03-05T00:00:00.000Z",
    }

    def _car_with_one_booked_window(self, client, world):
        built = fixtures.setup_in_service_vehicle(
            client, world, market_code="ATL", program_key="PGM"
        )
        vehicle_id = built["vehicle"]["id"]
        incumbent = fixtures.draft_order(
            client, vehicle_id, world.market_id("DFW"), distance_km=200, **self.INCUMBENT
        )
        return vehicle_id, incumbent

    def _draft_attempt(self, client, world, vehicle_id, depart, receive):
        return client.create_redistribution_order(
            factories.redistribution_order_payload(
                vehicle_id,
                world.market_id("DFW"),
                distance_km=200,
                planned_depart_at=depart,
                planned_receive_at=receive,
            ),
            make_fleet_planner_headers(),
        )

    def test_a_window_overlapping_the_incumbent_by_one_day_is_refused(
        self, client, world
    ):
        """Sharing a single day of the car's calendar is a collision.

        PRD 3.6: "And the proposed window must not collide with another haul for
        the same car: taking the interval from `planned_depart_at` inclusive to
        `planned_receive_at` **exclusive**, it must not overlap the corresponding
        interval of any existing non-terminal order for the same vehicle, and an
        overlap is refused with `ERR_VEHICLE_TRANSFER_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/vehicle_transfer_windows_half_open_adjacency_allowed
        """
        vehicle_id, incumbent = self._car_with_one_booked_window(client, world)
        assert incumbent["status"] == OrderStatus.DRAFT

        validate_error(
            self._draft_attempt(
                client,
                world,
                vehicle_id,
                "2026-03-04T00:00:00.000Z",
                "2026-03-08T00:00:00.000Z",
            ),
            ApiErrorId.VEHICLE_TRANSFER_OVERLAP,
        )

        assert (
            total_count(
                client.list_redistribution_orders(
                    make_fleet_planner_headers(), vehicle_id=vehicle_id
                )
            )
            == 1
        ), "the refused draft must not leave a row behind"

    def test_a_window_starting_exactly_where_the_incumbent_ends_is_accepted(
        self, client, world
    ):
        """Half-open intervals make back-to-back hauls legal.

        PRD 3.6: "Because that interval is half-open, back-to-back hauls are
        legal: one order's `planned_receive_at` may be exactly the next order's
        `planned_depart_at`."
        PRD 3.6: "Note the deliberate asymmetry with the prep-bay rule of §3.4,
        where a closed interval plus a buffer makes touching endpoints a
        conflict."

        Design: Difficulty/resource_temporal_overlap/vehicle_transfer_windows_half_open_adjacency_allowed
        """
        vehicle_id, incumbent = self._car_with_one_booked_window(client, world)

        adjacent = validate_success(
            self._draft_attempt(
                client,
                world,
                vehicle_id,
                incumbent["planned_receive_at"],
                "2026-03-09T00:00:00.000Z",
            ),
            expected_status=201,
        )
        assert adjacent["status"] == OrderStatus.DRAFT
        assert adjacent["estimated_transport_cost_cents"] == 61500
        assert (
            total_count(
                client.list_redistribution_orders(
                    make_fleet_planner_headers(), vehicle_id=vehicle_id
                )
            )
            == 2
        )

    def test_cancelling_the_incumbent_frees_the_window_it_held(self, client, world):
        """Only non-terminal orders participate in the collision scan.

        PRD 3.6: "Cancellation is available to a `FleetController` from every
        non-terminal status."
        PRD 3.6: "From `DRAFT`, from `PROPOSED`, from `REJECTED` and from
        `AUTHORIZED` it simply moves the order to `CANCELLED` and increments its
        `version` by 1, with no effect on the vehicle."

        Design: Difficulty/resource_temporal_overlap/vehicle_transfer_windows_half_open_adjacency_allowed
        """
        vehicle_id, incumbent = self._car_with_one_booked_window(client, world)
        validate_success(
            self._draft_attempt(
                client,
                world,
                vehicle_id,
                incumbent["planned_receive_at"],
                "2026-03-09T00:00:00.000Z",
            ),
            expected_status=201,
        )

        validate_error(
            self._draft_attempt(
                client,
                world,
                vehicle_id,
                "2026-03-02T00:00:00.000Z",
                "2026-03-04T00:00:00.000Z",
            ),
            ApiErrorId.VEHICLE_TRANSFER_OVERLAP,
        )

        cancelled = fixtures.cancel_order(client, incumbent["id"])
        assert cancelled["status"] == OrderStatus.CANCELLED

        freed = validate_success(
            self._draft_attempt(
                client,
                world,
                vehicle_id,
                "2026-03-02T00:00:00.000Z",
                "2026-03-04T00:00:00.000Z",
            ),
            expected_status=201,
        )
        assert freed["status"] == OrderStatus.DRAFT

        rows = list_rows(
            client.list_redistribution_orders(
                make_fleet_planner_headers(), vehicle_id=vehicle_id
            )
        )
        assert len(rows) == 3
        assert sorted(row["status"] for row in rows) == [
            OrderStatus.CANCELLED,
            OrderStatus.DRAFT,
            OrderStatus.DRAFT,
        ]


class TestPrepBayBufferedAdjacency:
    """The bay interval is closed and widened by sixty minutes at each end, so
    two windows that merely touch after buffering do intersect."""

    INCUMBENT = {
        "window_start": "2026-01-07T08:00:00.000Z",
        "window_end": "2026-01-07T10:00:00.000Z",
    }

    def _bay_occupied_at_chicago(self, client, world):
        """Two licensed cars at ORD, one of them already holding bay B1."""
        bought = fixtures.setup_allocation_with_units(
            client,
            world,
            market_code="ORD",
            program_key="PGM",
            unit_count=2,
            vin_prefix="BY",
        )
        vehicles = bought["vehicles"]
        for vehicle in vehicles:
            fixtures.in_fleet(client, world, vehicle["id"], "ORD")
            registration = fixtures.schedule_task(
                client, world, vehicle["id"], factories.registration_task_payload(), "ORD"
            )
            fixtures.complete_task(client, world, registration["id"], "ORD")
            licensing = fixtures.schedule_task(
                client, world, vehicle["id"], factories.licensing_task_payload(), "ORD"
            )
            fixtures.complete_task(client, world, licensing["id"], "ORD")

        incumbent = fixtures.schedule_task(
            client,
            world,
            vehicles[0]["id"],
            factories.preparation_task_payload(bay_code="B1", **self.INCUMBENT),
            "ORD",
        )
        return {
            "incumbent_task": incumbent,
            "free_vehicle_id": vehicles[1]["id"],
        }

    def _prep_attempt(self, client, world, vehicle_id, start, end, bay_code="B1"):
        return client.create_in_fleeting_task(
            vehicle_id,
            factories.preparation_task_payload(
                bay_code=bay_code, window_start=start, window_end=end
            ),
            make_market_operator_headers(world.market_id("ORD")),
        )

    def test_the_collision_is_per_bay_and_the_daily_count_is_not_the_cause(
        self, client, world
    ):
        """The identical colliding window is accepted in a different bay.

        PRD 3.4: "**Daily capacity** works on calendar dates instead: the count of
        `PENDING` plus `COMPLETED` `PREPARATION` tasks at the same market whose
        `window_start` falls on the same UTC calendar date as the new task's
        `window_start` may not exceed that market's `prep_capacity_per_day`, and a
        breach is `ERR_PREP_CAPACITY_EXCEEDED` (HTTP 422)."
        PRD 3.4: "Because bays are checked individually and dates are checked in
        aggregate, a market with several free bays can still refuse the day's
        fifth car."

        Design: Difficulty/resource_temporal_overlap/prep_bay_buffered_closed_interval_adjacency_forbidden
        """
        built = self._bay_occupied_at_chicago(client, world)
        assert fixtures.read_market(client, world.market_id("ORD"))[
            "prep_capacity_per_day"
        ] == 5

        # 09:00-11:00 shares the 09:00-10:00 hour with the incumbent's own
        # 08:00-10:00 occupation of B1, so the two intervals collide outright
        # rather than merely abutting after the sixty-minute expansion.
        refusal = validate_error(
            self._prep_attempt(
                client,
                world,
                built["free_vehicle_id"],
                "2026-01-07T09:00:00.000Z",
                "2026-01-07T11:00:00.000Z",
            ),
            ApiErrorId.PREP_BAY_CONFLICT,
        )
        assert refusal["error_id"] != ApiErrorId.PREP_CAPACITY_EXCEEDED

        other_bay = validate_success(
            self._prep_attempt(
                client,
                world,
                built["free_vehicle_id"],
                "2026-01-07T09:00:00.000Z",
                "2026-01-07T11:00:00.000Z",
                bay_code="B2",
            ),
            expected_status=201,
        )
        assert other_bay["bay_code"] == "B2"
        assert (
            total_count(
                client.list_in_fleeting_tasks(
                    make_fleet_planner_headers(),
                    market_id=world.market_id("ORD"),
                    task_type=TaskType.PREPARATION,
                )
            )
            == 2
        )
