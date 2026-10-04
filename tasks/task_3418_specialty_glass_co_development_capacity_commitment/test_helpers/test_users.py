"""Pre-built role headers for the six declared roles.

Five roles are opaque: the server never compares their ``X-User-ID`` to any
entity's ``id``, so a stable per-role identifier is enough. ``DeviceMaker`` is
entity-backed: ownership checks compare ``X-User-ID`` against the maker
entity's ``id``, so any ownership-gated call must use
``make_device_maker_headers(maker["id"])`` with the real entity id. Falling
back to a shared constant for that role fails every ownership check.

Segregation of duties on prepayment confirmation compares the caller's
``X-User-ID`` to the recorded ``countersigned_by``; tests therefore need
distinct planner and controller identifiers, which the per-role builders
provide.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CAPACITY_PLANNER,
    ROLE_DEVICE_MAKER,
    ROLE_FINANCE_CONTROLLER,
    ROLE_LEGAL_COUNSEL,
    ROLE_PLATFORM_ADMIN,
    ROLE_PROGRAM_MANAGER,
)

# Shared header sets for the five opaque roles. Safe for any call whose
# outcome does not depend on the caller owning a specific resource.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin_headers": build_user_headers(
        "11111111-1111-4111-8111-111111111111", ROLE_PLATFORM_ADMIN
    ),
    "program_manager_headers": build_user_headers(
        "22222222-2222-4222-8222-222222222222", ROLE_PROGRAM_MANAGER
    ),
    "capacity_planner_headers": build_user_headers(
        "33333333-3333-4333-8333-333333333333", ROLE_CAPACITY_PLANNER
    ),
    "finance_controller_headers": build_user_headers(
        "44444444-4444-4444-8444-444444444444", ROLE_FINANCE_CONTROLLER
    ),
    "legal_counsel_headers": build_user_headers(
        "55555555-5555-4555-8555-555555555555", ROLE_LEGAL_COUNSEL
    ),
    # Fallback for calls that are not ownership-gated (e.g. role/404 checks).
    # Never use for signing, testing, marketing submission, or usage reports.
    "device_maker_headers": build_user_headers(
        "66666666-6666-4666-8666-666666666666", ROLE_DEVICE_MAKER
    ),
}


# ── Per-instance builders ────────────────────────────────────────────────────

def make_platform_admin_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


def make_program_manager_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PROGRAM_MANAGER)


def make_capacity_planner_headers(user_id: str) -> Dict[str, str]:
    """Distinct planner ids keep countersignature actors apart across duties."""
    return build_user_headers(user_id, ROLE_CAPACITY_PLANNER)


def make_finance_controller_headers(user_id: str) -> Dict[str, str]:
    """A controller id distinct from the countersigner's passes segregation."""
    return build_user_headers(user_id, ROLE_FINANCE_CONTROLLER)


def make_legal_counsel_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_LEGAL_COUNSEL)


def make_device_maker_headers(device_maker_id: str) -> Dict[str, str]:
    """Headers for the entity-backed DeviceMaker role.

    Pass the acting maker entity's ``id`` — ownership checks compare
    ``X-User-ID`` to the resource's owning maker id.
    """
    return build_user_headers(device_maker_id, ROLE_DEVICE_MAKER)


# ── Malformed credentials for the authentication tier ────────────────────────

def headers_without_role(user_id: str) -> Dict[str, str]:
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str) -> Dict[str, str]:
    return {"X-User-Role": role, "Content-Type": "application/json"}


UNDECLARED_ROLE = "ShiftSupervisor"


def headers_with_undeclared_role(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, UNDECLARED_ROLE)
