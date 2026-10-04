"""Order pricing variants (PRD §3.9)."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, validate_success, validate_error,
    set_clock, make_mill, make_grade, make_account, make_order, publish_index,
    confirm_order, get_order,
)

AM = TEST_USERS["account_manager_headers"]


def _setup_two_mode_mill():
    """Mill with SHREDDED 2026-09/2026-10 indices, one BILLET grade, CONTRACT and
    SPOT accounts, one 20t order each (fulfillment 2026-10, base 25000)."""
    set_clock("2026-09-10T00:00:00Z")
    mill = make_mill(name="Crawfordsville Bar Mill", division="CONSTRUCTION")
    publish_index(mill["id"], grade_category="SHREDDED", effective_month="2026-09",
                  price_per_ton_cents=38000)
    publish_index(mill["id"], grade_category="SHREDDED", effective_month="2026-10",
                  price_per_ton_cents=40000)
    grade = make_grade(mill["id"], grade_code="GR40", product_form="BILLET")
    acct_c = make_account(mill["id"], name="Contract Builders Inc",
                          market="CONSTRUCTION", pricing_mode="CONTRACT")
    acct_s = make_account(mill["id"], name="Spot Fabricators LLC",
                          market="CONSTRUCTION", pricing_mode="SPOT")
    ord_c = make_order(mill["id"], acct_c["id"], grade["id"], tons=20,
                       fulfillment_month="2026-10", base_price_cents_per_ton=25000)
    ord_s = make_order(mill["id"], acct_s["id"], grade["id"], tons=20,
                       fulfillment_month="2026-10", base_price_cents_per_ton=25000)
    return mill, grade, acct_c, acct_s, ord_c, ord_s


def test_contract_pricing_resolves_fulfillment_month_index():
    """PRD §3.9: "For a `CONTRACT` account the index month is the order's
    `fulfillment_month`, the computed price is the per-ton unit
    (`base_price_cents_per_ton` plus the surcharge) times the order's `tons` rounded
    half-up to whole cents, `price_basis` is stamped `CONTRACT_MONTH_INDEX`, and that
    price is locked forever after."

    Design: Difficulty/dual_variant_calc/product_price_contract_month_vs_current_month
    """
    mill, grade, acct_c, _s, ord_c, _o = _setup_two_mode_mill()
    confirmed = confirm_order(mill["id"], acct_c["id"], ord_c)
    # (25000 + 40000) * 20 — fulfillment-month 2026-10 index.
    assert confirmed["computed_price_cents"] == 1_300_000
    assert confirmed["price_basis"] == "CONTRACT_MONTH_INDEX"


def test_spot_pricing_resolves_clock_month_index():
    """PRD §3.9: "For a `SPOT` account the index month is the calendar month of the
    logical clock at the call, the same unit-times-tons rounding applies, and
    `price_basis` is stamped `CURRENT_MONTH_INDEX`."
    PRD §3.9: "The surcharge component looks up the `PUBLISHED` surcharge index for
    the mill and the dominant scrap category of the ordered grade's product form —
    `BILLET` maps to `SHREDDED`, `BLOOM` to `BUSHLING`, `SLAB` to `HMS` — at the
    variant's index month"

    Design: Difficulty/dual_variant_calc/product_price_contract_month_vs_current_month
    """
    mill, grade, _c, acct_s, _o, ord_s = _setup_two_mode_mill()
    confirmed = confirm_order(mill["id"], acct_s["id"], ord_s)
    # (25000 + 38000) * 20 — current-month 2026-09 index at confirm (clock pinned
    # at 2026-09-10).
    assert confirmed["computed_price_cents"] == 1_260_000
    assert confirmed["price_basis"] == "CURRENT_MONTH_INDEX"


def _setup_spot_billet_and_bloom():
    """SPOT account with a BILLET order (20t) and a BLOOM order (10t), both
    fulfillment 2026-10; SHREDDED and BUSHLING indices for 2026-09 and 2026-10."""
    set_clock("2026-09-10T00:00:00Z")
    mill = make_mill(name="Decatur Sheet Mill", division="AUTOMOTIVE")
    publish_index(mill["id"], grade_category="SHREDDED", effective_month="2026-09",
                  price_per_ton_cents=38000)
    publish_index(mill["id"], grade_category="SHREDDED", effective_month="2026-10",
                  price_per_ton_cents=40000)
    publish_index(mill["id"], grade_category="BUSHLING", effective_month="2026-09",
                  price_per_ton_cents=42000)
    publish_index(mill["id"], grade_category="BUSHLING", effective_month="2026-10",
                  price_per_ton_cents=41000)
    grade_bil = make_grade(mill["id"], grade_code="BIL-50", product_form="BILLET")
    grade_blm = make_grade(mill["id"], grade_code="BLM-60", product_form="BLOOM",
                           grade_group="GROUP_B")
    acct = make_account(mill["id"], name="Spot Auto Stamping", market="AUTOMOTIVE",
                        pricing_mode="SPOT")
    o1 = make_order(mill["id"], acct["id"], grade_bil["id"], tons=20,
                    fulfillment_month="2026-10", base_price_cents_per_ton=25000)
    o2 = make_order(mill["id"], acct["id"], grade_blm["id"], product_family="BEAM",
                    tons=10, fulfillment_month="2026-10", base_price_cents_per_ton=25000)
    return mill, acct, o1, o2


def test_spot_billet_order_prices_via_shredded_category():
    """PRD §3.9: "`BILLET` maps to `SHREDDED`, `BLOOM` to `BUSHLING`, `SLAB` to
    `HMS`"
    PRD §3.9: "For a `SPOT` account the index month is the calendar month of the
    logical clock at the call, the same unit-times-tons rounding applies, and
    `price_basis` is stamped `CURRENT_MONTH_INDEX`."

    Design: Difficulty/combinatorial_formula/product_price_tiered_branching_by_mode_and_month
    """
    mill, acct, o1, _o2 = _setup_spot_billet_and_bloom()
    confirmed = confirm_order(mill["id"], acct["id"], o1)
    # (25000 + 38000) * 20 — BILLET -> SHREDDED at current month 2026-09.
    assert confirmed["computed_price_cents"] == 1_260_000
    assert confirmed["price_basis"] == "CURRENT_MONTH_INDEX"


def test_spot_bloom_order_prices_via_bushling_category():
    """PRD §3.9: "`BILLET` maps to `SHREDDED`, `BLOOM` to `BUSHLING`, `SLAB` to
    `HMS`"
    PRD §3.9: "Identical order data prices differently across the two modes whenever
    the index moved between the fulfillment month and the current month."

    Design: Difficulty/combinatorial_formula/product_price_tiered_branching_by_mode_and_month
    """
    mill, acct, _o1, o2 = _setup_spot_billet_and_bloom()
    confirmed = confirm_order(mill["id"], acct["id"], o2)
    # (25000 + 42000) * 10 — BLOOM -> BUSHLING at 2026-09; the BUSHLING 2026-10
    # index (41000) is deliberately NOT picked for SPOT.
    assert confirmed["computed_price_cents"] == 670_000
    assert confirmed["price_basis"] == "CURRENT_MONTH_INDEX"


def test_order_confirm_without_published_index_returns_index_missing():
    """PRD §3.9: "The surcharge component looks up the `PUBLISHED` surcharge index
    for the mill and the dominant scrap category of the ordered grade's product form
    — `BILLET` maps to `SHREDDED`, `BLOOM` to `BUSHLING`, `SLAB` to `HMS` — at the
    variant's index month; a missing index fails with `ERR_INDEX_MISSING`."

    Design: Corner/validations/index_missing_is_fiscal_not_state
    """
    mill = make_mill(name="Crawfordsville Bar Mill", division="CONSTRUCTION")
    grade = make_grade(mill["id"], grade_code="GR40", product_form="BILLET")
    acct = make_account(mill["id"], name="Contract Builders Inc",
                        market="CONSTRUCTION", pricing_mode="CONTRACT")
    order = make_order(mill["id"], acct["id"], grade["id"], tons=5,
                       fulfillment_month="2026-11", base_price_cents_per_ton=25000)

    resp = api_client.confirm_order(
        mill["id"], acct["id"], order["id"],
        {"expected_order_version": order["version"]}, AM)
    validate_error(resp, ApiErrorId.ERR_INDEX_MISSING, 422)
    assert get_order(mill["id"], order["id"])["status"] == "QUOTED"


def test_order_confirm_nonexistent_order_returns_order_not_found():
    """PRD §2.7: "(4) resource existence — path resources validated left to right
    from the mill down through contract, lot, heat, campaign, account, order,
    window, event, scorecard, or sheet, and body foreign keys such as `grade_id`,
    `heat_id`, `scrap_lot_id`, and `scope_id`, yield the matching `ERR_*_NOT_FOUND`
    (each at HTTP 404)"

    Design: Corner/validations/existence_beats_state_on_terminal_order_confirm
    """
    mill = make_mill(name="Crawfordsville Bar Mill", division="CONSTRUCTION")
    acct = make_account(mill["id"], name="Contract Builders Inc",
                        market="CONSTRUCTION", pricing_mode="CONTRACT")
    grade = make_grade(mill["id"], grade_code="GR40")
    order = make_order(mill["id"], acct["id"], grade["id"], tons=5,
                       fulfillment_month="2026-09", base_price_cents_per_ton=25000)

    resp = api_client.confirm_order(
        mill["id"], acct["id"], "00000000-0000-4000-8000-000000000009",
        {"expected_order_version": order["version"]}, AM)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND, 404)
