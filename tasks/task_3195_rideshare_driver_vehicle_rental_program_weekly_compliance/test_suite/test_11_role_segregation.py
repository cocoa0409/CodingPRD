"""Role segregation: operations reserved to one capacity, ownership gatekeeping,
and the authentication layer that runs before authorization.
"""
from test_helpers import (
    ADMIN,
    COMPLIANCE,
    FLEET,
    SUPPORT,
    agreement_version,
    api_client,
    create_agreement_payload,
    create_enrollment_payload,
    create_purchase_option_payload,
    create_unlimited_agreement_payload,
    enroll_and_verify,
    get_success_data,
    get_week,
    make_driver_headers,
    make_unknown_role_headers,
    register_driver,
    set_clock,
    setup_active_agreement,
    setup_agreement_with_due_week,
    validate_error,
)
from test_helpers.api_errors import ApiErrorId


def test_a_driver_may_not_activate_an_agreement(api):
    """PRD §3.3: "Moving an agreement from DRAFT to ACTIVE is what actually puts a
    unit on the road, and it is reserved to a FleetOpsAgent."
    PRD §2.1: "A request that is properly authenticated but attempts an operation
    the caller's role does not hold is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/validations/plain_driver_cannot_activate_agreement
    """
    ctx = setup_draft_agreement_for_driver()

    response = api_client.activate_agreement(
        ctx["agreement"]["id"], make_driver_headers(ctx["driver"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, 403)
    assert api_client.get_agreement(ctx["agreement"]["id"], FLEET).json()[
        "data"
    ]["agreement_status"] == "DRAFT"


def test_ownership_does_not_buy_the_driver_dispatch_authority(api):
    """PRD §2.1: "The four operations that are ownership-checked - withdrawal from
    the programme by the driver, and the three driver-facing purchase-option
    actions of electing, funding escrow and withdrawing an option - admit the
    owning driver, and are otherwise rejected with ERR_UNAUTHORIZED (HTTP 403).
    Every other operation is gated purely by role membership."

    Design: Corner/validations/plain_driver_cannot_activate_agreement
    """
    ctx = setup_draft_agreement_for_driver()
    assert ctx["agreement"]["driver_id"] == ctx["driver"]["id"]

    response = api_client.activate_agreement(
        ctx["agreement"]["id"], make_driver_headers(ctx["driver"]["id"])
    )
    assert response.status_code == 403
    assert response.json()["data"]["error_id"] == "ERR_UNAUTHORIZED"


def test_fleet_ops_may_not_decide_an_enrolment_outcome(api):
    """PRD §2.1: "FleetOpsAgent owns the fleet surface - admitting units,
    assigning and swapping them, reporting service events and executing recovery
    - but cannot decide who is admitted to the programme"

    Design: Corner/validations/fleet_ops_cannot_decide_enrollment
    """
    driver = register_driver()
    enrollment = get_success_data(api_client.enroll_driver(
        create_enrollment_payload(driver["id"]), COMPLIANCE
    ), expected_status=201)

    response = api_client.verify_enrollment(enrollment["id"], FLEET)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, 403)
    assert api_client.get_enrollment(enrollment["id"], COMPLIANCE).json()[
        "data"
    ]["enrollment_status"] == "PENDING_VERIFICATION"


def test_the_same_verification_succeeds_for_the_compliance_officer(api):
    """PRD §3.1: "Enrolment is the work of a ComplianceOfficer"
    PRD §2.1: "ComplianceOfficer decides enrolment outcomes and declares
    delinquency but holds no fleet dispatch authority"

    Design: Corner/validations/fleet_ops_cannot_decide_enrollment
    """
    driver = register_driver()
    enrollment = get_success_data(api_client.enroll_driver(
        create_enrollment_payload(driver["id"]), COMPLIANCE
    ), expected_status=201)

    verified = get_success_data(api_client.verify_enrollment(enrollment["id"], COMPLIANCE))
    assert verified["enrollment_status"] == "ACTIVE"


def test_a_driver_may_not_submit_a_unit_to_the_platform(api):
    """PRD §3.3: "Before a unit can carry platform work, it is submitted for a
    qualification check by a ComplianceOfficer, naming the agreement it serves as
    agreement_id and the unit itself as vehicle_id."
    PRD §2.1: "A request that is properly authenticated but attempts an operation
    the caller's role does not hold is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/validations/driver_cannot_submit_platform_check
    """
    ctx = setup_active_agreement(unlimited=True)

    response = api_client.submit_platform_check(
        {"agreement_id": ctx.agreement["id"], "vehicle_id": ctx.vehicle["id"]},
        ctx.driver_headers,
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, 403)
    assert api_client.list_platform_checks(FLEET).json()["meta"]["total_count"] == 0


def test_owning_the_unit_does_not_confer_the_qualification_authority(api):
    """PRD §3.3: "Before a unit can carry platform work, it is submitted for a
    qualification check by a ComplianceOfficer, naming the agreement it serves as
    agreement_id and the unit itself as vehicle_id."

    Design: Corner/validations/driver_cannot_submit_platform_check
    """
    from test_helpers import create_platform_check_payload

    ctx = setup_active_agreement(unlimited=True)
    response = api_client.submit_platform_check(
        create_platform_check_payload(ctx.agreement["id"], ctx.vehicle["id"]),
        ctx.driver_headers,
    )
    assert response.status_code == 403
    assert api_client.list_platform_checks(FLEET).json()["meta"]["total_count"] == 0


def test_an_unknown_capacity_is_rejected_at_authentication(api):
    """PRD §2.1: "A request whose X-User-Role header is absent or carries a value
    outside the five recognised roles is rejected with ERR_UNAUTHENTICATED (HTTP
    401)"
    PRD §2.7: "Role header. X-User-Role must be present and must name one of the
    five recognised roles. Failure is ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/validations/unknown_role_header_is_unauthenticated
    """
    response = api_client.list_vehicles(make_unknown_role_headers())
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)
    assert response.json()["data"]["error_id"] != "ERR_UNAUTHORIZED"


def test_the_five_recognised_roles_are_the_only_accepted_capacities(api):
    """PRD §2.1: "The five roles are Driver, FleetOpsAgent, ComplianceOfficer,
    PlatformAdmin and SupportAgent."

    Design: Corner/validations/unknown_role_header_is_unauthenticated
    """
    assert api_client.list_vehicles(make_unknown_role_headers(role="Auditor")).status_code == 401
    assert api_client.list_vehicles(make_unknown_role_headers(role="Admin")).status_code == 401
    assert api_client.list_vehicles(FLEET).status_code == 200


def test_a_support_agent_may_not_waive_a_charge(api):
    """PRD §3.6: "Finally, a PlatformAdmin may waive a week's amount due outright.
    Waiver is available while the week stands in DUE, GRACE or DELINQUENT"
    PRD §2.1: "PlatformAdmin configures the programme, prices buyouts, waives
    charges and controls the logical clock"

    Design: Corner/rbac/support_agent_cannot_waive_charges
    """
    ctx = setup_agreement_with_due_week(unlimited=True)

    response = api_client.waive_week(ctx.week["id"], SUPPORT)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, 403)
    assert get_week(ctx.week["id"])["week_status"] == "DUE"


def test_the_administrator_may_waive_the_same_charge(api):
    """PRD §3.6: "A waived week moves to WAIVED, which is terminal, and the
    agreement's cumulative waived total rises by that week's amount owed."

    Design: Corner/rbac/support_agent_cannot_waive_charges
    """
    ctx = setup_agreement_with_due_week(unlimited=True)

    waived = get_success_data(api_client.waive_week(ctx.week["id"], ADMIN))
    assert waived["week_status"] == "WAIVED"


def test_a_compliance_officer_may_not_admit_a_fleet_unit(api):
    """PRD §3.3: "The fleet side of the programme begins with admitting a unit. A
    FleetOpsAgent registers a programme vehicle with its identification number as
    vin, its model designation as model_name, its model year as model_year, its
    programme class as vehicle_class, its current odometer reading as
    odometer_miles, and the region it is allocated to as region_code."
    PRD §2.1: "FleetOpsAgent owns the fleet surface - admitting units, assigning
    and swapping them, reporting service events and executing recovery"

    Design: Corner/rbac/compliance_officer_cannot_admit_fleet_units
    """
    response = api_client.admit_vehicle(
        {
            "vin": "1HGCM82633A004352", "model_name": "Civic", "model_year": 2022,
            "vehicle_class": "STANDARD", "odometer_miles": 40_000, "region_code": "CA",
        },
        COMPLIANCE,
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, 403)
    assert api_client.list_vehicles(FLEET).json()["meta"]["total_count"] == 0


def test_no_vehicle_row_survives_a_refused_admission(api):
    """PRD §2.1: "ComplianceOfficer decides enrolment outcomes and declares
    delinquency but holds no fleet dispatch authority"

    Design: Corner/rbac/compliance_officer_cannot_admit_fleet_units
    """
    response = api_client.admit_vehicle(
        {
            "vin": "1HGCM82633A004353", "model_name": "Civic", "model_year": 2022,
            "vehicle_class": "STANDARD", "odometer_miles": 41_000, "region_code": "CA",
        },
        COMPLIANCE,
    )
    assert response.status_code == 403
    assert api_client.list_vehicles(FLEET).json()["meta"]["total_count"] == 0


def test_a_driver_may_not_fund_another_drivers_escrow(api):
    """PRD §2.1: "When X-User-Role is Driver, X-User-ID is the id of the acting
    Driver; ownership checks on any resource that references a Driver compare the
    resource's foreign-key field to X-User-ID."
    PRD §3.9: "Election, funding and withdrawal are three of the four
    ownership-checked operations, so a driver may act only on their own option and
    an attempt on someone else's is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/driver_cannot_fund_another_drivers_escrow
    """
    owner = register_driver()
    other = register_driver()
    owner_enrollment = enroll_and_verify(owner["id"])
    vehicle = get_success_data(api_client.admit_vehicle(
        {
            "vin": "1HGCM82633A004352", "model_name": "Civic", "model_year": 2022,
            "vehicle_class": "STANDARD", "odometer_miles": 40_000, "region_code": "CA",
        },
        FLEET,
    ), expected_status=201)
    agreement = get_success_data(api_client.create_agreement(
        create_unlimited_agreement_payload(owner_enrollment["id"], owner["id"], vehicle["id"]),
        FLEET,
    ), expected_status=201)
    api_client.activate_agreement(agreement["id"], FLEET)
    option = get_success_data(api_client.offer_purchase_option(
        create_purchase_option_payload(
            agreement["id"], owner["id"],
            purchase_price_cents=1_200_000, escrow_weeks_required=1,
        ),
        ADMIN,
    ), expected_status=201)
    api_client.elect_purchase_option(
        option["id"],
        {"expected_agreement_version": agreement_version(agreement["id"])},
        make_driver_headers(owner["id"]),
    )

    response = api_client.fund_escrow(option["id"], make_driver_headers(other["id"]))
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, 403)
    assert api_client.get_purchase_option(option["id"], COMPLIANCE).json()["data"][
        "escrow_weeks_funded"
    ] == 0


def test_the_owning_driver_funds_the_same_option(api):
    """PRD §3.9: "The driver funds the option one weekly period at a time. Each
    funding step requires option_status to be ELECTED or ESCROW_FUNDED and
    escrow_weeks_funded to still be below escrow_weeks_required;
    escrow_weeks_funded is incremented by one and escrow_balance_cents rises by
    escrow_required_cents."

    Design: Corner/rbac/driver_cannot_fund_another_drivers_escrow
    """
    ctx = setup_option_elected_for_owner(funded_weeks=0)
    funded = get_success_data(api_client.fund_escrow(
        ctx["option"]["id"], make_driver_headers(ctx["driver"]["id"])
    ))
    assert funded["escrow_weeks_funded"] == 1
    assert funded["escrow_balance_cents"] == funded["escrow_required_cents"]


def test_a_fleet_ops_agent_may_not_move_the_logical_clock(api):
    """PRD §2.9: "Only an administrator may move the clock, by supplying a
    destination instant as to_iso8601; the call returns the new clock value as
    current_utc."
    PRD §2.1: "PlatformAdmin configures the programme, prices buyouts, waives
    charges and controls the logical clock"

    Design: Corner/rbac/fleet_ops_cannot_control_logical_clock
    """
    ctx = setup_agreement_with_due_week(unlimited=True)

    response = api_client.set_clock("2026-09-20T00:00:00Z", FLEET)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, 403)
    assert get_week(ctx.week["id"])["week_status"] == "DUE", (
        "no time-gated transition fired"
    )


def test_advancing_the_clock_past_the_deadline_lapses_the_week_into_grace(api):
    """PRD §2.9: "Advancing the clock past a week's payment_deadline therefore
    moves that week into grace without any further request from a caller, and any
    other deadline that falls between the old and new instants is crossed in the
    same way."

    Design: Corner/rbac/fleet_ops_cannot_control_logical_clock
    """
    ctx = setup_agreement_with_due_week(unlimited=True)
    set_clock("2026-09-08T00:00:00Z")
    assert get_week(ctx.week["id"])["week_status"] == "GRACE"


# ─── Helpers ──────────────────────────────────────────

def setup_draft_agreement_for_driver():
    """A DRAFT agreement belonging to an eligible driver on an AVAILABLE unit."""
    driver = register_driver()
    enrollment = enroll_and_verify(driver["id"])
    vehicle = get_success_data(api_client.admit_vehicle(
        {
            "vin": "1HGCM82633A004371", "model_name": "Civic", "model_year": 2022,
            "vehicle_class": "STANDARD", "odometer_miles": 40_000, "region_code": "CA",
        },
        FLEET,
    ), expected_status=201)
    agreement = get_success_data(api_client.create_agreement(
        create_agreement_payload(enrollment["id"], driver["id"], vehicle["id"]),
        FLEET,
    ), expected_status=201)
    return {"driver": driver, "enrollment": enrollment, "vehicle": vehicle,
            "agreement": agreement}


def setup_option_elected_for_owner(funded_weeks=0):
    """An ELECTED purchase option on an agreement owned by a specific driver."""
    driver = register_driver()
    enrollment = enroll_and_verify(driver["id"])
    vehicle = get_success_data(api_client.admit_vehicle(
        {
            "vin": "1HGCM82633A004372", "model_name": "Civic", "model_year": 2022,
            "vehicle_class": "STANDARD", "odometer_miles": 40_000, "region_code": "CA",
        },
        FLEET,
    ), expected_status=201)
    agreement = get_success_data(api_client.create_agreement(
        create_unlimited_agreement_payload(enrollment["id"], driver["id"], vehicle["id"]),
        FLEET,
    ), expected_status=201)
    api_client.activate_agreement(agreement["id"], FLEET)
    option = get_success_data(api_client.offer_purchase_option(
        create_purchase_option_payload(
            agreement["id"], driver["id"],
            purchase_price_cents=1_200_000, escrow_weeks_required=2,
        ),
        ADMIN,
    ), expected_status=201)
    option = get_success_data(api_client.elect_purchase_option(
        option["id"],
        {"expected_agreement_version": agreement_version(agreement["id"])},
        make_driver_headers(driver["id"]),
    ))
    for _ in range(funded_weeks):
        option = get_success_data(api_client.fund_escrow(
            option["id"], make_driver_headers(driver["id"])
        ))
    return {"driver": driver, "enrollment": enrollment, "vehicle": vehicle,
            "agreement": agreement, "option": option}