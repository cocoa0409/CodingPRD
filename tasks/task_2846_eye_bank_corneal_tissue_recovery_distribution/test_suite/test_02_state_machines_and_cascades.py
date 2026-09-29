"""
Non-linear lifecycles and the multi-level cascades a single write can trigger.

The two state-machine cases walk a cornea through both of its independent dimensions and
walk a donor around the deferral cycle. The two cascade cases follow a substantiated
serious reaction five levels down to a sibling request, and a cold-chain rejection four
levels down to the surgeon's money ledger.
"""

from test_helpers import (
    CANCEL_REASON_TISSUE_QUARANTINED,
    CANCEL_REASON_UNUSED_TISSUE_RETURNED,
    QUARANTINE_REASON_COLD_CHAIN_MAJOR,
    T_NOW,
    assert_dimensions,
    assert_instant_equals,
    assert_ledger,
    assert_one_decimal,
    fixtures,
    make_surgeon_headers,
)


def _optical_tissue_and_routine_request(pinned_api, donor_code, surgery_date="2026-08-08T00:00:00.000Z"):
    chain = fixtures.tissue_chain(pinned_api, donor_code=donor_code)
    tissue = chain["tissues"][0]
    booking = fixtures.surgeon_with_request(
        pinned_api, "Dr Anwar Reed", "CTR-01", "PK", surgery_date=surgery_date
    )
    return tissue, booking


def test_dispatch_advances_both_tissue_dimensions_in_one_request(pinned_api):
    """
    Handing the parcel to the carrier is one of the five operations that moves the
    regulatory dimension and the physical dimension together.

    PRD 3.7: "On success `shipped_at` is stored, the shipment moves `PREPARED →
    IN_TRANSIT`, and the tissue moves on **both** dimensions in the same request:
    `disposition_status` goes `RESERVED → ISSUED` and `custody_status` goes `IN_HOUSE →
    IN_TRANSIT`, or `RETURNED_TO_BANK → IN_TRANSIT` when this is a re-issue of previously
    returned tissue."

    Design: Difficulty/non_linear_state_machine/tissue_custody_and_disposition_advance_as_independent_dimensions
    """
    tissue, booking = _optical_tissue_and_routine_request(pinned_api, "D-2846-C")

    chain = fixtures.issued_shipment(
        pinned_api, tissue["id"], booking.request_id, booking.surgeon_id
    )

    assert chain.shipment["status"] == "IN_TRANSIT"
    assert_instant_equals(chain.shipment["shipped_at"], "2026-08-03T10:00:00.000Z")
    issued = fixtures.read_tissue(pinned_api, tissue["id"])
    assert_dimensions(issued, "ISSUED", "IN_TRANSIT")
    assert issued["issue_count"] == 1
    assert issued["reissue_generation"] == 0


def test_delivery_moves_custody_while_the_disposition_stays_issued(pinned_api):
    """
    A clean arrival advances only the physical dimension: the graft is at the surgeon but
    its regulatory fate is still merely issued.

    PRD 3.8: "On `PASS` or `EXCURSION_MINOR` the shipment moves `IN_TRANSIT → DELIVERED`
    and the tissue's `custody_status` moves `IN_TRANSIT → AT_SURGEON`, while
    `disposition_status` **stays** at `ISSUED`; nothing else changes and the money ledger
    is untouched."

    Design: Difficulty/non_linear_state_machine/tissue_custody_and_disposition_advance_as_independent_dimensions
    """
    tissue, booking = _optical_tissue_and_routine_request(pinned_api, "D-2846-C")

    chain = fixtures.delivered_tissue(
        pinned_api, tissue["id"], booking.request_id, booking.surgeon_id
    )

    assert chain.shipment["status"] == "DELIVERED"
    assert chain.shipment["integrity_verdict"] == "PASS"
    assert chain.shipment["temp_excursion_minutes_over"] == 0
    delivered = fixtures.read_tissue(pinned_api, tissue["id"])
    assert_dimensions(delivered, "ISSUED", "AT_SURGEON")
    assert delivered["issue_count"] == 1


def test_unused_return_moves_both_dimensions_back_and_bumps_the_reissue_counter(pinned_api):
    """
    Returning an unused cornea from a clean shipment puts it back on the shelf, moves
    custody back to the bank and charges one re-issue generation.

    PRD 3.8: "When the delivering shipment's `integrity_verdict` is `PASS` **and** the
    tissue's `expires_at` is strictly later than the current logical instant,
    `disposition_status` moves `ISSUED → ELIGIBLE` and the cornea rejoins the allocatable
    pool."

    Design: Difficulty/non_linear_state_machine/tissue_custody_and_disposition_advance_as_independent_dimensions
    """
    tissue, booking = _optical_tissue_and_routine_request(pinned_api, "D-2846-C")
    chain = fixtures.returned_tissue_chain(
        pinned_api,
        tissue["id"],
        booking.request_id,
        booking.surgeon_id,
        return_reason="SURGERY_POSTPONED",
    )

    returned = fixtures.read_tissue(pinned_api, tissue["id"])
    assert_dimensions(returned, "ELIGIBLE", "RETURNED_TO_BANK")
    assert returned["reissue_generation"] == 1
    assert returned["issue_count"] == 1
    assert returned["quarantine_reason"] is None

    assert fixtures.read_shipment(pinned_api, chain.shipment_id)["status"] == "RETURNED"
    allocation = fixtures.read_allocation(pinned_api, chain.allocation_id)
    assert allocation["status"] == "RELEASED"
    assert allocation["cancel_reason"] == CANCEL_REASON_UNUSED_TISSUE_RETURNED
    assert fixtures.read_request(pinned_api, booking.request_id)["status"] == "OPEN"


def _cycled_donor(pinned_api):
    """A donor taken from referral to consent, then deferred by the medical director."""
    donor = fixtures.create_donor(
        pinned_api,
        donor_code="D-2846-CYC",
        referral_source="MEDICAL_EXAMINER",
        age_years=52,
    )
    assert donor["version"] == 1
    fixtures.add_screening(pinned_api, donor["id"], "TATTOO_12M", "NO", "SPOUSE")
    fixtures.record_consent(
        pinned_api,
        donor["id"],
        consent_type="NEXT_OF_KIN",
        consent_scope="TRANSPLANT_AND_RESEARCH",
        authorizing_party_name="Ada Ruiz",
    )
    consented = fixtures.read_donor(pinned_api, donor["id"])
    assert consented["status"] == "CONSENT_OBTAINED"
    assert consented["version"] == 3
    fixtures.defer_donor(
        pinned_api, donor["id"], deferral_reason="AWAITING_MEDICAL_RECORDS"
    )
    return donor["id"]


def test_reinstatement_returns_a_deferred_donor_to_screening_with_consent_intact(pinned_api):
    """
    The medical director's return edge clears the deferral reason and puts the donor back
    in SCREENING without discarding the authorization already on file.

    PRD 3.2: "Reinstatement is the return edge, reserved to the medical director: it is
    legal only from `DEFERRED`, requires `serology_status` to be anything other than
    `REACTIVE`, clears `deferral_reason` back to null and returns the donor to
    `SCREENING`."

    Design: Difficulty/non_linear_state_machine/donor_revisits_screening_through_the_deferral_cycle
    """
    donor_id = _cycled_donor(pinned_api)
    deferred = fixtures.read_donor(pinned_api, donor_id)
    assert deferred["status"] == "DEFERRED"
    assert deferred["deferral_reason"] == "AWAITING_MEDICAL_RECORDS"
    assert deferred["version"] == 4

    fixtures.reinstate_donor(pinned_api, donor_id)

    reinstated = fixtures.read_donor(pinned_api, donor_id)
    assert reinstated["status"] == "SCREENING"
    assert reinstated["deferral_reason"] is None
    assert reinstated["consent_scope"] == "TRANSPLANT_AND_RESEARCH"
    assert reinstated["consent_type"] == "NEXT_OF_KIN"
    assert reinstated["version"] == 5


def test_the_reinstated_donor_can_be_consented_and_approved_again(pinned_api):
    """
    The screening-deferral-screening cycle leaves the donor fully re-consentable, and the
    second pass reaches approval for recovery.

    PRD 3.2: "On success the donor advances `CONSENT_OBTAINED → APPROVED_FOR_RECOVERY` and
    its `version` is incremented; nothing else changes."

    Design: Difficulty/non_linear_state_machine/donor_revisits_screening_through_the_deferral_cycle
    """
    donor_id = _cycled_donor(pinned_api)
    fixtures.reinstate_donor(pinned_api, donor_id)

    fixtures.record_consent(
        pinned_api,
        donor_id,
        consent_type="NEXT_OF_KIN",
        consent_scope="TRANSPLANT_AND_RESEARCH",
        authorizing_party_name="Ada Ruiz",
    )
    second = fixtures.read_donor(pinned_api, donor_id)
    assert second["status"] == "CONSENT_OBTAINED"
    assert second["version"] == 6

    fixtures.approve_recovery(pinned_api, donor_id)

    approved = fixtures.read_donor(pinned_api, donor_id)
    assert approved["status"] == "APPROVED_FOR_RECOVERY"
    assert approved["version"] == 7
    assert approved["deferral_reason"] is None


def _implanted_graft_with_reserved_sibling(pinned_api):
    """
    One donor, two corneas: the first implanted in a surgeon's patient, the second still
    reserved against a later request from the same surgeon.
    """
    chain = fixtures.tissue_chain(
        pinned_api, donor_code="D-2846-LB", recovered_lateralities=("OD", "OS")
    )
    t1, t2 = chain["tissue_ids"]
    booking = fixtures.surgeon_with_request(pinned_api, "Dr Anwar Reed", "CTR-01", "PK")
    second_request = fixtures.create_request(
        pinned_api, booking.surgeon_id, surgery_date="2026-08-10T00:00:00.000Z"
    )
    first = fixtures.implanted_tissue(
        pinned_api, t1, booking.request_id, booking.surgeon_id
    )
    second_allocation = fixtures.allocate(pinned_api, t2, second_request["id"])
    report = fixtures.create_report(
        pinned_api,
        t1,
        booking.surgeon_id,
        reaction_type="PRIMARY_GRAFT_FAILURE",
        severity="SERIOUS",
        narrative="Graft failed on post-operative day one.",
    )
    return {
        "donor_id": chain["donor_id"],
        "t1": t1,
        "t2": t2,
        "surgeon_id": booking.surgeon_id,
        "request_1": booking.request_id,
        "request_2": second_request["id"],
        "allocation_1": first.allocation_id,
        "allocation_2": second_allocation["id"],
        "report_id": report["id"],
    }


def test_a_serious_substantiation_reaches_the_surgeon_the_donor_and_a_new_investigation(
    pinned_api,
):
    """
    Upholding one serious report charges the reporting surgeon's reaction count, flags the
    donor and opens an adverse-reaction lookback in the very same request.

    PRD 3.9: "A `SERIOUS` substantiated report additionally sets the donor's
    `lookback_flag` to true and opens a lookback investigation on that tissue's donor with
    `source_report_id` set to this report, `trigger_reason` `ADVERSE_REACTION` and `status`
    `OPEN`, running the full open cascade described below."

    Design: Difficulty/transitive_cascade/substantiated_serious_reaction_cascades_five_levels_to_the_sibling_request
    """
    state = _implanted_graft_with_reserved_sibling(pinned_api)

    upheld = fixtures.substantiate(
        pinned_api,
        state["report_id"],
        adjudication_note="Donor-attributable failure; opening lookback.",
    )

    assert upheld["status"] == "SUBSTANTIATED"
    assert upheld["adjudication_note"] == "Donor-attributable failure; opening lookback."

    surgeon = fixtures.read_surgeon(pinned_api, state["surgeon_id"])
    assert surgeon["substantiated_reaction_count"] == 1

    donor = fixtures.read_donor(pinned_api, state["donor_id"])
    assert donor["lookback_flag"] is True

    investigation = fixtures.first_investigation_for_donor(pinned_api, state["donor_id"])
    assert investigation is not None, "a serious substantiation must open an investigation"
    assert investigation["status"] == "OPEN"
    assert investigation["trigger_reason"] == "ADVERSE_REACTION"
    assert investigation["source_report_id"] == state["report_id"]
    assert investigation["donor_id"] == state["donor_id"]
    assert_instant_equals(investigation["opened_at"], T_NOW, "opened_at")


def test_the_open_cascade_counts_every_sibling_but_quarantines_only_the_reserved_one(
    pinned_api,
):
    """
    The investigation reports both of the donor's corneas as impacted yet quarantines only
    the reserved sibling, freeing its request; the implanted graft is left untouched.

    PRD 3.9: "The **quarantinable** subset is then those impacted tissues whose
    `disposition_status` is `ELIGIBLE` or `RESERVED`, and every one of them is moved to
    `QUARANTINED` — a reserved tissue's `RESERVED` allocation being cancelled with
    `cancel_reason` `TISSUE_QUARANTINED` and its request reopened to `OPEN`, exactly as a
    manual quarantine would."

    Design: Difficulty/transitive_cascade/substantiated_serious_reaction_cascades_five_levels_to_the_sibling_request
    """
    state = _implanted_graft_with_reserved_sibling(pinned_api)

    fixtures.substantiate(pinned_api, state["report_id"])

    investigation = fixtures.first_investigation_for_donor(pinned_api, state["donor_id"])
    assert investigation["impacted_tissue_count"] == 2
    assert investigation["quarantined_count"] == 1

    sibling = fixtures.read_tissue(pinned_api, state["t2"])
    assert_dimensions(sibling, "QUARANTINED", "IN_HOUSE")
    sibling_allocation = fixtures.read_allocation(pinned_api, state["allocation_2"])
    assert sibling_allocation["status"] == "CANCELLED"
    assert sibling_allocation["cancel_reason"] == CANCEL_REASON_TISSUE_QUARANTINED
    assert fixtures.read_request(pinned_api, state["request_2"])["status"] == "OPEN"

    implanted = fixtures.read_tissue(pinned_api, state["t1"])
    assert_dimensions(implanted, "IMPLANTED", "AT_SURGEON")
    assert (
        fixtures.read_allocation(pinned_api, state["allocation_1"])["status"] == "CONSUMED"
    )
    assert fixtures.read_request(pinned_api, state["request_1"])["status"] == "FULFILLED"


def _rejected_on_arrival(pinned_api):
    """
    A billed, dispatched cornea whose logger recorded one 15.0 degree sample an hour after
    hand-off, then acknowledged at the door.
    """
    chain = fixtures.tissue_chain(pinned_api, donor_code="D-2846-CC")
    tissue_id = chain["tissue_ids"][0]
    booking = fixtures.surgeon_with_request(pinned_api, "Dr Nils Auber", "CTR-03", "PK")
    allocation = fixtures.allocate(pinned_api, tissue_id, booking.request_id)
    fee = allocation["processing_fee_cents"]
    fixtures.confirm(pinned_api, allocation["id"])
    billed = fixtures.read_surgeon(pinned_api, booking.surgeon_id)

    shipment = fixtures.prepare_shipment(pinned_api, allocation["id"])
    fixtures.add_reading(pinned_api, shipment["id"], "2026-08-03T10:00:00.000Z", 4.0)
    fixtures.dispatch_shipment(pinned_api, shipment["id"], "2026-08-03T10:00:00.000Z")
    surgeon_headers = make_surgeon_headers(booking.surgeon_id)
    fixtures.add_reading(
        pinned_api, shipment["id"], "2026-08-03T11:00:00.000Z", 15.0, headers=surgeon_headers
    )
    fixtures.add_reading(
        pinned_api, shipment["id"], "2026-08-03T12:00:00.000Z", 5.0, headers=surgeon_headers
    )
    delivered = fixtures.deliver_shipment(
        pinned_api, shipment["id"], "2026-08-03T12:30:00.000Z", booking.surgeon_id
    )
    return {
        "tissue_id": tissue_id,
        "surgeon_id": booking.surgeon_id,
        "request_id": booking.request_id,
        "allocation_id": allocation["id"],
        "shipment_id": shipment["id"],
        "fee": fee,
        "billed": billed,
        "delivered": delivered,
    }


def test_the_excursion_is_charged_from_the_last_good_sample_and_grades_major(pinned_api):
    """
    The single out-of-range sample is charged back to the previous reading an hour earlier,
    and 60 minutes past a 15.0 degree spike can only be a major excursion.

    PRD 3.8: "It is `EXCURSION_MINOR` when `temp_excursion_minutes_over` is between 1 and
    45 inclusive **and** `max_temp_c` is at most 12.0 degrees **and** `min_temp_c` is at
    least minus 5.0 degrees — a brief deviation that stayed within survivable bounds."

    Design: Difficulty/transitive_cascade/cold_chain_rejection_cascades_four_levels_and_credits_the_fee
    """
    state = _rejected_on_arrival(pinned_api)
    shipment = state["delivered"]

    assert shipment["temp_excursion_minutes_over"] == 60
    assert_one_decimal(shipment["max_temp_c"], 15.0, "max_temp_c")
    assert_one_decimal(shipment["min_temp_c"], 4.0, "min_temp_c")
    assert shipment["integrity_verdict"] == "EXCURSION_MAJOR"
    assert shipment["status"] == "REJECTED_ON_ARRIVAL"
    assert_instant_equals(
        shipment["delivered_at"], "2026-08-03T12:30:00.000Z", "delivered_at"
    )


def test_rejection_unwinds_the_commitment_and_credits_the_fee_without_un_billing(
    pinned_api,
):
    """
    Refusal at the door reaches the tissue, the allocation, the request and the money
    ledger, and it does so by crediting rather than by reversing the original charge.

    PRD 3.8: "The money follows the release: the surgeon's `credited_fee_cents` increases
    by that allocation's `processing_fee_cents` and `outstanding_fee_cents` decreases by the
    same amount, while `gross_billed_cents` does not move — the bank never un-bills, it
    credits."

    Design: Difficulty/transitive_cascade/cold_chain_rejection_cascades_four_levels_and_credits_the_fee
    """
    state = _rejected_on_arrival(pinned_api)
    fee = state["fee"]
    assert fee == 245000
    assert_ledger(state["billed"], fee, 0, fee, "after confirmation")

    tissue = fixtures.read_tissue(pinned_api, state["tissue_id"])
    assert_dimensions(tissue, "QUARANTINED", "RETURNED_TO_BANK")
    assert tissue["quarantine_reason"] == QUARANTINE_REASON_COLD_CHAIN_MAJOR
    assert tissue["reissue_generation"] == 0
    assert tissue["issue_count"] == 1

    assert (
        fixtures.read_allocation(pinned_api, state["allocation_id"])["status"] == "RELEASED"
    )
    assert fixtures.read_request(pinned_api, state["request_id"])["status"] == "OPEN"

    surgeon = fixtures.read_surgeon(pinned_api, state["surgeon_id"])
    assert_ledger(surgeon, fee, fee, 0, "after rejection on arrival")
