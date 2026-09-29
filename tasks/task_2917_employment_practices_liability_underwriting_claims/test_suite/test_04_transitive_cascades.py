"""Multi-hop cascades: payment exhaustion, policy suspension, service revocation."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import api_errors as E
from test_helpers import fixtures as S
from test_helpers import test_users as U
from test_helpers import types as T
from test_helpers.assertions import assert_fields, assert_null, assert_same_instant


def _exhaustion_world(api):
    """A 10,000,000-cent TX policy with an open matter and one pending payment of 12,500,000."""
    S.create_jurisdiction(api, "TX")
    plan_id = S.create_active_rate_plan(api)["id"]
    firm = S.create_panel_firm(
        api,
        name="Lonestar Defense Group",
        tier=T.TIER_REGIONAL,
        jurisdiction_codes=["TX"],
        partner_rate_cents_per_hour=70000,
        associate_rate_cents_per_hour=43000,
        paralegal_rate_cents_per_hour=16000,
        capacity_open_matters=2,
    )
    applicant = S.create_applicant(
        api,
        legal_name="Bayline Foods LLC",
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
    policy = S.bind_policy(api, assessment["id"])
    claim = S.accepted_claim(
        api,
        policy["id"],
        claim_type=T.CLAIM_TYPE_DISCRIMINATION,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        alleged_damages_cents=15000000,
    )
    assignment = S.create_assignment(
        api,
        claim["id"],
        engagement_from="2026-08-01T00:00:00.000Z",
        engagement_to="2026-11-01T00:00:00.000Z",
        budget_cap_cents=2000000,
        panel_firm_id=firm["id"],
    )
    invoice = S.submit_invoice(
        api,
        assignment["id"],
        firm["id"],
        period_start="2026-08-01T00:00:00.000Z",
        period_end="2026-08-31T00:00:00.000Z",
        partner_hours=10.0,
        associate_hours=20.0,
        paralegal_hours=4.0,
        expenses_cents=50000,
    )
    payment = S.pending_payment(api, policy["id"], claim["id"], 12500000)
    return {
        "firm_id": firm["id"],
        "policy_id": policy["id"],
        "claim_id": claim["id"],
        "assignment_id": assignment["id"],
        "invoice_id": invoice["id"],
        "payment_id": payment["id"],
    }


def test_payment_approval_cascades_through_the_claim_onto_the_policy_limit(api):
    """Hops 1 and 2: the waterfall settles the retention then exhausts the aggregate.

    PRD: "In the first hop the claim's `retention_satisfied_cents` and
    `indemnity_paid_cents` are recomputed, and a claim sitting in
    `COVERAGE_ACCEPTED` or `DEFENSE_OPEN` transitions to `RESOLVED`."

    Design: Difficulty/transitive_cascade/payment_approval_exhaustion_cascade_depth_four
    """
    world = _exhaustion_world(api)
    payment = get_success_data(api.approve_payment(world["payment_id"], U.CLAIMS_MANAGER))
    assert_fields(
        payment,
        {
            "status": T.PAYMENT_APPROVED,
            "retention_portion_cents": 2500000,
            "insurer_portion_cents": 10000000,
            "sublimit_bucket": T.BUCKET_FIRST_PARTY,
        },
    )

    claim = get_success_data(api.get_claim(world["claim_id"], U.ADJUSTER))
    assert_fields(
        claim,
        {
            "retention_satisfied_cents": 2500000,
            "indemnity_paid_cents": 10000000,
            "status": T.CLAIM_RESOLVED,
        },
    )

    policy = get_success_data(api.get_policy(world["policy_id"], U.ADJUSTER))
    assert_fields(
        policy,
        {
            "indemnity_paid_cents": 10000000,
            "aggregate_limit_remaining_cents": 0,
            "limit_posture": T.POSTURE_EXHAUSTED,
            "status": T.POLICY_ACTIVE,
        },
    )


def test_exhaustion_closes_the_matter_and_rejects_the_invoice_still_in_flight(api):
    """Hops 3 and 4: funding ceases and the open invoice is held out as REJECTED.

    PRD: "In the third and fourth hops — which fire only when the second hop
    lands the policy on `EXHAUSTED` — defense funding is cut off across the
    whole policy: every defense assignment on any claim of this policy whose
    status is `ACTIVE` or `SUSPENDED_FUNDING` transitions to `CLOSED` with
    `funding_ceased_at` stamped at the logical-clock instant, and then each of
    those assignment mutations propagates to its own billing, so every invoice
    on a closed assignment whose status is `SUBMITTED`, `UNDER_AUDIT` or
    `ADJUSTED` transitions to `REJECTED` with `hold_reason` set to
    `LIMIT_EXHAUSTED`, with `open_matter_count` recomputed for every affected
    firm."

    Design: Difficulty/transitive_cascade/payment_approval_exhaustion_cascade_depth_four
    """
    world = _exhaustion_world(api)
    get_success_data(api.approve_payment(world["payment_id"], U.CLAIMS_MANAGER))

    assignment = get_success_data(api.get_assignment(world["assignment_id"], U.ADJUSTER))
    assert_fields(
        assignment, {"status": T.ASSIGNMENT_CLOSED, "budget_spent_cents": 0}
    )
    assert_same_instant(
        assignment["funding_ceased_at"], "2026-08-01T00:00:00.000Z", "funding_ceased_at"
    )

    invoice = get_success_data(api.get_invoice(world["invoice_id"], U.ADJUSTER))
    assert_fields(
        invoice, {"status": T.INVOICE_REJECTED, "hold_reason": T.HOLD_LIMIT_EXHAUSTED}
    )

    firm = get_success_data(api.get_panel_firm(world["firm_id"], U.ADMIN))
    assert firm["open_matter_count"] == 0


def _suspension_world(api):
    """A CA/TX policy with one accepted harassment claim, an ACTIVE matter and an open invoice."""
    world = S.defended_claim(
        api,
        firm_overrides={
            "name": "Ashford & Vance LLP",
            "tier": T.TIER_NATIONAL,
            "jurisdiction_codes": ["CA", "TX"],
            "partner_rate_cents_per_hour": 92000,
            "associate_rate_cents_per_hour": 51000,
            "paralegal_rate_cents_per_hour": 18000,
            "capacity_open_matters": 3,
        },
        claim_overrides={
            "claim_type": T.CLAIM_TYPE_HARASSMENT,
            "claimant_class": T.CLAIMANT_EMPLOYEE,
            "notice_type": T.NOTICE_LAWSUIT,
            "alleged_damages_cents": 18000000,
        },
        assignment_overrides={
            "engagement_from": "2026-08-01T00:00:00.000Z",
            "engagement_to": "2026-11-01T00:00:00.000Z",
            "budget_cap_cents": 5000000,
        },
    )
    invoice = S.submit_invoice(
        api,
        world["assignment_id"],
        world["firm_id"],
        period_start="2026-08-01T00:00:00.000Z",
        period_end="2026-08-31T00:00:00.000Z",
        partner_hours=10.0,
        associate_hours=20.0,
        paralegal_hours=4.0,
        expenses_cents=50000,
    )
    world["invoice_id"] = invoice["id"]
    return world


def test_suspension_gates_the_claim_without_moving_its_status(api):
    """Hop 1 of the suspend cascade sets the gate flag only.

    PRD: "In the first hop, every claim under this policy whose status is
    `UNDER_REVIEW`, `COVERAGE_ACCEPTED` or `DEFENSE_OPEN` has `coverage_gated`
    set to true, with its `version` incremented by 1."

    Design: Difficulty/transitive_cascade/policy_suspend_cascade_depth_three
    """
    world = _suspension_world(api)
    policy = get_success_data(
        api.suspend_policy(world["policy_id"], "Non-payment of the second instalment", U.UW_MANAGER)
    )
    assert_fields(
        policy,
        {
            "status": T.POLICY_SUSPENDED,
            "suspension_reason": "Non-payment of the second instalment",
            "limit_posture": T.POSTURE_OPEN,
        },
    )
    assert_same_instant(policy["suspended_at"], "2026-08-01T00:00:00.000Z", "suspended_at")

    claim = get_success_data(api.get_claim(world["claim_id"], U.ADJUSTER))
    assert_fields(claim, {"coverage_gated": True, "status": T.CLAIM_DEFENSE_OPEN})


def test_suspension_freezes_matter_funding_and_marks_the_open_invoice(api):
    """Hops 2 and 3 stamp POLICY_SUSPENDED on the matter and its billing.

    PRD: "In the third hop, those assignment mutations propagate into billing:
    every defense invoice on one of those assignments whose status is
    `SUBMITTED`, `UNDER_AUDIT` or `ADJUSTED` has `hold_reason` set to
    `POLICY_SUSPENDED`, again with its `version` incremented by 1."

    Design: Difficulty/transitive_cascade/policy_suspend_cascade_depth_three
    """
    world = _suspension_world(api)
    get_success_data(
        api.suspend_policy(world["policy_id"], "Non-payment of the second instalment", U.UW_MANAGER)
    )

    assignment = get_success_data(api.get_assignment(world["assignment_id"], U.ADJUSTER))
    assert_fields(
        assignment,
        {"status": T.ASSIGNMENT_SUSPENDED_FUNDING, "hold_reason": T.HOLD_POLICY_SUSPENDED},
    )

    invoice = get_success_data(api.get_invoice(world["invoice_id"], U.ADJUSTER))
    assert_fields(
        invoice, {"hold_reason": T.HOLD_POLICY_SUSPENDED, "status": T.INVOICE_SUBMITTED}
    )

    firm = get_success_data(api.get_panel_firm(world["firm_id"], U.ADMIN))
    assert firm["open_matter_count"] == 1


def _stale_credit_world(api):
    """A PRICED assessment resting on two completed risk-management services."""
    S.create_jurisdictions(api, ["CA", "TX"])
    plan_id = S.create_active_rate_plan(api)["id"]
    applicant = S.create_applicant(api)
    hotline = S.create_active_risk_service(
        api,
        applicant["id"],
        service_type=T.SERVICE_HOTLINE,
        credit_pct=0.08,
        effective_from="2026-07-01T00:00:00.000Z",
        effective_to="2027-07-01T00:00:00.000Z",
    )
    handbook = S.create_active_risk_service(
        api,
        applicant["id"],
        service_type=T.SERVICE_HANDBOOK,
        credit_pct=0.05,
        effective_from="2026-07-01T00:00:00.000Z",
        effective_to="2027-07-01T00:00:00.000Z",
    )
    assessment = S.create_priced_assessment(api, applicant["id"], plan_id)
    return {
        "applicant_id": applicant["id"],
        "hotline_id": hotline["id"],
        "handbook_id": handbook["id"],
        "assessment_id": assessment["id"],
        "assessment": assessment,
    }


def test_revoking_one_service_recomputes_the_credit_and_stales_the_assessment(api):
    """Both hops: the applicant credit drops and the PRICED assessment is referred.

    PRD: "Because the applicant's credit basis has changed, every exposure
    assessment belonging to that applicant whose status is `PRICED` transitions
    `PRICED → REFERRED` and has `credit_basis_stale` set to true, with its own
    `version` incremented by 1; an assessment already in `REFERRED` is left in
    `REFERRED` but also has `credit_basis_stale` set to true."

    Design: Difficulty/transitive_cascade/risk_service_revoke_cascade_depth_two
    """
    world = _stale_credit_world(api)
    before = get_success_data(api.get_applicant(world["applicant_id"], U.UNDERWRITER))
    assert_fields(before, {"risk_credit_pct": 0.13, "exposure_score": 65.20})
    assert_fields(
        world["assessment"],
        {
            "status": T.ASSESSMENT_PRICED,
            "credit_basis_stale": False,
            "indicated_premium_cents": 17360516,
        },
    )

    revoked = get_success_data(
        api.revoke_risk_service(
            world["handbook_id"], "Handbook review was never delivered by the vendor", U.UNDERWRITER
        )
    )
    assert_fields(
        revoked,
        {
            "status": T.SERVICE_REVOKED,
            "revocation_reason": "Handbook review was never delivered by the vendor",
        },
    )
    hotline = get_success_data(api.get_risk_service(world["hotline_id"], U.UNDERWRITER))
    assert hotline["status"] == T.SERVICE_ACTIVE

    applicant = get_success_data(api.get_applicant(world["applicant_id"], U.UNDERWRITER))
    assert_fields(applicant, {"risk_credit_pct": 0.08, "exposure_score": 69.20})

    assessment = get_success_data(api.get_assessment(world["assessment_id"], U.UNDERWRITER))
    assert_fields(
        assessment,
        {
            "status": T.ASSESSMENT_REFERRED,
            "credit_basis_stale": True,
            "indicated_premium_cents": 17360516,
            "risk_mgmt_credit_cents": 2700778,
        },
    )


def test_a_staled_assessment_cannot_be_released_until_it_is_repriced(api):
    """The second hop blocks approval with ERR_CREDIT_BASIS_STALE.

    PRD: "and `credit_basis_stale` must be false, else `ERR_CREDIT_BASIS_STALE`,
    which forces a re-price against the current basis before release can be
    attempted again."

    Design: Difficulty/transitive_cascade/risk_service_revoke_cascade_depth_two
    """
    world = _stale_credit_world(api)
    get_success_data(
        api.revoke_risk_service(
            world["handbook_id"], "Handbook review was never delivered by the vendor", U.UNDERWRITER
        )
    )

    validate_error(
        api.approve_assessment(world["assessment_id"], U.UW_MANAGER),
        E.ERR_CREDIT_BASIS_STALE,
        409,
    )

    assessment = get_success_data(api.get_assessment(world["assessment_id"], U.UNDERWRITER))
    assert assessment["status"] == T.ASSESSMENT_REFERRED
    assert_null(assessment, ["approved_by_user_id"])
