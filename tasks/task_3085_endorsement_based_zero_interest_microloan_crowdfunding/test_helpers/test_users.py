"""Pre-built role headers for every role in the PRD.

Anonymous, PlatformAdmin are opaque roles — a shared constant is canonical.
Borrower / Lender / Trustee are entity-backed: any ownership-gated call MUST
use the per-instance builder with the actual entity id, never the shared
constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests whose outcome does
# not depend on the caller owning the subject resource (404s, 400s, RBAC
# denials). For entity-backed roles prefer the make_* builders below.
TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-caller-1", "Anonymous"),
    "admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
    # Fallbacks for entity-backed roles — non-ownership tests only.
    "borrower_headers": build_user_headers("test-borrower-1", "Borrower"),
    "lender_headers": build_user_headers("test-lender-1", "Lender"),
    "trustee_headers": build_user_headers("test-trustee-1", "Trustee"),
}


def make_borrower_headers(user_id: str) -> dict:
    """Borrower is entity-backed: pass the actual Borrower.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Borrower")


def make_lender_headers(user_id: str) -> dict:
    """Lender is entity-backed: pass the actual Lender.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Lender")


def make_trustee_headers(user_id: str) -> dict:
    """Trustee is entity-backed: pass the actual Trustee.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Trustee")


def make_admin_headers(user_id: str = "platform-admin-1") -> dict:
    """PlatformAdmin is opaque; user_id is never compared to any entity."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_anonymous_headers(user_id: str = "anon-caller-1") -> dict:
    """Anonymous is opaque; user_id is never compared to any entity."""
    return build_user_headers(user_id, "Anonymous")
