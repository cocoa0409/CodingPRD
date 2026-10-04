"""Corner probes against the error catalogue: pool solvency on both directions."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    ASSOCIATION_ADMIN_HEADERS,
    BRANCH_DIRECTOR_HEADERS,
    assert_branch_pool_invariants,
    assert_cents,
)
from test_helpers import fixtures


def test_approve_fails_when_the_pool_cannot_cover_the_obligation(api):
    """The annualized obligation must fit inside the available pool.

    PRD §3.4: "And the branch's `scholarship_pool_available_cents` must be at
    least the annualized obligation — twelve times the category's
    `monthly_dues_cents` times the `award_pct` — else the approval fails with
    `ERR_POOL_EXHAUSTED`."

    Design: Corner/errors/error_pool_exhausted_on_approve
    """
    # Pool 30,000; dues 8,000 at award 0.50 obligate 48,000.
    world = fixtures.setup_funded_pool(api, amount_cents=30_000)
    application = fixtures.submit_application(api, world, household_size=1, annual_income_cents=2_000_000)
    get_success_data(api.review_application(application["id"], BRANCH_DIRECTOR_HEADERS))

    response = api.approve_application(
        application["id"],
        {"expected_membership_version": world["membership"]["version"]},
        BRANCH_DIRECTOR_HEADERS,
    )
    validate_error(response, "ERR_POOL_EXHAUSTED")

    current = get_success_data(api.get_application(application["id"], BRANCH_DIRECTOR_HEADERS))
    assert current["status"] == "UNDER_REVIEW"
    membership = get_success_data(api.get_membership(world["membership"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert membership["assistance_pct"] == 0


def test_refund_that_would_break_solvency_is_rejected_but_a_safe_one_passes(api):
    """A SCHOLARSHIP refund may not push the available pool below zero; the
    unobligated remainder refunds fine.

    PRD §3.7: "A `SCHOLARSHIP`-designated refund debits the branch pool's
    received counter as well — but only if solvency survives: a refund that
    would push `scholarship_pool_available_cents` below zero is rejected with
    `ERR_POOL_WOULD_GO_NEGATIVE`. A refunded donation lands in the terminal
    `REFUNDED` status."

    Design: Corner/errors/error_refund_pool_would_go_negative
    """
    # Pool 210,000 received; award obligation 48,000 -> available 162,000.
    world = fixtures.setup_funded_pool(api, amount_cents=200_000)
    small = fixtures.create_donation(
        api, world["campaign"]["id"], world["branch"]["id"], amount_cents=10_000, designation="SCHOLARSHIP"
    )
    get_success_data(api.receive_donation(small["id"], BRANCH_DIRECTOR_HEADERS))

    application = fixtures.submit_application(api, world, household_size=1, annual_income_cents=2_000_000)
    get_success_data(api.review_application(application["id"], BRANCH_DIRECTOR_HEADERS))
    get_success_data(
        api.approve_application(
            application["id"],
            {"expected_membership_version": world["membership"]["version"]},
            BRANCH_DIRECTOR_HEADERS,
        )
    )
    middle = get_success_data(api.get_branch(world["branch"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert_cents(middle["scholarship_pool_available_cents"], 162_000, "pool available after approve")

    # Refunding 200,000 would leave available at -38,000: rejected.
    validate_error(
        api.refund_donation(world["donation"]["id"], ASSOCIATION_ADMIN_HEADERS),
        "ERR_POOL_WOULD_GO_NEGATIVE",
    )
    big = get_success_data(api.get_donation(world["donation"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert big["status"] == "RECEIVED"

    # Refunding the 10,000 gift leaves available at 152,000 >= 0: allowed.
    refunded = get_success_data(api.refund_donation(small["id"], ASSOCIATION_ADMIN_HEADERS))
    assert refunded["status"] == "REFUNDED"
    after = get_success_data(api.get_branch(world["branch"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert_cents(after["scholarship_pool_received_cents"], 200_000, "pool received after small refund")
    assert_cents(after["scholarship_pool_available_cents"], 152_000, "pool available after small refund")
    assert_branch_pool_invariants(after)
