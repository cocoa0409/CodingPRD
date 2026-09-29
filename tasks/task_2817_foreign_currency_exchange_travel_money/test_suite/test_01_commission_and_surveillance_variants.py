"""Two calculations that each exist in two variants over the same inputs.

The first pair is transaction money: PRD 3.5 tiers the quote commission on "this
deal's own quoted_usd_gross_cents and nothing at all about the customer", while
settlement tiers it on "this deal's settled_usd_gross_cents plus the sum of
settled_usd_gross_cents over the same customer's other transactions that have
settlement_status SETTLED, the same branch_id, and a settled_at falling on the
same UTC calendar day".

The second pair is compliance: PRD 3.6 maintains a rolling 30-day window and a
calendar-month window "computed from exactly the same population", and the
STRUCTURING_SUSPICION report cites the calendar-month figure.
"""

from test_helpers import (
    ApiErrorId,
    assertions as a,
    factories as f,
    fixtures as fx,
    validate_paginated,
    validate_success,
)

MIX = [f.denom(2000, 10), f.denom(5000, 10), f.denom(10000, 20)]
SMALL_DEAL = [f.denom(10000, 1), f.denom(5000, 1), f.denom(2000, 2)]
EUR_SELL_RATE_MICROS = 878600


def test_settlement_commission_tiers_on_the_same_day_same_branch_basis(
    api, teller_headers
):
    """A 21626-cent sale carries 757 cents of commission at quote time, where the
    tier basis is its own gross, and 400 cents at settlement, where the basis also
    counts the customer's earlier 91054-cent settlement at this branch today and
    lands in the 150-bps band before the 400-cent floor lifts it.

    Design: Difficulty/dual_variant_calc/transaction_commission_provisional_vs_settlement_final_tier_basis
    """
    world = fx.trading_world(api, vault_limit_usd_cents=20_000_000, position_mix=MIX)

    earlier = fx.settled_deal(api, world, denominations=[f.denom(10000, 8)])
    assert earlier["settled_usd_gross_cents"] == 91054

    quote = validate_success(
        api.create_exchange_transaction(
            f.create_exchange_transaction_payload(
                world["branch"]["id"],
                world["customer"]["id"],
                world["card"]["id"],
                requested_denominations=SMALL_DEAL,
            ),
            teller_headers,
        ),
        201,
    )
    a.assert_exchange_transaction(quote)
    a.assert_quote_money(quote, 19000, EUR_SELL_RATE_MICROS, 21626, 757, 22383)

    fx.authorize_deal(api, quote["id"], teller_headers)
    settled = validate_success(api.settle_transaction(quote["id"], teller_headers))

    a.assert_settlement_money(settled, 21626, 400, 22026, price_adjustment_cents=-357)
    assert settled["settlement_status"] == "SETTLED"


def test_quote_commission_ignores_the_customers_settlement_history(api, teller_headers):
    """The provisional variant consults nothing about the customer: the same
    21626-cent gross is charged 350 bps of its own gross even though the customer
    has already settled 91054 cents at this branch today, and the earlier deal -
    whose own basis was its own gross - shows a zero price adjustment.

    Design: Difficulty/dual_variant_calc/transaction_commission_provisional_vs_settlement_final_tier_basis
    """
    world = fx.trading_world(api, vault_limit_usd_cents=20_000_000, position_mix=MIX)

    earlier = fx.settled_deal(api, world, denominations=[f.denom(10000, 8)])
    a.assert_settlement_money(earlier, 91054, 2276, 93330, price_adjustment_cents=0)

    quote = fx.quote_deal(api, world, denominations=SMALL_DEAL, headers=teller_headers)
    assert quote["quoted_commission_cents"] == 757, (
        "the quote-time tier basis is the deal's own 21626-cent gross, which sits "
        "below the 25000-cent edge and therefore attracts 350 bps"
    )
    assert quote["quoted_total_charge_cents"] == 22383
    assert quote["price_adjustment_cents"] is None or quote["settled_commission_cents"] is None


def _two_branch_customer_world(api):
    """Two branches trading EUR off one wholesale mid, each with 100 x 10000 notes,
    and one customer carrying an unexpired passport."""
    north = fx.register_branch(
        api, code="BR-CDG", name="Paris CDG", region_code="NORTH",
        vault_limit_usd_cents=20_000_000,
    )
    south = fx.register_branch(api, vault_limit_usd_cents=20_000_000)
    fx.register_currency(api)
    wholesale = fx.record_wholesale_rate(api)
    south_card = fx.published_rate_card(api, south["id"], wholesale["id"])
    north_card = fx.published_rate_card(api, north["id"], wholesale["id"])
    fx.open_position(api, south["id"], "EUR", [f.denom(10000, 100)])
    fx.open_position(api, north["id"], "EUR", [f.denom(10000, 100)])
    customer = fx.identified_customer(
        api, id_document_number="SE-882311", id_document_expiry="2027-01-01T00:00:00Z"
    )
    return {
        "south": {"branch": south, "card": south_card},
        "north": {"branch": north, "card": north_card},
        "customer": customer,
    }


def _sell_80_notes(api, world, side, teller_headers, manager_headers):
    """Quote, authorize and settle an 80 x 10000 EUR sale under dual control."""
    txn = validate_success(
        api.create_exchange_transaction(
            f.create_exchange_transaction_payload(
                world[side]["branch"]["id"],
                world["customer"]["id"],
                world[side]["card"]["id"],
                requested_denominations=[f.denom(10000, 80)],
            ),
            teller_headers,
        ),
        201,
    )
    validate_success(api.authorize_transaction(txn["id"], teller_headers))
    return validate_success(api.settle_transaction(txn["id"], manager_headers))


def test_rolling_window_and_calendar_month_window_diverge_over_one_month_boundary(
    api, teller_headers, manager_headers, compliance_headers
):
    """Two identical 910539-cent settlements five days apart, one on 2026-07-28 and
    one on 2026-08-02, leave rolling_30d_settled_usd_cents at 1821078 while
    calendar_month_settled_usd_cents holds only the August figure of 910539, and the
    rolling window's three outputs alone drive the score to 74 and the tier to HIGH.

    Design: Difficulty/dual_variant_calc/customer_structuring_rolling_30d_vs_calendar_month_across_month_boundary
    """
    world = _two_branch_customer_world(api)
    customer_id = world["customer"]["id"]

    fx.set_clock(api, "2026-07-28T10:00:00Z")
    first = _sell_80_notes(api, world, "south", teller_headers, manager_headers)
    assert first["settled_usd_gross_cents"] == 910539

    fx.set_clock(api, "2026-08-02T10:00:00Z")
    _sell_80_notes(api, world, "north", teller_headers, manager_headers)

    customer = fx.read_customer(api, customer_id, compliance_headers)
    a.assert_customer(customer)
    assert customer["rolling_30d_settled_usd_cents"] == 1821078
    assert customer["calendar_month_settled_usd_cents"] == 910539, (
        "the July settlement is inside the 30-day window but outside the August "
        "calendar month, so the two variants must not agree"
    )
    assert customer["near_threshold_txn_count"] == 2
    assert customer["distinct_branch_count"] == 2
    assert customer["structuring_risk_score"] == 74
    assert customer["structuring_risk_tier"] == "HIGH"
    assert customer["compliance_hold_active"] is True


def test_structuring_report_cites_the_calendar_month_variant(
    api, teller_headers, manager_headers, compliance_headers
):
    """The STRUCTURING_SUSPICION report raised by the second settlement carries
    aggregate_usd_cents 910539 - the calendar-month figure, not the 1821078 rolling
    figure - over the window that opens at the first instant of the UTC month and
    closes at the triggering instant; neither 910539-cent gross reaches the
    1,000,000-cent reporting threshold, so no THRESHOLD_REPORT exists.

    Design: Difficulty/dual_variant_calc/customer_structuring_rolling_30d_vs_calendar_month_across_month_boundary
    """
    world = _two_branch_customer_world(api)
    customer_id = world["customer"]["id"]

    fx.set_clock(api, "2026-07-28T10:00:00Z")
    _sell_80_notes(api, world, "south", teller_headers, manager_headers)
    fx.set_clock(api, "2026-08-02T10:00:00Z")
    second = _sell_80_notes(api, world, "north", teller_headers, manager_headers)

    rows, meta = validate_paginated(
        api.list_compliance_reports(
            compliance_headers,
            {"customer_id": customer_id, "report_type": "STRUCTURING_SUSPICION"},
        )
    )
    assert meta["total_count"] == 1
    report = rows[0]
    a.assert_compliance_report(report)
    assert report["report_type"] == "STRUCTURING_SUSPICION"
    assert report["aggregate_usd_cents"] == 910539
    a.assert_timestamp_equals(report["window_start"], "2026-08-01T00:00:00Z")
    a.assert_timestamp_equals(report["window_end"], "2026-08-02T10:00:00Z")
    assert report["transaction_count"] == 1
    assert report["status"] == "DRAFT"
    assert report["triggering_transaction_id"] == second["id"]

    _, threshold_meta = validate_paginated(
        api.list_compliance_reports(
            compliance_headers,
            {"customer_id": customer_id, "report_type": "THRESHOLD_REPORT"},
        )
    )
    assert threshold_meta["total_count"] == 0
    assert ApiErrorId.ERR_REPORT_NOT_FOUND == "ERR_REPORT_NOT_FOUND"
