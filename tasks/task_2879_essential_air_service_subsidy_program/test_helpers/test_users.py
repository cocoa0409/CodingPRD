"""Identity headers for every role.

Operator roles (ProgramAdmin, EligibilityAnalyst, SelectionOfficer) carry an
opaque X-User-ID that is never compared to a row id, so they can be fixed
constants. The two entity-backed roles must carry the id of the acting row:
CommunityRepresentative carries the Community id and Carrier carries the
Carrier id. Those two therefore have per-instance builders and no shared
constant — a shared one would fail every ownership-gated call.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CARRIER,
    ROLE_COMMUNITY_REPRESENTATIVE,
    ROLE_ELIGIBILITY_ANALYST,
    ROLE_PROGRAM_ADMIN,
    ROLE_SELECTION_OFFICER,
)

# ─── Operator identifiers ────────────────────────────────────────────

USER_ADMIN = "admin-1"
USER_ADMIN_SECOND = "admin-2"
USER_ADMIN_REVIEWER = "admin-reviewer"
USER_ADMIN_APPROVER = "admin-approver"
USER_ADMIN_DISBURSER = "admin-disburser"
USER_ADMIN_NEGOTIATOR = "admin-negotiator"

USER_ANALYST = "analyst-1"
USER_ANALYST_SECOND = "analyst-2"

USER_OFFICER = "officer-1"
USER_OFFICER_SECOND = "officer-2"

# ─── Operator header sets ────────────────────────────────────────────

ADMIN = build_user_headers(USER_ADMIN, ROLE_PROGRAM_ADMIN)
ADMIN_SECOND = build_user_headers(USER_ADMIN_SECOND, ROLE_PROGRAM_ADMIN)
ADMIN_REVIEWER = build_user_headers(USER_ADMIN_REVIEWER, ROLE_PROGRAM_ADMIN)
ADMIN_APPROVER = build_user_headers(USER_ADMIN_APPROVER, ROLE_PROGRAM_ADMIN)
ADMIN_DISBURSER = build_user_headers(USER_ADMIN_DISBURSER, ROLE_PROGRAM_ADMIN)
ADMIN_NEGOTIATOR = build_user_headers(USER_ADMIN_NEGOTIATOR, ROLE_PROGRAM_ADMIN)

ANALYST = build_user_headers(USER_ANALYST, ROLE_ELIGIBILITY_ANALYST)
ANALYST_SECOND = build_user_headers(USER_ANALYST_SECOND, ROLE_ELIGIBILITY_ANALYST)

OFFICER = build_user_headers(USER_OFFICER, ROLE_SELECTION_OFFICER)
OFFICER_SECOND = build_user_headers(USER_OFFICER_SECOND, ROLE_SELECTION_OFFICER)


# ─── Entity-backed identity builders ─────────────────────────────────

def make_community_rep_headers(community_id: str) -> Dict[str, str]:
    """Headers for the representative of one specific community.

    X-User-ID is the id of the acting Community, which is what every
    community-ownership check compares against.
    """
    return build_user_headers(community_id, ROLE_COMMUNITY_REPRESENTATIVE)


def make_carrier_headers(carrier_id: str) -> Dict[str, str]:
    """Headers for one specific carrier.

    X-User-ID is the id of the acting Carrier, which is what every
    carrier-ownership check compares against — directly on a proposal, or
    reached through the parent agreement for a period or a renegotiation.
    """
    return build_user_headers(carrier_id, ROLE_CARRIER)


def make_operator_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary operator identifier and role."""
    return build_user_headers(user_id, role)


# ─── Malformed identities (PRD §2.1 authentication rung) ─────────────

def headers_missing_user_id(role: str = ROLE_PROGRAM_ADMIN) -> Dict[str, str]:
    """Well-formed role, X-User-ID header entirely absent."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id: str = USER_ADMIN) -> Dict[str, str]:
    """Well-formed user id, X-User-Role header entirely absent."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_empty_user_id(role: str = ROLE_PROGRAM_ADMIN) -> Dict[str, str]:
    """X-User-ID present but empty. The value is "" — never whitespace."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_empty_role(user_id: str = USER_ADMIN) -> Dict[str, str]:
    """X-User-Role present but empty. The value is "" — never whitespace."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def headers_unknown_role(user_id: str = USER_ADMIN,
                         role: str = "Auditor") -> Dict[str, str]:
    """X-User-Role naming something that is not one of the five roles."""
    return build_user_headers(user_id, role)
