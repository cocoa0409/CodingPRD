"""Difficulty tests: boundary precision (queue A, rule boundary_precision_check).

  utilization_sample_landing_exactly_on_critical_threshold — on/just-below the
    critical percent
  migration_wave_gap_exactly_seven_days_allowed_six_rejected — 7-day / 6-day gap
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
    create_wave,
    get_service_group,
    get_success_data,
    set_clock,
    setup_legacy_cpe,
    setup_reclaim_action_in_progress,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["network_planner_headers"]


def _setup_boundary_node():
    """Node NE-B2 capacity 760 with SG-HI and SG-LO (warn 70 / crit 85)."""
    set_clock("2026-10-01T00:00:00Z")
    fa = create_franchise_area(
        name="Metro East", region_code="ME",
        obligation_homes_required=5000, obligation_deadline="2027-06-30T00:00:00Z",
    )
    node = create_node(fa["id"], node_code="NE-B2", homes_passed=800, downstream_spectrum_mhz=168)
    create_block(node["id"], block_type="DATA", mhz=60)
    create_block(node["id"], block_type="DATA", mhz=60)
    create_block(node["id"], block_type="LEGACY_VIDEO", mhz=24)
    create_block(node["id"], block_type="LEGACY_VIDEO", mhz=24)
    sghi = create_service_group(node["id"], sg_code="SG-HI", homes_passed=100)
    sglo = create_service_group(node["id"], sg_code="SG-LO", homes_passed=100)
    return sghi, sglo


def test_sample_landing_exactly_on_critical_threshold_flips_posture_critical():
    """PRD §3.2: "at or above `critical_threshold_pct` it is `CRITICAL`" and
    §2.6: "There is no floating-point tolerance anywhere: thresholds compare
    exactly, and boundary inclusivity is spelled out at each rule."

    Design: Difficulty/boundary_precision_check/utilization_sample_landing_exactly_on_critical_threshold
    """
    sghi, _ = _setup_boundary_node()
    create_sample(sghi["id"], 646)  # 646*100/760 == 85.0 exactly

    sg = get_service_group(sghi["id"])
    assert sg["current_utilization_pct"] == 85.0
    assert sg["posture"] == "CRITICAL", "the >= boundary must trigger CRITICAL at exactly 85.0"

    resp = api_client.list_capacity_actions(sghi["id"], ADMIN)
    actions, _ = validate_paginated(resp)
    assert len(actions) == 1
    assert actions[0]["origin"] == "SYSTEM"
    assert actions[0]["status"] == "PROPOSED"
    assert actions[0]["action_type"] == "SPECTRUM_RECLAIM"


def test_sample_one_mbps_below_critical_threshold_stays_elevated():
    """PRD §3.2: "at or above `warn_threshold_pct` but below
    `critical_threshold_pct` it is `ELEVATED`".

    Design: Difficulty/boundary_precision_check/utilization_sample_landing_exactly_on_critical_threshold
    """
    _, sglo = _setup_boundary_node()
    create_sample(sglo["id"], 645)  # 645*100/760 = 84.868... -> 84.9

    sg = get_service_group(sglo["id"])
    assert sg["current_utilization_pct"] == 84.9
    assert sg["posture"] == "ELEVATED"

    resp = api_client.list_capacity_actions(sglo["id"], ADMIN)
    actions, _ = validate_paginated(resp)
    assert actions == [], "an ELEVATED posture must not auto-create any capacity action"


def _setup_reclaim_with_first_wave():
    """Reclaim action IN_PROGRESS with wave W1 [2026-10-01, 2026-10-03] PLANNED
    and two more legacy CPEs ready for follow-up waves."""
    set_clock("2026-09-25T00:00:00Z")
    fa = create_franchise_area(
        name="Metro East", region_code="ME",
        obligation_homes_required=5000, obligation_deadline="2027-06-30T00:00:00Z",
    )
    node = create_node(fa["id"], node_code="NE-G", homes_passed=200, downstream_spectrum_mhz=96)
    v1 = create_block(node["id"], block_type="LEGACY_VIDEO", mhz=24)
    create_block(node["id"], block_type="LEGACY_VIDEO", mhz=24)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-G", homes_passed=100)
    action = setup_reclaim_action_in_progress(sg, [v1["id"]])
    _, cpe1 = setup_legacy_cpe(sg, premise_ref="P-G1", address="1 Gap Rd")
    _, cpe2 = setup_legacy_cpe(sg, premise_ref="P-G2", address="2 Gap Rd")
    _, cpe3 = setup_legacy_cpe(sg, premise_ref="P-G3", address="3 Gap Rd")
    create_wave(action["id"], [cpe1["id"]], wave_code="W1",
                window_start="2026-10-01T00:00:00Z", window_end="2026-10-03T00:00:00Z")
    return action, cpe2, cpe3


def test_wave_gap_six_days_rejected():
    """PRD §3.5: "between the new wave's window and the window of every sibling
    wave in `PLANNED` or `EXECUTED` under the same action, there must be a
    separation of at least 7 full days in one direction or the other" and "a gap
    one second short of 7 days is not, and a violation is rejected with
    `ERR_WAVE_GAP_VIOLATION` (HTTP 409)".

    Design: Difficulty/boundary_precision_check/migration_wave_gap_exactly_seven_days_allowed_six_rejected
    """
    action, cpe2, _ = _setup_reclaim_with_first_wave()

    resp = api_client.create_migration_wave(
        action["id"],
        {
            "wave_code": "W2-TOOSHORT",
            "window_start": "2026-10-09T00:00:00Z",
            "window_end": "2026-10-10T00:00:00Z",
            "target_cpe_ids": [cpe2["id"]],
        },
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_WAVE_GAP_VIOLATION)


def test_wave_gap_exactly_seven_days_allowed():
    """PRD §3.5: "A gap of exactly 7 days is permitted".

    Design: Difficulty/boundary_precision_check/migration_wave_gap_exactly_seven_days_allowed_six_rejected
    """
    action, _, cpe3 = _setup_reclaim_with_first_wave()

    resp = api_client.create_migration_wave(
        action["id"],
        {
            "wave_code": "W2-EXACT",
            "window_start": "2026-10-10T00:00:00Z",
            "window_end": "2026-10-11T00:00:00Z",
            "target_cpe_ids": [cpe3["id"]],
        },
        PLANNER,
    )
    wave = validate_success(resp, expected_status=201)
    assert wave["status"] == "PLANNED"
