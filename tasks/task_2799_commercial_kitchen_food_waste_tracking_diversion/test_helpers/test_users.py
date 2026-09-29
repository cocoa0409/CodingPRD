"""Caller identities and the header builders that thread them onto a request."""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# Opaque identities. The four opaque roles carry an operator identifier that the
# server records but never compares to any entity's id.
TEST_USERS = {
    "kitchen_staff": {"user_id": "ks-1", "role": Role.KITCHEN_STAFF.value},
    "kitchen_staff_alt": {"user_id": "ks-2", "role": Role.KITCHEN_STAFF.value},
    "shift_lead": {"user_id": "sl-1", "role": Role.SHIFT_LEAD.value},
    "shift_lead_alt": {"user_id": "sl-2", "role": Role.SHIFT_LEAD.value},
    "corporate_lead": {"user_id": "csl-1", "role": Role.CORPORATE_SUSTAINABILITY_LEAD.value},
    "corporate_lead_alt": {"user_id": "csl-2", "role": Role.CORPORATE_SUSTAINABILITY_LEAD.value},
    "platform_admin": {"user_id": "pa-1", "role": Role.PLATFORM_ADMIN.value},
}

# An identifier of the right shape that resolves to no Site and no Hauler row.
UNRECOGNIZED_IDENTITY = "00000000-0000-0000-0000-0000000000ff"


def make_kitchen_staff_headers(user_id: str = "ks-1") -> Dict[str, str]:
    return build_user_headers(user_id, Role.KITCHEN_STAFF.value)


def make_shift_lead_headers(user_id: str = "sl-1") -> Dict[str, str]:
    return build_user_headers(user_id, Role.SHIFT_LEAD.value)


def make_site_sustainability_manager_headers(site_id: str) -> Dict[str, str]:
    """``X-User-ID`` is the id of the acting Site for a SiteSustainabilityManager."""
    return build_user_headers(site_id, Role.SITE_SUSTAINABILITY_MANAGER.value)


def make_hauler_operator_headers(hauler_id: str) -> Dict[str, str]:
    """``X-User-ID`` is the id of the acting Hauler for a HaulerOperator."""
    return build_user_headers(hauler_id, Role.HAULER_OPERATOR.value)


def make_corporate_lead_headers(user_id: str = "csl-1") -> Dict[str, str]:
    return build_user_headers(user_id, Role.CORPORATE_SUSTAINABILITY_LEAD.value)


def make_platform_admin_headers(user_id: str = "pa-1") -> Dict[str, str]:
    return build_user_headers(user_id, Role.PLATFORM_ADMIN.value)


def make_headers_without_role(user_id: str = "ks-1") -> Dict[str, str]:
    """Headers carrying an identity but no ``X-User-Role`` at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def make_headers_without_identity(role: str = Role.KITCHEN_STAFF.value) -> Dict[str, str]:
    """Headers naming a role but carrying no ``X-User-ID``."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def make_headers_with_unknown_role(role: str = "SousChef") -> Dict[str, str]:
    """Headers naming a role that is not one of the six declared roles."""
    return build_user_headers("who-1", role)


def no_identity_headers() -> Dict[str, str]:
    """The logical-clock setter is open to any caller and needs no identity headers."""
    return {"Content-Type": "application/json"}
