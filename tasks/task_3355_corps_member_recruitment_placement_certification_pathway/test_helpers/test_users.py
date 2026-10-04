"""Pre-built role headers for every role in the API."""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import OPERATORS

# Shared constants. Safe for the six opaque operator roles, and for calls by
# the Applicant role that do not exercise ownership.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "selection_manager_headers": build_user_headers("sm_reviewer", "SelectionManager"),
    "placement_coordinator_headers": build_user_headers("test-pc-1", "PlacementCoordinator"),
    "institute_director_headers": build_user_headers("test-id-1", "InstituteDirector"),
    "certification_officer_headers": build_user_headers("co_completer", "CertificationOfficer"),
    "coach_headers": build_user_headers("coach_lee", "Coach"),
    # entity_backed role: the shared constant is a fallback for non-ownership
    # calls only. Ownership-gated calls MUST use make_applicant_headers().
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
}

# Named operator identities, so segregation-of-duties scenarios can pick two
# distinct operators per role.
SELECTION_MANAGER_HEADERS = {
    "reviewer": build_user_headers(OPERATORS["REVIEWER"], "SelectionManager"),
    "decider": build_user_headers(OPERATORS["DECIDER"], "SelectionManager"),
    "reviewer_2": build_user_headers(OPERATORS["REVIEWER_2"], "SelectionManager"),
    "decider_2": build_user_headers(OPERATORS["DECIDER_2"], "SelectionManager"),
}

CERTIFICATION_OFFICER_HEADERS = {
    "completer": build_user_headers(OPERATORS["COMPLETER"], "CertificationOfficer"),
    "verifier": build_user_headers(OPERATORS["VERIFIER"], "CertificationOfficer"),
}

COACH_HEADERS = {
    "lee": build_user_headers(OPERATORS["COACH"], "Coach"),
}


# ─── Per-instance builders ────────────────────────────

def make_applicant_headers(user_id: str) -> dict:
    """Headers for the Applicant role (entity_backed:Applicant).

    Pass the actual Applicant.id as user_id whenever the call is
    ownership-gated (resubmit, offer response).
    """
    return build_user_headers(user_id, "Applicant")


def make_selection_manager_headers(user_id: str) -> dict:
    """Headers for a named SelectionManager operator."""
    return build_user_headers(user_id, "SelectionManager")


def make_certification_officer_headers(user_id: str) -> dict:
    """Headers for a named CertificationOfficer operator."""
    return build_user_headers(user_id, "CertificationOfficer")


# ─── Header-shape helpers (authentication tests) ──────

def headers_without_role(user_id: str = "ghost_1") -> dict:
    """Headers carrying X-User-ID but no X-User-Role."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = "PlatformAdmin") -> dict:
    """Headers carrying X-User-Role but no X-User-ID."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_undeclared_role(user_id: str = "ghost_1", role: str = "Ghost") -> dict:
    """Headers naming a role outside the seven recognized names."""
    return build_user_headers(user_id, role)
