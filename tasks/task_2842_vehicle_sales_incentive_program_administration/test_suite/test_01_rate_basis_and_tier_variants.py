"""Dual-variant money arithmetic: the claim rate basis and the stair-step payout.

Two calculations in this service each carry two variants that turn identical
inputs into different numbers. The claim's per-unit rate flips between the
claim's own frozen snapshot and the program's repriced current amount, driven
only by whether a retroactive repricing window reaches back over the delivery's
sale instant. The stair-step payout flips between marginal bands and a
full-volume re-rate, driven only by the program's tier_bonus_mode.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import api_client
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import AUG_01, BUILD_FROM, BUILD_TO, SEP_01

AUG_02 = "2026-08-02T00:00:00.000Z"
AUG_05 = "2026-08-05T00:00:00.000Z"
AUG_20 = "2026-08-20T00:00:00.000Z"

FINANCE_RULE = {
    "model_code": "MX5",
    "region_code": "WEST",
    "build_date_from": BUILD_FROM,
    "build_date_to": BUILD_TO,
    "allowed_deal_types": ["FINANCE"],
}

STAIR_RULE = {
    "model_code": "MX5",
    "region_code": "WEST",
    "build_date_from": BUILD_FROM,
    "build_date_to": BUILD_TO,
    "allowed_deal_types": ["CASH"],
}

TIER_SCHEDULE = [
    {"tier_index": 1, "threshold_bps": 5000, "per_unit_bonus_cents": 30000},
    {"tier_index": 2, "threshold_bps": 10000, "per_unit_bonus_cents": 50000},
]


def _finance_claim_chain():
    """One ACTIVE FINANCE_SUBVENTION program at 200000 cents per unit with a
    300 bps buy-down, one VALIDATED FINANCE delivery of MSRP 4000000 sold on
    2026-08-05 over 60 months at a 299 bps contract APR, and one SUBMITTED,
    UNPAID claim on it whose snapshot_per_unit_cents is frozen at 200000."""
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        name="Northgate Motors",
        region_code="WEST",
        historical_volume_units=16,
        market_opportunity_bps=1500,
    )
    program = fx.create_active_program(
        payload=f.create_program_payload(
            name="August Finance Subvention",
            incentive_type="FINANCE_SUBVENTION",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=200000,
            budget_cents=100000000,
            stack_group="AUG-FIN",
            priority_rank=20,
            apr_buydown_bps=300,
        ),
        rules=[FINANCE_RULE],
    )
    fx.set_clock(AUG_05)
    delivery = fx.report_delivery(
        dealer["id"],
        model_code="MX5",
        trim_code="GT",
        build_date="2026-06-15T00:00:00.000Z",
        msrp_cents=4000000,
        sale_date=AUG_05,
        customer_region_code="WEST",
        deal_type="FINANCE",
        term_months=60,
        contract_apr_bps=299,
    )
    fx.validate_delivery(delivery["id"])
    claim = fx.submit_claim(dealer["id"], delivery["id"], program["id"], 800000)
    return {
        "dealer": dealer,
        "program": program,
        "delivery": delivery,
        "claim": claim,
    }


def _approve(claim_id):
    return validate_success(
        api_client.adjudicate_claim(
            claim_id, f.adjudicate_payload("APPROVE"), fx.ADJUDICATOR
        )
    )


def _reprice_retroactively(program_id, new_per_unit_amount_cents):
    return validate_success(
        api_client.create_repricing(
            program_id,
            f.create_repricing_payload(
                "RETROACTIVE_TO_MONTH_START",
                new_per_unit_amount_cents,
                fx.program_version(program_id),
            ),
            fx.DESIGNER,
        ),
        201,
    )


def test_claim_approved_on_the_as_sold_snapshot_rate_basis():
    """With no repricing event on the program, approval prices the claim from its
    own frozen snapshot and records the AS_SOLD_SNAPSHOT basis.

    PRD §3.7: "Otherwise the rate is the claim's own frozen
    `snapshot_per_unit_cents` and `rate_basis` is recorded as
    `AS_SOLD_SNAPSHOT`."

    Design: Difficulty/dual_variant_calc/claim_rate_basis_snapshot_versus_repriced_current
    """
    chain = _finance_claim_chain()

    approved = _approve(chain["claim"]["id"])

    a.assert_claim_shape(approved)
    assert approved["rate_basis"] == "AS_SOLD_SNAPSHOT", (
        "an un-repriced program must price the claim from the frozen snapshot, "
        f"got rate_basis {approved['rate_basis']!r}"
    )
    a.assert_money(approved, "snapshot_per_unit_cents", 200000)
    a.assert_money(approved, "approved_amount_cents", 800000)
    a.assert_claim_dimensions(approved, "VALIDATED", "UNPAID")


def test_finance_subvention_leg_rides_on_the_snapshot_rate():
    """The 800000 approved on the snapshot basis is the 200000 snapshot rate plus
    a 600000 finance-subvention leg computed once over the whole expression.

    PRD §3.7: "The leg is the delivery's `msrp_cents` multiplied by the effective
    buy-down in basis points, multiplied by the delivery's `term_months`, divided
    by 120000, with half-up rounding applied once to that entire expression
    rather than to any individual factor."

    Design: Difficulty/dual_variant_calc/claim_rate_basis_snapshot_versus_repriced_current
    """
    chain = _finance_claim_chain()

    approved = _approve(chain["claim"]["id"])

    a.assert_money(approved, "approved_amount_cents", 800000)
    a.assert_money(approved, "claimed_amount_cents", 800000)
    leg = approved["approved_amount_cents"] - approved["snapshot_per_unit_cents"]
    assert leg == 600000, (
        "the finance leg must be 600000 cents (4000000 msrp * 300 effective bps "
        f"* 60 months / 120000), got {leg}"
    )
    program = fx.read_program(chain["program"]["id"])
    a.assert_program_money(program, committed_cents=800000, paid_cents=0,
                           claimed_units=1)


def test_retroactive_repricing_flips_the_same_claim_to_repriced_current():
    """A RETROACTIVE_TO_MONTH_START repricing whose window contains the delivery's
    sale_date re-prices the already-approved claim from 800000 to 860000.

    PRD §3.7: "If there exists a repricing event on the claimed program whose
    `mode` is `RETROACTIVE_TO_MONTH_START` and whose window — from its
    `month_start` inclusive to its `effective_at` exclusive — contains the
    delivery's `sale_date`, then the rate is the program's **current**
    `per_unit_amount_cents` and `rate_basis` is recorded as `REPRICED_CURRENT`."

    Design: Difficulty/dual_variant_calc/claim_rate_basis_snapshot_versus_repriced_current
    """
    chain = _finance_claim_chain()
    approved = _approve(chain["claim"]["id"])
    a.assert_money(approved, "approved_amount_cents", 800000)

    fx.set_clock(AUG_20)
    _reprice_retroactively(chain["program"]["id"], 260000)

    repriced = fx.read_claim(chain["claim"]["id"])
    a.assert_money(repriced, "approved_amount_cents", 860000)
    assert repriced["approved_amount_cents"] != 800000, (
        "the repriced_current variant must pay 860000 (260000 current rate + "
        "600000 finance leg) and not the 800000 the as_sold_snapshot variant paid"
    )
    assert repriced["rate_basis"] == "REPRICED_CURRENT", (
        "the retroactive window covers the sale instant, so rate_basis must be "
        f"REPRICED_CURRENT, got {repriced['rate_basis']!r}"
    )
    a.assert_money(repriced, "snapshot_per_unit_cents", 200000)
    a.assert_claim_dimensions(repriced, "VALIDATED", "UNPAID")


def test_repricing_event_records_its_baseline_month_start_and_net_adjustment():
    """The repricing event itself is the discriminating side effect: it archives
    the pre-write rate, the containing month's first instant, and one affected
    claim carrying a +60000 signed delta.

    PRD §3.9: "The event records `previous_per_unit_amount_cents` as the
    program's `per_unit_amount_cents` immediately before the write, stamps
    `effective_at` from the logical clock, and computes `month_start` as the
    first instant of the calendar month containing `effective_at`."

    Design: Difficulty/dual_variant_calc/claim_rate_basis_snapshot_versus_repriced_current
    """
    chain = _finance_claim_chain()
    _approve(chain["claim"]["id"])

    fx.set_clock(AUG_20)
    event = _reprice_retroactively(chain["program"]["id"], 260000)

    a.assert_repricing_shape(event)
    assert event["mode"] == "RETROACTIVE_TO_MONTH_START", event["mode"]
    a.assert_money(event, "previous_per_unit_amount_cents", 200000)
    a.assert_money(event, "new_per_unit_amount_cents", 260000)
    assert event["month_start"] == AUG_01, (
        f"month_start must be {AUG_01}, got {event['month_start']!r}"
    )
    assert event["effective_at"] == AUG_20, (
        f"effective_at must be stamped from the clock at {AUG_20}, "
        f"got {event['effective_at']!r}"
    )
    a.assert_int_field(event, "affected_claim_count", 1)
    a.assert_money(event, "net_adjustment_cents", 60000)


def test_program_ledger_follows_the_repriced_amount():
    """The re-evaluation pass recomputes the program's committed ledger and its
    per-unit spend monitor from the repriced claim amount.

    PRD §3.9: "When the pass completes, the program's `committed_cents`,
    `claimed_units` and `per_unit_spend_cents` are all recomputed."

    Design: Difficulty/dual_variant_calc/claim_rate_basis_snapshot_versus_repriced_current
    """
    chain = _finance_claim_chain()
    _approve(chain["claim"]["id"])

    fx.set_clock(AUG_20)
    _reprice_retroactively(chain["program"]["id"], 260000)

    program = fx.read_program(chain["program"]["id"])
    a.assert_program_money(program, committed_cents=860000, paid_cents=0,
                           claimed_units=1)
    a.assert_money(program, "per_unit_spend_cents", 860000)
    a.assert_money(program, "per_unit_amount_cents", 260000)


def _two_mode_stair_step_chain():
    """One dealer whose historical volume of 4 units and zero market opportunity
    make objective_units 4, two ACTIVE DEALER_STAIR_STEP programs sharing the
    MX5/WEST/CASH footprint and an identical tier schedule but differing only in
    tier_bonus_mode, one PROPOSED objective under each, and three MX5/CASH
    deliveries of which two are already VALIDATED."""
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        name="Riverbend Auto",
        region_code="WEST",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    marginal = fx.create_draft_program_with_rules(
        payload=f.create_program_payload(
            name="August Stair Step Marginal",
            incentive_type="DEALER_STAIR_STEP",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=0,
            budget_cents=50000000,
            stack_group="AUG-STAIR",
            priority_rank=40,
            tier_schedule=TIER_SCHEDULE,
            tier_bonus_mode="MARGINAL",
        ),
        rules=[STAIR_RULE],
    )
    full_volume = fx.create_draft_program_with_rules(
        payload=f.create_program_payload(
            name="August Stair Step Full Volume",
            incentive_type="DEALER_STAIR_STEP",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=0,
            budget_cents=50000000,
            stack_group="AUG-STAIR",
            priority_rank=41,
            tier_schedule=TIER_SCHEDULE,
            tier_bonus_mode="FULL_VOLUME",
        ),
        rules=[STAIR_RULE],
    )
    # The two programs share one footprint, so the ALLOWED edge is the designer's
    # explicit statement that the collision is intentional and priced.
    fx.add_stack_edge(marginal["id"], full_volume["id"], "ALLOWED")
    for program_id in (marginal["id"], full_volume["id"]):
        fx.submit_program(program_id)
        fx.approve_program(program_id)
    objective_marginal = fx.assign_objective(marginal["id"], dealer["id"],
                                             stretch_bps=0)
    objective_full = fx.assign_objective(full_volume["id"], dealer["id"],
                                         stretch_bps=0)
    # The sale instants sit one day after the clock's startup default, so the
    # clock moves first and every report carries a reporting lag of zero.
    fx.set_clock(AUG_02)
    deliveries = []
    for day in (1, 2, 3):
        deliveries.append(
            fx.report_delivery(
                dealer["id"],
                model_code="MX5",
                trim_code="GT",
                build_date=f"2026-06-0{day}T00:00:00.000Z",
                msrp_cents=3000000,
                sale_date=AUG_02,
                customer_region_code="WEST",
                deal_type="CASH",
            )
        )
    fx.validate_delivery(deliveries[0]["id"])
    fx.validate_delivery(deliveries[1]["id"])
    return {
        "dealer": dealer,
        "marginal": marginal,
        "full_volume": full_volume,
        "objective_marginal": objective_marginal,
        "objective_full": objective_full,
        "deliveries": deliveries,
    }


def test_marginal_mode_pays_only_the_units_inside_the_attained_band():
    """At objective_units 4 and achieved_units 3 the MARGINAL variant pays 60000:
    tier 1's band spans units 2 through 3, so two band units earn 30000 each.

    PRD §3.7: "Under `MARGINAL`, `payout_cents` starts at 0 and accumulates one
    band at a time over the tiers whose `tier_index` is at or below
    `tier_attained`, taken in ascending `tier_index`: the band's upper unit is
    one less than the unit threshold of the next tier in the schedule, or
    unbounded when the tier is the last one; the band's unit count is the smaller
    of `achieved_units` and that upper unit, minus the tier's own unit threshold,
    plus one; and the band contributes its unit count multiplied by that tier's
    `per_unit_bonus_cents`."

    Design: Difficulty/dual_variant_calc/stair_step_payout_marginal_bands_versus_full_volume
    """
    chain = _two_mode_stair_step_chain()

    fx.validate_delivery(chain["deliveries"][2]["id"])

    objective = fx.read_objective(chain["objective_marginal"]["id"])
    a.assert_objective_shape(objective)
    a.assert_int_field(objective, "objective_units", 4)
    a.assert_objective_attainment(
        objective, achieved_units=3, attainment_bps=7500, tier_attained=1,
        payout_cents=60000,
    )
    assert objective["payout_cents"] != 90000, (
        "MARGINAL must pay 60000 for the two units inside tier 1's band and not "
        "the 90000 that re-rating all three achieved units would produce"
    )


def test_full_volume_mode_re_rates_every_achieved_unit_at_the_attained_tier():
    """On the identical objective the FULL_VOLUME variant pays 90000: all three
    achieved units re-rated at tier 1's 30000 per unit.

    PRD §3.7: "Under `FULL_VOLUME`, `payout_cents` is instead every one of the
    objective's `achieved_units` multiplied by the `per_unit_bonus_cents` of the
    single tier whose `tier_index` equals `tier_attained` — a retroactive re-rate
    of the whole volume at the top tier reached, which for identical
    `achieved_units`, `objective_units` and `tier_schedule` always pays strictly
    more than the marginal-band variant."

    Design: Difficulty/dual_variant_calc/stair_step_payout_marginal_bands_versus_full_volume
    """
    chain = _two_mode_stair_step_chain()

    fx.validate_delivery(chain["deliveries"][2]["id"])

    objective = fx.read_objective(chain["objective_full"]["id"])
    a.assert_objective_shape(objective)
    a.assert_int_field(objective, "objective_units", 4)
    a.assert_objective_attainment(
        objective, achieved_units=3, attainment_bps=7500, tier_attained=1,
        payout_cents=90000,
    )
    assert objective["payout_cents"] != 60000, (
        "FULL_VOLUME must re-rate all three achieved units to 90000 and not stop "
        "at the 60000 the marginal-band variant pays"
    )


def test_attainment_and_tier_are_identical_while_only_the_payout_diverges():
    """The mode flag is the only cause of the divergence: both objectives floor to
    the same attainment and reach the same tier, yet the payouts differ by
    exactly 30000.

    PRD §3.7: "`tier_attained` is the highest `tier_index` among the program's
    `tier_schedule` entries whose `threshold_bps` is **at or below**
    `attainment_bps`, and it is 0 when no tier qualifies."

    Design: Difficulty/dual_variant_calc/stair_step_payout_marginal_bands_versus_full_volume
    """
    chain = _two_mode_stair_step_chain()

    fx.validate_delivery(chain["deliveries"][2]["id"])

    marginal = fx.read_objective(chain["objective_marginal"]["id"])
    full_volume = fx.read_objective(chain["objective_full"]["id"])

    a.assert_bps(marginal, "attainment_bps", 7500)
    a.assert_bps(full_volume, "attainment_bps", 7500)
    a.assert_int_field(marginal, "tier_attained", 1)
    a.assert_int_field(full_volume, "tier_attained", 1)
    a.assert_int_field(marginal, "achieved_units", 3)
    a.assert_int_field(full_volume, "achieved_units", 3)
    divergence = full_volume["payout_cents"] - marginal["payout_cents"]
    assert divergence == 30000, (
        "with identical attainment and tier schedule the two bonus modes must "
        f"diverge by exactly 30000 cents, got {divergence}"
    )
