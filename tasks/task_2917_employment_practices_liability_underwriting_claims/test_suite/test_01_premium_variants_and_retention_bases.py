"""Dual-variant calculations: the two premium variants and the two retention bases."""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers import test_users as U
from test_helpers import types as T
from test_helpers.assertions import assert_fields, assert_money


def _standard_book(api):
    S.create_jurisdiction(api, "CA")
    S.create_jurisdiction(api, "TX")
    plan = S.create_active_rate_plan(api)
    return plan["id"]


def _quote_world(api, with_services):
    """The 400-employee CA/TX applicant priced on the standard plan."""
    plan_id = _standard_book(api)
    applicant = S.create_applicant(api)
    if with_services:
        S.create_active_risk_service(
            api,
            applicant["id"],
            service_type=T.SERVICE_HOTLINE,
            credit_pct=0.08,
            effective_from="2026-07-01T00:00:00.000Z",
            effective_to="2027-07-01T00:00:00.000Z",
        )
        S.advance_clock(api, "2026-08-10T00:00:00.000Z")
        S.create_active_risk_service(
            api,
            applicant["id"],
            service_type=T.SERVICE_HANDBOOK,
            credit_pct=0.05,
            effective_from="2026-08-06T00:00:00.000Z",
            effective_to="2027-08-06T00:00:00.000Z",
        )
    assessment = S.create_priced_assessment(
        api,
        applicant["id"],
        plan_id,
        requested_aggregate_limit_cents=200000000,
        requested_retention_cents=5000000,
        third_party_coverage_requested=True,
    )
    return {"applicant_id": applicant["id"], "plan_id": plan_id, "assessment": assessment}


def test_quote_variant_prices_from_prior_year_separations_alone(api):
    """The QUOTE variant's separations basis is prior_year_separations only.

    PRD: "The **quoting** variant runs at the price transition; its separations
    basis is `prior_year_separations` alone, its risk-management credit is
    summed over services whose status is `ACTIVE` at that moment, and it writes
    `base_premium_cents`, `turnover_load_cents`, `hazard_load_cents`,
    `limit_load_cents`, `retention_credit_cents`, `risk_mgmt_credit_cents` and
    `indicated_premium_cents` onto the assessment."

    Design: Difficulty/dual_variant_calc/premium_quote_vs_bound_audit_variant_divergence
    """
    world = _quote_world(api, with_services=True)
    assessment = world["assessment"]

    assert_fields(
        assessment,
        {
            "turnover_pct_snapshot": 24.00,
            "exposure_score_snapshot": 65.20,
            "base_premium_cents": 14278501,
            "turnover_load_cents": 1998990,
            "hazard_load_cents": 3069878,
            "limit_load_cents": 1427850,
            "retention_credit_cents": 713925,
            "risk_mgmt_credit_cents": 2700778,
            "indicated_premium_cents": 17360516,
            "status": T.ASSESSMENT_PRICED,
        },
    )
    applicant = get_success_data(api.get_applicant(world["applicant_id"], U.UNDERWRITER))
    assert applicant["risk_credit_pct"] == 0.13
    assert applicant["turnover_pct"] == 24.00


def test_bound_audit_variant_diverges_from_the_quote_it_audits(api):
    """The BOUND_AUDIT variant adds separations_since_assessment and drops late credits.

    PRD: "its separations basis is `prior_year_separations` plus
    `separations_since_assessment`, its risk-management credit is summed only
    over services that are both `ACTIVE` and whose `completed_at` is at or
    before the policy's `effective_from` — a service that only became active
    after inception earns no credit on the bound audit — and it writes
    `bound_premium_cents` and `premium_variance_cents` onto the policy."

    Design: Difficulty/dual_variant_calc/premium_quote_vs_bound_audit_variant_divergence
    """
    world = _quote_world(api, with_services=True)
    assessment_id = world["assessment"]["id"]
    get_success_data(api.approve_assessment(assessment_id, U.UW_MANAGER))
    get_success_data(
        api.patch_applicant(
            world["applicant_id"], {"separations_since_assessment": 44}, U.UNDERWRITER
        )
    )

    policy = validate_success(
        api.create_policy(
            F.policy(
                assessment_id,
                effective_from="2026-08-05T00:00:00.000Z",
                effective_to="2027-08-05T00:00:00.000Z",
            ),
            U.UNDERWRITER,
        ),
        201,
    )

    assert_money(policy["bound_premium_cents"], 19844261, "bound_premium_cents")
    assert_money(policy["premium_variance_cents"], 2483745, "premium_variance_cents")
    assert policy["bound_premium_cents"] != 17360516
    assert_fields(
        policy,
        {
            "aggregate_limit_cents": 200000000,
            "per_claim_retention_cents": 5000000,
            "wage_hour_sublimit_cents": 50000000,
            "third_party_sublimit_cents": 80000000,
            "status": T.POLICY_ACTIVE,
            "limit_posture": T.POSTURE_OPEN,
        },
    )
    assessment = get_success_data(api.get_assessment(assessment_id, U.UNDERWRITER))
    assert assessment["status"] == T.ASSESSMENT_BOUND
    assert assessment["indicated_premium_cents"] == 17360516
    applicant = get_success_data(api.get_applicant(world["applicant_id"], U.UNDERWRITER))
    assert applicant["turnover_pct"] == 24.00


def _grouped_wage_hour_world(api):
    """Three accepted wage-and-hour claims aggregated into one related-claim group."""
    plan_id = _standard_book(api)
    applicant = S.create_applicant(api)
    assessment = S.create_approved_assessment(
        api,
        applicant["id"],
        plan_id,
        requested_aggregate_limit_cents=200000000,
        requested_retention_cents=5000000,
        third_party_coverage_requested=True,
    )
    policy = S.bind_policy(api, assessment["id"])
    claims = [
        S.accepted_claim(
            api,
            policy["id"],
            claim_type=T.CLAIM_TYPE_WAGE_AND_HOUR,
            claimant_class=T.CLAIMANT_EMPLOYEE,
            notice_type=T.NOTICE_LAWSUIT,
            first_notice_at="2026-08-01T00:00:00.000Z",
            alleged_damages_cents=damages,
        )
        for damages in (40000000, 30000000, 20000000)
    ]
    group = get_success_data(
        api.create_group(
            F.group(policy["id"], claims[0]["id"], T.AGGREGATION_COMMON_POLICY_PRACTICE), U.CLAIMS_MANAGER
        ),
        201,
    )
    group = get_success_data(
        api.attach_claim_to_group(
            group["id"], F.group_attach(claims[1]["id"], group["version"]), U.CLAIMS_MANAGER
        )
    )
    group = get_success_data(
        api.attach_claim_to_group(
            group["id"], F.group_attach(claims[2]["id"], group["version"]), U.CLAIMS_MANAGER
        )
    )
    return {"policy_id": policy["id"], "claims": claims, "group": group}


def test_group_attachment_moves_every_member_onto_the_group_basis(api):
    """Members keep their own retention figure but apply none of it themselves.

    PRD: "Under `GROUP_AGGREGATED` basis the claim's `applied_retention_cents`
    is 0 — the group bears the retention instead of the claim — and the
    waterfall draws the outstanding retention from the group's
    `shared_retention_cents` less its `retention_paid_cents`, a single pot
    shared across every member."

    Design: Difficulty/dual_variant_calc/retention_per_claim_vs_group_aggregated_variant_divergence
    """
    world = _grouped_wage_hour_world(api)

    for claim in world["claims"]:
        row = get_success_data(api.get_claim(claim["id"], U.ADJUSTER))
        assert_fields(
            row,
            {
                "per_claim_retention_cents": 7500000,
                "retention_basis": T.RETENTION_GROUP_AGGREGATED,
                "applied_retention_cents": 0,
            },
        )
    group = get_success_data(api.get_group(world["group"]["id"], U.CLAIMS_MANAGER))
    assert_fields(
        group,
        {
            "member_count": 3,
            "shared_retention_cents": 7500000,
            "retention_basis_claim_id": world["claims"][0]["id"],
            "status": T.GROUP_OPEN,
        },
    )


def test_group_aggregated_waterfall_fills_one_shared_retention_pot(api):
    """The second tranche on a *different* member finishes the shared retention.

    PRD: "A group is `OPEN` while its `retention_paid_cents` remains strictly
    below its `shared_retention_cents`, and transitions `OPEN → LOCKED` the
    moment an approved payment on any member brings the paid figure to or above
    the shared retention."

    Design: Difficulty/dual_variant_calc/retention_per_claim_vs_group_aggregated_variant_divergence
    """
    world = _grouped_wage_hour_world(api)
    policy_id, claims = world["policy_id"], world["claims"]

    first = S.pending_payment(api, policy_id, claims[0]["id"], 5000000)
    get_success_data(api.approve_payment(first["id"], U.CLAIMS_MANAGER))
    second = S.pending_payment(api, policy_id, claims[1]["id"], 5000000)
    second = get_success_data(api.approve_payment(second["id"], U.CLAIMS_MANAGER))

    first = get_success_data(api.get_payment(first["id"], U.ADJUSTER))
    assert_money(first["retention_portion_cents"], 5000000, "first retention_portion_cents")
    assert_money(first["insurer_portion_cents"], 0, "first insurer_portion_cents")
    assert_money(second["retention_portion_cents"], 2500000, "second retention_portion_cents")
    assert_money(second["insurer_portion_cents"], 2500000, "second insurer_portion_cents")
    assert second["sublimit_bucket"] == T.BUCKET_WAGE_HOUR

    group = get_success_data(api.get_group(world["group"]["id"], U.CLAIMS_MANAGER))
    assert_fields(group, {"retention_paid_cents": 7500000, "status": T.GROUP_LOCKED})
    policy = get_success_data(api.get_policy(policy_id, U.ADJUSTER))
    assert_fields(
        policy,
        {
            "indemnity_paid_cents": 2500000,
            "aggregate_limit_remaining_cents": 197500000,
            "wage_hour_sublimit_remaining_cents": 47500000,
            "limit_posture": T.POSTURE_ERODED,
        },
    )
