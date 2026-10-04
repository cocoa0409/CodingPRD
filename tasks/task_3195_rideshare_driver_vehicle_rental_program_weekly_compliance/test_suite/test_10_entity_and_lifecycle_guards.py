"""Entity intake guards, envelope shape and state-machine lifecycle refusals."""
from test_helpers import (
    ADMIN,
    COMPLIANCE,
    FLEET,
    NON_EXISTENT_UUID,
    api_client,
    create_agreement_payload,
    create_driver_payload,
    create_enrollment_payload,
    get_success_data,
    get_vehicle,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId


def _admit(vin, **overrides):
    payload = {
        "vin": vin, "model_name": "Civic", "model_year": 2022,
        "vehicle_class": "STANDARD", "odometer_miles": 40_000, "region_code": "CA",
    }
    payload.update(overrides)
    return get_success_data(api_client.admit_vehicle(payload, FLEET), expected_status=201)


def _driver_and_verified_enrollment():
    driver = get_success_data(api_client.register_driver(
        create_driver_payload(email="owner@example.com", platform_driver_id="PLT-8K2M4QX9"),
        ADMIN,
    ), expected_status=201)
    enrollment = get_success_data(api_client.enroll_driver(
        create_enrollment_payload(driver["id"]), COMPLIANCE
    ), expected_status=201)
    api_client.verify_enrollment(enrollment["id"], COMPLIANCE)
    return driver, enrollment


def test_registering_a_driver_without_a_platform_identity_is_malformed(api):
    """PRD §3.1: "When a PlatformAdmin registers a driver, the payload carries the
    driver's legal name as full_name, a contact email as email, the external
    rideshare-platform identity used for activity verification as
    platform_driver_id, the driver's latest platform activity score as
    platform_activity_score, accumulated driving-record points as
    driving_record_points, the licence class presented at enrolment as
    license_class, and the programme tier at admission as program_driver_tier."

    Design: Corner/entities/create_driver_requires_all_declared_fields
    """
    incomplete = create_driver_payload()
    incomplete.pop("platform_driver_id")

    response = api_client.register_driver(incomplete, ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    listed = api_client.list_drivers(ADMIN)
    _, meta = validate_paginated(listed)
    assert meta["total_count"] == 0


def test_a_driver_is_registered_with_pending_eligibility(api):
    """PRD §3.1: "A newly registered driver starts with eligibility_status of
    PENDING."
    PRD §3.1: "Freshly entered drivers sit at PENDING"

    Design: Corner/entities/create_driver_requires_all_declared_fields
    """
    payload = create_driver_payload(platform_driver_id="PLT-8K2M4QX9")
    created = validate_success(
        api_client.register_driver(payload, ADMIN), expected_status=201
    )
    assert created["eligibility_status"] == "PENDING"
    assert created["platform_driver_id"] == "PLT-8K2M4QX9"
    assert created["platform_activity_score"] == payload["platform_activity_score"]


def test_a_derived_field_supplied_by_the_caller_is_undeclared(api):
    """PRD §2.7: "Payload schema. The body must supply every required field and
    must not carry any undeclared field. Failure is ERR_INVALID_REQUEST (HTTP
    400)."
    PRD §2.4: "A derived field is a mutation like any other"

    Design: Corner/entities/create_driver_ignores_system_fields
    """
    payload = create_driver_payload(platform_driver_id="PLT-8K2M4QX8")
    payload["eligibility_status"] = "ELIGIBLE"

    response = api_client.register_driver(payload, ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_a_driver_created_without_the_computed_field_starts_pending(api):
    """PRD §3.1: "A newly registered driver starts with eligibility_status of
    PENDING."
    PRD §2.4: "version (integer): a monotonically increasing integer that advances
    by exactly one on every mutation of the row."

    Design: Corner/entities/create_driver_ignores_system_fields
    """
    payload = create_driver_payload(platform_driver_id="PLT-8K2M4QX7")
    created = get_success_data(api_client.register_driver(payload, ADMIN), expected_status=201)
    assert "eligibility_status" in created
    assert created["eligibility_status"] == "PENDING"
    assert created["version"] == 1


def test_an_agreement_naming_a_foreign_key_that_does_not_exist_is_refused(api):
    """PRD §2.7: "Referential existence. Every foreign key in the request body
    must name an existing row of the referenced resource. Failure is
    ERR_REFERENCED_ENTITY_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/create_agreement_requires_existing_foreign_keys
    """
    driver, enrollment = _driver_and_verified_enrollment()

    response = api_client.create_agreement(
        create_agreement_payload(
            enrollment["id"], driver["id"],
            "3f7a1c2e-9b4d-4e8a-8c1f-2d5e6a7b8c9d",
        ),
        FLEET,
    )
    validate_error(response, ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND, 404)


def test_existence_is_checked_before_availability(api):
    """PRD §2.7: "Referential existence. Every foreign key in the request body
    must name an existing row of the referenced resource. Failure is
    ERR_REFERENCED_ENTITY_NOT_FOUND (HTTP 404)."
    PRD §2.7: "Guards 1 through 7 are universal: they apply to every call, and
    guards 5 and 6 in particular apply to every path-addressed call and to every
    call whose body carries a foreign key."

    Design: Corner/entities/create_agreement_requires_existing_foreign_keys
    """
    driver, enrollment = _driver_and_verified_enrollment()

    response = api_client.create_agreement(
        create_agreement_payload(enrollment["id"], driver["id"], NON_EXISTENT_UUID),
        FLEET,
    )
    assert response.status_code == 404
    assert response.json()["data"]["error_id"] == "ERR_REFERENCED_ENTITY_NOT_FOUND", (
        "no ERR_VEHICLE_NOT_AVAILABLE may be raised for a unit that does not exist"
    )
    assert api_client.list_agreements(FLEET).json()["meta"]["total_count"] == 0


def test_fetching_a_unit_that_does_not_exist_is_not_found(api):
    """PRD §2.7: "Path existence. The resource addressed by the path must exist.
    Failure is ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_vehicle_with_unknown_id_returns_not_found
    """
    response = api_client.get_vehicle("3f7a1c2e-9b4d-4e8a-8c1f-2d5e6a7b8c9d", FLEET)
    validate_error(response, ApiErrorId.ERR_NOT_FOUND, 404)
    assert response.json()["response_type"] == "error"
    assert response.json()["data"]["error_id"] == "ERR_NOT_FOUND"


def test_an_unknown_unit_id_is_reported_on_the_error_envelope(api):
    """PRD §2.2: "The error_id is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.10: "a request that names a non-existent parent is rejected for the
    parent, not for a deeper cause."

    Design: Corner/entities/get_vehicle_with_unknown_id_returns_not_found
    """
    response = api_client.get_vehicle(NON_EXISTENT_UUID, FLEET)
    assert response.status_code == 404
    body = response.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert body["data"]["message"].strip()


def test_listing_units_paginates_with_a_total_count(api):
    """PRD §2.3: "limit caps the number of items in the page; when omitted it
    defaults to 10, and the server enforces a floor of 1 and a ceiling of 100."
    PRD §2.3: "The meta object of a list response carries limit, offset,
    total_count and has_more alongside the request identifiers, so a caller can
    walk a result set without a second count query."

    Design: Corner/entities/list_vehicles_paginates_with_total_count
    """
    _admit("1HGCM82633A004352", odometer_miles=40_000)
    _admit("2HGES16575H606231", odometer_miles=61_000)
    _admit("5TFAX5GN2GX123456", model_name="Pilot", model_year=2023,
           vehicle_class="XL", odometer_miles=22_000)

    page, meta = validate_paginated(api_client.list_vehicles(
        FLEET, params={"region_code": "CA", "limit": 2, "offset": 0}
    ))
    assert len(page) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert all(row["region_code"] == "CA" for row in page)


def test_the_second_page_closes_the_result_set(api):
    """PRD §3.10: "active_agreements_count is taken to be that same figure - the
    programme treats the two as identical by construction"

    Design: Corner/entities/list_vehicles_paginates_with_total_count
    """
    _admit("1HGCM82633A004361")
    _admit("2HGES16575H606241")
    _admit("5TFAX5GN2GX123461", model_name="Pilot", model_year=2023, vehicle_class="XL")

    first, first_meta = validate_paginated(api_client.list_vehicles(
        FLEET, params={"region_code": "CA", "limit": 2, "offset": 0}
    ))
    second, second_meta = validate_paginated(api_client.list_vehicles(
        FLEET, params={"region_code": "CA", "limit": 2, "offset": 2}
    ))

    assert first_meta["has_more"] is True
    assert second_meta["has_more"] is False
    assert len(second) == 1
    assert first_meta["total_count"] == second_meta["total_count"] == 3


def test_activating_an_already_active_agreement_is_an_inadmissible_state(api):
    """PRD §3.3: "Moving an agreement from DRAFT to ACTIVE is what actually puts a
    unit on the road, and it is reserved to a FleetOpsAgent."
    PRD §2.7: "State admissibility. The target resource must be in a state from
    which the requested operation is declared. Failure is ERR_INVALID_STATE (HTTP
    409)."

    Design: Corner/state_machines/activate_agreement_from_active_returns_invalid_state
    """
    driver, enrollment = _driver_and_verified_enrollment()
    vehicle = _admit("1HGCM82633A004381")
    agreement = get_success_data(api_client.create_agreement(
        create_agreement_payload(enrollment["id"], driver["id"], vehicle["id"]),
        FLEET,
    ), expected_status=201)
    api_client.activate_agreement(agreement["id"], FLEET)

    response = api_client.activate_agreement(agreement["id"], FLEET)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)
    body = get_success_data(api_client.get_agreement(agreement["id"], FLEET))
    assert body["agreement_status"] == "ACTIVE"
    assert get_vehicle(vehicle["id"])["assigned_driver_id"] == driver["id"]


def test_a_completed_agreement_is_locked_down(api):
    """PRD §3.8: "Completion requires that no week of the agreement has
    week_status in DUE, GRACE or DELINQUENT"
    PRD §3.3: "Moving an agreement from DRAFT to ACTIVE is what actually puts a
    unit on the road"

    Design: Corner/state_machines/complete_terminal_agreement_is_refused
    """
    driver, enrollment = _driver_and_verified_enrollment()
    vehicle = _admit("1HGCM82633A004382")
    agreement = get_success_data(api_client.create_agreement(
        create_agreement_payload(enrollment["id"], driver["id"], vehicle["id"]),
        FLEET,
    ), expected_status=201)
    api_client.activate_agreement(agreement["id"], FLEET)
    api_client.complete_agreement(agreement["id"], FLEET)

    response = api_client.complete_agreement(agreement["id"], FLEET)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)
    assert api_client.get_agreement(agreement["id"], FLEET).json()["data"]["agreement_status"] == "COMPLETED"
    assert get_vehicle(vehicle["id"])["vehicle_status"] == "AVAILABLE"


def test_closing_an_agreement_returns_its_unit_to_the_pool(api):
    """PRD §3.8: "On success vehicle_status returns from ASSIGNED to AVAILABLE
    with assigned_driver_id cleared, and agreement_status becomes COMPLETED,
    another of its terminal values."

    Design: Corner/state_machines/complete_terminal_agreement_is_refused
    """
    driver, enrollment = _driver_and_verified_enrollment()
    vehicle = _admit("1HGCM82633A004383")
    agreement = get_success_data(api_client.create_agreement(
        create_agreement_payload(enrollment["id"], driver["id"], vehicle["id"]),
        FLEET,
    ), expected_status=201)
    api_client.activate_agreement(agreement["id"], FLEET)
    completed = get_success_data(api_client.complete_agreement(agreement["id"], FLEET))

    assert completed["agreement_status"] == "COMPLETED"
    released = get_vehicle(vehicle["id"])
    assert released["vehicle_status"] == "AVAILABLE"
    assert released["assigned_driver_id"] is None


def test_issuing_a_loaner_before_the_work_starts_is_refused(api):
    """PRD §3.7: "Issuing one is a distinct step a FleetOpsAgent takes against an
    event already in IN_PROGRESS, and it is gated in several ways: event_status
    must be IN_PROGRESS"

    Design: Corner/state_machines/issue_loaner_before_start_returns_invalid_state
    """
    ctx = _active_agreement_with_reported_event()
    from test_helpers import create_maintenance_event_payload, vehicle_version

    response = api_client.issue_loaner(ctx["event"]["id"], FLEET)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

    event = api_client.get_maintenance_event(ctx["event"]["id"], COMPLIANCE).json()["data"]
    assert event["event_status"] == "REPORTED"
    assert event["loaner_vehicle_id"] is None
    assert get_vehicle(ctx["spare"]["id"])["vehicle_status"] == "AVAILABLE"


def test_the_reported_event_is_untouched_by_the_refused_loaner(api):
    """PRD §3.7: "event_status must be IN_PROGRESS; downtime_hours must exceed 24"
    PRD §2.8: "the programme never fabricates a unit, never promotes a
    non-conforming unit, and never quietly leaves the driver without cover."

    Design: Corner/state_machines/issue_loaner_before_start_returns_invalid_state
    """
    ctx = _active_agreement_with_reported_event()
    api_client.issue_loaner(ctx["event"]["id"], FLEET)

    assert get_vehicle(ctx["vehicle"]["id"])["vehicle_status"] == "MAINTENANCE"
    assert get_vehicle(ctx["spare"]["id"])["vehicle_status"] == "AVAILABLE"
    assert ctx["event"]["downtime_hours"] == 30


def test_verifying_an_already_active_enrolment_is_refused(api):
    """PRD §3.1: "An APPROVED enrolment moves enrollment_status from
    PENDING_VERIFICATION to ACTIVE, the driver's eligibility_status moves from
    PENDING to ELIGIBLE, and verified_at is stamped with the logical clock
    instant."

    Design: Corner/state_machines/verify_unverified_enrollment_twice_is_idempotent_refused
    """
    driver, enrollment = _driver_and_verified_enrollment()

    response = api_client.verify_enrollment(enrollment["id"], COMPLIANCE)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)
    assert api_client.get_enrollment(enrollment["id"], COMPLIANCE).json()[
        "data"
    ]["enrollment_status"] == "ACTIVE"


def test_a_verified_enrolment_leaves_the_driver_eligible(api):
    """PRD §3.1: "An APPROVED enrolment moves enrollment_status from
    PENDING_VERIFICATION to ACTIVE, the driver's eligibility_status moves from
    PENDING to ELIGIBLE, and verified_at is stamped with the logical clock
    instant."

    Design: Corner/state_machines/verify_unverified_enrollment_twice_is_idempotent_refused
    """
    driver, enrollment = _driver_and_verified_enrollment()
    row = api_client.get_enrollment(enrollment["id"], COMPLIANCE).json()["data"]
    assert row["enrollment_status"] == "ACTIVE"
    assert row["verified_at"] == "2026-09-01T00:00:00Z"
    assert api_client.get_driver(driver["id"], COMPLIANCE).json()["data"][
        "eligibility_status"
    ] == "ELIGIBLE"


def _active_agreement_with_reported_event():
    """An ACTIVE agreement whose assigned unit is under a REPORTED 30-hour repair."""
    from test_helpers import (
        create_maintenance_event_payload,
        create_unlimited_agreement_payload,
        vehicle_version,
    )

    driver, enrollment = _driver_and_verified_enrollment()
    vehicle = _admit("1HGCM82633A004391")
    spare = _admit("2HGES16575H606251", odometer_miles=61_000)
    agreement = get_success_data(api_client.create_agreement(
        create_unlimited_agreement_payload(enrollment["id"], driver["id"], vehicle["id"]),
        FLEET,
    ), expected_status=201)
    api_client.activate_agreement(agreement["id"], FLEET)
    event = get_success_data(api_client.report_maintenance_event(
        create_maintenance_event_payload(
            agreement["id"], vehicle["id"],
            expected_vehicle_version=vehicle_version(vehicle["id"]),
            downtime_hours=30,
        ),
        FLEET,
    ), expected_status=201)
    return {
        "driver": driver, "enrollment": enrollment, "vehicle": vehicle,
        "spare": spare, "agreement": agreement, "event": event,
    }