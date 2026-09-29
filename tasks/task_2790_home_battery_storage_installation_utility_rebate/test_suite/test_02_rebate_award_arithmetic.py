"""
The rebate award: two variants, one rounding step, and an exact-fit budget.

The award recipe runs twice over a claim's life from the same six steps, and the money
is integer cents throughout. These tests pin the reserved-versus-final divergence, the
single rounding step that separates 55328 cents from 55329, and the inclusive fiscal
comparison at the exact remaining balance.
"""

from test_helpers import (
    ClaimStatus,
    ExportMode,
    ModelCode,
    TestType,
    assert_cents,
    assert_program_ledger,
    assert_quantity,
    factories,
    fixtures,
    validate_success,
)

COMMISSIONING_INSTANT = fixtures.COMMISSIONING_INSTANT


class TestReservedVersusFinalAward:
    """A verified capacity below the nameplate re-prices the claim downward."""

    def _under_delivering_project(self, api):
        """An installed bank whose capacity test delivered 24.30 of a possible 27.00 kWh."""
        return fixtures.tests_recorded_project(
            api, result_overrides={TestType.CAPACITY_DISCHARGE: {"delivered_kwh": 24.3}}
        )

    def test_reservation_prices_the_award_from_the_design_nameplate(self, api):
        """At reservation the basis is the bank's design energy, not any measured figure.

        Two PWX_A units give a design 27.0 kWh: 20 kWh in the first tier at 20000 cents
        and 7 kWh in the second at 10000 cents is 470000 cents unrounded, and the limited-
        export multiplier of 9000 basis points brings it to exactly 423000 cents.

        PRD 3.7: "At reservation the basis is the bank's design `usable_kwh`."
        PRD 3.7: "At reservation the results are written as `basis_kwh_reserved`, `stack_ceiling_cents` and `reserved_amount_cents`, and the program pool is then encumbered: if the program's `remaining_budget_cents` is at least the reserved amount — exact equality succeeds — that amount moves out of `remaining_budget_cents` and into `reserved_budget_cents`."

        Design: Difficulty/dual_variant_calc/rebate_award_reserved_vs_final_after_verified_capacity_shortfall
        """
        project = self._under_delivering_project(api)
        program_id = fixtures.create_state_program(api, project)

        claim = fixtures.reserve_claim(api, project, program_id)

        assert_quantity(claim, "basis_kwh_reserved", 27.0)
        assert_cents(claim, "reserved_amount_cents", 423000)
        assert claim["status"] == ClaimStatus.RESERVED
        assert claim.get("basis_kwh_final") is None
        assert claim.get("final_amount_cents") is None
        program = fixtures.read_program(api, program_id)
        assert_program_ledger(program, remaining=4577000, reserved=423000, paid=0)

    def test_commissioning_reprices_the_same_claim_from_the_verified_capacity(self, api):
        """Commissioning bills the smaller of nameplate and measured capacity.

        The capacity discharge test delivered 24.30 kWh, so the final basis is 24.30 and the
        award becomes 443000 cents unrounded, or 398700 after the limited-export multiplier.
        The 24300-cent difference is handed back to the pool rather than kept, and the claim
        itself stays in the reserved state — only its money fields moved.

        PRD 3.7: "At commissioning the basis is the smaller of the bank's design `usable_kwh` and its measured `verified_capacity_kwh`."
        PRD 3.6: "The third hop is caused by the second hop lowering each claim's effective hold. For every claim the second hop touched, the difference between its `reserved_amount_cents` and its new `final_amount_cents` is computed, that difference is subtracted from its program's `reserved_budget_cents` and added back to that program's `remaining_budget_cents`."

        Design: Difficulty/dual_variant_calc/rebate_award_reserved_vs_final_after_verified_capacity_shortfall
        """
        project = self._under_delivering_project(api)
        program_id = fixtures.create_state_program(api, project)
        claim = fixtures.reserve_claim(api, project, program_id)

        fixtures.advance_clock(api, project, COMMISSIONING_INSTANT)
        validate_success(
            api.commission(project.battery_system_id, headers=project.installer_headers)
        )

        system = fixtures.read_system(api, project)
        assert_quantity(system, "verified_capacity_kwh", 24.30)
        repriced = fixtures.read_claim(api, project, claim["id"])
        assert_quantity(repriced, "basis_kwh_reserved", 27.0)
        assert_cents(repriced, "reserved_amount_cents", 423000)
        assert_quantity(repriced, "basis_kwh_final", 24.30)
        assert_cents(repriced, "final_amount_cents", 398700)
        assert repriced["status"] == ClaimStatus.RESERVED
        program = fixtures.read_program(api, program_id)
        assert_program_ledger(program, remaining=4601300, reserved=398700, paid=0)


class TestAwardRoundsOnce:
    """Tier subtotals stay unrounded; only their multiplied sum is rounded."""

    PROGRAM = dict(
        name="Round-Once Capacity Adder",
        total_budget_cents=5000000,
        tier1_limit_kwh=10.5,
        tier1_rate_cents_per_kwh=3705,
        tier2_rate_cents_per_kwh=1235,
        per_project_cap_cents=1200000,
        stack_priority=1,
        max_stack_pct_of_cost_bp=5000,
        requires_export_commitment=True,
        min_capacity_commitment_kw=5.0,
    )

    def _full_export_project(self, api):
        """A 2-unit PWX_C bank of 23.8 kWh, installed at 24000 dollars with full export."""
        return fixtures.installed_project(
            api,
            approved_export_kw=9.0,
            application_overrides={
                "export_mode": ExportMode.FULL_EXPORT,
                "requested_export_kw": 9.0,
            },
            model_code=ModelCode.PWX_C,
            installed_cost_cents=2400000,
        )

    def _reserve(self, api, project):
        program_id = fixtures.create_state_program(api, project, **self.PROGRAM)
        claim = fixtures.reserve_claim(
            api,
            project,
            program_id,
            capacity_commitment_kw=9.0,
            export_commitment=ExportMode.FULL_EXPORT,
        )
        return program_id, claim

    def test_award_is_rounded_once_after_the_export_multiplier(self, api):
        """Summing the unrounded tiers first yields 55328 cents, not 55329.

        The basis is 23.8 kWh, so the first tier is 10.5 kWh at 3705 cents — 38902.5 cents —
        and the second is 13.3 kWh at 1235 cents — 16425.5 cents. Their sum of 55328.0 is
        exact, and the full-export multiplier of 10000 basis points leaves it unchanged.
        Rounding each tier on its own first would have paid 38903 + 16426 = 55329 cents.

        PRD 3.7: "The raw award is the first-tier energy multiplied by `tier1_rate_cents_per_kwh` plus the second-tier energy multiplied by `tier2_rate_cents_per_kwh`. This subtotal is **not** rounded."
        PRD 3.7: "This is the single rounding step of the whole computation; rounding either tier subtotal on its own, or rounding before applying the multiplier, produces a figure that can differ by a cent and is wrong."

        Design: Difficulty/combinatorial_formula/rebate_rounds_once_after_export_multiplier_not_per_tier
        """
        project = self._full_export_project(api)

        _, claim = self._reserve(api, project)

        assert_quantity(claim, "basis_kwh_reserved", 23.8)
        assert_cents(claim, "reserved_amount_cents", 55328)
        assert claim["reserved_amount_cents"] != 55329, (
            "the tiers were rounded separately before being summed"
        )

    def test_the_round_once_award_encumbers_the_pool_by_the_same_integer(self, api):
        """The ledger moves the same integer the claim recorded, to the cent.

        The stacking ceiling is 5000 basis points of the 2400000-cent installed cost, that is
        1200000 cents, and the 55328-cent award sits comfortably inside it, so exactly 55328
        cents leave the unencumbered balance for the reserved bucket.

        PRD 3.7: "The tightest `max_stack_pct_of_cost_bp` among those programs is taken, multiplied by the bank's `installed_cost_cents`, divided by 10000, and floored to a whole number of cents; that figure is the claim's `stack_ceiling_cents`."
        PRD 2.10: "Ledger transfers between buckets are exact integer moves and involve no rounding at all."

        Design: Difficulty/combinatorial_formula/rebate_rounds_once_after_export_multiplier_not_per_tier
        """
        project = self._full_export_project(api)

        program_id, claim = self._reserve(api, project)

        assert_cents(claim, "stack_ceiling_cents", 1200000)
        program = fixtures.read_program(api, program_id)
        assert_program_ledger(program, remaining=4944672, reserved=55328, paid=0)


class TestExactFitBudget:
    """The fiscal comparison is inclusive, so the last cent of a pool is spendable."""

    PROGRAM = dict(
        name="Exact-Fit Capacity Incentive",
        total_budget_cents=423000,
        tier1_limit_kwh=20,
        tier1_rate_cents_per_kwh=20000,
        tier2_rate_cents_per_kwh=10000,
        per_project_cap_cents=1500000,
        max_stack_pct_of_cost_bp=5000,
        requires_export_commitment=False,
        min_capacity_commitment_kw=5.0,
    )

    def test_an_award_equal_to_the_remaining_balance_is_accepted(self, api):
        """An award of exactly the remaining balance succeeds rather than being refused.

        The program holds 423000 cents and the claim computes an award of exactly 423000
        cents. Because the comparison asks whether the balance is at least the award, the
        reservation is created; a strict comparison would have rejected it.

        PRD 3.7: "if the program's `remaining_budget_cents` is at least the reserved amount — exact equality succeeds — that amount moves out of `remaining_budget_cents` and into `reserved_budget_cents`"

        Design: Difficulty/boundary_precision_check/program_budget_exact_equality_reserves_down_to_zero
        """
        project = fixtures.installed_project(api)
        program_id = fixtures.create_state_program(api, project, **self.PROGRAM)

        claim = validate_success(
            api.create_claim(
                factories.claim_payload(
                    project.battery_system_id,
                    program_id,
                    fixtures.system_version(api, project),
                ),
                headers=project.installer_headers,
            ),
            expected_status=201,
        )

        assert claim["status"] == ClaimStatus.RESERVED
        assert_cents(claim, "reserved_amount_cents", 423000)

    def test_the_exact_fit_reservation_drives_the_pool_to_zero_without_drift(self, api):
        """The pool lands on exactly zero unencumbered cents and still balances.

        Every cent of the 423000-cent pool is now held for this one claim, so the
        unencumbered bucket is zero, the reserved bucket carries the whole budget, and
        nothing has been disbursed.

        PRD 2.10: "After every single claim transition the following must hold exactly: `total_budget_cents` equals `remaining_budget_cents` plus `reserved_budget_cents` plus `paid_budget_cents`."

        Design: Difficulty/boundary_precision_check/program_budget_exact_equality_reserves_down_to_zero
        """
        project = fixtures.installed_project(api)
        program_id = fixtures.create_state_program(api, project, **self.PROGRAM)

        fixtures.reserve_claim(api, project, program_id)

        program = fixtures.read_program(api, program_id)
        assert_program_ledger(program, remaining=0, reserved=423000, paid=0)
