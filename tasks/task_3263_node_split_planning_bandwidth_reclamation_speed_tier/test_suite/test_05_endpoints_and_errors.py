"""Endpoint-surface and error-catalog tests (Corner/endpoints + Corner/errors)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_block,
    create_franchise_area,
    create_node,
    create_service_group,
    get_node_split_project,
    get_service_group,
    get_success_data,
    setup_completed_upgrade,
    setup_legacy_cpe,
    setup_project_in_construction,
    setup_proposed_action,
    setup_reclaim_action_in_progress,
    setup_service_group,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["network_planner_headers"]
ENGINEER = TEST_USERS["capacity_engineer_headers"]
FIELD_OPS = TEST_USERS["field_ops_coordinator_headers"]
PROVISIONING = TEST_USERS["provisioning_agent_headers"]


def test_utilization_ingest_is_computed_read_via_service_group_get():
    """PRD §3.1: "A new service group's `posture` is `NORMAL`, its
    `downstream_capacity_mbps` is the sum over the node's `DATA_ACTIVE` blocks,
    its `upstream_capacity_mbps` comes from the node's upstream lookup, and its
    `provisioned_downstream_mbps` is the sum of the provisioned downstream rates
    of its premises, starting at 0." and §3.2: "If the window is empty,
    `current_load_mbps` is 0."

    Design: Corner/endpoints/utilization_ingest_is_computed_read_via_service_group_get
    """
    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-RD", homes_passed=100, downstream_spectrum_mhz=48)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-RD", homes_passed=100)

    resp = api_client.get_service_group(sg["id"], ADMIN)
    data = validate_success(resp)
    assert data["downstream_capacity_mbps"] == 304
    assert data["upstream_capacity_mbps"] == 27
    assert data["current_load_mbps"] == 0
    assert data["current_utilization_pct"] == 0.0
    assert data["posture"] == "NORMAL"
    assert data["provisioned_downstream_mbps"] == 0


def test_capacity_action_create_supersedes_existing_proposed_action():
    """PRD §3.3: "Creating a new action supersedes any existing `PROPOSED`
    action of the same service group: the older one is cancelled and its
    `superseded_by_id` is set to the newer action's id." and "Manually created
    actions carry `origin` `MANUAL` and start in `PROPOSED`."

    Design: Corner/endpoints/capacity_action_create_supersedes_existing_proposed_action
    """
    ctx = setup_service_group(sg_code="SG-SUP", sg_homes=100, node_homes=100, node_code="NE-SUP")
    ca1 = setup_proposed_action(ctx["sg"], action_type="NODE_SPLIT")
    sg_now = get_service_group(ctx["sg"]["id"])

    resp = api_client.create_capacity_action(
        ctx["sg"]["id"],
        {
            "action_type": "MID_SPLIT_UPGRADE",
            "target_upstream_config": "MID_SPLIT",
            "expected_service_group_version": sg_now["version"],
        },
        PLANNER,
    )
    ca2 = get_success_data(resp)

    ca1_now = get_success_data(api_client.get_capacity_action(ca1["id"], ADMIN))
    assert ca1_now["status"] == "CANCELLED"
    assert ca1_now["superseded_by_id"] == ca2["id"]
    assert ca2["status"] == "PROPOSED"
    assert ca2["origin"] == "MANUAL"


def test_refresh_campaign_launch_counts_targeted_and_swap_credits_it():
    """PRD §3.8: "Launching moves it `DRAFT → LAUNCHED` and computes
    `targeted_count`: the number of `ACTIVE` equipment units anywhere in the
    franchise area whose `capability_class` ranks strictly below the campaign's
    `target_capability_class`. From then on, every swap that names the campaign
    through `refresh_campaign_id` — while it remains `LAUNCHED` — advances
    `swapped_count` by 1." and §3.6: "starts `ACTIVE`, and inherits
    `video_legacy` from the retired unit."

    Design: Corner/endpoints/refresh_campaign_launch_counts_targeted_and_swap_credits_it
    """
    ctx = setup_service_group(sg_code="SG-RC", sg_homes=100, node_homes=100, node_code="NE-RC")
    sg = ctx["sg"]
    fa = ctx["fa"]

    cp1 = get_success_data(api_client.create_customer_premise(
        sg["id"], {"premise_ref": "P-RC1", "address": "1 Refresh Rd"}, PROVISIONING))
    cpe1 = get_success_data(api_client.create_equipment(
        cp1["id"], {"model": "SB6183", "docsis_version": "3.0", "capability_class": "D30",
                    "max_downstream_mbps": 300, "video_legacy": True}, PROVISIONING))
    cp2 = get_success_data(api_client.create_customer_premise(
        sg["id"], {"premise_ref": "P-RC2", "address": "2 Refresh Rd"}, PROVISIONING))
    cpe2 = get_success_data(api_client.create_equipment(
        cp2["id"], {"model": "SB6183", "docsis_version": "3.0", "capability_class": "D30",
                    "max_downstream_mbps": 300, "video_legacy": True}, PROVISIONING))
    cp3 = get_success_data(api_client.create_customer_premise(
        sg["id"], {"premise_ref": "P-RC3", "address": "3 Refresh Rd"}, PROVISIONING))
    get_success_data(api_client.create_equipment(
        cp3["id"], {"model": "XB8", "docsis_version": "4.0", "capability_class": "D40",
                    "max_downstream_mbps": 1000, "video_legacy": False}, PROVISIONING))

    rc = get_success_data(api_client.create_refresh_campaign(
        fa["id"], {"campaign_code": "RC1", "target_capability_class": "D31"}, PROVISIONING))

    resp = api_client.launch_refresh_campaign(rc["id"], PROVISIONING)
    rc = validate_success(resp)
    assert rc["targeted_count"] == 2, "only the two D30 units rank strictly below D31"

    new_unit = validate_success(api_client.swap_equipment(
        cpe1["id"],
        {"model": "XB7", "docsis_version": "3.1", "capability_class": "D31",
         "max_downstream_mbps": 800, "refresh_campaign_id": rc["id"]},
        PROVISIONING,
    ), expected_status=201)
    validate_success(api_client.swap_equipment(
        cpe2["id"],
        {"model": "XB7", "docsis_version": "3.1", "capability_class": "D31", "max_downstream_mbps": 800},
        PROVISIONING,
    ), expected_status=201)

    rc = validate_success(api_client.get_refresh_campaign(rc["id"], ADMIN))
    assert rc["swapped_count"] == 1, "only the swap carrying refresh_campaign_id credits the campaign"

    old_unit = validate_success(api_client.get_equipment(cpe1["id"], ADMIN))
    assert old_unit["status"] == "RETIRED"
    assert new_unit["status"] == "ACTIVE"
    assert new_unit["capability_class"] == "D31"
    assert new_unit["video_legacy"] is True, "the replacement inherits video_legacy from the retired unit"


def test_swap_referencing_draft_campaign_rejected():
    """PRD §3.6: "If the swap supplies a `refresh_campaign_id`, the named
    campaign must be `LAUNCHED` — otherwise the swap is rejected with
    `ERR_CAMPAIGN_NOT_LAUNCHED` (HTTP 409)".

    Design: Corner/endpoints/swap_referencing_draft_campaign_rejected
    """
    ctx = setup_service_group(sg_code="SG-RC2", sg_homes=100, node_homes=100, node_code="NE-RC2")
    cp = get_success_data(api_client.create_customer_premise(
        ctx["sg"]["id"], {"premise_ref": "P-RC9", "address": "9 Refresh Rd"}, PROVISIONING))
    cpe = get_success_data(api_client.create_equipment(
        cp["id"], {"model": "SB6183", "docsis_version": "3.0", "capability_class": "D30",
                   "max_downstream_mbps": 300, "video_legacy": True}, PROVISIONING))
    rc = get_success_data(api_client.create_refresh_campaign(
        ctx["fa"]["id"], {"campaign_code": "RC2", "target_capability_class": "D31"}, PROVISIONING))

    resp = api_client.swap_equipment(
        cpe["id"],
        {"model": "XB7", "docsis_version": "3.1", "capability_class": "D31",
         "max_downstream_mbps": 800, "refresh_campaign_id": rc["id"]},
        PROVISIONING,
    )
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_LAUNCHED)

    cpe_now = validate_success(api_client.get_equipment(cpe["id"], ADMIN))
    assert cpe_now["status"] == "ACTIVE"


def test_error_node_retired_blocks_new_service_group():
    """PRD §3.1: "no new blocks, service groups, or capacity actions may be
    created against a `SPLIT_RETIRED` node, and attempts are rejected with
    `ERR_NODE_RETIRED` (HTTP 409)."

    Design: Corner/errors/error_node_retired_blocks_new_service_group
    """
    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-NR", homes_passed=600, downstream_spectrum_mhz=48)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-NR", homes_passed=600)
    _, project = setup_project_in_construction(sg)
    validate_success(api_client.cutover_node_split_project(project["id"], FIELD_OPS))

    resp = api_client.create_service_group(
        node["id"],
        {
            "sg_code": "SG-LATE",
            "homes_passed": 10,
            "warn_threshold_pct": 70,
            "critical_threshold_pct": 85,
            "utilization_method": "PEAK_PCT95",
        },
        ENGINEER,
    )
    validate_error(resp, ApiErrorId.ERR_NODE_RETIRED)


def test_error_permit_not_granted_alias_of_state_guard():
    """PRD §3.4: "the permit state must be `PERMIT_GRANTED` (a project in any
    other state is rejected — surfaced as `ERR_PERMIT_NOT_GRANTED`, HTTP 409,
    the scheduling-specific face of the lifecycle guard)".

    Design: Corner/errors/error_permit_not_granted_alias_of_state_guard
    """
    from test_helpers import deny_permit, setup_project_in_permit_review

    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-PM", homes_passed=600, downstream_spectrum_mhz=48)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-PM", homes_passed=600)
    _, project = setup_project_in_permit_review(sg)
    project = deny_permit(project["id"])

    resp = api_client.schedule_node_split_project(
        project["id"],
        {
            "window_start": "2026-11-01T00:00:00Z",
            "window_end": "2026-11-05T00:00:00Z",
            "expected_node_split_project_version": project["version"],
        },
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_GRANTED)
    project = get_node_split_project(project["id"])
    assert project["status"] == "PERMIT_DENIED"
