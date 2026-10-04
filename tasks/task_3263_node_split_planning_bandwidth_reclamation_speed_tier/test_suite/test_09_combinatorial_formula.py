"""Difficulty tests: combinatorial formulas (queue A, rule combinatorial_formula).

  node_split_homes_waterfall_with_clamps — waterfall value + cutover effects
  spectrum_reclaim_per_block_rounding_order — rounding order + reclaim lifecycle
  tier_projection_pinned_evaluation_order — boundary reject / pass
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_block,
    create_franchise_area,
    create_node,
    create_sample,
    create_service_group,
    create_tier,
    create_wave,
    get_node_split_project,
    get_service_group,
    get_success_data,
    set_clock,
    setup_legacy_cpe,
    setup_project_in_construction,
    setup_reclaim_action_in_progress,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ENGINEER = TEST_USERS["capacity_engineer_headers"]
FIELD_OPS = TEST_USERS["field_ops_coordinator_headers"]
PROVISIONING = TEST_USERS["provisioning_agent_headers"]


def _setup_split_1000_k3_min200_max400():
    """1000-home node fully walked to IN_CONSTRUCTION with k=3, min 200, max 400."""
    set_clock("2026-10-01T00:00:00Z")
    fa = create_franchise_area(
        name="Metro East", region_code="ME",
        obligation_homes_required=5000, obligation_deadline="2027-06-30T00:00:00Z",
    )
    node = create_node(fa["id"], node_code="NE-S", homes_passed=1000, downstream_spectrum_mhz=48)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-SPLIT", homes_passed=1000)
    action, project = setup_project_in_construction(
        sg, child_count=3, min_homes=200, max_homes=400,
        window_start="2026-11-01T00:00:00Z", window_end="2026-11-10T00:00:00Z",
    )
    return fa, node, sg, action, project


def test_cutover_waterfall_allocation_values_333_333_334():
    """PRD §3.4: "for each child, the remaining homes are divided by the number
    of children not yet allocated (including this one), truncated down to a
    whole number, and the result is clamped — raised to `min_homes_per_child` if
    below it, capped at `max_homes_per_child` if above it — before being
    subtracted from the remainder. The final child receives whatever remains"
    and "1000 homes across 3 children with bounds 200–400 allocates 333, 333,
    and 334".

    Design: Difficulty/combinatorial_formula/node_split_homes_waterfall_with_clamps
    """
    _, _, _, _, project = _setup_split_1000_k3_min200_max400()

    resp = api_client.cutover_node_split_project(project["id"], FIELD_OPS)
    project = validate_success(resp)
    assert project["status"] == "COMPLETED"
    assert project["child_allocations"] == [333, 333, 334]
    assert sum(project["child_allocations"]) == 1000
    assert len(project["child_service_group_ids"]) == 3


def test_cutover_waterfall_retires_parent_and_completes_action():
    """PRD §3.4: "The parent service group's `homes_passed` drops to 0 and its
    posture becomes `SPLIT_RETIRED`. The parent optical node's `status` becomes
    `SPLIT_RETIRED`. The parent capacity action auto-completes, moving to
    `COMPLETED` without an explicit completion call."

    Design: Difficulty/combinatorial_formula/node_split_homes_waterfall_with_clamps
    """
    _, node, sg, action, project = _setup_split_1000_k3_min200_max400()

    validate_success(api_client.cutover_node_split_project(project["id"], FIELD_OPS))

    sg_now = get_service_group(sg["id"])
    assert sg_now["posture"] == "SPLIT_RETIRED"
    assert sg_now["homes_passed"] == 0
    node_now = validate_success(api_client.get_optical_node(node["id"], ADMIN))
    assert node_now["status"] == "SPLIT_RETIRED"
    action_now = get_success_data(api_client.get_capacity_action(action["id"], ADMIN))
    assert action_now["status"] == "COMPLETED"


def _setup_reclaim_21_and_15():
    """Node NE-R (VIDEO 21 + VIDEO 15 + VIDEO 24 + DATA 60 = capacity 380),
    SG-R at CRITICAL from a 480-Mbps sample, MANUAL reclaim targeting the 21- and
    15-MHz video blocks walked to IN_PROGRESS with both waves EXECUTED."""
    set_clock("2026-10-01T00:00:00Z")
    fa = create_franchise_area(
        name="Metro East", region_code="ME",
        obligation_homes_required=5000, obligation_deadline="2027-06-30T00:00:00Z",
    )
    node = create_node(fa["id"], node_code="NE-R", homes_passed=300, downstream_spectrum_mhz=120)
    v21 = create_block(node["id"], block_type="LEGACY_VIDEO", mhz=21)
    v15 = create_block(node["id"], block_type="LEGACY_VIDEO", mhz=15)
    create_block(node["id"], block_type="LEGACY_VIDEO", mhz=24)
    create_block(node["id"], block_type="DATA", mhz=60)
    sg = create_service_group(node["id"], sg_code="SG-R", homes_passed=100)
    create_sample(sg["id"], 480)
    sg_now = get_service_group(sg["id"])
    action = setup_reclaim_action_in_progress(sg_now, [v21["id"], v15["id"]])
    _, cpe1 = setup_legacy_cpe(sg, premise_ref="P-R1", address="2 Oak Ave")
    _, cpe2 = setup_legacy_cpe(sg, premise_ref="P-R2", address="4 Oak Ave")
    w1 = create_wave(action["id"], [cpe1["id"]], wave_code="W1",
                     window_start="2026-10-01T00:00:00Z", window_end="2026-10-02T00:00:00Z")
    w2 = create_wave(action["id"], [cpe2["id"]], wave_code="W2",
                     window_start="2026-10-10T00:00:00Z", window_end="2026-10-11T00:00:00Z")
    get_success_data(api_client.execute_migration_wave(w1["id"], FIELD_OPS))
    get_success_data(api_client.execute_migration_wave(w2["id"], FIELD_OPS))
    return sg, action, v21, v15


def test_reclaim_completion_applies_per_block_truncation_order():
    """PRD §2.9: "The truncation order is authoritative: a node holding a 21 MHz
    block and a 15 MHz block yields 3 channels (114 Mbps) plus 2 channels
    (76 Mbps) for 190 Mbps — not 228 Mbps, which is what summing the widths
    first would produce."

    Design: Difficulty/combinatorial_formula/spectrum_reclaim_per_block_rounding_order
    """
    sg, action, v21, v15 = _setup_reclaim_21_and_15()

    resp = api_client.complete_capacity_action(action["id"], ENGINEER)
    action = validate_success(resp)
    assert action["status"] == "COMPLETED"

    b21 = validate_success(api_client.get_spectrum_block(v21["id"], ADMIN))
    b15 = validate_success(api_client.get_spectrum_block(v15["id"], ADMIN))
    assert b21["status"] == "DATA_ACTIVE"
    assert b15["status"] == "DATA_ACTIVE"

    sg_now = get_service_group(sg["id"])
    assert sg_now["downstream_capacity_mbps"] == 570, (
        f"380 + 114 + 76 = 570 per-block, got {sg_now['downstream_capacity_mbps']}"
    )


def test_reclaim_completion_recomputes_posture_downward():
    """PRD §3.3: "Completing a reclaim moves each target block to `DATA_ACTIVE`,
    recomputes the affected service groups' `downstream_capacity_mbps`, and
    recomputes posture, which may de-escalate the service group out of
    `CRITICAL`."

    Design: Difficulty/combinatorial_formula/spectrum_reclaim_per_block_rounding_order
    """
    sg, action, _, _ = _setup_reclaim_21_and_15()

    sg_before = get_service_group(sg["id"])
    assert sg_before["posture"] == "CRITICAL"

    validate_success(api_client.complete_capacity_action(action["id"], ENGINEER))

    sg_after = get_service_group(sg["id"])
    assert sg_after["current_utilization_pct"] == 84.2
    assert sg_after["posture"] == "ELEVATED", (
        "posture must de-escalate from CRITICAL to ELEVATED from the capacity increase alone"
    )


def _setup_projection_boundary():
    """SG-B capacity 760, load 600 (ELEVATED at 78.9%); the per-test tier and
    premise are built inline by each test."""
    set_clock("2026-10-01T00:00:00Z")
    fa = create_franchise_area(
        name="Metro East", region_code="ME",
        obligation_homes_required=5000, obligation_deadline="2027-06-30T00:00:00Z",
    )
    node = create_node(fa["id"], node_code="NE-B", homes_passed=800, downstream_spectrum_mhz=168)
    create_block(node["id"], block_type="DATA", mhz=60)
    create_block(node["id"], block_type="DATA", mhz=60)
    create_block(node["id"], block_type="LEGACY_VIDEO", mhz=24)
    create_block(node["id"], block_type="LEGACY_VIDEO", mhz=24)
    sg = create_service_group(node["id"], sg_code="SG-B", homes_passed=300)
    create_sample(sg["id"], 600)
    return sg


def _build_request(sg, tier_kwargs, premise_ref, address):
    tier = create_tier(**tier_kwargs)
    cp = get_success_data(api_client.create_customer_premise(
        sg["id"], {"premise_ref": premise_ref, "address": address}, PROVISIONING))
    get_success_data(api_client.create_equipment(
        cp["id"], {"model": "XB8", "docsis_version": "4.0", "capability_class": "D40",
                    "max_downstream_mbps": 1000, "video_legacy": False}, PROVISIONING))
    return get_success_data(api_client.create_provisioning_request(
        cp["id"], {"speed_tier_id": tier["id"], "expected_customer_premise_version": cp["version"]},
        PROVISIONING))


def test_tier_projection_rejects_exactly_on_the_critical_line():
    """PRD §3.7: "reject with `ERR_CAPACITY_EXCEEDED` (HTTP 422) when the
    projected load multiplied by 100 reaches or exceeds `critical_threshold_pct`
    times the capacity — landing exactly on the critical line rejects".

    Design: Difficulty/combinatorial_formula/tier_projection_pinned_evaluation_order
    """
    sg = _setup_projection_boundary()
    pr1 = _build_request(
        sg,
        dict(tier_code="T46", downstream_mbps=46, upstream_mbps=10,
             min_capability_class="D40", min_upstream_config="LEGACY"),
        "P-B1", "6 Elm St",
    )

    resp = api_client.validate_provisioning_request(pr1["id"], PROVISIONING)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)
    pr1_now = validate_success(api_client.get_provisioning_request(pr1["id"], ADMIN))
    assert pr1_now["status"] == "FAILED"
    assert pr1_now["failure_reason"] == "ERR_CAPACITY_EXCEEDED"


def test_tier_projection_accepts_one_mbps_below_the_line_and_generates_config():
    """PRD §3.7: "A request that passes every check moves `PENDING → VALIDATED`,
    and the modem configuration file is generated as `config_file_content` in
    the exact format
    `TIER=<tier_code>;DS=<downstream_mbps>;US=<upstream_mbps>;CPE=<capability_class>`."

    Design: Difficulty/combinatorial_formula/tier_projection_pinned_evaluation_order
    """
    sg = _setup_projection_boundary()
    pr2 = _build_request(
        sg,
        dict(tier_code="T45", downstream_mbps=45, upstream_mbps=10,
             min_capability_class="D40", min_upstream_config="LEGACY"),
        "P-B2", "8 Elm St",
    )

    resp = api_client.validate_provisioning_request(pr2["id"], PROVISIONING)
    pr2_now = validate_success(resp)
    assert pr2_now["status"] == "VALIDATED"
    assert pr2_now["config_file_content"] == "TIER=T45;DS=45;US=10;CPE=D40"
