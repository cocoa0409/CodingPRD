"""Header authentication, endpoint authorisation and the entity-specific 404 catalogue."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_payer_payload,
    post_txn,
    read_account,
    seed_account,
    seed_payer,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
ANALYST = TEST_USERS["credit_analyst_headers"]
APPROVER = TEST_USERS["refund_approver_headers"]
OFFICER = TEST_USERS["disbursement_officer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]

NOT_FOUND_PROBES = [
    ("get_patient_account", "00000000-0000-4000-8000-000000000001",
     ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value, "credit_analyst_headers"),
    ("get_account_transaction", "00000000-0000-4000-8000-000000000002",
     ApiErrorId.ERR_TRANSACTION_NOT_FOUND.value, "credit_analyst_headers"),
    ("get_credit_balance", "00000000-0000-4000-8000-000000000003",
     ApiErrorId.ERR_CREDIT_BALANCE_NOT_FOUND.value, "credit_analyst_headers"),
    ("get_root_cause_finding", "00000000-0000-4000-8000-000000000004",
     ApiErrorId.ERR_ROOT_CAUSE_FINDING_NOT_FOUND.value, "credit_analyst_headers"),
    ("get_refund_request", "00000000-0000-4000-8000-000000000005",
     ApiErrorId.ERR_REFUND_REQUEST_NOT_FOUND.value, "credit_analyst_headers"),
    ("get_refund_approval", "00000000-0000-4000-8000-000000000006",
     ApiErrorId.ERR_REFUND_APPROVAL_NOT_FOUND.value, "refund_approver_headers"),
    ("get_refund_batch", "00000000-0000-4000-8000-000000000007",
     ApiErrorId.ERR_REFUND_BATCH_NOT_FOUND.value, "disbursement_officer_headers"),
    ("get_check_disbursement", "00000000-0000-4000-8000-000000000008",
     ApiErrorId.ERR_CHECK_NOT_FOUND.value, "disbursement_officer_headers"),
    ("get_take_back_notice", "00000000-0000-4000-8000-000000000009",
     ApiErrorId.ERR_TAKE_BACK_NOTICE_NOT_FOUND.value, "credit_analyst_headers"),
    ("get_offset_application", "00000000-0000-4000-8000-00000000000a",
     ApiErrorId.ERR_OFFSET_APPLICATION_NOT_FOUND.value, "credit_analyst_headers"),
    ("get_medicare_obligation", "00000000-0000-4000-8000-00000000000b",
     ApiErrorId.ERR_MEDICARE_OBLIGATION_NOT_FOUND.value, "compliance_officer_headers"),
    ("get_escheatment_record", "00000000-0000-4000-8000-00000000000c",
     ApiErrorId.ERR_ESCHEATMENT_RECORD_NOT_FOUND.value, "compliance_officer_headers"),
    ("get_compliance_report", "00000000-0000-4000-8000-00000000000d",
     ApiErrorId.ERR_COMPLIANCE_REPORT_NOT_FOUND.value, "compliance_officer_headers"),
]


def test_request_without_well_formed_role_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to every endpoint — reads included — must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the capacity in which the caller is acting. If either header is missing, or if `X-User-Role` is not one of the six role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/request_without_role_and_user_headers_is_unauthenticated
    """
    payload = create_payer_payload(
        name="Ghost Payer", payer_code="GHO", payer_type="COMMERCIAL"
    )

    no_headers = api.create_payer(payload, {"Content-Type": "application/json"})
    validate_error(no_headers, ApiErrorId.ERR_UNAUTHENTICATED.value)

    undeclared_role = api.create_payer(
        payload,
        {
            "X-User-ID": "ghost-1",
            "X-User-Role": "NoSuchRole",
            "Content-Type": "application/json",
        },
    )
    validate_error(undeclared_role, ApiErrorId.ERR_UNAUTHENTICATED.value)

    _, meta = validate_paginated(api.list_payers(ADMIN))
    assert meta["total_count"] == 0


def test_authorisation_is_checked_before_the_path_id_is_resolved(api):
    """PRD §2.8: "2. The acting role is authorised for the endpoint — `ERR_FORBIDDEN_ROLE`."
    PRD §2.8: "3. Every id in the path resolves, left to right — the entity-specific 404 from §2.4."
    PRD §2.8: "The ordering below is normative — a request that both names a non-existent credit balance and carries an illegal enum value fails on existence, not on shape, because existence is checked first."

    Design: Corner/validations/forbidden_role_check_precedes_existence_check_priority_ordering
    """
    seed_payer(payer_code="COM", payer_type="COMMERCIAL")

    response = api.start_credit_balance_review(
        "00000000-0000-4000-8000-000000000000", {}, OFFICER
    )
    error = validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    assert error["error_id"] != ApiErrorId.ERR_CREDIT_BALANCE_NOT_FOUND.value


def test_system_admin_may_not_run_the_identification_sweep(api):
    """PRD §2.1: "A `SystemAdmin` seeds payers and accounts, moves an account's `status`, drives the logical clock and runs the nightly operations checkpoint. It deliberately holds no analyst, approval, disbursement or compliance authority."
    PRD §3.2: "A `CreditAnalyst` initiates the identification sweep, optionally narrowing it with an `account_ids` array; when that array is omitted the sweep considers every account in the system."

    Design: Corner/rbac/system_admin_cannot_run_the_credit_balance_identification_sweep
    """
    set_clock("2026-08-01T00:00:00Z")
    payer = seed_payer(payer_code="COM", payer_type="COMMERCIAL")
    account = seed_account(payer["id"], account_number="ACCT-SA1",
                           financial_class="INPATIENT", patient_name="Sal Ames")
    post_txn(account["id"], "CHARGE", 50_000, "SYSTEM", headers=ADMIN)
    set_clock("2026-08-15T00:00:00Z")
    post_txn(account["id"], "PAYMENT", -62_000, "PATIENT", headers=ADMIN)

    response = api.run_identify_sweep({"account_ids": [account["id"]]}, ADMIN)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    _, meta = validate_paginated(
        api.list_credit_balances(ANALYST, params={"account_id": account["id"]})
    )
    assert meta["total_count"] == 0
    stored = read_account(account["id"])
    assert stored["balance_cents"] == -12_000
    assert stored["credit_balance_cents"] == 0


def test_both_the_compliance_officer_and_the_system_admin_run_the_checkpoint(api):
    """PRD §3.14: "They are collected into a single operations checkpoint that a `SystemAdmin` or a `ComplianceOfficer` may run at any point, and which by convention is run nightly. The checkpoint takes no input, mutates whatever the current logical clock now justifies, and reports four counts."
    PRD §3.14: "The number moved is reported as `staled_check_count`."
    PRD §3.14: "The number withdrawn is reported as `withdrawn_notice_count`."

    Design: Corner/rbac/compliance_officer_and_system_admin_both_run_the_aging_sweep
    """
    set_clock("2026-08-16T00:00:00Z")

    for headers in (COMPLIANCE, ADMIN):
        result = validate_success(api.run_aging_sweep(headers, {}))
        assert result["staled_check_count"] == 0
        assert result["late_obligation_count"] == 0
        assert result["closed_batch_count"] == 0
        assert result["withdrawn_notice_count"] == 0


def test_reading_an_unstored_payer_returns_the_payer_not_found_error(api):
    """PRD §2.4: "The not-found errors are entity-specific: `ERR_PAYER_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_CREDIT_BALANCE_NOT_FOUND`, `ERR_ROOT_CAUSE_FINDING_NOT_FOUND`, `ERR_REFUND_REQUEST_NOT_FOUND`, `ERR_REFUND_APPROVAL_NOT_FOUND`, `ERR_REFUND_BATCH_NOT_FOUND`, `ERR_CHECK_NOT_FOUND`, `ERR_TAKE_BACK_NOTICE_NOT_FOUND`, `ERR_OFFSET_APPLICATION_NOT_FOUND`, `ERR_MEDICARE_OBLIGATION_NOT_FOUND`, `ERR_ESCHEATMENT_RECORD_NOT_FOUND` and `ERR_COMPLIANCE_REPORT_NOT_FOUND`, all HTTP 404."

    Design: Corner/entities/payer_get_with_unknown_uuid_returns_not_found
    """
    seed_payer(payer_code="COM", payer_type="COMMERCIAL")

    response = api.get_payer("00000000-0000-4000-8000-000000000000", ANALYST)
    validate_error(response, ApiErrorId.ERR_PAYER_NOT_FOUND.value)
    assert response.json()["response_type"] == "error"


@pytest.mark.parametrize(
    "method_name,unknown_id,expected_error_id,role_key", NOT_FOUND_PROBES
)
def test_single_resource_reads_map_to_entity_specific_not_found_errors(
    api, method_name, unknown_id, expected_error_id, role_key
):
    """PRD §2.4: "The not-found errors are entity-specific: `ERR_PAYER_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_CREDIT_BALANCE_NOT_FOUND`, `ERR_ROOT_CAUSE_FINDING_NOT_FOUND`, `ERR_REFUND_REQUEST_NOT_FOUND`, `ERR_REFUND_APPROVAL_NOT_FOUND`, `ERR_REFUND_BATCH_NOT_FOUND`, `ERR_CHECK_NOT_FOUND`, `ERR_TAKE_BACK_NOTICE_NOT_FOUND`, `ERR_OFFSET_APPLICATION_NOT_FOUND`, `ERR_MEDICARE_OBLIGATION_NOT_FOUND`, `ERR_ESCHEATMENT_RECORD_NOT_FOUND` and `ERR_COMPLIANCE_REPORT_NOT_FOUND`, all HTTP 404."
    PRD §2.4: "Path identifiers are resolved strictly left to right. A request naming several path segments that each carry an id resolves the leftmost first; if that id does not match a stored row the request fails immediately with that entity's not-found error and no further segment is examined."

    Design: Corner/errors/single_resource_reads_with_unknown_ids_return_entity_specific_not_found_errors
    """
    response = getattr(api, method_name)(unknown_id, TEST_USERS[role_key])
    validate_error(response, expected_error_id)
    assert response.json()["response_type"] == "error"
