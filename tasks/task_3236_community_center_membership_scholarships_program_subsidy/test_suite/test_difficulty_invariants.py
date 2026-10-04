"""Compensating invariants: a forward action and its compensating action return
the conserved quantity to its exact prior value."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    ASSOCIATION_ADMIN_HEADERS,
    BRANCH_DIRECTOR_HEADERS,
    FRONT_DESK_HEADERS,
    assert_branch_pool_invariants,
    assert_cents,
    make_member_headers,
)
from test_helpers import fixtures


def test_scholarship_refund_restores_the_pool_exactly(api):
    """Receive raises the pool; refunding the same gift returns it to the cent.

    PRD §2.8: "The stored counters are recomputed eagerly on every triggering
    mutation — donation receipt or refund, award approval, award expiry, or the
    cancellation or lapse of an awarded membership — and an audit read that
    replays donation and application state events in `created_at` ascending
    order must arrive at exactly the same value; the compensating refund
    transition is what keeps both consistent."
    PRD §3.7: "Receipt adds the `amount_cents` to the campaign's
    `base_raised_cents`"
    PRD §3.7: "It subtracts the amount from `base_raised_cents` and increments
    the campaign `version`; while the campaign is still `ACTIVE` the match tier
    is recomputed from the reduced attainment."

    Design: Difficulty/compensating_invariant/scholarship_refund_compensates_receive_pool_unchanged
    """
    world = fixtures.setup_funded_pool(api, amount_cents=200_000)

    before = get_success_data(api.get_branch(world["branch"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert_cents(before["scholarship_pool_received_cents"], 200_000, "pool received before")
    assert_cents(before["scholarship_pool_available_cents"], 200_000, "pool available before")

    extra = fixtures.create_donation(
        api, world["campaign"]["id"], world["branch"]["id"], amount_cents=50_000, designation="SCHOLARSHIP"
    )
    get_success_data(api.receive_donation(extra["id"], BRANCH_DIRECTOR_HEADERS))
    raised = get_success_data(api.get_branch(world["branch"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert_cents(raised["scholarship_pool_received_cents"], 250_000, "pool received after receive")
    assert_cents(raised["scholarship_pool_available_cents"], 250_000, "pool available after receive")

    refunded = get_success_data(api.refund_donation(extra["id"], ASSOCIATION_ADMIN_HEADERS))
    assert refunded["status"] == "REFUNDED"
    restored = get_success_data(api.get_branch(world["branch"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert_cents(restored["scholarship_pool_received_cents"], 200_000, "pool received after refund")
    assert_cents(restored["scholarship_pool_available_cents"], 200_000, "pool available after refund")
    assert_branch_pool_invariants(restored)

    untouched = get_success_data(api.get_donation(world["donation"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert untouched["status"] == "RECEIVED"


def test_general_refund_restores_campaign_base_exactly(api):
    """The compensating pair on the campaign side: a GENERAL receive followed by
    its refund returns base_raised_cents to its prior value.

    PRD §3.7: "Receipt adds the `amount_cents` to the campaign's
    `base_raised_cents`, increments the campaign's `version` by one"
    PRD §3.7: "Refund is the compensating action, restricted to
    `AssociationAdmin`. It subtracts the amount from `base_raised_cents` and
    increments the campaign `version`"

    Design: Difficulty/compensating_invariant/scholarship_refund_compensates_receive_pool_unchanged
    """
    world = fixtures.setup_funded_pool(api, amount_cents=200_000, designation="SCHOLARSHIP")

    before = get_success_data(api.get_campaign(world["campaign"]["id"], ASSOCIATION_ADMIN_HEADERS))
    extra = fixtures.create_donation(
        api, world["campaign"]["id"], world["branch"]["id"], amount_cents=40_000, designation="GENERAL"
    )
    get_success_data(api.receive_donation(extra["id"], BRANCH_DIRECTOR_HEADERS))
    raised = get_success_data(api.get_campaign(world["campaign"]["id"], ASSOCIATION_ADMIN_HEADERS))
    assert_cents(
        raised["base_raised_cents"], before["base_raised_cents"] + 40_000, "base after receive"
    )

    get_success_data(api.refund_donation(extra["id"], ASSOCIATION_ADMIN_HEADERS))
    restored = get_success_data(api.get_campaign(world["campaign"]["id"], ASSOCIATION_ADMIN_HEADERS))
    assert_cents(restored["base_raised_cents"], before["base_raised_cents"], "base after refund")


def test_hold_and_resume_conserve_billed_amount_and_membership_count(api):
    """A hold-resume pair bills nothing and never moves the branch's active
    membership count.

    PRD §3.3: "A hold ends when the logical clock reaches `hold_until`, or
    earlier when a `Member` or `BranchDirector` resumes the membership. Either
    way the status returns `ON_HOLD` → `ACTIVE`, `hold_days_used_trailing_12mo`
    is recomputed by the interval merge, and the next regular draft resumes at
    the full assisted dues amount."
    PRD §2.8: "A branch also tracks `active_membership_count`, the count of its
    memberships whose status is `ACTIVE` or `ON_HOLD`."
    PRD §3.3: "A `Member`, `BranchDirector`, or `FrontDesk` operator may settle
    a `PENDING` or `FAILED` draft, marking it `PAID` and adding its
    `amount_cents` to the membership's `lifetime_billed_cents` — the conserved
    billing quantity that accumulates successfully drafted cents minus
    reversals."

    Design: Difficulty/compensating_invariant/membership_hold_resume_conserves_billed_amount_and_seat_counts
    """
    world = fixtures.setup_membership(api)
    membership = world["membership"]
    member_headers = make_member_headers(world["member"]["id"])

    # Settle the activation draft so lifetime_billed_cents holds a known value.
    first = fixtures.first_draft_of(api, membership["id"])
    get_success_data(api.settle_draft(first["id"], FRONT_DESK_HEADERS))
    billed_before = get_success_data(api.get_membership(membership["id"], BRANCH_DIRECTOR_HEADERS))[
        "lifetime_billed_cents"
    ]
    assert billed_before == first["amount_cents"]

    branch_before = get_success_data(api.get_branch(world["branch"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert_cents(branch_before["active_membership_count"], 1, "active_membership_count before hold")

    # Hold and immediately resume: no drafts are created by either action.
    get_success_data(api.hold_membership(membership["id"], {"hold_until": "2026-11-01"}, member_headers))
    held = get_success_data(api.get_branch(world["branch"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert_cents(held["active_membership_count"], 1, "ON_HOLD stays counted")

    get_success_data(api.resume_membership(membership["id"], member_headers))
    after = get_success_data(api.get_membership(membership["id"], BRANCH_DIRECTOR_HEADERS))
    assert after["status"] == "ACTIVE"
    assert after["lifetime_billed_cents"] == billed_before, "hold+resume billed nothing"

    branch_after = get_success_data(api.get_branch(world["branch"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert_cents(branch_after["active_membership_count"], 1, "resume does not double-increment")


def test_cancel_is_not_the_compensating_pair_and_decrements_the_count(api):
    """Hold decrements nothing, but cancel does: the two paths are asymmetric on
    the conserved seat count.

    PRD §2.8: "A branch also tracks `active_membership_count`, the count of its
    memberships whose status is `ACTIVE` or `ON_HOLD`."
    PRD §3.3: "Cancellation is terminal, releases any approved award exactly as
    lapse does, resets the membership's `assistance_pct` to 0, and decrements
    the branch's `active_membership_count`."

    Design: Difficulty/compensating_invariant/membership_hold_resume_conserves_billed_amount_and_seat_counts
    """
    world = fixtures.setup_membership(api)
    membership = world["membership"]
    member_headers = make_member_headers(world["member"]["id"])

    get_success_data(api.hold_membership(membership["id"], {"hold_until": "2026-11-01"}, member_headers))
    held = get_success_data(api.get_branch(world["branch"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert_cents(held["active_membership_count"], 1, "ON_HOLD stays counted")

    get_success_data(api.cancel_membership(membership["id"], member_headers))
    cancelled = get_success_data(api.get_branch(world["branch"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert_cents(cancelled["active_membership_count"], 0, "cancel decrements the count")
