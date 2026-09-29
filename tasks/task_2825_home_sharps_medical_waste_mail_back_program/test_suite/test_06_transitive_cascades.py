"""Two cascades that end three entities away from the call that fired them: a risk
cascade that starts on a screening and finishes by un-exhausting the sponsor program,
and a logistics cascade that starts on a carrier scan and does the same.
"""

from test_helpers import (
    SECOND_INTAKE_TECHNICIAN_USER_ID,
    add_screened_kit_cycle,
    advance_transport,
    assert_enrollment,
    assert_facility_counters,
    assert_kit,
    assert_ledger_entry,
    assert_ledger_sequence,
    assert_patient_risk,
    assert_program_balances,
    assert_return_label,
    assert_shipment_axes,
    issue_kit_for,
    read_kit,
    read_enrollment,
    read_ledger_entries,
    read_patient,
    read_program,
    read_return_label,
    read_shipment,
    read_treatment_facility,
    screen_shipment,
    setup_active_enrollment,
    setup_tendered_shipment,
)

# A ceiling of exactly three ONE_QUART reservations, so three live kits park the
# program on available_cents == 0 and the release at the end of the cascade is
# visible as an EXHAUSTED -> ACTIVE flip.
_TIGHT_PROGRAM = {
    "program_code": "NPD-TIGHT",
    "funding_ceiling_cents": 4395,
    "per_kit_allowance_cents": 6000,
}

# A ceiling of exactly one reservation, for the loss cascade.
_ONE_KIT_PROGRAM = {
    "program_code": "NPD-ONEKIT",
    "funding_ceiling_cents": 1465,
    "per_kit_allowance_cents": 6000,
}


def _three_kits_with_an_exhausted_program(api):
    """Kit 1 screened NON_CONFORMING for UNAPPROVED_WASTE_TYPE (40 points, under the
    threshold), kit 2 delivered but unscreened, kit 3 still in ISSUED. Three live
    reservations exhaust the 4395-cent ceiling."""
    ctx = setup_active_enrollment(api, program_overrides=_TIGHT_PROGRAM)
    ctx["cycle_one"] = add_screened_kit_cycle(
        api, ctx, outcome="NON_CONFORMING", reason_code="UNAPPROVED_WASTE_TYPE"
    )
    ctx["cycle_two"] = add_screened_kit_cycle(
        api, ctx, screen=False, scheduled_intake_date="2026-08-11"
    )
    ctx["third_kit"] = issue_kit_for(api, ctx)
    return ctx


def _screen_the_second_parcel(api, ctx):
    """The trigger: a second rejection worth 25 points, which takes the running score
    from 40 to 65 and crosses the suspension threshold."""
    return screen_shipment(
        api,
        ctx,
        shipment=ctx["cycle_two"]["shipment"],
        outcome="NON_CONFORMING",
        observed_gross_weight_grams=1520,
        reason_code="OVERFILLED_CONTAINER",
        technician_user_id=SECOND_INTAKE_TECHNICIAN_USER_ID,
    )


def test_01_the_second_rejection_pushes_the_running_score_over_sixty(api):
    """40 for the first event plus 25 for the second is 65, and crossing 60 on a
    screening suspends the patient in the same request.

    PRD 3.7: "Third, and only when that recomputed score reaches at least 60 while the patient is `ENROLLED`, the patient is suspended, which is itself a multi-hop cascade covered in §3.9."
    PRD 3.9: "The first hop moves the patient `ENROLLED → SUSPENDED` and sets `suspended_at` to the current logical-clock instant."

    Design: Difficulty/transitive_cascade/nonconforming_screening_cascades_to_patient_suspension_enrollment_pause_and_reservation_release
    """
    ctx = _three_kits_with_an_exhausted_program(api)
    assert_patient_risk(
        read_patient(api, ctx["patient"]["id"]),
        screening_risk_score=40,
        status="ENROLLED",
    )

    _screen_the_second_parcel(api, ctx)

    assert_patient_risk(
        read_patient(api, ctx["patient"]["id"]),
        screening_risk_score=65,
        status="SUSPENDED",
    )


def test_02_the_second_hop_pauses_the_enrollment_and_clears_the_due_date(api):
    """The suspension travels to the enrollment, which is paused with its auto-ship
    due date cleared to null.

    PRD 3.9: "The second hop moves every enrollment of that patient whose status is `ACTIVE` to `PAUSED`."
    PRD 3.9: "The third hop applies to each of those newly paused enrollments: its `next_autoship_due_date` is cleared to null, and every kit of that enrollment whose status is `ISSUED` moves to `VOIDED` with `void_reason` set to `ENROLLMENT_PAUSED` — kits already in `ACTIVE_FILLING` are physically in the patient's hands and are pointedly **not** voided."

    Design: Difficulty/transitive_cascade/nonconforming_screening_cascades_to_patient_suspension_enrollment_pause_and_reservation_release
    """
    ctx = _three_kits_with_an_exhausted_program(api)

    _screen_the_second_parcel(api, ctx)

    assert_enrollment(
        read_enrollment(api, ctx["enrollment"]["id"]),
        status="PAUSED",
        next_autoship_due_date=None,
    )


def test_03_only_the_issued_kit_is_voided_and_the_received_ones_are_left_alone(api):
    """The third hop reaches exactly one kit: the one still sitting in ISSUED. The two
    parcels already in the facility's hands are untouched at RECEIVED.

    PRD 3.9: "The third hop applies to each of those newly paused enrollments: its `next_autoship_due_date` is cleared to null, and every kit of that enrollment whose status is `ISSUED` moves to `VOIDED` with `void_reason` set to `ENROLLMENT_PAUSED` — kits already in `ACTIVE_FILLING` are physically in the patient's hands and are pointedly **not** voided."

    Design: Difficulty/transitive_cascade/nonconforming_screening_cascades_to_patient_suspension_enrollment_pause_and_reservation_release
    """
    ctx = _three_kits_with_an_exhausted_program(api)

    _screen_the_second_parcel(api, ctx)

    assert_kit(
        read_kit(api, ctx["third_kit"]["id"]),
        status="VOIDED",
        void_reason="ENROLLMENT_PAUSED",
    )
    assert_kit(read_kit(api, ctx["cycle_one"]["kit"]["id"]), status="RECEIVED")
    assert_kit(read_kit(api, ctx["cycle_two"]["kit"]["id"]), status="RECEIVED")


def test_04_the_fourth_hop_appends_a_release_for_the_voided_kit_only(api):
    """Three reservations then exactly one release: the release negates the voided
    kit's provisional cost and nothing else moves.

    PRD 3.9: "The fourth hop applies to each kit just voided: a `RESERVATION_RELEASE` ledger entry for the negation of that kit's `provisional_cost_cents` is appended and the program's `reserved_cents` falls by that amount."
    PRD 2.9: "Finally, each entry snapshots the three program balances as they stood immediately after the append, in `reserved_after_cents`, `committed_after_cents` and `available_after_cents`, and records a human-readable origin in `memo` — \"kit issuance\", \"kit void\", \"certificate settlement\" and the like."

    Design: Difficulty/transitive_cascade/nonconforming_screening_cascades_to_patient_suspension_enrollment_pause_and_reservation_release
    """
    ctx = _three_kits_with_an_exhausted_program(api)

    _screen_the_second_parcel(api, ctx)

    entries = read_ledger_entries(api, ctx["sponsorship_program"]["id"])
    assert_ledger_sequence(
        entries,
        [
            (1, "RESERVATION", 1465),
            (2, "RESERVATION", 1465),
            (3, "RESERVATION", 1465),
            (4, "RESERVATION_RELEASE", -1465),
        ],
    )
    assert_ledger_entry(
        entries[3],
        reserved_after_cents=2930,
        committed_after_cents=0,
        available_after_cents=1465,
        kit_id=ctx["third_kit"]["id"],
    )


def test_05_the_last_hop_un_exhausts_the_program(api):
    """The program is EXHAUSTED at available_cents 0 immediately before the screening
    and ACTIVE at 1465 immediately after it, three entities downstream of the call.

    PRD 3.9: "The fifth hop follows from the fourth: because `reserved_cents` fell, the program's `available_cents` is recomputed and the program moves `EXHAUSTED → ACTIVE` when the recomputed figure is above 0."

    Design: Difficulty/transitive_cascade/nonconforming_screening_cascades_to_patient_suspension_enrollment_pause_and_reservation_release
    """
    ctx = _three_kits_with_an_exhausted_program(api)
    assert_program_balances(
        read_program(api, ctx["sponsorship_program"]["id"]),
        reserved_cents=4395,
        committed_cents=0,
        available_cents=0,
        status="EXHAUSTED",
    )

    _screen_the_second_parcel(api, ctx)

    assert_program_balances(
        read_program(api, ctx["sponsorship_program"]["id"]),
        reserved_cents=2930,
        committed_cents=0,
        available_cents=1465,
        status="ACTIVE",
    )


# --------------------------------------------------------------------------
# The loss cascade: physical custody and money unwind together
# --------------------------------------------------------------------------
def _one_kit_in_transit_on_an_exhausted_program(api):
    """A single kit tendered and scanned IN_TRANSIT under a program whose ceiling is
    exactly that kit's reservation, so available_cents is 0 and the facility is
    holding 69 pending intake units."""
    ctx = setup_tendered_shipment(api, program_overrides=_ONE_KIT_PROGRAM)
    advance_transport(api, ctx, "IN_TRANSIT")
    return ctx


def test_06_a_loss_scan_is_terminal_on_the_transport_axis_alone(api):
    """The parcel goes to LOST, the conformance axis is left at UNSCREENED, and the
    frozen custody figure is still readable afterwards.

    PRD 3.6: "A loss scan is a four-hop cascade and the same cascade regardless of whether the parcel was `TENDERED` or `IN_TRANSIT` when it went missing. First the shipment's `transport_status` becomes `LOST`, which is terminal on that axis."
    PRD 3.6: "No transport event ever writes `conformance_status`."

    Design: Difficulty/transitive_cascade/shipment_lost_cascades_to_kit_void_reservation_release_and_program_unexhaust
    """
    ctx = _one_kit_in_transit_on_an_exhausted_program(api)

    advance_transport(api, ctx, "LOST")

    assert_shipment_axes(
        read_shipment(api, ctx["shipment"]["id"]),
        transport_status="LOST",
        conformance_status="UNSCREENED",
        custody_units=69,
    )


def test_07_the_second_hop_voids_both_the_kit_and_its_activated_label(api):
    """The kit is written off as SHIPMENT_LOST and the label that carried it is voided
    by the system, not by an operator.

    PRD 3.6: "Second, because the shipment became `LOST`, its kit moves from `SEALED` or `IN_TRANSIT` to `VOIDED` with `void_reason` set to `SHIPMENT_LOST`, and its return label moves `ACTIVATED → VOIDED` with `voided_at` set to the current logical-clock instant."

    Design: Difficulty/transitive_cascade/shipment_lost_cascades_to_kit_void_reservation_release_and_program_unexhaust
    """
    ctx = _one_kit_in_transit_on_an_exhausted_program(api)

    advance_transport(api, ctx, "LOST")

    assert_kit(
        read_kit(api, ctx["kit"]["id"]), status="VOIDED", void_reason="SHIPMENT_LOST"
    )
    label = read_return_label(api, ctx["return_label"]["id"])
    assert_return_label(label, status="VOIDED")
    assert label["voided_at"] is not None, "a system-voided label must record voided_at"


def test_08_the_facility_stops_expecting_the_parcel(api):
    """A lost parcel never arrives, so the booked units leave the pending queue and
    nothing is ever destroyed.

    PRD 3.6: "Third, because the kit became `VOIDED`, a `RESERVATION_RELEASE` ledger entry for the negation of the kit's `provisional_cost_cents` is appended, the program's `reserved_cents` falls by that amount, and the destination facility's `pending_intake_units` falls by exactly the shipment's `custody_units`."

    Design: Difficulty/transitive_cascade/shipment_lost_cascades_to_kit_void_reservation_release_and_program_unexhaust
    """
    ctx = _one_kit_in_transit_on_an_exhausted_program(api)
    assert_facility_counters(
        read_treatment_facility(api, ctx["treatment_facility"]["id"]),
        pending_intake_units=69,
    )

    advance_transport(api, ctx, "LOST")

    assert_facility_counters(
        read_treatment_facility(api, ctx["treatment_facility"]["id"]),
        pending_intake_units=0,
        destroyed_units_total=0,
        certificates_issued_count=0,
    )


def test_09_the_release_snapshots_the_un_exhausted_balances(api):
    """Two appends in the program's whole life: the reservation that took available_cents
    to 0 and the release that lifted it back to 1465, each snapshotting the balances as
    they stood right after the append.

    PRD 3.6: "Fourth, because `reserved_cents` fell, the program's `available_cents` is recomputed and the program moves `EXHAUSTED → ACTIVE` when the recomputed figure is above 0."
    PRD 2.9: "A program's `status` is a pure function of that figure: `ACTIVE` while `available_cents` is greater than zero, and `EXHAUSTED` at exactly zero."

    Design: Difficulty/transitive_cascade/shipment_lost_cascades_to_kit_void_reservation_release_and_program_unexhaust
    """
    ctx = _one_kit_in_transit_on_an_exhausted_program(api)
    assert_program_balances(
        read_program(api, ctx["sponsorship_program"]["id"]),
        reserved_cents=1465,
        available_cents=0,
        status="EXHAUSTED",
    )

    advance_transport(api, ctx, "LOST")

    entries = read_ledger_entries(api, ctx["sponsorship_program"]["id"])
    assert_ledger_sequence(
        entries, [(1, "RESERVATION", 1465), (2, "RESERVATION_RELEASE", -1465)]
    )
    assert_ledger_entry(entries[0], available_after_cents=0, reserved_after_cents=1465)
    assert_ledger_entry(entries[1], available_after_cents=1465, reserved_after_cents=0)
    assert_program_balances(
        read_program(api, ctx["sponsorship_program"]["id"]),
        reserved_cents=0,
        committed_cents=0,
        available_cents=1465,
        status="ACTIVE",
    )


def test_10_the_loss_cascade_never_reaches_the_patient_or_the_enrollment(api):
    """All four hops stay on the logistics and money side; the household is not
    penalised for a carrier's loss.

    PRD 3.6: "A loss scan is a four-hop cascade and the same cascade regardless of whether the parcel was `TENDERED` or `IN_TRANSIT` when it went missing."
    PRD 3.9: "A patient may be suspended either by the risk threshold above or by a `ProgramAdmin` supplying an `action` of `SUSPEND` with an optional `reason`; the patient must be `ENROLLED`, otherwise `ERR_INVALID_PATIENT_STATE`."

    Design: Difficulty/transitive_cascade/shipment_lost_cascades_to_kit_void_reservation_release_and_program_unexhaust
    """
    ctx = _one_kit_in_transit_on_an_exhausted_program(api)

    advance_transport(api, ctx, "LOST")

    assert_patient_risk(
        read_patient(api, ctx["patient"]["id"]), screening_risk_score=0, status="ENROLLED"
    )
    assert_enrollment(read_enrollment(api, ctx["enrollment"]["id"]), status="ACTIVE")
