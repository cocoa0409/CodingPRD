"""Difficulty queue: compensating_invariant.

A forward/backward action pair with no intervening content change must
restore the conserved quantity exactly: the edition's pinned snapshot and
page estimate, and the questionnaire's shell cardinality.
"""
import pytest

from test_helpers import (
    TEN_WORDS,
    TWENTY_ONE_WORDS,
    add_candidate_contest,
    add_filing,
    assert_allocation_conservation,
    build_issued_scenario,
    build_locked_candidate_contest,
    create_edition,
    fresh_league,
    get_contest,
    get_edition,
    get_questionnaire,
    get_shell,
    get_success_data,
    list_shells,
    make_answer,
    ready_edition,
    submit_answers,
    validate_success,
)


def _locked_single_answer_contest(api):
    return build_locked_candidate_contest(
        api,
        filings=(("Ana One", "F-1"),),
        submissions={"F-1": [make_answer(1, TWENTY_ONE_WORDS)]},
    )


def test_reopen_repin_preserves_page_estimate(api):
    """PRD §3.6: "Re-opening (`READY` → `ASSEMBLING`) clears
    `snapshot_contest_ids` and `pinned_questionnaire_versions` while
    retaining the last `estimated_page_count` until the next readying."  A
    second readying with unchanged content recomputes the identical
    estimate.

    Design: Difficulty/compensating_invariant/reopen_repin_preserves_page_estimate
    """
    sc = _locked_single_answer_contest(api)
    ctx = sc["ctx"]
    edition = create_edition(api, ctx, channel="PARTNER")

    first = ready_edition(api, ctx, edition["id"])
    # ceil(ceil(21/10)/2) = 2 content pages + 2 front matter.
    assert first["estimated_page_count"] == 4
    assert first["snapshot_contest_ids"] == [sc["contest"]["id"]]
    pinned_version = sc["questionnaire"]["version"]
    assert first["pinned_questionnaire_versions"] == {
        sc["contest"]["id"]: pinned_version
    }

    reopened = get_success_data(
        api.transition_edition(edition["id"], {"to": "ASSEMBLING"}, ctx["editor_h"])
    )
    assert reopened["snapshot_contest_ids"] == []

    second = ready_edition(api, ctx, edition["id"])
    assert second["estimated_page_count"] == 4
    assert second["pinned_questionnaire_versions"] == {
        sc["contest"]["id"]: pinned_version
    }


def test_reopen_retains_estimate_and_bumps_version(api):
    """PRD §3.6: "Re-opening (`READY` → `ASSEMBLING`) clears
    `snapshot_contest_ids` and `pinned_questionnaire_versions` while
    retaining the last `estimated_page_count` until the next readying."
    PRD §2.5: "`version`, an integer that increments by exactly 1 on every
    mutation of that resource."

    Design: Difficulty/compensating_invariant/reopen_repin_preserves_page_estimate
    """
    sc = _locked_single_answer_contest(api)
    ctx = sc["ctx"]
    edition = create_edition(api, ctx, channel="PARTNER")
    first = ready_edition(api, ctx, edition["id"])

    reopened = get_success_data(
        api.transition_edition(edition["id"], {"to": "ASSEMBLING"}, ctx["editor_h"])
    )
    assert reopened["estimated_page_count"] == 4  # retained, not cleared
    assert reopened["snapshot_contest_ids"] == []
    assert reopened["pinned_questionnaire_versions"] == {}
    assert reopened["version"] == first["version"] + 1

    second = ready_edition(api, ctx, edition["id"])
    assert second["version"] == reopened["version"] + 1


def test_withdraw_refile_conserves_shell_cardinality(api):
    """PRD §3.2: "A successful refile refreshes `filed_at`, leaves
    `withdrawal_count` untouched, and — when a hidden shell exists for the
    filing — restores that shell to `INVITED` with its previously submitted
    `answers` preserved, recomputing the questionnaire's counters."
    PRD §3.3: "`invited_count` counts every shell ever created".

    Design: Difficulty/compensating_invariant/withdraw_refile_conserves_response_shell_cardinality
    """
    sc = build_issued_scenario(api, filings=(("Ana One", "F-1"), ("Bob Two", "F-2")))
    ctx, q = sc["ctx"], sc["questionnaire"]
    f1 = sc["filings"][0]
    data = validate_success(
        submit_answers(api, q["id"], f1["id"], [make_answer(1, TEN_WORDS)]),
        expected_status=201,
    )
    assert data["status"] == "SUBMITTED"

    get_success_data(api.withdraw_filing(f1["id"], ctx["coordinator_h"]))
    mid = get_questionnaire(api, ctx, q["id"])
    assert mid["invited_count"] == 2   # hidden, not destroyed
    assert mid["submitted_count"] == 0

    get_success_data(api.refile_filing(f1["id"], ctx["coordinator_h"]))
    get_success_data(api.verify_filing(f1["id"], ctx["coordinator_h"]))

    end = get_questionnaire(api, ctx, q["id"])
    assert end["invited_count"] == 2  # no duplicate shell created by re-verify
    shells = list_shells(api, ctx, q["id"])
    assert len(shells) == 2
    restored = get_shell(api, ctx, q["id"], f1["id"])
    assert restored["status"] == "INVITED"
    assert restored["answers"] == [{"position_index": 1, "text": TEN_WORDS}]
    assert get_contest(api, ctx, sc["contest"]["id"])["completion_index"] == pytest.approx(0.0)


def test_withdraw_of_unverified_filing_touches_no_shell(api):
    """PRD §3.2: "Withdrawing a merely `FILED` filing only increments
    `withdrawal_count`, because no shell can exist for a candidate who was
    never verified."

    Design: Difficulty/compensating_invariant/withdraw_refile_conserves_response_shell_cardinality
    """
    ctx = fresh_league(api)
    contest = add_candidate_contest(api, ctx)
    filing = add_filing(api, ctx, contest["id"], verify=False)
    assert filing["status"] == "FILED"

    withdrawn = get_success_data(
        api.withdraw_filing(filing["id"], ctx["coordinator_h"])
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["withdrawal_count"] == 1
    contest_after = get_contest(api, ctx, contest["id"])
    assert contest_after["verified_candidate_count"] == 0
