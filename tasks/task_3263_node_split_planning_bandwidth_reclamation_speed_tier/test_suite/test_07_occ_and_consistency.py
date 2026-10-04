"""Optimistic concurrency, derived-field reconciliation, and immediate
consistency tests (Corner/cross_cutting + Corner/consistency_model)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_block,
    create_franchise_area,
    create_node,
    create_service_group,
    create_tier,
    create_wave,
    get_service_group,
    get_success_data,
    set_clock,
    setup_legacy_cpe,
    setup_premise_with_cpe,
    setup_proposed_action,
    setup_project_in_construction,
    setup_project_in_permit_review,
    setup_reclaim_action_in_progress,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["network_planner_headers"]
ENGINEER = TEST_USERS["capacity_engineer_headers"]
FIELD_OPS = TEST_USERS["field_ops_coordinator_headers"]
PROVISIONING = TEST_USERS["provisioning_agent_headers"]
FRANCHISE_ADMIN = TEST_USERS["franchise_admin_headers"]


def test_occ_stale_service_group_version_on_action_create():
    """PRD §2.7: "a mismatch with the parent's current `version` is rejected
    with `ERR_STALE_VERSION` (HTTP 412)." and §3.3: "The creation itself is a
    mutation on the service group, incrementing its `version`."

    Design: Corner/cross_cutting/occ_stale_service_group_version_on_action_create
    """
    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-OCC", homes_passed=100, downstream_spectrum_mhz=48)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-OCC", homes_passed=100)
    ca1 = setup_proposed_action(sg, action_type="NODE_SPLIT")

    resp = api_client.create_capacity_action(
        sg["id"],
        {
            "action_type": "MID_SPLIT_UPGRADE",
            "target_upstream_config": "MID_SPLIT",
            "expected_service_group_version": sg["version"],
        },
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    resp = api_client.list_capacity_actions(sg["id"], ADMIN)
    data, _ = validate_paginated(resp)
    assert len(data) == 1, "the stale create must not supersede or add actions"


def test_occ_stale_premise_version_on_provisioning_create():
    """PRD §2.7: "a mismatch with the parent's current `version` is rejected
    with `ERR_STALE_VERSION` (HTTP 412)." and §3.7: "the creation increments
    the premise's `version`".

    Design: Corner/cross_cutting/occ_stale_premise_version_on_provisioning_create
    """
    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-OC2", homes_passed=100, downstream_spectrum_mhz=48)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-OC2", homes_passed=100)
    tier = create_tier(tier_code="T10", downstream_mbps=10, upstream_mbps=2)
    premise, _ = setup_premise_with_cpe(sg, premise_overrides={"premise_ref": "P-OCC", "address": "1 Version Ave"})

    resp = api_client.create_provisioning_request(
        premise["id"],
        {"speed_tier_id": tier["id"], "expected_customer_premise_version": premise["version"]},
        PROVISIONING,
    )
    get_success_data(resp)

    resp = api_client.create_provisioning_request(
        premise["id"],
        {"speed_tier_id": tier["id"], "expected_customer_premise_version": premise["version"]},
        PROVISIONING,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_occ_stale_project_version_on_schedule():
    """PRD §2.7: "a mismatch with the parent's current `version` is rejected
    with `ERR_STALE_VERSION` (HTTP 412)." — the schedule call carries the
    mandatory OCC field `expected_node_split_project_version` (PRD §2.7).

    Design: Corner/cross_cutting/occ_stale_project_version_on_schedule
    """
    from test_helpers import grant_permit

    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-OC3", homes_passed=600, downstream_spectrum_mhz=48)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-OC3", homes_passed=600)
    _, project = setup_project_in_permit_review(sg)
    stale_version = project["version"]
    project = grant_permit(project["id"])  # adjudication advances the version
    assert project["version"] != stale_version

    resp = api_client.schedule_node_split_project(
        project["id"],
        {
            "window_start": "2026-11-01T00:00:00Z",
            "window_end": "2026-11-05T00:00:00Z",
            "expected_node_split_project_version": stale_version,
        },
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    project = get_success_data(api_client.get_node_split_project(project["id"], ADMIN))
    assert project["status"] == "PERMIT_GRANTED"


def test_derived_fields_reconcile_after_block_reclaim_and_cancel():
    """PRD §2.9: "A service group's `downstream_capacity_mbps` is the sum of
    `capacity_mbps` over the parent node's `DATA_ACTIVE` blocks." and §3.3:
    "Completing a reclaim moves each target block to `DATA_ACTIVE`, recomputes
    the affected service groups' `downstream_capacity_mbps`".

    Design: Corner/cross_cutting/derived_fields_reconcile_after_block_reclaim_and_cancel
    """
    set_clock("2026-09-25T00:00:00Z")
    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-DR", homes_passed=100, downstream_spectrum_mhz=96)
    v1 = create_block(node["id"], block_type="LEGACY_VIDEO", mhz=24)
    v2 = create_block(node["id"], block_type="LEGACY_VIDEO", mhz=24)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-DR", homes_passed=100)
    action = setup_reclaim_action_in_progress(sg, [v1["id"]])
    _, cpe = setup_legacy_cpe(sg, premise_ref="P-DR1", address="1 Derive Dr")
    wave = create_wave(action["id"], [cpe["id"]], wave_code="W1")
    get_success_data(api_client.execute_migration_wave(wave["id"], FIELD_OPS))

    sg_now = get_service_group(sg["id"])
    assert sg_now["downstream_capacity_mbps"] == 304, (
        "RECLAIM_PENDING blocks contribute 0 capacity before completion"
    )

    get_success_data(api_client.complete_capacity_action(action["id"], ENGINEER))
    sg_now = get_service_group(sg["id"])
    assert sg_now["downstream_capacity_mbps"] == 456, (
        f"completing the reclaim adds floor(24/6)*38 = 152 Mbps, got {sg_now['downstream_capacity_mbps']}"
    )

    v2_now = validate_success(api_client.get_spectrum_block(v2["id"], ADMIN))
    assert v2_now["status"] == "VIDEO_ACTIVE"


def test_immediate_consistency_cutover_visible_in_same_reads():
    """PRD §3.4: "A new child optical node is created whose `node_code` is the
    parent's code suffixed with `-S1`, inheriting the parent's
    `downstream_spectrum_mhz` and `upstream_config`" and "The parent capacity
    action auto-completes, moving to `COMPLETED` without an explicit completion
    call."

    Design: Corner/consistency_model/immediate_consistency_cutover_visible_in_same_reads
    """
    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-IM2", homes_passed=600, downstream_spectrum_mhz=48)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-IM2", homes_passed=600)
    action, project = setup_project_in_construction(sg)

    resp = api_client.cutover_node_split_project(project["id"], FIELD_OPS)
    project = validate_success(resp)
    assert project["child_node_id"], "cutover response must carry child_node_id"
    assert len(project["child_service_group_ids"]) == 2

    resp = api_client.list_optical_nodes(fa["id"], ADMIN)
    nodes, _ = validate_paginated(resp)
    assert len(nodes) == 2
    by_code = {n["node_code"]: n for n in nodes}
    assert by_code["NE-IM2"]["status"] == "SPLIT_RETIRED"
    assert by_code["NE-IM2-S1"]["status"] == "ACTIVE"

    action_now = get_success_data(api_client.get_capacity_action(action["id"], ADMIN))
    assert action_now["status"] == "COMPLETED"
