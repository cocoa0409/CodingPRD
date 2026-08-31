"""Quote costing, the two costing bases and the volume rebate ladder."""

from test_helpers import (
    ApiErrorId,
    api_client,
    create_quote_payload,
    make_shop_planner_headers,
    open_quote,
    price_quote,
    read_part,
    read_quote,
    register_part,
    set_clock,
    setup_accepted_work_order,
    validate_error,
    validate_success,
)

PLANNER = make_shop_planner_headers()


def _price(quote_id, basis):
    return validate_success(
        api_client.price_quote(quote_id, {"costing_basis": basis}, PLANNER), 200
    )


class TestCostingBases:
    """The same quote priced on the two bases must produce different money."""

    def test_standard_and_historical_bases_produce_different_unit_prices(self):
        """PRD 3.3: "On the `STANDARD_CYCLE` basis it is the part's engineered
        `cycle_time_sec`. On the `HISTORICAL_CYCLE` basis it is the part's
        `observed_avg_cycle_time_sec` when that value is not null, and falls back
        to the engineered `cycle_time_sec` when it is null — a documented
        fallback, not an error."
        PRD 3.3: "`quoted_lot_cost_cents` is the sum of those four rounded
        integers."

        Design: Difficulty/dual_variant_calc/quote_price_standard_vs_historical_cycle_basis
        """
        shop = setup_accepted_work_order()
        second = open_quote(shop.part_id, lot_qty=2000, requested_lights_out_hours=12)

        standard = _price(second["id"], "STANDARD_CYCLE")
        assert standard["quoted_unit_price_cents"] == 289
        assert standard["quoted_lot_cost_cents"] == 451242

        historical = _price(second["id"], "HISTORICAL_CYCLE")
        assert historical["quoted_unit_price_cents"] == 305
        assert historical["quoted_lot_cost_cents"] == 475467
        assert historical["cycle_time_used_sec"] == 46.5
        assert historical["quoted_unit_price_cents"] != standard["quoted_unit_price_cents"], (
            "the two costing bases must not collapse onto one unit price"
        )

    def test_historical_basis_reads_the_parts_accepted_running_figures(self):
        """PRD 3.9: "`observed_accepted_qty` becomes the sum of `qty_good` over
        that accepted set. When that sum is zero, `observed_avg_cycle_time_sec`
        is set to null; otherwise it is the sum of `actual_run_seconds` over the
        same accepted set divided by the accepted good-piece count, rounded half
        up to 1 decimal place."
        PRD 3.3: "It may also be re-run on an already-`PRICED` quote, in which
        case the quote stays `PRICED` and every pricing field is overwritten; the
        previous figures are not retained anywhere."

        Design: Difficulty/dual_variant_calc/quote_price_standard_vs_historical_cycle_basis
        """
        shop = setup_accepted_work_order()
        part = read_part(shop.part_id)
        assert part["observed_avg_cycle_time_sec"] == 46.5
        assert part["observed_accepted_qty"] == 200

        second = open_quote(shop.part_id, lot_qty=2000, requested_lights_out_hours=12)
        _price(second["id"], "STANDARD_CYCLE")
        _price(second["id"], "HISTORICAL_CYCLE")

        stored = read_quote(second["id"])
        assert stored["costing_basis"] == "HISTORICAL_CYCLE"
        assert stored["status"] == "PRICED"


class TestLightsOutSplitAndComponentRounding:
    """The run cost is a branch, a nested cap and two separately rated buckets."""

    def test_lights_out_request_is_clipped_to_sixty_percent_of_spindle_hours(self):
        """PRD 3.3: "Otherwise the unattended hours are the lesser of the
        `requested_lights_out_hours` and sixty hundredths of the total spindle
        hours — the shop will not price more than three fifths of any run as
        lights-out."
        PRD 3.3: "`run_cost_cents` is the attended hours multiplied by 9,500
        cents per attended spindle hour, rounded half up to a whole cent, plus the
        unattended hours multiplied by 6,200 cents per lights-out spindle hour,
        rounded half up to a whole cent — the two hour buckets are rated and
        rounded separately and then added."

        Design: Difficulty/combinatorial_formula/quote_pricing_lights_out_cap_and_component_rounding
        """
        set_clock()
        part = register_part()
        quote = open_quote(part["id"], lot_qty=2000, requested_lights_out_hours=40)

        priced = _price(quote["id"], "STANDARD_CYCLE")
        assert priced["effective_qty"] == 2040
        assert priced["run_cost_cents"] == 178976
        assert priced["quoted_lot_cost_cents"] == 443718
        assert priced["quoted_unit_price_cents"] == 284

    def test_ineligible_part_prices_every_spindle_hour_at_the_attended_rate(self):
        """PRD 3.3: "When the part is not `lights_out_eligible`, the unattended
        hours are zero regardless of what the customer asked for."
        PRD 3.3: "`setup_cost_cents` is the part's `setup_hours` multiplied by
        11,000 cents per setup hour, rounded half up."
        PRD 3.3: "Note that secondary work is priced on the ordered lot quantity,
        not on the scrap-inflated effective quantity."

        Design: Difficulty/combinatorial_formula/quote_pricing_lights_out_cap_and_component_rounding
        """
        set_clock()
        eligible = register_part()
        ineligible = register_part(part_number="P-4471-NLO", lights_out_eligible=False)

        eligible_quote = open_quote(eligible["id"], lot_qty=2000, requested_lights_out_hours=40)
        ineligible_quote = open_quote(
            ineligible["id"], lot_qty=2000, requested_lights_out_hours=40
        )

        priced_eligible = _price(eligible_quote["id"], "STANDARD_CYCLE")
        priced_ineligible = _price(ineligible_quote["id"], "STANDARD_CYCLE")

        assert priced_ineligible["run_cost_cents"] == 226100
        assert priced_ineligible["quoted_lot_cost_cents"] == 490842
        assert priced_ineligible["quoted_unit_price_cents"] == 315
        assert priced_ineligible["effective_qty"] == 2040

        assert priced_eligible["setup_cost_cents"] == 38500
        assert priced_eligible["secondary_cost_cents"] == 98667
        assert priced_eligible["material_cost_cents"] == 127575


class TestRebateLadder:
    """The rebate tier is keyed on the total the rebate itself would change."""

    def test_rebate_tier_is_selected_from_the_pre_rebate_extended_total(self):
        """PRD 3.4: "From 2,000,000 cents up to but not including 10,000,000
        cents it is six hundredths."
        PRD 3.4: "The tier is never re-selected from the rebated figures, even
        when applying the rebate would drop the order into a lower tier."
        PRD 3.4: "`net_unit_price_cents` is the list unit price multiplied by one
        minus the rebate fraction, rounded half up to a whole cent, and
        `committed_value_cents` is that net unit price multiplied by the committed
        quantity."

        Design: Difficulty/combinatorial_formula/blanket_po_rebate_tier_pinned_to_pre_rebate_total
        """
        set_clock()
        part = register_part()
        quote = open_quote(part["id"], lot_qty=2000, requested_lights_out_hours=12)
        price_quote(quote["id"])

        po = validate_success(
            api_client.accept_quote(
                quote["id"],
                {
                    "customer_po_number": "ACME-REB",
                    "total_committed_qty": 7000,
                    "expires_on": "2027-06-30T00:00:00Z",
                },
                PLANNER,
            ),
            201,
        )
        assert po["pre_rebate_total_cents"] == 2023000
        assert po["rebate_pct"] == 0.06
        assert po["net_unit_price_cents"] == 272
        assert po["net_unit_price_cents"] != 280, (
            "re-selecting the tier from the rebated total would have produced 280"
        )
        assert po["committed_value_cents"] == 1904000

    def test_accepted_quote_seeds_the_blanket_order_ledger(self):
        """PRD 3.4: "`list_unit_price_cents` is copied verbatim from the quote's
        `quoted_unit_price_cents`."
        PRD 3.4: "The order's quantity ledger is seeded at the same moment:
        `remaining_qty` is set to the full `total_committed_qty`, while
        `open_released_qty` and `fulfilled_qty` both start at 0."
        PRD 3.3: "A priced quote is accepted by a `ShopPlanner`, which moves it
        `PRICED → ACCEPTED` and cuts the blanket purchase order described in
        §3.4."

        Design: Difficulty/combinatorial_formula/blanket_po_rebate_tier_pinned_to_pre_rebate_total
        """
        set_clock()
        part = register_part()
        quote = open_quote(part["id"], lot_qty=2000, requested_lights_out_hours=12)
        price_quote(quote["id"])

        po = validate_success(
            api_client.accept_quote(
                quote["id"],
                {
                    "customer_po_number": "ACME-REB",
                    "total_committed_qty": 7000,
                    "expires_on": "2027-06-30T00:00:00Z",
                },
                PLANNER,
            ),
            201,
        )
        assert po["list_unit_price_cents"] == 289
        assert po["remaining_qty"] == 7000
        assert po["open_released_qty"] == 0
        assert po["fulfilled_qty"] == 0
        assert po["status"] == "ACTIVE"
        assert read_quote(quote["id"])["status"] == "ACCEPTED"

    def test_rebate_tier_zero_applies_strictly_below_five_hundred_thousand_cents(self):
        """PRD 3.4: "Below 500,000 cents the `rebate_pct` is zero. From 500,000
        cents up to but not including 2,000,000 cents it is three hundredths."
        PRD 3.4: "Every tier boundary is inclusive on its lower edge and
        exclusive on its upper edge."

        Design: Corner/calculations/rebate_tier_zero_applies_strictly_below_five_hundred_thousand_cents
        """
        set_clock()
        part = register_part()
        below = price_quote(open_quote(part["id"], lot_qty=200)["id"])
        at_tier = price_quote(open_quote(part["id"], lot_qty=200)["id"])

        po_below = validate_success(
            api_client.accept_quote(
                below["id"],
                {
                    "customer_po_number": "ACME-A",
                    "total_committed_qty": 900,
                    "expires_on": "2027-06-30T00:00:00Z",
                },
                PLANNER,
            ),
            201,
        )
        assert po_below["pre_rebate_total_cents"] == 486900
        assert po_below["rebate_pct"] == 0.00
        assert po_below["net_unit_price_cents"] == 541
        assert po_below["committed_value_cents"] == 486900

        po_at_tier = validate_success(
            api_client.accept_quote(
                at_tier["id"],
                {
                    "customer_po_number": "ACME-B",
                    "total_committed_qty": 925,
                    "expires_on": "2027-06-30T00:00:00Z",
                },
                PLANNER,
            ),
            201,
        )
        assert po_at_tier["pre_rebate_total_cents"] == 500425
        assert po_at_tier["rebate_pct"] == 0.03
        assert po_at_tier["net_unit_price_cents"] == 525
        assert po_at_tier["committed_value_cents"] == 485625


def test_opening_a_quote_without_lot_qty_is_rejected():
    """PRD 3.3: "A quote opens in `DRAFT` with a payload naming the `part_id`
    being quoted, the `customer_code` it is addressed to, and the `lot_qty` in
    pieces, which must be at least 1."
    PRD 2.9: "then request-body well-formedness, yielding `ERR_INVALID_REQUEST`
    — this covers missing required fields, wrong types, enum members outside
    their declared sets, numeric fields outside their declared bounds, a
    `scheduled_end_at` that is not strictly after `scheduled_start_at`, and
    out-of-range pagination."

    Design: Corner/entities/create_quote_missing_required_lot_qty_returns_invalid_request
    """
    set_clock()
    part = register_part()
    payload = create_quote_payload(part["id"])
    payload.pop("lot_qty")
    payload.pop("requested_lights_out_hours")

    response = api_client.create_quote(payload, PLANNER)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    listed = validate_success(api_client.list_quotes(PLANNER, {"part_id": part["id"]}), 200)
    assert listed == [], "the rejected quote must not have been persisted"
