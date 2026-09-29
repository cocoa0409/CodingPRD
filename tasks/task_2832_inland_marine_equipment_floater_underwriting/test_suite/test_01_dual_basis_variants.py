"""The two priced answers a file always carries: schedule versus blanket, repair versus total loss."""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories, fixtures
from test_helpers.test_users import ADJUSTER, MANAGER, UNDERWRITER


def two_unit_file_priced_on_both_bases(api):
    """A scheduled part carrying an excavator and a generator, with a blanket limit declared."""
    fixtures.publish_rate_rule(api)
    fixtures.publish_rate_rule(api, equipment_type="GENERATOR", age_band_min_years=6,
                               age_band_max_years=12, base_rate_bp=120,
                               theft_hazard_grade="C")
    policy = fixtures.create_policy(api, policyholder_name="Ridgeline Contractors")
    part = fixtures.create_part(api, policy["id"], factories.scheduled_equipment_part(
        blanket_limit_cents=10000000, coinsurance_pct_bp=9000))
    e1 = fixtures.schedule_item(api, part["id"], policy["id"],
                                description="E1 excavator")
    e2 = fixtures.schedule_item(api, part["id"], policy["id"],
                                description="E2 generator",
                                equipment_type="GENERATOR", model_year=2018,
                                original_cost_cents=2000000)
    return fixtures.Ctx(policy_id=policy["id"], part_id=part["id"], e1=e1, e2=e2)


def test_scheduled_basis_charges_the_sum_of_individually_rated_units(api):
    """Two differently graded units roll up unit by unit and the blanket answer is only reported.

    PRD: The service therefore computes **both** answers on every quote, and charges only the one each part's own `rating_basis` names.
    PRD: On the scheduled basis a part's `rated_premium_cents` is the plain integer-cent sum of `rated_premium_cents` over the equipment items on the part whose `status` is `RATED` or `ACTIVE`.
    Design: Difficulty/dual_variant_calc/scheduled_versus_blanket_equipment_basis_divergence
    """
    ctx = two_unit_file_priced_on_both_bases(api)

    assert ctx.e1["insured_value_cents"] == 8160000
    assert ctx.e1["rated_premium_cents"] == 173318
    assert ctx.e2["age_years_at_rating"] == 8
    assert ctx.e2["insured_value_cents"] == 720000
    assert ctx.e2["rated_premium_cents"] == 8986

    quoted = fixtures.quote(api, ctx.policy_id)
    assert quoted["sum_of_part_premiums_cents"] == 182304
    assert quoted["written_premium_cents"] == 189596
    assert quoted["total_insured_value_cents"] == 8880000

    part = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert part["rating_basis"] == "SCHEDULED"
    assert part["rated_premium_cents"] == 182304

    summary = validate_success(api.get_premium_summary(ctx.policy_id, UNDERWRITER))
    assert summary["scheduled_basis_premium_cents"] == 189596
    assert summary["blanket_basis_premium_cents"] == 183274
    assert summary["written_premium_cents"] == 189596
    assert summary["minimum_premium_applied"] is False
    assert summary["referral_required"] is False


def test_endorsing_the_rating_basis_swaps_which_answer_is_charged(api):
    """The basis switch moves the charged premium to the blanket figure and leaves both units alone.

    PRD: Switching `rating_basis` or `valuation_basis` does not itself restate the charged premium; it changes which variant of the equipment roll-up will produce `rated_premium_cents` at the next quote.
    PRD: Next compute the coinsurance credit: 500 basis points when the part's `coinsurance_pct_bp` is at least 9,000 — that is, when the insured co-insures at 90 percent or better — and zero otherwise.
    Design: Difficulty/dual_variant_calc/scheduled_versus_blanket_equipment_basis_divergence
    """
    ctx = two_unit_file_priced_on_both_bases(api)
    fixtures.quote(api, ctx.policy_id)

    endorsed = validate_success(api.patch_coverage_part(
        ctx.part_id, factories.part_endorsement(rating_basis="BLANKET"), UNDERWRITER))
    assert endorsed["rating_basis"] == "BLANKET"
    assert endorsed["rated_premium_cents"] == 182304

    requoted = fixtures.quote(api, ctx.policy_id)
    assert requoted["sum_of_part_premiums_cents"] == 176225
    assert requoted["written_premium_cents"] == 183274
    assert requoted["scheduled_basis_premium_cents"] == 189596
    assert requoted["blanket_basis_premium_cents"] == 183274
    assert requoted["scheduled_basis_premium_cents"] - requoted[
        "blanket_basis_premium_cents"] == 6322

    part = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert part["rated_premium_cents"] == 176225

    e1 = get_success_data(api.get_equipment_item(ctx.e1["id"], UNDERWRITER))
    e2 = get_success_data(api.get_equipment_item(ctx.e2["id"], UNDERWRITER))
    assert e1["rated_premium_cents"] == 173318
    assert e2["rated_premium_cents"] == 8986
    assert e1["insured_value_cents"] == 8160000
    assert e2["insured_value_cents"] == 720000


def inspected_collision_claim(api, repair_estimate_cents=3000000):
    """The canonical file on risk, with one inspected collision loss on its excavator."""
    ctx = fixtures.build_in_force_file(api)
    fixtures.set_clock(api, "2026-08-20T00:00:00Z")
    ctx["claim"] = fixtures.build_inspected_claim(
        api, ctx, repair_estimate_cents, 8160000,
        loss_date="2026-08-15", loss_type="COLLISION")
    ctx["claim_id"] = ctx["claim"]["id"]
    return ctx


def test_the_worksheet_shows_repair_and_total_loss_side_by_side(api):
    """One inspection prices both bases at once and they differ by more than the estimate.

    PRD: Fourth, both settlement variants are computed and stored, so the worksheet can show them side by side.
    PRD: Then `constructive_total_loss_threshold_cents` is 7,500 basis points — seventy-five percent — of `valuation_at_loss_cents`, divided by ten thousand and rounded half-up once.
    Design: Difficulty/dual_variant_calc/repair_versus_total_loss_settlement_divergence
    """
    ctx = inspected_collision_claim(api)
    claim = ctx["claim"]
    assert claim["adjustment_status"] == "INSPECTED"
    assert claim["valuation_at_loss_cents"] == 8160000
    assert claim["constructive_total_loss_threshold_cents"] == 6120000
    assert claim["underreporting_factor_bp"] == 10000
    assert claim["repair_basis_settlement_cents"] == 2900000
    assert claim["total_loss_basis_settlement_cents"] == 8060000
    assert claim["adjustment_basis"] is None

    sheet = validate_success(api.get_settlement_worksheet(ctx["claim_id"], ADJUSTER))
    assert sheet["valuation_at_loss_cents"] == 8160000
    assert sheet["constructive_total_loss_threshold_cents"] == 6120000
    assert sheet["constructive_total_loss_reached"] is False
    assert sheet["underreporting_factor_bp"] == 10000
    assert sheet["claim_limit_cents"] == 20000000
    assert sheet["deductible_cents"] == 100000
    assert sheet["loss_of_use_paid_cents"] == 0
    assert sheet["repair_basis_settlement_cents"] == 2900000
    assert sheet["total_loss_basis_settlement_cents"] == 8060000
    assert sheet["repair_basis_selectable"] is True
    assert sheet["aggregate_available_cents"] == 200000000
    assert sheet["total_loss_basis_settlement_cents"] - sheet[
        "repair_basis_settlement_cents"] == 5160000


def test_choosing_repair_pays_the_estimate_and_keeps_the_unit_on_risk(api):
    """Selecting the cheaper basis stores it as the amount payable without discarding the other.

    PRD: The `REPAIR` branch stores the supplied `loss_of_use_days_claimed`, recomputes `loss_of_use_paid_cents`, sets `settlement_amount_cents` to `repair_basis_settlement_cents`, moves the claim `INSPECTED` → `REPAIR_APPROVED`, and leaves `salvage_status` dormant at `NOT_APPLICABLE`; the damaged unit stays on risk and the part's premium is untouched.
    PRD: Multiply `repair_estimate_cents` by `underreporting_factor_bp`, divide by ten thousand and round half-up **once**; take the smaller of that figure and `claim_limit_cents`; subtract the part's `deductible_cents`; if the result is below zero use zero; then add `loss_of_use_paid_cents`.
    Design: Difficulty/dual_variant_calc/repair_versus_total_loss_settlement_divergence
    """
    ctx = inspected_collision_claim(api)

    adjusted = validate_success(api.adjust_claim(
        ctx["claim_id"], factories.adjustment("REPAIR"), ADJUSTER))
    assert adjusted["adjustment_status"] == "REPAIR_APPROVED"
    assert adjusted["adjustment_basis"] == "REPAIR"
    assert adjusted["settlement_amount_cents"] == 2900000
    assert adjusted["total_loss_basis_settlement_cents"] == 8060000
    assert adjusted["salvage_status"] == "NOT_APPLICABLE"
    assert adjusted["declared_by_user_id"] == "adj-1"
    assert adjusted["settlement_paid_cents"] is None
    assert adjusted["loss_of_use_paid_cents"] == 0

    item = get_success_data(api.get_equipment_item(ctx["item_id"], UNDERWRITER))
    assert item["status"] == "ACTIVE"
    part = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert part["rated_premium_cents"] == 173318
    assert part["aggregate_paid_net_cents"] == 0

    settled = validate_success(api.settle_claim(ctx["claim_id"], MANAGER))
    assert settled["settlement_paid_cents"] == 2900000
    assert settled["adjustment_status"] == "CLOSED"
