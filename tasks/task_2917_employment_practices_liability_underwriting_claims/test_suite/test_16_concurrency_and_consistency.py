"""Optimistic-concurrency guards on the three parent rows, and same-request visibility."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated

from test_helpers import api_errors as E
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers import test_users as U
from test_helpers import types as T
from test_helpers.assertions import assert_fields, assert_null


def test_assessment_create_rejects_a_stale_applicant_version_then_accepts_the_refreshed_one(api):
    """A PATCH between read and write costs the writer its quote, but only once.

    PRD: "Opening an exposure assessment requires `expected_applicant_version` to
    equal the current `version` of the `Applicant` named by `applicant_id`. A
    mismatch is rejected with `ERR_STALE_APPLICANT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/assessment_create_rejects_a_stale_applicant_version_then_accepts_the_refreshed_one
    """
    S.create_jurisdiction(api, "TX")
    plan_id = S.create_active_rate_plan(api)["id"]
    applicant = S.create_applicant(
        api,
        legal_name="Coldwater Rail LLC",
        total_headcount=40,
        prior_year_separations=4,
        jurisdiction_headcounts=[{"code": "TX", "headcount": 40}],
        primary_jurisdiction_code="TX",
    )
    assert applicant["turnover_pct"] == 10.00

    patched = get_success_data(
        api.patch_applicant(applicant["id"], {"prior_year_separations": 9}, U.UNDERWRITER)
    )
    assert patched["turnover_pct"] == 22.50
    assert patched["version"] == applicant["version"] + 1

    def draft(expected_version):
        return api.create_assessment(
            F.assessment(
                applicant["id"],
                plan_id,
                expected_version,
                requested_aggregate_limit_cents=10000000,
                requested_retention_cents=2500000,
                third_party_coverage_requested=None,
            ),
            U.UNDERWRITER,
        )

    validate_error(draft(applicant["version"]), E.ERR_STALE_APPLICANT_VERSION, 412)
    _rows, meta = validate_paginated(
        api.list_assessments(U.UNDERWRITER, {"applicant_id": applicant["id"]})
    )
    assert meta["total_count"] == 0, "the 412 must not have created an assessment"

    # A failed OCC write does not itself bump the parent version.
    refreshed = get_success_data(api.get_applicant(applicant["id"], U.UNDERWRITER))
    assert refreshed["version"] == patched["version"]

    assessment = get_success_data(draft(refreshed["version"]), 201)
    assert_fields(
        assessment,
        {
            "applicant_id": applicant["id"],
            "status": T.ASSESSMENT_DRAFT,
            "requested_retention_cents": 2500000,
        },
    )
    _rows, meta = validate_paginated(
        api.list_assessments(U.UNDERWRITER, {"applicant_id": applicant["id"]})
    )
    assert meta["total_count"] == 1


def _tranche_world(api, legal_name):
    """An ACTIVE 10,000,000-cent TX policy carrying one accepted 2,500,000-retention claim."""
    S.create_jurisdiction(api, "TX")
    plan_id = S.create_active_rate_plan(api)["id"]
    applicant = S.create_applicant(
        api,
        legal_name=legal_name,
        total_headcount=40,
        prior_year_separations=4,
        jurisdiction_headcounts=[{"code": "TX", "headcount": 40}],
        primary_jurisdiction_code="TX",
    )
    assessment = S.create_approved_assessment(
        api,
        applicant["id"],
        plan_id,
        requested_aggregate_limit_cents=10000000,
        requested_retention_cents=2500000,
        third_party_coverage_requested=None,
    )
    return S.bind_policy(api, assessment["id"])["id"]


def test_payment_create_rejects_a_stale_policy_version_after_the_first_tranche(api):
    """Drafting bumps the policy, so the second tranche must re-read it first.

    PRD: "Recording an indemnity payment on a claim requires
    `expected_policy_version` to equal the current `version` of the owning
    `Policy`. A mismatch is rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412)."

    PRD: "Drafting sets `created_by_user_id` to the acting `X-User-ID`, copies the
    claim's `coverage_bucket` into the payment's `sublimit_bucket`, creates the
    payment in `PENDING_APPROVAL`, and increments the owning policy's `version` by
    1 — which is exactly why a client drafting a second tranche must re-read the
    policy first."

    Design: Corner/cross_cutting_complexity_layers/payment_create_rejects_a_stale_policy_version_after_the_first_tranche
    """
    policy_id = _tranche_world(api, "Dunmore Textiles LLC")
    claim = S.accepted_claim(
        api,
        policy_id,
        claim_type=T.CLAIM_TYPE_HARASSMENT,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        first_notice_at="2026-08-02T00:00:00.000Z",
        alleged_damages_cents=6000000,
    )
    version_1 = get_success_data(api.get_policy(policy_id, U.UNDERWRITER))["version"]

    first = get_success_data(
        api.create_payment(
            claim["id"], F.payment(1000000, version_1, payment_basis=T.PAYMENT_BASIS_SETTLEMENT), U.ADJUSTER
        ),
        201,
    )
    assert_fields(
        first,
        {
            "status": T.PAYMENT_PENDING_APPROVAL,
            "sublimit_bucket": T.BUCKET_FIRST_PARTY,
            "retention_portion_cents": 1000000,
            "insurer_portion_cents": 0,
        },
    )

    validate_error(
        api.create_payment(
            claim["id"], F.payment(1200000, version_1, payment_basis=T.PAYMENT_BASIS_SETTLEMENT), U.ADJUSTER
        ),
        E.ERR_STALE_POLICY_VERSION,
        412,
    )

    version_2 = get_success_data(api.get_policy(policy_id, U.UNDERWRITER))["version"]
    assert version_2 == version_1 + 1, "the successful draft bumped once, the 412 not at all"

    second = get_success_data(
        api.create_payment(
            claim["id"], F.payment(1200000, version_2, payment_basis=T.PAYMENT_BASIS_SETTLEMENT), U.ADJUSTER
        ),
        201,
    )
    # Only APPROVED payments consume the retention, so the second draft sees it unfilled.
    assert_fields(
        second, {"retention_portion_cents": 1200000, "insurer_portion_cents": 0}
    )

    policy = get_success_data(api.get_policy(policy_id, U.UNDERWRITER))
    assert policy["version"] == version_2 + 1
    assert_fields(
        policy,
        {"indemnity_paid_cents": 0, "aggregate_limit_remaining_cents": 10000000},
    )


def test_group_attach_rejects_a_stale_group_version_and_the_retry_re_derives_the_retention(api):
    """Every attach re-derives the aggregation, so the guard forces a re-read.

    PRD: "Attaching a claim to a related-claim group requires
    `expected_related_claim_group_version` to equal the current `version` of the
    `RelatedClaimGroup` named in the path. A mismatch is rejected with
    `ERR_STALE_GROUP_VERSION` (HTTP 412)."

    PRD: "`shared_retention_cents` is the **largest** `per_claim_retention_cents`
    among all member claims, scanned without any status filter so that denied and
    closed members still count; `retention_basis_claim_id` names the member
    achieving that maximum, with ties broken by the earliest member `created_at`."

    Design: Corner/cross_cutting_complexity_layers/group_attach_rejects_a_stale_group_version_and_the_retry_re_derives_the_shared_retention
    """
    policy_id = _tranche_world(api, "Elmridge Poultry LLC")
    c1 = S.accepted_claim(
        api,
        policy_id,
        claim_type=T.CLAIM_TYPE_HARASSMENT,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        first_notice_at="2026-08-02T00:00:00.000Z",
        alleged_damages_cents=6000000,
    )
    c2 = S.accepted_claim(
        api,
        policy_id,
        claim_type=T.CLAIM_TYPE_RETALIATION,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        first_notice_at="2026-08-03T00:00:00.000Z",
        alleged_damages_cents=2000000,
    )
    c3 = S.accepted_claim(
        api,
        policy_id,
        claim_type=T.CLAIM_TYPE_WAGE_AND_HOUR,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        first_notice_at="2026-08-04T00:00:00.000Z",
        alleged_damages_cents=3000000,
        claimant_count=12,
    )
    assert c1["per_claim_retention_cents"] == 2500000
    assert c2["per_claim_retention_cents"] == 2500000
    assert c3["per_claim_retention_cents"] == 3750000

    group = get_success_data(
        api.create_group(
            F.group(policy_id, c1["id"], aggregation_basis=T.AGGREGATION_COMMON_POLICY_PRACTICE),
            U.CLAIMS_MANAGER,
        ),
        201,
    )
    assert_fields(
        group,
        {
            "member_count": 1,
            "shared_retention_cents": 2500000,
            "retention_basis_claim_id": c1["id"],
            "status": T.GROUP_OPEN,
        },
    )

    after_c2 = get_success_data(
        api.attach_claim_to_group(
            group["id"], F.group_attach(c2["id"], group["version"]), U.CLAIMS_MANAGER
        )
    )
    # Tie on 2,500,000 is broken by the earliest member created_at, which is c1.
    assert_fields(
        after_c2,
        {
            "member_count": 2,
            "shared_retention_cents": 2500000,
            "retention_basis_claim_id": c1["id"],
        },
    )
    assert after_c2["version"] == group["version"] + 1

    validate_error(
        api.attach_claim_to_group(
            group["id"], F.group_attach(c3["id"], group["version"]), U.CLAIMS_MANAGER
        ),
        E.ERR_STALE_GROUP_VERSION,
        412,
    )
    refreshed = get_success_data(api.get_group(group["id"], U.CLAIMS_MANAGER))
    assert refreshed["version"] == after_c2["version"]
    assert refreshed["member_count"] == 2
    assert_null(get_success_data(api.get_claim(c3["id"], U.ADJUSTER)), ["related_claim_group_id"])

    after_c3 = get_success_data(
        api.attach_claim_to_group(
            group["id"], F.group_attach(c3["id"], refreshed["version"]), U.CLAIMS_MANAGER
        )
    )
    assert_fields(
        after_c3,
        {
            "member_count": 3,
            "shared_retention_cents": 3750000,
            "retention_basis_claim_id": c3["id"],
        },
    )
    assert after_c3["version"] == refreshed["version"] + 1

    member = get_success_data(api.get_claim(c3["id"], U.ADJUSTER))
    assert_fields(
        member,
        {
            "related_claim_group_id": group["id"],
            "retention_basis": T.RETENTION_GROUP_AGGREGATED,
            "applied_retention_cents": 0,
            "per_claim_retention_cents": 3750000,
        },
    )


def test_every_cross_entity_side_effect_is_readable_in_the_very_next_request(api):
    """Derived values land inside the write that causes them: no second read, no lag.

    PRD: "Only `ACTIVE` services count toward the credit."

    PRD: "Every one of the four service transitions that changes the `ACTIVE` set
    — complete, revoke from `PENDING`, revoke from `ACTIVE`, and lapse —
    recomputes both `risk_credit_pct` and the applicant's `exposure_score` and
    increments the applicant's `version` by 1."

    PRD: "The firm's `open_matter_count` starts at 0 and thereafter always equals
    the number of defense assignments naming that firm whose status is `ACTIVE` or
    `SUSPENDED_FUNDING`."

    Design: Corner/consistency_model/every_cross_entity_side_effect_is_readable_in_the_very_next_request
    """
    S.create_jurisdiction(api, "TX")
    plan_id = S.create_active_rate_plan(api)["id"]
    firm = S.create_panel_firm(
        api,
        name="Ashford & Vance LLP",
        tier=T.TIER_NATIONAL,
        jurisdiction_codes=["TX"],
        partner_rate_cents_per_hour=92000,
        associate_rate_cents_per_hour=51000,
        paralegal_rate_cents_per_hour=18000,
        capacity_open_matters=3,
    )
    # 92000*0.35 + 51000*0.50 + 18000*0.15 = 32200 + 25500 + 2700.
    assert_fields(firm, {"blended_rate_cents": 60400, "open_matter_count": 0})

    applicant = S.create_applicant(
        api,
        legal_name="Fairhaven Logistics LLC",
        total_headcount=40,
        prior_year_separations=4,
        jurisdiction_headcounts=[{"code": "TX", "headcount": 40}],
        primary_jurisdiction_code="TX",
    )
    assert_fields(
        applicant,
        {
            "turnover_pct": 10.00,
            "hazard_load_pct": 0.070,
            "risk_credit_pct": 0.00,
            "exposure_score": 28.00,
        },
    )

    service = S.create_risk_service(
        api,
        applicant["id"],
        service_type=T.SERVICE_HOTLINE,
        credit_pct=0.06,
        effective_from="2026-08-01T00:00:00.000Z",
        effective_to="2027-08-01T00:00:00.000Z",
    )
    assert service["status"] == T.SERVICE_PENDING
    # A PENDING service is excluded outright, not merely delayed.
    still_uncredited = get_success_data(api.get_applicant(applicant["id"], U.UNDERWRITER))
    assert_fields(still_uncredited, {"risk_credit_pct": 0.00, "exposure_score": 28.00})

    completed = get_success_data(api.complete_risk_service(service["id"], U.UNDERWRITER))
    assert completed["status"] == T.SERVICE_ACTIVE
    credited = get_success_data(api.get_applicant(applicant["id"], U.UNDERWRITER))
    assert_fields(credited, {"risk_credit_pct": 0.06, "exposure_score": 22.00})

    assessment = get_success_data(
        api.create_assessment(
            F.assessment(
                applicant["id"],
                plan_id,
                credited["version"],
                requested_aggregate_limit_cents=10000000,
                requested_retention_cents=2500000,
                third_party_coverage_requested=None,
            ),
            U.UNDERWRITER,
        ),
        201,
    )
    priced = get_success_data(api.price_assessment(assessment["id"], U.UNDERWRITER))
    assert_fields(
        priced,
        {
            "status": T.ASSESSMENT_PRICED,
            "exposure_score_snapshot": 22.00,
            "base_premium_cents": 1670000,
            "turnover_load_cents": 100200,
            "hazard_load_cents": 116900,
            "limit_load_cents": 0,
            "retention_credit_cents": 83500,
            "risk_mgmt_credit_cents": 113226,
            "indicated_premium_cents": 1690374,
        },
    )

    get_success_data(api.approve_assessment(assessment["id"], U.UW_MANAGER))
    policy = get_success_data(
        api.create_policy(F.policy(assessment["id"]), U.UNDERWRITER), 201
    )
    assert_fields(
        policy,
        {
            "wage_hour_sublimit_cents": 2500000,
            "third_party_sublimit_cents": 4000000,
            "aggregate_limit_remaining_cents": 10000000,
        },
    )

    claim = S.accepted_claim(
        api,
        policy["id"],
        claim_type=T.CLAIM_TYPE_DISCRIMINATION,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        first_notice_at="2026-08-02T00:00:00.000Z",
        alleged_damages_cents=4000000,
    )
    assignment = S.create_assignment(
        api,
        claim["id"],
        engagement_from="2026-08-06T00:00:00.000Z",
        engagement_to="2026-11-01T00:00:00.000Z",
        budget_cap_cents=3000000,
        panel_firm_id=firm["id"],
    )
    assert assignment["partner_rate_cents_per_hour"] == 92000

    assert get_success_data(api.get_panel_firm(firm["id"], U.ADJUSTER))["open_matter_count"] == 1
    assert get_success_data(api.get_claim(claim["id"], U.ADJUSTER))["status"] == T.CLAIM_DEFENSE_OPEN
