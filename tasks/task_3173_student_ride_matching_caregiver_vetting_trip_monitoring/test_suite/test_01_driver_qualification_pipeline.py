"""Driver qualification pipeline: experience, expiry and roster gates.

These tests exercise the gate conditions that hold a driver's inspection
attestation, the one operation that closes the qualification pipeline.
"""
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
)


def test_experience_shortfall_blocks_the_inspection_step():
    """PRD §3.3: "a driver's declared months must reach the twelve-month minimum
    in force, and a shortfall is refused with `ERR_CAREGIVER_EXPERIENCE_SHORT`
    (HTTP 422) at the points named below."
    PRD §3.3: "That second step requires the driver's declared caregiving
    experience to meet the twelve-month minimum, refusing a shortfall with
    `ERR_CAREGIVER_EXPERIENCE_SHORT` (HTTP 422), and requires at least one
    background check for the driver already to be in `CLEARED` result".

    Design: Difficulty/cross_entity_state_dependency/inspection_attestation_gated_by_the_driver_roster_state
    """
    set_clock("2026-09-01T00:00:00Z")
    short = onboard_driver(
        full_name="Short Experience", caregiver_experience_months=6
    )
    open_clearance(short["id"], "FINGERPRINT_FBI", "2027-03-01", clear=True)

    resp = record_inspection(
        short["id"], seat_count=6, inspector_note="premature",
        expires_on="2027-03-01", expect_success=False,
    )
    validate_error(resp, ApiErrorId.ERR_CAREGIVER_EXPERIENCE_SHORT)

    driver = read_driver(short["id"])
    assert driver["status"] == "BACKGROUND_CHECK", (
        f"a refused inspection must not advance the driver, got {driver['status']}"
    )
    inspections = get_success_data(
        api_client.list_driver_inspections(
            short["id"], TEST_USERS["district_admin_headers"]
        )
    )
    assert inspections == [], "no VehicleInspection row may exist after the refusal"


def test_attestation_refused_for_a_lapsed_inspection_date():
    """PRD §3.3: "Attestation requires the inspection to still be `PENDING`,
    requires its `expires_on` to fall strictly after the logical clock date — a
    lapsed date is refused with `ERR_CLEARANCE_EXPIRED` (HTTP 422)".

    Design: Difficulty/cross_entity_state_dependency/inspection_attestation_gated_by_the_driver_roster_state
    """
    set_clock("2026-09-01T00:00:00Z")
    driver = onboard_driver(caregiver_experience_months=18)
    open_clearance(driver["id"], "FINGERPRINT_FBI", "2027-03-01", clear=True)
    inspection = record_inspection(
        driver["id"], seat_count=6, inspector_note="clean",
        expires_on="2026-09-01",
    )

    resp = api_client.attest_inspection(
        inspection["id"], TEST_USERS["district_admin_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_CLEARANCE_EXPIRED)

    after = read_driver(driver["id"])
    assert after["status"] == "INSPECTION"
    assert after["approved_seat_count"] == 0
    assert after["compliance_expires_at"] is None


def test_attestation_refused_when_the_inspection_counts_no_usable_seats():
    """PRD §3.3: "requires the inspected `seat_count` to be at least one, since
    an inspection that counts no usable seats is refused with
    `ERR_INSPECTION_SEAT_COUNT` (HTTP 422)".

    Design: Difficulty/cross_entity_state_dependency/inspection_attestation_gated_by_the_driver_roster_state
    """
    set_clock("2026-09-01T00:00:00Z")
    driver = onboard_driver(caregiver_experience_months=18)
    open_clearance(driver["id"], "FINGERPRINT_FBI", "2027-03-01", clear=True)
    inspection = record_inspection(
        driver["id"], seat_count=0, inspector_note="no usable seats",
        expires_on="2027-03-01",
    )

    resp = api_client.attest_inspection(
        inspection["id"], TEST_USERS["district_admin_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_INSPECTION_SEAT_COUNT)

    after = read_driver(driver["id"])
    assert after["status"] == "INSPECTION", (
        "a zero-seat inspection cannot promote the driver to ACTIVE"
    )
    assert after["approved_seat_count"] == 0


def test_inspection_cannot_be_attested_before_the_roster_reaches_inspection():
    """PRD §3.3: "requires the driver to be in `INSPECTION` specifically,
    refusing any other driver status with `ERR_INVALID_STATE` (HTTP 409) even
    when the inspection itself is still pending."
    PRD §3.3: "In other words the pipeline will not skip a stage: a driver
    sitting in `PENDING` or `BACKGROUND_CHECK` cannot be promoted by attesting
    an inspection that happens to be pending."

    Design: Difficulty/cross_entity_state_dependency/inspection_attestation_gated_by_the_driver_roster_state
    """
    set_clock("2026-09-01T00:00:00Z")
    driver = onboard_driver(caregiver_experience_months=18)
    clearance = open_clearance(
        driver["id"], "FINGERPRINT_FBI", "2027-03-01", clear=True
    )
    inspection = record_inspection(
        driver["id"], seat_count=6, inspector_note="clean",
        expires_on="2027-03-01",
    )
    assert read_driver(driver["id"])["status"] == "INSPECTION"

    # Revoking the cleared clearance suspends the roster while the inspection
    # under test stays genuinely PENDING, so the attestation below faces a
    # driver status other than INSPECTION with a pending inspection on file.
    get_success_data(
        api_client.fail_background_check(
            clearance["id"], TEST_USERS["district_admin_headers"]
        )
    )
    assert read_driver(driver["id"])["status"] == "SUSPENDED"

    resp = api_client.attest_inspection(
        inspection["id"], TEST_USERS["district_admin_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    driver_after = read_driver(driver["id"])
    assert driver_after["status"] == "SUSPENDED", (
        "the refused attestation must not promote the roster"
    )
    remaining = get_success_data(
        api_client.list_driver_inspections(
            driver["id"], TEST_USERS["district_admin_headers"]
        )
    )
    assert [row["result"] for row in remaining] == ["PENDING"], (
        "the refusal leaves the inspection PENDING rather than consuming it"
    )