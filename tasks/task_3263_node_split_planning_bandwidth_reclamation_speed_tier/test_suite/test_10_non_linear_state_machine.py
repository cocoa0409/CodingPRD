"""Difficulty tests: non-linear state machines (queue A).

  capacity_action_revise_rework_cycle — revise edge / full rework cycle
  provisioning_request_failed_retry_cycle_after_equipment_swap — retry edge /
    full recovery cycle
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
    get_service_group,
    get_success_data,
    set_clock,
    setup_premise_with_cpe,
    setup_proposed_action,
    setup_service_group,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ENGINEER = TEST_USERS["capacity_engineer_headers"]
PROVISIONING = TEST_USERS["provisioning_agent_headers"]


def _setup_upgrade_action_approved():
    """LEGACY node with an APPROVED MID_SPLIT_UPGRADE action. Returns (node, sg, action)."""
    ctx = setup_service_group(sg_code="SG-U", sg_homes=100, node_homes=300, node_code="NE-U")
    sg = ctx["sg"]
    resp = api_client.create_capacity_action(
        sg["id"],
        {
            "action_type": "MID_SPLIT_UPGRADE",
            "target_upstream_config": "MID_SPLIT",
            "expected_service_group_version": sg["version"],
        },
        TEST_USERS["network_planner_headers"],
    )
    action = get_success_data(resp)
    action = get_success_data(api_client.approve_capacity_action(action["id"], ENGINEER))
    return ctx["node"], sg, action


def test_revise_sends_approved_action_back_to_proposed():
    """PRD §3.3: "The lifecycle deliberately includes a revision loop: a
    `CapacityEngineer` may send an `APPROVED` action back to `PROPOSED` for
    rework, optionally recording a fresh `note`."

    Design: Difficulty/non_linear_state_machine/capacity_action_revise_rework_cycle
    """
    _, _, action = _setup_upgrade_action_approved()
    assert action["status"] == "APPROVED"

    resp = api_client.revise_capacity_action(action["id"], {"note": "need updated BOM"}, ENGINEER)
    action = validate_success(resp)
    assert action["status"] == "PROPOSED", "revise must traverse the APPROVED -> PROPOSED cycle edge"


def test_full_revise_rework_cycle_lands_completed_and_upgrades_node():
    """PRD §3.3: "Completing an upgrade sets the node's `upstream_config` to the
    action's `target_upstream_config` and recomputes `upstream_capacity_mbps` on
    every non-retired service group of the node." and §2.9: "`MID_SPLIT` yields
    108 Mbps".

    Design: Difficulty/non_linear_state_machine/capacity_action_revise_rework_cycle
    """
    node, sg, action = _setup_upgrade_action_approved()

    action = validate_success(api_client.revise_capacity_action(
        action["id"], {"note": "need updated BOM"}, ENGINEER))
    assert action["status"] == "PROPOSED"
    action = validate_success(api_client.approve_capacity_action(action["id"], ENGINEER))
    assert action["status"] == "APPROVED"
    validate_success(api_client.begin_capacity_action(action["id"], ENGINEER))
    action = validate_success(api_client.complete_capacity_action(action["id"], ENGINEER))
    assert action["status"] == "COMPLETED"

    node_now = validate_success(api_client.get_optical_node(node["id"], ADMIN))
    assert node_now["upstream_config"] == "MID_SPLIT"
    sg_now = get_service_group(sg["id"])
    assert sg_now["upstream_capacity_mbps"] == 108


def _setup_failed_capability_request():
    """Premise with a D31 modem and a PENDING request against a D40-only tier.

    Returns dict: sg, tier, premise, cpe (the D31 unit), pr.
    """
    ctx = setup_service_group(sg_code="SG-P", sg_homes=100, node_homes=300, node_code="NE-P")
    sg = ctx["sg"]
    tier = create_tier(tier_code="GIG", downstream_mbps=200, upstream_mbps=20,
                       min_capability_class="D40", min_upstream_config="LEGACY")
    premise, cpe = setup_premise_with_cpe(
        sg,
        cpe_overrides={"model": "SB8200", "docsis_version": "3.1", "capability_class": "D31",
                       "max_downstream_mbps": 400, "video_legacy": False},
        premise_overrides={"premise_ref": "P-P1", "address": "9 Pine St"},
    )
    pr = get_success_data(api_client.create_provisioning_request(
        premise["id"],
        {"speed_tier_id": tier["id"], "expected_customer_premise_version": premise["version"]},
        PROVISIONING,
    ))
    return {"sg": sg, "tier": tier, "premise": premise, "cpe": cpe, "pr": pr}


def test_validate_fails_on_capability_and_records_failure_reason():
    """PRD §3.7: "the premise must hold an `ACTIVE` equipment unit whose
    `capability_class` ranks at or above the tier's `min_capability_class` and
    whose `max_downstream_mbps` is at least the tier's `downstream_mbps` (else
    `ERR_CAPABILITY_INSUFFICIENT`, HTTP 422)" and "A request that fails any
    check moves `PENDING → FAILED`, the failing check's error id is recorded as
    `failure_reason`, and the validate response itself carries that error (as a
    4xx)."

    Design: Difficulty/non_linear_state_machine/provisioning_request_failed_retry_cycle_after_equipment_swap
    """
    ctx = _setup_failed_capability_request()

    resp = api_client.validate_provisioning_request(ctx["pr"]["id"], PROVISIONING)
    validate_error(resp, ApiErrorId.ERR_CAPABILITY_INSUFFICIENT)
    pr = validate_success(api_client.get_provisioning_request(ctx["pr"]["id"], ADMIN))
    assert pr["status"] == "FAILED"
    assert pr["failure_reason"] == "ERR_CAPABILITY_INSUFFICIENT"


def test_retry_cycle_after_equipment_swap_reaches_active():
    """PRD §3.7: "Failure is recoverable: after corrective action — typically an
    equipment swap — a `ProvisioningAgent` may retry, returning the request
    `FAILED → PENDING` and clearing `failure_reason` to null, ready to validate
    again." and "Activation, by a `ProvisioningAgent`, moves a `VALIDATED`
    request to `ACTIVE` and applies the tier: the premise's `current_tier_id`
    becomes the request's `speed_tier_id`, its `provisioned_downstream_mbps`
    becomes the tier's `downstream_mbps`".

    Design: Difficulty/non_linear_state_machine/provisioning_request_failed_retry_cycle_after_equipment_swap
    """
    ctx = _setup_failed_capability_request()
    pr, cpe, premise, tier = ctx["pr"], ctx["cpe"], ctx["premise"], ctx["tier"]

    validate_error(api_client.validate_provisioning_request(pr["id"], PROVISIONING),
                   ApiErrorId.ERR_CAPABILITY_INSUFFICIENT)

    new_cpe = validate_success(api_client.swap_equipment(
        cpe["id"],
        {"model": "XB8", "docsis_version": "4.0", "capability_class": "D40", "max_downstream_mbps": 1000},
        PROVISIONING,
    ), expected_status=201)
    old_cpe = validate_success(api_client.get_equipment(cpe["id"], ADMIN))
    assert old_cpe["status"] == "RETIRED"
    assert new_cpe["status"] == "ACTIVE"
    assert new_cpe["capability_class"] == "D40"

    pr = validate_success(api_client.retry_provisioning_request(pr["id"], PROVISIONING))
    assert pr["status"] == "PENDING"
    assert pr["failure_reason"] is None

    pr = validate_success(api_client.validate_provisioning_request(pr["id"], PROVISIONING))
    assert pr["status"] == "VALIDATED"
    assert pr["config_file_content"] == "TIER=GIG;DS=200;US=20;CPE=D40"

    pr = validate_success(api_client.activate_provisioning_request(pr["id"], PROVISIONING))
    assert pr["status"] == "ACTIVE"
    premise_now = validate_success(api_client.get_customer_premise(premise["id"], ADMIN))
    assert premise_now["provisioned_downstream_mbps"] == 200
    assert premise_now["current_tier_id"] == tier["id"]
