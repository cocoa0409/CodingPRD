"""Illegal transitions, replayed transitions and double-void terminals.

Each family here drives an entity into one state and then fires a trigger that is
only legal from some other state, checking both the entity-specific refusal and
that the refusal left nothing behind.
"""

import pytest

from test_helpers import (
    assert_certificate,
    assert_enrollment,
    assert_facility_counters,
    assert_kit,
    assert_patient_risk,
    assert_program_balances,
    assert_return_label,
    assert_shipment_axes,
    assert_total_count,
    certificate_void_payload,
    create_california_rule,
    create_patient,
    eligibility_review_payload,
    get_success_data,
    label_activation_payload,
    label_void_payload,
    make_destruction_officer_headers,
    make_logistics_coordinator_headers,
    make_program_admin_headers,
    make_sponsor_representative_headers,
    read_destruction_certificate,
    read_enrollment,
    read_kit,
    read_patient,
    read_program,
    read_return_label,
    read_shipment,
    read_treatment_facility,
    seal_payload,
    set_clock,
    setup_filling_kit,
    setup_issued_certificate,
    setup_tendered_shipment,
    sponsor_decision_payload,
    status_action_payload,
    transport_event_payload,
    validate_error,
)

ADMIN = make_program_admin_headers()
LOGISTICS = make_logistics_coordinator_headers()
VOID_REASON = "destroyed unit count mis-keyed at the scale"


# --------------------------------------------------------------------------
# Shared context builders
# --------------------------------------------------------------------------
def _tendered_shipment(api):
    """A SEALED kit of 60 units whose ACTIVATED label produced a TENDERED /
    UNSCREENED shipment booked into the facility."""
    return setup_tendered_shipment(
        api,
        patient_overrides={"weekly_sharps_count": 20},
        enrollment_overrides={"cadence_days": 30, "kits_authorized": 3},
        fill_units=60,
        sealed_gross_weight_grams=1200,
        scheduled_intake_date="2026-08-10",
        declared_gross_weight_grams=1200,
    )


def _filling_kit(api):
    """An ENROLLED patient on an ACTIVE enrollment whose only kit has been
    acknowledged and is ACTIVE_FILLING."""
    return setup_filling_kit(
        api,
        patient_overrides={"weekly_sharps_count": 20},
        enrollment_overrides={"cadence_days": 30, "kits_authorized": 3},
    )


def _voided_certificate(api):
    """A settled kit whose destruction certificate has been voided once, leaving
    the certificate in the terminal VOIDED state."""
    ctx = setup_issued_certificate(
        api,
        patient_overrides={"weekly_sharps_count": 20},
        enrollment_overrides={"cadence_days": 30, "kits_authorized": 3},
        fill_units=60,
        sealed_gross_weight_grams=1200,
        declared_gross_weight_grams=1200,
        observed_gross_weight_grams=1200,
        destroyed_units=60,
    )
    ctx["voided_certificate"] = get_success_data(
        api.void_destruction_certificate(
            ctx["destruction_certificate"]["id"],
            certificate_void_payload(VOID_REASON),
            make_destruction_officer_headers(),
        )
    )
    return ctx


# --------------------------------------------------------------------------
# Triggers that are illegal from the state the entity is actually in
# --------------------------------------------------------------------------
def _submit_an_active_enrollment(api, ctx):
    return api.submit_enrollment(ctx["enrollment"]["id"], ADMIN)


def _acknowledge_receipt_again(api, ctx):
    return api.acknowledge_kit_receipt(ctx["kit"]["id"], ADMIN)


def _seal_an_already_sealed_kit(api, ctx):
    return api.seal_kit(
        ctx["kit"]["id"],
        seal_payload(fill_units=70, sealed_gross_weight_grams=1300),
        ADMIN,
    )


def _activate_an_activated_label(api, ctx):
    return api.activate_return_label(
        ctx["return_label"]["id"],
        label_activation_payload(
            ctx["treatment_facility"]["id"],
            scheduled_intake_date="2026-08-11",
            declared_gross_weight_grams=1200,
        ),
        LOGISTICS,
    )


def _void_an_activated_label(api, ctx):
    return api.void_return_label(
        ctx["return_label"]["id"], label_void_payload("operator changed their mind"), LOGISTICS
    )


def _deliver_a_tendered_shipment(api, ctx):
    return api.record_transport_event(
        ctx["shipment"]["id"], transport_event_payload("DELIVERED"), LOGISTICS
    )


ILLEGAL_TRIGGERS = [
    ("submit_an_active_enrollment", _submit_an_active_enrollment, "ERR_INVALID_ENROLLMENT_STATE"),
    ("acknowledge_a_sealed_kit", _acknowledge_receipt_again, "ERR_INVALID_KIT_STATE"),
    ("seal_a_sealed_kit", _seal_an_already_sealed_kit, "ERR_INVALID_KIT_STATE"),
    ("activate_an_activated_label", _activate_an_activated_label, "ERR_INVALID_LABEL_STATE"),
    ("void_an_activated_label", _void_an_activated_label, "ERR_INVALID_LABEL_STATE"),
    ("deliver_a_tendered_shipment", _deliver_a_tendered_shipment, "ERR_INVALID_SHIPMENT_STATE"),
]


@pytest.mark.parametrize(
    "trigger,expected_error_id",
    [(trigger, error_id) for _, trigger, error_id in ILLEGAL_TRIGGERS],
    ids=[name for name, _, _ in ILLEGAL_TRIGGERS],
)
def test_01_each_entity_refuses_a_trigger_that_is_illegal_from_its_current_state(
    api, trigger, expected_error_id
):
    """From one shared position — ACTIVE enrollment, SEALED kit, ACTIVATED label,
    TENDERED shipment — each trigger names the entity whose state blocked it.

    PRD 2.6: "Within the state-precondition band the sub-order is also fixed: enrollment state (`ERR_INVALID_ENROLLMENT_STATE`), then patient state (`ERR_INVALID_PATIENT_STATE`), then kit state (`ERR_INVALID_KIT_STATE`), then return-label state (`ERR_INVALID_LABEL_STATE`), then shipment state (`ERR_INVALID_SHIPMENT_STATE`), then non-conformance-event state (`ERR_INVALID_NONCONFORMANCE_STATE`), then certificate state (`ERR_INVALID_CERTIFICATE_STATE`)."
    PRD 2.6: "All seven carry HTTP 409."
    PRD 3.3: "It moves the enrollment `DRAFT → PENDING_SPONSOR_APPROVAL` and increments the enrollment's `version` by 1, and it requires three things at once: the enrollment must be in `DRAFT`, otherwise `ERR_INVALID_ENROLLMENT_STATE`; the patient must be in `ELIGIBLE` or `ENROLLED`, otherwise `ERR_INVALID_PATIENT_STATE`; and the funding sponsor must be `ACTIVE`, otherwise `ERR_SPONSOR_NOT_ACTIVE`."
    PRD 3.5: "It is legal from `ISSUED` and also from `RETURNED_TO_PATIENT`, and from any other kit state it is refused with `ERR_INVALID_KIT_STATE`; the kit's enrollment must additionally be `ACTIVE`, a paused or terminated enrollment producing `ERR_INVALID_ENROLLMENT_STATE`."
    PRD 3.5: "Then the kit must be in `ACTIVE_FILLING`, otherwise `ERR_INVALID_KIT_STATE`."
    PRD 3.6: "The label must be `PRINTED`, otherwise `ERR_INVALID_LABEL_STATE`; a facility `treatment_facility_id` that matches nothing yields `ERR_FACILITY_NOT_FOUND`."
    PRD 3.6: "Manual voiding is only ever legal from `PRINTED`: an `ACTIVATED` label is voided exclusively by the system, as a consequence of a return-to-patient remediation or a lost parcel, and an attempt to void an `ACTIVATED` or already-`VOIDED` label returns `ERR_INVALID_LABEL_STATE`."
    PRD 3.6: "Legality is judged against the transport axis alone: `IN_TRANSIT` requires the shipment to be `TENDERED`, `DELIVERED` requires it to be `IN_TRANSIT`, and `LOST` is legal from either `TENDERED` or `IN_TRANSIT`."
    PRD 3.6: "An illegal combination returns `ERR_INVALID_SHIPMENT_STATE` (HTTP 409)."
    Design: Corner/state_machines/triggers_illegal_from_the_current_state_are_rejected_per_entity_with_no_side_effects
    """
    ctx = _tendered_shipment(api)
    validate_error(trigger(api, ctx), expected_error_id, expected_status=409)


def test_02_the_refused_triggers_leave_the_kit_label_and_shipment_exactly_as_they_were(api):
    """Firing every illegal trigger in turn is a no-op: the kit is still SEALED,
    the label still ACTIVATED and unvoided, and the shipment's two axes and the
    facility's booking are untouched.

    PRD 2.6: "Within the state-precondition band the sub-order is also fixed: enrollment state (`ERR_INVALID_ENROLLMENT_STATE`), then patient state (`ERR_INVALID_PATIENT_STATE`), then kit state (`ERR_INVALID_KIT_STATE`), then return-label state (`ERR_INVALID_LABEL_STATE`), then shipment state (`ERR_INVALID_SHIPMENT_STATE`), then non-conformance-event state (`ERR_INVALID_NONCONFORMANCE_STATE`), then certificate state (`ERR_INVALID_CERTIFICATE_STATE`)."
    PRD 3.6: "The kit itself stays `SEALED`: it does not advance until the carrier's first scan."
    PRD 3.6: "The label moves `PRINTED → ACTIVATED` with `activated_at` set to the current logical-clock instant and its `version` incremented by 1."
    PRD 3.6: "Its two axes start at `transport_status` `TENDERED` and `conformance_status` `UNSCREENED`, with `observed_gross_weight_grams`, `delivered_at` and `screened_by_user_id` all null."
    PRD 3.6: "The destination facility's `pending_intake_units` rises by the new shipment's `custody_units`."
    Design: Corner/state_machines/triggers_illegal_from_the_current_state_are_rejected_per_entity_with_no_side_effects
    """
    ctx = _tendered_shipment(api)
    kit_version_before = read_kit(api, ctx["kit"]["id"])["version"]
    label_version_before = read_return_label(api, ctx["return_label"]["id"])["version"]
    shipment_version_before = read_shipment(api, ctx["shipment"]["id"])["version"]

    for _name, trigger, expected_error_id in ILLEGAL_TRIGGERS:
        validate_error(trigger(api, ctx), expected_error_id, expected_status=409)

    kit = read_kit(api, ctx["kit"]["id"])
    assert_kit(kit, status="SEALED", fill_units=60, void_reason=None)
    assert kit["version"] == kit_version_before, (
        f"A refused trigger must not bump the kit version, got {kit['version']}"
    )

    label = read_return_label(api, ctx["return_label"]["id"])
    assert_return_label(label, status="ACTIVATED", voided_at=None)
    assert label["version"] == label_version_before, (
        f"A refused trigger must not bump the label version, got {label['version']}"
    )

    shipment = read_shipment(api, ctx["shipment"]["id"])
    assert_shipment_axes(
        shipment,
        transport_status="TENDERED",
        conformance_status="UNSCREENED",
        custody_units=60,
        screened_by_user_id=None,
    )
    assert shipment["observed_gross_weight_grams"] is None, (
        "An unscreened shipment carries no observed weight"
    )
    assert shipment["delivered_at"] is None, (
        "A shipment that was never delivered carries no delivered_at"
    )
    assert shipment["version"] == shipment_version_before, (
        f"A refused trigger must not bump the shipment version, got {shipment['version']}"
    )

    assert_facility_counters(
        read_treatment_facility(api, ctx["treatment_facility"]["id"]),
        pending_intake_units=60,
        destroyed_units_total=0,
        certificates_issued_count=0,
        status="ACTIVE",
    )


# --------------------------------------------------------------------------
# A terminal INELIGIBLE patient refuses every further status action
# --------------------------------------------------------------------------
def _ineligible_patient(api):
    """A patient whose eligibility review was denied, leaving them in the terminal
    INELIGIBLE state."""
    set_clock(api)
    state_rule = create_california_rule(api)
    patient = create_patient(api, state_rule["id"], weekly_sharps_count=20)
    return get_success_data(
        api.review_patient_eligibility(
            patient["id"],
            eligibility_review_payload("DENY", note="no permitted mail-back pathway"),
            ADMIN,
        )
    )


def _review_the_patient_again(api, patient_id):
    return api.review_patient_eligibility(
        patient_id, eligibility_review_payload("APPROVE"), ADMIN
    )


def _withdraw_the_patient(api, patient_id):
    return api.patient_status_action(
        patient_id, status_action_payload("WITHDRAW", reason="housekeeping"), ADMIN
    )


def _reinstate_the_patient(api, patient_id):
    return api.patient_status_action(patient_id, status_action_payload("REINSTATE"), ADMIN)


TERMINAL_PATIENT_TRIGGERS = [
    ("review_an_already_decided_patient", _review_the_patient_again),
    ("withdraw_an_ineligible_patient", _withdraw_the_patient),
    ("reinstate_an_ineligible_patient", _reinstate_the_patient),
]


@pytest.mark.parametrize(
    "trigger",
    [trigger for _, trigger in TERMINAL_PATIENT_TRIGGERS],
    ids=[name for name, _ in TERMINAL_PATIENT_TRIGGERS],
)
def test_03_a_terminal_ineligible_patient_refuses_every_further_status_action(api, trigger):
    """INELIGIBLE is not in the legal source set of any patient trigger, so a
    second review, a withdrawal and a reinstatement all land on the same refusal.

    PRD 3.3: "`DENY` moves the patient `PENDING_ELIGIBILITY → INELIGIBLE` and likewise increments `version` by 1, but `INELIGIBLE` is terminal and permanently forecloses enrollment: no enrollment may ever be created for that patient afterwards."
    PRD 3.3: "A `ProgramAdmin` records the determination by supplying a `decision` of `APPROVE` or `DENY` with an optional `note`, and the patient must be in `PENDING_ELIGIBILITY` for either branch to be legal — a second review attempt on an already-decided patient is refused with `ERR_INVALID_PATIENT_STATE`."
    PRD 3.9: "**Withdrawal** takes an `action` of `WITHDRAW` with an optional `reason` and is legal from `ELIGIBLE`, `ENROLLED` or `SUSPENDED`; attempted from `PENDING_ELIGIBILITY`, `INELIGIBLE` or `WITHDRAWN` it returns `ERR_INVALID_PATIENT_STATE`."
    PRD 3.9: "**Reinstatement** takes an `action` of `REINSTATE` and requires the patient to be `SUSPENDED`, otherwise `ERR_INVALID_PATIENT_STATE`."
    PRD 2.6: "All seven carry HTTP 409."
    Design: Corner/state_machines/terminal_ineligible_patient_rejects_every_further_status_action
    """
    patient = _ineligible_patient(api)
    validate_error(
        trigger(api, patient["id"]), "ERR_INVALID_PATIENT_STATE", expected_status=409
    )


def test_04_the_terminal_ineligible_patient_row_never_changes_version(api):
    """A record that has reached a terminal state is never re-transitioned, so
    after all three refusals the row still reads exactly as the denial left it.

    PRD 3.3: "`DENY` moves the patient `PENDING_ELIGIBILITY → INELIGIBLE` and likewise increments `version` by 1, but `INELIGIBLE` is terminal and permanently forecloses enrollment: no enrollment may ever be created for that patient afterwards."
    PRD 2.8: "Two general principles apply throughout: a record that has already reached a terminal state is never re-transitioned, and a cascade never skips a hop merely because the hop's effect happens to be a no-op for the data at hand."
    PRD 2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC instant refreshed on every mutation of that row, and `version`, an integer that begins at 1 when the row is created and increments by exactly 1 on every mutation."
    Design: Corner/state_machines/terminal_ineligible_patient_rejects_every_further_status_action
    """
    patient = _ineligible_patient(api)
    assert patient["version"] == 2, (
        f"The denial is the patient's only mutation, so version must be 2, got "
        f"{patient['version']}"
    )

    for _name, trigger in TERMINAL_PATIENT_TRIGGERS:
        validate_error(
            trigger(api, patient["id"]), "ERR_INVALID_PATIENT_STATE", expected_status=409
        )

    reread = read_patient(api, patient["id"])
    assert_patient_risk(
        reread,
        screening_risk_score=0,
        audit_risk_score=0,
        status="INELIGIBLE",
        suspended_at=None,
    )
    assert reread["version"] == 2, (
        f"Refused triggers must not mutate the terminal row, got version "
        f"{reread['version']}"
    )


# --------------------------------------------------------------------------
# Replaying a transition that already fired
# --------------------------------------------------------------------------
def _replay_the_eligibility_approval(api, ctx):
    return api.review_patient_eligibility(
        ctx["patient"]["id"], eligibility_review_payload("APPROVE"), ADMIN
    )


def _replay_the_sponsor_approval(api, ctx):
    return api.record_sponsor_decision(
        ctx["enrollment"]["id"],
        sponsor_decision_payload("APPROVE"),
        make_sponsor_representative_headers(ctx["sponsor"]["id"]),
    )


REPLAY_TRIGGERS = [
    ("eligibility_approval", _replay_the_eligibility_approval, "ERR_INVALID_PATIENT_STATE"),
    ("enrollment_submission", _submit_an_active_enrollment, "ERR_INVALID_ENROLLMENT_STATE"),
    ("sponsor_approval", _replay_the_sponsor_approval, "ERR_INVALID_ENROLLMENT_STATE"),
    ("receipt_acknowledgement", _acknowledge_receipt_again, "ERR_INVALID_KIT_STATE"),
]


@pytest.mark.parametrize(
    "trigger,expected_error_id",
    [(trigger, error_id) for _, trigger, error_id in REPLAY_TRIGGERS],
    ids=[name for name, _, _ in REPLAY_TRIGGERS],
)
def test_05_replaying_a_transition_that_already_fired_returns_the_entity_specific_error(
    api, trigger, expected_error_id
):
    """Each hop of the intake chain has already fired once, so replaying it is
    refused by the state of whichever entity the hop reads first.

    PRD 3.3: "A `ProgramAdmin` records the determination by supplying a `decision` of `APPROVE` or `DENY` with an optional `note`, and the patient must be in `PENDING_ELIGIBILITY` for either branch to be legal — a second review attempt on an already-decided patient is refused with `ERR_INVALID_PATIENT_STATE`."
    PRD 3.3: "It moves the enrollment `DRAFT → PENDING_SPONSOR_APPROVAL` and increments the enrollment's `version` by 1, and it requires three things at once: the enrollment must be in `DRAFT`, otherwise `ERR_INVALID_ENROLLMENT_STATE`; the patient must be in `ELIGIBLE` or `ENROLLED`, otherwise `ERR_INVALID_PATIENT_STATE`; and the funding sponsor must be `ACTIVE`, otherwise `ERR_SPONSOR_NOT_ACTIVE`."
    PRD 3.3: "Both branches require the enrollment to be in `PENDING_SPONSOR_APPROVAL` — otherwise `ERR_INVALID_ENROLLMENT_STATE` — and both require that the acting `X-User-ID` equal the `sponsor_id` of the program the enrollment is bound to, a mismatch producing `ERR_NOT_RESOURCE_OWNER`."
    PRD 3.5: "It is legal from `ISSUED` and also from `RETURNED_TO_PATIENT`, and from any other kit state it is refused with `ERR_INVALID_KIT_STATE`; the kit's enrollment must additionally be `ACTIVE`, a paused or terminated enrollment producing `ERR_INVALID_ENROLLMENT_STATE`."
    PRD 2.6: "All seven carry HTTP 409."
    Design: Corner/state_machines/replaying_a_transition_that_already_fired_returns_the_entity_specific_state_error
    """
    ctx = _filling_kit(api)
    validate_error(trigger(api, ctx), expected_error_id, expected_status=409)


def test_06_the_replayed_transitions_leave_the_patient_enrollment_and_kit_unmoved(api):
    """Replaying all four hops changes nothing: the patient is still ENROLLED, the
    enrollment still ACTIVE at the version its kit issuance left it, and the kit
    still ACTIVE_FILLING at the version its acknowledgement left it.

    PRD 2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC instant refreshed on every mutation of that row, and `version`, an integer that begins at 1 when the row is created and increments by exactly 1 on every mutation."
    PRD 3.3: "The new enrollment starts at `DRAFT` with `kits_issued` at 0, `next_autoship_due_date` null, `activated_at` null, `sponsor_decision_note` null and `version` at 1."
    PRD 3.3: "On success `APPROVE` moves the enrollment `PENDING_SPONSOR_APPROVAL → ACTIVE`, sets `activated_at` to the current logical-clock instant, copies the submitted note into `sponsor_decision_note`, sets `next_autoship_due_date` to the current logical-clock UTC date so that the enrollment is immediately due for its first replacement container, and cascades the patient `ELIGIBLE → ENROLLED` with the patient's own `version` incremented by 1 — a child activation driving the parent forward."
    PRD 3.4: "*Fifth*, the enrollment's `next_autoship_due_date` is set to the UTC calendar date of `issued_at` advanced by `cadence_days`, its `kits_issued` is recomputed, and its `version` is incremented by 1."
    PRD 3.5: "Either way the kit's `acknowledged_at` is set to the current logical-clock instant, refreshing whatever value it already held, and the kit's `version` is incremented by 1."
    Design: Corner/state_machines/replaying_a_transition_that_already_fired_returns_the_entity_specific_state_error
    """
    ctx = _filling_kit(api)
    for _name, trigger, expected_error_id in REPLAY_TRIGGERS:
        validate_error(trigger(api, ctx), expected_error_id, expected_status=409)

    assert_patient_risk(read_patient(api, ctx["patient"]["id"]), status="ENROLLED")

    enrollment = read_enrollment(api, ctx["enrollment"]["id"])
    assert_enrollment(enrollment, status="ACTIVE", kits_issued=1, version=4)

    kit = read_kit(api, ctx["kit"]["id"])
    assert_kit(kit, status="ACTIVE_FILLING", fill_units=0, void_reason=None)
    assert kit["version"] == 2, (
        f"The acknowledgement is the kit's only mutation, so version must be 2, got "
        f"{kit['version']}"
    )


def test_07_the_replays_do_not_duplicate_the_reservation_or_the_kit(api):
    """The refused replays append no second reservation and mint no second kit, so
    the program's reserved figure and its ledger stay single-entry.

    PRD 3.4: "*Third*, a `RESERVATION` ledger entry for the positive `provisional_cost_cents` is appended at the next `sequence_no` and the program's `reserved_cents` rises by that amount."
    PRD 3.4: "`ONE_QUART` holds 0.9 litres, 100 units, and costs 1450 cents."
    PRD 3.4: "The base component is the catalogue's `unit_cost_cents` for the selected size."
    PRD 3.4: "The transport component estimates weight from capacity rather than from any actual fill: the container's `capacity_units` is multiplied by 4 grams per unit to give an estimated gram weight, that figure is multiplied by the transport rate of 38 cents per kilogram and divided by 1000 to convert grams to kilograms, and the result is rounded half up to a whole cent."
    PRD 3.4: "`provisional_cost_cents` is the base component plus that rounded transport component."
    PRD 3.4: "Kits are readable individually and as a list, filterable by `enrollment_id`, by `supersedes_kit_id` to walk the replacement chain, by `auto_ship_run_id` to see what a checkpoint produced, or by `status`."
    PRD 3.2: "Ledger entries are readable individually and as a list filtered by `sponsorship_program_id`, `kit_id` or `entry_type`, always in `sequence_no` ascending order."
    Design: Corner/state_machines/replaying_a_transition_that_already_fired_returns_the_entity_specific_state_error
    """
    ctx = _filling_kit(api)
    for _name, trigger, expected_error_id in REPLAY_TRIGGERS:
        validate_error(trigger(api, ctx), expected_error_id, expected_status=409)

    program = read_program(api, ctx["sponsorship_program"]["id"])
    assert_program_balances(
        program,
        reserved_cents=1465,
        committed_cents=0,
        available_cents=498535,
        funding_ceiling_cents=500000,
        status="ACTIVE",
    )
    assert program["kits_issued_count"] == 1, (
        f"Only one kit was ever issued, got kits_issued_count "
        f"{program['kits_issued_count']}"
    )
    assert_total_count(
        api.list_ledger_entries(
            ADMIN, {"sponsorship_program_id": ctx["sponsorship_program"]["id"]}
        ),
        1,
    )
    assert_total_count(
        api.list_kits(ADMIN, {"enrollment_id": ctx["enrollment"]["id"]}), 1
    )


# --------------------------------------------------------------------------
# A voided certificate is terminal and cannot be voided again
# --------------------------------------------------------------------------
def test_08_a_voided_certificate_cannot_be_voided_a_second_time(api):
    """VOIDED is terminal for a certificate, so the second void is refused and the
    row keeps the first void's reason and version.

    PRD 3.8: "The certificate must be in status `ISSUED`; voiding an already-`VOIDED` certificate returns `ERR_INVALID_CERTIFICATE_STATE` (HTTP 409)."
    PRD 3.8: "The certificate moves `ISSUED → VOIDED` with `voided_at` set to the current logical-clock instant and the supplied reason stored in `void_reason`."
    PRD 2.8: "Two general principles apply throughout: a record that has already reached a terminal state is never re-transitioned, and a cascade never skips a hop merely because the hop's effect happens to be a no-op for the data at hand."
    Design: Corner/state_machines/terminal_certificate_cannot_be_voided_twice
    """
    ctx = _voided_certificate(api)
    version_after_first_void = ctx["voided_certificate"]["version"]

    validate_error(
        api.void_destruction_certificate(
            ctx["destruction_certificate"]["id"],
            certificate_void_payload("second attempt at the same correction"),
            make_destruction_officer_headers(),
        ),
        "ERR_INVALID_CERTIFICATE_STATE",
        expected_status=409,
    )

    certificate = read_destruction_certificate(
        api, ctx["destruction_certificate"]["id"]
    )
    assert_certificate(certificate, destroyed_units=60, status="VOIDED")
    assert certificate["void_reason"] == VOID_REASON, (
        f"The first void's reason must survive, got {certificate['void_reason']!r}"
    )
    assert certificate["version"] == version_after_first_void, (
        f"A refused second void must not bump the certificate version, expected "
        f"{version_after_first_void}, got {certificate['version']}"
    )


def test_09_the_refused_second_void_does_not_apply_the_compensation_twice(api):
    """The compensation is applied exactly once: the program, the facility and the
    kit all read as they did after the first void, and the ledger gains no sixth
    entry.

    PRD 3.8: "The certificate must be in status `ISSUED`; voiding an already-`VOIDED` certificate returns `ERR_INVALID_CERTIFICATE_STATE` (HTTP 409)."
    PRD 3.8: "Two ledger entries are appended, again in a pinned order: first a `COMMITMENT_REVERSAL` for the negation of `final_kit_cost_cents`, then, at the immediately following `sequence_no`, a `RESERVATION` for the positive `provisional_cost_cents` of the kit — which restores the program's reserved, committed and available triple to precisely the values it held before the certificate was issued."
    PRD 3.8: "On the facility, `pending_intake_units` rises by exactly the shipment's `custody_units`, `destroyed_units_total` falls by the certificate's `destroyed_units`, and `certificates_issued_count` is deliberately left **unchanged** so that certificate numbers are never reused."
    PRD 3.8: "The kit moves `DESTROYED → RECEIVED` with its `version` incremented by 1, which is what re-opens the cycle and allows a corrected certificate to be issued."
    PRD 3.4: "`ONE_QUART` holds 0.9 litres, 100 units, and costs 1450 cents."
    PRD 3.4: "The base component is the catalogue's `unit_cost_cents` for the selected size."
    PRD 3.4: "The transport component estimates weight from capacity rather than from any actual fill: the container's `capacity_units` is multiplied by 4 grams per unit to give an estimated gram weight, that figure is multiplied by the transport rate of 38 cents per kilogram and divided by 1000 to convert grams to kilograms, and the result is rounded half up to a whole cent."
    PRD 3.4: "`provisional_cost_cents` is the base component plus that rounded transport component."
    PRD 3.2: "Ledger entries are readable individually and as a list filtered by `sponsorship_program_id`, `kit_id` or `entry_type`, always in `sequence_no` ascending order."
    Design: Corner/state_machines/terminal_certificate_cannot_be_voided_twice
    """
    ctx = _voided_certificate(api)
    kit_version_after_first_void = read_kit(api, ctx["kit"]["id"])["version"]

    validate_error(
        api.void_destruction_certificate(
            ctx["destruction_certificate"]["id"],
            certificate_void_payload("second attempt at the same correction"),
            make_destruction_officer_headers(),
        ),
        "ERR_INVALID_CERTIFICATE_STATE",
        expected_status=409,
    )

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
            ADMIN, {"sponsorship_program_id": ctx["sponsorship_program"]["id"]}
        ),
        5,
    )
    assert_facility_counters(
        read_treatment_facility(api, ctx["treatment_facility"]["id"]),
        pending_intake_units=60,
        destroyed_units_total=0,
        certificates_issued_count=1,
        status="ACTIVE",
    )
    kit = read_kit(api, ctx["kit"]["id"])
    assert_kit(kit, status="RECEIVED", fill_units=60)
    assert kit["version"] == kit_version_after_first_void, (
        f"A refused second void must not bump the kit version, expected "
        f"{kit_version_after_first_void}, got {kit['version']}"
    )
