"""Formulas whose limits and branches have to nest in exactly one order.

Three computations in this system pick a branch from stored dimensions and then
apply two limits in a normative sequence: the assessment picks a zone rate and a
class multiplier and then nests a per-night floor inside a per-period ceiling,
the program performance measurement fixes an efficiency tier on the gross cost
and then reuses it on the net cost, and the delinquency sweep rounds penalty and
interest once per statement before accumulating them.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_fields, assert_ratio_four_dp
from test_helpers.test_users import ADMIN


# --------------------------------------------------------------------------
# Chain: four statements chosen to exercise every corner of the formula
# --------------------------------------------------------------------------
def _four_statements_filed(api):
    """File all four properties of the roll with figures picked so that one is
    decided by the revenue component, one by the per-night floor, one by the
    ceiling, and one by the floor and then the ceiling in that order."""
    ctx = fx.period_with_statements(api)
    fx.file_statement(api, ctx, "st3_id", "b3_id", 900, 30000000)
    fx.file_statement(api, ctx, "st4_id", "b4_id", 3000, 1000000)
    fx.file_statement(api, ctx, "st2_id", "b2_id", 600, 200000000)
    fx.file_statement(api, ctx, "st1_id", "b1_id", 18000, 1000000)
    return ctx


def test_zone_rate_and_class_multiplier_select_the_revenue_component(api):
    """A perimeter boutique property is assessed on its revenue component,
    30000000 x 0.0125 x 0.90 = 337500, which clears its own 135000 floor.

    PRD 3.3: "the revenue component is the revenue basis multiplied by the zone
    rate for the zone basis and then by the class multiplier for the class basis,
    rounded half up to a whole cent."  "The zone rates are 0.0200 for ZONE_CORE,
    0.0125 for ZONE_PERIMETER and 0.0000 for OUTSIDE. The class multipliers are
    1.00 for FULL_SERVICE, 0.85 for LIMITED_SERVICE, 0.90 for BOUTIQUE and 1.15
    for SHORT_TERM_RENTAL."

    Design: Difficulty/combinatorial_formula/assessment_zone_class_floor_and_cap_nest_in_pinned_order
    """
    ctx = _four_statements_filed(api)

    statement = validate_success(api.get_assessment_statement(ctx.st3_id, headers=ADMIN))
    assert_fields(
        statement,
        zone_at_period_start="ZONE_PERIMETER",
        classification_at_period_start="BOUTIQUE",
        provisional_assessment_cents=337500,
        effective_assessment_cents=337500,
    )

    limited = validate_success(api.get_assessment_statement(ctx.st2_id, headers=ADMIN))
    assert_fields(limited, classification_at_period_start="LIMITED_SERVICE")


def test_per_night_floor_overrides_a_smaller_revenue_component(api):
    """A perimeter short-term rental reporting 3000 nights on 1000000 cents has a
    revenue component of only 14375, so the 3000 x 150 = 450000 floor decides it.

    PRD 3.3: "A per-night floor is computed separately as the nights basis
    multiplied by 150 cents, with no rounding, since it is already whole cents.
    The gross figure is then the larger of the revenue component and the floor."

    Design: Difficulty/combinatorial_formula/assessment_zone_class_floor_and_cap_nest_in_pinned_order
    """
    ctx = _four_statements_filed(api)

    statement = validate_success(api.get_assessment_statement(ctx.st4_id, headers=ADMIN))
    assert_fields(
        statement,
        zone_at_period_start="ZONE_PERIMETER",
        classification_at_period_start="SHORT_TERM_RENTAL",
        reported_room_nights=3000,
        reported_gross_room_revenue_cents=1000000,
        provisional_assessment_cents=450000,
    )
    assert statement["provisional_assessment_cents"] != 14375


def test_per_period_ceiling_caps_a_large_revenue_component(api):
    """A core limited-service property reporting 200000000 cents has a revenue
    component of 3400000, which the 2500000 per-period ceiling cuts down.

    PRD 3.3: "the gross figure is then capped: the capped figure is the smaller
    of the gross figure and a per-period ceiling of 2500000 cents."

    Design: Difficulty/combinatorial_formula/assessment_zone_class_floor_and_cap_nest_in_pinned_order
    """
    ctx = _four_statements_filed(api)

    statement = validate_success(api.get_assessment_statement(ctx.st2_id, headers=ADMIN))
    assert_fields(
        statement,
        reported_gross_room_revenue_cents=200000000,
        provisional_assessment_cents=2500000,
    )
    assert statement["provisional_assessment_cents"] != 3400000


def test_floor_is_applied_before_the_ceiling_so_a_high_floor_is_still_capped(api):
    """18000 nights lift the floor to 2700000, above the ceiling; because the
    floor comparison runs first, the ceiling still cuts the result to 2500000.

    PRD 3.3: "The order of these two limits is normative — the floor comparison
    inside the percentage branch runs before the ceiling comparison, because
    reversing them would let a per-night floor above the ceiling escape the
    ceiling entirely."

    Design: Difficulty/combinatorial_formula/assessment_zone_class_floor_and_cap_nest_in_pinned_order
    """
    ctx = _four_statements_filed(api)

    statement = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(
        statement,
        reported_room_nights=18000,
        reported_gross_room_revenue_cents=1000000,
        provisional_assessment_cents=2500000,
        effective_assessment_cents=2500000,
    )
    assert statement["provisional_assessment_cents"] != 2700000

    period = validate_success(api.get_assessment_period(ctx.ap_id, headers=ADMIN))
    assert_fields(period, statement_count=4)


# --------------------------------------------------------------------------
# Chain: a program closed on 20 verified nights against a 62000 commitment
# --------------------------------------------------------------------------
def _closed_program_on_twenty_nights(api):
    """Run a 62000-cent program, verify three claims on three properties over
    disjoint stays totalling 20 nights, and close it."""
    ctx = fx.running_program(api)
    fx.set_clock(api, "2026-09-25T00:00:00Z")
    fx.submit_claim(
        api,
        ctx,
        business_key="b1_id",
        key="rnc_a",
        stay_start="2026-09-01T00:00:00Z",
        stay_end="2026-09-08T00:00:00Z",
        room_nights=7,
    )
    fx.verify_claim(api, ctx, claim_key="rnc_a", decision="ALLOW", verified_room_nights=7)
    fx.submit_claim(
        api,
        ctx,
        business_key="b2_id",
        key="rnc_b",
        stay_start="2026-09-08T00:00:00Z",
        stay_end="2026-09-15T00:00:00Z",
        room_nights=7,
    )
    fx.verify_claim(api, ctx, claim_key="rnc_b", decision="ALLOW", verified_room_nights=7)
    fx.submit_claim(
        api,
        ctx,
        business_key="b3_id",
        key="rnc_c",
        stay_start="2026-09-15T00:00:00Z",
        stay_end="2026-09-21T00:00:00Z",
        room_nights=6,
    )
    fx.verify_claim(api, ctx, claim_key="rnc_c", decision="ALLOW", verified_room_nights=6)
    fx.close_program(api, ctx)
    return ctx


def test_efficiency_tier_is_read_off_the_gross_cost_per_room_night(api):
    """62000 over 20 verified nights is 3100 cents gross, which lands in
    TIER_MARGINAL rather than the TIER_STANDARD the net figure would suggest.

    PRD 3.8: "gross_cost_per_room_night_cents is committed_cents divided by the
    verified night count, rounded half up to a whole cent, and the tier is read
    off that gross figure: TIER_EFFICIENT at 1500 cents or below, otherwise
    TIER_STANDARD at 3000 cents or below, otherwise TIER_MARGINAL at 6000 cents
    or below, otherwise TIER_UNPRODUCTIVE. The tier selected in this pass is
    never reselected."

    Design: Difficulty/combinatorial_formula/program_performance_efficiency_tier_fixed_on_gross_cost_before_dmo_share
    """
    ctx = _closed_program_on_twenty_nights(api)

    program = validate_success(api.get_marketing_program(ctx.mp_id, headers=ADMIN))
    assert_fields(
        program,
        status="CLOSED",
        verified_room_nights=20,
        gross_cost_per_room_night_cents=3100,
        efficiency_tier="TIER_MARGINAL",
    )
    assert program["efficiency_tier"] != "TIER_STANDARD"


def test_dmo_share_uses_the_tier_fixed_in_the_first_pass(api):
    """TIER_MARGINAL carries a 0.10 share, so the DMO absorbs 6200 of the 62000
    and not the 15500 that TIER_STANDARD's 0.25 would have produced.

    PRD 3.8: "Using the tier fixed in pass one, dmo_cost_share_cents is
    committed_cents multiplied by the tier's share percentage, rounded half up to
    a whole cent, where the percentages are 0.40 for TIER_EFFICIENT, 0.25 for
    TIER_STANDARD, 0.10 for TIER_MARGINAL and 0.00 for TIER_UNPRODUCTIVE."

    Design: Difficulty/combinatorial_formula/program_performance_efficiency_tier_fixed_on_gross_cost_before_dmo_share
    """
    ctx = _closed_program_on_twenty_nights(api)

    program = validate_success(api.get_marketing_program(ctx.mp_id, headers=ADMIN))
    assert_fields(
        program,
        committed_cents=62000,
        dmo_cost_share_cents=6200,
        net_district_cost_cents=55800,
        net_cost_per_room_night_cents=2790,
    )
    assert program["dmo_cost_share_cents"] != 15500


def test_performance_index_and_flag_come_off_the_net_cost_without_re_tiering(api):
    """2500 over a net cost of 2790 is 0.8961 at four decimal places, which is
    below the 1.0000 benchmark but at or above 0.7500.

    PRD 3.8: "performance_index is a benchmark of 2500 cents divided by
    net_cost_per_room_night_cents, rounded half up to four decimal places.
    Re-tiering on the net figure is forbidden and would change the published
    index."

    Design: Difficulty/combinatorial_formula/program_performance_efficiency_tier_fixed_on_gross_cost_before_dmo_share
    """
    ctx = _closed_program_on_twenty_nights(api)

    program = validate_success(api.get_marketing_program(ctx.mp_id, headers=ADMIN))
    assert_ratio_four_dp(program["performance_index"], 0.8961, "performance_index")
    assert_fields(program, performance_flag="BELOW_BENCHMARK", efficiency_tier="TIER_MARGINAL")


# --------------------------------------------------------------------------
# Chain: two identical arrears rounded per statement, then accumulated
# --------------------------------------------------------------------------
def _swept_district_with_two_half_cent_arrears(api):
    """Build a three-property district in which two properties owe exactly
    375000 cents and are swept five days late.

    Each statement's interest is 375000 x 0.0005 x 5 = 937.5 cents, which is
    exactly on a half cent, so the district total distinguishes rounding once
    per statement from rounding once over the aggregate.
    """
    fx.pin_clock_to_origin(api)
    ctx = fx.create_district(
        api,
        name="Cannery Row Tourism Improvement District",
        included_zones=["ZONE_CORE"],
    )
    fx.add_business(
        api,
        ctx,
        f.lodging_business_payload(
            ctx.d_id,
            legal_name="Cannery Anchor Hotel",
            room_count=220,
            prior_year_gross_room_revenue_cents=60000000,
        ),
        "b1_id",
    )
    fx.add_business(
        api,
        ctx,
        f.lodging_business_payload(
            ctx.d_id,
            legal_name="Row House Hotel",
            room_count=90,
            prior_year_gross_room_revenue_cents=20000000,
        ),
        "b2_id",
    )
    fx.add_business(
        api,
        ctx,
        f.lodging_business_payload(
            ctx.d_id,
            legal_name="Wharf View Hotel",
            room_count=90,
            prior_year_gross_room_revenue_cents=20000000,
        ),
        "b3_id",
    )
    fx.open_formation_drive(api, ctx)
    fx.sign(api, ctx, "b1_id")
    fx.tally(api, ctx)
    fx.certify(api, ctx)
    fx.advance_district(api, ctx, "ACTIVE")
    fx.open_period(api, ctx)
    fx.generate_statements(api, ctx)
    fx.index_statements(api, ctx)
    fx.file_statement(api, ctx, "st2_id", "b2_id", 500, 18750000)
    fx.file_statement(api, ctx, "st3_id", "b3_id", 500, 18750000)
    fx.set_clock(api, "2026-11-16T00:00:00Z")
    fx.close_period(api, ctx)
    fx.set_clock(api, "2026-11-30T00:00:00Z")
    fx.sweep_period(api, ctx)
    return ctx


def test_penalty_and_interest_are_rounded_once_per_statement(api):
    """Each arrears of 375000 cents swept five days late carries a 37500 penalty
    and an interest of 937.5 rounded half up to 938.

    PRD 3.5: "penalty_cents becomes the outstanding amount multiplied by a
    penalty rate of 0.10, rounded half up to a whole cent. interest_cents becomes
    the outstanding amount multiplied by a daily interest rate of 0.0005 and then
    by the number of days late, rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/delinquency_penalty_and_interest_rounded_per_statement_before_accumulation
    """
    ctx = _swept_district_with_two_half_cent_arrears(api)

    for key in ("st2_id", "st3_id"):
        statement = validate_success(api.get_assessment_statement(ctx[key], headers=ADMIN))
        assert_fields(
            statement,
            effective_assessment_cents=375000,
            penalty_cents=37500,
            interest_cents=938,
            total_due_cents=413438,
            payment_status="DELINQUENT",
            delinquency_stage="NOTICE",
        )


def test_district_arrears_accumulate_the_rounded_per_statement_figures(api):
    """Two statements at 938 cents of interest give the district 76876 cents of
    delinquent charges, not the 76875 that rounding the aggregate would give.

    PRD 3.5: "The two charge figures are each rounded once per statement and only
    then accumulated into the district's delinquent_charges_cents; summing
    outstanding amounts across the period first and applying the rates to that
    aggregate is incorrect, because it yields a different total whenever any
    per-statement product lands on a half cent."

    Design: Difficulty/combinatorial_formula/delinquency_penalty_and_interest_rounded_per_statement_before_accumulation
    """
    ctx = _swept_district_with_two_half_cent_arrears(api)

    district = validate_success(api.get_district(ctx.d_id))
    assert_fields(district, delinquent_charges_cents=76876)
    assert district["delinquent_charges_cents"] != 76875

    period = validate_success(api.get_assessment_period(ctx.ap_id, headers=ADMIN))
    assert_fields(period, status="DELINQUENCY_SWEPT")


def test_never_filed_statement_owes_nothing_and_is_passed_over_by_the_sweep(api):
    """The property that never filed carries a zero assessment, so the sweep
    leaves it alone and charges it nothing.

    PRD 3.5: "The sweep considers only the statements of that period whose
    payment_status is UNPAID or PARTIALLY_PAID and whose total_due_cents is
    greater than zero."

    Design: Difficulty/combinatorial_formula/delinquency_penalty_and_interest_rounded_per_statement_before_accumulation
    """
    ctx = _swept_district_with_two_half_cent_arrears(api)

    statement = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(
        statement,
        filing_status="NOT_FILED",
        effective_assessment_cents=0,
        total_due_cents=0,
        penalty_cents=0,
        interest_cents=0,
        delinquency_stage="NONE",
        payment_status="UNPAID",
    )

    business = validate_success(api.get_lodging_business(ctx.b1_id, headers=ADMIN))
    assert_fields(business, delinquency_strike_count=0, compliance_standing="GOOD")
