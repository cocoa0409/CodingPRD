"""Driver roster surface: server-derived fields, enum closure and the terminal
state of a deactivated driver."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_success_data,
    onboard_driver,
    open_clearance,
    read_driver,
    record_inspection,
    set_clock,
    validate_error,
    validate_success,
    vet_driver,
)


def test_a_vehicle_class_outside_the_declared_members_is_refused():
    """PRD §3.3: "a `vehicle_class` of `SEDAN`, `SUV` or `WHEELCHAIR_VAN`, a
    declared `seat_capacity`".

    Design: Corner/entities/driver_create_out_of_enum_vehicle_class_returns_invalid_request
    """
    resp = api_client.create_driver(
        {
            "full_name": "Dee Alvarez",
            "phone": "5550111",
            "employer_org": "CareGo",
            "caregiver_experience_months": 18,
            "language_codes": ["en"],
            "vehicle_class": "COUPE",
            "seat_capacity": 4,
        },
        TEST_USERS["district_admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    accepted = validate_success(
        api_client.create_driver(
            {
                "full_name": "Dee Alvarez",
                "phone": "5550111",
                "employer_org": "CareGo",
                "caregiver_experience_months": 18,
                "language_codes": ["en"],
                "vehicle_class": "WHEELCHAIR_VAN",
                "seat_capacity": 4,
            },
            TEST_USERS["district_admin_headers"],
        ),
        201,
    )
    assert accepted["vehicle_class"] == "WHEELCHAIR_VAN"


def test_the_driver_pipeline_will_not_skip_a_stage():
    """PRD §3.3: "From `PENDING`, opening a `check_type` background check under
    the driver — providing a `reference_code` and an `expires_on` — moves the
    driver into `BACKGROUND_CHECK`".
    PRD §3.3: "In other words the pipeline will not skip a stage".

    Design: Corner/state_machines/driver_machine_rejects_advancement_straight_to_inspection
    """
    set_clock("2026-09-01T00:00:00Z")
    driver = onboard_driver(caregiver_experience_months=18)
    assert driver["status"] == "PENDING"

    resp = record_inspection(
        driver["id"], seat_count=6, inspector_note="premature",
        expires_on="2027-03-01", expect_success=False,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert read_driver(driver["id"])["status"] == "PENDING"
    assert get_success_data(
        api_client.list_driver_inspections(
            driver["id"], TEST_USERS["district_admin_headers"]
        )
    ) == []

    open_clearance(driver["id"], "FINGERPRINT_FBI", "2027-03-01", clear=True)
    assert read_driver(driver["id"])["status"] == "BACKGROUND_CHECK"
    record_inspection(driver["id"], seat_count=6, inspector_note="clean")
    assert read_driver(driver["id"])["status"] == "INSPECTION", (
        "the same inspection call now advances the pipeline"
    )


def test_a_new_driver_lands_in_the_declared_initial_state():
    """PRD §3.3: "A newly onboarded driver begins in `PENDING` status with a
    zero `approved_seat_count`, a null `compliance_expires_at` and a zero
    `incident_strike_count`."

    Design: Corner/state_machines/new_driver_lands_in_the_declared_initial_state
    """
    driver = onboard_driver(
        caregiver_experience_months=18, vehicle_class="SEDAN", seat_capacity=4
    )
    assert driver["status"] == "PENDING"
    assert driver["approved_seat_count"] == 0
    assert driver["compliance_expires_at"] is None
    assert driver["incident_strike_count"] == 0
    assert driver["version"] == 1


def test_an_inactivated_driver_admits_no_further_transition():
    """PRD §3.3: "A `DistrictAdmin` may deactivate the driver, moving them to
    `INACTIVE` with a zeroed approved seat count".
    PRD §2.5: "a resource that has already reached a terminal state for the
    dimension in question reports `ERR_ALREADY_TERMINAL` (HTTP 409) rather than
    the ordinary wrong-state error `ERR_INVALID_STATE` (HTTP 409)".
    PRD §2.4: "It is null whenever the driver's `status` is `PENDING` or
    `INACTIVE`".

    Design: Corner/state_machines/inactivated_driver_carries_no_further_transitions
    """
    driver = vet_driver()
    assert driver["status"] == "ACTIVE"
    assert driver["approved_seat_count"] == 6

    validate_success(
        api_client.deactivate_driver(driver["id"], TEST_USERS["district_admin_headers"])
    )
    inactive = read_driver(driver["id"])
    assert inactive["status"] == "INACTIVE"
    assert inactive["approved_seat_count"] == 0

    # PRD reports no compliance expiry at all for an INACTIVE driver, and
    # INACTIVE is terminal for the driver dimension, so the reactivation is
    # refused as a terminal probe rather than as a wrong-state error.
    assert inactive["compliance_expires_at"] is None
    reactivate = api_client.reactivate_driver(
        driver["id"], TEST_USERS["district_admin_headers"]
    )
    validate_error(reactivate, ApiErrorId.ERR_ALREADY_TERMINAL)

    still_inactive = read_driver(driver["id"])
    assert still_inactive["status"] == "INACTIVE"
    assert still_inactive["approved_seat_count"] == 0


def test_the_second_fingerprint_clearance_of_the_same_type_is_refused():
    """PRD §3.3: "This first step requires the driver to be in `PENDING` and
    refuses a driver who already holds a `FINGERPRINT_FBI` check with
    `ERR_DUPLICATE_CLEARANCE` (HTTP 409)."

    Design: Corner/state_machines/driver_background_check_transition_is_not_re_enterable
    """
    set_clock("2026-09-01T00:00:00Z")
    driver = onboard_driver(caregiver_experience_months=18)
    first = open_clearance(
        driver["id"], "FINGERPRINT_FBI", "2027-03-01", clear=False,
        reference_code="FBI-I",
    )
    assert read_driver(driver["id"])["status"] == "BACKGROUND_CHECK"

    resp = api_client.open_background_check(
        driver["id"],
        {
            "check_type": "FINGERPRINT_FBI",
            "reference_code": "FBI-I-B",
            "expires_on": "2027-04-01",
        },
        TEST_USERS["district_admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLEARANCE)

    assert read_driver(driver["id"])["status"] == "BACKGROUND_CHECK"
    checks = get_success_data(
        api_client.list_driver_background_checks(
            driver["id"], TEST_USERS["district_admin_headers"]
        )
    )
    assert [check["reference_code"] for check in checks] == ["FBI-I"], (
        "the driver still holds exactly the first check"
    )

    accepted = validate_success(
        api_client.open_background_check(
            driver["id"],
            {
                "check_type": "COUNTY_COURT",
                "reference_code": "C-I",
                "expires_on": "2027-03-01",
            },
            TEST_USERS["district_admin_headers"],
        ),
        201,
    )
    assert accepted["check_type"] == "COUNTY_COURT", (
        "the duplication rule is per check type"
    )