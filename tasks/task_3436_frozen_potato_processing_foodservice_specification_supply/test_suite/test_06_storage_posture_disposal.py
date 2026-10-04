"""Storage cells: posture derivation thresholds, reading immutability, lot
disposal, byproduct batches, and the facility stock conservation invariant."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_byproduct_batch,
    deliver_lot,
    make_facility,
    record_reading,
    set_clock,
    setup_procurement,
    validate_error,
    validate_paginated,
    validate_success,
)

GRM = TEST_USERS["grower_relations_manager_headers"]
QA = TEST_USERS["qa_lead_headers"]
STORAGE = TEST_USERS["storage_operator_headers"]


def test_reading_can_drive_posture_normal_straight_to_quarantined(api):
    """PRD §3.3: "if the latest reading's `disease_incidence_pct` is at least
    6.0 or its `sprout_index` is at least 4.0, the posture becomes
    `QUARANTINED`; otherwise, if `disease_incidence_pct` is at least 3.0 or
    `sprout_index` is at least 2.0 — a sprout index of exactly 2.0 already
    qualifies — the posture becomes `WATCH`; otherwise the facility is
    `NORMAL`."
    PRD §2.8: "A facility is created in `NORMAL` posture."
    PRD §3.3: "All six transitions among the three postures occur
    automatically as readings arrive".

    Design: Corner/state_machines/reading_can_drive_posture_normal_straight_to_quarantined
    """
    set_clock(api=api)
    facility = make_facility(api=api)
    assert facility["posture"] == "NORMAL"

    updated = record_reading(
        facility["id"], api=api,
        recorded_at="2026-09-02T00:00:00Z", temperature_f=41.0, humidity_pct=94.0,
        co2_pct=4.0, sprout_index=1.0, disease_incidence_pct=7.0,
    )
    assert updated["posture"] == "QUARANTINED", (
        f"disease 7.0 (>= 6.0) jumps NORMAL straight to QUARANTINED, got {updated['posture']}"
    )
    assert len(updated["recent_readings"]) == 1
    assert updated["recent_readings"][0]["disease_incidence_pct"] == 7.0

    recovered = record_reading(
        facility["id"], api=api,
        recorded_at="2026-09-03T00:00:00Z", temperature_f=38.0, humidity_pct=90.0,
        co2_pct=3.0, sprout_index=1.0, disease_incidence_pct=2.0,
    )
    assert recovered["posture"] == "NORMAL", "the latest reading rules: a clean reading recovers directly"


def test_posture_thresholds_sprout_2_watch_4_quarantine_inclusive(api):
    """PRD §3.3: "The thresholds are inclusive: if the latest reading's
    `disease_incidence_pct` is at least 6.0 or its `sprout_index` is at least
    4.0, the posture becomes `QUARANTINED`; otherwise, if
    `disease_incidence_pct` is at least 3.0 or `sprout_index` is at least 2.0
    — a sprout index of exactly 2.0 already qualifies — the posture becomes
    `WATCH`; otherwise the facility is `NORMAL`."

    Design: Corner/calculations/posture_thresholds_sprout_2_watch_4_quarantine_inclusive
    """
    set_clock(api=api)
    facility = make_facility(api=api)

    watch = record_reading(
        facility["id"], api=api,
        recorded_at="2026-09-02T00:00:00Z", temperature_f=38.0, humidity_pct=90.0,
        co2_pct=3.0, sprout_index=2.0, disease_incidence_pct=1.0,
    )
    assert watch["posture"] == "WATCH", "sprout exactly 2.0 is inclusively WATCH"

    quarantined = record_reading(
        facility["id"], api=api,
        recorded_at="2026-09-03T00:00:00Z", temperature_f=39.0, humidity_pct=91.0,
        co2_pct=3.2, sprout_index=4.0, disease_incidence_pct=1.0,
    )
    assert quarantined["posture"] == "QUARANTINED", "sprout exactly 4.0 is inclusively QUARANTINED"

    normal = record_reading(
        facility["id"], api=api,
        recorded_at="2026-09-04T00:00:00Z", temperature_f=38.0, humidity_pct=90.0,
        co2_pct=3.0, sprout_index=1.9, disease_incidence_pct=2.9,
    )
    assert normal["posture"] == "NORMAL", "1.9 / 2.9 sit strictly below both WATCH thresholds"


def test_byproduct_batch_is_immutable_without_version_or_updated_at(api):
    """PRD §2.4: "One entity deviates from this convention: the
    `ByproductBatch` is an immutable system-created record and carries only
    `id` and `created_at`; it has neither `updated_at` nor `version`."
    PRD §3.3: "The batch's `unit_revenue_cents_per_cwt` follows a fixed tariff
    by routing: 900 cents per hundredweight for `CATTLE_FEED`, 1,400 for
    `STARCH_RECOVERY`, and 0 for `CONDEMNED_WASTE`."

    Design: Corner/entities/byproduct_batch_is_immutable_without_version_or_updated_at
    """
    world = setup_procurement(api=api)
    lot = deliver_lot(
        world["contract"]["id"], world["facility"]["id"], world["grower"]["id"], api=api
    )
    validate_success(api.dispose_potato_lot(lot["id"], {"disposition": "STARCH_RECOVERY"}, QA))

    rows, _ = validate_paginated(
        api.list_byproduct_batches(QA, params={"source_lot_id": lot["id"]})
    )
    assert len(rows) == 1, "exactly one batch is booked for the disposed lot"
    batch = rows[0]
    assert_byproduct_batch(batch)  # enforces: id + created_at present, no version/updated_at
    assert batch["stream"] == "WHOLE_LOT"
    assert batch["routing"] == "STARCH_RECOVERY"
    assert batch["weight_cwt"] == 1000.0
    assert batch["unit_revenue_cents_per_cwt"] == 1400
    assert batch["total_revenue_cents"] == 1400000, "1000.0 cwt x 1400"


def test_facility_stock_store_then_dispose_restores_baseline(api):
    """PRD §3.3: "That stock figure is a live derived quantity: the sum of
    `net_weight_cwt` over the facility's lots in `IN_STORAGE` status, so a lot
    stops contributing the moment it becomes `ALLOCATED` or `DISPOSED`."
    PRD §3.3: "The lot moves to `DISPOSED`, its `disposition` field — null
    until this moment — records the chosen routing, its facility's
    `current_stock_cwt` falls by the lot's `net_weight_cwt`, and the system
    books a `ByproductBatch` with `stream` `WHOLE_LOT`, `routing` copied from
    the disposition, `weight_cwt` equal to the lot's `net_weight_cwt`, and
    `source_lot_id` pointing at the lot (with `source_run_id` null)."

    Design: Difficulty/compensating_invariant/facility_stock_store_then_dispose_restores_baseline
    """
    world = setup_procurement(api=api)
    facility_id = world["facility"]["id"]
    baseline = validate_success(api.get_storage_facility(facility_id, STORAGE))
    assert baseline["current_stock_cwt"] == 0.0

    lot = deliver_lot(
        world["contract"]["id"], facility_id, world["grower"]["id"], api=api
    )
    mid = validate_success(api.get_storage_facility(facility_id, STORAGE))
    assert mid["current_stock_cwt"] == 1000.0, "intake adds the lot's net weight"

    disposed = validate_success(api.dispose_potato_lot(lot["id"], {"disposition": "CATTLE_FEED"}, QA))
    assert disposed["status"] == "DISPOSED"
    assert disposed["disposition"] == "CATTLE_FEED"

    end = validate_success(api.get_storage_facility(facility_id, STORAGE))
    assert end["current_stock_cwt"] == 0.0, (
        "store + dispose conserve the stock quantity: the baseline is restored exactly"
    )

    rows, _ = validate_paginated(api.list_byproduct_batches(QA, params={"source_lot_id": lot["id"]}))
    assert len(rows) == 1
    assert rows[0]["weight_cwt"] == 1000.0
    assert rows[0]["routing"] == "CATTLE_FEED"
    assert rows[0]["total_revenue_cents"] == 900000, "1000.0 cwt x 900 cattle-feed tariff"


def test_disposal_does_not_un_deliver_and_condemned_waste_is_free(api):
    """PRD §3.1: "The read-only `delivered_volume_cwt` is the sum of
    `net_weight_cwt` over all of the contract's lots with `origin`
    `CONTRACTED`, regardless of lot status; disposing of a lot does not
    un-deliver it."
    PRD §3.3: "The batch's `unit_revenue_cents_per_cwt` follows a fixed tariff
    by routing: 900 cents per hundredweight for `CATTLE_FEED`, 1,400 for
    `STARCH_RECOVERY`, and 0 for `CONDEMNED_WASTE`."

    Design: Difficulty/compensating_invariant/facility_stock_store_then_dispose_restores_baseline
    """
    world = setup_procurement(api=api)
    lot = deliver_lot(
        world["contract"]["id"], world["facility"]["id"], world["grower"]["id"], api=api
    )
    validate_success(api.dispose_potato_lot(lot["id"], {"disposition": "CONDEMNED_WASTE"}, QA))

    facility = validate_success(api.get_storage_facility(world["facility"]["id"], STORAGE))
    assert facility["current_stock_cwt"] == 0.0, "the disposed lot leaves the stock sum"

    contract = validate_success(api.get_crop_contract(world["contract"]["id"], GRM))
    assert contract["delivered_volume_cwt"] == 1000.0, (
        "delivered volume is a historical fact: disposal does not un-deliver the lot"
    )

    rows, _ = validate_paginated(api.list_byproduct_batches(QA, params={"source_lot_id": lot["id"]}))
    assert rows[0]["routing"] == "CONDEMNED_WASTE"
    assert rows[0]["total_revenue_cents"] == 0, "condemned waste earns nothing"
