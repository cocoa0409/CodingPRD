"""Settlement fee reconciliation: the two rounding orders are kept separate.

Covers the settlement arithmetic of PRD §3.8.
"""
import pytest

from test_helpers import (
    setup_network, create_settlement_batch, open_settlement_batch,
    settle_settlement_batch, settle_settlement_batch_ok,
    create_and_fund_load, get_agreement, assert_settlement_rounding_identity,
)


def _settled_batch(two_load_principals=(3500, 4500)):
    net = setup_network()
    fees = []
    for p in two_load_principals:
        load = create_and_fund_load(net["location"], net["account"],
                                     net["agreement"], principal_cents=p)
        fees.append(load["convenience_fee_cents"])
    batch = create_settlement_batch(net["agreement"])
    open_settlement_batch(batch["id"])
    settled = settle_settlement_batch_ok(batch["id"])
    return net, fees, settled


def test_settlement_accrual_and_payable_use_opposite_rounding_orders():
    """PRD §3.8: "The retailer's accrual `accrued_retailer_share_cents` is the sum,
    over the attached loads, of each load's `retailer_fee_share_cents` — and each
    of those is itself rounded to two decimal places per load, so the accrual is a
    round-then-sum figure. The amount actually payable, `net_fee_payable_cents`, is
    computed the other way: the batch's total convenience fee is summed first and
    then multiplied once by the agreement's `fee_split_retailer_pct`, and the
    product is rounded half-up to two decimal places — a sum-then-round figure."

    Design: Difficulty/combinatorial_formula/settlement_fee_rounding_order
    """
    net, fees, settled = _settled_batch()
    assert fees[0] == pytest.approx(245.69, abs=0.01)
    assert fees[1] == pytest.approx(276.81, abs=0.01)
    # round-then-sum: 85.99 + 96.88 = 182.87
    assert settled["accrued_retailer_share_cents"] == pytest.approx(182.87, abs=0.01)
    # sum-then-round: (245.69 + 276.81) * 0.35 = 182.875 -> 182.88
    assert settled["net_fee_payable_cents"] == pytest.approx(182.88, abs=0.01)


def test_settlement_delta_exposes_the_rounding_drift():
    """PRD §3.8: "The two orders genuinely differ, and `settlement_rounding_delta_cents`
    exists precisely to expose the difference: it is the accrual minus the payable,
    and it accumulates the per-load rounding drift into a single period-level figure."

    Design: Difficulty/combinatorial_formula/settlement_fee_rounding_order
    """
    net, fees, settled = _settled_batch()
    assert settled["settlement_rounding_delta_cents"] == pytest.approx(-0.01, abs=0.001)
    assert settled["settlement_rounding_delta_cents"] != 0
    assert_settlement_rounding_identity(settled)


def test_settlement_posts_the_accrual_schedule_not_the_payable():
    """PRD §3.8: "Settling also posts the accrual to the agreement:
    `settled_fee_total_cents` increases by `accrued_retailer_share_cents` and
    `accrual_pending_cents` decreases by the same amount."
    PRD §3.8: "Neither order may be collapsed into the other."

    Design: Difficulty/combinatorial_formula/settlement_fee_rounding_order
    """
    net, fees, settled = _settled_batch()
    agreement = get_agreement(net["agreement"]["id"])
    assert agreement["settled_fee_total_cents"] == pytest.approx(
        settled["accrued_retailer_share_cents"], abs=0.01)
    assert agreement["accrual_pending_cents"] == 0
    assert settled["gross_principal_cents"] == 8000


def test_accrual_at_funding_and_payable_at_settlement_disagree_by_one_cent():
    """PRD §3.8: "The two orders genuinely differ, and `settlement_rounding_delta_cents`
    exists precisely to expose the difference: it is the accrual minus the payable,
    and it accumulates the per-load rounding drift into a single period-level figure."

    Design: Difficulty/dual_variant_calc/fee_split_accrual_vs_settlement_payable
    """
    net = setup_network()
    for _ in range(2):
        create_and_fund_load(net["location"], net["account"], net["agreement"],
                             principal_cents=3500)
    # accrual accumulated at funding: 85.99 + 85.99 = 171.98
    assert get_agreement(net["agreement"]["id"])["accrual_pending_cents"] == pytest.approx(
        171.98, abs=0.01)
    batch = create_settlement_batch(net["agreement"])
    open_settlement_batch(batch["id"])
    settled = settle_settlement_batch_ok(batch["id"])
    assert settled["accrued_retailer_share_cents"] == pytest.approx(171.98, abs=0.01)
    assert settled["net_fee_payable_cents"] == pytest.approx(171.98, abs=0.01)


def test_settlement_moves_the_accrued_residue_into_the_settled_total():
    """PRD §3.8: "Settling also posts the accrual to the agreement:
    `settled_fee_total_cents` increases by `accrued_retailer_share_cents` and
    `accrual_pending_cents` decreases by the same amount."

    Design: Difficulty/dual_variant_calc/fee_split_accrual_vs_settlement_payable
    """
    net = setup_network()
    loads = [create_and_fund_load(net["location"], net["account"], net["agreement"],
                                  principal_cents=3500) for _ in range(3)]
    assert get_agreement(net["agreement"]["id"])["accrual_pending_cents"] == pytest.approx(
        257.97, abs=0.01)
    batch = create_settlement_batch(net["agreement"])
    open_settlement_batch(batch["id"])
    settled = settle_settlement_batch_ok(batch["id"])
    agreement = get_agreement(net["agreement"]["id"])
    assert settled["accrued_retailer_share_cents"] == pytest.approx(257.97, abs=0.01)
    assert settled["gross_principal_cents"] == 10500
    assert agreement["settled_fee_total_cents"] == pytest.approx(257.97, abs=0.01)
    assert agreement["accrual_pending_cents"] == 0