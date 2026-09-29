"""Calculation corners: selector ranking, channel pricing, waterfall and tiers.

Each test pins one derived figure the PRD computes, with the inputs chosen so that a
mis-implemented rule produces a visibly different number.
"""
from test_helpers import (
    HEADERS_ASSORTMENT_PLANNER,
    HEADERS_COMPLIANCE_OFFICER,
    HEADERS_FUND_CONTROLLER,
    HEADERS_STORE_CASHIER,
    constants as C,
    factories,
    fixtures as fx,
    make_fund_controller_headers,
    validate_paginated,
    validate_success,
)


def _scene_two_overlapping_overseas_allocations(api, store_name, sku, blocks):
    """Two ACTIVE allocations of one item, both covering 08-10, with different subsidies."""
    store = fx.create_store(
        api,
        name=store_name,
        channel="COMMISSARY",
        region="OVERSEAS",
        surcharge_rate_bp=500,
        shelf_block_capacity_facings=24,
    )
    product = fx.create_product(
        api, sku=sku, name="Canned Tuna 12pk", category="GROCERY_STAPLE", unit_cost_cents=400
    )
    old = fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block=blocks[0],
        facings=4,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        overseas_shipping_allowance_cents=100,
        expected_store_version=store["version"],
    )
    new = fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block=blocks[1],
        facings=4,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_05,
        effective_to=C.AUG_25,
        overseas_shipping_allowance_cents=250,
        expected_store_version=fx.store_version(api, store["id"]),
    )
    patron = fx.create_patron(api, full_name="SSG B Kowalczyk", id_card_class="ACTIVE_DUTY")
    fx.set_clock(api, C.AUG_10)
    sale = fx.open_sale(api, store["id"], patron["id"])
    return {"store": store, "product": product, "old": old, "new": new, "sale": sale}


def test_the_allocation_with_the_latest_effective_from_governs_the_line(api):
    """Both windows cover 08-10, so the 08-05 window's 250 per unit governs, giving 500.

    PRD 3.4: "Among the candidates, the governing allocation is the one with the
    latest `effective_from`; where two candidates share the same `effective_from`, the
    one with the later `created_at` wins."
    PRD 3.5: "`line_shipping_allowance_cents` is the governing allocation's
    `overseas_shipping_allowance_cents` multiplied by `quantity`, but only when *both*
    conditions hold: the store's `region` is `OVERSEAS`, and the governing allocation's
    `supply_mode` is `WAREHOUSE`."
    PRD 3.5: "The remaining rollups are plain sums: `merchandise_cents` is the sum of
    `extended_cents` over the lines, `markup_total_cents` the sum of
    `line_markup_cents`, `subsidized_shipping_cents` the sum of
    `line_shipping_allowance_cents`, and `line_count` the number of lines."

    Design: Corner/calculations/corner_governing_assortment_selector_prefers_newest_effective_from
    """
    scene = _scene_two_overlapping_overseas_allocations(
        api, "Grafenwoehr Commissary", "SKU-SEL-400", ("Q1", "Q2")
    )

    line = validate_success(
        api.add_sale_line(
            scene["sale"]["id"],
            factories.sale_line_payload(scene["product"]["id"], 2),
            HEADERS_STORE_CASHIER,
        ),
        201,
    )
    assert line["unit_price_cents"] == 400
    assert line["extended_cents"] == 800
    assert line["line_markup_cents"] == 0
    assert line["line_surcharge_cents"] == 40
    assert line["line_shipping_allowance_cents"] == 500

    sale = fx.read_sale(api, scene["sale"]["id"])
    assert sale["subsidized_shipping_cents"] == 500
    assert sale["total_due_cents"] == 840

    assert validate_success(
        api.get_assortment(scene["old"]["id"], HEADERS_ASSORTMENT_PLANNER)
    )["status"] == "ACTIVE"
    assert validate_success(
        api.get_assortment(scene["new"]["id"], HEADERS_ASSORTMENT_PLANNER)
    )["status"] == "ACTIVE"


def test_a_retired_allocation_never_enters_the_candidate_set(api):
    """With the newer window retired the older one governs, so the subsidy is 200 not 500.

    PRD 3.4: "It gathers every allocation whose `store_id` and `product_id` match the
    context, whose `status` is `ACTIVE`, and whose closed window contains a reference
    instant — where the reference instant is the visit's `business_date` when a sale
    line is being priced, and the logical clock's current instant when a special order
    is being routed."
    PRD 3.4: "`RETIRED` allocations are never candidates."
    PRD 3.5: "`line_shipping_allowance_cents` is the governing allocation's
    `overseas_shipping_allowance_cents` multiplied by `quantity`, but only when *both*
    conditions hold: the store's `region` is `OVERSEAS`, and the governing allocation's
    `supply_mode` is `WAREHOUSE`."

    Design: Corner/calculations/corner_retired_assortment_is_excluded_from_selector_candidates
    """
    scene = _scene_two_overlapping_overseas_allocations(
        api, "Sagamihara Commissary", "SKU-RET-400", ("R1", "R2")
    )
    retired = fx.retire_assortment(api, scene["new"]["id"], reason="VENDOR_DISCONTINUED")
    assert retired["status"] == "RETIRED"
    assert validate_success(
        api.get_assortment(scene["old"]["id"], HEADERS_ASSORTMENT_PLANNER)
    )["status"] == "ACTIVE"

    line = validate_success(
        api.add_sale_line(
            scene["sale"]["id"],
            factories.sale_line_payload(scene["product"]["id"], 2),
            HEADERS_STORE_CASHIER,
        ),
        201,
    )
    assert line["line_shipping_allowance_cents"] == 200
    assert line["extended_cents"] == 800
    assert line["line_surcharge_cents"] == 40

    sale = fx.read_sale(api, scene["sale"]["id"])
    assert sale["subsidized_shipping_cents"] == 200


def test_a_commissary_line_carries_no_markup_even_at_the_maximum_surcharge(api):
    """777 at quantity 3 is 2331 of merchandise, 233 of surcharge and 2564 due.

    PRD 3.5: "At a `COMMISSARY` store the line's `unit_price_cents` is exactly
    `unit_cost_cents` — no markup, ever, under any configuration."
    PRD 3.5: "`line_markup_cents` is the difference between `unit_price_cents` and the
    product's `unit_cost_cents`, multiplied by `quantity` — which is 0 at every
    commissary line by construction."
    PRD 3.5: "`tax_cents` is always 0 — commissary and exchange sales are tax-free and
    there is no configuration in which they are not."

    Design: Corner/calculations/corner_commissary_line_price_equals_unit_cost_with_no_markup
    """
    store = fx.create_store(
        api,
        name="Fort Leonard Wood Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=1000,
    )
    product = fx.create_product(
        api,
        sku="SKU-NOM-777",
        name="Frozen Berries 3lb",
        category="GROCERY_STAPLE",
        unit_cost_cents=777,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="S1",
        facings=6,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="SPC D Amankwah", id_card_class="ACTIVE_DUTY")
    sale = fx.open_sale(api, store["id"], patron["id"])

    line = validate_success(
        api.add_sale_line(
            sale["id"], factories.sale_line_payload(product["id"], 3), HEADERS_STORE_CASHIER
        ),
        201,
    )
    assert line["unit_price_cents"] == 777
    assert line["line_markup_cents"] == 0
    assert line["extended_cents"] == 2331
    assert line["line_surcharge_cents"] == 233

    read_sale = fx.read_sale(api, sale["id"])
    assert read_sale["merchandise_cents"] == 2331
    assert read_sale["markup_total_cents"] == 0
    assert read_sale["surcharge_total_cents"] == 233
    assert read_sale["tax_cents"] == 0
    assert read_sale["total_due_cents"] == 2564


def test_the_waterfall_fills_the_first_bucket_to_its_ceiling_before_the_second(api):
    """A 1000-cent dividend pours 600 into rank 1 and only the 400 remainder into rank 2.

    PRD 3.9: "The candidates are the store's programmes whose `status` is `ACTIVE` and
    whose `ytd_funded_cents` is strictly below their `funding_ceiling_cents`;
    `SUSPENDED` programmes and programmes already at their ceiling are skipped
    entirely."
    PRD 3.9: "Otherwise it computes that programme's headroom as its
    `funding_ceiling_cents` less its `ytd_funded_cents`, and grants the smaller of the
    remaining amount and that headroom."
    PRD 3.9: "When the grant is greater than 0, a ledger entry is appended against the
    `DIVIDEND` fund with `entry_type` of `DIVIDEND_TRANSFER`, `amount_cents` equal to
    the negative of the grant, `source_ref_kind` of `MWR_PROGRAM` and `source_ref_id`
    naming the programme; the programme's `ytd_funded_cents` rises by the grant and the
    remaining amount falls by it, before the next candidate is considered."

    Design: Corner/calculations/corner_dividend_waterfall_fills_first_program_to_ceiling_then_second
    """
    store = fx.create_store(
        api,
        name="Fort Shafter Exchange",
        channel="EXCHANGE",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    product = fx.create_product(
        api,
        sku="SKU-WAT-1000",
        name="Snack Mix Case",
        category="GENERAL_MERCHANDISE",
        unit_cost_cents=1000,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="T2",
        facings=6,
        supply_mode="DSD",
        vendor_name="Bluewater Snacks",
        promo_allowance_bp=2000,
        promo_window_start=C.AUG_01,
        promo_window_end=C.SEP_01,
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    program_one = fx.create_mwr_program(
        api,
        store_id=store["id"],
        name="Library Expansion",
        priority_rank=1,
        funding_ceiling_cents=600,
    )
    program_two = fx.create_mwr_program(
        api,
        store_id=store["id"],
        name="Fitness Center Equipment",
        priority_rank=2,
        funding_ceiling_cents=1000,
    )
    patron = fx.create_patron(api, full_name="SGT E Villalobos", id_card_class="ACTIVE_DUTY")
    fx.set_clock(api, C.AUG_03)
    sale = fx.open_sale(api, store["id"], patron["id"])
    fx.add_line(api, sale["id"], product["id"], 5)
    tendered = fx.tender_sale(api, sale["id"])
    assert tendered["settled_allowance_cents"] == 1000
    assert tendered["provisional_allowance_cents"] == 1000
    assert tendered["allowance_variance_cents"] == 0

    validate_success(api.close_period(store["id"], None, HEADERS_FUND_CONTROLLER), 200)

    assert validate_success(
        api.get_mwr_program(program_one["id"], HEADERS_FUND_CONTROLLER)
    )["ytd_funded_cents"] == 600
    assert validate_success(
        api.get_mwr_program(program_two["id"], HEADERS_FUND_CONTROLLER)
    )["ytd_funded_cents"] == 400

    rows, meta = validate_paginated(
        api.list_fund_ledger(store["id"], {"fund": "DIVIDEND"}, HEADERS_FUND_CONTROLLER)
    )
    assert meta["total_count"] == 3
    assert [row["entry_type"] for row in rows] == [
        "ALLOWANCE_CREDIT",
        "DIVIDEND_TRANSFER",
        "DIVIDEND_TRANSFER",
    ]
    assert [row["amount_cents"] for row in rows] == [1000, -600, -400]
    assert [row["balance_after_cents"] for row in rows] == [1000, 400, 0]
    assert rows[1]["source_ref_id"] == program_one["id"]
    assert rows[2]["source_ref_id"] == program_two["id"]

    read_store = fx.read_store(api, store["id"])
    assert read_store["dividend_fund_balance_cents"] == 0
    assert read_store["surcharge_fund_balance_cents"] == 250
    assert read_store["fund_posture"] == "FROZEN"
    assert read_store["period_close_index"] == 1


def test_the_tier_ceiling_is_a_strict_upper_bound_so_the_bigger_request_obligates_less(api):
    """499999 obligates 549999 at 1000 bp while 500000 obligates only 535000 at 700 bp.

    PRD 3.9: "Contingency is added by tier, and the evaluation order is pinned: **the
    tier is selected from the contingency-free request amount, never from the
    obligation that already contains the contingency.**"
    PRD 3.9: "When `requested_amount_cents` is below 500000 cents (5,000.00 US
    dollars), `contingency_bp` is 1000 basis points — ten percent. When it is at least
    500000 cents but below 2000000 cents (20,000.00 US dollars), `contingency_bp` is 700
    basis points."
    PRD 3.9: "From that rate, `contingency_cents` is `requested_amount_cents`
    multiplied by `contingency_bp`, divided by ten thousand, and rounded to the nearest
    whole cent with an exact half rounding up."

    Design: Corner/calculations/corner_contingency_tier_boundary_at_ceiling_selects_second_tier
    """
    store = fx.create_store(
        api, name="Fort Huachuca Commissary", channel="COMMISSARY", region="CONUS"
    )
    below = validate_success(
        api.create_capital_project(
            factories.capital_project_payload(
                store_id=store["id"],
                title="Freezer compressor bank",
                requested_amount_cents=499999,
            ),
            make_fund_controller_headers("sfc-110"),
        ),
        201,
    )

    at_ceiling = validate_success(
        api.create_capital_project(
            factories.capital_project_payload(
                store_id=store["id"],
                title="Loading dock leveler",
                requested_amount_cents=500000,
            ),
            make_fund_controller_headers("sfc-110"),
        ),
        201,
    )

    assert below["contingency_bp"] == 1000
    assert below["contingency_cents"] == 50000
    assert below["obligation_cents"] == 549999
    assert at_ceiling["contingency_bp"] == 700
    assert at_ceiling["contingency_cents"] == 35000
    assert at_ceiling["obligation_cents"] == 535000
    assert at_ceiling["obligation_cents"] < below["obligation_cents"]

    read_store = fx.read_store(api, store["id"])
    assert read_store["surcharge_obligated_cents"] == 0


def test_the_third_manual_strike_carries_the_score_over_the_watch_threshold(api):
    """25 / 50 / 75: CLEAR after two strikes, WATCH on the third, card still VALID.

    PRD 3.7: "The second term is 25 points for each strike, where the strike count is
    the number of sales in the set whose `compliance_state` is `FLAGGED` plus the
    patron's `manual_strike_count`."
    PRD 3.7: "A score of at least 85 puts the patron at `RESTRICTED`; a score of at
    least 60 but below 85 puts them at `WATCH`; a score below 60 puts them at `CLEAR`."
    PRD 3.7: "When `recent_sales_risk_score` reaches 80 and the patron's `card_status`
    is `VALID`, the system suspends the card on the spot: `card_status` moves `VALID →
    SUSPENDED` with `suspension_reason` set to `RISK_THRESHOLD`, and the full three-hop
    cascade described below runs."

    Design: Corner/calculations/corner_third_confirmed_strike_crosses_watch_threshold
    """
    patron = fx.create_patron(api, full_name="SPC F Osterberg", id_card_class="ACTIVE_DUTY")
    fx.record_compliance_review(api, patron["id"], "CONFIRM_STRIKE")
    after_two = fx.record_compliance_review(api, patron["id"], "CONFIRM_STRIKE")
    assert after_two["resale_risk_score"] == 50
    assert after_two["resale_watch_status"] == "CLEAR"

    after_three = validate_success(
        api.compliance_review(
            patron["id"],
            factories.compliance_review_payload("CONFIRM_STRIKE"),
            HEADERS_COMPLIANCE_OFFICER,
        ),
        200,
    )

    assert after_three["manual_strike_count"] == 3
    assert after_three["resale_risk_score"] == 75
    assert after_three["resale_watch_status"] == "WATCH"
    assert after_three["recent_sales_risk_score"] == 75
    assert after_three["card_status"] == "VALID"
    assert after_three["suspension_reason"] is None
    assert after_three["restricted_units_30d"] == 0
    assert after_three["flagged_sale_count_30d"] == 0


def test_the_pardon_zeroes_the_strikes_and_re_derives_the_watch_from_the_fresh_score(api):
    """The tally resets first, so the score falls to 0 and the axis lands back at CLEAR.

    PRD 3.7: "`CLEAR_WATCH` is the pardon. It resets `manual_strike_count` to 0,
    recomputes both `resale_risk_score` and `recent_sales_risk_score`, and re-derives
    `resale_watch_status` from the fresh rolling score — which lands at `CLEAR` whenever
    that score is below 60."
    PRD 3.7: "It is legal from a `resale_watch_status` of either `WATCH` or
    `RESTRICTED`, and so it serves as both `RESTRICTED → CLEAR` and `WATCH → CLEAR`,
    closing the cycle `CLEAR → WATCH → RESTRICTED → CLEAR`."

    Design: Corner/calculations/corner_clear_watch_zeroes_strikes_and_rederives_watch_status
    """
    patron = fx.create_patron(api, full_name="SGT G Petrusich", id_card_class="ACTIVE_DUTY")
    for _ in range(3):
        fx.record_compliance_review(api, patron["id"], "CONFIRM_STRIKE")
    assert fx.read_patron(api, patron["id"])["resale_watch_status"] == "WATCH"

    pardoned = validate_success(
        api.compliance_review(
            patron["id"],
            factories.compliance_review_payload("CLEAR_WATCH"),
            HEADERS_COMPLIANCE_OFFICER,
        ),
        200,
    )

    assert pardoned["manual_strike_count"] == 0
    assert pardoned["resale_risk_score"] == 0
    assert pardoned["recent_sales_risk_score"] == 0
    assert pardoned["resale_watch_status"] == "CLEAR"
    assert pardoned["card_status"] == "VALID"
