"""Named rejections: the error identifiers the catalogue pins, at their own
trigger conditions.
"""
from test_helpers import (
    ADMIN,
    COMPLIANCE,
    FLEET,
    SUPPORT,
    api_client,
    create_enrollment_payload,
    create_platform_check_payload,
    create_unlimited_agreement_payload,
    enroll_and_verify,
    get_success_data,
    get_vehicle,
    get_week,
    lapse_grace,
    register_driver,
    set_clock,
    setup_agreement_with_due_week,
    setup_option_elected,
    validate_error,
)
from test_helpers.api_errors import ApiErrorId


def test_a_driving_record_over_six_is_refused_at_enrolment(api):
    """PRD §3.1: "A driver whose accumulated record points exceed 6 at the instant
    of evaluation is refused outright with ERR_DRIVING_RECORD_INELIGIBLE (HTTP
    422), and a driver whose platform activity score sits below the programme's
    activity floor of 50 points is refused with ERR_PLATFORM_ACTIVITY_INSUFFICIENT
    (HTTP 422)."

    Design: Corner/errors/driving_record_over_six_is_ineligible
    """
    driver = register_driver(platform_activity_score=95, driving_record_points=7)

    response = api_client.enroll_driver(create_enrollment_payload(driver["id"]), COMPLIANCE)
    validate_error(response, ApiErrorId.ERR_DRIVING_RECORD_INELIGIBLE, 422)
    assert api_client.list_enrollments(COMPLIANCE, params={"driver_id": driver["id"]}).json()[
        "meta"
    ]["total_count"] == 0


def test_the_driving_record_gate_does_not_consult_the_licence_class(api):
    """PRD §3.1: "enrolment is the one operation where the raw licence class is
    not consulted; the driving record is what gates it."

    Design: Corner/errors/driving_record_over_six_is_ineligible
    """
    driver = register_driver(
        platform_activity_score=95, driving_record_points=7, license_class="STANDARD"
    )
    response = api_client.enroll_driver(create_enrollment_payload(driver["id"]), COMPLIANCE)
    assert response.status_code == 422
    assert response.json()["data"]["error_id"] == "ERR_DRIVING_RECORD_INELIGIBLE"


def test_a_second_unit_is_refused_for_a_driver_already_holding_one(api):
    """PRD §3.3: "the driver may not already hold a unit in ASSIGNED status, or the
    request is rejected with ERR_DRIVER_VEHICLE_CONFLICT (HTTP 409)"

    Design: Corner/errors/driver_cannot_hold_two_units_at_once
    """
    ctx = setup_driver_with_active_agreement()
    second = get_success_data(api_client.admit_vehicle(
        {
            "vin": "2HGES16575H606261", "model_name": "Civic", "model_year": 2022,
            "vehicle_class": "STANDARD", "odometer_miles": 61_000, "region_code": "CA",
        },
        FLEET,
    ), expected_status=201)

    response = api_client.create_agreement(
        create_unlimited_agreement_payload(
            ctx["enrollment"]["id"], ctx["driver"]["id"], second["id"]
        ),
        FLEET,
    )
    validate_error(response, ApiErrorId.ERR_DRIVER_VEHICLE_CONFLICT, 409)


def test_the_conflict_resolves_on_the_driver_not_on_the_vehicle(api):
    """PRD §2.7: "Single-unit rule. The driver must not already hold a
    ProgramVehicle in ASSIGNED status. Failure is ERR_DRIVER_VEHICLE_CONFLICT
    (HTTP 409)."

    Design: Corner/errors/driver_cannot_hold_two_units_at_once
    """
    ctx = setup_driver_with_active_agreement()
    second = get_success_data(api_client.admit_vehicle(
        {
            "vin": "2HGES16575H606262", "model_name": "Civic", "model_year": 2022,
            "vehicle_class": "STANDARD", "odometer_miles": 62_000, "region_code": "CA",
        },
        FLEET,
    ), expected_status=201)

    api_client.create_agreement(
        create_unlimited_agreement_payload(
            ctx["enrollment"]["id"], ctx["driver"]["id"], second["id"]
        ),
        FLEET,
    )
    assert get_vehicle(second["id"])["vehicle_status"] == "AVAILABLE"
    assert api_client.list_agreements(
        FLEET, params={"driver_id": ctx["driver"]["id"]}
    ).json()["meta"]["total_count"] == 1


def test_a_unit_that_only_qualifies_for_delivery_may_not_serve_rides(api):
    """PRD §3.3: "the unit's class must actually be permitted for the activity the
    platform requires of it - a unit that only qualifies for delivery work may not
    be presented against a ride-only requirement, and the attempt is rejected with
    ERR_MODEL_NOT_QUALIFIED (HTTP 409)."
    PRD §3.3: "a DELIVERY_VAN unit will never qualify for ride work"

    Design: Corner/errors/delivery_vans_cannot_serve_ride_only_assignment
    """
    ctx = setup_driver_with_active_agreement()
    van = get_success_data(api_client.admit_vehicle(
        {
            "vin": "3VWFE21C04M000001", "model_name": "Sprinter", "model_year": 2023,
            "vehicle_class": "DELIVERY_VAN", "odometer_miles": 18_000, "region_code": "CA",
        },
        FLEET,
    ), expected_status=201)
    assert van["qualifies_ride"] is False

    response = api_client.submit_platform_check(
        create_platform_check_payload(ctx["agreement"]["id"], van["id"]), COMPLIANCE
    )
    validate_error(response, ApiErrorId.ERR_MODEL_NOT_QUALIFIED, 409)


def test_a_standard_unit_passes_the_same_qualification_check(api):
    """PRD §3.3: "ride_qualified is true when the class is STANDARD, XL or LUXURY -
    three classes. delivery_qualified is true when the class is STANDARD, XL or
    DELIVERY_VAN - also three classes. model_restriction_hit is set whenever the
    unit fails either of those two predicates."

    Design: Corner/errors/delivery_vans_cannot_serve_ride_only_assignment
    """
    ctx = setup_driver_with_active_agreement()
    check = get_success_data(api_client.submit_platform_check(
        create_platform_check_payload(ctx["agreement"]["id"], ctx["vehicle"]["id"]),
        COMPLIANCE,
    ), expected_status=201)

    assert check["integration_result"] == "QUALIFIED"
    assert check["ride_qualified"] is True
    assert check["delivery_qualified"] is True
    assert check["model_restriction_hit"] is False


def test_declaring_a_week_delinquent_before_grace_lapses_is_refused(api):
    """PRD §3.8: "the week must be in GRACE, and the logical clock must be at or
    past its grace deadline, or the request is rejected with ERR_GRACE_NOT_LAPSED
    (HTTP 422)."

    Design: Corner/errors/grace_not_lapsed_refuses_declaration
    """
    ctx = setup_agreement_with_due_week(unlimited=True)
    set_clock("2026-09-10T23:00:00Z")

    response = api_client.grace_lapse(ctx.week["id"], COMPLIANCE)
    validate_error(response, ApiErrorId.ERR_GRACE_NOT_LAPSED, 422)
    assert get_week(ctx.week["id"])["week_status"] == "GRACE"


def test_the_identical_call_succeeds_once_the_deadline_has_passed(api):
    """PRD §3.8: "Declaring the week delinquent is a deliberate step taken by a
    ComplianceOfficer after that grace has lapsed: the week must be in GRACE, and
    the logical clock must be at or past its grace deadline"

    Design: Corner/errors/grace_not_lapsed_refuses_declaration
    """
    ctx = setup_agreement_with_due_week(unlimited=True)
    set_clock("2026-09-11T00:00:00Z")

    declared = lapse_grace(ctx.week["id"])
    assert declared["week_status"] == "DELINQUENT"
    assert declared["payment_status"] == "FAILED"


def test_an_unfunded_option_may_not_be_completed(api):
    """PRD §3.9: "Completion requires escrow_weeks_funded to have reached
    escrow_weeks_required - otherwise the request is rejected with
    ERR_ESCROW_INCOMPLETE (HTTP 422)"

    Design: Corner/errors/escrow_incomplete_refuses_purchase_completion
    """
    ctx = setup_option_elected(escrow_weeks_required=2, funded_weeks=1)

    response = api_client.complete_purchase_option(ctx.option["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_ESCROW_INCOMPLETE, 422)
    assert get_vehicle(ctx.vehicle["id"])["vehicle_status"] == "ASSIGNED"


def test_the_incomplete_option_stays_funded_and_the_unit_stays_on_the_road(api):
    """PRD §3.9: "On success option_status reaches COMPLETED, vehicle_status is
    moved from ASSIGNED to RETIRED and the unit leaves the rental fleet
    permanently"

    Design: Corner/errors/escrow_incomplete_refuses_purchase_completion
    """
    ctx = setup_option_elected(escrow_weeks_required=2, funded_weeks=1)

    api_client.complete_purchase_option(ctx.option["id"], ADMIN)
    option = api_client.get_purchase_option(ctx.option["id"], COMPLIANCE).json()["data"]
    assert option["option_status"] == "ESCROW_FUNDED"
    assert option["escrow_weeks_funded"] == 1
    assert get_vehicle(ctx.vehicle["id"])["vehicle_status"] == "ASSIGNED"


# ─── Helpers ──────────────────────────────────────────

def setup_driver_with_active_agreement():
    driver = register_driver()
    enrollment = enroll_and_verify(driver["id"])
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
    api_client.activate_agreement(agreement["id"], FLEET)
    return {"driver": driver, "enrollment": enrollment, "vehicle": vehicle,
            "agreement": agreement}

def test_the_boundary_is_inclusive_on_the_amount_due(api):
    """PRD §3.6: "When enough has been tendered to cover the outstanding amount,
    payment_status becomes SETTLED and, if week_status was still DUE, GRACE or
    DELINQUENT, it also becomes PAID."
    PRD §3.6: "a first attempt that does not cover the bill is refused outright"

    Design: Corner/validations/partial_tender_at_exactly_amount_due_is_accepted
    """
    ctx = setup_agreement_with_due_week(unlimited=True)
    due = ctx.week["amount_due_cents"]

    settled = get_success_data(api_client.tender_payment(
        ctx.week["id"], {"amount_cents": due, "payment_outcome": "SUCCEEDED"}, SUPPORT
    ), expected_status=201)

    assert settled["payment_status"] == "SETTLED"
    assert settled["week_status"] == "PAID"
