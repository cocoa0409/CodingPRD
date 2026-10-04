"""Difficulty tests: transitive cascades (queue A).

  cutover_cascade_project_to_children_to_retirement_to_action — completion
    cascade / child topology and homes conservation
  reclaim_completion_cascade_blocks_capacity_posture — capacity hop / posture hop
"""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_block,
    create_franchise_area,
    create_node,
    create_sample,
    create_service_group,
    create_wave,
    get_node_split_project,
    get_service_group,
    get_success_data,
    set_clock,
    setup_legacy_cpe,
    setup_project_in_construction,
    setup_reclaim_action_in_progress,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ENGINEER = TEST_USERS["capacity_engineer_headers"]
FIELD_OPS = TEST_USERS["field_ops_coordinator_headers"]


def _setup_cutover_800_k2():
    """800-home node fully walked to IN_CONSTRUCTION with k=2, min 300, max 500."""
    set_clock("2026-10-01T00:00:00Z")
    fa = create_franchise_area(
        name="Metro East", region_code="ME",
        obligation_homes_required=5000, obligation_deadline="2027-06-30T00:00:00Z",
    )
    node = create_node(fa["id"], node_code="NE-X", homes_passed=800, downstream_spectrum_mhz=48)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-X", homes_passed=800)
    action, project = setup_project_in_construction(
        sg, child_count=2, min_homes=300, max_homes=500,
        window_start="2026-11-01T00:00:00Z", window_end="2026-11-05T00:00:00Z",
    )
    return fa, node, sg, action, project


def test_cutover_cascade_completes_project_action_and_retires_parent():
    """PRD §3.4: "The parent service group's `homes_passed` drops to 0 and its
    posture becomes `SPLIT_RETIRED`. The parent optical node's `status` becomes
    `SPLIT_RETIRED`. The parent capacity action auto-completes, moving to
    `COMPLETED` without an explicit completion call. The project itself lands in
    `COMPLETED`".

    Design: Difficulty/transitive_cascade/cutover_cascade_project_to_children_to_retirement_to_action
    """
    fa, node, sg, action, project = _setup_cutover_800_k2()

    resp = api_client.cutover_node_split_project(project["id"], FIELD_OPS)
    project = validate_success(resp)
    assert project["status"] == "COMPLETED"
    assert project["child_allocations"] == [400, 400]
    assert project["child_node_id"], "child_node_id must be recorded at cutover"
    assert len(project["child_service_group_ids"]) == 2

    action_now = get_success_data(api_client.get_capacity_action(action["id"], ADMIN))
    assert action_now["status"] == "COMPLETED", (
        "the parent action must auto-complete via the cascade, with no manual complete call"
    )
    node_now = validate_success(api_client.get_optical_node(node["id"], ADMIN))
    assert node_now["status"] == "SPLIT_RETIRED"
    sg_now = get_service_group(sg["id"])
    assert sg_now["posture"] == "SPLIT_RETIRED"
    assert sg_now["homes_passed"] == 0


def test_cutover_cascade_conserves_franchise_homes_progress():
    """PRD §2.10: "The area's `homes_built_progress` is computed on read as the
    sum of `homes_passed` over all service groups whose posture is not
    `SPLIT_RETIRED`, across every optical node of the area regardless of node
    status"."

    Design: Difficulty/transitive_cascade/cutover_cascade_project_to_children_to_retirement_to_action
    """
    fa, _, _, _, project = _setup_cutover_800_k2()

    validate_success(api_client.cutover_node_split_project(project["id"], FIELD_OPS))

    fa_now = validate_success(api_client.get_franchise_area(fa["id"], ADMIN))
    assert fa_now["homes_built_progress"] == 800, (
        "children 400+400 conserve the parent's 800 homes across the cascade"
    )


def _setup_reclaim_one_block_critical():
    """Node NE-R2 (VIDEO 24 x2 + DATA 48 = capacity 304), SG-R2 CRITICAL at
    115.1% from a 350-Mbps sample, reclaim targeting one video block walked to
    IN_PROGRESS with one wave EXECUTED."""
    set_clock("2026-10-01T00:00:00Z")
    fa = create_franchise_area(
        name="Metro East", region_code="ME",
        obligation_homes_required=5000, obligation_deadline="2027-06-30T00:00:00Z",
    )
    node = create_node(fa["id"], node_code="NE-R2", homes_passed=200, downstream_spectrum_mhz=96)
    v1 = create_block(node["id"], block_type="LEGACY_VIDEO", mhz=24)
    create_block(node["id"], block_type="LEGACY_VIDEO", mhz=24)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-R2", homes_passed=100)
    create_sample(sg["id"], 350)
    sg_now = get_service_group(sg["id"])
    action = setup_reclaim_action_in_progress(sg_now, [v1["id"]])
    _, cpe = setup_legacy_cpe(sg, premise_ref="P-R1", address="3 Oak Ave")
    w1 = create_wave(action["id"], [cpe["id"]], wave_code="W1",
                     window_start="2026-10-01T00:00:00Z", window_end="2026-10-02T00:00:00Z")
    get_success_data(api_client.execute_migration_wave(w1["id"], FIELD_OPS))
    return sg, action, v1


def test_reclaim_completion_flips_block_and_recomputes_capacity():
    """PRD §3.3: "Completing a reclaim moves each target block to `DATA_ACTIVE`,
    recomputes the affected service groups' `downstream_capacity_mbps`"."

    Design: Difficulty/transitive_cascade/reclaim_completion_cascade_blocks_capacity_posture
    """
    sg, action, v1 = _setup_reclaim_one_block_critical()

    resp = api_client.complete_capacity_action(action["id"], ENGINEER)
    action = validate_success(resp)
    assert action["status"] == "COMPLETED"

    block = validate_success(api_client.get_spectrum_block(v1["id"], ADMIN))
    assert block["status"] == "DATA_ACTIVE"
    assert block["capacity_mbps"] == 152

    sg_now = get_service_group(sg["id"])
    assert sg_now["downstream_capacity_mbps"] == 456, (
        f"304 + 152 = 456 after the target block flips, got {sg_now['downstream_capacity_mbps']}"
    )


def test_reclaim_completion_deescalates_posture_without_new_samples():
    """PRD §3.3: "recomputes posture, which may de-escalate the service group
    out of `CRITICAL`" and §3.2: "the same recomputation also runs — without a
    new sample — whenever the service group's `downstream_capacity_mbps`
    changes".

    Design: Difficulty/transitive_cascade/reclaim_completion_cascade_blocks_capacity_posture
    """
    sg, action, _ = _setup_reclaim_one_block_critical()

    sg_before = get_service_group(sg["id"])
    assert sg_before["posture"] == "CRITICAL"

    validate_success(api_client.complete_capacity_action(action["id"], ENGINEER))

    sg_after = get_service_group(sg["id"])
    assert sg_after["current_utilization_pct"] == 76.8
    assert sg_after["posture"] == "ELEVATED", (
        "posture must reflect the recomputed capacity, not the pre-completion value"
    )
