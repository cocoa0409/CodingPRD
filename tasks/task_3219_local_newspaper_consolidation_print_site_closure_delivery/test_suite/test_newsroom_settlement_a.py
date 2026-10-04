"""Difficulty queue A — non_linear_state_machine, the newsroom settlement cycle.

The settlement machine is a revision cycle on a third entity: an approved change
can be reopened to proposed and approved again as often as revisions are demanded,
so approval is not a one-way gate; only applied or rejected ends the loop.
"""
import pytest

from test_helpers import (
    api,
    create_hub,
    create_region,
    create_position,
    create_newsroom_change,
    reopen_newsroom_change,
    approve_newsroom_change,
    get_newsroom_change,
    hub_version,
    validate_success,
    TEST_USERS,
    NEWSROOM_MANAGER,
    NEWSROOM_MANAGER_ALT,
)
from test_helpers.constants import CLOCK_2026_09_01

ADMIN = TEST_USERS["platform_admin_headers"]
PRINT_OPS = TEST_USERS["print_ops_headers"]


@pytest.fixture
def proposed_change():
    """Hub with 30 heads, region North with one position, one proposed 40-slot change."""
    api.set_current_utc({"current_utc": CLOCK_2026_09_01}, ADMIN)
    hub = create_hub()
    region = create_region(hub["id"])
    position = create_position(region["id"])
    change = create_newsroom_change(
        position["id"], region["id"], region["id"], hub_version(hub["id"]),
        effective_date="2026-09-11", layoff_order_index=1, requested_slots=40)
    return hub, region, position, change


def test_approval_moves_the_change_to_approved(proposed_change):
    """PRD §3.8: "On creation the movement is `proposed` and the hub's `version`
    increments by 1."

    PRD §3.8: "Approval is admitted from `proposed` when the `effective_date` is
    strictly later than the current logical date".

    Design: Difficulty/non_linear_state_machine/newsroom_change_settlement_reopens_to_proposed
    """
    hub, region, position, change = proposed_change

    assert change["status"] == "proposed"
    approved = approve_newsroom_change(change["id"], headers=NEWSROOM_MANAGER_ALT)

    assert approved["status"] == "approved", (
        f"expected approved, got {approved['status']}"
    )


def test_reopen_returns_an_approved_change_to_proposed(proposed_change):
    """PRD §3.8: "or reopened from `approved` while it has not been applied,
    returning it to `proposed` and incrementing the hub's `version` by 1."
    PRD §3.8: "`applied` and `rejected` are terminal."

    Design: Difficulty/non_linear_state_machine/newsroom_change_settlement_reopens_to_proposed
    """
    hub, region, position, change = proposed_change

    version_before = hub_version(hub["id"])
    approve_newsroom_change(change["id"], headers=NEWSROOM_MANAGER_ALT)
    reopened = reopen_newsroom_change(change["id"])

    assert reopened["status"] == "proposed", (
        f"reopen must return the change to proposed, got {reopened['status']}"
    )
    version_after = hub_version(hub["id"])
    # §3.8 increments the hub version on creation and again on reopening; approval
    # is not listed among the incrementing events, so only one bump is derivable.
    assert version_after >= version_before + 1, (
        f"reopening increments the hub version: {version_before} -> {version_after}"
    )


def test_approval_is_reachable_more_than_once_on_the_same_row(proposed_change):
    """PRD §3.8: "or reopened from `approved` while it has not been applied,
    returning it to `proposed` and incrementing the hub's `version` by 1."
    PRD §2.5: "This happens on print-site closure planning and closure, on market
    transfer planning, redispatch and withdrawal, on delivery stop pause, resume and
    terminate, on contractor termination, and on newsroom change creation and
    reopening."

    Design: Difficulty/non_linear_state_machine/newsroom_change_settlement_reopens_to_proposed
    """
    hub, region, position, change = proposed_change

    approve_newsroom_change(change["id"], headers=NEWSROOM_MANAGER_ALT)
    assert get_newsroom_change(change["id"])["status"] == "approved"

    reopen_newsroom_change(change["id"])
    assert get_newsroom_change(change["id"])["status"] == "proposed"

    approve_newsroom_change(change["id"], headers=NEWSROOM_MANAGER_ALT)
    second = get_newsroom_change(change["id"])
    assert second["status"] == "approved", (
        f"approval must be reachable twice on the same row, got {second['status']}"
    )

    version_mid = hub_version(hub["id"])
    reopen_newsroom_change(change["id"])
    final = get_newsroom_change(change["id"])
    assert final["status"] == "proposed"
    assert hub_version(hub["id"]) >= version_mid + 1, (
        "the second reopen must advance the hub version again"
    )