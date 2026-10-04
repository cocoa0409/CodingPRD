"""Authentication context, role permissions, and clinic ownership (PRD §2.1, §2.9, §4)."""

from test_helpers import (
    ApiErrorId,
    CLOCK_START_ISO,
    TEST_USERS,
    activate_agreement,
    api_client,
    approve_agreement,
    build_user_headers,
    create_clinic,
    create_group_pricing_agreement,
    create_reagent_commitment_agreement_payload,
    draft_reagent_commitment_agreement,
    get_agreement,
    get_reagent_order,
    get_test_order,
    get_test_order_results,
    list_commitment_periods,
    make_clinic_manager_headers,
    patch_lab_test_order_payload,
    patch_reagent_order_payload,
    place_reagent_order,
    place_send_out_patient_order,
    record_payment_payload,
    setup_agreement_with_closed_period,
    setup_clinic_with_active_reagent_commitment,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, naming the capacity
    in which they act." PRD §2.1: "A request missing either header, or
    carrying a role outside these five, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_headers_rejected
    """
    resp = api_client.list_group_pricing_agreements({})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"].get("message"), str) and body["data"]["message"]


def test_unknown_role_header_rejected_as_invalid_context(api):
    """PRD §2.1: "The platform recognizes exactly five roles: `PlatformAdmin`,
    `FinanceReviewer`, `ClinicManager`, `FieldServiceEngineer`, and
    `LaboratoryTechnician`." PRD §2.1: "A request missing either header, or
    carrying a role outside these five, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)." — a 400, not a
    403: the role itself fails authentication before authorization runs.

    Design: Corner/validations/unknown_role_header_rejected_invalid_role
    """
    resp = api_client.list_group_pricing_agreements(
        build_user_headers("test-superuser-1", "SuperUser")
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    assert resp.status_code == 400


def test_clinic_manager_cannot_touch_other_clinic_order(api):
    """PRD §2.1: "When `X-User-Role` is `ClinicManager`, `X-User-ID` is the
    `id` of the acting Clinic: ownership checks on any resource that
    references a clinic compare the resource's `clinic_id` — on creation, the
    body's `clinic_id`; otherwise the owning clinic of the addressed entity —
    against `X-User-ID`, and a mismatch is rejected with
    `ERR_CLINIC_OWNERSHIP_MISMATCH` (HTTP 403)." PRD §3.4: "Fulfillment is the
    clinic's own action: from `SUBMITTED`, the owning `ClinicManager` marks
    the order `FULFILLED`".

    Design: Corner/validations/clinic_manager_cannot_touch_other_clinic_order
    """
    scenario_a = setup_clinic_with_active_reagent_commitment()
    clinic_a = scenario_a["clinic"]
    clinic_b = create_clinic(name="Other Vet", caseload_baseline_tests=800)
    draft_b = draft_reagent_commitment_agreement(clinic_b["id"])
    approve_agreement(draft_b["id"])
    agreement_b = activate_agreement(draft_b["id"])
    order_b = place_reagent_order(clinic_b["id"], agreement_b["id"])

    resp = api_client.update_reagent_order(
        order_b["id"],
        patch_reagent_order_payload("FULFILLED"),
        make_clinic_manager_headers(clinic_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CLINIC_OWNERSHIP_MISMATCH)
    assert get_reagent_order(order_b["id"])["status"] == "SUBMITTED"


def test_clinic_manager_cannot_approve_own_draft(api):
    """PRD §3.3: "Segregation of duties governs the rest of the lifecycle: no
    role performs its neighbor's step." PRD §3.3: "Approval moves `DRAFT` →
    `APPROVED` and belongs to `FinanceReviewer`". PRD §2.1: "A request whose
    role is not permitted for the target endpoint — or for the specific field
    or action within that endpoint — is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/clinic_manager_cannot_approve_own_draft
    """
    clinic = create_clinic()
    draft = draft_reagent_commitment_agreement(clinic["id"])

    resp = api_client.approve_placement_agreement(
        draft["id"], make_clinic_manager_headers(clinic["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    assert get_agreement(draft["id"])["status"] == "DRAFT"


def test_laboratory_technician_cannot_create_placement(api):
    """PRD §2.1: "A request whose role is not permitted for the target
    endpoint — or for the specific field or action within that endpoint — is
    rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)." PRD §4: the
    routing and authorization contract assigns "POST
    `/api/placement-agreements`" to `ClinicManager` only.

    Design: Corner/rbac/laboratory_technician_cannot_create_placement
    """
    clinic = create_clinic()
    resp = api_client.create_placement_agreement(
        create_reagent_commitment_agreement_payload(clinic["id"]),
        TEST_USERS["laboratory_technician_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    data, _meta = validate_paginated(api_client.list_placement_agreements(
        TEST_USERS["platform_admin_headers"], params={"clinic_id": clinic["id"]}
    ))
    assert data == []


def test_field_engineer_cannot_record_payment(api):
    """PRD §3.5: "An issued bill is settled through payment recording by
    `FinanceReviewer`". PRD §2.1: "A request whose role is not permitted for
    the target endpoint — or for the specific field or action within that
    endpoint — is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/field_engineer_cannot_record_payment
    """
    scenario = setup_agreement_with_closed_period()
    period = scenario["period"]
    assert period["billing_status"] == "ISSUED"

    resp = api_client.record_payment(
        period["id"],
        record_payment_payload(period["billed_cents"]),
        TEST_USERS["field_service_engineer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    periods = list_commitment_periods(scenario["agreement"]["id"])
    assert periods[0]["billing_status"] == "ISSUED"


def test_finance_reviewer_cannot_set_clock(api):
    """PRD §2.4: "A `PlatformAdmin`-only, test-driving capability advances the
    clock". PRD §2.1: "A request whose role is not permitted for the target
    endpoint — or for the specific field or action within that endpoint — is
    rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)." PRD §3.2: "An
    agreement born with `effective_from` at or before the logical clock starts
    `ACTIVE`; otherwise it starts `DRAFT`".

    Design: Corner/rbac/finance_reviewer_cannot_set_clock
    """
    resp = api_client.set_clock(
        "2026-12-01T00:00:00Z", TEST_USERS["finance_reviewer_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    # Probe: a window opening after the startup instant but before the
    # rejected target lands DRAFT only if the clock never moved.
    gpa = create_group_pricing_agreement(
        group_code="CORP-CLK",
        effective_from="2026-09-02T00:00:00Z",
        effective_to="2026-12-15T00:00:00Z",
    )
    assert gpa["status"] == "DRAFT"
    assert gpa["effective_from"] > CLOCK_START_ISO


def test_lab_test_action_role_matrix_enforced(api):
    """PRD §2.1: "Second, on the test-order pipeline the `action` value
    selects the permitted role: `RECEIVE` is `LaboratoryTechnician`-only;
    `RECORD_RESULT` belongs to `ClinicManager` for `IN_CLINIC` orders and to
    `LaboratoryTechnician` for `SEND_OUT` orders; `DELIVER` and `CANCEL` are
    `ClinicManager`-only." PRD §2.1: "Any other pairing of role and action is
    rejected with `ERR_INSUFFICIENT_PERMISSIONS`." PRD §3.8: "a `source`
    copied from the order's branch (`IN_CLINIC` or `REFERENCE_LAB`, so both
    pipelines land in one record shape)".

    Design: Corner/rbac/lab_test_action_role_matrix_enforced
    """
    clinic = create_clinic()
    order = place_send_out_patient_order(clinic["id"])
    cm = make_clinic_manager_headers(clinic["id"])
    lt = TEST_USERS["laboratory_technician_headers"]

    resp = api_client.update_lab_test_order(
        order["id"], patch_lab_test_order_payload("RECEIVE"), cm
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    assert get_test_order(order["id"])["status"] == "ORDERED"

    received = validate_success(api_client.update_lab_test_order(
        order["id"], patch_lab_test_order_payload("RECEIVE"), lt
    ))
    assert received["status"] == "RECEIVED"

    resp = api_client.update_lab_test_order(
        order["id"], patch_lab_test_order_payload("RECORD_RESULT", result_value=42.0), cm
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    recorded = validate_success(api_client.update_lab_test_order(
        order["id"], patch_lab_test_order_payload("RECORD_RESULT", result_value=42.0), lt
    ))
    assert recorded["status"] == "RESULT_RECORDED"
    assert recorded["delivery_status"] == "PENDING"

    results = get_test_order_results(order["id"])
    assert len(results) == 1
    assert results[0]["source"] == "REFERENCE_LAB"
    assert results[0]["verdict"] is None
