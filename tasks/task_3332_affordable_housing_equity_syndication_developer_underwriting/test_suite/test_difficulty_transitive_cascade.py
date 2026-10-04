"""Depth: cascades that travel more than one hop.

Distress moves upward from a project to its fund and its developer, and the
developer's derived standing then gates the next write. Both instances here
assert the end of such a chain, not just the first hop.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    SCENARIO,
    add_allocation,
    add_guarantee,
    add_project,
    api_client,
    commit_project,
    draw_on_guarantee,
    finalize_underwriting,
    get_success_data,
    open_review,
    read_developer,
    read_fund,
    read_project,
    resolve_review,
    setup_canonical_scenario,
    setup_two_projects_under_one_fund,
    validate_error,
)

_WILLOW = dict(SCENARIO["developer_willow"])
_JUNIPER = dict(SCENARIO["project_juniper"])
_CEDAR_POINT = dict(SCENARIO["project_cedar_point"])


def _escalate_review(project_id, period_index=1):
    review = open_review(project_id, review_period_index=period_index)
    return resolve_review(review["id"], outcome="ESCALATED")


def _two_distressed_projects():
    scenario = setup_two_projects_under_one_fund()
    return scenario


def _willow_juniper_scenario():
    """Willow Bend sponsors a committed Juniper Flats under fund IV."""
    return setup_canonical_scenario(
        developer_overrides=_WILLOW,
        project_overrides=_JUNIPER,
        with_subscription=True,
        with_project=True,
        with_allocation=True,
        with_finalized_underwriting=True,
        with_commit=True,
    )


def test_one_escalated_review_watches_the_sponsor_and_its_fund():
    """PRD §3.1: "A developer moves from `ELIGIBLE` to `WATCH` when its coverage
    ratio falls below 2.0, or when at least one of its projects is `DISTRESSED`,
    or when at least one review of one of its non-`EXITED` projects is
    `ESCALATED`."

    Design: Difficulty/transitive_cascade/two_escalated_reviews_suspend_sponsor_then_freeze_fund
    """
    scenario = _two_distressed_projects()

    _escalate_review(scenario.project["id"], period_index=1)

    assert read_project(scenario.project["id"])["status"] == "DISTRESSED"
    assert read_project(scenario.project2["id"])["status"] == "COMMITTED"
    assert read_developer(scenario.developer["id"])["status"] == "WATCH"
    assert read_fund(scenario.fund["id"])["posture"] == "WATCH"


def test_two_escalated_reviews_suspend_the_sponsor_and_freeze_the_fund():
    """PRD §3.1: "A developer moves from either `ELIGIBLE` or `WATCH` to
    `SUSPENDED` when at least two reviews across its non-`EXITED` projects are
    `ESCALATED` and at least one of its projects is `DISTRESSED`."
    PRD §3.1: "Every affected fund's `posture` becomes `FROZEN`."

    Design: Difficulty/transitive_cascade/two_escalated_reviews_suspend_sponsor_then_freeze_fund
    """
    scenario = _two_distressed_projects()

    _escalate_review(scenario.project["id"], period_index=1)
    _escalate_review(scenario.project2["id"], period_index=2)

    assert read_project(scenario.project["id"])["status"] == "DISTRESSED"
    assert read_project(scenario.project2["id"])["status"] == "DISTRESSED"
    assert read_developer(scenario.developer["id"])["status"] == "SUSPENDED"
    assert read_fund(scenario.fund["id"])["posture"] == "FROZEN"


def test_recapture_draw_moves_the_guarantee_to_drawn_and_watches_the_sponsor(
    asset_manager_headers,
):
    """PRD §3.6: "The amount drawn increases by the lesser of the requested amount
    and the guarantee's remaining capacity, so a draw larger than the capacity
    simply consumes the capacity rather than being rejected."
    PRD §3.6: "When a recapture guarantee moves to `DRAWN`, the owning project
    becomes `DISTRESSED`, and the owning fund's posture and the owning
    developer's status are recomputed."

    Design: Difficulty/transitive_cascade/recapture_draw_distresses_juniper_then_watches_sponsor_and_blocks_the_next_commit
    """
    scenario = _willow_juniper_scenario()
    guarantee = add_guarantee(
        scenario.project["id"],
        guarantee_type="RECAPTURE",
        guaranteed_amount_cents=90000000,
        recapture_pct=0.125,
    )
    _escalate_review(scenario.project["id"], period_index=1)

    drawn = draw_on_guarantee(guarantee["id"], 25000000, asset_manager_headers)

    assert drawn["status"] == "DRAWN"
    assert drawn["drawn_amount_cents"] == 25000000
    assert drawn["remaining_capacity_cents"] == 65000000
    assert read_project(scenario.project["id"])["status"] == "DISTRESSED"
    assert read_developer(scenario.developer["id"])["status"] == "WATCH"
    assert read_fund(scenario.fund["id"])["posture"] == "WATCH"


def test_a_watched_sponsor_cannot_commit_its_next_project(underwriter_headers):
    """PRD §3.4: "A commit whose developer is on `WATCH` or `SUSPENDED` is
    rejected with `ERR_DEVELOPER_WATCH_BLOCKED`."

    Design: Difficulty/transitive_cascade/recapture_draw_distresses_juniper_then_watches_sponsor_and_blocks_the_next_commit
    """
    scenario = _willow_juniper_scenario()
    guarantee = add_guarantee(
        scenario.project["id"],
        guarantee_type="RECAPTURE",
        guaranteed_amount_cents=90000000,
        recapture_pct=0.125,
    )
    _escalate_review(scenario.project["id"], period_index=1)
    draw_on_guarantee(guarantee["id"], 25000000)

    cedar_point = add_project(
        scenario.developer["id"], scenario.fund["id"], **_CEDAR_POINT
    )
    add_allocation(cedar_point["id"])
    cedar_point = finalize_underwriting(cedar_point)
    assert read_project(cedar_point["id"])["underwriting_stage"] == "FINAL"

    response = api_client.commit_project(cedar_point["id"], underwriter_headers)

    validate_error(response, ApiErrorId.ERR_DEVELOPER_WATCH_BLOCKED)
    assert read_project(cedar_point["id"])["status"] == "UNDERWRITING"
