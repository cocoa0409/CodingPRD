"""Machines whose next state is not a function of the trigger alone.

A weld seam runs a counted repair loop that diverts to a terminal state at its
cap; a tank carries two orthogonal state fields that move independently; a
coating application runs an uncapped loop that wipes its own evidence on re-entry.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import fixtures as X
from test_helpers.api_errors import ERR_COATING_STEP_INVALID, ERR_REPAIR_LIMIT_EXCEEDED
from test_helpers.assertions import assert_money, assert_settlement, assert_tank_state
from test_helpers.constants import (
    COATING_ACCEPTED,
    COATING_PREP_ACCEPTED,
    COATING_REWORK_REQUIRED,
    COURSE_FITTED,
    DECISION_ACCEPT,
    DECISION_REJECT,
    DEFECT_CRACK,
    DEFECT_POROSITY,
    DEFECT_SLAG_INCLUSION,
    DFT_NOT_EVALUATED,
    DFT_PASS,
    DFT_SPOT_AVERAGE_80_120,
    FULL_EXAMINATION_PCT,
    NC_CLOSED_BY_SUPERSEDING_SURVEY,
    PHASE_ERECTION_IN_PROGRESS,
    POSTURE_FROZEN,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    PREP_SSPC_SP10,
    PREP_SSPC_SP5,
    SEAM_REPLACEMENT_REQUIRED,
    SEAM_RT_REJECTED,
    SEAM_WELDED,
    VERDICT_OUT_OF_TOLERANCE,
    VERDICT_WITHIN_TOLERANCE,
)
from test_helpers.test_users import ES1, QC1, welder_headers


def _examine(api, seam_id, day, decision, indication_count, defect_type=None):
    """One RT examination on its own calendar day, so buffers never collide."""
    start, end = X.rt_window(day, 0)
    report = X.schedule_nde(api, seam_id, start, end)
    X.report_nde(api, report["id"], decision, indication_count, 4, defect_type)
    return report["id"]


def _seam_at_repair_cap(api):
    """Walk the repair loop twice so `repair_cycle_count` reaches its cap of 2."""
    ctx = X.welded_course(api)
    ctx.trace = []

    _examine(api, ctx.seam_id, "2026-08-11", DECISION_REJECT, 2, DEFECT_SLAG_INCLUSION)
    ctx.trace.append(X.read_seam(api, ctx.seam_id))

    X.repair_start(api, ctx.seam_id)
    ctx.trace.append(X.weld(api, ctx.seam_id, ctx.welder_id, filler_lot="E7018-B"))

    _examine(api, ctx.seam_id, "2026-08-12", DECISION_ACCEPT, 0)
    _examine(api, ctx.seam_id, "2026-08-13", DECISION_REJECT, 1, DEFECT_POROSITY)
    ctx.trace.append(X.read_seam(api, ctx.seam_id))

    X.repair_start(api, ctx.seam_id)
    ctx.trace.append(X.weld(api, ctx.seam_id, ctx.welder_id, filler_lot="E7018-C"))

    _examine(api, ctx.seam_id, "2026-08-14", DECISION_ACCEPT, 0)
    return ctx


class TestWeldSeamRepairCycleCap:
    def test_each_traverse_of_the_repair_loop_increments_the_cycle_counter(self, api):
        """A re-weld after excavation counts; the first weld does not.

        PRD: "either `FIT_READY → WELDED` for a first weld or
        `REPAIR_IN_PROGRESS → WELDED` for a re-weld after excavation, in which
        case `repair_cycle_count` is incremented by 1."

        Design: Difficulty/non_linear_state_machine/weld_seam_repair_cycle_terminates_at_cap
        """
        ctx = _seam_at_repair_cap(api)
        first_reject, first_reweld, second_reject, second_reweld = ctx.trace

        assert first_reject["status"] == SEAM_RT_REJECTED
        assert first_reject["repair_cycle_count"] == 0
        assert first_reweld["status"] == SEAM_WELDED
        assert first_reweld["repair_cycle_count"] == 1
        assert second_reject["status"] == SEAM_RT_REJECTED
        assert second_reject["repair_cycle_count"] == 1
        assert second_reweld["status"] == SEAM_WELDED
        assert second_reweld["repair_cycle_count"] == 2

    def test_a_rejection_at_the_cap_diverts_the_seam_to_replacement_required(self, api):
        """The same trigger produces a different target state on the third pass.

        PRD: "a rejection recorded while `repair_cycle_count` is already 2 sends
        the seam to the terminal `REPLACEMENT_REQUIRED` instead of `RT_REJECTED`,
        meaning the plate must be cut out and replaced."

        Design: Difficulty/non_linear_state_machine/weld_seam_repair_cycle_terminates_at_cap
        """
        ctx = _seam_at_repair_cap(api)

        _examine(api, ctx.seam_id, "2026-08-15", DECISION_REJECT, 3, DEFECT_CRACK)

        seam = X.read_seam(api, ctx.seam_id)
        assert seam["status"] == SEAM_REPLACEMENT_REQUIRED
        assert seam["repair_cycle_count"] == 2
        assert X.read_course(api, ctx.course_id)["status"] == COURSE_FITTED

    def test_both_loop_entry_points_are_refused_once_replacement_is_required(self, api):
        """Neither a further weld log nor a further repair start is accepted.

        PRD: "A seam in `REPLACEMENT_REQUIRED` accepts neither a further weld log
        nor a further repair start, and either attempt is rejected with
        `ERR_REPAIR_LIMIT_EXCEEDED`."

        Design: Difficulty/non_linear_state_machine/weld_seam_repair_cycle_terminates_at_cap
        """
        ctx = _seam_at_repair_cap(api)
        _examine(api, ctx.seam_id, "2026-08-15", DECISION_REJECT, 3, DEFECT_CRACK)

        validate_error(
            api.weld_log(
                ctx.seam_id,
                {"welder_id": ctx.welder_id, "filler_lot": "E7018-D"},
                welder_headers(ctx.welder_id),
            ),
            ERR_REPAIR_LIMIT_EXCEEDED,
        )
        validate_error(
            api.repair_start(
                ctx.seam_id, {"defect_disposition": "CUT_OUT_AND_REPLACE"}, ES1
            ),
            ERR_REPAIR_LIMIT_EXCEEDED,
        )

        assert X.read_seam(api, ctx.seam_id)["status"] == SEAM_REPLACEMENT_REQUIRED

    def test_the_loop_preserves_its_examination_history_and_escalates_coverage(self, api):
        """Three rejections out of five examinations mandate full radiography.

        PRD: "a rate of 0.50 or higher mandates 100.0 percent examination"

        Design: Difficulty/non_linear_state_machine/weld_seam_repair_cycle_terminates_at_cap
        """
        ctx = _seam_at_repair_cap(api)
        _examine(api, ctx.seam_id, "2026-08-15", DECISION_REJECT, 3, DEFECT_CRACK)

        tank = X.read_tank(api, ctx.tank_id)
        assert tank["weld_reject_rate"] == pytest.approx(0.6000, abs=1e-9)
        assert tank["required_examination_pct"] == pytest.approx(FULL_EXAMINATION_PCT)
        assert_tank_state(tank, posture=POSTURE_RESTRICTED, nonconformance_count=1)


class TestTankPhaseAndPostureMoveIndependently:
    def _two_welded_seams(self, api):
        return X.welded_course(api, seam_labels=("V1", "V2"))

    def test_two_rejections_degrade_the_posture_while_the_phase_stays_put(self, api):
        """The posture band moves on the count; the phase answers only to an operator.

        PRD: "`quality_posture` is then `OPEN` when the count is zero,
        `RESTRICTED` when the count is 1 or 2 inclusive, and `FROZEN` when the
        count is 3 or more."

        Design: Difficulty/non_linear_state_machine/tank_phase_and_posture_move_independently
        """
        ctx = self._two_welded_seams(api)

        X.reject_examination(api, ctx.seams[0]["id"], "2026-08-11", 0)
        assert_tank_state(
            X.read_tank(api, ctx.tank_id),
            phase=PHASE_ERECTION_IN_PROGRESS,
            posture=POSTURE_RESTRICTED,
            nonconformance_count=1,
        )

        X.reject_examination(api, ctx.seams[1]["id"], "2026-08-12", 0)
        assert_tank_state(
            X.read_tank(api, ctx.tank_id),
            phase=PHASE_ERECTION_IN_PROGRESS,
            posture=POSTURE_RESTRICTED,
            nonconformance_count=2,
        )

    def test_a_third_carrier_freezes_the_tank_without_moving_the_phase(self, api):
        """An out-of-tolerance survey is a different carrier of the same count.

        PRD: "An `OUT_OF_TOLERANCE` monitoring survey instead moves to `OPEN`,
        which raises the tank's `open_nonconformance_count` and triggers the
        posture recomputation and the suspension cascade of §2.8"

        Design: Difficulty/non_linear_state_machine/tank_phase_and_posture_move_independently
        """
        ctx = self._two_welded_seams(api)
        X.reject_examination(api, ctx.seams[0]["id"], "2026-08-11", 0)
        X.reject_examination(api, ctx.seams[1]["id"], "2026-08-12", 0)

        survey = X.create_survey(api, ctx.package_id, X.DISHED_POINT1, 50.0)

        assert_settlement(survey["uniform_settlement_in"], 0.750, "uniform")
        assert_settlement(survey["max_out_of_plane_in"], 3.750, "out of plane")
        assert_settlement(survey["max_adjacent_differential_in"], 6.000, "adjacent pair")
        assert_settlement(survey["governing_metric_in"], 3.750, "governing")
        assert survey["verdict"] == VERDICT_OUT_OF_TOLERANCE

        assert_tank_state(
            X.read_tank(api, ctx.tank_id),
            phase=PHASE_ERECTION_IN_PROGRESS,
            posture=POSTURE_FROZEN,
            nonconformance_count=3,
        )
        assert X.read_course(api, ctx.course_id)["status"] == COURSE_FITTED

    def test_a_superseding_survey_walks_the_posture_back_to_restricted(self, api):
        """The posture reverses along the same axis while the phase never moves.

        PRD: "the earlier survey moves `OPEN → CLOSED_BY_SUPERSEDING_SURVEY`, its
        `superseded_by_survey_id` is pointed at the new survey, the tank's count
        is decremented"

        Design: Difficulty/non_linear_state_machine/tank_phase_and_posture_move_independently
        """
        ctx = self._two_welded_seams(api)
        X.reject_examination(api, ctx.seams[0]["id"], "2026-08-11", 0)
        X.reject_examination(api, ctx.seams[1]["id"], "2026-08-12", 0)
        opened = X.create_survey(api, ctx.package_id, X.DISHED_POINT1, 50.0)

        healed = X.create_survey(api, ctx.package_id, X.UNIFORM_BASELINE, 50.0)

        assert healed["verdict"] == VERDICT_WITHIN_TOLERANCE
        opened = X.read_survey(api, opened["id"])
        assert opened["nonconformance_state"] == NC_CLOSED_BY_SUPERSEDING_SURVEY
        assert opened["superseded_by_survey_id"] == healed["id"]

        assert_tank_state(
            X.read_tank(api, ctx.tank_id),
            phase=PHASE_ERECTION_IN_PROGRESS,
            posture=POSTURE_RESTRICTED,
            nonconformance_count=2,
        )


class TestCoatingReworkLoopIsUncappedAndResets:
    def _application_in_first_rework(self, api):
        """One lining driven through readings into a holiday failure."""
        X.set_clock(api, "2026-08-10T00:00:00Z")
        tank = X.create_tank(api)
        application = X.create_coating(
            api,
            tank["id"],
            surface_area_sqft=12000.0,
            specified_prep_standard=PREP_SSPC_SP10,
            specified_min_dft_mils=10.0,
            dft_acceptance_method=DFT_SPOT_AVERAGE_80_120,
            coating_system="epoxy-phenolic 2 coat",
        )
        X.surface_prep(api, application["id"], achieved_prep_standard=PREP_SSPC_SP10,
                       profile_mils=3.0, dew_point_spread_f=12.0)
        X.dft_readings(api, application["id"], [[10.0, 10.0, 10.0], [11.0, 11.0, 11.0]])
        reworked = X.holiday_test(api, application["id"], 2, 900.0)
        return tank, application["id"], reworked

    def test_a_holiday_failure_opens_a_nonconformance_and_demands_rework(self, api):
        """The loop is entered from the measured state, not from the specification.

        PRD: "First, the application moves `DFT_RECORDED → REWORK_REQUIRED` with
        `holidays_found` and `holiday_test_voltage_v` stored."

        Design: Difficulty/non_linear_state_machine/coating_rework_loop_resets_and_is_uncapped
        """
        tank, _, reworked = self._application_in_first_rework(api)

        assert reworked["status"] == COATING_REWORK_REQUIRED
        assert reworked["holidays_found"] == 2
        assert_tank_state(
            X.read_tank(api, tank["id"]), posture=POSTURE_RESTRICTED, nonconformance_count=1
        )

    def test_re_preparation_increments_the_cycle_and_wipes_the_earlier_evidence(self, api):
        """Re-entry discards the previous cycle's aggregates rather than keeping them.

        PRD: "That step increments `rework_cycle_count` by 1, resets `dft_verdict`
        to `NOT_EVALUATED`, resets `spot_count` to 0 and every computed DFT
        aggregate to 0.0, and resets `holidays_found` and `holiday_test_voltage_v`
        to null — the previous cycle's evidence is discarded rather than kept
        alongside the new cycle's."

        Design: Difficulty/non_linear_state_machine/coating_rework_loop_resets_and_is_uncapped
        """
        tank, application_id, _ = self._application_in_first_rework(api)

        reprepared = X.surface_prep(api, application_id, achieved_prep_standard=PREP_SSPC_SP10,
                                    profile_mils=3.0, dew_point_spread_f=8.0)

        assert reprepared["status"] == COATING_PREP_ACCEPTED
        assert reprepared["rework_cycle_count"] == 1
        assert reprepared["dft_verdict"] == DFT_NOT_EVALUATED
        assert reprepared["spot_count"] == 0
        assert_money(reprepared["computed_spot_average_min_mils"], 0.00, "min spot average")
        assert_money(reprepared["computed_spot_average_max_mils"], 0.00, "max spot average")
        assert_money(reprepared["computed_overall_average_mils"], 0.00, "overall average")
        assert_money(reprepared["computed_min_gauge_reading_mils"], 0.00, "min gauge")
        assert reprepared["holidays_found"] is None
        assert reprepared["holiday_test_voltage_v"] is None

        assert_tank_state(
            X.read_tank(api, tank["id"]), posture=POSTURE_OPEN, nonconformance_count=0
        )

    def test_the_next_reading_set_is_a_full_recompute_not_an_accumulation(self, api):
        """One spot after a two-spot cycle reports one spot.

        PRD: "every aggregate is recomputed from scratch over the submitted
        payload alone."

        Design: Difficulty/non_linear_state_machine/coating_rework_loop_resets_and_is_uncapped
        """
        _, application_id, _ = self._application_in_first_rework(api)
        X.surface_prep(api, application_id, achieved_prep_standard=PREP_SSPC_SP10,
                       profile_mils=3.0, dew_point_spread_f=8.0)

        measured = X.dft_readings(api, application_id, [[12.0, 12.0, 12.0]])

        assert measured["spot_count"] == 1
        assert_money(measured["computed_overall_average_mils"], 12.00, "overall average")

    def test_the_loop_has_no_ceiling_and_the_third_cycle_reaches_accepted(self, api):
        """A second rework is accepted and the terminal state then refuses every step.

        PRD: "`rework_cycle_count` has no ceiling; the cycle `SPEC_ISSUED →
        PREP_ACCEPTED → DFT_RECORDED → REWORK_REQUIRED → PREP_ACCEPTED` may repeat
        indefinitely."

        Design: Difficulty/non_linear_state_machine/coating_rework_loop_resets_and_is_uncapped
        """
        _, application_id, _ = self._application_in_first_rework(api)
        X.surface_prep(api, application_id, achieved_prep_standard=PREP_SSPC_SP10,
                       profile_mils=3.0, dew_point_spread_f=8.0)
        X.dft_readings(api, application_id, [[12.0, 12.0, 12.0]])

        second_rework = X.holiday_test(api, application_id, 1, 900.0)
        assert second_rework["status"] == COATING_REWORK_REQUIRED
        assert second_rework["rework_cycle_count"] == 1

        reprepared = X.surface_prep(api, application_id, achieved_prep_standard=PREP_SSPC_SP5,
                                    profile_mils=3.5, dew_point_spread_f=10.0)
        assert reprepared["status"] == COATING_PREP_ACCEPTED
        assert reprepared["rework_cycle_count"] == 2

        measured = X.dft_readings(api, application_id, [[10.0, 11.0, 12.0]])
        assert measured["dft_verdict"] == DFT_PASS
        assert_money(measured["computed_overall_average_mils"], 11.00, "overall average")

        accepted = X.holiday_test(api, application_id, 0, 675.0)
        assert accepted["status"] == COATING_ACCEPTED

        validate_error(
            api.surface_prep(
                application_id,
                {
                    "achieved_prep_standard": PREP_SSPC_SP10,
                    "profile_mils": 3.0,
                    "dew_point_spread_f": 12.0,
                },
                QC1,
            ),
            ERR_COATING_STEP_INVALID,
        )
        assert X.read_coating(api, application_id)["rework_cycle_count"] == 2
