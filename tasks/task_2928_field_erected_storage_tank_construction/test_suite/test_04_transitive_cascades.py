"""Single triggers whose effects reach three, four and five entities deep.

An examination rejection walks report to seam to tank posture to plan to
withdrawal to source ledger; a holiday test walks coating to posture to phase to
a document package nobody touched; scheduling a re-examination walks seam to
course to phase while leaving the posture alone.
"""

import pytest

from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_plan_costs,
    assert_source_ledger,
    assert_tank_state,
)
from test_helpers.constants import (
    BASE_EXAMINATION_PCT,
    CANCELLATION_PLAN_SUSPENDED,
    COURSE_FITTED,
    COURSE_RT_ACCEPTED,
    COURSE_WELDED,
    DECISION_REJECT,
    DEFECT_SLAG_INCLUSION,
    FULL_EXAMINATION_PCT,
    NDE_REPORTED_ACCEPT,
    NDE_REPORTED_REJECT,
    PACKAGE_RETURNED_FOR_CORRECTION,
    PACKAGE_SUBMITTED,
    PHASE_COATED,
    PHASE_ERECTION_IN_PROGRESS,
    PHASE_HYDROTEST_PASSED,
    PHASE_SHELL_COMPLETE,
    PLAN_APPROVED,
    PLAN_PASSED,
    PLAN_SUSPENDED,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    SCOPE_EXTERNAL_COATING,
    SEAM_EXAM_SCHEDULED,
    SEAM_RT_ACCEPTED,
    SEAM_RT_REJECTED,
    WITHDRAWAL_CANCELLED,
    WITHDRAWAL_CONSUMED,
    COATING_ACCEPTED,
    COATING_REWORK_REQUIRED,
)
from test_helpers.test_users import PE1_ID


def _approved_plan_holding_two_windows(api):
    """A SHELL_COMPLETE tank with an approved plan and two reserved windows."""
    ctx = X.approved_plan(api)
    ctx.withdrawals = [
        X.reserve_withdrawal(
            api, ctx.plan_id, ctx.source_id,
            f"2026-08-11T{hour:02d}:00:00Z", f"2026-08-11T{hour + 6:02d}:00:00Z",
            300.0, 100000.0,
        )
        for hour in (0, 6)
    ]
    return ctx


class TestNdeRejectionFiveHopCascade:
    def _reject_a_reexamination(self, api):
        ctx = _approved_plan_holding_two_windows(api)
        start, end = X.rt_window("2026-08-12", 0)
        report = X.schedule_nde(api, ctx.seam_id, start, end)
        ctx.rejection = X.report_nde(
            api, report["id"], DECISION_REJECT, 2, 4, DEFECT_SLAG_INCLUSION
        )
        return ctx

    def test_the_rejection_reaches_the_seam_the_course_and_the_tank_posture(self, api):
        """Hops one through three: report, seam, course and posture.

        PRD: "First, the seam moves to `RT_REJECTED`, or straight to the terminal
        `REPLACEMENT_REQUIRED` when its `repair_cycle_count` has already reached 2.
        Second, that newly open rejection raises the tank's
        `open_nonconformance_count`, so `quality_posture` is recomputed."

        Design: Difficulty/transitive_cascade/nde_rejection_five_hop_posture_suspension_water_release
        """
        ctx = self._reject_a_reexamination(api)

        assert ctx.rejection["status"] == NDE_REPORTED_REJECT
        assert ctx.rejection["nonconformance_open"] is True

        seam = X.read_seam(api, ctx.seam_id)
        assert seam["status"] == SEAM_RT_REJECTED
        assert seam["repair_cycle_count"] == 0
        assert X.read_course(api, ctx.course_id)["status"] == COURSE_FITTED

        assert_tank_state(
            X.read_tank(api, ctx.tank_id),
            phase=PHASE_ERECTION_IN_PROGRESS,
            posture=POSTURE_RESTRICTED,
            nonconformance_count=1,
        )

    def test_the_degraded_posture_suspends_the_live_plan_and_records_its_prior_state(self, api):
        """Hop four: the approved plan is suspended and remembers where it was.

        PRD: "Third, a resulting `RESTRICTED` or `FROZEN` posture suspends every
        hydrostatic test plan of the tank sitting in `APPROVED`, `FILLING` or
        `FILL_HOLD`, each recording its `state_before_suspension`."

        Design: Difficulty/transitive_cascade/nde_rejection_five_hop_posture_suspension_water_release
        """
        ctx = self._reject_a_reexamination(api)

        plan = X.read_plan(api, ctx.plan_id)
        assert plan["status"] == PLAN_SUSPENDED
        assert plan["state_before_suspension"] == PLAN_APPROVED
        assert plan["suspension_reason"] is not None
        assert plan["fill_percent_current"] == pytest.approx(0.0)
        assert plan["hold_started_at_utc"] is None

    def test_the_suspension_cancels_the_windows_and_releases_the_permit_volume(self, api):
        """Hops five and six: every reserved window is cancelled and its volume freed.

        PRD: "Fifth, each cancelled window releases its `reserved_volume_gal` back
        into its source's `available_volume_gal`."

        Design: Difficulty/transitive_cascade/nde_rejection_five_hop_posture_suspension_water_release
        """
        ctx = self._reject_a_reexamination(api)

        for index, withdrawal in enumerate(ctx.withdrawals):
            row = X.read_withdrawal(api, withdrawal["id"])
            assert row["status"] == WITHDRAWAL_CANCELLED, index
            assert row["cancellation_reason"] == CANCELLATION_PLAN_SUSPENDED, index

        assert_source_ledger(
            X.read_water_source(api, ctx.source_id),
            reserved=0.00,
            consumed=0.00,
            available=2000000.00,
        )

    def test_the_released_reservations_collapse_the_plans_whole_cost_chain(self, api):
        """The cost chain is recomputed over an input set that is now empty.

        PRD: "Cancelled withdrawals are excluded entirely."

        Design: Difficulty/transitive_cascade/nde_rejection_five_hop_posture_suspension_water_release
        """
        ctx = self._reject_a_reexamination(api)

        plan = X.read_plan(api, ctx.plan_id)
        assert_plan_costs(
            plan, water=0.00, disposal=0.00, subtotal=0.00,
            surcharge_pct=0.00, surcharge=0.00, total=0.00,
        )

        tank = X.read_tank(api, ctx.tank_id)
        assert tank["weld_reject_rate"] == pytest.approx(0.5000, abs=1e-9)
        assert tank["required_examination_pct"] == pytest.approx(FULL_EXAMINATION_PCT)


class TestCoatingHolidayFourHopCascade:
    def _external_lining_at_dft(self, api):
        """A COATED tank with a submitted package and a second application measured."""
        ctx = X.submitted_package_tank(api)
        ctx.external = X.create_coating(api, ctx.tank_id, SCOPE_EXTERNAL_COATING)
        ctx.external_id = ctx.external["id"]
        X.surface_prep(api, ctx.external_id)
        ctx.external = X.dft_readings(api, ctx.external_id, X.PASSING_SPOT_READINGS)
        return ctx

    def test_the_project_stands_complete_before_the_holiday_test(self, api):
        """The frozen cost chain, the consumed water and the submitted package.

        PRD: "The whole cost chain is recomputed on every withdrawal reservation
        and on every withdrawal cancellation, and it is frozen onto the plan when
        the plan passes."

        Design: Difficulty/transitive_cascade/coating_holiday_four_hop_returns_submitted_commissioning_package
        """
        ctx = self._external_lining_at_dft(api)

        assert_tank_state(
            X.read_tank(api, ctx.tank_id), phase=PHASE_COATED, posture=POSTURE_OPEN,
            nonconformance_count=0,
        )
        package = X.read_commissioning_package(api, ctx.commissioning_id)
        assert package["status"] == PACKAGE_SUBMITTED
        assert package["submitted_by_user_id"] == PE1_ID
        assert package["deficiency_count"] == 0

        plan = X.read_plan(api, ctx.plan_id)
        assert plan["status"] == PLAN_PASSED
        assert plan["settlement_survey_count"] == 4
        assert_plan_costs(
            plan, water=1332.00, disposal=840.00, subtotal=2172.00,
            surcharge_pct=0.05, surcharge=108.60, total=2280.60,
        )

        assert X.read_withdrawal(api, ctx.withdrawal_id)["status"] == WITHDRAWAL_CONSUMED
        assert_source_ledger(
            X.read_water_source(api, ctx.source_id),
            reserved=0.00, consumed=400000.00, available=1600000.00,
        )

    def test_a_holiday_on_the_external_coat_degrades_the_posture(self, api):
        """Hops one and two: the application reworks and the posture drops.

        PRD: "Second, the tank's posture is recomputed: an open coating rework
        counts as one nonconformance, so a previously `OPEN` tank becomes
        `RESTRICTED`."

        Design: Difficulty/transitive_cascade/coating_holiday_four_hop_returns_submitted_commissioning_package
        """
        ctx = self._external_lining_at_dft(api)

        reworked = X.holiday_test(api, ctx.external_id, 3, 200.0)

        assert reworked["status"] == COATING_REWORK_REQUIRED
        assert reworked["holidays_found"] == 3
        assert reworked["holiday_test_voltage_v"] == pytest.approx(200.0)
        assert_tank_state(
            X.read_tank(api, ctx.tank_id), posture=POSTURE_RESTRICTED,
            nonconformance_count=1,
        )

    def test_a_completed_milestone_is_taken_back_and_the_package_is_returned(self, api):
        """Hops three and four: the phase reverts and the package comes back mechanically.

        PRD: "That fourth link deliberately leaves `reviewed_by_user_id`
        untouched, because no inspector acted — the return was mechanical."

        Design: Difficulty/transitive_cascade/coating_holiday_four_hop_returns_submitted_commissioning_package
        """
        ctx = self._external_lining_at_dft(api)

        X.holiday_test(api, ctx.external_id, 3, 200.0)

        assert X.read_tank(api, ctx.tank_id)["construction_phase"] == PHASE_HYDROTEST_PASSED

        package = X.read_commissioning_package(api, ctx.commissioning_id)
        assert package["status"] == PACKAGE_RETURNED_FOR_CORRECTION
        assert package["deficiency_count"] == 1
        assert package["next_internal_due_utc"] is None
        assert package["next_external_due_utc"] is None
        assert package["reviewed_by_user_id"] is None

    def test_the_cascade_touches_only_the_application_that_failed(self, api):
        """The internal lining that passed keeps its terminal status.

        PRD: "A tank may carry any number of applications, and each is
        independent."

        Design: Difficulty/transitive_cascade/coating_holiday_four_hop_returns_submitted_commissioning_package
        """
        ctx = self._external_lining_at_dft(api)

        X.holiday_test(api, ctx.external_id, 3, 200.0)

        assert X.read_coating(api, ctx.coating_id)["status"] == COATING_ACCEPTED


class TestReexaminationThreeHopPhaseRevert:
    def test_the_tank_stands_shell_complete_before_the_second_window_is_booked(self, api):
        """The starting position: seam, course and tank all at their accepted states.

        PRD: "The course is `RT_ACCEPTED` when it has at least one seam and every
        one of its seams is `RT_ACCEPTED`."

        Design: Difficulty/transitive_cascade/reexamination_three_hop_phase_revert_without_posture_change
        """
        ctx = X.shell_complete_tank(api)

        assert X.read_seam(api, ctx.seam_id)["status"] == SEAM_RT_ACCEPTED
        assert X.read_course(api, ctx.course_id)["status"] == COURSE_RT_ACCEPTED
        assert X.read_tank(api, ctx.tank_id)["construction_phase"] == PHASE_SHELL_COMPLETE

    def test_scheduling_a_further_radiograph_walks_seam_course_and_phase_back(self, api):
        """Three hops from a plain creation call, with nothing wrong yet.

        PRD: "A course falling out of `RT_ACCEPTED` back to `WELDED`, because a
        fresh examination was scheduled on an already accepted seam, also reverts
        the tank `SHELL_COMPLETE → ERECTION_IN_PROGRESS` when the tank had reached
        `SHELL_COMPLETE`"

        Design: Difficulty/transitive_cascade/reexamination_three_hop_phase_revert_without_posture_change
        """
        ctx = X.shell_complete_tank(api)

        start, end = X.rt_window("2026-08-12", 0)
        second = X.schedule_nde(api, ctx.seam_id, start, end)

        seam = X.read_seam(api, ctx.seam_id)
        assert seam["status"] == SEAM_EXAM_SCHEDULED
        assert seam["last_nde_report_id"] == second["id"]
        assert X.read_course(api, ctx.course_id)["status"] == COURSE_WELDED
        assert X.read_tank(api, ctx.tank_id)["construction_phase"] == PHASE_ERECTION_IN_PROGRESS

    def test_the_posture_dimension_and_the_earlier_acceptance_are_untouched(self, api):
        """Nothing is wrong, so no nonconformance carrier moves.

        PRD: "`weld_reject_rate` is 0.0 when that population is empty, and
        otherwise the count of rejected reports divided by the count of examined
        reports, rounded half up to 4 decimal places."

        Design: Difficulty/transitive_cascade/reexamination_three_hop_phase_revert_without_posture_change
        """
        ctx = X.shell_complete_tank(api)
        start, end = X.rt_window("2026-08-12", 0)
        X.schedule_nde(api, ctx.seam_id, start, end)

        tank = X.read_tank(api, ctx.tank_id)
        assert_tank_state(tank, posture=POSTURE_OPEN, nonconformance_count=0)
        assert tank["weld_reject_rate"] == pytest.approx(0.0)
        assert tank["required_examination_pct"] == pytest.approx(BASE_EXAMINATION_PCT)

        first = X.read_nde_report(api, ctx.report_id)
        assert first["status"] == NDE_REPORTED_ACCEPT
        assert first["nonconformance_open"] is False
