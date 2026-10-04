"""Caller identities for the seven declared roles (PRD §2.1).

Every request carries an ``X-User-ID`` and an ``X-User-Role`` header. Six
roles are opaque: their ``X-User-ID`` is never compared against any persisted
entity, so a stable identifier is enough. ``DistrictManager`` is the exception
- it acts for exactly one district, and ownership checks compare the
resource's district foreign key to ``X-User-ID`` - so a DistrictManager must
present the ``id`` of a real District row. That role therefore gets a
per-instance builder that takes the district identifier the test created;
falling back to the shared placeholder below for an ownership-gated call
(delivery-order creation, transfer propose/resubmit, impact-review filing,
agreement ratification) would fail every ownership check, because the
placeholder id never equals any district's id.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_DISTRICT_MANAGER,
    ROLE_ENVIRONMENTAL_OFFICER,
    ROLE_FINANCE_OFFICER,
    ROLE_HYDROLOGY_OFFICER,
    ROLE_RECLAMATION_OPERATOR,
    ROLE_REGIONAL_DIRECTOR,
    ROLE_SYSTEM_ADMIN,
)

# Opaque identifiers for the roles that are not matched against a District row,
# plus a placeholder for DistrictManager usable only where ownership is never
# exercised (malformed-payload and missing-resource rejections).
TEST_USERS: Dict[str, Dict[str, str]] = {
    "system_admin": {"id": "11111111-1111-4111-8111-111111111111", "role": ROLE_SYSTEM_ADMIN},
    "reclamation_operator": {"id": "22222222-2222-4222-8222-222222222222", "role": ROLE_RECLAMATION_OPERATOR},
    "hydrology_officer": {"id": "33333333-3333-4333-8333-333333333333", "role": ROLE_HYDROLOGY_OFFICER},
    "district_manager": {"id": "44444444-4444-4444-8444-444444444444", "role": ROLE_DISTRICT_MANAGER},
    "environmental_officer": {"id": "55555555-5555-4555-8555-555555555555", "role": ROLE_ENVIRONMENTAL_OFFICER},
    "finance_officer": {"id": "66666666-6666-4666-8666-666666666666", "role": ROLE_FINANCE_OFFICER},
    "regional_director": {"id": "77777777-7777-4777-8777-777777777777", "role": ROLE_REGIONAL_DIRECTOR},
}

# Ready-made header dicts for the opaque roles.
SYSTEM_ADMIN_HEADERS = build_user_headers(TEST_USERS["system_admin"]["id"], ROLE_SYSTEM_ADMIN)
RECLAMATION_OPERATOR_HEADERS = build_user_headers(
    TEST_USERS["reclamation_operator"]["id"], ROLE_RECLAMATION_OPERATOR
)
HYDROLOGY_OFFICER_HEADERS = build_user_headers(
    TEST_USERS["hydrology_officer"]["id"], ROLE_HYDROLOGY_OFFICER
)
ENVIRONMENTAL_OFFICER_HEADERS = build_user_headers(
    TEST_USERS["environmental_officer"]["id"], ROLE_ENVIRONMENTAL_OFFICER
)
FINANCE_OFFICER_HEADERS = build_user_headers(TEST_USERS["finance_officer"]["id"], ROLE_FINANCE_OFFICER)
REGIONAL_DIRECTOR_HEADERS = build_user_headers(
    TEST_USERS["regional_director"]["id"], ROLE_REGIONAL_DIRECTOR
)


# ── Entity-backed role ─────────────────────────────────────────────────────

def make_district_manager_headers(district_id: str) -> Dict[str, str]:
    """Headers for the DistrictManager of the district with this identifier.

    Pass the actual District ``id`` whenever the call is ownership-gated
    (delivery-order creation, transfer propose/resubmit, impact-review
    filing, shortage-agreement ratification): the server compares
    ``X-User-ID`` against the resource's district foreign key.
    """
    return build_user_headers(district_id, ROLE_DISTRICT_MANAGER)


# ── Malformed credentials, for the authentication tier (PRD §2.9 step 1) ───

def headers_without_role(user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers that omit X-User-Role entirely."""
    return {"X-User-ID": user_id or TEST_USERS["system_admin"]["id"], "Content-Type": "application/json"}


def headers_without_user_id(role: str = ROLE_SYSTEM_ADMIN) -> Dict[str, str]:
    """Headers that omit X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


# A syntactically valid header value that names none of the seven declared roles.
UNDECLARED_ROLE = "FieldInspector"


def headers_with_undeclared_role(user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers naming a role the contract does not declare."""
    return build_user_headers(user_id or TEST_USERS["system_admin"]["id"], UNDECLARED_ROLE)
