"""Initial states, refused transitions, terminal lockdown and one-shot side effects."""

from test_helpers import (
    COMPLIANCE,
    CONTRACTS,
    CONTRACTS_2,
    PLANT,
    SALES,
    TX_BID_CONFIG,
    ApiErrorId,
    api_client,
    advance_build,
    assert_line_ledger,
    assert_same_instant,
    close_solicitation,
    commit_slot,
    create_bay,
    create_bid,
    create_bus_model,
    create_campaign,
    create_dealer,
    create_line,
    create_profile,
    create_solicitation,
    make_dealer_agent_headers,
    mint_unit,
    nv_profile_payload,
    pass_always_required_tests,
    plan_slot,
    read_bid,
    read_dealer,
    read_line,
    read_order,
    read_profile,
    read_slot,
    read_test,
    read_unit,
    record_result,
    release_slot,
    schedule_test,
    set_clock,
    setup_awarded_order,
    setup_order_with_units,
    setup_tx_catalogue,
    setup_unit_ready_to_certify,
    submit_bid,
    validate_error,
    validate_success,
)

SUBMIT_INSTANT = "2026-08-15T00:00:00Z"
AWARD_INSTANT = "2026-09-01T00:00:00Z"
DELIVERY_INSTANT = "2026-09-20T00:00:00Z"

# One Texas bus at 71 seats with the mandated lighting, arm and mirrors, escalated
# and administered from the September award onto a December promise.
TX_AWARDED_UNIT_CENTS = 14_641_571
TX_ONE_UNIT_TOTAL_CENTS = 16_090_216


class TestCreationLandsInTheDeclaredInitialState:
    """A new line and a new campaign begin with their derived counters at zero."""

    def test_a_new_line_and_a_new_campaign_start_empty(self):
        """The line opens running with nothing booked, and the campaign opens as a
        draft whose whole kit pool is still available.

        PRD: "A line is created `RUNNING` with `committed_slot_days` at 0; its only
        other status is `DOWN_FOR_MAINTENANCE`."
        PRD: "A campaign is created `DRAFT` with `launched_at` empty,
        `affected_unit_count` at 0, `reserved_kits` and `consumed_kits` at 0,
        `available_kits` equal to `total_kits`, and `escalated_task_count` and
        `kit_shortfall_count` at 0."

        Design: Corner/state_machines/production_line_and_recall_campaign_initial_states_on_creation
        """
        model = create_bus_model()
        line = create_line()
        assert line["status"] == "RUNNING"
        assert_line_ledger(line, 0)
        assert line["horizon_slot_day_capacity"] == 30
        assert line["version"] == 1

        campaign = create_campaign(
            model["id"],
            campaign_code="RC-DSL-09",
            defect_category="WIRING_HARNESS",
            kits_per_unit=2,
            total_kits=10,
        )
        assert campaign["status"] == "DRAFT"
        assert campaign["launched_at"] in (None, "")
        assert campaign["total_kits"] == 10
        assert campaign["available_kits"] == 10
        assert campaign["reserved_kits"] == 0
        assert campaign["consumed_kits"] == 0
        assert campaign["affected_unit_count"] == 0
        assert campaign["escalated_task_count"] == 0
        assert campaign["kit_shortfall_count"] == 0
        assert campaign["version"] == 1


class TestTransitionsRefusedFromThePlanningPhase:
    """A bus that holds no slot may not be advanced, certified or delivered."""

    def _one_planned_bus(self) -> dict:
        """A single awarded Texas bus with no build slot anywhere."""
        scenario = setup_awarded_order(
            setup_tx_catalogue(),
            solicitation_overrides={
                "solicitation_code": "SOL-TX-100",
                "price_cap_cents_per_unit": 20_000_000,
            },
        )
        scenario["unit"] = mint_unit(scenario["order"]["id"], "1TXDSL0000000101")
        return scenario

    def test_four_different_actions_all_report_the_same_phase_error(self):
        """Skipping to a built body, joining before a slot exists, certifying and
        delivering are all refused on the bus's phase alone.

        PRD: "The bus's `production_status` permits the requested action — advancing
        to `BODY_JOINED` requires `SLOTTED`, advancing to `BUILT` requires
        `BODY_JOINED`, certification requires `BUILT`, delivery requires `BUILT`, a
        slot commit requires `PLANNED`, and scheduling a quality test requires
        `SLOTTED`, `BODY_JOINED` or `BUILT`: `ERR_UNIT_PHASE_INVALID` (409)".

        Design: Corner/state_machines/advance_build_and_certify_from_planned_are_rejected_as_invalid_transitions
        """
        scenario = self._one_planned_bus()
        unit_id = scenario["unit"]["id"]
        assert scenario["unit"]["production_status"] == "PLANNED"

        phase_error = ApiErrorId.ERR_UNIT_PHASE_INVALID.value
        validate_error(
            api_client.advance_build(unit_id, "BUILT", PLANT), phase_error, 409
        )
        validate_error(
            api_client.advance_build(unit_id, "BODY_JOINED", PLANT), phase_error, 409
        )
        # Certification reports the phase, not the missing tests it also lacks.
        validate_error(
            api_client.certify_bus_unit(unit_id, COMPLIANCE), phase_error, 409
        )
        # Delivery reports the phase, not the certification it also lacks.
        validate_error(
            api_client.deliver_bus_unit(unit_id, CONTRACTS), phase_error, 409
        )

        unit = read_unit(unit_id)
        assert unit["production_status"] == "PLANNED"
        assert unit["certification_status"] == "PENDING"
        assert unit["service_status"] == "NONE"
        assert unit["certified_at"] in (None, "")
        assert unit["delivered_at"] in (None, "")
        order = read_order(scenario["order"]["id"])
        assert order["delivery_posture"] == "ON_TRACK"
        assert order["created_unit_count"] == 1
        assert order["delivered_unit_count"] == 0


class TestTerminalStatesLockFurtherActions:
    """A released slot and an awarded solicitation accept nothing more."""

    def test_a_released_slot_refuses_both_a_commit_and_a_second_release(self):
        """Release is terminal for a slot, and because the released slot was only
        planned the line never lost a slot-day over it.

        PRD: "A `PlantScheduler` may release a slot that is `PLANNED`, `COMMITTED` or
        `IN_PROGRESS`; a slot already `COMPLETED` or `RELEASED` refuses with
        `ERR_SLOT_STATE_INVALID`."
        PRD: "Releasing a slot that was only `PLANNED` leaves `committed_slot_days`
        untouched, because such a slot never consumed capacity, and leaves the bus's
        `production_status` untouched, because that slot never moved it".

        Design: Corner/state_machines/released_slot_and_awarded_solicitation_are_terminal_and_lock_further_actions
        """
        scenario = setup_awarded_order(
            setup_tx_catalogue(),
            solicitation_overrides={
                "solicitation_code": "SOL-TX-101",
                "price_cap_cents_per_unit": 20_000_000,
            },
        )
        unit = mint_unit(scenario["order"]["id"], "1TXDSL0000000102")
        line = create_line()
        slot = plan_slot(line["id"], unit["id"], "2026-09-07", "2026-09-14")
        released = release_slot(slot["id"])
        assert released["status"] == "RELEASED"

        slot_error = ApiErrorId.ERR_SLOT_STATE_INVALID.value
        validate_error(
            api_client.commit_build_slot(slot["id"], PLANT), slot_error, 409
        )
        validate_error(
            api_client.release_build_slot(slot["id"], PLANT), slot_error, 409
        )
        assert read_slot(slot["id"])["status"] == "RELEASED"
        assert_line_ledger(read_line(line["id"]), 0)
        assert read_unit(unit["id"])["production_status"] == "PLANNED"

    def test_an_awarded_solicitation_cannot_be_closed_again(self):
        """The award carried the solicitation past `CLOSED`, and closing is only ever
        legal while it is open.

        PRD: "The solicitation is `OPEN`: `ERR_SOLICITATION_NOT_OPEN` (409), on
        drafting a bid, appending a bid revision, submitting a bid, requesting a
        revision and closing the solicitation."

        Design: Corner/state_machines/released_slot_and_awarded_solicitation_are_terminal_and_lock_further_actions
        """
        scenario = setup_awarded_order(
            setup_tx_catalogue(),
            solicitation_overrides={
                "solicitation_code": "SOL-TX-101",
                "price_cap_cents_per_unit": 20_000_000,
            },
        )
        solicitation_id = scenario["solicitation"]["id"]
        assert (
            validate_success(api_client.get_solicitation(solicitation_id, SALES))[
                "status"
            ]
            == "AWARDED"
        )

        validate_error(
            api_client.close_solicitation(solicitation_id, CONTRACTS),
            ApiErrorId.ERR_SOLICITATION_NOT_OPEN.value,
            409,
        )
        after = validate_success(api_client.get_solicitation(solicitation_id, SALES))
        assert after["status"] == "AWARDED"


class TestPublicationIsAOneShotTransition:
    """A second publish is a refusal, not a no-op re-stamp."""

    def test_republishing_keeps_the_first_publication_instant(self):
        """The clock has moved a fortnight on, but the refused publish leaves
        `published_at` exactly where the first one set it.

        PRD: "the profile must currently be in `DRAFT`, otherwise the attempt is
        refused with `ERR_PROFILE_NOT_DRAFT`, and on success the transition `DRAFT →
        PUBLISHED` stamps `published_at` with the logical clock's current instant."

        Design: Corner/state_machines/publishing_a_published_profile_twice_reports_profile_not_draft
        """
        set_clock(SUBMIT_INSTANT)
        profile = create_profile(nv_profile_payload())
        assert profile["status"] == "PUBLISHED"
        assert_same_instant(profile["published_at"], SUBMIT_INSTANT, "published_at")

        set_clock(AWARD_INSTANT)
        validate_error(
            api_client.publish_state_spec_profile(profile["id"], COMPLIANCE),
            ApiErrorId.ERR_PROFILE_NOT_DRAFT.value,
            409,
        )

        after = read_profile(profile["id"])
        assert after["status"] == "PUBLISHED"
        assert_same_instant(after["published_at"], SUBMIT_INSTANT, "published_at")
        # A profile never supersedes itself.
        assert after["superseded_by_profile_id"] in (None, "")
        assert after["version"] == profile["version"]


class TestAwardFansOutAcrossFourRecords:
    """One award writes the winner, its siblings, the solicitation and a new order."""

    def _two_solicitations_with_three_submitted_bids(self) -> dict:
        """Two bids competing for one Texas contract and a third bid on a separate
        solicitation that the award must not touch."""
        catalogue = setup_tx_catalogue()
        model_id = catalogue["model"]["id"]
        package_id = catalogue["package"]["id"]
        contested = create_solicitation(
            catalogue["profile"]["id"],
            solicitation_code="SOL-TX-102",
            buyer_type="COOPERATIVE",
            buyer_name="North Texas Coop",
            price_cap_cents_per_unit=20_000_000,
        )
        untouched = create_solicitation(
            catalogue["profile"]["id"],
            solicitation_code="SOL-TX-103",
            buyer_name="Katy ISD",
            price_cap_cents_per_unit=20_000_000,
        )
        winner = create_bid(contested["id"], model_id, package_id, **TX_BID_CONFIG)
        loser_config = dict(TX_BID_CONFIG)
        loser_config["offered_seat_capacity"] = 72
        loser = create_bid(contested["id"], model_id, package_id, **loser_config)
        bystander = create_bid(untouched["id"], model_id, package_id, **TX_BID_CONFIG)

        set_clock(SUBMIT_INSTANT)
        winner = submit_bid(winner["id"])
        loser = submit_bid(loser["id"])
        bystander = submit_bid(bystander["id"])
        close_solicitation(contested["id"])
        return {
            "catalogue": catalogue,
            "contested": contested,
            "untouched": untouched,
            "winner": winner,
            "loser": loser,
            "bystander": bystander,
        }

    def test_the_award_rejects_only_the_siblings_of_the_awarded_solicitation(self):
        """The sibling bid on the same solicitation is rejected, the bid on the other
        solicitation stays submitted, and that other solicitation stays open.

        PRD: "the bid moves `SUBMITTED → AWARDED` with its `version` incremented by
        1, the solicitation moves `CLOSED → AWARDED`, and every *other* bid on that
        solicitation whose status is `SUBMITTED` or `REVISION_REQUESTED` moves to
        `REJECTED`, each with its own `version` incremented by 1, the fan-out
        processed in ascending creation order."

        Design: Corner/state_machines/award_fans_out_rejecting_sibling_bids_and_awarding_the_solicitation
        """
        scene = self._two_solicitations_with_three_submitted_bids()
        set_clock(AWARD_INSTANT)
        # The award brings a new resource into existence, so it answers 201.
        order = validate_success(
            api_client.award_bid(scene["winner"]["id"], "2026-12-01", CONTRACTS_2), 201
        )

        assert read_bid(scene["winner"]["id"])["status"] == "AWARDED"
        assert read_bid(scene["loser"]["id"])["status"] == "REJECTED"
        assert read_bid(scene["bystander"]["id"])["status"] == "SUBMITTED"
        assert (
            validate_success(
                api_client.get_solicitation(scene["contested"]["id"], SALES)
            )["status"]
            == "AWARDED"
        )
        assert (
            validate_success(
                api_client.get_solicitation(scene["untouched"]["id"], SALES)
            )["status"]
            == "OPEN"
        )
        assert order["bid_id"] == scene["winner"]["id"]
        assert order["spec_profile_id"] == scene["catalogue"]["profile"]["id"]

    def test_the_new_order_opens_priced_but_with_no_buses_on_it(self):
        """A bid awarded seventeen days after submission escalates by zero months, so
        the order's unit price is the provisional one and its counters are empty.

        PRD: "The order is created with `status` `ACTIVE` — its only other status is
        `FULFILLED` — a `delivery_posture` of `ON_TRACK`, `created_unit_count` and
        `delivered_unit_count` at 0, `at_risk_unit_count` at 0 and
        `liquidated_damages_cents` at 0."
        PRD: "a bid awarded 17 days after submission has escalated by zero months and
        is not escalated at all."

        Design: Corner/state_machines/award_fans_out_rejecting_sibling_bids_and_awarding_the_solicitation
        """
        scene = self._two_solicitations_with_three_submitted_bids()
        set_clock(AWARD_INSTANT)
        order = validate_success(
            api_client.award_bid(scene["winner"]["id"], "2026-12-01", CONTRACTS_2), 201
        )

        assert order["status"] == "ACTIVE"
        assert order["delivery_posture"] == "ON_TRACK"
        assert order["created_unit_count"] == 0
        assert order["delivered_unit_count"] == 0
        assert order["at_risk_unit_count"] == 0
        assert order["liquidated_damages_cents"] == 0
        assert order["unit_count"] == 1
        assert order["awarded_unit_price_cents"] == TX_AWARDED_UNIT_CENTS
        assert order["total_contract_cents"] == TX_ONE_UNIT_TOTAL_CENTS
        # The bid keeps the provisional figure forever.
        assert (
            read_bid(scene["winner"]["id"])["provisional_unit_price_cents"]
            == TX_AWARDED_UNIT_CENTS
        )


class TestWaiverBranchesOnTheFailedTestType:
    """Two nonconforming buses, one waivable and one not."""

    def _two_built_buses_on_one_line(self) -> dict:
        """Two Texas buses built in adjacent weeks on one line, plus a bay that
        supports every test type."""
        scenario = setup_order_with_units(
            setup_tx_catalogue(),
            vin_list=["1TXDSL0000000103", "1TXDSL0000000104"],
            solicitation_overrides={
                "solicitation_code": "SOL-TX-104",
                "price_cap_cents_per_unit": 20_000_000,
            },
        )
        line = create_line()
        windows = [("2026-09-07", "2026-09-14"), ("2026-09-14", "2026-09-21")]
        slots = []
        for unit, (start, end) in zip(scenario["units"], windows):
            slot = commit_slot(plan_slot(line["id"], unit["id"], start, end)["id"])
            advance_build(unit["id"], "BODY_JOINED")
            advance_build(unit["id"], "BUILT")
            slots.append(slot)
        bay = create_bay(
            supported_test_types=[
                "BRAKE", "EMERGENCY_EXIT", "ELECTRICAL", "JOINT_STRENGTH", "ROLLOVER",
            ],
            max_concurrent_electrical=2,
        )
        scenario.update({"line": line, "slots": slots, "bay": bay})
        return scenario

    def test_a_non_safety_failure_is_waivable_and_a_brake_failure_is_not(self):
        """The bus whose joint coupon failed is waived and its failed test voided,
        while the bus whose brake test failed is refused outright.

        PRD: "A `ComplianceOfficer` may waive a `NONCONFORMING` bus by supplying a
        `waiver_justification`, provided no `FAILED` test of the bus is of type
        `BRAKE` or `ROLLOVER` — brake and rollover failures may never be waived, and
        attempting it draws `ERR_WAIVER_NOT_PERMITTED`."
        PRD: "On success the `waiver_justification` is stored, every `FAILED` test of
        the bus moves to `VOIDED`, the bus moves `NONCONFORMING → WAIVED`".

        Design: Corner/state_machines/waiver_eligibility_depends_on_which_test_type_failed
        """
        scenario = self._two_built_buses_on_one_line()
        waivable, unwaivable = scenario["units"]
        bay_id = scenario["bay"]["id"]
        pass_always_required_tests(waivable["id"], bay_id)

        joint = schedule_test(
            waivable["id"], bay_id, "JOINT_STRENGTH", "2026-09-18", "2026-09-18"
        )
        # The minimum comes from the profile even though no joint test is required.
        assert joint["min_required_value"] == 55.0
        record_result(joint["id"], "FAIL", measured_value=52.0,
                      result_notes="joint coupon below the Texas minimum")
        brake = schedule_test(
            unwaivable["id"], bay_id, "BRAKE", "2026-09-19", "2026-09-19"
        )
        record_result(brake["id"], "FAIL",
                      result_notes="service brake pull beyond tolerance")
        assert read_unit(waivable["id"])["certification_status"] == "NONCONFORMING"
        assert read_unit(unwaivable["id"])["certification_status"] == "NONCONFORMING"

        validate_error(
            api_client.waive_nonconformance(
                unwaivable["id"], "district accepts the brake finding", COMPLIANCE
            ),
            ApiErrorId.ERR_WAIVER_NOT_PERMITTED.value,
            422,
        )
        assert read_unit(unwaivable["id"])["certification_status"] == "NONCONFORMING"
        assert read_test(brake["id"])["status"] == "FAILED"

        waived = validate_success(
            api_client.waive_nonconformance(
                waivable["id"], "joint coupon retest deferred", COMPLIANCE
            )
        )
        assert waived["certification_status"] == "WAIVED"
        assert waived["waiver_justification"] == "joint coupon retest deferred"
        assert read_test(joint["id"])["status"] == "VOIDED"

    def test_a_failure_on_a_completed_slot_unwinds_nothing(self):
        """Both buses had finished their slots before they failed, so the line keeps
        every booked slot-day and neither bus falls back to planning.

        PRD: "Caused by the bus being nonconforming: the bus's build slot in status
        `COMMITTED` or `IN_PROGRESS` moves to `RELEASED`. **If the bus has no such
        slot, hops 2 through 4 do not fire at all** — a failure on a bus whose slot
        was already released costs nothing further."

        Design: Corner/state_machines/waiver_eligibility_depends_on_which_test_type_failed
        """
        scenario = self._two_built_buses_on_one_line()
        first, second = scenario["units"]
        bay_id = scenario["bay"]["id"]
        assert_line_ledger(read_line(scenario["line"]["id"]), 14)

        joint = schedule_test(
            first["id"], bay_id, "JOINT_STRENGTH", "2026-09-18", "2026-09-18"
        )
        record_result(joint["id"], "FAIL", measured_value=52.0)
        brake = schedule_test(second["id"], bay_id, "BRAKE", "2026-09-19", "2026-09-19")
        record_result(brake["id"], "FAIL")

        assert_line_ledger(read_line(scenario["line"]["id"]), 14)
        for unit in (first, second):
            assert read_unit(unit["id"])["production_status"] == "BUILT"
        for slot in scenario["slots"]:
            assert read_slot(slot["id"])["status"] == "COMPLETED"

        # Certification separates the two failures: one bus is missing a required
        # pass, the other has every required pass but an open failure.
        validate_error(
            api_client.certify_bus_unit(second["id"], COMPLIANCE),
            ApiErrorId.ERR_REQUIRED_TEST_MISSING.value,
            422,
        )
        pass_always_required_tests(
            first["id"], bay_id, windows=["2026-09-21", "2026-09-22", "2026-09-23"]
        )
        validate_error(
            api_client.certify_bus_unit(first["id"], COMPLIANCE),
            ApiErrorId.ERR_OPEN_TEST_FAILURE.value,
            422,
        )


class TestDeliveryPreconditionsUnwindOneAtATime:
    """The same delivery call reports a different obstacle each time one is cleared."""

    def test_certification_then_training_then_the_order_closes(self):
        """An uncertified bus, then an untrained one, then a delivered one — and the
        order that has delivered its only bus refuses to mint another.

        PRD: "Its `certification_status` must be `CERTIFIED` or `WAIVED` — a `PENDING`
        or `NONCONFORMING` bus is refused with `ERR_UNIT_NOT_CERTIFIED`".
        PRD: "And its `driver_training_status` must be `COMPLETED`, otherwise
        `ERR_DRIVER_TRAINING_INCOMPLETE`."
        PRD: "Minting against a `FULFILLED` order is refused with
        `ERR_ORDER_NOT_ACTIVE`".

        Design: Corner/state_machines/delivery_gates_unwind_one_precondition_at_a_time
        """
        scenario = setup_unit_ready_to_certify(
            setup_tx_catalogue(),
            vin="1TXDSL0000000105",
            solicitation_overrides={
                "solicitation_code": "SOL-TX-105",
                "price_cap_cents_per_unit": 20_000_000,
            },
        )
        unit_id = scenario["unit"]["id"]
        order_id = scenario["order"]["id"]
        dealer = create_dealer()
        set_clock(DELIVERY_INSTANT)

        validate_error(
            api_client.deliver_bus_unit(unit_id, CONTRACTS),
            ApiErrorId.ERR_UNIT_NOT_CERTIFIED.value,
            422,
        )
        assert read_unit(unit_id)["certification_status"] == "PENDING"

        certified = validate_success(
            api_client.certify_bus_unit(unit_id, COMPLIANCE)
        )
        assert certified["certification_status"] == "CERTIFIED"
        assert_same_instant(certified["certified_at"], DELIVERY_INSTANT, "certified_at")
        validate_success(api_client.assign_dealer(unit_id, dealer["id"], CONTRACTS))

        validate_error(
            api_client.deliver_bus_unit(unit_id, CONTRACTS),
            ApiErrorId.ERR_DRIVER_TRAINING_INCOMPLETE.value,
            409,
        )
        assert read_unit(unit_id)["production_status"] == "BUILT"
        assert read_unit(unit_id)["delivered_at"] in (None, "")

        validate_success(
            api_client.complete_driver_training(
                unit_id, make_dealer_agent_headers(dealer["id"])
            )
        )
        delivered = validate_success(
            api_client.deliver_bus_unit(unit_id, CONTRACTS)
        )
        assert delivered["production_status"] == "DELIVERED"
        assert_same_instant(delivered["delivered_at"], DELIVERY_INSTANT, "delivered_at")

        order = read_order(order_id)
        assert order["status"] == "FULFILLED"
        assert order["delivered_unit_count"] == 1
        assert read_dealer(dealer["id"])["delivered_unit_count"] == 1

        # The order is closed, and that outranks the unit-count ceiling it also hits.
        validate_error(
            api_client.mint_bus_unit(order_id, "1TXDSL0000000106", PLANT),
            ApiErrorId.ERR_ORDER_NOT_ACTIVE.value,
            409,
        )
