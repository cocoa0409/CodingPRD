"""Difficulty queue: cross_entity_state_dependency.

A request on one aggregate is gated by the state of a sibling aggregate:
the response shell by its filing, the contest by its questionnaire.
"""
from test_helpers import (
    ApiErrorId,
    ELEVEN_WORDS,
    FIVE_WORDS,
    PAST_DUE_AT,
    advance_contest,
    build_issued_scenario,
    contest_version,
    get_contest,
    get_shell,
    get_success_data,
    make_answer,
    resubmit_answers,
    set_clock,
    submit_answers,
    validate_error,
    validate_success,
)


def test_submit_blocked_when_filing_hidden(api):
    """PRD §3.4: "the shell's filing must be `VERIFIED`, meaning the shell
    must not be `WITHDRAWN_HIDDEN` (`ERR_FILING_NOT_VERIFIED`)"

    Design: Difficulty/cross_entity_state_dependency/response_submit_blocked_when_filing_hidden
    """
    sc = build_issued_scenario(api)
    ctx, q = sc["ctx"], sc["questionnaire"]
    filing = sc["filings"][0]

    # The window is still open (clock 2026-09-16 <= due_at); only the
    # sibling filing's state blocks the submission.
    get_success_data(api.withdraw_filing(filing["id"], ctx["coordinator_h"]))
    resp = submit_answers(api, q["id"], filing["id"], [make_answer(1, FIVE_WORDS)])
    validate_error(resp, ApiErrorId.ERR_FILING_NOT_VERIFIED)
    assert resp.status_code == 409

    shell = get_shell(api, ctx, q["id"], filing["id"])
    assert shell["status"] == "WITHDRAWN_HIDDEN"


def test_resubmit_blocked_when_filing_hidden(api):
    """PRD §3.4: "From `OVER_LIMIT_RETURNED` the candidate resubmits a
    corrected answer set under the same four gates" — and the second of the
    four is "the shell's filing must be `VERIFIED`, meaning the shell must
    not be `WITHDRAWN_HIDDEN` (`ERR_FILING_NOT_VERIFIED`)".

    Design: Difficulty/cross_entity_state_dependency/response_submit_blocked_when_filing_hidden
    """
    sc = build_issued_scenario(api, word_limit=10)
    ctx, q = sc["ctx"], sc["questionnaire"]
    filing = sc["filings"][0]

    first = submit_answers(api, q["id"], filing["id"],
                           [make_answer(1, ELEVEN_WORDS)])
    shell = validate_success(first, expected_status=201)
    assert shell["status"] == "OVER_LIMIT_RETURNED"

    get_success_data(api.withdraw_filing(filing["id"], ctx["coordinator_h"]))
    resp = resubmit_answers(api, shell["id"], filing["id"],
                            [make_answer(1, FIVE_WORDS)])
    validate_error(resp, ApiErrorId.ERR_FILING_NOT_VERIFIED)
    assert resp.status_code == 409


def test_guide_ready_blocked_until_questionnaire_pinned(api):
    """PRD §3.2: "a candidate race requires its questionnaire to be
    `PINNED` (`ERR_QUESTIONNAIRE_NOT_PINNED`), while a ballot-measure
    contest requires its measure to be `APPROVED_FOR_GUIDE`
    (`ERR_NEUTRALITY_REVIEW_OUTSTANDING`)."

    Design: Difficulty/cross_entity_state_dependency/contest_guide_ready_blocked_until_questionnaire_pinned
    """
    sc = build_issued_scenario(api)
    ctx, contest = sc["ctx"], sc["contest"]
    # Questionnaire is merely ISSUED.
    version = contest_version(api, ctx, contest["id"])
    resp = api.transition_contest(
        contest["id"],
        {"to": "GUIDE_READY", "expected_contest_version": version},
        ctx["coordinator_h"],
    )
    validate_error(resp, ApiErrorId.ERR_QUESTIONNAIRE_NOT_PINNED)
    assert resp.status_code == 422
    assert get_contest(api, ctx, contest["id"])["status"] == "QUESTIONNAIRE_PHASE"


def test_closed_but_unpinned_questionnaire_still_blocks_guide_ready(api):
    """PRD §3.3: "Pinning (`CLOSED` → `PINNED`) carries no further
    preconditions and establishes the questionnaire as the snapshot source
    for guide editions — the pin is precisely what a candidate race needs
    before its contest may advance to `GUIDE_READY`."

    Design: Difficulty/cross_entity_state_dependency/contest_guide_ready_blocked_until_questionnaire_pinned
    """
    sc = build_issued_scenario(api)
    ctx, contest, q = sc["ctx"], sc["contest"], sc["questionnaire"]
    set_clock(api, PAST_DUE_AT)
    get_success_data(api.close_questionnaire(q["id"], ctx["editor_h"]))

    version = contest_version(api, ctx, contest["id"])
    resp = api.transition_contest(
        contest["id"],
        {"to": "GUIDE_READY", "expected_contest_version": version},
        ctx["coordinator_h"],
    )
    validate_error(resp, ApiErrorId.ERR_QUESTIONNAIRE_NOT_PINNED)

    get_success_data(api.pin_questionnaire(q["id"], ctx["editor_h"]))
    ready = advance_contest(api, ctx, contest["id"], "GUIDE_READY")
    assert ready["status"] == "GUIDE_READY"
