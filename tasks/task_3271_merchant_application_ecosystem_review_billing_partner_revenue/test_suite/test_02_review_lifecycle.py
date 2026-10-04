"""Review lifecycle state-machine tests (corner design: state_machines)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_app,
    create_app_version,
    create_developer,
    create_merchant,
    create_scope_request,
    get_success_data,
    make_admin_headers,
    make_developer_headers,
    make_merchant_headers,
    make_reviewer_headers,
    register_permission_scope,
    setup_active_installation,
    setup_listed_app,
    setup_paid_invoice,
    setup_support_ticket,
    setup_suspended_app,
    submit_app,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_app_submit_from_in_review_rejected(api):
    """PRD §3.2: "The first submission requires that the app be in `DRAFT`,
    that the developer account be `ACTIVE`, and that at least one version of
    the app be in `SUBMITTED` status."

    Design: Corner/state_machines/app_submit_from_in_review_rejected
    """
    developer = create_developer(company_name="DS1")
    app = create_app(developer["id"], name="AppS1", category="PRODUCTIVITY")
    create_app_version(app["id"], developer["id"])
    submit_app(app["id"], developer["id"])
    resp = api.submit_app(app["id"], {}, make_developer_headers(developer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_approve_with_pending_scope_request_rejected(api):
    """PRD §3.3: "Approval of a version requires that every scope request
    attached to the version be resolved — that is, every scope request must
    have status `APPROVED` or `DENIED`, with none still `PENDING`. An approval
    issued while any scope request remains `PENDING` is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/approve_with_pending_scope_request_rejected
    """
    developer = create_developer(company_name="DS2")
    app = create_app(developer["id"], name="AppS2", category="MARKETING")
    version = create_app_version(app["id"], developer["id"])
    register_permission_scope("read_products", risk_level="LOW")
    create_scope_request(version["id"], developer["id"], "read_products")
    submit_app(app["id"], developer["id"])
    resp = api.approve_version(
        version["id"], {"reviewer_id": "rev-1"}, make_reviewer_headers("rev-1")
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_version_reject_denies_pending_scope_requests(api):
    """PRD §3.3: "As a side effect of rejection, every still-`PENDING` scope
    request on the version transitions to `DENIED` with `denied_reason` set to
    the literal string `VERSION_REJECTED`."
    PRD §3.3: "transitions the version `IN_REVIEW → REJECTED` (a terminal
    state for the version; the `REJECTED` status is one of the two terminal
    states a version can reach), and returns the app to `DRAFT` so the
    developer may iterate on a new version."

    Design: Corner/state_machines/version_reject_denies_pending_scope_requests
    """
    developer = create_developer(company_name="DS3")
    app = create_app(developer["id"], name="AppS3", category="FULFILLMENT")
    version = create_app_version(app["id"], developer["id"])
    register_permission_scope("read_products", risk_level="LOW")
    scope_request = create_scope_request(version["id"], developer["id"], "read_products")
    submit_app(app["id"], developer["id"])
    resp = api.reject_version(
        version["id"], {"reviewer_id": "rev-1", "reason": "security gaps"},
        make_reviewer_headers("rev-1"),
    )
    validate_success(resp)
    sr = get_success_data(
        api.get_scope_request(scope_request["id"], make_reviewer_headers("rev-1"))
    )
    assert sr["status"] == "DENIED", f"expected DENIED, got {sr['status']}"
    assert sr["denied_reason"] == "VERSION_REJECTED", (
        f"expected VERSION_REJECTED, got {sr['denied_reason']}"
    )
    app_after = get_success_data(
        api.get_app(app["id"], make_developer_headers(developer["id"]))
    )
    assert app_after["status"] == "DRAFT", f"expected DRAFT, got {app_after['status']}"


def test_installation_initial_state_pending_consent(api):
    """PRD §3.5: "The new installation enters `PENDING_CONSENT` status with
    `installed_at`, `uninstalled_at`, `data_deletion_deadline`, and
    `data_deletion_confirmed_at` all null."

    Design: Corner/state_machines/installation_initial_state_pending_consent
    """
    developer, app, _ = setup_listed_app(company="DS5", category="PRODUCTIVITY")
    merchant = create_merchant()
    resp = api.create_installation(
        {"app_id": app["id"], "merchant_id": merchant["id"]},
        make_merchant_headers(merchant["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "PENDING_CONSENT", (
        f"expected PENDING_CONSENT, got {data['status']}"
    )
    assert data["installed_at"] is None, (
        f"expected installed_at null, got {data['installed_at']}"
    )


def test_charge_approve_idempotency_second_call_fails(api):
    """PRD §3.6: "Approval or decline attempted on a charge that is no longer
    `PENDING` is rejected with `ERR_CHARGE_NOT_PENDING`."

    Design: Corner/state_machines/charge_approve_idempotency_second_call_fails
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company="DS6", category="FINANCE"
    )
    charge = get_success_data(
        api.create_billing_charge(
            installation["id"],
            {"charge_type": "ONE_TIME", "base_amount_cents": 600, "description": "idem"},
            make_developer_headers(developer["id"]),
        )
    )
    merchant_headers = make_merchant_headers(merchant["id"])
    validate_success(api.approve_charge(charge["id"], {}, merchant_headers))
    resp = api.approve_charge(charge["id"], {}, merchant_headers)
    validate_error(resp, ApiErrorId.ERR_CHARGE_NOT_PENDING)


def test_terminal_invoice_void_rejected(api):
    """PRD §3.8: "Voiding an invoice is the escape hatch for an open invoice
    that should never have been created. It requires the invoice to be `OPEN`
    and requires that no charge of the cycle has status `INVOICED`; voiding an
    invoice that is not `OPEN`, or one that already contains invoiced charges,
    is rejected with `ERR_INVOICE_NOT_VOIDABLE`."

    Design: Corner/state_machines/terminal_invoice_void_rejected
    """
    _, _, _, _, _, _, invoice = setup_paid_invoice(
        company="DS7", category="MARKETING", charge_amounts=(700,)
    )
    resp = api.void_invoice(invoice["id"], {}, make_admin_headers())
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_VOIDABLE)


def test_ticket_dispute_reopen_cycle(api):
    """PRD §3.12: "On success the ticket transitions `RESOLVED → DISPUTED`,
    from which the developer may resolve again."

    Design: Corner/state_machines/ticket_dispute_reopen_cycle
    """
    developer, app, merchant, ticket = setup_support_ticket(
        severity="LOW", company="DS8", category="PRODUCTIVITY"
    )
    dev_headers = make_developer_headers(developer["id"])
    validate_success(api.respond_ticket(ticket["id"], {}, dev_headers))
    validate_success(api.resolve_ticket(ticket["id"], {}, dev_headers))
    disputed = validate_success(
        api.dispute_ticket(ticket["id"], {}, make_merchant_headers(merchant["id"]))
    )
    assert disputed["status"] == "DISPUTED", (
        f"expected DISPUTED, got {disputed['status']}"
    )
    resolved = validate_success(api.resolve_ticket(ticket["id"], {}, dev_headers))
    assert resolved["status"] == "RESOLVED", (
        f"expected RESOLVED, got {resolved['status']}"
    )


def test_performance_breach_guarded_delist_transition(api):
    """PRD §2.13: "A breach of this budget first marks the app's
    `performance_state` as `DEGRADED` and opens a governance strike with
    reason `PERFORMANCE_BREACH`; a third consecutive breaching window
    transitions the app's `performance_state` to `DELISTED_PERFORMANCE` and
    drives the app into the delisted terminal state described in §3.2."

    Design: Corner/state_machines/performance_breach_guarded_delist_transition
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company="DS9", category="FULFILLMENT"
    )
    api.create_performance_sample(
        installation["id"],
        {"storefront_load_ms": 300, "sampled_at": "2026-09-03T00:00:00Z"},
        make_developer_headers(developer["id"]),
    )
    app_after = get_success_data(api.get_app(app["id"], make_admin_headers()))
    assert app_after["performance_state"] == "DEGRADED", (
        f"expected DEGRADED, got {app_after['performance_state']}"
    )
    assert app_after["status"] == "LISTED", (
        f"expected LISTED (single breach does not delist), got {app_after['status']}"
    )
    strikes, _ = validate_paginated(
        api.list_app_strikes(app["id"], make_admin_headers())
    )
    assert len(strikes) >= 1, "expected at least one strike"
    assert strikes[0]["reason"] == "PERFORMANCE_BREACH", (
        f"expected PERFORMANCE_BREACH, got {strikes[0]['reason']}"
    )


def test_delist_below_strike_threshold_rejected(api):
    """PRD §3.11: "Delisting a suspended app requires the app to be
    `SUSPENDED` and requires at least five governance strikes of the app to be
    simultaneously `ACTIVE` and unexpired (their `strike_ends_at` strictly
    after the current logical time). A delist attempted with fewer than five
    qualifying strikes is rejected with `ERR_STRIKE_THRESHOLD`."

    Design: Corner/state_machines/delist_below_strike_threshold_rejected
    """
    developer, app, _ = setup_suspended_app(company="DS10", category="ANALYTICS")
    resp = api.delist_app(app["id"], {}, make_admin_headers())
    validate_error(resp, ApiErrorId.ERR_STRIKE_THRESHOLD)
