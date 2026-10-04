"""Cross-entity dependencies: an operation that is legal only because of the
state of a different resource in the same graph.
"""
from test_helpers import (
    COMPLIANCE,
    FLEET,
    api_client,
    create_unlimited_agreement_payload,
    get_agreement,
    get_driver,
    get_success_data,
    get_vehicle,
    get_week,
    register_driver,
    make_driver_headers,
    setup_with_delinquent_weeks,
    validate_error,
)
from test_helpers.api_errors import ApiErrorId


def test_activation_is_refused_once_the_authorising_enrolment_is_withdrawn(api):
    """PRD §3.3: "Three things must be true first: the authorising enrolment's
    enrollment_status must be ACTIVE, or the request is rejected with
    ERR_ENROLLMENT_NOT_ACTIVE (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/agreement_activation_requires_active_enrollment
    """
    driver = register_driver()
    enrollment = get_success_data(api_client.enroll_driver(
        {"driver_id": driver["id"], "program_tier": "TIER_1"}, COMPLIANCE
    ), expected_status=201)
    api_client.verify_enrollment(enrollment["id"], COMPLIANCE)
    vehicle = get_success_data(api_client.admit_vehicle(
        {
            "vin": "1HGCM82633A004352", "model_name": "Civic", "model_year": 2022,
            "vehicle_class": "STANDARD", "odometer_miles": 40_000, "region_code": "CA",
        },
        FLEET,
    ), expected_status=201)
    agreement = get_success_data(api_client.create_agreement(
        create_unlimited_agreement_payload(enrollment["id"], driver["id"], vehicle["id"]),
        FLEET,
    ), expected_status=201)

    withdrawn = get_success_data(api_client.withdraw_enrollment(
        enrollment["id"], make_driver_headers(driver["id"])
    ))
    assert withdrawn["enrollment_status"] == "WITHDRAWN"

    response = api_client.activate_agreement(agreement["id"], FLEET)
    validate_error(response, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE, 409)
    assert get_agreement(agreement["id"])["agreement_status"] == "DRAFT"
    assert get_vehicle(vehicle["id"])["vehicle_status"] == "AVAILABLE"


def test_the_draft_agreement_itself_is_not_what_blocks_the_withdrawal(api):
    """PRD §3.1: "A driver leaving the programme, or a ComplianceOfficer
    withdrawing an active or suspended enrolment on the driver's behalf, is
    refused while any agreement of that enrolment still holds occupancy.
    Occupancy-holding agreement states are ACTIVE, RENEWAL_DUE, DELINQUENT,
    RECOVERY_PENDING and PURCHASE_PENDING; an agreement in any other state -
    DRAFT, RECOVERED, COMPLETED, PURCHASED - does not block withdrawal."

    Design: Difficulty/cross_entity_state_dependency/agreement_activation_requires_active_enrollment
    """
    driver = register_driver()
    enrollment = get_success_data(api_client.enroll_driver(
        {"driver_id": driver["id"], "program_tier": "TIER_1"}, COMPLIANCE
    ), expected_status=201)
    api_client.verify_enrollment(enrollment["id"], COMPLIANCE)
    vehicle = get_success_data(api_client.admit_vehicle(
        {
            "vin": "1HGCM82633A004353", "model_name": "Civic", "model_year": 2022,
            "vehicle_class": "STANDARD", "odometer_miles": 40_000, "region_code": "CA",
        },
        FLEET,
    ), expected_status=201)
    api_client.create_agreement(
        create_unlimited_agreement_payload(enrollment["id"], driver["id"], vehicle["id"]),
        FLEET,
    )

    response = api_client.withdraw_enrollment(
        enrollment["id"], make_driver_headers(driver["id"])
    )
    assert response.status_code == 200, "a DRAFT agreement does not hold occupancy"

    driver_row = get_driver(driver["id"])
    assert driver_row["eligibility_status"] == "INELIGIBLE", (
        "the driver holds no other ACTIVE enrolment, so their posture is forced to INELIGIBLE"
    )


def test_a_delinquent_week_reopens_while_the_posture_is_restricted(api):
    """PRD §3.8: "Reopening requires week_status to be DELINQUENT,
    compliance_posture to be exactly RESTRICTED, and eligibility_status to be
    ELIGIBLE - in other words, it is available in the narrow window where the
    agreement has been flagged but not yet frozen."
    PRD §3.8: "A reopened week's week_status returns to OPEN with payment_status
    reset to UNPAID, and both deadlines are freshly stamped: payment_deadline
    moves to seven days from the logical clock instant and grace_deadline to 72
    hours after that."

    Design: Difficulty/cross_entity_state_dependency/week_reopen_requires_restricted_not_frozen_posture
    """
    ctx = setup_with_delinquent_weeks(count=1, unlimited=True)
    week_id = ctx.weeks[0]["id"]

    assert get_agreement(ctx.agreement["id"])["compliance_posture"] == "RESTRICTED"
    assert get_driver(ctx.driver["id"])["eligibility_status"] == "ELIGIBLE"

    reopened = get_success_data(api_client.reopen_week(week_id, COMPLIANCE))
    assert reopened["week_status"] == "OPEN"
    assert reopened["payment_status"] == "UNPAID"
    assert reopened["payment_deadline"] == "2026-09-18T00:00:00Z"
    assert reopened["grace_deadline"] == "2026-09-21T00:00:00Z"

    agreement = get_agreement(ctx.agreement["id"])
    assert agreement["compliance_posture"] == "OPEN", (
        "reopening genuinely relieves the posture rather than masking it"
    )
    assert agreement["agreement_status"] == "ACTIVE"


def test_a_frozen_agreement_cannot_reopen_its_delinquent_week(api):
    """PRD §3.8: "it is unavailable precisely when the situation has escalated
    past that point or when the driver is already suspended."
    PRD §3.8: "One at FROZEN whose count drops back to 1 returns to RESTRICTED."

    Design: Difficulty/cross_entity_state_dependency/week_reopen_requires_restricted_not_frozen_posture
    """
    ctx = setup_with_delinquent_weeks(count=2, unlimited=True)
    assert get_agreement(ctx.agreement["id"])["compliance_posture"] == "FROZEN"
    assert get_driver(ctx.driver["id"])["eligibility_status"] == "SUSPENDED"

    response = api_client.reopen_week(ctx.weeks[0]["id"], COMPLIANCE)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_week(ctx.weeks[0]["id"])["week_status"] == "DELINQUENT"
    assert get_agreement(ctx.agreement["id"])["compliance_posture"] == "FROZEN"