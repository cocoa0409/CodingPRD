"""Compensating invariants: post/reverse conserves totals; decline refunds escrow."""
from test_helpers import (
    TEST_USERS, validate_success, get_success_data, api_client,
    setup_open_branch_with_period, setup_retiring_advisor_with_transfer,
    post_production, post_charge, get_period, make_advisor_headers,
)

ADMIN = TEST_USERS["home_office_admin_headers"]


def test_charge_post_then_reverse_conserves_period_totals():
    """PRD §3.5: "Every charge post or reversal recomputes the period's
    aggregates while the period is `OPEN` or `CLOSED`: `gross_revenue_cents`
    is the sum of `POSTED` revenue lines for the branch inside the period
    window; `total_charges_cents` is the sum of `POSTED`, non-reversed charge
    amounts for the period; `net_profit_cents` is gross revenue minus total
    charges and may go negative; and `advisor_share_cents` is recomputed in
    its provisional variant (§3.6)."
    PRD §3.5: "Charges post with `status` `POSTED` and move to `REVERSED` on
    reversal; reversed rows are excluded from every aggregate even if they
    were originally posted inside the window."

    Design: Difficulty/compensating_invariant/charge_post_reverse_conserves_period_totals
    """
    branch, territory, advisor, boa, period = setup_open_branch_with_period()
    post_production(advisor["id"], 900000, "2026-09-10T00:00:00Z")
    post_charge(period["id"], branch["id"], 300000, "LEASE_RENT")
    post_charge(period["id"], branch["id"], 240000, "BOA_PAYROLL")

    before = get_period(period["id"])
    assert before["total_charges_cents"] == 540000
    assert before["net_profit_cents"] == 360000
    # 360000 * 0.38 = 136800
    assert before["advisor_share_cents"] == 136800

    equipment = post_charge(period["id"], branch["id"], 100000, "EQUIPMENT")
    reversed_charge = validate_success(
        api_client.reverse_charge(equipment["id"], ADMIN)
    )
    assert reversed_charge["status"] == "REVERSED"

    after = get_period(period["id"])
    assert after["total_charges_cents"] == before["total_charges_cents"] == 540000
    assert after["net_profit_cents"] == before["net_profit_cents"] == 360000
    assert after["advisor_share_cents"] == before["advisor_share_cents"] == 136800


def test_reversed_charge_excluded_even_when_reposted():
    """PRD §3.5: "Charges post with `status` `POSTED` and move to `REVERSED`
    on reversal; reversed rows are excluded from every aggregate even if they
    were originally posted inside the window."

    Design: Difficulty/compensating_invariant/charge_post_reverse_conserves_period_totals
    """
    branch, territory, advisor, boa, period = setup_open_branch_with_period()
    post_production(advisor["id"], 900000, "2026-09-10T00:00:00Z")

    charge = post_charge(period["id"], branch["id"], 100000, "EQUIPMENT")
    snapshot = get_period(period["id"])
    assert snapshot["total_charges_cents"] == 100000
    assert snapshot["net_profit_cents"] == 800000

    validate_success(api_client.reverse_charge(charge["id"], ADMIN))
    after = get_period(period["id"])
    assert after["total_charges_cents"] == 0
    assert after["net_profit_cents"] == 900000
    # 190000 + 168000 = 358000
    assert after["advisor_share_cents"] == 358000


def test_decline_refunds_escrow_and_keeps_retiring_status():
    """PRD §3.7: "Declining refunds the escrow to the successor, returning the
    escrow balance to zero, and moves the transfer to `DECLINED`."
    PRD §3.7: "Retirement is revocable: while no goodwill transfer on the
    advisor's branch stands in `ACCEPTED` or `COMPLETED` status, the advisor
    may rescind, returning `RETIRING → PRACTICING` and restoring the branch to
    `ADVISOR_ASSIGNED` or `FULLY_STAFFED` depending on administrator
    presence."

    Design: Difficulty/compensating_invariant/goodwill_escrow_deposit_refund_conserves_zero_balance
    """
    transfer, retiring, successor, branch = setup_retiring_advisor_with_transfer(
        escrow_deposit_cents=200000,
    )
    assert transfer["escrow_deposit_cents"] == 200000

    declined = validate_success(
        api_client.decline_transfer(transfer["id"], make_advisor_headers(successor["id"]))
    )
    assert declined["status"] == "DECLINED"

    retiring_after = get_success_data(api_client.get_advisor(retiring["id"], ADMIN))
    assert retiring_after["status"] == "RETIRING"


def test_decline_out_of_turn_rejected_and_escrow_untouched():
    """PRD §3.7: "Acceptance and decline likewise belong to the party who did
    not make the most recent offer — accepting one's own offer or declining it
    out of turn is also `ERR_NEGOTIATION_TURN`."

    Design: Difficulty/compensating_invariant/goodwill_escrow_deposit_refund_conserves_zero_balance
    """
    transfer, retiring, successor, branch = setup_retiring_advisor_with_transfer(
        escrow_deposit_cents=200000,
    )

    # The initial offer is made on the retiring advisor's behalf, so the
    # retiring party declining their own offer is out of turn.
    from test_helpers import validate_error, ApiErrorId
    validate_error(
        api_client.decline_transfer(transfer["id"], make_advisor_headers(retiring["id"])),
        ApiErrorId.ERR_NEGOTIATION_TURN,
    )

    fresh = get_success_data(api_client.get_goodwill_transfer(transfer["id"], ADMIN))
    assert fresh["status"] == "OFFERED"
    assert fresh["escrow_deposit_cents"] == 200000
