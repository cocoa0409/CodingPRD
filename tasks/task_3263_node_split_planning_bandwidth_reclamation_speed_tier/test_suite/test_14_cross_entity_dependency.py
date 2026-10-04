"""Difficulty tests: cross-entity state dependencies (queue A).

  provisioning_validate_gated_by_tier_and_cpe_states — retired tier / prior success
  begin_construction_gated_by_parent_action_in_progress — gate / satisfaction
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_block,
    create_franchise_area,
    create_node,
    create_service_group,
    create_tier,
    get_success_data,
    set_clock,
    setup_premise_with_cpe,
    setup_project_in_permit_review,
    setup_project_scheduled,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ENGINEER = TEST_USERS["capacity_engineer_headers"]
FIELD_OPS = TEST_USERS["field_ops_coordinator_headers"]
PLANNER = TEST_USERS["network_planner_headers"]
PROVISIONING = TEST_USERS["provisioning_agent_headers"]


def _setup_tier_retire_scenario():
    """SG-D with tier LEG and two premises (D31 modems). R1 is created and
    validated while the tier is PUBLISHED; the tier is then RETIRED; R2 is
    created on the second premise. Returns (tier, pr1, pr2)."""
    set_clock("2026-10-01T00:00:00Z")
    fa = create_franchise_area(
        name="Metro East", region_code="ME",
        obligation_homes_required=5000, obligation_deadline="2027-06-30T00:00:00Z",
    )
    node = create_node(fa["id"], node_code="NE-D", homes_passed=300, downstream_spectrum_mhz=48)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-D", homes_passed=100)
    tier = create_tier(tier_code="LEG", downstream_mbps=50, upstream_mbps=5,
                       min_capability_class="D30", min_upstream_config="LEGACY")
    cp1, _ = setup_premise_with_cpe(
        sg,
        cpe_overrides={"model": "SB8200", "docsis_version": "3.1", "capability_class": "D31",
                       "max_downstream_mbps": 400, "video_legacy": False},
        premise_overrides={"premise_ref": "P-D1", "address": "7 Elm St"},
    )
    cp2, _ = setup_premise_with_cpe(
        sg,
        cpe_overrides={"model": "SB8200", "docsis_version": "3.1", "capability_class": "D31",
                       "max_downstream_mbps": 400, "video_legacy": False},
        premise_overrides={"premise_ref": "P-D2", "address": "9 Elm St"},
    )
    pr1 = get_success_data(api_client.create_provisioning_request(
        cp1["id"], {"speed_tier_id": tier["id"], "expected_customer_premise_version": cp1["version"]},
        PROVISIONING))
    pr1 = validate_success(api_client.validate_provisioning_request(pr1["id"], PROVISIONING))
    get_success_data(api_client.retire_speed_tier(tier["id"], ADMIN))
    pr2 = get_success_data(api_client.create_provisioning_request(
        cp2["id"], {"speed_tier_id": tier["id"], "expected_customer_premise_version": cp2["version"]},
        PROVISIONING))
    return tier, pr1, pr2


def test_validate_against_retired_tier_rejected():
    """PRD §3.6: "Validation of any new provisioning request against a `RETIRED`
    tier is rejected with `ERR_TIER_RETIRED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/provisioning_validate_gated_by_tier_and_cpe_states
    """
    _, _, pr2 = _setup_tier_retire_scenario()

    resp = api_client.validate_provisioning_request(pr2["id"], PROVISIONING)
    validate_error(resp, ApiErrorId.ERR_TIER_RETIRED)
    pr2_now = validate_success(api_client.get_provisioning_request(pr2["id"], ADMIN))
    assert pr2_now["status"] == "FAILED"
    assert pr2_now["failure_reason"] == "ERR_TIER_RETIRED"


def test_request_validated_before_retire_keeps_its_validated_state():
    """PRD §3.6: "Validation of any new provisioning request against a `RETIRED`
    tier is rejected with `ERR_TIER_RETIRED` (HTTP 409)." — the gate binds at
    validation time, so a request validated while the tier was PUBLISHED stands.

    Design: Difficulty/cross_entity_state_dependency/provisioning_validate_gated_by_tier_and_cpe_states
    """
    _, pr1, _ = _setup_tier_retire_scenario()

    pr1_now = validate_success(api_client.get_provisioning_request(pr1["id"], ADMIN))
    assert pr1_now["status"] == "VALIDATED", (
        "the request that validated while the tier was PUBLISHED must remain VALIDATED"
    )


def _setup_scheduled_project_parent_not_begun():
    """NODE_SPLIT action APPROVED (never begun) with its project SCHEDULED for
    2026-11-01..2026-11-05."""
    set_clock("2026-10-01T00:00:00Z")
    fa = create_franchise_area(
        name="Metro East", region_code="ME",
        obligation_homes_required=5000, obligation_deadline="2027-06-30T00:00:00Z",
    )
    node = create_node(fa["id"], node_code="NE-J", homes_passed=600, downstream_spectrum_mhz=48)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-J", homes_passed=600)
    action, project = setup_project_scheduled(
        sg, window_start="2026-11-01T00:00:00Z", window_end="2026-11-05T00:00:00Z"
    )
    return action, project


def test_begin_construction_rejected_while_parent_action_not_in_progress():
    """PRD §3.4: "A `FieldOpsCoordinator` begins construction, moving the
    project `SCHEDULED → IN_CONSTRUCTION`; this is gated on the parent capacity
    action being `IN_PROGRESS`, and a project whose parent action is in any
    other status is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/begin_construction_gated_by_parent_action_in_progress
    """
    _, project = _setup_scheduled_project_parent_not_begun()

    resp = api_client.begin_construction(project["id"], FIELD_OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    project_now = validate_success(api_client.get_node_split_project(project["id"], ADMIN))
    assert project_now["status"] == "SCHEDULED"


def test_begin_construction_succeeds_once_parent_action_in_progress():
    """PRD §3.4: "A `FieldOpsCoordinator` begins construction, moving the
    project `SCHEDULED → IN_CONSTRUCTION`; this is gated on the parent capacity
    action being `IN_PROGRESS`".

    Design: Difficulty/cross_entity_state_dependency/begin_construction_gated_by_parent_action_in_progress
    """
    action, project = _setup_scheduled_project_parent_not_begun()

    validate_error(api_client.begin_construction(project["id"], FIELD_OPS),
                   ApiErrorId.ERR_INVALID_STATE)
    get_success_data(api_client.begin_capacity_action(action["id"], ENGINEER))
    project = validate_success(api_client.begin_construction(project["id"], FIELD_OPS))
    assert project["status"] == "IN_CONSTRUCTION"
