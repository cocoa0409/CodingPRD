"""Energy interval metering: posture snapshot and kwh accumulation (PRD §3.7)."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, validate_success, validate_error,
    make_mill, make_grade, setup_supply_pool, setup_charged_heat, make_event,
    activate_event, grant_waiver, get_heat,
)

MO = TEST_USERS["mill_operator_headers"]
ED = TEST_USERS["energy_dispatcher_headers"]


def test_energy_interval_posture_snapshot_and_kwh_accumulation():
    """PRD §3.7: "At record time the server snapshots the mill's posture into
    `posture_at_interval` (`NORMAL` or `INTERRUPTED`) and adds the interval's `kwh`
    into the heat's accumulated `energy_kwh`."

    Design: Corner/entities/energy_interval_computed_posture_snapshot_and_kwh_accumulation
    """
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    contract, lots = setup_supply_pool(
        mill["id"], price=39000, committed=100,
        lots=[{"received_on": "2026-09-03", "tons_received": 20, "moisture_pct": 0.0}],
    )
    grade = make_grade(mill["id"], grade_code="GR40")
    heat, _line = setup_charged_heat(mill["id"], grade["id"], lots[0]["id"], 8)

    normal = validate_success(
        api_client.record_interval(
            mill["id"], heat["id"],
            {"interval_start": "2026-09-09T10:00:00Z",
             "interval_end": "2026-09-09T11:00:00Z", "kwh": 500},
            MO), 201)
    assert normal["posture_at_interval"] == "NORMAL"

    event = make_event(mill["id"], called_at="2026-09-09T12:00:00Z",
                       released_at="2026-09-09T14:00:00Z")
    activate_event(mill["id"], event["id"])

    interrupted = validate_success(
        api_client.record_interval(
            mill["id"], heat["id"],
            {"interval_start": "2026-09-09T12:30:00Z",
             "interval_end": "2026-09-09T13:00:00Z", "kwh": 300},
            ED), 201)
    assert interrupted["posture_at_interval"] == "INTERRUPTED"

    assert get_heat(mill["id"], heat["id"])["energy_kwh"] == 800
