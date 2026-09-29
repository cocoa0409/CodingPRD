"""
Round trips that must leave a conserved aggregate exactly where it started.

One pair reserves a cornea and cancels the reservation, watching the inventory counts; the
other bills a surgeon and takes the cornea back unused, watching the money ledger.
"""

from test_helpers import (
    CANCEL_REASON_UNUSED_TISSUE_RETURNED,
    COORDINATOR_HEADERS,
    FEE_OPTICAL_ALL_SURCHARGES_CENTS,
    assert_dimensions,
    assert_instant_equals,
    assert_ledger,
    fixtures,
    total_count_of,
)


def _inventory_counts(pinned_api):
    """The five inventory positions of section 2.11, read from the tissue collection."""

    def count(**filters):
        return total_count_of(pinned_api.list_tissues(COORDINATOR_HEADERS, **filters))

    available = count(disposition_status="ELIGIBLE", custody_status="IN_HOUSE") + count(
        disposition_status="ELIGIBLE", custody_status="RETURNED_TO_BANK"
    )
    committed = count(disposition_status="RESERVED") + count(disposition_status="ISSUED")
    held = count(disposition_status="QUARANTINED")
    retired = (
        count(disposition_status="IMPLANTED")
        + count(disposition_status="DISCARDED")
        + count(disposition_status="RELEASED_FOR_RESEARCH")
        + count(disposition_status="RELEASED_FOR_TRAINING")
    )
    ungraded = count(disposition_status="UNGRADED")
    graded = count() - ungraded
    return {
        "available": available,
        "committed": committed,
        "held": held,
        "retired": retired,
        "ungraded": ungraded,
        "graded": graded,
    }


def _two_eligible_corneas_and_a_request(pinned_api):
    """A bilateral donor whose two corneas are both eligible, plus one open request."""
    chain = fixtures.tissue_chain(
        pinned_api, donor_code="D-2846-CI1", recovered_lateralities=("OD", "OS")
    )
    booking = fixtures.surgeon_with_request(pinned_api, "Dr Hana Iqbal", "CTR-08", "PK")
    return chain, booking


def test_reserving_a_cornea_moves_one_unit_from_available_to_committed(pinned_api):
    """
    The bank starts with two available units and no committed ones; one reservation shifts
    exactly one unit across without changing the graded total.

    PRD 2.11: "Reading the tissue collection filtered by `disposition_status` and taking
    `total_count` from the pagination envelope yields the bank's inventory position: the
    available units are the tissues whose `disposition_status` is `ELIGIBLE` and whose
    `custody_status` is `IN_HOUSE` or `RETURNED_TO_BANK`; the committed units are those whose
    `disposition_status` is `RESERVED` or `ISSUED`; the held units are those `QUARANTINED`;
    the retired units are those `IMPLANTED`, `DISCARDED`, `RELEASED_FOR_RESEARCH` or
    `RELEASED_FOR_TRAINING`; and the graded units are every tissue whose
    `disposition_status` is anything other than `UNGRADED`."

    Design: Difficulty/compensating_invariant/reservation_then_cancellation_restores_the_tissue_unit_ledger
    """
    chain, booking = _two_eligible_corneas_and_a_request(pinned_api)
    before = _inventory_counts(pinned_api)
    assert before == {
        "available": 2,
        "committed": 0,
        "held": 0,
        "retired": 0,
        "ungraded": 0,
        "graded": 2,
    }

    fixtures.allocate(pinned_api, chain["tissue_ids"][0], booking.request_id)

    after = _inventory_counts(pinned_api)
    assert after["available"] == 1
    assert after["committed"] == 1
    assert after["held"] == 0
    assert after["retired"] == 0
    assert (
        after["available"] + after["committed"] + after["held"] + after["retired"]
        == after["graded"]
    ), "available plus committed plus held plus retired must equal graded"


def test_cancelling_the_reservation_restores_the_pre_reservation_counts(pinned_api):
    """
    Cancelling the reservation puts the unit back on the shelf, costs the surgeon nothing and
    leaves the untouched sibling exactly as it was.

    PRD 2.11: "Reservation and its compensating cancellation form a round trip: reserving a
    tissue and then cancelling that reservation restores the available count to exactly its
    pre-reservation value and leaves the committed count at exactly its pre-reservation
    value."

    Design: Difficulty/compensating_invariant/reservation_then_cancellation_restores_the_tissue_unit_ledger
    """
    chain, booking = _two_eligible_corneas_and_a_request(pinned_api)
    reserved_id, untouched_id = chain["tissue_ids"]
    before = _inventory_counts(pinned_api)
    sibling_before = fixtures.read_tissue(pinned_api, untouched_id)
    allocation = fixtures.allocate(pinned_api, reserved_id, booking.request_id)

    cancelled = fixtures.cancel_allocation(
        pinned_api, allocation["id"], cancel_reason="SURGERY_CANCELLED"
    )

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "SURGERY_CANCELLED"
    assert _inventory_counts(pinned_api) == before

    tissue = fixtures.read_tissue(pinned_api, reserved_id)
    assert_dimensions(tissue, "ELIGIBLE", "IN_HOUSE")
    assert tissue["issue_count"] == 0
    assert tissue["reissue_generation"] == 0
    assert fixtures.read_request(pinned_api, booking.request_id)["status"] == "OPEN"
    assert_ledger(
        fixtures.read_surgeon(pinned_api, booking.surgeon_id), 0, 0, 0, "after cancellation"
    )

    sibling_after = fixtures.read_tissue(pinned_api, untouched_id)
    assert sibling_after == sibling_before


def _optical_cornea_and_an_urgent_dmek_booking(pinned_api):
    """A top-grade cornea and the urgent DMEK request whose fee carries all three surcharges."""
    chain = fixtures.tissue_chain(pinned_api, donor_code="D-2846-CI2")
    tissue = chain["tissues"][0]
    booking = fixtures.surgeon_with_request(
        pinned_api,
        "Dr Owen Marsh",
        "CTR-09",
        "DMEK",
        procedure_type="DMEK",
        surgery_date="2026-08-05T00:00:00.000Z",
        urgency="URGENT",
    )
    return tissue, booking


def test_confirmation_bills_the_gross_and_the_outstanding_while_reservation_bills_nothing(
    pinned_api,
):
    """
    Holding the cornea costs the surgeon nothing; committing to ship it moves the gross and
    the outstanding by exactly the allocation's fee.

    PRD 3.7: "On success the allocation moves `RESERVED → CONFIRMED`, and the money ledger
    moves with it: the surgeon's `gross_billed_cents` and `outstanding_fee_cents` each
    increase by exactly that allocation's `processing_fee_cents`, while `credited_fee_cents`
    is unchanged."

    Design: Difficulty/compensating_invariant/confirm_then_unused_return_conserves_the_surgeon_money_ledger
    """
    tissue, booking = _optical_cornea_and_an_urgent_dmek_booking(pinned_api)
    assert booking.request["priority_tier"] == "PLATINUM"
    assert booking.request["priority_score"] == 85
    assert_ledger(booking.surgeon, 0, 0, 0, "at registration")

    allocation = fixtures.allocate(pinned_api, tissue["id"], booking.request_id)
    assert allocation["processing_fee_cents"] == FEE_OPTICAL_ALL_SURCHARGES_CENTS
    assert_ledger(
        fixtures.read_surgeon(pinned_api, booking.surgeon_id), 0, 0, 0, "after reservation"
    )

    fixtures.confirm(pinned_api, allocation["id"])

    assert_ledger(
        fixtures.read_surgeon(pinned_api, booking.surgeon_id),
        FEE_OPTICAL_ALL_SURCHARGES_CENTS,
        0,
        FEE_OPTICAL_ALL_SURCHARGES_CENTS,
        "after confirmation",
    )


def test_the_unused_return_credits_the_fee_and_never_lowers_the_gross(pinned_api):
    """
    Taking the cornea back after a clean delivery compensates the billing: the outstanding
    returns to zero through a credit, not by reversing the original charge.

    PRD 3.8: "The release credits the surgeon exactly as a cold-chain rejection does:
    `credited_fee_cents` increases by the allocation's `processing_fee_cents`,
    `outstanding_fee_cents` decreases by the same amount, and `gross_billed_cents` is
    unchanged."

    Design: Difficulty/compensating_invariant/confirm_then_unused_return_conserves_the_surgeon_money_ledger
    """
    tissue, booking = _optical_cornea_and_an_urgent_dmek_booking(pinned_api)
    assert_instant_equals(tissue["expires_at"], "2026-08-17T09:00:00.000Z", "expires_at")
    fee = FEE_OPTICAL_ALL_SURCHARGES_CENTS

    chain = fixtures.returned_tissue_chain(
        pinned_api,
        tissue["id"],
        booking.request_id,
        booking.surgeon_id,
        return_reason="RECIPIENT_UNFIT_FOR_SURGERY",
    )

    surgeon = fixtures.read_surgeon(pinned_api, booking.surgeon_id)
    assert_ledger(surgeon, fee, fee, 0, "after the unused return")
    assert surgeon["gross_billed_cents"] == fee
    assert (
        surgeon["outstanding_fee_cents"] + surgeon["credited_fee_cents"]
        == surgeon["gross_billed_cents"]
    )

    returned = fixtures.read_tissue(pinned_api, tissue["id"])
    assert_dimensions(returned, "ELIGIBLE", "RETURNED_TO_BANK")
    assert returned["reissue_generation"] == 1
    allocation = fixtures.read_allocation(pinned_api, chain.allocation_id)
    assert allocation["status"] == "RELEASED"
    assert allocation["cancel_reason"] == CANCEL_REASON_UNUSED_TISSUE_RETURNED
    assert fixtures.read_shipment(pinned_api, chain.shipment_id)["status"] == "RETURNED"
    assert fixtures.read_request(pinned_api, booking.request_id)["status"] == "OPEN"
