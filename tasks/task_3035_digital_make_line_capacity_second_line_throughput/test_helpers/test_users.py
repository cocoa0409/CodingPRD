"""Caller identities for the five declared roles.

Every request carries an ``X-User-ID`` and an ``X-User-Role`` header. Four roles
are opaque: the acting user's identifier is never matched against a stored row,
so a stable opaque identifier is enough. ``MarketplaceChannel`` is entity-backed:
when that role places a marketplace order, the order's ``marketplace_channel_id``
must equal the caller's ``X-User-ID``, so it gets a per-call builder that takes
the channel identifier the test created.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_GENERAL_MANAGER,
    ROLE_LINE_WORKER,
    ROLE_MARKETPLACE_CHANNEL,
    ROLE_PLATFORM_ADMIN,
    ROLE_STORE_MANAGER,
)

# Opaque identifiers for the roles that are not matched against a stored row.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin": {"id": "admin-1", "role": ROLE_PLATFORM_ADMIN},
    "store_manager": {"id": "sm-1", "role": ROLE_STORE_MANAGER},
    "general_manager": {"id": "gm-1", "role": ROLE_GENERAL_MANAGER},
    "line_worker": {"id": "lw-1", "role": ROLE_LINE_WORKER},
}

# Ready-made header dicts for the opaque roles.
PLATFORM_ADMIN_HEADERS = build_user_headers(
    TEST_USERS["platform_admin"]["id"], ROLE_PLATFORM_ADMIN
)
STORE_MANAGER_HEADERS = build_user_headers(
    TEST_USERS["store_manager"]["id"], ROLE_STORE_MANAGER
)
GENERAL_MANAGER_HEADERS = build_user_headers(
    TEST_USERS["general_manager"]["id"], ROLE_GENERAL_MANAGER
)
LINE_WORKER_HEADERS = build_user_headers(
    TEST_USERS["line_worker"]["id"], ROLE_LINE_WORKER
)


# ── Per-instance builders for the opaque roles ─────────────────────────────
# Segregation-of-duties checks compare X-User-ID between publish and lock, so
# tests that exercise that rule need to pin the identifier explicitly.

def make_platform_admin_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


def make_store_manager_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_STORE_MANAGER)


def make_general_manager_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_GENERAL_MANAGER)


def make_line_worker_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_LINE_WORKER)


# ── Entity-backed role ─────────────────────────────────────────────────────

def make_marketplace_channel_headers(channel_id: str) -> Dict[str, str]:
    """Headers for a MarketplaceChannel acting under its own channel identifier."""
    return build_user_headers(channel_id, ROLE_MARKETPLACE_CHANNEL)


# ── Malformed credentials, for the header-presence tier ────────────────────

def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers that omit X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers that omit X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


# A syntactically valid header value that names no declared role.
UNDECLARED_ROLE = "Cashier"


def headers_with_undeclared_role(user_id: str) -> Dict[str, str]:
    """Headers naming a role the contract does not declare."""
    return build_user_headers(user_id, UNDECLARED_ROLE)
