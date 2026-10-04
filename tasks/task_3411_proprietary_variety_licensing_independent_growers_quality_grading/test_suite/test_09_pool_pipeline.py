"""Pool pipeline (canonical 3-lot scenario): provisional vs final variants,
pinned evaluation order, per-lot rounding with remainder allocation, and the
zero-sum distribution invariant.

Canonical scenario (PRD section 3.8 rules applied): H1 net 1150 PREMIUM
(weighted 1322.5, cold-chain compliant); H2 net 800 STANDARD (9h breach);
H3 net 2000 STANDARD (grower G2). Pool STRAWBERRY [2026-10-05, 2026-10-12),
closed at estimated 500c/kg, settled at actual 520c/kg.
"""
import pytest
from test_helpers import (
    validate_success,
    POOL_CLOSE_CLOCK, POOL_ESTIMATED_PRICE, POOL_ACTUAL_PRICE,
    set_clock, create_grower, create_active_agreement, create_plant_lot,
    plan_planting, confirm_planting, create_lot_in_transit, receive_lot,
    submit_grade, certify_lot, create_pool, close_pool, settle_pool,
    get_pool, get_harvest_lot, get_statement, find_statement,
    setup_lot_certified, assert_pool_zero_sum,
)

STANDARD_SCORES = dict(flavor_brix=9.5, firmness_g=320,
                       appearance_score=75, defect_pct=4.0)


def _canonical_pool(api, settle=False):
    """Builds the canonical scenario through close (and optionally settle).
    Returns dict with pool, h1, h2, h3, g1, g2, s1, s2 (freshly read)."""
    bundle = setup_lot_certified()  # H1 net 1150 PREMIUM compliant, G1
    g1 = bundle["grower"]
    variety = bundle["variety"]
    # H2 on the same planting: net 800 STANDARD, 9h precool breach.
    set_clock("2026-10-07T06:30:00Z")
    h2 = create_lot_in_transit(bundle["planting"], g1,
                               harvested_at="2026-10-07T06:00:00Z",
                               gross_weight_kg=850, tare_weight_kg=50)
    set_clock("2026-10-07T15:30:00Z")
    h2 = receive_lot(h2["id"], received_at="2026-10-07T15:00:00Z",
                     pulp_temp_c_at_receipt=3.0)
    h2 = submit_grade(h2["id"], **STANDARD_SCORES)
    h2 = certify_lot(h2["id"])
    # G2 chain: planting P2 (2500 plants), H3 net 2000 STANDARD compliant.
    g2 = create_grower(legal_name="Coastal Berry Co")
    a2 = create_active_agreement(g2, variety,
                                 cultural_practice_codes=["CONVENTIONAL"])
    l2 = create_plant_lot(a2, variety, quantity_plants=3000)
    p2 = plan_planting(a2, l2, g2, planned_plants=2500)
    p2 = confirm_planting(p2, g2, 2500)
    set_clock("2026-10-08T06:30:00Z")
    h3 = create_lot_in_transit(p2, g2, harvested_at="2026-10-08T06:00:00Z",
                               gross_weight_kg=2050, tare_weight_kg=50)
    set_clock("2026-10-08T12:30:00Z")
    h3 = receive_lot(h3["id"], received_at="2026-10-08T12:00:00Z",
                     pulp_temp_c_at_receipt=2.8)
    h3 = submit_grade(h3["id"], **STANDARD_SCORES)
    h3 = certify_lot(h3["id"])
    pool = create_pool()  # STRAWBERRY [2026-10-05, 2026-10-12), not shoulder
    set_clock(POOL_CLOSE_CLOCK)
    pool = close_pool(pool["id"], POOL_ESTIMATED_PRICE)
    s1 = find_statement(pool["id"], g1["id"])
    s2 = find_statement(pool["id"], g2["id"])
    if settle:
        pool = settle_pool(pool["id"], POOL_ACTUAL_PRICE)
    out = {"pool": get_pool(pool["id"]),
           "h1": get_harvest_lot(bundle["harvest_lot"]["id"]),
           "h2": get_harvest_lot(h2["id"]), "h3": get_harvest_lot(h3["id"]),
           "g1": g1, "g2": g2,
           "s1": get_statement(s1["id"]), "s2": get_statement(s2["id"])}
    return out


def test_pool_provisional_pipeline_at_close(api):
    """PRD section 3.8: "First, `total_net_kg` is the sum of `net_kg` over the
    included lots. Second, `total_weighted_kg` is the sum over included lots of
    each lot's `net_kg` multiplied by its grade's pool weight — 1.15 for
    `PREMIUM`, 1.00 for `STANDARD`, 0.55 for `PROCESS`, and 0.25 for `JUICE`."
    PRD section 3.8: "at close this is stored as `provisional_pool_rate`".

    Design: Difficulty/dual_variant_calc/pool_rate_provisional_vs_final
    """
    s = _canonical_pool(api, settle=False)
    pool = s["pool"]
    assert pool["status"] == "CLOSED"
    assert pool["total_net_kg"] == 3950
    assert pool["total_weighted_kg"] == 4122.5
    assert pool["gross_pool_revenue_cents"] == 1975000
    assert pool["marketing_fee_cents"] == 118500
    assert pool["net_pool_revenue_cents"] == 1856500
    assert pool["provisional_pool_rate"] == pytest.approx(450.3335, abs=5e-5)
    assert pool["final_pool_rate"] is None
    assert s["h1"]["lot_gross_provisional_cents"] == 595566
    assert s["h2"]["lot_gross_provisional_cents"] == 360267
    assert s["h3"]["lot_gross_provisional_cents"] == 900667
    assert s["s1"]["status"] == "PROVISIONAL"
    assert s["s1"]["provisional_net_cents"] == 927012


def test_pool_final_pipeline_at_settle_persists_both_variants(api):
    """PRD section 3.8: "The same pipeline re-runs with the actual price, and
    identical lots under a different price legitimately produce different money
    — that reconciliation is the point of the two-stage design."

    Design: Difficulty/dual_variant_calc/pool_rate_provisional_vs_final
    """
    s = _canonical_pool(api, settle=True)
    pool = s["pool"]
    assert pool["status"] == "SETTLED"
    assert pool["gross_pool_revenue_cents"] == 2054000
    assert pool["marketing_fee_cents"] == 123240
    assert pool["net_pool_revenue_cents"] == 1930760
    assert pool["final_pool_rate"] == pytest.approx(468.3469, abs=5e-5)
    assert pool["pool_distributable_cents"] == 1930760
    assert not (abs(pool["provisional_pool_rate"] - pool["final_pool_rate"]) < 1e-9)
    # Both variants persist side by side on every lot.
    assert s["h1"]["lot_gross_provisional_cents"] == 595566
    assert s["h1"]["lot_gross_final_cents"] == 619389
    assert s["h2"]["lot_gross_provisional_cents"] == 360267
    assert s["h2"]["lot_gross_final_cents"] == 374678
    assert s["h3"]["lot_gross_provisional_cents"] == 900667
    assert s["h3"]["lot_gross_final_cents"] == 936693, "includes -1 remainder"
    for lot in (s["h1"], s["h2"], s["h3"]):
        assert lot["lot_status"] == "SETTLED"
        assert lot["pool_period_id"] == pool["id"]
    assert s["s1"]["status"] == "ISSUED"
    assert s["s1"]["gross_cents"] == 994067
    assert s["s1"]["cold_chain_deduction_cents"] == 29974
    assert s["s1"]["royalty_offset_cents"] == 0
    assert s["s1"]["recall_credit_cents"] == 0
    assert s["s1"]["net_cents"] == 964093
    assert s["s2"]["gross_cents"] == 936693
    assert s["s2"]["cold_chain_deduction_cents"] == 0
    assert s["s2"]["net_cents"] == 936693


def test_evaluation_order_fee_carved_from_gross_at_close(api):
    """PRD section 3.8: "Fourth, `marketing_fee_cents` is 6% of
    `gross_pool_revenue_cents`, rounded half-up to whole cents."
    PRD section 3.8: "The ordering is load-bearing: the marketing fee is carved
    out of gross revenue before the rate is derived, and the rate is never an
    input to the fee."

    Design: Difficulty/combinatorial_formula/settlement_evaluation_order_mode_c
    """
    s = _canonical_pool(api, settle=True)
    pool = s["pool"]
    assert pool["marketing_fee_cents"] != 111390, (
        "111390 would be 6% of NET revenue — the inverted order")
    # 118500 == round_half_up(1975000 x 0.06): fee computed FROM gross.
    assert pool["provisional_pool_rate"] == pytest.approx(450.3335, abs=5e-5)
    assert not (abs(pool["provisional_pool_rate"] - 479.0782) < 1e-4), (
        "479.0782 would derive the rate from gross — the inverted order")


def test_evaluation_order_fee_carved_from_gross_at_settle(api):
    """PRD section 3.8: "Sixth, the base rate is `net_pool_revenue_cents`
    divided by `total_weighted_kg`, rounded half-up to 4 decimal places."

    Design: Difficulty/combinatorial_formula/settlement_evaluation_order_mode_c
    """
    s = _canonical_pool(api, settle=True)
    pool = s["pool"]
    assert pool["marketing_fee_cents"] == 123240, "round_half_up(2054000 x 0.06)"
    assert pool["final_pool_rate"] == pytest.approx(468.3469, abs=5e-5), (
        "468.3469 == round_half_up(1930760 / 4122.5, 4): rate from NET")


def test_per_lot_rounding_remainder_on_largest_lot(api):
    """PRD section 3.8: "Each included lot's `lot_gross_final_cents` is its
    `net_kg` multiplied by its grade's weight and by the final pool rate,
    rounded half-up to whole cents — per lot first, then summed."
    PRD section 3.8: "the remainder — `pool_distributable_cents` minus the sum
    of all `lot_gross_final_cents`, which may be negative — is allocated in
    full to the included lot with the largest weighted kilograms".

    Design: Difficulty/combinatorial_formula/per_lot_rounding_then_sum_mode_b
    """
    s = _canonical_pool(api, settle=True)
    assert s["h1"]["lot_gross_final_cents"] == 619389, "raw 619388.78 per-lot"
    assert s["h2"]["lot_gross_final_cents"] == 374678, "raw 374677.52 per-lot"
    # H3 raw 936693.80 would round to 936694; as the largest-weighted lot
    # (2000 wkg > 1322.5 > 800) it absorbs the -1 remainder.
    assert s["h3"]["lot_gross_final_cents"] == 936693


def test_per_lot_round_then_sum_matches_distributable(api):
    """PRD section 2.6: "Per-lot monetary values are always rounded to integer
    cents first and only then summed — the system never sums unrounded per-lot
    values and rounds the total."

    Design: Difficulty/combinatorial_formula/per_lot_rounding_then_sum_mode_b
    """
    s = _canonical_pool(api, settle=True)
    naive = 619389 + 374678 + 936694  # per-lot rounded WITHOUT the remainder
    assert naive == 1930761 != s["pool"]["pool_distributable_cents"]
    actual = (s["h1"]["lot_gross_final_cents"] + s["h2"]["lot_gross_final_cents"]
              + s["h3"]["lot_gross_final_cents"])
    assert actual == 1930760 == s["pool"]["pool_distributable_cents"]


def test_pool_zero_sum_lot_level(api):
    """PRD section 3.8: "the remainder — `pool_distributable_cents` minus the
    sum of all `lot_gross_final_cents`, which may be negative — is allocated in
    full to the included lot with the largest weighted kilograms, with ties
    broken toward the earliest `received_at` and then the earliest
    `created_at`."

    Design: Difficulty/compensating_invariant/pool_revenue_zero_sum
    """
    s = _canonical_pool(api, settle=True)
    assert_pool_zero_sum(s["pool"], [s["h1"], s["h2"], s["h3"]])


def test_pool_zero_sum_statement_rollup(api):
    """PRD section 3.8: "The statement's `gross_cents` is the sum of
    `lot_gross_final_cents` over the grower's included lots."
    PRD section 3.8: "Eighth, `pool_distributable_cents` is
    `net_pool_revenue_cents` multiplied by 1.10 for a shoulder week — or taken
    unchanged otherwise — rounded half-up to whole cents."

    Design: Difficulty/compensating_invariant/pool_revenue_zero_sum
    """
    s = _canonical_pool(api, settle=True)
    total = s["s1"]["gross_cents"] + s["s2"]["gross_cents"]
    assert total == 1930760 == s["pool"]["pool_distributable_cents"]
    provisional = (s["h1"]["lot_gross_provisional_cents"]
                   + s["h2"]["lot_gross_provisional_cents"]
                   + s["h3"]["lot_gross_provisional_cents"])
    assert provisional == 1856500, "the provisional pass conserved the same way"
