"""Shipment lifecycle, cold-storage aggregate capacity, and the sellable-units ledger."""
from test_helpers import (
    ApiErrorId, TEST_USERS,
    validate_success, validate_error,
    setup_released_batch, setup_batch_process_complete,
    create_shipment_entity, create_shipment_payload, shipment_action,
    get_batch_entity, set_logical_clock,
    assert_shipment,
)

_SP = TEST_USERS["supply_planner_headers"]


def _small_released_env():
    """RELEASED batch of final yield 625 on a 2 L train; site cold storage 500 units."""
    return setup_released_batch(
        stage_durations=(10,),
        site_overrides={"name": "Cork Fill-Finish", "region": "IE-COR",
                        "monthly_capacity_hours": 5000, "cold_storage_capacity_units": 500,
                        "licensed_authorities": ["EMA"]},
        train_overrides={"train_code": "TR-S", "capacity_liters": 2,
                         "supported_molecule_types": ["MONOCLONAL_ANTIBODY"]},
        titer_values=(2.5,))


def test_shipment_create_starts_planned_with_no_evaluation(api):
    """PRD §3.6: "A created shipment records its `batch_lot_id`, enters `PLANNED` — occupying cold storage per §2.11 — with `shipped_at` and `delivered_at` null and both `excursion_evaluation` and `evaluation_variant` at `NONE`."

    Design: Corner/state_machines/shipment_create_starts_planned_with_no_evaluation
    """
    env = setup_released_batch()
    payload = create_shipment_payload(destination_region="IE-DUB", market_type="COMMERCIAL",
                                      quantity_units=1000)
    data = validate_success(api.create_shipment(env["batch"]["id"], payload, _SP),
                            expected_status=201)
    assert_shipment(data)
    assert data["status"] == "PLANNED"
    assert data["excursion_evaluation"] == "NONE" and data["evaluation_variant"] == "NONE"
    assert data["shipped_at"] is None and data["delivered_at"] is None


def test_shipment_quantity_exceeds_available_rejected(api):
    """PRD §3.6: "`quantity_units` must not exceed the batch's `available_to_ship_units` (`ERR_SHIPMENT_QUANTITY_EXCEEDS_AVAILABLE`, HTTP 409)"

    Design: Corner/validations/shipment_quantity_exceeds_available_rejected
    """
    env = setup_released_batch()  # final yield 625000, no shipments yet
    payload = create_shipment_payload(quantity_units=625001)
    resp = api.create_shipment(env["batch"]["id"], payload, _SP)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_QUANTITY_EXCEEDS_AVAILABLE)


def test_deliver_at_expiry_exact_allowed_then_expired(api, supply_planner_headers):
    """PRD §3.6: "the logical clock must be at or before the batch's `expiry_utc` — delivery exactly at expiry is allowed, and a clock past expiry is rejected with `ERR_BATCH_EXPIRED` (HTTP 409); a successful delivery stamps `delivered_at`."
    PRD §3.4: "sets `expiry_utc` to `process_completed_at` plus the product's `shelf_life_hours`"

    Design: Corner/calculations/deliver_at_expiry_exact_allowed_then_expired
    """
    env = setup_released_batch(
        stage_durations=(10,),
        product_overrides={
            "product_code": "ENZ-048", "molecule_type": "RECOMBINANT_ENZYME",
            "market_scope": "BOTH", "requires_cold_chain": True,
            "min_storage_temp_c": 2.0, "max_storage_temp_c": 8.0,
            "shelf_life_hours": 48, "changeover_hours": 8,
            "same_product_turnaround_hours": 4, "required_materials": []},
        train_overrides={"train_code": "TR-E", "capacity_liters": 500,
                         "supported_molecule_types": ["RECOMBINANT_ENZYME"]},
        campaign_overrides={"demand_type": "CLINICAL",
                            "planned_start_utc": "2026-10-01T00:00:00Z",
                            "planned_end_utc": "2026-10-05T00:00:00Z",
                            "upstream_hours": 8, "downstream_hours": 24},
        titer_values=(2.5,))
    batch_id = env["batch"]["id"]
    assert env["batch"]["expiry_utc"].startswith("2026-10-03T10:00:00"), \
        "completion 2026-10-01T10:00Z + 48 h"
    s1 = create_shipment_entity(batch_id, quantity_units=10, market_type="CLINICAL",
                                destination_region="US-BOS")
    s2 = create_shipment_entity(batch_id, quantity_units=10, market_type="CLINICAL",
                                destination_region="US-NYC")
    shipment_action(s1["id"], "SHIP")
    shipment_action(s2["id"], "SHIP")
    set_logical_clock("2026-10-03T10:00:00Z")
    delivered = validate_success(api.shipment_action(s1["id"], "DELIVER", _SP))
    assert delivered["status"] == "DELIVERED", "delivery exactly at expiry is allowed"
    set_logical_clock("2026-10-03T10:00:01Z")
    resp = api.shipment_action(s2["id"], "DELIVER", supply_planner_headers)
    validate_error(resp, ApiErrorId.ERR_BATCH_EXPIRED)
    late = validate_success(api.get_shipment(s2["id"], _SP))
    assert late["status"] == "IN_TRANSIT" and late["delivered_at"] is None


def test_cold_storage_exact_capacity_allowed_one_over_rejected(api):
    """PRD §2.11: "Planning a new shipment is admitted only while the existing occupancy plus the new shipment's `quantity_units` is less than or equal to `cold_storage_capacity_units`; a plan that lands exactly at capacity is allowed, and one that overflows is rejected with `ERR_COLD_STORAGE_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/cold_storage_aggregate_capacity_overlap_semantics
    """
    env = _small_released_env()
    batch_id = env["batch"]["id"]
    assert get_batch_entity(batch_id)["quantity_units"] == 625
    s1 = create_shipment_entity(batch_id, quantity_units=300, destination_region="IE-DUB")
    s2 = create_shipment_entity(batch_id, quantity_units=200, destination_region="US-BOS")
    assert s1["status"] == "PLANNED" and s2["status"] == "PLANNED", "exactly 500 of 500"
    payload = create_shipment_payload(destination_region="US-SEA", quantity_units=1)
    resp = api.create_shipment(batch_id, payload, _SP)
    validate_error(resp, ApiErrorId.ERR_COLD_STORAGE_CAPACITY_EXCEEDED)  # 501 > 500


def test_shipping_frees_cold_storage_occupancy_immediately(api):
    """PRD §3.6: "Shipping moves a `PLANNED` shipment to `IN_TRANSIT`, stamps `shipped_at` with the logical clock, and releases the shipment's cold-storage occupancy at the origin site."
    PRD §2.11: "Occupancy is released the moment a shipment leaves `PLANNED` — by shipping, by cancellation, by the rejection-driven cancellation of §3.5, or by the quarantine cascade."

    Design: Difficulty/resource_temporal_overlap/cold_storage_aggregate_capacity_overlap_semantics
    """
    env = _small_released_env()
    batch_id = env["batch"]["id"]
    s1 = create_shipment_entity(batch_id, quantity_units=300, destination_region="IE-DUB")
    create_shipment_entity(batch_id, quantity_units=200, destination_region="US-BOS")
    shipment_action(s1["id"], "SHIP")  # frees 300 units of occupancy
    s3 = create_shipment_entity(batch_id, quantity_units=100, destination_region="US-SEA")
    assert s3["status"] == "PLANNED"


def test_shipment_cancel_restores_sellable_units_exactly(api):
    """PRD §3.6: "Cancelling moves a `PLANNED` shipment to `CANCELLED`, releases its occupancy, and restores the batch's `available_to_ship_units` by the shipment's `quantity_units`."
    PRD §3.4: "The batch's `available_to_ship_units` is `quantity_units` minus the sum of `quantity_units` over the batch's shipments in `PLANNED`, `IN_TRANSIT`, `EXCURSION_HOLD`, or `DELIVERED` — quarantined and cancelled shipments do not encumber it."

    Design: Difficulty/compensating_invariant/shipment_create_cancel_roundtrip_conserves_sellable_units
    """
    env = _small_released_env()
    batch_id = env["batch"]["id"]
    create_shipment_entity(batch_id, quantity_units=300, destination_region="IE-DUB")
    s2 = create_shipment_entity(batch_id, quantity_units=200, destination_region="US-BOS")
    assert get_batch_entity(batch_id)["available_to_ship_units"] == 125, "625 - 300 - 200"
    cancelled = shipment_action(s2["id"], "CANCEL")
    assert cancelled["status"] == "CANCELLED"
    assert get_batch_entity(batch_id)["available_to_ship_units"] == 325, \
        "cancel restores exactly the cancelled 200; no drift"


def test_post_cancel_replan_fits_storage_exactly(api):
    """PRD §2.11: "occupancy is the sum of `quantity_units` over every shipment in `PLANNED` status whose batch belongs to a campaign of a train of that site."
    PRD §2.11: "a plan that lands exactly at capacity is allowed"

    Design: Difficulty/compensating_invariant/shipment_create_cancel_roundtrip_conserves_sellable_units
    """
    env = _small_released_env()
    batch_id = env["batch"]["id"]
    create_shipment_entity(batch_id, quantity_units=300, destination_region="IE-DUB")
    s2 = create_shipment_entity(batch_id, quantity_units=200, destination_region="US-BOS")
    shipment_action(s2["id"], "CANCEL")
    s3 = create_shipment_entity(batch_id, quantity_units=200, destination_region="US-SEA")
    assert s3["status"] == "PLANNED", "storage exactly 300 + 200 == 500; availability 325 >= 200"
    assert get_batch_entity(batch_id)["available_to_ship_units"] == 125


def test_shipment_create_on_unreleased_batch_beats_storage_gate(api):
    """PRD §3.6: "A `SupplyPlanner` plans a shipment against a batch whose `quality_status` is `RELEASED` (`ERR_BATCH_NOT_RELEASED`, HTTP 409, otherwise)"
    PRD §3.6: "After the release gate, the remaining checks run in this order: the shipment's `market_type` must equal the demand type of the batch's campaign (`ERR_MARKET_SCOPE_VIOLATION`, HTTP 422); `quantity_units` must not exceed the batch's `available_to_ship_units` (`ERR_SHIPMENT_QUANTITY_EXCEEDS_AVAILABLE`, HTTP 409); and the origin site's aggregate cold-storage rule of §2.11 must admit the new plan (`ERR_COLD_STORAGE_CAPACITY_EXCEEDED`)."

    Design: Difficulty/priority_pair_validation_conflict/shipment_create_referential_error_precedes_storage_fiscal
    """
    env = setup_batch_process_complete(
        stage_durations=(10,),
        site_overrides={"name": "Cork Fill-Finish", "region": "IE-COR",
                        "monthly_capacity_hours": 5000, "cold_storage_capacity_units": 500,
                        "licensed_authorities": ["EMA"]},
        train_overrides={"train_code": "TR-S", "capacity_liters": 2,
                         "supported_molecule_types": ["MONOCLONAL_ANTIBODY"]},
        titer_values=(2.5,))
    batch_id = env["batch"]["id"]
    assert get_batch_entity(batch_id)["quantity_units"] == 625
    assert env["batch"]["quality_status"] == "READY_FOR_REVIEW", "never submitted"
    payload = create_shipment_payload(destination_region="IE-DUB", quantity_units=600)
    resp = api.create_shipment(batch_id, payload, _SP)
    error_data = validate_error(resp, ApiErrorId.ERR_BATCH_NOT_RELEASED)
    assert error_data["error_id"] != "ERR_COLD_STORAGE_CAPACITY_EXCEEDED", \
        "600 > 500 would violate storage, but the release gate fires first"


def test_shipment_create_release_gate_fires_alone_under_capacity(api):
    """PRD §3.6: "A `SupplyPlanner` plans a shipment against a batch whose `quality_status` is `RELEASED` (`ERR_BATCH_NOT_RELEASED`, HTTP 409, otherwise)"

    Design: Difficulty/priority_pair_validation_conflict/shipment_create_referential_error_precedes_storage_fiscal
    """
    env = setup_batch_process_complete(
        stage_durations=(10,),
        site_overrides={"name": "Cork Fill-Finish", "region": "IE-COR",
                        "monthly_capacity_hours": 5000, "cold_storage_capacity_units": 500,
                        "licensed_authorities": ["EMA"]},
        train_overrides={"train_code": "TR-S", "capacity_liters": 2,
                         "supported_molecule_types": ["MONOCLONAL_ANTIBODY"]},
        titer_values=(2.5,))
    payload = create_shipment_payload(destination_region="IE-DUB", quantity_units=400)
    resp = api.create_shipment(env["batch"]["id"], payload, _SP)
    validate_error(resp, ApiErrorId.ERR_BATCH_NOT_RELEASED)
