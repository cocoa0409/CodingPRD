"""Header builders for the five roles of the presort bureau API.

Every request carries ``X-User-ID`` and ``X-User-Role``.

``ClientContact`` is the one role whose identity is entity-backed: its
``X-User-ID`` is the ``id`` of the acting ``Client``, and ownership checks
compare a resource's client foreign key to it. Because a client's id is only
known at runtime, that role gets a per-instance builder rather than a constant.

The other four roles carry opaque operator identifiers that the server records
for audit but never compares to an entity id. They get named constants — and
several distinct constants per role, because the segregation-of-duties rule
compares two operator identifiers to each other, so a filer and a verifier must
never share one.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from test_helpers.constants import (
    ROLE_ACCEPTANCE_CLERK,
    ROLE_BUREAU_ADMIN,
    ROLE_CLIENT_CONTACT,
    ROLE_POSTAGE_MANAGER,
    ROLE_PRESORT_OPERATOR,
)

# ─── Opaque operator identifiers ──────────────────────────────────────────

BUREAU_ADMIN_USER_ID = "admin-001"
PRESORT_OPERATOR_USER_ID = "op-001"
PRESORT_OPERATOR_2_USER_ID = "op-002"
POSTAGE_MANAGER_USER_ID = "pm-001"
POSTAGE_MANAGER_2_USER_ID = "pm-002"
ACCEPTANCE_CLERK_USER_ID = "clerk-007"
ACCEPTANCE_CLERK_2_USER_ID = "clerk-008"


# ─── Per-instance builder for the entity-backed role ──────────────────────


def make_client_contact_headers(client_id: str) -> Dict[str, str]:
    """Headers for a ``ClientContact`` acting as the client with this id."""
    return build_user_headers(client_id, ROLE_CLIENT_CONTACT)


# ─── Builders for the opaque operator roles ───────────────────────────────


def make_bureau_admin_headers(user_id: str = BUREAU_ADMIN_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_BUREAU_ADMIN)


def make_presort_operator_headers(
    user_id: str = PRESORT_OPERATOR_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PRESORT_OPERATOR)


def make_postage_manager_headers(
    user_id: str = POSTAGE_MANAGER_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_POSTAGE_MANAGER)


def make_acceptance_clerk_headers(
    user_id: str = ACCEPTANCE_CLERK_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_ACCEPTANCE_CLERK)


# ─── Shared constants for role-only tests ─────────────────────────────────

BUREAU_ADMIN = make_bureau_admin_headers()
PRESORT_OPERATOR = make_presort_operator_headers()
PRESORT_OPERATOR_2 = make_presort_operator_headers(PRESORT_OPERATOR_2_USER_ID)
POSTAGE_MANAGER = make_postage_manager_headers()
POSTAGE_MANAGER_2 = make_postage_manager_headers(POSTAGE_MANAGER_2_USER_ID)
ACCEPTANCE_CLERK = make_acceptance_clerk_headers()
ACCEPTANCE_CLERK_2 = make_acceptance_clerk_headers(ACCEPTANCE_CLERK_2_USER_ID)

TEST_USERS = {
    ROLE_BUREAU_ADMIN: BUREAU_ADMIN,
    ROLE_PRESORT_OPERATOR: PRESORT_OPERATOR,
    ROLE_POSTAGE_MANAGER: POSTAGE_MANAGER,
    ROLE_ACCEPTANCE_CLERK: ACCEPTANCE_CLERK,
}

OPERATOR_ROLE_HEADERS = dict(TEST_USERS)


# ─── Malformed identity headers ───────────────────────────────────────────
#
# A header that is absent, empty, or whitespace-only is treated as absent. An
# empty string is sent as an empty string — never as a run of spaces, which some
# HTTP clients refuse to transmit at all — while the whitespace-only cases use
# genuine space and tab characters because the contract names them explicitly.


def headers_missing_user_id(role: str) -> Dict[str, str]:
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id: str = BUREAU_ADMIN_USER_ID) -> Dict[str, str]:
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_empty_user_id(role: str) -> Dict[str, str]:
    return {
        "X-User-ID": "",
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


def headers_empty_role(user_id: str = BUREAU_ADMIN_USER_ID) -> Dict[str, str]:
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def headers_whitespace_user_id(role: str) -> Dict[str, str]:
    return {
        "X-User-ID": "   ",
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


def headers_whitespace_role(user_id: str = BUREAU_ADMIN_USER_ID) -> Dict[str, str]:
    return {
        "X-User-ID": user_id,
        "X-User-Role": "\t",
        "Content-Type": "application/json",
    }


def headers_unknown_role(user_id: str = BUREAU_ADMIN_USER_ID) -> Dict[str, str]:
    """A syntactically valid header holding a string outside the five roles."""
    return build_user_headers(user_id, "MailroomIntern")


NO_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
