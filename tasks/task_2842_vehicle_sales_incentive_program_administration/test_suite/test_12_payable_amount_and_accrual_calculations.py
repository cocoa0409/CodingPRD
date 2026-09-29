"""Payable-amount, objective, accrual, spend, projection and repricing arithmetic.

Every expected value below is the single answer the PRD's pinned formulas and
pinned rounding directions produce; nothing here is recomputed by the test.
"""
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import api_client, make_dealer_headers
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx

AUG_01 = "2026-08-01T00:00:00.000Z"
AUG_06 = "2026-08-06T00:00:00.000Z"
SEP_01 = "2026-09-01T00:00:00.000Z"
BUILD_FROM = "2026-05-01T00:00:00.000Z"
BUILD_TO = "2026-07-31T00:00:00.000Z"
BUILD_DATE = "2026-06-01T00:00:00.000Z"
SALE_AUG_05 = "2026-08-05T00:00:00.000Z"


def _rule(model_code, region_code, deal_types, build_from=BUILD_FROM,
          build_to=BUILD_TO):
    """One eligibility footprint row's overrides."""
    return {
        "model_code": model_code,
        "region_code": region_code,
        "build_date_from": build_from,
        "build_date_to": build_to,
        "allowed_deal_types": list(deal_types),
    }


def _submit_and_approve_claim(dealer_id, delivery_id, program_id,
                              claimed_amount_cents):
    """Submit one claim as its own dealer and approve it as the adjudicating
    auditor, returning the adjudicated claim payload."""
    created = validate_success(
        api_client.create_claim(
            f.create_claim_payload(
                delivery_id,
                program_id,
                claimed_amount_cents,
                fx.program_version(program_id),
            ),
            make_dealer_headers(dealer_id),
        ),
        201,
    )
    return validate_success(
        api_client.adjudicate_claim(
            created["id"], f.adjudicate_payload("APPROVE"), fx.ADJUDICATOR
        )
    )


# --- The finance-subvention leg ---------------------------------------------

# contract_apr_bps -> the approved_amount_cents the PRD's clamp produces on a
# program whose per_unit_amount_cents is 100000 and apr_buydown_bps is 250,
# for a delivery of msrp_cents 3600000 over term_months 60.
APR_GAP_CASES = (
    (549, 550000),
    (599, 460000),
    (799, 100000),
    (850, 100000),
)


def test_finance_leg_clamps_the_buydown_at_the_market_apr_gap():
    """The effective buy-down is min(max(0, 799 - contract_apr_bps), apr_buydown_bps).

    PRD §3.7: "For `FINANCE_SUBVENTION`, first take the market benchmark APR of
    799 basis points, that is 7.99 percent, and subtract the delivery's
    `contract_apr_bps`; if that difference is negative, treat it as 0. The
    effective buy-down in basis points is then the smaller of that non-negative
    difference and the program's `apr_buydown_bps`."

    Design: Corner/calculations/finance_subvention_leg_clamps_the_buydown_at_the_market_apr_gap
    """
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        region_code="WEST", historical_volume_units=4, market_opportunity_bps=0
    )
    program = fx.create_active_program(
        rules=[_rule("MX5", "WEST", ["FINANCE"])],
        name="APR Gap Subvention",
        incentive_type="FINANCE_SUBVENTION",
        effective_from=AUG_01,
        effective_to=SEP_01,
        per_unit_amount_cents=100000,
        apr_buydown_bps=250,
        budget_cents=12000000,
        stack_group="CRNAPR",
        priority_rank=401,
        accrual_method="UNIT_BASED",
    )
    fx.set_clock(AUG_06)

    for contract_apr_bps, expected_amount in APR_GAP_CASES:
        delivery = fx.report_finance_delivery(
            dealer["id"],
            model_code="MX5",
            trim_code="BASE",
            build_date=BUILD_DATE,
            msrp_cents=3600000,
            sale_date=SALE_AUG_05,
            customer_region_code="WEST",
            term_months=60,
            contract_apr_bps=contract_apr_bps,
        )
        fx.validate_delivery(delivery["id"])
        claim = _submit_and_approve_claim(
            dealer["id"], delivery["id"], program["id"], expected_amount
        )
        a.assert_claim_shape(claim)
        a.assert_money(claim, "approved_amount_cents", expected_amount)
        # No repricing exists on this program, so every leg is priced from the
        # claim's own frozen snapshot.
        assert claim["rate_basis"] == "AS_SOLD_SNAPSHOT", claim["rate_basis"]

    # A customer APR above the market benchmark never produces a negative leg:
    # the fourth case pays the per-unit rate and nothing more.


def test_finance_leg_rounds_once_over_the_whole_expression():
    """3333333 * 137 * 39 / 120000 rounds half-up once, to 148417 and not 148434.

    PRD §3.7: "The leg is the delivery's `msrp_cents` multiplied by the effective
    buy-down in basis points, multiplied by the delivery's `term_months`, divided
    by 120000, with half-up rounding applied once to that entire expression
    rather than to any individual factor."

    Design: Corner/calculations/finance_leg_rounds_once_over_the_whole_expression
    """
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        region_code="NORTH", historical_volume_units=4, market_opportunity_bps=0
    )
    program = fx.create_active_program(
        rules=[_rule("SDN3", "NORTH", ["FINANCE"])],
        name="Rounding Subvention",
        incentive_type="FINANCE_SUBVENTION",
        effective_from=AUG_01,
        effective_to=SEP_01,
        per_unit_amount_cents=0,
        apr_buydown_bps=137,
        budget_cents=12000000,
        stack_group="CRNRND",
        priority_rank=402,
        accrual_method="UNIT_BASED",
    )
    fx.set_clock(AUG_06)
    delivery = fx.report_finance_delivery(
        dealer["id"],
        model_code="SDN3",
        trim_code="SPORT",
        build_date="2026-06-15T00:00:00.000Z",
        msrp_cents=3333333,
        sale_date=SALE_AUG_05,
        customer_region_code="NORTH",
        term_months=39,
        contract_apr_bps=500,
    )
    fx.validate_delivery(delivery["id"])

    submitted = validate_success(
        api_client.create_claim(
            f.create_claim_payload(
                delivery["id"], program["id"], 148417,
                fx.program_version(program["id"]),
            ),
            make_dealer_headers(dealer["id"]),
        ),
        201,
    )
    # With per_unit_amount_cents 0 the snapshot leg is genuinely zero, not absent.
    a.assert_money(submitted, "snapshot_per_unit_cents", 0)

    claim = validate_success(
        api_client.adjudicate_claim(
            submitted["id"], f.adjudicate_payload("APPROVE"), fx.ADJUDICATOR
        )
    )
    a.assert_money(claim, "approved_amount_cents", 148417)
    assert claim["approved_amount_cents"] != 148434, (
        "148434 is what rounding msrp * bps / 120000 to 3806 before multiplying "
        "by term_months would produce"
    )
    assert claim["rate_basis"] == "AS_SOLD_SNAPSHOT", claim["rate_basis"]

    summary = validate_success(
        api_client.get_spend_summary(program["id"], fx.CONTROLLER)
    )
    a.assert_money(summary, "committed_cents", 148417)
    a.assert_money(summary, "per_unit_spend_cents", 148417)


# --- Objective unit proposal --------------------------------------------------


def test_objective_units_clamp_the_total_uplift_and_floor_at_one_unit():
    """The 5000 bps uplift ceiling, half-up rounding at 10.5 and the one-unit floor.

    PRD §3.3: "Second, the total uplift in basis points is the smaller of two
    quantities: the sum of the dealer's `market_opportunity_bps` and the
    objective's `stretch_bps`, and a system ceiling of 5000 basis points, that is
    50.00 percent; the ceiling means no objective may ever demand more than one
    and a half times the dealer's basis volume however aggressively the field
    stretches it." And: "Fourth, `objective_units` is the raw unit target rounded
    half-up to a whole number, and then raised to 1 if that rounding produced
    anything smaller — the floor of one unit guarantees that attainment can always
    be divided by the objective without a division error."

    Design: Corner/calculations/objective_units_clamp_the_total_uplift_and_floor_at_one_unit
    """
    fx.set_clock(AUG_01)
    dealer_a = fx.register_dealer(
        name="Uplift Dealer A", region_code="WEST",
        historical_volume_units=7, market_opportunity_bps=4000,
    )
    dealer_b = fx.register_dealer(
        name="Uplift Dealer B", region_code="WEST",
        historical_volume_units=7, market_opportunity_bps=4000,
    )
    dealer_c = fx.register_dealer(
        name="Uplift Dealer C", region_code="WEST",
        historical_volume_units=0, market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        rules=[_rule("MX5", "WEST", ["CASH"])],
        name="Uplift Stair",
        incentive_type="DEALER_STAIR_STEP",
        effective_from=AUG_01,
        effective_to=SEP_01,
        per_unit_amount_cents=0,
        budget_cents=12000000,
        stack_group="CRNUP",
        priority_rank=403,
        tier_schedule=[
            {"tier_index": 1, "threshold_bps": 8000, "per_unit_bonus_cents": 30000}
        ],
        tier_bonus_mode="MARGINAL",
    )

    # Dealer A: 4000 + 3000 == 7000 is clamped to 5000, raw == 7 * 15000 / 10000
    # == 10.5, and half-up rounding lifts it to 11 rather than to an even 10.
    objective_a = validate_success(
        api_client.create_objective(
            program["id"],
            f.create_objective_payload(dealer_a["id"], stretch_bps=3000),
            fx.FSM,
        ),
        201,
    )
    a.assert_objective_shape(objective_a)
    a.assert_int_field(objective_a, "basis_units", 7)
    a.assert_int_field(objective_a, "objective_units", 11)
    # Nothing has been validated yet, so the objective is born at zero attainment.
    a.assert_bps(objective_a, "attainment_bps", 0)

    # Dealer B: identical history, 4000 + 500 == 4500 stays under the ceiling.
    objective_b = validate_success(
        api_client.create_objective(
            program["id"],
            f.create_objective_payload(dealer_b["id"], stretch_bps=500),
            fx.FSM,
        ),
        201,
    )
    a.assert_int_field(objective_b, "basis_units", 7)
    a.assert_int_field(objective_b, "objective_units", 10)

    # Dealer C: a zero basis rounds to 0 and is then raised to the one-unit floor.
    objective_c = validate_success(
        api_client.create_objective(
            program["id"], {"dealer_id": dealer_c["id"]}, fx.FSM
        ),
        201,
    )
    a.assert_int_field(objective_c, "basis_units", 0)
    a.assert_int_field(objective_c, "objective_units", 1)
    a.assert_bps(objective_c, "stretch_bps", 0)


# --- Monthly budget accrual --------------------------------------------------


def test_take_rate_accrual_diverges_from_the_cancel_reserve_accrual():
    """Identical units and per-unit amounts accrue 291750 versus 195000.

    PRD §3.9: "Under `UNIT_BASED`, the line amount is the line's unit count
    multiplied by the program's `per_unit_amount_cents`, multiplied by the
    quantity ten thousand minus 275, divided by ten thousand — that is, actual
    validated units net of a flat cancellation reserve of 2.75 percent, withheld
    against the deals that will not stick. Under `TAKE_RATE_BASED`, the line
    amount is the line's unit count multiplied by the program's
    `per_unit_amount_cents`, multiplied by the program's
    `projected_take_rate_bps`, divided by ten thousand."

    Design: Corner/calculations/take_rate_accrual_variant_diverges_from_the_cancel_reserve_variant
    """
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        name="Accrual Variant Motors", region_code="WEST",
        historical_volume_units=6, market_opportunity_bps=0,
    )
    program_unit = fx.create_active_program(
        rules=[_rule("MX5", "WEST", ["CASH"])],
        name="Accrual Unit Based",
        incentive_type="CUSTOMER_CASH",
        effective_from=AUG_01,
        effective_to=SEP_01,
        per_unit_amount_cents=100000,
        budget_cents=12000000,
        stack_group="CRNACC",
        priority_rank=404,
        accrual_method="UNIT_BASED",
    )
    # A disjoint model footprint, so the two programs never collide on overlap.
    program_take = fx.create_active_program(
        rules=[_rule("TRK9", "WEST", ["CASH"])],
        name="Accrual Take Rate",
        incentive_type="CUSTOMER_CASH",
        effective_from=AUG_01,
        effective_to=SEP_01,
        per_unit_amount_cents=100000,
        budget_cents=12000000,
        stack_group="CRNACC",
        priority_rank=405,
        accrual_method="TAKE_RATE_BASED",
        projected_take_rate_bps=6500,
    )

    fx.set_clock("2026-08-10T00:00:00.000Z")
    for model_code, msrp_cents in (("MX5", 3100000), ("TRK9", 4200000)):
        for sale_day in ("2026-08-05", "2026-08-06", "2026-08-07"):
            delivery = fx.report_delivery(
                dealer["id"],
                model_code=model_code,
                trim_code="BASE",
                build_date=BUILD_DATE,
                msrp_cents=msrp_cents,
                sale_date=f"{sale_day}T00:00:00.000Z",
                customer_region_code="WEST",
                deal_type="CASH",
            )
            fx.validate_delivery(delivery["id"])

    unit_entry = validate_success(
        api_client.run_accrual(
            program_unit["id"], f.run_accrual_payload("2026-08"), fx.CONTROLLER
        ),
        201,
    )
    a.assert_accrual_shape(unit_entry)
    a.assert_int_field(unit_entry, "unit_basis", 3)
    a.assert_money(unit_entry, "accrued_cents", 291750)
    a.assert_money(unit_entry, "reversal_cents", 0)
    assert unit_entry["entry_type"] == "ACCRUAL", unit_entry["entry_type"]
    # The method is snapshotted onto the row, so a later program edit cannot
    # silently restate history.
    assert unit_entry["accrual_method"] == "UNIT_BASED", unit_entry["accrual_method"]

    take_entry = validate_success(
        api_client.run_accrual(
            program_take["id"], f.run_accrual_payload("2026-08"), fx.CONTROLLER
        ),
        201,
    )
    a.assert_int_field(take_entry, "unit_basis", 3)
    a.assert_money(take_entry, "accrued_cents", 195000)
    assert take_entry["accrual_method"] == "TAKE_RATE_BASED", (
        take_entry["accrual_method"]
    )

    # Identical unit_basis, so the 96750-cent divergence is the variant alone.
    assert take_entry["unit_basis"] == unit_entry["unit_basis"]
    assert take_entry["accrued_cents"] - unit_entry["accrued_cents"] == -96750

    unit_summary = validate_success(
        api_client.get_spend_summary(program_unit["id"], fx.CONTROLLER)
    )
    a.assert_money(unit_summary, "accrued_budget_cents", 291750)
    take_summary = validate_success(
        api_client.get_spend_summary(program_take["id"], fx.CONTROLLER)
    )
    a.assert_money(take_summary, "accrued_budget_cents", 195000)
    # Neither program carries a single claim, so the accrual is delivery-driven.
    a.assert_int_field(unit_summary, "claimed_units", 0)
    a.assert_int_field(take_summary, "claimed_units", 0)


# --- Residual value impact ----------------------------------------------------


def test_residual_impact_floors_at_every_one_of_its_three_divisions():
    """A second supported lease LOWERS residual_impact_bps from 240 to 239.

    PRD §3.9: "Every division in this calculation floors — half-up rounding
    appears nowhere in it — and the floors are applied at steps three, four and
    five in that order."

    Design: Corner/calculations/residual_impact_floors_at_every_one_of_its_three_divisions
    """
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        name="Residual Motors", region_code="SOUTH",
        historical_volume_units=4, market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        rules=[_rule("SDN3", "SOUTH", ["LEASE"])],
        name="Residual Lease Support",
        incentive_type="LEASE_SUPPORT",
        effective_from=AUG_01,
        effective_to=SEP_01,
        per_unit_amount_cents=0,
        residual_support_bps=400,
        budget_cents=12000000,
        stack_group="CRNRES",
        priority_rank=406,
        accrual_method="UNIT_BASED",
    )
    fx.set_clock(AUG_06)
    deliveries = []
    for msrp_cents in (3750000, 3333333):
        delivery = fx.report_lease_delivery(
            dealer["id"],
            model_code="SDN3",
            trim_code="BASE",
            build_date=BUILD_DATE,
            msrp_cents=msrp_cents,
            sale_date=SALE_AUG_05,
            customer_region_code="SOUTH",
            term_months=36,
            base_residual_bps=5500,
        )
        fx.validate_delivery(delivery["id"])
        deliveries.append(delivery)

    # With no supported unit yet the calculation stops at step two with 0 —
    # never null and never a division error.
    a.assert_bps(fx.read_program(program["id"]), "residual_impact_bps", 0)

    first = _submit_and_approve_claim(
        dealer["id"], deliveries[0]["id"], program["id"], 150000
    )
    a.assert_money(first, "approved_amount_cents", 150000)
    after_one = validate_success(
        api_client.get_spend_summary(program["id"], fx.CONTROLLER)
    )
    a.assert_bps(after_one, "residual_impact_bps", 240)

    second = _submit_and_approve_claim(
        dealer["id"], deliveries[1]["id"], program["id"], 133333
    )
    a.assert_money(second, "approved_amount_cents", 133333)
    after_two = validate_success(
        api_client.get_spend_summary(program["id"], fx.CONTROLLER)
    )
    a.assert_bps(after_two, "residual_impact_bps", 239)
    assert after_two["residual_impact_bps"] < after_one["residual_impact_bps"], (
        "the three stacked floors make a second supported lease lower the "
        "residual impact by one basis point"
    )
    # Every step read the raw msrp_cents of the two deliveries, with no
    # deduction for anything stacked on the same deals.
    a.assert_money(after_two, "committed_cents", 283333)


# --- The per-unit incentive spend monitor -------------------------------------


def test_per_unit_spend_floors_the_average_and_excludes_rejected_claims():
    """595017 over 2 units floors to 297508, and a rejected claim leaves the set.

    PRD §3.7: "`per_unit_spend_cents` is that spend divided by `claimed_units` and
    floored; when `claimed_units` is 0 the result is exactly 0 rather than null and
    never a division error."

    Design: Corner/calculations/per_unit_spend_floors_the_average_and_excludes_rejected_claims
    """
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        name="Spend Filter Motors", region_code="EAST",
        historical_volume_units=4, market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        rules=[_rule("SDN3", "EAST", ["FINANCE"])],
        name="Spend Filter Subvention",
        incentive_type="FINANCE_SUBVENTION",
        effective_from=AUG_01,
        effective_to=SEP_01,
        per_unit_amount_cents=100000,
        apr_buydown_bps=137,
        budget_cents=12000000,
        stack_group="CRNSPD",
        priority_rank=407,
        accrual_method="UNIT_BASED",
    )
    fx.set_clock(AUG_06)
    specs = (
        (3333333, 39, 500),
        (3600000, 60, 599),
        (3600000, 60, 599),
    )
    deliveries = []
    for msrp_cents, term_months, contract_apr_bps in specs:
        delivery = fx.report_finance_delivery(
            dealer["id"],
            model_code="SDN3",
            trim_code="BASE",
            build_date=BUILD_DATE,
            msrp_cents=msrp_cents,
            sale_date=SALE_AUG_05,
            customer_region_code="EAST",
            term_months=term_months,
            contract_apr_bps=contract_apr_bps,
        )
        fx.validate_delivery(delivery["id"])
        deliveries.append(delivery)

    first = _submit_and_approve_claim(
        dealer["id"], deliveries[0]["id"], program["id"], 248417
    )
    a.assert_money(first, "approved_amount_cents", 248417)
    second = _submit_and_approve_claim(
        dealer["id"], deliveries[1]["id"], program["id"], 346600
    )
    a.assert_money(second, "approved_amount_cents", 346600)

    two_claims = validate_success(
        api_client.get_spend_summary(program["id"], fx.CONTROLLER)
    )
    a.assert_int_field(two_claims, "claimed_units", 2)
    a.assert_money(two_claims, "committed_cents", 595017)
    # The true average is 297508.5, so flooring and half-up rounding disagree
    # here and flooring is the pinned direction.
    a.assert_money(two_claims, "per_unit_spend_cents", 297508)

    third = validate_success(
        api_client.create_claim(
            f.create_claim_payload(
                deliveries[2]["id"], program["id"], 346600,
                fx.program_version(program["id"]),
            ),
            make_dealer_headers(dealer["id"]),
        ),
        201,
    )
    rejected = validate_success(
        api_client.adjudicate_claim(
            third["id"],
            f.adjudicate_payload("REJECT", rejection_error_id="ERR_DUPLICATE_CLAIM"),
            fx.ADJUDICATOR,
        )
    )
    a.assert_claim_dimensions(rejected, "REJECTED", "UNPAID")
    a.assert_money(rejected, "approved_amount_cents", 0)

    three_claims = validate_success(
        api_client.get_spend_summary(program["id"], fx.CONTROLLER)
    )
    # The rejected claim is absent from BOTH the numerator and the denominator.
    a.assert_int_field(three_claims, "claimed_units", 2)
    a.assert_money(three_claims, "committed_cents", 595017)
    a.assert_money(three_claims, "per_unit_spend_cents", 297508)

    # The rejected claim still exists and is still listed; it is excluded from
    # the aggregate rather than deleted.
    listed, _meta = validate_paginated(
        api_client.list_claims(fx.CONTROLLER, {"program_id": program["id"]})
    )
    assert third["id"] in [row["id"] for row in listed], listed


# --- The read-only stacking-waterfall projection ------------------------------


def test_eligible_programs_projection_separates_eligible_capped_out_and_blocked():
    """One pass fills all three buckets: P1 accepted, P2 capped out, P3 blocked.

    PRD §3.6: "The read-only projection over one delivery returns that whole
    picture at once: the `delivery_id` it was asked about, `eligible_program_ids`
    for the candidates the walk accepted, `blocked_program_ids` for those a
    `FORBIDDEN` edge excluded, `capped_out_program_ids` for those a ceiling
    excluded, and `stacked_total_cents` for the running total the walk arrived at."

    Design: Corner/calculations/eligible_programs_projection_separates_eligible_capped_out_and_blocked
    """
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        name="Waterfall Motors", region_code="WEST",
        historical_volume_units=4, market_opportunity_bps=0,
    )
    shared_rule = [_rule("MX5", "WEST", ["FINANCE"])]
    # Three different incentive types, so the program-overlap rule never applies.
    p1 = fx.create_draft_program_with_rules(
        rules=shared_rule,
        name="Waterfall Cash",
        incentive_type="CUSTOMER_CASH",
        effective_from=AUG_01,
        effective_to=SEP_01,
        per_unit_amount_cents=100000,
        budget_cents=12000000,
        stack_group="CRNWF",
        priority_rank=10,
        accrual_method="UNIT_BASED",
    )
    p2 = fx.create_draft_program_with_rules(
        rules=shared_rule,
        name="Waterfall Subvention",
        incentive_type="FINANCE_SUBVENTION",
        effective_from=AUG_01,
        effective_to=SEP_01,
        per_unit_amount_cents=50000,
        apr_buydown_bps=200,
        stack_cap_cents=200000,
        budget_cents=12000000,
        stack_group="CRNWF",
        priority_rank=20,
        accrual_method="UNIT_BASED",
    )
    p3 = fx.create_draft_program_with_rules(
        rules=shared_rule,
        name="Waterfall Lease",
        incentive_type="LEASE_SUPPORT",
        effective_from=AUG_01,
        effective_to=SEP_01,
        per_unit_amount_cents=0,
        residual_support_bps=300,
        budget_cents=12000000,
        stack_group="CRNWF",
        priority_rank=30,
        accrual_method="UNIT_BASED",
    )
    edge = fx.add_stack_edge(p1["id"], p3["id"], "FORBIDDEN")
    assert edge["mode"] == "FORBIDDEN", edge["mode"]
    for program in (p1, p2, p3):
        fx.submit_program(program["id"])
        fx.approve_program(program["id"])

    fx.set_clock(AUG_06)
    # The projection runs on a REPORTED delivery: the waterfall does not require
    # the delivery to have been validated.
    delivery = fx.report_finance_delivery(
        dealer["id"],
        model_code="MX5",
        trim_code="BASE",
        build_date=BUILD_DATE,
        msrp_cents=3600000,
        sale_date=SALE_AUG_05,
        customer_region_code="WEST",
        term_months=60,
        contract_apr_bps=599,
    )

    projection = validate_success(
        api_client.get_eligible_programs(delivery["id"], fx.VALIDATOR)
    )
    assert projection["delivery_id"] == delivery["id"], projection["delivery_id"]
    # P1 comes first at priority_rank 10 with nothing accepted to conflict with,
    # and its stack_cap_cents of 0 means it imposes no ceiling of its own.
    assert projection["eligible_program_ids"] == [p1["id"]], projection
    # P2's gross is 50000 + 360000 == 410000, so the running total of
    # 100000 + 410000 == 510000 strictly exceeds its own 200000 ceiling.
    assert projection["capped_out_program_ids"] == [p2["id"]], projection
    # P3 is only decidable once P1 has been accepted, which is what makes the
    # pass stateful rather than three independent filters.
    assert projection["blocked_program_ids"] == [p3["id"]], projection
    # The running total counts accepted programs only.
    a.assert_money(projection, "stacked_total_cents", 100000)


# --- Retroactive repricing ----------------------------------------------------


def test_retroactive_repricing_processes_its_window_in_sale_date_order():
    """Two August claims are repriced in sale_date order; the July claim is outside.

    PRD §3.9: "The target claims are processed in `sale_date` ascending order and,
    where sale instants tie, in claim `created_at` ascending order; identifiers are
    never used to order the pass."

    Design: Corner/calculations/retroactive_repricing_processes_its_window_in_sale_date_order
    """
    fx.set_clock("2026-07-01T00:00:00.000Z")
    dealer = fx.register_dealer(
        name="Repricing Order Motors", region_code="WEST",
        historical_volume_units=4, market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        rules=[_rule("MX5", "WEST", ["CASH"], build_from="2026-04-01T00:00:00.000Z")],
        name="Repricing Order Cash",
        incentive_type="CUSTOMER_CASH",
        effective_from="2026-07-01T00:00:00.000Z",
        effective_to=SEP_01,
        per_unit_amount_cents=100000,
        budget_cents=12000000,
        stack_group="CRNRPX",
        priority_rank=408,
        accrual_method="UNIT_BASED",
    )

    fx.set_clock("2026-07-28T00:00:00.000Z")
    july = fx.report_delivery(
        dealer["id"],
        model_code="MX5",
        trim_code="BASE",
        build_date="2026-05-01T00:00:00.000Z",
        msrp_cents=3100000,
        sale_date="2026-07-27T00:00:00.000Z",
        customer_region_code="WEST",
        deal_type="CASH",
    )
    fx.validate_delivery(july["id"])
    july_claim = _submit_and_approve_claim(
        dealer["id"], july["id"], program["id"], 100000
    )
    a.assert_money(july_claim, "approved_amount_cents", 100000)
    assert july_claim["rate_basis"] == "AS_SOLD_SNAPSHOT", july_claim["rate_basis"]

    fx.set_clock("2026-08-08T00:00:00.000Z")
    # The later sale is reported and claimed FIRST, so creation order runs
    # opposite to sale_date order.
    late = fx.report_delivery(
        dealer["id"],
        model_code="MX5",
        trim_code="BASE",
        build_date="2026-05-02T00:00:00.000Z",
        msrp_cents=3100000,
        sale_date="2026-08-07T00:00:00.000Z",
        customer_region_code="WEST",
        deal_type="CASH",
    )
    early = fx.report_delivery(
        dealer["id"],
        model_code="MX5",
        trim_code="BASE",
        build_date="2026-05-03T00:00:00.000Z",
        msrp_cents=3100000,
        sale_date="2026-08-03T00:00:00.000Z",
        customer_region_code="WEST",
        deal_type="CASH",
    )
    fx.validate_delivery(late["id"])
    fx.validate_delivery(early["id"])
    late_claim = _submit_and_approve_claim(
        dealer["id"], late["id"], program["id"], 100000
    )
    early_claim = _submit_and_approve_claim(
        dealer["id"], early["id"], program["id"], 100000
    )

    before = validate_success(
        api_client.get_spend_summary(program["id"], fx.CONTROLLER)
    )
    a.assert_money(before, "committed_cents", 300000)
    a.assert_money(before, "per_unit_spend_cents", 100000)

    fx.set_clock("2026-08-10T00:00:00.000Z")
    repricing = validate_success(
        api_client.create_repricing(
            program["id"],
            f.create_repricing_payload(
                "RETROACTIVE_TO_MONTH_START", 120000,
                fx.program_version(program["id"]),
            ),
            fx.DESIGNER,
        ),
        201,
    )
    a.assert_repricing_shape(repricing)
    assert repricing["mode"] == "RETROACTIVE_TO_MONTH_START", repricing["mode"]
    a.assert_money(repricing, "previous_per_unit_amount_cents", 100000)
    a.assert_money(repricing, "new_per_unit_amount_cents", 120000)
    # month_start is derived from the logical clock, never from a payload field.
    assert repricing["effective_at"] == "2026-08-10T00:00:00.000Z", repricing
    assert repricing["month_start"] == AUG_01, repricing
    # Only the two August claims sit in the half-open window.
    a.assert_int_field(repricing, "affected_claim_count", 2)
    a.assert_money(repricing, "net_adjustment_cents", 40000)

    for claim in (early_claim, late_claim):
        repriced = fx.read_claim(claim["id"])
        a.assert_money(repriced, "approved_amount_cents", 120000)
        assert repriced["rate_basis"] == "REPRICED_CURRENT", repriced["rate_basis"]

    untouched = fx.read_claim(july_claim["id"])
    a.assert_money(untouched, "approved_amount_cents", 100000)
    assert untouched["rate_basis"] == "AS_SOLD_SNAPSHOT", untouched["rate_basis"]

    after = validate_success(
        api_client.get_spend_summary(program["id"], fx.CONTROLLER)
    )
    a.assert_money(after, "committed_cents", 340000)
    a.assert_int_field(after, "claimed_units", 3)
    a.assert_money(after, "per_unit_spend_cents", 113333)
