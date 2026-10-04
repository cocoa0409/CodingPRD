"""Difficulty queue: transitive_cascade.

One trigger (incident substantiation, filing withdrawal) fires a chain of
caused state changes across entity boundaries; each link is asserted.
"""
import pytest

from test_helpers import (
    TEN_WORDS,
    advance_contest,
    assert_instant_equals,
    build_issued_scenario,
    build_measure_pipeline,
    get_contest,
    get_measure,
    get_questionnaire,
    get_shell,
    get_success_data,
    make_answer,
    report_incident,
    submit_answers,
    substantiate_incident,
    validate_success,
)


def _approved_measure_at_guide_ready(api):
    sc = build_measure_pipeline(api, approve=True)
    ctx = sc["ctx"]
    contest = advance_contest(api, ctx, sc["contest"]["id"], "GUIDE_READY")
    return ctx, contest, sc["measure"]


def test_incident_substantiation_suspends_remands_reverts(api):
    """PRD §3.8: "First, the volunteer moves from `ACTIVE` to the terminal
    `SUSPENDED`. Second, every ballot measure that volunteer drafted which
    currently sits in `DRAFTING`, `IN_NEUTRALITY_REVIEW`, or
    `APPROVED_FOR_GUIDE` is quarantined to `REMANDED`, and every forum that
    volunteer moderates in `PLANNED` or `CONFIRMED` is cancelled."
    PRD §3.8: "Third, each contest whose measure was quarantined and which
    currently sits in `GUIDE_READY` or `LOCKED` reverts to
    `QUESTIONNAIRE_PHASE`, incrementing that contest's `version`;
    candidate-race contests are never touched by this cascade."

    Design: Difficulty/transitive_cascade/incident_substantiation_suspends_remands_reverts
    """
    ctx, contest, measure = _approved_measure_at_guide_ready(api)
    editor = ctx["editor"]
    contest_version_before = contest["version"]

    incident = report_incident(
        api, ctx, editor["id"],
        description="Editor endorsed a candidate at a chapter meeting.",
    )
    resolved = substantiate_incident(api, ctx, incident["id"])
    assert resolved["status"] == "SUBSTANTIATED"
    assert_instant_equals(resolved["resolved_at"], "2026-09-16T00:00:00Z",
                          "resolved_at")

    # Link 1: the drafter is suspended.
    volunteer = get_success_data(api.get_volunteer(editor["id"], ctx["admin_h"]))
    assert volunteer["status"] == "SUSPENDED"
    assert volunteer["substantiated_incident_count"] == 1

    # Link 2: their approved measure is quarantined.
    measure_after = get_success_data(api.get_measure(measure["id"], ctx["admin_h"]))
    assert measure_after["status"] == "REMANDED"

    # Link 3: the measure's contest reverts from GUIDE_READY.
    contest_after = get_contest(api, ctx, contest["id"])
    assert contest_after["status"] == "QUESTIONNAIRE_PHASE"
    assert contest_after["version"] == contest_version_before + 1


def test_incident_dismissal_fires_no_cascade(api):
    """PRD §3.8: "Dismissal (`REPORTED` → `DISMISSED`) merely stamps
    `resolved_at` and changes nothing else."

    Design: Difficulty/transitive_cascade/incident_substantiation_suspends_remands_reverts
    """
    ctx, contest, measure = _approved_measure_at_guide_ready(api)
    incident = report_incident(api, ctx, ctx["editor"]["id"])
    dismissed = get_success_data(
        api.transition_incident(
            incident["id"], {"to": "DISMISSED"}, ctx["admin_h"]
        )
    )
    assert dismissed["status"] == "DISMISSED"
    assert dismissed.get("resolved_at")

    volunteer = get_success_data(
        api.get_volunteer(ctx["editor"]["id"], ctx["admin_h"])
    )
    assert volunteer["status"] == "ACTIVE"
    assert volunteer["substantiated_incident_count"] == 0
    measure_after = get_success_data(api.get_measure(measure["id"], ctx["admin_h"]))
    assert measure_after["status"] == "APPROVED_FOR_GUIDE"
    assert get_contest(api, ctx, contest["id"])["status"] == "GUIDE_READY"


def _two_submitted_responses(api):
    sc = build_issued_scenario(
        api, filings=(("Ana One", "F-1"), ("Bob Two", "F-2"))
    )
    qid = sc["questionnaire"]["id"]
    for filing in sc["filings"]:
        resp = submit_answers(api, qid, filing["id"],
                              [make_answer(1, TEN_WORDS)])
        validate_success(resp, expected_status=201)
    return sc


def test_filing_withdrawal_hides_response_recomputes_completion(api):
    """PRD §3.2: "Withdrawing a `VERIFIED` filing increments the filing's
    `withdrawal_count`, recomputes `verified_candidate_count`, increments
    the contest's `version`, and cascades: the candidate's response shell,
    whatever its current status, moves to `WITHDRAWN_HIDDEN`, and the
    questionnaire's `submitted_count`, `nonresponse_count`, and `late_count`
    are recomputed, with the contest's `completion_index` re-deriving on its
    next read."

    Design: Difficulty/transitive_cascade/filing_withdrawal_hides_response_recomputes_completion
    """
    sc = _two_submitted_responses(api)
    ctx, contest, q = sc["ctx"], sc["contest"], sc["questionnaire"]
    f1 = sc["filings"][0]

    before = get_contest(api, ctx, contest["id"])
    assert before["completion_index"] == pytest.approx(100.0)

    get_success_data(api.withdraw_filing(f1["id"], ctx["coordinator_h"]))

    # Link 1: exactly one shell hidden, and it is the withdrawn filing's.
    hidden = get_shell(api, ctx, q["id"], f1["id"])
    assert hidden["status"] == "WITHDRAWN_HIDDEN"
    other = get_shell(api, ctx, q["id"], sc["filings"][1]["id"])
    assert other["status"] == "SUBMITTED"

    # Link 2: counters and the derived completion index.
    questionnaire = get_questionnaire(api, ctx, q["id"])
    assert questionnaire["submitted_count"] == 1
    assert questionnaire["invited_count"] == 2
    after = get_contest(api, ctx, contest["id"])
    assert after["completion_index"] == pytest.approx(50.0)
    assert after["verified_candidate_count"] == 1


def test_withdrawal_sets_withdrawn_indicator(api):
    """PRD §3.4: "`WITHDRAWN_HIDDEN` shows as `WITHDRAWN`" and
    "`SUBMITTED` shows as `PUBLISHED_UNEDITED`".

    Design: Difficulty/transitive_cascade/filing_withdrawal_hides_response_recomputes_completion
    """
    sc = _two_submitted_responses(api)
    ctx, q = sc["ctx"], sc["questionnaire"]
    f1, f2 = sc["filings"]

    get_success_data(api.withdraw_filing(f1["id"], ctx["coordinator_h"]))
    assert get_shell(api, ctx, q["id"], f1["id"])["published_indicator"] == "WITHDRAWN"
    surviving = get_shell(api, ctx, q["id"], f2["id"])
    assert surviving["status"] == "SUBMITTED"
    assert surviving["published_indicator"] == "PUBLISHED_UNEDITED"
