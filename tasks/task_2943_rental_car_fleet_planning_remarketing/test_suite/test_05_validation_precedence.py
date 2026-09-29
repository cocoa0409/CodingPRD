"""Requests that violate two rules at once, where only the higher one may speak.

One pair crosses bands — concurrency against a fiscal posture gate — and one
sits entirely inside the business band with both candidates on the same HTTP
status, so only the error identifier can distinguish the two orderings.
"""

from test_helpers import (
    ApiErrorId,
    Posture,
    TaskStatus,
    TaskType,
    factories,
    fixtures,
    make_fleet_planner_headers,
    make_market_operator_headers,
    validate_error,
)
from test_helpers.assertions import total_count


class TestStaleVersionOutranksPosture:
    """A stale plan version is reported before the frozen posture it also breaks."""

    def _plan_filled_to_its_planned_size(self, client, world):
        plan = fixtures.setup_locked_plan(
            client, world, market_code="ATL", planned_unit_count=10
        )
        locked_version = plan["version"]
        fixtures.add_allocation(
            client,
            plan["id"],
            world.program_id("PGM"),
            world.segment_id("MIDSIZE"),
            10,
            locked_version,
        )
        return plan["id"], locked_version

    def _one_more_unit(self, world, expected_version):
        return factories.purchase_allocation_payload(
            world.program_id("PGM"), world.segment_id("MIDSIZE"), 1, expected_version
        )

    def test_the_stale_version_is_reported_and_not_the_frozen_posture(
        self, client, world
    ):
        """The 412 wins over the 422 the same request would also have earned.

        PRD 2.9: "And a stale-version create is rejected before any uniqueness or
        state check runs, so an allocation carrying a stale
        `expected_plan_version` against a plan that is also frozen reports the
        stale version, not the posture."
        PRD 2.7: "If it does not equal the plan's current `version`, the create is
        rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412)."

        Design: Difficulty/priority_pair_validation_conflict/stale_plan_version_outranks_frozen_posture_on_allocation_create
        """
        plan_id, locked_version = self._plan_filled_to_its_planned_size(client, world)

        filled = fixtures.read_plan(client, plan_id)
        assert filled["allocated_unit_count"] == 10
        assert filled["posture"] == Posture.FROZEN
        assert filled["version"] == locked_version + 1

        validate_error(
            client.create_purchase_allocation(
                plan_id,
                self._one_more_unit(world, locked_version),
                make_fleet_planner_headers(),
            ),
            ApiErrorId.STALE_PLAN_VERSION,
        )

    def test_the_posture_refusal_surfaces_once_the_version_is_refreshed(
        self, client, world
    ):
        """The second violation was present all along and speaks on the retry.

        PRD 3.3: "while the posture is `FROZEN`, no allocation is accepted at any
        size whatsoever, and the refusal is `ERR_PLAN_POSTURE_FROZEN` (HTTP
        422)."
        PRD 2.9: "Fiscal checks last, in this internal order:
        `ERR_PLAN_POSTURE_RESTRICTED`; then `ERR_PLAN_POSTURE_FROZEN` and
        `ERR_TRANSPORT_COST_EXCEEDS_BENEFIT`; then `ERR_PROCEEDS_BELOW_FLOOR`
        (all 422)."

        Design: Difficulty/priority_pair_validation_conflict/stale_plan_version_outranks_frozen_posture_on_allocation_create
        """
        plan_id, _locked_version = self._plan_filled_to_its_planned_size(client, world)
        fresh = fixtures.read_plan(client, plan_id)

        validate_error(
            client.create_purchase_allocation(
                plan_id,
                self._one_more_unit(world, fresh["version"]),
                make_fleet_planner_headers(),
            ),
            ApiErrorId.PLAN_POSTURE_FROZEN,
        )

    def test_neither_refusal_leaves_a_trace_on_the_plan_or_its_children(
        self, client, world
    ):
        """The plan's arithmetic and version are untouched by both refusals.

        PRD 2.7: "In both cases the version field is a **required** input, not an
        optional hint, and a request that omits it is a schema violation."
        PRD 2.12: "`allocated_unit_count` is the sum of `unit_count` across the
        plan's allocations whose status is `ORDERED`, `PARTIALLY_INFLEETED` or
        `INFLEETED`; allocations in `CANCELLED` contribute nothing."

        Design: Difficulty/priority_pair_validation_conflict/stale_plan_version_outranks_frozen_posture_on_allocation_create
        """
        plan_id, locked_version = self._plan_filled_to_its_planned_size(client, world)
        before = fixtures.read_plan(client, plan_id)

        validate_error(
            client.create_purchase_allocation(
                plan_id,
                self._one_more_unit(world, locked_version),
                make_fleet_planner_headers(),
            ),
            ApiErrorId.STALE_PLAN_VERSION,
        )
        validate_error(
            client.create_purchase_allocation(
                plan_id,
                self._one_more_unit(world, before["version"]),
                make_fleet_planner_headers(),
            ),
            ApiErrorId.PLAN_POSTURE_FROZEN,
        )

        after = fixtures.read_plan(client, plan_id)
        assert after["allocated_unit_count"] == 10
        assert after["version"] == before["version"]
        assert (
            total_count(
                client.list_purchase_allocations(
                    make_fleet_planner_headers(), plan_id=plan_id
                )
            )
            == 1
        )


class TestPrepSequenceOutranksDailyCapacity:
    """Two 422s on one request: the temporal band speaks before the capacity band."""

    PREP_WINDOW = {
        "window_start": "2026-01-07T08:00:00.000Z",
        "window_end": "2026-01-07T10:00:00.000Z",
    }

    def _market_day_filled_and_one_car_missing_its_licence(self, client, world):
        plan = fixtures.setup_locked_plan(
            client, world, market_code="ATL", planned_unit_count=10
        )
        allocation = fixtures.add_allocation(
            client,
            plan["id"],
            world.program_id("PGM"),
            world.segment_id("MIDSIZE"),
            3,
            plan["version"],
        )
        vehicles = [
            fixtures.mint_vehicle(
                client, allocation["id"], factories.vin(f"PV{index}"), world.market_id("ATL")
            )
            for index in (1, 2, 3)
        ]
        for vehicle in vehicles:
            fixtures.in_fleet(client, world, vehicle["id"], "ATL")
            registration = fixtures.schedule_task(
                client, world, vehicle["id"], factories.registration_task_payload(), "ATL"
            )
            fixtures.complete_task(client, world, registration["id"], "ATL")

        for vehicle, bay in zip(vehicles[:2], ("B1", "B2")):
            licensing = fixtures.schedule_task(
                client, world, vehicle["id"], factories.licensing_task_payload(), "ATL"
            )
            fixtures.complete_task(client, world, licensing["id"], "ATL")
            fixtures.schedule_task(
                client,
                world,
                vehicle["id"],
                factories.preparation_task_payload(bay_code=bay, **self.PREP_WINDOW),
                "ATL",
            )

        unlicensed_licensing = fixtures.schedule_task(
            client, world, vehicles[2]["id"], factories.licensing_task_payload(), "ATL"
        )
        return {
            "vehicle_id": vehicles[2]["id"],
            "licensing_task_id": unlicensed_licensing["id"],
        }

    def _free_bay_request(self, client, vehicle_id, world):
        return client.create_in_fleeting_task(
            vehicle_id,
            factories.preparation_task_payload(bay_code="B3", **self.PREP_WINDOW),
            make_market_operator_headers(world.market_id("ATL")),
        )

    def test_the_sequence_rule_is_reported_and_not_the_daily_capacity(
        self, client, world
    ):
        """An unlicensed car is refused for its order, not for the crowded day.

        PRD 3.4: "Preparation cannot jump the queue: a `PREPARATION` task may
        only be created once the vehicle's `REGISTRATION` **and** `LICENSING`
        tasks are both resolved, meaning each is either `COMPLETED` or `WAIVED`,
        and an early attempt is refused with `ERR_PREP_BEFORE_REGISTRATION`
        (HTTP 422)."
        PRD 2.9: "Temporal sequencing and window shape —
        `ERR_PREP_BEFORE_REGISTRATION`, `ERR_INVALID_WINDOW` and
        `ERR_TRANSFER_WINDOW_INVALID` (422), then the minimum-holding gate
        `ERR_MIN_HOLDING_PERIOD_NOT_MET` (422), then the interval-collision
        checks `ERR_VEHICLE_TRANSFER_OVERLAP` and `ERR_PREP_BAY_CONFLICT` (409)."

        Design: Difficulty/priority_pair_validation_conflict/prep_sequence_temporal_outranks_prep_daily_capacity_constraint
        """
        built = self._market_day_filled_and_one_car_missing_its_licence(client, world)

        pending_preps = total_count(
            client.list_in_fleeting_tasks(
                make_fleet_planner_headers(),
                market_id=world.market_id("ATL"),
                task_type=TaskType.PREPARATION,
            )
        )
        assert pending_preps == 2
        assert (
            fixtures.read_task(client, built["licensing_task_id"])["status"]
            == TaskStatus.PENDING
        )

        validate_error(
            self._free_bay_request(client, built["vehicle_id"], world),
            ApiErrorId.PREP_BEFORE_REGISTRATION,
        )

    def test_the_capacity_refusal_surfaces_once_the_licence_is_resolved(
        self, client, world
    ):
        """The identical request then fails on the day's count, at the same status.

        PRD 3.4: "**Daily capacity** works on calendar dates instead: the count
        of `PENDING` plus `COMPLETED` `PREPARATION` tasks at the same market
        whose `window_start` falls on the same UTC calendar date as the new
        task's `window_start` may not exceed that market's
        `prep_capacity_per_day`, and a breach is `ERR_PREP_CAPACITY_EXCEEDED`
        (HTTP 422)."
        PRD 2.9: "Capacity and constraint checks, in this internal order:
        `ERR_ALLOCATION_UNIT_LIMIT_REACHED`, `ERR_PREP_CAPACITY_EXCEEDED` and
        `ERR_ODOMETER_REGRESSION`; then `ERR_RECONDITION_CAP_EXCEEDED`,
        `ERR_RECONDITION_OVERRUN` and `ERR_RECOVERY_EXCEEDS_CAP`; then
        `ERR_NO_ELIGIBLE_CHANNEL` (all 422)."

        Design: Difficulty/priority_pair_validation_conflict/prep_sequence_temporal_outranks_prep_daily_capacity_constraint
        """
        built = self._market_day_filled_and_one_car_missing_its_licence(client, world)

        validate_error(
            self._free_bay_request(client, built["vehicle_id"], world),
            ApiErrorId.PREP_BEFORE_REGISTRATION,
        )
        fixtures.complete_task(client, world, built["licensing_task_id"], "ATL")
        validate_error(
            self._free_bay_request(client, built["vehicle_id"], world),
            ApiErrorId.PREP_CAPACITY_EXCEEDED,
        )

    def test_neither_refusal_stores_a_partial_task_and_the_bay_never_clashes(
        self, client, world
    ):
        """A free bay means the collision code is never the answer here.

        PRD 3.4: "Tasks are stored in status `PENDING` with a null
        `completed_at`, and are discoverable by `vehicle_id`, by `market_id`, by
        `task_type` and by `status`."
        PRD 3.4: "Because bays are checked individually and dates are checked in
        aggregate, a market with several free bays can still refuse the day's
        fifth car."

        Design: Difficulty/priority_pair_validation_conflict/prep_sequence_temporal_outranks_prep_daily_capacity_constraint
        """
        built = self._market_day_filled_and_one_car_missing_its_licence(client, world)

        first = validate_error(
            self._free_bay_request(client, built["vehicle_id"], world),
            ApiErrorId.PREP_BEFORE_REGISTRATION,
        )
        fixtures.complete_task(client, world, built["licensing_task_id"], "ATL")
        second = validate_error(
            self._free_bay_request(client, built["vehicle_id"], world),
            ApiErrorId.PREP_CAPACITY_EXCEEDED,
        )
        assert first["error_id"] != ApiErrorId.PREP_BAY_CONFLICT
        assert second["error_id"] != ApiErrorId.PREP_BAY_CONFLICT

        assert (
            total_count(
                client.list_in_fleeting_tasks(
                    make_fleet_planner_headers(),
                    vehicle_id=built["vehicle_id"],
                    task_type=TaskType.PREPARATION,
                )
            )
            == 0
        )
