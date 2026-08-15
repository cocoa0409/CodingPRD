"""Employee administration: listing filters, termination rules, payroll
rollup reconciliation, OCC patch, immediate consistency, RBAC (PRD §2.7,
§3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_approved_profile,
    create_department_payload,
    create_employee,
    create_employee_payload,
    create_mapping_decision_payload,
    create_program,
    get_success_data,
    make_department_manager_headers,
    setup_framework,
    setup_published_band_pair,
    setup_published_program,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["comp_admin_headers"]
ANALYST = TEST_USERS["comp_analyst_headers"]
MANAGER = TEST_USERS["comp_manager_headers"]
HRBP = TEST_USERS["hrbp_headers"]


def test_employee_list_filtered_by_department(api, comp_analyst_headers):
    """PRD §3.6: "The employee list supports filtering by `department_id`,
    `job_profile_id`, `geo_zone_id`, and `status`."

    Design: Corner/cross_cutting_layers/employee_list_filtered_by_department
    """
    fw = setup_framework(levels=(("P1", "Engineer I", 1),))
    prof = create_approved_profile(fw["family"]["id"], fw["levels"][0]["id"])
    dept_a = get_success_data(api_client.create_department(
        create_department_payload(name="Dept A", code="DA"), ADMIN))
    dept_b = get_success_data(api_client.create_department(
        create_department_payload(name="Dept B", code="DB"), ADMIN))
    e1 = get_success_data(api_client.create_employee(
        create_employee_payload(dept_a["id"], prof["id"], fw["zone"]["id"],
                                employee_ref="E1", base_salary_cents=10_000_000),
        HRBP))
    get_success_data(api_client.create_employee(
        create_employee_payload(dept_b["id"], prof["id"], fw["zone"]["id"],
                                employee_ref="E2", base_salary_cents=11_000_000,
                                hire_date="2021-03-01"),
        HRBP))
    data, meta = validate_paginated(
        api.list_employees(comp_analyst_headers, params={"department_id": dept_a["id"]}))
    assert [row["id"] for row in data] == [e1["id"]]
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    _data2, meta2 = validate_paginated(api.list_employees(comp_analyst_headers))
    assert meta2["total_count"] == 2


def test_terminate_reconciles_payroll_rollup(api):
    """PRD §3.6: "Termination recomputes the department payroll projection
    excluding the employee and refreshes the program total, and because
    `TERMINATED` is terminal, any further action on the employee is rejected
    with `ERR_ALREADY_TERMINAL`."
    PRD §2.10: "Each department also carries a computed
    `projected_payroll_cents`, the sum of `base_salary_cents` over its `ACTIVE`
    employees, and the program mirrors this at the top with
    `total_payroll_projection_cents`, the sum of every department's projection,
    recomputed on every employee salary or status change."

    Design: Corner/cross_cutting_layers/terminate_reconciles_payroll_rollup
    """
    fw = setup_framework(levels=(("P1", "Engineer I", 1),))
    prof = create_approved_profile(fw["family"]["id"], fw["levels"][0]["id"])
    prog = create_program()
    dept = get_success_data(api_client.create_department(
        create_department_payload(name="Dept A", code="DA"), ADMIN))
    emp = get_success_data(api_client.create_employee(
        create_employee_payload(dept["id"], prof["id"], fw["zone"]["id"],
                                employee_ref="E1", base_salary_cents=10_000_000),
        HRBP))
    assert validate_success(api.get_department(dept["id"], ADMIN), 200)["projected_payroll_cents"] == 10_000_000
    assert validate_success(api.get_program(prog["id"], ADMIN), 200)["total_payroll_projection_cents"] == 10_000_000
    term = validate_success(api.terminate_employee(emp["id"], HRBP), 200)
    assert term["status"] == "TERMINATED"
    assert validate_success(api.get_department(dept["id"], ADMIN), 200)["projected_payroll_cents"] == 0
    assert validate_success(api.get_program(prog["id"], ADMIN), 200)["total_payroll_projection_cents"] == 0


def test_terminate_blocked_by_inflight_mapping(api):
    """PRD §3.6: "An `HRBP` may terminate an `ACTIVE` employee, moving them to
    `TERMINATED`, but only while no mapping decision for that employee is in
    flight — that is, none sits in `DRAFT`, `SUBMITTED`, `HRBP_REVIEWED`,
    `COMP_TRIAGED`, or `RETURNED` — with a blocked termination rejected as
    `ERR_REFERENCED_ENTITY_STATE`."

    Design: Corner/validations/terminate_blocked_by_inflight_mapping
    """
    from test_helpers import create_submitted_mapping
    ctx = setup_published_band_pair()
    emp = create_employee(ctx, profile_rank=1, base_salary_cents=10_000_000,
                          employee_ref="E1")
    md = get_success_data(api_client.create_mapping_decision(
        create_mapping_decision_payload(emp["id"], ctx["profiles"][2]["id"]),
        make_department_manager_headers(ctx["department"]["id"])))
    get_success_data(api_client.submit_mapping_decision(
        md["id"], make_department_manager_headers(ctx["department"]["id"])))
    res = api.terminate_employee(emp["id"], HRBP)
    validate_error(res, ApiErrorId.ERR_REFERENCED_ENTITY_STATE, expected_status=422)
    get_success_data(api_client.withdraw_mapping_decision(
        md["id"], make_department_manager_headers(ctx["department"]["id"])))
    term = validate_success(api.terminate_employee(emp["id"], HRBP), 200)
    assert term["status"] == "TERMINATED"


def test_occ_employee_patch_stale_version(api, comp_admin_headers):
    """PRD §2.7: "Administratively patching an employee likewise requires
    `expected_employee_version`, preventing a data fix from silently
    overwriting a mapping or exception side effect, with mismatches refused as
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_employee_patch_stale_version
    """
    fw = setup_framework(levels=(("P1", "Engineer I", 1),))
    prof = create_approved_profile(fw["family"]["id"], fw["levels"][0]["id"])
    dept = get_success_data(api_client.create_department(
        create_department_payload(name="Dept A", code="DA"), ADMIN))
    emp = get_success_data(api_client.create_employee(
        create_employee_payload(dept["id"], prof["id"], fw["zone"]["id"],
                                employee_ref="E1", base_salary_cents=10_000_000),
        HRBP))
    stale = emp["version"] - 1
    res = api.patch_employee(emp["id"], {"expected_employee_version": stale,
                                         "base_salary_cents": 10_100_000},
                             comp_admin_headers)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    patched = validate_success(api.patch_employee(
        emp["id"], {"expected_employee_version": emp["version"],
                    "base_salary_cents": 10_100_000},
        comp_admin_headers), 200)
    assert patched["base_salary_cents"] == 10_100_000
    assert patched["version"] == emp["version"] + 1


def test_create_response_immediately_consistent(api):
    """PRD §3.6: "A new employee opens `ACTIVE`, and creation immediately
    recomputes the department's `projected_payroll_cents` and the program's
    `total_payroll_projection_cents` to include the new salary."
    PRD §2.10: "Every recomputation in these cascades is immediate — there is
    no deferred settlement."

    Design: Corner/consistency_model/create_response_immediately_consistent
    """
    from test_helpers import create_accepted_survey_with_cut, create_price_approve_publish_band, setup_pricing_program
    ctx = setup_pricing_program(approve_profiles=(1,))
    create_accepted_survey_with_cut(ctx["profiles"][2]["id"], ctx["zone"]["id"],
                                    13_000_000)
    create_price_approve_publish_band(
        ctx["program"]["id"], ctx["family"]["id"], ctx["levels"][1]["id"],
        ctx["zone"]["id"])
    dept = get_success_data(api_client.create_department(
        create_department_payload(name="Dept A", code="DA"), ADMIN))
    emp = validate_success(api_client.create_employee(
        create_employee_payload(dept["id"], ctx["profiles"][2]["id"],
                                ctx["zone"]["id"], base_salary_cents=14_000_000,
                                hire_date="2019-05-01", employee_ref="E1"),
        HRBP), 201)
    assert emp["compa_ratio"] == pytest.approx(1.0769, abs=1e-9)
    assert emp["range_position"] == "IN_RANGE"
    assert validate_success(api.get_department(dept["id"], ADMIN), 200)["projected_payroll_cents"] == 14_000_000


def test_department_manager_cannot_create_employee(api):
    """PRD §2.1: "Every endpoint declares the roles permitted to call it; an
    authenticated caller whose role is not listed for the endpoint is rejected
    with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: POST /comp/employees lists only HRBP.

    Design: Corner/rbac/department_manager_cannot_create_employee
    """
    fw = setup_framework(levels=(("P1", "Engineer I", 1),))
    prof = create_approved_profile(fw["family"]["id"], fw["levels"][0]["id"])
    dept = get_success_data(api_client.create_department(
        create_department_payload(name="Dept A", code="DA"), ADMIN))
    res = api.create_employee(
        create_employee_payload(dept["id"], prof["id"], fw["zone"]["id"],
                                employee_ref="E1"),
        make_department_manager_headers(dept["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
    _data, meta = validate_paginated(api.list_employees(HRBP))
    assert meta["total_count"] == 0
