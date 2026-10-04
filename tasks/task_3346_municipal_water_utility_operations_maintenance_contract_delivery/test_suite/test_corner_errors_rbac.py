"""Corner-queue tests for triggerable errors and the role separation rules."""
from test_helpers import (
    NON_EXISTENT_ASSET_ID,
    api_client,
    award_contract,
    create_standard,
    employee_payload,
    freeze_baseline,
    get_success_data,
    permit_payload,
    raise_and_schedule_work_order,
    read_contract,
    register_asset,
    register_municipality,
    setup_operating_contract,
    staffing_commitment_payload,
    submit_baseline_assessment,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import make_employee_headers

# A well-formed identifier that no contract can carry.
UNKNOWN_CONTRACT_ID = "1c9d2ab4-6f30-4d17-8b2a-9e4c7d0f3a55"


def test_ingesting_a_work_order_under_an_unknown_contract_reports_not_found(api):
    """PRD §3.10: "Any request whose path or payload names a municipality, contract, permit, standard, measurement, asset, assessment, employee, staffing commitment, work order, schedule, emergency event, penalty allocation, renewal proposal or transition obligation that does not exist is rejected with the matching not-found error from §2.6."
    PRD §2.6: "the parent named by the first segment must exist before the child named by the last segment is considered. A failure at any segment produces the not-found error for that segment's entity, and no later segment is evaluated."

    Design: Corner/errors/contract_not_found_error_on_work_order_ingest
    """
    # The OperatorAdmin actor must be bound to a real contract.
    municipality, municipality_headers = register_municipality()
    _, contract_headers = award_contract(municipality, municipality_headers)

    response = api_client.ingest_work_order(
        UNKNOWN_CONTRACT_ID,
        {
            "asset_id": NON_EXISTENT_ASSET_ID,
            "work_type": "CORRECTIVE",
            "estimated_cost_cents": 100000,
            "reported_at": "2026-09-01T00:00:00Z",
        },
        contract_headers,
    )
    validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_FOUND)


def test_permit_with_an_expiration_before_its_effective_date_is_rejected(api):
    """PRD §3.1: "This same ordering rule governs measurement periods, whose `period_end` must be strictly after `period_start`, and permits, whose `expiration_date` must be strictly after `effective_date`."
    PRD §3.5: "Inverted or equal effective and expiration dates are rejected with `ERR_INVALID_DATE_WINDOW` (HTTP 400)."

    Design: Corner/errors/invalid_date_window_on_permit_creation
    """
    municipality, municipality_headers = register_municipality()
    contract, contract_headers = award_contract(municipality, municipality_headers)

    response = api_client.create_permit(
        contract["id"],
        permit_payload(
            permit_number="OH-2027-301",
            effective_date="2027-04-30T00:00:00Z",
            expiration_date="2026-05-01T00:00:00Z",
        ),
        contract_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_DATE_WINDOW)

    permits = get_success_data(
        api_client.list_contract_permits(contract["id"], contract_headers)
    )
    assert permits == [], "a rejected permit must not create a row"


def test_operator_admin_cannot_freeze_the_baseline(api):
    """PRD §2.9: "`MunicipalityAdmin` alone may award a contract, freeze the baseline, begin the transition back, complete the transition back, terminate a contract, and record a penalty allocation under a permit."
    PRD §2.1: "When the role is authenticated but is not permitted for the requested operation, the request is rejected with `ERR_ROLE_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/operator_admin_cannot_freeze_the_baseline
    """
    municipality, municipality_headers = register_municipality()
    contract, contract_headers = award_contract(municipality, municipality_headers)
    create_standard(contract["id"], contract_headers, activate=True)
    asset = register_asset(
        contract["id"],
        municipality_headers,
        asset_tag="PMP-108",
        asset_class="PUMP",
        install_year=2020,
        useful_life_years=15,
        criticality_rank=1,
    )
    submit_baseline_assessment(
        asset["id"], contract_headers, municipality_headers=municipality_headers
    )

    response = api_client.freeze_baseline(contract["id"], contract_headers)
    validate_error(response, ApiErrorId.ERR_ROLE_FORBIDDEN)

    after = read_contract(contract["id"], contract_headers)
    assert after["baseline_frozen"] is False, (
        "a role-forbidden freeze leaves the baseline unfrozen"
    )


def test_employee_self_service_call_must_carry_the_employees_own_identity(api):
    """PRD §2.1: "Employee self-service calls that carry an `X-User-ID` other than the employee's own `id` are rejected with `ERR_SELF_SERVICE_OWNER_MISMATCH` (HTTP 403)."
    PRD §2.1: "When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting `Employee`."

    Design: Corner/rbac/employee_self_service_requires_own_identity
    """
    municipality, municipality_headers = register_municipality()
    contract, contract_headers = award_contract(municipality, municipality_headers)
    create_standard(contract["id"], contract_headers, activate=True)
    get_success_data(
        api_client.create_staffing_commitment(
            contract["id"], staffing_commitment_payload(committed_fte=4.0), contract_headers
        )
    )
    get_success_data(api_client.mobilize_contract(contract["id"], contract_headers))

    first = get_success_data(
        api_client.register_employee(
            contract["id"],
            employee_payload(full_name="Dana Whitfield", municipal_hire_date="2016-05-01T00:00:00Z"),
            contract_headers,
        )
    )
    second = get_success_data(
        api_client.register_employee(
            contract["id"],
            employee_payload(full_name="Marcus Ndiaye", municipal_hire_date="2019-05-01T00:00:00Z"),
            contract_headers,
        )
    )
    for employee in (first, second):
        get_success_data(
            api_client.offer_transfer(contract["id"], employee["id"], contract_headers)
        )

    # The Employee role acts for the first employee but names the second employee's
    # record in the path.
    response = api_client.accept_transfer_offer(
        second["id"], make_employee_headers(first["id"])
    )
    validate_error(response, ApiErrorId.ERR_SELF_SERVICE_OWNER_MISMATCH)

    untouched = get_success_data(api_client.get_employee(second["id"], contract_headers))
    assert untouched["status"] == "OFFERED", (
        "the mismatched self-service call does not move the offer"
    )


def test_municipality_admin_cannot_complete_the_operators_work_order(api):
    """PRD §2.9: "`OperatorAdmin` alone may mobilize a contract, commence operations, schedule a work order, complete a work order, regenerate a preventive maintenance schedule, dispatch an emergency crew and record containment."
    PRD §2.1: "When the role is authenticated but is not permitted for the requested operation, the request is rejected with `ERR_ROLE_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/municipality_admin_cannot_execute_the_operators_maintenance_steps
    """
    scenario = setup_operating_contract()
    order = raise_and_schedule_work_order(
        scenario.asset["id"],
        scenario.con_h,
        work_type="CORRECTIVE",
        estimated_cost_cents=400000,
    )
    started = validate_success(api_client.start_work_order(order["id"], scenario.con_h))
    assert started["status"] == "IN_PROGRESS"

    response = api_client.complete_work_order(
        order["id"],
        {
            "labour_hours": 3.0,
            "materials_cents": 200000,
            "closure_narrative": "Attempted completion by the municipal contract manager.",
        },
        scenario.mun_h,
    )
    validate_error(response, ApiErrorId.ERR_ROLE_FORBIDDEN)

    untouched = get_success_data(api_client.get_work_order(order["id"], scenario.con_h))
    assert untouched["status"] == "IN_PROGRESS", (
        "the role-forbidden completion does not advance the work order"
    )
