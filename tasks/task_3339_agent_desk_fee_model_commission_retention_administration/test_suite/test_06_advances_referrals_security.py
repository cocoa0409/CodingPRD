"""Advances, referral network rules, security (auth/RBAC), and the generic
envelope / pagination / not-found / priority-ordering corners."""
from test_helpers import (
    BOR, CA, MB, NON_EXISTENT_UUID, TA,
    AgentStatus, CdaStatus, InvoiceStatus, OfficeStatus, ReferralStatus,
    build_user_headers,
    create_active_agent, create_agent, create_office, create_second_office,
    create_transaction_under_contract, create_cda,
    create_offer, create_referral_agreement_payload,
    generate_september_invoices,
    get_success_data,
    set_clock, setup_office_with_active_agent, setup_office_with_schedule,
    setup_office_with_two_active_agents,
    validate_error, validate_paginated, validate_success,
    make_agent_headers,
    api_client,
)


# ---------------------------------------------------------------------------
# Advances (compensating invariant)
# ---------------------------------------------------------------------------

def test_advance_and_return_preserve_unearned_balance(api):
    """PRD §3.9: "The advance posts a `CommissionEntry` of kind `ADVANCE` in
    `DISBURSED` status (cash has left the trust), and the agent's
    `unearned_advance_balance_cents` is increased by the amount. The agent may
    later return an advance themselves by submitting an `amount_cents`; the
    return posts an `ADVANCE_RETURN` entry and decreases
    `unearned_advance_balance_cents` by the amount, with a return larger than
    the outstanding balance rejected as `ERR_OVERPAYMENT`."

    Design: Difficulty/compensating_invariant/advance_and_return_preserve_unearned_balance
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    validate_success(api.advance_commission(alice["id"], {"amount_cents": 100000}, MB),
                     expected_status=201)
    after_adv = validate_success(api.get_agent(alice["id"], MB))
    assert after_adv["unearned_advance_balance_cents"] == 100000

    validate_success(api.return_advance(
        alice["id"], {"amount_cents": 100000}, make_agent_headers(alice["id"])),
        expected_status=201)
    after_ret = validate_success(api.get_agent(alice["id"], MB))
    assert after_ret["unearned_advance_balance_cents"] == 0

    entries, _ = validate_paginated(api.list_commission_entries(
        TA, params={"office_id": office["id"]}))
    # PRD §3.9 pins the entry kinds and the balance movement, but not the
    # sign convention of the entry amount_cents — assert sign-agnostically.
    kinds = {(e["entry_kind"], abs(e["amount_cents"])) for e in entries}
    assert ("ADVANCE", 100000) in kinds
    assert ("ADVANCE_RETURN", 100000) in kinds


def test_return_advance_beyond_balance_rejected(api):
    """PRD §3.9: "the return posts an `ADVANCE_RETURN` entry and decreases
    `unearned_advance_balance_cents` by the amount, with a return larger than
    the outstanding balance rejected as `ERR_OVERPAYMENT`."

    Design: Difficulty/compensating_invariant/advance_and_return_preserve_unearned_balance
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    validate_success(api.advance_commission(alice["id"], {"amount_cents": 100000}, MB),
                     expected_status=201)
    validate_success(api.return_advance(
        alice["id"], {"amount_cents": 100000}, make_agent_headers(alice["id"])),
        expected_status=201)
    resp = api.return_advance(
        alice["id"], {"amount_cents": 1}, make_agent_headers(alice["id"]))
    validate_error(resp, "ERR_OVERPAYMENT")
    agent = validate_success(api.get_agent(alice["id"], MB))
    assert agent["unearned_advance_balance_cents"] == 0


# ---------------------------------------------------------------------------
# Validation conflict pairs (priority pairs from the design index)
# ---------------------------------------------------------------------------

def test_cda_review_on_terminal_approved_reports_invalid_state(api):
    """PRD §3.6: "An `APPROVE` at rung 2 completes the ladder: the CDA's
    `status` becomes `APPROVED`, and from that moment the parent transaction
    may advance to `PENDING_CLOSE`."
    PRD §5: "`ERR_INVALID_STATE` | 409 Conflict"

    Design: Difficulty/priority_pair_validation_conflict/cda_review_wrong_rung_and_terminal_state_conflict
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    offer, txn = create_transaction_under_contract(office["id"], alice)
    cda = create_cda(txn["id"])
    # Fully approve the ladder so the CDA is terminal APPROVED.
    validate_success(api.review_cda(cda["id"], {"verdict": "APPROVE"}, CA))
    validate_success(api.review_cda(cda["id"], {"verdict": "APPROVE"}, TA))
    final = validate_success(api.review_cda(cda["id"], {"verdict": "APPROVE"}, MB))
    assert final["status"] == CdaStatus.APPROVED.value

    # A further review — even by the wrong rung owner — hits the terminal
    # state first and reports ERR_INVALID_STATE, not ERR_REVIEW_RUNG_MISMATCH.
    resp = api.review_cda(cda["id"], {"verdict": "APPROVE"}, TA)
    err = validate_error(resp, "ERR_INVALID_STATE")
    assert err["error_id"] != "ERR_REVIEW_RUNG_MISMATCH"
    still = validate_success(api.get_cda(cda["id"], MB))
    assert still["status"] == CdaStatus.APPROVED.value


def test_cda_review_terminal_conflict_is_not_rung_mismatch(api):
    """PRD §3.6: "Reviews proceed one rung at a time, and each rung is owned
    by exactly one role: rung 0 belongs to `ComplianceAuditor`, rung 1 to
    `TrustAccountant`, and rung 2 to `ManagingBroker`."
    PRD §5: "`ERR_INVALID_STATE` | 409 Conflict"

    Design: Difficulty/priority_pair_validation_conflict/cda_review_wrong_rung_and_terminal_state_conflict
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    offer, txn = create_transaction_under_contract(office["id"], alice)
    cda = create_cda(txn["id"])
    validate_success(api.review_cda(cda["id"], {"verdict": "APPROVE"}, CA))
    validate_success(api.review_cda(cda["id"], {"verdict": "APPROVE"}, TA))
    validate_success(api.review_cda(cda["id"], {"verdict": "APPROVE"}, MB))
    # Repeat review attempts remain ERR_INVALID_STATE regardless of role.
    for headers in (CA, TA, MB):
        resp = api.review_cda(cda["id"], {"verdict": "REJECT"}, headers)
        validate_error(resp, "ERR_INVALID_STATE")


def test_pay_paid_invoice_reports_invalid_state_not_overpayment(api):
    """PRD §3.4: "A payment carries `amount_cents`, which must be strictly
    greater than zero and no greater than the remaining balance
    (`amount_due_cents` minus `amount_paid_cents`); anything larger is
    rejected with `ERR_OVERPAYMENT` (HTTP 422)."
    PRD §5: "`ERR_INVALID_STATE` | 409 Conflict"

    Design: Difficulty/priority_pair_validation_conflict/pay_invoice_overpayment_vs_terminal_state_conflict
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-01T00:00:00Z")
    inv = generate_september_invoices(office["id"])[0]
    validate_success(api.pay_invoice(
        inv["id"], {"amount_cents": 365000}, make_agent_headers(alice["id"])))
    assert validate_success(api.get_invoice(inv["id"], MB))["status"] == \
        InvoiceStatus.PAID.value

    resp = api.pay_invoice(inv["id"], {"amount_cents": 99999999},
                           make_agent_headers(alice["id"]))
    err = validate_error(resp, "ERR_INVALID_STATE")
    assert err["error_id"] != "ERR_OVERPAYMENT"
    after = validate_success(api.get_invoice(inv["id"], MB))
    assert after["amount_paid_cents"] == 365000


def test_pay_paid_invoice_leaves_amount_paid_unchanged(api):
    """PRD §3.4: "a payment equal to the remaining balance moves the invoice
    to `PAID`."
    PRD §5: "`ERR_INVALID_STATE` | 409 Conflict"

    Design: Difficulty/priority_pair_validation_conflict/pay_invoice_overpayment_vs_terminal_state_conflict
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-01T00:00:00Z")
    inv = generate_september_invoices(office["id"])[0]
    validate_success(api.pay_invoice(
        inv["id"], {"amount_cents": 365000}, make_agent_headers(alice["id"])))
    for amount in (1, 365000, 99999999):
        resp = api.pay_invoice(inv["id"], {"amount_cents": amount},
                               make_agent_headers(alice["id"]))
        validate_error(resp, "ERR_INVALID_STATE")
    after = validate_success(api.get_invoice(inv["id"], MB))
    assert after["amount_paid_cents"] == 365000
    assert after["status"] == InvoiceStatus.PAID.value


# ---------------------------------------------------------------------------
# Referral network rules
# ---------------------------------------------------------------------------

def test_same_market_referral_rejected_at_accept(api):
    """PRD §3.11: "the referring office's `market_code` must differ from the
    receiving office's `market_code` — referral fees apply only across
    markets, and a same-market pair is rejected with
    `ERR_SAME_MARKET_REFERRAL` (HTTP 422)"

    Design: Corner/errors/same_market_referral_rejected
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    office_den2 = create_office(office_name="Denver Suburban", market_code="DEN",
                                recruiting_target_agents=5)
    ref = get_success_data(api.create_referral_agreement(
        create_referral_agreement_payload(
            referring_office_id=office_den2["id"], receiving_office_id=office["id"],
            agent_id=alice["id"], referral_fee_bps=2000), MB))
    resp = api.accept_referral_agreement(ref["id"], MB)
    validate_error(resp, "ERR_SAME_MARKET_REFERRAL")
    after = validate_success(api.get_referral_agreement(ref["id"], MB))
    assert after["status"] == ReferralStatus.PROPOSED.value


def test_replacement_of_non_active_agreement_rejected(api):
    """PRD §3.11: "when `replaces_agreement_id` is set, the referenced
    agreement must exist and be `ACTIVE`, otherwise the request is rejected
    with `ERR_REPLACED_NOT_ACTIVE` (HTTP 409)."

    Design: Corner/errors/replacement_of_non_active_agreement_rejected
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    office2 = create_second_office()
    ref1 = get_success_data(api.create_referral_agreement(
        create_referral_agreement_payload(
            referring_office_id=office2["id"], receiving_office_id=office["id"],
            agent_id=alice["id"], referral_fee_bps=2000), MB))
    ref2 = get_success_data(api.create_referral_agreement(
        create_referral_agreement_payload(
            referring_office_id=office2["id"], receiving_office_id=office["id"],
            agent_id=alice["id"], referral_fee_bps=2500,
            replaces_agreement_id=ref1["id"]), MB))
    # ref1 was never accepted, so accepting ref2 must be rejected.
    resp = api.accept_referral_agreement(ref2["id"], MB)
    validate_error(resp, "ERR_REPLACED_NOT_ACTIVE")
    r1 = validate_success(api.get_referral_agreement(ref1["id"], MB))
    r2 = validate_success(api.get_referral_agreement(ref2["id"], MB))
    assert r1["status"] == ReferralStatus.PROPOSED.value
    assert r2["status"] == ReferralStatus.PROPOSED.value


# ---------------------------------------------------------------------------
# Security: auth, RBAC, ownership
# ---------------------------------------------------------------------------

def test_missing_role_header_is_unauthenticated(api):
    """PRD §2.1: "Every request carries two mandatory headers: `X-User-ID`
    identifies the acting operator and `X-User-Role` names their operational
    role. A request missing either header, or carrying a role the system does
    not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/unauthenticated_request_missing_role_header
    """
    headers = {"X-User-ID": "someone", "Content-Type": "application/json"}
    resp = api.get_office(NON_EXISTENT_UUID, headers)
    validate_error(resp, "ERR_UNAUTHENTICATED")


def test_forbidden_role_cannot_close_office(api):
    """PRD §3.1: "A `FranchiseeOwner` closes an office by invoking the close
    operation."
    PRD §2.1: "Once authenticated, the role is checked against the endpoint's
    authorization list; an authenticated caller whose role is not permitted
    for the operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/errors/forbidden_role_cannot_close_office
    """
    set_clock("2026-09-10T00:00:00Z")
    office = create_office()
    resp = api.close_office(office["id"], MB)
    validate_error(resp, "ERR_FORBIDDEN")
    after = validate_success(api.get_office(office["id"], MB))
    assert after["status"] == OfficeStatus.ACTIVE.value


def test_agent_cannot_pay_another_agents_invoice(api):
    """PRD §2.1: "An agent attempting to pay another agent's invoice, accept
    another agent's fee assignment, terminate another agent, or return an
    advance on another agent's balance is rejected with `ERR_FORBIDDEN`."

    Design: Corner/roles/agent_cannot_pay_another_agents_invoice
    """
    office, schedule, alice, bob = setup_office_with_two_active_agents(
        "2026-09-01T00:00:00Z")
    invoices = generate_september_invoices(office["id"])
    inv_alice = next(i for i in invoices if i["agent_id"] == alice["id"])
    resp = api.pay_invoice(inv_alice["id"], {"amount_cents": 365000},
                           make_agent_headers(bob["id"]))
    validate_error(resp, "ERR_FORBIDDEN")
    after = validate_success(api.get_invoice(inv_alice["id"], MB))
    assert after["amount_paid_cents"] == 0


def test_trust_accountant_cannot_generate_invoices(api):
    """PRD §4: "| POST | `/offices/{officeId}/generate-invoices` | Monthly
    billing run: one AUTO_RUN invoice per ACTIVE agent with an in-force
    ACCEPTED assignment | ManagingBroker |"
    PRD §2.1: "Once authenticated, the role is checked against the endpoint's
    authorization list; an authenticated caller whose role is not permitted
    for the operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/roles/trust_accountant_cannot_generate_invoices
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-01T00:00:00Z")
    resp = api.generate_invoices(office["id"], {"billing_month": "2026-09"}, TA)
    validate_error(resp, "ERR_FORBIDDEN")
    rows, _ = validate_paginated(api.list_invoices(MB, params={"office_id": office["id"]}))
    assert rows == []


def test_compliance_auditor_reviews_rung_zero_but_not_rung_two(api):
    """PRD §3.6: "Reviews proceed one rung at a time, and each rung is owned
    by exactly one role: rung 0 belongs to `ComplianceAuditor`, rung 1 to
    `TrustAccountant`, and rung 2 to `ManagingBroker`. A review submitted by a
    role that does not own the current rung is rejected with
    `ERR_REVIEW_RUNG_MISMATCH` (HTTP 409)."

    Design: Corner/roles/compliance_auditor_reviews_rung_zero_but_not_rung_two
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    offer, txn = create_transaction_under_contract(office["id"], alice)
    cda = create_cda(txn["id"])
    # ComplianceAuditor owns rung 0.
    ok = validate_success(api.review_cda(cda["id"], {"verdict": "APPROVE"}, CA))
    assert ok["current_rung"] == 1
    validate_success(api.review_cda(cda["id"], {"verdict": "APPROVE"}, TA))
    # ComplianceAuditor at rung 2 (BROKER_SIGNOFF) is a rung mismatch.
    resp = api.review_cda(cda["id"], {"verdict": "APPROVE"}, CA)
    validate_error(resp, "ERR_REVIEW_RUNG_MISMATCH")
    after = validate_success(api.get_cda(cda["id"], MB))
    assert after["current_rung"] == 2
    assert after["status"] == CdaStatus.IN_REVIEW.value


# ---------------------------------------------------------------------------
# Generic corners: not-found, envelope, pagination, existence order, suspended
# ---------------------------------------------------------------------------

def test_offer_get_unknown_id_returns_not_found(api):
    """PRD §2.10: "Endpoints whose paths nest resource identifiers — for
    example an agent under an office, or a closing-statement line under a
    transaction — validate path segments left to right. The server first
    confirms the leftmost identifier exists, then the next, and so on; the
    first segment that fails produces a `ERR_NOT_FOUND` (HTTP 404) response
    and no further segment is examined."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/entities/offer_get_unknown_id_returns_not_found
    """
    set_clock("2026-09-10T00:00:00Z")
    resp = api.get_offer(NON_EXISTENT_UUID, MB)
    err = validate_error(resp, "ERR_NOT_FOUND")
    assert "error_id" in err and "message" in err


def test_transaction_create_checks_body_foreign_keys(api):
    """PRD §3.5: "The referenced offer and both agents must resolve to live
    entities; a dangling reference is rejected with
    `ERR_REFERENTIAL_INTEGRITY`."

    Design: Corner/entities/transaction_create_checks_body_foreign_keys_in_declared_input_order
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    resp1 = api.create_transaction(office["id"], {
        "listing_agent_id": NON_EXISTENT_UUID,
        "selling_agent_id": NON_EXISTENT_UUID,
        "offer_id": NON_EXISTENT_UUID,
        "sale_price_cents": 50000000,
        "gross_commission_cents": 1000000,
    }, MB)
    resp2 = api.create_transaction(office["id"], {
        "listing_agent_id": alice["id"],
        "selling_agent_id": alice["id"],
        "offer_id": NON_EXISTENT_UUID,
        "sale_price_cents": 50000000,
        "gross_commission_cents": 1000000,
    }, MB)
    for resp in (resp1, resp2):
        assert resp.status_code in (404, 422), (
            f"dangling FK must be rejected with 404 ERR_NOT_FOUND or 422 "
            f"ERR_REFERENTIAL_INTEGRITY, got {resp.status_code}")
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] in ("ERR_NOT_FOUND", "ERR_REFERENTIAL_INTEGRITY")
    rows, _ = validate_paginated(api.list_transactions(MB, params={"office_id": office["id"]}))
    assert rows == []


def test_invoices_list_paginates_and_filters(api):
    """PRD §2.3: "List endpoints paginate via the `limit` and `offset` query
    parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of
    100. `offset` defaults to 0. Unless otherwise specified, every list
    endpoint returns resources sorted by `created_at` ascending. List
    responses carry four pagination fields in `meta`: `limit`, `offset`,
    `total_count`, and `has_more`."
    PRD §4: "| GET | `/invoices` | List invoices (filters: `office_id`,
    `agent_id`, `invoice_id`, `status`, `billing_month`) |"

    Design: Corner/entities/invoices_list_paginates_with_total_count_and_has_more
    """
    set_clock("2026-09-01T00:00:00Z")
    office = create_office()
    from test_helpers import create_schedule
    schedule = create_schedule()
    alice = create_active_agent(office["id"], schedule)
    bob = create_active_agent(office["id"], schedule, name="Bob Agent",
                              email="bob@x.com", license_number="LIC-B-002")
    carol = create_active_agent(office["id"], schedule, name="Carol Agent",
                                email="carol@x.com", license_number="LIC-C-003")
    generate_september_invoices(office["id"])

    page1, meta1 = validate_paginated(api.list_invoices(
        TA, params={"office_id": office["id"], "limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(api.list_invoices(
        TA, params={"office_id": office["id"], "limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["has_more"] is False

    issued, _ = validate_paginated(api.list_invoices(
        TA, params={"office_id": office["id"], "status": "ISSUED"}))
    assert len(issued) == 3

    other_month, _ = validate_paginated(api.list_invoices(
        TA, params={"office_id": office["id"], "billing_month": "2026-10"}))
    assert other_month == []

    default_page, meta_default = validate_paginated(api.list_invoices(TA))
    assert len(default_page) == 3
    assert meta_default["limit"] == 10
    assert meta_default["offset"] == 0


def test_onboarding_into_suspended_office_rejected(api):
    """PRD §3.1: "While an office is suspended (or closed), new agent
    onboarding into it is rejected with `ERR_OFFICE_SUSPENDED` (HTTP 409);
    existing agents, transactions, and ledgers continue to operate."

    Design: Corner/validations/onboarding_into_suspended_office_rejected
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-01T00:00:00Z")
    inv = generate_september_invoices(office["id"])[0]
    # Advance past due + 30 days so the unpaid invoice escalates to
    # COLLECTIONS and the office suspends.
    set_clock("2026-10-09T00:00:00Z")
    read = validate_success(api.get_invoice(inv["id"], TA))
    assert read["status"] == InvoiceStatus.COLLECTIONS.value

    resp = api.create_agent(office["id"], {
        "full_name": "Late Joiner", "email": "late@x.com",
        "license_number": "LIC-L-009",
    }, MB)
    validate_error(resp, "ERR_OFFICE_SUSPENDED")
    rows, _ = validate_paginated(api.list_agents(MB, params={"office_id": office["id"]}))
    assert len(rows) == 1


def test_existence_precedes_state_on_unknown_invoice_pay(api):
    """PRD §2.10: "Endpoints whose paths nest resource identifiers — for
    example an agent under an office, or a closing-statement line under a
    transaction — validate path segments left to right. The server first
    confirms the leftmost identifier exists, then the next, and so on; the
    first segment that fails produces a `ERR_NOT_FOUND` (HTTP 404) response
    and no further segment is examined."

    Design: Corner/validations/existence_precedes_state_on_unknown_invoice_pay
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    resp = api.pay_invoice(NON_EXISTENT_UUID, {"amount_cents": 99999999},
                           make_agent_headers(alice["id"]))
    err = validate_error(resp, "ERR_NOT_FOUND")
    assert err["error_id"] not in ("ERR_OVERPAYMENT", "ERR_INVALID_STATE")
