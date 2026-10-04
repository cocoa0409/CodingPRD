"""Pre-built role headers for every role in PRD Section 2.1.

Two forms per role:

* A shared-constant entry in ``TEST_USERS`` — used only by tests whose success
  does NOT depend on the caller owning the subject resource (e.g. 400/404
  paths, or calls by the six opaque roles whose X-User-ID is never compared
  to an entity id).
* A per-instance builder ``make_<role>_headers(user_id)`` — mandatory for the
  entity-backed ``Customer`` role (X-User-ID must equal a real Customer.id for
  any ownership-gated call), and required wherever segregation-of-duties needs
  two specific operator identities (protocol submitter vs approver, inspection
  reporter vs verifier).
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole


# Default operator identities. These are opaque identifiers (PRD Section 2.1:
# "an opaque operator identifier not tied to any persisted entity").
ADMIN_USER_ID = "admin-1"
FACILITY_MANAGER_USER_ID = "fm-1"
VETERINARIAN_USER_ID = "vet-1"
IACUC_REVIEWER_USER_ID = "rev-1"
LOGISTICS_COORDINATOR_USER_ID = "logi-1"
WELFARE_INSPECTOR_USER_ID = "insp-1"

# Fallback shared id for the entity-backed Customer role. Safe ONLY for tests
# that never exercise ownership (no real Customer carries this id).
CUSTOMER_FALLBACK_USER_ID = "customer-fallback-1"


TEST_USERS = {
    "admin_headers": build_user_headers(ADMIN_USER_ID, UserRole.PLATFORM_ADMIN.value),
    "facility_manager_headers": build_user_headers(
        FACILITY_MANAGER_USER_ID, UserRole.FACILITY_MANAGER.value
    ),
    "veterinarian_headers": build_user_headers(
        VETERINARIAN_USER_ID, UserRole.VETERINARIAN.value
    ),
    "iacuc_reviewer_headers": build_user_headers(
        IACUC_REVIEWER_USER_ID, UserRole.IACUC_REVIEWER.value
    ),
    # Fallback only — ownership-gated calls must use make_customer_headers().
    "customer_headers": build_user_headers(
        CUSTOMER_FALLBACK_USER_ID, UserRole.CUSTOMER.value
    ),
    "logistics_headers": build_user_headers(
        LOGISTICS_COORDINATOR_USER_ID, UserRole.LOGISTICS_COORDINATOR.value
    ),
    "inspector_headers": build_user_headers(
        WELFARE_INSPECTOR_USER_ID, UserRole.WELFARE_INSPECTOR.value
    ),
}


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.PLATFORM_ADMIN.value)


def make_facility_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.FACILITY_MANAGER.value)


def make_veterinarian_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.VETERINARIAN.value)


def make_iacuc_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.IACUC_REVIEWER.value)


def make_customer_headers(customer_id: str) -> dict:
    """Customer is entity-backed (PRD Section 2.1): pass the real Customer.id
    whenever the call is ownership-gated (own record, orders, contracts,
    receiving protocol)."""
    return build_user_headers(customer_id, UserRole.CUSTOMER.value)


def make_logistics_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.LOGISTICS_COORDINATOR.value)


def make_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.WELFARE_INSPECTOR.value)


__all__ = [
    "ADMIN_USER_ID",
    "FACILITY_MANAGER_USER_ID",
    "VETERINARIAN_USER_ID",
    "IACUC_REVIEWER_USER_ID",
    "LOGISTICS_COORDINATOR_USER_ID",
    "WELFARE_INSPECTOR_USER_ID",
    "CUSTOMER_FALLBACK_USER_ID",
    "TEST_USERS",
    "make_admin_headers",
    "make_facility_manager_headers",
    "make_veterinarian_headers",
    "make_iacuc_reviewer_headers",
    "make_customer_headers",
    "make_logistics_headers",
    "make_inspector_headers",
]
