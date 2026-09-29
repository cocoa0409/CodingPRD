"""Boundary precision: the referral threshold, capacity of one, exact exhaustion."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import api_errors as E
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers import test_users as U
from test_helpers import types as T
from test_helpers.assertions import assert_fields


def _threshold_pair(api):
    """Two identical NY risks whose separations differ by exactly one."""
    S.create_jurisdiction(
        api,
        "NY",
        pre_suit_window_days=150,
        class_action_propensity_pct=31.00,
        pre_suit_mediation_required=True,
    )
    plan_id = S.create_active_rate_plan(api)["id"]
    at_threshold = S.create_applicant(
        api,
        legal_name="Meridian Grid Services",
        total_headcount=10000,
        prior_year_separations=2250,
        jurisdiction_headcounts=[{"code": "NY", "headcount": 10000}],
        primary_jurisdiction_code="NY",
    )
    below = S.create_applicant(
        api,
        legal_name="Meridian Grid Holdings",
        total_headcount=10000,
        prior_year_separations=2249,
        jurisdiction_headcounts=[{"code": "NY", "headcount": 10000}],
        primary_jurisdiction_code="NY",
    )
    kwargs = {"requested_aggregate_limit_cents": 100000000, "requested_retention_cents": 0,
              "third_party_coverage_requested": None}
    at_assessment = S.create_assessment(api, at_threshold["id"], plan_id, **kwargs)
    below_assessment = S.create_assessment(api, below["id"], plan_id, **kwargs)
    return {
        "at_applicant_id": at_threshold["id"],
        "below_applicant_id": below["id"],
        "at_assessment_id": at_assessment["id"],
        "below_assessment_id": below_assessment["id"],
    }


def test_a_score_of_exactly_seventy_two_refers_the_assessment(api):
    """The closed threshold refers at 72.00 rather than pricing it.

    PRD: "The referral decision is a closed threshold on the high side: when the
    snapshot score is at or above 72.00 the assessment lands in `REFERRED`, and
    when it is strictly below 72.00 it lands in `PRICED`."

    Design: Difficulty/boundary_precision_check/exposure_score_referral_threshold_exact_72_00
    """
    world = _threshold_pair(api)
    priced = get_success_data(api.price_assessment(world["at_assessment_id"], U.UNDERWRITER))
    assert_fields(
        priced,
        {
            "exposure_score_snapshot": 72.00,
            "turnover_pct_snapshot": 22.50,
            "status": T.ASSESSMENT_REFERRED,
            "limit_load_cents": 0,
            "retention_credit_cents": 0,
        },
    )
    applicant = get_success_data(api.get_applicant(world["at_applicant_id"], U.UNDERWRITER))
    assert_fields(applicant, {"turnover_pct": 22.50, "exposure_score": 72.00})


def test_one_separation_below_the_threshold_stays_priceable(api):
    """A 71.99 score is strictly below 72.00 and lands in PRICED.

    PRD: "when the snapshot score is at or above 72.00 the assessment lands in
    `REFERRED`, and when it is strictly below 72.00 it lands in `PRICED`."

    Design: Difficulty/boundary_precision_check/exposure_score_referral_threshold_exact_72_00
    """
    world = _threshold_pair(api)
    priced = get_success_data(api.price_assessment(world["below_assessment_id"], U.UNDERWRITER))
    assert_fields(
        priced, {"exposure_score_snapshot": 71.99, "status": T.ASSESSMENT_PRICED}
    )
    applicant = get_success_data(api.get_applicant(world["below_applicant_id"], U.UNDERWRITER))
    assert_fields(applicant, {"turnover_pct": 22.49, "exposure_score": 71.99})


def _capacity_one_world(api):
    """One LOCAL CA firm with capacity 1, two accepted claims, one matter already open."""
    S.create_jurisdictions(api, ["CA", "TX"])
    plan_id = S.create_active_rate_plan(api)["id"]
    firm = S.create_panel_firm(
        api,
        name="Harbor Coast Counsel LLP",
        tier=T.TIER_LOCAL,
        jurisdiction_codes=["CA"],
        partner_rate_cents_per_hour=70000,
        associate_rate_cents_per_hour=43000,
        paralegal_rate_cents_per_hour=16000,
        capacity_open_matters=1,
    )
    applicant = S.create_applicant(api)
    assessment = S.create_approved_assessment(api, applicant["id"], plan_id)
    policy = S.bind_policy(api, assessment["id"])
    claim_one = S.accepted_claim(
        api,
        policy["id"],
        claim_type=T.CLAIM_TYPE_HARASSMENT,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        alleged_damages_cents=9000000,
    )
    claim_two = S.accepted_claim(
        api,
        policy["id"],
        claim_type=T.CLAIM_TYPE_HARASSMENT,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        alleged_damages_cents=7000000,
    )
    first = S.create_assignment(
        api,
        claim_one["id"],
        engagement_from="2026-08-01T00:00:00.000Z",
        engagement_to="2026-11-01T00:00:00.000Z",
        budget_cap_cents=3000000,
    )
    return {
        "firm_id": firm["id"],
        "claim_two_id": claim_two["id"],
        "first_assignment": first,
    }


def test_an_overlapping_window_empties_the_pool_of_the_only_firm(api):
    """Capacity one plus one overlapping matter leaves no candidate at all.

    PRD: "If the candidate pool is empty, the engagement is refused with
    `ERR_NO_ELIGIBLE_PANEL_FIRM` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/panel_candidate_pool_empties_at_capacity_one
    """
    world = _capacity_one_world(api)
    assert_fields(
        world["first_assignment"],
        {
            "panel_firm_id": world["firm_id"],
            "selection_reason": T.SELECTION_AUTO_SELECTED,
            "status": T.ASSIGNMENT_ACTIVE,
        },
    )
    firm = get_success_data(api.get_panel_firm(world["firm_id"], U.ADMIN))
    assert firm["blended_rate_cents"] == 48400

    validate_error(
        api.create_assignment(
            world["claim_two_id"],
            F.assignment(
                engagement_from="2026-09-01T00:00:00.000Z",
                engagement_to="2026-12-01T00:00:00.000Z",
                budget_cap_cents=3000000,
            ),
            U.ADJUSTER,
        ),
        E.ERR_NO_ELIGIBLE_PANEL_FIRM,
        422,
    )


def test_a_window_starting_exactly_where_the_last_one_ended_still_selects(api):
    """The half-open overlap rule frees the single capacity slot at the boundary.

    PRD: "`CLOSED` assignments consume no capacity, and a firm at capacity for
    one window can still take a disjoint window."

    Design: Difficulty/boundary_precision_check/panel_candidate_pool_empties_at_capacity_one
    """
    world = _capacity_one_world(api)
    second = S.create_assignment(
        api,
        world["claim_two_id"],
        engagement_from="2026-11-01T00:00:00.000Z",
        engagement_to="2027-01-01T00:00:00.000Z",
        budget_cap_cents=3000000,
    )
    assert_fields(
        second,
        {
            "panel_firm_id": world["firm_id"],
            "selection_reason": T.SELECTION_AUTO_SELECTED,
            "partner_rate_cents_per_hour": 70000,
            "associate_rate_cents_per_hour": 43000,
            "paralegal_rate_cents_per_hour": 16000,
        },
    )
    firm = get_success_data(api.get_panel_firm(world["firm_id"], U.ADMIN))
    assert firm["open_matter_count"] == 2

    claim = get_success_data(api.get_claim(world["claim_two_id"], U.ADJUSTER))
    assert claim["status"] == T.CLAIM_DEFENSE_OPEN


def _exact_exhaustion_world(api):
    """A 10,000,000-cent policy with two accepted claims and two drafted payments."""
    S.create_jurisdiction(api, "TX")
    plan_id = S.create_active_rate_plan(api)["id"]
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
    claim_one = S.accepted_claim(
        api,
        policy["id"],
        claim_type=T.CLAIM_TYPE_DISCRIMINATION,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        first_notice_at="2026-08-02T00:00:00.000Z",
        alleged_damages_cents=13000000,
    )
    claim_two = S.accepted_claim(
        api,
        policy["id"],
        claim_type=T.CLAIM_TYPE_DISCRIMINATION,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        first_notice_at="2026-08-03T00:00:00.000Z",
        alleged_damages_cents=13000000,
    )
    over = S.pending_payment(api, policy["id"], claim_two["id"], 12500001)
    exact = S.pending_payment(api, policy["id"], claim_one["id"], 12500000)
    return {
        "policy_id": policy["id"],
        "claim_one_id": claim_one["id"],
        "claim_two_id": claim_two["id"],
        "over_id": over["id"],
        "over": over,
        "exact_id": exact["id"],
    }


def test_an_insurer_portion_one_cent_over_the_aggregate_is_refused(api):
    """10,000,001 against a 10,000,000 remainder erodes nothing.

    PRD: "and in every bucket, an insurer portion exceeding
    `aggregate_limit_remaining_cents` is `ERR_AGGREGATE_LIMIT_EXHAUSTED`."

    Design: Difficulty/boundary_precision_check/aggregate_limit_exact_exhaustion_boundary
    """
    world = _exact_exhaustion_world(api)
    assert_fields(
        world["over"],
        {
            "insurer_portion_cents": 10000001,
            "retention_portion_cents": 2500000,
            "sublimit_bucket": T.BUCKET_FIRST_PARTY,
        },
    )

    validate_error(
        api.approve_payment(world["over_id"], U.CLAIMS_MANAGER), E.ERR_AGGREGATE_LIMIT_EXHAUSTED, 409
    )

    payment = get_success_data(api.get_payment(world["over_id"], U.ADJUSTER))
    assert payment["status"] == T.PAYMENT_PENDING_APPROVAL
    claim = get_success_data(api.get_claim(world["claim_two_id"], U.ADJUSTER))
    assert claim["status"] == T.CLAIM_COVERAGE_ACCEPTED
    policy = get_success_data(api.get_policy(world["policy_id"], U.ADJUSTER))
    assert_fields(
        policy,
        {
            "aggregate_limit_remaining_cents": 10000000,
            "indemnity_paid_cents": 0,
            "limit_posture": T.POSTURE_OPEN,
        },
    )


def test_an_insurer_portion_exactly_equal_to_the_aggregate_is_allowed(api):
    """Equality passes the strictly-greater-than comparison and exhausts the limit.

    PRD: "A `FIRST_PARTY` payment skips the sublimit stage entirely and is
    bounded only by the aggregate."

    Design: Difficulty/boundary_precision_check/aggregate_limit_exact_exhaustion_boundary
    """
    world = _exact_exhaustion_world(api)
    payment = get_success_data(api.approve_payment(world["exact_id"], U.CLAIMS_MANAGER))
    assert_fields(
        payment, {"status": T.PAYMENT_APPROVED, "insurer_portion_cents": 10000000}
    )

    policy = get_success_data(api.get_policy(world["policy_id"], U.ADJUSTER))
    assert_fields(
        policy,
        {
            "indemnity_paid_cents": 10000000,
            "aggregate_limit_remaining_cents": 0,
            "limit_posture": T.POSTURE_EXHAUSTED,
            "wage_hour_sublimit_remaining_cents": 2500000,
            "third_party_sublimit_remaining_cents": 4000000,
        },
    )

    claim = get_success_data(api.get_claim(world["claim_one_id"], U.ADJUSTER))
    assert_fields(
        claim,
        {
            "retention_satisfied_cents": 2500000,
            "indemnity_paid_cents": 10000000,
            "status": T.CLAIM_RESOLVED,
        },
    )
