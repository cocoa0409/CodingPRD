"""Two-reading pricing, the sell-through projection and manifest valuation."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as A
from test_helpers import fixtures as F
from test_helpers.test_users import clerk_headers, manager_headers


def test_markdown_quote_prices_one_lot_under_both_ladder_readings(api):
    """A read-only quote reports the calendar and sell-through readings side by side.

    PRD 3.3: "Before committing, an administrator, manager or clerk may ask for a
    read-only markdown quote on a lot, which prices it under **both** ladder
    readings and writes nothing at all -- in particular the lot's `version` is
    left untouched. The quote echoes `lot_id`, the current `days_remaining`, the
    lot's `expected_sell_through_pct`, the ladder's `sell_through_floor_pct` and
    `max_total_discount_pct`, the derived `cost_floor_price_cents`, and the
    `base_rung_index` selected by the calendar alone."

    PRD 3.3: "Otherwise the shortfall is the gap between the floor and the lot's
    expected sell-through, divided by 20 percentage points and rounded **up** to
    the next whole number of steps".

    With days remaining 3 the base rung is rung 0 at 15 percent, pricing 599 at
    509 cents.  Expected sell-through is 4.00 forecast units times the STANDARD
    multiplier 1.00 times 3 days, over 24 units on hand, which is 50.00 percent
    -- one full 20-point step below the 60 percent floor -- so the sell-through
    reading advances to rung 1 at 30 percent and 419 cents.

    Design: Difficulty/dual_variant_calc/markdown_price_ladder_days_vs_sell_through_on_same_lot
    """
    chain = F.build_meat_four_rung_chain(
        api, store_overrides={"dock_door_codes": ["D1", "D2"]}
    )
    F.set_clock(api, "2026-08-12T00:00:00.000Z")

    quote = validate_success(api.get_markdown_quote(chain.lot["id"], manager_headers()))

    A.assert_fields(
        quote,
        lot_id=chain.lot["id"],
        days_remaining=3,
        expected_sell_through_pct=50.00,
        sell_through_floor_pct=60,
        base_rung_index=0,
        ladder_days_rung_index=0,
        ladder_days_price_cents=509,
        sell_through_shortfall_steps=1,
        sell_through_rung_index=1,
        sell_through_price_cents=419,
    )
    assert quote["ladder_days_price_cents"] - quote["sell_through_price_cents"] == 90

    unwritten = F.reload_lot(api, chain.lot["id"])
    A.assert_unchanged(chain.lot, unwritten, "version", "current_price_cents", "status")


def test_sell_through_variant_markdown_cuts_the_deepened_label(api):
    """The SELL_THROUGH reading commits the deepened rung, price and barcode.

    PRD 3.3: "Sending `pricing_variant` as `SELL_THROUGH` deepens the rung for
    slow movers." and "The `reason` takes one of four values: `LADDER_AUTO` for a
    first markdown under the calendar reading, `SELL_THROUGH` for a first markdown
    under the sell-through reading".

    PRD 3.3: "The barcode is scannable and its format is fixed: the literal
    characters `MD-`, then the item's `upc`, then another hyphen, then
    `to_price_cents` written as a decimal integer left-padded with zeros to
    exactly 5 digits".

    PRD 3.3: "Alongside the label, the markdown rewrites the lot:
    `current_price_cents` becomes the label's `to_price_cents`,
    `current_rung_index` becomes the label's `rung_index`, `total_discount_pct` is
    recomputed".

    Landing 599 at 419 is a total discount of (599 - 419) / 599 * 100 = 30.05
    percent once rounded half up to two decimals.

    Design: Difficulty/dual_variant_calc/markdown_price_ladder_days_vs_sell_through_on_same_lot
    """
    chain = F.build_meat_four_rung_chain(
        api, store_overrides={"dock_door_codes": ["D1", "D2"]}
    )
    F.set_clock(api, "2026-08-12T00:00:00.000Z")

    label = F.cut_markdown(
        api,
        chain.lot,
        pricing_variant="SELL_THROUGH",
        headers=manager_headers(),
    )

    A.assert_label(
        label,
        status="QUEUED",
        from_price_cents=599,
        to_price_cents=419,
        discount_pct=30.05,
        reason="SELL_THROUGH",
        barcode="MD-000111222333-00419",
    )
    assert label["rung_index"] == 1

    lot = F.reload_lot(api, chain.lot["id"])
    A.assert_lot_pricing(lot, 419, 1, 30.05, status="MARKED_DOWN")


def test_chronological_actual_order_feedback_counts_verified_shrink_only(api):
    """CHRONOLOGICAL_ACTUAL ignores an unverified event and dampens with the rounded rate.

    PRD 3.9: "`CHRONOLOGICAL_ACTUAL`, which is the default when `method` is
    omitted, counts only shrink events in `VERIFIED` or `POSTED` -- money the
    department has already recognised. Nothing projected, nothing unverified."

    PRD 3.9: "The dampener uses the already-rounded two-decimal `shrink_rate_pct`,
    not the raw unrounded ratio."

    Received units over 2026-08-10..2026-08-12 are the 30 of lot C plus the 10 of
    lot D, so 40; only the verified 5-unit event counts, giving 12.50 percent;
    open units are 25 plus 10, so 35; and 20.00 forecast units times 3 days times
    (1 - 12.50 / 100) is 52.5, rounded half up to 53, less 35 open units, which is
    18 recommended units.

    Design: Difficulty/dual_variant_calc/order_feedback_chronological_actual_vs_forward_looking_projected
    """
    chain = F.build_meat_chain(
        api,
        item_overrides={
            "upc": "000444555666",
            "description": "Beef Sirloin 16oz",
            "base_retail_cents": 899,
            "unit_cost_cents": 500,
            "daily_forecast_units": 20.00,
        },
        lot_overrides={"production_date": "2026-08-05", "quantity_original": 30},
    )
    F.record_and_verify_shrink(
        api,
        chain.lot["id"],
        5,
        "SPOILAGE",
        recorder_headers=clerk_headers(),
        verifier_headers=manager_headers(),
    )

    F.set_clock(api, "2026-08-11T09:00:00.000Z")
    lot_d = F.build_lot(
        api, chain.item["id"], production_date="2026-08-06", quantity_original=10
    )
    F.record_shrink(api, lot_d["id"], 2, "DAMAGE", headers=clerk_headers())
    F.set_clock(api, "2026-08-13T12:00:00.000Z")

    item = F.reload_item(api, chain.item["id"])
    recommendation = F.build_recommendation(
        api,
        item,
        "2026-08-10",
        "2026-08-12",
        method="CHRONOLOGICAL_ACTUAL",
    )

    A.assert_fields(
        recommendation,
        received_units=40,
        shrink_units=5,
        shrink_rate_pct=12.50,
        open_units=35,
        recommended_order_units=18,
        status="DRAFT",
    )


def test_forward_looking_projected_order_feedback_adds_recorded_and_projected_units(api):
    """FORWARD_LOOKING_PROJECTED adds the unverified event and the per-lot projection.

    PRD 3.9: "`FORWARD_LOOKING_PROJECTED` counts all of that, plus every event
    still sitting in `RECORDED` awaiting a manager's verification, plus a
    projection for each still-open lot of the item whose `status` is `FRESH` or
    `MARKED_DOWN`: for such a lot, the projected loss is its `quantity_on_hand`
    less the item's `daily_forecast_units` multiplied by that lot's days remaining
    floored at zero, that product rounded half up to a whole number, and the
    difference itself floored at 0 so a lot expected to sell out projects no loss."

    PRD 3.9: "If an earlier recommendation for the same `item_id`,
    `window_start_date` and `window_end_date` is currently `ISSUED`, that earlier
    row moves from `ISSUED` to `SUPERSEDED` [...] when there was no such row,
    `supersedes_recommendation_id` stays null."  Neither row here is issued, so
    the second row's `supersedes_recommendation_id` is null.

    The verified 5 units plus the recorded 2 units plus lot C's projection of
    25 - 20.00 * 1 = 5 units gives 12 shrink units on 40 received, so 30.00
    percent; 20.00 * 3 * (1 - 30.00 / 100) is 42, less 35 open units, which is 7.

    Design: Difficulty/dual_variant_calc/order_feedback_chronological_actual_vs_forward_looking_projected
    """
    chain = F.build_meat_chain(
        api,
        item_overrides={
            "upc": "000444555666",
            "description": "Beef Sirloin 16oz",
            "base_retail_cents": 899,
            "unit_cost_cents": 500,
            "daily_forecast_units": 20.00,
        },
        lot_overrides={"production_date": "2026-08-05", "quantity_original": 30},
    )
    F.record_and_verify_shrink(
        api,
        chain.lot["id"],
        5,
        "SPOILAGE",
        recorder_headers=clerk_headers(),
        verifier_headers=manager_headers(),
    )

    F.set_clock(api, "2026-08-11T09:00:00.000Z")
    lot_d = F.build_lot(
        api, chain.item["id"], production_date="2026-08-06", quantity_original=10
    )
    F.record_shrink(api, lot_d["id"], 2, "DAMAGE", headers=clerk_headers())
    F.set_clock(api, "2026-08-13T12:00:00.000Z")

    chronological = F.build_recommendation(
        api,
        F.reload_item(api, chain.item["id"]),
        "2026-08-10",
        "2026-08-12",
        method="CHRONOLOGICAL_ACTUAL",
    )
    forward = F.build_recommendation(
        api,
        F.reload_item(api, chain.item["id"]),
        "2026-08-10",
        "2026-08-12",
        method="FORWARD_LOOKING_PROJECTED",
    )

    A.assert_fields(
        forward,
        received_units=40,
        shrink_units=12,
        shrink_rate_pct=30.00,
        open_units=35,
        recommended_order_units=7,
    )
    assert (
        chronological["recommended_order_units"] - forward["recommended_order_units"] == 11
    )
    A.assert_absent_or_none(forward, "supersedes_recommendation_id")


def test_expected_sell_through_folds_velocity_and_days_while_label_is_queued(api):
    """Three inputs and the AGGRESSIVE multiplier give 62.50 percent before application.

    PRD 3.2: "First, the department's velocity multiplier: 1.00 under `STANDARD`,
    1.25 under `AGGRESSIVE`, 0.80 under `CONSERVATIVE`." and "Third, the calendar:
    the item's `daily_forecast_units` multiplied by the velocity multiplier
    multiplied by days remaining, where days remaining is floored at zero".

    PRD 3.2: "Note the sequencing consequence: a markdown creates its label in
    `QUEUED`, so **a markdown never lifts its own sell-through** -- only the
    separate act of applying a printed label does."

    The item's own `shelf_life_days` of 6 wins over the department default of 8, so
    a lot packed 2026-08-08 sells by 2026-08-14 and has 2 days remaining at the
    parked clock.  5.00 forecast units times 1.25 times 2 days is 12.5 projected
    units over 20 on hand, which is 62.50 percent, and the fresh QUEUED label adds
    no lift.  The base rung is rung 1 at 35 percent, pricing 700 at 455 cents.

    Design: Difficulty/combinatorial_formula/expected_sell_through_three_inputs_two_branches_aggressive_deli
    """
    chain = F.build_deli_aggressive_chain(api)
    F.set_clock(api, "2026-08-12T00:00:00.000Z")

    label = F.cut_markdown(api, chain.lot, headers=manager_headers())

    A.assert_label(
        label,
        status="QUEUED",
        from_price_cents=700,
        to_price_cents=455,
        discount_pct=35.00,
        reason="LADDER_AUTO",
        barcode="MD-000777888999-00455",
    )
    assert label["rung_index"] == 1

    lot = F.reload_lot(api, chain.lot["id"])
    A.assert_percent(lot["expected_sell_through_pct"], 62.50, "expected_sell_through_pct")
    A.assert_lot_pricing(lot, 455, 1, 35.00, status="MARKED_DOWN")


def test_applied_label_adds_the_promotional_lift_to_expected_sell_through(api):
    """Applying the printed label raises the same lot from 62.50 to 72.50 percent.

    PRD 3.2: "Second, the promotional lift: if at least one of the lot's markdown
    labels has reached `APPLIED`, one tenth of the lot's `quantity_on_hand` -- that
    is, 10 percent of it -- is added as extra projected movement; if no applied
    label exists, the lift is zero."

    PRD 3.4: "Application is the single call that turns that lift on."

    One tenth of the 20 units on hand is 2 projected units, so the projection rises
    from 12.5 to 14.5 units and the percentage from 62.50 to 72.50 -- exactly 10.00
    percentage points.

    Design: Difficulty/combinatorial_formula/expected_sell_through_three_inputs_two_branches_aggressive_deli
    """
    chain = F.build_deli_aggressive_chain(api)
    F.set_clock(api, "2026-08-12T00:00:00.000Z")

    label = F.cut_markdown(api, chain.lot, headers=manager_headers())
    queued_lot = F.reload_lot(api, chain.lot["id"])

    F.print_label(api, label["id"], headers=clerk_headers())
    applied = F.apply_label(api, label["id"], headers=clerk_headers())

    assert applied["status"] == "APPLIED"
    applied_lot = F.reload_lot(api, chain.lot["id"])
    A.assert_percent(
        queued_lot["expected_sell_through_pct"], 62.50, "expected_sell_through_pct"
    )
    A.assert_percent(
        applied_lot["expected_sell_through_pct"], 72.50, "expected_sell_through_pct"
    )
    assert (
        round(
            applied_lot["expected_sell_through_pct"]
            - queued_lot["expected_sell_through_pct"],
            2,
        )
        == 10.00
    )
    A.assert_lot_pricing(applied_lot, 455, 1, 35.00, status="MARKED_DOWN")


def _build_two_line_produce_manifest(api):
    """PRODUCE store with two donation-eligible items, two lots and a DRAFT manifest."""
    chain = F.build_produce_chain(
        api,
        store_overrides={"dock_door_codes": ["D1", "D2"], "donation_program_enabled": True},
        partner_overrides={"cold_chain_certified": False},
        department_overrides={"shelf_life_days_default": 8},
        item_overrides={
            "upc": "000222333444",
            "description": "Organic Berry Tray",
            "base_retail_cents": 899,
            "unit_cost_cents": 400,
            "daily_forecast_units": 10.00,
            "donation_eligible": True,
        },
        lot_overrides={"production_date": "2026-08-05", "quantity_original": 60},
    )
    chain.item_b = F.build_item(
        api,
        chain.department["id"],
        upc="000555666777",
        description="Salad Kit",
        base_retail_cents=599,
        unit_cost_cents=250,
        daily_forecast_units=8.00,
        donation_eligible=True,
    )
    chain.lot_b = F.build_lot(
        api, chain.item_b["id"], production_date="2026-08-05", quantity_original=20
    )
    F.set_clock(api, "2026-08-12T00:00:00.000Z")
    chain.pickup = F.book_pickup(
        api,
        chain.store["id"],
        chain.partner["id"],
        dock_door_code="D1",
        scheduled_window_start="2026-08-12T14:00:00.000Z",
        scheduled_window_end="2026-08-12T16:00:00.000Z",
        headers=manager_headers(),
    )
    return chain


def test_manifest_credit_tier_is_keyed_on_the_provisional_total(api):
    """A 65,920-cent manifest credits at 72.50 percent, not at the lower tier.

    PRD 3.7: "`provisional_value_cents` is the sum, over every manifest line on the
    pickup in `ASSIGNED`, of that line's `quantity_units` multiplied by its
    `unit_price_cents_snapshot`."

    PRD 3.7: "`credit_rate_pct` is selected from that provisional total by tier:
    62.50 percent when the provisional value is below 50,000 cents (that is, under
    five hundred dollars), 72.50 percent when it is at or above 50,000 cents but
    below 200,000 cents, and 80 percent when it is at or above 200,000 cents. **The
    tier is keyed on the provisional total and never on the credited total**".

    60 units at 899 cents is 53,940 and 20 units at 599 cents is 11,980, so the
    provisional total is 65,920 -- above the 50,000 boundary and below 200,000.

    Design: Difficulty/combinatorial_formula/donation_manifest_tier_keyed_on_provisional_total
    """
    chain = _build_two_line_produce_manifest(api)

    line_a = F.pledge_lot(api, chain.pickup["id"], chain.lot["id"], 60)
    line_b = F.pledge_lot(api, chain.pickup["id"], chain.lot_b["id"], 20)
    sealed = F.seal_pickup(api, chain.pickup["id"], headers=manager_headers())

    A.assert_fields(
        line_a, unit_price_cents_snapshot=899, line_value_cents=53940
    )
    A.assert_fields(
        line_b, unit_price_cents_snapshot=599, line_value_cents=11980
    )
    A.assert_fields(
        sealed,
        assignment_count=2,
        provisional_value_cents=65920,
        credit_rate_pct=72.5,
        manifest_credit_cents=47793,
        manifest_status="SEALED",
        logistics_status="SCHEDULED",
    )
    assert sealed["manifest_credit_cents"] != 41201


def test_manifest_credit_rounds_every_line_before_summing(api):
    """Each line is rounded individually, so the manifest credit is 47,793 not 47,792.

    PRD 3.7: "Each line, walked in `created_at` ascending order, receives a
    `line_credit_cents` equal to its `quantity_units` multiplied by its
    `unit_price_cents_snapshot` multiplied by `credit_rate_pct`, divided by 100, and
    rounded half up to whole cents. Every line is rounded individually."

    PRD 3.7: "`manifest_credit_cents` is the exact integer sum of those
    already-rounded line credits -- never a single rounding of the unrounded total."

    53,940 at 72.5 percent is 39,106.5 which rounds half up to 39,107, and 11,980 at
    72.5 percent is exactly 8,685.5 which rounds half up to 8,686; their sum is
    47,793, whereas rounding 65,920 at 72.5 percent once would give 47,792.

    Design: Difficulty/combinatorial_formula/donation_manifest_tier_keyed_on_provisional_total
    """
    chain = _build_two_line_produce_manifest(api)

    line_a = F.pledge_lot(api, chain.pickup["id"], chain.lot["id"], 60)
    line_b = F.pledge_lot(api, chain.pickup["id"], chain.lot_b["id"], 20)
    assert line_a["line_credit_cents"] == 0
    assert line_b["line_credit_cents"] == 0

    sealed = F.seal_pickup(api, chain.pickup["id"], headers=manager_headers())

    credited_a = validate_success(
        api.get_donation_assignment(line_a["id"], manager_headers())
    )
    credited_b = validate_success(
        api.get_donation_assignment(line_b["id"], manager_headers())
    )
    A.assert_money_cents(credited_a["line_credit_cents"], 39107, "line_credit_cents")
    A.assert_money_cents(credited_b["line_credit_cents"], 8686, "line_credit_cents")
    A.assert_money_cents(sealed["manifest_credit_cents"], 47793, "manifest_credit_cents")
    assert sealed["manifest_credit_cents"] != 47792
    assert (
        credited_a["line_credit_cents"] + credited_b["line_credit_cents"]
        == sealed["manifest_credit_cents"]
    )

    for lot_id in (chain.lot["id"], chain.lot_b["id"]):
        assert F.reload_lot(api, lot_id)["status"] == "DONATION_PENDING"
