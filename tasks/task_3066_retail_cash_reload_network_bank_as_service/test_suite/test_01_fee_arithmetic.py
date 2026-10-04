"""Convenience-fee arithmetic: the marginal tier walk and its rounding.

Covers the fee-computation claims of PRD §3.4.
"""
import pytest

from test_helpers import (
    validate_success, get_success_data, validate_error, ApiErrorId,
    setup_network, create_load, create_load_raw, assert_load_fee_identity,
)


def test_convenience_fee_first_band_is_flat_at_1500_and_2000():
    """PRD §3.4: "The first band runs from 0 to 2000 cents and is flat: any load
    whose principal exceeds 0 pays a flat 199 cents, so a 1500-cent load and a
    2000-cent load pay the same opening fee."

    Design: Difficulty/combinatorial_formula/convenience_fee_marginal_tier_walk
    """
    net = setup_network()
    load_1500 = create_load(net["location"], net["account"], net["agreement"],
                            principal_cents=1500)
    load_2000 = create_load(net["location"], net["account"], net["agreement"],
                            principal_cents=2000)
    assert load_1500["convenience_fee_cents"] == pytest.approx(199.00, abs=0.01)
    assert load_2000["convenience_fee_cents"] == pytest.approx(199.00, abs=0.01)


def test_convenience_fee_second_band_is_proportional_not_flat():
    """PRD §3.4: "The second band runs from 2000 to 10000 cents and its 249-cent
    rate is proportional rather than flat: the fee adds 249 cents multiplied by
    the fraction of that band the principal actually covers, where the band spans
    8000 cents, so the covered span is the principal minus 2000 capped at 10000."
    PRD §3.4: "A flat reading of the second band, in which any principal above 2000
    simply pays 249 flat, is a misreading; the proportional walk is authoritative."

    Design: Difficulty/combinatorial_formula/convenience_fee_marginal_tier_walk
    """
    net = setup_network()
    load_3000 = create_load(net["location"], net["account"], net["agreement"],
                            principal_cents=3000)
    # 199 flat + 249 * 1000/8000 = 230.125 -> 230.13 (a flat read would give 448.00)
    assert load_3000["convenience_fee_cents"] == pytest.approx(230.13, abs=0.01)
    assert_load_fee_identity(load_3000)


def test_convenience_fee_third_band_adds_flat_399_above_10000():
    """PRD §3.4: "The third band opens above 10000 cents and contributes a flat
    399 cents whenever the principal exceeds 10000. Bands the principal never
    reaches contribute nothing".
    PRD §3.4: "the whole running fee is rounded half-up to two decimal places
    exactly once, at the end of the walk."

    Design: Difficulty/combinatorial_formula/convenience_fee_marginal_tier_walk
    """
    net = setup_network()
    load = create_load(net["location"], net["account"], net["agreement"],
                       principal_cents=10001)
    # 199 + 249 + 399 == 847.00
    assert load["convenience_fee_cents"] == pytest.approx(847.00, abs=0.01)
    assert load["posted_total_cents"] == pytest.approx(10001 + 847.00, abs=0.01)
    assert_load_fee_identity(load)


def test_convenience_fee_rounds_half_up_not_truncated():
    """PRD §3.4: "the whole running fee is rounded half-up to two decimal places
    exactly once, at the end of the walk."
    PRD §2.6: "Computed monetary and score values that are not integral are rounded
    to exactly 2 decimal places using the round-half-up rule".

    Design: Corner/calculations/convenience_fee_rounds_half_up_at_two_decimals
    """
    net = setup_network()
    load = create_load(net["location"], net["account"], net["agreement"],
                       principal_cents=3500)
    # 199 + 249 * 1500 / 8000 = 245.6875 -> 245.69 half-up (truncation gives 245.68)
    assert load["convenience_fee_cents"] == pytest.approx(245.69, abs=0.001)
    assert_load_fee_identity(load)
    assert load["posted_total_cents"] == pytest.approx(3500 + 245.69, abs=0.01)


def test_convenience_fee_retailer_and_program_shares_sum_to_the_fee():
    """PRD §3.4: "The retailer's cut is `retailer_fee_share_cents`, a
    per-transaction rounded share of the convenience fee, and the remainder is
    `program_fee_share_cents`, computed as the fee minus the retailer's share."

    Design: Difficulty/combinatorial_formula/convenience_fee_marginal_tier_walk
    """
    net = setup_network()
    load = create_load(net["location"], net["account"], net["agreement"],
                       principal_cents=3500)
    assert load["retailer_fee_share_cents"] == pytest.approx(85.99, abs=0.01)
    assert load["program_fee_share_cents"] == pytest.approx(159.70, abs=0.01)
    assert (load["retailer_fee_share_cents"] + load["program_fee_share_cents"]
            == pytest.approx(load["convenience_fee_cents"], abs=0.01))