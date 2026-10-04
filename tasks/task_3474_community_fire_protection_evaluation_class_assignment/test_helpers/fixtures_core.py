"""Composite fixtures, tier 0–1: clock, community bundle, cycle ladder.

Every test starts against a fresh deployment, so these helpers build state
only through the public API. Setup calls use the lenient success reader:
a failure here surfaces as "Setup failed" with the server's error body,
not as a confusing assertion deep inside a test.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    DEFAULT_COORDINATOR_ID,
    TEST_USERS,
    make_comms_supervisor_headers,
    make_evaluation_coordinator_headers,
    make_fire_chief_headers,
    make_water_utility_manager_headers,
)

COORDINATOR = TEST_USERS["evaluation_coordinator_headers"]

# The coordinator ladder, in order. WITHDRAWN is reachable from any
# non-terminal state via a single transition and is not part of the ladder.
_CYCLE_LADDER = ["SCHEDULED", "INTAKE", "DATA_COLLECTION", "FIELD_VERIFICATION", "SCORING", "CLASSIFICATION_REVIEW"]


# ── Logical clock ────────────────────────────────────────────────────────

def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Advance the logical clock; returns {"current_utc": ...}."""
    return get_success_data(api.set_clock(f.clock_payload(to_iso8601), COORDINATOR))


# ── Readers and OCC version capture ──────────────────────────────────────

def get_community(api: ApiClient, community_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_community(community_id, COORDINATOR))


def get_cycle(api: ApiClient, cycle_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_evaluation_cycle(cycle_id, COORDINATOR))


def community_version(api: ApiClient, community_id: str) -> int:
    """Fresh community version for expected_community_version OCC fields."""
    return get_community(api, community_id)["version"]


def cycle_version(api: ApiClient, cycle_id: str) -> int:
    """Fresh cycle version for expected_cycle_version OCC fields."""
    return get_cycle(api, cycle_id)["version"]


def get_department_of(api: ApiClient, community_id: str) -> Dict[str, Any]:
    """The community's auto-created FireDepartment shell (exactly one)."""
    rows = get_success_data(api.list_fire_departments(COORDINATOR, params={"community_id": community_id}))
    assert len(rows) == 1, f"expected exactly one department for {community_id}, got {len(rows)}"
    return rows[0]


def get_water_system_of(api: ApiClient, community_id: str) -> Dict[str, Any]:
    """The community's auto-created WaterSupplySystem shell (exactly one)."""
    rows = get_success_data(api.list_water_supply_systems(COORDINATOR, params={"community_id": community_id}))
    assert len(rows) == 1, f"expected exactly one water system for {community_id}, got {len(rows)}"
    return rows[0]


# ── Community bundle (Tier 2 root) ───────────────────────────────────────

def create_community(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a community; returns the full community row."""
    return get_success_data(api.create_community(f.community_payload(**overrides), COORDINATOR))


def create_community_bundle(api: ApiClient, **community_overrides: Any) -> Dict[str, Any]:
    """Community plus its auto-created department and water-system shells.

    Returns {"community", "department", "system"} — the entry point every
    deeper fixture builds on.
    """
    community = create_community(api, **community_overrides)
    return {
        "community": community,
        "department": get_department_of(api, community["id"]),
        "system": get_water_system_of(api, community["id"]),
    }


# ── Cycle creation and ladder walking (Tier 1) ───────────────────────────

def create_cycle(
    api: ApiClient,
    community_id: str,
    field_analyst_id: str = f.DEFAULT_ANALYST_ID,
    scheduled_open_date: str = f.DEFAULT_OPEN_DATE,
    data_freeze_date: str = f.DEFAULT_FREEZE_DATE,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.evaluation_cycle_payload(
        community_id,
        field_analyst_id=field_analyst_id,
        scheduled_open_date=scheduled_open_date,
        data_freeze_date=data_freeze_date,
        **overrides,
    )
    return get_success_data(api.create_evaluation_cycle(payload, COORDINATOR))


def transition_cycle(api: ApiClient, cycle_id: str, target_state: str) -> Dict[str, Any]:
    return get_success_data(
        api.transition_evaluation_cycle(cycle_id, f.cycle_transition_payload(target_state), COORDINATOR)
    )


def advance_cycle_to(api: ApiClient, cycle_id: str, target_state: str) -> Dict[str, Any]:
    """Walk the cycle up the coordinator ladder to target_state.

    Reads the cycle's current status first, then issues one transition per
    rung. Only ladder targets are walkable this way; WITHDRAWN and the
    dispute-driven states are reached through their own triggers.
    """
    assert target_state in _CYCLE_LADDER, f"cannot ladder-walk to {target_state}"
    cycle = get_cycle(api, cycle_id)
    current = cycle["status"]
    if current == target_state:
        return cycle
    assert current in _CYCLE_LADDER, f"cycle is in {current}, not on the coordinator ladder"
    for rung in _CYCLE_LADDER[_CYCLE_LADDER.index(current) + 1:]:
        cycle = transition_cycle(api, cycle_id, rung)
        if rung == target_state:
            return cycle
    return cycle


# ── Data-window submissions (Tier 1, ownership-threaded) ─────────────────

def submit_department_data(api: ApiClient, department_id: str, **fields: Any) -> Dict[str, Any]:
    """FireChief PATCH on its own department; sets data_submitted true."""
    return get_success_data(
        api.patch_fire_department(
            department_id, f.department_data_payload(**fields), make_fire_chief_headers(department_id)
        )
    )


def attest_comms(api: ApiClient, community_id: str, **fields: Any) -> Dict[str, Any]:
    """CommsSupervisor attestation; flips comms_attested true."""
    return get_success_data(
        api.attest_comms(community_id, f.attest_comms_payload(**fields), make_comms_supervisor_headers())
    )


def add_apparatus(api: ApiClient, department_id: str, kind: str = "ENGINE", **fields: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_apparatus(f.apparatus_payload(department_id, kind, **fields), make_fire_chief_headers(department_id))
    )


def set_apparatus_status(api: ApiClient, department_id: str, apparatus_id: str, status: str) -> Dict[str, Any]:
    return get_success_data(
        api.patch_apparatus(apparatus_id, f.apparatus_status_payload(status), make_fire_chief_headers(department_id))
    )


def patch_water_system(api: ApiClient, system_id: str, **fields: Any) -> Dict[str, Any]:
    return get_success_data(
        api.patch_water_supply_system(
            system_id, f.water_system_patch_payload(**fields), make_water_utility_manager_headers(system_id)
        )
    )


def add_hydrant(api: ApiClient, system_id: str, location_descriptor: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_hydrant(
            f.hydrant_payload(system_id, location_descriptor, **overrides),
            make_water_utility_manager_headers(system_id),
        )
    )


def set_hydrant_status(api: ApiClient, system_id: str, hydrant_id: str, status: str) -> Dict[str, Any]:
    return get_success_data(
        api.patch_hydrant(hydrant_id, f.hydrant_status_payload(status), make_water_utility_manager_headers(system_id))
    )


def submit_flow_test(api: ApiClient, system_id: str, hydrant_id: str, **fields: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_flow_test(
            f.flow_test_payload(system_id, hydrant_id, **fields),
            make_water_utility_manager_headers(system_id),
        )
    )
