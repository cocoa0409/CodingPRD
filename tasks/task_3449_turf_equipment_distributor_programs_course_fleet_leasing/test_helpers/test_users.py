"""Pre-built role headers for every role in the PRD (§2.1).

CorporateAdmin is an opaque role: the server never compares its X-User-ID to
any entity id, so the shared constant is the canonical form.

DistributorManager and IrrigationDealer are entity-backed by Distributor, and
CourseManager is entity-backed by GolfCourse: for ownership-gated calls the
X-User-ID MUST be the actual backing entity's id, so use the per-instance
builders below (e.g. make_distributor_manager_headers(distributor["id"])).
The shared constants for entity-backed roles are fallbacks for tests that do
not exercise ownership (400-shape, 401/403 role checks, 404 lookups).
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Shared constants — safe for the opaque role, and for non-ownership tests.
TEST_USERS = {
    # opaque role: canonical form.
    "corporate_admin_headers": build_user_headers(
        "test-corporate-admin-1", UserRole.CORPORATE_ADMIN.value
    ),
    # entity_backed:Distributor — fallback for non-ownership tests only.
    "distributor_manager_headers": build_user_headers(
        "test-distributor-manager-1", UserRole.DISTRIBUTOR_MANAGER.value
    ),
    # entity_backed:GolfCourse — fallback for non-ownership tests only.
    "course_manager_headers": build_user_headers(
        "test-course-manager-1", UserRole.COURSE_MANAGER.value
    ),
    # entity_backed:Distributor (irrigation channel) — fallback only.
    "irrigation_dealer_headers": build_user_headers(
        "test-irrigation-dealer-1", UserRole.IRRIGATION_DEALER.value
    ),
}


def make_corporate_admin_headers(user_id: str = "test-corporate-admin-1") -> dict:
    """CorporateAdmin (opaque identity): any operator id works."""
    return build_user_headers(user_id, UserRole.CORPORATE_ADMIN.value)


def make_distributor_manager_headers(user_id: str) -> dict:
    """DistributorManager (entity-backed by Distributor). Pass the actual
    Distributor.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, UserRole.DISTRIBUTOR_MANAGER.value)


def make_course_manager_headers(user_id: str) -> dict:
    """CourseManager (entity-backed by GolfCourse). Pass the actual
    GolfCourse.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, UserRole.COURSE_MANAGER.value)


def make_irrigation_dealer_headers(user_id: str) -> dict:
    """IrrigationDealer (entity-backed by an irrigation-channel Distributor).
    Pass the actual Distributor.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, UserRole.IRRIGATION_DEALER.value)
