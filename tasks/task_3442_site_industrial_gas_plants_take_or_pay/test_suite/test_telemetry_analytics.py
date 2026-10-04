"""Tank telemetry analytics: dual burn-rate variants, runout projections,
append-only reading storage, strict chronological ordering, and immediate
read-after-write consistency."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_tank,
    assert_telemetry_reading,
    create_customer,
    create_tank,
    create_tank_payload,
    create_telemetry_payload,
    post_telemetry,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant; runout equality is by instant, not text."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_tank_runout_instant_vs_wma_divergence(api):
    """PRD section 3.5: "The instantaneous variant, exposed as
    `burn_rate_instant_lph`, is simply the latest interval's burn, and it
    reacts immediately to a consumption change."
    PRD section 3.5: "When fewer than four intervals exist, only the leading
    weights are used — a single interval contributes its burn multiplied by one
    half; two intervals use one half and one quarter; three use one half, one
    quarter, and one eighth — and the unused weights are discarded rather than
    redistributed."
    PRD section 3.5: "`projected_runout_instant_at` and
    `projected_runout_wma_at` are the timestamp of the latest reading plus the
    hours needed to consume the liters standing between the current level and
    the safety stock at that variant's burn rate, rounded half up to whole
    seconds."

    Design: Difficulty/dual_variant_calc/tank_runout_instant_vs_wma_divergence
    """
    set_logical_clock()
    customer = create_customer(name="Fabrikam Chips", segment="ELECTRONICS",
                               credit_standing="PRIME")
    tank = create_tank(customer["id"], required_purity_percent=99.9,
                       max_impurity_ppm=50)
    post_telemetry(tank["id"], "2026-10-01T00:00:00Z", 40000)
    post_telemetry(tank["id"], "2026-10-01T10:00:00Z", 37000)
    refreshed = post_telemetry(tank["id"], "2026-10-01T20:00:00Z", 35000)
    assert_tank(refreshed)
    assert refreshed["current_level_liters"] == 35000
    # interval burns 300 then 200 L/h: instant tracks the latest interval.
    assert refreshed["burn_rate_instant_lph"] == 200
    # two intervals: wma = 0.5*200 + 0.25*300 = 175.
    assert refreshed["burn_rate_wma_lph"] == 175
    # instant runout: 20:00 + (35000-5000)/200 h = +150h -> 2026-10-08T02:00:00Z.
    assert _parse_instant(refreshed["projected_runout_instant_at"]) == _parse_instant(
        "2026-10-08T02:00:00Z"
    )
    # wma runout: 30000/175 h = 617142.857s, rounded half up to 617143s.
    assert _parse_instant(refreshed["projected_runout_wma_at"]) == _parse_instant(
        "2026-10-08T23:25:43Z"
    )
    assert refreshed["status"] == "NORMAL", (
        "35000 is above the reorder point 20000, so no delivery may be created"
    )


def test_runout_null_until_two_readings(api):
    """PRD section 3.5: "Both are null while the tank has fewer than two
    readings, and both are null whenever the applicable burn rate is zero or
    negative."

    Design: Corner/calculations/runout_null_until_two_readings
    """
    set_logical_clock()
    customer = create_customer(name="Fabrikam Chips", segment="ELECTRONICS",
                               credit_standing="PRIME")
    tank = create_tank(customer["id"])
    refreshed = post_telemetry(tank["id"], "2026-10-01T00:00:00Z", 30000)
    assert_tank(refreshed)
    assert refreshed["burn_rate_instant_lph"] is None
    assert refreshed["burn_rate_wma_lph"] is None
    assert refreshed["projected_runout_instant_at"] is None
    assert refreshed["projected_runout_wma_at"] is None
    assert refreshed["current_level_liters"] == 30000
    assert refreshed["status"] == "NORMAL"


def test_telemetry_reading_is_immutable_append_only(api):
    """PRD section 2.5: "`TelemetryReading` is the single exception. As an
    append-only measurement it carries only `id` and `created_at`; `updated_at`
    and `version` are absent from it entirely."
    PRD section 3.5: "Readings flow in through the `TelemetryGateway`, each
    carrying `measured_at` and `level_liters`, and each is recorded as an
    immutable `TelemetryReading` whose `tank_id` comes from the path."

    Design: Corner/entities/telemetry_reading_is_immutable_append_only
    """
    set_logical_clock()
    customer = create_customer(name="Fabrikam Chips", segment="ELECTRONICS",
                               credit_standing="PRIME")
    tank = create_tank(customer["id"])
    post_telemetry(tank["id"], "2026-10-01T00:00:00Z", 25000)
    post_telemetry(tank["id"], "2026-10-01T05:00:00Z", 20000)
    readings, _ = validate_paginated(api_client.list_telemetry_readings(
        tank["id"], TEST_USERS["telemetry_gateway_headers"]
    ))
    assert len(readings) == 2
    assert [r["measured_at"] for r in readings] == [
        "2026-10-01T00:00:00Z", "2026-10-01T05:00:00Z",
    ], "readings must list in chronological measured_at order"
    assert [r["level_liters"] for r in readings] == [25000, 20000]
    for reading in readings:
        assert_telemetry_reading(reading)


def test_telemetry_out_of_order_reading_rejected(api):
    """PRD section 3.5: "Two rules keep the series clean, and both are enforced
    before any analytics run: `measured_at` must be strictly later than the
    tank's latest existing reading, and the level must lie within 0 and the
    tank's capacity inclusive — either violation is rejected with
    `ERR_READING_OUT_OF_ORDER`."

    Design: Corner/state_machines/telemetry_out_of_order_reading_rejected
    """
    set_logical_clock()
    customer = create_customer(name="Fabrikam Chips", segment="ELECTRONICS",
                               credit_standing="PRIME")
    tank = create_tank(customer["id"])
    post_telemetry(tank["id"], "2026-10-01T00:00:00Z", 25000)
    response = api_client.create_telemetry_reading(
        tank["id"],
        create_telemetry_payload("2026-10-01T00:00:00Z", 24000),
        TEST_USERS["telemetry_gateway_headers"],
    )
    validate_error(response, ApiErrorId.ERR_READING_OUT_OF_ORDER)
    after = validate_success(api_client.get_tank(
        tank["id"], TEST_USERS["telemetry_gateway_headers"]
    ))
    assert after["current_level_liters"] == 25000, (
        "a rejected reading must not mutate the tank level"
    )


def test_immediate_read_after_write_consistency(api):
    """PRD section 3.5: "A new tank's `status` reads `NORMAL`, and its
    `current_level_liters` stays null until the first reading arrives."
    PRD section 2.2: "Unless otherwise noted, operations that create or modify
    a resource will return the created or updated resource object in the data
    field."
    PRD section 2.5: "`version`: an integer that increments on every mutation
    of the resource."

    Design: Corner/consistency_model/immediate_read_after_write_consistency
    """
    set_logical_clock()
    customer = create_customer(name="Fabrikam Chips", segment="ELECTRONICS",
                               credit_standing="PRIME")
    created = validate_success(api_client.create_tank(
        create_tank_payload(customer["id"]), TEST_USERS["plant_operator_headers"]
    ), 201)
    assert_tank(created)
    assert created["status"] == "NORMAL", (
        "the create response already carries the eagerly computed posture"
    )
    assert created["current_level_liters"] is None
    fetched = validate_success(api_client.get_tank(
        created["id"], TEST_USERS["plant_operator_headers"]
    ))
    assert fetched["status"] == "NORMAL"
    assert fetched["current_level_liters"] is None
    assert fetched["version"] == created["version"], (
        "a read is not a mutation: version must be identical on create and GET"
    )
