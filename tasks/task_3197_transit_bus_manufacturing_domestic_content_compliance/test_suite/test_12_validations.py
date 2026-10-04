"""Corner tests: validation claims (auth, suspended agency, inspection
defects, duplicate stock pair, fiscal sanity, training cancel deadline)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    build_bus_to_plant_inspection,
    create_agency,
    create_agency_payload,
    create_component,
    create_contract_payload,
    create_parts_stock_payload,
    create_training_session_payload,
    get_success_data,
    make_agency_admin_headers,
    setup_active_contract,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PO = TEST_USERS["procurement_officer_headers"]
WA = TEST_USERS["warranty_admin_headers"]
INSP = TEST_USERS["agency_inspector_headers"]


def test_missing_auth_headers_rejected(api):
    """PRD section 2.1: "A request missing either header, or carrying a role
    that is not one of the declared roles, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unauthenticated_request_rejected
    """
    resp = api.create_agency(
        {"name": "NoAuth Transit", "agency_code": "NAU1",
         "transition_target_year": 2035},
        headers={},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_contract_create_for_suspended_agency_rejected(api):
    """PRD section 3.1: "A suspended agency cannot have new contracts created
    for it: contract creation against a `SUSPENDED` agency is rejected with
    `ERR_AGENCY_SUSPENDED`."

    Design: Corner/validations/contract_create_for_suspended_agency_rejected
    """
    agency = create_agency()
    resp = api.update_agency(
        agency["id"], {"status": "SUSPENDED"},
        make_agency_admin_headers(agency["id"]),
    )
    validate_success(resp)
    resp = api.create_contract(create_contract_payload(agency["id"]), PO)
    validate_error(resp, ApiErrorId.ERR_AGENCY_SUSPENDED)


def test_fail_inspection_without_defects_rejected(api):
    """PRD section 3.8: "A `FAIL` inspection must name its problems: recording
    a failure with an empty `defects` list is rejected with
    `ERR_INSPECTION_DEFECTS_REQUIRED` (HTTP 400)."

    Design: Corner/validations/inspection_fail_without_defects_rejected
    """
    setup = setup_active_contract(contract_overrides={"base_quantity": 1})
    bus = build_bus_to_plant_inspection(setup)
    resp = api.create_inspection_record(
        {"bus_unit_id": bus["id"], "inspection_type": "PLANT",
         "inspector_id": "insp-1", "result": "FAIL", "defects": []},
        INSP,
    )
    validate_error(resp, ApiErrorId.ERR_INSPECTION_DEFECTS_REQUIRED)


def test_duplicate_parts_stock_pair_rejected(api):
    """PRD section 3.9: "both the `agency_id` and the `component_id` must
    reference existing records, with unknown references rejected as
    `ERR_REFERENTIAL_INTEGRITY`, and the agency-component pair is unique, with
    a duplicate pair rejected with `ERR_DUPLICATE`."

    Design: Corner/validations/parts_stock_duplicate_pair_rejected
    """
    agency = create_agency(federally_funded=False)
    component = create_component(name="Brake Pad", category="AXLE",
                                 unit_cost_cents=12000)
    resp = api.create_parts_stock(
        create_parts_stock_payload(agency["id"], component["id"], quantity=10),
        WA,
    )
    validate_success(resp, expected_status=201)
    resp = api.create_parts_stock(
        create_parts_stock_payload(agency["id"], component["id"], quantity=5),
        WA,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE)


def test_nonpositive_base_quantity_rejected(api):
    """PRD section 3.2: "Fiscal sanity rules apply at creation:
    `base_quantity` must be at least 1 and prices must be positive, and a
    non-positive quantity or price is rejected with `ERR_FISCAL_VIOLATION`."

    Design: Corner/validations/nonpositive_fiscal_values_rejected
    """
    agency = create_agency()
    resp = api.create_contract(
        create_contract_payload(agency["id"], base_quantity=0), PO
    )
    validate_error(resp, ApiErrorId.ERR_FISCAL_VIOLATION)


def test_training_cancel_after_scheduled_date_rejected(api):
    """PRD section 3.10: "A session is born `SCHEDULED` and may then be
    completed once the current logical time has reached its `scheduled_date`,
    moving `SCHEDULED` → `COMPLETED`, or cancelled strictly before that date,
    moving `SCHEDULED` → `CANCELLED`; a cancellation attempted at or after the
    session's date is rejected with `ERR_DEADLINE_PASSED`."

    Design: Corner/validations/training_cancel_after_date_rejected
    """
    agency = create_agency()
    resp = api.create_training_session(
        create_training_session_payload(
            agency["id"], scheduled_date="2026-09-10T09:00:00Z"
        ),
        WA,
    )
    session = get_success_data(resp)
    get_success_data(
        api.set_clock({"to_iso8601": "2026-09-10T09:00:01Z"}, ADMIN),
    )
    resp = api.cancel_training_session(session["id"], WA)
    validate_error(resp, ApiErrorId.ERR_DEADLINE_PASSED)
