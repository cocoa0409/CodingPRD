"""Difficulty queue: priority_pair_validation_conflict.

When one request violates two rules, the PRD's validation ladder (§2.7)
pins which error the caller sees.
"""
from test_helpers import (
    ApiErrorId,
    ELEVEN_WORDS,
    FIVE_WORDS,
    PAST_DUE_AT,
    add_argument,
    add_measure_contest,
    build_issued_scenario,
    build_locked_candidate_contest,
    create_edition,
    create_measure,
    fresh_league,
    get_edition,
    get_shell,
    get_success_data,
    make_answer,
    move_to_questionnaire_phase,
    review_measure,
    set_clock,
    submit_answers,
    resubmit_answers,
    validate_error,
    validate_success,
)


def _closed_questionnaire_scenario(api, *, word_limit=None):
    sc = build_issued_scenario(api, word_limit=word_limit)
    ctx = sc["ctx"]
    set_clock(api, PAST_DUE_AT)
    get_success_data(
        api.close_questionnaire(sc["questionnaire"]["id"], ctx["editor_h"])
    )
    return sc


def test_closed_questionnaire_state_beats_past_due_temporal_on_submit(api):
    """PRD §2.7: "on a candidate submission or resubmission, a questionnaire
    that has already been `CLOSED` is rejected with
    `ERR_QUESTIONNAIRE_NOT_ACCEPTING_SUBMISSIONS` even when the submission
    window has also expired — the state check is evaluated before the
    temporal one, so state beats temporal."

    Design: Difficulty/priority_pair_validation_conflict/closed_questionnaire_state_beats_past_due_temporal
    """
    sc = _closed_questionnaire_scenario(api)
    filing = sc["filings"][0]
    # Both failures hold: questionnaire CLOSED and clock past due_at.
    resp = submit_answers(
        api, sc["questionnaire"]["id"], filing["id"], [make_answer(1, FIVE_WORDS)]
    )
    validate_error(resp, ApiErrorId.ERR_QUESTIONNAIRE_NOT_ACCEPTING_SUBMISSIONS)
    assert resp.status_code == 409


def test_closed_questionnaire_state_beats_past_due_temporal_on_resubmit(api):
    """PRD §2.7: "on a candidate submission or resubmission, a questionnaire
    that has already been `CLOSED` is rejected with
    `ERR_QUESTIONNAIRE_NOT_ACCEPTING_SUBMISSIONS` even when the submission
    window has also expired — the state check is evaluated before the
    temporal one, so state beats temporal."

    Design: Difficulty/priority_pair_validation_conflict/closed_questionnaire_state_beats_past_due_temporal
    """
    sc = build_issued_scenario(api, word_limit=10)
    ctx = sc["ctx"]
    filing = sc["filings"][0]
    # In-window over-limit submission lands the shell in OVER_LIMIT_RETURNED.
    first = submit_answers(
        api, sc["questionnaire"]["id"], filing["id"],
        [make_answer(1, ELEVEN_WORDS)],
    )
    shell = validate_success(first, expected_status=201)
    assert shell["status"] == "OVER_LIMIT_RETURNED"

    set_clock(api, PAST_DUE_AT)
    get_success_data(
        api.close_questionnaire(sc["questionnaire"]["id"], ctx["editor_h"])
    )
    resp = resubmit_answers(api, shell["id"], filing["id"],
                            [make_answer(1, FIVE_WORDS)])
    validate_error(resp, ApiErrorId.ERR_QUESTIONNAIRE_NOT_ACCEPTING_SUBMISSIONS)
    assert resp.status_code == 409


def _cycle_with_locked_contest_and_pending_review(api, *, reviewers=()):
    """Cycle carrying a LOCKED candidate contest (pinned empty
    questionnaire) and a measure contest whose measure sits
    IN_NEUTRALITY_REVIEW."""
    ctx = fresh_league(api, reviewers=reviewers)
    build_locked_candidate_contest(api, ctx, filings=())
    mcontest = add_measure_contest(api, ctx)
    move_to_questionnaire_phase(api, ctx, mcontest["id"], at="2026-10-03T00:00:00Z")
    measure = create_measure(api, ctx, mcontest["id"])
    add_argument(api, ctx, measure["id"], side="PRO", credit="Yes on R")
    add_argument(api, ctx, measure["id"], side="CON", credit="No on R")
    get_success_data(api.submit_measure_for_review(measure["id"], ctx["editor_h"]))
    edition = create_edition(api, ctx, language_code="ES", channel="WEB")
    return ctx, measure, edition


def test_neutrality_outstanding_beats_language_constraint(api):
    """PRD §2.7: "Compliance posture (`ERR_NEUTRALITY_REVIEW_OUTSTANDING`)
    comes next, then the temporal rules (`ERR_FILING_DEADLINE_PASSED`,
    `ERR_FILING_STILL_OPEN`, `ERR_SUBMISSION_WINDOW_CLOSED`,
    `ERR_CLOSE_BEFORE_DEADLINE`, `ERR_FORUM_TIME_OVERLAP`,
    `ERR_MODERATOR_BUFFER_VIOLATION`, `ERR_FORUM_NOT_CONCLUDED`), and
    finally the uniqueness and business constraints (`ERR_DUPLICATE_FIPS`,
    `ERR_DUPLICATE_FILING_REFERENCE`, `ERR_DUPLICATE_QUESTIONNAIRE`,
    `ERR_DUPLICATE_MEASURE`, `ERR_DUPLICATE_REVIEW_THIS_ROUND`,
    `ERR_CONTEST_KIND_MISMATCH`, `ERR_MISSING_PRO_OR_CON`,
    `ERR_FORUM_QUORUM_NOT_MET`, `ERR_QUESTION_CAP_REACHED`,
    `ERR_LANGUAGE_UNSUPPORTED`, `ERR_ACCESSIBILITY_GRADE_EXCEEDED`,
    `ERR_STALE_SNAPSHOT`, `ERR_CONTESTS_NOT_LOCKED`,
    `ERR_UNRESOLVED_INCIDENTS_EXIST`, `ERR_NO_DISTRIBUTED_EDITION`)."

    Design: Difficulty/priority_pair_validation_conflict/neutrality_outstanding_safety_beats_language_constraint
    """
    ctx, _measure, edition = _cycle_with_locked_contest_and_pending_review(api)
    # Both failures hold: a measure IN_NEUTRALITY_REVIEW, and ES not in the
    # jurisdiction's supported_language_codes [EN].
    resp = api.transition_edition(edition["id"], {"to": "READY"}, ctx["editor_h"])
    validate_error(resp, ApiErrorId.ERR_NEUTRALITY_REVIEW_OUTSTANDING)
    assert resp.status_code == 422
    assert get_edition(api, ctx, edition["id"])["status"] == "ASSEMBLING"


def test_language_constraint_surfaces_once_review_completes(api):
    """PRD §3.6: "The edition's `language_code` must appear in the
    `supported_language_codes` of every jurisdiction of the cycle
    (`ERR_LANGUAGE_UNSUPPORTED`)."

    Design: Difficulty/priority_pair_validation_conflict/neutrality_outstanding_safety_beats_language_constraint
    """
    ctx, measure, edition = _cycle_with_locked_contest_and_pending_review(
        api, reviewers=("Rhea Reviewer", "Ray ReviewerTwo")
    )
    # Cure the safety failure: two distinct NEUTRAL reviewers approve.
    get_success_data(review_measure(api, ctx, measure["id"], 0), expected_status=201)
    get_success_data(review_measure(api, ctx, measure["id"], 1), expected_status=201)
    resp = api.transition_edition(edition["id"], {"to": "READY"}, ctx["editor_h"])
    validate_error(resp, ApiErrorId.ERR_LANGUAGE_UNSUPPORTED)
    assert resp.status_code == 422
    assert get_edition(api, ctx, edition["id"])["status"] == "ASSEMBLING"
