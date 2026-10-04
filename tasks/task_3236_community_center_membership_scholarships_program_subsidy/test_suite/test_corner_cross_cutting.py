"""Corner probes against the cross-cutting complexity layers: optimistic
concurrency and the fixed startup clock."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    ASSOCIATION_ADMIN_HEADERS,
    BRANCH_DIRECTOR_HEADERS,
    PROGRAM_COORDINATOR_HEADERS,
)
from test_helpers import factories, fixtures


def test_stale_membership_version_on_patch_is_rejected(api):
    """A PATCH carrying the version observed before a draft was created fails;
    replaying with the fresh version succeeds and bumps it.

    PRD §2.5: "Updating a membership's mutable fields (a `category_id` change or
    a `member_ids` household edit) requires `expected_membership_version`
    matching the membership's current `version`, so an operator editing
    household composition cannot silently overwrite a category change or
    assistance award that landed on the same row in the meantime."
    PRD §2.5: "A version mismatch is always `ERR_STALE_VERSION` with HTTP 412."
    PRD §3.3: "Creating a draft increments the membership's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_membership_version_on_patch
    """
    world = fixtures.setup_membership(api)
    membership = world["membership"]
    observed = membership["version"]

    # A later mutation moves the version forward.
    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    get_success_data(api.create_draft_for_membership(membership["id"], BRANCH_DIRECTOR_HEADERS))

    stale = api.update_membership(
        membership["id"],
        {"member_ids": [world["member"]["id"]], "expected_membership_version": observed},
        BRANCH_DIRECTOR_HEADERS,
    )
    validate_error(stale, "ERR_STALE_VERSION")

    current = get_success_data(api.get_membership(membership["id"], BRANCH_DIRECTOR_HEADERS))
    assert current["version"] == observed + 1, "the failed PATCH must not bump the version"

    fresh = get_success_data(
        api.update_membership(
            membership["id"],
            {"member_ids": [world["member"]["id"]], "expected_membership_version": current["version"]},
            BRANCH_DIRECTOR_HEADERS,
        )
    )
    assert fresh["version"] == current["version"] + 1


def test_stale_campaign_version_on_close_is_rejected(api):
    """A close carrying the version observed before a donation was received
    fails; the campaign stays ACTIVE.

    PRD §2.5: "Closing a campaign requires `expected_campaign_version` matching
    the campaign's current `version`; donations received in between advance the
    version, and a stale close is rejected so the frozen match tier reflects the
    true final attainment rather than a snapshot."
    PRD §2.5: "A version mismatch is always `ERR_STALE_VERSION` with HTTP 412."
    PRD §3.7: "Receipt adds the `amount_cents` to the campaign's
    `base_raised_cents`, increments the campaign's `version` by one"

    Design: Corner/cross_cutting_complexity_layers/occ_stale_campaign_version_on_close
    """
    world = fixtures.setup_association_and_branch(api)
    campaign = fixtures.create_campaign(api, world["association"]["id"], goal_cents=100_000)
    activated = get_success_data(api.activate_campaign(campaign["id"], ASSOCIATION_ADMIN_HEADERS))
    observed = activated["version"]

    donation = fixtures.create_donation(
        api, campaign["id"], world["branch"]["id"], amount_cents=10_000, designation="GENERAL"
    )
    get_success_data(api.receive_donation(donation["id"], BRANCH_DIRECTOR_HEADERS))

    stale = api.close_campaign(
        campaign["id"], {"expected_campaign_version": observed}, ASSOCIATION_ADMIN_HEADERS
    )
    validate_error(stale, "ERR_STALE_VERSION")

    current = get_success_data(api.get_campaign(campaign["id"], ASSOCIATION_ADMIN_HEADERS))
    assert current["status"] == "ACTIVE"

    closed = get_success_data(
        api.close_campaign(
            campaign["id"], {"expected_campaign_version": current["version"]}, ASSOCIATION_ADMIN_HEADERS
        )
    )
    assert closed["status"] == "CLOSED"


def test_clock_starts_at_the_fixed_startup_instant(api):
    """No set_current_utc call means the logical clock reads the PRD's startup
    instant, and created rows are stamped with it.

    PRD §2.6: "The server maintains a logical clock whose startup value is
    exactly 2026-09-01T00:00:00Z; the server must never consult wall-clock
    time."
    PRD §2.6: "a session flips from `SCHEDULED` to `REG_OPEN` when the clock
    reaches `member_opens_on`"
    PRD §3.5: "Two system-computed dates govern enrollment: `public_opens_on` is
    the `start_on` date minus 14 days, and `member_opens_on` is
    `member_priority_days` earlier still"

    Design: Corner/cross_cutting_complexity_layers/clock_default_is_fixed_startup_instant
    """
    # Deliberately never touch the clock.
    association = fixtures.create_association(api)
    branch = fixtures.create_branch(api, association["id"])
    space = fixtures.create_space(api, branch["id"], name="Studio 1", kind="STUDIO", capacity=30, dropin_capacity=5)
    program = fixtures.create_program(
        api, branch["id"], name="Hoops", kind="SPORTS", base_fee_cents=4_000, member_priority_days=0
    )
    # start_on 2026-09-10 -> public/member window opens 2026-08-27, before the startup instant.
    session = fixtures.create_session(
        api, program["id"], space["id"], start_on="2026-09-10", end_on="2026-09-10",
        time_start="18:00", time_end="19:00", capacity=10,
    )

    fetched = get_success_data(api.get_session(session["id"], PROGRAM_COORDINATOR_HEADERS))
    assert fetched["status"] == "REG_OPEN", (
        "with priority days 0 the window opens at start_on minus 14 days, before the startup instant"
    )
    assert fetched["created_at"].startswith("2026-09-01T00:00:00"), (
        f"created_at must be stamped from the logical clock, got {fetched['created_at']!r}"
    )
