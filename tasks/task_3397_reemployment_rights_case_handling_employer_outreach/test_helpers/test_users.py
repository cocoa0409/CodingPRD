"""Caller identities for the six declared roles.

Every request carries ``X-User-Role`` and - for every role except Anonymous -
an ``X-User-ID``. Three roles are entity-backed: the identifier is compared
against a stored entity's ``id`` (member_id / employer_id /
assigned_ombudsman_id), so ServiceMember, Employer and Ombudsman callers get
per-instance builders that take the real entity identifier the test created.
Falling back to a shared constant for those roles makes every ownership check
reject the call.

ProgramCoordinator and AgencyReviewer identifiers are opaque: the server may
record them (proctor_id, author_id, nominated_by_id) but never compares them
to an entity. Segregation of duties requires at least two distinct coordinator
identities - the one who proctored a volunteer's records may not certify that
volunteer - so two standing coordinators are provided, plus a builder for
arbitrary extras.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_AGENCY_REVIEWER,
    ROLE_ANONYMOUS,
    ROLE_EMPLOYER,
    ROLE_OMBUDSMAN,
    ROLE_PROGRAM_COORDINATOR,
    ROLE_SERVICE_MEMBER,
)

# ── Shared identity registry ───────────────────────────────────────────────
# Entity-backed entries are fallbacks for tests that do not exercise
# ownership (bad-payload 400s, missing-resource 404s); ownership-gated calls
# MUST use the per-instance builders below with the real entity id.
TEST_USERS: Dict[str, Dict[str, Optional[str]]] = {
    "anonymous": {"id": None, "role": ROLE_ANONYMOUS},
    "service_member": {"id": "11111111-1111-4111-8111-111111111111", "role": ROLE_SERVICE_MEMBER},
    "employer": {"id": "22222222-2222-4222-8222-222222222222", "role": ROLE_EMPLOYER},
    "ombudsman": {"id": "33333333-3333-4333-8333-333333333333", "role": ROLE_OMBUDSMAN},
    # Generic coordinator for calls with no segregation-of-duties stake.
    "coordinator": {"id": "pc-coordinator", "role": ROLE_PROGRAM_COORDINATOR},
    # The proctor: records training records in the standard certification fixture.
    "coordinator_admin": {"id": "pc-admin", "role": ROLE_PROGRAM_COORDINATOR},
    # The certifier: never proctored the standard fixture's records.
    "coordinator_lead": {"id": "pc-lead", "role": ROLE_PROGRAM_COORDINATOR},
    "agency_reviewer": {"id": "agency-reviewer-1", "role": ROLE_AGENCY_REVIEWER},
}

# ── Ready-made headers for the opaque roles ────────────────────────────────

# Anonymous callers are unauthenticated registrants: no X-User-ID at all.
ANONYMOUS_HEADERS: Dict[str, str] = {
    "X-User-Role": ROLE_ANONYMOUS,
    "Content-Type": "application/json",
}

COORDINATOR_HEADERS = build_user_headers(TEST_USERS["coordinator"]["id"], ROLE_PROGRAM_COORDINATOR)
COORDINATOR_ADMIN_HEADERS = build_user_headers(TEST_USERS["coordinator_admin"]["id"], ROLE_PROGRAM_COORDINATOR)
COORDINATOR_LEAD_HEADERS = build_user_headers(TEST_USERS["coordinator_lead"]["id"], ROLE_PROGRAM_COORDINATOR)
AGENCY_REVIEWER_HEADERS = build_user_headers(TEST_USERS["agency_reviewer"]["id"], ROLE_AGENCY_REVIEWER)

# Shared fallbacks for the entity-backed roles (non-ownership tests only).
SERVICE_MEMBER_HEADERS = build_user_headers(TEST_USERS["service_member"]["id"], ROLE_SERVICE_MEMBER)
EMPLOYER_HEADERS = build_user_headers(TEST_USERS["employer"]["id"], ROLE_EMPLOYER)
OMBUDSMAN_HEADERS = build_user_headers(TEST_USERS["ombudsman"]["id"], ROLE_OMBUDSMAN)


# ── Per-instance builders for the entity-backed roles ──────────────────────

def make_service_member_headers(member_id: str) -> Dict[str, str]:
    """Headers for the ServiceMember whose id is ``member_id``.

    Pass the real ServiceMember.id whenever the call is ownership-gated
    (filing a case, withdrawing, reopening, reading own rows, responding to a
    round addressed to MEMBER).
    """
    return build_user_headers(member_id, ROLE_SERVICE_MEMBER)


def make_employer_headers(employer_id: str) -> Dict[str, str]:
    """Headers for the Employer whose id is ``employer_id``."""
    return build_user_headers(employer_id, ROLE_EMPLOYER)


def make_ombudsman_headers(ombudsman_id: str) -> Dict[str, str]:
    """Headers for the Ombudsman whose id is ``ombudsman_id``."""
    return build_user_headers(ombudsman_id, ROLE_OMBUDSMAN)


def make_coordinator_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary ProgramCoordinator operator id.

    Use a fresh id when a test needs a coordinator who is neither the proctor
    nor the certifier of a volunteer (segregation-of-duties scenarios).
    """
    return build_user_headers(user_id, ROLE_PROGRAM_COORDINATOR)


def make_agency_reviewer_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary AgencyReviewer operator id."""
    return build_user_headers(user_id, ROLE_AGENCY_REVIEWER)


# ── Malformed credentials, for the authentication tier ─────────────────────

def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers that omit X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers that omit X-User-ID entirely (invalid for every non-Anonymous role)."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str) -> Dict[str, str]:
    """Headers whose X-User-ID is present but empty."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


UNDECLARED_ROLE = "FieldMarshal"


def headers_with_undeclared_role(user_id: str) -> Dict[str, str]:
    """Headers naming a role the contract does not declare."""
    return build_user_headers(user_id, UNDECLARED_ROLE)
