"""Security and envelope tests: missing auth context, segregation-of-duties
role denial, entity-backed identity checks, and the error envelope shape."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_partner,
    create_active_restaurant,
    create_draft_contract,
    submit_contract,
    create_yield_standard,
    create_open_period,
    create_meat_cut_batch,
    audit_batch,
    setup_active_contract,
    set_clock,
    make_managing_partner_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
HR = TEST_USERS["hr_recruiter_headers"]
CONTROLLER = TEST_USERS["corporate_controller_headers"]
AUDITOR = TEST_USERS["operations_auditor_headers"]


def test_missing_auth_headers_rejected_before_anything(api):
    """PRD §2.1: "A request missing either header, or carrying an empty value
    for either, is rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
    (HTTP 400)."
    PRD §2.5 item 1: "Authentication context — presence of the `X-User-ID` and
    `X-User-Role` headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`)."

    Design: Corner/validations/missing_auth_headers_rejected_before_anything
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api.get_partner(
        "00000000-0000-0000-0000-000000000000",
        headers={"X-User-ID": "", "X-User-Role": "HRRecruiter"},
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    resp2 = api.get_partner("00000000-0000-0000-0000-000000000000", headers={})
    validate_error(resp2, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_error_envelope_shape_on_every_failure(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard error envelope format: { meta: { api_request_id, ...,
    api_request_timestamp }, response_type: 'error', data: { error_id,
    message } }."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/errors/error_envelope_shape_on_every_failure
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api.create_partner({"full_name": "Only Name"}, HR)
    assert resp.status_code == 400
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_INVALID_REQUEST"
    assert isinstance(body["data"]["message"], str) and len(body["data"]["message"]) > 0
    assert body["meta"].get("api_request_id")
    assert body["meta"].get("api_request_timestamp")


def test_managing_partner_cannot_finalize_period(api):
    """PRD §4: "POST /api/profit-periods/{id}/finalize | Finalize a computed
    period: profit, share, override, retained | CorporateController".
    PRD §2.1: "Once the headers are present, the role is checked against the
    endpoint's authorized set; a role not permitted for the endpoint is
    rejected with ERR_INSUFFICIENT_PERMISSIONS (HTTP 403)."

    Design: Corner/rbac/managing_partner_cannot_finalize_period
    """
    from test_helpers import create_open_period, post_line_item, compute_period

    setup = setup_active_contract()
    period = create_open_period(setup["restaurant"]["id"], "2027-04-01", "2027-05-01")
    set_clock("2027-04-15T00:00:00Z")
    post_line_item(period["id"], "REVENUE", 5000000, "FINALIZED")
    compute_period(period["id"])
    resp = api.finalize_period(
        period["id"], make_managing_partner_headers(setup["partner"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    fetched = validate_success(api.get_profit_period(period["id"], AUDITOR))
    assert fetched["status"] == "COMPUTED"


def test_controller_cannot_certify_and_recruiter_cannot_waive(api):
    """PRD §4: "POST /api/partners/{id}/certify | Certify a partner after
    sufficient training tenure | HRRecruiter".
    PRD §4: "POST /api/meat-cut-batches/{id}/waive | Waive a confirmed
    variance charge | CorporateController".
    PRD §2.1: "Once the headers are present, the role is checked against the
    endpoint's authorized set; a role not permitted for the endpoint is
    rejected with ERR_INSUFFICIENT_PERMISSIONS (HTTP 403)."

    Design: Corner/rbac/controller_cannot_certify_and_recruiter_cannot_waive
    """
    set_clock("2026-09-01T00:00:00Z")
    trainee = create_partner(full_name="Trainee Cid", email="tc@x.com")
    validate_success(api.start_training(trainee["id"], HR))
    setup = setup_active_contract()
    # 10 lbs @ 70% yield, 6 lbs actual: excess = 4.0 - 3.15 = 0.85 lbs;
    # per-batch half-up charge = round(0.85 * 300) = 255 cents.
    create_yield_standard(
        cut_code="SIR_8", expected_yield_pct=70, waste_tolerance_pct=5,
        standard_cost_per_lb_cents=300,
    )
    period = create_open_period(setup["restaurant"]["id"], "2027-01-01", "2027-02-01")
    set_clock("2027-01-10T00:00:00Z")
    batch = create_meat_cut_batch(
        setup["restaurant"]["id"], period["id"], "SIR_8", 10.0
    )
    batch = audit_batch(batch["id"], 6.0)
    assert batch["status"] == "VARIANCE_CONFIRMED"
    assert batch["waste_charge_cents"] == 255

    set_clock("2027-09-07T00:00:00Z")  # trainee at >= 52 accrued weeks
    resp_certify = api.certify_partner(trainee["id"], CONTROLLER)
    validate_error(resp_certify, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    trainee_now = validate_success(api.get_partner(trainee["id"], HR))
    assert trainee_now["status"] in ("IN_TRAINING", "TRAINING_EXTENDED")

    resp_waive = api.waive_meat_cut_batch(batch["id"], HR)
    validate_error(resp_waive, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    batch_now = validate_success(api.get_meat_cut_batch(batch["id"], AUDITOR))
    assert batch_now["status"] == "VARIANCE_CONFIRMED"
    assert batch_now["waste_charge_cents"] == 255


def test_entity_backed_identity_contract_partner_mismatch(api):
    """PRD §2.1: "When X-User-Role is ManagingPartner, X-User-ID is the id of
    the acting Partner; ownership checks on any resource that references a
    Partner (a contract's partner_id, a dispute's filed_by_partner_id) compare
    that foreign-key field to X-User-ID."
    PRD §3.3: "The funding partner must be the contract's own partner — the
    request is rejected with ERR_CONTRACT_PARTNER_MISMATCH when X-User-ID does
    not equal the contract's partner_id."

    Design: Corner/rbac/entity_backed_identity_contract_partner_mismatch
    """
    set_clock("2026-09-01T00:00:00Z")
    p1 = create_partner(full_name="Pat Morgan", email="pm@x.com")
    p5 = create_partner(full_name="Otto Ther", email="ot@x.com")
    restaurant = create_active_restaurant()
    contract = create_draft_contract(p1["id"], restaurant["id"])
    submit_contract(contract["id"])
    resp = api.post_buy_in_payment(
        contract["id"], {"amount_cents": 100}, make_managing_partner_headers(p5["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACT_PARTNER_MISMATCH)
    fetched = validate_success(api.get_contract(contract["id"], CONTROLLER))
    assert fetched["buy_in_escrow_cents"] == 0
