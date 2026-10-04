"""Pricing mathematics: dual-variant landed cost, per-unit rounding order,
and the jurisdictional advertised-price legality branches."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    complete_screening,
    create_cleared_lot,
    create_default_jurisdiction,
    create_event,
    create_jurisdiction,
    create_lot,
    create_member,
    create_vendor,
    get_lot,
    guest_purchase,
    member_purchase,
    open_screening,
    price_lot,
    set_clock,
    setup_sellable_store,
    validate_error,
    validate_paginated,
)


def test_landed_cost_provisional_variant_at_creation(api, buyer_headers):
    """PRD §3.5: "Before any screening has passed, the provisional variant
    divides the lot's `total_cost_cents` by `est_sellable_qty` and rounds
    half-up to a whole cent."
    PRD §3.2: "the lot's `landed_unit_cost_cents` is computed immediately
    using the provisional variant described in §3.5."

    Design: Difficulty/dual_variant_calc/landed_cost_provisional_vs_final_variant
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    lot = create_lot(vendor["id"], jur["id"], buyer_headers,
                     quantity_total=100, total_cost_cents=100000,
                     est_sellable_qty=50)
    # provisional: round_half_up(100000 / 50) == 2000
    assert lot["landed_unit_cost_cents"] == 2000
    assert lot["sellable_qty_confirmed"] is None


def test_landed_cost_final_variant_after_passed_screening(api, buyer_headers,
                                                          officer_headers):
    """PRD §3.5: "After the first `PASSED` screening, the final variant
    divides `total_cost_cents` by a grade-weighted effective quantity — each
    observed grade-A unit counts in full, each grade-B unit counts as
    eight-tenths of a unit, and each grade-C unit counts as six-tenths —
    again rounding half-up to a whole cent."
    PRD §3.3: "A `PASSED` screening moves the lot from `SCREENING` to
    `CLEARED`, sets `safety_status` to `CLEARED`, records
    `sellable_qty_confirmed` as the sum of the three observed grade counts,
    and recomputes `landed_unit_cost_cents` using the final variant of §3.5."

    Design: Difficulty/dual_variant_calc/landed_cost_provisional_vs_final_variant
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    lot = create_lot(vendor["id"], jur["id"], buyer_headers,
                     quantity_total=100, total_cost_cents=100000,
                     est_sellable_qty=50)
    scr = open_screening(lot["id"], officer_headers)
    complete_screening(lot["id"], scr["id"], officer_headers,
                       qty_grade_a=50, qty_grade_b=20, qty_grade_c=30)
    lot_after = get_lot(lot["id"])
    # effective = 50*1.0 + 20*0.8 + 30*0.6 = 84; round_half_up(100000/84) == 1190
    assert lot_after["landed_unit_cost_cents"] == 1190
    assert lot_after["sellable_qty_confirmed"] == 100
    assert lot_after["commercial_status"] == "CLEARED"
    assert lot_after["safety_status"] == "CLEARED"


def test_advertised_price_legality_branching(api, pricing_headers):
    """PRD §3.5: "Under `WAS_NOW_WINDOW`, the `comparison_price_cents` must be
    at least the retail price marked up by twenty percent — that is, at least
    the retail price multiplied by 1.20, with the anchor computed in whole
    cents rounded half-up, and the comparison boundary inclusive — otherwise
    `ERR_ANCHOR_PREMIUM_INSUFFICIENT`. The advertised discount percent is then
    computed as the difference between the comparison price and the retail
    price, expressed in hundredths of a percent of the comparison price with
    the final figure rounded half-up to two decimal places; if that figure
    exceeds the jurisdiction's `max_advertised_discount_pct`, the pricing is
    rejected with `ERR_ADVERTISED_DISCOUNT_TOO_DEEP`, with the cap boundary
    inclusive."
    PRD §3.5: "Under `MSRP_REFERENCE`, the `comparison_price_cents` must equal
    the lot's `vendor_msrp_cents` exactly, else `ERR_COMPARISON_NOT_MSRP`, and
    the `retail_price_cents` must not exceed the comparison price — a retail
    above the comparison is rejected as `ERR_ADVERTISED_DISCOUNT_TOO_DEEP`."

    Design: Difficulty/combinatorial_formula/advertised_price_legality_branching
    """
    jur_ca = create_default_jurisdiction()
    jur_tx = create_jurisdiction(jurisdiction_code="TX",
                                 comparison_rule="MSRP_REFERENCE",
                                 max_advertised_discount_pct=90,
                                 member_discount_cap_pct=40)
    vendor = create_vendor()
    lot_a = create_cleared_lot(vendor["id"], jur_ca["id"],
                               source_type="PACKAGE_CHANGE",
                               comparison_price_cents=10000,
                               vendor_msrp_cents=10000)
    lot_b = create_cleared_lot(vendor["id"], jur_tx["id"],
                               quantity_total=10, total_cost_cents=9000,
                               est_sellable_qty=10,
                               comparison_price_cents=9000,
                               vendor_msrp_cents=10000)

    # discount 80% > cap 70 (anchor 2400 <= 10000 passes first)
    r1 = api.price_lot(lot_a["id"], {"retail_price_cents": 2000,
                                     "advertises_comparison": True},
                       pricing_headers)
    validate_error(r1, ApiErrorId.ERR_ADVERTISED_DISCOUNT_TOO_DEEP)
    # anchor round_half_up(9000 * 1.2) = 10800 > comparison 10000
    r2 = api.price_lot(lot_a["id"], {"retail_price_cents": 9000,
                                     "advertises_comparison": True},
                       pricing_headers)
    validate_error(r2, ApiErrorId.ERR_ANCHOR_PREMIUM_INSUFFICIENT)
    # MSRP_REFERENCE: comparison 9000 != vendor msrp 10000
    r3 = api.price_lot(lot_b["id"], {"retail_price_cents": 5000,
                                     "advertises_comparison": True},
                       pricing_headers)
    validate_error(r3, ApiErrorId.ERR_COMPARISON_NOT_MSRP)
    # legal price succeeds and moves the lot to PRICED
    ok = price_lot(lot_a["id"], retail_price_cents=4000)
    assert ok["commercial_status"] == "PRICED"
    assert ok["retail_price_cents"] == 4000


def test_advertised_price_legality_msrp_retail_above_comparison(api,
                                                                pricing_headers):
    """PRD §3.5: "Under `MSRP_REFERENCE`, the `comparison_price_cents` must
    equal the lot's `vendor_msrp_cents` exactly, else
    `ERR_COMPARISON_NOT_MSRP`, and the `retail_price_cents` must not exceed
    the comparison price — a retail above the comparison is rejected as
    `ERR_ADVERTISED_DISCOUNT_TOO_DEEP`."

    Design: Difficulty/combinatorial_formula/advertised_price_legality_branching
    """
    jur_tx = create_jurisdiction(jurisdiction_code="TX",
                                 comparison_rule="MSRP_REFERENCE",
                                 max_advertised_discount_pct=90,
                                 member_discount_cap_pct=40)
    vendor = create_vendor()
    lot = create_cleared_lot(vendor["id"], jur_tx["id"],
                             quantity_total=10, total_cost_cents=9000,
                             est_sellable_qty=10,
                             comparison_price_cents=10000,
                             vendor_msrp_cents=10000)
    # MSRP matches but retail 12000 exceeds comparison 10000.
    resp = api.price_lot(lot["id"], {"retail_price_cents": 12000,
                                     "advertises_comparison": True},
                         pricing_headers)
    validate_error(resp, ApiErrorId.ERR_ADVERTISED_DISCOUNT_TOO_DEEP)
    assert get_lot(lot["id"])["commercial_status"] == "CLEARED"


def test_anchor_premium_exact_boundary_passes(api, pricing_headers):
    """PRD §3.5: "the `comparison_price_cents` must be at least the retail
    price marked up by twenty percent — that is, at least the retail price
    multiplied by 1.20, with the anchor computed in whole cents rounded
    half-up, and the comparison boundary inclusive — otherwise
    `ERR_ANCHOR_PREMIUM_INSUFFICIENT`."

    Design: Corner/calculations/anchor_premium_exact_boundary_passes
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    lot_x = create_cleared_lot(vendor["id"], jur["id"], quantity_total=10,
                               total_cost_cents=1000, est_sellable_qty=10,
                               comparison_price_cents=4800,
                               vendor_msrp_cents=4800)
    lot_y = create_cleared_lot(vendor["id"], jur["id"], quantity_total=10,
                               total_cost_cents=1000, est_sellable_qty=10,
                               comparison_price_cents=4799,
                               vendor_msrp_cents=4799)
    # 4800 >= round_half_up(4000 * 1.2) == 4800, inclusive boundary passes
    ok = price_lot(lot_x["id"], retail_price_cents=4000)
    assert ok["commercial_status"] == "PRICED"
    # one cent below the anchor fails
    bad = api.price_lot(lot_y["id"], {"retail_price_cents": 4000,
                                      "advertises_comparison": True},
                        pricing_headers)
    validate_error(bad, ApiErrorId.ERR_ANCHOR_PREMIUM_INSUFFICIENT)


def test_member_price_per_unit_rounding_half_up_at_unit_level(api):
    """PRD §3.6: "The per-unit price is the lot's current `retail_price_cents`
    reduced by that percent, rounded half-up to a whole cent and recorded as
    `unit_price_cents`; the `line_total_cents` is exactly the per-unit price
    multiplied by `qty` with no further rounding."
    PRD §3.6: "a member purchase with no `ACTIVE` event covering the instant
    takes the tier discount — five percent for `BRONZE`, ten for `SILVER`,
    fifteen for `GOLD` — with `pricing_variant` `STANDARD`."

    Design: Difficulty/combinatorial_formula/member_price_nested_rounding_order
    """
    # Retail 3999 with SILVER 10 pct: round_half_up(3999 * 90/100) =
    # round_half_up(3599.1) = 3599 per unit; line = 3599 * 2 = 7198 (no
    # second rounding at line level).
    jur = create_default_jurisdiction()
    ctx = setup_sellable_store(jurisdiction_id=jur["id"],
                               retail_price_cents=3999,
                               daily_unit_limit=10)
    member = create_member(ctx["store"]["id"], member_code="M-S2",
                           tier="SILVER")
    purchase = member_purchase(ctx["store"]["id"], ctx["lot"]["id"], 2,
                               member["id"])
    assert purchase["pricing_variant"] == "STANDARD"
    assert purchase["discount_pct_applied"] == 10
    assert purchase["unit_price_cents"] == 3599
    assert purchase["line_total_cents"] == 7198


def test_member_price_nested_rounding_order(api):
    """PRD §3.6: "Pricing then follows a pinned evaluation order — rounding
    order matters, and rounding never happens at line level." and "The
    per-unit price is the lot's current `retail_price_cents` reduced by that
    percent, rounded half-up to a whole cent and recorded as
    `unit_price_cents`; the `line_total_cents` is exactly the per-unit price
    multiplied by `qty` with no further rounding."
    PRD §3.6: "a member purchase during an `ACTIVE` event whose tier qualifies
    takes the tier discount plus the event's `extra_discount_pct`, with
    `pricing_variant` `EVENT`."

    Design: Difficulty/combinatorial_formula/member_price_nested_rounding_order
    """
    jur = create_default_jurisdiction()
    ctx = setup_sellable_store(jurisdiction_id=jur["id"],
                               retail_price_cents=3999,
                               daily_unit_limit=10)
    member = create_member(ctx["store"]["id"], member_code="M-SILVER",
                           tier="SILVER")
    create_event(ctx["lot"]["id"], starts_at="2026-09-02T10:00:00Z",
                 ends_at="2026-09-02T12:00:00Z", min_tier="BRONZE",
                 extra_discount_pct=10)
    set_clock("2026-09-02T11:00:00Z")
    purchase = member_purchase(ctx["store"]["id"], ctx["lot"]["id"], 3,
                               member["id"])
    # SILVER 10 + event extra 10 == 20 pct, under the cap of 30
    assert purchase["discount_pct_applied"] == 20
    # per-unit rounding pinned: round_half_up(3999 * 80 / 100) == 3199
    assert purchase["unit_price_cents"] == 3199
    # line total is unit * qty with no second rounding: 3199 * 3 == 9597
    assert purchase["line_total_cents"] == 9597
    assert purchase["pricing_variant"] == "EVENT"


def test_member_price_event_vs_standard_variant(api):
    """PRD §3.6: "a member purchase with no `ACTIVE` event covering the
    instant takes the tier discount — five percent for `BRONZE`, ten for
    `SILVER`, fifteen for `GOLD` — with `pricing_variant` `STANDARD`" and
    "a member purchase during an `ACTIVE` event whose tier qualifies takes the
    tier discount plus the event's `extra_discount_pct`, with
    `pricing_variant` `EVENT`."
    PRD §2.5: "early-access events whose windows now cover the current instant
    move from `SCHEDULED` to `ACTIVE`".

    Design: Difficulty/dual_variant_calc/member_price_event_vs_standard_variant
    """
    ctx = setup_sellable_store(daily_unit_limit=10)
    member = create_member(ctx["store"]["id"], member_code="M-GOLD",
                           tier="GOLD")
    create_event(ctx["lot"]["id"], starts_at="2026-09-02T10:00:00Z",
                 ends_at="2026-09-02T12:00:00Z", min_tier="GOLD",
                 extra_discount_pct=10)
    # Before the window: STANDARD variant, GOLD 15 pct off 4000 -> 3400.
    std = member_purchase(ctx["store"]["id"], ctx["lot"]["id"], 2, member["id"])
    assert std["pricing_variant"] == "STANDARD"
    assert std["unit_price_cents"] == 3400
    assert std["line_total_cents"] == 6800
    # Advance into the window: EVENT variant, 15 + 10 = 25 pct -> 3000.
    set_clock("2026-09-02T11:00:00Z")
    evt = member_purchase(ctx["store"]["id"], ctx["lot"]["id"], 2, member["id"])
    assert evt["pricing_variant"] == "EVENT"
    assert evt["unit_price_cents"] == 3000
    assert evt["line_total_cents"] == 6000
    data, _ = validate_paginated(api.list_early_access_events(
        ctx["lot"]["id"], TEST_USERS["admin_headers"]))
    assert data[0]["status"] == "ACTIVE"


def test_member_price_standard_variant_guest_and_tiers(api):
    """PRD §3.6: "guests (no `member_id`) pay full freight with a percent of
    zero and `pricing_variant` `GUEST`; a member purchase with no `ACTIVE`
    event covering the instant takes the tier discount — five percent for
    `BRONZE`, ten for `SILVER`, fifteen for `GOLD` — with `pricing_variant`
    `STANDARD`".

    Design: Difficulty/dual_variant_calc/member_price_event_vs_standard_variant
    """
    ctx = setup_sellable_store(daily_unit_limit=10)
    g = guest_purchase(ctx["store"]["id"], ctx["lot"]["id"], 1)
    assert g["pricing_variant"] == "GUEST"
    assert g["discount_pct_applied"] == 0
    assert g["unit_price_cents"] == 4000
    bronze = create_member(ctx["store"]["id"], member_code="M-B",
                           tier="BRONZE")
    b = member_purchase(ctx["store"]["id"], ctx["lot"]["id"], 1, bronze["id"])
    assert b["pricing_variant"] == "STANDARD"
    assert b["discount_pct_applied"] == 5
    assert b["unit_price_cents"] == 3800  # round_half_up(4000 * 95/100)
    assert b["line_total_cents"] == 3800
