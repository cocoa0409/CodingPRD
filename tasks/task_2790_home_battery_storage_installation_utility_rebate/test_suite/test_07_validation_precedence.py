"""
Which objection wins when a request breaks more than one rule.

Every one of these requests is wrong in two independent ways at once, and the
specification fixes exactly which complaint the caller hears. Each pair sits at a
different place in the precedence order: state against fiscal, safety against temporal,
and constraint against fiscal.
"""

from test_helpers import (
    ApiErrorId,
    BuildStatus,
    ProgramType,
    TestResult,
    TestType,
    assert_cents,
    assert_program_ledger,
    assert_unset,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
)

DEPLETED_PROGRAM = dict(name="Depleted Capacity Program", total_budget_cents=1000)

TIGHT_STACK_PROGRAM = dict(
    name="Tight-Stack Municipal Adder",
    program_type=ProgramType.FEDERAL_ADDER,
    total_budget_cents=5000000,
    tier1_limit_kwh=20,
    tier1_rate_cents_per_kwh=10000,
    tier2_rate_cents_per_kwh=5000,
    per_project_cap_cents=500000,
    stack_priority=3,
    max_stack_pct_of_cost_bp=1500,
    requires_export_commitment=False,
    min_capacity_commitment_kw=3.0,
)

LATE_PROGRAM = dict(
    name="Late Federal Adder",
    program_type=ProgramType.FEDERAL_ADDER,
    total_budget_cents=10000,
    tier1_limit_kwh=20,
    tier1_rate_cents_per_kwh=20000,
    tier2_rate_cents_per_kwh=10000,
    per_project_cap_cents=1500000,
    stack_priority=4,
    max_stack_pct_of_cost_bp=5000,
    requires_export_commitment=False,
    min_capacity_commitment_kw=5.0,
)


class TestStateBeatsBudget:
    """A bank that never applied for interconnection is refused on state, not money."""

    def _unapplied_bank_and_empty_pool(self, api):
        project = fixtures.design_locked_project(api)
        program_id = fixtures.create_state_program(api, project, **DEPLETED_PROGRAM)
        return project, program_id

    def _attempt(self, api, project, program_id):
        return api.create_claim(
            factories.claim_payload(
                project.battery_system_id,
                program_id,
                fixtures.system_version(api, project),
            ),
            headers=project.installer_headers,
        )

    def test_the_grid_state_objection_is_reported_before_the_budget_objection(self, api):
        """Both rules are broken; only the state complaint is returned.

        The bank has never filed an interconnection application, so its grid dimension has
        not reached the approval this reservation requires, and the pool holds 1000 cents
        against an award that would come to 423000. The state objection is the one reported.

        PRD 3.7: "Reservation is only meaningful in a specific window of the bank's life: the bank's `build_status` must be `DESIGN_LOCKED` or `INSTALLED` and its `grid_status` must be `APPROVED_TO_INSTALL` or `PTO_GRANTED`, else `ERR_SYSTEM_GRID_STATE_INVALID`."
        PRD 2.12: "Evaluated last, so that every state, referential, temporal and constraint objection is reported in preference to a budget objection: the program's `remaining_budget_cents` must cover the reservation, else `ERR_PROGRAM_BUDGET_EXHAUSTED`."

        Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_budget_on_rebate_reservation
        """
        project, program_id = self._unapplied_bank_and_empty_pool(api)

        error = validate_error(
            self._attempt(api, project, program_id),
            ApiErrorId.ERR_SYSTEM_GRID_STATE_INVALID,
            expected_status=409,
        )

        assert error["error_id"] != ApiErrorId.ERR_PROGRAM_BUDGET_EXHAUSTED

    def test_the_refused_reservation_leaves_the_pool_and_the_claim_set_untouched(self, api):
        """No bucket moves and no claim row is written when the state gate refuses.

        The rejection happens before the pool is consulted at all, so the program still holds
        its whole 1000 cents unencumbered and the bank carries no claim of any status.

        PRD 3.7: "If it is strictly less, the whole reservation is rejected with `ERR_PROGRAM_BUDGET_EXHAUSTED`, and no bucket moves."
        PRD 2.10: "At program creation `remaining_budget_cents` equals `total_budget_cents` and the other two buckets are zero."

        Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_budget_on_rebate_reservation
        """
        project, program_id = self._unapplied_bank_and_empty_pool(api)

        validate_error(
            self._attempt(api, project, program_id),
            ApiErrorId.ERR_SYSTEM_GRID_STATE_INVALID,
        )

        program = fixtures.read_program(api, program_id)
        assert_program_ledger(program, remaining=1000, reserved=0, paid=0)
        claims, _ = validate_paginated(
            api.list_claims(
                {"battery_system_id": project.battery_system_id},
                headers=project.installer_headers,
            )
        )
        assert claims == [], "a claim row was written for a refused reservation"


class TestSafetyBeatsPermitExpiry:
    """A failed transition test is named before the permit's lapsed validity window."""

    def _failed_transition_and_lapsed_permit(self, api):
        project = fixtures.tests_recorded_project(
            api,
            result_overrides={TestType.BACKUP_TRANSITION: {"transition_ms": 250}},
            expires_on="2026-08-09T00:00:00.000Z",
        )
        return fixtures.advance_clock(api, project, "2026-08-10T17:00:00Z")

    def test_the_safety_objection_is_reported_before_the_lapsed_permit(self, api):
        """The transition failure is named specifically, ahead of the expiry complaint.

        The transition test measured 250 milliseconds against a 200 millisecond ceiling, and
        the permit's validity window closed the day before the clock now reads. The safety
        gate runs first, and within it the transition failure has its own named objection.

        PRD 3.6: "If all four have been recorded but the `BACKUP_TRANSITION` one failed, the rejection is the specific `ERR_BACKUP_TRANSITION_NOT_VERIFIED` — the backup transition is the safety-critical verification and is named in preference to the generic objection."
        PRD 3.6: "Only after the test gate is satisfied does the permit gate apply: the bank's permit must not have reached its `expires_on`, else `ERR_PERMIT_EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/commissioning_safety_beats_permit_expiry_temporal_check
        """
        project = self._failed_transition_and_lapsed_permit(api)

        error = validate_error(
            api.commission(project.battery_system_id, headers=project.installer_headers),
            ApiErrorId.ERR_BACKUP_TRANSITION_NOT_VERIFIED,
            expected_status=422,
        )

        assert error["error_id"] != ApiErrorId.ERR_PERMIT_EXPIRED

    def test_the_refused_commissioning_leaves_the_bank_installed_and_unverified(self, api):
        """Nothing of the commissioning cascade fires when the safety gate refuses.

        The transition test's verdict is a failure, the bank is still merely installed, and
        neither the commissioning instant nor the measured capacity has been written.

        PRD 3.6: "A `BACKUP_TRANSITION` test passes when its `transition_ms` is at most 200 milliseconds and fails otherwise."
        PRD 3.6: "The first hop sets `build_status` to `COMMISSIONED`, stamps `commissioned_at` from the logical clock, derives `warranty_deadline_at` as `commissioned_at` plus 30 days, copies the `delivered_kwh` of the recorded `CAPACITY_DISCHARGE` test into the bank's `verified_capacity_kwh`, and increments the accountable installer's `commissioned_system_count` by one."

        Design: Difficulty/priority_pair_validation_conflict/commissioning_safety_beats_permit_expiry_temporal_check
        """
        project = self._failed_transition_and_lapsed_permit(api)

        validate_error(
            api.commission(project.battery_system_id, headers=project.installer_headers),
            ApiErrorId.ERR_BACKUP_TRANSITION_NOT_VERIFIED,
        )

        transition_test = fixtures.get_success_data(
            api.get_commissioning_test(
                project.test_ids[TestType.BACKUP_TRANSITION],
                headers=project.installer_headers,
            )
        )
        assert transition_test["result"] == TestResult.FAIL
        system = fixtures.read_system(api, project)
        assert system["build_status"] == BuildStatus.INSTALLED
        assert_unset(system, "commissioned_at", "verified_capacity_kwh")


class TestStackingBeatsBudget:
    """Exhausted stacking headroom is reported before an exhausted pool."""

    def _headroom_fully_consumed(self, api):
        """Two live reservations whose holds add up to exactly the tightest ceiling."""
        project = fixtures.installed_project(api)
        state_id = fixtures.create_state_program(api, project)
        tight_id = fixtures.create_federal_program(api, project, **TIGHT_STACK_PROGRAM)
        late_id = fixtures.create_federal_program(api, project, **LATE_PROGRAM)

        fixtures.reserve_claim(api, project, state_id)
        truncated = fixtures.reserve_claim(
            api, project, tight_id, capacity_commitment_kw=5.0
        )
        return project, late_id, truncated

    def test_the_stacking_objection_is_reported_before_the_budget_objection(self, api):
        """Zero headroom is reported even though the target pool is also too small.

        The tightest ceiling among the involved programs is 1500 basis points of the
        3200000-cent installed cost, that is 480000 cents, and the two live sibling holds of
        423000 and 57000 consume it exactly. Headroom of exactly zero is the stacking
        objection, and the target program's 10000-cent pool is never even consulted.

        PRD 3.7: "Headroom is the ceiling less that committed sum, floored at zero. Headroom of exactly zero is the `ERR_STACK_CAP_EXCEEDED` case."
        PRD 2.12: "In this internal order: export commitment (`ERR_EXPORT_COMMITMENT_REQUIRED`), then capacity commitment bounds (`ERR_CAPACITY_COMMITMENT_INVALID`), then stacking headroom (`ERR_STACK_CAP_EXCEEDED`)"

        Design: Difficulty/priority_pair_validation_conflict/stacking_constraint_beats_budget_on_third_program_claim
        """
        project, late_id, _ = self._headroom_fully_consumed(api)

        error = validate_error(
            api.create_claim(
                factories.claim_payload(
                    project.battery_system_id,
                    late_id,
                    fixtures.system_version(api, project),
                ),
                headers=project.installer_headers,
            ),
            ApiErrorId.ERR_STACK_CAP_EXCEEDED,
            expected_status=422,
        )

        assert error["error_id"] != ApiErrorId.ERR_PROGRAM_BUDGET_EXHAUSTED
        late_program = fixtures.read_program(api, late_id)
        assert_program_ledger(late_program, remaining=10000, reserved=0, paid=0)

    def test_the_sibling_claim_was_truncated_to_the_headroom_that_remained(self, api):
        """The waterfall truncation is what left exactly zero headroom behind.

        The municipal claim's own schedule would have paid 211500 cents, but the tightest
        ceiling of 480000 less the state program's 423000-cent hold left only 57000 cents of
        headroom, so the reservation was reduced to that figure rather than refused.

        PRD 3.7: "Finally the award is reduced to the headroom if the headroom is smaller. This waterfall truncation is not an error — a program late in the priority order simply receives less than its own schedule would have paid."

        Design: Difficulty/priority_pair_validation_conflict/stacking_constraint_beats_budget_on_third_program_claim
        """
        _, _, truncated = self._headroom_fully_consumed(api)

        assert_cents(truncated, "reserved_amount_cents", 57000)
        assert_cents(truncated, "stack_ceiling_cents", 480000)
