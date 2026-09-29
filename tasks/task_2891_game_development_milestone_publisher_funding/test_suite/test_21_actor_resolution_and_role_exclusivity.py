"""The five-step authorization preamble, and the operations each role owns alone."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import factories as f
from test_helpers.assertions import assert_payment_components
from test_helpers.constants import ALPHA_PASSING_METRICS, UNKNOWN_ACTOR_ID
from test_helpers.fixtures import (
    DEFAULT_CRITERIA_1,
    payment_of_milestone,
    setup_single_alpha,
    submit_build,
)
from test_helpers.test_users import (
    NO_AUTH_HEADERS,
    make_headers,
    make_publisher_finance_headers,
    make_publisher_reviewer_headers,
)


def test_corner_actor_resolution_ladder_runs_from_missing_headers_to_function_mismatch(api):
    """Each step of the authorization preamble answers with its own code, and the
    function check is reached only after the role check has passed.

    PRD §2.1 fixes the ladder: an `X-User-ID` "that matches no row of the backing
    table is rejected with `ERR_ACTOR_NOT_FOUND` (401)"; then "Once the actor
    resolves, the server checks that the acting role appears in the endpoint's
    authorized-role list as published in §4; if it does not, the answer is
    `ERR_ROLE_NOT_PERMITTED` (403)"; and only then "Acting as
    `PublisherReviewer` requires a `function` of `REVIEW` or `DUAL` ... A
    mismatch — a `FINANCE`-only operator presenting itself as a reviewer ... is
    rejected with `ERR_ROLE_FUNCTION_MISMATCH` (403)". PRD §2.10 orders the
    preamble 1 to 5, with `ERR_MISSING_AUTH_HEADERS` and `ERR_UNKNOWN_ROLE` ahead
    of any path lookup. PRD §4 lists `POST /publisher-reviews` for
    `PublisherReviewer` alone.

    Design: Corner/rbac/corner_actor_resolution_ladder_from_missing_headers_to_function_mismatch
    """
    scenario = setup_single_alpha(
        api, contractor_budget_cents=0, acceptance_criteria=DEFAULT_CRITERIA_1
    )
    reg = scenario.reg
    build = submit_build(reg, scenario.m1["id"], 1, ALPHA_PASSING_METRICS)
    accepting = f.accepted_review_payload(build["id"], "2026-08-01", 9, 10)

    validate_error(
        api.get_agreement(scenario.agreement_id, NO_AUTH_HEADERS),
        "ERR_MISSING_AUTH_HEADERS",
        401,
    )
    validate_error(
        api.get_agreement(scenario.agreement_id, make_headers(reg.finance_id, "GhostRole")),
        "ERR_UNKNOWN_ROLE",
        401,
    )
    validate_error(
        api.get_agreement(
            scenario.agreement_id, make_publisher_finance_headers(UNKNOWN_ACTOR_ID)
        ),
        "ERR_ACTOR_NOT_FOUND",
        401,
    )
    validate_error(
        api.create_review(accepting, reg.finance), "ERR_ROLE_NOT_PERMITTED", 403
    )
    # The role IS permitted here; only the acting operator's function fails.
    validate_error(
        api.create_review(accepting, make_publisher_reviewer_headers(reg.finance_id)),
        "ERR_ROLE_FUNCTION_MISMATCH",
        403,
    )

    review = validate_success(
        api.create_review(accepting, reg.reviewer), expected_status=201
    )
    assert review["reviewer_user_id"] == reg.reviewer_id, review
    assert scenario.read_milestone(scenario.m1["id"])["status"] == "ACCEPTED"
    rows = get_success_data(api.list_reviews(reg.reviewer, {"build_id": build["id"]}))
    assert len(rows) == 1, f"the four refused calls left a review behind: {rows}"


def test_corner_each_role_owns_its_exclusive_operations_and_shares_only_the_declared_ones(api):
    """Build submission, scope definition, the verdict, authorization and registry
    writes are each closed to the peer roles, and the two shared writes are shared
    with exactly the roles PRD §4 lists.

    PRD §2.1 says the server "checks that the acting role appears in the
    endpoint's authorized-role list as published in §4; if it does not, the answer
    is `ERR_ROLE_NOT_PERMITTED` (403)". PRD §4 lists `POST /milestone-builds` for
    `Developer` alone, `POST /publisher-reviews` for `PublisherReviewer` alone,
    `POST /milestone-payments/{id}/authorize` for `PublisherFinance` alone,
    `POST /publisher-users` for `PlatformAdmin` alone, `POST /milestones` for
    "PlatformAdmin, Developer, PublisherFinance" — no reviewer — and
    `POST /change-orders` for "Developer, PublisherReviewer, PublisherFinance" —
    no platform admin.

    Design: Corner/rbac/corner_each_role_owns_its_exclusive_operations_and_shares_only_the_declared_ones
    """
    scenario = setup_single_alpha(
        api, contractor_budget_cents=0, acceptance_criteria=DEFAULT_CRITERIA_1
    )
    reg = scenario.reg
    milestone_id = scenario.m1["id"]
    build_body = f.build_payload_from_metrics(milestone_id, 1, ALPHA_PASSING_METRICS)

    validate_error(
        api.create_build(build_body, reg.reviewer), "ERR_ROLE_NOT_PERMITTED", 403
    )

    version = scenario.version()
    order_body = f.change_order_payload(
        scenario.agreement_id, milestone_id, "FUNDING_UPLIFT", version,
        "Extra polish funding", requested_amount_cents=100000, ship_date_delta_days=0,
    )
    validate_error(
        api.create_change_order(order_body, reg.admin), "ERR_ROLE_NOT_PERMITTED", 403
    )
    # The same body is lawful for the reviewer, who does appear on that role list.
    proposed = validate_success(
        api.create_change_order(order_body, reg.reviewer), expected_status=201
    )
    assert proposed["state"] == "PROPOSED", proposed

    validate_error(
        api.create_milestone(
            f.milestone_payload(
                scenario.agreement_id, 2, "Reviewer scope", "BETA", 10000, 0,
                ["Defined by the wrong party"],
            ),
            reg.reviewer,
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    build = validate_success(
        api.create_build(build_body, reg.dev), expected_status=201
    )
    accepting = f.accepted_review_payload(build["id"], "2026-08-01", 9, 10)
    validate_error(api.create_review(accepting, reg.dev), "ERR_ROLE_NOT_PERMITTED", 403)
    validate_success(api.create_review(accepting, reg.reviewer), expected_status=201)

    payment = payment_of_milestone(reg, milestone_id)
    validate_error(
        api.authorize_payment(payment["id"], reg.dev, {}), "ERR_ROLE_NOT_PERMITTED", 403
    )
    authorized = validate_success(api.authorize_payment(payment["id"], reg.finance, {}))
    assert authorized["status"] == "AUTHORIZED", authorized
    assert authorized["authorized_by_user_id"] == reg.finance_id, authorized
    assert_payment_components(authorized, 3600000, 0, 3600000, 500, 180000, 3420000)

    validate_error(
        api.create_publisher_user(
            f.publisher_user_payload(reg.publisher_id, "Self-service signup", "REVIEW"),
            reg.finance,
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    operators = get_success_data(api.list_publisher_users(reg.admin))
    assert len(operators) == 2, f"the refused registry write created a row: {operators}"
