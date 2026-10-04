"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Shared constants — safe for opaque roles, and for tests that do not exercise
# entity-backed ownership.
TEST_USERS = {
    # opaque role: canonical form.
    "consortium_admin_headers": build_user_headers(
        "test-consortium-admin-1", UserRole.CONSORTIUM_ADMIN.value,
    ),
    "system_analyst_headers": build_user_headers(
        "test-system-analyst-1", UserRole.SYSTEM_ANALYST.value,
    ),
    # entity-backed roles: fallback for non-ownership tests only.
    "library_admin_headers": build_user_headers(
        "test-library-admin-1", UserRole.LIBRARY_ADMIN.value,
    ),
    "patron_headers": build_user_headers(
        "test-patron-1", UserRole.PATRON.value,
    ),
}


def make_consortium_admin_headers(user_id: str = "test-consortium-admin-1") -> dict:
    """ConsortiumAdmin is opaque; any user_id works."""
    return build_user_headers(user_id, UserRole.CONSORTIUM_ADMIN.value)


def make_system_analyst_headers(user_id: str = "test-system-analyst-1") -> dict:
    """SystemAnalyst is opaque; any user_id works."""
    return build_user_headers(user_id, UserRole.SYSTEM_ANALYST.value)


def make_library_admin_headers(library_id: str) -> dict:
    """LibraryAdmin is entity-backed by Library: pass the actual Library.id
    whenever the call is ownership-gated."""
    return build_user_headers(library_id, UserRole.LIBRARY_ADMIN.value)


def make_patron_headers(patron_id: str) -> dict:
    """Patron is entity-backed by Patron: pass the actual Patron.id whenever
    the call is ownership-gated."""
    return build_user_headers(patron_id, UserRole.PATRON.value)
