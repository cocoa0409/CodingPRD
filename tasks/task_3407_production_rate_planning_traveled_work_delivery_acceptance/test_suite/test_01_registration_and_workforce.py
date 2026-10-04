"""Registrations, program health defaults, workforce hiring (PRD §2.1, §2.9, §3.1)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    is_valid_uuid, NON_EXISTENT_UUID,
    ApiErrorId,
    make_supplier_manager_headers,
    api_client,
    create_program_payload, create_supplier_payload, create_aircraft_unit_payload,
    hire_payload,
    create_program, create_supplier, setup_aircraft,
    create_workforce_plan, hire,
    assert_program, assert_supplier,
)


def test_program_create_returns_defaults_and_computed_posture(api, admin_headers):
    """PRD §3.2: "the announced target always reflects the `proposed_rate` of the most
    recently created case currently in `ANNOUNCED` or `GATED_REVIEW` — the latest by
    `created_at` wins — and falls back to `current_rate_per_month` when no such case
    exists."
    PRD §2.9: "Multiply that count by 100 and divide by the program's
    `required_component_codes`; if `required_component_codes` is zero, supply readiness is
    defined as 100."
    PRD §2.9: "Sum `hired_headcount` over all of the program's workforce plans, multiply by
    100, and divide by the sum of `required_headcount` over the same plans; if the program
    has no workforce plans, or the summed requirement is zero, workforce readiness is
    defined as 100."
    PRD §2.9: "It is `DISTRESSED` when any of the following holds: the `readiness_index` is
    below 60.0; any `CRITICAL` quality escape on a program aircraft is in `OPEN`,
    `ROOT_CAUSE`, or `DISPOSITIONED`; the `open_escape_count` is 3 or more; or any
    commitment of the program is `AT_RISK`."

    Design: Corner/entities/program_create_returns_defaults_and_computed_posture
    """
    resp = api_client.create_program(
        create_program_payload(
            model_code="M1", current_rate_per_month=5, required_component_codes=1,
            rework_budget_total_cents=1000000,
        ),
        admin_headers,
    )
    program = validate_success(resp, 201)
    assert_program(program)
    assert is_valid_uuid(program["id"])
    assert isinstance(program["version"], int) and program["version"] >= 1
    assert program["announced_target_rate"] == 5, "no announced case: falls back to current rate"
    assert program["open_escape_count"] == 0
    assert program["traveled_work_open_hours"] == 0
    assert program["undelivered_inventory_count"] == 0
    assert program["rework_budget_consumed_cents"] == 0
    assert program["cancellation_reserve_cents"] == 0
    assert program["storage_fees_accrued_cents"] == 0
    assert program["supply_chain_readiness_pct"] == 0.0, "0 of 1 component codes covered"
    assert program["workforce_readiness_pct"] == 100.0, "no workforce plans: defined as 100"
    assert program["readiness_index"] == 0.0
    assert program["posture"] == "DISTRESSED", "index 0.0 is below 60.0"


def test_program_missing_required_field_returns_invalid_request(api, admin_headers):
    """PRD §3.1: "Registering a production program takes a unique `model_code`, the
    currently committed build rate `current_rate_per_month` (at least one aircraft per
    month), `required_component_codes` — the count of distinct long-lead component families
    that supplier commitments must cover before a rate increase can pass gating, at least
    one — and `rework_budget_total_cents`, the program's lifetime rework budget in integer
    cents (zero or more)."
    PRD §2.8: "field presence, types, enum membership, and integer lower bounds are
    validated only after every rule above has passed: `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/program_missing_required_field_returns_invalid_request
    """
    payload = {
        "model_code": "M1",
        "current_rate_per_month": 5,
        "required_component_codes": 1,
    }
    resp = api_client.create_program(payload, admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_program_get_unknown_id_returns_not_found(api, admin_headers):
    """PRD §2.8: "The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the *first*
    path identifier that does not resolve to an existing resource; later identifiers are
    never examined."

    Design: Corner/entities/program_get_unknown_id_returns_not_found
    """
    resp = api_client.get_program(NON_EXISTENT_UUID, admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_duplicate_supplier_code_rejected(api, admin_headers):
    """PRD §3.1: "Suppliers register with a unique `supplier_code` plus a legal `name` and
    home `region`; customer airlines register with a unique `airline_code`, a `name`, and a
    `credit_standing` of `GOOD`, `WATCH`, or `POOR` — the same uniqueness error guards both
    codes."
    PRD §3.1: "A second program registered under the same `model_code` is rejected with
    `ERR_DUPLICATE_CODE` (HTTP 409)."

    Design: Corner/entities/duplicate_supplier_code_rejected
    """
    create_supplier(supplier_code="S1", name="Engines Co", region="NA")
    resp = api_client.create_supplier(
        create_supplier_payload(supplier_code="S1", name="Other Co", region="EU"),
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CODE)


def test_aircraft_duplicate_line_number_in_same_program_rejected(api, planner_headers):
    """PRD §3.1: "Aircraft join the line through the `ProductionPlanner` as well, each
    carrying its `customer_id`, a `line_number` unique within its program (same uniqueness
    error), the as-built `configuration_code`, the contracted `ordered_configuration_code` —
    delivery acceptance later demands equality of the two — a `contract_price_cents` of at
    least one cent that anchors the liquidated-damages cap, and a `contracted_delivery_date`
    that anchors the days-late arithmetic of §3.9."
    PRD §3.1: "A second program registered under the same `model_code` is rejected with
    `ERR_DUPLICATE_CODE` (HTTP 409)."

    Design: Corner/entities/aircraft_duplicate_line_number_in_same_program_rejected
    """
    program, customer, _aircraft = setup_aircraft(line_number=1001)
    resp = api_client.create_aircraft_unit(
        program["id"],
        create_aircraft_unit_payload(customer["id"], line_number=1001),
        planner_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CODE)


def test_workforce_readiness_ratio_computed_from_hires(api, planner_headers):
    """PRD §3.1: "Each plan names a `skill_code` (unique within its program, under the same
    `ERR_DUPLICATE_CODE` discipline) and a `required_headcount` of at least one;
    `hired_headcount` starts at zero, and the plan's `readiness_ratio` — hired divided by
    required, carried to two decimal places — feeds program readiness."

    Design: Corner/entities/workforce_readiness_ratio_computed_from_hires
    """
    program = create_program()
    plan = create_workforce_plan(program["id"], skill_code="AVIONICS", required_headcount=12)
    assert plan["hired_headcount"] == 0
    plan = hire(plan["id"], 3)
    assert plan["hired_headcount"] == 3
    assert plan["readiness_ratio"] == 0.25, "3 / 12 carried to two decimal places"


def test_write_immediately_visible_in_same_read(api, admin_headers):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will
    return the created or updated resource object in the data field."
    PRD §4: the supplier read endpoint is documented as "Read a supplier", so the record
    returned by the create is exactly what the very next read serves.

    Design: Corner/consistency_model/write_immediately_visible_in_same_read
    """
    created = validate_success(
        api_client.create_supplier(
            create_supplier_payload(supplier_code="S1", name="Engines Co", region="NA"),
            admin_headers,
        ),
        201,
    )
    fetched = validate_success(api_client.get_supplier(created["id"], admin_headers))
    assert_supplier(fetched)
    assert fetched["id"] == created["id"]
    assert fetched["supplier_code"] == "S1"
    assert fetched["name"] == "Engines Co"
    assert fetched["region"] == "NA"
    assert fetched["version"] == created["version"]


def test_call_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a role the system does not
    declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/call_missing_auth_headers_returns_unauthenticated
    """
    resp = api_client.create_program(create_program_payload(), None)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_supplier_manager_cannot_create_programs(api):
    """PRD §2.1: "`ProgramAdmin` is the platform operator: it registers programs, suppliers,
    and customers, and drives the test clock."
    PRD §2.1: "Attempting an operation outside one's role is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/supplier_manager_cannot_create_programs
    """
    supplier = create_supplier()
    resp = api_client.create_program(
        create_program_payload(
            model_code="M9", current_rate_per_month=2,
            required_component_codes=1, rework_budget_total_cents=1000,
        ),
        make_supplier_manager_headers(supplier["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_hire_exact_fill_allowed_then_one_more_rejected(api, planner_headers):
    """PRD §3.1: "Recording hires takes a `count` of at least one, and the cumulative
    `hired_headcount` plus the new `count` may not exceed `required_headcount`; an over-hire
    is rejected with `ERR_HIRE_EXCEEDS_REQUIRED` (HTTP 422)."
    PRD §3.1: "`hired_headcount` starts at zero, and the plan's `readiness_ratio` — hired
    divided by required, carried to two decimal places — feeds program readiness."

    Design: Difficulty/boundary_precision_check/hire_to_exactly_required_allowed_then_one_more_rejected
    """
    program = create_program()
    plan = create_workforce_plan(program["id"], skill_code="AVIONICS", required_headcount=10)
    plan = hire(plan["id"], 6)
    assert plan["hired_headcount"] == 6
    plan = hire(plan["id"], 4)
    assert plan["hired_headcount"] == 10, "6 + 4 == required: exact fill is allowed"
    assert plan["readiness_ratio"] == 1.0
    resp = api_client.hire(plan["id"], hire_payload(1), planner_headers)
    validate_error(resp, ApiErrorId.ERR_HIRE_EXCEEDS_REQUIRED)
    plans, _meta = validate_paginated(
        api_client.list_workforce_plans(program["id"], planner_headers)
    )
    assert plans[0]["hired_headcount"] == 10, "rejected hire must not move the counter"


def test_hire_single_call_exact_fill_then_one_more_rejected(api, planner_headers):
    """PRD §3.1: "Recording hires takes a `count` of at least one, and the cumulative
    `hired_headcount` plus the new `count` may not exceed `required_headcount`; an over-hire
    is rejected with `ERR_HIRE_EXCEEDS_REQUIRED` (HTTP 422)."
    PRD §3.1: "`hired_headcount` starts at zero, and the plan's `readiness_ratio` — hired
    divided by required, carried to two decimal places — feeds program readiness."

    Design: Difficulty/boundary_precision_check/hire_to_exactly_required_allowed_then_one_more_rejected
    """
    program = create_program()
    plan = create_workforce_plan(program["id"], skill_code="AVIONICS", required_headcount=10)
    plan = hire(plan["id"], 10)
    assert plan["hired_headcount"] == 10, "0 + 10 == required: equality is allowed"
    assert plan["readiness_ratio"] == 1.0
    resp = api_client.hire(plan["id"], hire_payload(1), planner_headers)
    validate_error(resp, ApiErrorId.ERR_HIRE_EXCEEDS_REQUIRED)
    plans, _meta = validate_paginated(
        api_client.list_workforce_plans(program["id"], planner_headers)
    )
    assert plans[0]["hired_headcount"] == 10, "rejected hire must not move the counter"
