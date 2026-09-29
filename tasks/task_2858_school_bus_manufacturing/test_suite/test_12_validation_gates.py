"""Validation gates: inclusive boundaries, aggregate ceilings and re-gated items."""

from test_helpers import (
    CA_BID_CONFIG,
    COMPLIANCE,
    CONTRACTS,
    CONTRACTS_2,
    PLANT,
    QUALITY,
    SALES,
    ApiErrorId,
    api_client,
    assert_contract_order,
    assert_line_ledger,
    assert_same_instant,
    award_bid,
    bid_payload,
    build_slot_payload,
    ca_profile_payload,
    close_solicitation,
    commit_slot,
    create_bay,
    create_bus_model,
    create_line,
    create_profile,
    create_propulsion_package,
    create_solicitation,
    diesel_package_payload,
    nv_profile_payload,
    plan_slot,
    quality_test_payload,
    read_bid,
    read_line,
    read_order,
    read_slot,
    read_test,
    read_unit,
    record_result,
    record_result_payload,
    schedule_test,
    set_clock,
    setup_built_unit,
    setup_ca_catalogue,
    setup_nv_catalogue,
    setup_order_with_units,
    setup_submitted_bid,
    setup_tx_catalogue,
    tx_profile_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

AWARD_INSTANT = "2026-09-01T00:00:00Z"
SUBMIT_INSTANT = "2026-08-15T00:00:00Z"
# Seventeen days on the table escalate the offer by nothing at all.
TX_AWARDED_UNIT_CENTS = 14_641_571

# An unoptioned offer, for a state that mandates nothing beyond the base body.
BASE_BID_CONFIG = {
    "offered_seat_capacity": 71,
    "offered_emergency_exit_count": 5,
    "offered_mirror_config": "STANDARD",
    "offered_lap_shoulder_belts": False,
    "offered_eight_lamp_system": False,
    "offered_crossing_arm": False,
    "offered_rollover_reinforcement": False,
}


class TestThePromiseMayEqualTheRequiredDateButNotExceedIt:
    """The award-time promise check is inclusive on the required date."""

    def test_one_day_past_the_required_date_is_refused_and_equality_is_awarded(self):
        """The refused award writes nothing, so the very next attempt at the required
        date itself produces the order.

        PRD: "And the `promised_delivery_date` must fall on or before the
        solicitation's `required_delivery_date`, otherwise
        `ERR_PROMISE_EXCEEDS_REQUIRED_DATE`."
        PRD: "A successful award mints a **Contract Order** recording the `bid_id` it
        came from, the `spec_profile_id` of the profile that is published at award
        time, the `unit_count` copied from the bid, and the `promised_delivery_date`."

        Design: Corner/validations/promised_delivery_date_passes_at_equality_and_fails_one_day_later
        """
        scenario = setup_submitted_bid(
            setup_tx_catalogue(),
            submit_clock=SUBMIT_INSTANT,
            solicitation_overrides={
                "solicitation_code": "SOL-TX-110",
                "buyer_name": "Plano ISD",
                "required_delivery_date": "2026-12-01",
                "price_cap_cents_per_unit": 20_000_000,
            },
        )
        bid_id = scenario["bid"]["id"]
        solicitation_id = scenario["solicitation"]["id"]
        close_solicitation(solicitation_id)
        set_clock(AWARD_INSTANT)

        refused = api_client.award_bid(bid_id, "2026-12-02", CONTRACTS_2)
        validate_error(
            refused, ApiErrorId.ERR_PROMISE_EXCEEDS_REQUIRED_DATE.value, 422
        )
        assert read_bid(bid_id)["status"] == "SUBMITTED"
        assert validate_success(
            api_client.get_solicitation(solicitation_id, CONTRACTS)
        )["status"] == "CLOSED"

        order = validate_success(
            api_client.award_bid(bid_id, "2026-12-01", CONTRACTS_2), 201
        )
        assert_contract_order(order)
        assert order["status"] == "ACTIVE"
        assert order["promised_delivery_date"] == "2026-12-01"
        assert order["awarded_unit_price_cents"] == TX_AWARDED_UNIT_CENTS
        assert order["created_unit_count"] == 0
        assert read_bid(bid_id)["status"] == "AWARDED"


class TestHorizonCapacityIsAnAggregateCheckedAtCommit:
    """Planning never consults capacity; committing compares against the total."""

    def test_the_second_week_is_planned_freely_and_refused_at_commit(self):
        """A thirteen-day line takes one seven-day booking, refuses the commit of a
        second, and then accepts a six-day slot that lands exactly on the ceiling.

        PRD: "the line's `committed_slot_days` plus the slot's `slot_days` must not
        exceed the line's `horizon_slot_day_capacity`, otherwise
        `ERR_LINE_CAPACITY_EXCEEDED`."
        PRD: "Creating the slot increments the line's `version` by 1 and leaves
        `committed_slot_days` untouched, because a plan books no capacity."

        Design: Corner/validations/line_horizon_capacity_is_checked_at_commit_against_the_running_total
        """
        scenario = setup_order_with_units(
            setup_tx_catalogue(),
            vin_list=[
                "1TXDSL0000000501",
                "1TXDSL0000000502",
                "1TXDSL0000000503",
            ],
            solicitation_overrides={
                "solicitation_code": "SOL-TX-111",
                "buyer_type": "COOPERATIVE",
                "buyer_name": "North Texas Coop",
                "price_cap_cents_per_unit": 20_000_000,
            },
        )
        first, second, third = scenario["units"]
        line = create_line(
            line_code="L-TIGHT",
            supported_body_classes=["TYPE_C"],
            horizon_slot_day_capacity=13,
        )
        line_id = line["id"]

        commit_slot(plan_slot(line_id, first["id"], "2026-09-07", "2026-09-14")["id"])
        assert_line_ledger(read_line(line_id), 7)

        over = plan_slot(line_id, second["id"], "2026-09-14", "2026-09-21")
        assert over["slot_days"] == 7
        assert over["status"] == "PLANNED"
        version_before = read_line(line_id)["version"]

        refused = api_client.commit_build_slot(over["id"], PLANT)
        validate_error(refused, ApiErrorId.ERR_LINE_CAPACITY_EXCEEDED.value, 409)
        after_refusal = read_line(line_id)
        assert_line_ledger(after_refusal, 7)
        assert after_refusal["version"] == version_before
        assert read_slot(over["id"])["status"] == "PLANNED"
        assert read_unit(second["id"])["production_status"] == "PLANNED"

        # Six more days fit exactly: the comparison is strictly greater.
        fits = plan_slot(line_id, third["id"], "2026-09-21", "2026-09-27")
        assert fits["slot_days"] == 6
        committed = commit_slot(fits["id"])
        assert committed["status"] == "COMMITTED"
        final = read_line(line_id)
        assert_line_ledger(final, 13)
        assert final["committed_slot_days"] == final["horizon_slot_day_capacity"]


class TestSlotWindowsAreNonEmptyAndLeaveFinishingTime:
    """Two refusals that touch nothing, and one window that satisfies the lead rule
    at equality."""

    def test_an_empty_window_and_a_late_window_are_both_refused(self):
        """A same-day window is refused before any arithmetic, a window ending one day
        too late misses the finishing lead time, and neither moves the line.

        PRD: "First, `end_date` must be strictly after `start_date`, so the narrowest
        legal slot is one day wide; otherwise `ERR_INVALID_SLOT_WINDOW`."
        PRD: "Fourth, the slot must leave 21 days of finishing lead time: the
        `end_date` plus 21 days must fall on or before the promised delivery date of
        the bus's contract order, otherwise `ERR_SLOT_MISSES_DEADLINE`".

        Design: Corner/validations/slot_window_must_be_non_empty_and_finish_before_the_promise_lead_time
        """
        scenario = setup_order_with_units(
            setup_tx_catalogue(),
            vin_list=["1TXDSL0000000531"],
            promised_delivery_date="2026-10-05",
            solicitation_overrides={
                "solicitation_code": "SOL-TX-114",
                "required_delivery_date": "2026-10-05",
                "price_cap_cents_per_unit": 20_000_000,
            },
        )
        unit_id = scenario["units"][0]["id"]
        line = create_line()
        line_id = line["id"]
        version = line["version"]
        assert version == 1

        empty = api_client.create_build_slot(
            build_slot_payload(
                version, line_id, unit_id, "2026-09-10", "2026-09-10"
            ),
            PLANT,
        )
        validate_error(empty, ApiErrorId.ERR_INVALID_SLOT_WINDOW.value, 422)

        # 2026-09-15 plus 21 days is 2026-10-06, one day past the promise.
        late = api_client.create_build_slot(
            build_slot_payload(
                version, line_id, unit_id, "2026-09-10", "2026-09-15"
            ),
            PLANT,
        )
        validate_error(late, ApiErrorId.ERR_SLOT_MISSES_DEADLINE.value, 409)

        # 2026-09-14 plus 21 days is the promise itself, which satisfies the rule.
        accepted = validate_success(
            api_client.create_build_slot(
                build_slot_payload(
                    version, line_id, unit_id, "2026-09-07", "2026-09-14"
                ),
                PLANT,
            ),
            201,
        )
        assert accepted["slot_days"] == 7
        assert accepted["status"] == "PLANNED"
        final = read_line(line_id)
        assert final["version"] == version + 1
        assert_line_ledger(final, 0)
        assert read_order(scenario["order"]["id"])["created_unit_count"] == 1


class TestMintReGatesTheEngineeringItemsAgainstTheFrozenProfile:
    """A bid that conformed at submit can still be blocked at minting, because the
    order froze a profile the bid was never measured against."""

    def _submitted_bid_then_a_stricter_publication(self, catalogue, profile_payload,
                                                   *, solicitation_overrides,
                                                   bid_config=None) -> dict:
        """Submit under the published profile, then publish a stricter successor and
        award, so the order carries the successor."""
        scenario = setup_submitted_bid(
            catalogue,
            submit_clock=SUBMIT_INSTANT,
            solicitation_overrides=solicitation_overrides,
            bid_config=bid_config,
        )
        assert scenario["bid"]["spec_compliance_status"] == "CONFORMING"
        assert scenario["bid"]["evaluated_spec_profile_id"] == scenario["profile"]["id"]

        scenario["successor"] = create_profile(profile_payload, publish=True)
        close_solicitation(scenario["solicitation"]["id"])
        set_clock(AWARD_INSTANT)
        scenario["order"] = award_bid(scenario["bid"]["id"], "2026-12-01")
        return scenario

    def test_the_frozen_successor_blocks_the_mint_on_joint_strength(self):
        """Raising the Texas joint-strength minimum to 70 kilonewtons between submit
        and award leaves the awarded body at 58 and refuses the mint.

        PRD: "This is also where the two mandatory engineering items skipped at award
        are finally re-gated against that profile: the bus's derated route range must
        be at least the profile's `required_route_range_mi`, or the mint is refused
        with `ERR_ROUTE_RANGE_INSUFFICIENT`, and its joint strength must be at least
        the profile's `min_joint_strength_kn`, or it is refused with
        `ERR_JOINT_STRENGTH_INSUFFICIENT`."

        Design: Corner/validations/unit_minting_re_gates_the_engineering_items_against_the_award_time_profile
        """
        catalogue = setup_tx_catalogue()
        scenario = self._submitted_bid_then_a_stricter_publication(
            catalogue,
            tx_profile_payload(min_joint_strength_kn=70.0),
            solicitation_overrides={
                "solicitation_code": "SOL-TX-112",
                "buyer_name": "Plano ISD",
                "required_delivery_date": "2026-12-01",
                "price_cap_cents_per_unit": 20_000_000,
            },
        )
        order = scenario["order"]
        assert order["spec_profile_id"] == scenario["successor"]["id"]
        assert order["spec_profile_id"] != catalogue["profile"]["id"]
        # The award-time upgrade cannot raise joint strength: no rollover was needed.
        assert order["awarded_joint_strength_kn"] == 58.0
        assert order["awarded_rollover_reinforcement"] is False

        refused = api_client.mint_bus_unit(
            order["id"], "1TXDSL0000000511", PLANT
        )
        validate_error(
            refused, ApiErrorId.ERR_JOINT_STRENGTH_INSUFFICIENT.value, 422
        )
        assert read_order(order["id"])["created_unit_count"] == 0
        assert read_bid(scenario["bid"]["id"])["status"] == "AWARDED"

    def test_the_frozen_successor_blocks_the_mint_on_derated_route_range(self):
        """Raising the Nevada route requirement to 100 miles between submit and award
        refuses a bus whose rolling-terrain range is 79.7.

        PRD: "Every one of these comparisons has an inclusive boundary: a derated
        route range of exactly `79.7` miles satisfies a required route range of
        `79.7`."
        PRD: "The `derated_route_range_mi` figure is at least the governing profile's
        `required_route_range_mi`: `ERR_ROUTE_RANGE_INSUFFICIENT` (422), on minting a
        bus and on certifying a bus."

        Design: Corner/validations/unit_minting_re_gates_the_engineering_items_against_the_award_time_profile
        """
        catalogue = setup_nv_catalogue(propulsion="ELECTRIC", terrain_class="ROLLING")
        scenario = self._submitted_bid_then_a_stricter_publication(
            catalogue,
            nv_profile_payload(
                terrain_class="ROLLING", required_route_range_mi=100.0
            ),
            solicitation_overrides={
                "solicitation_code": "SOL-NV-112",
                "buyer_name": "Washoe County SD",
                "required_delivery_date": "2026-12-01",
                "price_cap_cents_per_unit": 40_000_000,
            },
            bid_config=BASE_BID_CONFIG,
        )
        assert scenario["bid"]["derated_route_range_mi"] == 79.7
        order = scenario["order"]
        assert order["spec_profile_id"] == scenario["successor"]["id"]

        refused = api_client.mint_bus_unit(
            order["id"], "1NVELE0000000512", PLANT
        )
        validate_error(refused, ApiErrorId.ERR_ROUTE_RANGE_INSUFFICIENT.value, 422)
        assert read_order(order["id"])["created_unit_count"] == 0


class TestTheRequiredTestSetExpandsWithTheProfileFlags:
    """California switches on both optional test mandates, so three passes are not
    enough and two of the tests carry minimum values."""

    def _california_bus_built_with_two_bays(self) -> dict:
        """A fully-optioned electric Type C built on a Californian order, with one bay
        for the four routine test types and a second bay for rollover alone."""
        scenario = setup_built_unit(
            setup_ca_catalogue(),
            vin="1CAELE0000000521",
            bid_config=CA_BID_CONFIG,
            solicitation_overrides={
                "solicitation_code": "SOL-CA-113",
                "buyer_name": "Fresno USD",
                "required_delivery_date": "2026-12-01",
                "price_cap_cents_per_unit": 32_000_000,
            },
        )
        scenario["bay"] = create_bay(
            bay_code="TB-CA",
            supported_test_types=[
                "BRAKE", "EMERGENCY_EXIT", "ELECTRICAL", "JOINT_STRENGTH",
            ],
            max_concurrent_electrical=2,
        )
        scenario["rollover_bay"] = create_bay(
            bay_code="TB-ROLL",
            supported_test_types=["ROLLOVER"],
            max_concurrent_electrical=1,
        )
        assert scenario["unit"]["production_status"] == "BUILT"
        assert scenario["unit"]["joint_strength_kn"] == 67.5
        return scenario

    def _pass_the_four_bay_tests(self, unit_id: str, bay_id: str) -> list:
        """Brake, emergency exit, electrical and joint strength, one day apart."""
        passed = []
        for test_type, day in (
            ("BRAKE", "2026-09-15"),
            ("EMERGENCY_EXIT", "2026-09-16"),
            ("ELECTRICAL", "2026-09-17"),
        ):
            test = schedule_test(unit_id, bay_id, test_type, day, day)
            passed.append(record_result(test["id"], "PASS"))
        joint = schedule_test(
            unit_id, bay_id, "JOINT_STRENGTH", "2026-09-18", "2026-09-18"
        )
        passed.append(record_result(joint["id"], "PASS", measured_value=65.0))
        return passed

    def test_a_reversed_window_is_refused_and_the_joint_minimum_is_enforced(self):
        """The routine test types carry no minimum, the joint-strength test takes 62.5
        from the profile, and a pass below that minimum is refused while leaving the
        test schedulable for a second attempt.

        PRD: "Unlike a build slot, a test window is a **closed** interval: both
        endpoints are occupied, so `window_end` need only fall on or after
        `window_start` — a single-day window is perfectly legal — and anything earlier
        draws `ERR_INVALID_TEST_WINDOW`."
        PRD: "When the test's `min_required_value` is present, `measured_value` is
        required, and a `PASS` additionally requires that `measured_value` be at least
        the minimum".

        Design: Corner/validations/required_test_set_expands_with_the_profile_flags
        """
        scenario = self._california_bus_built_with_two_bays()
        unit_id = scenario["unit"]["id"]
        bay_id = scenario["bay"]["id"]

        reversed_window = api_client.create_quality_test(
            quality_test_payload(
                unit_id, bay_id, "BRAKE", "2026-09-16", "2026-09-14"
            ),
            QUALITY,
        )
        validate_error(reversed_window, ApiErrorId.ERR_INVALID_TEST_WINDOW.value, 422)
        _, meta = validate_paginated(
            api_client.list_quality_tests(QUALITY, {"bus_unit_id": unit_id})
        )
        assert meta["total_count"] == 0

        brake = schedule_test(unit_id, bay_id, "BRAKE", "2026-09-15", "2026-09-15")
        assert brake["min_required_value"] in (None, "")
        assert record_result(brake["id"], "PASS")["status"] == "PASSED"

        joint = schedule_test(
            unit_id, bay_id, "JOINT_STRENGTH", "2026-09-18", "2026-09-18"
        )
        assert joint["min_required_value"] == 62.5

        below = api_client.record_test_result(
            joint["id"], record_result_payload("PASS", measured_value=60.0), QUALITY
        )
        validate_error(
            below, ApiErrorId.ERR_MEASURED_VALUE_BELOW_MINIMUM.value, 422
        )
        assert read_test(joint["id"])["status"] == "SCHEDULED"

        retried = record_result(joint["id"], "PASS", measured_value=65.0)
        assert retried["status"] == "PASSED"
        assert retried["measured_value"] == 65.0

    def test_four_passes_are_not_enough_until_the_rollover_test_is_recorded(self):
        """Certification is refused while rollover is outstanding, the rollover test
        only fits the bay that supports it, its minimum comes from the curb weight, and
        it cannot be recorded twice.

        PRD: "Every test type in the profile-conditional required set must have a
        `PASSED` test, otherwise `ERR_REQUIRED_TEST_MISSING`".
        PRD: "The requested `test_type` must appear in the bay's
        `supported_test_types`, otherwise `ERR_TEST_TYPE_UNSUPPORTED`."
        PRD: "The test must still be `SCHEDULED`, otherwise `ERR_TEST_NOT_SCHEDULED`;
        a `PASSED`, `FAILED` or `VOIDED` test is terminal and cannot be re-recorded."

        Design: Corner/validations/required_test_set_expands_with_the_profile_flags
        """
        scenario = self._california_bus_built_with_two_bays()
        unit_id = scenario["unit"]["id"]
        bay_id = scenario["bay"]["id"]
        self._pass_the_four_bay_tests(unit_id, bay_id)

        premature = api_client.certify_bus_unit(unit_id, COMPLIANCE)
        validate_error(premature, ApiErrorId.ERR_REQUIRED_TEST_MISSING.value, 422)
        assert read_unit(unit_id)["certification_status"] == "PENDING"

        wrong_bay = api_client.create_quality_test(
            quality_test_payload(
                unit_id, bay_id, "ROLLOVER", "2026-09-19", "2026-09-19"
            ),
            QUALITY,
        )
        validate_error(wrong_bay, ApiErrorId.ERR_TEST_TYPE_UNSUPPORTED.value, 422)

        rollover = schedule_test(
            unit_id, scenario["rollover_bay"]["id"], "ROLLOVER",
            "2026-09-19", "2026-09-19",
        )
        # 21,500 pounds at 0.0025 kilonewtons a pound, half up to the cent.
        assert rollover["min_required_value"] == 53.75
        recorded = record_result(rollover["id"], "PASS", measured_value=60.0)
        assert recorded["status"] == "PASSED"

        again = api_client.record_test_result(
            rollover["id"], record_result_payload("PASS", measured_value=55.0), QUALITY
        )
        validate_error(again, ApiErrorId.ERR_TEST_NOT_SCHEDULED.value, 409)
        unchanged = read_test(rollover["id"])
        assert unchanged["measured_value"] == 60.0
        assert unchanged["recorded_at"] == recorded["recorded_at"]

        certified = validate_success(
            api_client.certify_bus_unit(unit_id, COMPLIANCE)
        )
        assert certified["certification_status"] == "CERTIFIED"
        assert_same_instant(certified["certified_at"], AWARD_INSTANT, "certified_at")


class TestSubmitReportsTheComplianceVerdictBeforeThePriceCap:
    """A nonconforming draft is stored happily and refused only at submit."""

    def test_the_nonconforming_verdict_outranks_the_price_cap_breach(self):
        """The base body against every Californian mandate is stored with three unmet
        mandatory items and five exceptions, and submitting it reports the compliance
        failure rather than the cap breach it also commits.

        PRD: "The verdict in `spec_compliance_status` is `NONCONFORMING` whenever
        `unmet_mandatory_items` is non-empty, `EXCEPTIONS_TAKEN` when that list is
        empty and `exception_count` is at least 1, and `CONFORMING` when the list is
        empty and the count is zero."
        PRD: "If that recomputed verdict is `NONCONFORMING`, the submission is refused
        with `ERR_SPEC_NONCONFORMING`".

        Design: Corner/validations/submitting_a_nonconforming_bid_reports_the_compliance_violation
        """
        model = create_bus_model()
        package = create_propulsion_package(diesel_package_payload(model["id"]))
        profile = create_profile(ca_profile_payload(), publish=True)
        solicitation = create_solicitation(
            profile["id"],
            solicitation_code="SOL-CA-115",
            buyer_name="Fresno USD",
            price_cap_cents_per_unit=10_000_000,
        )

        bid = validate_success(
            api_client.create_bid(
                bid_payload(solicitation["id"], model["id"], package["id"]), SALES
            ),
            201,
        )
        assert bid["spec_compliance_status"] == "NONCONFORMING"
        assert bid["unmet_mandatory_items"] == [
            "joint_strength", "rollover_protection", "emergency_exits"
        ]
        assert bid["exception_count"] == 5
        assert bid["offered_joint_strength_kn"] == 58.0
        assert bid["provisional_unit_price_cents"] == 14_332_501
        assert bid["provisional_unit_price_cents"] > 10_000_000

        refused = api_client.submit_bid(bid["id"], SALES)
        validate_error(refused, ApiErrorId.ERR_SPEC_NONCONFORMING.value, 422)

        after = read_bid(bid["id"])
        assert after["status"] == "DRAFT"
        assert after["submitted_at"] in (None, "")
        assert after["exception_count"] == 5
