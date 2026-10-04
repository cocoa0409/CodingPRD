"""Registry onboarding, response envelope, authentication, and role access."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_payee,
    create_collection_agency_payload,
    create_creditor_agency_payload,
    create_federal_creditor,
    create_notice_payload,
    create_payee_payload,
    create_refund_claim_payload,
    make_creditor_analyst_headers,
    read_debt,
    read_payment,
    refer_debt,
    register_collection_agency,
    register_payee,
    set_logical_clock,
    setup_evaluated_payment,
    validate_error,
    validate_success,
)

OPERATOR = TEST_USERS["treasury_operator_headers"]
SUPERVISOR = TEST_USERS["treasury_supervisor_headers"]
AGENCY_ANALYST = TEST_USERS["payment_agency_analyst_headers"]
OFFICER = TEST_USERS["refund_officer_headers"]


def test_payee_create_returns_201_with_system_fields(api):
    """PRD §4: "Operations that create a new resource return `201 Created`".
    PRD §2.5: "Every resource in the system — creditor agencies, payees,
    exemption policies, debts, payment files, payments, offsets, refund claims,
    collection agencies, collection actions, reverse-offset requests, reciprocal
    agreements, and do-not-pay records — carries a standard set of system-managed
    fields".

    Design: Corner/entities/payee_create_returns_201_with_system_fields
    """
    set_logical_clock()
    resp = api.create_payee(
        create_payee_payload(
            tin="111-22-3333",
            tin_type="SSN",
            legal_name="Pat Doe",
            routing_number="021000021",
            account_last4="4321",
        ),
        OPERATOR,
    )
    assert resp.json()["response_type"] == "object"
    data = validate_success(resp, 201)
    assert_payee(data)
    assert data["tin"] == "111-22-3333"
    assert data["tin_type"] == "SSN"
    assert data["legal_name"] == "Pat Doe"
    assert data["version"] == 1
    assert data["created_at"] and data["updated_at"]


def test_creditor_state_code_conditional_requirement(api):
    """PRD §3.1: "The `state_code` field is conditional: a `STATE` creditor must
    supply its two-letter code, and a missing code is `ERR_STATE_CODE_REQUIRED`;
    a `FEDERAL` creditor must omit it entirely, and a supplied code is
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/creditor_state_code_conditional_requirement
    """
    set_logical_clock()
    resp_state = api.create_creditor_agency(
        {
            "creditor_code": "CA-FTB",
            "legal_name": "California Franchise Tax Board",
            "creditor_type": "STATE",
        },
        SUPERVISOR,
    )
    validate_error(resp_state, ApiErrorId.ERR_STATE_CODE_REQUIRED)

    resp_fed = api.create_creditor_agency(
        {
            "creditor_code": "IRS-7469",
            "legal_name": "Federal Test Creditor",
            "creditor_type": "FEDERAL",
            "state_code": "CA",
        },
        SUPERVISOR,
    )
    err = validate_error(resp_fed, ApiErrorId.ERR_INVALID_REQUEST)
    assert err["error_id"] != ApiErrorId.ERR_STATE_CODE_REQUIRED


def test_duplicate_tin_returns_conflict(api):
    """PRD §3.1: "Each payee declares a `tin` — unique across all payees, with
    duplicates rejected as `ERR_DUPLICATE_TIN`".

    Design: Corner/validations/duplicate_tin_returns_conflict
    """
    set_logical_clock()
    register_payee(tin="111-22-3333")
    resp = api.create_payee(
        create_payee_payload(tin="111-22-3333", legal_name="Patricia Doeh"),
        OPERATOR,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_TIN)


def test_duplicate_registry_codes_return_conflict(api):
    """PRD §3.1: "A `TreasurySupervisor` registers each creditor agency with a
    unique `creditor_code` — duplicates are rejected with
    `ERR_DUPLICATE_CREDITOR_CODE`".
    PRD §3.1: "each with a unique `agency_code` — duplicates rejected with
    `ERR_DUPLICATE_AGENCY_CODE`".

    Design: Corner/validations/duplicate_registry_codes_return_conflict
    """
    set_logical_clock()
    create_federal_creditor(creditor_code="IRS-7469")
    register_collection_agency(agency_code="PCA-A")

    resp_creditor = api.create_creditor_agency(
        create_creditor_agency_payload(
            creditor_code="IRS-7469", legal_name="Impostor Bureau"
        ),
        SUPERVISOR,
    )
    validate_error(resp_creditor, ApiErrorId.ERR_DUPLICATE_CREDITOR_CODE)

    resp_agency = api.create_collection_agency(
        create_collection_agency_payload(
            agency_code="PCA-A", name="Pioneer Again", capacity_max_active=3
        ),
        SUPERVISOR,
    )
    validate_error(resp_agency, ApiErrorId.ERR_DUPLICATE_AGENCY_CODE)


def test_payment_create_missing_auth_headers_returns_400(api):
    """PRD §2.1: "A request missing either header, or presenting a role the
    system does not declare, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400)."

    Design: Corner/errors/payment_create_missing_auth_headers_returns_400
    """
    set_logical_clock()
    resp = api.create_payee(
        create_payee_payload(tin="111-22-3333", legal_name="Pat Doe"),
        None,  # no X-User-ID / X-User-Role headers at all
    )
    err = validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    assert err["error_id"] and err["message"]


def test_clock_default_reads_2026_09_01(api):
    """PRD §2.4: "Before it is ever set, the clock reads exactly
    2026-09-01T00:00:00Z, and it never falls back to wall-clock time on its own."

    Design: Corner/endpoints/clock_default_reads_2026_09_01
    """
    # Deliberately no set_logical_clock call: the clock has never been set.
    creditor = create_federal_creditor(creditor_code="IRS-7469")
    for field in ("created_at", "updated_at"):
        stamp = creditor[field]
        assert stamp.startswith("2026-09-01T00:00:00") and stamp.endswith("Z"), (
            f"{field} must read the pinned default clock instant, got {stamp!r}"
        )


def test_payment_agency_analyst_cannot_execute_payment(api):
    """PRD §2.1: "Every endpoint restricts which roles may invoke it (see §4); a
    caller whose role is not listed for the endpoint is rejected with
    `ERR_FORBIDDEN_FOR_ROLE` (403)."
    PRD §4: POST /payments/{paymentId}/execute is authorized for
    TreasuryOperator only.

    Design: Corner/rbac/payment_agency_analyst_cannot_execute_payment
    """
    ns = setup_evaluated_payment(amount_cents=25000, payment_type="VENDOR")
    resp = api.execute_payment(ns["payment"]["id"], AGENCY_ANALYST)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
    payment = read_payment(ns["payment"]["id"])
    assert payment["processing_status"] == "EVALUATED"


def test_creditor_analyst_cannot_notice_other_creditors_debt(api):
    """PRD §2.1: "ownership checks on any resource that references a creditor
    compare the resource's `creditor_agency_id` field to `X-User-ID`, and a
    mismatch is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/creditor_analyst_cannot_notice_other_creditors_debt
    """
    set_logical_clock()
    cred_fed = create_federal_creditor(creditor_code="IRS-7469")
    cred_ssa = create_federal_creditor(
        creditor_code="SSA-111", legal_name="Social Security Test Bureau"
    )
    debt = refer_debt(cred_ssa)
    assert debt["status"] == "REFERRED"

    resp = api.notice_debt(
        debt["id"],
        create_notice_payload(),
        make_creditor_analyst_headers(cred_fed["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
    assert read_debt(debt["id"])["status"] == "REFERRED"


def test_refund_officer_cannot_file_claim(api):
    """PRD §2.1: "a caller whose role is not listed for the endpoint is rejected
    with `ERR_FORBIDDEN_FOR_ROLE` (403)."
    PRD §2.8: "The ordering is observable behavior: a request failing an earlier
    tier never surfaces a later tier's error".

    Design: Corner/rbac/refund_officer_cannot_file_claim
    """
    set_logical_clock()
    resp = api.create_refund_claim(
        create_refund_claim_payload(NON_EXISTENT_UUID, 100),
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
