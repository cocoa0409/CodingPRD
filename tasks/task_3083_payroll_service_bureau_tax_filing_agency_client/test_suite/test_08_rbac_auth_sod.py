"""RBAC, authentication, segregation of duties, and validation-order tests
(PRD §2.1, §2.8, §2.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    build_user_headers,
    create_client,
    create_jurisdiction,
    create_jurisdiction_payload,
    create_payroll_run_payload,
    create_registration_payload,
    create_return_for,
    create_run,
    create_wage_statement_payload,
    get_success_data,
    impound_run,
    make_client_admin_headers,
    set_clock,
    setup_active_client,
    submit_run,
    validate_error,
    validate_success,
)


def test_missing_role_header_returns_unauthenticated():
    """PRD §2.1: "If `X-User-Role` is missing or does not name one of these
    declared roles — or if `X-User-ID` is missing for a role whose identity is
    entity-backed — the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)
    before any other check runs."

    Design: Corner/validations/v_missing_role_header_returns_unauthenticated
    """
    resp = api_client.list_jurisdictions(headers={"X-User-ID": "nobody"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_undeclared_role_returns_unauthenticated():
    """PRD §2.1: "If `X-User-Role` is missing or does not name one of these
    declared roles — or if `X-User-ID` is missing for a role whose identity is
    entity-backed — the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)
    before any other check runs."

    Design: Corner/validations/v_missing_role_header_returns_unauthenticated
    """
    resp = api_client.list_jurisdictions(
        headers=build_user_headers("rogue-1", "SuperAdmin")
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_existence_checked_before_state():
    """PRD §2.8: "Only then does the system verify existence: path and body
    resource identifiers must correspond to existing resources ... and the first
    missing identifier yields `ERR_NOT_FOUND` (HTTP 404)."
    PRD §2.8: "Next, any state-transition endpoint verifies the target resource is
    in a state from which the requested transition is defined, failing with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/validations/v_existence_checked_before_state
    """
    resp = api_client.submit_deposit(
        "00000000-0000-4000-8000-000000000000", TEST_USERS["filer_alpha_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_unknown_return_id_on_file_returns_not_found():
    """PRD §2.8: "path and body resource identifiers must correspond to existing
    resources, validated left-to-right with path identifiers checked before body
    identifiers and body identifiers checked in their declared input order, and
    the first missing identifier yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/validations/v_existence_checked_before_state
    """
    resp = api_client.file_return(
        "00000000-0000-4000-8000-000000000000", TEST_USERS["filer_alpha_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_onboarder_cannot_create_jurisdiction():
    """PRD §2.1: "A request whose role is valid but not permitted for the target
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.1: "a `BureauCompliance` officer configures the tax agency
    jurisdictions the bureau files with."

    Design: Corner/rbac/r_onboarder_cannot_create_jurisdiction
    """
    resp = api_client.create_jurisdiction(
        create_jurisdiction_payload(code="XX-1", name="Nope"),
        TEST_USERS["onboarder_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


def test_treasury_cannot_create_jurisdiction():
    """PRD §2.1: "A request whose role is valid but not permitted for the target
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.1: "a `BureauCompliance` officer configures the tax agency
    jurisdictions the bureau files with."

    Design: Corner/rbac/r_onboarder_cannot_create_jurisdiction
    """
    resp = api_client.create_jurisdiction(
        create_jurisdiction_payload(code="XX-2", name="Nope Two"),
        TEST_USERS["treasury_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


def test_treasury_cannot_file_return():
    """PRD §2.1: "A request whose role is valid but not permitted for the target
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.7: "A `BureauTaxFiler` drafts a TaxReturn for a client."

    Design: Corner/rbac/r_treasury_cannot_file_return
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    ret = create_return_for(client, jurisdiction["id"], "2026-Q3")
    set_clock("2026-10-05T00:00:00Z")  # period closed, so only the role gate can fail
    resp = api_client.file_return(ret["id"], TEST_USERS["treasury_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
    assert validate_success(
        api_client.get_return(ret["id"], TEST_USERS["filer_alpha_headers"])
    )["status"] == "DRAFT"


def test_onboarder_cannot_file_return():
    """PRD §2.1: "A request whose role is valid but not permitted for the target
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.7: "A `BureauTaxFiler` drafts a TaxReturn for a client."

    Design: Corner/rbac/r_treasury_cannot_file_return
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    ret = create_return_for(client, jurisdiction["id"], "2026-Q3")
    set_clock("2026-10-05T00:00:00Z")
    resp = api_client.file_return(ret["id"], TEST_USERS["onboarder_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


def test_client_admin_cannot_settle_impound():
    """PRD §2.1: "A request whose role is valid but not permitted for the target
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.4: "Settlement and failure are treasury actions driven by bank
    webhooks."

    Design: Corner/rbac/r_client_admin_cannot_settle_impound
    """
    setup = setup_active_client()
    client = setup["client"]
    run = create_run(client)
    submit_run(client, run)
    imp = impound_run(client, run)
    resp = api_client.settle_impound(imp["id"], make_client_admin_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
    assert get_success_data(
        api_client.get_impound(imp["id"], TEST_USERS["treasury_headers"])
    )["status"] == "PENDING"


def test_filer_cannot_settle_impound():
    """PRD §2.1: "A request whose role is valid but not permitted for the target
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.4: "Settlement and failure are treasury actions driven by bank
    webhooks."

    Design: Corner/rbac/r_client_admin_cannot_settle_impound
    """
    setup = setup_active_client()
    client = setup["client"]
    run = create_run(client)
    submit_run(client, run)
    imp = impound_run(client, run)
    resp = api_client.settle_impound(imp["id"], TEST_USERS["filer_alpha_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


def test_filer_who_filed_cannot_accept_same_return():
    """PRD §2.9: "The operator whose opaque `X-User-ID` filed a TaxReturn may not
    be the operator who accepts, rejects, or reconciles that same return; likewise,
    the operator who filed a ReturnAmendment may not accept or reject it. Any such
    self-action is rejected with `ERR_SOD_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/r_filer_who_filed_cannot_accept_same_return
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    ret = create_return_for(client, jurisdiction["id"], "2026-Q3")
    set_clock("2026-10-05T00:00:00Z")
    validate_success(
        api_client.file_return(ret["id"], TEST_USERS["filer_alpha_headers"])
    )
    resp = api_client.accept_return(ret["id"], TEST_USERS["filer_alpha_headers"])
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, 403)
    accepted = validate_success(
        api_client.accept_return(ret["id"], TEST_USERS["filer_beta_headers"])
    )
    assert accepted["status"] == "ACCEPTED"


def test_filer_who_filed_cannot_reconcile_same_return():
    """PRD §2.9: "The operator whose opaque `X-User-ID` filed a TaxReturn may not
    be the operator who accepts, rejects, or reconciles that same return; likewise,
    the operator who filed a ReturnAmendment may not accept or reject it. Any such
    self-action is rejected with `ERR_SOD_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/r_filer_who_filed_cannot_accept_same_return
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    ret = create_return_for(client, jurisdiction["id"], "2026-Q3")
    set_clock("2026-10-05T00:00:00Z")
    validate_success(
        api_client.file_return(ret["id"], TEST_USERS["filer_alpha_headers"])
    )
    validate_success(
        api_client.accept_return(ret["id"], TEST_USERS["filer_beta_headers"])
    )
    resp = api_client.reconcile_return(ret["id"], TEST_USERS["filer_alpha_headers"])
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, 403)
    reconciled = validate_success(
        api_client.reconcile_return(ret["id"], TEST_USERS["filer_beta_headers"])
    )
    assert reconciled["status"] == "RECONCILED"


def test_state_precondition_beats_referential_poa_check():
    """PRD §2.8: "Next, any state-transition endpoint verifies the target resource
    is in a state from which the requested transition is defined, failing with
    `ERR_INVALID_STATE` (HTTP 409). Only after these generic layers pass do the
    endpoint-specific business rules run."
    PRD §3.3: "Verification moves the registration from `PENDING` to `VERIFIED` and
    is refused with `ERR_POA_REQUIRED` (HTTP 422) unless both the
    `poa_document_ref` and the `agency_account_number` are present."

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_referential_poa_check
    """
    jurisdiction = create_jurisdiction()
    j_ny = create_jurisdiction(
        code="NY-NYS45", name="NY NYS-45", deposit_frequency="MONTHLY",
        underpayment_threshold_cents=100000,
    )
    client = create_client(legal_name="Priority One Co")
    api_client.begin_onboarding(client["id"], TEST_USERS["onboarder_headers"])
    reg_verified = get_success_data(
        api_client.create_registration(
            client["id"],
            create_registration_payload(jurisdiction_id=jurisdiction["id"]),
            TEST_USERS["onboarder_headers"],
        )
    )
    get_success_data(
        api_client.verify_registration(
            reg_verified["id"], TEST_USERS["onboarder_headers"]
        )
    )
    reg_blank_poa = get_success_data(
        api_client.create_registration(
            client["id"],
            create_registration_payload(
                jurisdiction_id=j_ny["id"], poa_document_ref=""
            ),
            TEST_USERS["onboarder_headers"],
        )
    )

    # Re-verifying a VERIFIED registration: transition undefined -> 409 state gate.
    resp_a = api_client.verify_registration(
        reg_verified["id"], TEST_USERS["onboarder_headers"]
    )
    err_a = validate_error(resp_a, ApiErrorId.ERR_INVALID_STATE, 409)

    # Verifying a PENDING registration with blank POA -> 422 referential gate.
    resp_b = api_client.verify_registration(
        reg_blank_poa["id"], TEST_USERS["onboarder_headers"]
    )
    err_b = validate_error(resp_b, ApiErrorId.ERR_POA_REQUIRED, 422)

    assert err_a["error_id"] != err_b["error_id"]


def test_verify_verified_registration_again_is_invalid_state():
    """PRD §3.3: "`VERIFIED` is terminal for the registration itself."
    PRD §2.8: "any state-transition endpoint verifies the target resource is in a
    state from which the requested transition is defined, failing with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_referential_poa_check
    """
    setup = setup_active_client()
    reg = setup["registration"]
    resp = api_client.verify_registration(reg["id"], TEST_USERS["onboarder_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    fetched = validate_success(
        api_client.get_registration(reg["id"], TEST_USERS["onboarder_headers"])
    )
    assert fetched["status"] == "VERIFIED"


def test_identity_authz_beats_temporal_year_gate():
    """PRD §2.1: "When `X-User-Role` is `ClientPayrollAdmin`, `X-User-ID` is the
    `id` of the acting `Client`; the header value must equal the `client_id` of the
    client aggregate being touched, and a mismatch on any client-scoped endpoint is
    rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.8: "For client-scoped endpoints invoked as `ClientPayrollAdmin`, the
    entity-backed identity check runs next ... Only then does the system verify
    existence ... Only after these generic layers pass do the endpoint-specific
    business rules run."

    Design: Difficulty/priority_pair_validation_conflict/identity_authz_beats_temporal_year_gate
    """
    setup = setup_active_client()
    client_a = setup["client"]
    other = create_client(legal_name="Beta Client")
    ws = get_success_data(
        api_client.create_wage_statement(
            create_wage_statement_payload(client_id=client_a["id"], employee_ref="E-1"),
            TEST_USERS["filer_alpha_headers"],
        )
    )
    # Default clock 2026-09-01: tax year 2026 is NOT closed — but the identity
    # check fires first, so the cross-client issue attempt is 403, not 409.
    resp = api_client.issue_wage_statement(
        ws["id"], make_client_admin_headers(other["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
    assert validate_success(
        api_client.get_wage_statement(ws["id"], TEST_USERS["filer_alpha_headers"])
    )["status"] == "DRAFT"


def test_identity_authz_beats_year_gate_on_void_too():
    """PRD §2.1: "When `X-User-Role` is `ClientPayrollAdmin`, `X-User-ID` is the
    `id` of the acting `Client`; the header value must equal the `client_id` of the
    client aggregate being touched, and a mismatch on any client-scoped endpoint is
    rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/identity_authz_beats_temporal_year_gate
    """
    setup = setup_active_client()
    client_a = setup["client"]
    other = create_client(legal_name="Gamma Client")
    ws = get_success_data(
        api_client.create_wage_statement(
            create_wage_statement_payload(client_id=client_a["id"], employee_ref="E-2"),
            TEST_USERS["filer_alpha_headers"],
        )
    )
    resp = api_client.void_wage_statement(
        ws["id"], make_client_admin_headers(other["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
