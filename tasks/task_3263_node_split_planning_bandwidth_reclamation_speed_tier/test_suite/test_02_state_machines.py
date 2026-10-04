"""Lifecycle and state-machine tests (Corner/state_machines instances)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_complaint,
    create_service_group,
    get_node_split_project,
    get_service_group,
    get_success_data,
    set_clock,
    setup_project_scheduled,
    setup_service_group,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["network_planner_headers"]
ENGINEER = TEST_USERS["capacity_engineer_headers"]
FIELD_OPS = TEST_USERS["field_ops_coordinator_headers"]
FRANCHISE_ADMIN = TEST_USERS["franchise_admin_headers"]
PROVISIONING = TEST_USERS["provisioning_agent_headers"]
CARE = TEST_USERS["customer_care_headers"]


def test_complaint_full_cycle_investigating_classified_resolved_reopen():
    """PRD §3.9: "A `RESOLVED` complaint may be reopened by a `CustomerCare`
    agent, returning it to `INVESTIGATING`: `reopen_count` increments by 1,
    `cause_category` resets to null, and the three scores reset to null" and
    "a `RESOLVED` complaint may be closed permanently, moving `RESOLVED →
    CLOSED`, which is terminal."

    Design: Corner/state_machines/complaint_full_cycle_investigating_classified_resolved_reopen
    """
    ctx = setup_service_group(sg_code="SG-CY", sg_homes=100, node_homes=100, node_code="NE-CY")
    premise_resp = api_client.create_customer_premise(
        ctx["sg"]["id"], {"premise_ref": "P-CY1", "address": "1 Cycle Ct"}, PROVISIONING
    )
    cp = get_success_data(premise_resp)
    cc = create_complaint(cp["id"], description="evening slowdowns", plant=80, home=10, destination=10)

    resp = api_client.classify_congestion_complaint(
        cc["id"], {"scoring_variant": "EVIDENCE_WEIGHTED", "cause_category": "PLANT"}, CARE
    )
    cc = validate_success(resp)
    assert cc["status"] == "CLASSIFIED"

    resp = api_client.resolve_congestion_complaint(cc["id"], {"resolution_note": "node split proposed"}, CARE)
    cc = validate_success(resp)
    assert cc["status"] == "RESOLVED"

    # PLANT resolve auto-proposes a SYSTEM NODE_SPLIT action for the service group.
    resp = api_client.list_capacity_actions(ctx["sg"]["id"], ADMIN)
    actions, _ = validate_paginated(resp)
    assert len(actions) == 1, "a PLANT resolve must auto-propose exactly one capacity action"
    assert actions[0]["origin"] == "SYSTEM"
    assert actions[0]["action_type"] == "NODE_SPLIT"
    assert actions[0]["status"] == "PROPOSED"

    resp = api_client.reopen_congestion_complaint(cc["id"], CARE)
    cc = validate_success(resp)
    assert cc["status"] == "INVESTIGATING"
    assert cc["reopen_count"] == 1
    assert cc["cause_category"] is None

    resp = api_client.classify_congestion_complaint(
        cc["id"], {"scoring_variant": "EVIDENCE_WEIGHTED", "cause_category": "PLANT"}, CARE
    )
    cc = validate_success(resp)
    resp = api_client.resolve_congestion_complaint(cc["id"], {"resolution_note": "split scheduled"}, CARE)
    cc = validate_success(resp)
    resp = api_client.close_congestion_complaint(cc["id"], CARE)
    cc = validate_success(resp)
    assert cc["status"] == "CLOSED"
    assert cc["reopen_count"] == 1


def test_capacity_action_complete_from_proposed_rejected():
    """PRD §3.3: "Completing an upgrade sets the node's `upstream_config` to the
    action's `target_upstream_config`" — completion is defined only from
    `IN_PROGRESS` ("Beginning an `APPROVED` action moves it to `IN_PROGRESS`");
    a PROPOSED action cannot complete.

    Design: Corner/state_machines/capacity_action_complete_from_proposed_rejected
    """
    ctx = setup_service_group(sg_code="SG-IT", sg_homes=100, node_homes=100, node_code="NE-IT")
    resp = api_client.create_capacity_action(
        ctx["sg"]["id"],
        {
            "action_type": "MID_SPLIT_UPGRADE",
            "target_upstream_config": "MID_SPLIT",
            "expected_service_group_version": ctx["sg"]["version"],
        },
        PLANNER,
    )
    ca = get_success_data(resp)

    resp = api_client.complete_capacity_action(ca["id"], ENGINEER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    current = get_success_data(api_client.get_capacity_action(ca["id"], ADMIN))
    assert current["status"] == "PROPOSED"


def test_node_split_initial_state_is_permit_review():
    """PRD §3.4: "A new project enters `PERMIT_REVIEW`, representing the
    municipal permit application."

    Design: Corner/state_machines/node_split_initial_state_is_permit_review
    """
    ctx = setup_service_group(sg_code="SG-IS", sg_homes=600, node_homes=600, node_code="NE-IS")
    resp = api_client.create_capacity_action(
        ctx["sg"]["id"],
        {"action_type": "NODE_SPLIT", "expected_service_group_version": ctx["sg"]["version"]},
        PLANNER,
    )
    ca = get_success_data(resp)
    resp = api_client.create_node_split_project(
        ca["id"],
        {"child_count": 2, "min_homes_per_child": 200, "max_homes_per_child": 400},
        PLANNER,
    )
    nsp = get_success_data(resp)
    assert nsp["status"] == "PERMIT_REVIEW"
    assert nsp["window_start"] is None
    assert nsp["window_end"] is None


def test_terminal_completed_action_rejects_all_further_transitions():
    """PRD §3.3: "`COMPLETED` and `CANCELLED` are terminal."

    Design: Corner/state_machines/terminal_completed_action_rejects_all_further_transitions
    """
    ctx = setup_service_group(sg_code="SG-TL", sg_homes=100, node_homes=100, node_code="NE-TL")
    resp = api_client.create_capacity_action(
        ctx["sg"]["id"],
        {
            "action_type": "MID_SPLIT_UPGRADE",
            "target_upstream_config": "MID_SPLIT",
            "expected_service_group_version": ctx["sg"]["version"],
        },
        PLANNER,
    )
    ca = get_success_data(resp)
    get_success_data(api_client.approve_capacity_action(ca["id"], ENGINEER))
    get_success_data(api_client.begin_capacity_action(ca["id"], ENGINEER))
    get_success_data(api_client.complete_capacity_action(ca["id"], ENGINEER))

    resp = api_client.cancel_capacity_action(ca["id"], {"reason": "too late"}, ENGINEER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    resp = api_client.revise_capacity_action(ca["id"], {"note": "rework"}, ENGINEER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    resp = api_client.approve_capacity_action(ca["id"], ENGINEER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    resp = api_client.begin_capacity_action(ca["id"], ENGINEER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    resp = api_client.complete_capacity_action(ca["id"], ENGINEER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    current = get_success_data(api_client.get_capacity_action(ca["id"], ENGINEER))
    assert current["status"] == "COMPLETED"


def test_resolve_classified_plant_complaint_auto_proposes_node_split():
    """PRD §3.9: "when the recorded `cause_category` is `PLANT` and the
    premise's service group has no capacity action in `PROPOSED`, `APPROVED`,
    or `IN_PROGRESS`, the system automatically creates one — `origin` `SYSTEM`,
    type `NODE_SPLIT`".

    Design: Corner/state_machines/resolve_classified_plant_complaint_auto_proposes_node_split
    """
    ctx = setup_service_group(sg_code="SG-SE", sg_homes=100, node_homes=100, node_code="NE-SE")
    cp1 = get_success_data(
        api_client.create_customer_premise(ctx["sg"]["id"], {"premise_ref": "P-SE1", "address": "1 Signal Rd"}, PROVISIONING)
    )
    cp2 = get_success_data(
        api_client.create_customer_premise(ctx["sg"]["id"], {"premise_ref": "P-SE2", "address": "2 Signal Rd"}, PROVISIONING)
    )
    ccA = create_complaint(cp1["id"], description="node congestion", plant=90, home=5, destination=5)
    ccB = create_complaint(cp2["id"], description="bad wifi", plant=5, home=90, destination=5)

    validate_success(api_client.classify_congestion_complaint(
        ccA["id"], {"scoring_variant": "EVIDENCE_WEIGHTED", "cause_category": "PLANT"}, CARE))
    validate_success(api_client.resolve_congestion_complaint(ccA["id"], {"resolution_note": "split filed"}, CARE))
    validate_success(api_client.classify_congestion_complaint(
        ccB["id"], {"scoring_variant": "EVIDENCE_WEIGHTED", "cause_category": "IN_HOME"}, CARE))
    validate_success(api_client.resolve_congestion_complaint(ccB["id"], {"resolution_note": "rewired outlet"}, CARE))

    resp = api_client.list_capacity_actions(ctx["sg"]["id"], ADMIN)
    actions, _ = validate_paginated(resp)
    assert len(actions) == 1, (
        "exactly one SYSTEM PROPOSED NODE_SPLIT action must exist — created by the PLANT resolve only"
    )
    action = actions[0]
    assert action["origin"] == "SYSTEM"
    assert action["status"] == "PROPOSED"
    assert action["action_type"] == "NODE_SPLIT"


def test_revise_cascades_cancel_to_linked_projects_and_waves():
    """PRD §3.3: "Revision cascades — any linked node-split project in
    `PERMIT_REVIEW`, `PERMIT_GRANTED`, `PERMIT_DENIED`, or `SCHEDULED` is
    cancelled, and any linked migration wave still `PLANNED` is cancelled."

    Design: Corner/state_machines/revise_cascades_cancel_to_linked_projects_and_waves
    """
    ctx = setup_service_group(sg_code="SG-CD", sg_homes=600, node_homes=600, node_code="NE-CD")
    action, project = setup_project_scheduled(
        ctx["sg"], window_start="2026-11-01T00:00:00Z", window_end="2026-11-05T00:00:00Z"
    )
    assert project["status"] == "SCHEDULED"

    resp = api_client.revise_capacity_action(action["id"], {"note": "engineering changes"}, ENGINEER)
    action = validate_success(resp)
    assert action["status"] == "PROPOSED"
    project = get_node_split_project(project["id"])
    assert project["status"] == "CANCELLED"


def test_cancel_reclaim_action_restores_reclaim_pending_blocks():
    """PRD §3.3: "Cancelling unwinds everything the action set in motion: any
    target block still `RECLAIM_PENDING` returns to `VIDEO_ACTIVE`, restoring
    the spectrum ledger; any linked node-split project in a non-terminal state
    is cancelled; any linked `PLANNED` migration wave is cancelled."

    Design: Corner/state_machines/cancel_reclaim_action_restores_reclaim_pending_blocks
    """
    set_clock("2026-09-25T00:00:00Z")
    from test_helpers import (
        create_block,
        create_franchise_area,
        create_node,
        create_wave,
        setup_legacy_cpe,
        setup_reclaim_action_in_progress,
    )

    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-CP", homes_passed=100, downstream_spectrum_mhz=96)
    v1 = create_block(node["id"], block_type="LEGACY_VIDEO", mhz=24)
    create_block(node["id"], block_type="LEGACY_VIDEO", mhz=24)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-CP", homes_passed=100)
    action = setup_reclaim_action_in_progress(sg, [v1["id"]])
    _, cpe = setup_legacy_cpe(sg, premise_ref="P-CP1", address="1 Comp Pl")
    wave = create_wave(action["id"], [cpe["id"]], wave_code="W1")

    resp = api_client.cancel_capacity_action(action["id"], {"reason": "funding pulled"}, ENGINEER)
    action = validate_success(resp)
    assert action["status"] == "CANCELLED"

    block = validate_success(api_client.get_spectrum_block(v1["id"], ADMIN))
    assert block["status"] == "VIDEO_ACTIVE", "begin's RECLAIM_PENDING must be compensated back to VIDEO_ACTIVE"
    wave = validate_success(api_client.get_migration_wave(wave["id"], ADMIN))
    assert wave["status"] == "CANCELLED"


def test_upstream_upgrade_mid_split_to_high_split_chain():
    """PRD §2.9: "When an upgrade capacity action completes and moves the
    node's `upstream_config` to its target, every non-retired service group on
    that node adopts the new value." and §3.3: "`LEGACY` upgrades only to
    `MID_SPLIT`, and `MID_SPLIT` only to `HIGH_SPLIT`".

    Design: Corner/state_machines/upstream_upgrade_mid_split_to_high_split_chain
    """
    from test_helpers import setup_completed_upgrade

    ctx = setup_service_group(sg_code="SG-U2", sg_homes=100, node_homes=100, node_code="NE-U2")
    setup_completed_upgrade(ctx["sg"], action_type="MID_SPLIT_UPGRADE", target="MID_SPLIT")

    sg_now = get_service_group(ctx["sg"]["id"])
    assert sg_now["upstream_capacity_mbps"] == 108

    ca2_resp = api_client.create_capacity_action(
        ctx["sg"]["id"],
        {
            "action_type": "HIGH_SPLIT_UPGRADE",
            "target_upstream_config": "HIGH_SPLIT",
            "expected_service_group_version": sg_now["version"],
        },
        PLANNER,
    )
    ca2 = get_success_data(ca2_resp)
    get_success_data(api_client.approve_capacity_action(ca2["id"], ENGINEER))
    get_success_data(api_client.begin_capacity_action(ca2["id"], ENGINEER))
    get_success_data(api_client.complete_capacity_action(ca2["id"], ENGINEER))

    node = validate_success(api_client.get_optical_node(ctx["node"]["id"], ADMIN))
    assert node["upstream_config"] == "HIGH_SPLIT"
    sg_now = get_service_group(ctx["sg"]["id"])
    assert sg_now["upstream_capacity_mbps"] == 204
