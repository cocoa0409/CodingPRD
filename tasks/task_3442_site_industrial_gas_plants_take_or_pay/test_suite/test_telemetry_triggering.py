"""Telemetry-driven replenishment: reorder-point edge semantics, posture
transitions, and open-delivery suppression of the auto-trigger."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_customer,
    create_tank,
    list_tank_deliveries,
    post_telemetry,
    set_logical_clock,
    validate_success,
)


def test_tank_reorder_point_exact_trigger(api):
    """PRD section 3.5: "Posture is recomputed on every accepted reading. A
    level at or below `safety_stock_liters` puts the tank into `CRITICAL`; a
    level above the safety stock but at or below `reorder_point_liters` puts it
    into `REORDER_DUE`; anything above the reorder point is `NORMAL`."
    PRD section 3.5: "On such an entry edge, if the tank has no open delivery —
    open meaning `transport_status` `SCHEDULED`, or `DELIVERED` with
    `quality_status` still `QC_PENDING` — the system creates one automatically:
    `triggered_by` set to `TELEMETRY`, `quantity_liters` equal to the tank's
    headroom (capacity minus current level, an integer number of liters),
    `route_date` set to the current logical date, and
    `required_purity_percent` with `max_impurity_ppm` snapshotted from the
    tank."

    Design: Difficulty/boundary_precision_check/tank_reorder_point_exact_trigger
    """
    set_logical_clock()
    customer = create_customer(name="Fabrikam Chips", segment="ELECTRONICS",
                               credit_standing="PRIME")
    tank_eq = create_tank(customer["id"], required_purity_percent=99.9,
                          max_impurity_ppm=50)
    tank_gt = create_tank(customer["id"], required_purity_percent=99.9,
                          max_impurity_ppm=50)
    post_telemetry(tank_eq["id"], "2026-10-01T00:00:00Z", 25000)
    post_telemetry(tank_gt["id"], "2026-10-01T00:00:00Z", 25000)

    at_point = post_telemetry(tank_eq["id"], "2026-10-01T05:00:00Z", 20000)
    assert at_point["status"] == "REORDER_DUE", (
        f"level exactly equal to the reorder point triggers (<= semantics), got {at_point['status']}"
    )
    deliveries = list_tank_deliveries(tank_eq["id"])
    assert len(deliveries) == 1
    assert deliveries[0]["triggered_by"] == "TELEMETRY"
    assert deliveries[0]["quantity_liters"] == 30000, (
        f"headroom 50000 - 20000 sizes the delivery at 30000, got {deliveries[0]['quantity_liters']}"
    )

    above = post_telemetry(tank_gt["id"], "2026-10-01T05:00:00Z", 20001)
    assert above["status"] == "NORMAL", (
        f"one liter above the reorder point stays NORMAL, got {above['status']}"
    )
    assert list_tank_deliveries(tank_gt["id"]) == []


def test_tank_critical_posture_then_recovery(api):
    """PRD section 3.5: "A level at or below `safety_stock_liters` puts the
    tank into `CRITICAL`; a level above the safety stock but at or below
    `reorder_point_liters` puts it into `REORDER_DUE`; anything above the
    reorder point is `NORMAL`. The tank's `status` follows the levels through
    all six transitions among the three states as inventory falls and
    recovers."
    PRD section 3.5: "When an open delivery already exists, the trigger is
    skipped — a tank never accumulates duplicate open deliveries."

    Design: Corner/state_machines/tank_critical_posture_then_recovery
    """
    set_logical_clock()
    customer = create_customer(name="Fabrikam Chips", segment="ELECTRONICS",
                               credit_standing="PRIME")
    tank = create_tank(customer["id"])
    post_telemetry(tank["id"], "2026-10-01T00:00:00Z", 25000)
    low = post_telemetry(tank["id"], "2026-10-01T05:00:00Z", 20000)
    assert low["status"] == "REORDER_DUE"
    critical = post_telemetry(tank["id"], "2026-10-01T09:00:00Z", 5000)
    assert critical["status"] == "CRITICAL", (
        "level exactly at safety_stock 5000 puts the tank into CRITICAL (<= semantics)"
    )
    recovered = post_telemetry(tank["id"], "2026-10-02T00:00:00Z", 45000)
    assert recovered["status"] == "NORMAL", (
        f"refill above the reorder point recovers to NORMAL, got {recovered['status']}"
    )
    deliveries = list_tank_deliveries(tank["id"])
    assert len(deliveries) == 1, (
        "the CRITICAL entry edge is suppressed by the still-open delivery"
    )
    assert deliveries[0]["triggered_by"] == "TELEMETRY"


def test_telemetry_trigger_suppressed_while_delivery_open(api):
    """PRD section 3.5: "Replenishment is edge-triggered, never
    level-triggered: a delivery is considered only when a reading moves the
    tank into `REORDER_DUE` or `CRITICAL`, and a reading that merely deepens an
    existing low posture triggers nothing."
    PRD section 3.5: "When an open delivery already exists, the trigger is
    skipped — a tank never accumulates duplicate open deliveries."

    Design: Corner/calculations/telemetry_trigger_suppressed_while_delivery_open
    """
    set_logical_clock()
    customer = create_customer(name="Fabrikam Chips", segment="ELECTRONICS",
                               credit_standing="PRIME")
    tank = create_tank(customer["id"])
    post_telemetry(tank["id"], "2026-10-01T00:00:00Z", 25000)
    post_telemetry(tank["id"], "2026-10-01T05:00:00Z", 20000)
    deeper = post_telemetry(tank["id"], "2026-10-01T06:00:00Z", 19500)
    assert deeper["status"] == "REORDER_DUE"
    critical = post_telemetry(tank["id"], "2026-10-01T07:00:00Z", 4000)
    assert critical["status"] == "CRITICAL", (
        f"4000 <= safety stock 5000 must be CRITICAL, got {critical['status']}"
    )
    deliveries = list_tank_deliveries(tank["id"])
    assert len(deliveries) == 1, (
        f"exactly one delivery across three low readings, got {len(deliveries)}"
    )
    assert deliveries[0]["triggered_by"] == "TELEMETRY"
    assert deliveries[0]["quantity_liters"] == 30000, (
        "the delivery is sized at the REORDER_DUE entry edge (50000 - 20000)"
    )
