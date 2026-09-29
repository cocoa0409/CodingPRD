"""Refusals on the last two calls of the custody route and on the two fiscal
gates that guard a sponsor's money.

Every test builds its own world from scratch through the PRD's own endpoints;
the harness restarts the server with an empty database before each one. Each
refusal is asserted together with the state it must NOT have written.
"""

from test_helpers import (
    TEST_USERS,
    add_enrolled_patient,
    assert_certificate,
    assert_enrollment,
    assert_facility_counters,
    assert_kit,
    assert_ledger_entry,
    assert_ledger_sequence,
    assert_non_conformance_event,
    assert_program_balances,
    assert_shipment_axes,
    assert_total_count,
    conformance_screening_payload,
    destruction_certificate_payload,
    funding_adjustment_payload,
    get_success_data,
    issue_kit_for,
    kit_issuance_payload,
    make_destruction_officer_headers,
    make_intake_technician_headers,
    make_sponsor_representative_headers,
    notify_customer_payload,
    read_enrollment_version,
    read_first_non_conformance_event,
    read_kit,
    read_ledger_entries,
    read_non_conformance_event,
    read_program,
    read_shipment,
    read_treatment_facility,
    remediation_payload,
    setup_delivered_shipment,
    setup_program_foundations,
    setup_screened_shipment,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]

TECH_ID = "tech-77"
OFFICER_ID = "officer-12"

_EXEMPT_CA_RULE = {
    "state_code": "CA",
    "household_sharps_classification": "HOUSEHOLD_EXEMPT",
    "mail_back_permitted": True,
    "max_container_volume_liters": 30.3,
    "certificate_retention_years": 3,
    "notification_deadline_hours": 72,
}
_MAILBACK_SPEC = {
    "spec_code": "MB-USPS",
    "un_specification_code": "UN 4G/X7.5/S/26",
    "postal_service": "USPS_PARCEL_SELECT_MAILBACK",
    "hazard_class": "UN3291_SHARPS_ONLY",
    "max_gross_weight_grams": 8000,
    "allowed_container_sizes": ["ONE_QUART", "TWO_GALLON"],
}
_SHARPS_ONLY_FACILITY = {
    "name": "Bay Area Sharps Treatment",
    "permit_number": "CA-TF-0001",
    "accepted_hazard_classes": ["UN3291_SHARPS_ONLY"],
    "daily_intake_capacity_units": 200,
}
_MANUFACTURER = {"sponsor_type": "MANUFACTURER"}
_PROGRAM = {"program_code": "NW-2026", "funding_ceiling_cents": 500000, "per_kit_allowance_cents": 5000}
_DANA = {"full_name": "Dana Reyes", "weekly_sharps_count": 20, "contact_email": "dana@example.com"}
_CADENCE_30 = {"cadence_days": 30, "kits_authorized": 3}

_SEALED_KIT = dict(
    fill_units=60,
    sealed_gross_weight_grams=1200,
    declared_gross_weight_grams=1200,
    scheduled_intake_date="2026-08-05",
    state_rule_overrides=dict(_EXEMPT_CA_RULE),
    packaging_spec_overrides=dict(_MAILBACK_SPEC),
    sponsor_overrides=dict(_MANUFACTURER),
    program_overrides=dict(_PROGRAM),
    patient_overrides=dict(_DANA),
    enrollment_overrides=dict(_CADENCE_30),
)


# ==========================================================================
# Destruction-stage refusals (PRD 3.7, 3.8)
# ==========================================================================
def _delivered_but_unscreened_parcel(api):
    """Dana's ONE_QUART parcel has arrived at the facility: `transport_status` is
    DELIVERED while `conformance_status` is still UNSCREENED."""
    return setup_delivered_shipment(
        api, facility_overrides=dict(_SHARPS_ONLY_FACILITY), **_SEALED_KIT
    )


def _certifiable_parcel(api):
    """The same parcel, screened CONFORMING by the technician `tech-77`."""
    return setup_screened_shipment(
        api,
        outcome="CONFORMING",
        observed_gross_weight_grams=1200,
        technician_user_id=TECH_ID,
        facility_overrides=dict(_SHARPS_ONLY_FACILITY),
        **_SEALED_KIT,
    )


def test_01_certification_is_refused_while_the_conformance_axis_is_unresolved(api):
    """Delivery alone does not make a parcel certifiable: the second axis must
    read CONFORMING or REMEDIATED first, and the refusal writes nothing.

    PRD 3.8: "The shipment's `transport_status` must be `DELIVERED` and its `conformance_status` must be either `CONFORMING` or `REMEDIATED`, failing which the answer is `ERR_DELIVERY_REQUIRED_BEFORE_DESTRUCTION` (HTTP 409) — waste that is still in the mail, or that has been rejected but not yet remediated, cannot be certified destroyed."
    Design: Corner/errors/destruction_stage_refusals_cover_ordering_duties_reconciliation_and_replay
    """
    ctx = _delivered_but_unscreened_parcel(api)
    shipment_id = ctx["shipment"]["id"]
    assert_shipment_axes(
        read_shipment(api, shipment_id),
        transport_status="DELIVERED",
        conformance_status="UNSCREENED",
    )

    response = api.issue_destruction_certificate(
        shipment_id,
        destruction_certificate_payload(60),
        make_destruction_officer_headers(OFFICER_ID),
    )
    validate_error(response, "ERR_DELIVERY_REQUIRED_BEFORE_DESTRUCTION", 409)

    assert_total_count(
        api.list_destruction_certificates(ADMIN, {"shipment_id": shipment_id}), 0
    )
    assert_kit(read_kit(api, ctx["kit"]["id"]), status="RECEIVED")
    assert_facility_counters(
        read_treatment_facility(api, ctx["treatment_facility"]["id"]),
        destroyed_units_total=0,
        certificates_issued_count=0,
        pending_intake_units=60,
    )


def test_02_a_second_screening_of_the_same_parcel_is_refused(api):
    """A parcel is screened exactly once, so replaying the identical screening is
    refused even though it would write the identical values.

    PRD 3.7: "Three gates apply, in this order: the shipment's `transport_status` must read `DELIVERED`, and a screening attempted on a parcel that has not arrived is refused with `ERR_INVALID_SHIPMENT_STATE`; then, **on a `CONFORMING` outcome only**, `observed_gross_weight_grams` must not exceed the pinned specification's `max_gross_weight_grams`, an excess being `ERR_POSTAL_WEIGHT_EXCEEDED`; then the shipment's `conformance_status` must still be `UNSCREENED`, a second attempt being refused with `ERR_SHIPMENT_ALREADY_SCREENED` (HTTP 409)."
    PRD 3.7: "A parcel is screened exactly once — a rejected parcel moves on through remediation, never through a second screening."
    Design: Corner/errors/destruction_stage_refusals_cover_ordering_duties_reconciliation_and_replay
    """
    ctx = _delivered_but_unscreened_parcel(api)
    shipment_id = ctx["shipment"]["id"]
    screening = conformance_screening_payload(
        outcome="CONFORMING", observed_gross_weight_grams=1200
    )
    tech = make_intake_technician_headers(TECH_ID)

    screened = validate_success(api.screen_shipment_conformance(shipment_id, screening, tech), 200)
    assert_shipment_axes(
        screened,
        transport_status="DELIVERED",
        conformance_status="CONFORMING",
        screened_by_user_id=TECH_ID,
    )

    replay = api.screen_shipment_conformance(shipment_id, screening, tech)
    validate_error(replay, "ERR_SHIPMENT_ALREADY_SCREENED", 409)
    assert_shipment_axes(
        read_shipment(api, shipment_id),
        conformance_status="CONFORMING",
        screened_by_user_id=TECH_ID,
    )


def test_03_the_technician_who_screened_the_parcel_may_not_certify_it(api):
    """Segregation of duties compares the acting identifier with the one recorded
    at screening, and the bar sits in the safety band, above every constraint
    check below it — here the destroyed count is perfectly reconcilable.

    PRD 3.8: "Then the safety band asserts segregation of duties: the acting `X-User-ID` must differ from the shipment's `screened_by_user_id`, and equality is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    Design: Corner/errors/destruction_stage_refusals_cover_ordering_duties_reconciliation_and_replay
    """
    ctx = _certifiable_parcel(api)
    shipment_id = ctx["shipment"]["id"]
    assert_shipment_axes(
        read_shipment(api, shipment_id),
        conformance_status="CONFORMING",
        screened_by_user_id=TECH_ID,
    )

    response = api.issue_destruction_certificate(
        shipment_id,
        destruction_certificate_payload(60),
        make_destruction_officer_headers(TECH_ID),
    )
    validate_error(response, "ERR_SEGREGATION_OF_DUTIES", 403)

    assert_total_count(
        api.list_destruction_certificates(ADMIN, {"shipment_id": shipment_id}), 0
    )
    assert_kit(read_kit(api, ctx["kit"]["id"]), status="RECEIVED")


def test_04_a_destroyed_count_that_misses_the_sealed_count_is_refused(api):
    """The certificate has to reconcile to what the patient sealed, and the
    reconciliation is exact rather than a tolerance: 59 against a sealed 60 is
    refused.

    PRD 3.8: "Finally the submitted `destroyed_units` must equal the kit's `fill_units` exactly — neither more nor less, since the certificate has to reconcile to what the patient sealed — and any discrepancy is refused with `ERR_DESTROYED_UNITS_MISMATCH` (HTTP 422)."
    Design: Corner/errors/destruction_stage_refusals_cover_ordering_duties_reconciliation_and_replay
    """
    ctx = _certifiable_parcel(api)
    shipment_id = ctx["shipment"]["id"]
    assert_kit(read_kit(api, ctx["kit"]["id"]), status="RECEIVED", fill_units=60)

    response = api.issue_destruction_certificate(
        shipment_id,
        destruction_certificate_payload(59),
        make_destruction_officer_headers(OFFICER_ID),
    )
    validate_error(response, "ERR_DESTROYED_UNITS_MISMATCH", 422)

    assert_total_count(
        api.list_destruction_certificates(ADMIN, {"shipment_id": shipment_id}), 0
    )
    assert_kit(read_kit(api, ctx["kit"]["id"]), status="RECEIVED")
    assert_total_count(
        api.list_ledger_entries(
            ADMIN, {"sponsorship_program_id": ctx["sponsorship_program"]["id"]}
        ),
        1,
    )


def test_05_replaying_a_successful_certification_is_refused(api):
    """The accepted certification settles the kit at 1676 cents and takes the
    facility's first certificate number; the identical call replayed immediately
    afterwards is refused, and exactly one certificate row survives.

    PRD 3.8: "The kit must be `RECEIVED`; a kit that has already been certified and is therefore `DESTROYED`, or one that was mailed back and is `RETURNED_TO_PATIENT`, blocks certification with `ERR_INVALID_KIT_STATE`."
    PRD 3.8: "Its `certificate_number` is the literal text `CERT-`, then the facility's `permit_number`, then a hyphen, then a sequence number zero-padded to five digits, where the sequence number is the facility's `certificates_issued_count` plus one."
    PRD 3.8: "Two ledger entries are appended in a pinned order that must not be swapped: first a `RESERVATION_RELEASE` for the negation of the kit's `provisional_cost_cents`, then, at the immediately following `sequence_no`, a `COMMITMENT` for the positive `final_kit_cost_cents`."
    PRD 3.8: "On the facility, `certificates_issued_count` rises by 1, `pending_intake_units` falls by exactly the shipment's `custody_units`, and `destroyed_units_total` rises by the certificate's `destroyed_units`."
    Design: Corner/errors/destruction_stage_refusals_cover_ordering_duties_reconciliation_and_replay
    """
    ctx = _certifiable_parcel(api)
    shipment_id = ctx["shipment"]["id"]
    facility_id = ctx["treatment_facility"]["id"]
    program_id = ctx["sponsorship_program"]["id"]
    officer = make_destruction_officer_headers(OFFICER_ID)
    payload = destruction_certificate_payload(60)

    certificate = validate_success(
        api.issue_destruction_certificate(shipment_id, payload, officer), 201
    )
    assert_certificate(
        certificate,
        certificate_number="CERT-CA-TF-0001-00001",
        destroyed_units=60,
        final_kit_cost_cents=1676,
        issued_by_user_id=OFFICER_ID,
        status="ISSUED",
    )

    replay = api.issue_destruction_certificate(shipment_id, payload, officer)
    validate_error(replay, "ERR_INVALID_KIT_STATE", 409)

    rows, _ = assert_total_count(
        api.list_destruction_certificates(ADMIN, {"shipment_id": shipment_id}), 1
    )
    assert rows[0]["id"] == certificate["id"]

    assert_ledger_sequence(
        read_ledger_entries(api, program_id),
        [
            (1, "RESERVATION", 1465),
            (2, "RESERVATION_RELEASE", -1465),
            (3, "COMMITMENT", 1676),
        ],
    )
    assert_facility_counters(
        read_treatment_facility(api, facility_id),
        certificates_issued_count=1,
        destroyed_units_total=60,
        pending_intake_units=0,
    )


# ==========================================================================
# Non-conformance workflow ordering (PRD 3.7)
# ==========================================================================
def _open_non_conformance(api):
    """Dana's parcel was rejected at intake for loose sharps, opening exactly one
    non-conformance event in status OPEN. The California rule classifies household
    sharps as exempt and the facility's permit covers both hazard classes, so
    every remediation action is legal on its merits here."""
    return setup_screened_shipment(
        api,
        outcome="NON_CONFORMING",
        reason_code="LOOSE_SHARPS_IN_BOX",
        observed_gross_weight_grams=1200,
        technician_user_id=TECH_ID,
        **_SEALED_KIT,
    )


def test_06_remediation_may_not_leapfrog_the_customer_notification(api):
    """The workflow gate fires ahead of the action's own legality check, so an
    action that would be perfectly legal here is still refused while the event
    has not reached CUSTOMER_NOTIFIED.

    PRD 3.7: "The event must be `CUSTOMER_NOTIFIED` — remediation cannot leapfrog notification, and an attempt from `OPEN` or `RESOLVED` returns `ERR_INVALID_NONCONFORMANCE_STATE`."
    PRD 3.7: "`ON_SITE_REPACK` is always legal."
    Design: Corner/errors/nonconformance_event_rejects_out_of_order_notification_and_remediation
    """
    ctx = _open_non_conformance(api)
    event = read_first_non_conformance_event(api, ctx["shipment"]["id"])
    assert_non_conformance_event(event, status="OPEN", reason_code="LOOSE_SHARPS_IN_BOX")

    response = api.remediate_non_conformance(
        event["id"],
        remediation_payload("ON_SITE_REPACK"),
        make_intake_technician_headers(TECH_ID),
    )
    validate_error(response, "ERR_INVALID_NONCONFORMANCE_STATE", 409)

    assert_non_conformance_event(
        read_non_conformance_event(api, event["id"]),
        status="OPEN",
        remediation_action=None,
        notified_at=None,
    )
    assert_shipment_axes(
        read_shipment(api, ctx["shipment"]["id"]), conformance_status="NON_CONFORMING"
    )


def test_07_a_second_customer_notification_is_refused(api):
    """Notification is legal from OPEN only, so a second recording — even on a
    different channel — is refused and the stored channel is untouched.

    PRD 3.7: "The event must be `OPEN`, otherwise `ERR_INVALID_NONCONFORMANCE_STATE`, and the current logical-clock instant must be at or before the event's `notification_deadline_at` — a notification recorded after that instant is refused with `ERR_NOTIFICATION_DEADLINE_PASSED` (HTTP 422), and recording it at the instant exactly equal to the deadline is still permitted."
    PRD 3.7: "Success moves the event `OPEN → CUSTOMER_NOTIFIED`, sets `notified_at` to the current logical-clock instant, stores the channel, and increments the event's `version` by 1."
    Design: Corner/errors/nonconformance_event_rejects_out_of_order_notification_and_remediation
    """
    ctx = _open_non_conformance(api)
    event_id = read_first_non_conformance_event(api, ctx["shipment"]["id"])["id"]
    tech = make_intake_technician_headers(TECH_ID)

    notified = validate_success(
        api.notify_customer(event_id, notify_customer_payload("EMAIL"), tech), 200
    )
    assert_non_conformance_event(
        notified, status="CUSTOMER_NOTIFIED", notification_channel="EMAIL"
    )
    assert notified["notified_at"] is not None, "notified_at must record the notification instant"

    response = api.notify_customer(event_id, notify_customer_payload("PHONE"), tech)
    validate_error(response, "ERR_INVALID_NONCONFORMANCE_STATE", 409)

    assert_non_conformance_event(
        read_non_conformance_event(api, event_id),
        status="CUSTOMER_NOTIFIED",
        notification_channel="EMAIL",
    )


def test_08_a_second_remediation_of_a_resolved_event_is_refused(api):
    """RESOLVED is terminal, so a second disposition is refused and the stored
    action stands; no refused call ever creates a second event.

    PRD 3.7: "The event must be `CUSTOMER_NOTIFIED` — remediation cannot leapfrog notification, and an attempt from `OPEN` or `RESOLVED` returns `ERR_INVALID_NONCONFORMANCE_STATE`."
    PRD 3.7: "Whichever action is chosen, the event moves `CUSTOMER_NOTIFIED → RESOLVED` with the chosen `remediation_action` stored, the shipment's conformance axis moves `NON_CONFORMING → REMEDIATED` while `transport_status` stays `DELIVERED`, and both records have their `version` incremented by 1."
    PRD 3.7: "Non-conformance events are readable individually, as a list scoped to one shipment, and as a global list filtered by `shipment_id`, `reason_code` or `status`."
    Design: Corner/errors/nonconformance_event_rejects_out_of_order_notification_and_remediation
    """
    ctx = _open_non_conformance(api)
    shipment_id = ctx["shipment"]["id"]
    event_id = read_first_non_conformance_event(api, shipment_id)["id"]
    tech = make_intake_technician_headers(TECH_ID)
    get_success_data(api.notify_customer(event_id, notify_customer_payload("EMAIL"), tech))

    resolved = validate_success(
        api.remediate_non_conformance(event_id, remediation_payload("ON_SITE_REPACK"), tech),
        200,
    )
    assert_non_conformance_event(
        resolved, status="RESOLVED", remediation_action="ON_SITE_REPACK"
    )
    assert_shipment_axes(
        read_shipment(api, shipment_id),
        transport_status="DELIVERED",
        conformance_status="REMEDIATED",
    )

    response = api.remediate_non_conformance(
        event_id, remediation_payload("DISPOSE_AS_RMW"), tech
    )
    validate_error(response, "ERR_INVALID_NONCONFORMANCE_STATE", 409)

    assert_non_conformance_event(
        read_non_conformance_event(api, event_id),
        status="RESOLVED",
        remediation_action="ON_SITE_REPACK",
    )
    assert_total_count(
        api.list_non_conformance_events(ADMIN, {"shipment_id": shipment_id}), 1
    )


# ==========================================================================
# The two fiscal refusals (PRD 3.2, 3.4)
# ==========================================================================
_THIN_PROGRAM = {
    "program_code": "NW-THIN",
    "funding_ceiling_cents": 1500,
    "per_kit_allowance_cents": 5000,
}
_FERN = {"full_name": "Fern Iqbal", "weekly_sharps_count": 20, "contact_email": "fern@example.com"}


def _thin_program_world(api):
    """A 1500-cent ceiling with a 5000-cent per-kit allowance, so the allowance
    never interferes. Dana's ONE_QUART kit has reserved 1465, leaving 35 cents of
    headroom, and Fern's enrollment is ACTIVE with no kit yet."""
    ctx = setup_program_foundations(
        api,
        state_rule_overrides=dict(_EXEMPT_CA_RULE),
        packaging_spec_overrides=dict(_MAILBACK_SPEC),
        facility_overrides=dict(_SHARPS_ONLY_FACILITY),
        sponsor_overrides=dict(_MANUFACTURER),
        program_overrides=dict(_THIN_PROGRAM),
    )
    add_enrolled_patient(
        api, ctx, patient_overrides=dict(_DANA), enrollment_overrides=dict(_CADENCE_30)
    )
    issue_kit_for(api, ctx)
    add_enrolled_patient(
        api,
        ctx,
        patient_overrides=dict(_FERN),
        enrollment_overrides=dict(_CADENCE_30),
        key="fern",
    )
    return ctx


def test_09_issuance_is_refused_when_the_pool_cannot_cover_the_reservation(api):
    """35 cents of headroom cannot cover a 1465-cent reservation, and the pool
    check is the last gate of all, so nothing at all is written.

    PRD 3.4: "Likewise the pool check compares the program's `available_cents`, with the superseded kit's reservation already released, against the new kit's `provisional_cost_cents`; a shortfall is refused with `ERR_PROGRAM_FUNDING_EXHAUSTED` (HTTP 422)."
    PRD 2.9: "`available_cents` is `funding_ceiling_cents` less `reserved_cents` less `committed_cents`, recomputed after every append."
    Design: Corner/errors/funding_exhaustion_and_clawback_below_obligations_both_reject_at_the_fiscal_band
    """
    ctx = _thin_program_world(api)
    program_id = ctx["sponsorship_program"]["id"]
    fern_enrollment = ctx["enrollment_fern"]["id"]
    version_before = read_enrollment_version(api, fern_enrollment)

    response = api.issue_kit(
        fern_enrollment, kit_issuance_payload(version_before), ADMIN
    )
    validate_error(response, "ERR_PROGRAM_FUNDING_EXHAUSTED", 422)

    assert_total_count(api.list_kits(ADMIN, {"enrollment_id": fern_enrollment}), 0)
    assert_enrollment(
        get_success_data(api.get_enrollment(fern_enrollment, ADMIN)),
        version=version_before,
        kits_issued=0,
    )
    assert_total_count(
        api.list_ledger_entries(ADMIN, {"sponsorship_program_id": program_id}), 1
    )
    assert_program_balances(
        read_program(api, program_id),
        reserved_cents=1465,
        committed_cents=0,
        available_cents=35,
        funding_ceiling_cents=1500,
        status="ACTIVE",
    )


def test_10_a_clawback_below_the_outstanding_obligations_is_refused(api):
    """Trimming the ceiling by 500 would leave 1000 cents against 1465 already
    reserved, which is money the sponsor no longer owns.

    PRD 3.2: "The delta is added to `funding_ceiling_cents`, which may rise or fall, but it may never be pushed below the sum of `reserved_cents` and `committed_cents`: a sponsor cannot claw back money that is already reserved against outstanding kits or committed against issued certificates, and an attempt to do so is refused with `ERR_FUNDING_BELOW_OBLIGATIONS` (HTTP 422)."
    Design: Corner/errors/funding_exhaustion_and_clawback_below_obligations_both_reject_at_the_fiscal_band
    """
    ctx = _thin_program_world(api)
    program_id = ctx["sponsorship_program"]["id"]
    sponsor_headers = make_sponsor_representative_headers(ctx["sponsor"]["id"])
    program_version = read_program(api, program_id)["version"]

    response = api.create_funding_adjustment(
        program_id,
        funding_adjustment_payload(-500, program_version, memo="trim"),
        sponsor_headers,
    )
    validate_error(response, "ERR_FUNDING_BELOW_OBLIGATIONS", 422)

    program = read_program(api, program_id)
    assert_program_balances(
        program,
        funding_ceiling_cents=1500,
        reserved_cents=1465,
        committed_cents=0,
        available_cents=35,
        status="ACTIVE",
    )
    assert program["version"] == program_version, (
        f"a refused adjustment must not bump the program version, got {program['version']}"
    )
    assert_total_count(
        api.list_ledger_entries(ADMIN, {"sponsorship_program_id": program_id}), 1
    )


def test_11_trimming_the_ceiling_to_exactly_the_obligations_is_accepted(api):
    """The clawback boundary is inclusive: a ceiling of exactly reserved plus
    committed is legal, and it drives the program to EXHAUSTED with no headroom
    left, which the next issuance attempt then runs into.

    PRD 3.2: "A successful adjustment appends a `FUNDING_ADJUSTMENT` ledger entry whose `amount_cents` is the submitted `delta_cents` signed exactly as submitted, whose `kit_id` is null, whose `memo` is copied from the request, and whose three after-balances are snapshotted; it then recomputes `available_cents`, flips the program between `EXHAUSTED` and `ACTIVE` if the recomputed figure crosses zero, and increments the program's `version` by 1."
    PRD 3.4: "Likewise the pool check compares the program's `available_cents`, with the superseded kit's reservation already released, against the new kit's `provisional_cost_cents`; a shortfall is refused with `ERR_PROGRAM_FUNDING_EXHAUSTED` (HTTP 422)."
    Design: Corner/errors/funding_exhaustion_and_clawback_below_obligations_both_reject_at_the_fiscal_band
    """
    ctx = _thin_program_world(api)
    program_id = ctx["sponsorship_program"]["id"]
    fern_enrollment = ctx["enrollment_fern"]["id"]
    sponsor_headers = make_sponsor_representative_headers(ctx["sponsor"]["id"])
    program_version = read_program(api, program_id)["version"]

    adjusted = validate_success(
        api.create_funding_adjustment(
            program_id,
            funding_adjustment_payload(-35, program_version),
            sponsor_headers,
        ),
        200,
    )
    assert_program_balances(
        adjusted,
        funding_ceiling_cents=1465,
        reserved_cents=1465,
        committed_cents=0,
        available_cents=0,
        status="EXHAUSTED",
    )
    assert adjusted["version"] == program_version + 1, (
        f"Expected program version {program_version + 1}, got {adjusted['version']}"
    )

    entries = read_ledger_entries(api, program_id)
    assert_ledger_sequence(
        entries, [(1, "RESERVATION", 1465), (2, "FUNDING_ADJUSTMENT", -35)]
    )
    assert_ledger_entry(
        entries[1],
        entry_type="FUNDING_ADJUSTMENT",
        amount_cents=-35,
        sequence_no=2,
        reserved_after_cents=1465,
        committed_after_cents=0,
        available_after_cents=0,
        kit_id=None,
    )

    response = api.issue_kit(
        fern_enrollment,
        kit_issuance_payload(read_enrollment_version(api, fern_enrollment)),
        ADMIN,
    )
    validate_error(response, "ERR_PROGRAM_FUNDING_EXHAUSTED", 422)
    assert_total_count(api.list_kits(ADMIN, {"enrollment_id": fern_enrollment}), 0)


def test_12_topping_the_ceiling_back_up_reopens_issuance(api):
    """Once the ceiling rises again the program flips back to ACTIVE and the very
    same issuance that was refused twice succeeds, reserving a second 1465.

    PRD 3.2: "A successful adjustment appends a `FUNDING_ADJUSTMENT` ledger entry whose `amount_cents` is the submitted `delta_cents` signed exactly as submitted, whose `kit_id` is null, whose `memo` is copied from the request, and whose three after-balances are snapshotted; it then recomputes `available_cents`, flips the program between `EXHAUSTED` and `ACTIVE` if the recomputed figure crosses zero, and increments the program's `version` by 1."
    PRD 3.4: "*Third*, a `RESERVATION` ledger entry for the positive `provisional_cost_cents` is appended at the next `sequence_no` and the program's `reserved_cents` rises by that amount."
    Design: Corner/errors/funding_exhaustion_and_clawback_below_obligations_both_reject_at_the_fiscal_band
    """
    ctx = _thin_program_world(api)
    program_id = ctx["sponsorship_program"]["id"]
    sponsor_headers = make_sponsor_representative_headers(ctx["sponsor"]["id"])
    program_version = read_program(api, program_id)["version"]

    get_success_data(
        api.create_funding_adjustment(
            program_id, funding_adjustment_payload(-35, program_version), sponsor_headers
        )
    )
    topped_up = validate_success(
        api.create_funding_adjustment(
            program_id,
            funding_adjustment_payload(2000, program_version + 1),
            sponsor_headers,
        ),
        200,
    )
    assert_program_balances(
        topped_up,
        funding_ceiling_cents=3465,
        reserved_cents=1465,
        committed_cents=0,
        available_cents=2000,
        status="ACTIVE",
    )

    kit = issue_kit_for(api, ctx, enrollment=ctx["enrollment_fern"])
    assert_kit(kit, status="ISSUED", container_size="ONE_QUART", provisional_cost_cents=1465)
    assert_program_balances(
        read_program(api, program_id),
        reserved_cents=2930,
        committed_cents=0,
        available_cents=535,
        status="ACTIVE",
    )
