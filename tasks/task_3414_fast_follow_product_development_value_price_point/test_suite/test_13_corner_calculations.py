"""Calculation corners: every fixed price-point tier, the CM quarterly
capacity pool (first accepted wins), tooling-reuse lead-time detection, the
markdown depth tier boundary at exactly four weeks, and the momentum score's
source-filtered input set.
"""

import pytest

from test_helpers import (
    CLOCK_MARKDOWN_WEEK4,
    TEST_USERS,
    ApiErrorId,
    accept_quote,
    create_approved_formula,
    create_concept,
    create_manufacturer,
    create_product,
    create_quote,
    create_selected_concept,
    create_selected_trend,
    create_trend,
    evaluate_quote,
    read_cost_quote,
    read_product,
    set_clock,
    setup_executed_plan,
    transition_concept,
    transition_product,
    transition_trend,
    validate_error,
    validate_success,
)

_SCOUT = TEST_USERS["trend_scout_headers"]
_SOURCING = TEST_USERS["sourcing_lead_headers"]
_PM = TEST_USERS["product_manager_headers"]


@pytest.mark.parametrize(
    "price_point,expected_cost",
    [(300, 84), (600, 168), (1000, 260), (1500, 360), (2000, 440)],
    ids=["300->84", "600->168", "1000->260", "1500->360", "2000->440"],
)
def test_target_unit_cost_all_five_price_tiers(api, price_point, expected_cost):
    """PRD §3.2: "The derivation applies a ratio that steps down as the price
    point rises: twenty-eight percent of the price point for a price point of
    600 cents or less, twenty-six percent for one of 1000 cents or less,
    twenty-four percent for one of 1500 cents or less, and twenty-two percent
    for one of 2000 cents or less; the result is rounded down to a whole cent
    and stored as `target_unit_cost_cents`. The five price points therefore
    yield cost targets of 84, 168, 260, 360, and 440 cents respectively."

    Design: Corner/calculations/target_unit_cost_all_five_price_tiers
    """
    set_clock()
    trend = create_selected_trend()

    concept = create_concept(trend["id"], target_price_point_cents=price_point)
    selected = transition_concept(concept["id"], "SELECTED")

    assert selected["target_unit_cost_cents"] == expected_cost


def test_cm_quarterly_capacity_first_accepted_wins(api):
    """PRD §3.5: "...the manufacturer's quarterly pool must have room — the
    count of that manufacturer's `ACCEPTED` quotes sharing the same
    `production_quarter` must be strictly below `capacity_slots_per_quarter`,
    else `ERR_CAPACITY_EXCEEDED`."
    PRD §2.9: "Acceptance order determines which quotes hold slots: quotes
    consume in `accepted_at` ascending order, with `created_at` ascending as
    the tie-break when two acceptances share a timestamp — never by
    identifier."
    With one 2026-Q4 slot, the first acceptance consumes it and the second
    quote — a different product, same manufacturer and quarter — is rejected.

    Design: Corner/calculations/cm_quarterly_capacity_first_accepted_wins
    """
    set_clock()
    trend = create_selected_trend()
    manufacturer = create_manufacturer(
        name="TinyCap Labs", capabilities=["EYES"], capacity_slots_per_quarter=1
    )
    quotes = []
    for name in ("First Face", "Second Skin"):
        concept = create_selected_concept(trend["id"], name=name)
        product = create_product(concept["id"])
        create_approved_formula(product["id"], manufacturer["id"])
        transition_product(product["id"], "SOURCING")
        quote = create_quote(product["id"], manufacturer["id"])
        evaluate_quote(quote["id"])
        quotes.append(quote)

    accepted = accept_quote(quotes[0]["id"])
    assert accepted["status"] == "ACCEPTED"
    assert accepted["accepted_at"] is not None

    response = api.patch_cost_quote(quotes[1]["id"], {"status": "ACCEPTED"}, _SOURCING)

    validate_error(response, ApiErrorId.ERR_CAPACITY_EXCEEDED.value)
    assert read_cost_quote(quotes[1]["id"])["status"] == "UNDER_EVALUATION"


def test_packaging_lead_weeks_tooling_reuse_detection(api):
    """PRD §3.3: "Packaging lead time is computed once at creation: the
    platform detects `tooling_reuse` — true exactly when a `tooling_code` was
    supplied and another product exists with the same `tooling_code`, a
    strictly earlier `created_at`, and a status other than `KILLED` — and sets
    `packaging_lead_weeks` to five weeks when tooling is reused and fourteen
    weeks when new tooling must be cut."
    First use of a code: 14 (new). Same code, strictly later: 5 (reuse). A
    null code can never reuse: 14.

    Design: Corner/calculations/packaging_lead_weeks_tooling_reuse_detection
    """
    set_clock()
    trend = create_selected_trend()
    concept_a = create_selected_concept(trend["id"], name="Reuse One")
    concept_b = create_selected_concept(
        trend["id"], name="Reuse Two", target_price_point_cents=600
    )
    concept_c = create_selected_concept(
        trend["id"], name="No Tooling", target_price_point_cents=300
    )

    first = create_product(concept_a["id"], tooling_code="LASH-TUBE-V1")
    assert first["tooling_reuse"] is False
    assert first["packaging_lead_weeks"] == 14

    set_clock("2026-09-02T00:00:00Z")
    second = create_product(concept_b["id"], tooling_code="LASH-TUBE-V1")
    assert second["tooling_reuse"] is True
    assert second["packaging_lead_weeks"] == 5

    no_tooling = create_product(concept_c["id"])
    assert no_tooling["tooling_reuse"] is False
    assert no_tooling["packaging_lead_weeks"] == 14


def test_markdown_exposure_is_zero_at_the_week_4_boundary(api):
    """PRD §3.8: "Reconciliation moves every unsold unit to markdown:
    `markdown_units` is set to `retail_units_available`, and
    `markdown_exposure_cents` is computed from the markdown depth tier for the
    product's age. The depth depends on whole weeks since `launched_at`: zero
    percent when four weeks or fewer have elapsed, thirty percent through
    eight weeks, fifty percent through twelve weeks, and seventy percent
    beyond that; the exposure is `markdown_units` times `landed_locked_cents`
    times the depth, in integer cents."
    Launched 2026-11-01, reconciled 2026-11-29: exactly 28 days -> 4 whole
    weeks -> depth 0.00, so 800 markdown units cost 0 cents.

    Design: Corner/calculations/markdown_exposure_zero_depth_at_week4_boundary
    """
    ctx = setup_executed_plan()
    set_clock(CLOCK_MARKDOWN_WEEK4)

    response = api.patch_launch_plan(ctx["plan"]["id"], {"status": "RECONCILED"}, _PM)

    plan = validate_success(response)
    assert plan["status"] == "RECONCILED"
    assert plan["markdown_units"] == 800
    assert plan["markdown_exposure_cents"] == 0
    assert read_product(ctx["product"]["id"])["status"] == "LAUNCHED"


def test_trend_score_social_variant_uses_spread_input(api):
    """PRD §3.1: "The score normalizes each raw input against a cap: the
    velocity component is `mention_velocity_7d` divided by five thousand
    mentions per day, capped at one; the growth component is
    `engagement_growth_pct` divided by two, capped at one; and the signal
    component is `prestige_similarity` taken as-is for a prestige-sourced
    trend or `cross_platform_spread` taken as-is for a social one."
    Social signal with velocity 2500 / growth 1.0 / spread 0.9 scores
    25.0 + 15.0 + 18.0 == 58.0 — below the selection threshold.

    Design: Corner/calculations/trend_score_social_variant_uses_spread_input
    """
    set_clock()
    trend = create_trend(
        source="SOCIAL_PLATFORM",
        platform="tiktok",
        category="LIPS",
        mention_velocity_7d=2500,
        engagement_growth_pct=1.0,
        prestige_similarity=None,
        cross_platform_spread=0.9,
    )

    evaluated = transition_trend(trend["id"], "EVALUATING")
    assert evaluated["momentum_score"] == pytest.approx(58.0)

    response = api.patch_trend_signal(trend["id"], {"status": "SELECTED"}, _SCOUT)

    validate_error(response, ApiErrorId.ERR_TREND_SCORE_BELOW_THRESHOLD.value)
