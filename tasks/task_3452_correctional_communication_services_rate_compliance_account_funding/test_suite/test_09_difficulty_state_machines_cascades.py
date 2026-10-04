"""Difficulty coverage: non-linear state machines (the recipient block
cycle on parallel dimensions; the video-session cancel fork) and the two
transitive cascades (inmate release ordering refunds before the closure
snapshot; refund disbursement chaining ledger entries into account fields)
(PRD §3.4, §3.7, §3.8).
"""
from test_helpers import (
    assert_closure_balance_partition,
    block_recipient,
    cancel_session,
    close_account,
    confirm_session,
    create_and_confirm_session,
    create_message,
    create_session,
    get_account,
    get_ledger,
    get_success_data,
    make_compliance_officer_headers,
    make_recipient_party_headers,
    release_inmate,
    setup_call_ready_account,
    setup_funded_account,
    setup_paid_refund_account,
    validate_success,
)


def test_block_cycle_block_phase_preserves_parallel_dimensions(api):
    """PRD §3.4: "Requesting a block — available only while the number is `VERIFIED`, otherwise `ERR_INVALID_STATE` — moves `block_status` from `NOT_BLOCKED` to `BLOCKED` and stores the recipient's optional `reason` as `block_reason`."

    Design: Difficulty/non_linear_state_machine/recipient_number_block_cycle_with_parallel_dimensions_intact
    """
    env = setup_call_ready_account()
    recipient = env["recipient"]
    assert recipient["verification_status"] == "VERIFIED"
    assert recipient["privilege_status"] == "NONE"

    blocked = block_recipient(recipient, reason="harassment")
    assert blocked["block_status"] == "BLOCKED"
    assert blocked["block_reason"] == "harassment"
    assert blocked["verification_status"] == "VERIFIED", (
        "the verification dimension is untouched by a block"
    )
    assert blocked["privilege_status"] == "NONE", (
        "the privilege dimension is untouched by a block"
    )


def test_block_cycle_reverify_lifts_block(api):
    """PRD §3.4: "The same call doubles as the unblock path: on a `BLOCKED` number, a correct code plus fresh consent lifts the block — `block_status` returns to `NOT_BLOCKED`, `block_reason` is cleared, and consent is re-captured."

    Design: Difficulty/non_linear_state_machine/recipient_number_block_cycle_with_parallel_dimensions_intact
    """
    env = setup_call_ready_account()
    recipient = env["recipient"]
    block_recipient(recipient, reason="harassment")

    unblocked = validate_success(
        api.verify_recipient_number(
            recipient["id"],
            recipient["verification_code"],
            True,
            make_recipient_party_headers(recipient["id"]),
        )
    )
    assert unblocked["block_status"] == "NOT_BLOCKED", "the cycle closes"
    assert unblocked["block_reason"] is None
    assert unblocked["verification_status"] == "VERIFIED"
    assert unblocked["privilege_status"] == "NONE"
    assert unblocked["consent_to_recording"] is True


def test_cancel_requested_session_appends_no_refund(api):
    """PRD §3.7: "Cancelling a still-`REQUESTED` session — by the account holder or by `FacilityStaff` — simply moves it to `CANCELLED` with `cancelled_at` stamped: no charge was ever made, and no refund is appended."

    Design: Difficulty/non_linear_state_machine/video_session_branching_cancel_paths_diverge_on_refund
    """
    env = setup_funded_account()
    session = create_session(
        env["facility"],
        env["inmate"],
        env["account"],
        scheduled_start="2026-09-10T10:00:00Z",
        scheduled_end="2026-09-10T10:30:00Z",
    )
    assert session["status"] == "REQUESTED"

    cancelled = cancel_session(session, account=env["account"])
    assert cancelled["status"] == "CANCELLED"

    assert get_account(env["account"]["id"])["balance_cents"] == 1000, (
        "the REQUESTED branch never charged, so nothing is refunded"
    )
    rows = get_ledger(env["account"]["id"])
    assert not any(
        row["type"] in ("VIDEO_CHARGE", "VIDEO_REFUND") for row in rows
    ), "no video ledger movement may exist for the REQUESTED branch"


def test_cancel_confirmed_session_appends_full_refund(api):
    """PRD §3.7: "A successful confirmed cancellation appends a `VIDEO_REFUND` credit of the full `charge_cents`, recomputes the balance, and restores the session's booth-minutes to the facility's bookable pool exactly, as the booth-minutes invariant requires."

    Design: Difficulty/non_linear_state_machine/video_session_branching_cancel_paths_diverge_on_refund
    """
    env = setup_funded_account()
    account = env["account"]
    requested = create_session(
        env["facility"],
        env["inmate"],
        account,
        scheduled_start="2026-09-10T10:00:00Z",
        scheduled_end="2026-09-10T10:30:00Z",
    )
    confirmed = create_and_confirm_session(
        env["facility"],
        env["inmate"],
        account,
        scheduled_start="2026-09-11T10:00:00Z",
        scheduled_end="2026-09-11T10:30:00Z",
    )
    assert confirmed["charge_cents"] == 500
    assert get_account(account["id"])["balance_cents"] == 500

    cancelled_requested = cancel_session(requested, account=account)
    assert cancelled_requested["status"] == "CANCELLED"
    assert get_account(account["id"])["balance_cents"] == 500, (
        "the REQUESTED cancel moved no money"
    )

    cancelled_confirmed = cancel_session(confirmed, account=account)
    assert cancelled_confirmed["status"] == "CANCELLED"
    assert get_account(account["id"])["balance_cents"] == 1000, (
        "the CONFIRMED cancel refunds the full charge"
    )

    rows = get_ledger(account["id"])
    charges = [r for r in rows if r["type"] == "VIDEO_CHARGE"]
    refunds = [r for r in rows if r["type"] == "VIDEO_REFUND"]
    assert len(charges) == 1 and charges[0]["amount_cents"] == -500
    assert len(refunds) == 1 and refunds[0]["amount_cents"] == 500
    assert refunds[0]["reference_id"] == confirmed["id"]


def test_release_cascade_refunds_before_closure_snapshot(
    api, facility_staff_headers
):
    """PRD §3.8: "First, every video session of the inmate that is still `REQUESTED` or `CONFIRMED` and whose `scheduled_start` lies in the future is cancelled; the confirmed ones are refunded in full with a `VIDEO_REFUND` credit of their `charge_cents`. Second, every message of the inmate still `PENDING_REVIEW` is rejected, with a `MESSAGE_REFUND` credit of its `price_cents`. Third — strictly after the first two steps, so those refunds land inside the closure snapshot — every `ACTIVE` `DEBIT` account belonging to the inmate auto-closes with its closure fee waived and the closure recorded as initiated by 'system'."

    Design: Difficulty/transitive_cascade/inmate_release_cascade_orders_refunds_before_closure_snapshot
    """
    env = setup_funded_account(funding_model="DEBIT", deposit_as_staff=True)
    facility, inmate, account = env["facility"], env["inmate"], env["account"]

    session = create_and_confirm_session(
        facility,
        inmate,
        account,
        as_staff=True,
        scheduled_start="2026-09-20T10:00:00Z",
        scheduled_end="2026-09-20T10:30:00Z",
    )
    message = create_message(account, inmate, "see you soon")
    assert get_account(account["id"])["balance_cents"] == 485, (
        "1000 - 500 video charge - 15 message charge"
    )

    released = release_inmate(inmate["id"])
    assert released["status"] == "RELEASED"

    session_after = get_success_data(
        api.get_video_session(session["id"], facility_staff_headers)
    )
    assert session_after["status"] == "CANCELLED"
    message_after = get_success_data(api.get_message(message["id"], facility_staff_headers))
    assert message_after["status"] == "REJECTED"

    closed = get_account(account["id"])
    assert closed["status"] == "CLOSED"
    assert closed["balance_at_closure_cents"] == 1000, (
        "both refunds land inside the closure snapshot: 485 pre-release "
        "balance + 500 video refund + 15 message refund"
    )
    assert closed["refundable_computed_cents"] == 1000, (
        "the release auto-close waives the closure fee"
    )


def test_release_cascade_auto_close_creates_system_refund_request(
    api, compliance_officer_headers
):
    """PRD §3.8: "Third — strictly after the first two steps, so those refunds land inside the closure snapshot — every `ACTIVE` `DEBIT` account belonging to the inmate auto-closes with its closure fee waived and the closure recorded as initiated by 'system'. `PREPAID` and `COLLECT` accounts are entirely unaffected by a release."
    PRD §3.8: "When it is positive, a **RefundRequest** is created with `source` `CLOSURE` and status `REQUESTED`, its `requested_amount_cents` equal to the full closure snapshot; the balance stays frozen on the ledger, `latest_refund_request_id` is set on the account, and `requested_by_user_id` with `requested_by_role` record who closed it ('system' for the auto-close)."

    Design: Difficulty/transitive_cascade/inmate_release_cascade_orders_refunds_before_closure_snapshot
    """
    env = setup_funded_account(funding_model="DEBIT", deposit_as_staff=True)
    facility, inmate, account = env["facility"], env["inmate"], env["account"]

    session = create_and_confirm_session(
        facility,
        inmate,
        account,
        as_staff=True,
        scheduled_start="2026-09-20T10:00:00Z",
        scheduled_end="2026-09-20T10:30:00Z",
    )
    message = create_message(account, inmate, "see you soon")
    release_inmate(inmate["id"])

    closed = get_account(account["id"])
    refund_request_id = closed["latest_refund_request_id"]
    assert refund_request_id, "the auto-close opened a RefundRequest"
    refund_request = get_success_data(
        api.get_refund_request(refund_request_id, compliance_officer_headers)
    )
    assert refund_request["source"] == "CLOSURE"
    assert refund_request["status"] == "REQUESTED"
    assert refund_request["requested_amount_cents"] == 1000
    assert refund_request["requested_by_user_id"] == "system"
    assert refund_request["requested_by_role"] == "system"

    rows = get_ledger(account["id"])
    video_refunds = [
        r for r in rows if r["type"] == "VIDEO_REFUND" and r["amount_cents"] == 500
    ]
    message_refunds = [
        r for r in rows if r["type"] == "MESSAGE_REFUND" and r["amount_cents"] == 15
    ]
    assert len(video_refunds) == 1
    assert video_refunds[0]["reference_id"] == session["id"]
    assert len(message_refunds) == 1
    assert message_refunds[0]["reference_id"] == message["id"]


def test_mark_paid_sets_account_refund_fields(api):
    """PRD §3.8: "Payment stamps `paid_by_user_id` and `paid_at`, then appends two ledger entries: a `REFUND_PAYOUT` debit of `computed_payout_cents`, and a settling `CLOSURE_FEE` entry whose amount is the negative of the closure snapshot minus the payout minus any amounts already settled — which makes that entry a credit rather than a debit in the unusual case where the restored deposit fees exceed the closure fee. The ledger balance is left equal to the snapshot minus everything settled, the account's `refunded_total_cents` grows by the payout, and `retained_fees_cents` becomes the snapshot minus the total settled payouts."

    Design: Difficulty/transitive_cascade/refund_mark_paid_chains_ledger_then_account_fields
    """
    # Deposit 1000 (not the 1025 default): 1000 - 25 fee -> balance 975 at
    # closure; refundable 975 - 100 closure fee = 875 (the asserted geometry).
    env = setup_paid_refund_account(deposit_amount=1000)
    decision = env["decision"]
    assert decision["status"] == "APPROVED"
    assert decision["computed_payout_cents"] == 875
    assert decision["refund_method_applied"] == "SIMPLE_BALANCE"

    payment = env["payment"]
    assert payment["status"] == "PAID"
    assert payment["paid_by_user_id"] != decision["decided_by_user_id"], (
        "the payer differs from the decider (segregation of duties)"
    )

    account = env["account"]
    assert account["balance_at_closure_cents"] == 975
    assert account["balance_cents"] == 0
    assert account["refunded_total_cents"] == 875
    assert account["retained_fees_cents"] == 100


def test_mark_paid_appends_payout_and_settling_fee_entries(api):
    """PRD §3.8: "Payment stamps `paid_by_user_id` and `paid_at`, then appends two ledger entries: a `REFUND_PAYOUT` debit of `computed_payout_cents`, and a settling `CLOSURE_FEE` entry whose amount is the negative of the closure snapshot minus the payout minus any amounts already settled"
    PRD §2.10: "Once an account is closed, its `balance_at_closure_cents` is always fully accounted for as the sum of its refunded total, its escheated total, its retained fees, the not-yet-settled remainder still frozen on the ledger, and any unclaimed balance."

    Design: Difficulty/transitive_cascade/refund_mark_paid_chains_ledger_then_account_fields
    """
    # Same geometry as the sibling test: deposit 1000 -> balance 975 at
    # closure; payout 875; settling CLOSURE_FEE -100.
    env = setup_paid_refund_account(deposit_amount=1000)
    account = env["account"]

    rows = get_ledger(account["id"])
    assert [r["type"] for r in rows] == [
        "DEPOSIT",
        "DEPOSIT_FEE",
        "REFUND_PAYOUT",
        "CLOSURE_FEE",
    ], "payment appends the payout then the settling closure-fee entry"
    assert rows[-2]["amount_cents"] == -875
    assert rows[-2]["reference_id"] == env["refund_request"]["id"]
    assert rows[-1]["amount_cents"] == -100, (
        "settling CLOSURE_FEE = -(975 snapshot - 875 payout)"
    )

    assert account["balance_cents"] == 0
    assert_closure_balance_partition(account, remaining_frozen_cents=0)
