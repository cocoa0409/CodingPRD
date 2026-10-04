"""Endpoint behavior, error catalogue, RBAC, and cross-cutting corner tests."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_app,
    create_app_version,
    create_approved_charge,
    create_developer,
    create_merchant,
    create_scope_request,
    get_success_data,
    make_admin_headers,
    make_developer_headers,
    make_merchant_headers,
    make_reviewer_headers,
    open_invoice,
    register_permission_scope,
    setup_active_installation,
    setup_listed_app,
    setup_uninstalled_installation,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ---------------------------------------------------------------------------
# endpoints section
# ---------------------------------------------------------------------------

def test_response_envelope_error_shape(api):
    """PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what
    went wrong."

    Design: Corner/endpoints/response_envelope_error_shape
    """
    resp = api.get_merchant(NON_EXISTENT_UUID, make_admin_headers())
    body = resp.json()
    assert body["response_type"] == "error", (
        f"expected response_type error, got {body.get('response_type')}"
    )
    error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert error_data.get("message"), "error message must be non-empty"


def test_charge_create_assigns_billing_cycle_from_clock(api):
    """PRD §2.11: "When a charge is created, the server mints its
    `billing_cycle` from the current logical clock — the charge's cycle is the
    calendar month containing the creation timestamp."
    PRD §3.6: "New charges enter `PENDING` status."

    Design: Corner/endpoints/charge_create_assigns_billing_cycle_from_clock
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company="DE1", category="PRODUCTIVITY"
    )
    charge = validate_success(
        api.create_billing_charge(
            installation["id"],
            {"charge_type": "ONE_TIME", "base_amount_cents": 500,
             "description": "cycle check"},
            make_developer_headers(developer["id"]),
        ),
        expected_status=201,
    )
    assert charge["billing_cycle"] == "2026-09", (
        f"expected billing_cycle 2026-09, got {charge['billing_cycle']}"
    )
    assert charge["status"] == "PENDING", f"expected PENDING, got {charge['status']}"


def test_install_unlisted_app_rejected(api):
    """PRD §3.5: "Installation is only possible against an app whose
    `listing_status` is `LISTED`; an attempt against an unlisted, suspended,
    or delisted app is rejected with `ERR_APP_NOT_LISTED`."

    Design: Corner/endpoints/install_unlisted_app_rejected
    """
    developer = create_developer(company_name="DE2")
    app = create_app(developer["id"], name="AppE2", category="MARKETING")
    merchant = create_merchant()
    resp = api.create_installation(
        {"app_id": app["id"], "merchant_id": merchant["id"]},
        make_merchant_headers(merchant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_APP_NOT_LISTED)


def test_issue_invoice_without_approved_charges_rejected(api):
    """PRD §3.8: "An issue attempt against an invoice with no `APPROVED`
    charges for the cycle is rejected with `ERR_INVALID_AMOUNT`."

    Design: Corner/endpoints/issue_invoice_without_approved_charges_rejected
    """
    merchant = create_merchant(shop_domain="me3.myshop.com")
    invoice = open_invoice(merchant, cycle="2026-09")
    resp = api.issue_invoice(
        invoice["id"],
        {"expected_invoice_version": invoice["version"]},
        make_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_AMOUNT)


def test_version_semver_unique_per_app(api):
    """PRD §3.2: "A developer creates a version for an app by providing a
    `semver` string, which must be unique within the app — reusing a `semver`
    already on file for the same app is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/endpoints/version_semver_unique_per_app
    """
    developer = create_developer(company_name="DE4")
    app = create_app(developer["id"], name="AppE4", category="FINANCE")
    create_app_version(app["id"], developer["id"], semver="1.0.0")
    resp = api.create_app_version(
        app["id"], {"semver": "1.0.0"}, make_developer_headers(developer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# errors section (non-stub instances)
# ---------------------------------------------------------------------------

def test_error_unauthenticated_missing_headers(api):
    """PRD §2.1: "Requests missing either header, or presenting a role the
    platform does not recognize, are rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/errors/error_unauthenticated_missing_headers
    """
    resp = api.list_apps({"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_error_already_terminal_on_uninstalled_installation(api):
    """PRD §3.9: "`UNINSTALLED` is terminal for the installation."
    PRD §2.7: "State — the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`, or the more specific
    state errors `ERR_UNINSTALL_IN_PROGRESS`, `ERR_CHARGE_NOT_PENDING`,
    `ERR_INVOICE_NOT_ISSUABLE`, `ERR_INVOICE_NOT_VOIDABLE`,
    `ERR_VERSION_NOT_REVIEWABLE`, `ERR_APP_NOT_LISTED`,
    `ERR_ALREADY_TERMINAL`)."

    Design: Corner/errors/error_already_terminal_on_uninstalled_installation
    """
    developer, app, merchant, installation = setup_uninstalled_installation(
        company="DX1", category="PRODUCTIVITY"
    )
    resp = api.create_billing_charge(
        installation["id"],
        {"charge_type": "ONE_TIME", "base_amount_cents": 100, "description": "too late"},
        make_developer_headers(developer["id"]),
    )
    # PRD §3.9 names both `ERR_UNINSTALL_IN_PROGRESS` ("Operations that
    # require an installed installation — ... creating charges ... — are
    # rejected with `ERR_UNINSTALL_IN_PROGRESS` when attempted against an
    # installation that is `UNINSTALLING` or `UNINSTALLED`") and
    # `ERR_ALREADY_TERMINAL` (§2.7's state-error list, with `UNINSTALLED`
    # terminal per §3.9); PRD does not pin which of the two applies here.
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_ALREADY_TERMINAL, ApiErrorId.ERR_UNINSTALL_IN_PROGRESS]
    )


def test_error_version_not_reviewable(api):
    """PRD §3.3: "Approval of a version requires that every scope request
    attached to the version be resolved" — and §2.7 names
    `ERR_VERSION_NOT_REVIEWABLE` among the specific state errors for a target
    resource not in a state from which the requested transition is defined.

    Design: Corner/errors/error_version_not_reviewable
    """
    developer = create_developer(company_name="DX2")
    app = create_app(developer["id"], name="AppX2", category="ANALYTICS")
    version = create_app_version(app["id"], developer["id"])
    # App never submitted: the version is SUBMITTED, not IN_REVIEW.
    resp = api.approve_version(
        version["id"], {"reviewer_id": "rev-1"}, make_reviewer_headers("rev-1")
    )
    validate_error(resp, ApiErrorId.ERR_VERSION_NOT_REVIEWABLE)


# ---------------------------------------------------------------------------
# rbac section
# ---------------------------------------------------------------------------

def test_merchant_cannot_suspend_app(api):
    """PRD §2.1: "A request whose role is authenticated but not authorized for
    the target endpoint — or whose principal fails an ownership check the
    endpoint declares — is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: `POST /apps/{id}/suspend` is authorized for PlatformAdmin only.

    Design: Corner/rbac/merchant_cannot_suspend_app
    """
    developer, app, _ = setup_listed_app(company="DR1", category="PRODUCTIVITY")
    merchant = create_merchant(shop_domain="mr1.myshop.com")
    resp = api.suspend_app(app["id"], {}, make_merchant_headers(merchant["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_reviewer_cannot_create_app(api):
    """PRD §2.1: "A request whose role is authenticated but not authorized for
    the target endpoint — or whose principal fails an ownership check the
    endpoint declares — is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: `POST /apps` is authorized for Developer only.

    Design: Corner/rbac/reviewer_cannot_create_app
    """
    developer = create_developer(company_name="DR2")
    resp = api.create_app(
        {"developer_id": developer["id"], "name": "AppR2", "category": "MARKETING"},
        make_reviewer_headers("rev-9"),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_developer_cannot_decide_scope_request(api):
    """PRD §2.1: "A request whose role is authenticated but not authorized for
    the target endpoint — or whose principal fails an ownership check the
    endpoint declares — is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: `POST /scope-requests/{id}/decide` is authorized for Reviewer only.

    Design: Corner/rbac/developer_cannot_decide_scope_request
    """
    developer = create_developer(company_name="DR3")
    app = create_app(developer["id"], name="AppR3", category="FINANCE")
    version = create_app_version(app["id"], developer["id"])
    register_permission_scope("read_products", risk_level="LOW")
    scope_request = create_scope_request(version["id"], developer["id"], "read_products")
    resp = api.decide_scope_request(
        scope_request["id"], {"decision": "APPROVED"},
        make_developer_headers(developer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_merchant_cannot_approve_other_merchants_charge(api):
    """PRD §2.1: "When `X-User-Role` is `Merchant`, `X-User-ID` is the `id` of
    the acting `MerchantAccount`; ownership checks on any resource that
    references a merchant (an installation's `merchant_id`, an invoice's
    `merchant_id`, a support ticket's `merchant_id`) compare that field to
    `X-User-ID`."
    PRD §3.6: "A merchant approves a pending charge on their own installation"

    Design: Corner/rbac/merchant_cannot_approve_other_merchants_charge
    """
    developer, app, version, merchant_a, installation = setup_active_installation(
        company="DR4", category="ANALYTICS"
    )
    merchant_b = create_merchant(shop_domain="mr4b.myshop.com")
    charge = get_success_data(
        api.create_billing_charge(
            installation["id"],
            {"charge_type": "ONE_TIME", "base_amount_cents": 400,
             "description": "owned by mR4a"},
            make_developer_headers(developer["id"]),
        )
    )
    resp = api.approve_charge(charge["id"], {}, make_merchant_headers(merchant_b["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# cross_cutting_complexity_layers + consistency_model sections
# ---------------------------------------------------------------------------

def test_occ_stale_version_rejected(api):
    """PRD §2.6: "Updating an app's mutable fields requires the request to
    carry `expected_app_version` equal to the `App` resource's current
    `version` at the moment the client last read it. If the app's `version`
    has advanced since — because a reviewer action flipped the app into
    `CHANGES_REQUESTED`, or because a performance cascade mutated the app —
    the update is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.1: "Successful updates increment the app's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_rejected
    """
    developer = create_developer(company_name="DCC1")
    app = create_app(developer["id"], name="AppCC1", category="PRODUCTIVITY")
    dev_headers = make_developer_headers(developer["id"])
    updated = validate_success(
        api.update_app(
            app["id"],
            {"name": "AppCC1-renamed", "expected_app_version": app["version"]},
            dev_headers,
        )
    )
    assert updated["version"] == app["version"] + 1, (
        f"expected version {app['version'] + 1}, got {updated['version']}"
    )
    resp = api.update_app(
        app["id"],
        {"name": "AppCC1-stale", "expected_app_version": app["version"]},
        dev_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_immediate_consistency_invoice_total_in_issue_response(api):
    """PRD §3.8: "On success, every matching `APPROVED` charge transitions
    `APPROVED → INVOICED` (each such charge's `version` increments and its
    `platform_share_cents` and `developer_net_cents` are finalized per §3.6
    using the app's `revenue_share_tier` in force at invoice time), the
    invoice transitions `OPEN → ISSUED`, `issued_at` is set to the current
    logical time, the invoice's `total_cents` is recomputed as the sum of
    `final_amount_cents` over the merchant's `INVOICED` charges for the cycle"

    Design: Corner/consistency_model/immediate_consistency_invoice_total_in_issue_response
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company="DIM1", category="MARKETING"
    )
    create_approved_charge(installation, developer, merchant, 2500)
    invoice = open_invoice(merchant, cycle="2026-09")
    issued = validate_success(
        api.issue_invoice(
            invoice["id"],
            {"expected_invoice_version": invoice["version"]},
            make_admin_headers(),
        )
    )
    assert issued["total_cents"] == 2500, (
        f"expected total_cents 2500 in the issue response, got {issued['total_cents']}"
    )
    assert issued["status"] == "ISSUED", f"expected ISSUED, got {issued['status']}"
