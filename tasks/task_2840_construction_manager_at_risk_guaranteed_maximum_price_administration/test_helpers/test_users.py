"""Operator identities and their request headers.

Every role carries an opaque identity: an operator identifier is never compared
to an entity id, but it *is* recorded on bids, change events and draws so that
later rules can compare two operators against each other. The suite therefore
keeps several distinct operator ids per role.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CONSTRUCTION_MANAGER,
    ROLE_INDEPENDENT_AUDITOR,
    ROLE_OWNER_REPRESENTATIVE,
    ROLE_PROCUREMENT_OFFICER,
    ROLE_PROGRAM_ADMIN,
)

#: Logical operator name -> (X-User-ID, X-User-Role)
TEST_USERS: Dict[str, Dict[str, str]] = {
    "program_admin": {"user_id": "admin-1", "role": ROLE_PROGRAM_ADMIN},
    "cm_estimator": {"user_id": "cm-estimator-1", "role": ROLE_CONSTRUCTION_MANAGER},
    "cm_estimator_2": {"user_id": "cm-estimator-2", "role": ROLE_CONSTRUCTION_MANAGER},
    "cm_pm": {"user_id": "cm-pm-1", "role": ROLE_CONSTRUCTION_MANAGER},
    "cm_pm_2": {"user_id": "cm-pm-2", "role": ROLE_CONSTRUCTION_MANAGER},
    "procurement_officer": {"user_id": "po-1", "role": ROLE_PROCUREMENT_OFFICER},
    "procurement_officer_independent": {
        "user_id": "po-independent",
        "role": ROLE_PROCUREMENT_OFFICER,
    },
    "owner_rep": {"user_id": "owner-1", "role": ROLE_OWNER_REPRESENTATIVE},
    "owner_rep_2": {"user_id": "owner-2", "role": ROLE_OWNER_REPRESENTATIVE},
    "auditor": {"user_id": "auditor-1", "role": ROLE_INDEPENDENT_AUDITOR},
}


def headers_for(role: str, user_id: str) -> Dict[str, str]:
    """Build request headers for an arbitrary operator id acting under ``role``."""
    return build_user_headers(user_id, role)


def headers_of(name: str) -> Dict[str, str]:
    """Build request headers for one of the named operators in ``TEST_USERS``."""
    entry = TEST_USERS[name]
    return build_user_headers(entry["user_id"], entry["role"])


def user_id_of(name: str) -> str:
    """The ``X-User-ID`` string of one of the named operators."""
    return TEST_USERS[name]["user_id"]


# Pre-built header dicts for the common case where the operator identity does
# not matter, only the role does.
ADMIN_HEADERS = headers_of("program_admin")
CM_HEADERS = headers_of("cm_estimator")
CM_PM_HEADERS = headers_of("cm_pm")
CM_PM_2_HEADERS = headers_of("cm_pm_2")
PO_HEADERS = headers_of("procurement_officer")
PO_INDEPENDENT_HEADERS = headers_of("procurement_officer_independent")
OWNER_HEADERS = headers_of("owner_rep")
OWNER_2_HEADERS = headers_of("owner_rep_2")
AUDITOR_HEADERS = headers_of("auditor")

#: Headers carrying no identity at all, for the unauthenticated check.
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
