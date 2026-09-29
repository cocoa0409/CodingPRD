"""
Acting identities for the design-firm project accounting API.

PRD §2.1 splits identity in two. Four of the five roles — FirmAdmin, Controller,
ProjectManager and ProjectAccountant — carry an **opaque** X-User-ID that is
never resolved as a foreign key, so their identifiers are just strings chosen
here. ClientContact is the one **entity-backed** identity: its X-User-ID must be
the ``id`` of the acting Client, which is only known at run time, so it has a
builder rather than a constant.

Distinct identifiers per role matter because three separate gates compare them:
project-manager ownership (against the project's ``project_manager_user_id``),
segregation of duties (the approver must differ from the preparer) and the
write-off approval level. Every fixture that needs two different operators of
the same role has a pair available here.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CLIENT_CONTACT,
    ROLE_CONTROLLER,
    ROLE_FIRM_ADMIN,
    ROLE_PROJECT_ACCOUNTANT,
    ROLE_PROJECT_MANAGER,
    UNRECOGNISED_ROLE,
)

# ─── Opaque operator identifiers ──────────────────────────────────────

FIRM_ADMIN_USER_ID = "admin-001"
CONTROLLER_USER_ID = "ctl-001"
CONTROLLER_ALT_USER_ID = "ctl-002"
CONTROLLER_PREPARER_USER_ID = "ctl-prep"
CONTROLLER_CERTIFIER_USER_ID = "ctl-cert"
PROJECT_MANAGER_USER_ID = "pm-001"
PROJECT_MANAGER_ALT_USER_ID = "pm-002"
ACCOUNTANT_USER_ID = "acct-001"
ACCOUNTANT_ALT_USER_ID = "acct-002"

# ─── Ready-made header dicts ──────────────────────────────────────────

FIRM_ADMIN = build_user_headers(FIRM_ADMIN_USER_ID, ROLE_FIRM_ADMIN)
CONTROLLER = build_user_headers(CONTROLLER_USER_ID, ROLE_CONTROLLER)
CONTROLLER_ALT = build_user_headers(CONTROLLER_ALT_USER_ID, ROLE_CONTROLLER)
CONTROLLER_PREPARER = build_user_headers(CONTROLLER_PREPARER_USER_ID, ROLE_CONTROLLER)
CONTROLLER_CERTIFIER = build_user_headers(CONTROLLER_CERTIFIER_USER_ID, ROLE_CONTROLLER)
PROJECT_MANAGER = build_user_headers(PROJECT_MANAGER_USER_ID, ROLE_PROJECT_MANAGER)
PROJECT_MANAGER_ALT = build_user_headers(
    PROJECT_MANAGER_ALT_USER_ID, ROLE_PROJECT_MANAGER
)
ACCOUNTANT = build_user_headers(ACCOUNTANT_USER_ID, ROLE_PROJECT_ACCOUNTANT)
ACCOUNTANT_ALT = build_user_headers(ACCOUNTANT_ALT_USER_ID, ROLE_PROJECT_ACCOUNTANT)

# Every firm-side role, for RBAC sweeps over an operation's admitted set.
FIRM_SIDE_HEADERS: Dict[str, Dict[str, str]] = {
    ROLE_FIRM_ADMIN: FIRM_ADMIN,
    ROLE_CONTROLLER: CONTROLLER,
    ROLE_PROJECT_MANAGER: PROJECT_MANAGER,
    ROLE_PROJECT_ACCOUNTANT: ACCOUNTANT,
}


def make_client_contact_headers(client_id: str) -> Dict[str, str]:
    """
    Headers for the entity-backed ClientContact identity of PRD §2.1: the
    acting X-User-ID is the ``id`` of the Client the contact speaks for.
    """
    return build_user_headers(client_id, ROLE_CLIENT_CONTACT)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary acting identity, for ownership and segregation-of-duties probes."""
    return build_user_headers(user_id, role)


def unrecognised_role_headers(user_id: str = FIRM_ADMIN_USER_ID) -> Dict[str, str]:
    """Headers declaring a role that is not one of the five recognised roles."""
    return build_user_headers(user_id, UNRECOGNISED_ROLE)


def headers_without_user_id(role: str = ROLE_CONTROLLER) -> Dict[str, str]:
    """Headers carrying X-User-Role but no X-User-ID at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str = CONTROLLER_USER_ID) -> Dict[str, str]:
    """Headers carrying X-User-ID but no X-User-Role at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str = ROLE_CONTROLLER) -> Dict[str, str]:
    """Headers whose X-User-ID is present but empty."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_role(user_id: str = CONTROLLER_USER_ID) -> Dict[str, str]:
    """Headers whose X-User-Role is present but empty."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}
