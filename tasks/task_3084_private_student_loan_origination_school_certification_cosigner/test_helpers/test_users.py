"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the opaque roles (Underwriter, Servicer,
# PlatformAdmin) and, for entity-backed roles, only for tests whose success
# does not depend on the caller owning the subject resource.
TEST_USERS = {
    "borrower_headers": build_user_headers("test-borrower-1", "Borrower"),
    "cosigner_headers": build_user_headers("test-cosigner-1", "Cosigner"),
    "school_headers": build_user_headers("test-school-1", "School"),
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    "servicer_headers": build_user_headers("test-servicer-1", "Servicer"),
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


def make_borrower_headers(user_id: str) -> dict:
    """For Borrower (identity entity_backed:Borrower). Pass the actual
    Borrower.id as user_id for any ownership-gated call."""
    return build_user_headers(user_id, "Borrower")


def make_cosigner_headers(user_id: str) -> dict:
    """For Cosigner (identity entity_backed:Cosigner). Pass the actual
    Cosigner.id as user_id for any ownership-gated call."""
    return build_user_headers(user_id, "Cosigner")


def make_school_headers(user_id: str) -> dict:
    """For School (identity entity_backed:School). Pass the actual School.id as
    user_id for any ownership-gated call such as filing or certifying."""
    return build_user_headers(user_id, "School")


def make_underwriter_headers(user_id: str = "test-underwriter-1") -> dict:
    """Underwriter is an opaque operator identity."""
    return build_user_headers(user_id, "Underwriter")


def make_servicer_headers(user_id: str = "test-servicer-1") -> dict:
    """Servicer is an opaque operator identity."""
    return build_user_headers(user_id, "Servicer")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """PlatformAdmin is an opaque operator identity."""
    return build_user_headers(user_id, "PlatformAdmin")