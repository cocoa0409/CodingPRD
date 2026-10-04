"""Difficulty tests: temporal-window semantics (queue A, resource_temporal_overlap).

  construction_window_half_open_adjacency_vs_overlap — true overlap / adjacency
  migration_wave_buffer_gap_semantics_differ_from_half_open — buffer is stricter
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_block,
    create_franchise_area,
    create_node,
    create_service_group,
    get_node_split_project,
    get_success_data,
    set_clock,
    setup_legacy_cpe,
    setup_project_in_permit_granted,
    setup_project_scheduled,
    setup_reclaim_action_in_progress,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["network_planner_headers"]


def _setup_two_granted_projects_one_scheduled():
    """Franchise with two nodes; project A SCHEDULED [2026-11-01, 2026-11-10),
    project B PERMIT_GRANTED."""
    set_clock("2026-10-01T00:00:00Z")
    fa = create_franchise_area(
        name="Metro East", region_code="ME",
        obligation_homes_required=5000, obligation_deadline="2027-06-30T00:00:00Z",
    )
    on1 = create_node(fa["id"], node_code="NE-H1", homes_passed=600, downstream_spectrum_mhz=48)
    create_block(on1["id"], block_type="DATA", mhz=48)
    sg1 = create_service_group(on1["id"], sg_code="SG-H1", homes_passed=600)
    setup_project_scheduled(
        sg1, window_start="2026-11-01T00:00:00Z", window_end="2026-11-10T00:00:00Z"
    )
    on2 = create_node(fa["id"], node_code="NE-H2", homes_passed=600, downstream_spectrum_mhz=48)
    create_block(on2["id"], block_type="DATA", mhz=48)
    sg2 = create_service_group(on2["id"], sg_code="SG-H2", homes_passed=600)
    _, project_b = setup_project_in_permit_granted(sg2)
    return project_b


def test_overlapping_construction_window_rejected():
    """PRD §3.4: "It may not overlap the window of any other node-split project
    in `SCHEDULED` or `IN_CONSTRUCTION` under the same franchise area" and
    "Either calendar violation is rejected with `ERR_WINDOW_CONFLICT`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/construction_window_half_open_adjacency_vs_overlap
    """
    project_b = _setup_two_granted_projects_one_scheduled()

    resp = api_client.schedule_node_split_project(
        project_b["id"],
        {
            "window_start": "2026-11-09T00:00:00Z",
            "window_end": "2026-11-20T00:00:00Z",
            "expected_node_split_project_version": project_b["version"],
        },
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_CONFLICT)
    project_b = get_node_split_project(project_b["id"])
    assert project_b["status"] == "PERMIT_GRANTED"
    assert project_b["window_start"] is None


def test_adjacent_construction_window_accepted_half_open():
    """PRD §3.4: "two half-open windows that merely touch — one's `window_end`
    equal to the other's `window_start` — do not overlap."

    Design: Difficulty/resource_temporal_overlap/construction_window_half_open_adjacency_vs_overlap
    """
    project_b = _setup_two_granted_projects_one_scheduled()

    validate_error(api_client.schedule_node_split_project(
        project_b["id"],
        {
            "window_start": "2026-11-09T00:00:00Z",
            "window_end": "2026-11-20T00:00:00Z",
            "expected_node_split_project_version": project_b["version"],
        },
        PLANNER,
    ), ApiErrorId.ERR_WINDOW_CONFLICT)

    project_b = get_node_split_project(project_b["id"])
    resp = api_client.schedule_node_split_project(
        project_b["id"],
        {
            "window_start": "2026-11-10T00:00:00Z",
            "window_end": "2026-11-20T00:00:00Z",
            "expected_node_split_project_version": project_b["version"],
        },
        PLANNER,
    )
    project_b = validate_success(resp)
    assert project_b["status"] == "SCHEDULED", (
        "B.start == A.end is adjacency under half-open semantics, not overlap"
    )


def _setup_reclaim_with_wave_and_second_cpe():
    """Reclaim action IN_PROGRESS; wave W1 [2026-10-01, 2026-10-03] PLANNED;
    CPE2 available for a second wave."""
    set_clock("2026-09-25T00:00:00Z")
    fa = create_franchise_area(
        name="Metro East", region_code="ME",
        obligation_homes_required=5000, obligation_deadline="2027-06-30T00:00:00Z",
    )
    node = create_node(fa["id"], node_code="NE-V", homes_passed=200, downstream_spectrum_mhz=96)
    v1 = create_block(node["id"], block_type="LEGACY_VIDEO", mhz=24)
    create_block(node["id"], block_type="LEGACY_VIDEO", mhz=24)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-V", homes_passed=100)
    action = setup_reclaim_action_in_progress(sg, [v1["id"]])
    _, cpe1 = setup_legacy_cpe(sg, premise_ref="P-V1", address="1 Wave Ln")
    _, cpe2 = setup_legacy_cpe(sg, premise_ref="P-V2", address="2 Wave Ln")
    from test_helpers import create_wave
    create_wave(action["id"], [cpe1["id"]], wave_code="W1",
                window_start="2026-10-01T00:00:00Z", window_end="2026-10-03T00:00:00Z")
    return action, cpe2


def test_wave_gap_rule_is_stricter_than_half_open_overlap():
    """PRD §3.5: "between the new wave's window and the window of every sibling
    wave in `PLANNED` or `EXECUTED` under the same action, there must be a
    separation of at least 7 full days in one direction or the other — the new
    window's start at or after the sibling's end plus 7 days, or the new
    window's end at or before the sibling's start minus 7 days."

    Design: Difficulty/resource_temporal_overlap/migration_wave_buffer_gap_semantics_differ_from_half_open
    """
    action, cpe2 = _setup_reclaim_with_wave_and_second_cpe()

    resp = api_client.create_migration_wave(
        action["id"],
        {
            "wave_code": "W2",
            "window_start": "2026-10-04T00:00:00Z",
            "window_end": "2026-10-05T00:00:00Z",
            "target_cpe_ids": [cpe2["id"]],
        },
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_WAVE_GAP_VIOLATION)


def test_rejected_wave_is_not_created():
    """PRD §3.5: "a violation is rejected with `ERR_WAVE_GAP_VIOLATION`
    (HTTP 409)" — a rejected plan call creates no wave.

    Design: Difficulty/resource_temporal_overlap/migration_wave_buffer_gap_semantics_differ_from_half_open
    """
    action, cpe2 = _setup_reclaim_with_wave_and_second_cpe()

    api_client.create_migration_wave(
        action["id"],
        {
            "wave_code": "W2",
            "window_start": "2026-10-04T00:00:00Z",
            "window_end": "2026-10-05T00:00:00Z",
            "target_cpe_ids": [cpe2["id"]],
        },
        PLANNER,
    )
    resp = api_client.list_migration_waves(action["id"], ADMIN)
    waves, _ = validate_paginated(resp)
    assert len(waves) == 1, "the gap-violating wave must not be persisted"
