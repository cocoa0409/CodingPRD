"""Caller identities.

The `Developer` role is entity-backed: `X-User-ID` must be the id of a registered
developer, so developer headers are always built from a real created entity via
``make_developer_headers``. Every other role is an opaque operator identity, so those
are fixed module-level constants with distinct ids per operator.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ADMIN_ID,
    ANONYMOUS_ID,
    DEV_REL_MANAGER_ALT_ID,
    DEV_REL_MANAGER_ID,
    SUPPORT_AGENT_ID,
    TRUST_OFFICER_ALT_ID,
    TRUST_OFFICER_ID,
)
from .types import UserRole


# --------------------------------------------------------------- entity-backed role
def make_developer_headers(developer_id: str) -> Dict[str, str]:
    """Headers for the `Developer` role acting as the developer with this id."""
    return build_user_headers(developer_id, UserRole.DEVELOPER.value)


# ------------------------------------------------------------- opaque operator roles
def make_dev_rel_manager_headers(user_id: str = DEV_REL_MANAGER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.DEV_REL_MANAGER.value)


def make_platform_admin_headers(user_id: str = ADMIN_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.PLATFORM_ADMIN.value)


def make_trust_officer_headers(user_id: str = TRUST_OFFICER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.TRUST_AND_SAFETY_OFFICER.value)


def make_support_agent_headers(user_id: str = SUPPORT_AGENT_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.PARTNER_SUPPORT_AGENT.value)


def make_anonymous_headers(user_id: str = ANONYMOUS_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.ANONYMOUS.value)


def make_headers_for_role(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary role string, used by role-matrix tests."""
    return build_user_headers(user_id, role)


PLATFORM_ADMIN = make_platform_admin_headers()
DEV_REL_MANAGER = make_dev_rel_manager_headers()
DEV_REL_MANAGER_ALT = make_dev_rel_manager_headers(DEV_REL_MANAGER_ALT_ID)
TRUST_OFFICER = make_trust_officer_headers()
TRUST_OFFICER_ALT = make_trust_officer_headers(TRUST_OFFICER_ALT_ID)
SUPPORT_AGENT = make_support_agent_headers()
ANONYMOUS = make_anonymous_headers()


# --------------------------------------------------------------- malformed identities
def headers_without_user_id(role: str = UserRole.DEVELOPER.value) -> Dict[str, str]:
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str = ADMIN_ID) -> Dict[str, str]:
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_blank_user_id(role: str = UserRole.DEVELOPER.value) -> Dict[str, str]:
    """`X-User-ID` present but empty. The empty string, never whitespace."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_blank_role(user_id: str = ADMIN_ID) -> Dict[str, str]:
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str = ADMIN_ID, role: str = "SuperAdmin") -> Dict[str, str]:
    return build_user_headers(user_id, role)


NO_HEADERS: Dict[str, str] = {}
