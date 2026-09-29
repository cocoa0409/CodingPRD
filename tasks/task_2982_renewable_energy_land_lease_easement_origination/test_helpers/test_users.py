"""
Acting principals for the Renewable Land Origination API.

Four of the five roles carry opaque identity, so their X-User-ID values are
stable operator literals. Two distinct TitleCounsel identifiers and two distinct
PortfolioManager identifiers exist because the PRD's two four-eyes rules require
the resolver of a curative item to differ from its raiser, and the principal who
exercises an option to differ from the one who executed it.

The Landowner role is entity-backed: its X-User-ID is the id of the acting
Landowner row, so its headers can only be built once that row exists.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_LAND_AGENT,
    ROLE_LANDOWNER,
    ROLE_PAYMENT_ADMINISTRATOR,
    ROLE_PORTFOLIO_MANAGER,
    ROLE_TITLE_COUNSEL,
    UNDECLARED_ROLE,
)

# ─── Opaque operator identifiers ──────────────────────

LAND_AGENT_USER_ID = "la-user-01"
LAND_AGENT_USER_ID_2 = "la-user-02"
TITLE_COUNSEL_USER_ID = "tc-user-01"
TITLE_COUNSEL_USER_ID_2 = "tc-user-02"
PORTFOLIO_MANAGER_USER_ID = "pm-user-01"
PORTFOLIO_MANAGER_USER_ID_2 = "pm-user-02"
PAYMENT_ADMIN_USER_ID = "pa-user-01"

# ─── Ready-made header sets ───────────────────────────

LAND_AGENT = build_user_headers(LAND_AGENT_USER_ID, ROLE_LAND_AGENT)
LAND_AGENT_2 = build_user_headers(LAND_AGENT_USER_ID_2, ROLE_LAND_AGENT)
TITLE_COUNSEL = build_user_headers(TITLE_COUNSEL_USER_ID, ROLE_TITLE_COUNSEL)
TITLE_COUNSEL_2 = build_user_headers(TITLE_COUNSEL_USER_ID_2, ROLE_TITLE_COUNSEL)
PORTFOLIO_MANAGER = build_user_headers(
    PORTFOLIO_MANAGER_USER_ID, ROLE_PORTFOLIO_MANAGER
)
PORTFOLIO_MANAGER_2 = build_user_headers(
    PORTFOLIO_MANAGER_USER_ID_2, ROLE_PORTFOLIO_MANAGER
)
PAYMENT_ADMIN = build_user_headers(PAYMENT_ADMIN_USER_ID, ROLE_PAYMENT_ADMINISTRATOR)


def make_landowner_headers(landowner_id: str) -> Dict[str, str]:
    """
    Headers for the entity-backed Landowner role.

    The PRD is explicit that "when X-User-Role is Landowner, X-User-ID is the id
    of the acting Landowner row", so the real row id must be threaded through
    rather than any shared constant.
    """
    return build_user_headers(landowner_id, ROLE_LANDOWNER)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary identifier/role pair."""
    return build_user_headers(user_id, role)


# ─── Malformed authentication ─────────────────────────

def headers_without_user_id(role: str = ROLE_LAND_AGENT) -> Dict[str, str]:
    """Headers carrying X-User-Role but no X-User-ID at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str = LAND_AGENT_USER_ID) -> Dict[str, str]:
    """Headers carrying X-User-ID but no X-User-Role at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str = ROLE_LAND_AGENT) -> Dict[str, str]:
    """
    Headers whose X-User-ID is present but empty.

    The value is the empty string exactly — never whitespace, which a transport
    layer would reject as a malformed header before the server saw it.
    """
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_role(user_id: str = LAND_AGENT_USER_ID) -> Dict[str, str]:
    """Headers whose X-User-Role is present but empty."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


UNDECLARED_ROLE_HEADERS = build_user_headers("aud-user-01", UNDECLARED_ROLE)
