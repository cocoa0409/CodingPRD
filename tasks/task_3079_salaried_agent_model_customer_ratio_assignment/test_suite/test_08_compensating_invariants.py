"""Difficulty tests — compensating-action invariants (queue A, rule `compensating_invariant`).

Each instance re-derives a quantity after a compensating move and checks that the
conserved total is unchanged to the cent / to the credited count.
"""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    PLATFORM_ADMIN,
    OPERATIONS_COORDINATOR,
    TRANSACTION_COORDINATOR,
    create_region,
    create_lead_agent,
    create_client,
    assign_client,
    open_transaction,
    advance_to_review,
    close_transaction,
    create_referral,
    reconcile_referral,
    assert_referral_split_conserves,
    set_clock,
)


@pytest.fixture(autouse=True)
def _clock():
    set_clock()


def test_referral_fee_is_rederived_without_drifting_on_a_late_price():
    """PRD §2.10: "the basis is the larger of the client's contract price and 1, so a referral that is reconciled before any price is recorded still produces a definable, non-negative fee rather than an error from a zero basis".
    PRD §3.8: "the fee is the basis multiplied by `referral_fee_bps` and divided by 10,000, rounded half-up to whole cents, and it is split by rounding the partner's share half-up to whole cents and defining the retained side as what is left".

    Design: Difficulty/compensating_invariant/referral_partner_and_house_split_conserves_contract_price_basis
    """
    region = create_region(target_client_ratio=2.0)
    create_lead_agent(region["id"])
    overflow = create_client(full_name="Omar Overflow", service_area_code="98101")
    referral = create_referral(overflow["id"], region["id"], referral_fee_bps=1500,
                               split_policy="SPLIT_50_PARTNER")

    first = reconcile_referral(referral["id"], 99_999)
    # 99999 * 1500 / 10000 = 14999.85 -> 15000 halves up
    assert first["referral_fee_cents"] == 15_000, first
    assert first["partner_cents"] + first["house_cents"] == 15_000, first

    second = reconcile_referral(referral["id"], 100_001)
    # 100001 * 1500 / 10000 = 15000.15 -> 15000
    assert second["referral_fee_cents"] == 15_000, second
    assert second["partner_cents"] + second["house_cents"] == 15_000, second


def test_referral_conservation_survives_a_compensating_rederivation():
    """PRD §2.10: "the partner's side plus the retained side equals the computed fee to the cent, with the retained side defined as the fee minus the partner's side so the equality holds by construction."

    Design: Difficulty/compensating_invariant/referral_partner_and_house_split_conserves_contract_price_basis
    """
    region = create_region(target_client_ratio=2.0)
    create_lead_agent(region["id"])
    overflow = create_client(full_name="Omar Overflow", service_area_code="98101")
    referral = create_referral(overflow["id"], region["id"], referral_fee_bps=1500,
                               split_policy="SPLIT_50_PARTNER")

    reconcile_referral(referral["id"], 99_999)
    reconcile_referral(referral["id"], 100_001)

    final = get_success_data(api_client.get_referral(referral["id"], PLATFORM_ADMIN))
    assert_referral_split_conserves(final)
    assert final["settlement_status"] == "COMPUTED", final


def test_reopened_client_transaction_carries_the_decayed_satisfaction_credit():
    """PRD §3.10: "`agent_satisfaction_credit` from the client's most recent transaction whose `coordination_status` is `CLOSED`, ordered by `closed_at` descending and then `created_at` descending".
    PRD §3.10: "If the prior transaction closed at least 180 days before the current instant — the boundary is inside the eligible side, so exactly 180 days qualifies — the credit is 0.05".

    Design: Difficulty/compensating_invariant/transaction_close_reopen_preserves_agent_satisfaction_credit_ledger
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    client = create_client(full_name="Repeat Buyer", service_area_code="98101")
    assign_client(client["id"])

    tx1 = open_transaction(client["id"])
    advance_to_review(tx1["id"], 75_000_000)
    close_transaction(tx1["id"])

    # Move the clock to exactly 180 days after the close (2026-09-01 + 180 days).
    get_success_data(api_client.set_current_utc("2027-02-28T00:00:00Z", PLATFORM_ADMIN))

    tx2 = open_transaction(client["id"])
    assert tx2["agent_satisfaction_credit"] == pytest.approx(0.05, abs=1e-2), tx2


def test_reopen_leaves_the_closed_transaction_count_unchanged():
    """PRD §3.5: "Cancelling is the desk's alternative terminus, and it is reserved for transactions that never carried a price".
    PRD §3.4: "The `LeadCapacity` row is the per-agent instrument the selector reads".

    Design: Difficulty/compensating_invariant/transaction_close_reopen_preserves_agent_satisfaction_credit_ledger
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    client = create_client(full_name="Repeat Buyer", service_area_code="98101")
    assign_client(client["id"])

    tx1 = open_transaction(client["id"])
    advance_to_review(tx1["id"], 75_000_000)
    close_transaction(tx1["id"])
    agent_after_close = get_success_data(api_client.get_agent(lead["id"], PLATFORM_ADMIN))
    assert agent_after_close["close_rate"] == pytest.approx(1.0, abs=1e-4), agent_after_close

    get_success_data(api_client.set_current_utc("2027-03-05T00:00:00Z", PLATFORM_ADMIN))
    open_transaction(client["id"])

    agent_after_reopen = get_success_data(api_client.get_agent(lead["id"], PLATFORM_ADMIN))
    assert agent_after_reopen["close_rate"] == pytest.approx(1.0, abs=1e-4), agent_after_reopen
    reopened = get_success_data(api_client.get_client(client["id"], PLATFORM_ADMIN))
    assert reopened["status"] == "IN_TRANSACTION", reopened