"""RETURN_TO_PATIENT is the hop that makes the kit lifecycle genuinely cyclic: the
same kit row leaves RECEIVED, goes back to the household, and re-enters
ACTIVE_FILLING to be sealed a second time with new declared values."""

from test_helpers import (
    acknowledge_kit,
    assert_facility_counters,
    assert_kit,
    assert_ledger_sequence,
    assert_non_conformance_event,
    assert_patient_risk,
    assert_program_balances,
    assert_return_label,
    assert_shipment_axes,
    read_kit,
    read_ledger_entries,
    read_patient,
    read_program,
    read_return_label,
    read_shipment,
    read_treatment_facility,
    remediate_for,
    seal_kit_for,
    setup_notified_non_conformance,
)


def _returned_kit(api):
    """Baseline chain to an UNSEALED_CONTAINER rejection notified by postal mail, then
    resolved by mailing the parcel back to the household."""
    ctx = setup_notified_non_conformance(
        api, reason_code="UNSEALED_CONTAINER", notification_channel="POSTAL_MAIL"
    )
    remediate_for(api, ctx, "RETURN_TO_PATIENT")
    return ctx


def test_01_return_to_patient_sends_the_kit_out_of_the_facility(api):
    """The kit leaves RECEIVED for RETURNED_TO_PATIENT and the facility's pending queue
    drops the units it had been holding.

    PRD 3.7: "`RETURN_TO_PATIENT` sends the parcel back: the kit moves `RECEIVED → RETURNED_TO_PATIENT` with its `version` incremented by 1, the facility's `pending_intake_units` falls by exactly the shipment's `custody_units`, and the shipment's return label moves `ACTIVATED → VOIDED` with `voided_at` set to the current logical-clock instant, which starts the label's 24-hour quarantine on that kit."

    Design: Difficulty/non_linear_state_machine/kit_cycles_back_to_active_filling_after_return_to_patient
    """
    ctx = _returned_kit(api)

    assert_kit(read_kit(api, ctx["kit"]["id"]), status="RETURNED_TO_PATIENT")
    assert_facility_counters(
        read_treatment_facility(api, ctx["treatment_facility"]["id"]),
        pending_intake_units=0,
    )


def test_02_the_outbound_label_is_voided_by_the_return(api):
    """The label that carried the parcel in is spent; it moves ACTIVATED to VOIDED and
    records when.

    PRD 3.7: "`RETURN_TO_PATIENT` sends the parcel back: the kit moves `RECEIVED → RETURNED_TO_PATIENT` with its `version` incremented by 1, the facility's `pending_intake_units` falls by exactly the shipment's `custody_units`, and the shipment's return label moves `ACTIVATED → VOIDED` with `voided_at` set to the current logical-clock instant, which starts the label's 24-hour quarantine on that kit."

    Design: Difficulty/non_linear_state_machine/kit_cycles_back_to_active_filling_after_return_to_patient
    """
    ctx = _returned_kit(api)

    label = read_return_label(api, ctx["return_label"]["id"])
    assert_return_label(label, status="VOIDED")
    assert label["voided_at"] is not None, (
        "a voided label must record voided_at"
    )


def test_03_the_second_acknowledgement_carries_the_same_row_back_to_filling(api):
    """Acknowledging receipt a second time is legal from RETURNED_TO_PATIENT and lands
    the very same kit id back in ACTIVE_FILLING.

    PRD 3.5: "The transition `ISSUED → ACTIVE_FILLING` is the ordinary first acknowledgement; the transition `RETURNED_TO_PATIENT → ACTIVE_FILLING` is the second acknowledgement that occurs after a rejected parcel has been mailed back to the household, and it is what makes this lifecycle cyclic — the same kit row re-enters the filling stage it has already passed through, and the whole run from `ACTIVE_FILLING` through `SEALED` and onward may play out again on that row."

    Design: Difficulty/non_linear_state_machine/kit_cycles_back_to_active_filling_after_return_to_patient
    """
    ctx = _returned_kit(api)
    original_kit_id = ctx["kit"]["id"]

    reacknowledged = acknowledge_kit(api, ctx)

    assert reacknowledged["id"] == original_kit_id, (
        "the cycle must reuse the same kit row, not mint a replacement"
    )
    assert_kit(reacknowledged, status="ACTIVE_FILLING")


def test_04_the_re_seal_overwrites_the_declared_count_and_weight(api):
    """Sealing runs again on the recycled row and stores the household's new
    declaration of 40 units at 900 grams.

    PRD 3.5: "On success the kit moves `ACTIVE_FILLING → SEALED`, both declared values are stored on the kit, and the kit's `version` is incremented by 1."

    Design: Difficulty/non_linear_state_machine/kit_cycles_back_to_active_filling_after_return_to_patient
    """
    ctx = _returned_kit(api)
    acknowledge_kit(api, ctx)

    resealed = seal_kit_for(api, ctx, fill_units=40, sealed_gross_weight_grams=900)

    assert_kit(resealed, status="SEALED", fill_units=40, container_size="ONE_QUART")
    assert resealed["sealed_gross_weight_grams"] == 900, (
        f"expected the re-declared weight 900, got "
        f"{resealed['sealed_gross_weight_grams']}"
    )


def test_05_the_resolved_event_and_the_shipment_axes_do_not_move_again(api):
    """The kit's second pass through filling leaves the first shipment and its event
    exactly where remediation left them.

    PRD 3.7: "Whichever action is chosen, the event moves `CUSTOMER_NOTIFIED → RESOLVED` with the chosen `remediation_action` stored, the shipment's conformance axis moves `NON_CONFORMING → REMEDIATED` while `transport_status` stays `DELIVERED`, and both records have their `version` incremented by 1."

    Design: Difficulty/non_linear_state_machine/kit_cycles_back_to_active_filling_after_return_to_patient
    """
    ctx = _returned_kit(api)
    acknowledge_kit(api, ctx)
    seal_kit_for(api, ctx, fill_units=40, sealed_gross_weight_grams=900)

    assert_shipment_axes(
        read_shipment(api, ctx["shipment"]["id"]),
        transport_status="DELIVERED",
        conformance_status="REMEDIATED",
    )
    assert_non_conformance_event(
        ctx["non_conformance_event"],
        status="RESOLVED",
        reason_code="UNSEALED_CONTAINER",
        notification_channel="POSTAL_MAIL",
        remediation_action="RETURN_TO_PATIENT",
    )


def test_06_nothing_was_destroyed_so_the_facility_totals_stay_at_zero(api):
    """A returned parcel is never certified, so no certificate is issued and the
    lifetime destroyed total never moves.

    PRD 3.7: "The kit is no longer certifiable, and the household's next receipt acknowledgement will carry it back to `ACTIVE_FILLING`."
    PRD 3.8: "On the facility, `certificates_issued_count` rises by 1, `pending_intake_units` falls by exactly the shipment's `custody_units`, and `destroyed_units_total` rises by the certificate's `destroyed_units`."

    Design: Difficulty/non_linear_state_machine/kit_cycles_back_to_active_filling_after_return_to_patient
    """
    ctx = _returned_kit(api)
    acknowledge_kit(api, ctx)
    seal_kit_for(api, ctx, fill_units=40, sealed_gross_weight_grams=900)

    assert_facility_counters(
        read_treatment_facility(api, ctx["treatment_facility"]["id"]),
        pending_intake_units=0,
        destroyed_units_total=0,
        certificates_issued_count=0,
    )


def test_07_the_rejection_scored_thirty_and_left_the_patient_enrolled(api):
    """UNSEALED_CONTAINER weighs 30 on a fresh event, which is below the suspension
    threshold, so the enrollment stays usable for the second fill.

    PRD 3.9: "Each event contributes a weight determined by its `reason_code`: `LOOSE_SHARPS_IN_BOX` weighs 45, `UNAPPROVED_WASTE_TYPE` weighs 40, `UNSEALED_CONTAINER` weighs 30, `OVERFILLED_CONTAINER` weighs 25, `WEIGHT_EXCEEDS_SPEC` weighs 20 and `MISSING_ABSORBENT` weighs 15."
    PRD 3.9: "This score is recomputed on every conformance screening, whatever the outcome, and it is also refreshed inside every auto-ship run."

    Design: Difficulty/non_linear_state_machine/kit_cycles_back_to_active_filling_after_return_to_patient
    """
    ctx = _returned_kit(api)

    assert_patient_risk(
        read_patient(api, ctx["patient"]["id"]),
        screening_risk_score=30,
        status="ENROLLED",
    )


def test_08_the_reservation_survives_the_round_trip_uncommitted(api):
    """The only ledger append in the whole cycle is the original 1465-cent reservation:
    a return neither releases it nor commits anything, so the money is still held.

    PRD 2.9: "On the program side, `reserved_cents` is the sum of `RESERVATION` amounts less the sum of `RESERVATION_RELEASE` amounts over that program's entries, and `committed_cents` is the sum of `COMMITMENT` amounts less the sum of `COMMITMENT_REVERSAL` amounts."
    PRD 3.7: "`RETURN_TO_PATIENT` sends the parcel back: the kit moves `RECEIVED → RETURNED_TO_PATIENT` with its `version` incremented by 1, the facility's `pending_intake_units` falls by exactly the shipment's `custody_units`, and the shipment's return label moves `ACTIVATED → VOIDED` with `voided_at` set to the current logical-clock instant, which starts the label's 24-hour quarantine on that kit."

    Design: Difficulty/non_linear_state_machine/kit_cycles_back_to_active_filling_after_return_to_patient
    """
    ctx = _returned_kit(api)
    acknowledge_kit(api, ctx)
    seal_kit_for(api, ctx, fill_units=40, sealed_gross_weight_grams=900)

    entries = read_ledger_entries(api, ctx["sponsorship_program"]["id"])
    assert_ledger_sequence(entries, [(1, "RESERVATION", 1465)])
    assert_program_balances(
        read_program(api, ctx["sponsorship_program"]["id"]),
        reserved_cents=1465,
        committed_cents=0,
        available_cents=498535,
    )
