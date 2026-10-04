"""Difficulty tests: validation-order priority pairs (queue A).

  schedule_state_error_beats_window_conflict — single-error guard / loser check
  validate_capability_error_beats_capacity_exceeded — first-failure report /
    combined scenario
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
    get_node_split_project,
    get_success_data,
    set_clock,
    setup_premise_with_cpe,
    setup_project_in_permit_review,
    setup_project_scheduled,
    setup_service_group,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["network_planner_headers"]
PROVISIONING = TEST_USERS["provisioning_agent_headers"]


def _setup_two_split_projects_same_franchise():
    """Franchise with two 600-home nodes; project A SCHEDULED for
    [2026-11-01, 2026-11-10), project B still in PERMIT_REVIEW."""
    set_clock("2026-10-01T00:00:00Z")
    fa = create_franchise_area(
        name="Metro East", region_code="ME",
        obligation_homes_required=5000, obligation_deadline="2027-06-30T00:00:00Z",
    )
    on1 = create_node(fa["id"], node_code="NE-W1", homes_passed=600, downstream_spectrum_mhz=48)
    create_block(on1["id"], block_type="DATA", mhz=48)
    sg1 = create_service_group(on1["id"], sg_code="SG-W1", homes_passed=600)
    setup_project_scheduled(
        sg1, window_start="2026-11-01T00:00:00Z", window_end="2026-11-10T00:00:00Z"
    )
    on2 = create_node(fa["id"], node_code="NE-W2", homes_passed=600, downstream_spectrum_mhz=48)
    create_block(on2["id"], block_type="DATA", mhz=48)
    sg2 = create_service_group(on2["id"], sg_code="SG-W2", homes_passed=600)
    _, project_b = setup_project_in_permit_review(sg2)
    return project_b


def test_schedule_blocked_by_permit_state_even_before_calendar_checks():
    """PRD §3.4: "the permit state must be `PERMIT_GRANTED` (a project in any
    other state is rejected — surfaced as `ERR_PERMIT_NOT_GRANTED`, HTTP 409,
    the scheduling-specific face of the lifecycle guard); then the OCC version
    must match, with a mismatch rejected as `ERR_STALE_VERSION`; then the
    window itself must be well-formed, with `window_start` strictly earlier
    than `window_end`; then the calendar checks."

    Design: Difficulty/priority_pair_validation_conflict/schedule_state_error_beats_window_conflict
    """
    project_b = _setup_two_split_projects_same_franchise()

    resp = api_client.schedule_node_split_project(
        project_b["id"],
        {
            "window_start": "2026-11-05T00:00:00Z",
            "window_end": "2026-11-12T00:00:00Z",
            "expected_node_split_project_version": project_b["version"],
        },
        PLANNER,
    )
    err = validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_GRANTED)
    assert err["error_id"] == "ERR_PERMIT_NOT_GRANTED"
    assert err["error_id"] != "ERR_WINDOW_CONFLICT"
    project_b = get_node_split_project(project_b["id"])
    assert project_b["status"] == "PERMIT_REVIEW"


def test_schedule_blocked_by_permit_state_leaves_window_unset():
    """PRD §3.4: "the permit state must be `PERMIT_GRANTED` (a project in any
    other state is rejected — surfaced as `ERR_PERMIT_NOT_GRANTED`, HTTP 409,
    the scheduling-specific face of the lifecycle guard)".

    Design: Difficulty/priority_pair_validation_conflict/schedule_state_error_beats_window_conflict
    """
    project_b = _setup_two_split_projects_same_franchise()

    api_client.schedule_node_split_project(
        project_b["id"],
        {
            "window_start": "2026-11-05T00:00:00Z",
            "window_end": "2026-11-12T00:00:00Z",
            "expected_node_split_project_version": project_b["version"],
        },
        PLANNER,
    )
    project_b = get_node_split_project(project_b["id"])
    assert project_b["window_start"] is None, "a rejected schedule must not record a window"
    assert project_b["status"] == "PERMIT_REVIEW"


def _setup_capability_and_capacity_both_failing():
    """SG-Q capacity 304, load 250 (ELEVATED 82.2%); tier BIG DS 100 min D40;
    premise with a D31 modem. Both the capability check and the capacity
    projection would fail for a validate against BIG."""
    set_clock("2026-10-01T00:00:00Z")
    fa = create_franchise_area(
        name="Metro East", region_code="ME",
        obligation_homes_required=5000, obligation_deadline="2027-06-30T00:00:00Z",
    )
    node = create_node(fa["id"], node_code="NE-Q", homes_passed=300, downstream_spectrum_mhz=48)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-Q", homes_passed=200)
    create_sample(sg["id"], 250)
    tier = create_tier(tier_code="BIG", downstream_mbps=100, upstream_mbps=10,
                       min_capability_class="D40", min_upstream_config="LEGACY")
    premise, _ = setup_premise_with_cpe(
        sg,
        cpe_overrides={"model": "SB8200", "docsis_version": "3.1", "capability_class": "D31",
                       "max_downstream_mbps": 400, "video_legacy": False},
        premise_overrides={"premise_ref": "P-Q1", "address": "5 Elm St"},
    )
    pr = get_success_data(api_client.create_provisioning_request(
        premise["id"],
        {"speed_tier_id": tier["id"], "expected_customer_premise_version": premise["version"]},
        PROVISIONING,
    ))
    return pr


def test_validate_reports_first_failing_check_capability_before_capacity():
    """PRD §3.7: "Validation is the gate, performed by a `ProvisioningAgent`,
    and its checks are evaluated in order so that the first failure is the one
    reported."

    Design: Difficulty/priority_pair_validation_conflict/validate_capability_error_beats_capacity_exceeded
    """
    pr = _setup_capability_and_capacity_both_failing()

    resp = api_client.validate_provisioning_request(pr["id"], PROVISIONING)
    err = validate_error(resp, ApiErrorId.ERR_CAPABILITY_INSUFFICIENT)
    assert err["error_id"] == "ERR_CAPABILITY_INSUFFICIENT"
    assert err["error_id"] != "ERR_CAPACITY_EXCEEDED"


def test_validate_failure_records_capability_as_failure_reason():
    """PRD §3.7: "A request that fails any check moves `PENDING → FAILED`, the
    failing check's error id is recorded as `failure_reason`".

    Design: Difficulty/priority_pair_validation_conflict/validate_capability_error_beats_capacity_exceeded
    """
    pr = _setup_capability_and_capacity_both_failing()

    api_client.validate_provisioning_request(pr["id"], PROVISIONING)
    pr_now = validate_success(api_client.get_provisioning_request(pr["id"], ADMIN))
    assert pr_now["status"] == "FAILED"
    assert pr_now["failure_reason"] == "ERR_CAPABILITY_INSUFFICIENT"
