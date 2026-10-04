"""Creation, initial values and request-shape rules."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    E,
    api_client,
    create_appointment_payload,
    create_consent_payload,
    create_customer_payload,
    create_jurisdiction_payload,
    create_piercer_payload,
    create_store_payload,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    COMPLIANCE,
    INTAKE,
    MANAGER,
    READER,
    certify,
    create_customer,
    create_jurisdiction,
    create_piercer,
    create_store,
    set_clock,
    setup_cycle_and_lot,
)


def test_jurisdiction_creation_returns_configured_profile_with_initial_values(api):
    """PRD §2.4: "A profile is created in `status` `ACTIVE`".
    PRD §2.4: "Each profile is identified by a `state_code` that must consist of exactly
    two uppercase letters and must be unique across `Jurisdiction` rows".
    PRD §2.5: "`version` is an integer that increments by one on every mutation of the row".

    Design: Corner/entities/jurisdiction_create_returns_config_defaults_and_system_fields
    """
    set_clock()
    res = api.create_jurisdiction(
        create_jurisdiction_payload(
            permitted_sites=["LOBE", "UPPER_LOBE", "HELIX", "TRAGUS"],
        ),
        COMPLIANCE,
    )
    jurisdiction = validate_success(res, 201)

    assert jurisdiction["status"] == "ACTIVE"
    assert jurisdiction["version"] == 1
    assert jurisdiction["state_code"] == "IL"
    assert jurisdiction["min_age_self_consent"] == 18
    assert jurisdiction["min_age_with_guardian"] == 6
    assert jurisdiction["min_age_absolute"] == 6
    assert jurisdiction["permitted_sites"] == ["LOBE", "UPPER_LOBE", "HELIX", "TRAGUS"]
    assert jurisdiction["requires_guardian_presence"] is False
    assert jurisdiction["record_retention_years"] == 7
    assert jurisdiction["id"] is not None
    assert jurisdiction["created_at"] is not None
    assert jurisdiction["updated_at"] is not None


def test_customer_starts_active_with_zeroed_monetary_ledger(api):
    """PRD §3.1: "Registration creates the customer in `status` `ACTIVE` with
    `aftercare_credit_cents`, `refunded_cents` and `retained_cents` all starting at zero."
    PRD §2.5: "`Customer.aftercare_credit_cents`, `Customer.refunded_cents` and
    `Customer.retained_cents` start 0 and `Customer.status` starts `ACTIVE`."

    Design: Corner/entities/customer_defaults_are_zeroed_and_status_active_on_creation
    """
    set_clock()
    customer = create_customer()

    assert customer["status"] == "ACTIVE"
    assert customer["aftercare_credit_cents"] == 0
    assert customer["refunded_cents"] == 0
    assert customer["retained_cents"] == 0
    assert customer["version"] == 1


def test_get_unknown_jurisdiction_reports_jurisdiction_not_found(api):
    """PRD §2.11: "the resource-specific forms are `ERR_JURISDICTION_NOT_FOUND`".
    PRD §2.11: "the first identifier that does not resolve to an existing row terminates the
    request with an HTTP 404 carrying the error identifier for that specific missing resource".

    Design: Corner/entities/jurisdiction_get_unknown_id_returns_not_found
    """
    set_clock()
    res = api.get_jurisdiction(NON_EXISTENT_UUID, READER)
    validate_error(res, E.JURISDICTION_NOT_FOUND, expected_status=404)


def test_piercer_with_unknown_home_store_is_rejected(api):
    """PRD §2.11: "a parent that does not exist is reported before any child-level business
    rule is evaluated".
    PRD §2.11: "the resource-specific forms are `ERR_JURISDICTION_NOT_FOUND`,
    `ERR_STORE_NOT_FOUND`, `ERR_PIERCER_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`".

    Design: Corner/entities/piercer_create_rejects_unknown_home_store
    """
    set_clock()
    res = api.create_piercer(
        create_piercer_payload(home_store_id=NON_EXISTENT_UUID), MANAGER
    )
    validate_error(res, E.STORE_NOT_FOUND, expected_status=404)


def test_cartridge_lot_availability_is_derived_from_received_units(api):
    """PRD §2.7: "When a cycle closes as `PASSED`, every `CartridgeLot` bound to it becomes
    `AVAILABLE` with `units_available` equal to its `units_received`."
    PRD §2.7: "Its availability is governed by the calculation `cartridge_lot_availability`:
    `units_available` equals `units_received` minus `units_consumed` minus `units_quarantined`,
    floored at 0."

    Design: Corner/entities/cartridge_lot_computed_availability_derives_from_received
    """
    set_clock()
    jurisdiction = create_jurisdiction()
    store = create_store(jurisdiction["id"])
    _, lot = setup_cycle_and_lot(store["id"], units_received=50)

    fetched = get_success_data(api.get_cartridge_lot(lot["id"], READER))
    assert fetched["units_received"] == 50
    assert fetched["units_available"] == 50
    assert fetched["units_consumed"] == 0
    assert fetched["units_quarantined"] == 0
    assert fetched["status"] == "AVAILABLE"


def test_consent_with_unrecognized_type_is_a_malformed_request(api):
    """PRD §3.2: "A consent instrument is captured at intake as a `ConsentRecord` by an
    `IntakeAssociate`, who supplies `customer_id`, `jurisdiction_id`, `consent_type`,
    `identification_type`, `identification_number_masked` and `signed_at`."
    PRD §2.12: "A request that is missing a required field, that is malformed, or that
    violates a declared field constraint — a `state_code` that is not exactly two uppercase
    letters or is not unique, a `permitted_sites` entry outside the enumerated site set, a
    `contraindication_codes` entry outside the enumerated contraindication set, or a
    `reaction_codes` entry outside the enumerated reaction set — is rejected with
    `ERR_INVALID_REQUEST` at HTTP 400."

    Design: Corner/entities/consent_type_enum_violation_rejected
    """
    set_clock()
    jurisdiction = create_jurisdiction()
    customer = create_customer()

    res = api.create_consent(
        create_consent_payload(
            customer["id"], jurisdiction["id"], consent_type="FRIEND_PRESENT"
        ),
        INTAKE,
    )
    validate_error(res, E.INVALID_REQUEST, expected_status=400)


def test_appointment_is_created_booked_with_zero_reschedules(api):
    """PRD §3.3: "The appointment is created in `status` `BOOKED` with `reschedule_count` 0".
    PRD §2.5: "`Appointment.reschedule_count` starts 0 and `Appointment.status` starts `BOOKED`."

    Design: Corner/state_machines/appointment_new_row_starts_booked_with_zero_reschedules
    """
    set_clock()
    jurisdiction = create_jurisdiction()
    store = create_store(jurisdiction["id"])
    piercer = create_piercer(store["id"])
    certify(piercer["id"])
    customer = create_customer()

    res = api.create_appointment(
        create_appointment_payload(
            store["id"], customer["id"], piercer["id"], jurisdiction["id"]
        ),
        INTAKE,
    )
    appointment = validate_success(res, 201)

    assert appointment["status"] == "BOOKED"
    assert appointment["reschedule_count"] == 0


def test_store_retrieval_round_trips_the_posted_configuration(api):
    """PRD §2.7: "A `StoreLocation` is identified by its `name` and carries `jurisdiction_id`,
    the regime the store operates under, and `piercing_room_count`".
    PRD §2.5: "`StoreLocation.compliance_posture` starts `OPEN`, `StoreLocation.open_incident_count`
    starts 0, and `StoreLocation.status` starts `OPEN`."
    PRD §2.7: "reading a store's posture recomputes it before returning the store's
    `compliance_posture` and `open_incident_count`."

    Design: Corner/entities/store_retrieval_round_trips_configuration
    """
    set_clock()
    jurisdiction = create_jurisdiction()
    store = validate_success(
        api.create_store(
            create_store_payload(jurisdiction["id"], name="Chicago Loop", piercing_room_count=4),
            COMPLIANCE,
        ),
        201,
    )

    fetched = get_success_data(api.get_store(store["id"], READER))
    assert fetched["name"] == "Chicago Loop"
    assert fetched["piercing_room_count"] == 4
    assert fetched["jurisdiction_id"] == jurisdiction["id"]
    assert fetched["compliance_posture"] == "OPEN"
    assert fetched["open_incident_count"] == 0


def test_appointment_listing_reports_the_pagination_envelope(api):
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` in the
    `meta` object of the response envelope."
    PRD §2.3: "Unless a specific endpoint description says otherwise, list endpoints return
    rows ordered by `created_at` ascending."

    Design: Corner/entities/appointment_listing_paginates_with_total_count
    """
    set_clock()
    jurisdiction = create_jurisdiction()
    store = create_store(jurisdiction["id"])
    piercer = create_piercer(store["id"])
    certify(piercer["id"])
    customer = create_customer()
    validate_success(
        api.create_appointment(
            create_appointment_payload(
                store["id"], customer["id"], piercer["id"], jurisdiction["id"]
            ),
            INTAKE,
        ),
        201,
    )

    res = api.list_appointments(READER)
    data, meta = validate_paginated(res)
    assert len(data) == 1
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert isinstance(meta["limit"], int)
    assert isinstance(meta["offset"], int)