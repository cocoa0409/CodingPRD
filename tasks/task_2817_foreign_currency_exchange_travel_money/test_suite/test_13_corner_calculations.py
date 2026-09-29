"""The arithmetic surface: mid-rate selection, spread derivation, the commission
schedule, vault utilisation, surveillance aggregates and the rate-lock clock.

PRD 2.11 pins the selection order: "the candidates are ordered by `effective_at`
descending and, where two share the same `effective_at`, by `created_at` descending,
and the first candidate's `mid_rate_micros` is used - so the later-recorded of two
simultaneously-effective quotes wins".  PRD 3.5 pins the conversion order: "each
denomination line is converted and rounded *first*, and the rounded line values are
summed afterwards", and the commission "floor of 400 cents (four dollars) applied
**after** that rounding".
"""

from test_helpers import (
    ApiErrorId,
    assertions as a,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_mid_rate_selection_walks_effective_at_not_recording_order(
    api, treasury_headers
):
    """Of three EUR quotes recorded out of order the 900000 mid effective 2026-07-15
    wins - so a 100000-minor manifest values at 111111 cents rather than the 108696 of
    the earlier-effective 920000 quote or the 117647 of the future-dated 850000 quote -
    a later-recorded quote sharing that effective_at then takes over at 109890, and a
    currency whose only quote is future-dated cannot be valued at all.

    Design: Corner/calculations/wholesale_selection_ignores_future_and_honours_recording_order
    """
    branch = fx.register_branch(api)
    fx.register_currency(api)
    fx.register_currency(api, f.jpy_currency_payload())

    fx.record_wholesale_rate(
        api, mid_rate_micros=900_000, effective_at="2026-07-15T00:00:00Z"
    )
    fx.record_wholesale_rate(
        api, mid_rate_micros=920_000, effective_at="2026-07-01T00:00:00Z"
    )
    fx.record_wholesale_rate(
        api, mid_rate_micros=850_000, effective_at="2026-09-01T00:00:00Z"
    )
    fx.record_wholesale_rate(
        api,
        currency_code="JPY",
        mid_rate_micros=15_000_000,
        effective_at="2026-09-01T00:00:00Z",
    )

    first = fx.raise_shipment(
        api, branch["id"], "EUR", "REPLENISHMENT", [f.denom(10000, 10)]
    )
    a.assert_cash_shipment(first)
    assert first["manifest_minor_units"] == 100000
    assert first["manifest_usd_equivalent_cents"] == 111111
    assert first["manifest_usd_equivalent_cents"] not in (108696, 117647)

    fx.record_wholesale_rate(
        api,
        mid_rate_micros=910_000,
        effective_at="2026-07-15T00:00:00Z",
        source_code="INTERBANK_CLOSE",
    )

    second = fx.raise_shipment(
        api, branch["id"], "EUR", "REPLENISHMENT", [f.denom(10000, 10)]
    )
    assert second["manifest_minor_units"] == 100000
    assert second["manifest_usd_equivalent_cents"] == 109890

    validate_error(
        api.create_cash_shipment(
            f.create_cash_shipment_payload(
                branch["id"], "JPY", "REPLENISHMENT", [f.denom(10000, 10)]
            ),
            treasury_headers,
        ),
        ApiErrorId.ERR_WHOLESALE_RATE_NOT_FOUND,
        404,
    )

    _, meta = validate_paginated(
        api.list_wholesale_rates(treasury_headers, {"currency_code": "EUR"})
    )
    assert meta["total_count"] == 4


def test_both_spreads_round_half_up_from_the_same_mid(api, treasury_headers):
    """From a 912345-micro mid the 555-bps buy spread's exact 962980.1475 rounds down
    to 962980 while the 445-bps sell spread's exact 871745.6475 rounds up to 871746,
    and the card stays anchored to the cited quote.

    Design: Corner/calculations/rate_card_derivation_rounds_both_spreads_half_up
    """
    branch = fx.register_branch(api, code="BR-ZRH", name="Zurich", region_code="NORTH")
    fx.register_currency(api, f.chf_currency_payload())
    wholesale = fx.record_wholesale_rate(
        api, currency_code="CHF", mid_rate_micros=912_345
    )

    card = validate_success(
        api.create_rate_card(
            f.create_rate_card_payload(
                branch["id"],
                wholesale["id"],
                branch["version"],
                currency_code="CHF",
                buy_spread_bps=555,
                sell_spread_bps=445,
                board_display_label="CHF Swiss Franc",
            ),
            treasury_headers,
        ),
        201,
    )

    a.assert_rate_card(card)
    assert card["buy_rate_micros"] == 962980
    assert card["sell_rate_micros"] == 871746
    assert card["buy_rate_micros"] > 912345 > card["sell_rate_micros"]
    assert card["wholesale_rate_id"] == wholesale["id"]


def test_the_currency_profile_supplies_the_recovery_percentage(
    api, teller_headers, teller2_headers, manager_headers
):
    """With damaged_note_recovery_bps declared as 4000 instead of the 6500 default, a
    three-note damaged block recovers 12364 cents through the pinned two-step rounding
    - not the 12363 a single step would give, and not the 20091 the default would - and
    the discount exchange returns all 23 notes to stock.

    Design: Corner/calculations/damaged_recovery_bps_override_and_two_step_rounding
    """
    world = fx.trading_world(
        api,
        currency_payload=f.create_currency_payload(damaged_note_recovery_bps=4000),
        position_mix=[f.denom(10000, 20)],
        identified=False,
    )
    assert world["currency"]["damaged_note_recovery_bps"] == 4000

    txn = fx.settled_deal(
        api,
        world,
        "BUY_FX_FROM_CUSTOMER",
        [f.denom(10000, 3)],
        teller_headers,
        settle_headers=teller2_headers,
    )
    a.assert_settlement_money(txn, 30909, 773, 30136)

    assessment = fx.detain_notes(
        api,
        world["branch"]["id"],
        world["position"]["id"],
        txn["id"],
        10000,
        3,
        "DAMAGED",
        teller_headers,
    )
    assert assessment["face_fx_minor_units"] == 30000

    assessed = fx.assess_notes(
        api, assessment["id"], "EXCHANGED_AT_DISCOUNT", "water damage", manager_headers
    )

    a.assert_note_assessment(assessed)
    assert assessed["status"] == "ASSESSED"
    assert assessed["outcome"] == "EXCHANGED_AT_DISCOUNT"
    assert assessed["recovery_usd_cents"] == 12364
    assert assessed["recovery_usd_cents"] not in (12363, 20091)

    position = fx.read_position(api, world["position"]["id"])
    a.assert_position_mix_invariants(position)
    a.assert_mix_counts(position, 10000, available=23, quarantined=0)
    assert position["total_minor_units"] == 230000
    assert position["usd_equivalent_cents"] == 250000

    a.assert_vault_state(fx.read_branch(api, world["branch"]["id"]), 250000, 125, "OPEN")


def test_the_tier_ceiling_makes_a_bigger_deal_cheaper(api, teller_headers):
    """The 25000-cent ceiling is exclusive, so a 24470-cent quote pays 856 cents of
    commission at 350 bps while a quote only 569 cents larger pays 626 at 250 bps; the
    250-bps band still holds at 56909 and the 100000-cent ceiling drops 113817 to 150
    bps; and no quote moves a note.

    Design: Corner/calculations/commission_tier_ceilings_straddled_on_quotes
    """
    mix = [f.denom(500, 5), f.denom(1000, 5), f.denom(2000, 5), f.denom(10000, 20)]
    world = fx.trading_world(api, position_mix=mix)

    first = fx.quote_deal(
        api,
        world,
        "SELL_FX_TO_CUSTOMER",
        [f.denom(10000, 2), f.denom(1000, 1), f.denom(500, 1)],
        teller_headers,
    )
    a.assert_quote_money(first, 21500, 878600, 24470, 856, 25326)

    second = fx.quote_deal(
        api,
        world,
        "SELL_FX_TO_CUSTOMER",
        [f.denom(10000, 2), f.denom(2000, 1)],
        teller_headers,
    )
    a.assert_quote_money(second, 22000, 878600, 25039, 626, 25665)
    assert second["quoted_usd_gross_cents"] > first["quoted_usd_gross_cents"]
    assert second["quoted_commission_cents"] < first["quoted_commission_cents"]

    third = fx.quote_deal(
        api, world, "SELL_FX_TO_CUSTOMER", [f.denom(10000, 5)], teller_headers
    )
    a.assert_quote_money(third, 50000, 878600, 56909, 1423, 58332)

    fourth = fx.quote_deal(
        api, world, "SELL_FX_TO_CUSTOMER", [f.denom(10000, 10)], teller_headers
    )
    a.assert_quote_money(fourth, 100000, 878600, 113817, 1707, 115524)

    position = fx.read_position(api, world["position"]["id"])
    a.assert_mix_counts(position, 500, available=5)
    a.assert_mix_counts(position, 1000, available=5)
    a.assert_mix_counts(position, 2000, available=5)
    a.assert_mix_counts(position, 10000, available=20)


def test_the_four_hundred_cent_floor_applies_after_rounding(api, teller_headers):
    """A single 500-minor note grosses 569 cents on the sell side and 515 on the buy
    side, and both raw commissions - 20 and 18 cents - are lifted to the 400-cent floor
    after rounding, so the customer pays 969 on the sale and receives only 115 on the
    purchase.

    Design: Corner/calculations/commission_minimum_floor_applies_after_rounding
    """
    world = fx.trading_world(
        api, position_mix=[f.denom(500, 5), f.denom(10000, 20)], identified=False
    )

    sell = fx.quote_deal(
        api, world, "SELL_FX_TO_CUSTOMER", [f.denom(500, 1)], teller_headers
    )
    a.assert_quote_money(sell, 500, 878600, 569, 400, 969)
    assert sell["quoted_commission_cents"] not in (18, 20)

    buy = fx.quote_deal(
        api, world, "BUY_FX_FROM_CUSTOMER", [f.denom(500, 1)], teller_headers
    )
    a.assert_quote_money(buy, 500, 970600, 515, 400, 115)
    assert buy["quoted_commission_cents"] not in (18, 20)


def test_the_restricted_band_is_inclusive_at_both_ends(api, treasury_headers):
    """Three kiosks sharing the 100000-cent minimum ceiling land on 8967 bps OPEN,
    exactly 10000 bps RESTRICTED - not FROZEN - and 10054 bps FROZEN, and only the two
    non-OPEN branches raise an automatic repatriation whose manifest is a whole-note
    waterfall down towards eighty-five percent of the ceiling.

    Design: Corner/calculations/vault_posture_bands_at_exact_boundaries
    """
    fx.register_currency(api)
    fx.record_wholesale_rate(api)
    open_branch = fx.register_branch(
        api, code="BR-A", name="Kiosk A", vault_limit_usd_cents=100_000
    )
    edge_branch = fx.register_branch(
        api, code="BR-B", name="Kiosk B", vault_limit_usd_cents=100_000
    )
    frozen_branch = fx.register_branch(
        api, code="BR-C", name="Kiosk C", vault_limit_usd_cents=100_000
    )

    open_position = fx.open_position(
        api,
        open_branch["id"],
        "EUR",
        [f.denom(10000, 8), f.denom(2000, 1), f.denom(500, 1)],
    )
    edge_position = fx.open_position(
        api, edge_branch["id"], "EUR", [f.denom(10000, 9), f.denom(2000, 1)]
    )
    frozen_position = fx.open_position(
        api,
        frozen_branch["id"],
        "EUR",
        [f.denom(10000, 9), f.denom(2000, 1), f.denom(500, 1)],
    )

    assert open_position["total_minor_units"] == 82500
    assert open_position["usd_equivalent_cents"] == 89674
    calm = fx.read_branch(api, open_branch["id"])
    a.assert_vault_state(calm, 89674, 8967, "OPEN")
    assert calm["repatriation_pending"] is False

    assert edge_position["total_minor_units"] == 92000
    assert edge_position["usd_equivalent_cents"] == 100000
    edge = fx.read_branch(api, edge_branch["id"])
    a.assert_vault_state(edge, 100000, 10000, "RESTRICTED")
    assert edge["posture"] != "FROZEN"
    assert edge["repatriation_pending"] is True

    assert frozen_position["total_minor_units"] == 92500
    assert frozen_position["usd_equivalent_cents"] == 100543
    frozen = fx.read_branch(api, frozen_branch["id"])
    a.assert_vault_state(frozen, 100543, 10054, "FROZEN")
    assert frozen["repatriation_pending"] is True

    auto_rows, auto_meta = validate_paginated(
        api.list_cash_shipments(treasury_headers, {"auto_generated": True})
    )
    assert auto_meta["total_count"] == 2
    for row in auto_rows:
        assert row["status"] == "REQUESTED"
        assert row["direction"] == "REPATRIATION"
        assert row["auto_generated"] is True
        assert row["branch_id"] != open_branch["id"]

    edge_auto = [r for r in auto_rows if r["branch_id"] == edge_branch["id"]][0]
    assert [
        (e["denomination_minor_units"], e["note_count"])
        for e in edge_auto["manifest_denominations"]
    ] == [(2000, 1), (10000, 1)]
    assert edge_auto["manifest_minor_units"] == 12000
    assert edge_auto["manifest_usd_equivalent_cents"] == 13043

    frozen_auto = [r for r in auto_rows if r["branch_id"] == frozen_branch["id"]][0]
    assert [
        (e["denomination_minor_units"], e["note_count"])
        for e in frozen_auto["manifest_denominations"]
    ] == [(500, 1), (2000, 1), (10000, 1)]
    assert frozen_auto["manifest_minor_units"] == 12500
    assert frozen_auto["manifest_usd_equivalent_cents"] == 13587


def test_only_settled_rows_feed_the_surveillance_aggregates(
    api, teller_headers, teller2_headers, manager_headers
):
    """Two settlements of 11382 put the rolling total at 22764; a third deal voided
    from QUOTED contributes nothing at all; and reversing one settlement subtracts it
    again, leaving 11382 with the branch count still at 1 and the tier still NORMAL.

    Design: Corner/calculations/structuring_aggregates_exclude_voided_and_reversed_rows
    """
    world = fx.trading_world(api, position_mix=[f.denom(10000, 20)], identified=False)
    deals = [
        fx.quote_deal(
            api, world, "SELL_FX_TO_CUSTOMER", [f.denom(10000, 1)], teller_headers
        )
        for _ in range(3)
    ]
    for deal in deals[:2]:
        a.assert_quote_money(deal, 10000, 878600, 11382, 400, 11782)
        fx.authorize_deal(api, deal["id"], teller_headers)
        fx.settle_deal(api, deal["id"], teller2_headers)

    validate_success(
        api.void_transaction(
            deals[2]["id"], f.void_payload("customer left"), teller_headers
        )
    )
    after_void = fx.read_customer(api, world["customer"]["id"])
    assert after_void["rolling_30d_settled_usd_cents"] == 22764

    fx.reverse_deal(
        api, deals[1]["id"], manager_headers, "wrong denomination handed over"
    )

    after_reverse = fx.read_customer(api, world["customer"]["id"])
    a.assert_customer(after_reverse)
    assert after_reverse["rolling_30d_settled_usd_cents"] == 11382
    assert after_reverse["calendar_month_settled_usd_cents"] == 11382
    assert after_reverse["near_threshold_txn_count"] == 0
    assert after_reverse["distinct_branch_count"] == 1
    assert after_reverse["structuring_risk_score"] == 0
    assert after_reverse["structuring_risk_tier"] == "NORMAL"

    position = fx.read_position(api, world["position"]["id"])
    a.assert_mix_counts(position, 10000, available=19)


def test_each_risk_component_is_capped_and_the_dispersion_term_clamped(
    api, teller_headers, teller2_headers, compliance_headers
):
    """One 910539-cent settlement scores 47 (36 volume, 11 frequency, 0 dispersion);
    the second lifts the raw volume term to 72 but the cap holds it at 40 for a total
    of exactly 62, still ELEVATED and still unreported; and a customer with no
    settlements at all scores 0 rather than a negative dispersion term.

    Design: Corner/calculations/risk_components_capped_and_dispersion_clamped
    """
    world = fx.trading_world(
        api,
        vault_limit_usd_cents=100_000_000,
        position_mix=[f.denom(10000, 200)],
        customer_overrides={"id_document_expiry": "2030-01-01T00:00:00Z"},
    )
    assert world["position"]["usd_equivalent_cents"] == 2173913
    a.assert_vault_state(world["branch"], 2173913, 217, "OPEN")
    quiet = fx.onboard_customer(
        api, full_name="Ana Diaz", nationality_code="ES", home_branch_id=world["branch"]["id"]
    )

    first = fx.settled_deal(
        api,
        world,
        "SELL_FX_TO_CUSTOMER",
        [f.denom(10000, 80)],
        teller_headers,
        settle_headers=teller2_headers,
    )
    a.assert_settlement_money(first, 910539, 13658, 924197)

    after_one = fx.read_customer(api, world["customer"]["id"])
    assert after_one["structuring_risk_score"] == 47
    assert after_one["structuring_risk_tier"] == "ELEVATED"

    second = fx.settled_deal(
        api,
        world,
        "SELL_FX_TO_CUSTOMER",
        [f.denom(10000, 80)],
        teller_headers,
        settle_headers=teller2_headers,
    )
    a.assert_settlement_money(second, 910539, 13658, 924197)

    scored = fx.read_customer(api, world["customer"]["id"])
    assert scored["structuring_risk_score"] == 62
    assert scored["structuring_risk_tier"] == "ELEVATED"
    assert scored["near_threshold_txn_count"] == 2
    assert scored["distinct_branch_count"] == 1
    assert scored["compliance_hold_active"] is False

    _, reports_meta = validate_paginated(
        api.list_compliance_reports(compliance_headers)
    )
    assert reports_meta["total_count"] == 0

    assert fx.read_customer(api, quiet["id"])["structuring_risk_score"] == 0


def test_the_rate_lock_sweep_fires_on_strict_inequality(
    api, teller_headers, teller2_headers
):
    """A lock issued at the clock's start instant expires exactly 31 days later, and
    the sweep needs the expiry to lie strictly before the new clock: at 2026-09-01
    itself nothing expires and the 20606-cent liability stands, one second later the
    contract is EXPIRED with a zero liability while its remaining notional is kept.

    Design: Corner/calculations/buyback_rate_lock_expiry_boundary_on_clock_sweep
    """
    world = fx.trading_world(api, position_mix=[f.denom(10000, 20)], identified=False)
    txn = fx.settled_deal(
        api,
        world,
        "SELL_FX_TO_CUSTOMER",
        [f.denom(10000, 2)],
        teller_headers,
        settle_headers=teller2_headers,
    )
    assert txn["settled_usd_gross_cents"] == 22763

    contract = fx.issue_contract(api, world["customer"]["id"], txn["id"])

    a.assert_buyback_contract(contract)
    assert contract["status"] == "ISSUED"
    assert contract["locked_buy_rate_micros"] == 970600
    assert contract["locked_fx_minor_units"] == 20000
    assert contract["fee_usd_cents"] == 683
    assert contract["liability_usd_cents"] == 20606
    a.assert_timestamp_equals(contract["rate_lock_expires_at"], "2026-09-01T00:00:00Z")
    assert (
        fx.read_branch(api, world["branch"]["id"])["buyback_liability_usd_cents"] == 20606
    )

    at_edge = fx.set_clock(api, "2026-09-01T00:00:00Z")
    assert at_edge["expired_contract_count"] == 0
    unexpired = fx.read_contract(api, contract["id"])
    assert unexpired["status"] == "ISSUED"
    assert unexpired["liability_usd_cents"] == 20606

    past_edge = fx.set_clock(api, "2026-09-01T00:00:01Z")
    assert past_edge["expired_contract_count"] == 1

    expired = fx.read_contract(api, contract["id"])
    assert expired["status"] == "EXPIRED"
    assert expired["liability_usd_cents"] == 0
    assert expired["remaining_fx_minor_units"] == 20000
    assert fx.read_branch(api, world["branch"]["id"])["buyback_liability_usd_cents"] == 0
