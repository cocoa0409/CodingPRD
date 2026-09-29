"""State machines with parallel axes, backward edges and self-loops.

A data packet carries two independent status axes that must not be collapsed into
one, and a quantification run re-enters the same states through two different
triggers while the verification underneath it cycles on a self-loop.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers.assertions import assert_acres, assert_pct, assert_rate, assert_tonnes
from test_helpers.constants import (
    COMPLETENESS_COMPLETE,
    COMPLETENESS_PARTIAL,
    METHOD_MODEL,
    OPINION_ADVERSE,
    OPINION_PENDING,
    OPINION_POSITIVE,
    OPINION_QUALIFIED,
    QC_FLAGGED,
    QC_PASSED,
    QC_PENDING,
    RUN_DRAFT,
    RUN_REJECTED,
    RUN_SUBMITTED,
    RUN_VERIFIED,
)
from test_helpers.test_users import ADMIN_HEADERS


def test_quality_decision_never_touches_the_coverage_axis(scenario):
    """A telemetry packet arrives scoring 96.00, complete on coverage and pending on
    quality, and flagging it moves only the quality axis.

    PRD §3.5: "Under both decisions the `completeness_status` axis is neither recomputed
    nor changed."

    Design: Difficulty/non_linear_state_machine/data_packet_parallel_qc_and_completeness_axes
    """
    scenario.active_enrollment()

    packet = scenario.file_packet()

    assert_pct(packet["qc_score"], 96.00)
    assert packet["qc_status"] == QC_PENDING
    assert packet["completeness_status"] == COMPLETENESS_COMPLETE
    assert packet["correction_count"] == 0

    flagged = scenario.qc_packet(packet["id"], "FLAG")

    assert flagged["qc_status"] == QC_FLAGGED
    assert flagged["completeness_status"] == COMPLETENESS_COMPLETE
    assert_pct(flagged["qc_score"], 96.00)


def test_correction_walks_the_quality_axis_backwards_and_re_derives_coverage(scenario):
    """A correction dropping coverage to 80.00 returns the quality axis to pending, flips
    the coverage axis to partial and re-scores to 90.00; passing then leaves it partial.

    PRD §3.5: "The `qc_score` is then recomputed from the corrected figures, the
    `completeness_status` axis is re-derived from the new `coverage_pct` and may move in
    either direction, `correction_count` increases by one, `flag_reason` is cleared to
    null, and `qc_status` returns from `FLAGGED` to `PENDING`."

    Design: Difficulty/non_linear_state_machine/data_packet_parallel_qc_and_completeness_axes
    """
    scenario.active_enrollment()
    packet = scenario.file_packet()
    scenario.qc_packet(packet["id"], "FLAG")

    corrected = get_success_data(
        scenario.api.correct_data_packet(packet["id"], {"coverage_pct": 80.00}, ADMIN_HEADERS)
    )

    assert corrected["qc_status"] == QC_PENDING
    assert corrected["completeness_status"] == COMPLETENESS_PARTIAL
    assert_pct(corrected["coverage_pct"], 80.00)
    assert corrected["correction_count"] == 1
    assert_pct(corrected["qc_score"], 90.00)
    assert corrected["flag_reason"] is None
    # Fields the correction omitted keep their filed values rather than being nulled.
    assert_acres(corrected["reported_acres"], 1000.00)
    assert_rate(corrected["measured_value"], 0.3000)

    passed = scenario.qc_packet(packet["id"], "PASS")

    assert passed["qc_status"] == QC_PASSED
    assert passed["completeness_status"] == COMPLETENESS_PARTIAL


def test_adverse_opinion_rejects_the_run_and_revision_recomputes_on_re_entry(scenario):
    """An adverse opinion drives the submitted run to rejected, and revision walks it back
    to draft, counts the revision and re-runs the calculation over the same packet set.

    PRD §3.6: "A run driven to `REJECTED` by an adverse opinion may be reopened by a
    `ProgramAdmin`: revision moves it `REJECTED → DRAFT`, increases `revision_count` by
    one, and re-runs the whole computation above against the quality-passed packet set as
    it now stands."

    Design: Difficulty/non_linear_state_machine/run_rejected_revise_qualified_resample_cycle
    """
    scenario.active_enrollment()
    scenario.passed_packet()
    scenario.create_run(METHOD_MODEL)
    scenario.submit_run()
    assert scenario.run["revision_count"] == 0
    scenario.accredit_body()
    first = scenario.commission_verification(sample_pct=20.00)

    opined = scenario.opine(OPINION_ADVERSE, findings_note="boundary mismatch on the north strip")

    assert opined["opinion"] == OPINION_ADVERSE
    assert scenario.reload_run()["status"] == RUN_REJECTED

    revised = get_success_data(
        scenario.api.revise_quantification_run(scenario.run_id, None, ADMIN_HEADERS)
    )

    assert revised["status"] == RUN_DRAFT
    assert revised["revision_count"] == 1
    assert_tonnes(revised["net_removals_t"], 283.360)
    assert get_success_data(scenario.api.get_verification(first["id"], ADMIN_HEADERS))[
        "opinion"] == OPINION_ADVERSE


def test_qualified_opinion_is_a_self_loop_that_resampling_reopens(scenario):
    """A qualified opinion leaves the resubmitted run where it is, a resample returns the
    verification to pending with the fresh sample, and only the positive opinion advances.

    PRD §3.6: "A `QUALIFIED` opinion moves the verification `PENDING → QUALIFIED` and
    leaves the run exactly where it was, still `SUBMITTED`, with issuance still blocked
    pending a resample."

    Design: Difficulty/non_linear_state_machine/run_rejected_revise_qualified_resample_cycle
    """
    scenario.active_enrollment()
    scenario.passed_packet()
    scenario.create_run(METHOD_MODEL)
    scenario.submit_run()
    scenario.accredit_body()
    first = scenario.commission_verification(sample_pct=20.00)
    scenario.opine(OPINION_ADVERSE)
    get_success_data(scenario.api.revise_quantification_run(scenario.run_id, None, ADMIN_HEADERS))
    scenario.submit_run()
    second = scenario.commission_verification(
        sample_pct=25.00, site_visit_start="2027-01-11", site_visit_end="2027-01-15"
    )

    qualified = scenario.opine(
        OPINION_QUALIFIED, findings_note="sample too thin on the east headland"
    )

    assert qualified["opinion"] == OPINION_QUALIFIED
    assert scenario.reload_run()["status"] == RUN_SUBMITTED

    resampled = get_success_data(
        scenario.api.resample_verification(
            second["id"],
            {"sample_pct": 40.00, "site_visit_start": "2027-02-01",
             "site_visit_end": "2027-02-04"},
            scenario.verifier_auth,
        )
    )

    assert resampled["opinion"] == OPINION_PENDING
    assert_pct(resampled["sample_pct"], 40.00)
    assert resampled["resample_count"] == 1

    final = scenario.opine(OPINION_POSITIVE, verification_id=second["id"])

    assert final["opinion"] == OPINION_POSITIVE
    run = scenario.reload_run()
    assert run["status"] == RUN_VERIFIED
    assert run["revision_count"] == 1
    stale = get_success_data(scenario.api.get_verification(first["id"], ADMIN_HEADERS))
    assert stale["opinion"] == OPINION_ADVERSE
    assert stale["resample_count"] == 0
