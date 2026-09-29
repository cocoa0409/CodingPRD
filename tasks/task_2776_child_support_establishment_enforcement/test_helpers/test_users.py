"""
Caller identities for the Child Support Enforcement API test suite.

Five of the eight roles carry an opaque identity: for those the ``X-User-ID``
is an operator identifier not tied to any persisted entity, so a shared
constant header dict is enough. The remaining three are backed by a persisted
entity — a ``CustodialParty`` and a ``NoncustodialParty`` caller present the
``id`` of the acting participant, and an ``EmployerAgent`` caller presents the
``id`` of the acting employer — so those callers get per-instance builders that
must be threaded with a real entity identifier.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CASE_WORKER,
    ROLE_CUSTODIAL_PARTY,
    ROLE_EMPLOYER_AGENT,
    ROLE_FINANCE_OFFICER,
    ROLE_INTERSTATE_LIAISON,
    ROLE_NONCUSTODIAL_PARTY,
    ROLE_PROGRAM_ADMIN,
    ROLE_SUPERVISING_ATTORNEY,
)

# ---------------------------------------------------------------------------
# Opaque operator identifiers
# ---------------------------------------------------------------------------

CASE_WORKER_USER_ID = "user-caseworker-001"
SUPERVISING_ATTORNEY_USER_ID = "user-attorney-001"
FINANCE_OFFICER_USER_ID = "user-finance-001"
INTERSTATE_LIAISON_USER_ID = "user-liaison-001"
PROGRAM_ADMIN_USER_ID = "user-admin-001"

#: Second and third distinct operators, for the segregation-of-duties rule.
SECOND_CASE_WORKER_USER_ID = "user-caseworker-002"
SECOND_SUPERVISING_ATTORNEY_USER_ID = "user-attorney-002"
THIRD_SUPERVISING_ATTORNEY_USER_ID = "user-attorney-003"

# ---------------------------------------------------------------------------
# Shared headers for the five opaque roles
# ---------------------------------------------------------------------------

CASE_WORKER_HEADERS = build_user_headers(CASE_WORKER_USER_ID, ROLE_CASE_WORKER)
SUPERVISING_ATTORNEY_HEADERS = build_user_headers(
    SUPERVISING_ATTORNEY_USER_ID, ROLE_SUPERVISING_ATTORNEY
)
FINANCE_OFFICER_HEADERS = build_user_headers(FINANCE_OFFICER_USER_ID, ROLE_FINANCE_OFFICER)
INTERSTATE_LIAISON_HEADERS = build_user_headers(
    INTERSTATE_LIAISON_USER_ID, ROLE_INTERSTATE_LIAISON
)
PROGRAM_ADMIN_HEADERS = build_user_headers(PROGRAM_ADMIN_USER_ID, ROLE_PROGRAM_ADMIN)

SECOND_CASE_WORKER_HEADERS = build_user_headers(
    SECOND_CASE_WORKER_USER_ID, ROLE_CASE_WORKER
)
SECOND_SUPERVISING_ATTORNEY_HEADERS = build_user_headers(
    SECOND_SUPERVISING_ATTORNEY_USER_ID, ROLE_SUPERVISING_ATTORNEY
)
THIRD_SUPERVISING_ATTORNEY_HEADERS = build_user_headers(
    THIRD_SUPERVISING_ATTORNEY_USER_ID, ROLE_SUPERVISING_ATTORNEY
)

TEST_USERS: Dict[str, Dict[str, str]] = {
    ROLE_CASE_WORKER: CASE_WORKER_HEADERS,
    ROLE_SUPERVISING_ATTORNEY: SUPERVISING_ATTORNEY_HEADERS,
    ROLE_FINANCE_OFFICER: FINANCE_OFFICER_HEADERS,
    ROLE_INTERSTATE_LIAISON: INTERSTATE_LIAISON_HEADERS,
    ROLE_PROGRAM_ADMIN: PROGRAM_ADMIN_HEADERS,
}

# ---------------------------------------------------------------------------
# Per-instance builders for the three entity-backed roles
# ---------------------------------------------------------------------------


def make_case_worker_headers(user_id: str) -> Dict[str, str]:
    """Headers for a specific `CaseWorker` operator identifier."""
    return build_user_headers(user_id, ROLE_CASE_WORKER)


def make_supervising_attorney_headers(user_id: str) -> Dict[str, str]:
    """Headers for a specific `SupervisingAttorney` operator identifier."""
    return build_user_headers(user_id, ROLE_SUPERVISING_ATTORNEY)


def make_finance_officer_headers(user_id: str) -> Dict[str, str]:
    """Headers for a specific `FinanceOfficer` operator identifier."""
    return build_user_headers(user_id, ROLE_FINANCE_OFFICER)


def make_interstate_liaison_headers(user_id: str) -> Dict[str, str]:
    """Headers for a specific `InterstateLiaison` operator identifier."""
    return build_user_headers(user_id, ROLE_INTERSTATE_LIAISON)


def make_program_admin_headers(user_id: str) -> Dict[str, str]:
    """Headers for a specific `ProgramAdmin` operator identifier."""
    return build_user_headers(user_id, ROLE_PROGRAM_ADMIN)


def make_custodial_party_headers(participant_id: str) -> Dict[str, str]:
    """
    Headers for a `CustodialParty` caller.

    ``participant_id`` must be the ``id`` of the acting custodial `Participant`;
    ownership checks compare it to the target case's ``custodial_party_id``.
    """
    return build_user_headers(participant_id, ROLE_CUSTODIAL_PARTY)


def make_noncustodial_party_headers(participant_id: str) -> Dict[str, str]:
    """
    Headers for a `NoncustodialParty` caller.

    ``participant_id`` must be the ``id`` of the acting noncustodial
    `Participant`; every read and write is gated on it equalling the target
    case's ``noncustodial_party_id``.
    """
    return build_user_headers(participant_id, ROLE_NONCUSTODIAL_PARTY)


def make_employer_agent_headers(employer_id: str) -> Dict[str, str]:
    """
    Headers for an `EmployerAgent` caller.

    ``employer_id`` must be the ``id`` of the acting `Employer`; remittances and
    withholding-order reads are scoped to rows whose ``employer_id`` matches.
    """
    return build_user_headers(employer_id, ROLE_EMPLOYER_AGENT)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary user identifier and role string."""
    return build_user_headers(user_id, role)


#: Headers carrying no authentication at all.
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers that name a role but omit ``X-User-ID`` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers that name a user but omit ``X-User-Role`` entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str) -> Dict[str, str]:
    """Headers whose ``X-User-ID`` is present but empty."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_role(user_id: str) -> Dict[str, str]:
    """Headers whose ``X-User-Role`` is present but empty."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}
