"""Pre-built caller identities for the five declared roles.

Four roles are opaque - their ``X-User-ID`` never matches a stored entity - so
a stable shared header set is enough. ``SupplierAnalyst`` is entity-backed: its
``X-User-ID`` must equal the ``SupplierAccount.id`` it acts for, so callers use
``make_supplier_analyst_headers(account_id)`` with the real account id whenever
the call is ownership-gated.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles: shared constants are the canonical form.
    "retailer_admin_headers": build_user_headers("admin-1", UserRole.RETAILER_ADMIN.value),
    "category_manager_headers": build_user_headers("cm-1", UserRole.CATEGORY_MANAGER.value),
    "insights_scientist_headers": build_user_headers("scientist-1", UserRole.INSIGHTS_SCIENTIST.value),
    "data_steward_headers": build_user_headers("steward-1", UserRole.DATA_STEWARD.value),
    # Entity-backed role: fallback for tests that do not exercise ownership
    # (bad-payload 400s, missing-resource 404s). Ownership-gated calls must use
    # make_supplier_analyst_headers() with the actual account id.
    "supplier_analyst_headers": build_user_headers("analyst-orphan-1", UserRole.SUPPLIER_ANALYST.value),
}


def make_supplier_analyst_headers(supplier_account_id: str) -> Dict[str, str]:
    """Headers for a SupplierAnalyst acting for the given SupplierAccount id.

    Required for every ownership-gated supplier write (reports, segments,
    activations, grants, queries): the contract compares ``X-User-ID`` to the
    owning account's id.
    """
    return build_user_headers(supplier_account_id, UserRole.SUPPLIER_ANALYST.value)


def make_data_steward_headers(user_id: str) -> Dict[str, str]:
    """Headers for a specific DataSteward identity.

    Segregation-of-duties checks compare the steward's ``X-User-ID`` against a
    grant's ``requested_by_user_id``, so tests that need a distinct (or a
    colliding) steward identity build it here.
    """
    return build_user_headers(user_id, UserRole.DATA_STEWARD.value)
