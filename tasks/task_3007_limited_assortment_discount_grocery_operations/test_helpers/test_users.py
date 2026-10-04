"""Caller identities for the eight declared roles.

Every request carries an ``X-User-ID`` and an ``X-User-Role`` header. Three
roles are entity-backed: a SupplierRep's id is the acting Supplier's id, a
StoreManager's id is the acting Store's id, and a Cashier's id is the acting
Employee's id. Those roles therefore get per-instance builders that take the
real entity id; falling back to a canned id for them would fail every
ownership check. The other five roles use opaque identifiers that the server
never matches against a stored row.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Stable opaque identifiers for the non-entity-backed roles.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "operations_admin": {"id": "11111111-1111-4111-8111-111111111111", "role": "OperationsAdmin"},
    "category_manager": {"id": "22222222-2222-4222-8222-222222222222", "role": "CategoryManager"},
    "procurement_lead": {"id": "33333333-3333-4333-8333-333333333333", "role": "ProcurementLead"},
    "qa_lead": {"id": "44444444-4444-4444-8444-444444444444", "role": "QualityAssuranceLead"},
    "customer_service_agent": {"id": "55555555-5555-4555-8555-555555555555", "role": "CustomerServiceAgent"},
}

OPERATIONS_ADMIN_HEADERS = build_user_headers(
    TEST_USERS["operations_admin"]["id"], "OperationsAdmin"
)
CATEGORY_MANAGER_HEADERS = build_user_headers(
    TEST_USERS["category_manager"]["id"], "CategoryManager"
)
PROCUREMENT_LEAD_HEADERS = build_user_headers(
    TEST_USERS["procurement_lead"]["id"], "ProcurementLead"
)
QA_LEAD_HEADERS = build_user_headers(TEST_USERS["qa_lead"]["id"], "QualityAssuranceLead")
CUSTOMER_SERVICE_HEADERS = build_user_headers(
    TEST_USERS["customer_service_agent"]["id"], "CustomerServiceAgent"
)


# ── Entity-backed roles ────────────────────────────────────────────────────


def make_supplier_rep_headers(supplier_id: str) -> Dict[str, str]:
    """Headers for a SupplierRep; the id must be the acting Supplier's id."""
    return build_user_headers(supplier_id, "SupplierRep")


def make_store_manager_headers(store_id: str) -> Dict[str, str]:
    """Headers for a StoreManager; the id must be the acting Store's id."""
    return build_user_headers(store_id, "StoreManager")


def make_cashier_headers(employee_id: str) -> Dict[str, str]:
    """Headers for a Cashier; the id must be the acting Employee's id."""
    return build_user_headers(employee_id, "Cashier")


# ── Credential edge shapes, for the authentication tier ────────────────────


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers that omit X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers that omit X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
