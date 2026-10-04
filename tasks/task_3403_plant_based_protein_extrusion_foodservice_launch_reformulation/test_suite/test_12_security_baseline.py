"""Authentication and role-admission baseline (PRD sections 2.1, 4)."""
import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS,
    validate_error, validate_paginated,
    qc_decision_payload,
    create_qualified_active_supplier, create_received_lot, create_bare_supplier,
    fetch_lot,
)

_PM = TEST_USERS["procurement_manager_headers"]


def test_unrecognized_role_is_unauthenticated(api):
    """PRD section 2.1: "A request that omits either header, or carries a
    role the system does not recognize, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)." `Anonymous` is not one of the eight
    declared roles, and the check runs first even on a plain GET (PRD
    section 2.8 tier 1).

    Design: Corner/validations/cn_val_missing_auth_headers_returns_unauthenticated
    """
    resp = api.list_products({"X-User-ID": "anon-1",
                              "X-User-Role": "Anonymous"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_procurement_manager_cannot_run_qc_decision(api):
    """PRD section 4: `POST /protein-ops/ingredient-lots/{id}/qc-decision`
    admits `QualityManager` only. PRD section 2.1: "when the presented role
    is not among the roles an endpoint admits, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)" — the lot stays QUARANTINE.

    Design: Corner/validations/cn_val_wrong_role_on_qc_decision
    """
    supplier = create_qualified_active_supplier(supplier_code="SUP-K-1")
    lot = create_received_lot(supplier["id"], lot_code="LOT-K-1")
    resp = api.qc_decision(
        lot["id"],
        qc_decision_payload("RELEASED", invoiced_unit_cost_cents=500,
                            actual_freight_cents_per_kg=35),
        _PM)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert fetch_lot(lot["id"])["qc_status"] == "QUARANTINE"


def test_get_endpoints_open_to_all_roles(api):
    """PRD section 4: "In the table below, \"Any\" in the role column means
    every authenticated role from §2.1 may call the endpoint" — `GET
    /protein-ops/suppliers` answers 200 for a FinanceController, which owns
    no write operation here.

    Design: Corner/rbac/cn_rbac_get_endpoints_open_to_all_roles
    """
    create_bare_supplier(supplier_code="SUP-K-1")
    _data, meta = validate_paginated(api.list_suppliers(
        TEST_USERS["finance_controller_headers"]))
    assert meta["total_count"] == 1
