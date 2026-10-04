"""Combinatorial formulas: tender award scoring, clearance rounding order, waterfall.

Three calculation rules whose outputs are pinned to literal values: the
weighted tender award score with its disqualification branch, the per-unit-first
clearance rounding order, and the tier-aware allocation waterfall with leftover
distribution.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    CATEGORY_MANAGER_HEADERS,
    PROCUREMENT_LEAD_HEADERS,
    QA_LEAD_HEADERS,
    fixtures,
    make_store_manager_headers,
)


def test_tender_award_score_weighted_blend_and_disqualify_branch(api):
    """Panel 80/70 score 65.0/57.0; cheapest bid is disqualified at panel 55 with -1.0.

    PRD §3.4: "If the bid's panel `score` is below 60, or the bid's `unit_cost_cents` exceeds the tender's `bid_ceiling_cents`, the bid is marked `DISQUALIFIED` and its `award_score` is set to the marker value −1.0. Otherwise the bid is marked `ELIGIBLE`, and its score is a weighted blend: one-half of the panel `score`, plus three-tenths of a price score, plus one-fifth of the bidding supplier's `quality_score`. The price score is 100 times the headroom between the ceiling and the offered cost, expressed as a fraction of the ceiling — that is, the difference between `bid_ceiling_cents` and the bid's `unit_cost_cents`, divided by `bid_ceiling_cents`, multiplied by 100. The blended result is rounded half-up to 2 decimal places."

    Design: Difficulty/combinatorial_formula/tender_award_score_weighted_disqualify_branch
    """
    category = fixtures.create_category(api)
    sup_a = fixtures.create_supplier(api, name="Sup A")
    sup_b = fixtures.create_supplier(api, name="Sup B")
    sup_c = fixtures.create_supplier(api, name="Sup C")
    product = fixtures.create_product(api, category["id"], unit_cost_cents=200)
    tender = fixtures.create_open_tender(api, product["id"], bid_ceiling_cents=1000)

    bid_a = fixtures.submit_bid(api, tender["id"], sup_a, 700)
    bid_b = fixtures.submit_bid(api, tender["id"], sup_b, 800)
    bid_c = fixtures.submit_bid(api, tender["id"], sup_c, 100)
    fixtures.score_bid_panel(api, bid_a, 80, sample_code="BLIND-A1")
    fixtures.score_bid_panel(api, bid_b, 70, sample_code="BLIND-B1")
    fixtures.score_bid_panel(api, bid_c, 55, sample_code="BLIND-C1")

    r = api.close_tender(tender["id"], PROCUREMENT_LEAD_HEADERS)
    validate_success(r)
    r = api.evaluate_tender(tender["id"], PROCUREMENT_LEAD_HEADERS)
    validate_success(r)

    read_a = validate_success(api.get_bid(bid_a["id"], PROCUREMENT_LEAD_HEADERS))
    read_b = validate_success(api.get_bid(bid_b["id"], PROCUREMENT_LEAD_HEADERS))
    read_c = validate_success(api.get_bid(bid_c["id"], PROCUREMENT_LEAD_HEADERS))

    assert read_a["award_score"] == 65.0, (
        f"0.5*80 + 0.3*30 + 0.2*80 = 65.0, got {read_a['award_score']}"
    )
    assert read_a["status"] == "ELIGIBLE"
    assert read_b["award_score"] == 57.0, (
        f"0.5*70 + 0.3*20 + 0.2*80 = 57.0, got {read_b['award_score']}"
    )
    assert read_b["status"] == "ELIGIBLE"
    assert read_c["award_score"] == -1.0, (
        f"panel 55 < 60 must mark the bid with -1.0, got {read_c['award_score']}"
    )
    assert read_c["status"] == "DISQUALIFIED", (
        "the cheapest bid (100 cents) is DISQUALIFIED because its panel scored below 60"
    )


def test_tender_award_score_price_headroom_component(api):
    """A zero-headroom bid scores purely on panel and quality, not price.

    PRD §3.4: "Otherwise the bid is marked `ELIGIBLE`, and its score is a weighted blend: one-half of the panel `score`, plus three-tenths of a price score, plus one-fifth of the bidding supplier's `quality_score`. The price score is 100 times the headroom between the ceiling and the offered cost, expressed as a fraction of the ceiling — that is, the difference between `bid_ceiling_cents` and the bid's `unit_cost_cents`, divided by `bid_ceiling_cents`, multiplied by 100. The blended result is rounded half-up to 2 decimal places."

    Design: Difficulty/combinatorial_formula/tender_award_score_weighted_disqualify_branch
    """
    category = fixtures.create_category(api)
    sup_a = fixtures.create_supplier(api, name="Sup A")
    sup_b = fixtures.create_supplier(api, name="Sup B")
    product = fixtures.create_product(api, category["id"])
    tender = fixtures.create_open_tender(api, product["id"], bid_ceiling_cents=1000)

    # Bid at exactly the ceiling: price score 0; panel 80; quality 80.
    bid_a = fixtures.submit_bid(api, tender["id"], sup_a, 1000)
    bid_b = fixtures.submit_bid(api, tender["id"], sup_b, 500)
    fixtures.score_bid_panel(api, bid_a, 80, sample_code="BLIND-A1")
    fixtures.score_bid_panel(api, bid_b, 80, sample_code="BLIND-B1")

    validate_success(api.close_tender(tender["id"], PROCUREMENT_LEAD_HEADERS))
    validate_success(api.evaluate_tender(tender["id"], PROCUREMENT_LEAD_HEADERS))

    read_a = validate_success(api.get_bid(bid_a["id"], PROCUREMENT_LEAD_HEADERS))
    read_b = validate_success(api.get_bid(bid_b["id"], PROCUREMENT_LEAD_HEADERS))

    # A: 0.5*80 + 0.3*0 + 0.2*80 = 40 + 0 + 16 = 56.0
    assert read_a["award_score"] == 56.0, (
        f"at-ceiling bid: 0.5*80 + 0.3*0 + 0.2*80 = 56.0, got {read_a['award_score']}"
    )
    # B: price score 50 -> 0.5*80 + 0.3*50 + 0.2*80 = 40 + 15 + 16 = 71.0
    assert read_b["award_score"] == 71.0, (
        f"half-ceiling bid: 0.5*80 + 0.3*50 + 0.2*80 = 71.0, got {read_b['award_score']}"
    )


def test_clearance_value_rounds_per_unit_before_multiplying(api):
    """Per-unit-first rounding: round_half_up(199*0.7)=139, times 3 = 417 — never 418.

    PRD §3.5: "The allocation's sale window is replaced by the clearance window, and its `clearance_value_cents` is computed: the unit clearance price is the product's `price_cents` multiplied by one minus the markdown fraction, rounded half-up to a whole cent per unit first, and that rounded unit price is then multiplied by the allocation's `remaining_quantity`. The per-unit-first rounding order is contractual — rounding only after multiplying by quantity can differ by cents and is not equivalent."

    Design: Difficulty/combinatorial_formula/clearance_markdown_per_unit_rounding_order
    """
    category = fixtures.create_category(api)
    product = fixtures.active_finds_product(api, category, price_cents=199)
    store = fixtures.create_store(api)
    world = fixtures.finds_buy_on_sale(
        api, product["id"], total_quantity=3,
        week_start_date="2026-09-07", week_end_date="2026-09-13",
    )
    alloc = world["allocations"][0]
    assert alloc["allocated_quantity"] == 3

    cleared = validate_success(
        api.clearance_allocation(
            alloc["id"],
            {
                "clearance_markdown_pct": 0.30,
                "clearance_start_date": "2026-09-14",
                "clearance_end_date": "2026-09-20",
            },
            make_store_manager_headers(store["id"]),
        )
    )
    assert cleared["clearance_value_cents"] == 417, (
        f"round_half_up(199*0.7)=139 per unit, times 3 remaining = 417, got {cleared['clearance_value_cents']}"
    )
    assert cleared["clearance_value_cents"] != 418, (
        "418 is the forbidden sum-then-round outcome"
    )
    assert cleared["status"] == "CLEARANCE"


def test_clearance_value_uses_remaining_quantity_at_clearance_time(api):
    """The markdown multiplies the remaining quantity, not the allocated quantity.

    PRD §3.5: "The allocation's sale window is replaced by the clearance window, and its `clearance_value_cents` is computed: the unit clearance price is the product's `price_cents` multiplied by one minus the markdown fraction, rounded half-up to a whole cent per unit first, and that rounded unit price is then multiplied by the allocation's `remaining_quantity`."

    Design: Difficulty/combinatorial_formula/clearance_markdown_per_unit_rounding_order
    """
    category = fixtures.create_category(api)
    product = fixtures.active_finds_product(api, category, price_cents=100)
    store = fixtures.create_store(api)
    world = fixtures.finds_buy_on_sale(
        api, product["id"], total_quantity=5,
        week_start_date="2026-09-07", week_end_date="2026-09-13",
    )
    alloc = world["allocations"][0]
    manager = make_store_manager_headers(store["id"])

    fixtures.set_clock(api, "2026-09-08T10:00:00Z")
    validate_success(api.sell_allocation(alloc["id"], {"quantity": 2}, manager))

    cleared = validate_success(
        api.clearance_allocation(
            alloc["id"],
            {
                "clearance_markdown_pct": 0.25,
                "clearance_start_date": "2026-09-14",
                "clearance_end_date": "2026-09-20",
            },
            manager,
        )
    )
    # round_half_up(100 * 0.75) = 75 per unit; remaining is 3 after selling 2.
    assert cleared["clearance_value_cents"] == 225, (
        f"75 per unit times remaining 3 = 225, got {cleared['clearance_value_cents']}"
    )


def test_finds_waterfall_tier_pools_leftover_order_and_conservation(api):
    """101 units over 1 HIGH_VOLUME + 2 STANDARD stores yields exactly 61/20/20.

    PRD §3.5: "The waterfall distributes `total_quantity` across all `ACTIVE` stores. Stores carry a `tier` of either `HIGH_VOLUME` or `STANDARD`; tiers are processed in priority order, `HIGH_VOLUME` first. Each tier's pool is the buy's `total_quantity` multiplied by the tier's share — 60 percent for `HIGH_VOLUME`, 40 percent for `STANDARD` — rounded down to whole units. Shares renormalize over the tiers actually present: if only one tier has stores, its share is the entire quantity. Within a tier, the pool is divided evenly, each store's per-store quota being the tier pool divided by the tier's store count, again rounded down. Whatever remains after quotas are assigned is distributed one unit at a time to stores ordered first by tier priority and then by store `created_at`, earliest first, until nothing remains."

    Design: Difficulty/combinatorial_formula/finds_waterfall_tier_leftover_order
    """
    category = fixtures.create_category(api)
    product = fixtures.active_finds_product(api, category, price_cents=199)
    hv = fixtures.create_store(api, code="HV1", tier="HIGH_VOLUME")
    st1 = fixtures.create_store(api, code="ST1", tier="STANDARD")
    st2 = fixtures.create_store(api, code="ST2", tier="STANDARD")

    buy = fixtures.create_finds_buy(
        api, product["id"],
        total_quantity=101, week_start_date="2026-09-07", week_end_date="2026-09-13",
    )
    buy = fixtures.plan_allocations(api, buy)

    assert buy["allocated_quantity"] == 101, (
        f"waterfall conservation: allocated must equal total 101, got {buy['allocated_quantity']}"
    )

    def qty_for(store_id):
        rows = validate_success(api.list_store_allocations(store_id, CATEGORY_MANAGER_HEADERS))
        assert len(rows) == 1, f"expected exactly one allocation for store {store_id}"
        return rows[0]["allocated_quantity"]

    # HIGH_VOLUME pool floor(101*0.6)=60 over 1 store -> quota 60;
    # STANDARD pool floor(101*0.4)=40 over 2 stores -> 20 each.
    # Leftover 101 - 100 = 1 goes to the highest-priority earliest store: HV1.
    assert qty_for(hv["id"]) == 61
    assert qty_for(st1["id"]) == 20
    assert qty_for(st2["id"]) == 20


def test_finds_waterfall_renormalizes_when_only_one_tier_present(api):
    """With only STANDARD stores, that tier's share is the entire quantity.

    PRD §3.5: "Shares renormalize over the tiers actually present: if only one tier has stores, its share is the entire quantity."

    Design: Difficulty/combinatorial_formula/finds_waterfall_tier_leftover_order
    """
    category = fixtures.create_category(api)
    product = fixtures.active_finds_product(api, category)
    st1 = fixtures.create_store(api, code="ST1", tier="STANDARD")
    st2 = fixtures.create_store(api, code="ST2", tier="STANDARD")

    buy = fixtures.create_finds_buy(api, product["id"], total_quantity=11)
    buy = fixtures.plan_allocations(api, buy)

    assert buy["allocated_quantity"] == 11

    def qty_for(store_id):
        rows = validate_success(api.list_store_allocations(store_id, CATEGORY_MANAGER_HEADERS))
        return rows[0]["allocated_quantity"]

    # Pool is the full 11: quota floor(11/2)=5 each, leftover 1 to the earliest store.
    quantities = sorted([qty_for(st1["id"]), qty_for(st2["id"])], reverse=True)
    assert quantities == [6, 5], f"expected 6/5 split of 11, got {quantities}"
