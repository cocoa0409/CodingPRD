"""Corner queue: calculation claims — KEEP side of the composite threshold,
the 90-day sell-through date math, negotiation aggregates and TTL stamping,
the CORE_BRAND 100-point cap, and the empty-set waterfall.
"""
from datetime import datetime, timezone

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_combined_negotiation,
    create_brand,
    create_brand_term,
    create_combined_negotiation_payload,
    create_decide_payload,
    create_innovation_project_payload,
    create_item,
    create_plant,
    create_rationalization_case_payload,
    create_retailer,
    get_item,
    set_clock,
    setup_capital_cycle,
    setup_scored_case,
    validate_created,
    validate_ok,
)

PM = TEST_USERS["portfolio_manager_headers"]
PM_PROPOSER = TEST_USERS["portfolio_manager_proposer_headers"]
PM_DECIDER = TEST_USERS["portfolio_manager_decider_headers"]
FC = TEST_USERS["finance_controller_headers"]


def _iso_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant regardless of fractional-digit style."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_recommendation_keep_below_composite_threshold():
    """PRD §3.2: "The `composite_score` is then computed **from the four
    already-rounded sub-scores** as a weighted blend — 0.30 times
    `volume_score`, plus 0.25 times `margin_score`, plus 0.20 times
    `shelf_resilience_score`, plus 0.25 times `backlash_resilience_score`".
    PRD §3.2: "a `composite_score` of at least 65 yields a recommendation of
    `CUT`; anything below 65 yields `KEEP`."

    Design: Corner/calculations/recommendation_keep_below_composite_threshold
    """
    brand = create_brand(core_flag=True, private_label_share_pct=40,
                         annual_net_revenue_cents=1000000000)
    plant = create_plant(quarterly_capacity_units=1000000)
    # Star item: every sub-score clamps to the floor except backlash (63.00).
    item = create_item(brand["id"], plant["id"], annual_units=200000,
                       unit_net_revenue_cents=2000, unit_cost_cents=1000,
                       units_on_hand=0)
    resp = api_client.create_rationalization_case(
        create_rationalization_case_payload(item["id"]), PM_PROPOSER
    )
    case = validate_created(resp)
    assert case["volume_score"] == 0.00, "200000/50000*100 = 400 -> 100-400 clamps to 0"
    assert case["margin_score"] == 0.00, "margin 0.50 above the 0.35 ref -> clamps to 0"
    assert case["shelf_resilience_score"] == 0.00, "revenue share 0.40 vs 0.20 ref -> clamps to 0"
    assert case["backlash_resilience_score"] == 63.00
    assert case["composite_score"] == 15.75, (
        f"0.25 * 63.00 = 15.75, got {case['composite_score']}"
    )
    assert case["recommendation"] == "KEEP", (
        f"composite 15.75 < 65 must recommend KEEP, got {case['recommendation']}"
    )


def test_sell_through_deadline_exact_date_math():
    """PRD §3.2: "An `APPROVE` decision moves the case from `SCORED` to
    `EXECUTING` and the item from `CUT_PROPOSED` to `SELL_THROUGH`, stamping
    the item's `sell_through_deadline` as the logical-clock timestamp of the
    decision plus exactly 90 days, with the time-of-day preserved."

    Design: Corner/calculations/sell_through_deadline_exact_date_math
    """
    _, _, item, case = setup_scored_case()
    set_clock("2026-10-05T12:00:00Z")
    api_client.decide_rationalization_case(
        case["id"], create_decide_payload("APPROVE"), PM_DECIDER
    )
    item_after = get_item(item["id"])
    # 2026-10-05T12:00:00Z + 90 days == 2027-01-03T12:00:00Z.
    expected = _iso_instant("2027-01-03T12:00:00Z")
    assert _iso_instant(item_after["sell_through_deadline"]) == expected, (
        f"deadline must be decide instant + 90 days (time-of-day preserved), "
        f"got {item_after['sell_through_deadline']}"
    )


def test_negotiation_shelf_reduction_aggregates_and_expiry():
    """PRD §3.6: "At creation the server aggregates the terms:
    `total_baseline_facings` is the sum of `baseline_facings` across
    `brand_terms`, `total_proposed_facings` is the sum of `proposed_facings`,
    and `shelf_reduction_pct` is the difference between the two totals divided
    by the baseline total, multiplied by 100, and rounded half-up to 2 decimal
    places; when the baseline total is 0 the reduction is defined as 0.00."
    PRD §3.6: "The negotiation is born `TERMS_PROPOSED` with an `expires_at`
    stamped as its `created_at` plus exactly 30 days — the offer's
    time-to-live."

    Design: Corner/calculations/negotiation_shelf_reduction_aggregates_and_expiry
    """
    retailer = create_retailer(risk_rating="LOW")
    brand1 = create_brand(private_label_share_pct=40)
    brand2 = create_brand(private_label_share_pct=10,
                          annual_net_revenue_cents=500000000)
    terms = [create_brand_term(brand1["id"], 100, 80),
             create_brand_term(brand2["id"], 60, 60)]
    resp = api_client.create_combined_negotiation(
        create_combined_negotiation_payload(retailer["id"], terms), PM
    )
    negotiation = validate_created(resp)
    assert_combined_negotiation(negotiation)
    assert negotiation["total_baseline_facings"] == 160
    assert negotiation["total_proposed_facings"] == 140
    assert negotiation["shelf_reduction_pct"] == 12.50, (
        f"round_half_up(20/160*100, 2dp) = 12.50, got "
        f"{negotiation['shelf_reduction_pct']}"
    )
    # Created at the default clock 2026-09-01 -> expires 2026-10-01.
    expected_expiry = _iso_instant("2026-10-01T00:00:00Z")
    assert _iso_instant(negotiation["expires_at"]) == expected_expiry, (
        f"expires_at must be created_at + 30 days = 2026-10-01, got "
        f"{negotiation['expires_at']}"
    )
    assert negotiation["negotiation_status"] == "TERMS_PROPOSED"


def test_priority_score_core_variant_capped_at_100():
    """PRD §3.7: "Under the `CORE_BRAND` variant (`core_flag` true), a bonus of
    exactly 10 points is added **after** the rounding, and the result is then
    capped at 100."

    Design: Corner/calculations/priority_score_core_variant_capped_at_100
    """
    cycle = setup_capital_cycle(total_capital_cents=1000000000)
    brand = create_brand(core_flag=True)
    resp = api_client.create_innovation_project(
        create_innovation_project_payload(
            brand["id"], cycle["id"], requested_capital_cents=1000,
            expected_revenue_cents_year3=2000000000, strategic_fit_score=100,
        ),
        PM,
    )
    project = validate_created(resp)
    # Blend 0.6*100 + 0.4*100 = 100.00; +10 = 110.00 -> capped at 100.00.
    assert project["priority_score"] == 100.00, (
        f"CORE_BRAND cap must pin 110.00 to 100.00, got {project['priority_score']}"
    )


def test_run_selection_empty_proposed_set_locks_at_zero():
    """PRD §3.7: "The selector takes every project in the cycle still
    `PROPOSED` — an empty set is legal and simply locks the cycle with
    `allocated_cents` of 0 — and ranks them by `priority_score` descending,
    breaking ties by `created_at` ascending and never by `id`."

    Design: Corner/calculations/run_selection_empty_proposed_set_locks_at_zero
    """
    cycle = setup_capital_cycle(total_capital_cents=750000000)
    resp = api_client.run_capital_cycle_selection(cycle["id"], FC)
    locked = validate_ok(resp)
    assert locked["allocated_cents"] == 0
    assert locked["remaining_cents"] == 750000000
    assert locked["cycle_status"] == "LOCKED"
