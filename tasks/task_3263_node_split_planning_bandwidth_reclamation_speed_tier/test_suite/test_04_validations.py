"""Validation-guard tests (Corner/validations instances)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_block,
    create_franchise_area,
    create_node,
    create_sample,
    create_service_group,
    create_tier,
    create_wave,
    get_service_group,
    get_success_data,
    set_clock,
    setup_legacy_cpe,
    setup_pending_provisioning_request,
    setup_premise_with_cpe,
    setup_proposed_action,
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


def test_existence_checked_before_state_on_unknown_action():
    """PRD §2.8: "then existence of path- and body-referenced resources
    (`ERR_NOT_FOUND`), then basic request shape — parseable body, required
    fields present, enum values legal (`ERR_VALIDATION`, HTTP 400) — then
    optimistic-concurrency version checks (`ERR_STALE_VERSION`), then
    lifecycle-state permissibility (`ERR_INVALID_STATE`, HTTP 409)".

    Design: Corner/validations/existence_checked_before_state_on_unknown_action
    """
    resp = api_client.approve_capacity_action(NON_EXISTENT_UUID, ENGINEER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_blackout_intersection_rejected_with_window_conflict():
    """PRD §3.4: "It may also not intersect any entry in the franchise area's
    `blackout_windows`, and blackout intervals are closed on both ends, so a
    construction window that merely touches a blackout's start or end instant
    does intersect it. Either calendar violation is rejected with
    `ERR_WINDOW_CONFLICT` (HTTP 409)."

    Design: Corner/validations/blackout_intersection_rejected_with_window_conflict
    """
    from test_helpers import grant_permit, setup_project_in_permit_review

    fa = create_franchise_area(
        blackout_windows=[{"start": "2026-12-24T00:00:00Z", "end": "2026-12-26T00:00:00Z"}]
    )
    node = create_node(fa["id"], node_code="NE-BO", homes_passed=600, downstream_spectrum_mhz=48)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-BO", homes_passed=600)
    action, project = setup_project_in_permit_review(sg)
    project = grant_permit(project["id"])

    resp = api_client.schedule_node_split_project(
        project["id"],
        {
            "window_start": "2026-12-20T00:00:00Z",
            "window_end": "2026-12-24T00:00:00Z",
            "expected_node_split_project_version": project["version"],
        },
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_CONFLICT)
    project = get_success_data(api_client.get_node_split_project(project["id"], ADMIN))
    assert project["status"] == "PERMIT_GRANTED"


def test_provisioning_create_blocked_while_service_group_critical():
    """PRD §3.7: "Creation is blocked outright while the premise's service
    group posture is `CRITICAL` — a congested service group takes no new sales,
    and the attempt is rejected with `ERR_SG_CONGESTED` (HTTP 409)."

    Design: Corner/validations/provisioning_create_blocked_while_service_group_critical
    """
    set_clock("2026-10-01T00:00:00Z")
    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-CR", homes_passed=100, downstream_spectrum_mhz=48)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-CR", homes_passed=100)
    create_sample(sg["id"], 300)  # 300*100/304 = 98.7% -> CRITICAL
    tier = create_tier(tier_code="LITE", downstream_mbps=10, upstream_mbps=2,
                       min_capability_class="D30", min_upstream_config="LEGACY")
    premise, _ = setup_premise_with_cpe(sg)

    resp = api_client.create_provisioning_request(
        premise["id"],
        {"speed_tier_id": tier["id"], "expected_customer_premise_version": premise["version"]},
        PROVISIONING,
    )
    validate_error(resp, ApiErrorId.ERR_SG_CONGESTED)

    resp = api_client.list_provisioning_requests(ADMIN, params={"customer_premise_id": premise["id"]})
    data, _ = validate_paginated(resp)
    assert data == [], "no provisioning request may be created while the service group is CRITICAL"


def test_reclaim_targeting_all_video_blocks_rejected():
    """PRD §3.3: "a proposal that would target every remaining video block is
    rejected with `ERR_LAST_VIDEO_BLOCK` (HTTP 422)".

    Design: Corner/validations/reclaim_targeting_all_video_blocks_rejected
    """
    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-LV", homes_passed=100, downstream_spectrum_mhz=96)
    v1 = create_block(node["id"], block_type="LEGACY_VIDEO", mhz=24)
    v2 = create_block(node["id"], block_type="LEGACY_VIDEO", mhz=24)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-LV", homes_passed=100)

    resp = api_client.create_capacity_action(
        sg["id"],
        {
            "action_type": "SPECTRUM_RECLAIM",
            "target_block_ids": [v1["id"], v2["id"]],
            "expected_service_group_version": sg["version"],
        },
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_LAST_VIDEO_BLOCK)

    resp = api_client.list_capacity_actions(sg["id"], ADMIN)
    data, _ = validate_paginated(resp)
    assert data == [], "no capacity action may be created when the last video block would be targeted"


def test_homes_sum_over_node_total_rejected():
    """PRD §2.10: "the homes served by a node's non-retired service groups may
    never exceed the node's own `homes_passed`; creating a service group that
    would breach this is rejected with `ERR_HOMES_EXCEED_NODE` (HTTP 422)".

    Design: Corner/validations/homes_sum_over_node_total_rejected
    """
    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-HS", homes_passed=600, downstream_spectrum_mhz=48)
    create_block(node["id"], block_type="DATA", mhz=48)
    create_service_group(node["id"], sg_code="SG-A", homes_passed=300)

    resp = api_client.create_service_group(
        node["id"],
        {
            "sg_code": "SG-B",
            "homes_passed": 400,
            "warn_threshold_pct": 70,
            "critical_threshold_pct": 85,
            "utilization_method": "PEAK_PCT95",
        },
        ENGINEER,
    )
    validate_error(resp, ApiErrorId.ERR_HOMES_EXCEED_NODE)


def test_spectrum_overallocation_rejected():
    """PRD §2.9: "the sum of block widths on a node may never exceed the node's
    declared spectrum, and a block creation that would push the sum past the
    limit is rejected with `ERR_SPECTRUM_OVERALLOCATED` (HTTP 422)".

    Design: Corner/validations/spectrum_overallocation_rejected
    """
    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-SO", homes_passed=100, downstream_spectrum_mhz=96)
    create_block(node["id"], block_type="DATA", mhz=48)
    create_block(node["id"], block_type="LEGACY_VIDEO", mhz=24)

    resp = api_client.create_spectrum_block(node["id"], {"block_type": "DATA", "mhz": 30}, ENGINEER)
    validate_error(resp, ApiErrorId.ERR_SPECTRUM_OVERALLOCATED)


def test_upgrade_path_two_steps_rejected():
    """PRD §3.3: "`target_upstream_config` must be exactly one step above the
    node's current `upstream_config` — `LEGACY` upgrades only to `MID_SPLIT`,
    and `MID_SPLIT` only to `HIGH_SPLIT`; anything else is rejected with
    `ERR_UPGRADE_PATH_INVALID` (HTTP 422)."

    Design: Corner/validations/upgrade_path_two_steps_rejected
    """
    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-UP", homes_passed=100, downstream_spectrum_mhz=48)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-UP", homes_passed=100)

    resp = api_client.create_capacity_action(
        sg["id"],
        {
            "action_type": "HIGH_SPLIT_UPGRADE",
            "target_upstream_config": "HIGH_SPLIT",
            "expected_service_group_version": sg["version"],
        },
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_UPGRADE_PATH_INVALID)


def test_tier_requiring_mid_split_upstream_rejected_on_legacy_node():
    """PRD §3.7: "Third, the serving node's `upstream_config` must rank at or
    above the tier's `min_upstream_config` under the ordering `LEGACY` below
    `MID_SPLIT` below `HIGH_SPLIT` (else `ERR_UPSTREAM_CONFIG_INSUFFICIENT`,
    HTTP 422)."

    Design: Corner/validations/tier_requiring_mid_split_upstream_rejected_on_legacy_node
    """
    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-UC", homes_passed=100, downstream_spectrum_mhz=48)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-UC", homes_passed=100)
    ctx = setup_pending_provisioning_request(
        sg,
        tier_code="FAST50",
        downstream_mbps=50,
        upstream_mbps=10,
        min_capability_class="D30",
        min_upstream_config="MID_SPLIT",
    )

    resp = api_client.validate_provisioning_request(ctx["pr"]["id"], PROVISIONING)
    validate_error(resp, ApiErrorId.ERR_UPSTREAM_CONFIG_INSUFFICIENT)
    pr = validate_success(api_client.get_provisioning_request(ctx["pr"]["id"], ADMIN))
    assert pr["status"] == "FAILED"
    assert pr["failure_reason"] == "ERR_UPSTREAM_CONFIG_INSUFFICIENT"


def test_child_entity_under_wrong_action_type_rejected():
    """PRD §3.4: "filing one under any other action type is rejected with
    `ERR_ACTION_TYPE_MISMATCH` (HTTP 422)".

    Design: Corner/validations/child_entity_under_wrong_action_type_rejected
    """
    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-TM", homes_passed=100, downstream_spectrum_mhz=96)
    v1 = create_block(node["id"], block_type="LEGACY_VIDEO", mhz=24)
    create_block(node["id"], block_type="LEGACY_VIDEO", mhz=24)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-TM", homes_passed=100)
    action = setup_proposed_action(sg, action_type="SPECTRUM_RECLAIM", target_block_ids=[v1["id"]])

    resp = api_client.create_node_split_project(
        action["id"],
        {"child_count": 2, "min_homes_per_child": 100, "max_homes_per_child": 300},
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_ACTION_TYPE_MISMATCH)


def test_wave_execute_with_already_migrated_cpe_rejected():
    """PRD §3.5: "Execution requires the parent capacity action to be
    `IN_PROGRESS` (else `ERR_INVALID_STATE`) and requires every id in
    `target_cpe_ids` to name equipment that exists, is `ACTIVE`, and still has
    `video_legacy` true; a target that is missing, retired, or already migrated
    is rejected with `ERR_CPE_NOT_ELIGIBLE` (HTTP 422)."

    Design: Corner/validations/wave_execute_with_already_migrated_cpe_rejected
    """
    set_clock("2026-09-25T00:00:00Z")
    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-WX", homes_passed=100, downstream_spectrum_mhz=96)
    v1 = create_block(node["id"], block_type="LEGACY_VIDEO", mhz=24)
    create_block(node["id"], block_type="LEGACY_VIDEO", mhz=24)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-WX", homes_passed=100)
    action = setup_reclaim_action_in_progress(sg, [v1["id"]])
    premise, _ = setup_premise_with_cpe(
        sg,
        cpe_overrides={
            "model": "XB7",
            "docsis_version": "3.1",
            "capability_class": "D31",
            "max_downstream_mbps": 800,
            "video_legacy": False,
        },
        premise_overrides={"premise_ref": "P-WX1", "address": "1 Wave Ct"},
    )
    cpe_resp = api_client.list_equipment(premise["id"], ADMIN)
    cpe_list, _ = validate_paginated(cpe_resp)
    cpe_id = cpe_list[0]["id"]
    wave = create_wave(action["id"], [cpe_id], wave_code="W1")

    resp = api_client.execute_migration_wave(wave["id"], FIELD_OPS)
    validate_error(resp, ApiErrorId.ERR_CPE_NOT_ELIGIBLE)
    wave = validate_success(api_client.get_migration_wave(wave["id"], ADMIN))
    assert wave["status"] == "PLANNED"
