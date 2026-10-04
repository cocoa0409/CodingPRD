"""Pre-built role headers for the eight roles the PRD declares.

Five roles are opaque — the server never compares their ``X-User-ID`` to a
stored entity id — so their shared header constants are canonical.
Three roles are entity-backed and their ``X-User-ID`` must equal the owned
entity's ``id``: FireChief → FireDepartment.id, WaterUtilityManager →
WaterSupplySystem.id, CommunityOfficial → Community.id. For those, the
``make_*_headers`` builders are mandatory whenever a call is
ownership-gated; the shared constants are safe only for tests that never
exercise ownership (400/404 probes, opaque-role denials).

Segregation-of-duties scenarios need distinct opaque operator ids; use
``make_class_registrar_headers("registrar-2")`` and friends rather than
hand-rolling header dicts.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CLASS_REGISTRAR,
    ROLE_COMMUNITY_OFFICIAL,
    ROLE_COMMS_SUPERVISOR,
    ROLE_EVALUATION_COORDINATOR,
    ROLE_FIELD_ANALYST,
    ROLE_FIRE_CHIEF,
    ROLE_INSURER,
    ROLE_WATER_UTILITY_MANAGER,
)

# Default opaque operator ids (stable across a test run; quoted in assertions).
DEFAULT_COORDINATOR_ID = "coordinator-1"
DEFAULT_ANALYST_ID = "analyst-1"
SECOND_ANALYST_ID = "analyst-2"
DEFAULT_REGISTRAR_ID = "registrar-1"
SECOND_REGISTRAR_ID = "registrar-2"
DEFAULT_COMMS_SUPERVISOR_ID = "comms-supervisor-1"
DEFAULT_INSURER_ID = "insurer-1"

# Shared header constants. For the entity-backed roles these are fallbacks
# only — they do not match any real entity id, so ownership-gated calls with
# them will be rejected; use the builders below instead.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "evaluation_coordinator_headers": build_user_headers(DEFAULT_COORDINATOR_ID, ROLE_EVALUATION_COORDINATOR),
    "field_analyst_headers": build_user_headers(DEFAULT_ANALYST_ID, ROLE_FIELD_ANALYST),
    "class_registrar_headers": build_user_headers(DEFAULT_REGISTRAR_ID, ROLE_CLASS_REGISTRAR),
    "fire_chief_headers": build_user_headers("test-fire-chief-1", ROLE_FIRE_CHIEF),
    "water_utility_manager_headers": build_user_headers("test-water-manager-1", ROLE_WATER_UTILITY_MANAGER),
    "comms_supervisor_headers": build_user_headers(DEFAULT_COMMS_SUPERVISOR_ID, ROLE_COMMS_SUPERVISOR),
    "community_official_headers": build_user_headers("test-community-official-1", ROLE_COMMUNITY_OFFICIAL),
    "insurer_headers": build_user_headers(DEFAULT_INSURER_ID, ROLE_INSURER),
}


# ── Opaque roles: builder takes any operator id ──────────────────────────

def make_evaluation_coordinator_headers(user_id: str = DEFAULT_COORDINATOR_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_EVALUATION_COORDINATOR)


def make_field_analyst_headers(user_id: str = DEFAULT_ANALYST_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_FIELD_ANALYST)


def make_class_registrar_headers(user_id: str = DEFAULT_REGISTRAR_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_CLASS_REGISTRAR)


def make_comms_supervisor_headers(user_id: str = DEFAULT_COMMS_SUPERVISOR_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_COMMS_SUPERVISOR)


def make_insurer_headers(user_id: str = DEFAULT_INSURER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_INSURER)


# ── Entity-backed roles: builder takes the OWNED entity's id ─────────────

def make_fire_chief_headers(department_id: str) -> Dict[str, str]:
    """FireChief acts as its FireDepartment; pass department['id']."""
    return build_user_headers(department_id, ROLE_FIRE_CHIEF)


def make_water_utility_manager_headers(system_id: str) -> Dict[str, str]:
    """WaterUtilityManager acts as its WaterSupplySystem; pass system['id']."""
    return build_user_headers(system_id, ROLE_WATER_UTILITY_MANAGER)


def make_community_official_headers(community_id: str) -> Dict[str, str]:
    """CommunityOfficial acts on behalf of its Community; pass community['id']."""
    return build_user_headers(community_id, ROLE_COMMUNITY_OFFICIAL)
