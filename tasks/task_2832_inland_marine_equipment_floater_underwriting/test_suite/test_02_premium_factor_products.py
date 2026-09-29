"""Multi-factor products: the five-factor unit premium under its credit cap, and the transit tier."""

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories, fixtures
from test_helpers.test_users import UNDERWRITER


def hardened_site_file(api):
    """A scheduled part on a policy that also owns a perfect-score jobsite."""
    fixtures.publish_rate_rule(api)
    site = fixtures.create_jobsite(api, name="J3 hardened yard")
    site = fixtures.survey_jobsite(api, site["id"], factories.SURVEY_TIER_3)
    policy = fixtures.create_policy(api, policyholder_name="Ridgeline Contractors")
    part = fixtures.create_part(api, policy["id"],
                                factories.scheduled_equipment_part())
    return fixtures.Ctx(policy_id=policy["id"], part_id=part["id"],
                        jobsite=site, jobsite_id=site["id"])


@pytest.mark.parametrize(
    "geo_tracker_installed,on_the_hardened_site,expected_credit_bp,expected_premium_cents",
    [
        (False, False, 0, 173318),
        (True, False, 1500, 147321),
        (False, True, 1200, 152520),
        (True, True, 2500, 129989),
    ],
)
def test_unit_premium_multiplies_five_dimensions_under_a_capped_credit(
        api, geo_tracker_installed, on_the_hardened_site, expected_credit_bp,
        expected_premium_cents):
    """The tracker credit and the site credit add, then the sum is trimmed to the cap.

    PRD: The unit's `rated_premium_cents` is the product of five independent dimensions, rounded exactly once at the very end.
    PRD: The item's `applied_credit_bp` is the lesser of 2,500 basis points and the sum of the two credits, so the cap binds exactly when a tracker on a high-hazard unit (1,500) meets a perfect site (1,200) and the uncapped sum of 2,700 is trimmed to 2,500.
    Design: Difficulty/combinatorial_formula/equipment_premium_five_factor_product_with_credit_cap
    """
    ctx = hardened_site_file(api)
    assert ctx.jobsite["security_score"] == 5
    assert ctx.jobsite["security_tier"] == "TIER_3"

    item = fixtures.schedule_item(
        api, ctx.part_id, ctx.policy_id,
        geo_tracker_installed=geo_tracker_installed,
        assigned_jobsite_id=ctx.jobsite_id if on_the_hardened_site else None)

    assert item["age_years_at_rating"] == 4
    assert item["insured_value_cents"] == 8160000
    assert item["applied_base_rate_bp"] == 180
    assert item["applied_credit_bp"] == expected_credit_bp
    assert item["rated_premium_cents"] == expected_premium_cents
    assert item["status"] == "RATED"


def test_four_credit_combinations_roll_up_into_one_loaded_policy_premium(api):
    """Four otherwise identical units priced at four different credits sum without re-rounding.

    PRD: On the scheduled basis a part's `rated_premium_cents` is the plain integer-cent sum of `rated_premium_cents` over the equipment items on the part whose `status` is `RATED` or `ACTIVE`.
    PRD: The territory expense load is then applied **once, to that single sum** — never per part: multiply `sum_of_part_premiums_cents` by the expense load of the policy's `territory_code`, divide by ten thousand, and round half-up once.
    Design: Difficulty/combinatorial_formula/equipment_premium_five_factor_product_with_credit_cap
    """
    ctx = hardened_site_file(api)
    plain = fixtures.schedule_item(api, ctx.part_id, ctx.policy_id,
                                   description="I_PLAIN")
    tracked = fixtures.schedule_item(api, ctx.part_id, ctx.policy_id,
                                     description="I_TRK",
                                     geo_tracker_installed=True)
    sited = fixtures.schedule_item(api, ctx.part_id, ctx.policy_id,
                                   description="I_SEC",
                                   assigned_jobsite_id=ctx.jobsite_id)
    both = fixtures.schedule_item(api, ctx.part_id, ctx.policy_id,
                                  description="I_FULL",
                                  geo_tracker_installed=True,
                                  assigned_jobsite_id=ctx.jobsite_id)
    assert [plain["rated_premium_cents"], tracked["rated_premium_cents"],
            sited["rated_premium_cents"], both["rated_premium_cents"]] == [
        173318, 147321, 152520, 129989]

    quoted = fixtures.quote(api, ctx.policy_id)
    assert quoted["sum_of_part_premiums_cents"] == 603148
    assert quoted["written_premium_cents"] == 627274
    assert quoted["total_insured_value_cents"] == 32640000
    assert quoted["referral_required"] is False

    part = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert part["rated_premium_cents"] == 603148


TRANSIT_LIMITS = {
    "CAT_TIER_2": dict(transit_owned_limit_cents=10000000,
                       transit_hired_limit_cents=4000000,
                       catastrophe_limit_cents=5000000),
    "CAT_TIER_3": dict(transit_owned_limit_cents=40000000,
                       transit_hired_limit_cents=8000000,
                       catastrophe_limit_cents=9000000),
}


@pytest.mark.parametrize("limits,expected_premium_cents,expected_written_cents", [
    (TRANSIT_LIMITS["CAT_TIER_2"], 553000, 575120),
    (TRANSIT_LIMITS["CAT_TIER_3"], 1596000, 1659840),
])
def test_transit_premium_takes_its_surcharge_from_the_pre_surcharge_base(
        api, limits, expected_premium_cents, expected_written_cents):
    """Two separately rounded components pick the tier, and the tier prices the cat limit.

    PRD: The owned component is `transit_owned_limit_cents` multiplied by 65 basis points and divided by ten thousand, rounded half-up; the hired component is `transit_hired_limit_cents` multiplied by 95 basis points and divided by ten thousand, rounded half-up.
    PRD: The catastrophe tier is then read off that summed, rounded, **pre-surcharge** base: the tier is `CAT_TIER_1` when the base is below 65,000 cents, `CAT_TIER_2` when the base is 65,000 cents or more but below 300,000 cents, and `CAT_TIER_3` when the base is 300,000 cents or more.
    Design: Difficulty/combinatorial_formula/transit_premium_three_limit_tier_keyed_on_pre_surcharge_base
    """
    ctx = fixtures.build_transit_file(api, part_kwargs=limits, quote_it=True)

    part = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert part["rated_premium_cents"] == expected_premium_cents
    assert ctx.quoted["sum_of_part_premiums_cents"] == expected_premium_cents
    assert ctx.quoted["written_premium_cents"] == expected_written_cents
    assert ctx.quoted["total_insured_value_cents"] == 0


def test_two_transit_parts_in_different_tiers_share_one_expense_load(api):
    """Each part carries its own tier, then a single load is taken on the sum.

    PRD: A `TRANSIT` or `INSTALLATION_FLOATER` part has only its single `rated_premium_cents`, computed as described in §3.6 and §3.7, and it contributes that identical figure to both comparison roll-ups.
    PRD: Because the load is applied to the sum rather than per part, two identical `T2_URBAN` parts of 173,318 cents each roll up to 360,501 cents and not 360,502.
    Design: Difficulty/combinatorial_formula/transit_premium_three_limit_tier_keyed_on_pre_surcharge_base
    """
    ctx = fixtures.build_transit_file(
        api, part_kwargs=TRANSIT_LIMITS["CAT_TIER_2"])
    second = fixtures.create_part(
        api, ctx.policy_id,
        factories.transit_part(**TRANSIT_LIMITS["CAT_TIER_3"]))

    quoted = fixtures.quote(api, ctx.policy_id)

    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["rated_premium_cents"] == 553000
    assert get_success_data(api.get_coverage_part(
        second["id"], UNDERWRITER))["rated_premium_cents"] == 1596000
    assert quoted["sum_of_part_premiums_cents"] == 2149000
    assert quoted["written_premium_cents"] == 2234960
    assert quoted["referral_required"] is False

    summary = validate_success(api.get_premium_summary(ctx.policy_id, UNDERWRITER))
    assert summary["expense_load_bp"] == 10400
    assert summary["sum_of_part_premiums_cents"] == 2149000
    assert summary["written_premium_cents"] == 2234960
    assert summary["scheduled_basis_premium_cents"] == 2234960
    assert summary["blanket_basis_premium_cents"] == 2234960
    assert summary["minimum_premium_applied"] is False
    assert summary["total_insured_value_cents"] == 0
