"""Difficulty queue: non_linear_state_machine.

CandidateFiling runs FILED -> VERIFIED -> WITHDRAWN -> FILED cycles, and
BallotMeasure runs review rounds with remand -> revise -> resubmit.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    add_candidate_contest,
    add_filing,
    assert_instant_equals,
    build_measure_pipeline,
    fresh_league,
    get_measure,
    get_success_data,
    make_filing_payload,
    review_measure,
    set_clock,
)


def test_filing_withdraw_refile_cycle_restores_verified(api):
    """PRD §3.2: "Refiling returns a `WITHDRAWN` filing to `FILED` and is
    deadline-gated" and "A successful refile refreshes `filed_at`, leaves
    `withdrawal_count` untouched".

    Design: Difficulty/non_linear_state_machine/filing_withdraw_refile_cycle_restores_verified
    """
    ctx = fresh_league(api)
    contest = add_candidate_contest(api, ctx)
    filing = add_filing(api, ctx, contest["id"],
                        candidate_name="Wendy Cycle", filing_reference="F-9")
    fid = filing["id"]

    withdrawn = get_success_data(api.withdraw_filing(fid, ctx["coordinator_h"]))
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["withdrawal_count"] == 1

    set_clock(api, "2026-09-02T00:00:00Z")
    refiled = get_success_data(api.refile_filing(fid, ctx["coordinator_h"]))
    assert refiled["status"] == "FILED"
    assert_instant_equals(refiled["filed_at"], "2026-09-02T00:00:00Z", "filed_at")
    assert refiled["withdrawal_count"] == 1

    set_clock(api, "2026-09-03T00:00:00Z")
    verified = get_success_data(api.verify_filing(fid, ctx["coordinator_h"]))
    assert verified["status"] == "VERIFIED"
    assert_instant_equals(verified["verified_at"], "2026-09-03T00:00:00Z",
                          "verified_at")
    assert verified["withdrawal_count"] == 1


def test_withdrawal_count_accumulates_across_cycles(api):
    """PRD §3.2: "Withdrawing a `VERIFIED` filing increments the filing's
    `withdrawal_count`" and a refile "leaves `withdrawal_count` untouched" —
    so a second withdraw after a refile+verify cycle reads 2.

    Design: Difficulty/non_linear_state_machine/filing_withdraw_refile_cycle_restores_verified
    """
    ctx = fresh_league(api)
    contest = add_candidate_contest(api, ctx)
    filing = add_filing(api, ctx, contest["id"],
                        candidate_name="Wendy Cycle", filing_reference="F-9")
    fid = filing["id"]
    get_success_data(api.withdraw_filing(fid, ctx["coordinator_h"]))
    get_success_data(api.refile_filing(fid, ctx["coordinator_h"]))
    get_success_data(api.verify_filing(fid, ctx["coordinator_h"]))
    withdrawn = get_success_data(api.withdraw_filing(fid, ctx["coordinator_h"]))
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["withdrawal_count"] == 2


def test_measure_remand_revise_resubmit_second_round(api):
    """PRD §3.5: "Either remanding verdict, `LOADED_LANGUAGE` or
    `UNBALANCED`, ends the round immediately by moving the measure to
    `REMANDED`." and "may review a given measure at most once per round
    (`ERR_DUPLICATE_REVIEW_THIS_ROUND`)" — the guard is per round, so the
    round-1 remanding reviewer may review round 2.

    Design: Difficulty/non_linear_state_machine/measure_remand_revise_resubmit_second_round
    """
    sc = build_measure_pipeline(api, submit=True)
    ctx = sc["ctx"]
    measure = sc["measure"]
    mid = measure["id"]

    remanded = get_success_data(
        review_measure(api, ctx, mid, 0, verdict="UNBALANCED",
                       notes="Con side is thinner than pro.")
    )
    measure = get_measure(api, ctx, mid)
    assert measure["status"] == "REMANDED"

    get_success_data(
        api.revise_measure(
            mid, {"explanation_text": "Cats run fast with dogs on soft "
                                      "brown mats near cedar."},
            ctx["editor_h"],
        )
    )
    assert get_measure(api, ctx, mid)["status"] == "DRAFTING"

    measure = get_success_data(api.submit_measure_for_review(mid, ctx["editor_h"]))
    assert measure["status"] == "IN_NEUTRALITY_REVIEW"
    assert measure["review_round_count"] == 2
    assert measure["approvals_this_round"] == 0

    # The reviewer who remanded round 1 may review round 2.
    review = get_success_data(
        review_measure(api, ctx, mid, 0, verdict="NEUTRAL",
                       notes="Now balanced."), expected_status=201
    )
    assert review["round_index"] == 2
    assert get_measure(api, ctx, mid)["status"] == "IN_NEUTRALITY_REVIEW"

    get_success_data(
        review_measure(api, ctx, mid, 1, verdict="NEUTRAL",
                       notes="Second approval completes round 2."),
        expected_status=201,
    )
    measure = get_measure(api, ctx, mid)
    assert measure["status"] == "APPROVED_FOR_GUIDE"
    assert measure["approvals_this_round"] == 2


def test_revise_recomputes_grades_and_returns_to_drafting(api):
    """PRD §3.5: "a revision replaces `explanation_text`, recomputes both
    grades, returns a remanded measure to `DRAFTING`, and increments the
    measure's `version`."

    Design: Difficulty/non_linear_state_machine/measure_remand_revise_resubmit_second_round
    """
    sc = build_measure_pipeline(api, submit=True)
    ctx = sc["ctx"]
    mid = sc["measure"]["id"]
    before = get_measure(api, ctx, mid)
    assert before["grade_fk"] == pytest.approx(2.65, abs=1e-9)

    get_success_data(
        review_measure(api, ctx, mid, 0, verdict="LOADED_LANGUAGE",
                       notes="Loaded phrasing in sentence one.")
    )
    assert get_measure(api, ctx, mid)["status"] == "REMANDED"

    revised = get_success_data(
        api.revise_measure(
            mid, {"explanation_text": "Cats run fast with dogs on soft "
                                      "brown mats near cedar."},
            ctx["editor_h"],
        )
    )
    assert revised["status"] == "DRAFTING"
    # banana (3 syllables, polysyllable) -> cedar (2 syllables): 12 syllables,
    # 0 polysyllables, 11 words, 1 sentence.
    assert revised["grade_fk"] == pytest.approx(1.57, abs=1e-9)
    assert revised["grade_smog"] == pytest.approx(3.13, abs=1e-9)
    assert revised["version"] == before["version"] + 2
