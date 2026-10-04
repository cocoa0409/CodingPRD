"""Pre-built role headers for every role in the PRD (§2.1).

For non-Customer roles X-User-ID is an opaque operator identifier; segregation-
of-duties rules compare those ids, so builders accept explicit user ids.
For Customer, X-User-ID IS the acting Customer resource's id — always build
those headers with the real customer id via make_customer_headers().
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import ANALYST_ONE, ANALYST_TWO, OFFICER_ONE, OFFICER_TWO

# Shared constants — safe for calls that do not exercise ownership or
# segregation-of-duties identity checks.
TEST_USERS = {
    "program_admin_headers": build_user_headers("admin-1", "ProgramAdmin"),
    "metrologist_headers": build_user_headers(ANALYST_ONE, "Metrologist"),
    "certification_officer_headers": build_user_headers(OFFICER_ONE, "CertificationOfficer"),
    "inventory_manager_headers": build_user_headers("inv-1", "InventoryManager"),
    "calibration_coordinator_headers": build_user_headers("coord-1", "CalibrationCoordinator"),
    "accreditation_officer_headers": build_user_headers("ao-1", "AccreditationOfficer"),
    # Fallback only for non-ownership tests; real customer calls must use
    # make_customer_headers(customer["id"]).
    "customer_headers": build_user_headers("cust-opaque-1", "Customer"),
}


def make_program_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_metrologist_headers(user_id: str) -> dict:
    """Metrologist identity is recorded as analyst_user_id on methods."""
    return build_user_headers(user_id, "Metrologist")


def make_certification_officer_headers(user_id: str) -> dict:
    """CertificationOfficer identity is recorded as publisher_user_id."""
    return build_user_headers(user_id, "CertificationOfficer")


def make_inventory_manager_headers(user_id: str = "inv-1") -> dict:
    return build_user_headers(user_id, "InventoryManager")


def make_calibration_coordinator_headers(user_id: str = "coord-1") -> dict:
    return build_user_headers(user_id, "CalibrationCoordinator")


def make_accreditation_officer_headers(user_id: str = "ao-1") -> dict:
    return build_user_headers(user_id, "AccreditationOfficer")


def make_customer_headers(user_id: str) -> dict:
    """Customer is entity-backed: pass the actual Customer.id as user_id
    whenever the call is ownership-gated or creates a customer-owned row."""
    return build_user_headers(user_id, "Customer")
