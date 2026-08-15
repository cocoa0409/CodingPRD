"""Program defaults, framework primitives, geo differentials, pagination, and
request-shape violations (PRD §2.2-§2.5, §3.1, §3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_department_payload,
    create_geo_zone_payload,
    create_job_family_payload,
    create_job_level_payload,
    create_program_payload,
    get_success_data,
    setup_framework,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["comp_admin_headers"]
ANALYST = TEST_USERS["comp_analyst_headers"]


def test_program_creation_applies_defaults(api, comp_admin_headers):
    """PRD §2.4: "A new program opens in `DRAFT` status with both computed
    totals, `total_payroll_projection_cents` and `refresh_budget_spent_cents`,
    initialized to zero."
    PRD §2.4: "the cadence defaults to 12 and must be at least 1."

    Design: Corner/entities/program_creation_defaults
    """
    res = api.create_program(
        create_program_payload(
            fiscal_year=2027,
            merit_budget_cents=50_000_000,
            refresh_budget_cents=2_000_000,
            pricing_as_of_date="2026-08-01",
        ),
        comp_admin_headers,
    )
    prog = validate_success(res, 201)
    assert prog["refresh_cadence_months"] == 12
    assert prog["status"] == "DRAFT"
    assert prog["total_payroll_projection_cents"] == 0
    assert prog["refresh_budget_spent_cents"] == 0
    assert prog["version"] == 1


def test_employee_create_ignores_client_system_fields(api):
    """PRD §2.8 tier 3: "Unknown request fields are ignored entirely and are
    never an error."
    PRD §3.6: "when no such band exists, the employee's `compa_ratio` is null,
    the `range_position` is `UNBANDED`, and the `red_circled` flag is left
    unchanged."

    Design: Corner/entities/employee_create_system_fields_input_ignored
    """
    fw = setup_framework(levels=(("P1", "Engineer I", 1),))
    from test_helpers import create_approved_profile, create_employee_payload
    prof = create_approved_profile(fw["family"]["id"], fw["levels"][0]["id"])
    dept = get_success_data(api_client.create_department(
        create_department_payload(name="Dept A", code="DA"), ADMIN))
    payload = create_employee_payload(
        dept["id"], prof["id"], fw["zone"]["id"],
        employee_ref="E1", base_salary_cents=10_000_000, hire_date="2020-01-15")
    payload["id"] = "deadbeef-0000-0000-0000-000000000000"
    payload["version"] = 99
    payload["compa_ratio"] = 9.9999
    emp = validate_success(
        api_client.create_employee(payload, TEST_USERS["hrbp_headers"]), 201)
    assert emp["id"] != "deadbeef-0000-0000-0000-000000000000"
    assert emp["version"] == 1
    assert emp["compa_ratio"] is None
    assert emp["range_position"] == "UNBANDED"


def test_pay_band_get_not_found(api, comp_analyst_headers):
    """PRD §2.8 tier 4: "Path identifiers and body foreign-key references are
    resolved left to right, and the first identifier that does not resolve
    yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/pay_band_get_not_found
    """
    res = api.get_pay_band("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", comp_analyst_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_employee_create_missing_required_field(api):
    """PRD §2.8 tier 3: "Every field the endpoint requires is present, enum
    fields carry declared members only, numeric fields sit in their declared
    domains — `sample_size` at least 1, `spread_pct` and the policy percentages
    non-negative, `differential_ratio` greater than zero, all dates well-formed
    ISO values — and violations yield `ERR_INVALID_REQUEST` (HTTP 400), with
    undeclared enum members yielding `ERR_INVALID_ENUM` (HTTP 400)."

    Design: Corner/entities/employee_create_missing_required_field
    """
    from test_helpers import create_approved_profile, create_employee_payload
    fw = setup_framework(levels=(("P1", "Engineer I", 1),))
    prof = create_approved_profile(fw["family"]["id"], fw["levels"][0]["id"])
    dept = get_success_data(api_client.create_department(
        create_department_payload(name="Dept A", code="DA"), ADMIN))
    payload = create_employee_payload(
        dept["id"], prof["id"], fw["zone"]["id"],
        employee_ref="E1", hire_date="2020-01-15")
    del payload["base_salary_cents"]
    res = api_client.create_employee(payload, TEST_USERS["hrbp_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_band_create_invalid_enum_rejected(api, comp_analyst_headers):
    """PRD §2.8 tier 3: "Every field the endpoint requires is present, enum
    fields carry declared members only, numeric fields sit in their declared
    domains — `sample_size` at least 1, `spread_pct` and the policy percentages
    non-negative, `differential_ratio` greater than zero, all dates well-formed
    ISO values — and violations yield `ERR_INVALID_REQUEST` (HTTP 400), with
    undeclared enum members yielding `ERR_INVALID_ENUM` (HTTP 400)."
    PRD §3.4: "A `CompAnalyst` creates it by naming the `comp_program_id`,
    `job_family_id`, `job_level_id`, and `geo_zone_id` that fix its
    coordinates, choosing a `target_percentile` of `P50`, `P62_5`, or `P75`
    for market positioning, declaring the band width `spread_pct` as a
    non-negative four-decimal figure (a spread of 0.3000 yields a band thirty
    percent wide), and optionally supplying a `policy_adjustment_factor`, a
    four-decimal policy lever that defaults to 1.0 when omitted."

    Design: Corner/entities/band_create_invalid_enum_rejected
    """
    from test_helpers import create_pay_band_payload, create_program
    fw = setup_framework()
    prog = create_program()
    payload = create_pay_band_payload(
        prog["id"], fw["family"]["id"], fw["levels"][1]["id"], fw["zone"]["id"],
        target_percentile="P90")
    res = api.create_pay_band(payload, comp_analyst_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_ENUM, expected_status=400)


def test_department_list_pagination(api, comp_analyst_headers):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10 when omitted, accepts a minimum of 1, and accepts a maximum
    of 100. The `offset` parameter states how many items to skip and defaults
    to 0."
    PRD §2.3: "Paginated list responses carry four fields in the `meta` object
    of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/department_list_pagination
    """
    for name, code in [("Dept A", "DA"), ("Dept B", "DB"), ("Dept C", "DC")]:
        get_success_data(api_client.create_department(
            create_department_payload(name=name, code=code), ADMIN))
    page1, meta1 = validate_paginated(
        api.list_departments(comp_analyst_headers, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0
    page2, meta2 = validate_paginated(
        api.list_departments(comp_analyst_headers, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_geo_differential_compounding_root_to_leaf(api, comp_admin_headers):
    """PRD §3.1: "a root zone's effective ratio is simply its own differential
    ratio rounded half-up to six decimal places, while a child zone's effective
    ratio is its parent's effective ratio multiplied by the child's own
    differential ratio, with every intermediate product rounded half-up to six
    decimal places before the next multiplication."

    Design: Corner/calculations/geo_differential_compounding
    """
    nat = validate_success(api.create_geo_zone(
        create_geo_zone_payload(zone_code="US-NAT", name="US National",
                                differential_ratio=1.000000),
        comp_admin_headers), 201)
    assert nat["effective_ratio"] == pytest.approx(1.000000, abs=1e-9)
    bay = validate_success(api.create_geo_zone(
        create_geo_zone_payload(zone_code="US-BAY", name="SF Bay",
                                differential_ratio=1.180000,
                                parent_zone_id=nat["id"]),
        comp_admin_headers), 201)
    assert bay["effective_ratio"] == pytest.approx(1.180000, abs=1e-9)
    sfd = validate_success(api.create_geo_zone(
        create_geo_zone_payload(zone_code="US-SFD", name="SF Downtown",
                                differential_ratio=1.050000,
                                parent_zone_id=bay["id"]),
        comp_admin_headers), 201)
    assert sfd["effective_ratio"] == pytest.approx(1.239000, abs=1e-9)


def test_geo_cycle_rejected_on_reparent(api, comp_admin_headers):
    """PRD §3.1: "The parent chain must be acyclic — a creation or re-parenting
    that would close a cycle is rejected with `ERR_GEO_CYCLE` (HTTP 422)."

    Design: Corner/errors/geo_cycle_rejected
    """
    nat = validate_success(api.create_geo_zone(
        create_geo_zone_payload(zone_code="US-NAT", name="US National",
                                differential_ratio=1.000000),
        comp_admin_headers), 201)
    bay = validate_success(api.create_geo_zone(
        create_geo_zone_payload(zone_code="US-BAY", name="SF Bay",
                                differential_ratio=1.180000,
                                parent_zone_id=nat["id"]),
        comp_admin_headers), 201)
    res = api.patch_geo_zone(nat["id"], {"parent_zone_id": bay["id"]}, comp_admin_headers)
    validate_error(res, ApiErrorId.ERR_GEO_CYCLE, expected_status=422)
    nat_after = validate_success(api.get_geo_zone(nat["id"], comp_admin_headers), 200)
    bay_after = validate_success(api.get_geo_zone(bay["id"], comp_admin_headers), 200)
    assert nat_after["effective_ratio"] == pytest.approx(1.000000, abs=1e-9)
    assert bay_after["effective_ratio"] == pytest.approx(1.180000, abs=1e-9)
