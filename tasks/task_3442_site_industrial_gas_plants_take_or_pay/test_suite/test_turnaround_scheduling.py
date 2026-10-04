"""Turnaround scheduling gates: half-open overlap semantics, closed blackout
intervals, and the start due-gate."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_accepted_evaluation,
    create_agreed_turnaround,
    create_contract,
    create_operating_plant,
    create_scheduled_turnaround,
    create_turnaround,
    agree_turnaround,
    schedule_turnaround,
    set_logical_clock,
    setup_standard_onsite_scenario,
    validate_error,
    validate_success,
)


def _get_turnaround(plant_id, turnaround_id):
    turnarounds = validate_success(api_client.list_plant_turnarounds(
        plant_id, TEST_USERS["plant_operator_headers"]
    ))
    match = [t for t in turnarounds if t["id"] == turnaround_id]
    assert len(match) == 1, f"turnaround {turnaround_id} not found on plant"
    return match[0]


def test_turnaround_halfopen_adjacency_allowed(api):
    """PRD section 3.7: "Second, the window must not overlap any other
    `SCHEDULED` or `IN_PROGRESS` turnaround of the same plant under half-open
    semantics: two windows conflict when the existing window starts before the
    new window ends and the new window starts before the existing window ends,
    while mere adjacency — one window ending exactly as the other begins — is
    allowed (`ERR_TURNAROUND_OVERLAP`)."

    Design: Difficulty/resource_temporal_overlap/turnaround_halfopen_adjacency_allowed
    """
    bundle = setup_standard_onsite_scenario()
    customer, plant = bundle["customer"], bundle["plant"]
    create_scheduled_turnaround(
        plant["id"], customer["id"],
        window_start="2026-11-01T00:00:00Z", window_end="2026-11-05T00:00:00Z",
        scope="TA1 exchanger",
    )
    adjacent = create_scheduled_turnaround(
        plant["id"], customer["id"],
        window_start="2026-11-05T00:00:00Z", window_end="2026-11-09T00:00:00Z",
        scope="TA2 adjacent turbine",
    )
    assert adjacent["status"] == "SCHEDULED", (
        "end == start adjacency shares no instant and must schedule"
    )

    overlapping = create_turnaround(
        plant["id"], window_start="2026-11-04T00:00:00Z",
        window_end="2026-11-06T00:00:00Z", scope="TA3 overlapping",
    )
    overlapping = agree_turnaround(
        overlapping["id"], overlapping["version"], customer["id"]
    )
    response = api_client.schedule_turnaround(
        overlapping["id"], TEST_USERS["plant_operator_headers"]
    )
    validate_error(response, ApiErrorId.ERR_TURNAROUND_OVERLAP)
    after = _get_turnaround(plant["id"], overlapping["id"])
    assert after["status"] == "AGREED", (
        "a rejected schedule leaves the turnaround AGREED"
    )


def test_blackout_closed_interval_touching_rules(api):
    """PRD section 3.7: "Third, the window must not share any instant with any
    of the customer's blackout windows, which are closed intervals: a conflict
    exists when the turnaround window starts at or before a blackout's end and
    ends after that blackout's start (`ERR_TURNAROUND_IN_BLACKOUT`)."
    PRD section 3.1: "Blackout windows are closed intervals: both the start
    instant and the end instant belong to the blackout, which matters when
    turnaround windows are checked against them in §3.7."

    Design: Corner/validations/blackout_closed_interval_touching_rules
    """
    set_logical_clock()
    customer, evaluation = create_accepted_evaluation(
        {
            "name": "BlackCo", "segment": "CHEMICAL", "credit_standing": "PRIME",
            "blackout_windows": [
                {"start_iso": "2027-03-10T00:00:00Z",
                 "end_iso": "2027-03-20T00:00:00Z"},
            ],
        },
        {
            "site_label": "BLK-1", "demand_avg_nm3h": 5000,
            "demand_peak_nm3h": 7000, "required_purity_percent": 99.9,
            "required_product": "H2", "pipeline_available": False,
        },
    )
    contract = create_contract(customer["id"], evaluation["id"])
    activate = api_client.activate_contract(
        contract["id"], TEST_USERS["supply_planner_headers"]
    )
    validate_success(activate)
    plant = create_operating_plant(contract["id"])

    touching_start = create_agreed_turnaround(
        plant["id"], customer["id"],
        window_start="2027-03-09T00:00:00Z", window_end="2027-03-10T00:00:00Z",
        scope="Touching-start window",
    )
    touching_end = create_agreed_turnaround(
        plant["id"], customer["id"],
        window_start="2027-03-20T00:00:00Z", window_end="2027-03-22T00:00:00Z",
        scope="Touching-end window",
    )

    scheduled = schedule_turnaround(touching_start["id"])
    assert scheduled["status"] == "SCHEDULED", (
        "[2027-03-09, 2027-03-10) ends exactly at the blackout start and "
        "shares no instant with the closed blackout"
    )
    response = api_client.schedule_turnaround(
        touching_end["id"], TEST_USERS["plant_operator_headers"]
    )
    validate_error(response, ApiErrorId.ERR_TURNAROUND_IN_BLACKOUT)
    after = _get_turnaround(plant["id"], touching_end["id"])
    assert after["status"] == "AGREED"


def test_turnaround_start_before_window_rejected(api):
    """PRD section 3.7: "Starting the work is due-gated: the logical clock must
    have reached `window_start`, or the start is rejected with
    `ERR_TURNAROUND_NOT_DUE`."

    Design: Corner/state_machines/turnaround_start_before_window_rejected
    """
    bundle = setup_standard_onsite_scenario()
    customer, plant = bundle["customer"], bundle["plant"]
    turnaround = create_scheduled_turnaround(
        plant["id"], customer["id"],
        window_start="2026-10-10T00:00:00Z", window_end="2026-10-14T00:00:00Z",
        scope="Early start check",
    )
    set_logical_clock("2026-10-09T23:59:59Z")
    response = api_client.start_turnaround(
        turnaround["id"], TEST_USERS["plant_operator_headers"]
    )
    validate_error(response, ApiErrorId.ERR_TURNAROUND_NOT_DUE)
    after = _get_turnaround(plant["id"], turnaround["id"])
    assert after["status"] == "SCHEDULED"
    plant_after = validate_success(api_client.get_plant(
        plant["id"], TEST_USERS["plant_operator_headers"]
    ))
    assert plant_after["status"] == "OPERATING", (
        "a rejected start must not disturb the plant"
    )
