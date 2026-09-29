"""Single transitions: the edges that exist, the edges that refuse, and their
side effects.

A plan's lock, an allocation's cancel and a task's resolution are each a one-hop
move with a precise set of consequences, and re-firing a completed hop is a
refusal rather than a replay.
"""

from test_helpers import (
    AllocationStatus,
    ApiErrorId,
    BASE_CLOCK_STAMP,
    ConditionStatus,
    DamageStatus,
    EntryType,
    FleetStatus,
    MarketStatus,
    PlanStatus,
    Posture,
    SourceEntityType,
    TaskStatus,
    factories,
    fixtures,
    make_fleet_controller_headers,
    make_fleet_planner_headers,
    validate_error,
    validate_success,
)
from test_helpers.assertions import (
    assert_fleet_plan,
    assert_instant_equals,
    entries_of_type,
    total_count,
)


class TestFleetPlanLifecycle:
    """A plan is drafted, locked once, and never locked twice."""

    def test_a_drafted_plan_opens_in_draft_with_an_open_posture(self, client, world):
        """Three derived companions come with the initial state.

        PRD 3.3: "A new plan is stored in status `DRAFT`, with
        `allocated_unit_count` 0, `in_fleeted_unit_count` 0 and `posture` `OPEN`."
        PRD 3.3: "The payload names the `market_id` the plan covers, a `season` of
        `PEAK`, `SHOULDER` or `OFF_PEAK`, a `plan_year` of 2020 or later, a
        `planned_unit_count` greater than zero, a `revenue_per_unit_target_cents`
        greater than zero, and a `utilization_target_pct` greater than 0 and at most
        1 carried to four decimal places."

        Design: Corner/state_machines/fleet_plan_is_created_in_draft_with_open_posture_and_zero_counters
        """
        plan = validate_success(
            client.create_fleet_plan(
                factories.fleet_plan_payload(world.market_id("ATL")),
                make_fleet_planner_headers(),
            ),
            expected_status=201,
        )

        assert_fleet_plan(plan)
        assert plan["status"] == PlanStatus.DRAFT
        assert plan["posture"] == Posture.OPEN
        assert plan["allocated_unit_count"] == 0
        assert plan["in_fleeted_unit_count"] == 0
        assert plan["planned_unit_count"] == 10
        assert plan["version"] == 1

    def test_locking_a_draft_moves_it_to_locked_and_bumps_the_version(
        self, client, world
    ):
        """The lock recomputes a posture that is still OPEN at zero fill.

        PRD 3.3: "Locking recomputes the plan's `posture` from its
        `allocated_unit_count` — which for a plan that has taken no allocations
        means a fill ratio of zero and therefore `OPEN` — and increments the plan's
        `version` by 1."
        PRD 3.3: "A `DRAFT` plan buys nothing."

        Design: Corner/state_machines/fleet_plan_lock_moves_draft_to_locked_and_bumps_version
        """
        drafted = fixtures.draft_plan(client, world.market_id("ATL"))
        assert drafted["version"] == 1

        locked = validate_success(
            client.lock_fleet_plan(drafted["id"], make_fleet_controller_headers())
        )
        assert locked["status"] == PlanStatus.LOCKED
        assert locked["posture"] == Posture.OPEN
        assert locked["version"] == 2

        stored = fixtures.read_plan(client, drafted["id"])
        assert stored["status"] == PlanStatus.LOCKED
        assert stored["version"] == locked["version"]

    def test_a_second_lock_is_refused_and_leaves_the_version_alone(
        self, client, world
    ):
        """The transition is not idempotent; the replay is a 409.

        PRD 3.3: "Two conditions are checked: the plan's `status` must still be
        `DRAFT`, or the attempt is refused with `ERR_PLAN_NOT_DRAFT` (HTTP 409); and
        the plan's market must still be `ACTIVE`, or the attempt is refused with
        `ERR_MARKET_SUSPENDED`."
        PRD 2.5: "`version` is an integer that starts at 1 when the row is created
        and increases by exactly 1 on each subsequent mutation."

        Design: Corner/state_machines/second_lock_on_a_locked_plan_returns_409_plan_not_draft
        """
        plan = fixtures.setup_locked_plan(client, world, market_code="ATL")
        locked_version = plan["version"]

        validate_error(
            client.lock_fleet_plan(plan["id"], make_fleet_controller_headers()),
            ApiErrorId.PLAN_NOT_DRAFT,
        )

        after = fixtures.read_plan(client, plan["id"])
        assert after["version"] == locked_version
        assert after["status"] == PlanStatus.LOCKED

    def test_a_suspended_parent_market_blocks_the_lock(self, client, world):
        """The cross-entity precondition is on the plan's market, not the plan.

        PRD 3.1: "A `SUSPENDED` market can no longer host new fleet plans, cannot be
        the market a vehicle is in-fleeted at, and cannot be the destination of a
        transfer, each of those refusals carrying `ERR_MARKET_SUSPENDED` (HTTP
        422)."
        PRD 3.1: "Suspension moves `status` from `ACTIVE` to `SUSPENDED`, is
        permitted only while the market is `ACTIVE`, and increments the market's
        `version`."

        Design: Corner/state_machines/plan_lock_on_a_suspended_market_returns_409_market_suspended
        """
        drafted = fixtures.draft_plan(client, world.market_id("ATL"))
        suspended = fixtures.suspend_market(client, world.market_id("ATL"))
        assert suspended["status"] == MarketStatus.SUSPENDED
        assert suspended["version"] == 2

        validate_error(
            client.lock_fleet_plan(drafted["id"], make_fleet_controller_headers()),
            ApiErrorId.MARKET_SUSPENDED,
        )

        after = fixtures.read_plan(client, drafted["id"])
        assert after["status"] == PlanStatus.DRAFT
        assert after["version"] == 1


class TestAllocationCancellation:
    """The cancel edge exists from ORDERED but not once a car has been minted."""

    def test_a_minted_car_blocks_the_cancel_and_no_side_effect_fires(
        self, client, world
    ):
        """The derived child count, not the status, is what refuses here.

        PRD 3.3: "It moves the allocation `ORDERED → CANCELLED` and is permitted
        only when the allocation's `status` is `ORDERED` **and** its
        `created_vehicle_count` is exactly 0; an allocation that is
        `PARTIALLY_INFLEETED`, `INFLEETED` or already `CANCELLED`, or one that has
        already minted even a single car, is refused with
        `ERR_ALLOCATION_NOT_CANCELLABLE` (HTTP 409)."
        PRD 3.3: "Cancellation conserves the plan's arithmetic exactly: the plan's
        `allocated_unit_count` is reduced by the cancelled allocation's
        `unit_count`, the plan's `posture` is recomputed from the reduced figure, the
        plan's `version` is incremented by 1, and the allocation's own `version` is
        incremented by 1."

        Design: Corner/state_machines/allocation_cancel_after_a_vehicle_was_minted_is_rejected
        """
        built = fixtures.setup_allocation_with_units(
            client,
            world,
            market_code="ATL",
            program_key="PGM",
            unit_count=1,
            planned_unit_count=10,
            vin_prefix="CN",
        )
        allocation = built["allocation"]
        plan_before = fixtures.read_plan(client, built["plan"]["id"])
        assert allocation["created_vehicle_count"] == 1

        validate_error(
            client.cancel_purchase_allocation(
                allocation["id"], make_fleet_planner_headers()
            ),
            ApiErrorId.ALLOCATION_NOT_CANCELLABLE,
        )

        after = fixtures.read_allocation(client, allocation["id"])
        assert after["status"] == AllocationStatus.ORDERED
        assert after["created_vehicle_count"] == 1
        assert after["version"] == allocation["version"]

        plan_after = fixtures.read_plan(client, built["plan"]["id"])
        assert plan_after["allocated_unit_count"] == plan_before["allocated_unit_count"]
        assert plan_after["version"] == plan_before["version"]
        assert (
            fixtures.read_vehicle(client, built["vehicles"][0]["id"])["fleet_status"]
            == FleetStatus.ON_ORDER
        )


class TestTaskResolution:
    """Completion and waiving are equal-weight terminal moves that differ only
    in whether a cost row is posted."""

    def _in_fleeting_car(self, client, world, vin_suffix, program_key="PGM"):
        built = fixtures.setup_allocation_with_units(
            client,
            world,
            market_code="ATL",
            program_key=program_key,
            unit_count=1,
            vin_prefix=vin_suffix,
        )
        vehicle_id = built["vehicles"][0]["id"]
        fixtures.in_fleet(client, world, vehicle_id, "ATL")
        return vehicle_id

    def test_a_waived_task_refuses_a_later_completion(self, client, world):
        """WAIVED is terminal, so the operator's complete call is a 409.

        PRD 3.4: "It moves the task `PENDING → WAIVED` under the same two
        preconditions — the task must be `PENDING`, or the refusal is
        `ERR_TASK_ALREADY_RESOLVED`, and the vehicle must be in `IN_FLEETING` —
        stamps `completed_at` from the logical clock, stamps the same vehicle
        milestone according to `task_type`, increments the task's `version` by 1, and
        hands off to the same promotion evaluation."
        PRD 3.4: "The single difference is fiscal: a waived task posts **no** ledger
        line at all, so its `cost_cents` never enters the unit's cost basis."

        Design: Corner/state_machines/waived_task_cannot_be_completed_returns_409_task_already_resolved
        """
        vehicle_id = self._in_fleeting_car(client, world, "WV")
        task = fixtures.schedule_task(
            client, world, vehicle_id, factories.registration_task_payload(), "ATL"
        )

        waived = fixtures.waive_task(client, task["id"])
        assert waived["status"] == TaskStatus.WAIVED
        assert_instant_equals(waived["completed_at"], BASE_CLOCK_STAMP)
        assert waived["version"] == 2
        assert_instant_equals(
            fixtures.read_vehicle(client, vehicle_id)["registered_at"],
            BASE_CLOCK_STAMP,
        )

        validate_error(
            client.complete_in_fleeting_task(task["id"], world.operator("ATL")),
            ApiErrorId.TASK_ALREADY_RESOLVED,
        )

        after = fixtures.read_task(client, task["id"])
        assert after["status"] == TaskStatus.WAIVED
        assert after["version"] == waived["version"]
        assert (
            total_count(
                client.list_vehicle_ledger_entries(
                    vehicle_id,
                    make_fleet_planner_headers(),
                    entry_type=EntryType.PREP_COST,
                )
            )
            == 0
        )

    def test_completion_posts_the_cost_and_stamps_only_its_own_milestone(
        self, client, world
    ):
        """Four side effects fire at once and the third milestone stays null.

        PRD 3.4: "Completion stamps the task's `completed_at` from the logical clock,
        posts a ledger line of `entry_type` `PREP_COST` for a positive `amount_cents`
        equal to the task's `cost_cents` with `source_entity_type` `InFleetingTask`,
        stamps the matching milestone on the vehicle — `registered_at` for
        `REGISTRATION`, `licensed_at` for `LICENSING`, `prep_completed_at` for
        `PREPARATION` — increments the task's `version` by 1, and then hands off to
        the vehicle's promotion evaluation."
        PRD 3.4: "Both `COMPLETED` and `WAIVED` are terminal, and both count as
        resolved for the promotion gate."

        Design: Corner/state_machines/task_completion_posts_prep_cost_and_stamps_the_matching_timestamp
        """
        vehicle_id = self._in_fleeting_car(client, world, "CP")
        task = fixtures.schedule_task(
            client,
            world,
            vehicle_id,
            factories.licensing_task_payload(cost_cents=9500),
            "ATL",
        )
        assert task["status"] == TaskStatus.PENDING
        assert task["completed_at"] is None

        fixtures.set_clock(client, "2026-01-06T09:00:00Z")
        completed = validate_success(
            client.complete_in_fleeting_task(task["id"], world.operator("ATL"))
        )
        assert completed["status"] == TaskStatus.COMPLETED
        assert_instant_equals(completed["completed_at"], "2026-01-06T09:00:00.000Z")
        assert completed["version"] == 2

        rows = entries_of_type(
            fixtures.read_ledger(client, vehicle_id), EntryType.PREP_COST
        )
        assert len(rows) == 1
        assert rows[0]["amount_cents"] == 9500
        assert rows[0]["source_entity_type"] == SourceEntityType.IN_FLEETING_TASK
        assert rows[0]["source_entity_id"] == task["id"]

        vehicle = fixtures.read_vehicle(client, vehicle_id)
        assert_instant_equals(vehicle["licensed_at"], "2026-01-06T09:00:00.000Z")
        assert vehicle["registered_at"] is None
        assert vehicle["prep_completed_at"] is None
        assert vehicle["fleet_status"] == FleetStatus.IN_FLEETING
        assert vehicle["in_service_at"] is None

    def test_a_total_loss_in_the_bay_waives_the_pending_work_only(
        self, client, world
    ):
        """The conditional cascade rewrites the pending task and nothing else.

        PRD 3.7: "From **`IN_FLEETING`** the abandoned paperwork is cleaned up: every
        `InFleetingTask` for the vehicle whose `status` is `PENDING` is set to
        `WAIVED` with its `completed_at` stamped at the current logical clock and
        **no** `PREP_COST` posted, while tasks already `COMPLETED` or `WAIVED` are
        left exactly as they are — a conditional cascade that touches only unresolved
        work, and one that deliberately does not promote the car to service even
        though it may thereby hold three resolved tasks."
        PRD 3.7: "The declaration computes `total_loss_gain_loss_cents` as
        `salvage_proceeds_cents` plus `recovered_cents` — treated as zero when null,
        which is the ordinary case for an event declared straight from `REPORTED` —
        minus `net_book_value_at_report_cents`."
        PRD 3.7: "`net_book_value_at_report_cents` captures the vehicle's
        `net_book_value_cents` at that instant, which is why the report requires an
        `ACTIVE` depreciation policy for the segment."

        Design: Corner/state_machines/total_loss_during_in_fleeting_waives_only_the_pending_tasks
        """
        vehicle_id = self._in_fleeting_car(client, world, "TL", program_key="RSK")
        registration = fixtures.schedule_task(
            client,
            world,
            vehicle_id,
            factories.registration_task_payload(cost_cents=14000),
            "ATL",
        )
        licensing = fixtures.schedule_task(
            client,
            world,
            vehicle_id,
            factories.licensing_task_payload(cost_cents=9500),
            "ATL",
        )
        fixtures.complete_task(client, world, registration["id"], "ATL")

        fixtures.set_clock(client, "2026-01-07T12:00:00Z")
        event = fixtures.report_damage(client, world, vehicle_id, 2000000)
        assert event["net_book_value_at_report_cents"] == 2800000
        assert event["total_loss_required"] is True

        declared = fixtures.declare_total_loss(client, event["id"], 600000)
        assert declared["status"] == DamageStatus.TOTAL_LOSS_DECLARED
        assert declared["total_loss_gain_loss_cents"] == -2200000

        vehicle = fixtures.read_vehicle(client, vehicle_id)
        assert vehicle["fleet_status"] == FleetStatus.TOTAL_LOSS
        assert vehicle["condition_status"] == ConditionStatus.TOTALED

        waived = fixtures.read_task(client, licensing["id"])
        assert waived["status"] == TaskStatus.WAIVED
        assert_instant_equals(waived["completed_at"], "2026-01-07T12:00:00.000Z")

        untouched = fixtures.read_task(client, registration["id"])
        assert untouched["status"] == TaskStatus.COMPLETED
        assert_instant_equals(untouched["completed_at"], BASE_CLOCK_STAMP)

        prep_costs = entries_of_type(
            fixtures.read_ledger(client, vehicle_id), EntryType.PREP_COST
        )
        assert len(prep_costs) == 1
        assert prep_costs[0]["amount_cents"] == 14000
        assert fixtures.census(client, world.market_id("ATL")) == 0
