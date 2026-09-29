"""Pre-built role headers for every role in the PRD.

``IsoAdmin``, ``ResidualAnalyst`` and ``ResidualController`` carry an opaque
``X-User-ID`` that is never compared to an entity id, so shared constants are
the canonical form for them. For the ``Agent`` role ``X-User-ID`` is the id of
the acting agent row, so ownership-gated calls MUST use
``make_agent_headers(agent["id"])``.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "iso_admin_headers": build_user_headers("test-iso-admin-1", "IsoAdmin"),
    "residual_analyst_headers": build_user_headers("test-analyst-1", "ResidualAnalyst"),
    "residual_controller_headers": build_user_headers(
        "test-controller-1", "ResidualController"
    ),
    # Fallback only — for calls that never reach an ownership comparison.
    "agent_headers": build_user_headers("test-agent-1", "Agent"),
}

# Distinct controller principals, for segregation-of-duties scenarios.
CONTROLLER_ONE_ID = "ctrl-1"
CONTROLLER_TWO_ID = "ctrl-2"
CONTROLLER_ONE = build_user_headers(CONTROLLER_ONE_ID, "ResidualController")
CONTROLLER_TWO = build_user_headers(CONTROLLER_TWO_ID, "ResidualController")

ANALYST_ONE_ID = "analyst-1"
ANALYST_ONE = build_user_headers(ANALYST_ONE_ID, "ResidualAnalyst")
ADMIN_ONE_ID = "admin-1"
ADMIN_ONE = build_user_headers(ADMIN_ONE_ID, "IsoAdmin")


def make_iso_admin_headers(user_id: str) -> dict:
    """IsoAdmin acting as an arbitrary opaque operator id."""
    return build_user_headers(user_id, "IsoAdmin")


def make_residual_analyst_headers(user_id: str) -> dict:
    """ResidualAnalyst acting as an arbitrary opaque operator id."""
    return build_user_headers(user_id, "ResidualAnalyst")


def make_residual_controller_headers(user_id: str) -> dict:
    """ResidualController acting as an arbitrary opaque operator id."""
    return build_user_headers(user_id, "ResidualController")


def make_agent_headers(agent_id: str) -> dict:
    """For the Agent role: pass the acting agent's own ``id`` as ``X-User-ID``."""
    return build_user_headers(agent_id, "Agent")
