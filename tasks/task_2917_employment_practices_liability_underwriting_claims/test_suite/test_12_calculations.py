"""Arithmetic: blended rates, premium bands, the waterfall, panel ranking and credits."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import fixtures as S
from test_helpers import test_users as U
from test_helpers import types as T
from test_helpers.assertions import assert_fields, assert_same_instant


def _hundred_head_tx_applicant(api, legal_name, prior_year_separations=0):
    """A 100-employee single-jurisdiction TX applicant, base premium 3,861,875 cents."""
    return S.create_applicant(
        api,
        legal_name=legal_name,
        total_headcount=100,
        prior_year_separations=prior_year_separations,
        jurisdiction_headcounts=[{"code": "TX", "headcount": 100}],
        primary_jurisdiction_code="TX",
    )


def test_the_blended_rate_is_the_weighted_average_of_the_three_rates(api):
    """0.35 partner, 0.50 associate, 0.15 paralegal, rounded half up to whole cents.

    PRD: "the partner rate is weighted at 0.35, the associate rate at 0.50 and
    the paralegal rate at 0.15 — weights that sum to exactly 1.00 — and the
    weighted sum is rounded half up to whole cents and stored as
    `blended_rate_cents`."

    Design: Corner/calculations/blended_rate_is_the_weighted_average_of_the_three_timekeeper_rates
    """
    S.create_jurisdiction(api, "CA")
    firm_a = S.create_panel_firm(
        api,
        name="Ashford & Vance LLP",
        tier=T.TIER_NATIONAL,
        jurisdiction_codes=["CA"],
        partner_rate_cents_per_hour=92000,
        associate_rate_cents_per_hour=51000,
        paralegal_rate_cents_per_hour=18000,
        capacity_open_matters=3,
    )
    firm_b = S.create_panel_firm(
        api,
        name="Bellweather Rowe LLP",
        tier=T.TIER_REGIONAL,
        jurisdiction_codes=["CA"],
        partner_rate_cents_per_hour=70000,
        associate_rate_cents_per_hour=43000,
        paralegal_rate_cents_per_hour=16000,
        capacity_open_matters=2,
    )
    assert firm_a["blended_rate_cents"] == 60400
    assert firm_b["blended_rate_cents"] == 48400
    assert 18000 < firm_a["blended_rate_cents"] < 92000
    assert_fields(firm_a, {"open_matter_count": 0, "status": T.PANEL_ACTIVE})


def test_the_minimum_premium_floor_is_applied_after_both_credits(api):
    """A tiny risk prices below the floor and is lifted to min_premium_cents.

    PRD: "The net premium is the gross premium less credit E and less credit F,
    and the result is the larger of that net premium and the plan's
    `min_premium_cents`. The minimum-premium floor is applied **after** both
    credits, never before them."

    Design: Corner/calculations/min_premium_floor_applies_after_every_load_and_credit
    """
    S.create_jurisdiction(api, "TX")
    plan_id = S.create_active_rate_plan(api)["id"]
    applicant = S.create_applicant(
        api,
        legal_name="Willow Bay Studio LLC",
        total_headcount=5,
        prior_year_separations=0,
        jurisdiction_headcounts=[{"code": "TX", "headcount": 5}],
        primary_jurisdiction_code="TX",
    )
    priced = S.create_priced_assessment(
        api,
        applicant["id"],
        plan_id,
        requested_aggregate_limit_cents=1000000,
        requested_retention_cents=0,
        third_party_coverage_requested=None,
    )
    assert_fields(
        priced,
        {
            "status": T.ASSESSMENT_PRICED,
            "base_premium_cents": 208750,
            "turnover_load_cents": 0,
            "hazard_load_cents": 14613,
            "limit_load_cents": 0,
            "retention_credit_cents": 0,
            "risk_mgmt_credit_cents": 0,
            "indicated_premium_cents": 750000,
            "exposure_score_snapshot": 20.00,
            "turnover_pct_snapshot": 0.00,
            "priced_by_user_id": U.UW_001,
            "credit_basis_stale": False,
        },
    )


def test_the_turnover_load_band_opens_at_exactly_ten_percent(api):
    """Turnover 10.00 earns the 0.06 band while 9.00 earns nothing.

    PRD: "Component B, the turnover load, is component A multiplied by a load
    fraction read from the applicable turnover percentage: 0.00 when turnover is
    from 0.00 through 9.99, 0.06 from 10.00 through 19.99, 0.14 from 20.00
    through 34.99, and 0.25 at 35.00 or above."

    Design: Corner/calculations/turnover_load_band_boundary_at_exactly_ten_percent_turnover
    """
    S.create_jurisdiction(api, "TX")
    plan_id = S.create_active_rate_plan(api)["id"]
    ten = _hundred_head_tx_applicant(api, "Cedar Point Logistics LLC", 10)
    nine = _hundred_head_tx_applicant(api, "Delta Ridge Staffing LLC", 9)
    assert ten["turnover_pct"] == 10.00
    assert nine["turnover_pct"] == 9.00

    priced_ten = S.create_priced_assessment(
        api,
        ten["id"],
        plan_id,
        requested_aggregate_limit_cents=100000000,
        requested_retention_cents=0,
        third_party_coverage_requested=None,
    )
    priced_nine = S.create_priced_assessment(
        api,
        nine["id"],
        plan_id,
        requested_aggregate_limit_cents=100000000,
        requested_retention_cents=0,
        third_party_coverage_requested=None,
    )
    assert_fields(
        priced_ten,
        {
            "status": T.ASSESSMENT_PRICED,
            "base_premium_cents": 3861875,
            "turnover_load_cents": 231713,
            "hazard_load_cents": 270331,
            "indicated_premium_cents": 4363919,
            "exposure_score_snapshot": 36.00,
        },
    )
    assert_fields(
        priced_nine,
        {
            "status": T.ASSESSMENT_PRICED,
            "base_premium_cents": 3861875,
            "turnover_load_cents": 0,
            "hazard_load_cents": 270331,
            "indicated_premium_cents": 4132206,
            "exposure_score_snapshot": 35.20,
        },
    )


def test_the_retention_credit_bands_open_inclusively_on_the_low_side(api):
    """2,499,999 earns nothing, 2,500,000 earns 0.05 and 10,000,000 earns 0.11.

    PRD: "Credit E, the retention credit, is component A multiplied by a credit
    fraction read from `requested_retention_cents`: 0.00 for a retention from 0
    through 2,499,999 cents, 0.05 from 2,500,000 through 9,999,999 cents, and
    0.11 at 10,000,000 cents or above."

    Design: Corner/calculations/retention_credit_band_boundaries_at_2500000_and_10000000
    """
    S.create_jurisdiction(api, "TX")
    plan_id = S.create_active_rate_plan(api)["id"]
    cases = [
        ("Everline Manufacturing LLC", 2499999, 0, 4132206),
        ("Fairmount Grocers LLC", 2500000, 193094, 3939112),
        ("Granite Way Hotels LLC", 10000000, 424806, 3707400),
    ]
    for legal_name, retention, credit, indicated in cases:
        applicant = _hundred_head_tx_applicant(api, legal_name, 0)
        priced = S.create_priced_assessment(
            api,
            applicant["id"],
            plan_id,
            requested_aggregate_limit_cents=100000000,
            requested_retention_cents=retention,
            third_party_coverage_requested=None,
        )
        assert_fields(
            priced,
            {
                "retention_credit_cents": credit,
                "indicated_premium_cents": indicated,
                "base_premium_cents": 3861875,
                "hazard_load_cents": 270331,
                "exposure_score_snapshot": 28.00,
            },
        )


def test_the_waterfall_fills_the_retention_bucket_before_the_insurer_attaches(api):
    """A 1,000,000 payment is all retention; the next 2,000,000 splits 1,500,000 / 500,000.

    PRD: "The `retention_portion_cents` — the part the insured bears — is the
    smaller of `amount_cents` and that outstanding retention, so the retention
    bucket must fill completely before the insurer attaches."

    Design: Corner/calculations/payment_below_the_retention_fills_the_retention_bucket_first
    """
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
    claim = S.accepted_claim(
        api,
        policy["id"],
        first_notice_at="2026-08-05T00:00:00.000Z",
        alleged_damages_cents=5000000,
    )

    first = S.approved_payment(api, policy["id"], claim["id"], 1000000)
    assert_fields(
        first,
        {
            "retention_portion_cents": 1000000,
            "insurer_portion_cents": 0,
            "sublimit_bucket": T.BUCKET_FIRST_PARTY,
            "status": T.PAYMENT_APPROVED,
        },
    )
    mid_claim = get_success_data(api.get_claim(claim["id"], U.ADJUSTER))
    assert_fields(
        mid_claim, {"retention_satisfied_cents": 1000000, "indemnity_paid_cents": 0}
    )
    mid_policy = get_success_data(api.get_policy(policy["id"], U.ADJUSTER))
    assert_fields(
        mid_policy,
        {
            "indemnity_paid_cents": 0,
            "aggregate_limit_remaining_cents": 10000000,
            "limit_posture": T.POSTURE_OPEN,
        },
    )

    second = S.approved_payment(api, policy["id"], claim["id"], 2000000)
    assert_fields(
        second,
        {
            "retention_portion_cents": 1500000,
            "insurer_portion_cents": 500000,
            "status": T.PAYMENT_APPROVED,
        },
    )
    final_claim = get_success_data(api.get_claim(claim["id"], U.ADJUSTER))
    assert_fields(
        final_claim,
        {
            "retention_satisfied_cents": 2500000,
            "indemnity_paid_cents": 500000,
            "status": T.CLAIM_RESOLVED,
        },
    )
    final_policy = get_success_data(api.get_policy(policy["id"], U.ADJUSTER))
    assert_fields(
        final_policy,
        {
            "indemnity_paid_cents": 500000,
            "aggregate_limit_remaining_cents": 9500000,
            "limit_posture": T.POSTURE_ERODED,
            "status": T.POLICY_ACTIVE,
        },
    )


def test_auto_selection_breaks_the_blended_rate_tie_on_tier_then_capacity(api):
    """The LOCAL firm wins the 48,400 tie; once it is full the REGIONAL firm wins.

    PRD: "Ties are broken first by panel tier ascending, where `LOCAL` ranks
    ahead of `REGIONAL` and `REGIONAL` ahead of `NATIONAL`, and then by
    `created_at` ascending."

    Design: Corner/calculations/panel_auto_selection_ranks_blended_rate_then_tier_then_created_at
    """
    S.create_jurisdiction(api, "CA")
    plan_id = S.create_active_rate_plan(api)["id"]
    national = S.create_panel_firm(
        api,
        name="Ashford & Vance LLP",
        tier=T.TIER_NATIONAL,
        jurisdiction_codes=["CA"],
        partner_rate_cents_per_hour=92000,
        associate_rate_cents_per_hour=51000,
        paralegal_rate_cents_per_hour=18000,
        capacity_open_matters=3,
    )
    regional = S.create_panel_firm(
        api,
        name="Bellweather Rowe LLP",
        tier=T.TIER_REGIONAL,
        jurisdiction_codes=["CA"],
        partner_rate_cents_per_hour=70000,
        associate_rate_cents_per_hour=43000,
        paralegal_rate_cents_per_hour=16000,
        capacity_open_matters=2,
    )
    local = S.create_panel_firm(
        api,
        name="Harbor Coast Counsel LLP",
        tier=T.TIER_LOCAL,
        jurisdiction_codes=["CA"],
        partner_rate_cents_per_hour=70000,
        associate_rate_cents_per_hour=43000,
        paralegal_rate_cents_per_hour=16000,
        capacity_open_matters=1,
    )
    applicant = S.create_applicant(
        api,
        legal_name="Redwood Grove Cafes LLC",
        total_headcount=20,
        prior_year_separations=0,
        jurisdiction_headcounts=[{"code": "CA", "headcount": 20}],
        primary_jurisdiction_code="CA",
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
        claim_type=T.CLAIM_TYPE_HARASSMENT,
        first_notice_at="2026-08-05T00:00:00.000Z",
        alleged_damages_cents=5000000,
    )
    claim_two = S.accepted_claim(
        api,
        policy["id"],
        claim_type=T.CLAIM_TYPE_RETALIATION,
        first_notice_at="2026-08-06T00:00:00.000Z",
        alleged_damages_cents=4000000,
    )

    first = S.create_assignment(
        api,
        claim_one["id"],
        engagement_from="2026-08-06T00:00:00.000Z",
        engagement_to="2026-11-01T00:00:00.000Z",
        budget_cap_cents=3000000,
        panel_firm_id=None,
    )
    assert_fields(
        first,
        {
            "panel_firm_id": local["id"],
            "selection_reason": T.SELECTION_AUTO_SELECTED,
            "partner_rate_cents_per_hour": 70000,
            "associate_rate_cents_per_hour": 43000,
            "paralegal_rate_cents_per_hour": 16000,
            "litigation_guideline_version": 1,
            "budget_spent_cents": 0,
            "budget_remaining_cents": 3000000,
            "status": T.ASSIGNMENT_ACTIVE,
        },
    )
    assert get_success_data(api.get_panel_firm(local["id"], U.ADJUSTER))["open_matter_count"] == 1

    second = S.create_assignment(
        api,
        claim_two["id"],
        engagement_from="2026-08-06T00:00:00.000Z",
        engagement_to="2026-11-01T00:00:00.000Z",
        budget_cap_cents=3000000,
        panel_firm_id=None,
    )
    assert_fields(
        second,
        {"panel_firm_id": regional["id"], "selection_reason": T.SELECTION_AUTO_SELECTED},
    )
    assert second["panel_firm_id"] != national["id"]
    assert get_success_data(api.get_panel_firm(regional["id"], U.ADJUSTER))["open_matter_count"] == 1
    assert get_success_data(api.get_panel_firm(national["id"], U.ADJUSTER))["open_matter_count"] == 0

    for claim_id in (claim_one["id"], claim_two["id"]):
        assert get_success_data(api.get_claim(claim_id, U.ADJUSTER))["status"] == T.CLAIM_DEFENSE_OPEN


def test_the_pre_suit_credit_is_thirty_percent_capped_at_seven_hundred_fifty_thousand(api):
    """600,000 passes through, 750,000 lands on the cap and 900,000 is clipped to it.

    PRD: "The credit itself, `incentive_credit_cents`, is the
    `settlement_offer_cents` multiplied by 0.30 and rounded half up to whole
    cents, then capped at 750,000 cents — the cap is applied **after** the
    rounding."

    Design: Corner/calculations/pre_suit_incentive_credit_reduces_retention_and_caps_at_the_ceiling
    """
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

    cases = [(5000000, 2000000, 600000, 1900000), (6000000, 2500000, 750000, 1750000), (7000000, 3000000, 750000, 1750000)]
    for damages, offer_cents, credit, applied in cases:
        claim = S.accepted_claim(
            api,
            policy["id"],
            notice_type=T.NOTICE_ADMIN_CHARGE,
            first_notice_at="2026-08-01T00:00:00.000Z",
            alleged_damages_cents=damages,
        )
        offer = get_success_data(
            api.create_pre_suit_resolution(
                claim["id"],
                {
                    "offer_expires_at": "2026-09-01T00:00:00.000Z",
                    "settlement_offer_cents": offer_cents,
                },
                U.ADJUSTER,
            ),
            expected_status=201,
        )
        assert_same_instant(
            offer["mediation_offered_at"], "2026-08-01T00:00:00.000Z", "mediation_offered_at"
        )
        accepted = get_success_data(api.accept_pre_suit_resolution(offer["id"], U.ADJUSTER))
        assert_fields(
            accepted,
            {
                "status": T.RESOLUTION_ACCEPTED,
                "elapsed_days_at_accept": 0,
                "incentive_credit_cents": credit,
            },
        )
        after = get_success_data(api.get_claim(claim["id"], U.ADJUSTER))
        assert_fields(
            after,
            {
                "pre_suit_credit_cents": credit,
                "applied_retention_cents": applied,
                "per_claim_retention_cents": 2500000,
                "status": T.CLAIM_RESOLVED,
            },
        )
