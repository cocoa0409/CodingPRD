"""Two unwinds that must compensate exactly the quantity they touched and nothing
else: a kit void that reverses money through the append-only ledger, and a
return-to-patient remediation that gives back custody while keeping the money booked."""

from test_helpers import (
    ADMIN,
    assert_append_only_system_fields,
    assert_enrollment,
    assert_facility_counters,
    assert_kit,
    assert_ledger_entry,
    assert_ledger_sequence,
    assert_ledger_sequence_numbers_start_at_one,
    assert_non_conformance_event,
    assert_patient_risk,
    assert_program_balances,
    assert_return_label,
    assert_shipment_axes,
    assert_total_count,
    get_success_data,
    kit_void_payload,
    read_enrollment,
    read_kit,
    read_ledger_entries,
    read_non_conformance_event,
    read_patient,
    read_program,
    read_return_label,
    read_shipment,
    read_treatment_facility,
    remediate_for,
    setup_issued_kit,
    setup_notified_non_conformance,
)


def _normalised_instant(value):
    """Split an ISO 8601 UTC instant into its whole-second head and a
    three-digit fraction so that equality does not depend on how many
    fractional digits the serialiser chose to print."""
    assert isinstance(value, str) and value.endswith("Z"), (
        f"expected an ISO 8601 UTC instant, got {value!r}"
    )
    head, _, fraction = value[:-1].partition(".")
    return head, (fraction + "000")[:3]


# --------------------------------------------------------------------------
# Voiding an unopened kit: money reversed to the cent through the ledger
# --------------------------------------------------------------------------
def _an_issued_kit_then_voided(api):
    """One ONE_QUART kit is issued under a 500000-cent program, reserving 1465 cents,
    and is voided before the household ever acknowledges it."""
    ctx = setup_issued_kit(api)
    ctx["void_response"] = api.void_kit(
        ctx["kit"]["id"], kit_void_payload("patient changed therapy"), ADMIN
    )
    ctx["voided_kit"] = get_success_data(ctx["void_response"])
    return ctx


def test_01_the_voided_kit_keeps_the_provisional_figure_it_reserved(api):
    """The kit reaches its terminal `VOIDED` state carrying the supplied reason, and its
    `provisional_cost_cents` is left at 1465 — the void reverses the money in the ledger
    rather than by erasing the figure from the kit.

    PRD 3.5: "The kit moves to `VOIDED`, which is terminal, with the supplied reason stored in `void_reason`."
    PRD 2.9: "Sponsor money is never adjusted by direct assignment. Every movement is an append to an immutable ledger, and a program's balances are derived from those appends."

    Design: Difficulty/compensating_invariant/kit_void_restores_program_available_cents_exactly
    """
    ctx = _an_issued_kit_then_voided(api)

    assert_kit(
        read_kit(api, ctx["kit"]["id"]),
        status="VOIDED",
        provisional_cost_cents=1465,
        void_reason="patient changed therapy",
    )


def test_02_the_balance_triple_returns_to_the_untouched_ceiling(api):
    """`reserved_cents` falls back to 0, `committed_cents` never moved, and
    `available_cents` is recomputed to the full 500000 ceiling, so the program's status
    stays the pure function `ACTIVE`.

    PRD 3.5: "Accounting unwinds in the same request: a `RESERVATION_RELEASE` ledger entry for the negation of the kit's `provisional_cost_cents` is appended at the next `sequence_no`, the program's `reserved_cents` falls by that amount, and the program's `available_cents`, `kits_issued_count` and `status` are recomputed — the program moving `EXHAUSTED → ACTIVE` if the recomputed `available_cents` is above 0."
    PRD 2.9: "A program's `status` is a pure function of that figure: `ACTIVE` while `available_cents` is greater than zero, and `EXHAUSTED` at exactly zero."

    Design: Difficulty/compensating_invariant/kit_void_restores_program_available_cents_exactly
    """
    ctx = _an_issued_kit_then_voided(api)

    assert_program_balances(
        read_program(api, ctx["sponsorship_program"]["id"]),
        reserved_cents=0,
        committed_cents=0,
        available_cents=500000,
        funding_ceiling_cents=500000,
        status="ACTIVE",
    )


def test_03_the_reservation_row_survives_and_an_equal_and_opposite_row_joins_it(api):
    """Two rows exist in `sequence_no` order: the original +1465 `RESERVATION` is still
    there untouched, and the compensation is a separate -1465 `RESERVATION_RELEASE`
    appended at the next number rather than an edit or a deletion.

    PRD 2.9: "On the program side, `reserved_cents` is the sum of `RESERVATION` amounts less the sum of `RESERVATION_RELEASE` amounts over that program's entries, and `committed_cents` is the sum of `COMMITMENT` amounts less the sum of `COMMITMENT_REVERSAL` amounts."
    PRD 2.9: "Each entry also carries a `sequence_no`, a per-program monotonic counter starting at 1, which pins the relative order of appends made in the same request or at the same clock instant; ledger listings are returned in `sequence_no` ascending order."

    Design: Difficulty/compensating_invariant/kit_void_restores_program_available_cents_exactly
    """
    ctx = _an_issued_kit_then_voided(api)

    entries = read_ledger_entries(api, ctx["sponsorship_program"]["id"])
    assert_ledger_sequence_numbers_start_at_one(entries)
    assert_ledger_sequence(
        entries,
        [(1, "RESERVATION", 1465), (2, "RESERVATION_RELEASE", -1465)],
    )


def test_04_each_row_snapshots_the_balances_that_stood_right_after_its_own_append(api):
    """The running snapshots walk 1465 reserved / 498535 available and then back to
    0 reserved / 500000 available, which is how a reader reconstructs the reversal
    without recomputing anything from scratch.

    PRD 2.9: "each entry snapshots the three program balances as they stood immediately after the append, in `reserved_after_cents`, `committed_after_cents` and `available_after_cents`"
    PRD 2.9: "`available_cents` is `funding_ceiling_cents` less `reserved_cents` less `committed_cents`, recomputed after every append."

    Design: Difficulty/compensating_invariant/kit_void_restores_program_available_cents_exactly
    """
    ctx = _an_issued_kit_then_voided(api)

    entries = read_ledger_entries(api, ctx["sponsorship_program"]["id"])
    assert_ledger_entry(
        entries[0],
        entry_type="RESERVATION",
        amount_cents=1465,
        sequence_no=1,
        reserved_after_cents=1465,
        committed_after_cents=0,
        available_after_cents=498535,
        kit_id=ctx["kit"]["id"],
    )
    assert_ledger_entry(
        entries[1],
        entry_type="RESERVATION_RELEASE",
        amount_cents=-1465,
        sequence_no=2,
        reserved_after_cents=0,
        committed_after_cents=0,
        available_after_cents=500000,
        kit_id=ctx["kit"]["id"],
    )


def test_05_the_kit_s_own_two_signed_amounts_sum_to_zero_on_immutable_rows(api, program_admin_headers):
    """Filtering the ledger by `kit_id` returns exactly the pair, their signed amounts
    cancel to 0, and neither row carries `updated_at` or `version` because the ledger is
    append-only.

    PRD 2.9: "carries a signed `amount_cents` — positive for a reservation or a commitment, negative for either reversal, and signed exactly as submitted for a funding adjustment"
    PRD 3.2: "They are the audit trail of every cent the program has moved, and because they are append-only they carry neither `updated_at` nor `version`."

    Design: Difficulty/compensating_invariant/kit_void_restores_program_available_cents_exactly
    """
    ctx = _an_issued_kit_then_voided(api)

    rows, _ = assert_total_count(
        api.list_ledger_entries(program_admin_headers, {"kit_id": ctx["kit"]["id"]}), 2
    )
    assert sum(row["amount_cents"] for row in rows) == 0
    for row in rows:
        assert_append_only_system_fields(row)


def test_06_the_void_frees_the_enrollment_s_authorization_slot(api):
    """`kits_issued` is recomputed over the enrollment's non-voided kits, so the single
    voided kit brings the count back to 0.

    PRD 3.5: "The enrollment's `kits_issued` is recomputed as well, which is what frees an authorization slot."

    Design: Difficulty/compensating_invariant/kit_void_restores_program_available_cents_exactly
    """
    ctx = _an_issued_kit_then_voided(api)

    assert_enrollment(read_enrollment(api, ctx["enrollment"]["id"]), kits_issued=0)


# --------------------------------------------------------------------------
# Mailing a rejected parcel back: custody unwound, money deliberately not
# --------------------------------------------------------------------------
def _a_rejected_parcel_mailed_back_to_the_household(api):
    """A 69-unit parcel is delivered to the 1000-unit CA facility, screened
    NON_CONFORMING for LOOSE_SHARPS_IN_BOX, the customer notified by EMAIL, and the
    rejection then resolved by mailing the container back to the patient."""
    ctx = setup_notified_non_conformance(
        api, reason_code="LOOSE_SHARPS_IN_BOX", notification_channel="EMAIL"
    )
    remediate_for(api, ctx, "RETURN_TO_PATIENT")
    return ctx


def test_07_the_facility_gives_back_exactly_the_units_the_activation_booked(api):
    """The 69 units activation booked come straight back off `pending_intake_units`,
    while the destruction counters stay at 0 because nothing was destroyed here.

    PRD 3.7: "`RETURN_TO_PATIENT` sends the parcel back: the kit moves `RECEIVED → RETURNED_TO_PATIENT` with its `version` incremented by 1, the facility's `pending_intake_units` falls by exactly the shipment's `custody_units`, and the shipment's return label moves `ACTIVATED → VOIDED` with `voided_at` set to the current logical-clock instant, which starts the label's 24-hour quarantine on that kit."
    PRD 3.6: "Those three exclusions are precisely the situations in which the units have stopped being the facility's problem: a lost parcel never arrives, a certified-destroyed parcel is gone, and a returned parcel has gone back to the household."

    Design: Difficulty/compensating_invariant/return_to_patient_remediation_restores_facility_pending_intake_units
    """
    ctx = _a_rejected_parcel_mailed_back_to_the_household(api)

    assert_facility_counters(
        read_treatment_facility(api, ctx["treatment_facility"]["id"]),
        pending_intake_units=0,
        destroyed_units_total=0,
        certificates_issued_count=0,
    )


def test_08_the_shipment_s_frozen_custody_figure_is_not_rewritten_by_the_unwind(api):
    """`custody_units` stays at the 69 it froze at tender even though the facility no
    longer holds them, and only the conformance axis moves while transport stays
    `DELIVERED`.

    PRD 3.6: "freezing `custody_units` to the kit's `fill_units` as of this instant — a value that never changes afterwards, whatever happens to the kit"
    PRD 3.7: "Whichever action is chosen, the event moves `CUSTOMER_NOTIFIED → RESOLVED` with the chosen `remediation_action` stored, the shipment's conformance axis moves `NON_CONFORMING → REMEDIATED` while `transport_status` stays `DELIVERED`, and both records have their `version` incremented by 1."

    Design: Difficulty/compensating_invariant/return_to_patient_remediation_restores_facility_pending_intake_units
    """
    ctx = _a_rejected_parcel_mailed_back_to_the_household(api)

    assert_shipment_axes(
        read_shipment(api, ctx["shipment"]["id"]),
        transport_status="DELIVERED",
        conformance_status="REMEDIATED",
        custody_units=69,
    )
    assert_non_conformance_event(
        read_non_conformance_event(api, ctx["non_conformance_event"]["id"]),
        status="RESOLVED",
        reason_code="LOOSE_SHARPS_IN_BOX",
        remediation_action="RETURN_TO_PATIENT",
    )


def test_09_the_kit_is_still_alive_so_the_reservation_is_deliberately_not_released(api, program_admin_headers):
    """The compensation is partial by design: the return-to-patient consequence list
    touches the kit, the facility and the label and appends no ledger row at all, so the
    1465 cents stay reserved, nothing is committed, and the single issuance row is the
    program's whole ledger.

    PRD 3.7: "`RETURN_TO_PATIENT` sends the parcel back: the kit moves `RECEIVED → RETURNED_TO_PATIENT` with its `version` incremented by 1, the facility's `pending_intake_units` falls by exactly the shipment's `custody_units`, and the shipment's return label moves `ACTIVATED → VOIDED` with `voided_at` set to the current logical-clock instant, which starts the label's 24-hour quarantine on that kit."
    PRD 2.9: "Sponsor money is never adjusted by direct assignment. Every movement is an append to an immutable ledger, and a program's balances are derived from those appends."

    Design: Difficulty/compensating_invariant/return_to_patient_remediation_restores_facility_pending_intake_units
    """
    ctx = _a_rejected_parcel_mailed_back_to_the_household(api)

    assert_program_balances(
        read_program(api, ctx["sponsorship_program"]["id"]),
        reserved_cents=1465,
        committed_cents=0,
        available_cents=498535,
        funding_ceiling_cents=500000,
        status="ACTIVE",
    )
    assert_total_count(
        api.list_ledger_entries(
            program_admin_headers,
            {"sponsorship_program_id": ctx["sponsorship_program"]["id"]},
        ),
        1,
    )


def test_10_the_container_goes_home_with_its_declared_contents_and_a_dead_label(api):
    """The kit moves `RECEIVED → RETURNED_TO_PATIENT` still carrying the 69 units the
    patient declared, and the label that carried it is voided, which is what starts the
    quarantine before a replacement label can be printed.

    PRD 3.7: "The kit is no longer certifiable, and the household's next receipt acknowledgement will carry it back to `ACTIVE_FILLING`."
    PRD 3.7: "`RETURN_TO_PATIENT` sends the parcel back: the kit moves `RECEIVED → RETURNED_TO_PATIENT` with its `version` incremented by 1, the facility's `pending_intake_units` falls by exactly the shipment's `custody_units`, and the shipment's return label moves `ACTIVATED → VOIDED` with `voided_at` set to the current logical-clock instant, which starts the label's 24-hour quarantine on that kit."

    Design: Difficulty/compensating_invariant/return_to_patient_remediation_restores_facility_pending_intake_units
    """
    ctx = _a_rejected_parcel_mailed_back_to_the_household(api)

    assert_kit(read_kit(api, ctx["kit"]["id"]), status="RETURNED_TO_PATIENT", fill_units=69)

    label = read_return_label(api, ctx["return_label"]["id"])
    assert_return_label(label, status="VOIDED")
    assert _normalised_instant(label["voided_at"]) == _normalised_instant("2026-08-01T00:00:00Z")


def test_11_a_forty_five_point_rejection_stays_under_the_suspension_threshold(api):
    """`LOOSE_SHARPS_IN_BOX` weighs 45 and the event is brand new, so the recomputed
    screening score is 45 — short of 60 — and the patient is left `ENROLLED`.

    PRD 3.9: "Each event contributes a weight determined by its `reason_code`: `LOOSE_SHARPS_IN_BOX` weighs 45, `UNAPPROVED_WASTE_TYPE` weighs 40, `UNSEALED_CONTAINER` weighs 30, `OVERFILLED_CONTAINER` weighs 25, `WEIGHT_EXCEEDS_SPEC` weighs 20 and `MISSING_ABSORBENT` weighs 15."
    PRD 3.7: "Third, and only when that recomputed score reaches at least 60 while the patient is `ENROLLED`, the patient is suspended, which is itself a multi-hop cascade covered in §3.9."

    Design: Difficulty/compensating_invariant/return_to_patient_remediation_restores_facility_pending_intake_units
    """
    ctx = _a_rejected_parcel_mailed_back_to_the_household(api)

    assert_patient_risk(
        read_patient(api, ctx["patient"]["id"]),
        screening_risk_score=45,
        status="ENROLLED",
        suspended_at=None,
    )
