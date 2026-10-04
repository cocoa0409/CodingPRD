"""The award decision fork, score-threshold boundary, appeal loop with
round-scoped reviewer exclusion, and decide/appeal state gates
(PRD §3.6, §2.1).
"""

import pytest

from test_helpers import (
    ApiErrorId,
    AWARDS_DIRECTOR,
    apply_for_reviewer,
    create_assignment,
    create_draft_submission,
    create_eligible_reviewer,
    create_government,
    create_member,
    decide_submission,
    file_round_findings,
    make_government_contact_headers,
    make_reviewer_headers,
    refresh_submission,
    appeal_submission,
    set_logical_clock,
    setup_decided_submission,
    setup_decision_ready_submission,
    setup_submission_with_review_round,
    setup_submitted_submission,
    submit_submission,
    validate_error,
    validate_success,
)


def test_award_score_variants_diverge_across_programs(api):
    """PRD §3.6: "The decision first computes `final_score` from the three
    current-round findings. The base is the mean of the three findings'
    `weighted_score` values, rounded half-up to 2 decimal places. For a
    `FINANCIAL_REPORTING` submission the final score is exactly this base. For
    a `BUDGET_PRESENTATION` submission, when the round's three findings
    collectively contain zero `MAJOR` and zero `MINOR` comments, a
    clean-presentation bonus of 1.00 is added after the mean has been rounded,
    and the result is then capped at 100.00 — the final score is the lesser of
    100.00 and the base plus 1.00; when any comment of either severity exists,
    the final score is the base alone."

    Design: Difficulty/dual_variant_calc/award_score_variants_diverge_across_programs
    """
    # Identical per-finding weighted scores (85.00 each, zero comments) under
    # both programs; only the program variant may differ in the final score.
    fr_bundle = setup_decision_ready_submission(
        api, program_type="FINANCIAL_REPORTING", scores=85
    )
    budget_bundle = setup_decision_ready_submission(
        api, program_type="BUDGET_PRESENTATION", scores=85
    )
    for finding in fr_bundle["findings"] + budget_bundle["findings"]:
        assert finding["weighted_score"] == pytest.approx(85.00, abs=1e-9)

    fr_decided = decide_submission(api, fr_bundle["submission"]["id"])
    budget_decided = decide_submission(api, budget_bundle["submission"]["id"])

    assert fr_decided["final_score"] == pytest.approx(85.00, abs=1e-9)
    assert budget_decided["final_score"] == pytest.approx(86.00, abs=1e-9)
    assert budget_decided["final_score"] - fr_decided["final_score"] == pytest.approx(
        1.00, abs=1e-9
    ), "the clean-round bonus diverges the variants by exactly 1.00"
    assert fr_decided["status"] == "DECIDED_AWARDED"
    assert budget_decided["status"] == "DECIDED_AWARDED"


def test_decide_threshold_exact_boundary(api):
    """PRD §3.6: "The decision then forks deterministically. When the computed
    `final_score` is at least the pinned checklist's `pass_score` and the
    `major_deficiency_total` is zero, the submission is decided
    `DECIDED_AWARDED`: `final_score` is stored, `decided_at` and
    `conferred_at` are stamped with the logical clock, `award_conferred`
    becomes true, the cycle's `conferred_count` increments, and the
    government's `lifetime_award_count` increments, with the `version` of the
    submission, the cycle, and the government each advancing by one.
    `DECIDED_AWARDED` is terminal."
    PRD §3.6: "Otherwise the submission is decided `DECIDED_DENIED`:
    `final_score` is still computed and stored, `decided_at` is stamped,
    `required_improvements` is compiled as the texts of every `MAJOR` comment
    from the current round's findings in the order the findings were
    submitted, `award_conferred` stays false and the government's lifetime
    count is untouched, and the submission's `version` increments."

    Design: Difficulty/boundary_precision_check/decide_threshold_exact_boundary
    """
    set_logical_clock(api, "2026-09-15T00:00:00Z")

    # Submission A: weighted findings 85.00 / 86.00 / 84.00 -> final exactly
    # 85.00 == pass_score -> the >= boundary is inclusive, AWARDED.
    bundle_a = setup_submission_with_review_round(api)
    criteria = bundle_a["checklist"]["criteria"]
    file_round_findings(
        api, bundle_a["assignments"], criteria,
        scores=[[90, 80], [88, 84], [92, 76]],
    )

    # Submission B (same cycle, another government): 85.00 / 86.00 / 83.97
    # -> final 84.99, one cent below the threshold -> DENIED.
    other_gov = create_government(api)
    submission_b = create_draft_submission(api, other_gov["id"], bundle_a["cycle"]["id"])
    submit_submission(api, submission_b["id"], other_gov["id"])
    assignments_b = [
        create_assignment(api, submission_b["id"]) for _ in range(3)
    ]
    for assignment in assignments_b:
        api_call = api.accept_review_assignment(
            assignment["id"],
            headers=make_reviewer_headers(assignment["reviewer_id"]),
        )
        validate_success(api_call)
    file_round_findings(
        api, assignments_b, criteria,
        scores=[[90, 80], [88, 84], [87.94, 80]],
    )

    decided_a = decide_submission(api, bundle_a["submission"]["id"])
    decided_b = decide_submission(api, submission_b["id"])

    assert decided_a["final_score"] == pytest.approx(85.00, abs=1e-9)
    assert decided_a["status"] == "DECIDED_AWARDED"
    assert decided_a["award_conferred"] is True
    assert decided_a["conferred_at"].startswith("2026-09-15T00:00:00")

    assert decided_b["final_score"] == pytest.approx(84.99, abs=1e-9)
    assert decided_b["status"] == "DECIDED_DENIED"
    assert decided_b["award_conferred"] is False
    assert decided_b["conferred_at"] is None


def test_submission_decide_fork_then_appeal_cycle(api):
    """PRD §3.6: "Otherwise the submission is decided `DECIDED_DENIED`:
    `final_score` is still computed and stored, `decided_at` is stamped,
    `required_improvements` is compiled as the texts of every `MAJOR` comment
    from the current round's findings in the order the findings were
    submitted, `award_conferred` stays false and the government's lifetime
    count is untouched, and the submission's `version` increments."
    PRD §3.6: "An accepted appeal moves the submission to `APPEALED`,
    increments `appeal_round` by one, resets `provisional_score` to null and
    `major_deficiency_total` to zero, and cancels every assignment of the
    superseded round still sitting in `OFFERED` or `ACCEPTED` — each cancelled
    assignment moves to `CANCELLED` and its reviewer's `open_assignment_count`
    decrements — while the submission's `version` increments. The cycle then
    repeats: a fresh blind assignment round under the new `appeal_round`
    returns the submission to `UNDER_REVIEW` on its first assignment, with
    every reviewer from every prior round excluded from selection by the
    any-round rule of §3.5."

    Design: Difficulty/non_linear_state_machine/submission_decide_fork_then_appeal_cycle
    """
    bundle = setup_decided_submission(
        api, awarded=False, major_comment_text="Missing note disclosure"
    )
    denied = bundle["submission"]

    assert denied["status"] == "DECIDED_DENIED"
    assert denied["final_score"] == pytest.approx(80.00, abs=1e-9)
    assert denied["major_deficiency_total"] == 1
    assert denied["required_improvements"] == ["Missing note disclosure"]
    assert denied["award_conferred"] is False

    # A fourth reviewer is the whole round-2 candidate pool: every round-1
    # reviewer is excluded by the any-appeal-round rule.
    late_reviewer = create_eligible_reviewer(api)

    appealed = appeal_submission(api, denied)
    assert appealed["status"] == "APPEALED"
    assert appealed["appeal_round"] == 2
    assert appealed["provisional_score"] is None
    assert appealed["major_deficiency_total"] == 0

    round_two = create_assignment(api, denied["id"])
    assert round_two["reviewer_id"] == late_reviewer["id"]
    assert round_two["reviewer_alias"] == "R2-1"
    assert round_two["appeal_round"] == 2

    assert refresh_submission(api, denied["id"])["status"] == "UNDER_REVIEW"


def test_decide_from_under_review_returns_findings_incomplete(api):
    """PRD §3.6: "Attempted while the submission is still `UNDER_REVIEW` —
    that is, with fewer than three current-round findings filed — it is
    rejected with `ERR_FINDINGS_INCOMPLETE`; attempted from `DRAFT` or
    `SUBMITTED` it is rejected with `ERR_SUBMISSION_STATE_INVALID`."

    Design: Corner/state_machines/decide_from_under_review_returns_findings_incomplete
    """
    bundle = setup_submission_with_review_round(api, num_reviewers=1, accept=False)
    submission_id = bundle["submission"]["id"]
    assert refresh_submission(api, submission_id)["status"] == "UNDER_REVIEW"

    resp = api.decide_report_submission(submission_id, headers=AWARDS_DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_FINDINGS_INCOMPLETE)

    after = refresh_submission(api, submission_id)
    assert after["status"] == "UNDER_REVIEW"
    assert after["final_score"] is None


def test_appeal_from_decided_awarded_returns_state_invalid(api):
    """PRD §3.6: "`DECIDED_AWARDED` is terminal."
    PRD §3.6: "the `GovernmentContact` who owns the submission (else
    `ERR_NOT_RESOURCE_OWNER`) may appeal only from `DECIDED_DENIED` (else
    `ERR_SUBMISSION_STATE_INVALID`)"

    Design: Corner/state_machines/appeal_from_decided_awarded_returns_state_invalid
    """
    bundle = setup_decided_submission(api, awarded=True)
    awarded = bundle["submission"]
    assert awarded["status"] == "DECIDED_AWARDED"
    assert awarded["award_conferred"] is True

    resp = api.appeal_report_submission(
        awarded["id"],
        headers=make_government_contact_headers(awarded["government_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SUBMISSION_STATE_INVALID)
    assert refresh_submission(api, awarded["id"])["status"] == "DECIDED_AWARDED"


def test_appeal_after_30_days_returns_appeal_window_closed(api):
    """PRD §3.6: "A denied government may appeal within thirty days: the
    `GovernmentContact` who owns the submission (else
    `ERR_NOT_RESOURCE_OWNER`) may appeal only from `DECIDED_DENIED` (else
    `ERR_SUBMISSION_STATE_INVALID`) and only while the logical clock is no
    later than `decided_at` plus thirty days, after which the request is
    rejected with `ERR_APPEAL_WINDOW_CLOSED`."

    Design: Corner/state_machines/appeal_after_30_days_returns_appeal_window_closed
    """
    bundle = setup_decided_submission(api, awarded=False)
    denied = bundle["submission"]
    assert denied["status"] == "DECIDED_DENIED"
    assert denied["decided_at"].startswith("2026-09-15T00:00:00")

    # 2026-09-15 + 30 days = 2026-10-15 is the last valid day; this is day 31.
    set_logical_clock(api, "2026-10-16T00:00:00Z")
    resp = api.appeal_report_submission(
        denied["id"],
        headers=make_government_contact_headers(denied["government_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)

    after = refresh_submission(api, denied["id"])
    assert after["status"] == "DECIDED_DENIED"
    assert after["appeal_round"] == 1


def test_reviewer_cannot_decide_forbidden(api):
    """PRD §2.1: "Each operation declares the roles authorized to call it (§4);
    a caller whose role is not on that operation's list is rejected with
    `ERR_FORBIDDEN_ROLE`."
    PRD §4 (endpoint table, POST /gfoa/report-submissions/{id}/decide):
    "Decide the award from `DECISION_READY`" — authorized role:
    `AwardsDirector` only.

    Design: Corner/rbac/reviewer_cannot_decide_forbidden
    """
    bundle = setup_submitted_submission(api)
    member = create_member(api)
    employer = create_government(api)
    profile = apply_for_reviewer(api, member["id"], employer["id"])

    resp = api.decide_report_submission(
        bundle["submission"]["id"],
        headers=make_reviewer_headers(profile["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
