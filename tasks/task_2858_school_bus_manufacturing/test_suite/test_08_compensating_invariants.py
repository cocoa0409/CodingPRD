"""Compensating actions that must restore a ledger exactly, not approximately."""

from test_helpers import (
    assert_kit_pool_conserved,
    assert_line_ledger,
    assert_order_posture,
    cancel_task,
    commit_slot,
    complete_task,
    create_bay,
    create_line,
    list_tasks,
    mint_unit,
    plan_slot,
    read_campaign,
    read_dealer,
    read_line,
    read_order,
    read_slot,
    read_test,
    read_unit,
    release_slot,
    schedule_test,
    setup_awarded_order,
    setup_launched_campaign,
    setup_tx_catalogue,
    start_task,
)


class TestLineLedgerReturnsToItsPreCommitValue:
    """A commit followed by the release of that same slot leaves the line's ledger
    exactly where it started."""

    def _line_with_a_planned_week(self) -> dict:
        """One Texas bus and a seven-day plan on an empty thirty-day line, with a
        bay holding a scheduled emergency-exit test."""
        scenario = setup_awarded_order(
            setup_tx_catalogue(),
            solicitation_overrides={
                "solicitation_code": "SOL-TX-007",
                "buyer_name": "Tyler ISD",
                "price_cap_cents_per_unit": 20_000_000,
            },
        )
        scenario["unit"] = mint_unit(scenario["order"]["id"], "1TXDSL0000000501")
        line = create_line(line_code="L-D1", plant_code="PLANT-D",
                           horizon_slot_day_capacity=30)
        scenario["line_at_creation"] = line
        scenario["slot"] = plan_slot(
            line["id"], scenario["unit"]["id"], "2026-09-07", "2026-09-14"
        )
        scenario["bay"] = create_bay(
            bay_code="TB-3", plant_code="PLANT-D",
            supported_test_types=["BRAKE", "EMERGENCY_EXIT", "ELECTRICAL"],
            max_concurrent_electrical=1,
        )
        return scenario

    def test_the_ledger_climbs_by_the_slot_days_and_comes_back_to_zero(self):
        """The commit books seven slot-days and the release hands back exactly
        seven, with each of the three writes moving the line's version by one.

        PRD: "after a commit of a given slot and the subsequent release of that
        same slot, the line's `committed_slot_days` is exactly the value it held
        before the commit."
        PRD: "A write to a derived counter counts as a mutation: when a slot commit
        raises a line's `committed_slot_days` ... the touched record's `updated_at`
        is refreshed and its `version` increments."

        Design: Difficulty/compensating_invariant/line_slot_day_ledger_returns_to_pre_commit_value_on_release
        """
        scenario = self._line_with_a_planned_week()
        line_id = scenario["line_at_creation"]["id"]
        slot_id = scenario["slot"]["id"]
        assert_line_ledger(scenario["line_at_creation"], 0)
        created_version = scenario["line_at_creation"]["version"]

        after_plan = read_line(line_id)
        assert_line_ledger(after_plan, 0)
        assert after_plan["version"] == created_version + 1

        commit_slot(slot_id)
        after_commit = read_line(line_id)
        assert_line_ledger(after_commit, 7)
        assert after_commit["version"] == created_version + 2

        release_slot(slot_id)
        after_release = read_line(line_id)
        assert_line_ledger(after_release, 0)
        assert after_release["version"] == created_version + 3
        # The slot keeps its width; only its contribution to the ledger is undone.
        released = read_slot(slot_id)
        assert released["status"] == "RELEASED"
        assert released["slot_days"] == 7

    def test_the_release_reverts_the_bus_voids_its_test_and_reprices_the_order(self):
        """Releasing a committed slot drops the bus back to `PLANNED`, voids the
        test window it no longer needs, and returns the bus to the order's at-risk
        count.

        PRD: "the bus's `production_status` reverts to `PLANNED` from wherever it
        stood, whether `SLOTTED → PLANNED`, `BODY_JOINED → PLANNED` or `BUILT →
        PLANNED`; every `SCHEDULED` quality test of that bus moves to `VOIDED`,
        freeing its bay window for reuse".

        Design: Difficulty/compensating_invariant/line_slot_day_ledger_returns_to_pre_commit_value_on_release
        """
        scenario = self._line_with_a_planned_week()
        unit_id = scenario["unit"]["id"]
        order_id = scenario["order"]["id"]
        assert read_unit(unit_id)["production_status"] == "PLANNED"
        assert_order_posture(read_order(order_id), "ON_TRACK", 1)

        commit_slot(scenario["slot"]["id"])
        assert read_unit(unit_id)["production_status"] == "SLOTTED"
        assert_order_posture(read_order(order_id), "ON_TRACK", 0)
        test = schedule_test(
            unit_id, scenario["bay"]["id"], "EMERGENCY_EXIT",
            "2026-09-16", "2026-09-16",
        )
        assert test["status"] == "SCHEDULED"

        release_slot(scenario["slot"]["id"])
        assert read_unit(unit_id)["production_status"] == "PLANNED"
        assert read_test(test["id"])["status"] == "VOIDED"
        assert_order_posture(read_order(order_id), "ON_TRACK", 1)
        assert read_order(order_id)["liquidated_damages_cents"] == 0


class TestRecallKitPoolConservation:
    """Completion moves kits between buckets and cancellation returns them, and
    neither ever invents or destroys one."""

    def _launched_campaign_with_two_escalated_tasks(self) -> dict:
        """The restricted-dealer launch, where both tasks hold two kits each."""
        scenario = setup_launched_campaign(setup_tx_catalogue())
        scenario["tasks"] = list_tasks(
            recall_campaign_id=scenario["campaign"]["id"]
        )
        for task in scenario["tasks"]:
            assert task["kits_reserved"] == 2
            assert task["escalation_level"] == "FACTORY_DIRECTED"
        return scenario

    def test_completion_moves_kits_across_buckets_without_moving_availability(self):
        """Starting a task moves no kit at all, and completing it shifts two kits
        from reserved to consumed while `available_kits` stays exactly where it was.

        PRD: "completing a task moves kits from reserved to consumed without
        changing `available_kits`".
        PRD: "the campaign's `consumed_kits` increases by the task's `kits_reserved`
        and `reserved_kits` decreases by exactly the same amount, so
        `available_kits` does not move. Kits are consumed, not conjured."

        Design: Difficulty/compensating_invariant/recall_kit_pool_conserved_across_completion_and_cancellation
        """
        scenario = self._launched_campaign_with_two_escalated_tasks()
        campaign_id = scenario["campaign"]["id"]
        dealer_id = scenario["dealer"]["id"]
        first = scenario["tasks"][0]

        at_launch = read_campaign(campaign_id)
        assert at_launch["total_kits"] == 5
        assert at_launch["reserved_kits"] == 4
        assert at_launch["consumed_kits"] == 0
        assert at_launch["available_kits"] == 1
        assert_kit_pool_conserved(at_launch)

        started = start_task(first["id"], dealer_id)
        assert started["status"] == "IN_PROGRESS"
        assert started["kits_reserved"] == 2
        after_start = read_campaign(campaign_id)
        assert after_start["reserved_kits"] == 4
        assert after_start["consumed_kits"] == 0
        assert after_start["available_kits"] == 1

        completed = complete_task(first["id"], dealer_id)
        assert completed["status"] == "COMPLETED"
        after_completion = read_campaign(campaign_id)
        assert after_completion["reserved_kits"] == 2
        assert after_completion["consumed_kits"] == 2
        assert after_completion["available_kits"] == 1
        assert_kit_pool_conserved(after_completion)
        assert after_completion["status"] == "LAUNCHED"

    def test_cancellation_returns_both_the_base_and_the_escalation_kit(self):
        """Cancelling the remaining escalated task hands back all two of its kits
        and leaves the consumed figure alone, closing the campaign with its pool
        whole.

        PRD: "cancelling a task returns its kits to `available_kits` and leaves
        `consumed_kits` untouched."
        PRD: "a cancelled escalated task therefore returns both its base kits and
        its extra kit to the pool."

        Design: Difficulty/compensating_invariant/recall_kit_pool_conserved_across_completion_and_cancellation
        """
        scenario = self._launched_campaign_with_two_escalated_tasks()
        campaign_id = scenario["campaign"]["id"]
        dealer_id = scenario["dealer"]["id"]
        first, second = scenario["tasks"]
        start_task(first["id"], dealer_id)
        complete_task(first["id"], dealer_id)

        cancelled = cancel_task(second["id"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["kits_reserved"] == 2
        # Escalation is one-way: a cancelled task keeps the level it was raised to.
        assert cancelled["escalation_level"] == "FACTORY_DIRECTED"

        campaign = read_campaign(campaign_id)
        assert campaign["status"] == "COMPLETED"
        assert campaign["reserved_kits"] == 0
        assert campaign["consumed_kits"] == 2
        assert campaign["available_kits"] == 3
        assert campaign["available_kits"] == campaign["total_kits"] - 2
        assert_kit_pool_conserved(campaign)

        # The remedied bus keeps a closed record; the cancelled one keeps none.
        remedied, untouched = scenario["legacy_units"]
        assert read_unit(remedied["id"])["service_status"] == "RECALL_CLOSED"
        assert read_unit(untouched["id"])["service_status"] == "NONE"
        dealer = read_dealer(dealer_id)
        assert dealer["open_recall_unit_count"] == 0
        assert dealer["certification_standing"] == "GOOD"
