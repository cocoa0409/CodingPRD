"""Compensating edges: the reversal restores exactly what the forward move took."""
from test_helpers import (
    ADMIN,
    POST_RELEASE_CLOCK_UTC,
    create_send,
    create_shipment,
    get_order,
    get_registration,
    get_send,
    host_headers,
    set_clock,
    setup_confirmed_registration,
    setup_released_score,
    transition_order,
    transition_send,
    transition_shipment,
)


# --------------------------------------------------------------------------
# ScoreSend: the fee ledger nets to zero across the cancel pair
# --------------------------------------------------------------------------

def test_cancelling_a_pending_send_restores_exactly_its_fee():
    """PRD §3.8: "Cancellation is available while the send is `PENDING` to a `SchoolCoordinator` — and to a `SchoolStudent` when the acting student owns the score — provided the logical clock is at or before the later of seven days after the send was created and `2027-07-31T23:59:59Z`; the cancelled send's `credit_back_cents` is set to its `fee_cents`."

    Design: Difficulty/compensating_invariant/score_send_fee_refund_conserves_settled_ledger
    """
    bundle = setup_released_score()
    score, school = bundle["score"], bundle["school"]
    sends = [
        create_send(score, school, recipient_type="COLLEGE", recipient_code=f"C300{index}")
        for index in (1, 2, 3)
    ]
    third = sends[2]
    fee_charged = third["fee_cents"]

    cancelled = transition_send(third, "CANCELLED", school=school)

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["credit_back_cents"] == fee_charged, (
        "the compensating credit must restore exactly the fee that was charged"
    )
    assert cancelled["credit_back_cents"] == cancelled["fee_cents"]


def test_uncancelled_sends_keep_their_credit_back_at_zero():
    """PRD §3.8: "the cancelled send's `credit_back_cents` is set to its `fee_cents`."
    PRD §3.8: "A `PENDING` send moves to `SENT` only when the underlying score is `RELEASED`"

    Design: Difficulty/compensating_invariant/score_send_fee_refund_conserves_settled_ledger
    """
    bundle = setup_released_score()
    score, school = bundle["score"], bundle["school"]
    sends = [
        create_send(score, school, recipient_type="COLLEGE", recipient_code=f"C310{index}")
        for index in (1, 2, 3)
    ]
    transition_send(sends[2], "CANCELLED", school=school)

    for send in sends[:2]:
        after = get_send(send["id"], school)
        assert after["status"] == "PENDING", "only the cancelled row moves"
        assert after["credit_back_cents"] == 0, (
            "no credit is restored on a row that was never cancelled"
        )


# --------------------------------------------------------------------------
# Material compromise: the seal break and the compensating return move no cents
# --------------------------------------------------------------------------

def _shipped_in_transit_setup():
    bundle = setup_confirmed_registration(subject="AP-MACRO")
    school, order = bundle["school"], bundle["order"]
    shipment = create_shipment(school, order)
    order = transition_order(order, "SUBMITTED", headers=host_headers(school))
    order = transition_order(order, "MATERIALS_SHIPPED")
    shipment = transition_shipment(shipment, "DISPATCHED")
    shipment = transition_shipment(shipment, "IN_TRANSIT")
    bundle["order"] = order
    bundle["shipment"] = shipment
    return bundle


def test_broken_seal_reverts_the_order_and_clears_the_sealed_flag():
    """PRD §3.5: "First, the owning exam order, if it is in `MATERIALS_SHIPPED`, reverts to `SUBMITTED` and its `materials_sealed` flag is set back to false"
    PRD §3.5: "From `IN_TRANSIT`, a `SchoolCoordinator` reports `seal_intact` as false and the shipment moves to `SEAL_BROKEN`, appending a seal-break report."

    Design: Difficulty/compensating_invariant/material_compromise_revert_conserves_money_value
    """
    bundle = _shipped_in_transit_setup()
    school, shipment = bundle["school"], bundle["shipment"]

    broken = transition_shipment(
        shipment, "SEAL_BROKEN", {"seal_intact": False}, headers=host_headers(school)
    )

    assert broken["status"] == "SEAL_BROKEN"
    order = get_order(bundle["order"]["id"])
    assert order["status"] == "SUBMITTED", "the revert edge takes the order back one step"
    assert order["materials_sealed"] is False


def test_seal_break_and_return_pair_moves_no_cents():
    """PRD §3.5: "The machine declares `RECEIVED`, `RETURNED` and `SEAL_BROKEN` as its terminal states, and defines one further edge out of `SEAL_BROKEN` — to `RETURNED` — for sending compromised material back to the program."
    PRD §3.2: "Submission prices the order: `order_fee_cents` is set to the provisional variant of the dual-variant order fee"

    Design: Difficulty/compensating_invariant/material_compromise_revert_conserves_money_value
    """
    bundle = _shipped_in_transit_setup()
    school, shipment = bundle["school"], bundle["shipment"]

    order_before = get_order(bundle["order"]["id"])
    registration_before = get_registration(bundle["registration"]["id"])

    transition_shipment(shipment, "SEAL_BROKEN", {"seal_intact": False}, headers=host_headers(school))
    returned = transition_shipment(
        get_shipment_status(bundle["shipment"]["id"]), "RETURNED", headers=ADMIN
    )

    order_after = get_order(bundle["order"]["id"])
    registration_after = get_registration(bundle["registration"]["id"])

    assert returned["status"] == "RETURNED"
    assert order_after["order_fee_cents"] == order_before["order_fee_cents"], (
        "the compromise pair must not move the order fee"
    )
    assert order_after["unused_exam_charge_cents"] == order_before["unused_exam_charge_cents"]
    assert registration_after["fees_paid_cents"] == registration_before["fees_paid_cents"]


def get_shipment_status(shipment_id):
    from test_helpers import api_client, get_success_data

    return get_success_data(api_client.get_material_shipment(shipment_id, ADMIN))
