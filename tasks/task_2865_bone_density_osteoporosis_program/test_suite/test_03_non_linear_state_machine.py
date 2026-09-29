"""State machines that run backwards, or that need more than one event to move.

An acquisition can be pushed back to IN_PROGRESS while its schedule stays
terminal, a therapy plan can leave and re-enter ON_THERAPY on data alone, and a
device on quality-control hold needs two clean phantom runs rather than one.
"""

import pytest

from test_helpers import (
    BMD_FEMORAL_NECK_OSTEOPENIC,
    BMD_FEMORAL_NECK_OSTEOPOROTIC,
    BMD_LUMBAR_OSTEOPENIC,
    PHYSICIAN_HEADERS,
    ProgramWorld,
    TECHNOLOGIST_HEADERS,
    assert_counters,
    assert_instant_equals,
    assert_qc_scoring,
    assert_review_outcome,
    assert_three_decimals,
    get_success_data,
    validate_success,
)

TWO_SITE_STUDY = [
    ("LUMBAR_SPINE", BMD_LUMBAR_OSTEOPENIC),
    ("FEMORAL_NECK", BMD_FEMORAL_NECK_OSTEOPENIC),
]


def _repeat_required_session(world: ProgramWorld):
    """A two-site study submitted and then judged unfit by an independent reviewer."""
    return world.build(
        stop_after="reviewed",
        sites=TWO_SITE_STUDY,
        defect_codes=["ROTATION_FEMUR"],
    )


class TestRepeatCycleRunsTheAcquisitionBackwards:
    """REPEAT_REQUIRED drags acquisition_status back and erases the derived scores."""

    def test_repeat_reopens_the_session_and_nulls_every_derived_score(
        self, world: ProgramWorld
    ):
        """Both dimensions rewind and the three aggregate scores go back to null.

        "Repeating moves `acquisition_status` from `SUBMITTED` back to
        `IN_PROGRESS` and `review_status` from `REPEAT_REQUIRED` back to
        `NOT_REVIEWED`, increments `repeat_count` by one, resets
        `submitted_at_utc`, `lowest_t_score`, `lowest_t_score_site` and
        `lowest_z_score` to null."

        Design: Difficulty/non_linear_state_machine/session_repeat_cycle_reverts_acquisition_while_order_stays_terminal
        """
        pipeline = _repeat_required_session(world)
        assert_review_outcome(pipeline.review, 3, True, "REPEAT_REQUIRED")
        assert pipeline.session["review_status"] == "REPEAT_REQUIRED"

        reopened = world.repeat(pipeline.session_id)

        assert reopened["acquisition_status"] == "IN_PROGRESS"
        assert reopened["review_status"] == "NOT_REVIEWED"
        assert reopened["repeat_count"] == 1
        assert reopened["submitted_at_utc"] is None
        assert reopened["lowest_t_score"] is None
        assert reopened["lowest_t_score_site"] is None
        assert reopened["lowest_z_score"] is None
        assert reopened["measured_site_count"] == 0

    def test_the_schedule_stays_terminal_while_the_measurements_are_superseded(
        self, world: ProgramWorld
    ):
        """The visit is not undone: both rows supersede but the slot stays COMPLETED.

        "... and marks **every** existing measurement on the session
        `superseded`, which returns `measured_site_count` to zero and requires
        the whole site set to be re-acquired from scratch." "The appointment
        stays `COMPLETED` and the order stays `COMPLETED` throughout - the
        patient is still on the table for the same visit, so nothing about the
        schedule is undone."

        Design: Difficulty/non_linear_state_machine/session_repeat_cycle_reverts_acquisition_while_order_stays_terminal
        """
        pipeline = _repeat_required_session(world)

        world.repeat(pipeline.session_id)

        rows = validate_success(
            world.api.list_site_measurements(
                pipeline.session_id,
                TECHNOLOGIST_HEADERS,
                {"include_superseded": True},
            )
        )
        by_site = {row["site_code"]: row for row in rows}
        assert by_site["LUMBAR_SPINE"]["superseded"] is True
        assert by_site["FEMORAL_NECK"]["superseded"] is True

        live = validate_success(
            world.api.list_site_measurements(pipeline.session_id, TECHNOLOGIST_HEADERS)
        )
        assert live == []

        appointment = get_success_data(
            world.api.get_scan_appointment(pipeline.appointment_id, PHYSICIAN_HEADERS)
        )
        assert appointment["status"] == "COMPLETED"

        order = get_success_data(
            world.api.get_scan_order(pipeline.order_id, PHYSICIAN_HEADERS)
        )
        assert order["status"] == "COMPLETED"
        assert order["reschedule_required"] is False

        assert_counters(world.read_patient(pipeline.patient_id), 0, 0)


def _plan_with_two_claims(world: ProgramWorld):
    """An oral bisphosphonate plan carrying sixty covered days, clock at the first due date."""
    pipeline = world.build(
        stop_after="finalized",
        sites=[("FEMORAL_NECK", BMD_FEMORAL_NECK_OSTEOPOROTIC)],
    )
    plan = world.create_plan(
        pipeline.patient_id,
        pipeline.report_id,
        drug_class="BISPHOSPHONATE_ORAL",
        start_date="2026-04-01",
        adherence_source_policy="CLAIMS_ONLY",
    )
    assert plan["status"] == "INITIATED"
    assert plan["followup_interval_months"] == 3
    assert plan["next_followup_due_date"] == "2026-07-01"

    world.set_clock("2026-06-15T08:00:00Z")
    world.record_refill(
        plan["id"],
        dispensed_date="2026-04-01",
        days_supplied=30,
        source="PHARMACY_CLAIM",
    )
    world.record_refill(
        plan["id"],
        dispensed_date="2026-05-01",
        days_supplied=30,
        source="PHARMACY_CLAIM",
    )
    world.set_clock("2026-07-01T08:00:00Z")
    return plan


class TestTreatmentPlanLeavesAndReEntersOnTherapy:
    """The same endpoint with the same AUTO action walks the plan in both directions."""

    def test_first_two_reviews_walk_initiated_to_on_therapy_then_onto_hold(
        self, world: ProgramWorld
    ):
        """A widening window over unchanged refills flips PARTIAL to NON_ADHERENT.

        "From `INITIATED` or `ADHERENCE_HOLD`, an `ADHERENT` or `PARTIAL` verdict
        moves the plan to `ON_THERAPY` and resets `consecutive_nonadherent_reviews`
        to zero. From `INITIATED` or `ON_THERAPY`, a `NON_ADHERENT` verdict — or a
        denosumab gap beyond its limit — moves the plan to `ADHERENCE_HOLD` and
        increments `consecutive_nonadherent_reviews`."

        Design: Difficulty/non_linear_state_machine/treatment_plan_leaves_and_re_enters_on_therapy_across_three_reviews
        """
        plan = _plan_with_two_claims(world)

        first = world.review_adherence(
            plan["id"], requested_action="AUTO", note="review 1"
        )
        assert first["adherence_window_days"] == 91
        assert first["covered_days_supplied"] == pytest.approx(60.0, abs=0.05)
        assert_three_decimals(
            first["medication_possession_ratio"], 0.659, "medication_possession_ratio"
        )
        assert first["adherence_status"] == "PARTIAL"
        assert first["status"] == "ON_THERAPY"
        assert first["consecutive_nonadherent_reviews"] == 0
        assert first["adherence_review_count"] == 1
        assert first["next_followup_due_date"] == "2026-10-01"

        world.set_clock("2026-10-01T08:00:00Z")
        second = world.review_adherence(
            plan["id"], requested_action="AUTO", note="review 2"
        )
        assert second["adherence_window_days"] == 183
        assert second["covered_days_supplied"] == pytest.approx(60.0, abs=0.05)
        assert_three_decimals(
            second["medication_possession_ratio"], 0.328, "medication_possession_ratio"
        )
        assert second["adherence_status"] == "NON_ADHERENT"
        assert second["status"] == "ADHERENCE_HOLD"
        assert second["consecutive_nonadherent_reviews"] == 1
        assert second["adherence_review_count"] == 2
        assert second["next_followup_due_date"] == "2027-01-01"

    def test_third_review_re_enters_on_therapy_and_resets_the_failure_counter(
        self, world: ProgramWorld
    ):
        """Newly recorded refills lift the ratio to exactly the adherent minimum.

        "That closes the first cycle in this entity — `ON_THERAPY` to
        `ADHERENCE_HOLD` and back to `ON_THERAPY` — with a bounded escape hatch
        after two consecutive failures." "`discontinuation_reason_code` is
        populated exactly when `status` is `DISCONTINUED` and null otherwise."

        Design: Difficulty/non_linear_state_machine/treatment_plan_leaves_and_re_enters_on_therapy_across_three_reviews
        """
        plan = _plan_with_two_claims(world)
        world.review_adherence(plan["id"], requested_action="AUTO", note="review 1")
        world.set_clock("2026-10-01T08:00:00Z")
        world.review_adherence(plan["id"], requested_action="AUTO", note="review 2")

        world.set_clock("2026-12-20T08:00:00Z")
        world.record_refill(
            plan["id"],
            dispensed_date="2026-10-01",
            days_supplied=90,
            source="PHARMACY_CLAIM",
        )
        world.record_refill(
            plan["id"],
            dispensed_date="2026-11-15",
            days_supplied=70,
            source="PHARMACY_CLAIM",
        )
        world.set_clock("2027-01-01T08:00:00Z")

        third = world.review_adherence(
            plan["id"], requested_action="AUTO", note="review 3"
        )

        assert third["adherence_window_days"] == 275
        assert third["covered_days_supplied"] == pytest.approx(220.0, abs=0.05)
        assert_three_decimals(
            third["medication_possession_ratio"], 0.800, "medication_possession_ratio"
        )
        assert third["adherence_status"] == "ADHERENT"
        assert third["status"] == "ON_THERAPY"
        assert third["consecutive_nonadherent_reviews"] == 0
        assert third["adherence_review_count"] == 3
        assert third["last_review_date"] == "2027-01-01"
        assert third["next_followup_due_date"] == "2027-04-01"
        assert third["discontinuation_reason_code"] is None
        assert third["holiday_eligible"] is False


def _device_on_out_of_control_hold(world: ProgramWorld):
    """A registered device driven onto hold by one failing phantom run."""
    world.set_clock("2026-03-05T08:00:00Z")
    device = world.create_device(
        phantom_baseline_bmd_g_cm2=1.0000, phantom_baseline_sd_g_cm2=0.0100
    )
    assert device["status"] == "ACTIVE"

    failing = world.record_qc_run(device["id"], phantom_bmd_g_cm2=1.0200)
    assert_qc_scoring(failing, 0.0200, 2.000, "FAIL")
    assert failing["shift_detected"] is False

    held = world.read_device(device["id"])
    assert held["status"] == "QC_HOLD"
    assert held["qc_hold_reason_code"] == "OUT_OF_CONTROL_FAIL"
    assert held["consecutive_qc_pass_count"] == 0
    return device["id"], failing, held


class TestQcHoldReleaseNeedsTwoConsecutivePasses:
    """The QC_HOLD to ACTIVE edge waits for an accumulated counter, not for a request."""

    def test_first_passing_run_only_advances_the_counter(self, world: ProgramWorld):
        """One clean phantom run inside a hold leaves the hold fields intact.

        "Otherwise, on a `PASS`, `consecutive_qc_pass_count` increments by one; and
        if the device was in `QC_HOLD` and the new count has reached two, the device
        returns to `ACTIVE` ... Two consecutive clean runs are required for release,
        so the first passing run inside a hold only advances the counter and the
        device stays on hold."

        Design: Difficulty/non_linear_state_machine/densitometer_qc_hold_release_requires_two_passes_not_one
        """
        device_id, _, held = _device_on_out_of_control_hold(world)
        hold_started_at = held["qc_hold_started_at"]
        assert hold_started_at is not None

        first_pass = world.record_qc_run(device_id, phantom_bmd_g_cm2=1.0000)
        assert_qc_scoring(first_pass, 0.0000, 0.000, "PASS")
        assert first_pass["shift_detected"] is False

        still_held = world.read_device(device_id)
        assert still_held["status"] == "QC_HOLD"
        assert still_held["qc_hold_reason_code"] == "OUT_OF_CONTROL_FAIL"
        assert still_held["consecutive_qc_pass_count"] == 1
        assert_instant_equals(
            still_held["qc_hold_started_at"], hold_started_at, "qc_hold_started_at"
        )
        assert still_held["last_qc_result"] == "PASS"

    def test_second_passing_run_clears_the_hold_and_returns_the_device_to_active(
        self, world: ProgramWorld
    ):
        """The identical request one run later takes the release edge instead.

        "... the device returns to `ACTIVE` with `qc_hold_started_at` and
        `qc_hold_reason_code` both cleared to null. ... In every case the device's
        `last_qc_result` and `last_qc_run_at` are refreshed from the most recent
        daily run."

        Design: Difficulty/non_linear_state_machine/densitometer_qc_hold_release_requires_two_passes_not_one
        """
        device_id, _, _ = _device_on_out_of_control_hold(world)

        world.record_qc_run(device_id, phantom_bmd_g_cm2=1.0000)
        second_pass = world.record_qc_run(device_id, phantom_bmd_g_cm2=1.0000)

        assert second_pass["result"] == "PASS"
        assert second_pass["shift_detected"] is False

        released = world.read_device(device_id)
        assert released["status"] == "ACTIVE"
        assert released["consecutive_qc_pass_count"] == 2
        assert released["qc_hold_reason_code"] is None
        assert released["qc_hold_started_at"] is None
        assert released["last_qc_result"] == "PASS"
