"""Formulas whose shape - rounding order, evaluation order, nested bounds - is
what the arithmetic actually turns on.

PRD 3.5 pins the USD conversion: "each requested denomination line is valued
separately ... and the per-line results are then summed", walking the lines in
ascending denomination order.  PRD 3.5 also pins the commission's five-step order,
selecting the tier from the basis before the total is assembled.  PRD 3.3 nests a
class cap inside a vault cap inside a note-rounding step.
"""

from test_helpers import (
    assertions as a,
    factories as f,
    fixtures as fx,
    validate_success,
)

EUR_SELL_RATE_MICROS = 878600


def test_usd_gross_rounds_each_denomination_line_before_summing(api, teller_headers):
    """1 x 10000 + 1 x 5000 + 2 x 2000 EUR at 878600 micros yields 11382 + 5691 +
    4553 = 21626 cents, one cent above the 21625 that a single rounding of the
    19000-minor-unit total would have produced.

    Design: Difficulty/combinatorial_formula/usd_conversion_round_per_line_then_sum_pinned_order
    """
    world = fx.trading_world(
        api, vault_limit_usd_cents=20_000_000, with_position=False, identified=False
    )
    lines = [f.denom(10000, 1), f.denom(5000, 1), f.denom(2000, 2)]

    quote = fx.quote_deal(api, world, denominations=lines, headers=teller_headers)

    a.assert_exchange_transaction(quote)
    assert quote["applied_rate_micros"] == EUR_SELL_RATE_MICROS
    assert quote["fx_gross_minor_units"] == 19000
    assert a.per_line_usd_cents(lines, EUR_SELL_RATE_MICROS) == 21626
    assert quote["quoted_usd_gross_cents"] == 21626
    assert quote["quoted_usd_gross_cents"] != 21625, (
        "21625 is the sum-then-round reading of the same 19000 minor units; the "
        "per-line order keeps the three separate roundings"
    )
    assert quote["quoted_commission_cents"] == 757
    assert quote["quoted_total_charge_cents"] == 22383


def test_per_line_rounding_survives_a_line_whose_own_value_rounds_up(api, teller_headers):
    """3 x 500 + 2 x 10000 EUR converts as 1707 + 22763 = 24470 cents: the small
    line is valued on its own 1500 minor units rather than being absorbed into the
    21500-minor-unit total, and the ascending walk fixes which value is which.

    Design: Difficulty/combinatorial_formula/usd_conversion_round_per_line_then_sum_pinned_order
    """
    world = fx.trading_world(
        api, vault_limit_usd_cents=20_000_000, with_position=False, identified=False
    )
    lines = [f.denom(500, 3), f.denom(10000, 2)]

    quote = fx.quote_deal(api, world, denominations=lines, headers=teller_headers)

    assert quote["fx_gross_minor_units"] == 21500
    assert a.usd_cents_from_minor(1500, EUR_SELL_RATE_MICROS) == 1707
    assert a.usd_cents_from_minor(20000, EUR_SELL_RATE_MICROS) == 22763
    assert quote["quoted_usd_gross_cents"] == 24470
    assert quote["requested_denominations"] == [f.denom(500, 3), f.denom(10000, 2)]


def test_commission_tier_is_selected_from_the_basis_not_from_the_assembled_total(
    api, teller_headers
):
    """A 24470-cent gross sits below the 25000-cent tier edge, so 350 bps applies
    and the commission is 856 cents for a 25326-cent total; keying the tier off that
    already-assembled total, which has crossed the edge, would give 612 and 25082.

    Design: Difficulty/combinatorial_formula/commission_tier_keyed_on_basis_not_total_pinned_evaluation_order
    """
    world = fx.trading_world(
        api, vault_limit_usd_cents=20_000_000, with_position=False, identified=False
    )

    quote = fx.quote_deal(
        api,
        world,
        denominations=[f.denom(500, 3), f.denom(10000, 2)],
        headers=teller_headers,
    )

    assert quote["fx_gross_minor_units"] == 21500
    assert quote["quoted_usd_gross_cents"] == 24470
    assert quote["quoted_commission_cents"] == 856
    assert quote["quoted_total_charge_cents"] == 25326
    assert quote["quoted_commission_cents"] != 612
    assert quote["quoted_total_charge_cents"] != 25082


def test_a_gross_above_the_tier_edge_takes_the_second_band(api, teller_headers):
    """The tier edge itself is real, not an artefact of the ordering: 2 x 10000 EUR
    grosses 22763 cents and pays 350 bps (797), while 8 x 10000 grosses 91054 cents,
    clears 25000 and pays 250 bps (2276), both computed from the gross basis.

    Design: Difficulty/combinatorial_formula/commission_tier_keyed_on_basis_not_total_pinned_evaluation_order
    """
    world = fx.trading_world(
        api, vault_limit_usd_cents=20_000_000, with_position=False, identified=False
    )

    small = fx.quote_deal(api, world, denominations=[f.denom(10000, 2)], headers=teller_headers)
    a.assert_quote_money(small, 20000, EUR_SELL_RATE_MICROS, 22763, 797, 23560)

    large = fx.quote_deal(api, world, denominations=[f.denom(10000, 8)], headers=teller_headers)
    a.assert_quote_money(large, 80000, EUR_SELL_RATE_MICROS, 91054, 2276, 93330)
    assert a.round_half_up(91054 * 250, 10000) == 2276


def _plan_world(api):
    """A 5,000,000-cent branch trading MAJOR EUR and RESTRICTED MAD, with a SUMMER
    corridor into MAD carrying a 13500-bps demand index."""
    branch = fx.register_branch(api, vault_limit_usd_cents=5_000_000)
    fx.register_currency(api, f.eur_currency_payload())
    fx.register_currency(
        api, f.restricted_currency_payload(export_limit_minor_units=200_000)
    )
    fx.record_wholesale_rate(api, currency_code="EUR", mid_rate_micros=920_000)
    fx.record_wholesale_rate(api, currency_code="MAD", mid_rate_micros=10_000_000)
    corridor = fx.register_corridor(
        api,
        code="LHR-CMN-SUMMER",
        destination_country_code="MA",
        destination_currency_code="MAD",
        season="SUMMER",
        season_start_date="2026-06-01T00:00:00Z",
        season_end_date="2026-09-01T00:00:00Z",
        demand_index_bps=13500,
    )
    return branch, corridor


def test_plan_targets_resolve_through_different_branches_of_the_nested_bounds(
    api, manager_headers
):
    """One submit resolves the EUR line through its raw seasonal requirement
    (248400 rounded to 25 notes of 10000 = 250000) and the MAD line through the
    RESTRICTED class cap (621000 clamped to twice the 200000 export limit = 400000),
    so no single cap explains both numbers.

    Design: Difficulty/combinatorial_formula/corridor_inventory_target_nested_min_max_across_currency_classes
    """
    branch, corridor = _plan_world(api)
    plan = fx.draft_plan(api, branch["id"], corridor["id"], season_days=92)
    assert plan["status"] == "DRAFT"
    assert plan["computed_targets"] == []

    submitted = validate_success(
        api.submit_inventory_plan(
            plan["id"],
            {
                "target_lines": [
                    f.target_line("EUR", 2000),
                    f.target_line("MAD", 5000),
                ]
            },
            manager_headers,
        )
    )

    a.assert_inventory_plan(submitted)
    assert submitted["status"] == "SUBMITTED"
    a.assert_computed_targets_shape(submitted["computed_targets"])
    assert submitted["computed_targets"] == [
        {"currency_code": "EUR", "target_minor_units": 250000},
        {"currency_code": "MAD", "target_minor_units": 400000},
    ]


def test_plan_target_falls_back_to_one_largest_note_when_the_bounds_collapse(
    api, manager_headers
):
    """A 1-minor-unit daily baseline over 92 days gives a raw requirement of 12 EUR
    minor units, below the 10000 largest denomination, and the floor lifts the line
    to exactly one 10000 note rather than rounding it away to zero.

    Design: Difficulty/combinatorial_formula/corridor_inventory_target_nested_min_max_across_currency_classes
    """
    branch, corridor = _plan_world(api)
    plan = fx.draft_plan(api, branch["id"], corridor["id"], season_days=92)

    submitted = fx.submit_plan(api, plan["id"], [f.target_line("EUR", 1)], manager_headers)

    assert submitted["computed_targets"] == [
        {"currency_code": "EUR", "target_minor_units": 10000}
    ]
