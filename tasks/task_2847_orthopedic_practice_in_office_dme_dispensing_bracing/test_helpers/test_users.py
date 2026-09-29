"""Acting users and their request headers.

Four of the six roles are opaque to the server: any non-empty `X-User-Id` is
accepted, so a shared constant is enough. The two clinical roles are not: an
`OrthoPhysician` acts as a real `Physician` row and a `DmeFitter` acts as a
real `Fitter` row, and the server resolves the clinic, the credential and the
privilege scope from that row. Tests therefore build those two headers from
the id the fixture actually created, never from a shared placeholder.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_DME_FITTER,
    ROLE_INSURANCE_COORDINATOR,
    ROLE_INVENTORY_MANAGER,
    ROLE_ORTHO_PHYSICIAN,
    ROLE_PRACTICE_ADMIN,
)

# Stable acting ids for the four opaque roles, plus placeholders for the two
# entity-backed roles that only unknown-actor tests should use directly.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "practice_admin": {
        "user_id": "11111111-1111-4111-8111-111111111111",
        "role": ROLE_PRACTICE_ADMIN,
    },
    "compliance_officer": {
        "user_id": "22222222-2222-4222-8222-222222222222",
        "role": ROLE_COMPLIANCE_OFFICER,
    },
    "inventory_manager": {
        "user_id": "33333333-3333-4333-8333-333333333333",
        "role": ROLE_INVENTORY_MANAGER,
    },
    "insurance_coordinator": {
        "user_id": "44444444-4444-4444-8444-444444444444",
        "role": ROLE_INSURANCE_COORDINATOR,
    },
    "ortho_physician": {
        "user_id": "55555555-5555-4555-8555-555555555555",
        "role": ROLE_ORTHO_PHYSICIAN,
    },
    "dme_fitter": {
        "user_id": "66666666-6666-4666-8666-666666666666",
        "role": ROLE_DME_FITTER,
    },
}


def headers_for(user_key: str) -> Dict[str, str]:
    """Headers for one of the named acting users."""
    user = TEST_USERS[user_key]
    return build_user_headers(user["user_id"], user["role"])


# -- the four opaque roles ---------------------------------------------------
def practice_admin_headers() -> Dict[str, str]:
    return headers_for("practice_admin")


def compliance_officer_headers() -> Dict[str, str]:
    return headers_for("compliance_officer")


def inventory_manager_headers() -> Dict[str, str]:
    return headers_for("inventory_manager")


def insurance_coordinator_headers() -> Dict[str, str]:
    return headers_for("insurance_coordinator")


# -- per-instance builders for the two entity-backed roles -------------------
def make_ortho_physician_headers(physician_id: str) -> Dict[str, str]:
    """Headers for the physician row identified by `physician_id`."""
    return build_user_headers(physician_id, ROLE_ORTHO_PHYSICIAN)


def make_dme_fitter_headers(fitter_id: str) -> Dict[str, str]:
    """Headers for the fitter row identified by `fitter_id`."""
    return build_user_headers(fitter_id, ROLE_DME_FITTER)


def make_practice_admin_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PRACTICE_ADMIN)


def make_compliance_officer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def make_inventory_manager_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_INVENTORY_MANAGER)


def make_insurance_coordinator_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_INSURANCE_COORDINATOR)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary role / acting id pair."""
    return build_user_headers(user_id, role)


# -- malformed header families ----------------------------------------------
def headers_without_user_id() -> Dict[str, str]:
    return {"X-User-Role": ROLE_PRACTICE_ADMIN, "Content-Type": "application/json"}


def headers_without_role() -> Dict[str, str]:
    return {
        "X-User-Id": TEST_USERS["practice_admin"]["user_id"],
        "Content-Type": "application/json",
    }


def headers_with_empty_user_id() -> Dict[str, str]:
    return {
        "X-User-Id": "",
        "X-User-Role": ROLE_PRACTICE_ADMIN,
        "Content-Type": "application/json",
    }


def headers_with_empty_role() -> Dict[str, str]:
    return {
        "X-User-Id": TEST_USERS["practice_admin"]["user_id"],
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def headers_with_unknown_role() -> Dict[str, str]:
    return build_user_headers(TEST_USERS["practice_admin"]["user_id"], "BillingClerk")
