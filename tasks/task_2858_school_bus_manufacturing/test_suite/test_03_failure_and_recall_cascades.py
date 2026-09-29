"""Multi-hop cascades: a failed test unwinding a build, a launch escalating tasks."""

from test_helpers import (
    COMPLIANCE,
    QUALITY,
    ApiErrorId,
    api_client,
    assert_kit_pool_conserved,
    assert_line_ledger,
    assert_order_posture,
    assert_remedy_task,
    assert_same_instant,
    assert_unit_dimensions,
    advance_build,
    create_bay,
    list_tasks,
    read_campaign,
    read_dealer,
    read_line,
    read_order,
    read_slot,
    read_test,
    read_unit,
    record_result_payload,
    schedule_test,
    set_clock,
    setup_committed_slot,
    setup_launched_campaign,
    setup_tx_catalogue,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import QUALITY_INSPECTOR_USER_ID

FAILURE_CLOCK = "2026-10-20T00:00:00Z"
# 14,641,571 cents per bus plus 1,250,000 freight and a 198,645 administration fee.
TX_ONE_UNIT_TOTAL_CENTS = 16_090_216


def _bus_joined_with_two_scheduled_tests(vin: str) -> dict:
    """A Texas bus body-joined on a seven-day slot, with a brake test and an
    emergency-exit test scheduled in the same bay."""
    scenario = setup_committed_slot(
        setup_tx_catalogue(),
        vin=vin,
        promised_delivery_date="2026-10-05",
        required_delivery_date="2026-10-05",
        solicitation_overrides={"solicitation_code": "SOL-TX-003"},
    )
    unit_id = scenario["unit"]["id"]
    scenario["unit"] = advance_build(unit_id, "BODY_JOINED")
    bay = create_bay(
        supported_test_types=["BRAKE", "EMERGENCY_EXIT", "ELECTRICAL"]
    )
    scenario["bay"] = bay
    scenario["brake_test"] = schedule_test(
        unit_id, bay["id"], "BRAKE", "2026-09-15", "2026-09-15"
    )
    scenario["exit_test"] = schedule_test(
        unit_id, bay["id"], "EMERGENCY_EXIT", "2026-09-16", "2026-09-16"
    )
    return scenario


class TestQualityFailureCascade:
    """One recorded brake failure walks four hops from the test to the order's
    damages figure."""

    def test_failure_releases_the_slot_reverts_the_bus_and_voids_its_siblings(self):
        """The test fails, the bus goes nonconforming, its live slot is released
        with the line's ledger handed back, the bus drops to `PLANNED` and the
        other scheduled test is voided.

        PRD: "A quality-test failure walks four hops: the bus becomes
        nonconforming, its live slot is released, the line's ledger and the bus's
        build phase are reverted while the bus's other scheduled tests are voided,
        and finally the owning order's schedule posture — and, when that posture
        lands on breach, its damages figure — is recomputed."

        Design: Difficulty/transitive_cascade/cascade_a_test_failure_reaches_order_breach_and_damages
        """
        scenario = _bus_joined_with_two_scheduled_tests("1TXDSL0000000101")
        line_id = scenario["line"]["id"]
        assert_line_ledger(read_line(line_id), 7)
        assert read_slot(scenario["slot"]["id"])["status"] == "IN_PROGRESS"
        line_before = read_line(line_id)
        set_clock(FAILURE_CLOCK)

        failed = validate_success(
            api_client.record_test_result(
                scenario["brake_test"]["id"],
                record_result_payload("FAIL", result_notes="Pedal travel excessive."),
                QUALITY,
            )
        )
        assert failed["status"] == "FAILED"
        assert failed["recorded_by_user_id"] == QUALITY_INSPECTOR_USER_ID
        assert_same_instant(failed["recorded_at"], FAILURE_CLOCK, "recorded_at")

        unit = read_unit(scenario["unit"]["id"])
        assert_unit_dimensions(unit, production="PLANNED", certification="NONCONFORMING")
        assert read_slot(scenario["slot"]["id"])["status"] == "RELEASED"
        assert read_slot(scenario["slot"]["id"])["slot_days"] == 7
        line_after = read_line(line_id)
        assert_line_ledger(line_after, 0)
        assert line_after["version"] > line_before["version"]
        assert read_test(scenario["exit_test"]["id"])["status"] == "VOIDED"

    def test_the_breach_surfaces_on_the_failure_not_on_the_clock_move(self):
        """Moving the clock past the promised date leaves the posture alone; the
        failure's own recomputation is what breaches the order and prices the
        fifteen days late at 112,500 cents.

        PRD: "no contract order's `delivery_posture` and no
        `liquidated_damages_cents` figure changes merely because the clock moved
        past a promised date."
        PRD: "the raw amount is computed as the order's `at_risk_unit_count`
        multiplied by the number of whole days the clock's date is past the
        `promised_delivery_date`, multiplied by 7,500 cents, rounded half up to a
        whole cent."

        Design: Difficulty/transitive_cascade/cascade_a_test_failure_reaches_order_breach_and_damages
        """
        scenario = _bus_joined_with_two_scheduled_tests("1TXDSL0000000102")
        order_id = scenario["order"]["id"]
        assert scenario["order"]["total_contract_cents"] == TX_ONE_UNIT_TOTAL_CENTS

        set_clock(FAILURE_CLOCK)
        assert_order_posture(read_order(order_id), "ON_TRACK", 0, damages=0)

        validate_success(
            api_client.record_test_result(
                scenario["brake_test"]["id"], record_result_payload("FAIL"), QUALITY
            )
        )
        order = read_order(order_id)
        # One bus back in PLANNED, fifteen days past 2026-10-05, well under the
        # 804,511 cent cap of five percent of the contract.
        assert_order_posture(order, "BREACHED", 1, damages=112_500)
        assert order["status"] == "ACTIVE"

    def test_a_failed_brake_test_can_never_be_waived(self):
        """The nonconformance a brake failure creates is not waivable, so the bus
        stays nonconforming.

        PRD: "A `ComplianceOfficer` may waive a `NONCONFORMING` bus by supplying a
        `waiver_justification`, provided no `FAILED` test of the bus is of type
        `BRAKE` or `ROLLOVER` — brake and rollover failures may never be waived,
        and attempting it draws `ERR_WAIVER_NOT_PERMITTED`."

        Design: Difficulty/transitive_cascade/cascade_a_test_failure_reaches_order_breach_and_damages
        """
        scenario = _bus_joined_with_two_scheduled_tests("1TXDSL0000000103")
        unit_id = scenario["unit"]["id"]
        validate_success(
            api_client.record_test_result(
                scenario["brake_test"]["id"], record_result_payload("FAIL"), QUALITY
            )
        )

        refused = api_client.waive_nonconformance(
            unit_id, "Brake shortfall accepted by the district.", COMPLIANCE
        )
        validate_error(refused, ApiErrorId.ERR_WAIVER_NOT_PERMITTED.value)
        assert read_unit(unit_id)["certification_status"] == "NONCONFORMING"


class TestCampaignLaunchCascade:
    """A launch creates tasks, opens the buses' service dimension, recomputes each
    dealer's standing and escalates the work that dealer now owns."""

    def _launched(self) -> dict:
        return setup_launched_campaign(
            setup_tx_catalogue(), clock="2026-08-20T00:00:00Z"
        )

    def test_launch_creates_one_task_per_affected_bus_in_delivery_order(self):
        """Two legacy diesel buses inside the build window yield two open tasks in
        ascending `delivered_at` order, and both buses open their service dimension
        without leaving `DELIVERED`.

        PRD: "The scope is ordered by `delivered_at` ascending with `created_at`
        ascending as the only tie-break, and that order is the order in which
        remedy tasks are created."

        Design: Difficulty/transitive_cascade/cascade_b_campaign_launch_escalates_through_dealer_standing
        """
        scenario = self._launched()
        campaign = scenario["campaign"]
        assert campaign["status"] == "LAUNCHED"
        assert campaign["affected_unit_count"] == 2
        assert_same_instant(campaign["launched_at"], "2026-08-20T00:00:00Z")

        tasks = scenario["tasks"]
        assert len(tasks) == 2
        for task in tasks:
            assert_remedy_task(task)
            assert task["status"] == "OPEN"
            assert task["dealer_id"] == scenario["dealer"]["id"]
            assert task["recall_campaign_id"] == campaign["id"]

        earlier, later = scenario["legacy_units"]
        assert [task["bus_unit_id"] for task in tasks] == [earlier["id"], later["id"]]
        for unit in (earlier, later):
            refreshed = read_unit(unit["id"])
            assert_unit_dimensions(
                refreshed, production="DELIVERED", service="RECALL_OPEN"
            )
            assert refreshed["is_legacy_import"] is True

        filtered, meta = validate_paginated(
            api_client.list_remedy_tasks(
                COMPLIANCE,
                {"recall_campaign_id": campaign["id"], "status": "OPEN"},
            )
        )
        assert meta["total_count"] == 2
        assert len(filtered) == 2

    def test_restricted_standing_escalates_both_tasks_and_reserves_an_extra_kit(self):
        """Two open buses put the dealer in `RESTRICTED`, which escalates both
        tasks to factory direction and lifts each task's reservation to two kits.

        PRD: "Standing follows from the count alone: `SUSPENDED` at 4 or more open
        buses, `RESTRICTED` at 2 or 3, `GOOD` below 2."
        PRD: "the escalated task reserves 1 extra kit **when its own campaign's
        `available_kits` is at least 1 at that moment**, raising its
        `kits_reserved`."

        Design: Difficulty/transitive_cascade/cascade_b_campaign_launch_escalates_through_dealer_standing
        """
        scenario = self._launched()
        dealer = read_dealer(scenario["dealer"]["id"])
        assert dealer["open_recall_unit_count"] == 2
        assert dealer["certification_standing"] == "RESTRICTED"
        assert dealer["delivered_unit_count"] == 2

        for task in list_tasks(recall_campaign_id=scenario["campaign"]["id"]):
            assert task["escalation_level"] == "FACTORY_DIRECTED"
            assert task["kits_reserved"] == 2

        campaign = read_campaign(scenario["campaign"]["id"])
        assert campaign["escalated_task_count"] == 2
        assert campaign["reserved_kits"] == 4
        assert campaign["consumed_kits"] == 0
        assert campaign["available_kits"] == 1
        assert campaign["kit_shortfall_count"] == 0
        assert_kit_pool_conserved(campaign)
        assert campaign["total_kits"] == 5
