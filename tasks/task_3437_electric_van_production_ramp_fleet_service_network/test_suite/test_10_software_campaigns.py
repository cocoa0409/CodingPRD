"""Software campaigns: staged-rollout gates, pause/resume pinning, per-vehicle
result intake rules, and the rollback hold/recall cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    campaign_result_payload,
    create_campaign,
    provision_and_activate_telematics,
    read_campaign,
    read_order,
    read_vehicle,
    record_campaign_result,
    set_logical_clock,
    setup_base_fleet,
    start_campaign,
    transition_campaign,
    transition_payload,
    transition_vehicle,
    validate_error,
    validate_success,
)

_RELEASE = TEST_USERS["release_manager_headers"]
_TELEMATICS = TEST_USERS["telematics_ingestion_headers"]


def test_campaign_advance_with_empty_cohort_rejected(api):
    """PRD section 3.7: "A stage advance with a zero cohort is rejected with
    `ERR_EMPTY_COHORT`."

    Design: Corner/state_machines/campaign_advance_with_empty_cohort_rejected
    """
    set_logical_clock()
    campaign = start_campaign()
    resp = api.transition_software_campaign(
        campaign["id"], transition_payload("EXPANDED"), _RELEASE
    )
    validate_error(resp, ApiErrorId.ERR_EMPTY_COHORT)
    assert read_campaign(campaign["id"])["status"] == "CANARY"


def test_campaign_resume_to_wrong_stage_rejected(api):
    """PRD section 3.7: "Resuming returns to exactly that recorded stage — a
    campaign paused from `EXPANDED` resumes only to `EXPANDED` — and clears
    `paused_from` to null; a resume to any other stage is
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/campaign_resume_to_wrong_stage_rejected
    """
    set_logical_clock()
    campaign = start_campaign()
    transition_campaign(campaign["id"], "PAUSED")
    resp = api.transition_software_campaign(
        campaign["id"], transition_payload("GENERAL"), _RELEASE
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    current = read_campaign(campaign["id"])
    assert current["status"] == "PAUSED"
    assert current["paused_from"] == "CANARY"


def test_duplicate_vehicle_result_rejected(api):
    """PRD section 3.7: "only once per vehicle: a second result for the same
    vehicle is `ERR_DUPLICATE_VEHICLE_RESULT`" and "the derived counters
    `succeeded_count` and `failed_count` start at 0 and recompute on every
    accepted result".

    Design: Corner/endpoints/duplicate_vehicle_result_rejected
    """
    fleet = setup_base_fleet(quantity=2)
    veh_id = fleet["vehicles"][0]["id"]
    provision_and_activate_telematics(veh_id)
    campaign = start_campaign()
    record_campaign_result(campaign["id"], veh_id, "SUCCESS")
    resp = api.record_vehicle_result(
        campaign["id"], campaign_result_payload(veh_id, "FAILED"), _TELEMATICS
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_VEHICLE_RESULT)
    current = read_campaign(campaign["id"])
    assert current["succeeded_count"] == 1 and current["failed_count"] == 0, (
        "the rejected duplicate must not move the counters"
    )


def test_vehicle_results_rejected_when_campaign_not_active(api):
    """PRD section 3.7: "A result is accepted only while the campaign is in
    `CANARY`, `EXPANDED`, or `GENERAL` — otherwise `ERR_CAMPAIGN_NOT_ACTIVE`".

    Design: Corner/endpoints/vehicle_results_rejected_when_campaign_not_active
    """
    fleet = setup_base_fleet(quantity=2)
    veh_id = fleet["vehicles"][0]["id"]
    provision_and_activate_telematics(veh_id)
    campaign = create_campaign()  # left in DRAFT
    resp = api.record_vehicle_result(
        campaign["id"], campaign_result_payload(veh_id, "SUCCESS"), _TELEMATICS
    )
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_ACTIVE)
    assert read_campaign(campaign["id"])["results"] == []


def test_campaign_gate_success_rate_pass_and_fail(api):
    """PRD section 3.7: "Leaving `CANARY` requires a cohort of at least 3
    vehicles; leaving `EXPANDED` requires at least 10; a shortfall is
    `ERR_ROLLOUT_GATE_FAILED`. The success rate — succeeded divided by cohort,
    compared exactly with no pre-rounding — must be at least 0.95 or the
    advance is refused with `ERR_ROLLOUT_GATE_FAILED`"; and "An accepted
    `SUCCESS` also advances that vehicle's `software_version` to the
    campaign's `target_version`."

    Design: Corner/calculations/campaign_gate_success_rate_pass_and_fail
    """
    fleet = setup_base_fleet(quantity=3)
    veh_ids = [vehicle["id"] for vehicle in fleet["vehicles"]]
    for veh_id in veh_ids:
        provision_and_activate_telematics(veh_id)
    campaign_a = start_campaign(target_version="2.0.0", telematics_tier_scope="ALL")
    for veh_id in veh_ids:
        record_campaign_result(campaign_a["id"], veh_id, "SUCCESS")
    advanced = transition_campaign(campaign_a["id"], "EXPANDED")
    assert advanced["status"] == "EXPANDED", "3/3 = 1.0 >= 0.95 with cohort 3 >= 3 passes"

    campaign_b = start_campaign(target_version="2.0.1", telematics_tier_scope="ALL")
    record_campaign_result(campaign_b["id"], veh_ids[0], "SUCCESS")
    record_campaign_result(campaign_b["id"], veh_ids[1], "FAILED")
    record_campaign_result(campaign_b["id"], veh_ids[2], "SUCCESS")
    resp = api.transition_software_campaign(
        campaign_b["id"], transition_payload("EXPANDED"), _RELEASE
    )
    validate_error(resp, ApiErrorId.ERR_ROLLOUT_GATE_FAILED)
    current_b = read_campaign(campaign_b["id"])
    assert current_b["status"] == "CANARY"
    assert current_b["succeeded_count"] == 2 and current_b["failed_count"] == 1
    assert read_vehicle(veh_ids[0])["software_version"] == "2.0.1", (
        "campaign B's SUCCESS moved the vehicle to B's target version"
    )
    assert read_vehicle(veh_ids[1])["software_version"] == "2.0.0", (
        "a FAILED result leaves the version at the earlier campaign's target"
    )


def test_campaign_pause_resume_returns_to_recorded_stage(api):
    """PRD section 3.7: "From any of `CANARY`, `EXPANDED`, or `GENERAL` the
    campaign can move to `PAUSED`, which records the abandoned stage in
    `paused_from`. Resuming returns to exactly that recorded stage ... and
    clears `paused_from` to null".

    Design: Difficulty/non_linear_state_machine/software_campaign_pause_resume_cycle_then_rollback
    """
    set_logical_clock()
    campaign = start_campaign()
    paused = transition_campaign(campaign["id"], "PAUSED")
    assert paused["status"] == "PAUSED"
    assert paused["paused_from"] == "CANARY", "the pause recorded the origin stage"
    resumed = transition_campaign(campaign["id"], "CANARY")
    assert resumed["status"] == "CANARY", "resume returns to exactly paused_from"
    assert resumed["paused_from"] is None


def test_campaign_rollback_after_resume_is_terminal(api):
    """PRD section 3.7: "A campaign may be rolled back from `CANARY`,
    `EXPANDED`, `GENERAL`, or `PAUSED`; attempting any transition out of
    `COMPLETE` or `ROLLED_BACK` is `ERR_ALREADY_TERMINAL`."

    Design: Difficulty/non_linear_state_machine/software_campaign_pause_resume_cycle_then_rollback
    """
    set_logical_clock()
    campaign = start_campaign()
    transition_campaign(campaign["id"], "PAUSED")
    transition_campaign(campaign["id"], "CANARY")
    rolled_back = transition_campaign(campaign["id"], "ROLLED_BACK")
    assert rolled_back["status"] == "ROLLED_BACK"
    resp = api.transition_software_campaign(
        campaign["id"], transition_payload("CANARY"), _RELEASE
    )
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


def _setup_rollback_scenario():
    """Two-vehicle order (both VINs registered); vehicle 1 telematics ACTIVE
    and delivery IN_TRANSIT; vehicle 2 untouched; a CANARY campaign (target
    2.0.0, scope ALL) holding one SUCCESS result for vehicle 1."""
    fleet = setup_base_fleet(quantity=2)
    veh1_id = fleet["vehicles"][0]["id"]
    veh2_id = fleet["vehicles"][1]["id"]
    provision_and_activate_telematics(veh1_id)
    transition_vehicle(veh1_id, "DELIVERY", "IN_TRANSIT")
    campaign = start_campaign(target_version="2.0.0", telematics_tier_scope="ALL")
    record_campaign_result(campaign["id"], veh1_id, "SUCCESS")
    return fleet, veh1_id, veh2_id, campaign["id"]


def test_rollback_holds_and_recalls_successful_vehicle(api):
    """PRD section 3.7: "Link 1: every vehicle holding a `SUCCESS` entry in
    this campaign's `results` and currently telematics `ACTIVE` gets
    `software_hold` set true. Link 2: each such vehicle whose
    `delivery_status` is `IN_TRANSIT` reverts to `ASSEMBLED` — a physical
    recall of vans on the road."

    Design: Difficulty/transitive_cascade/campaign_rollback_recalls_vehicles_and_recomputes_order_hold_count
    """
    _fleet, veh1_id, veh2_id, campaign_id = _setup_rollback_scenario()
    assert read_vehicle(veh1_id)["software_version"] == "2.0.0", (
        "the accepted SUCCESS advanced the vehicle to the campaign target"
    )
    transition_campaign(campaign_id, "ROLLED_BACK")
    v1 = read_vehicle(veh1_id)
    assert v1["software_hold"] is True, "link 1: SUCCESS + telematics ACTIVE"
    assert v1["delivery_status"] == "ASSEMBLED", "link 2: the hold recalled the IN_TRANSIT van"
    assert v1["software_version"] == "2.0.0", "rollback does not rewrite the version field"
    assert read_vehicle(veh2_id)["software_hold"] is False, (
        "no SUCCESS result for vehicle 2 — the conditional cascade skips it"
    )


def test_rollback_recomputes_parent_order_hold_count(api):
    """PRD section 3.7: "Link 3: each affected order's `hold_count` is
    recomputed from its vehicles' hold flags."; PRD section 3.6: "every
    vehicle mutation — however caused — recomputes `hold_count` as the number
    of the order's vehicles whose `software_hold` is true."

    Design: Difficulty/transitive_cascade/campaign_rollback_recalls_vehicles_and_recomputes_order_hold_count
    """
    fleet, _veh1_id, _veh2_id, campaign_id = _setup_rollback_scenario()
    assert read_order(fleet["order"]["id"])["hold_count"] == 0
    transition_campaign(campaign_id, "ROLLED_BACK")
    order = read_order(fleet["order"]["id"])
    assert order["hold_count"] == 1, (
        "link 3: the derived hold_count recomputed from the child vehicle mutation"
    )
