"""Per-entry rounding of the handling share, and the gross-keyed fee band."""

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_money,
    assert_pct_equals,
    entries_of_type,
    sole_entry_of_type,
)
from test_helpers.constants import (
    DISPOSITION_LIQUIDATE,
    ENTRY_RECOVERY_CREDIT,
    GRADE_C,
    REASON_DEFECTIVE,
)


def _three_line_liquidation_world(api, client_code):
    """Three graded-C lines of one SKU in a single carton, all routed to auction."""
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs(client_code, name="Rounding Client"),
        items=[fx.widget_item_kwargs()],
        lines=[
            {"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE},
            {"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE},
            {"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE},
        ],
        condition_grade=GRADE_C,
    )
    world["channel"] = fx.make_channel(api, **fx.auction_channel_kwargs("AUC1"))
    orders = []
    for line in world["lines"]:
        order = fx.propose_order(
            api,
            line["id"],
            channel_id=world["channel"]["id"],
            disposition=DISPOSITION_LIQUIDATE,
            quantity=1,
        )
        fx.approve_order(api, order["id"])
        orders.append(order)
    world["orders"] = orders
    return world


def test_three_recovery_credits_are_rounded_per_entry_then_summed(api):
    """PRD §2.5: "To make the third point concrete: three recovery credits with
    net recoveries of 1333, 2777 and 4111 cents contribute 7605 cents in total
    under the pinned per-entry order, and 7604 cents under the forbidden
    sum-then-round order."

    Design: Difficulty/combinatorial_formula/client_settlement_rounding_per_entry_then_sum
    """
    world = _three_line_liquidation_world(api, "CLROUND")
    prices = [1626, 3387, 5013]
    expected_nets = [1333, 2777, 4111]
    for order, price, net in zip(world["orders"], prices, expected_nets):
        executed = fx.execute_order(
            api, order["id"], realized_unit_price_cents=price
        )
        assert_money(executed["gross_lot_value_cents"], price, "gross_lot_value_cents")
        assert_pct_equals(executed["effective_fee_pct"], 0.18, "effective_fee_pct")
        assert_money(executed["net_recovery_cents"], net, "net_recovery_cents")

    credits = entries_of_type(
        fx.list_ledger(api, world["client"]["id"]), ENTRY_RECOVERY_CREDIT
    )
    assert len(credits) == 3, f"expected three recovery credits, got {len(credits)}"
    assert [c["amount_cents"] for c in credits] == [1233, 2569, 3803]

    client = fx.read_client(api, world["client"]["id"])
    assert_money(client["settlement_balance_cents"], 7605, "settlement_balance_cents")
    assert client["settlement_balance_cents"] != 7604


def test_audit_recovery_credit_total_matches_the_per_entry_sum(api):
    """PRD §3.8: "A client's `settlement_balance_cents` is the sum of
    `amount_cents` across **all** of that client's entries regardless of type,
    traversed in `sequence_no` ascending order; nothing is ever filtered out,
    because the ledger is append-only."

    Design: Difficulty/combinatorial_formula/client_settlement_rounding_per_entry_then_sum
    """
    world = _three_line_liquidation_world(api, "CLROUND2")
    for order, price in zip(world["orders"], [1626, 3387, 5013]):
        fx.execute_order(api, order["id"], realized_unit_price_cents=price)

    report = fx.read_audit(api, world["client"]["id"])
    assert_money(report["recovery_credit_cents"], 7605, "recovery_credit_cents")
    assert_money(report["settlement_balance_cents"], 7605, "settlement_balance_cents")
    assert report["money_conservation_ok"] is True

    ledger = fx.list_ledger(api, world["client"]["id"])
    assert [e["sequence_no"] for e in ledger] == [1, 2, 3]


def _band_world(api, client_code):
    """One graded-C line with an approved auction order frozen at 7200 a unit."""
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs(client_code, name="Band Client"),
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
    )
    world["channel"] = fx.make_channel(api, **fx.auction_channel_kwargs("AUC1"))
    order = fx.propose_order(
        api,
        world["line"]["id"],
        channel_id=world["channel"]["id"],
        disposition=DISPOSITION_LIQUIDATE,
        quantity=1,
    )
    world["order"] = fx.approve_order(api, order["id"])
    return world


def test_gross_lot_of_exactly_25000_is_a_mid_lot_with_no_surcharge(api):
    """PRD §3.6: "Both band boundaries are inclusive on their lower edge, so
    exactly 25000 is a mid lot and exactly 100000 is a large lot."

    Design: Difficulty/combinatorial_formula/disposition_fee_band_keyed_on_gross_not_net
    """
    world = _band_world(api, "CLBAND")
    executed = fx.execute_order(
        api, world["order"]["id"], realized_unit_price_cents=25000
    )
    assert_money(executed["gross_lot_value_cents"], 25000, "gross_lot_value_cents")
    assert_pct_equals(executed["effective_fee_pct"], 0.12, "effective_fee_pct")
    assert_money(executed["channel_fee_cents"], 3000, "channel_fee_cents")
    assert_money(executed["net_recovery_cents"], 22000, "net_recovery_cents")


def test_fee_band_is_keyed_on_gross_so_the_net_keyed_answer_never_appears(api):
    """PRD §3.6: "a commission surcharge band is selected from the gross lot
    value computed in step one — and explicitly not from the net figure, which
    would be circular: a gross lot below 25000 cents is a small lot carrying a
    surcharge of plus 0.06, a gross lot from 25000 cents up to but excluding
    100000 cents is a mid lot carrying no surcharge, and a gross lot of 100000
    cents or more is a large lot carrying a discount of minus 0.04."

    Design: Difficulty/combinatorial_formula/disposition_fee_band_keyed_on_gross_not_net
    """
    world = _band_world(api, "CLBAND2")
    executed = fx.execute_order(
        api, world["order"]["id"], realized_unit_price_cents=25000
    )
    # A band keyed on the net figure would have charged 0.18 and 4500 cents.
    assert executed["channel_fee_cents"] != 4500
    assert executed["net_recovery_cents"] != 20500

    line = fx.read_return_line(api, world["line"]["id"])
    assert_money(line["recovery_value_cents"], 22000, "final recovery")

    credit = sole_entry_of_type(
        fx.list_ledger(api, world["client"]["id"]), ENTRY_RECOVERY_CREDIT
    )
    assert_money(credit["amount_cents"], 20350, "RECOVERY_CREDIT amount_cents")
    client = fx.read_client(api, world["client"]["id"])
    assert_money(client["settlement_balance_cents"], 20350, "settlement_balance_cents")
