"""Pre-built role headers for every role named in the PRD.

Three roles are entity-backed and their ``X-User-ID`` must be a real row id:
``EvaluationChair`` and ``Evaluator`` carry the acting ``Provider.id``, and
``Parent`` carries the acting ``Child.id``. Use the ``make_*`` builders whenever
the call is ownership-gated; the shared constants below are only safe for
opaque roles and for calls that never reach an ownership check.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Shared constants. The three opaque roles (ChildFindCoordinator,
# PlacementAdministrator, DistrictAdmin) carry an operator identifier that the
# server never compares to any row id, so these are always correct for them.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "coordinator_headers": build_user_headers(
        "op-coordinator-1", "ChildFindCoordinator"
    ),
    "placement_headers": build_user_headers("op-placement-1", "PlacementAdministrator"),
    "district_admin_headers": build_user_headers("op-district-admin-1", "DistrictAdmin"),
    # Entity-backed roles: fallbacks for tests that never reach an ownership
    # check (for example a request rejected on role authorisation alone).
    "chair_headers": build_user_headers("unowned-chair-provider", "EvaluationChair"),
    "evaluator_headers": build_user_headers("unowned-evaluator-provider", "Evaluator"),
    "parent_headers": build_user_headers("unowned-parent-child", "Parent"),
}


# ------------------------------------------------------- per-instance builders
def make_coordinator_headers(user_id: str = "op-coordinator-1") -> Dict[str, str]:
    """ChildFindCoordinator (opaque identity)."""
    return build_user_headers(user_id, "ChildFindCoordinator")


def make_placement_headers(user_id: str = "op-placement-1") -> Dict[str, str]:
    """PlacementAdministrator (opaque identity; stamped as determined_by_user_id)."""
    return build_user_headers(user_id, "PlacementAdministrator")


def make_district_admin_headers(user_id: str = "op-district-admin-1") -> Dict[str, str]:
    """DistrictAdmin (opaque identity)."""
    return build_user_headers(user_id, "DistrictAdmin")


def make_chair_headers(provider_id: str) -> Dict[str, str]:
    """EvaluationChair. Pass the chairing Provider's id — the server compares it
    to the target case's ``chair_provider_id``."""
    return build_user_headers(provider_id, "EvaluationChair")


def make_evaluator_headers(provider_id: str) -> Dict[str, str]:
    """Evaluator. Pass the assessing Provider's id — the server compares it to
    the target assessment's ``evaluator_provider_id``."""
    return build_user_headers(provider_id, "Evaluator")


def make_parent_headers(child_id: str) -> Dict[str, str]:
    """Parent. Pass the Child's id — the guardian holding educational rights is
    addressed through the child's own identifier."""
    return build_user_headers(child_id, "Parent")


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary role string, including unrecognised ones."""
    return build_user_headers(user_id, role)


def headers_without_user_id(role: str = "ChildFindCoordinator") -> Dict[str, str]:
    """Headers carrying a role but no ``X-User-ID`` at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str = "ChildFindCoordinator") -> Dict[str, str]:
    """Headers carrying an empty ``X-User-ID``."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str = "op-coordinator-1") -> Dict[str, str]:
    """Headers carrying an identity but no ``X-User-Role``."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
