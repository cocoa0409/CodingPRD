"""Dealer cash movements and the compensating release/reversal pair."""
import pytest

from test_helpers import (
    api_client,
    set_logical_clock,
    setup_funded_package_contract,
    validate_success,
    TEST_USERS,
)

_ANALYST = TEST_USERS["funding_analyst_headers"]


def _funded_dealer_with_reserve():
    """Dealer D1 with a funded PREMIUM child, so the reserve holds its holdback."""
    set_logical_clock("2026-09-01T00:00:00Z")
    dealer, package, contract = setup_funded_package_contract(
        dealer_code="D1", holdback_rate=0.10, quality_tier="TIER_1",
        package_reference="PKG-P3", equipment_config_code="PREMIUM",
        contract_term_months=60, customer_email="cleo.chargeback@example.com")
    dealer = validate_success(api_client.get_dealer(dealer["id"], _ANALYST), 200)
    # PREMIUM capex 24900, holdback_rate 0.10 -> reserve 2490.
    assert dealer["holdback_reserve_cents"] == 2490
    return dealer


# ─── Difficulty: compensating_invariant / dealer_holdback_release_reversal_conserves_account_total ───

def test_holdback_release_moves_cents_into_the_due_balance(api):
    """PRD §3.1: "A holdback release moves the smaller of the requested `amount_cents` and the current reserve out of `holdback_reserve_cents` and into `chargeback_balance_due_cents`"

    Design: Difficulty/compensating_invariant/dealer_holdback_release_reversal_conserves_account_total
    """
    dealer = _funded_dealer_with_reserve()
    before_total = dealer["holdback_reserve_cents"] + dealer["chargeback_balance_due_cents"]

    released = validate_success(api_client.release_holdback(
        dealer["id"], {"amount_cents": 500}, _ANALYST), 200)

    assert released["holdback_reserve_cents"] == dealer["holdback_reserve_cents"] - 500
    assert released["chargeback_balance_due_cents"] == dealer["chargeback_balance_due_cents"] + 500
    assert (released["holdback_reserve_cents"]
            + released["chargeback_balance_due_cents"]) == before_total


def test_holdback_reversal_restores_the_pre_release_position_exactly(api):
    """PRD §3.1: "a holdback reversal moves the smaller of the requested `amount_cents` and the current balance back out of `chargeback_balance_due_cents` and into `holdback_reserve_cents`. Both movements re-derive standing afterwards"

    Design: Difficulty/compensating_invariant/dealer_holdback_release_reversal_conserves_account_total
    """
    dealer = _funded_dealer_with_reserve()
    before_total = dealer["holdback_reserve_cents"] + dealer["chargeback_balance_due_cents"]

    api_client.release_holdback(dealer["id"], {"amount_cents": 500}, _ANALYST)
    restored = validate_success(api_client.reverse_holdback(
        dealer["id"], {"amount_cents": 500}, _ANALYST), 200)

    assert restored["holdback_reserve_cents"] == dealer["holdback_reserve_cents"]
    assert restored["chargeback_balance_due_cents"] == dealer["chargeback_balance_due_cents"]
    # The conserved quantity is unchanged by the forward-plus-compensating pair.
    assert (restored["holdback_reserve_cents"]
            + restored["chargeback_balance_due_cents"]) == before_total