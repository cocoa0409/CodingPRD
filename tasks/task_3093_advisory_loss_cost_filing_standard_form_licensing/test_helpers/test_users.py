"""Pre-built role headers for every role in the PRD (§2.1).

Identity semantics per PRD §2.1:
- BureauAdmin / BureauActuary: opaque operator identifiers, never compared to entity ids
  (except the segregation-of-duties comparison, which is a user-id vs user-id comparison).
- RegulatorAnalyst: X-User-ID is the id of the acting StateDepartment.
- InsurerUser: X-User-ID is the id of the acting MemberInsurer.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "BureauAdmin"),
    "actuary_headers": build_user_headers("test-actuary-1", "BureauActuary"),
    # Entity-backed roles: shared constants are a fallback for non-ownership
    # tests only (e.g., 404-on-missing-resource, or rejection paths that never
    # reach an ownership comparison).
    "regulator_headers": build_user_headers("test-dept-1", "RegulatorAnalyst"),
    "insurer_headers": build_user_headers("test-insurer-1", "InsurerUser"),
}


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """BureauAdmin (opaque identity). user_id may be varied to drive the
    segregation-of-duties comparison at complete-review."""
    return build_user_headers(user_id, "BureauAdmin")


def make_actuary_headers(user_id: str = "test-actuary-1") -> dict:
    """BureauActuary (opaque identity). user_id participates in the
    segregation-of-duties comparison at complete-review."""
    return build_user_headers(user_id, "BureauActuary")


def make_regulator_headers(department_id: str) -> dict:
    """RegulatorAnalyst (entity-backed: the StateDepartment id). Pass the actual
    department id whenever the call is jurisdiction-gated."""
    return build_user_headers(department_id, "RegulatorAnalyst")


def make_insurer_headers(insurer_id: str) -> dict:
    """InsurerUser (entity-backed: the MemberInsurer id). Pass the actual
    insurer id whenever the call is ownership-gated."""
    return build_user_headers(insurer_id, "InsurerUser")
