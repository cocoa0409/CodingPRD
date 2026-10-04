"""Difficulty tests: dual-variant calculations (queue A).

Two tests per instance:
  utilization_peak_pct95_vs_sustained_avg_same_samples — one per aggregation variant
  complaint_evidence_vs_recency_weighted_same_signals — one per scoring variant
"""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_block,
    create_complaint,
    create_franchise_area,
    create_node,
    create_sample,
    create_service_group,
    get_service_group,
    get_success_data,
    set_clock,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ENGINEER = TEST_USERS["capacity_engineer_headers"]
PROVISIONING = TEST_USERS["provisioning_agent_headers"]
CARE = TEST_USERS["customer_care_headers"]


def _setup_dual_variant_groups():
    """One node (capacity 456) with SG-P (PEAK_PCT95) and SG-S (SUSTAINED_AVG),
    both fed the identical samples 300/320/400/410."""
    set_clock("2026-10-01T00:00:00Z")
    fa = create_franchise_area(
        name="Metro East", region_code="ME",
        obligation_homes_required=5000, obligation_deadline="2027-06-30T00:00:00Z",
    )
    node = create_node(fa["id"], node_code="NE-100", homes_passed=1000, downstream_spectrum_mhz=168)
    create_block(node["id"], block_type="DATA", mhz=48)
    create_block(node["id"], block_type="DATA", mhz=24)
    for _ in range(4):
        create_block(node["id"], block_type="LEGACY_VIDEO", mhz=24)
    sgp = create_service_group(node["id"], sg_code="SG-P", homes_passed=500, utilization_method="PEAK_PCT95")
    sgs = create_service_group(node["id"], sg_code="SG-S", homes_passed=100, utilization_method="SUSTAINED_AVG")
    for i, value in enumerate((300, 320, 400, 410)):
        ts = f"2026-09-30T18:{i * 5:02d}:00Z"
        create_sample(sgp["id"], value, measured_at=ts)
        create_sample(sgs["id"], value, measured_at=ts)
    return sgp, sgs


def test_peak_pct95_variant_yields_critical_posture_and_system_reclaim_action():
    """PRD §3.2: "Under `PEAK_PCT95`, the window's samples are sorted ascending
    by `downstream_mbps`, the rank is computed as the 95th percentile rank using
    the nearest-rank method — the count of samples is multiplied by 0.95 and
    rounded up to a whole rank — and `current_load_mbps` is the value at that
    1-indexed rank, so spikes dominate." and "if the service group has no
    capacity action in `PROPOSED`, `APPROVED`, or `IN_PROGRESS`, the system
    creates one with `origin` recorded as `SYSTEM`, choosing the remediation
    type by inspecting the plant — `SPECTRUM_RECLAIM` when the node still has at
    least 2 blocks in `VIDEO_ACTIVE`".

    Design: Difficulty/dual_variant_calc/utilization_peak_pct95_vs_sustained_avg_same_samples
    """
    sgp, _ = _setup_dual_variant_groups()

    sgp_now = get_service_group(sgp["id"])
    assert sgp_now["current_load_mbps"] == 410, (
        f"nearest-rank P95 over 4 samples is rank ceil(0.95*4)=4 -> 410, got {sgp_now['current_load_mbps']}"
    )
    assert sgp_now["current_utilization_pct"] == 89.9
    assert sgp_now["posture"] == "CRITICAL"

    resp = api_client.list_capacity_actions(sgp["id"], ADMIN)
    actions, _ = validate_paginated(resp)
    assert len(actions) == 1, "the CRITICAL breach must auto-create exactly one SYSTEM action"
    assert actions[0]["origin"] == "SYSTEM"
    assert actions[0]["status"] == "PROPOSED"
    assert actions[0]["action_type"] == "SPECTRUM_RECLAIM"


def test_sustained_avg_variant_dilutes_spikes_and_stays_elevated():
    """PRD §3.2: "Under `SUSTAINED_AVG`, only samples whose `downstream_mbps` is
    at least half of `downstream_capacity_mbps` are eligible; if no sample
    qualifies, all samples in the window become eligible; `current_load_mbps` is
    the mean of the eligible samples' `downstream_mbps`, truncated down to an
    integer, so brief spikes are diluted." and "at or above `warn_threshold_pct`
    but below `critical_threshold_pct` it is `ELEVATED`".

    Design: Difficulty/dual_variant_calc/utilization_peak_pct95_vs_sustained_avg_same_samples
    """
    _, sgs = _setup_dual_variant_groups()

    sgs_now = get_service_group(sgs["id"])
    assert sgs_now["current_load_mbps"] == 357, (
        f"floor of sustained mean 357.5 must be 357, got {sgs_now['current_load_mbps']}"
    )
    assert sgs_now["current_utilization_pct"] == 78.3
    assert sgs_now["posture"] == "ELEVATED"

    resp = api_client.list_capacity_actions(sgs["id"], ADMIN)
    actions, _ = validate_paginated(resp)
    assert actions == [], "an ELEVATED posture must not auto-create any capacity action"


def _setup_complaints_with_prior_in_home():
    """Premise with a prior RESOLVED IN_HOME complaint plus two fresh complaints
    B and C with identical signals 70/60/50."""
    set_clock("2026-10-01T00:00:00Z")
    fa = create_franchise_area(
        name="Metro East", region_code="ME",
        obligation_homes_required=5000, obligation_deadline="2027-06-30T00:00:00Z",
    )
    node = create_node(fa["id"], node_code="NE-C", homes_passed=500, downstream_spectrum_mhz=72)
    create_block(node["id"], block_type="DATA", mhz=48)
    create_block(node["id"], block_type="LEGACY_VIDEO", mhz=24)
    sg = create_service_group(node["id"], sg_code="SG-C", homes_passed=200)
    cp = get_success_data(api_client.create_customer_premise(
        sg["id"], {"premise_ref": "P-1", "address": "1 Main St"}, PROVISIONING))

    ccA = create_complaint(cp["id"], description="first: pixelation", plant=10, home=80, destination=10)
    validate_success(api_client.classify_congestion_complaint(
        ccA["id"], {"scoring_variant": "EVIDENCE_WEIGHTED", "cause_category": "IN_HOME"}, CARE))
    validate_success(api_client.resolve_congestion_complaint(ccA["id"], {"resolution_note": "rewired drop"}, CARE))

    ccB = create_complaint(cp["id"], description="second: buffering", plant=70, home=60, destination=50)
    ccC = create_complaint(cp["id"], description="third: buffering again", plant=70, home=60, destination=50)
    return ccB, ccC


def test_evidence_weighted_classifies_raw_argmax_plant():
    """PRD §3.9: "Under `EVIDENCE_WEIGHTED`, the scores are simply the raw
    signals: `score_plant` is `plant_signal`, `score_in_home` is `home_signal`,
    and `score_destination` is `destination_signal`, with history ignored."

    Design: Difficulty/dual_variant_calc/complaint_evidence_vs_recency_weighted_same_signals
    """
    ccB, _ = _setup_complaints_with_prior_in_home()

    resp = api_client.classify_congestion_complaint(
        ccB["id"], {"scoring_variant": "EVIDENCE_WEIGHTED", "cause_category": "PLANT"}, CARE
    )
    cc = validate_success(resp)
    assert cc["status"] == "CLASSIFIED"
    assert cc["cause_category"] == "PLANT"
    assert cc["score_plant"] == 70.0
    assert cc["score_in_home"] == 60.0
    assert cc["score_destination"] == 50.0


def test_recency_weighted_boost_flips_argmax_to_in_home():
    """PRD §3.9: "Under `RECENCY_WEIGHTED`, the system finds the premise's most
    recent complaint in `RESOLVED` or `CLOSED` status by creation timestamp, and
    each score is six-tenths of the corresponding raw signal plus a flat boost
    of 40 when that prior complaint exists and its `cause_category` matches the
    score's cause — the boost can flip the outcome relative to the raw signals."

    Design: Difficulty/dual_variant_calc/complaint_evidence_vs_recency_weighted_same_signals
    """
    _, ccC = _setup_complaints_with_prior_in_home()

    resp = api_client.classify_congestion_complaint(
        ccC["id"], {"scoring_variant": "RECENCY_WEIGHTED", "cause_category": "IN_HOME"}, CARE
    )
    cc = validate_success(resp)
    assert cc["status"] == "CLASSIFIED"
    assert cc["cause_category"] == "IN_HOME"
    assert cc["score_plant"] == 42.0
    assert cc["score_in_home"] == 76.0
    assert cc["score_destination"] == 30.0
