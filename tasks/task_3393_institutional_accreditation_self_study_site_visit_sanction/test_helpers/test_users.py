"""Pre-built role headers for every role in the PRD (§2.1).

Entity-backed roles (InstitutionLiaison -> Institution id, PeerReviewer ->
Reviewer id) MUST use the per-instance builders with the real entity id;
the shared constants for those roles are fallbacks for non-ownership tests
only (e.g. 400/404 checks where no owned resource is involved).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: X-User-ID binds to no stored resource (PRD §2.1).
    "admin_headers": build_user_headers("test-admin-1", "CommissionAdmin"),
    "staff_headers": build_user_headers("test-staff-1", "CommissionStaff"),
    # Entity-backed fallbacks — NEVER pass an ownership-gated call with these;
    # the id matches no Institution/Reviewer, so the ownership check rejects.
    "liaison_headers": build_user_headers("test-liaison-unbound", "InstitutionLiaison"),
    "reviewer_headers": build_user_headers("test-reviewer-unbound", "PeerReviewer"),
}


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """CommissionAdmin is opaque; any stable id works."""
    return build_user_headers(user_id, "CommissionAdmin")


def make_staff_headers(user_id: str = "test-staff-1") -> dict:
    """CommissionStaff is opaque; any stable id works."""
    return build_user_headers(user_id, "CommissionStaff")


def make_liaison_headers(institution_id: str) -> dict:
    """InstitutionLiaison: X-User-ID must equal the Institution.id acted upon."""
    return build_user_headers(institution_id, "InstitutionLiaison")


def make_reviewer_headers(reviewer_id: str) -> dict:
    """PeerReviewer: X-User-ID must equal the Reviewer.id the endpoint binds."""
    return build_user_headers(reviewer_id, "PeerReviewer")
