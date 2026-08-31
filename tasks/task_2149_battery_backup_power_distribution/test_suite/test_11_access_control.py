"""Authentication, role authorisation, account scoping and separation of duties."""
import pytest

from test_helpers import (
    validate_error, validate_success, validate_paginated, ApiErrorId, TEST_USERS,
    make_hazmat_certifier_headers, make_compliance_officer_headers, make_customer_headers,
    create_warehouse, create_account, create_battery_model, receive_lot, create_order,
    add_line, submit_order, allocate_order, pack_shipment, certify_shipment,
    create_disposal_manifest, scrap_lot, submit_disposal_manifest, set_clock,
    read_order, read_shipment, read_manifest, read_account, read_lot,
    setup_packed_shipment, setup_certified_shipment,
)

ADMIN = TEST_USERS["admin_headers"]
REP = TEST_USERS["sales_rep_headers"]
OPERATOR = TEST_USERS["warehouse_operator_headers"]


def test_the_operator_who_packed_a_shipment_may_not_certify_it(api):
    """PRD §2.8: "A shipment's hazmat certification must be performed by an
    `X-User-ID` different from the `packed_by_user_id` recorded when the
    shipment was packed. A disposal manifest's filing must be performed by an
    `X-User-ID` different from the `created_by_user_id` recorded when the
    manifest was opened. Either violation is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §2.8: "Both checks sit above every state and business check in the
    rejection ladder, so a certifier who packed the shipment is told about the
    conflict of interest even when the shipment is also in the wrong status."

    Design: Corner/rbac/certifier_who_packed_the_shipment_is_refused
    """
    env = setup_packed_shipment(
        quantity=2, core_expected_count=0, model_preset="IB-AGM-95",
        lot_overrides={"manufactured_on": "2026-06-01", "quantity_on_hand": 30},
        order_overrides={"requested_ship_date": "2026-08-05"},
    )
    assert env["shipment"]["packed_by_user_id"] == "op-1"

    resp = api.certify_shipment(env["shipment"]["id"],
                                {"certification_decision": "APPROVE"},
                                make_hazmat_certifier_headers("op-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    shipment = read_shipment(env["shipment"]["id"])
    assert shipment["status"] == "PACKED"
    assert shipment["certified_by_user_id"] is None
    assert read_order(env["order"]["id"])["hazmat_fee_cents"] == 2678


def test_the_officer_who_opened_a_manifest_may_not_file_it(api):
    """PRD §3.9: "The filer must not be the officer who opened it, as Section
    2.8 requires."
    PRD §2.8: "A disposal manifest's filing must be performed by an `X-User-ID`
    different from the `created_by_user_id` recorded when the manifest was
    opened. Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP
    403)."

    Design: Corner/rbac/manifest_author_cannot_file_their_own_manifest
    """
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    model = create_battery_model("IB-31-FLD")
    lot = receive_lot(model["id"], warehouse["id"], manufactured_on="2024-01-01",
                      quantity_on_hand=4)
    manifest = create_disposal_manifest(warehouse["id"])
    scrap_lot(lot["id"], manifest["id"])
    submitted = submit_disposal_manifest(manifest["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["created_by_user_id"] == "comp-1"

    resp = api.file_disposal_manifest(manifest["id"],
                                      make_compliance_officer_headers("comp-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    stored = read_manifest(manifest["id"])
    assert stored["status"] == "SUBMITTED"
    assert stored["filed_by_user_id"] is None
    assert stored["filed_at"] is None


def test_a_sales_rep_may_not_add_a_catalog_model(api):
    """PRD §2.1: "`PlatformAdmin` is the distributor's operations administrator.
    It owns the catalog, the sites, the carriers, the accounts and the logical
    clock, and it is the only role that may register an account, add or
    discontinue a catalog model, register a warehouse or a carrier, or move the
    clock."
    PRD §2.1: "A syntactically valid role that is simply not permitted on the
    requested endpoint is a different failure: that is `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/sales_rep_cannot_create_a_battery_model
    """
    resp = api.create_battery_model({
        "sku": "IB-ROGUE-1", "chemistry": "AGM", "nominal_voltage": 12,
        "amp_hour_capacity": 95, "peukert_exponent": 1.10, "unit_weight_kg": 28.0,
        "lead_content_kg": 13.0, "core_deposit_cents": 2500, "list_price_cents": 26000,
        "warranty_free_replacement_months": 24, "warranty_prorata_months": 36,
        "shelf_life_days": 730, "self_discharge_pct_per_month": 3.0,
    }, REP)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    _rows, meta = validate_paginated(api.list_battery_models(
        ADMIN, params={"limit": 10, "offset": 0}))
    assert meta["total_count"] == 0, "The refused call created nothing"


def test_a_hazmat_certifier_may_not_dispatch_a_shipment(api):
    """PRD §2.1: "`WarehouseOperator` is the site operator: it receives and
    maintains lots, allocates orders, packs, dispatches and delivers shipments,
    and inspects returned cores."
    PRD §2.6: "The role appearing in the endpoint's authorised-role list,
    otherwise `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/hazmat_certifier_cannot_dispatch_a_shipment
    """
    env = setup_certified_shipment(
        quantity=2, core_expected_count=0, model_preset="IB-AGM-95",
        lot_overrides={"manufactured_on": "2026-06-01", "quantity_on_hand": 30},
        order_overrides={"requested_ship_date": "2026-08-05"},
    )
    set_clock("2026-08-05T09:00:00Z")

    resp = api.dispatch_shipment(env["shipment"]["id"],
                                 TEST_USERS["hazmat_certifier_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    shipment = read_shipment(env["shipment"]["id"])
    assert shipment["status"] == "CERTIFIED"
    assert shipment["dispatched_at"] is None
    assert read_order(env["order"]["id"])["fulfillment_status"] == "ALLOCATED"


def test_a_customer_may_not_submit_another_accounts_order(api):
    """PRD §2.1: "Concretely, a `Customer` may act on an order only when
    `Order.account_id` equals `X-User-ID`, on a core return only when
    `CoreReturn.account_id` equals `X-User-ID`, on a warranty claim only when
    `WarrantyClaim.account_id` equals `X-User-ID`, on a service contract only
    when `ServiceContract.account_id` equals `X-User-ID`, and on a creation
    request only when the `account_id` in the body equals `X-User-ID`."
    PRD §2.1: "A `Customer` reaching outside its own account is rejected with
    `ERR_ACCOUNT_SCOPE_VIOLATION` (HTTP 403); this scoping applies to every
    endpoint whose authorised-role list includes `Customer`, reads included."

    Design: Corner/rbac/customer_cannot_submit_another_accounts_order
    """
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    account_a = create_account(name="Account A", account_tier="STANDARD", state_code="TX",
                               credit_limit_cents=100000000, storm_priority_rank=5)
    account_b = create_account(name="Account B", account_tier="STANDARD", state_code="TX",
                               credit_limit_cents=100000000, storm_priority_rank=5)
    model = create_battery_model("IB-AGM-95")
    order = create_order(account_a["id"], warehouse["id"], requested_ship_date="2026-08-11")
    add_line(order["id"], model["id"], 4, core_expected_count=0)

    resp = api.submit_order(order["id"], make_customer_headers(account_b["id"]))
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_SCOPE_VIOLATION.value)

    stored = read_order(order["id"])
    assert stored["fulfillment_status"] == "DRAFT"
    assert stored["credit_status"] == "PENDING"
    assert read_account(account_a["id"])["open_receivable_cents"] == 0

    owned = validate_success(
        api.submit_order(order["id"], make_customer_headers(account_a["id"]))
    )
    assert owned["total_cents"] == 118080, "The owning account may submit its own order"


def test_a_request_without_the_user_id_header_is_unauthenticated(api):
    """PRD §2.1: "Every request to the API — without exception, including reads
    — must carry two headers. `X-User-ID` identifies the caller and
    `X-User-Role` declares the capacity in which the caller is acting. If either
    header is absent or present but empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.6: "Both authentication headers present and non-empty, otherwise
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_x_user_id_header_returns_unauthenticated
    """
    headerless = {"X-User-Role": "PlatformAdmin", "Content-Type": "application/json"}
    resp = api.create_account({
        "name": "Headerless Co", "account_tier": "STANDARD", "state_code": "TX",
        "credit_limit_cents": 500000,
    }, headerless)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    _rows, meta = validate_paginated(api.list_orders(REP, params={"limit": 10, "offset": 0}))
    assert meta["total_count"] == 0
