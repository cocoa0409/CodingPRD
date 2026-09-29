"""Exact cutoffs: the constructive total loss, the reporting cliff, the catastrophe tier and the floor."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.test_users import ADJUSTER, UNDERWRITER


def two_rigs_with_one_claim_each(api, at_threshold_estimate, below_threshold_estimate):
    """Two identical rigs, each carrying an inspected claim on its own estimate."""
    fixtures.publish_rate_rule(api)
    policy = fixtures.create_policy(api, policyholder_name="Twin Rig Contractors")
    part = fixtures.create_part(api, policy["id"],
                                factories.scheduled_equipment_part())
    rig_at = fixtures.schedule_item(api, part["id"], policy["id"],
                                    description="Rig AT")
    rig_below = fixtures.schedule_item(api, part["id"], policy["id"],
                                       description="Rig BELOW")
    quoted = fixtures.quote(api, policy["id"])
    fixtures.bind(api, policy["id"])
    fixtures.activate(api, policy["id"])
    fixtures.activate_item(api, rig_at["id"])
    fixtures.activate_item(api, rig_below["id"])
    fixtures.set_clock(api, "2026-08-20T00:00:00Z")
    ctx = fixtures.Ctx(policy_id=policy["id"], part_id=part["id"], quoted=quoted)

    def inspected(item_id, estimate):
        claim = get_success_data(api.create_claim(
            policy["id"],
            factories.claim(part["id"], loss_date="2026-08-15",
                            loss_type="COLLISION", equipment_item_id=item_id),
            UNDERWRITER))
        return get_success_data(api.inspect_claim(
            claim["id"], factories.inspection(estimate, 8160000), ADJUSTER))

    ctx["claim_at"] = inspected(rig_at["id"], at_threshold_estimate)
    ctx["claim_below"] = inspected(rig_below["id"], below_threshold_estimate)
    return ctx


def test_an_estimate_exactly_at_the_threshold_is_already_a_constructive_total_loss(api):
    """Seventy-five percent of the valuation to the cent bars the repair basis.

    PRD: Choosing `REPAIR` additionally requires that either the claim has no `equipment_item_id` at all, or its `repair_estimate_cents` is strictly below `constructive_total_loss_threshold_cents`; an equipment repair estimate that has reached the threshold is refused with `ERR_CONSTRUCTIVE_TOTAL_LOSS`.
    PRD: The `REPAIR` variant remains computable and is still returned on the worksheet in that situation; it is simply no longer selectable, which is what makes the two bases non-symmetric.
    Design: Difficulty/boundary_precision_check/constructive_total_loss_threshold_inclusive_boundary
    """
    ctx = two_rigs_with_one_claim_each(api, 6120000, 6119999)
    assert ctx.quoted["written_premium_cents"] == 360501
    at = ctx.claim_at
    assert at["constructive_total_loss_threshold_cents"] == 6120000
    assert at["repair_basis_settlement_cents"] == 6020000
    assert at["total_loss_basis_settlement_cents"] == 8060000

    worksheet = validate_success(
        api.get_settlement_worksheet(at["id"], ADJUSTER))
    assert worksheet["constructive_total_loss_reached"] is True
    assert worksheet["repair_basis_selectable"] is False
    assert worksheet["repair_basis_settlement_cents"] == 6020000

    refused = api.adjust_claim(at["id"], factories.adjustment("REPAIR"), ADJUSTER)

    validate_error(refused, "ERR_CONSTRUCTIVE_TOTAL_LOSS", 409)
    unchanged = get_success_data(api.get_claim(at["id"], ADJUSTER))
    assert unchanged["adjustment_status"] == "INSPECTED"
    assert unchanged["adjustment_basis"] is None
    assert unchanged["settlement_amount_cents"] is None


def test_one_cent_below_the_threshold_still_pays_on_the_repair_basis(api):
    """The same valuation, one cent less estimate, and the repair branch stays open.

    PRD: The comparison is inclusive on the threshold: an estimate exactly equal to seventy-five percent of the valuation is already a constructive total loss.
    PRD: The `REPAIR` branch stores the supplied `loss_of_use_days_claimed`, recomputes `loss_of_use_paid_cents`, sets `settlement_amount_cents` to `repair_basis_settlement_cents`, moves the claim `INSPECTED` → `REPAIR_APPROVED`, and leaves `salvage_status` dormant at `NOT_APPLICABLE`; the damaged unit stays on risk and the part's premium is untouched.
    Design: Difficulty/boundary_precision_check/constructive_total_loss_threshold_inclusive_boundary
    """
    ctx = two_rigs_with_one_claim_each(api, 6120000, 6119999)
    below = ctx.claim_below
    assert below["constructive_total_loss_threshold_cents"] == 6120000

    worksheet = validate_success(
        api.get_settlement_worksheet(below["id"], ADJUSTER))
    assert worksheet["constructive_total_loss_reached"] is False
    assert worksheet["repair_basis_selectable"] is True

    approved = validate_success(api.adjust_claim(
        below["id"], factories.adjustment("REPAIR"), ADJUSTER))

    assert approved["adjustment_status"] == "REPAIR_APPROVED"
    assert approved["settlement_amount_cents"] == 6019999
    assert approved["total_loss_basis_settlement_cents"] == 8060000
    assert approved["salvage_status"] == "NOT_APPLICABLE"


AUGUST = ("2026-08-01", "2026-08-31")


def two_reporting_parts_each_with_a_claim(api):
    """Two reporting-form parts differing only in the value their August report declared."""
    fixtures.publish_rate_rule(api)
    policy = fixtures.create_policy(api,
                                    policyholder_name="Yard Stock Reporting Co")
    parts = [fixtures.create_part(api, policy["id"],
                                  factories.reporting_form_part(
                                      per_item_limit_cents=20000000))
             for _ in range(2)]
    items = [fixtures.schedule_item(api, part["id"], policy["id"],
                                    description=f"Stock rig {index}")
             for index, part in enumerate(parts, start=1)]
    fixtures.quote(api, policy["id"])
    fixtures.bind(api, policy["id"])
    fixtures.activate(api, policy["id"])
    for item in items:
        fixtures.activate_item(api, item["id"])
    fixtures.set_clock(api, "2026-09-05T00:00:00Z")

    reports = []
    for part, declared in zip(parts, (9000000, 8999000)):
        filed = fixtures.file_value_report(api, part["id"], AUGUST[0], AUGUST[1],
                                           declared)
        reports.append(get_success_data(
            api.adjudicate_value_report(filed["id"], UNDERWRITER)))

    claims = []
    for part, item in zip(parts, items):
        claim = get_success_data(api.create_claim(
            policy["id"],
            factories.claim(part["id"], loss_date="2026-08-20",
                            loss_type="THEFT", equipment_item_id=item["id"]),
            UNDERWRITER))
        claims.append(get_success_data(api.inspect_claim(
            claim["id"], factories.inspection(4000000, 10000000), ADJUSTER)))

    return fixtures.Ctx(policy_id=policy["id"], part_full=parts[0]["id"],
                        part_short=parts[1]["id"], report_full=reports[0],
                        report_short=reports[1], claim_full=claims[0],
                        claim_short=claims[1])


def test_a_reported_ratio_of_exactly_nine_thousand_basis_points_pays_in_full(api):
    """Ninety percent declared to the cent snaps the factor back to ten thousand.

    PRD: Otherwise the reported ratio in basis points is the governing report's `reported_value_cents` multiplied by ten thousand, divided by the claim's `actual_value_at_loss_cents`, rounded half-up once; the factor is 10000 when that ratio is at least 9,000 basis points, and is the ratio itself when it is below 9,000.
    PRD: The threshold is inclusive, so a ratio of exactly 9,000 basis points snaps to full reporting.
    Design: Difficulty/boundary_precision_check/underreporting_full_reporting_threshold_inclusive_boundary
    """
    ctx = two_reporting_parts_each_with_a_claim(api)
    assert ctx.report_full["status"] == "ACCEPTED"
    assert ctx.report_full["period_days"] == 31
    assert ctx.report_full["period_earned_premium_cents"] == 19110
    assert ctx.report_full["late_penalty_cents"] == 0
    assert ctx.claim_full["underreporting_factor_bp"] == 10000
    assert ctx.claim_full["repair_basis_settlement_cents"] == 3900000

    worksheet = validate_success(
        api.get_settlement_worksheet(ctx.claim_full["id"], ADJUSTER))
    assert worksheet["claim_limit_cents"] == 20000000
    assert worksheet["underreporting_factor_bp"] == 10000

    approved = validate_success(api.adjust_claim(
        ctx.claim_full["id"], factories.adjustment("REPAIR"), ADJUSTER))

    assert approved["settlement_amount_cents"] == 3900000
    assert get_success_data(api.get_coverage_part(
        ctx.part_full, UNDERWRITER))["earned_reported_premium_cents"] == 19110


def test_one_basis_point_short_of_the_cliff_cuts_the_claim_by_the_whole_ratio(api):
    """A thousand cents less declared moves the settlement by four hundred thousand.

    PRD: The cliff is deliberate: declare ninety percent or more of the true value and the insurer pays in full, declare one basis point less and the claim is cut by the whole shortfall ratio rather than by the difference.
    PRD: Multiply `repair_estimate_cents` by `underreporting_factor_bp`, divide by ten thousand and round half-up **once**; take the smaller of that figure and `claim_limit_cents`; subtract the part's `deductible_cents`; if the result is below zero use zero; then add `loss_of_use_paid_cents`.
    Design: Difficulty/boundary_precision_check/underreporting_full_reporting_threshold_inclusive_boundary
    """
    ctx = two_reporting_parts_each_with_a_claim(api)
    assert ctx.report_short["status"] == "ACCEPTED"
    assert ctx.report_short["period_earned_premium_cents"] == 19107
    assert ctx.claim_short["underreporting_factor_bp"] == 8999
    assert ctx.claim_short["repair_basis_settlement_cents"] == 3499600
    assert (ctx.claim_full["repair_basis_settlement_cents"]
            - ctx.claim_short["repair_basis_settlement_cents"]) == 400400

    approved = validate_success(api.adjust_claim(
        ctx.claim_short["id"], factories.adjustment("REPAIR"), ADJUSTER))

    assert approved["settlement_amount_cents"] == 3499600
    assert get_success_data(api.get_coverage_part(
        ctx.part_short, UNDERWRITER))["earned_reported_premium_cents"] == 19107


def two_transit_parts_astride_the_tier_cutoff(api):
    """One part whose base rounds to 64994 and one whose base lands on 65000."""
    policy = fixtures.create_policy(api, policyholder_name="Cutoff Cartage")
    below = fixtures.create_part(api, policy["id"], factories.transit_part(
        transit_owned_limit_cents=9999000, transit_hired_limit_cents=0,
        catastrophe_limit_cents=5000000))
    at = fixtures.create_part(api, policy["id"], factories.transit_part(
        transit_owned_limit_cents=10000000, transit_hired_limit_cents=0,
        catastrophe_limit_cents=5000000))
    return fixtures.Ctx(policy_id=policy["id"], below_id=below["id"],
                        at_id=at["id"], quoted=fixtures.quote(api, policy["id"]))


def test_a_base_of_exactly_sixty_five_thousand_cents_buys_the_higher_tier(api):
    """One cent of rounded base moves the surcharge from four hundred to nine hundred.

    PRD: The cutoffs are inclusive on the lower side, so a base of 64,999 cents is `CAT_TIER_1` and a base of exactly 65,000 cents is `CAT_TIER_2`.
    PRD: The catastrophe surcharge is the part's `catastrophe_limit_cents` multiplied by the tier's surcharge rate — 400 basis points for `CAT_TIER_1`, 900 for `CAT_TIER_2`, 1,400 for `CAT_TIER_3` — divided by ten thousand and rounded half-up.
    Design: Difficulty/boundary_precision_check/catastrophe_tier_boundary_at_pre_surcharge_base_65000
    """
    ctx = two_transit_parts_astride_the_tier_cutoff(api)

    below = get_success_data(api.get_coverage_part(ctx.below_id, UNDERWRITER))
    at = get_success_data(api.get_coverage_part(ctx.at_id, UNDERWRITER))

    assert below["rated_premium_cents"] == 264994
    assert at["rated_premium_cents"] == 515000
    assert at["rated_premium_cents"] - below["rated_premium_cents"] == 250006


def test_the_two_tiered_parts_roll_up_above_the_minimum_premium(api):
    """The loaded sum clears the floor, so the floor flag stays down.

    PRD: Finally the minimum premium floor is applied, strictly **after** the load: `written_premium_cents` is the greater of the loaded figure and the policy's `minimum_premium_cents`.
    PRD: The policy's premium summary is a computed read that derives everything on the fly and returns `sum_of_part_premiums_cents`, the `expense_load_bp` actually in force for the policy's territory, `written_premium_cents`, `scheduled_basis_premium_cents`, `blanket_basis_premium_cents`, a `minimum_premium_applied` boolean stating whether the floor rather than the loaded figure produced the written premium, `total_insured_value_cents`, `premium_balance_cents`, `incurred_loss_cents` and `referral_required`.
    Design: Difficulty/boundary_precision_check/catastrophe_tier_boundary_at_pre_surcharge_base_65000
    """
    ctx = two_transit_parts_astride_the_tier_cutoff(api)
    assert ctx.quoted["sum_of_part_premiums_cents"] == 779994
    assert ctx.quoted["written_premium_cents"] == 811194

    summary = validate_success(api.get_premium_summary(ctx.policy_id, UNDERWRITER))

    assert summary["sum_of_part_premiums_cents"] == 779994
    assert summary["written_premium_cents"] == 811194
    assert summary["minimum_premium_applied"] is False
    assert summary["expense_load_bp"] == 10400


def test_a_part_with_nothing_scheduled_prices_at_zero_and_charges_the_floor(api):
    """An empty schedule is ratable: the part rates to zero and the floor supplies the premium.

    PRD: On the scheduled basis a part's `rated_premium_cents` is the plain integer-cent sum of `rated_premium_cents` over the equipment items on the part whose `status` is `RATED` or `ACTIVE`.
    PRD: Finally the minimum premium floor is applied, strictly **after** the load: `written_premium_cents` is the greater of the loaded figure and the policy's `minimum_premium_cents`.
    Design: Difficulty/boundary_precision_check/minimum_premium_floor_at_zero_and_no_ratable_coverage_boundary
    """
    ctx = fixtures.build_scheduled_file(
        api, policy_kwargs=dict(policyholder_name="Empty Schedule Co",
                                minimum_premium_cents=250000),
        with_item=False)

    quoted = validate_success(api.quote_policy(ctx.policy_id, UNDERWRITER))

    assert quoted["status"] == "QUOTED"
    assert quoted["sum_of_part_premiums_cents"] == 0
    assert quoted["written_premium_cents"] == 250000
    assert quoted["total_insured_value_cents"] == 0
    assert quoted["referral_required"] is False
    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["rated_premium_cents"] == 0

    summary = validate_success(api.get_premium_summary(ctx.policy_id, UNDERWRITER))
    assert summary["sum_of_part_premiums_cents"] == 0
    assert summary["minimum_premium_applied"] is True
    assert summary["written_premium_cents"] == 250000
    assert summary["scheduled_basis_premium_cents"] == 250000
    assert summary["blanket_basis_premium_cents"] == 250000


def test_a_policy_with_no_coverage_part_at_all_cannot_be_quoted(api):
    """Nothing to rate is a different answer from something that rates to nothing.

    PRD: The policy must have at least one `ACTIVE` coverage part, else `ERR_NO_RATABLE_COVERAGE`, and each such part must end the call with a `rated_premium_cents` actually set.
    PRD: A `DRAFT` policy becomes `QUOTED`; a `QUOTED` policy re-quotes to `QUOTED` again, which is how a policy is re-priced after a schedule or limit endorsement without leaving the quoted state.
    Design: Difficulty/boundary_precision_check/minimum_premium_floor_at_zero_and_no_ratable_coverage_boundary
    """
    policy = fixtures.create_policy(api, policyholder_name="No Parts Co")

    refused = api.quote_policy(policy["id"], UNDERWRITER)

    validate_error(refused, "ERR_NO_RATABLE_COVERAGE", 422)
    unchanged = get_success_data(api.get_policy(policy["id"], UNDERWRITER))
    assert unchanged["status"] == "DRAFT"
    assert unchanged["written_premium_cents"] == 0
    assert unchanged["quoted_at"] is None
