"""Dispute resolution and the compensating invariants around balances,
wallet credits, trailing GMV, and clawback lines."""

from test_helpers import (
    ApiErrorId,
    assert_balance_conservation,
    create_active_talent,
    create_confirmed_order,
    get_success_data,
    lines_for_order,
    make_admin_headers,
    make_buyer_headers,
    open_dispute,
    payout_lines_for_talent,
    read_buyer,
    read_order,
    read_talent,
    register_buyer,
    validate_error,
    validate_success,
)


def test_payout_completion_conserves_balances(api):
    """PRD §2.9: "When a payout completes, the amount that leaves
    `pending_balance_cents` is exactly the amount that enters
    `paid_out_balance_cents`."
    PRD §3.8: "Completion moves a `PROCESSING` payout to `PAID`, stamps
    `paid_at` with the current logical time, transitions every attached
    payout line from `UNSETTLED` to `SETTLED`, and performs the conserved
    balance shift: the talent's `pending_balance_cents` is debited by
    `total_cents` and `paid_out_balance_cents` is credited by exactly the
    same amount, so the sum of the two balances is invariant across the
    transition."

    Design: Difficulty/compensating_invariant/payout_balance_conservation
    """
    admin = make_admin_headers()
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    create_confirmed_order(api, talent, buyer)

    before = read_talent(api, talent["id"])
    assert before["pending_balance_cents"] == 7500
    assert before["paid_out_balance_cents"] == 0

    payout = api.payout_sweep(
        "2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z", headers=admin
    ).json()["data"][0]
    validate_success(api.initiate_payout(payout["id"], headers=admin))
    completed = validate_success(api.complete_payout(payout["id"], headers=admin))
    assert completed["status"] == "PAID"
    assert completed["total_cents"] == 7500

    after = read_talent(api, talent["id"])
    assert_balance_conservation(
        before["pending_balance_cents"],
        before["paid_out_balance_cents"],
        after["pending_balance_cents"],
        after["paid_out_balance_cents"],
    )
    assert after["pending_balance_cents"] == 0
    assert after["paid_out_balance_cents"] == 7500

    lines = api.list_payout_lines_of_payout(payout["id"], headers=admin).json()["data"]
    assert lines, "a completed payout must carry its swept lines"
    for line in lines:
        assert line["settlement_status"] == "SETTLED"


def test_initiate_does_not_shift_balances(api):
    """PRD §3.8: "Completion moves a `PROCESSING` payout to `PAID`, stamps
    `paid_at` with the current logical time, transitions every attached
    payout line from `UNSETTLED` to `SETTLED`, and performs the conserved
    balance shift: the talent's `pending_balance_cents` is debited by
    `total_cents` and `paid_out_balance_cents` is credited by exactly the
    same amount, so the sum of the two balances is invariant across the
    transition."
    PRD §3.8: "A scheduled payout cannot move until tax compliance is proven:
    initiation — which moves the payout from `SCHEDULED` to `PROCESSING` —
    requires the payout's talent to hold at least one `VERIFIED` tax
    document, and is otherwise rejected with `ERR_TAX_DOC_MISSING` (HTTP
    422)."

    Design: Difficulty/compensating_invariant/payout_balance_conservation
    """
    admin = make_admin_headers()
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    create_confirmed_order(api, talent, buyer)

    payout = api.payout_sweep(
        "2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z", headers=admin
    ).json()["data"][0]
    initiated = validate_success(api.initiate_payout(payout["id"], headers=admin))
    assert initiated["status"] == "PROCESSING"

    mid = read_talent(api, talent["id"])
    # The shift is promised on completion, not initiation.
    assert mid["pending_balance_cents"] == 7500
    assert mid["paid_out_balance_cents"] == 0


def test_full_refund_restores_wallet_pending_and_gmv(api):
    """PRD §3.6: "Under `FULL_REFUND`, the dispute resolves to
    `RESOLVED_REFUND` with `refund_to_buyer_cents` set to the order's full
    gross amount. The order transitions to `REFUNDED` with
    `refund_amount_cents` equal to the gross, the buyer's wallet is credited
    in full, and the talent's share is clawed back: a `PayoutLine` of kind
    `CLAWBACK` is created with `amount_cents` equal to the negative of the
    order's `talent_net_cents`, the order's `clawback_cents` records the
    clawed amount, and the talent's `pending_balance_cents` is debited by the
    same."
    PRD §3.6: "The order's gross is subtracted from `trailing_gmv_cents` and
    the tier is recomputed."

    Design: Difficulty/compensating_invariant/full_refund_gmv_and_wallet_conservation
    """
    admin = make_admin_headers()
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order, _video = create_confirmed_order(api, talent, buyer)

    mid = read_talent(api, talent["id"])
    assert mid["pending_balance_cents"] == 7500
    assert mid["trailing_gmv_cents"] == 10000

    dispute = open_dispute(api, buyer, order)
    resolved = validate_success(
        api.resolve_dispute(dispute["id"], "FULL_REFUND", headers=admin)
    )
    assert resolved["status"] == "RESOLVED_REFUND"
    assert resolved["refund_to_buyer_cents"] == 10000

    final_order = read_order(api, order["id"])
    assert final_order["status"] == "REFUNDED"
    assert final_order["refund_amount_cents"] == 10000
    assert final_order["clawback_cents"] == 7500

    refreshed_buyer = read_buyer(api, buyer["id"])
    assert refreshed_buyer["wallet_credit_cents"] == 10000

    final_talent = read_talent(api, talent["id"])
    assert final_talent["pending_balance_cents"] == 0
    assert final_talent["trailing_gmv_cents"] == 0

    clawbacks = [l for l in lines_for_order(api, order["id"]) if l["kind"] == "CLAWBACK"]
    assert len(clawbacks) == 1
    assert clawbacks[0]["amount_cents"] == -7500


def test_no_refund_returns_order_to_confirmed_with_normal_payout(api):
    """PRD §3.6: "Under `NO_REFUND`, the dispute resolves to
    `RESOLVED_NO_REFUND` with `refund_to_buyer_cents` zero. The order returns
    from `REFUND_PENDING` to `CONFIRMED`, and payout computation runs exactly
    as on a normal confirmation — the `VIDEO_EARNING` line, the
    pending-balance credit, and the GMV-and-tier recompute all happen at this
    point, keyed to the tier in force at resolution."
    PRD §3.6: "All four require the dispute to be `OPEN` and the order to be
    `REFUND_PENDING`."

    Design: Difficulty/compensating_invariant/full_refund_gmv_and_wallet_conservation
    """
    admin = make_admin_headers()
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order, _video = create_confirmed_order(api, talent, buyer)
    # A dispute on a CONFIRMED order moves it to REFUND_PENDING.
    dispute = open_dispute(api, buyer, order, reason="still mismatched")
    assert read_order(api, order["id"])["status"] == "REFUND_PENDING"

    # Resolve NO_REFUND: back to CONFIRMED; payout computation reruns.
    # The confirm already credited pending once; the recompute on resolution
    # must produce the same split again without double-crediting.
    pending_before = read_talent(api, talent["id"])["pending_balance_cents"]
    resolved = validate_success(
        api.resolve_dispute(dispute["id"], "NO_REFUND", headers=admin)
    )
    assert resolved["status"] == "RESOLVED_NO_REFUND"
    assert resolved["refund_to_buyer_cents"] == 0

    final_order = read_order(api, order["id"])
    assert final_order["status"] == "CONFIRMED"
    assert final_order["platform_commission_cents"] == 2500
    assert final_order["talent_net_cents"] == 7500

    final_talent = read_talent(api, talent["id"])
    assert final_talent["pending_balance_cents"] == pending_before
    assert final_talent["trailing_gmv_cents"] == 10000


def test_buyer_mismatch_platform_absorbs(api):
    """PRD §3.6: "Under `BUYER_MISMATCH_PLATFORM_ABSORB`, the dispute
    resolves to `RESOLVED_BUYER_MISMATCH`: the buyer is still made whole with
    a full-gross wallet credit, but the platform absorbs the cost."
    PRD §3.6: "The order transitions to `REFUNDED` with `refund_amount_cents`
    equal to the gross, `platform_absorbed_cents` equal to the gross, and
    `clawback_cents` zero. No `CLAWBACK` line is created, the talent's
    `pending_balance_cents` is untouched, and `trailing_gmv_cents` is
    unchanged — the sale still counts toward the talent's tier."

    Design: Difficulty/compensating_invariant/full_refund_gmv_and_wallet_conservation
    """
    admin = make_admin_headers()
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order, _video = create_confirmed_order(api, talent, buyer)

    dispute = open_dispute(api, buyer, order, reason="wrong recipient")
    resolved = validate_success(
        api.resolve_dispute(
            dispute["id"], "BUYER_MISMATCH_PLATFORM_ABSORB", headers=admin
        )
    )
    assert resolved["status"] == "RESOLVED_BUYER_MISMATCH"
    assert resolved["refund_to_buyer_cents"] == 10000

    final_order = read_order(api, order["id"])
    assert final_order["status"] == "REFUNDED"
    assert final_order["refund_amount_cents"] == 10000
    assert final_order["platform_absorbed_cents"] == 10000
    assert final_order["clawback_cents"] == 0

    assert read_buyer(api, buyer["id"])["wallet_credit_cents"] == 10000

    final_talent = read_talent(api, talent["id"])
    assert final_talent["pending_balance_cents"] == 7500
    assert final_talent["trailing_gmv_cents"] == 10000

    clawbacks = [l for l in lines_for_order(api, order["id"]) if l["kind"] == "CLAWBACK"]
    assert clawbacks == []


def test_clawback_solvency_blocks_full_refund(api):
    """PRD §3.6: "For both refund-bearing clawback outcomes — `FULL_REFUND`
    and `PARTIAL_REFUND` — solvency is checked before anything is written: if
    the talent's `pending_balance_cents` is below the clawback amount, the
    resolution is rejected outright with `ERR_PENDING_BALANCE_INSUFFICIENT`
    and nothing mutates."
    PRD §2.9: "Clawbacks are never allowed to drive `pending_balance_cents`
    negative; a resolution that would do so is rejected with
    `ERR_PENDING_BALANCE_INSUFFICIENT` (HTTP 422)."

    Design: Difficulty/compensating_invariant/full_refund_gmv_and_wallet_conservation
    """
    admin = make_admin_headers()
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    # Confirm order 1, then fully refund it: the order's earning and clawback
    # cancel, so no payout covers this order's money.
    order1, _ = create_confirmed_order(api, talent, buyer)
    dispute1 = open_dispute(api, buyer, order1, reason="refund me")
    validate_success(api.resolve_dispute(dispute1["id"], "FULL_REFUND", headers=admin))

    # Order 2 is confirmed, swept, and paid out, draining the pending balance.
    order2, _ = create_confirmed_order(api, talent, buyer)
    payout = api.payout_sweep(
        "2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z", headers=admin
    ).json()["data"][0]
    validate_success(api.initiate_payout(payout["id"], headers=admin))
    validate_success(api.complete_payout(payout["id"], headers=admin))
    assert read_talent(api, talent["id"])["pending_balance_cents"] == 0

    # A full-refund dispute against the already-paid order2 then tries to
    # claw back 7500 with nothing left in pending.
    dispute2 = open_dispute(api, buyer, order2, reason="paid out already")
    response = api.resolve_dispute(dispute2["id"], "FULL_REFUND", headers=admin)
    validate_error(response, ApiErrorId.ERR_PENDING_BALANCE_INSUFFICIENT.value)
