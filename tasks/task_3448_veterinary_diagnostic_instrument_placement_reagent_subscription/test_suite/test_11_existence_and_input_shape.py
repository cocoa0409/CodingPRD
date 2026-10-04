"""Existence checks, foreign-key ordering, and input-shape errors (PRD §2.4, §2.9, §2.10, §3)."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    UNKNOWN_UUID_1,
    UNKNOWN_UUID_2,
    api_client,
    create_clinic,
    create_reagent_order_payload,
    get_agreement,
    make_clinic_manager_headers,
    patch_lab_test_order_payload,
    patch_service_case_payload,
    reagent_line,
    record_payment_payload,
    resolve_renegotiation_payload,
    setup_agreement_in_renegotiation,
    setup_patient_order_ready,
    validate_error,
    validate_paginated,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_FINANCE = TEST_USERS["finance_reviewer_headers"]
_ENGINEER = TEST_USERS["field_service_engineer_headers"]


def test_unknown_id_reads_return_entity_specific_not_found(api):
    """PRD §2.9 tier 4: "**Existence** — path identifiers are validated left
    to right, then body foreign keys in the order the endpoint's input list
    declares them (`clinic_id` before `agreement_id` before `analyzer_id`),
    else the matching `ERR_CLINIC_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
    `ERR_ANALYZER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`,
    `ERR_TEST_ORDER_NOT_FOUND`, or `ERR_SERVICE_CASE_NOT_FOUND`." PRD §2.2:
    the error envelope carries "response_type": "error" with `error_id` and
    `message`.

    Design: Corner/entities/unknown_id_reads_return_entity_specific_not_found
    """
    expectations = [
        (api_client.get_clinic(NON_EXISTENT_UUID, _ADMIN), ApiErrorId.ERR_CLINIC_NOT_FOUND),
        (api_client.get_placement_agreement(NON_EXISTENT_UUID, _ADMIN), ApiErrorId.ERR_AGREEMENT_NOT_FOUND),
        (api_client.get_analyzer(NON_EXISTENT_UUID, _ADMIN), ApiErrorId.ERR_ANALYZER_NOT_FOUND),
        (api_client.get_reagent_order(NON_EXISTENT_UUID, _ADMIN), ApiErrorId.ERR_ORDER_NOT_FOUND),
        (api_client.get_lab_test_order(NON_EXISTENT_UUID, _ADMIN), ApiErrorId.ERR_TEST_ORDER_NOT_FOUND),
    ]
    for resp, error_id in expectations:
        validate_error(resp, error_id)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == error_id.value
        assert isinstance(body["data"].get("message"), str) and body["data"]["message"]


def test_unknown_id_actions_return_not_found(api):
    """PRD §2.9 tier 4: "**Existence** — path identifiers are validated left
    to right, then body foreign keys in the order the endpoint's input list
    declares them (`clinic_id` before `agreement_id` before `analyzer_id`),
    else the matching `ERR_CLINIC_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
    `ERR_ANALYZER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`,
    `ERR_TEST_ORDER_NOT_FOUND`, or `ERR_SERVICE_CASE_NOT_FOUND`." — existence
    (tier 4) precedes state legality (tier 6), so action endpoints on
    unknown ids answer 404 before any state logic runs.

    Design: Corner/entities/unknown_id_actions_return_not_found
    """
    resp = api_client.update_service_case(
        NON_EXISTENT_UUID, patch_service_case_payload("DISPATCH"), _ENGINEER
    )
    validate_error(resp, ApiErrorId.ERR_SERVICE_CASE_NOT_FOUND)

    resp = api_client.record_payment(
        NON_EXISTENT_UUID, record_payment_payload(100), _FINANCE
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_FOUND)


def test_body_foreign_keys_checked_in_input_order(api):
    """PRD §2.9 tier 4: "then body foreign keys in the order the endpoint's
    input list declares them (`clinic_id` before `agreement_id` before
    `analyzer_id`)". With both keys unknown the clinic error reports; with
    only the agreement unknown the agreement error reports.

    Design: Corner/validations/body_foreign_keys_checked_in_input_order
    """
    clinic = create_clinic()

    both_unknown = api_client.create_reagent_order(
        create_reagent_order_payload(
            UNKNOWN_UUID_1, UNKNOWN_UUID_2,
            order_month="2026-09", lines=[reagent_line("VC300_CHEM_SLIDE", 1)],
        ),
        make_clinic_manager_headers(UNKNOWN_UUID_1),
    )
    validate_error(both_unknown, ApiErrorId.ERR_CLINIC_NOT_FOUND)

    agreement_unknown = api_client.create_reagent_order(
        create_reagent_order_payload(
            clinic["id"], UNKNOWN_UUID_2,
            order_month="2026-09", lines=[reagent_line("VC300_CHEM_SLIDE", 1)],
        ),
        make_clinic_manager_headers(clinic["id"]),
    )
    validate_error(agreement_unknown, ApiErrorId.ERR_AGREEMENT_NOT_FOUND)

    rows, _meta = validate_paginated(api_client.list_reagent_orders(
        _ADMIN, params={"clinic_id": clinic["id"]}
    ))
    assert rows == []


def test_invalid_request_sweep_missing_and_bad_inputs(api):
    """PRD §2.9 tier 5: "required fields present; enum membership ... —
    reported as `ERR_INVALID_REQUEST`". PRD §3.8: "Every recording requires
    `result_value` present (`ERR_INVALID_REQUEST`)". PRD §3.6: "when
    accepting, `new_minimum_cents` must be present and at least 50000 cents,
    or the resolution fails with `ERR_INVALID_REQUEST`". PRD §2.4: "the
    caller supplies `to_iso8601`, which must be strictly later than the
    current logical time — a non-advancing value is rejected with
    `ERR_INVALID_REQUEST`".

    Design: Corner/errors/invalid_request_sweep_missing_and_bad_inputs
    """
    # (a) required field missing on clinic create (PRD §3.1: name is supplied at onboarding)
    resp = api_client.create_clinic({"caseload_baseline_tests": 500}, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    # (b) RECORD_RESULT without result_value
    scenario_b = setup_patient_order_ready()
    order = scenario_b["patient_order"]
    resp = api_client.update_lab_test_order(
        order["id"],
        patch_lab_test_order_payload("RECORD_RESULT"),
        make_clinic_manager_headers(scenario_b["clinic"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert order["id"]  # order untouched; nothing recorded

    # (c) accept=true without new_minimum_cents
    scenario_c = setup_agreement_in_renegotiation()
    agreement = scenario_c["agreement"]
    resp = api_client.resolve_renegotiation(
        agreement["id"],
        resolve_renegotiation_payload(True, agreement["version"]),
        _FINANCE,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert get_agreement(agreement["id"])["status"] == "RENEGOTIATION"

    # (d) clock-set moving backwards from the startup instant
    resp = api_client.set_clock("2026-08-01T00:00:00Z", _ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
