"""Caller identities for the seven declared roles.

Every request carries an ``X-User-ID`` and an ``X-User-Role`` header. Identity
in this contract is deliberately shallow: for all seven roles the ``X-User-ID``
is an opaque operator identifier that is never compared against any resource's
``id``. What it is compared against is an identifier the server stamped earlier
on the same record, which is how the three segregation-of-duties controls work.

So each role gets a ready-made header dict carrying a stable default operator,
and each role also gets a builder that takes an explicit operator identifier -
because a test that drives a segregation-of-duties rule has to control exactly
which operator performs, results or implements, and which one then validates,
releases or verifies. One human being may legitimately hold two roles, so the
same identifier may appear under two different role headers.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_LINE_OPERATOR,
    ROLE_PLANT_ADMIN,
    ROLE_QA_MANAGER,
    ROLE_QA_TECHNICIAN,
    ROLE_RECEIVING_CLERK,
    ROLE_SANITATION_TECH,
    ROLE_SHIPPING_CLERK,
    UNDECLARED_ROLE,
)

# ── Named operators ────────────────────────────────────────────────────────
# Distinct identifiers so that a test can put the same person, or deliberately
# a different person, on both sides of a segregation-of-duties comparison.

USER_PLANT_ADMIN = "admin-1"
USER_RECEIVING_CLERK = "recv-1"
USER_QA_TECH_A = "qat-1"
USER_QA_TECH_B = "qat-2"
USER_QA_TECH_C = "qat-3"
USER_QA_TECH_D = "qat-4"
USER_QA_TECH_IMPLEMENTER = "qat-7"
USER_QA_MANAGER_A = "qam-1"
USER_QA_MANAGER_B = "qam-3"
USER_QA_MANAGER_C = "qam-2"
USER_LINE_OPERATOR = "lop-1"
USER_SANITATION_TECH_A = "sant-1"
USER_SANITATION_TECH_B = "sant-2"
USER_SHIPPING_CLERK = "ship-1"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "plant_admin": {"id": USER_PLANT_ADMIN, "role": ROLE_PLANT_ADMIN},
    "receiving_clerk": {"id": USER_RECEIVING_CLERK, "role": ROLE_RECEIVING_CLERK},
    "qa_technician": {"id": USER_QA_TECH_A, "role": ROLE_QA_TECHNICIAN},
    "qa_technician_b": {"id": USER_QA_TECH_B, "role": ROLE_QA_TECHNICIAN},
    "qa_manager": {"id": USER_QA_MANAGER_A, "role": ROLE_QA_MANAGER},
    "qa_manager_b": {"id": USER_QA_MANAGER_B, "role": ROLE_QA_MANAGER},
    "qa_manager_c": {"id": USER_QA_MANAGER_C, "role": ROLE_QA_MANAGER},
    "qa_technician_c": {"id": USER_QA_TECH_C, "role": ROLE_QA_TECHNICIAN},
    "qa_technician_d": {"id": USER_QA_TECH_D, "role": ROLE_QA_TECHNICIAN},
    "line_operator": {"id": USER_LINE_OPERATOR, "role": ROLE_LINE_OPERATOR},
    "sanitation_tech": {"id": USER_SANITATION_TECH_A, "role": ROLE_SANITATION_TECH},
    "sanitation_tech_b": {"id": USER_SANITATION_TECH_B, "role": ROLE_SANITATION_TECH},
    "shipping_clerk": {"id": USER_SHIPPING_CLERK, "role": ROLE_SHIPPING_CLERK},
}

# ── Ready-made header dicts, one per role ──────────────────────────────────

PLANT_ADMIN_HEADERS = build_user_headers(USER_PLANT_ADMIN, ROLE_PLANT_ADMIN)
RECEIVING_CLERK_HEADERS = build_user_headers(USER_RECEIVING_CLERK, ROLE_RECEIVING_CLERK)
QA_TECHNICIAN_HEADERS = build_user_headers(USER_QA_TECH_A, ROLE_QA_TECHNICIAN)
QA_MANAGER_HEADERS = build_user_headers(USER_QA_MANAGER_A, ROLE_QA_MANAGER)
LINE_OPERATOR_HEADERS = build_user_headers(USER_LINE_OPERATOR, ROLE_LINE_OPERATOR)
SANITATION_TECH_HEADERS = build_user_headers(USER_SANITATION_TECH_A, ROLE_SANITATION_TECH)
SHIPPING_CLERK_HEADERS = build_user_headers(USER_SHIPPING_CLERK, ROLE_SHIPPING_CLERK)

# Every role's default headers, keyed by the role name the contract declares.
HEADERS_BY_ROLE: Dict[str, Dict[str, str]] = {
    ROLE_PLANT_ADMIN: PLANT_ADMIN_HEADERS,
    ROLE_RECEIVING_CLERK: RECEIVING_CLERK_HEADERS,
    ROLE_QA_TECHNICIAN: QA_TECHNICIAN_HEADERS,
    ROLE_QA_MANAGER: QA_MANAGER_HEADERS,
    ROLE_LINE_OPERATOR: LINE_OPERATOR_HEADERS,
    ROLE_SANITATION_TECH: SANITATION_TECH_HEADERS,
    ROLE_SHIPPING_CLERK: SHIPPING_CLERK_HEADERS,
}


# ── Per-operator builders, for the segregation-of-duties comparisons ───────

def make_plant_admin_headers(user_id: str) -> Dict[str, str]:
    """Headers for a PlantAdmin acting under this operator identifier."""
    return build_user_headers(user_id, ROLE_PLANT_ADMIN)


def make_receiving_clerk_headers(user_id: str) -> Dict[str, str]:
    """Headers for a ReceivingClerk acting under this operator identifier."""
    return build_user_headers(user_id, ROLE_RECEIVING_CLERK)


def make_qa_technician_headers(user_id: str) -> Dict[str, str]:
    """Headers for a QATechnician acting under this operator identifier."""
    return build_user_headers(user_id, ROLE_QA_TECHNICIAN)


def make_qa_manager_headers(user_id: str) -> Dict[str, str]:
    """Headers for a QAManager acting under this operator identifier."""
    return build_user_headers(user_id, ROLE_QA_MANAGER)


def make_line_operator_headers(user_id: str) -> Dict[str, str]:
    """Headers for a LineOperator acting under this operator identifier."""
    return build_user_headers(user_id, ROLE_LINE_OPERATOR)


def make_sanitation_tech_headers(user_id: str) -> Dict[str, str]:
    """Headers for a SanitationTech acting under this operator identifier."""
    return build_user_headers(user_id, ROLE_SANITATION_TECH)


def make_shipping_clerk_headers(user_id: str) -> Dict[str, str]:
    """Headers for a ShippingClerk acting under this operator identifier."""
    return build_user_headers(user_id, ROLE_SHIPPING_CLERK)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary role and operator pair."""
    return build_user_headers(user_id, role)


# ── Credentials the authentication tier must refuse ────────────────────────
# An empty header value is the empty string. It is never a space, because a
# whitespace-only header value is rejected by the HTTP layer before it can
# reach the server, which would test the client rather than the contract.

def headers_without_role(user_id: str = USER_PLANT_ADMIN) -> Dict[str, str]:
    """Headers that omit X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = ROLE_PLANT_ADMIN) -> Dict[str, str]:
    """Headers that omit X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_role(user_id: str = USER_PLANT_ADMIN) -> Dict[str, str]:
    """Headers whose X-User-Role is present but is the empty string."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str = ROLE_PLANT_ADMIN) -> Dict[str, str]:
    """Headers whose X-User-ID is present but is the empty string."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_undeclared_role(user_id: str = USER_QA_MANAGER_A) -> Dict[str, str]:
    """Headers naming a role string the contract does not declare."""
    return build_user_headers(user_id, UNDECLARED_ROLE)
