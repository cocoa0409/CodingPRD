"""
Gates that read a set rather than a single field, and a gate a flag turns off.

The commissioning gate is satisfied by a collection — four types, each recorded, each passing
— so a bank can hold nothing but passes and still fail it. The export-commitment gate is
conditional on the funding program's own flag, so the very same claim is refused by one pool
and accepted by another.
"""

from test_helpers import (
    BuildStatus,
    ExportMode,
    GridStatus,
    ApiErrorId,
    TestType,
    WarrantyStatus,
    assert_cents,
    assert_instant_equals,
    assert_program_ledger,
    assert_quantity,
    assert_stamped_from_clock,
    assert_unset,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

COMMISSIONING_INSTANT = "2026-08-10T17:00:00Z"
WARRANTY_DEADLINE = "2026-09-09T17:00:00Z"

UTILITY_PROGRAM = dict(
    total_budget_cents=2000000,
    per_project_cap_cents=400000,
    min_capacity_commitment_kw=5.0,
)


class TestTheFourTestCommissioningGate:
    """Three passes are not the gate; the gate is one recorded pass of each type."""

    def _three_of_the_four_types_recorded(self, api):
        """An installed, inspected bank with no firmware baseline ever booked."""
        project = fixtures.installed_project(api)
        for test_type, window_start, window_end in factories.FOUR_TEST_WINDOWS[:3]:
            booked = validate_success(
                api.create_commissioning_test(
                    factories.commissioning_test_payload(
                        project.battery_system_id, test_type, window_start, window_end
                    ),
                    headers=project.installer_headers,
                ),
                expected_status=201,
            )
            project.test_ids[test_type] = booked["id"]
            validate_success(
                api.record_test_result(
                    booked["id"],
                    factories.result_payload_for(test_type),
                    headers=project.installer_headers,
                )
            )
        project = fixtures.pass_inspection(api, project)
        return fixtures.advance_clock(api, project, COMMISSIONING_INSTANT)

    def test_a_missing_test_type_blocks_commissioning_though_every_verdict_passed(self, api):
        """The transition test, the discharge test and the islanding test all passed.

        Nothing on this bank has failed: three verdicts are recorded and all three are passes.
        What is missing is the fourth type, which was never booked at all, so the completeness
        half of the safety gate is unsatisfied and the request is refused as incomplete rather
        than as failed. The bank holds exactly the three tests it booked and is still merely
        installed, with no commissioning instant on it.

        PRD 3.6: "Its safety gate is evaluated before any of its temporal gates: for each of the four test types there must be exactly one test of that type on the bank whose `status` is `RECORDED`, and every one of the four must have a `result` of `PASS`."
        PRD 3.6: "A missing type, or a type still sitting at `SCHEDULED`, is rejected with `ERR_COMMISSIONING_TESTS_INCOMPLETE`."
        PRD 3.6: "**Commissioning the bank.** Commissioning advances the bank `INSTALLED → COMMISSIONED`."

        Design: Corner/validations/commission_without_the_firmware_baseline_test_returns_tests_incomplete
        """
        project = self._three_of_the_four_types_recorded(api)

        validate_error(
            api.commission(project.battery_system_id, headers=project.installer_headers),
            ApiErrorId.ERR_COMMISSIONING_TESTS_INCOMPLETE,
            expected_status=422,
        )

        tests, meta = validate_paginated(
            api.list_commissioning_tests(
                {"battery_system_id": project.battery_system_id},
                headers=project.installer_headers,
            )
        )
        assert meta["total_count"] == 3
        assert len(tests) == 3
        assert TestType.FIRMWARE_BASELINE not in [test["test_type"] for test in tests]
        system = fixtures.read_system(api, project)
        assert system["build_status"] == BuildStatus.INSTALLED
        assert_unset(system, "commissioned_at")

    def test_the_fourth_passing_test_opens_the_gate_and_the_cascade_lands(self, api):
        """With all four types recorded and passing, every first-hop side effect appears.

        The bank commissions at the instant the clock reads, and the registration deadline is
        derived from that instant as thirty days later rather than from any other date. The
        measured energy of the discharge test is copied onto the bank as its verified capacity,
        and the accountable installer's commissioned counter reaches one. The other two
        dimensions are untouched: the warranty is still unregistered, because registration is a
        separate step, and the grid dimension is still where the utility left it.

        PRD 3.6: "The first hop sets `build_status` to `COMMISSIONED`, stamps `commissioned_at` from the logical clock, derives `warranty_deadline_at` as `commissioned_at` plus 30 days, copies the `delivered_kwh` of the recorded `CAPACITY_DISCHARGE` test into the bank's `verified_capacity_kwh`, and increments the accountable installer's `commissioned_system_count` by one."
        PRD 3.6: "**Warranty registration.** Once a bank is commissioned, the installer registers the manufacturer warranty by supplying the `coverage_years` term and the `serial_numbers` of the individual units, whose count must equal the bank's `unit_count`."
        PRD 3.3: "A new bank opens at `build_status` of `DESIGN_DRAFT` and `grid_status` of `NOT_APPLIED`, with `warranty_status` of `UNREGISTERED`, `verified_capacity_kwh` unset, and `expands_system_id` null because it is an original build rather than an expansion."
        PRD 2.8: "Neither dimension implies anything about the other."

        Design: Corner/validations/commission_with_all_four_tests_passing_stamps_warranty_window_and_capacity
        """
        project = fixtures.inspection_passed_project(api)
        project = fixtures.advance_clock(api, project, COMMISSIONING_INSTANT)

        system = validate_success(
            api.commission(project.battery_system_id, headers=project.installer_headers)
        )

        assert system["build_status"] == BuildStatus.COMMISSIONED
        assert_stamped_from_clock(system, "commissioned_at", COMMISSIONING_INSTANT)
        assert_instant_equals(
            system["warranty_deadline_at"], WARRANTY_DEADLINE, "warranty_deadline_at"
        )
        assert_quantity(system, "verified_capacity_kwh", 25.65)
        assert system["warranty_status"] == WarrantyStatus.UNREGISTERED
        assert system["grid_status"] == GridStatus.APPROVED_TO_INSTALL
        installer = get_success_data(
            api.get_installer(project.installer_id, headers=project.installer_headers)
        )
        assert installer["commissioned_system_count"] == 1


class TestTheProgramFlagThatTurnsTheExportGateOn:
    """One posture, two pools: the flag decides whether the posture is acceptable."""

    def _two_pools(self, api):
        """An installed bank, one pool demanding export and one indifferent to it."""
        project = fixtures.installed_project(api)
        utility_id = fixtures.create_utility_program(api, project, **UTILITY_PROGRAM)
        state_id = fixtures.create_state_program(api, project)
        return project, utility_id, state_id

    def test_the_demanding_pool_refuses_the_non_export_claim_and_holds_nothing(self, api):
        """A household that will not export cannot draw on a pool that requires exporting.

        The pool's flag is set, so the claim's posture must not be the non-exporting one, and
        this claim's is. The refusal is the export-commitment objection, and because the
        reservation is rejected whole, the pool is exactly as it was at creation: nothing
        encumbered and the entire budget still unencumbered.

        PRD 3.7: "When the program's `requires_export_commitment` is true, the claim's `export_commitment` must not be `NON_EXPORT` and the bank's interconnection `export_mode` must not be `NON_EXPORT` either, else `ERR_EXPORT_COMMITMENT_REQUIRED`."
        PRD 2.10: "At program creation `remaining_budget_cents` equals `total_budget_cents` and the other two buckets are zero."

        Design: Corner/validations/export_commitment_flag_rejects_non_export_claim_but_permits_it_when_flag_absent
        """
        project, utility_id, _ = self._two_pools(api)

        validate_error(
            api.create_claim(
                factories.claim_payload(
                    project.battery_system_id,
                    utility_id,
                    fixtures.system_version(api, project),
                    export_commitment=ExportMode.NON_EXPORT,
                ),
                headers=project.installer_headers,
            ),
            ApiErrorId.ERR_EXPORT_COMMITMENT_REQUIRED,
            expected_status=422,
        )

        utility = fixtures.read_program(api, utility_id)
        assert_program_ledger(utility, remaining=2000000, reserved=0, paid=0)
        claims, _ = validate_paginated(
            api.list_claims(
                {"program_id": utility_id}, headers=project.installer_headers
            )
        )
        assert claims == [], "a refused reservation left a claim behind"

    def test_the_indifferent_pool_accepts_the_same_posture_at_the_lowest_multiplier(self, api):
        """The identical claim goes through where the flag is absent, priced at 7500 basis points.

        With the flag unset the export gate never runs, so the non-exporting posture is
        acceptable and the award is computed from it. The basis is the bank's 27.0 kilowatt-hour
        design energy, which bills 20 kilowatt-hours at the first-tier rate and the remaining 7
        at the second, a raw award of 470000 cents; the non-exporting multiplier keeps three
        quarters of that, 352500 cents, and that exact figure is encumbered.

        PRD 3.7: "`requires_export_commitment` is a boolean that defaults to false, and `min_capacity_commitment_kw` is the least dispatchable capacity a claim must commit and must be non-negative."
        PRD 3.7: "The export multiplier is read from the claim's `export_commitment`: 7500 basis points for `NON_EXPORT`, 9000 basis points for `LIMITED_EXPORT`, and 10000 basis points for `FULL_EXPORT`."
        PRD 3.7: "At reservation the results are written as `basis_kwh_reserved`, `stack_ceiling_cents` and `reserved_amount_cents`, and the program pool is then encumbered: if the program's `remaining_budget_cents` is at least the reserved amount — exact equality succeeds — that amount moves out of `remaining_budget_cents` and into `reserved_budget_cents`."

        Design: Corner/validations/export_commitment_flag_rejects_non_export_claim_but_permits_it_when_flag_absent
        """
        project, _, state_id = self._two_pools(api)

        claim = fixtures.reserve_claim(
            api, project, state_id, export_commitment=ExportMode.NON_EXPORT
        )

        assert claim["export_commitment"] == ExportMode.NON_EXPORT
        assert_quantity(claim, "basis_kwh_reserved", 27.0)
        assert_cents(claim, "stack_ceiling_cents", 1600000)
        assert_cents(claim, "reserved_amount_cents", 352500)
        state = fixtures.read_program(api, state_id)
        assert_program_ledger(state, remaining=4647500, reserved=352500, paid=0)
