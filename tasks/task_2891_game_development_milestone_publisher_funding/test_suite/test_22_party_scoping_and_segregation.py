"""Segregation of duties measured per payment, and party scoping measured per actor."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import factories as f
from test_helpers.assertions import assert_ledger, assert_payment_components
from test_helpers.constants import ALPHA_PASSING_METRICS, FUNCTION_DUAL, FUNCTION_FINANCE
from test_helpers.fixtures import (
    DEFAULT_CRITERIA_1,
    payment_of_milestone,
    record_accepted_review,
    setup_single_alpha,
    setup_twinpeak,
    submit_build,
)
from test_helpers.test_users import (
    make_developer_headers,
    make_publisher_finance_headers,
    make_publisher_reviewer_headers,
)


def test_corner_segregation_of_duties_is_scoped_to_the_milestone_the_reviewer_accepted(api):
    """A `DUAL` operator may not pay for the milestone it accepted, yet may pay for
    a milestone a different operator accepted.

    PRD §2.11 says "the operator authorizing a milestone payment must not be the
    same `PublisherUser` recorded as `reviewer_user_id` on the accepting review of
    that milestone. When they match, the authorization is refused with
    `ERR_SEGREGATION_OF_DUTIES` (403). A `DUAL` operator may therefore accept a
    milestone or pay for it, but never both." The two holdback tiers come from PRD
    §3.6: "A gross of at most 2500000 cents, that is 25000 currency units, attracts
    a tier rate of 0 basis points; a gross above that but at most 10000000 cents,
    100000 currency units, attracts 500 basis points, a five percent holdback".

    Design: Corner/rbac/corner_segregation_of_duties_is_scoped_to_the_milestone_the_reviewer_accepted
    """
    scenario = setup_twinpeak(api, with_dual=True)
    reg = scenario.reg
    dov_id = reg.dual_id
    van_id = reg.add_publisher_user("Van Dual", FUNCTION_DUAL)
    dov_reviewer = make_publisher_reviewer_headers(dov_id)
    dov_finance = make_publisher_finance_headers(dov_id)
    van_reviewer = make_publisher_reviewer_headers(van_id)
    van_finance = make_publisher_finance_headers(van_id)

    build_1 = submit_build(reg, scenario.m1["id"], 1, ALPHA_PASSING_METRICS)
    record_accepted_review(reg, build_1["id"], "2026-08-01", 9, 10, dov_reviewer)
    first_payment = payment_of_milestone(reg, scenario.m1["id"])

    validate_error(
        api.authorize_payment(first_payment["id"], dov_finance, {}),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )
    assert validate_success(api.get_payment(first_payment["id"], reg.finance))["status"] == (
        "PENDING_AUTHORIZATION"
    )

    authorized_first = validate_success(
        api.authorize_payment(first_payment["id"], van_finance, {})
    )
    assert authorized_first["authorized_by_user_id"] == van_id, authorized_first
    assert_payment_components(authorized_first, 3600000, 0, 3600000, 500, 180000, 3420000)

    # M1's acceptance unlocked M2, which a different DUAL operator now accepts.
    build_2 = validate_success(
        api.create_build(
            f.build_payload(scenario.m2["id"], 1, 92.00, 98.50, 85.00, 3, None,
                            "Beta candidate"),
            reg.dev,
        ),
        expected_status=201,
    )
    record_accepted_review(reg, build_2["id"], "2026-08-01", 11, 12, van_reviewer)
    assert scenario.read_milestone(scenario.m2["id"])["status"] == "ACCEPTED"

    second_payment = payment_of_milestone(reg, scenario.m2["id"])
    authorized_second = validate_success(
        api.authorize_payment(second_payment["id"], dov_finance, {})
    )
    assert authorized_second["authorized_by_user_id"] == dov_id, authorized_second
    assert_payment_components(authorized_second, 2400000, 0, 2400000, 0, 0, 2400000)

    assert_ledger(
        scenario.read_agreement(),
        advance_disbursed_cents=5820000,
        holdback_reserve_cents=180000,
    )


def test_corner_non_party_actors_cannot_read_or_write_another_agreement(api):
    """A foreign studio and a foreign publisher are both refused on the same
    agreement, on a read and on a write, while `PlatformAdmin` reads it and the
    party studio writes the identical body.

    PRD §2.1 says "A `Developer` whose `Studio` `id` differs from the agreement's
    `studio_id`, or a `PublisherReviewer` or `PublisherFinance` whose
    `PublisherUser` `publisher_id` differs from the agreement's `publisher_id`,
    receives `ERR_NOT_AGREEMENT_PARTY` (403) ... `PlatformAdmin` is exempt from
    this check. This rule deliberately outranks every state, temporal and fiscal
    rule in the system: an outsider must never be able to probe a milestone's
    internal state by reading the error code that comes back." PRD §2.10 rule 20
    scopes it to "every agreement-scoped read and mutation", and PRD §2.1 adds
    that "a build resolves through its milestone to the agreement".

    Design: Corner/rbac/corner_non_party_actors_cannot_read_or_write_another_agreement
    """
    scenario = setup_single_alpha(
        api,
        title="Aurora Solo",
        advance_total_cents=3600000,
        contractor_budget_cents=0,
        acceptance_criteria=DEFAULT_CRITERIA_1,
        live_ops_quarterly_funding_cents=100000,
    )
    reg = scenario.reg
    assert scenario.read_agreement()["status"] == "ACTIVE"
    assert scenario.read_milestone(scenario.m1["id"])["status"] == "IN_DEVELOPMENT"

    foreign_studio_id = validate_success(
        api.create_studio(
            f.studio_payload("Farshore Games", "hi@farshore.example", "PL"), reg.admin
        ),
        expected_status=201,
    )["id"]
    foreign_publisher_id = validate_success(
        api.create_publisher(
            f.publisher_payload("Rivalcorp", "ops@rivalcorp.example", "US"), reg.admin
        ),
        expected_status=201,
    )["id"]
    rival_finance_id = validate_success(
        api.create_publisher_user(
            f.publisher_user_payload(foreign_publisher_id, "Rho Finance", FUNCTION_FINANCE),
            reg.admin,
        ),
        expected_status=201,
    )["id"]
    foreign_dev = make_developer_headers(foreign_studio_id)
    rival_finance = make_publisher_finance_headers(rival_finance_id)

    # The row exists, so the answer is 403 about the actor, never a 404 about the row.
    validate_error(
        api.get_agreement(scenario.agreement_id, foreign_dev),
        "ERR_NOT_AGREEMENT_PARTY",
        403,
    )
    validate_error(
        api.get_recoupment_summary(scenario.agreement_id, rival_finance),
        "ERR_NOT_AGREEMENT_PARTY",
        403,
    )

    build_body = f.build_payload(
        scenario.m1["id"], 1, 75.00, 96.00, 60.00, 5, None, "Build from a foreign studio"
    )
    validate_error(api.create_build(build_body, foreign_dev), "ERR_NOT_AGREEMENT_PARTY", 403)
    assert scenario.read_milestone(scenario.m1["id"])["latest_build_number"] == 0, (
        "the foreign build was recorded despite the party refusal"
    )
    assert get_success_data(api.list_milestone_builds(scenario.m1["id"], reg.dev)) == []

    admin_read = validate_success(api.get_agreement(scenario.agreement_id, reg.admin))
    assert admin_read["id"] == scenario.agreement_id, admin_read

    # The identical body from the party studio is accepted, so the three denials
    # were about the actor and nothing else.
    party_build = validate_success(
        api.create_build(
            f.build_payload(
                scenario.m1["id"], 1, 75.00, 96.00, 60.00, 5, None,
                "Build from the party studio",
            ),
            reg.dev,
        ),
        expected_status=201,
    )
    assert party_build["milestone_id"] == scenario.m1["id"], party_build
    assert scenario.read_milestone(scenario.m1["id"])["latest_build_number"] == 1
