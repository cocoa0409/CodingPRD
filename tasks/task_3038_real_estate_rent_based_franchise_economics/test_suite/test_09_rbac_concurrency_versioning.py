"""RBAC denials, ownership checks, optimistic concurrency, and version bumps."""
import test_helpers as th


def test_operator_cannot_create_sites(api, admin_headers):
    """PRD §2.1: "Any attempt to perform an operation outside the caller's
    designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP
    403)."
    PRD §4: "POST /franchise-system/sites — Register a site (fee-simple
    purchase or ground lease) — FranchisorAdmin."

    Design: Corner/roles_rbac/operator_cannot_create_sites
    """
    op = th.create_operator(legal_name="RBAC Op LLC", fy_net_worth_cents=1_000_000,
                            fy_operating_income_cents=100_000)
    resp = api.create_site(
        th.create_site_payload(site_code="CS15", address="115 Corner St"),
        th.make_operator_headers(op["id"]),
    )
    th.validate_error(resp, th.ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)


def test_coop_manager_cannot_disburse_national_fund(api, admin_headers, coop_headers):
    """PRD §3.9: "Either a `FranchisorAdmin` or a `CoopManager` may disburse
    from a fund by supplying an `amount_cents` and a `purpose`, but a
    `CoopManager` is restricted to `LOCAL_COOP` funds — attempting to disburse
    from a `NATIONAL` fund is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/roles_rbac/coop_manager_cannot_disburse_national_fund
    """
    fund = th.get_success_data(api.create_advertising_fund(
        th.create_advertising_fund_payload(name="National Only", fund_type="NATIONAL", admin_fee_rate=0.0),
        admin_headers,
    ))
    resp = api.disburse_fund(fund["id"], {"amount_cents": 100, "purpose": "coop trying national"}, coop_headers)
    th.validate_error(resp, th.ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)


def test_operator_cannot_submit_other_operators_sales_report(api, finance_headers):
    """PRD §2.1: "an `Operator` caller acting on a resource owned by a
    different operator is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §3.4: "Submitting the report is an owner-only action: the `X-User-ID`
    must equal the operator that owns the report's store (else
    `ERR_NOT_RESOURCE_OWNER`), and the store must be `OPEN` (else
    `ERR_STORE_NOT_OPEN`)."

    Design: Corner/roles_rbac/operator_cannot_submit_other_operators_sales_report
    """
    ctx = th.setup_open_store()
    intruder = th.create_operator(legal_name="Intruder Op LLC")

    owner_headers = th.make_operator_headers(ctx["operator"]["id"])
    report = th.get_success_data(api.create_sales_report(
        th.create_sales_report_payload(ctx["store"]["id"], "2026-09", 1_000_000), owner_headers
    ))

    resp = api.submit_sales_report(report["id"], th.make_operator_headers(intruder["id"]))
    th.validate_error(resp, th.ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)
    after = th.validate_success(api.get_sales_report(report["id"], finance_headers))
    assert after["status"] == "DRAFT"


def test_stale_operator_version_on_store_create(api, admin_headers, finance_headers):
    """PRD §2.9: "Creating a store requires the request body to include
    `expected_operator_version`, holding the client-observed `version` of the
    `Operator` the store will be attached to; if the operator's current
    `version` has advanced since that observation — for example because a
    capacity review submission changed `max_stores`, or another store was just
    created — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/stale_operator_version_on_store_create
    """
    site = th.create_site()
    operator = th.create_strong_approved_operator(legal_name="OCC Op LLC")
    observed_version = th.get_operator_version(operator["id"])

    # An escrow deposit bumps the operator's version after the client read it.
    th.deposit_escrow(operator["id"], 500)

    resp = api.create_store(
        th.create_store_payload(site["id"], operator["id"], observed_version),
        admin_headers,
    )
    th.validate_error(resp, th.ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_rent_charge_version_increments_on_payment(api, finance_headers):
    """PRD §2.4: "`version` is an integer starting at 1 that increments by
    exactly 1 on every mutation of the resource, including mutations driven by
    cascades originating on other entities."
    PRD §3.5: "each payment's `amount_cents` adds to `amount_paid_cents`, and
    when the cumulative payments fully cover the selected rent the charge moves
    `OPEN → PAID`, again recomputing `delinquency_balance_cents`."

    Design: Corner/cross_cutting_layers/rent_charge_version_increments_on_payment
    """
    ctx = th.setup_open_store()
    charge = th.post_rent_charge(ctx["store"]["id"], ctx["sublease"]["id"])
    assert charge["version"] == 1
    assert charge["amount_paid_cents"] == 0

    th.validate_success(api.pay_rent_charge(charge["id"], {"amount_cents": 1_000_000}, finance_headers))

    after = th.validate_success(api.get_rent_charge(charge["id"], finance_headers))
    assert after["amount_paid_cents"] == 1_000_000
    # 1,000,000 < 2,448,000: partial payment keeps the charge OPEN.
    assert after["status"] == "OPEN"
    assert after["version"] == 2


def test_rent_charge_terminal_paid_lockdown(api, finance_headers):
    """PRD §3.5: "Payments arrive through a `FranchiseFinance` officer against
    a charge that must be `OPEN` (else `ERR_CHARGE_NOT_OPEN`); each payment's
    `amount_cents` adds to `amount_paid_cents`, and when the cumulative
    payments fully cover the selected rent the charge moves `OPEN → PAID`,
    again recomputing `delinquency_balance_cents`."

    Design: Corner/state_machines/rent_charge_terminal_paid_lockdown
    """
    ctx = th.setup_open_store()
    charge = th.post_rent_charge(ctx["store"]["id"], ctx["sublease"]["id"])
    full = charge["selected_rent_cents"]

    th.validate_success(api.pay_rent_charge(charge["id"], {"amount_cents": full}, finance_headers))
    paid = th.validate_success(api.get_rent_charge(charge["id"], finance_headers))
    assert paid["status"] == "PAID"

    resp = api.pay_rent_charge(charge["id"], {"amount_cents": 1}, finance_headers)
    th.validate_error(resp, th.ApiErrorId.ERR_CHARGE_NOT_OPEN, expected_status=409)
    after = th.validate_success(api.get_rent_charge(charge["id"], finance_headers))
    assert after["status"] == "PAID"
    assert after["amount_paid_cents"] == full
