"""Caller identities and auth headers.

PRD §2.1 makes every request carry an ``X-User-ID`` and an ``X-User-Role``. Four of
the five roles carry an opaque operator identifier that is never compared with any
stored entity id, so those get fixed constants here. The ``Analyst`` role is the one
exception: its ``X-User-ID`` is the Analyst row's own id, so analyst headers must be
built per analyst from the id the registry handed back.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# ─── Role names (PRD §2.1) ────────────────────────────

ROLE_EVIDENCE_TECHNICIAN = "EvidenceTechnician"
ROLE_CASE_MANAGER = "CaseManager"
ROLE_ANALYST = "Analyst"
ROLE_QUALITY_MANAGER = "QualityManager"
ROLE_LAB_DIRECTOR = "LabDirector"

ALL_ROLES = [
    ROLE_EVIDENCE_TECHNICIAN,
    ROLE_CASE_MANAGER,
    ROLE_ANALYST,
    ROLE_QUALITY_MANAGER,
    ROLE_LAB_DIRECTOR,
]

# ─── Opaque operator identifiers ──────────────────────

TEST_USERS: Dict[str, str] = {
    "director": "op-director-0001",
    "director_alt": "op-director-0002",
    "quality": "op-quality-0001",
    "quality_alt": "op-quality-0002",
    "case_manager": "op-casemgr-0001",
    "case_manager_alt": "op-casemgr-0002",
    "technician": "op-tech-0001",
    "technician_alt": "op-tech-0002",
}

DIRECTOR_ID = TEST_USERS["director"]
DIRECTOR_ALT_ID = TEST_USERS["director_alt"]
QUALITY_ID = TEST_USERS["quality"]
QUALITY_ALT_ID = TEST_USERS["quality_alt"]
CASE_MANAGER_ID = TEST_USERS["case_manager"]
CASE_MANAGER_ALT_ID = TEST_USERS["case_manager_alt"]
TECHNICIAN_ID = TEST_USERS["technician"]
TECHNICIAN_ALT_ID = TEST_USERS["technician_alt"]

# An identifier that belongs to no role's roster and no entity row.
UNKNOWN_OPERATOR_ID = "op-nobody-9999"

# A role string outside the five the PRD recognises.
UNRECOGNISED_ROLE = "ForensicIntern"


# ─── Header builders ──────────────────────────────────

def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Build auth headers for an arbitrary identity/role pair."""
    return build_user_headers(user_id, role)


def make_director_headers(user_id: str = DIRECTOR_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_LAB_DIRECTOR)


def make_quality_manager_headers(user_id: str = QUALITY_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_QUALITY_MANAGER)


def make_case_manager_headers(user_id: str = CASE_MANAGER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_CASE_MANAGER)


def make_technician_headers(user_id: str = TECHNICIAN_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_EVIDENCE_TECHNICIAN)


def make_analyst_headers(analyst_id: str) -> Dict[str, str]:
    """Headers for a bench examiner.

    The identifier must be the Analyst row's own id, because the identity-binding
    rule compares it against the request's assigned analyst.
    """
    return build_user_headers(analyst_id, ROLE_ANALYST)


def make_unrecognised_role_headers(user_id: str = DIRECTOR_ID) -> Dict[str, str]:
    """Headers naming a role outside the five the PRD recognises."""
    return build_user_headers(user_id, UNRECOGNISED_ROLE)


# ─── Ready-made header dicts for the opaque roles ──────

DIRECTOR_HEADERS = make_director_headers()
QUALITY_MANAGER_HEADERS = make_quality_manager_headers()
QUALITY_MANAGER_ALT_HEADERS = make_quality_manager_headers(QUALITY_ALT_ID)
CASE_MANAGER_HEADERS = make_case_manager_headers()
CASE_MANAGER_ALT_HEADERS = make_case_manager_headers(CASE_MANAGER_ALT_ID)
TECHNICIAN_HEADERS = make_technician_headers()


# ─── Malformed auth headers ───────────────────────────
#
# A "missing" credential is expressed either by omitting the header outright or by
# sending an empty string. Never a whitespace-only value: a blank-but-present header
# value is rejected by the HTTP client before the request leaves the process, which
# would test the client rather than the API.

def headers_without_user_id(role: str = ROLE_LAB_DIRECTOR) -> Dict[str, str]:
    """Auth headers carrying a role but no identity header at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str = ROLE_LAB_DIRECTOR) -> Dict[str, str]:
    """Auth headers whose identity header is present but empty."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str = DIRECTOR_ID) -> Dict[str, str]:
    """Auth headers carrying an identity but no role header at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_empty_role(user_id: str = DIRECTOR_ID) -> Dict[str, str]:
    """Auth headers whose role header is present but empty."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


NO_AUTH_HEADERS = {"Content-Type": "application/json"}
