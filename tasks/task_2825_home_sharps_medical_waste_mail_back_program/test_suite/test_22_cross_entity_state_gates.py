"""Two calls refused by the state of a row that is not the endpoint's own: an owning
enrollment two hops up, and a peer facility reached sideways from the shipment."""

from test_helpers import (
    ADMIN,
    DESTRUCTION_OFFICER_USER_ID,
    acknowledge_kit,
    assert_empty_listing,
    assert_enrollment,
    assert_facility_counters,
    assert_kit,
    assert_program_balances,
    assert_shipment_axes,
    destruction_certificate_payload,
    make_destruction_officer_headers,
    make_patient_headers,
    read_enrollment,
    read_kit,
    read_patient,
    read_program,
    read_shipment,
    read_treatment_facility,
    seal_payload,
    setup_certifiable_shipment,
    setup_issued_kit,
    status_action_payload,
    validate_error,
)


# --------------------------------------------------------------------------
# Sealing a kit is blocked by the enrollment, two hops away
# --------------------------------------------------------------------------
def _filling_kit_whose_enrollment_was_paused_behind_it(api):
    """The kit is acknowledged, so it is ACTIVE_FILLING and physically in the patient's
    hands. Suspending the patient pauses the enrollment but pointedly leaves this kit
    alone, so a perfectly sealable kit survives the cascade."""
    ctx = setup_issued_kit(api)
    acknowledge_kit(api, ctx)
    ctx["suspension"] = api.patient_status_action(
        ctx["patient"]["id"],
        status_action_payload("SUSPEND", reason="risk review pending"),
        ADMIN,
    )
    return ctx


def _attempt_seal(api, ctx):
    return api.seal_kit(
        ctx["kit"]["id"],
        seal_payload(69, 1400),
        make_patient_headers(ctx["patient"]["id"]),
    )


def test_01_the_paused_enrollment_blocks_a_seal_on_a_legal_kit(api):
    """The kit's own status is the legal ACTIVE_FILLING and the payload is in range, so
    only the cross-entity read of the enrollment can refuse the call.

    PRD 3.5: "The kit's enrollment must be `ACTIVE` — this cross-entity guard fires ahead of every kit-state and payload-range check, so a patient whose enrollment was paused mid-fill is told `ERR_INVALID_ENROLLMENT_STATE` rather than anything about the container."

    Design: Difficulty/cross_entity_state_dependency/kit_seal_blocked_when_enrollment_paused
    """
    ctx = _filling_kit_whose_enrollment_was_paused_behind_it(api)
    assert_kit(read_kit(api, ctx["kit"]["id"]), status="ACTIVE_FILLING")

    response = _attempt_seal(api, ctx)

    validate_error(response, "ERR_INVALID_ENROLLMENT_STATE", 409)
    assert response.json()["data"]["error_id"] != "ERR_INVALID_KIT_STATE", (
        "the kit itself is in a sealable state; the refusal must name the enrollment"
    )


def test_02_the_refused_seal_stores_neither_declared_value(api):
    """A refusal writes nothing: the kit stays in ACTIVE_FILLING with its gross weight
    still unset.

    PRD 3.5: "On success the kit moves `ACTIVE_FILLING → SEALED`, both declared values are stored on the kit, and the kit's `version` is incremented by 1."
    PRD 3.4: "*Second*, the new kit is minted in status `ISSUED` with `enrollment_id` pointing at its enrollment, `required_units`, `container_size`, `capacity_units` and `volume_liters` from the sizing rule above, `provisional_cost_cents` from the costing rule above, `issued_at` set to the current logical-clock instant, `fill_units` at 0, `sealed_gross_weight_grams` null, `acknowledged_at` null, `void_reason` null, `auto_ship_run_id` null for an operator-driven issuance, and `supersedes_kit_id` set to the id of the kit that was just superseded — or null when there was none."

    Design: Difficulty/cross_entity_state_dependency/kit_seal_blocked_when_enrollment_paused
    """
    ctx = _filling_kit_whose_enrollment_was_paused_behind_it(api)

    _attempt_seal(api, ctx)

    kit = read_kit(api, ctx["kit"]["id"])
    assert_kit(kit, status="ACTIVE_FILLING")
    assert kit["sealed_gross_weight_grams"] is None, (
        f"a refused seal must not store a weight, got {kit['sealed_gross_weight_grams']!r}"
    )


def test_03_the_filling_kit_keeps_its_reservation_through_the_suspension(api):
    """Because the kit was ACTIVE_FILLING rather than ISSUED, the cascade voided nothing
    and the program still holds the 1465-cent reservation.

    PRD 3.9: "The third hop applies to each of those newly paused enrollments: its `next_autoship_due_date` is cleared to null, and every kit of that enrollment whose status is `ISSUED` moves to `VOIDED` with `void_reason` set to `ENROLLMENT_PAUSED` — kits already in `ACTIVE_FILLING` are physically in the patient's hands and are pointedly **not** voided."
    PRD 3.9: "The second hop moves every enrollment of that patient whose status is `ACTIVE` to `PAUSED`."

    Design: Difficulty/cross_entity_state_dependency/kit_seal_blocked_when_enrollment_paused
    """
    ctx = _filling_kit_whose_enrollment_was_paused_behind_it(api)

    _attempt_seal(api, ctx)

    assert read_patient(api, ctx["patient"]["id"])["status"] == "SUSPENDED"
    assert_enrollment(read_enrollment(api, ctx["enrollment"]["id"]), status="PAUSED")
    assert_program_balances(
        read_program(api, ctx["sponsorship_program"]["id"]),
        reserved_cents=1465,
        committed_cents=0,
        available_cents=498535,
    )


# --------------------------------------------------------------------------
# Certifying destruction is blocked by the facility, reached sideways
# --------------------------------------------------------------------------
def _certifiable_shipment_at_a_facility_suspended_after_intake(api):
    """Both shipment axes are in their success states and the officer differs from the
    screener, so only the facility's status can block certification."""
    ctx = setup_certifiable_shipment(api)
    api.treatment_facility_status_action(
        ctx["treatment_facility"]["id"],
        status_action_payload("SUSPEND", reason="state permit audit"),
        ADMIN,
    )
    return ctx


def _attempt_certification(api, ctx):
    return api.issue_destruction_certificate(
        ctx["shipment"]["id"],
        destruction_certificate_payload(69),
        make_destruction_officer_headers(DESTRUCTION_OFFICER_USER_ID),
    )


def test_04_a_suspended_facility_may_not_certify_waste_it_already_holds(api):
    """The parcel is physically inside the facility and both axes are ready, but
    suspension blocks forward motion.

    PRD 3.8: "The facility's `status` must be `ACTIVE`; a suspended facility may not certify destruction even of waste it already physically holds, and the refusal is `ERR_INVALID_FACILITY_STATE`."
    PRD 3.1: "What suspension blocks is forward motion — while a facility is `SUSPENDED` no new parcel may be routed to it and no destruction certificate may be issued at it, not even for waste it already physically holds. Both refusals carry `ERR_INVALID_FACILITY_STATE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/certificate_issuance_blocked_when_treatment_facility_suspended
    """
    ctx = _certifiable_shipment_at_a_facility_suspended_after_intake(api)

    response = _attempt_certification(api, ctx)

    validate_error(response, "ERR_INVALID_FACILITY_STATE", 409)


def test_05_suspension_never_rewrites_the_units_it_is_holding(api):
    """The 69 custody units stay booked while certification is blocked, and neither the
    lifetime destroyed total nor the numbering counter moves.

    PRD 3.1: "The critical property of suspension is what it does **not** do: parcels already tendered or in transit to the facility keep their units booked, and suspension never rewrites `pending_intake_units`."
    PRD 3.8: "On the facility, `certificates_issued_count` rises by 1, `pending_intake_units` falls by exactly the shipment's `custody_units`, and `destroyed_units_total` rises by the certificate's `destroyed_units`."

    Design: Difficulty/cross_entity_state_dependency/certificate_issuance_blocked_when_treatment_facility_suspended
    """
    ctx = _certifiable_shipment_at_a_facility_suspended_after_intake(api)

    _attempt_certification(api, ctx)

    facility = read_treatment_facility(api, ctx["treatment_facility"]["id"])
    assert facility["status"] == "SUSPENDED"
    assert_facility_counters(
        facility,
        pending_intake_units=69,
        destroyed_units_total=0,
        certificates_issued_count=0,
    )


def test_06_the_shipment_and_kit_stay_ready_to_certify_once_reinstated(api):
    """Nothing about the parcel is spoiled by the refusal: the kit is still RECEIVED and
    the two axes still read DELIVERED and CONFORMING, and no certificate exists.

    PRD 3.8: "The kit must be `RECEIVED`; a kit that has already been certified and is therefore `DESTROYED`, or one that was mailed back and is `RETURNED_TO_PATIENT`, blocks certification with `ERR_INVALID_KIT_STATE`."
    PRD 3.8: "The shipment must carry no destruction certificate in status `ISSUED`, otherwise `ERR_CERTIFICATE_ALREADY_ISSUED` (HTTP 409); a previously voided certificate does not block re-issuance."

    Design: Difficulty/cross_entity_state_dependency/certificate_issuance_blocked_when_treatment_facility_suspended
    """
    ctx = _certifiable_shipment_at_a_facility_suspended_after_intake(api)

    _attempt_certification(api, ctx)

    assert_kit(read_kit(api, ctx["kit"]["id"]), status="RECEIVED")
    assert_shipment_axes(
        read_shipment(api, ctx["shipment"]["id"]),
        transport_status="DELIVERED",
        conformance_status="CONFORMING",
    )
    assert_empty_listing(
        api.list_destruction_certificates(
            ADMIN, params={"shipment_id": ctx["shipment"]["id"]}
        )
    )


def test_07_the_blocked_settlement_leaves_the_money_reserved(api):
    """Settlement is the only thing that converts a reservation into a commitment, so a
    blocked certification leaves the 1465 cents merely reserved.

    PRD 2.9: "On the program side, `reserved_cents` is the sum of `RESERVATION` amounts less the sum of `RESERVATION_RELEASE` amounts over that program's entries, and `committed_cents` is the sum of `COMMITMENT` amounts less the sum of `COMMITMENT_REVERSAL` amounts."

    Design: Difficulty/cross_entity_state_dependency/certificate_issuance_blocked_when_treatment_facility_suspended
    """
    ctx = _certifiable_shipment_at_a_facility_suspended_after_intake(api)

    _attempt_certification(api, ctx)

    assert_program_balances(
        read_program(api, ctx["sponsorship_program"]["id"]),
        reserved_cents=1465,
        committed_cents=0,
        available_cents=498535,
    )
