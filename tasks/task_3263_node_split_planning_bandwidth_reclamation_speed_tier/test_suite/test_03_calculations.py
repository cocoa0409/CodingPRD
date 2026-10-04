"""Calculation tests (Corner/calculations instances)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_block,
    create_complaint,
    create_franchise_area,
    create_node,
    create_sample,
    create_service_group,
    get_node_split_project,
    get_service_group,
    get_success_data,
    set_clock,
    setup_project_in_construction,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ENGINEER = TEST_USERS["capacity_engineer_headers"]
FIELD_OPS = TEST_USERS["field_ops_coordinator_headers"]
PROVISIONING = TEST_USERS["provisioning_agent_headers"]
CARE = TEST_USERS["customer_care_headers"]


def test_utilization_window_excludes_samples_older_than_seven_days():
    """PRD §3.2: "The aggregation works over the trailing seven-day window: only
    samples whose `measured_at` falls inside the closed interval from seven days
    before the logical clock's current instant up to that instant count."

    Design: Corner/calculations/utilization_window_excludes_samples_older_than_seven_days
    """
    set_clock("2026-10-01T00:00:00Z")
    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-WIN", homes_passed=100, downstream_spectrum_mhz=48)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-WIN", homes_passed=100)
    create_sample(sg["id"], 900, measured_at="2026-09-20T18:00:00Z")
    create_sample(sg["id"], 100, measured_at="2026-09-30T18:00:00Z")

    sg = get_service_group(sg["id"])
    assert sg["current_load_mbps"] == 100, (
        f"out-of-window 900-Mbps sample must be excluded, got load {sg['current_load_mbps']}"
    )
    assert sg["current_utilization_pct"] == 32.9
    assert sg["posture"] == "NORMAL"


def test_sustained_avg_falls_back_to_all_samples_when_none_sustained():
    """PRD §3.2: "Under `SUSTAINED_AVG`, only samples whose `downstream_mbps` is
    at least half of `downstream_capacity_mbps` are eligible; if no sample
    qualifies, all samples in the window become eligible; `current_load_mbps` is
    the mean of the eligible samples' `downstream_mbps`, truncated down to an
    integer".

    Design: Corner/calculations/sustained_avg_falls_back_to_all_samples_when_none_sustained
    """
    set_clock("2026-10-01T00:00:00Z")
    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-FB", homes_passed=100, downstream_spectrum_mhz=48)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-FB", homes_passed=100, utilization_method="SUSTAINED_AVG")
    create_sample(sg["id"], 50, measured_at="2026-09-30T18:00:00Z", upstream_mbps=5)
    create_sample(sg["id"], 70, measured_at="2026-09-30T19:00:00Z", upstream_mbps=5)

    sg = get_service_group(sg["id"])
    assert sg["current_load_mbps"] == 60
    assert sg["current_utilization_pct"] == 19.7
    assert sg["posture"] == "NORMAL"


def test_cutover_allocation_remainder_outside_bounds_rejected():
    """PRD §3.4: "The final child receives whatever remains, and if that
    remainder falls outside the inclusive range from `min_homes_per_child` to
    `max_homes_per_child`, the cutover is rejected with `ERR_ALLOCATION_INVALID`
    (HTTP 422): homes are conserved exactly, and a split that would strand or
    invent homes never executes."

    Design: Corner/calculations/cutover_allocation_remainder_outside_bounds_rejected
    """
    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-AL", homes_passed=1000, downstream_spectrum_mhz=48)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-AL", homes_passed=1000)
    action, project = setup_project_in_construction(sg, child_count=3, min_homes=200, max_homes=300)

    resp = api_client.cutover_node_split_project(project["id"], FIELD_OPS)
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_INVALID)

    project = get_node_split_project(project["id"])
    assert project["status"] == "IN_CONSTRUCTION"
    action = get_success_data(api_client.get_capacity_action(action["id"], ADMIN))
    assert action["status"] == "IN_PROGRESS"
    sg_now = get_service_group(sg["id"])
    assert sg_now["homes_passed"] == 1000
    assert sg_now["posture"] != "SPLIT_RETIRED"


def test_franchise_progress_aggregates_across_nodes():
    """PRD §2.10: "The area's `homes_built_progress` is computed on read as the
    sum of `homes_passed` over all service groups whose posture is not
    `SPLIT_RETIRED`, across every optical node of the area regardless of node
    status".

    Design: Corner/calculations/franchise_progress_aggregates_across_nodes
    """
    fa = create_franchise_area()
    on1 = create_node(fa["id"], node_code="NE-F1", homes_passed=400, downstream_spectrum_mhz=48)
    create_block(on1["id"], block_type="DATA", mhz=48)
    create_service_group(on1["id"], sg_code="SG-F1", homes_passed=400)
    on2 = create_node(fa["id"], node_code="NE-F2", homes_passed=250, downstream_spectrum_mhz=48)
    create_block(on2["id"], block_type="DATA", mhz=48)
    create_service_group(on2["id"], sg_code="SG-F2", homes_passed=250)

    resp = api_client.get_franchise_area(fa["id"], ADMIN)
    fa_now = validate_success(resp)
    assert fa_now["homes_built_progress"] == 650


def test_classify_rejects_wrong_cause_with_mismatch():
    """PRD §3.9: "If it does not, the classification is rejected with
    `ERR_CAUSE_MISMATCH` (HTTP 422) and the complaint remains `INVESTIGATING` —
    the system will not record a cause the evidence does not support."

    Design: Corner/calculations/classify_rejects_wrong_cause_with_mismatch
    """
    from test_helpers import create_service_group as _csg

    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-CM", homes_passed=100, downstream_spectrum_mhz=48)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-CM", homes_passed=100)
    cp = get_success_data(
        api_client.create_customer_premise(sg["id"], {"premise_ref": "P-CM1", "address": "1 Cause Way"}, PROVISIONING)
    )
    cc = create_complaint(cp["id"], description="one website slow", plant=10, home=10, destination=80)

    resp = api_client.classify_congestion_complaint(
        cc["id"], {"scoring_variant": "EVIDENCE_WEIGHTED", "cause_category": "PLANT"}, CARE
    )
    validate_error(resp, ApiErrorId.ERR_CAUSE_MISMATCH)

    cc = validate_success(api_client.get_congestion_complaint(cc["id"], ADMIN))
    assert cc["status"] == "INVESTIGATING"
    assert cc["cause_category"] is None

    resp = api_client.classify_congestion_complaint(
        cc["id"], {"scoring_variant": "EVIDENCE_WEIGHTED", "cause_category": "DESTINATION"}, CARE
    )
    cc = validate_success(resp)
    assert cc["status"] == "CLASSIFIED"
    assert cc["cause_category"] == "DESTINATION"
