"""Temperature-excursion detection guards and the SCREENING vs MKT verdict variants."""
from test_helpers import (
    ApiErrorId, TEST_USERS,
    validate_success, validate_error,
    setup_released_batch,
    create_shipment_entity, shipment_action, create_reading_entity, record_readings,
    evaluate_excursion,
)

_SP = TEST_USERS["supply_planner_headers"]
_ADMIN = TEST_USERS["platform_admin_headers"]


def _shipment_on_hold(api, readings, market_type="COMMERCIAL", titer_values=(2.4, 2.6),
                      campaign_overrides=None):
    """RELEASED batch + IN_TRANSIT shipment held by the given reading series."""
    env = setup_released_batch(campaign_overrides=campaign_overrides or {},
                               titer_values=titer_values)
    shipment = create_shipment_entity(env["batch"]["id"], quantity_units=1000,
                                      market_type=market_type)
    shipment_action(shipment["id"], "SHIP")
    record_readings(shipment["id"], readings, start_utc="2026-10-22T01:00:00Z")
    held = validate_success(api.get_shipment(shipment["id"], _ADMIN))
    assert held["status"] == "EXCURSION_HOLD"
    assert held["excursion_evaluation"] == "PENDING"
    return env, shipment


def test_mkt_exactly_at_allowance_boundary_is_acceptable(api):
    """PRD §3.6: "The `MKT` verdict is `ACCEPTABLE` when the rounded mean kinetic temperature is less than or equal to `max_storage_temp_c` plus a 1.0 degree allowance — a value landing exactly on the allowance is acceptable"
    PRD §3.6: "An `ACCEPTABLE` verdict returns the shipment to `IN_TRANSIT`"

    Design: Difficulty/combinatorial_formula/mkt_three_guard_boundary_at_allowance
    """
    _env, shipment = _shipment_on_hold(api, [9.0, 9.0, 9.0])
    result = evaluate_excursion(shipment["id"])
    assert result["excursion_evaluation"] == "ACCEPTABLE", "MKT exactly 9.000 <= 8.0 + 1.0"
    assert result["evaluation_variant"] == "MKT"
    assert result["status"] == "IN_TRANSIT"


def test_count_guard_holds_exactly_on_third_reading_above_max(api):
    """PRD §3.6: "counting the new reading, the number of this shipment's readings above `max_storage_temp_c` exceeds two."
    PRD §3.6: "any one of them flips the shipment to `EXCURSION_HOLD` with `excursion_evaluation` set to `PENDING`"

    Design: Difficulty/combinatorial_formula/mkt_three_guard_boundary_at_allowance
    """
    env = setup_released_batch()
    shipment = create_shipment_entity(env["batch"]["id"], quantity_units=1000)
    shipment_action(shipment["id"], "SHIP")
    create_reading_entity(shipment["id"], 9.0, "2026-10-02T01:00:00Z")
    create_reading_entity(shipment["id"], 9.0, "2026-10-02T02:00:00Z")
    mid = validate_success(api.get_shipment(shipment["id"], _ADMIN))
    assert mid["status"] == "IN_TRANSIT" and mid["excursion_evaluation"] == "NONE", \
        "two readings above the max do not exceed the count of two"
    create_reading_entity(shipment["id"], 9.0, "2026-10-02T03:00:00Z")
    held = validate_success(api.get_shipment(shipment["id"], _ADMIN))
    assert held["status"] == "EXCURSION_HOLD"
    assert held["excursion_evaluation"] == "PENDING"


def test_screening_variant_rejects_series_mkt_accepts(api):
    """PRD §3.6: "For `CLINICAL` shipments the `SCREENING` variant applies a count-and-band rule: the excursion is `ACCEPTABLE` when every recorded reading lies within the labeled band from `min_storage_temp_c` to `max_storage_temp_c` inclusive *and* no more than two readings exceed the maximum — exactly two passes."
    PRD §3.6: "an `UNACCEPTABLE` verdict moves it to `QUARANTINED`; either way `excursion_evaluation` records the verdict."

    Design: Difficulty/dual_variant_calc/excursion_screening_vs_mkt_verdicts_diverge
    """
    _env, shipment = _shipment_on_hold(
        api, [9.0, 9.0, 9.0, 5.0, 5.0], market_type="CLINICAL",
        titer_values=(2.5,), campaign_overrides={"demand_type": "CLINICAL"})
    result = evaluate_excursion(shipment["id"])
    assert result["evaluation_variant"] == "SCREENING"
    assert result["excursion_evaluation"] == "UNACCEPTABLE", \
        "three readings above 8.0 exceed the screening count of two"
    assert result["status"] == "QUARANTINED"


def test_mkt_variant_accepts_series_screening_rejects(api):
    """PRD §3.6: "The `MKT` verdict is `ACCEPTABLE` when the rounded mean kinetic temperature is less than or equal to `max_storage_temp_c` plus a 1.0 degree allowance — a value landing exactly on the allowance is acceptable — *and* the highest reading is at most `max_storage_temp_c` plus 5.0 degrees, *and* the lowest reading is at least `min_storage_temp_c` minus 0.5 degrees; otherwise it is `UNACCEPTABLE`. The kinetic variant can accept a series that screening would reject, and vice versa."

    Design: Difficulty/dual_variant_calc/excursion_screening_vs_mkt_verdicts_diverge
    """
    _env, shipment = _shipment_on_hold(api, [9.0, 9.0, 9.0, 5.0, 5.0])
    result = evaluate_excursion(shipment["id"])
    assert result["evaluation_variant"] == "MKT"
    assert result["excursion_evaluation"] == "ACCEPTABLE", \
        "MKT 7.621 <= 9.0; spike 9.0 <= 13.0; freeze 5.0 >= 1.5"
    assert result["status"] == "IN_TRANSIT"


def test_deliver_quarantined_shipment_rejected(api, supply_planner_headers):
    """PRD §3.6: "Requesting any of the three actions from a shipment state that does not admit it is `ERR_INVALID_SHIPMENT_STATE` (HTTP 409)."
    PRD §3.6: "an `UNACCEPTABLE` verdict moves it to `QUARANTINED`"

    Design: Corner/state_machines/deliver_quarantined_shipment_rejected
    """
    env = setup_released_batch()
    shipment = create_shipment_entity(env["batch"]["id"], quantity_units=1000,
                                      destination_region="IE-DUB", market_type="COMMERCIAL")
    shipment_action(shipment["id"], "SHIP")
    create_reading_entity(shipment["id"], 14.0, "2026-10-02T01:00:00Z")
    held = validate_success(api.get_shipment(shipment["id"], _ADMIN))
    assert held["status"] == "EXCURSION_HOLD" and held["excursion_evaluation"] == "PENDING"
    evaluated = evaluate_excursion(shipment["id"])
    assert evaluated["excursion_evaluation"] == "UNACCEPTABLE", "14.0 spike exceeds 13.0"
    assert evaluated["status"] == "QUARANTINED"
    resp = api.shipment_action(shipment["id"], "DELIVER", supply_planner_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_SHIPMENT_STATE)
    final = validate_success(api.get_shipment(shipment["id"], _ADMIN))
    assert final["status"] == "QUARANTINED" and final["delivered_at"] is None
