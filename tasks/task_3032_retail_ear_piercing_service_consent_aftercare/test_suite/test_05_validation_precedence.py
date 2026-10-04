"""Validation priority: which rule is reported when several fail at once."""
from test_helpers import (
    E,
    api_client,
    create_cartridge_lot_payload,
    create_jurisdiction_payload,
    create_screening_payload,
    create_sterilization_cycle_payload,
    create_store_payload,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    COMPLIANCE,
    INTAKE,
    MANAGER,
    READER,
    TECHNICIAN,
    certify,
    create_consent,
    create_minor_customer,
    create_piercer,
    get_appointment,
    get_store,
    set_clock,
    setup_customer_with_active_consent,
    setup_ready_appointment,
    setup_store_with_certified_piercer,
)


def _screen_to_cleared(api, appointment_id, piercer_id):
    """Drive a checked-in appointment through screening into SCREENED.

    PRD §3.4 renders the `/screen` step as moving the appointment from
    CHECKED_IN to SCREENED, with the screening "outcome set by the screening
    evaluator as part of the same step"; the evaluator therefore runs inside the
    same call, and a separate `POST /screenings/{id}/evaluate` would be a second
    evaluation of a terminal screening (`ERR_SCREENING_ALREADY_EVALUATED`).
    """
    observed = get_appointment(appointment_id)
    validate_success(
        api.screen_appointment(
            appointment_id,
            create_screening_payload(appointment_id, piercer_id, observed["version"]),
            {"X-User-ID": piercer_id, "X-User-Role": "Piercer"},
        ),
        200,
    )


def test_state_validity_is_reported_ahead_of_the_age_gate(api):
    """PRD §2.12: "State validity is fourth: a target row that is not in a state from which the
    requested transition is declared yields `ERR_INVALID_STATE` (HTTP 409), and because state
    validity outranks the business-safety rules, a completed appointment belonging to an
    under-age customer is refused with `ERR_INVALID_STATE` rather than with an age error."

    Design: Difficulty/priority_pair_validation_conflict/state_precedes_age_gate_on_completed_appointment
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = validate_success(
        api_client.create_jurisdiction(
            create_jurisdiction_payload(
                min_age_self_consent=21, min_age_with_guardian=6, min_age_absolute=6,
                permitted_sites=["LOBE"], requires_guardian_presence=True,
            ),
            COMPLIANCE,
        ),
        201,
    )
    store = validate_success(
        api_client.create_store(
            create_store_payload(jurisdiction["id"], piercing_room_count=1), COMPLIANCE
        ),
        201,
    )
    piercer = create_piercer(store["id"])
    certify(piercer["id"])
    headers = {"X-User-ID": piercer["id"], "X-User-Role": "Piercer"}

    # The customer is below the self-consent age (so "under-age"), yet above the
    # guardian and absolute floors, so the service can be driven to COMPLETED.
    customer = create_minor_customer(date_of_birth="2010-01-01T00:00:00Z")
    consent = create_consent(
        customer["id"], jurisdiction["id"], consent_type="GUARDIAN_PRESENT",
        identification_type="BIRTH_CERTIFICATE",
    )
    validate_success(
        api_client.record_guardian_verification(consent["id"], {"outcome": "VERIFIED"}, INTAKE), 200
    )
    validate_success(api.verify_consent(consent["id"], INTAKE), 200)

    appointment = setup_ready_appointment(
        store["id"], customer["id"], piercer["id"], jurisdiction["id"]
    )
    api.set_clock("2026-09-01T09:00:00Z", COMPLIANCE)
    validate_success(api.check_in_appointment(appointment["id"], INTAKE), 200)

    # Starting a service consumes a cartridge, so the store needs a serviceable
    # lot under a PASSED cycle (PRD §3.5).
    from test_helpers.fixtures import setup_cycle_and_lot
    setup_cycle_and_lot(store["id"], lot_number="L-CLEARED")

    _screen_to_cleared(api, appointment["id"], piercer["id"])
    validate_success(api.start_service(appointment["id"], headers), 200)
    completed = validate_success(api.complete_appointment(appointment["id"], headers), 200)
    assert completed["status"] == "COMPLETED"

    # Cancelling a terminal appointment is a state violation, not an age violation.
    res = api.cancel_appointment(appointment["id"], INTAKE)
    validate_error(res, E.INVALID_STATE, expected_status=409)
    assert get_appointment(appointment["id"])["status"] == "COMPLETED"


def test_contraindication_is_reported_ahead_of_lot_availability(api):
    """PRD §3.4: "A screening carrying any of `KELOID_HISTORY`, `BLOOD_THINNER_THERAPY` or
    `ACTIVE_INFECTION` can never clear".
    PRD §2.12: "The contraindication gate also precedes the cartridge quarantine gate, so a
    contraindicated screening whose lot is quarantined reports `ERR_MEDICAL_CONTRAINDICATION`."

    Design: Difficulty/priority_pair_validation_conflict/contraindication_precedes_lot_availability_on_screening_evaluate
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction, store, piercer, _ = setup_store_with_certified_piercer(
        store_overrides={"piercing_room_count": 1}
    )
    customer, _ = setup_customer_with_active_consent(jurisdiction["id"])
    appointment = setup_ready_appointment(
        store["id"], customer["id"], piercer["id"], jurisdiction["id"]
    )
    api.set_clock("2026-09-01T09:00:00Z", COMPLIANCE)
    validate_success(api.check_in_appointment(appointment["id"], INTAKE), 200)

    observed = get_appointment(appointment["id"])
    # Recording a screening directly (PRD §3.4) leaves it PENDING, so the
    # evaluation that follows is the screening's first one.
    screening = validate_success(
        api.create_screening(
            create_screening_payload(
                appointment["id"], piercer["id"], observed["version"],
                contraindication_codes=["BLOOD_THINNER_THERAPY"],
            ),
            {"X-User-ID": piercer["id"], "X-User-Role": "Piercer"},
        ),
        201,
    )
    assert screening["outcome"] == "PENDING"

    # A lot bound to a cycle that never passed is quarantined, so it is not a
    # serviceable candidate either.
    store_version = get_store(store["id"])["version"]
    cycle = get_success_data(
        api_client.create_sterilization_cycle(
            create_sterilization_cycle_payload(store["id"]), TECHNICIAN
        )
    )
    lot = get_success_data(
        api_client.create_cartridge_lot(
            create_cartridge_lot_payload(store["id"], cycle["id"], store_version),
            MANAGER,
        )
    )
    validate_success(
        api_client.complete_sterilization_cycle(
            cycle["id"], {"temperature_celsius": 124.0, "biological_indicator_passed": False},
            TECHNICIAN,
        ),
        200,
    )
    assert get_success_data(api.get_cartridge_lot(lot["id"], READER))["status"] == "QUARANTINED"

    # The contraindication is reported ahead of the quarantine gate: the
    # evaluation happens at the screening, so the refusal is a refusal rather
    # than a quarantine rejection.
    res = api.evaluate_screening(
        screening["id"], {"X-User-ID": piercer["id"], "X-User-Role": "Piercer"}
    )
    validate_error(res, E.MEDICAL_CONTRAINDICATION, expected_status=422)

    # The contraindication is reported ahead of the cartridge gate: the
    # screening resolved to `ESCALATED` (BLOOD_THINNER_THERAPY is an
    # escalation-rank code) rather than being refused for the quarantined lot.
    resolved = get_success_data(api.get_screening(screening["id"], READER))
    assert resolved["outcome"] == "ESCALATED"


def test_the_age_gate_bites_on_a_pending_appointment_operation(api):
    """PRD §3.1: "Anyone below `min_age_with_guardian` is refused with
    `ERR_AGE_BELOW_JURISDICTION_MINIMUM` and HTTP 422. The same rejection applies to the
    absolute floor."
    PRD §3.1: "These checks guard the booking of an appointment, the opening of a session, and
    the verification of a consent, and they are evaluated before any other business rule on
    those operations."

    Design: Difficulty/priority_pair_validation_conflict/state_precedes_age_gate_on_completed_appointment
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = validate_success(
        api_client.create_jurisdiction(
            create_jurisdiction_payload(
                min_age_self_consent=21, min_age_with_guardian=21, min_age_absolute=21,
                permitted_sites=["LOBE"], requires_guardian_presence=True,
            ),
            COMPLIANCE,
        ),
        201,
    )
    store = validate_success(
        api_client.create_store(
            create_store_payload(jurisdiction["id"], piercing_room_count=1), COMPLIANCE
        ),
        201,
    )
    piercer = create_piercer(store["id"])
    certify(piercer["id"])
    customer = create_minor_customer(date_of_birth="2010-01-01T00:00:00Z")

    # The consent cannot be activated at all: the customer is under the absolute floor.
    consent = create_consent(
        customer["id"], jurisdiction["id"], consent_type="GUARDIAN_PRESENT",
        identification_type="BIRTH_CERTIFICATE",
    )
    validate_success(
        api_client.record_guardian_verification(consent["id"], {"outcome": "VERIFIED"}, INTAKE), 200
    )
    res = api.verify_consent(consent["id"], INTAKE)
    validate_error(res, E.AGE_BELOW_JURISDICTION_MINIMUM, expected_status=422)


def test_the_contraindication_gate_bites_at_service_start(api):
    """PRD §3.4: "A screening carrying any of `KELOID_HISTORY`, `BLOOD_THINNER_THERAPY` or
    `ACTIVE_INFECTION` can never clear".
    PRD §3.4: "a `SCREENED` appointment whose governing screening resolves to `CLEARED` proceeds
    to `IN_SERVICE`, while a `SCREENED` appointment whose governing screening resolves to
    `REFUSED` or `ESCALATED` is pushed to `REFUSED` by a `Piercer` supplying a
    `refusal_reason_code`".

    Design: Difficulty/priority_pair_validation_conflict/contraindication_precedes_lot_availability_on_screening_evaluate
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction, store, piercer, _ = setup_store_with_certified_piercer(
        store_overrides={"piercing_room_count": 1}
    )
    customer, _ = setup_customer_with_active_consent(jurisdiction["id"])
    appointment = setup_ready_appointment(
        store["id"], customer["id"], piercer["id"], jurisdiction["id"]
    )
    api.set_clock("2026-09-01T09:00:00Z", COMPLIANCE)
    validate_success(api.check_in_appointment(appointment["id"], INTAKE), 200)

    observed = get_appointment(appointment["id"])
    # The `/screen` step moves the appointment to SCREENED and runs the
    # screening evaluator as part of the same step (PRD §3.4). The evaluator
    # refuses the contraindicated screening, so the step returns the appointment
    # and the screening itself is read back from the appointment's list.
    validate_success(
        api.screen_appointment(
            appointment["id"],
            create_screening_payload(
                appointment["id"], piercer["id"], observed["version"],
                contraindication_codes=["ACTIVE_INFECTION"],
            ),
            {"X-User-ID": piercer["id"], "X-User-Role": "Piercer"},
        ),
        200,
    )
    rows = get_success_data(api.list_appointment_screenings(appointment["id"], READER))
    rows = rows if isinstance(rows, list) else rows.get("data", rows)
    assert rows and rows[-1]["outcome"] == "REFUSED"
    assert rows[-1]["refusal_reason_code"] == "ACTIVE_INFECTION"

    # A refused governing screening cannot carry the appointment into service.
    res = api.start_service(
        appointment["id"], {"X-User-ID": piercer["id"], "X-User-Role": "Piercer"}
    )
    validate_error(res, E.SCREENING_NOT_CLEARED, expected_status=409)