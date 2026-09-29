"""Cascades that travel further than the row the client named.

One call completing a leaf task bubbles four levels up the ownership spine, and
one call declaring a total loss fans out across three sibling aggregates.
"""

from test_helpers import (
    AllocationStatus,
    ChannelCode,
    ConditionStatus,
    ConsignmentStatus,
    DamageStatus,
    EntryType,
    FleetStatus,
    OrderStatus,
    PlanStatus,
    SourceEntityType,
    TaskStatus,
    factories,
    fixtures,
)
from test_helpers.assertions import (
    assert_instant_equals,
    assert_no_version_bump,
    entries_of_type,
    sum_amount,
)


def _two_unit_plan_with_one_car_waiting_in_the_bay(client, world):
    """A plan satisfied by exactly two cars, one in service and one mid-prep."""
    plan = fixtures.setup_locked_plan(
        client, world, market_code="ATL", planned_unit_count=2
    )
    allocation = fixtures.add_allocation(
        client,
        plan["id"],
        world.program_id("PGM"),
        world.segment_id("MIDSIZE"),
        2,
        plan["version"],
    )
    first = fixtures.mint_vehicle(
        client, allocation["id"], factories.vin("CA1"), world.market_id("ATL")
    )
    second = fixtures.mint_vehicle(
        client, allocation["id"], factories.vin("CB1"), world.market_id("ATL")
    )
    fixtures.bring_to_in_service(
        client, world, first["id"], market_code="ATL", prep_date="2026-01-07"
    )
    fixtures.in_fleet(client, world, second["id"], "ATL")
    registration = fixtures.schedule_task(
        client, world, second["id"], factories.registration_task_payload(), "ATL"
    )
    fixtures.complete_task(client, world, registration["id"], "ATL")
    licensing = fixtures.schedule_task(
        client, world, second["id"], factories.licensing_task_payload(), "ATL"
    )
    licensing_done = fixtures.complete_task(client, world, licensing["id"], "ATL")
    preparation = fixtures.schedule_task(
        client,
        world,
        second["id"],
        factories.preparation_task_payload(
            bay_code="B1",
            window_start="2026-01-09T14:00:00.000Z",
            window_end="2026-01-09T16:00:00.000Z",
        ),
        "ATL",
    )
    fixtures.set_clock(client, "2026-01-20T00:00:00Z")
    return {
        "plan_id": plan["id"],
        "allocation_id": allocation["id"],
        "first_id": first["id"],
        "second_id": second["id"],
        "licensing_task": licensing_done,
        "preparation_id": preparation["id"],
    }


class TestInFleetingBubbleUp:
    """Task, vehicle, allocation and plan all move on one client call."""

    def test_the_second_to_last_task_moves_nothing_above_the_task_itself(
        self, client, world
    ):
        """Each hop is gated, so resolving licensing leaves the spine untouched.

        PRD 3.4: "Promotion itself is a system transition no client can request.
        When the third distinct `task_type` for a vehicle reaches a resolved
        state — that is, when the vehicle holds one task in `COMPLETED` or
        `WAIVED` for **each** of `REGISTRATION`, `LICENSING` and `PREPARATION` —
        a vehicle sitting in `IN_FLEETING` moves to `IN_SERVICE`."
        PRD 3.3: "From `ORDERED` an allocation moves to `PARTIALLY_INFLEETED`
        when a child vehicle enters service and the recomputed `in_fleeted_count`
        is greater than 0 but strictly less than the allocation's `unit_count`;
        the move recomputes `in_fleeted_count` and increments the allocation's
        `version` by 1."

        Design: Difficulty/transitive_cascade/task_completion_cascades_vehicle_allocation_plan_four_levels
        """
        built = _two_unit_plan_with_one_car_waiting_in_the_bay(client, world)

        assert built["licensing_task"]["status"] == TaskStatus.COMPLETED
        waiting = fixtures.read_vehicle(client, built["second_id"])
        assert waiting["fleet_status"] == FleetStatus.IN_FLEETING
        assert waiting["licensed_at"] is not None

        allocation = fixtures.read_allocation(client, built["allocation_id"])
        assert allocation["status"] == AllocationStatus.PARTIALLY_INFLEETED
        assert allocation["in_fleeted_count"] == 1

        plan = fixtures.read_plan(client, built["plan_id"])
        assert plan["status"] == PlanStatus.LOCKED
        assert plan["in_fleeted_unit_count"] == 1

    def test_the_last_task_completion_moves_all_four_levels_at_once(
        self, client, world
    ):
        """Task, vehicle, allocation and plan all advance on the single call.

        PRD 3.4: "Completion stamps the task's `completed_at` from the logical
        clock, posts a ledger line of `entry_type` `PREP_COST` for a positive
        `amount_cents` equal to the task's `cost_cents` with `source_entity_type`
        `InFleetingTask`, stamps the matching milestone on the vehicle —
        `registered_at` for `REGISTRATION`, `licensed_at` for `LICENSING`,
        `prep_completed_at` for `PREPARATION` — increments the task's `version`
        by 1, and then hands off to the vehicle's promotion evaluation."
        PRD 3.3: "From `PARTIALLY_INFLEETED` an allocation moves to `INFLEETED`
        on the same condition."
        PRD 3.3: "A plan moves `LOCKED → CLOSED` when an allocation beneath it
        has just reached `INFLEETED` and the plan's recomputed
        `in_fleeted_unit_count` is greater than or equal to its
        `planned_unit_count`."

        Design: Difficulty/transitive_cascade/task_completion_cascades_vehicle_allocation_plan_four_levels
        """
        built = _two_unit_plan_with_one_car_waiting_in_the_bay(client, world)

        task = fixtures.complete_task(client, world, built["preparation_id"], "ATL")

        assert task["status"] == TaskStatus.COMPLETED
        assert_instant_equals(task["completed_at"], "2026-01-20T00:00:00.000Z")

        vehicle = fixtures.read_vehicle(client, built["second_id"])
        assert vehicle["fleet_status"] == FleetStatus.IN_SERVICE
        assert_instant_equals(vehicle["in_service_at"], "2026-01-20T00:00:00.000Z")
        assert_instant_equals(
            vehicle["first_rent_ready_at"], "2026-01-20T00:00:00.000Z"
        )

        assert fixtures.census(client, world.market_id("ATL")) == 2

        allocation = fixtures.read_allocation(client, built["allocation_id"])
        assert allocation["status"] == AllocationStatus.INFLEETED
        assert allocation["in_fleeted_count"] == 2

        plan = fixtures.read_plan(client, built["plan_id"])
        assert plan["status"] == PlanStatus.CLOSED
        assert plan["in_fleeted_unit_count"] == 2

    def test_the_three_resolved_tasks_leave_three_prep_cost_lines_on_the_unit(
        self, client, world
    ):
        """Every completion books its own cost against the unit's basis.

        PRD 2.10: "The sign convention is fixed and uniform: a **positive**
        `amount_cents` is a cost debited to the unit's fleet cost basis, and a
        **negative** `amount_cents` is a credit, a recovery or sale proceeds."
        PRD 2.10: "`source_entity_type` names the kind of row whose transition
        emitted the line and is one of `Vehicle`, `InFleetingTask`,
        `RedistributionOrder`, `DamageEvent` or `Consignment`, while
        `source_entity_id` carries that row's identifier."
        PRD 3.4: "The single difference is fiscal: a waived task posts **no**
        ledger line at all, so its `cost_cents` never enters the unit's cost
        basis."

        Design: Difficulty/transitive_cascade/task_completion_cascades_vehicle_allocation_plan_four_levels
        """
        built = _two_unit_plan_with_one_car_waiting_in_the_bay(client, world)
        fixtures.complete_task(client, world, built["preparation_id"], "ATL")

        rows = fixtures.read_ledger(client, built["second_id"])
        prep_rows = entries_of_type(rows, EntryType.PREP_COST)
        assert len(prep_rows) == 3
        assert sum_amount(prep_rows) == 44000
        for row in prep_rows:
            assert row["amount_cents"] > 0
            assert row["source_entity_type"] == SourceEntityType.IN_FLEETING_TASK


def _consigned_car_with_an_open_and_a_dead_haul(client, world):
    """A HELD_FOR_SALE car carrying one DRAFT haul, one CANCELLED haul, a claim."""
    built = fixtures.setup_in_service_vehicle(
        client,
        world,
        market_code="ATL",
        program_key="PGM",
        in_service_clock="2026-01-15T00:00:00Z",
    )
    vehicle_id = built["vehicle"]["id"]
    open_order = fixtures.draft_order(
        client,
        vehicle_id,
        world.market_id("DFW"),
        distance_km=200,
        planned_depart_at="2026-05-05T00:00:00.000Z",
        planned_receive_at="2026-05-07T00:00:00.000Z",
    )
    dead_order = fixtures.draft_order(
        client,
        vehicle_id,
        world.market_id("DFW"),
        distance_km=200,
        planned_depart_at="2026-05-10T00:00:00.000Z",
        planned_receive_at="2026-05-12T00:00:00.000Z",
    )
    fixtures.cancel_order(client, dead_order["id"])
    fixtures.set_clock(client, "2026-04-01T00:00:00Z")
    consignment = fixtures.consign(
        client, world, vehicle_id, channel_code=ChannelCode.AUCTION
    )
    event = fixtures.report_damage(
        client, world, vehicle_id, 2000000, market_code="ATL"
    )
    return {
        "vehicle_id": vehicle_id,
        "open_order_id": open_order["id"],
        "dead_order_id": dead_order["id"],
        "consignment_id": consignment["id"],
        "event_id": event["id"],
    }


class TestTotalLossFanOut:
    """One declaration reaches the vehicle, its hauls, its listing and the books."""

    def test_declaration_retires_the_vehicle_on_both_dimensions(self, client, world):
        """The event and the car reach their terminal states together.

        PRD 3.7: "A `FleetController` moves the event to `TOTAL_LOSS_DECLARED`
        from `REPORTED` or from `RECOVERY_PENDING`, in each case requiring
        `total_loss_required` to be true, and supplies the
        `salvage_proceeds_cents` realised on the wreck."
        PRD 3.7: "All five branches share the same two preconditions — the
        event's `total_loss_required` is true and its `status` is `REPORTED` or
        `RECOVERY_PENDING` — and all five set the vehicle's `condition_status` to
        `TOTALED` and increment the vehicle's `version` by 1."

        Design: Difficulty/transitive_cascade/total_loss_cascades_vehicle_orders_and_market_census_three_levels
        """
        built = _consigned_car_with_an_open_and_a_dead_haul(client, world)

        before = fixtures.read_damage_event(client, built["event_id"])
        assert before["total_loss_required"] is True
        assert before["status"] == DamageStatus.REPORTED

        event = fixtures.declare_total_loss(client, built["event_id"], 420000)
        assert event["status"] == DamageStatus.TOTAL_LOSS_DECLARED

        vehicle = fixtures.read_vehicle(client, built["vehicle_id"])
        assert vehicle["fleet_status"] == FleetStatus.TOTAL_LOSS
        assert vehicle["condition_status"] == ConditionStatus.TOTALED

    def test_the_sweep_cancels_open_hauls_and_leaves_terminal_siblings_alone(
        self, client, world
    ):
        """Three sibling aggregates are swept, and only the non-terminal ones move.

        PRD 3.7: "**every** `RedistributionOrder` for the vehicle whose `status`
        is `DRAFT`, `PROPOSED`, `REJECTED`, `AUTHORIZED` or `IN_TRANSIT` moves to
        `CANCELLED`, and **every** `Consignment` for the vehicle whose `status`
        is `DRAFT`, `RECONDITION_PENDING` or `LISTED` moves to `WITHDRAWN`, each
        with its own `version` incremented by 1."
        PRD 3.6: "When the vehicle it moves is declared a total loss, **every**
        order for that vehicle whose `status` is `DRAFT`, `PROPOSED`, `REJECTED`,
        `AUTHORIZED` or `IN_TRANSIT` moves to `CANCELLED` with its `version`
        incremented by 1."

        Design: Difficulty/transitive_cascade/total_loss_cascades_vehicle_orders_and_market_census_three_levels
        """
        built = _consigned_car_with_an_open_and_a_dead_haul(client, world)

        open_before = fixtures.read_order(client, built["open_order_id"])
        dead_before = fixtures.read_order(client, built["dead_order_id"])
        assert open_before["status"] == OrderStatus.DRAFT
        assert dead_before["status"] == OrderStatus.CANCELLED
        assert (
            fixtures.read_consignment(client, built["consignment_id"])["status"]
            == ConsignmentStatus.DRAFT
        )

        fixtures.declare_total_loss(client, built["event_id"], 420000)

        open_after = fixtures.read_order(client, built["open_order_id"])
        dead_after = fixtures.read_order(client, built["dead_order_id"])
        assert open_after["status"] == OrderStatus.CANCELLED
        assert dead_after["status"] == OrderStatus.CANCELLED
        assert_no_version_bump(dead_before, dead_after)
        assert (
            fixtures.read_consignment(client, built["consignment_id"])["status"]
            == ConsignmentStatus.WITHDRAWN
        )

    def test_a_consignment_swept_by_the_cascade_posts_no_reversal(
        self, client, world
    ):
        """The census is untouched from HELD_FOR_SALE and no reversal is booked.

        PRD 3.7: "From **`HELD_FOR_SALE`** the census is likewise not touched,
        because consignment already removed the unit, and the downstream cascade
        runs."
        PRD 3.7: "a consignment withdrawn by an operator posts a
        `RECONDITION_REVERSAL` to hand back the reconditioning spend, whereas a
        consignment withdrawn by the total-loss cascade posts **none** — the
        money sunk into fixing up a car that was then destroyed is retained in
        the book value the total-loss gain or loss is measured against."

        Design: Difficulty/transitive_cascade/total_loss_cascades_vehicle_orders_and_market_census_three_levels
        """
        built = _consigned_car_with_an_open_and_a_dead_haul(client, world)
        assert fixtures.census(client, world.market_id("ATL")) == 0

        fixtures.declare_total_loss(client, built["event_id"], 420000)

        assert fixtures.census(client, world.market_id("ATL")) == 0
        rows = fixtures.read_ledger(client, built["vehicle_id"])
        assert entries_of_type(rows, EntryType.RECONDITION_REVERSAL) == []

    def test_the_declaration_books_salvage_as_a_credit_and_a_signed_gain_loss(
        self, client, world
    ):
        """Two lines are posted: negative salvage and the signed gain or loss.

        PRD 3.7: "The declaration computes `total_loss_gain_loss_cents` as
        `salvage_proceeds_cents` plus `recovered_cents` — treated as zero when
        null, which is the ordinary case for an event declared straight from
        `REPORTED` — minus `net_book_value_at_report_cents`."
        PRD 3.7: "Two ledger lines are posted, both with `source_entity_type`
        `DamageEvent`: one of `entry_type` `SALVAGE_PROCEEDS` for a **negative**
        `amount_cents` equal to `salvage_proceeds_cents`, and one of `entry_type`
        `DISPOSAL_GAIN_LOSS` for an `amount_cents` equal to
        `total_loss_gain_loss_cents`, carrying whatever sign that figure has."

        Design: Difficulty/transitive_cascade/total_loss_cascades_vehicle_orders_and_market_census_three_levels
        """
        built = _consigned_car_with_an_open_and_a_dead_haul(client, world)

        event = fixtures.declare_total_loss(client, built["event_id"], 420000)
        assert event["salvage_proceeds_cents"] == 420000
        assert event["total_loss_gain_loss_cents"] == (
            420000 - event["net_book_value_at_report_cents"]
        )
        assert event["total_loss_gain_loss_cents"] < 0

        rows = fixtures.read_ledger(client, built["vehicle_id"])
        salvage = entries_of_type(rows, EntryType.SALVAGE_PROCEEDS)
        gain_loss = entries_of_type(rows, EntryType.DISPOSAL_GAIN_LOSS)
        assert len(salvage) == 1
        assert salvage[0]["amount_cents"] == -420000
        assert salvage[0]["source_entity_type"] == SourceEntityType.DAMAGE_EVENT
        assert len(gain_loss) == 1
        assert gain_loss[0]["amount_cents"] == event["total_loss_gain_loss_cents"]
