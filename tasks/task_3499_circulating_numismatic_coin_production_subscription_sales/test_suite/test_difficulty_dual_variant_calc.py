"""Difficulty rule dual_variant_calc (PRD §2.9, §3.1, §3.2): one entity state
feeds two PRD-pinned calculation variants. The same fulfilled Federal Reserve
order carries a budgeted seigniorage snapshot and a realized seigniorage
finalization; the same unhedged metal lots yield a mark-to-market exposure and
a budget-variance exposure."""
import pytest

from test_helpers import TEST_USERS, validate_success
from test_helpers.assertions import (
    assert_report_envelope,
    budgeted_unit_seigniorage_cents,
    realized_seigniorage_cents,
    realized_unit_blank_cost_cents,
)
from test_helpers.constants import (
    DEFAULT_DENOMINATION,
    DEFAULT_LOCKED_COPPER_PRICE_CENTS_PER_TONNE,
)
from test_helpers.fixtures import (
    create_denomination,
    create_metal_lot,
    create_run,
    inspect_run,
    set_clock,
    setup_circulating_base,
    start_run,
)

LIAISON = TEST_USERS["fed_liaison_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


def test_seigniorage_budgeted_vs_realized_on_fulfillment(api):
    """PRD §3.1: "Newly submitted orders sit in `SUBMITTED`, and at creation the
    platform snapshots `budgeted_seigniorage_cents` as `quantity_ordered_pieces`
    multiplied by the denomination's current `budgeted_unit_seigniorage_cents`."
    PRD §3.1: "When a completing run pushes the fulfilled count to at least the
    ordered quantity, the order auto-transitions `FULFILLING → FULFILLED` and
    finalizes its `realized_seigniorage_cents`: the platform computes the
    denomination's realized unit blank cost by dividing the summed
    `realized_cost_cents` of that denomination's `DELIVERED` lots by the summed
    `blanks_produced` of those same lots, rounding the quotient half-up to 2
    decimal places; it then subtracts that unit cost and the denomination's
    `striking_cost_cents` from `face_value_cents`, rounds the resulting unit
    margin half-up to 2 decimal places, and only then multiplies by
    `quantity_ordered_pieces`."
    PRD §2.9: "The seigniorage report carries one row per denomination with
    `budgeted_seigniorage_cents` summed over non-cancelled orders' creation-time
    snapshots, `realized_seigniorage_cents` summed over `FULFILLED` orders, and
    the reconciliation figures `blanks_on_hand_pieces`, `blanks_reserved_pieces`,
    `blanks_produced_pieces`, `blanks_scrapped_pieces`, and
    `blanks_delivered_pieces`; optional `fiscal_year` and `denomination_code`
    query parameters narrow the rows."

    Design: Difficulty/dual_variant_calc/seigniorage_budgeted_vs_realized_on_fulfillment
    """
    # QUARTER (face 25c, budget blank 4.0c, striking 2.0c, 176000 blanks/tonne);
    # one hedged 10t COPPER lot locked at 900000c/t, DELIVERED (1760000 blanks,
    # realized cost 9000000c); FY2026 order for 100000 pieces.
    denomination, lot, fed_order = setup_circulating_base(
        api, quantity_ordered_pieces=100000)
    run = create_run(
        api, fed_order["id"], facility="PHILADELPHIA", press_line="P1",
        planned_start="2026-10-05T08:00:00Z", planned_end="2026-10-05T16:00:00Z",
        planned_quantity=100000)
    start_run(api, run["id"])
    run = inspect_run(api, run["id"], outcome="PASS", good_pieces=100000)
    assert run["status"] == "COMPLETED"

    resp = api.get_fed_order(fed_order["id"], LIAISON)
    order = validate_success(resp)
    assert order["status"] == "FULFILLED"

    # Expected variants via the pinned calculators (design literals cross-checked).
    expected_unit_seigniorage = budgeted_unit_seigniorage_cents(
        DEFAULT_DENOMINATION["face_value_cents"],
        DEFAULT_DENOMINATION["blank_budget_cost_cents"],
        DEFAULT_DENOMINATION["striking_cost_cents"])
    assert expected_unit_seigniorage == 19.0
    expected_budgeted = 100000 * expected_unit_seigniorage
    assert expected_budgeted == 1900000.0
    expected_unit_blank = realized_unit_blank_cost_cents(
        [(10 * DEFAULT_LOCKED_COPPER_PRICE_CENTS_PER_TONNE,
          10 * DEFAULT_DENOMINATION["blanks_per_tonne"])])
    assert expected_unit_blank == 5.11
    expected_realized = realized_seigniorage_cents(
        100000, DEFAULT_DENOMINATION["face_value_cents"],
        expected_unit_blank, DEFAULT_DENOMINATION["striking_cost_cents"])
    assert expected_realized == 1789000.0

    assert order["budgeted_seigniorage_cents"] == pytest.approx(expected_budgeted, abs=0.01)
    assert order["realized_seigniorage_cents"] == pytest.approx(expected_realized, abs=0.01)

    resp = api.get_report(
        "seigniorage", FINANCE,
        params={"fiscal_year": 2026, "denomination_code": "QUARTER"})
    report = validate_success(resp)
    assert_report_envelope(report, "seigniorage")
    assert len(report["rows"]) == 1
    row = report["rows"][0]
    assert row["budgeted_seigniorage_cents"] == pytest.approx(expected_budgeted, abs=0.01)
    assert row["realized_seigniorage_cents"] == pytest.approx(expected_realized, abs=0.01)
    assert row["budgeted_seigniorage_cents"] - row["realized_seigniorage_cents"] == pytest.approx(111000.0, abs=0.01)


def test_metal_exposure_mark_to_market_vs_budget_variance(api):
    """PRD §3.2: "Commodity exposure is reported only for unhedged lots — those
    whose `locked_unit_price_cents_per_tonne` is absent — in either `ORDERED` or
    `DELIVERED` status, grouped by `commodity`."
    PRD §3.2: "The default variant, `mark_to_market`, measures drift since each
    order was placed: for every exposed lot, its `quantity_tonnes` multiplied by
    the difference between the commodity's current spot price and the lot's
    `order_spot_cents_per_tonne`, summed per commodity into an integer-cents
    `exposure_cents`. The `budget_variance` variant measures drift against the
    budget reference: the same tonnage multiplied by the difference between the
    current spot price and the lot's `budget_price_cents_per_tonne`."
    PRD §3.2: "Hedged lots are excluded from both variants."

    Design: Difficulty/dual_variant_calc/metal_exposure_mark_to_market_vs_budget_variance
    """
    set_clock(api, "2026-09-01T00:00:00Z", {"COPPER": 800000})
    create_denomination(api)
    # Hedged 10t lot (locked 820000): contributes 0 to both variants.
    create_metal_lot(api, quantity_tonnes=10,
                     budget_price_cents_per_tonne=700000,
                     locked_unit_price_cents_per_tonne=820000,
                     vault="WEST_POINT", planned_delivery_date="2026-09-05")
    # Unhedged 20t lot: order_spot recorded as 800000 at creation.
    create_metal_lot(api, quantity_tonnes=20,
                     budget_price_cents_per_tonne=750000,
                     locked_unit_price_cents_per_tonne=None,
                     vault="FORT_KNOX", planned_delivery_date="2026-09-06")
    set_clock(api, "2026-09-02T00:00:00Z", {"COPPER": 900000})

    resp = api.get_report("metal-exposure", FINANCE,
                          params={"variant": "mark_to_market", "commodity": "COPPER"})
    report = validate_success(resp)
    assert_report_envelope(report, "metal-exposure")
    assert len(report["rows"]) == 1
    mark_to_market_cents = report["rows"][0]["exposure_cents"]
    assert mark_to_market_cents == 2000000  # 20t x (900000 - 800000)

    resp = api.get_report("metal-exposure", FINANCE,
                          params={"variant": "budget_variance", "commodity": "COPPER"})
    report = validate_success(resp)
    assert_report_envelope(report, "metal-exposure")
    assert len(report["rows"]) == 1
    budget_variance_cents = report["rows"][0]["exposure_cents"]
    assert budget_variance_cents == 3000000  # 20t x (900000 - 750000)
    assert budget_variance_cents - mark_to_market_cents == 1000000
