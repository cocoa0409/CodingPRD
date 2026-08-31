"""Authentication, role authorisation, ownership, existence and the rejection order."""

from test_helpers import (
    NO_AUTH_HEADERS,
    TEST_USERS,
    ApiErrorId,
    assign_work_order,
    bootstrap_monitor_campus,
    bootstrap_pump_campus,
    department_version,
    create_vendor,
    drive_to_verified,
    intake_work_order,
    make_dept_steward_headers,
    make_vendor_rep_headers,
    read_department,
    read_device,
    read_pm_task,
    read_work_order,
    set_clock,
    setup_department_on_hold,
    setup_quarantined_device_with_expired_pm_window,
    setup_retired_device_in_on_hold_department,
    setup_reverse_reachability_scene,
    setup_two_departments_one_device,
    setup_two_vendors_one_assigned_order,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_facility_payload

UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


def test_a_request_without_auth_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to the service must carry two headers: `X-User-ID`, identifying
    the caller, and `X-User-Role`, naming the caller's role. If either header is absent or
    empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other
    processing occurs."

    Design: Corner/validations/create_facility_missing_auth_headers_returns_unauthenticated
    """
    response = api.create_facility(create_facility_payload(), NO_AUTH_HEADERS)
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_a_technician_may_not_register_a_campus(api, biomed_tech_headers):
    """PRD §2.1: "If both headers are present but the named role is not among the roles
    authorized for the endpoint (see the table in §4), the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/biomed_tech_cannot_create_a_facility
    """
    response = api.create_facility(
        create_facility_payload(name="Rogue Campus", facility_code="RGE-01"),
        biomed_tech_headers,
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_a_technician_may_not_drive_the_cyber_dimension(api, biomed_tech_headers):
    """PRD §2.1: "If both headers are present but the named role is not among the roles
    authorized for the endpoint (see the table in §4), the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.8: "The `SecurityOfficer` owns the cyber dimension described in §2.8."

    Design: Corner/rbac/biomed_tech_cannot_change_device_security_state
    """
    scene = bootstrap_monitor_campus(model_overrides={"is_network_connected": True})

    response = api.set_device_security_state(scene["device"]["id"],
                                             {"to_state": "ASSESSED_OK"},
                                             biomed_tech_headers)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert read_device(scene["device"]["id"])["security_state"] == "UNASSESSED"


def test_a_department_steward_may_not_close_a_work_order(api):
    """PRD §2.1: "If both headers are present but the named role is not among the roles
    authorized for the endpoint (see the table in §4), the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.5: "Only a `CEManager` closes a work order, and only from `VERIFIED`."

    Design: Corner/rbac/dept_steward_cannot_close_a_work_order
    """
    scene = bootstrap_monitor_campus()
    steward = make_dept_steward_headers(scene["department"]["id"])
    order = drive_to_verified(scene["device"]["id"], 60, 0, intake_headers=steward,
                              problem_summary="Steward-reported fault")
    version = department_version(scene["department"]["id"])

    response = api.close_work_order(order["id"],
                                    {"expected_department_version": version}, steward)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    assert read_work_order(order["id"])["status"] == "VERIFIED"
    assert read_department(scene["department"]["id"])["downtime_spend_cents"] == 0


def test_a_steward_may_not_report_a_fault_on_another_departments_device(api):
    """PRD §2.1: "Concretely, a `DeptSteward` may act on a device only when that device's
    `department_id` equals `X-User-ID`, and may read a department only when that department's
    own `id` equals `X-User-ID`. A violation is rejected with `ERR_OWNERSHIP_VIOLATION`
    (HTTP 403)."

    Design: Corner/validations/dept_steward_cannot_report_fault_on_another_departments_device
    """
    scene = setup_two_departments_one_device()
    foreign_steward = make_dept_steward_headers(scene["department_a"]["id"])

    response = api.create_work_order(
        {"device_id": scene["device"]["id"], "reported_severity": "ROUTINE",
         "problem_summary": "Not my department's device"},
        foreign_steward,
    )
    validate_error(response, ApiErrorId.ERR_OWNERSHIP_VIOLATION.value, 403)

    assert read_device(scene["device"]["id"])["operational_state"] == "IN_SERVICE"
    listed, _ = validate_paginated(
        api.list_work_orders(foreign_steward, params={"device_id": scene["device"]["id"]})
    )
    assert listed == [], "A rejected intake must not create an order"


def test_a_vendor_rep_may_not_complete_another_vendors_repair(api):
    """PRD §2.1: "A `VendorRep` may therefore act on a work order only when that order's
    `vendor_id` equals `X-User-ID`, and on a service contract only when that contract's
    `vendor_id` equals `X-User-ID`. A violation is rejected with `ERR_OWNERSHIP_VIOLATION`
    (HTTP 403)."

    Design: Corner/validations/vendor_rep_cannot_complete_another_vendors_work_order
    """
    scene = setup_two_vendors_one_assigned_order()
    rival = make_vendor_rep_headers(scene["rival_vendor"]["id"])

    response = api.complete_repair(scene["work_order"]["id"],
                                   {"labor_minutes": 60, "parts_cost_cents": 0}, rival)
    validate_error(response, ApiErrorId.ERR_OWNERSHIP_VIOLATION.value, 403)

    order = read_work_order(scene["work_order"]["id"])
    assert order["status"] == "IN_REPAIR"
    assert order["repaired_by_user_id"] is None
    assert order["labor_minutes"] == 0


def test_the_assigned_vendor_rep_may_complete_and_a_technician_may_verify(api,
                                                                         biomed_tech_headers):
    """PRD §3.4: "Either a `BiomedTech` or, on a vendor-mode order, the `VendorRep` whose
    `X-User-ID` equals the order's `vendor_id`, supplies the `labor_minutes` and
    `parts_cost_cents` for the pass."
    PRD §3.4: "A `PASS` moves the order `REPAIR_COMPLETE` → `VERIFIED` and records
    `verified_by_user_id` from `X-User-ID`."

    Design: Corner/rbac/vendor_rep_completes_repair_on_its_own_work_order
    """
    scene = bootstrap_pump_campus()
    vendor = create_vendor()
    set_clock("2026-08-02T10:00:00Z")
    order = intake_work_order(scene["device"]["id"], problem_summary="Vendor service call")
    assign_work_order(order["id"], service_mode="VENDOR", vendor_id=vendor["id"],
                      headers=TEST_USERS["ce_manager_headers"])

    completed = validate_success(
        api.complete_repair(order["id"], {"labor_minutes": 60, "parts_cost_cents": 5000},
                            make_vendor_rep_headers(vendor["id"])),
        200,
    )
    assert completed["status"] == "REPAIR_COMPLETE"
    assert completed["repaired_by_user_id"] == vendor["id"]
    assert completed["estimated_cost_cents"] == 47500, (
        f"60 min at 18500 c/h is 18500, plus 5000 parts and 24000 travel; "
        f"got {completed['estimated_cost_cents']}"
    )

    verified = validate_success(
        api.verify_work_order(order["id"], {"result": "PASS"}, biomed_tech_headers), 200
    )
    assert verified["status"] == "VERIFIED"
    assert verified["verified_by_user_id"] == biomed_tech_headers["X-User-ID"]


def test_an_on_hold_department_may_not_open_a_new_work_order(api, biomed_tech_headers):
    """PRD §2.9: "A department in `ON_HOLD` may not open new corrective work orders and may not
    take on new loaner coverage; both attempts are rejected with
    `ERR_DEPARTMENT_BUDGET_ON_HOLD` (HTTP 402)."

    Design: Corner/validations/department_on_hold_blocks_new_work_order_intake
    """
    scene = setup_department_on_hold()
    device_id = scene["device"]["id"]
    assert scene["department"]["budget_state"] == "ON_HOLD"
    assert read_device(device_id)["operational_state"] == "IN_SERVICE"

    response = api.create_work_order(
        {"device_id": device_id, "reported_severity": "ROUTINE",
         "problem_summary": "Second repair"},
        biomed_tech_headers,
    )
    validate_error(response, ApiErrorId.ERR_DEPARTMENT_BUDGET_ON_HOLD.value, 402)

    department = read_department(scene["department"]["id"])
    assert department["downtime_spend_cents"] == 60000
    assert department["budget_state"] == "ON_HOLD"
    listed, meta = validate_paginated(
        api.list_work_orders(biomed_tech_headers, params={"device_id": device_id})
    )
    assert meta["total_count"] == 1, "The rejected intake must not add a second order"


def test_every_foreign_key_is_reachable_in_reverse_through_its_filtered_list(api,
                                                                            ce_manager_headers,
                                                                            security_officer_headers):
    """PRD §3.1: "Departments can be listed and filtered by owning campus and by budget state;
    the department read is also how a manager obtains the `version` needed for the fiscal guard
    described in §2.7."
    PRD §3.3: "PM tasks can be read individually and listed filtered by `device_id` and by
    `status`."
    PRD §3.6: "Assignments can be read individually and listed with filters on
    `loaner_device_id`, `work_order_id` and `status`."
    PRD §3.7: "Notices can be read individually and listed with filters on `facility_id`,
    `device_model_id` and `status`."
    PRD §3.5: "Contracts can be read individually and listed with filters on `vendor_id`,
    `device_model_id` and `status`."
    PRD §3.8: "Findings can be read individually and listed with filters on `device_id`,
    `status` and `severity`."

    Design: Corner/endpoints/fk_reverse_reachability_filtered_lists_resolve_children
    """
    scene = setup_reverse_reachability_scene()

    checks = [
        (api.list_departments(ce_manager_headers,
                              params={"facility_id": scene["facility"]["id"]}),
         scene["department"]["id"], "departments"),
        (api.list_pm_tasks(ce_manager_headers,
                           params={"device_id": scene["device"]["id"]}),
         scene["pm_task"]["id"], "pm-tasks"),
        (api.list_loaner_assignments(ce_manager_headers,
                                     params={"work_order_id": scene["work_order"]["id"]}),
         scene["loaner"]["id"], "loaner-assignments"),
        (api.list_recall_notices(ce_manager_headers,
                                 params={"facility_id": scene["facility"]["id"]}),
         scene["notice"]["id"], "recall-notices"),
        (api.list_service_contracts(ce_manager_headers,
                                    params={"vendor_id": scene["vendor"]["id"]}),
         scene["contract"]["id"], "service-contracts"),
        (api.list_security_findings(security_officer_headers,
                                    params={"device_id": scene["device"]["id"]}),
         scene["finding"]["id"], "security-findings"),
    ]
    for response, expected_id, label in checks:
        data, meta = validate_paginated(response)
        assert len(data) == 1, f"{label} filtered list returned {len(data)} rows, expected 1"
        assert meta["total_count"] == 1, f"{label} total_count must be 1"
        assert data[0]["id"] == expected_id, f"{label} returned the wrong child row"

    assert read_device(scene["device"]["id"])["security_state"] == "UNASSESSED", (
        "A LOW finding changes no device state"
    )


def test_pm_audit_on_unknown_facility_returns_not_found(api, ce_manager_headers):
    """PRD §2.11: "Existence of every resource named in the URL path, validated left to
    right — the not-found code matching the missing resource type: `ERR_FACILITY_NOT_FOUND`,
    `ERR_DEPARTMENT_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_DEVICE_MODEL_NOT_FOUND`,
    `ERR_DEVICE_NOT_FOUND`, `ERR_PM_TASK_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
    `ERR_LOANER_ASSIGNMENT_NOT_FOUND`, `ERR_RECALL_NOTICE_NOT_FOUND`,
    `ERR_RECALL_MATCH_NOT_FOUND`, `ERR_SERVICE_CONTRACT_NOT_FOUND` or
    `ERR_SECURITY_FINDING_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors/pm_audit_on_unknown_facility_returns_facility_not_found
    """
    response = api.run_pm_audit(UNKNOWN_ID, ce_manager_headers)
    validate_error(response, ApiErrorId.ERR_FACILITY_NOT_FOUND.value, 404)


def test_department_read_with_unknown_id_returns_not_found(api, ce_manager_headers):
    """PRD §2.11: "Existence of every resource named in the URL path, validated left to
    right — the not-found code matching the missing resource type: `ERR_FACILITY_NOT_FOUND`,
    `ERR_DEPARTMENT_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_DEVICE_MODEL_NOT_FOUND`,
    `ERR_DEVICE_NOT_FOUND`, `ERR_PM_TASK_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
    `ERR_LOANER_ASSIGNMENT_NOT_FOUND`, `ERR_RECALL_NOTICE_NOT_FOUND`,
    `ERR_RECALL_MATCH_NOT_FOUND`, `ERR_SERVICE_CONTRACT_NOT_FOUND` or
    `ERR_SECURITY_FINDING_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors/get_unknown_department_returns_department_not_found
    """
    response = api.get_department(UNKNOWN_ID, ce_manager_headers)
    validate_error(response, ApiErrorId.ERR_DEPARTMENT_NOT_FOUND.value, 404)


def test_vendor_read_with_unknown_id_returns_not_found(api, ce_manager_headers):
    """PRD §2.11: "Existence of every resource named in the URL path, validated left to
    right — the not-found code matching the missing resource type: `ERR_FACILITY_NOT_FOUND`,
    `ERR_DEPARTMENT_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_DEVICE_MODEL_NOT_FOUND`,
    `ERR_DEVICE_NOT_FOUND`, `ERR_PM_TASK_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
    `ERR_LOANER_ASSIGNMENT_NOT_FOUND`, `ERR_RECALL_NOTICE_NOT_FOUND`,
    `ERR_RECALL_MATCH_NOT_FOUND`, `ERR_SERVICE_CONTRACT_NOT_FOUND` or
    `ERR_SECURITY_FINDING_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors/get_unknown_vendor_returns_vendor_not_found
    """
    response = api.get_vendor(UNKNOWN_ID, ce_manager_headers)
    validate_error(response, ApiErrorId.ERR_VENDOR_NOT_FOUND.value, 404)


def test_device_model_read_with_unknown_id_returns_not_found(api, ce_manager_headers):
    """PRD §2.11: "Existence of every resource named in the URL path, validated left to
    right — the not-found code matching the missing resource type: `ERR_FACILITY_NOT_FOUND`,
    `ERR_DEPARTMENT_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_DEVICE_MODEL_NOT_FOUND`,
    `ERR_DEVICE_NOT_FOUND`, `ERR_PM_TASK_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
    `ERR_LOANER_ASSIGNMENT_NOT_FOUND`, `ERR_RECALL_NOTICE_NOT_FOUND`,
    `ERR_RECALL_MATCH_NOT_FOUND`, `ERR_SERVICE_CONTRACT_NOT_FOUND` or
    `ERR_SECURITY_FINDING_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors/get_unknown_device_model_returns_device_model_not_found
    """
    response = api.get_device_model(UNKNOWN_ID, ce_manager_headers)
    validate_error(response, ApiErrorId.ERR_DEVICE_MODEL_NOT_FOUND.value, 404)


def test_pm_task_read_with_unknown_id_returns_not_found(api, biomed_tech_headers):
    """PRD §2.11: "Existence of every resource named in the URL path, validated left to
    right — the not-found code matching the missing resource type: `ERR_FACILITY_NOT_FOUND`,
    `ERR_DEPARTMENT_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_DEVICE_MODEL_NOT_FOUND`,
    `ERR_DEVICE_NOT_FOUND`, `ERR_PM_TASK_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
    `ERR_LOANER_ASSIGNMENT_NOT_FOUND`, `ERR_RECALL_NOTICE_NOT_FOUND`,
    `ERR_RECALL_MATCH_NOT_FOUND`, `ERR_SERVICE_CONTRACT_NOT_FOUND` or
    `ERR_SECURITY_FINDING_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors/get_unknown_pm_task_returns_pm_task_not_found
    """
    response = api.get_pm_task(UNKNOWN_ID, biomed_tech_headers)
    validate_error(response, ApiErrorId.ERR_PM_TASK_NOT_FOUND.value, 404)


def test_work_order_read_with_unknown_id_returns_not_found(api, ce_manager_headers):
    """PRD §2.11: "Existence of every resource named in the URL path, validated left to
    right — the not-found code matching the missing resource type: `ERR_FACILITY_NOT_FOUND`,
    `ERR_DEPARTMENT_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_DEVICE_MODEL_NOT_FOUND`,
    `ERR_DEVICE_NOT_FOUND`, `ERR_PM_TASK_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
    `ERR_LOANER_ASSIGNMENT_NOT_FOUND`, `ERR_RECALL_NOTICE_NOT_FOUND`,
    `ERR_RECALL_MATCH_NOT_FOUND`, `ERR_SERVICE_CONTRACT_NOT_FOUND` or
    `ERR_SECURITY_FINDING_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors/get_unknown_work_order_returns_work_order_not_found
    """
    response = api.get_work_order(UNKNOWN_ID, ce_manager_headers)
    validate_error(response, ApiErrorId.ERR_WORK_ORDER_NOT_FOUND.value, 404)


def test_loaner_assignment_read_with_unknown_id_returns_not_found(api, ce_manager_headers):
    """PRD §2.11: "Existence of every resource named in the URL path, validated left to
    right — the not-found code matching the missing resource type: `ERR_FACILITY_NOT_FOUND`,
    `ERR_DEPARTMENT_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_DEVICE_MODEL_NOT_FOUND`,
    `ERR_DEVICE_NOT_FOUND`, `ERR_PM_TASK_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
    `ERR_LOANER_ASSIGNMENT_NOT_FOUND`, `ERR_RECALL_NOTICE_NOT_FOUND`,
    `ERR_RECALL_MATCH_NOT_FOUND`, `ERR_SERVICE_CONTRACT_NOT_FOUND` or
    `ERR_SECURITY_FINDING_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors/get_unknown_loaner_assignment_returns_loaner_assignment_not_found
    """
    response = api.get_loaner_assignment(UNKNOWN_ID, ce_manager_headers)
    validate_error(response, ApiErrorId.ERR_LOANER_ASSIGNMENT_NOT_FOUND.value, 404)


def test_recall_notice_read_with_unknown_id_returns_not_found(api, ce_manager_headers):
    """PRD §2.11: "Existence of every resource named in the URL path, validated left to
    right — the not-found code matching the missing resource type: `ERR_FACILITY_NOT_FOUND`,
    `ERR_DEPARTMENT_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_DEVICE_MODEL_NOT_FOUND`,
    `ERR_DEVICE_NOT_FOUND`, `ERR_PM_TASK_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
    `ERR_LOANER_ASSIGNMENT_NOT_FOUND`, `ERR_RECALL_NOTICE_NOT_FOUND`,
    `ERR_RECALL_MATCH_NOT_FOUND`, `ERR_SERVICE_CONTRACT_NOT_FOUND` or
    `ERR_SECURITY_FINDING_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors/get_unknown_recall_notice_returns_recall_notice_not_found
    """
    response = api.get_recall_notice(UNKNOWN_ID, ce_manager_headers)
    validate_error(response, ApiErrorId.ERR_RECALL_NOTICE_NOT_FOUND.value, 404)


def test_recall_match_read_with_unknown_id_returns_not_found(api, ce_manager_headers):
    """PRD §2.11: "Existence of every resource named in the URL path, validated left to
    right — the not-found code matching the missing resource type: `ERR_FACILITY_NOT_FOUND`,
    `ERR_DEPARTMENT_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_DEVICE_MODEL_NOT_FOUND`,
    `ERR_DEVICE_NOT_FOUND`, `ERR_PM_TASK_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
    `ERR_LOANER_ASSIGNMENT_NOT_FOUND`, `ERR_RECALL_NOTICE_NOT_FOUND`,
    `ERR_RECALL_MATCH_NOT_FOUND`, `ERR_SERVICE_CONTRACT_NOT_FOUND` or
    `ERR_SECURITY_FINDING_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors/get_unknown_recall_match_returns_recall_match_not_found
    """
    response = api.get_recall_match(UNKNOWN_ID, ce_manager_headers)
    validate_error(response, ApiErrorId.ERR_RECALL_MATCH_NOT_FOUND.value, 404)


def test_service_contract_read_with_unknown_id_returns_not_found(api, ce_manager_headers):
    """PRD §2.11: "Existence of every resource named in the URL path, validated left to
    right — the not-found code matching the missing resource type: `ERR_FACILITY_NOT_FOUND`,
    `ERR_DEPARTMENT_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_DEVICE_MODEL_NOT_FOUND`,
    `ERR_DEVICE_NOT_FOUND`, `ERR_PM_TASK_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
    `ERR_LOANER_ASSIGNMENT_NOT_FOUND`, `ERR_RECALL_NOTICE_NOT_FOUND`,
    `ERR_RECALL_MATCH_NOT_FOUND`, `ERR_SERVICE_CONTRACT_NOT_FOUND` or
    `ERR_SECURITY_FINDING_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors/get_unknown_service_contract_returns_service_contract_not_found
    """
    response = api.get_service_contract(UNKNOWN_ID, ce_manager_headers)
    validate_error(response, ApiErrorId.ERR_SERVICE_CONTRACT_NOT_FOUND.value, 404)


def test_security_finding_read_with_unknown_id_returns_not_found(api, security_officer_headers):
    """PRD §2.11: "Existence of every resource named in the URL path, validated left to
    right — the not-found code matching the missing resource type: `ERR_FACILITY_NOT_FOUND`,
    `ERR_DEPARTMENT_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_DEVICE_MODEL_NOT_FOUND`,
    `ERR_DEVICE_NOT_FOUND`, `ERR_PM_TASK_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
    `ERR_LOANER_ASSIGNMENT_NOT_FOUND`, `ERR_RECALL_NOTICE_NOT_FOUND`,
    `ERR_RECALL_MATCH_NOT_FOUND`, `ERR_SERVICE_CONTRACT_NOT_FOUND` or
    `ERR_SECURITY_FINDING_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors/get_unknown_security_finding_returns_security_finding_not_found
    """
    response = api.get_security_finding(UNKNOWN_ID, security_officer_headers)
    validate_error(response, ApiErrorId.ERR_SECURITY_FINDING_NOT_FOUND.value, 404)


def test_retirement_is_reported_before_the_budget_hold(api):
    """PRD §2.11: "When more than one rule could reject a request, the rules are evaluated in a
    fixed order and the **first** failing rule alone decides the response."
    PRD §2.11: "Device retirement — `ERR_DEVICE_RETIRED` (HTTP 409) when the device addressed
    directly or through a child resource has `operational_state` equal to `RETIRED`. This
    guards work-order intake, PM-task creation, PM completion, loaner creation and device
    update."

    Design: Difficulty/priority_pair_validation_conflict/retired_device_state_beats_department_budget_hold
    """
    scene = setup_retired_device_in_on_hold_department()
    steward = make_dept_steward_headers(scene["department"]["id"])

    response = api.create_work_order(
        {"device_id": scene["device"]["id"], "reported_severity": "ROUTINE",
         "problem_summary": "Second fault report"},
        steward,
    )
    validate_error(response, ApiErrorId.ERR_DEVICE_RETIRED.value, 409)
    assert read_device(scene["device"]["id"])["operational_state"] == "RETIRED"


def test_the_budget_hold_is_masked_even_though_it_also_applies(api, ce_manager_headers):
    """PRD §2.11: "Departmental budget hold — `ERR_DEPARTMENT_BUDGET_ON_HOLD` (HTTP 402) on
    work-order intake and on loaner creation."
    PRD §2.9: "From the two, the system derives `budget_state`: it is `ON_HOLD` when
    `downtime_spend_cents` has reached or passed `downtime_budget_cents`; otherwise it is
    `WARNING` when `downtime_spend_cents` multiplied by 100 has reached or passed
    `downtime_budget_cents` multiplied by 80 — that is, when spending stands at eighty percent
    of the ceiling or above; otherwise it is `OPEN`."

    Design: Difficulty/priority_pair_validation_conflict/retired_device_state_beats_department_budget_hold
    """
    scene = setup_retired_device_in_on_hold_department()
    assert scene["department"]["budget_state"] == "ON_HOLD"
    steward = make_dept_steward_headers(scene["department"]["id"])

    response = api.create_work_order(
        {"device_id": scene["device"]["id"], "reported_severity": "ROUTINE",
         "problem_summary": "Second fault report"},
        steward,
    )
    assert response.status_code >= 400, (
        f"An intake on a retired unit must be rejected, got {response.status_code}"
    )
    reported = response.json()["data"].get("error_id")
    assert reported != ApiErrorId.ERR_DEPARTMENT_BUDGET_ON_HOLD.value, (
        "The retirement rule sits above the budget hold in the rejection order"
    )

    listed, meta = validate_paginated(
        api.list_work_orders(ce_manager_headers,
                             params={"device_id": scene["device"]["id"]})
    )
    assert meta["total_count"] == 1, "The rejected intake must not create a second order"


def test_quarantine_is_reported_before_the_pm_window(api, biomed_tech_headers):
    """PRD §2.11: "Quarantine safety — `ERR_DEVICE_QUARANTINED` (HTTP 422) when the device
    under service is quarantined, and, on loaner creation, when the named loaner unit's
    `security_state` is `VULNERABLE` or `QUARANTINED`. This guards PM completion, loaner
    creation and work-order close."
    PRD §2.11: "When more than one rule could reject a request, the rules are evaluated in a
    fixed order and the **first** failing rule alone decides the response."

    Design: Difficulty/priority_pair_validation_conflict/quarantine_safety_beats_pm_window_temporal
    """
    scene = setup_quarantined_device_with_expired_pm_window()

    response = api.complete_pm_task(scene["pm_task"]["id"],
                                    {"result": "PASS", "labor_minutes": 30},
                                    biomed_tech_headers)
    validate_error(response, ApiErrorId.ERR_DEVICE_QUARANTINED.value, 422)
    assert read_device(scene["device"]["id"])["security_state"] == "QUARANTINED"


def test_the_pm_window_rule_is_masked_even_though_the_window_has_closed(api,
                                                                       biomed_tech_headers):
    """PRD §2.11: "PM window — `ERR_PM_OUTSIDE_WINDOW` (HTTP 422) on PM completion."
    PRD §3.3: "Three further guards apply, in the order of §2.11: the device must not be
    `RETIRED` (`ERR_DEVICE_RETIRED`), the device's `security_state` must not be `QUARANTINED`
    (`ERR_DEVICE_QUARANTINED`), and the logical clock must lie at or after `window_start` and
    at or before `window_end` of the task's **current** window — a completion attempt outside
    that closed interval is rejected with `ERR_PM_OUTSIDE_WINDOW`."

    Design: Difficulty/priority_pair_validation_conflict/quarantine_safety_beats_pm_window_temporal
    """
    scene = setup_quarantined_device_with_expired_pm_window()

    response = api.complete_pm_task(scene["pm_task"]["id"],
                                    {"result": "PASS", "labor_minutes": 30},
                                    biomed_tech_headers)
    assert response.status_code >= 400, (
        f"PM completion on a quarantined unit must be rejected, got {response.status_code}"
    )
    reported = response.json()["data"].get("error_id")
    assert reported != ApiErrorId.ERR_PM_OUTSIDE_WINDOW.value, (
        "The quarantine guard sits above the PM window guard in the rejection order"
    )

    task = read_pm_task(scene["pm_task"]["id"])
    assert task["status"] == "SCHEDULED"
    assert task["completed_at"] is None
