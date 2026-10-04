"""Difficulty tests: compensating invariants (queue A).

  homes_conserved_across_split_cutover — franchise progress / child sums
  provisioned_mbps_activate_then_cancel_leaves_no_drift — activate state /
    cancel compensation
"""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_block,
    create_franchise_area,
    create_node,
    create_service_group,
    get_service_group,
    get_success_data,
    set_clock,
    setup_pending_provisioning_request,
    setup_project_in_construction,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
FIELD_OPS = TEST_USERS["field_ops_coordinator_headers"]
PROVISIONING = TEST_USERS["provisioning_agent_headers"]


def _setup_split_1000_k3():
    """1000-home node fully walked to IN_CONSTRUCTION with k=3, min 200, max 400."""
    set_clock("2026-10-01T00:00:00Z")
    fa = create_franchise_area(
        name="Metro East", region_code="ME",
        obligation_homes_required=5000, obligation_deadline="2027-06-30T00:00:00Z",
    )
    node = create_node(fa["id"], node_code="NE-C1", homes_passed=1000, downstream_spectrum_mhz=48)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-C1", homes_passed=1000)
    action, project = setup_project_in_construction(
        sg, child_count=3, min_homes=200, max_homes=400,
        window_start="2026-11-01T00:00:00Z", window_end="2026-11-10T00:00:00Z",
    )
    return fa, sg, project


def test_franchise_progress_unchanged_by_cutover():
    """PRD §2.10: "node-split cutover conserves homes exactly: the sum of homes
    allocated to the child service groups equals the parent service group's
    `homes_passed` with no remainder and no invention."

    Design: Difficulty/compensating_invariant/homes_conserved_across_split_cutover
    """
    fa, sg, project = _setup_split_1000_k3()

    before = validate_success(api_client.get_franchise_area(fa["id"], ADMIN))
    assert before["homes_built_progress"] == 1000

    validate_success(api_client.cutover_node_split_project(project["id"], FIELD_OPS))

    after = validate_success(api_client.get_franchise_area(fa["id"], ADMIN))
    assert after["homes_built_progress"] == 1000, (
        "333+333+334 children + 0 retired parent conserves the 1000 homes"
    )


def test_child_homes_sum_to_parent_homes_and_parent_zeroed():
    """PRD §3.4: "The parent service group's `homes_passed` drops to 0 and its
    posture becomes `SPLIT_RETIRED`." and §2.10: "node-split cutover conserves
    homes exactly".

    Design: Difficulty/compensating_invariant/homes_conserved_across_split_cutover
    """
    _, sg, project = _setup_split_1000_k3()

    project = validate_success(api_client.cutover_node_split_project(project["id"], FIELD_OPS))

    child_sum = 0
    for child_id in project["child_service_group_ids"]:
        child = validate_success(api_client.get_service_group(child_id, ADMIN))
        child_sum += child["homes_passed"]
    assert child_sum == 1000, "no home is created or destroyed by the split"

    parent = get_service_group(sg["id"])
    assert parent["homes_passed"] == 0
    assert parent["posture"] == "SPLIT_RETIRED"


def _setup_validated_pro_request():
    """SG-Z with tier PRO DS 200 min D31 and a VALIDATED request on a premise
    with a D31 modem."""
    set_clock("2026-10-01T00:00:00Z")
    fa = create_franchise_area(
        name="Metro East", region_code="ME",
        obligation_homes_required=5000, obligation_deadline="2027-06-30T00:00:00Z",
    )
    node = create_node(fa["id"], node_code="NE-Z", homes_passed=300, downstream_spectrum_mhz=48)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-Z", homes_passed=100)
    ctx = setup_pending_provisioning_request(
        sg,
        cpe_overrides={"model": "SB8200", "docsis_version": "3.1", "capability_class": "D31",
                       "max_downstream_mbps": 400, "video_legacy": False},
        premise_overrides={"premise_ref": "P-Z1", "address": "3 Pine St"},
        tier_code="PRO", downstream_mbps=200, upstream_mbps=20,
        min_capability_class="D31", min_upstream_config="LEGACY",
    )
    ctx["pr"] = validate_success(api_client.validate_provisioning_request(ctx["pr"]["id"], PROVISIONING))
    return sg, ctx


def test_activate_applies_tier_to_premise_and_service_group():
    """PRD §3.7: "Activation, by a `ProvisioningAgent`, moves a `VALIDATED`
    request to `ACTIVE` and applies the tier: the premise's `current_tier_id`
    becomes the request's `speed_tier_id`, its `provisioned_downstream_mbps`
    becomes the tier's `downstream_mbps`, and the service group's aggregate
    `provisioned_downstream_mbps` is recomputed."

    Design: Difficulty/compensating_invariant/provisioned_mbps_activate_then_cancel_leaves_no_drift
    """
    sg, ctx = _setup_validated_pro_request()

    pr = validate_success(api_client.activate_provisioning_request(ctx["pr"]["id"], PROVISIONING))
    assert pr["status"] == "ACTIVE"

    premise_now = validate_success(api_client.get_customer_premise(ctx["premise"]["id"], ADMIN))
    assert premise_now["provisioned_downstream_mbps"] == 200
    assert premise_now["current_tier_id"] == ctx["tier"]["id"]

    sg_now = get_service_group(sg["id"])
    assert sg_now["provisioned_downstream_mbps"] == 200


def test_cancel_of_active_request_leaves_zero_provisioned_drift():
    """PRD §3.7: "Cancelling the `ACTIVE` request deprovisions the tier: the
    premise's `current_tier_id` returns to null, its
    `provisioned_downstream_mbps` returns to 0, and the service group's
    provisioned total is recomputed."

    Design: Difficulty/compensating_invariant/provisioned_mbps_activate_then_cancel_leaves_no_drift
    """
    sg, ctx = _setup_validated_pro_request()

    validate_success(api_client.activate_provisioning_request(ctx["pr"]["id"], PROVISIONING))
    pr = validate_success(api_client.cancel_provisioning_request(ctx["pr"]["id"], PROVISIONING))
    assert pr["status"] == "CANCELLED"

    premise_now = validate_success(api_client.get_customer_premise(ctx["premise"]["id"], ADMIN))
    assert premise_now["provisioned_downstream_mbps"] == 0
    assert premise_now["current_tier_id"] is None

    sg_now = get_service_group(sg["id"])
    assert sg_now["provisioned_downstream_mbps"] == 0, (
        "the activate/cancel pair must leave the conserved provisioned quantity unchanged"
    )
