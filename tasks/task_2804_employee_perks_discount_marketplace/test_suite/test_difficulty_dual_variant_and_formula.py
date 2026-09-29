"""Queue A — dual_variant_calc and combinatorial_formula.

Every test below translates exactly one instance of §1.8's difficulty design
index; the `Design:` line of each docstring names it.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    DiscountType, EmploymentStatus, PerkCategory, PlacementTier,
    StatementStatus, VerificationStatus, api_client, assertions as A,
    constants as C, factories as F, fixtures as fx,
    make_employer_admin_headers, make_partner_manager_headers,
)


def _dual_variant_program():
    """An ACTIVE DINING/CA partner, a LIVE employer and a PERCENT + FIXED pair.

    Both offers hang off the same agreement (commission 1,200 bps, employer
    share 2,500 bps) so the only thing that differs between them is the
    discount shape.
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.live_program(
        record_count=1,
        commission_rate_bps=1200,
        employer_revenue_share_bps=2500,
        revenue_share_enabled=True,
        privacy_min_cohort_size=3,
        offer_overrides={
            "title": "20 percent off dinner",
            "min_spend_cents": 1000,
            "inventory_limit": 10,
            "per_member_limit": 5,
        },
    )
    fixed_offer = fx.approved_offer(
        program["agreement"]["id"], program["merchant"]["id"],
        title="800 cents off dinner",
        discount_type=DiscountType.FIXED,
        discount_value_bps=F.OMIT,
        discount_value_cents=800,
        min_spend_cents=1000,
        inventory_limit=10,
        per_member_limit=5,
    )
    program["fixed_offer"] = fixed_offer
    program["membership"] = program["memberships"][0]
    return program


def test_percent_offer_verification_prices_the_line_from_basis_points():
    """A PERCENT offer discounts 2,000 bps of a 5,000 cent ticket, then chains.

    PRD: "For a `PERCENT` offer, `discount_amount_cents` is the lesser of `gross_amount_cents` and the result of multiplying `gross_amount_cents` by `discount_value_bps`, dividing by 10,000 and rounding half up to whole cents — the discount can never exceed the ticket."

    Design: Difficulty/dual_variant_calc/percent_versus_fixed_discount_variant_divergence_at_identical_gross
    """
    program = _dual_variant_program()
    merchant_id = program["merchant"]["id"]
    membership_id = program["membership"]["id"]

    created = fx.create_redemption(
        program["offer"]["id"], membership_id, intended_gross_amount_cents=5000
    )
    fx.set_clock("2026-08-02T00:00:00Z")
    verified = fx.verify_redemption(created, merchant_id, gross_amount_cents=5000)

    # 5000 * 2000 / 10000 = 1000 discount; net 4000; 4000 * 1200 / 10000 = 480
    # commission; 480 * 2500 / 10000 = 120 share; provider keeps 360.
    A.assert_line_economics(verified, 5000, 1000, 4000, 480, 120, 360)
    A.assert_fields(verified, {
        "verification_status": VerificationStatus.VERIFIED.value,
    }, "redemption")


def test_fixed_offer_verification_prices_the_line_from_a_cent_discount():
    """A FIXED offer discounts a flat 800 cents of the same 5,000 cent ticket.

    PRD: "For a `FIXED` offer, `discount_amount_cents` is the lesser of `discount_value_cents` and `gross_amount_cents`."

    Design: Difficulty/dual_variant_calc/percent_versus_fixed_discount_variant_divergence_at_identical_gross
    """
    program = _dual_variant_program()
    merchant_id = program["merchant"]["id"]
    membership_id = program["membership"]["id"]

    created = fx.create_redemption(
        program["fixed_offer"]["id"], membership_id, intended_gross_amount_cents=5000
    )
    fx.set_clock("2026-08-02T00:00:00Z")
    verified = fx.verify_redemption(created, merchant_id, gross_amount_cents=5000)

    # 800 flat discount; net 4200; 4200 * 1200 / 10000 = 504 commission;
    # 504 * 2500 / 10000 = 126 share; provider keeps 378.
    A.assert_line_economics(verified, 5000, 800, 4200, 504, 126, 378)
    A.assert_fields(verified, {
        "verification_status": VerificationStatus.VERIFIED.value,
    }, "redemption")


def test_percent_and_fixed_variants_diverge_on_every_downstream_column():
    """At an identical gross the two discount shapes disagree all the way down.

    PRD: "The line economics are **five ordered steps, each rounding to whole cents before feeding the next**."

    Design: Difficulty/dual_variant_calc/percent_versus_fixed_discount_variant_divergence_at_identical_gross
    """
    program = _dual_variant_program()
    merchant_id = program["merchant"]["id"]
    membership_id = program["membership"]["id"]

    percent_created = fx.create_redemption(
        program["offer"]["id"], membership_id, intended_gross_amount_cents=5000
    )
    fixed_created = fx.create_redemption(
        program["fixed_offer"]["id"], membership_id, intended_gross_amount_cents=5000
    )
    fx.set_clock("2026-08-02T00:00:00Z")
    percent = fx.verify_redemption(percent_created, merchant_id, gross_amount_cents=5000)
    fixed = fx.verify_redemption(fixed_created, merchant_id, gross_amount_cents=5000)

    assert percent["gross_amount_cents"] == fixed["gross_amount_cents"] == 5000
    assert fixed["discount_amount_cents"] - percent["discount_amount_cents"] == -200
    assert fixed["commission_amount_cents"] - percent["commission_amount_cents"] == 24
    assert fixed["employer_share_cents"] - percent["employer_share_cents"] == 6
    assert fixed["provider_net_cents"] - percent["provider_net_cents"] == 18


def _three_redeemer_program():
    """One employer with three memberships and three verified DINING lines."""
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.live_program(
        record_count=3,
        commission_rate_bps=1200,
        employer_revenue_share_bps=2500,
        revenue_share_enabled=True,
        privacy_min_cohort_size=3,
        offer_overrides={"min_spend_cents": 1000, "inventory_limit": 10},
    )
    created = [
        fx.create_redemption(
            program["offer"]["id"], membership["id"], intended_gross_amount_cents=5000
        )
        for membership in program["memberships"]
    ]
    fx.set_clock("2026-08-02T00:00:00Z")
    for redemption in created:
        fx.verify_redemption(
            redemption, program["merchant"]["id"], gross_amount_cents=5000
        )
    return program


def test_employer_scope_report_publishes_a_row_sitting_on_its_cohort_floor():
    """Three distinct redeemers meet a floor of three, so nothing is withheld.

    PRD: "A row whose cohort metric equals the floor is **not** suppressed — the floor is inclusive."

    Design: Difficulty/dual_variant_calc/employer_scope_versus_partner_scope_privacy_cohort_variant_divergence
    """
    program = _three_redeemer_program()
    employer_id = program["employer"]["id"]

    response = api_client.get_engagement_report(
        employer_id, make_employer_admin_headers(employer_id),
        params=F.report_params("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z"),
    )
    report = validate_success(response)

    assert report["privacy_min_cohort_size"] == 3
    assert len(report["category_rows"]) == 1
    row = A.category_row(report, PerkCategory.DINING.value)
    A.assert_row_visible(
        row, "distinct_redeemer_count",
        redemption_count=3, discount_amount_cents=3000, cohort_value=3,
    )
    assert report["suppressed_category_count"] == 0
    assert report["total_redemption_count"] == 3
    assert report["total_discount_amount_cents"] == 3000
    assert report["total_distinct_redeemer_count"] == 3


def test_partner_scope_feed_suppresses_the_same_row_beneath_its_own_floor():
    """One employer behind the row is below the fixed platform floor of two.

    PRD: "When a row's cohort metric is strictly below the applicable floor, the row is suppressed: `suppressed` is true and `redemption_count`, `discount_amount_cents` and the cohort metric are all reported as null."

    Design: Difficulty/dual_variant_calc/employer_scope_versus_partner_scope_privacy_cohort_variant_divergence
    """
    _three_redeemer_program()

    response = api_client.get_category_demand(
        make_partner_manager_headers(),
        params=F.report_params("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z"),
    )
    feed = validate_success(response)

    assert feed["partner_min_employer_cohort"] == C.PARTNER_MIN_EMPLOYER_COHORT == 2
    assert len(feed["category_rows"]) == 1
    row = A.category_row(feed, PerkCategory.DINING.value)
    A.assert_row_suppressed(row, "distinct_employer_count")
    assert feed["suppressed_category_count"] == 1
    # Suppression hides the breakdown, never the period total.
    assert feed["total_redemption_count"] == 3


def _mixed_roster_program():
    """A LIVE employer whose five-record roster yields an eligible headcount of 4.

    Three memberships are ACTIVE, one is on LEAVE — both count — and one is
    TERMINATED, which does not.
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    records = [
        F.eligibility_record("E-001"),
        F.eligibility_record("E-002"),
        F.eligibility_record("E-003"),
        F.eligibility_record("E-004", employment_status=EmploymentStatus.LEAVE),
        F.eligibility_record("E-005", employment_status=EmploymentStatus.TERMINATED),
    ]
    return fx.live_program(
        records=records,
        commission_rate_bps=1200,
        placement_fee_base_cents=36000,
        employer_revenue_share_bps=2500,
        revenue_share_enabled=True,
        privacy_min_cohort_size=3,
        offer_overrides={"min_spend_cents": 1000, "inventory_limit": 10},
    )


def test_employer_eligible_headcount_counts_active_and_leave_rows_only():
    """The reach figure behind placement pricing excludes terminated staff.

    PRD: "The employer's `eligible_headcount` is the number of that employer's memberships that satisfy three conditions at once: `status` is `ELIGIBLE`, `employment_status` is `ACTIVE` or `LEAVE`, and the logical clock falls at or after `eligibility_valid_from` and strictly before `eligibility_valid_until`."

    Design: Difficulty/combinatorial_formula/placement_fee_volume_tier_keyed_on_post_surcharge_gross
    """
    program = _mixed_roster_program()

    employer = fx.get_employer(program["employer"]["id"])
    assert employer["eligible_headcount"] == 4
    assert employer["employee_count_declared"] == 250


def test_placement_fee_keys_the_volume_tier_on_the_post_surcharge_gross():
    """A reach surcharge pushes the gross over the 200,000 cent volume floor.

    PRD: "`volume_discount_bps` is selected from a tier over `gross_fee_cents` — that is, over the step-3 figure **after** the reach surcharge has been added, never over the bare base: a gross below 100,000 cents (one thousand dollars) selects 0 basis points; a gross from 100,000 cents up to but not including 200,000 cents selects 500 basis points; a gross of 200,000 cents (two thousand dollars) or more selects 1,200 basis points."

    Design: Difficulty/combinatorial_formula/placement_fee_volume_tier_keyed_on_post_surcharge_gross
    """
    program = _mixed_roster_program()

    slot = fx.reserve_slot(
        program["offer"], program["employer"]["id"], program["merchant"]["id"],
        placement_tier=PlacementTier.STANDARD,
        slot_window_start="2026-09-01T00:00:00Z",
        slot_window_end="2026-09-06T00:00:00Z",
    )

    # 5 days * 36000 = 180000 base; headcount 4 -> 1500 bps -> 27000 surcharge;
    # gross 207000 clears the 200000 floor -> 1200 bps -> 24840; fee 182160.
    A.assert_placement_fee_breakdown(
        slot,
        slot_duration_days=5,
        base_fee_cents=180000,
        reach_surcharge_bps=1500,
        reach_surcharge_cents=27000,
        gross_fee_cents=207000,
        volume_discount_bps=1200,
        volume_discount_cents=24840,
        placement_fee_cents=182160,
    )
    # 198000 is what keying the volume tier on the bare base would produce.
    assert slot["placement_fee_cents"] != 198000
    assert slot["status"] == "RESERVED"


def _two_line_statement_program():
    """Two verified 8,396 cent lines and a DRAFT ACCRUAL statement over them."""
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.live_program(
        record_count=1,
        commission_rate_bps=1200,
        employer_revenue_share_bps=2500,
        revenue_share_enabled=True,
        offer_overrides={
            "min_spend_cents": 1000, "inventory_limit": 10, "per_member_limit": 5,
        },
    )
    membership_id = program["memberships"][0]["id"]
    created = [
        fx.create_redemption(
            program["offer"]["id"], membership_id, intended_gross_amount_cents=8396
        )
        for _ in range(2)
    ]
    fx.set_clock("2026-08-02T00:00:00Z")
    program["lines"] = [
        fx.verify_redemption(
            redemption, program["merchant"]["id"], gross_amount_cents=8396
        )
        for redemption in created
    ]
    program["statement"] = fx.create_statement(
        program["employer"]["id"],
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-09-01T00:00:00Z",
        basis="ACCRUAL",
    )
    fx.set_clock("2026-09-02T00:00:00Z")
    return program


def test_statement_sums_already_rounded_per_redemption_employer_shares():
    """Two 202 cent shares sum to 404, not the 403 a single rounding would give.

    PRD: "It is never obtained by applying `employer_revenue_share_bps` to `gross_commission_cents`; per-redemption rounding first, then summation."

    Design: Difficulty/combinatorial_formula/statement_employer_share_rounds_per_redemption_before_summing
    """
    program = _two_line_statement_program()

    for line in program["lines"]:
        # 8396 - 1679 = 6717 net; 6717 * 1200 / 10000 = 806.04 -> 806;
        # 806 * 2500 / 10000 = 201.5 -> 202 by round half up.
        assert line["commission_amount_cents"] == 806
        assert line["employer_share_cents"] == 202

    statement = fx.finalize_statement(program["statement"]["id"])

    A.assert_fields(statement, {
        "status": StatementStatus.FINALIZED.value,
        "included_redemption_count": 2,
        "gross_commission_cents": 1612,
        "employer_share_cents": 404,
        "provider_retained_cents": 1208,
        "reversal_adjustment_cents": 0,
    }, "statement")
    # 403 is what rounding the summed 1612 commission once would produce.
    assert statement["employer_share_cents"] != 403


def test_statement_finalize_claims_the_redemptions_it_counted():
    """Finalizing stamps its own id onto every unclaimed included redemption.

    PRD: "It stamps the statement's id into the `statement_id` of every redemption the inclusion set selected whose `statement_id` is currently null."

    Design: Difficulty/combinatorial_formula/statement_employer_share_rounds_per_redemption_before_summing
    """
    program = _two_line_statement_program()
    merchant_id = program["merchant"]["id"]

    for line in program["lines"]:
        assert fx.get_redemption(line["id"], merchant_id=merchant_id)["statement_id"] is None

    statement = fx.finalize_statement(program["statement"]["id"])

    for line in program["lines"]:
        claimed = fx.get_redemption(line["id"], merchant_id=merchant_id)
        assert claimed["statement_id"] == statement["id"]
