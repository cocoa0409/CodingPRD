"""Queue A — boundary_precision_check: inclusive boundaries on two different
metrics (elapsed seconds since the last scored delivery; CE hours at the
component minimum).
"""
from test_helpers import (
    cat_fail_responses,
    create_approved_exam_application,
    schedule_attempt,
    setup_scored_attempt,
    setup_submitted_recert,
)


def test_retake_wait_exactly_15_days_allowed(api):
    """PRD §3.4: "If at least one attempt has already been consumed on the
    basis, the new window's start must fall at least fifteen days after the
    most recent scored attempt's `delivered_at` — equality allowed — otherwise
    `ERR_RETAKE_WAIT_ACTIVE`."
    PRD §3.4: "A scheduled attempt records its `attempt_number`, one more than
    the basis's consumed count at scheduling".

    The last delivery was at 2026-09-03T12:00:00Z; a new window opening at
    exactly 2026-09-18T12:00:00Z satisfies the inclusive fifteen-day boundary.

    Design: Difficulty/boundary_precision_check/retake_wait_exactly_15_days_allowed
    """
    ctx = setup_scored_attempt(responses_payload=cat_fail_responses())
    application = create_approved_exam_application(
        ctx["candidate"]["id"], ctx["level"]["id"], ctx["completion_record"]["id"],
    )
    attempt = schedule_attempt(
        ctx["candidate"]["id"], application["att_id"],
        "2026-09-18T12:00:00Z", "2026-09-19T00:00:00Z",
    )
    assert attempt["status"] == "SCHEDULED"
    assert attempt["attempt_number"] == 2, (
        f"one attempt consumed on the basis, got attempt_number {attempt['attempt_number']}"
    )


def test_ce_component_exact_minimum_passes(api):
    """PRD §3.6: "Sufficiency under the `NCCP` model is checked in a fixed
    order, first failure wins: credited national hours against
    `ce_national_min_hours`, then local against `ce_local_min_hours`, then
    individual against `ce_individual_min_hours` — any shortfall rejected with
    `ERR_CE_COMPONENT_SHORTFALL` — and finally the credited total against
    `ce_total_hours` (`ERR_CE_TOTAL_SHORTFALL`)."
    PRD §2.6: "Where a boundary is described as inclusive, an instant exactly on
    the boundary satisfies it. Hour quantities — remedial education and
    continuing education — are recorded in half-hour increments and compared
    exactly."

    Each component lands exactly on its minimum (N 20, L 10, I 10; total 40):
    the portfolio is sufficient and the submission lands in SUBMITTED.

    Design: Difficulty/boundary_precision_check/ce_component_exact_minimum_passes
    """
    ctx = setup_submitted_recert()
    application = ctx["recert_application"]
    assert application["national_credited_hours"] == 20, (
        f"exactly 20.0 national hours satisfy >= 20, got {application['national_credited_hours']}"
    )
    assert application["local_credited_hours"] == 10
    assert application["individual_credited_hours"] == 10
    assert application["total_credited_hours"] == 40
    assert application["status"] == "SUBMITTED"
