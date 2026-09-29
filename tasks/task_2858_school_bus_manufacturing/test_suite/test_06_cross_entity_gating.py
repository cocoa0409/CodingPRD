"""Gates that read a state held on a different record entirely."""

from test_helpers import (
    CLOCK_START_UTC,
    CONTRACTS,
    PLANT,
    ApiErrorId,
    api_client,
    assert_line_ledger,
    cancel_task,
    commit_slot,
    create_campaign,
    create_line,
    launch_campaign,
    list_tasks,
    mint_unit,
    plan_slot,
    read_campaign,
    read_dealer,
    read_line,
    read_slot,
    read_unit,
    setup_awarded_order,
    setup_dealer_with_legacy_units,
    setup_tx_catalogue,
    validate_error,
    validate_success,
)


class TestSlotCommitGatedByLineMaintenanceState:
    """A slot's commit reads the parent line's running status, not its own."""

    def _planned_slot_on_a_line_taken_down(self) -> dict:
        """A seven-day slot planned while the line was running, with the line since
        moved into maintenance."""
        scenario = setup_awarded_order(
            setup_tx_catalogue(),
            solicitation_overrides={
                "solicitation_code": "SOL-TX-005",
                "buyer_name": "Irving ISD",
                "price_cap_cents_per_unit": 20_000_000,
            },
        )
        scenario["unit"] = mint_unit(scenario["order"]["id"], "1TXDSL0000000301")
        line = create_line(
            line_code="L-B1",
            plant_code="PLANT-B",
            supported_body_classes=["TYPE_C"],
            horizon_slot_day_capacity=30,
            changeover_buffer_days=3,
        )
        slot = plan_slot(
            line["id"], scenario["unit"]["id"], "2026-09-07", "2026-09-14"
        )
        down = validate_success(
            api_client.set_production_line_status(
                line["id"], "DOWN_FOR_MAINTENANCE", PLANT
            )
        )
        scenario.update({"line": down, "slot": slot})
        return scenario

    def test_a_commit_is_refused_while_the_line_is_down_and_taken_when_it_returns(self):
        """The identical commit that the maintenance state refused is accepted once
        the line is running again, booking its seven slot-days.

        PRD: "The slot must be `PLANNED`, otherwise `ERR_SLOT_STATE_INVALID`; the
        line must be `RUNNING`, otherwise `ERR_LINE_DOWN_FOR_MAINTENANCE`".

        Design: Difficulty/cross_entity_state_dependency/slot_commit_gated_by_production_line_maintenance_state
        """
        scenario = self._planned_slot_on_a_line_taken_down()
        line_id = scenario["line"]["id"]
        slot_id = scenario["slot"]["id"]
        assert scenario["line"]["status"] == "DOWN_FOR_MAINTENANCE"
        assert scenario["slot"]["slot_days"] == 7

        refused = api_client.commit_build_slot(slot_id, PLANT)
        validate_error(refused, ApiErrorId.ERR_LINE_DOWN_FOR_MAINTENANCE.value)
        assert read_slot(slot_id)["status"] == "PLANNED"

        restored = validate_success(
            api_client.set_production_line_status(line_id, "RUNNING", PLANT)
        )
        assert restored["status"] == "RUNNING"

        committed = commit_slot(slot_id)
        assert committed["status"] == "COMMITTED"
        assert committed["slot_days"] == 7
        assert_line_ledger(read_line(line_id), 7)
        assert read_unit(scenario["unit"]["id"])["production_status"] == "SLOTTED"

    def test_taking_the_line_down_leaves_the_planned_slot_and_the_ledger_alone(self):
        """The maintenance transition itself moves no slot and books no capacity,
        and the refused commit leaves the line's version where the transition put
        it.

        PRD: "Taking a line down touches none of its committed slots — the work
        already booked stays booked — but no new commit may be made while the line
        is down."
        PRD: "A slot still in `PLANNED` contributes nothing, because a plan is a
        reservation request rather than a booking".

        Design: Difficulty/cross_entity_state_dependency/slot_commit_gated_by_production_line_maintenance_state
        """
        scenario = self._planned_slot_on_a_line_taken_down()
        line_id = scenario["line"]["id"]
        before = read_line(line_id)
        assert_line_ledger(before, 0)
        assert read_slot(scenario["slot"]["id"])["status"] == "PLANNED"
        assert read_unit(scenario["unit"]["id"])["production_status"] == "PLANNED"

        refused = api_client.commit_build_slot(scenario["slot"]["id"], PLANT)
        validate_error(refused, ApiErrorId.ERR_LINE_DOWN_FOR_MAINTENANCE.value)

        after = read_line(line_id)
        assert after["version"] == before["version"]
        assert_line_ledger(after, 0)
        assert after["status"] == "DOWN_FOR_MAINTENANCE"
        assert after["horizon_slot_day_capacity"] == 30


class TestDealerAssignmentGatedByStandingFromOtherBuses:
    """Assignment reads a standing derived from recall work on entirely different
    buses."""

    def _restricted_dealer_and_a_bus_to_place(self) -> dict:
        """A dealer put into `RESTRICTED` by two open remedy tasks on its legacy
        fleet, plus a freshly minted bus from an unrelated order."""
        catalogue = setup_tx_catalogue()
        scenario = setup_dealer_with_legacy_units(
            catalogue,
            deliveries=[
                ("1TXDSL0000007701", "2026-05-10T00:00:00Z"),
                ("1TXDSL0000007702", "2026-06-02T00:00:00Z"),
            ],
            dealer_overrides={
                "dealer_code": "D-TX-03",
                "dealer_name": "Brazos Bus Center",
                "licensed_state_codes": ["TX"],
                "training_capacity_per_month": 15,
            },
            clock=CLOCK_START_UTC,
        )
        campaign = create_campaign(
            catalogue["model"]["id"],
            campaign_code="RC-DSL-02",
            defect_category="EMERGENCY_EXIT_LATCH",
            build_window_start="2026-01-01",
            build_window_end="2026-07-31",
            kits_per_unit=1,
            total_kits=6,
        )
        scenario["campaign"] = launch_campaign(campaign["id"])
        scenario["tasks"] = list_tasks(recall_campaign_id=campaign["id"])

        order_scenario = setup_awarded_order(
            catalogue,
            solicitation_overrides={
                "solicitation_code": "SOL-TX-006",
                "buyer_name": "Waco ISD",
                "price_cap_cents_per_unit": 20_000_000,
            },
        )
        scenario["order"] = order_scenario["order"]
        scenario["unit"] = mint_unit(
            order_scenario["order"]["id"], "1TXDSL0000000401"
        )
        return scenario

    def test_a_restricted_dealer_takes_no_assignment(self):
        """Two open tasks on other buses restrict the dealer, and the assignment of
        an unrelated bus is refused without touching that bus.

        PRD: "The dealer's `certification_standing` must be `GOOD`; a `RESTRICTED`
        or `SUSPENDED` dealer takes no new assignments and the request is refused
        with `ERR_DEALER_STANDING_RESTRICTED`."

        Design: Difficulty/cross_entity_state_dependency/dealer_assignment_gated_by_dealer_standing_derived_from_other_units
        """
        scenario = self._restricted_dealer_and_a_bus_to_place()
        dealer = read_dealer(scenario["dealer"]["id"])
        assert dealer["open_recall_unit_count"] == 2
        assert dealer["certification_standing"] == "RESTRICTED"

        refused = api_client.assign_dealer(
            scenario["unit"]["id"], dealer["id"], CONTRACTS
        )
        validate_error(refused, ApiErrorId.ERR_DEALER_STANDING_RESTRICTED.value)

        unit = read_unit(scenario["unit"]["id"])
        assert unit["dealer_id"] in (None, "")
        assert unit["registration_state_code"] == "TX"
        assert unit["production_status"] == "PLANNED"

    def test_cancelling_the_open_tasks_restores_standing_and_lets_the_bus_through(self):
        """Cancelling both tasks returns the dealer to `GOOD`, leaves no trace on
        the clean buses, and the identical assignment then succeeds.

        PRD: "The bus's `service_status` returns to `RECALL_CLOSED` if it has a
        `COMPLETED` task and to `NONE` if it does not, so cancelling the only task
        a clean bus ever had leaves no trace on it."
        PRD: "cancelling a task returns its kits to `available_kits` and leaves
        `consumed_kits` untouched."

        Design: Difficulty/cross_entity_state_dependency/dealer_assignment_gated_by_dealer_standing_derived_from_other_units
        """
        scenario = self._restricted_dealer_and_a_bus_to_place()
        for task in scenario["tasks"]:
            cancelled = cancel_task(task["id"])
            assert cancelled["status"] == "CANCELLED"

        dealer = read_dealer(scenario["dealer"]["id"])
        assert dealer["open_recall_unit_count"] == 0
        assert dealer["certification_standing"] == "GOOD"
        for legacy in scenario["legacy_units"]:
            assert read_unit(legacy["id"])["service_status"] == "NONE"

        campaign = read_campaign(scenario["campaign"]["id"])
        assert campaign["status"] == "COMPLETED"
        assert campaign["reserved_kits"] == 0
        assert campaign["consumed_kits"] == 0
        assert campaign["available_kits"] == 6

        assigned = validate_success(
            api_client.assign_dealer(
                scenario["unit"]["id"], dealer["id"], CONTRACTS
            )
        )
        assert assigned["dealer_id"] == dealer["id"]
        assert assigned["registration_state_code"] in dealer["licensed_state_codes"]
