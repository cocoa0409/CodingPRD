"""The two labor-cost variants, the calendar gate and the fiscal ceiling."""
from test_helpers import (
    ApiErrorId,
    assert_money,
    assert_plan_ledger,
    assert_work_order,
    validate_error,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

YOUNG_PLAN_BUDGETS = {
    "pruning_budget_per_acre": 100.00,
    "canopy_budget_per_acre": 60.00,
    "irrigation_budget_per_acre": 37.00,
    "pest_budget_per_acre": 60.00,
}


class TestHourlyOvertime:
    """PRD §3.4 — hours are split at the eight-hour standard shift."""

    def test_hourly_crew_pays_overtime_beyond_the_standard_shift(self, api):
        """For an `HOURLY` crew, hours are split at the eight-hour standard shift — regular hours are the lesser of the reported hours and eight, and overtime hours are the excess above eight, or zero when there is no excess — and the structural gross is the crew's `crew_size` multiplied by its `base_hourly_rate` multiplied by the sum of the regular hours plus one and a half times the overtime hours.

        Design: Corner/calculations/hourly_labor_cost_applies_overtime_multiplier_beyond_std_shift
        """
        s = fx.setup_operational_block(api, hourly_crew=True)

        straight = fx.create_work_order(
            api, s.block["id"], s.plan["id"], s.crew["id"], task_type="SUCKERING",
            scheduled_start="2026-08-10T14:00:00Z",
            scheduled_end="2026-08-10T22:00:00Z",
            planned_vines=3000, planned_hours=8.0,
        )
        overtime = fx.create_work_order(
            api, s.block["id"], s.plan["id"], s.crew["id"], task_type="LEAFING",
            scheduled_start="2026-08-11T14:00:00Z",
            scheduled_end="2026-08-12T00:00:00Z",
            planned_vines=3000, planned_hours=10.0,
        )

        assert_work_order(straight)
        assert_money(straight["estimated_labor_cost"], 1809.28,
                     "estimated_labor_cost")
        assert_money(overtime["estimated_labor_cost"], 2487.76,
                     "estimated_labor_cost")

        plan = fx.read_plan(api, s.plan["id"])
        assert_plan_ledger(plan, 4297.04, 10390.46, "WITHIN_BUDGET")

    def test_the_make_whole_floor_beats_a_thin_piece_rate_but_not_overtime(self, api):
        """Two worked cases show why the floor matters: a twelve-worker `PIECE_RATE` crew at 0.65 dollars per vine reporting 13,000 vines over 10.0 hours has a structural gross of 8,450.00 against a floor of 1,980.00, so gross pay is 8,450.00, burden 2,408.25 and labor cost 10,858.25 — but the same crew reporting only 1,000 vines over the same 10.0 hours has a structural gross of just 650.00, the 1,980.00 floor wins, and the labor cost is 2,544.30.

        Design: Difficulty/combinatorial_formula/labor_cost_floor_dominates_over_piece_rate_and_overtime
        """
        s = fx.setup_operational_block(api)
        hourly_crew = fx.create_hourly_crew(api)

        piece_order = fx.create_work_order(
            api, s.block["id"], s.plan["id"], s.crew["id"], task_type="SUCKERING",
            scheduled_start="2026-08-06T14:00:00Z",
            scheduled_end="2026-08-07T00:00:00Z",
            planned_vines=1000, planned_hours=10.0,
        )
        hourly_order = fx.create_work_order(
            api, s.block["id"], s.plan["id"], hourly_crew["id"], task_type="LEAFING",
            scheduled_start="2026-08-06T14:00:00Z",
            scheduled_end="2026-08-07T00:00:00Z",
            planned_vines=900, planned_hours=10.0,
        )

        assert_money(piece_order["estimated_labor_cost"], 2544.30,
                     "estimated_labor_cost")
        assert_money(hourly_order["estimated_labor_cost"], 2487.76,
                     "estimated_labor_cost")
        assert piece_order["execution_status"] == "SCHEDULED"
        assert hourly_order["execution_status"] == "SCHEDULED"

    def test_the_two_pay_structures_diverge_on_the_same_reported_hours(self, api):
        """An eight-worker `HOURLY` crew at 22.00 dollars per hour working 10.0 hours earns eight regular and two overtime hours for a gross of 1,936.00 and a labor cost of 2,487.76; the same crew working exactly 8.0 hours costs 1,809.28.

        Design: Difficulty/combinatorial_formula/labor_cost_floor_dominates_over_piece_rate_and_overtime
        """
        s = fx.setup_operational_block(api)
        hourly_crew = fx.create_hourly_crew(api)

        fx.create_work_order(
            api, s.block["id"], s.plan["id"], s.crew["id"], task_type="SUCKERING",
            scheduled_start="2026-08-06T14:00:00Z",
            scheduled_end="2026-08-07T00:00:00Z",
            planned_vines=1000, planned_hours=10.0,
        )
        fx.create_work_order(
            api, s.block["id"], s.plan["id"], hourly_crew["id"], task_type="LEAFING",
            scheduled_start="2026-08-06T14:00:00Z",
            scheduled_end="2026-08-07T00:00:00Z",
            planned_vines=900, planned_hours=10.0,
        )

        plan = fx.read_plan(api, s.plan["id"])
        assert_plan_ledger(plan, 5032.06, 9655.44, "WITHIN_BUDGET")


class TestEstimatedVersusActualLabor:
    """PRD §3.4 — the formula runs in two variants over identical arithmetic."""

    def test_completion_writes_an_actual_cost_that_diverges_from_the_estimate(self, api):
        """The variant used at scheduling time consumes `planned_vines` and `planned_hours` and writes `estimated_labor_cost`, which is frozen on the row and never recomputed for the life of the order. The variant used when the work is reported consumes `actual_vines` and `actual_hours` and writes `actual_labor_cost`.

        Design: Difficulty/dual_variant_calc/work_order_labor_cost_estimated_vs_actual_divergence
        """
        s = fx.setup_operational_block(api)
        order = fx.create_work_order(
            api, s.block["id"], s.plan["id"], s.crew["id"], task_type="PRUNING",
            scheduled_start="2026-08-03T14:00:00Z",
            scheduled_end="2026-08-04T00:00:00Z",
            planned_vines=13000, planned_hours=10.0,
        )
        assert_money(order["estimated_labor_cost"], 10858.25, "estimated_labor_cost")

        fx.start_work_order(api, order["id"], s.crew["id"])
        completed = fx.complete_work_order(api, order["id"], s.crew["id"], 5200, 12.0)

        assert_money(completed["actual_labor_cost"], 4343.30, "actual_labor_cost")
        assert_money(completed["estimated_labor_cost"], 10858.25,
                     "estimated_labor_cost")
        assert completed["actual_labor_cost"] != completed["estimated_labor_cost"]
        assert_money(
            completed["estimated_labor_cost"] - completed["actual_labor_cost"],
            6514.95, "estimate less actual",
        )
        assert completed["execution_status"] == "COMPLETED"
        assert completed["payroll_status"] == "PENDING"

    def test_the_plan_ledger_swaps_the_estimate_out_for_the_actual(self, api):
        """Completion moves execution `IN_PROGRESS → COMPLETED`, stamps `completed_at`, writes `actual_labor_cost` from the reported-work variant of the labor formula, advances payroll `NOT_PAYABLE → PENDING`, and recomputes the plan's `committed_cost`, `remaining_budget` and `budget_posture` — where the frozen estimate is now displaced by the actual — along with the crew's `scheduled_work_order_count`.

        Design: Difficulty/dual_variant_calc/work_order_labor_cost_estimated_vs_actual_divergence
        """
        s = fx.setup_operational_block(api)
        order = fx.create_work_order(
            api, s.block["id"], s.plan["id"], s.crew["id"], task_type="PRUNING",
            scheduled_start="2026-08-03T14:00:00Z",
            scheduled_end="2026-08-04T00:00:00Z",
            planned_vines=13000, planned_hours=10.0,
        )
        assert_plan_ledger(fx.read_plan(api, s.plan["id"]), 10858.25, 3829.25,
                           "WITHIN_BUDGET")

        fx.start_work_order(api, order["id"], s.crew["id"])
        fx.complete_work_order(api, order["id"], s.crew["id"], 5200, 12.0)

        plan = fx.read_plan(api, s.plan["id"])
        assert_money(plan["total_budget"], 14687.50, "total_budget")
        assert_plan_ledger(plan, 4343.30, 10344.20, "WITHIN_BUDGET")
        assert fx.read_crew(api, s.crew["id"])["scheduled_work_order_count"] == 0


class TestBudgetPostureAndCeiling:
    """PRD §3.3 and §3.4 — the posture bands and the inclusive fiscal ceiling."""

    def _young_block_with_plan(self, api):
        ranch = fx.create_vineyard(api)
        block = fx.create_block(
            api, ranch["id"], block_code="B-30", vine_spacing_ft=6.0,
            row_spacing_ft=10.0, acres=4.0, planting_year=2019,
        )
        plan = fx.create_farming_plan(api, block["id"], **YOUNG_PLAN_BUDGETS)
        fx.submit_farming_plan(api, plan["id"])
        plan = fx.approve_farming_plan(api, plan["id"])
        return block, plan

    def test_posture_crosses_into_at_risk_just_above_eighty_percent(self, api):
        """When the ratio is at most 0.80 the posture is `WITHIN_BUDGET`; when it is greater than 0.80 but at most 1.00 the posture is `AT_RISK`; when it is greater than 1.00 the posture is `EXHAUSTED`.

        Design: Corner/complexity layers/plan_budget_posture_crosses_into_at_risk_above_eighty_percent
        """
        block, plan = self._young_block_with_plan(api)
        crew = fx.create_hourly_crew(
            api, crew_size=1, base_hourly_rate=100.00,
            task_capabilities=["LEAFING", "SUCKERING"],
        )
        assert_money(plan["total_budget"], 1028.00, "total_budget")

        first = fx.create_work_order(
            api, block["id"], plan["id"], crew["id"], task_type="LEAFING",
            scheduled_start="2026-08-03T06:00:00Z",
            scheduled_end="2026-08-03T12:24:00Z",
            planned_vines=200, planned_hours=6.4,
        )
        assert_money(first["estimated_labor_cost"], 822.40, "estimated_labor_cost")
        assert_plan_ledger(fx.read_plan(api, plan["id"]), 822.40, 205.60,
                           "WITHIN_BUDGET")

        second = fx.create_work_order(
            api, block["id"], plan["id"], crew["id"], task_type="SUCKERING",
            scheduled_start="2026-08-03T14:00:00Z",
            scheduled_end="2026-08-03T14:30:00Z",
            planned_vines=20, planned_hours=0.5,
        )
        assert_money(second["estimated_labor_cost"], 64.25, "estimated_labor_cost")
        assert_plan_ledger(fx.read_plan(api, plan["id"]), 886.65, 141.35, "AT_RISK")

    def test_an_order_landing_exactly_on_the_budget_is_accepted(self, api):
        """Only after the calendar is clear does the budget gate run: the plan's current `committed_cost` plus this order's freshly computed `estimated_labor_cost`, rounded to two decimal places, must not exceed the plan's `total_budget`. Equality is permitted; anything above is refused with `ERR_PLAN_BUDGET_EXCEEDED`.

        Design: Difficulty/boundary_precision_check/work_order_at_exact_plan_budget_equality_is_accepted
        """
        ranch = fx.create_vineyard(api)
        block = fx.create_block_b14(api, ranch["id"])
        plan = fx.create_farming_plan(api, block["id"], **YOUNG_PLAN_BUDGETS)
        fx.submit_farming_plan(api, plan["id"])
        plan = fx.approve_farming_plan(api, plan["id"])
        crew = fx.create_hourly_crew(
            api, crew_size=1, base_hourly_rate=100.00,
            task_capabilities=["PRUNING", "SUCKERING"],
        )

        exact = fx.create_work_order(
            api, block["id"], plan["id"], crew["id"], task_type="PRUNING",
            scheduled_start="2026-08-06T06:00:00Z",
            scheduled_end="2026-08-06T14:00:00Z",
            planned_vines=2000, planned_hours=8.0,
        )

        assert_money(exact["estimated_labor_cost"], 1028.00, "estimated_labor_cost")
        assert exact["execution_status"] == "SCHEDULED"
        plan = fx.read_plan(api, plan["id"])
        assert_money(plan["total_budget"], 1028.00, "total_budget")
        assert_plan_ledger(plan, 1028.00, 0.00, "AT_RISK")

    def test_the_next_order_past_the_budget_is_refused(self, api):
        """This gate is the reason a plan cannot be pushed past its budget by labor alone.

        Design: Difficulty/boundary_precision_check/work_order_at_exact_plan_budget_equality_is_accepted
        """
        ranch = fx.create_vineyard(api)
        block = fx.create_block_b14(api, ranch["id"])
        plan = fx.create_farming_plan(api, block["id"], **YOUNG_PLAN_BUDGETS)
        fx.submit_farming_plan(api, plan["id"])
        plan = fx.approve_farming_plan(api, plan["id"])
        crew = fx.create_hourly_crew(
            api, crew_size=1, base_hourly_rate=100.00,
            task_capabilities=["PRUNING", "SUCKERING"],
        )
        fx.create_work_order(
            api, block["id"], plan["id"], crew["id"], task_type="PRUNING",
            scheduled_start="2026-08-06T06:00:00Z",
            scheduled_end="2026-08-06T14:00:00Z",
            planned_vines=2000, planned_hours=8.0,
        )

        validate_error(
            api.create_work_order(
                f.work_order_payload(
                    block["id"], plan["id"], crew["id"], task_type="SUCKERING",
                    scheduled_start="2026-08-07T06:00:00Z",
                    scheduled_end="2026-08-07T06:30:00Z",
                    planned_vines=100, planned_hours=0.5,
                ),
                fx.VM,
            ),
            ApiErrorId.ERR_PLAN_BUDGET_EXCEEDED,
        )

        assert_plan_ledger(fx.read_plan(api, plan["id"]), 1028.00, 0.00, "AT_RISK")
        assert fx.read_crew(api, crew["id"])["scheduled_work_order_count"] == 1


class TestCrewCalendarGeometry:
    """PRD §3.4 — the half-open interval and the travel buffer are separate rules."""

    def _two_blocks_two_plans_one_crew(self, api):
        ranch = fx.create_vineyard(api)
        block_a = fx.create_block(api, ranch["id"])
        block_b = fx.create_block_b14(api, ranch["id"])
        plan_a = fx.create_farming_plan(api, block_a["id"])
        fx.submit_farming_plan(api, plan_a["id"])
        plan_a = fx.approve_farming_plan(api, plan_a["id"])
        plan_b = fx.create_farming_plan(api, block_b["id"], **YOUNG_PLAN_BUDGETS)
        fx.submit_farming_plan(api, plan_b["id"])
        plan_b = fx.approve_farming_plan(api, plan_b["id"])
        crew = fx.create_hourly_crew(api, crew_size=1, base_hourly_rate=20.00)
        return block_a, block_b, plan_a, plan_b, crew

    def test_back_to_back_orders_on_the_same_block_need_no_separation(self, api):
        """Two orders on the same block need no separation at all, so back-to-back work where one interval ends exactly when the next begins is permitted.

        Design: Difficulty/resource_temporal_overlap/crew_schedule_travel_buffer_differs_by_block
        """
        block_a, _, plan_a, _, crew = self._two_blocks_two_plans_one_crew(api)

        first = fx.create_work_order(
            api, block_a["id"], plan_a["id"], crew["id"], task_type="PRUNING",
            scheduled_start="2026-08-03T14:00:00Z",
            scheduled_end="2026-08-03T22:00:00Z",
            planned_vines=280, planned_hours=8.0,
        )
        second = fx.create_work_order(
            api, block_a["id"], plan_a["id"], crew["id"], task_type="SUCKERING",
            scheduled_start="2026-08-03T22:00:00Z",
            scheduled_end="2026-08-04T06:00:00Z",
            planned_vines=280, planned_hours=8.0,
        )

        assert_money(first["estimated_labor_cost"], 205.60, "estimated_labor_cost")
        assert_money(second["estimated_labor_cost"], 205.60, "estimated_labor_cost")
        assert second["execution_status"] == "SCHEDULED"
        assert_plan_ledger(fx.read_plan(api, plan_a["id"]), 411.20, 14276.30,
                           "WITHIN_BUDGET")
        assert fx.read_crew(api, crew["id"])["scheduled_work_order_count"] == 2

    def test_the_same_adjacency_across_blocks_needs_sixty_minutes_of_travel(self, api):
        """Two orders on different blocks require one hour of travel separation, and the pair conflicts until a full 60 minutes lies between them.

        Design: Difficulty/resource_temporal_overlap/crew_schedule_travel_buffer_differs_by_block
        """
        block_a, block_b, plan_a, plan_b, crew = self._two_blocks_two_plans_one_crew(api)
        fx.create_work_order(
            api, block_a["id"], plan_a["id"], crew["id"], task_type="PRUNING",
            scheduled_start="2026-08-03T14:00:00Z",
            scheduled_end="2026-08-03T22:00:00Z",
            planned_vines=280, planned_hours=8.0,
        )
        fx.create_work_order(
            api, block_a["id"], plan_a["id"], crew["id"], task_type="SUCKERING",
            scheduled_start="2026-08-03T22:00:00Z",
            scheduled_end="2026-08-04T06:00:00Z",
            planned_vines=280, planned_hours=8.0,
        )

        validate_error(
            api.create_work_order(
                f.work_order_payload(
                    block_b["id"], plan_b["id"], crew["id"], task_type="LEAFING",
                    scheduled_start="2026-08-04T06:00:00Z",
                    scheduled_end="2026-08-04T14:00:00Z",
                    planned_vines=280, planned_hours=8.0,
                ),
                fx.VM,
            ),
            ApiErrorId.ERR_CREW_SCHEDULE_CONFLICT,
        )

        after_buffer = fx.create_work_order(
            api, block_b["id"], plan_b["id"], crew["id"], task_type="LEAFING",
            scheduled_start="2026-08-04T07:00:00Z",
            scheduled_end="2026-08-04T15:00:00Z",
            planned_vines=280, planned_hours=8.0,
        )
        assert_money(after_buffer["estimated_labor_cost"], 205.60,
                     "estimated_labor_cost")

        assert fx.read_crew(api, crew["id"])["scheduled_work_order_count"] == 3
        assert_plan_ledger(fx.read_plan(api, plan_a["id"]), 411.20, 14276.30,
                           "WITHIN_BUDGET")
        assert_plan_ledger(fx.read_plan(api, plan_b["id"]), 205.60, 822.40,
                           "WITHIN_BUDGET")


class TestCancellationCompensation:
    """PRD §3.4 — cancelling from `SCHEDULED` reverses the commitment outright."""

    def test_create_then_cancel_restores_the_plan_ledger_baseline(self, api):
        """Cancelling from `SCHEDULED` reverses the commitment outright: `actual_labor_cost` stays null and `payroll_status` stays `NOT_PAYABLE`, because no pay is owed for work never started; the plan's ledger releases the estimate; the crew's `scheduled_work_order_count` is recomputed; and the crew's half-open interval is freed for re-booking.

        Design: Difficulty/compensating_invariant/plan_committed_cost_returns_to_baseline_after_create_then_cancel
        """
        s = fx.setup_operational_block(api)
        assert_plan_ledger(s.plan, 0.00, 14687.50, "WITHIN_BUDGET")

        order = fx.create_work_order(
            api, s.block["id"], s.plan["id"], s.crew["id"], task_type="LEAFING",
            scheduled_start="2026-08-06T06:00:00Z",
            scheduled_end="2026-08-06T16:00:00Z",
            planned_vines=6000, planned_hours=10.0,
        )
        assert_money(order["estimated_labor_cost"], 5011.50, "estimated_labor_cost")
        assert_plan_ledger(fx.read_plan(api, s.plan["id"]), 5011.50, 9676.00,
                           "WITHIN_BUDGET")

        cancelled = fx.cancel_work_order(api, order["id"], "WEATHER")
        assert cancelled["execution_status"] == "CANCELLED"
        assert cancelled["cancel_reason"] == "WEATHER"
        assert cancelled["actual_labor_cost"] is None
        assert cancelled["payroll_status"] == "NOT_PAYABLE"

        assert_plan_ledger(fx.read_plan(api, s.plan["id"]), 0.00, 14687.50,
                           "WITHIN_BUDGET")
        assert fx.read_crew(api, s.crew["id"])["scheduled_work_order_count"] == 0

    def test_cancelling_after_a_start_substitutes_reporting_time_pay(self, api):
        """That guarantee is the crew's `crew_size` multiplied by the same 16.50 dollars per worker-hour multiplied by a four-hour call-in minimum, rounded to two decimal places, plus the same 28.50 percent burden on that rounded gross, itself rounded, with the two added and rounded again — a twelve-worker crew therefore yields a gross of 792.00, a burden of 225.72 and an `actual_labor_cost` of 1,017.72.

        Design: Difficulty/compensating_invariant/plan_committed_cost_returns_to_baseline_after_create_then_cancel
        """
        s = fx.setup_operational_block(api)
        order = fx.create_work_order(
            api, s.block["id"], s.plan["id"], s.crew["id"], task_type="PRUNING",
            scheduled_start="2026-08-08T06:00:00Z",
            scheduled_end="2026-08-08T16:00:00Z",
            planned_vines=6000, planned_hours=10.0,
        )
        fx.start_work_order(api, order["id"], s.crew["id"])

        cancelled = fx.cancel_work_order(api, order["id"], "CREW_UNAVAILABLE")
        assert cancelled["execution_status"] == "CANCELLED"
        assert_money(cancelled["actual_labor_cost"], 1017.72, "actual_labor_cost")
        assert cancelled["payroll_status"] == "PENDING"

        assert_plan_ledger(fx.read_plan(api, s.plan["id"]), 1017.72, 13669.78,
                           "WITHIN_BUDGET")
