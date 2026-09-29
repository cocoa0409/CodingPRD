"""
Arithmetic pinned at the values where a wrong recipe stops being invisible.

Each computation here is chosen so that one plausible mistake — adding both HVAC figures,
billing the whole basis at the second-tier rate, comparing a measured discharge strictly,
or editing the base bank instead of superseding it — changes the answer rather than merely
the wording. The expected figures are derived by hand from the declared rules.
"""

from test_helpers import (
    BuildStatus,
    GridStatus,
    ApiErrorId,
    TestResult,
    TestStatus,
    TestType,
    WarrantyStatus,
    assert_cents,
    assert_program_ledger,
    assert_quantity,
    assert_unset,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

WIDE_TIER_PROGRAM = dict(
    name="Wide-Tier Capacity Incentive",
    tier1_limit_kwh=30,
    tier1_rate_cents_per_kwh=20000,
    tier2_rate_cents_per_kwh=10000,
    per_project_cap_cents=1500000,
    max_stack_pct_of_cost_bp=5000,
)

EXPANSION = dict(
    additional_unit_count=2,
    installed_cost_cents=2400000,
)


class TestLoadSizingUnderTheStandardMethod:
    """The nameplate recipe, run once against a premises with four backed circuits."""

    def test_the_three_sizing_figures_are_the_hand_computed_ones(self, api):
        """Two thousand four hundred square feet size to 21.48, 7.00 and 9.25 kilowatts.

        The lighting term is 7200 volt-amperes, which with the 18000 volt-ampere appliance
        load gives a 25200 volt-ampere subtotal; the demand split keeps the first 3000 whole
        and takes 40 percent of the remaining 22200, giving 11880. The HVAC term is the larger
        of the heating and cooling figures alone, 9600, so the connected load is 21480
        volt-amperes, or 21.48 kilowatts — a recipe that added both HVAC figures would report
        24.36. The two largest backed circuits total 6.0 kilowatts and the remaining two total
        2.0, so the continuous requirement is 7.00, well under the connected load. The only
        motor circuit draws 2.5 kilowatts, giving a 7.5 kilowatt inrush candidate, and a
        quarter of the continuous requirement on top of it gives a surge requirement of 9.25.

        PRD 3.2: "The general lighting term is the `lighting_area_sqft` figure multiplied by 3 volt-amperes per square foot."
        PRD 3.2: "Separately, the HVAC term is the larger of `heating_va` and `cooling_va` — the smaller of the two is discarded, not added."
        PRD 3.2: "The `load_kw` figures of the top 2 ranked circuits are summed to give a top-circuit total; the `load_kw` figures of all remaining circuits are summed to give a remainder total."
        PRD 3.2: "The continuous requirement is the top-circuit total plus half of the remainder total, but never more than `connected_load_kw` — the smaller of those two quantities is taken — rounded half up to two decimals."
        PRD 3.2: "`required_surge_kw` is then that motor surge figure plus 25 percent of the already-computed `required_continuous_kw`, rounded half up to two decimals."

        Design: Corner/calculations/load_sizing_essential_loads_standard_method_correct_result
        """
        project = fixtures.certified_installer(api)
        project = fixtures.site_for(api, project)

        calculation = validate_success(
            api.create_load_calculation(
                factories.load_calculation_payload(project.site_id),
                headers=project.installer_headers,
            ),
            expected_status=201,
        )

        assert_quantity(calculation, "connected_load_kw", 21.48)
        assert calculation["connected_load_kw"] != 24.36
        assert_quantity(calculation, "required_continuous_kw", 7.00)
        assert_quantity(calculation, "required_surge_kw", 9.25)


class TestAnAwardThatNeverLeavesTheFirstTier:
    """A tier boundary above the whole basis, so the second rate is dead weight."""

    def test_the_second_tier_rate_never_enters_the_arithmetic(self, api):
        """Twenty-seven kilowatt-hours under a thirty kilowatt-hour boundary bill at one rate.

        The bank's design energy is the whole basis and it sits below the tier boundary, so the
        first-tier energy is 27.0 kilowatt-hours and the second-tier energy is zero: the raw
        award is 540000 cents at the first-tier rate alone. The limited-export posture pays 9000
        basis points of that, 486000 cents, which is below both the per-project cap and the
        stacking ceiling of half the 3200000-cent installed cost. Exactly that figure moves out
        of the unencumbered bucket and into the encumbered one.

        PRD 3.7: "At reservation the basis is the bank's design `usable_kwh`."
        PRD 3.7: "The first-tier energy is the basis or `tier1_limit_kwh`, whichever is smaller. The second-tier energy is the amount by which the basis exceeds `tier1_limit_kwh`, or zero when the basis does not exceed it."
        PRD 3.7: "The raw award is the first-tier energy multiplied by `tier1_rate_cents_per_kwh` plus the second-tier energy multiplied by `tier2_rate_cents_per_kwh`."
        PRD 3.7: "The export multiplier is read from the claim's `export_commitment`: 7500 basis points for `NON_EXPORT`, 9000 basis points for `LIMITED_EXPORT`, and 10000 basis points for `FULL_EXPORT`."
        PRD 3.7: "The tightest `max_stack_pct_of_cost_bp` among those programs is taken, multiplied by the bank's `installed_cost_cents`, divided by 10000, and floored to a whole number of cents; that figure is the claim's `stack_ceiling_cents`."

        Design: Corner/calculations/rebate_award_wholly_within_tier1_ignores_the_tier2_rate
        """
        project = fixtures.installed_project(api)
        program_id = fixtures.create_state_program(api, project, **WIDE_TIER_PROGRAM)

        claim = fixtures.reserve_claim(api, project, program_id)

        assert_quantity(claim, "basis_kwh_reserved", 27.0)
        assert_cents(claim, "stack_ceiling_cents", 1600000)
        assert_cents(claim, "reserved_amount_cents", 486000)
        program = fixtures.read_program(api, program_id)
        assert_program_ledger(program, remaining=4514000, reserved=486000, paid=0)


class TestTheDischargeThresholdBoundary:
    """Ninety percent of the design energy, hit exactly and then missed by a hundredth."""

    def _three_verdicts_on_record(self, api):
        """An installed bank whose discharge test alone is still awaiting its figure."""
        project = fixtures.installed_project(api)
        project = fixtures.schedule_four_tests(api, project)
        for test_type in (
            TestType.BACKUP_TRANSITION,
            TestType.ANTI_ISLANDING,
            TestType.FIRMWARE_BASELINE,
        ):
            validate_success(
                api.record_test_result(
                    project.test_ids[test_type],
                    factories.result_payload_for(test_type),
                    headers=project.installer_headers,
                )
            )
        return project

    def _read_test(self, api, project, test_type):
        return get_success_data(
            api.get_commissioning_test(
                project.test_ids[test_type], headers=project.installer_headers
            )
        )

    def test_a_discharge_exactly_at_ninety_percent_is_a_pass(self, api):
        """Twenty-four point three kilowatt-hours out of twenty-seven is exactly the bar.

        Ninety percent of the two-unit bank's 27.0 kilowatt-hour design energy is 24.30, and the
        boundary belongs to the passing side, so the recorded verdict is a pass rather than the
        failure a strictly-greater comparison would produce. The other three verdicts, measured
        inside their own ceilings, are passes too, so the bank now carries four passes.

        PRD 3.6: "A `CAPACITY_DISCHARGE` test passes when its `delivered_kwh` is at least 90 percent of the bank's design `usable_kwh`, the boundary being inclusive, and fails otherwise."
        PRD 3.6: "Recording sets `status` to `RECORDED` and stamps `recorded_at` from the logical clock."
        PRD 2.11: "Model `PWX_A` provides 13.5 usable kWh and 5.0 kW of continuous power per unit, permits at most 10 units in one bank, and requires firmware `24.4.0` or newer."

        Design: Corner/calculations/capacity_discharge_exactly_at_ninety_percent_of_usable_passes
        """
        project = self._three_verdicts_on_record(api)

        recorded = validate_success(
            api.record_test_result(
                project.test_ids[TestType.CAPACITY_DISCHARGE],
                factories.capacity_discharge_result_payload(delivered_kwh=24.3),
                headers=project.installer_headers,
            )
        )

        assert recorded["status"] == TestStatus.RECORDED
        assert_quantity(recorded, "delivered_kwh", 24.30)
        assert recorded["result"] == TestResult.PASS
        for test_type in (
            TestType.BACKUP_TRANSITION,
            TestType.ANTI_ISLANDING,
            TestType.FIRMWARE_BASELINE,
        ):
            assert self._read_test(api, project, test_type)["result"] == TestResult.PASS

    def test_a_hundredth_below_the_bar_fails_and_blocks_commissioning(self, api):
        """Twenty-four point two nine kilowatt-hours is one hundredth short of the bar.

        The measured energy misses 24.30 by a hundredth of a kilowatt-hour, so the discharge
        verdict is a failure. All four verdicts are on record and the one that failed is not the
        backup transition, so commissioning is refused with the generic test-failure objection,
        and none of the cascade's first hop lands: the bank is still merely installed, with no
        measured capacity and no commissioning instant, and the installer's commissioned count
        has not moved.

        PRD 3.6: "A `CAPACITY_DISCHARGE` test passes when its `delivered_kwh` is at least 90 percent of the bank's design `usable_kwh`, the boundary being inclusive, and fails otherwise."
        PRD 3.6: "If all four have been recorded and some test other than `BACKUP_TRANSITION` failed, the rejection is `ERR_COMMISSIONING_TEST_FAILED`."
        PRD 3.6: "The first hop sets `build_status` to `COMMISSIONED`, stamps `commissioned_at` from the logical clock, derives `warranty_deadline_at` as `commissioned_at` plus 30 days, copies the `delivered_kwh` of the recorded `CAPACITY_DISCHARGE` test into the bank's `verified_capacity_kwh`, and increments the accountable installer's `commissioned_system_count` by one."

        Design: Corner/calculations/capacity_discharge_one_hundredth_below_threshold_fails_and_blocks_commissioning
        """
        project = fixtures.inspection_passed_project(
            api, result_overrides={TestType.CAPACITY_DISCHARGE: {"delivered_kwh": 24.29}}
        )
        project = fixtures.advance_clock(api, project, fixtures.COMMISSIONING_INSTANT)

        validate_error(
            api.commission(project.battery_system_id, headers=project.installer_headers),
            ApiErrorId.ERR_COMMISSIONING_TEST_FAILED,
            expected_status=422,
        )

        discharge = self._read_test(api, project, TestType.CAPACITY_DISCHARGE)
        assert discharge["result"] == TestResult.FAIL
        system = fixtures.read_system(api, project)
        assert system["build_status"] == BuildStatus.INSTALLED
        assert_unset(system, "verified_capacity_kwh", "commissioned_at")
        installer = get_success_data(
            api.get_installer(project.installer_id, headers=project.installer_headers)
        )
        assert installer["commissioned_system_count"] == 0


class TestExpandingABankInService:
    """Two more units, propagated through the catalog into a brand-new bank row."""

    def test_the_expanded_bank_is_catalog_sized_and_the_base_is_superseded(self, api):
        """Four units of the same model come to 54.0 kilowatt-hours and 20.0 kilowatts.

        The energized two-unit bank takes two more units, and the new row's capacity is derived
        from the catalog rather than from anything the request supplied: four units of the model
        are 54.0 kilowatt-hours and 20.0 kilowatts. The new row points back at the bank it
        replaces, carries the combined installed cost of 5600000 cents, and starts at the
        beginning of both lifecycles with nothing commissioned or warranted on it. The base bank
        is superseded exactly once, and the reverse lookup on the base bank finds precisely the
        one successor.

        PRD 3.8: "Expansion is available only for a bank whose `build_status` is `COMMISSIONED` and whose `grid_status` is `PTO_GRANTED`."
        PRD 3.8: "Its `expands_system_id` points at the base bank's `id`, its `unit_count` is the base count plus `additional_unit_count`, its `installed_cost_cents` is the base bank's installed cost plus the supplied additional cost, and its `site_id`, `installer_id`, `load_calculation_id` and `model_code` are copied from the base bank while its `inverter_model` and `firmware_version` come from the request."
        PRD 3.8: "The new row starts fresh: `build_status` of `DESIGN_DRAFT`, `grid_status` of `NOT_APPLIED`, `warranty_status` of `UNREGISTERED`, and no `verified_capacity_kwh`, `commissioned_at`, `warranty_deadline_at`, `warranty_registered_at`, `warranty_coverage_years` or `serial_numbers` — the expanded bank must be permitted, approved, installed, commissioned and registered on its own account."
        PRD 3.8: "Its first hop sets the base bank's `build_status` to `SUPERSEDED`."
        PRD 2.11: "A bank's `usable_kwh` is its `unit_count` multiplied by the per-unit usable energy of its model, and its `continuous_kw` is its `unit_count` multiplied by the per-unit continuous power of its model, each rounded half up to two decimals."

        Design: Corner/calculations/expansion_propagates_catalog_capacity_and_supersedes_the_base_bank
        """
        project = fixtures.pto_granted_project(api)
        base_id = project.battery_system_id

        expanded = validate_success(
            api.expand_system(
                base_id,
                factories.expansion_payload(
                    fixtures.system_version(api, project), **EXPANSION
                ),
                headers=project.installer_headers,
            ),
            expected_status=201,
        )

        assert expanded["id"] != base_id
        assert expanded["unit_count"] == 4
        assert_quantity(expanded, "usable_kwh", 54.0)
        assert_quantity(expanded, "continuous_kw", 20.0)
        assert expanded["expands_system_id"] == base_id
        assert_cents(expanded, "installed_cost_cents", 5600000)
        assert expanded["build_status"] == BuildStatus.DESIGN_DRAFT
        assert expanded["grid_status"] == GridStatus.NOT_APPLIED
        assert expanded["warranty_status"] == WarrantyStatus.UNREGISTERED
        assert_unset(
            expanded,
            "verified_capacity_kwh",
            "commissioned_at",
            "warranty_deadline_at",
            "warranty_registered_at",
            "warranty_coverage_years",
        )

        base = fixtures.read_system(api, project)
        assert base["build_status"] == BuildStatus.SUPERSEDED
        successors, _ = validate_paginated(
            api.list_battery_systems(
                {"expands_system_id": base_id}, headers=project.installer_headers
            )
        )
        assert [system["id"] for system in successors] == [expanded["id"]]
