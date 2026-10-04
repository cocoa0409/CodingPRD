"""Composite setup helpers (fixtures).

Every fixture builds its preconditions from scratch against an empty
database using only PRD-declared endpoints, and uses get_success_data()
internally so a setup failure surfaces as a clear "Setup failed" error.

Common setup flow across most fixtures:
  franchise area (PlatformAdmin) -> optical node (NetworkPlanner)
  -> spectrum blocks (CapacityEngineer) -> service group (CapacityEngineer)
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_congestion_complaint_payload,
    create_customer_premise_payload,
    create_equipment_payload,
    create_franchise_area_payload,
    create_node_split_project_payload,
    create_optical_node_payload,
    create_service_group_payload,
    create_spectrum_block_payload,
    create_speed_tier_payload,
    create_utilization_sample_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["network_planner_headers"]
ENGINEER = TEST_USERS["capacity_engineer_headers"]
FIELD_OPS = TEST_USERS["field_ops_coordinator_headers"]
FRANCHISE_ADMIN = TEST_USERS["franchise_admin_headers"]
PROVISIONING = TEST_USERS["provisioning_agent_headers"]
CARE = TEST_USERS["customer_care_headers"]


def set_clock(current_utc="2026-10-01T00:00:00Z"):
    """Move the logical clock (PRD §2.4)."""
    if current_utc is None:
        return
    resp = api_client.set_clock({"current_utc": current_utc}, ADMIN)
    get_success_data(resp)


def create_franchise_area(**overrides):
    resp = api_client.create_franchise_area(create_franchise_area_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_node(fa_id, **overrides):
    resp = api_client.create_optical_node(fa_id, create_optical_node_payload(**overrides), PLANNER)
    return get_success_data(resp)


def create_block(node_id, block_type="DATA", mhz=48):
    resp = api_client.create_spectrum_block(
        node_id, create_spectrum_block_payload(block_type=block_type, mhz=mhz), ENGINEER
    )
    return get_success_data(resp)


def create_service_group(node_id, **overrides):
    resp = api_client.create_service_group(node_id, create_service_group_payload(**overrides), ENGINEER)
    return get_success_data(resp)


def create_sample(sg_id, downstream_mbps, measured_at="2026-09-30T18:00:00Z", upstream_mbps=10):
    resp = api_client.create_utilization_sample(
        sg_id,
        create_utilization_sample_payload(
            measured_at=measured_at, downstream_mbps=downstream_mbps, upstream_mbps=upstream_mbps
        ),
        ADMIN,
    )
    return get_success_data(resp)


def create_capacity_action(sg_id, sg_version, action_type="NODE_SPLIT", **extra):
    payload = {"action_type": action_type, "expected_service_group_version": sg_version}
    payload.update(extra)
    resp = api_client.create_capacity_action(sg_id, payload, PLANNER)
    return get_success_data(resp)


def create_premise(sg_id, **overrides):
    resp = api_client.create_customer_premise(sg_id, create_customer_premise_payload(**overrides), PROVISIONING)
    return get_success_data(resp)


def create_equipment(cp_id, **overrides):
    resp = api_client.create_equipment(cp_id, create_equipment_payload(**overrides), PROVISIONING)
    return get_success_data(resp)


def create_tier(**overrides):
    resp = api_client.create_speed_tier(create_speed_tier_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_provisioning_request(cp_id, tier_id, cp_version):
    resp = api_client.create_provisioning_request(
        cp_id,
        {"speed_tier_id": tier_id, "expected_customer_premise_version": cp_version},
        PROVISIONING,
    )
    return get_success_data(resp)


def create_complaint(cp_id, description="slow evenings", plant=50, home=30, destination=20):
    resp = api_client.create_congestion_complaint(
        cp_id,
        create_congestion_complaint_payload(
            description=description,
            plant_signal=plant,
            home_signal=home,
            destination_signal=destination,
        ),
        CARE,
    )
    return get_success_data(resp)


def get_service_group(sg_id):
    resp = api_client.get_service_group(sg_id, ADMIN)
    return get_success_data(resp)


def get_capacity_action(ca_id):
    resp = api_client.get_capacity_action(ca_id, ADMIN)
    return get_success_data(resp)


def get_node_split_project(nsp_id):
    resp = api_client.get_node_split_project(nsp_id, ADMIN)
    return get_success_data(resp)


def get_premise(cp_id):
    resp = api_client.get_customer_premise(cp_id, ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: basic plant setup
# ---------------------------------------------------------------------------

def setup_node_with_data_block(
    node_code="NE-1",
    node_homes=100,
    spectrum_mhz=48,
    upstream_config="LEGACY",
    clock="2026-10-01T00:00:00Z",
):
    """Franchise area + node + one 48-MHz DATA block. Returns (fa, node, block)."""
    set_clock(clock)
    fa = create_franchise_area()
    node = create_node(
        fa["id"],
        node_code=node_code,
        homes_passed=node_homes,
        downstream_spectrum_mhz=spectrum_mhz,
        upstream_config=upstream_config,
    )
    block = create_block(node["id"], block_type="DATA", mhz=48)
    return fa, node, block


def setup_service_group(
    sg_code="SG-1",
    sg_homes=100,
    warn=70,
    crit=85,
    method="PEAK_PCT95",
    node_homes=600,
    node_code="NE-1",
    spectrum_mhz=48,
    block_mhz=48,
    upstream_config="LEGACY",
    clock="2026-10-01T00:00:00Z",
):
    """Franchise area + node + one DATA block + one service group.

    Returns dict with keys: fa, node, block, sg.
    """
    set_clock(clock)
    fa = create_franchise_area()
    node = create_node(
        fa["id"],
        node_code=node_code,
        homes_passed=node_homes,
        downstream_spectrum_mhz=spectrum_mhz,
        upstream_config=upstream_config,
    )
    block = create_block(node["id"], block_type="DATA", mhz=block_mhz)
    sg = create_service_group(
        node["id"],
        sg_code=sg_code,
        homes_passed=sg_homes,
        warn_threshold_pct=warn,
        critical_threshold_pct=crit,
        utilization_method=method,
    )
    return {"fa": fa, "node": node, "block": block, "sg": sg}


# ---------------------------------------------------------------------------
# Tier 2: capacity actions
# ---------------------------------------------------------------------------

def setup_proposed_action(sg, action_type="NODE_SPLIT", **extra):
    """Create a MANUAL PROPOSED capacity action on sg. Returns the action."""
    return create_capacity_action(sg["id"], sg["version"], action_type=action_type, **extra)


def setup_approved_action(sg, action_type="NODE_SPLIT", **extra):
    """PROPOSED -> APPROVED capacity action. Returns the action."""
    action = setup_proposed_action(sg, action_type=action_type, **extra)
    resp = api_client.approve_capacity_action(action["id"], ENGINEER)
    return get_success_data(resp)


def setup_in_progress_action(sg, action_type="NODE_SPLIT", **extra):
    """PROPOSED -> APPROVED -> IN_PROGRESS capacity action. Returns the action."""
    action = setup_approved_action(sg, action_type=action_type, **extra)
    resp = api_client.begin_capacity_action(action["id"], ENGINEER)
    return get_success_data(resp)


def setup_completed_upgrade(sg, action_type="MID_SPLIT_UPGRADE", target="MID_SPLIT"):
    """Full upgrade lifecycle to COMPLETED. Returns the action."""
    action = setup_in_progress_action(sg, action_type=action_type, target_upstream_config=target)
    resp = api_client.complete_capacity_action(action["id"], ENGINEER)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: node-split project lifecycle
# ---------------------------------------------------------------------------

def create_project(ca_id, child_count=2, min_homes=200, max_homes=400):
    resp = api_client.create_node_split_project(
        ca_id,
        create_node_split_project_payload(
            child_count=child_count,
            min_homes_per_child=min_homes,
            max_homes_per_child=max_homes,
        ),
        PLANNER,
    )
    return get_success_data(resp)


def grant_permit(nsp_id):
    resp = api_client.adjudicate_permit(nsp_id, {"decision": "GRANTED"}, FRANCHISE_ADMIN)
    return get_success_data(resp)


def deny_permit(nsp_id):
    resp = api_client.adjudicate_permit(nsp_id, {"decision": "DENIED"}, FRANCHISE_ADMIN)
    return get_success_data(resp)


def schedule_project(nsp_id, nsp_version, window_start="2026-11-01T00:00:00Z", window_end="2026-11-05T00:00:00Z"):
    resp = api_client.schedule_node_split_project(
        nsp_id,
        {
            "window_start": window_start,
            "window_end": window_end,
            "expected_node_split_project_version": nsp_version,
        },
        PLANNER,
    )
    return get_success_data(resp)


def setup_project_in_permit_review(sg, child_count=2, min_homes=200, max_homes=400):
    """Approved NODE_SPLIT action + project in PERMIT_REVIEW. Returns (action, project)."""
    action = setup_approved_action(sg, action_type="NODE_SPLIT")
    project = create_project(action["id"], child_count=child_count, min_homes=min_homes, max_homes=max_homes)
    return action, project


def setup_project_in_permit_granted(sg, child_count=2, min_homes=200, max_homes=400):
    """Project advanced to PERMIT_GRANTED. Returns (action, project)."""
    action, project = setup_project_in_permit_review(sg, child_count=child_count, min_homes=min_homes, max_homes=max_homes)
    project = grant_permit(project["id"])
    return action, project


def setup_project_scheduled(
    sg,
    child_count=2,
    min_homes=200,
    max_homes=400,
    window_start="2026-11-01T00:00:00Z",
    window_end="2026-11-05T00:00:00Z",
):
    """Project in SCHEDULED with the given window. Returns (action, project)."""
    action, project = setup_project_in_permit_granted(sg, child_count=child_count, min_homes=min_homes, max_homes=max_homes)
    project = schedule_project(project["id"], project["version"], window_start=window_start, window_end=window_end)
    return action, project


def setup_project_in_construction(
    sg,
    child_count=2,
    min_homes=200,
    max_homes=400,
    window_start="2026-11-01T00:00:00Z",
    window_end="2026-11-05T00:00:00Z",
):
    """Full walk to IN_CONSTRUCTION: action IN_PROGRESS + project SCHEDULED ->
    IN_CONSTRUCTION. Returns (action, project)."""
    action, project = setup_project_scheduled(
        sg,
        child_count=child_count,
        min_homes=min_homes,
        max_homes=max_homes,
        window_start=window_start,
        window_end=window_end,
    )
    resp = api_client.begin_capacity_action(action["id"], ENGINEER)
    action = get_success_data(resp)
    resp = api_client.begin_construction(project["id"], FIELD_OPS)
    project = get_success_data(resp)
    return action, project


# ---------------------------------------------------------------------------
# Tier 4: reclaim + migration waves
# ---------------------------------------------------------------------------

def setup_reclaim_action_in_progress(sg, target_block_ids):
    """SPECTRUM_RECLAIM action walked to IN_PROGRESS on the given target blocks."""
    return setup_in_progress_action(
        sg, action_type="SPECTRUM_RECLAIM", target_block_ids=target_block_ids
    )


def create_wave(ca_id, cpe_ids, wave_code="W1", window_start="2026-10-01T00:00:00Z", window_end="2026-10-02T00:00:00Z"):
    resp = api_client.create_migration_wave(
        ca_id,
        {
            "wave_code": wave_code,
            "window_start": window_start,
            "window_end": window_end,
            "target_cpe_ids": cpe_ids,
        },
        PLANNER,
    )
    return get_success_data(resp)


def setup_legacy_cpe(sg, premise_ref="P-R1", address="1 Legacy Ln"):
    """Premise + ACTIVE D30 CPE with video_legacy true. Returns (premise, cpe)."""
    premise = create_premise(sg["id"], premise_ref=premise_ref, address=address)
    cpe = create_equipment(
        premise["id"],
        model="SB6183",
        docsis_version="3.0",
        capability_class="D30",
        max_downstream_mbps=300,
        video_legacy=True,
    )
    return premise, cpe


# ---------------------------------------------------------------------------
# Tier 5: provisioning lifecycle
# ---------------------------------------------------------------------------

def setup_premise_with_cpe(sg, cpe_overrides=None, premise_overrides=None):
    """Premise + one ACTIVE CPE. Returns (premise, cpe)."""
    premise = create_premise(sg["id"], **(premise_overrides or {}))
    cpe = create_equipment(premise["id"], **(cpe_overrides or {}))
    return premise, cpe


def setup_pending_provisioning_request(sg, cpe_overrides=None, premise_overrides=None, **tier_overrides):
    """Tier + premise + CPE + PENDING provisioning request.

    Returns dict: tier, premise, cpe, pr.
    """
    tier = create_tier(**tier_overrides)
    premise, cpe = setup_premise_with_cpe(
        sg, cpe_overrides=cpe_overrides, premise_overrides=premise_overrides
    )
    pr = create_provisioning_request(premise["id"], tier["id"], premise["version"])
    return {"tier": tier, "premise": premise, "cpe": cpe, "pr": pr}


def setup_validated_provisioning_request(sg, cpe_overrides=None, premise_overrides=None, **tier_overrides):
    """PENDING -> VALIDATED request (validate must succeed for the given setup)."""
    ctx = setup_pending_provisioning_request(
        sg, cpe_overrides=cpe_overrides, premise_overrides=premise_overrides, **tier_overrides
    )
    resp = api_client.validate_provisioning_request(ctx["pr"]["id"], PROVISIONING)
    ctx["pr"] = get_success_data(resp)
    return ctx
