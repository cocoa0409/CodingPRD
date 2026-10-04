"""Difficulty queue: boundary_precision_check.

Strict-greater word limit (X vs X+1) and the >= quorum at exactly 2.
"""
from test_helpers import (
    ApiErrorId,
    CLOCK_START,
    ELEVEN_WORDS,
    TEN_WORDS,
    add_candidate_contest,
    add_filing,
    add_forum,
    build_issued_scenario,
    confirm_forum,
    fresh_league,
    get_success_data,
    make_answer,
    make_candidate_headers,
    move_to_questionnaire_phase,
    resubmit_answers,
    set_clock,
    submit_answers,
    validate_error,
    validate_success,
)


def test_word_count_exactly_at_limit_accepted(api):
    """PRD §3.4: "an answer is over limit only when its count strictly
    exceeds that limit; a count exactly at the limit passes."

    Design: Difficulty/boundary_precision_check/word_count_exactly_at_limit_accepted
    """
    sc = build_issued_scenario(
        api, filings=(("Ana One", "F-1"), ("Bob Two", "F-2")), word_limit=10
    )
    qid = sc["questionnaire"]["id"]
    f1, f2 = sc["filings"]

    at_limit = submit_answers(api, qid, f1["id"], [make_answer(1, TEN_WORDS)])
    data = validate_success(at_limit, expected_status=201)
    assert data["status"] == "SUBMITTED"
    assert data["per_answer_word_counts"] == [10]
    assert data["over_limit_positions"] == []

    over = submit_answers(api, qid, f2["id"], [make_answer(1, ELEVEN_WORDS)])
    data = validate_success(over, expected_status=201)
    assert data["status"] == "OVER_LIMIT_RETURNED"
    assert data["per_answer_word_counts"] == [11]
    assert data["over_limit_positions"] == [1]


def test_resubmit_at_exactly_the_limit_is_accepted(api):
    """PRD §3.4: "the resubmission recomputes the counts and either lands
    `SUBMITTED` — stamping `submitted_at`, recomputing counters, incrementing
    the questionnaire's `version` — or remains `OVER_LIMIT_RETURNED` with
    refreshed `over_limit_positions` and replaced answers."

    Design: Difficulty/boundary_precision_check/word_count_exactly_at_limit_accepted
    """
    sc = build_issued_scenario(api, word_limit=10)
    ctx = sc["ctx"]
    qid = sc["questionnaire"]["id"]
    filing = sc["filings"][0]

    first = submit_answers(api, qid, filing["id"], [make_answer(1, ELEVEN_WORDS)])
    shell = validate_success(first, expected_status=201)
    assert shell["status"] == "OVER_LIMIT_RETURNED"

    second = resubmit_answers(api, shell["id"], filing["id"],
                              [make_answer(1, TEN_WORDS)])
    data = validate_success(second)
    assert data["status"] == "SUBMITTED"
    assert data["per_answer_word_counts"] == [10]
    assert data["over_limit_positions"] == []
    assert data["submitted_at"]


def _two_contests_with_filings(api, counts):
    """Two candidate contests in QUESTIONNAIRE_PHASE; `counts` gives the
    number of verified filings per contest.  Two moderators so the 24h
    buffer rule stays out of scope."""
    ctx = fresh_league(api, moderators=("Mod One", "Mod Two"))
    contests = []
    for idx, (office, n) in enumerate(zip(("Mayor", "Clerk"), counts)):
        # The prior contest's phase advance moved the clock past the filing
        # deadline; rewind so this contest's filing window is open (PRD 3.2).
        set_clock(api, CLOCK_START)
        contest = add_candidate_contest(api, ctx, office_name=office)
        for i in range(1, n + 1):
            add_filing(api, ctx, contest["id"],
                       candidate_name=f"Candidate {office} {i}",
                       filing_reference=f"F-{office}-{i}")
        move_to_questionnaire_phase(api, ctx, contest["id"])
        contests.append(contest)
    return ctx, contests


def test_forum_quorum_exactly_two_confirms(api):
    """PRD §3.7: "Confirming (`PLANNED` → `CONFIRMED`) recomputes
    `eligible_candidate_count` at that moment and requires a quorum of at
    least two eligible candidates, exactly two being sufficient
    (`ERR_FORUM_QUORUM_NOT_MET`)."

    Design: Difficulty/boundary_precision_check/forum_quorum_exactly_two_confirms
    """
    ctx, (contest_a, contest_b) = _two_contests_with_filings(api, (2, 1))
    mod1, mod2 = ctx["moderators"][0], ctx["moderators"][1]
    forum_a = add_forum(api, ctx, contest_a["id"], mod1[0]["id"],
                        start="2026-10-10T10:00:00Z", end="2026-10-10T12:00:00Z")
    forum_b = add_forum(api, ctx, contest_b["id"], mod2[0]["id"],
                        start="2026-10-12T10:00:00Z", end="2026-10-12T12:00:00Z")
    assert forum_a["eligible_candidate_count"] == 2

    confirmed = confirm_forum(api, forum_a["id"], mod1[1])
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["eligible_candidate_count"] == 2

    resp = api.transition_forum(forum_b["id"], {"to": "CONFIRMED"}, mod2[1])
    validate_error(resp, ApiErrorId.ERR_FORUM_QUORUM_NOT_MET)
    assert resp.status_code == 422
    forum_b_after = get_success_data(api.get_forum(forum_b["id"], mod2[1]))
    assert forum_b_after["status"] == "PLANNED"


def test_quorum_recomputed_at_confirm_time(api):
    """PRD §3.7: "A created forum is `PLANNED`, with
    `eligible_candidate_count` computed at creation as the number of the
    contest's filings currently `VERIFIED`." and "Confirming (`PLANNED` →
    `CONFIRMED`) recomputes `eligible_candidate_count` at that moment and
    requires a quorum of at least two eligible candidates, exactly two being
    sufficient (`ERR_FORUM_QUORUM_NOT_MET`)."

    Design: Difficulty/boundary_precision_check/forum_quorum_exactly_two_confirms
    """
    ctx = fresh_league(api, moderators=("Mod One",))
    contest = add_candidate_contest(api, ctx)
    filing1 = add_filing(api, ctx, contest["id"],
                         candidate_name="Ana One", filing_reference="F-1")
    filing2 = add_filing(api, ctx, contest["id"],
                         candidate_name="Bob Two", filing_reference="F-2",
                         verify=False)
    move_to_questionnaire_phase(api, ctx, contest["id"])
    mod_vol, mod_h = ctx["moderators"][0]
    forum = add_forum(api, ctx, contest["id"], mod_vol["id"])
    assert forum["eligible_candidate_count"] == 1  # computed at creation

    # The second filing verifies after creation; confirm recomputes.
    get_success_data(api.verify_filing(filing2["id"], ctx["coordinator_h"]))
    confirmed = confirm_forum(api, forum["id"], mod_h)
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["eligible_candidate_count"] == 2
