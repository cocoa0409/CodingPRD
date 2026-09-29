"""The QC round loop, its boundary comparisons and its cross-entity precondition."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers.api_errors import ERR_BOOKING_NOT_COMPLETED
from test_helpers.assertions import (
    assert_decimal,
    assert_immutable_record,
    assert_unpaginated_list,
)
from test_helpers.constants import QC_VERDICT_FAIL, QC_VERDICT_PASS
from test_helpers.test_users import QC_ONE_HEADERS


class TestRejectRemediateResubmitPassCycle:
    """One deliverable through two rounds, leaving two immutable reports."""

    def test_the_cycle_appends_one_report_per_evaluated_round(self, world):
        """Round 0 fails at 1.00 LU, round 1 passes at 0.20 LU, both on the record.

        PRD §3.7: "Every evaluation appends an immutable **QC report** — this is the one
        operation in the QC loop that creates a new resource rather than mutating one."

        Design: Difficulty/non_linear_state_machine/qc_reject_remediate_resubmit_pass_cycle_with_append_only_reports
        """
        environment = world.prepared_environment()
        deliverable_id = environment["deliverable"]["id"]

        world.qc_submit(
            deliverable_id,
            measured_integrated_lufs=-25.00,
            measured_true_peak_dbtp=-3.00,
            me_stems_present=False,
        )
        first_report = world.qc_evaluate(deliverable_id)

        assert first_report["round"] == 0
        assert first_report["verdict"] == QC_VERDICT_FAIL
        assert first_report["rejection_codes"] == ["LOUDNESS_OUT_OF_TOLERANCE"]
        assert_decimal(first_report["deviation_lu"], 1.00)
        assert_decimal(first_report["measured_integrated_lufs"], -25.00)
        assert_decimal(first_report["target_lufs"], -24.00)

        rejected = world.get_deliverable(deliverable_id)
        assert rejected["status"] == "QC_REJECTED"
        assert rejected["qc_rejection_codes"] == ["LOUDNESS_OUT_OF_TOLERANCE"]

        reopened = world.remediate(deliverable_id)
        assert reopened["status"] == "REMEDIATION"
        assert reopened["remediation_round"] == 1
        assert reopened["qc_rejection_codes"] == []

        world.qc_submit(
            deliverable_id,
            measured_integrated_lufs=-24.20,
            measured_true_peak_dbtp=-3.00,
            me_stems_present=False,
        )
        second_report = world.qc_evaluate(deliverable_id)

        assert second_report["round"] == 1
        assert second_report["verdict"] == QC_VERDICT_PASS
        assert second_report["rejection_codes"] == []
        assert_decimal(second_report["deviation_lu"], 0.20)

        passed = world.get_deliverable(deliverable_id)
        assert passed["status"] == "QC_PASSED"
        assert passed["remediation_round"] == 1
        assert passed["qc_rejection_codes"] == []
        assert_decimal(passed["deviation_lu"], 0.20)

    def test_the_rejected_round_survives_its_own_remediation_unrewritten(self, world):
        """The round-0 row still reads as the failure that caused the remediation.

        PRD §2.5: "A **QC report** is an append-only evaluation record: one row per
        evaluated round, never rewritten, so the audit trail of a rejected mix survives
        its remediation."

        Design: Difficulty/non_linear_state_machine/qc_reject_remediate_resubmit_pass_cycle_with_append_only_reports
        """
        environment = world.prepared_environment()
        deliverable_id = environment["deliverable"]["id"]

        world.qc_submit(
            deliverable_id,
            measured_integrated_lufs=-25.00,
            measured_true_peak_dbtp=-3.00,
            me_stems_present=False,
        )
        world.qc_evaluate(deliverable_id)
        world.remediate(deliverable_id)
        world.qc_submit(
            deliverable_id,
            measured_integrated_lufs=-24.20,
            measured_true_peak_dbtp=-3.00,
            me_stems_present=False,
        )
        world.qc_evaluate(deliverable_id)

        reports = world.qc_reports(deliverable_id)
        assert_unpaginated_list(reports)
        assert len(reports) == 2
        assert [report["round"] for report in reports] == [0, 1]

        historical, current = reports
        assert historical["verdict"] == QC_VERDICT_FAIL
        assert historical["rejection_codes"] == ["LOUDNESS_OUT_OF_TOLERANCE"]
        assert_decimal(historical["measured_integrated_lufs"], -25.00)
        assert_decimal(historical["deviation_lu"], 1.00)
        assert current["verdict"] == QC_VERDICT_PASS
        for report in reports:
            assert_immutable_record(report)
            assert report["deliverable_id"] == deliverable_id


class TestLoudnessAndTruePeakBoundaries:
    """Both QC comparisons are strict, so the boundary value passes."""

    def _spec_environment(self, world):
        return world.prepared_environment(
            spec={
                "spec_label": "Theatrical Boundary Spec",
                "target_lufs": -24.00,
                "tolerance_lu": 0.50,
                "true_peak_max_dbtp": -2.00,
                "requires_me_stems": False,
                "max_remediation_rounds": 2,
            }
        )

    def test_a_deviation_one_hundredth_beyond_tolerance_is_rejected(self, world):
        """0.51 against a 0.50 tolerance fails on the loudness code alone.

        PRD §3.7: "`LOUDNESS_OUT_OF_TOLERANCE` is contributed when `deviation_lu` is
        **strictly greater** than the specification's `tolerance_lu` — a deviation
        exactly equal to the tolerance passes."

        Design: Difficulty/boundary_precision_check/loudness_deviation_exactly_at_tolerance_and_true_peak_exactly_at_max_pass
        """
        environment = self._spec_environment(world)
        deliverable_id = environment["deliverable"]["id"]

        world.qc_submit(
            deliverable_id,
            measured_integrated_lufs=-24.51,
            measured_true_peak_dbtp=-2.00,
            me_stems_present=False,
        )
        report = world.qc_evaluate(deliverable_id)

        assert_decimal(report["deviation_lu"], 0.51)
        assert report["verdict"] == QC_VERDICT_FAIL
        assert report["rejection_codes"] == ["LOUDNESS_OUT_OF_TOLERANCE"]
        assert world.get_deliverable(deliverable_id)["status"] == "QC_REJECTED"

    def test_a_deviation_exactly_at_tolerance_and_a_peak_exactly_at_the_ceiling_pass(self, world):
        """0.50 LU and -2.00 dBTP are both admissible, so the round passes.

        PRD §3.7: "`TRUE_PEAK_EXCEEDED` is contributed when `measured_true_peak_dbtp` is
        **strictly greater** than the specification's `true_peak_max_dbtp` — a peak
        exactly at the ceiling passes."

        Design: Difficulty/boundary_precision_check/loudness_deviation_exactly_at_tolerance_and_true_peak_exactly_at_max_pass
        """
        environment = self._spec_environment(world)
        deliverable_id = environment["deliverable"]["id"]

        world.qc_submit(
            deliverable_id,
            measured_integrated_lufs=-24.51,
            measured_true_peak_dbtp=-2.00,
            me_stems_present=False,
        )
        world.qc_evaluate(deliverable_id)
        world.remediate(deliverable_id)
        world.qc_submit(
            deliverable_id,
            measured_integrated_lufs=-24.50,
            measured_true_peak_dbtp=-2.00,
            me_stems_present=False,
        )
        report = world.qc_evaluate(deliverable_id)

        assert report["round"] == 1
        assert_decimal(report["deviation_lu"], 0.50)
        assert report["verdict"] == QC_VERDICT_PASS
        assert report["rejection_codes"] == []
        assert "TRUE_PEAK_EXCEEDED" not in report["rejection_codes"]
        assert_decimal(report["measured_true_peak_dbtp"], -2.00)

        deliverable = world.get_deliverable(deliverable_id)
        assert deliverable["status"] == "QC_PASSED"
        assert deliverable["remediation_round"] == 1
        assert_decimal(deliverable["deviation_lu"], 0.50)


class TestQcSubmitRequiresACompletedSession:
    """QC cannot start until the stage session it was cut from is closed."""

    def _confirmed_only(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        spec = world.platform_spec(platform="THEATRICAL")
        stage = world.mix_stage(hourly_rate_cents=120000)
        mixer = world.mixer(certified_platforms=["THEATRICAL"])
        project = world.locked_project()
        package = world.conformed_package(project["id"], cue_durations=(120,))
        booking = world.booking(
            project["id"], stage["id"], mixer["id"], booking_type="FINAL_MIX", platform="THEATRICAL"
        )
        world.confirm_booking(booking["id"], mixer["id"])
        deliverable = world.deliverable(project["id"], spec["id"], package["id"], booking["id"])
        return project, mixer, booking, deliverable

    def test_submission_against_a_merely_confirmed_booking_is_refused(self, world, api):
        """A prepared deliverable cannot be measured before its session closes.

        PRD §2.11: "the referenced mix stage booking's `status` is not `COMPLETED`, on QC
        submission: `ERR_BOOKING_NOT_COMPLETED`, 409."

        Design: Difficulty/cross_entity_state_dependency/qc_submit_gated_on_booking_completion_state
        """
        _project, _mixer, booking, deliverable = self._confirmed_only(world)
        assert world.get_booking(booking["id"])["status"] == "CONFIRMED"

        response = api.qc_submit(
            deliverable["id"],
            f.qc_submit_payload(
                measured_integrated_lufs=-24.20,
                measured_true_peak_dbtp=-3.00,
                me_stems_present=False,
            ),
            QC_ONE_HEADERS,
        )
        validate_error(response, ERR_BOOKING_NOT_COMPLETED, 409)

        untouched = world.get_deliverable(deliverable["id"])
        assert untouched["status"] == "PREPARED"
        assert untouched["measured_integrated_lufs"] is None
        assert untouched["measured_true_peak_dbtp"] is None
        assert untouched["deviation_lu"] is None

    def test_an_open_session_still_blocks_and_completion_unblocks_the_same_payload(self, world, api):
        """IN_PROGRESS is refused too; the byte-identical third attempt is accepted.

        PRD §3.6: "**Closing** the stage moves the booking `IN_PROGRESS → COMPLETED` and
        stamps `actual_end_utc` with the logical clock's current instant."

        Design: Difficulty/cross_entity_state_dependency/qc_submit_gated_on_booking_completion_state
        """
        project, mixer, booking, deliverable = self._confirmed_only(world)
        measurements = f.qc_submit_payload(
            measured_integrated_lufs=-24.20,
            measured_true_peak_dbtp=-3.00,
            me_stems_present=False,
        )

        world.set_clock("2026-09-14T10:00:00Z")
        world.start_booking(booking["id"], mixer["id"])
        validate_error(
            api.qc_submit(deliverable["id"], measurements, QC_ONE_HEADERS),
            ERR_BOOKING_NOT_COMPLETED,
            409,
        )
        assert world.get_deliverable(deliverable["id"])["status"] == "PREPARED"

        world.set_clock("2026-09-14T13:00:00Z")
        closed = world.complete_booking(booking["id"], mixer["id"])
        assert closed["status"] == "COMPLETED"
        assert_decimal(closed["billable_hours_final"], 3.00)
        assert closed["final_cost_cents"] == 360000

        submitted = world.qc_submit(
            deliverable["id"],
            measured_integrated_lufs=-24.20,
            measured_true_peak_dbtp=-3.00,
            me_stems_present=False,
        )
        assert submitted["status"] == "QC_SUBMITTED"
        assert_decimal(submitted["deviation_lu"], 0.20)

        report = world.qc_evaluate(deliverable["id"])
        assert report["round"] == 0
        assert report["verdict"] == QC_VERDICT_PASS
        assert world.get_deliverable(deliverable["id"])["status"] == "QC_PASSED"
        assert_decimal(world.get_project(project["id"])["stage_hours_consumed"], 3.00)
