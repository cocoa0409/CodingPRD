"""Derived figures: the line ledger's input set, schedule posture, damages and scope."""

from test_helpers import (
    CLOCK_START_UTC,
    COMPLIANCE,
    ApiErrorId,
    api_client,
    advance_build,
    assert_kit_pool_conserved,
    assert_line_ledger,
    assert_order_posture,
    assert_same_instant,
    commit_slot,
    create_campaign,
    create_dealer,
    create_legacy_unit,
    create_line,
    create_propulsion_package,
    launch_campaign,
    list_tasks,
    complete_task,
    mint_unit,
    plan_slot,
    propane_package_payload,
    read_campaign,
    read_dealer,
    read_line,
    read_order,
    read_slot,
    read_task,
    read_unit,
    release_slot,
    set_clock,
    setup_awarded_order,
    setup_order_with_units,
    setup_tx_catalogue,
    validate_error,
)

LATE_CLOCK = "2026-10-20T00:00:00Z"
TX_ONE_UNIT_TOTAL_CENTS = 16_090_216
# One bus, fifteen whole days past a 5 October promise, at 7,500 cents a day.
FIFTEEN_DAY_DAMAGES_CENTS = 112_500
# Five percent of the contract, rounded half up — the ceiling those damages stay under.
DAMAGES_CAP_CENTS = 804_511


class TestLineLedgerCountsOnlyBookedSlotsOnItsOwnLine:
    """Four slots, three of which must contribute nothing to one line's ledger."""

    def test_only_the_committed_slot_of_this_line_is_counted(self):
        """A planned slot, a released slot and a committed slot on a second line all
        leave the first line's ledger reading seven days.

        PRD: "the line's `committed_slot_days` increases by exactly the slot's
        `slot_days` and the line's `version` increments by 1".
        PRD: "Creating the slot increments the line's `version` by 1 and leaves
        `committed_slot_days` untouched, because a plan books no capacity."

        Design: Corner/calculations/committed_slot_day_ledger_counts_only_booked_slots_on_its_own_line
        """
        scenario = setup_order_with_units(
            setup_tx_catalogue(),
            vin_list=[
                "1TXDSL0000000201",
                "1TXDSL0000000202",
                "1TXDSL0000000203",
                "1TXDSL0000000204",
            ],
            solicitation_overrides={
                "solicitation_code": "SOL-TX-106",
                "buyer_type": "COOPERATIVE",
                "buyer_name": "North Texas Coop",
                "price_cap_cents_per_unit": 20_000_000,
            },
        )
        first, second, third, fourth = scenario["units"]
        line_a = create_line()
        line_b = create_line(
            line_code="L-B1", plant_code="PLANT-B", supported_body_classes=["TYPE_C"]
        )

        booked = commit_slot(
            plan_slot(line_a["id"], first["id"], "2026-09-07", "2026-09-14")["id"]
        )
        assert booked["slot_days"] == 7
        assert_line_ledger(read_line(line_a["id"]), 7)

        handed_back = plan_slot(
            line_a["id"], second["id"], "2026-09-14", "2026-09-21"
        )
        commit_slot(handed_back["id"])
        assert_line_ledger(read_line(line_a["id"]), 14)
        release_slot(handed_back["id"])
        assert_line_ledger(read_line(line_a["id"]), 7)

        never_booked = plan_slot(
            line_a["id"], third["id"], "2026-09-21", "2026-09-28"
        )
        assert never_booked["status"] == "PLANNED"
        assert never_booked["slot_days"] == 7
        assert_line_ledger(read_line(line_a["id"]), 7)

        commit_slot(
            plan_slot(line_b["id"], fourth["id"], "2026-09-07", "2026-09-14")["id"]
        )
        # Each line keeps its own ledger; the second line's booking never leaks.
        assert_line_ledger(read_line(line_a["id"]), 7)
        assert_line_ledger(read_line(line_b["id"]), 7)
        assert read_slot(booked["id"])["status"] == "COMMITTED"
        assert read_slot(handed_back["id"])["status"] == "RELEASED"


class TestSchedulePostureIsRefreshedOnlyByTransitions:
    """The posture is a function of the clock that no clock change ever recomputes."""

    def _order_promised_for_the_fifth_of_october(self) -> dict:
        """A one-bus Texas order awarded on 1 September against a 5 October promise,
        with a line ready to take the bus."""
        scenario = setup_awarded_order(
            setup_tx_catalogue(),
            promised_delivery_date="2026-10-05",
            solicitation_overrides={
                "solicitation_code": "SOL-TX-107",
                "required_delivery_date": "2026-10-05",
                "price_cap_cents_per_unit": 20_000_000,
            },
        )
        assert scenario["order"]["total_contract_cents"] == TX_ONE_UNIT_TOTAL_CENTS
        scenario["line"] = create_line()
        scenario["unit"] = mint_unit(scenario["order"]["id"], "1TXDSL0000000301")
        return scenario

    def test_the_posture_walks_at_risk_then_on_track_as_the_bus_is_booked(self):
        """Minting inside the replanning window puts the order at risk, and the slot
        commit that takes the bus off the unbooked list returns it to on track.

        PRD: "it is `AT_RISK` when `at_risk_unit_count` is at least 1 and the number
        of whole days from the clock's date to the `promised_delivery_date` is fewer
        than 45 — the replanning lead time the plant needs to recover a slipping
        order."

        Design: Corner/calculations/delivery_posture_recomputes_on_transitions_and_never_on_clock_advance
        """
        scenario = self._order_promised_for_the_fifth_of_october()
        order_id = scenario["order"]["id"]
        # Thirty-four days from the award to the promise, one unbooked bus.
        assert_order_posture(read_order(order_id), "AT_RISK", 1, damages=0)

        slot = plan_slot(
            scenario["line"]["id"], scenario["unit"]["id"], "2026-09-07", "2026-09-14"
        )
        commit_slot(slot["id"])
        assert_order_posture(read_order(order_id), "ON_TRACK", 0, damages=0)
        assert read_unit(scenario["unit"]["id"])["production_status"] == "SLOTTED"

    def test_the_clock_alone_never_breaches_an_order_but_the_next_write_does(self):
        """Jumping the clock past the promise leaves the stored posture alone; the
        next build advance breaches with no damages, and the release that puts the bus
        back into planning finally charges them.

        PRD: "Setting the clock is deliberately inert with respect to business state:
        no entity is recomputed by it, and in particular no contract order's
        `delivery_posture` and no `liquidated_damages_cents` figure changes merely
        because the clock moved past a promised date."
        PRD: "the raw amount is computed as the order's `at_risk_unit_count`
        multiplied by the number of whole days the clock's date is past the
        `promised_delivery_date`, multiplied by 7,500 cents, rounded half up to a
        whole cent."

        Design: Corner/calculations/delivery_posture_recomputes_on_transitions_and_never_on_clock_advance
        """
        scenario = self._order_promised_for_the_fifth_of_october()
        order_id = scenario["order"]["id"]
        unit_id = scenario["unit"]["id"]
        slot = plan_slot(
            scenario["line"]["id"], unit_id, "2026-09-07", "2026-09-14"
        )
        commit_slot(slot["id"])

        set_clock(LATE_CLOCK)
        # A read recomputes nothing: the order still carries what the commit wrote.
        assert_order_posture(read_order(order_id), "ON_TRACK", 0, damages=0)

        advance_build(unit_id, "BODY_JOINED")
        breached = read_order(order_id)
        assert_order_posture(breached, "BREACHED", 0, damages=0)

        release_slot(slot["id"])
        after_release = read_order(order_id)
        # Absorbing: the bus falling back to planning cannot lift the breach.
        assert_order_posture(
            after_release, "BREACHED", 1, damages=FIFTEEN_DAY_DAMAGES_CENTS
        )
        assert after_release["liquidated_damages_cents"] < DAMAGES_CAP_CENTS
        assert read_unit(unit_id)["production_status"] == "PLANNED"
        assert_line_ledger(read_line(scenario["line"]["id"]), 0)


class TestDealerStandingFollowsTheOpenBusCount:
    """One launch, three dealers, and the two thresholds that separate them."""

    def _three_dealers_swept_by_one_campaign(self) -> dict:
        """Seven historical Texas diesel buses split one, two and four across three
        dealers, with a twenty-kit campaign covering all of them."""
        catalogue = setup_tx_catalogue()
        model_id = catalogue["model"]["id"]
        package_id = catalogue["package"]["id"]
        profile_id = catalogue["profile"]["id"]

        dealers = {}
        for code, name in (
            ("D-TX-A", "Alamo Bus Sales"),
            ("D-TX-B", "Brazos Bus Sales"),
            ("D-TX-C", "Caprock Bus Sales"),
        ):
            dealers[code] = create_dealer(
                dealer_code=code,
                dealer_name=name,
                licensed_state_codes=["TX"],
                training_capacity_per_month=8,
            )

        plan = [("D-TX-A", 1), ("D-TX-B", 2), ("D-TX-C", 4)]
        serial = 401
        for code, count in plan:
            for _ in range(count):
                create_legacy_unit(
                    dealers[code]["id"], model_id, package_id, profile_id,
                    f"1TXDSL0000000{serial}", f"2026-05-{serial - 400:02d}T00:00:00Z",
                )
                serial += 1

        campaign = create_campaign(
            model_id,
            campaign_code="RC-DSL-20",
            defect_category="WIRING_HARNESS",
            total_kits=20,
        )
        return {"dealers": dealers, "campaign": campaign}

    def test_one_launch_lands_three_dealers_on_three_different_standings(self):
        """Counts of one, two and four put the same launch's dealers in good,
        restricted and suspended standing, and only the two that left good standing
        have their work escalated.

        PRD: "Standing follows from the count alone: `SUSPENDED` at 4 or more open
        buses, `RESTRICTED` at 2 or 3, `GOOD` below 2."
        PRD: "Caused by a dealer leaving `GOOD` standing: that dealer's `OPEN` and
        `IN_PROGRESS` tasks whose `escalation_level` is still `DEALER_DIRECTED` move
        to `FACTORY_DIRECTED`".

        Design: Corner/calculations/dealer_standing_crosses_the_restrict_and_suspend_thresholds_by_count
        """
        fleet = self._three_dealers_swept_by_one_campaign()
        dealers = fleet["dealers"]

        launched = launch_campaign(fleet["campaign"]["id"])
        assert launched["status"] == "LAUNCHED"
        assert launched["affected_unit_count"] == 7
        assert_same_instant(launched["launched_at"], CLOCK_START_UTC, "launched_at")

        expected = {
            "D-TX-A": (1, "GOOD", "DEALER_DIRECTED", 1),
            "D-TX-B": (2, "RESTRICTED", "FACTORY_DIRECTED", 2),
            "D-TX-C": (4, "SUSPENDED", "FACTORY_DIRECTED", 2),
        }
        for code, (count, standing, level, kits) in expected.items():
            dealer = read_dealer(dealers[code]["id"])
            assert dealer["open_recall_unit_count"] == count, code
            assert dealer["certification_standing"] == standing, code
            assert dealer["delivered_unit_count"] == count, code
            tasks = list_tasks(dealer_id=dealers[code]["id"])
            assert len(tasks) == count, code
            for task in tasks:
                assert task["status"] == "OPEN", code
                assert task["escalation_level"] == level, code
                assert task["kits_reserved"] == kits, code

        # Six of the seven tasks took an extra kit; the good dealer's did not.
        campaign = read_campaign(fleet["campaign"]["id"])
        assert campaign["escalated_task_count"] == 6
        assert campaign["reserved_kits"] == 13
        assert campaign["available_kits"] == 7
        assert campaign["consumed_kits"] == 0
        assert campaign["kit_shortfall_count"] == 0
        assert_kit_pool_conserved(campaign)

    def test_closing_one_bus_walks_the_suspended_dealer_back_to_restricted(self):
        """The suspended dealer's count falling from four to three restores
        restricted standing, while the escalations it earned are not unwound.

        PRD: "As tasks close out it walks back down — `SUSPENDED → RESTRICTED` when
        the count falls into the 2-or-3 band, `RESTRICTED → GOOD` when it falls below
        2 — but tasks already escalated keep `escalation_level` `FACTORY_DIRECTED` and
        keep their extra kit."
        PRD: "the campaign's `consumed_kits` increases by the task's `kits_reserved`
        and `reserved_kits` decreases by exactly the same amount, so `available_kits`
        does not move."

        Design: Corner/calculations/dealer_standing_crosses_the_restrict_and_suspend_thresholds_by_count
        """
        fleet = self._three_dealers_swept_by_one_campaign()
        campaign_id = fleet["campaign"]["id"]
        suspended_id = fleet["dealers"]["D-TX-C"]["id"]
        launch_campaign(campaign_id)

        tasks = list_tasks(dealer_id=suspended_id)
        closed = complete_task(tasks[0]["id"], suspended_id)
        assert closed["status"] == "COMPLETED"
        assert closed["kits_reserved"] == 2

        dealer = read_dealer(suspended_id)
        assert dealer["open_recall_unit_count"] == 3
        assert dealer["certification_standing"] == "RESTRICTED"
        for sibling in tasks[1:]:
            still_open = read_task(sibling["id"])
            assert still_open["status"] == "OPEN"
            assert still_open["escalation_level"] == "FACTORY_DIRECTED"
            assert still_open["kits_reserved"] == 2

        campaign = read_campaign(campaign_id)
        assert campaign["consumed_kits"] == 2
        assert campaign["reserved_kits"] == 11
        assert campaign["available_kits"] == 7
        assert campaign["status"] == "LAUNCHED"
        assert campaign["escalated_task_count"] == 6
        assert_kit_pool_conserved(campaign)


class TestRecallScopeIsChronologicalOverAClosedWindow:
    """Five historical buses, three of them in scope, and a kit pool one short."""

    def _five_historical_buses_at_one_dealer(self) -> dict:
        """A Texas dealer holding four diesel buses delivered across March to August
        and one propane bus, with a five-kit wiring-harness campaign in draft."""
        catalogue = setup_tx_catalogue()
        model_id = catalogue["model"]["id"]
        diesel_id = catalogue["package"]["id"]
        profile_id = catalogue["profile"]["id"]
        propane_id = create_propulsion_package(propane_package_payload(model_id))["id"]

        dealer = create_dealer(
            dealer_code="D-TX-CH",
            dealer_name="Chisholm Bus Sales",
            licensed_state_codes=["TX"],
            training_capacity_per_month=10,
        )
        imports = {}
        for label, vin, package_id, delivered_at in (
            ("june", "1TXDSL0000000411", diesel_id, "2026-06-15T00:00:00Z"),
            ("march", "1TXDSL0000000412", diesel_id, "2026-03-02T00:00:00Z"),
            ("july", "1TXDSL0000000413", diesel_id, "2026-07-31T00:00:00Z"),
            ("august", "1TXDSL0000000414", diesel_id, "2026-08-01T00:00:00Z"),
            ("propane", "1TXPRP0000000415", propane_id, "2026-05-05T00:00:00Z"),
        ):
            imports[label] = create_legacy_unit(
                dealer["id"], model_id, package_id, profile_id, vin, delivered_at
            )
            assert imports[label]["production_status"] == "DELIVERED"
            assert imports[label]["service_status"] == "NONE"

        campaign = create_campaign(
            model_id,
            campaign_code="RC-DSL-21",
            defect_category="WIRING_HARNESS",
            total_kits=5,
        )
        return {"dealer": dealer, "imports": imports, "campaign": campaign}

    def test_tasks_appear_oldest_delivery_first_and_skip_the_day_after_the_window(self):
        """The March, June and July buses draw tasks in that order; the bus delivered
        the day after the window closes and the propane bus draw none.

        PRD: "whose `delivered_at` date falls on or after `build_window_start` and on
        or before `build_window_end` — both endpoints are in scope, so a bus delivered
        exactly on the window's last day is covered and one delivered the next day is
        not".
        PRD: "The scope is ordered by `delivered_at` ascending with `created_at`
        ascending as the only tie-break, and that order is the order in which remedy
        tasks are created."

        Design: Corner/calculations/recall_tasks_are_created_in_delivered_at_order_over_the_closed_window
        """
        fleet = self._five_historical_buses_at_one_dealer()
        buses = fleet["imports"]

        launched = launch_campaign(fleet["campaign"]["id"])
        assert launched["affected_unit_count"] == 3

        tasks = list_tasks(recall_campaign_id=fleet["campaign"]["id"])
        assert [task["bus_unit_id"] for task in tasks] == [
            buses["march"]["id"], buses["june"]["id"], buses["july"]["id"]
        ]
        for label in ("march", "june", "july"):
            assert read_unit(buses[label]["id"])["service_status"] == "RECALL_OPEN"
        # Out of the window by one day, and out of the propulsion scope entirely.
        assert read_unit(buses["august"]["id"])["service_status"] == "NONE"
        assert read_unit(buses["propane"]["id"])["service_status"] == "NONE"

        dealer = read_dealer(fleet["dealer"]["id"])
        assert dealer["open_recall_unit_count"] == 3
        assert dealer["certification_standing"] == "RESTRICTED"
        assert dealer["delivered_unit_count"] == 5

    def test_the_last_escalation_finds_the_pool_empty_and_records_a_shortfall(self):
        """Two escalations exhaust the five-kit pool and the third keeps its single
        kit while the campaign records one shortfall; the campaign then refuses a
        second launch.

        PRD: "When the pool is exhausted the task keeps its original `kits_reserved`
        and the campaign's `kit_shortfall_count` increments instead. The shortfall is
        recorded, not retried."
        PRD: "Launch requires the campaign to be `DRAFT`, otherwise
        `ERR_CAMPAIGN_NOT_DRAFT`".

        Design: Corner/calculations/recall_tasks_are_created_in_delivered_at_order_over_the_closed_window
        """
        fleet = self._five_historical_buses_at_one_dealer()
        campaign_id = fleet["campaign"]["id"]
        launch_campaign(campaign_id)

        tasks = list_tasks(recall_campaign_id=campaign_id)
        assert [task["kits_reserved"] for task in tasks] == [2, 2, 1]
        assert all(task["escalation_level"] == "FACTORY_DIRECTED" for task in tasks)
        assert sum(task["kits_reserved"] for task in tasks) == 5

        campaign = read_campaign(campaign_id)
        assert campaign["escalated_task_count"] == 3
        assert campaign["reserved_kits"] == 5
        assert campaign["available_kits"] == 0
        assert campaign["consumed_kits"] == 0
        assert campaign["kit_shortfall_count"] == 1
        assert_kit_pool_conserved(campaign)

        validate_error(
            api_client.launch_recall_campaign(campaign_id, COMPLIANCE),
            ApiErrorId.ERR_CAMPAIGN_NOT_DRAFT.value,
            409,
        )
        assert len(list_tasks(recall_campaign_id=campaign_id)) == 3
        assert read_campaign(campaign_id)["kit_shortfall_count"] == 1
