"""Recall enforcement: the depth-4 cascade across plantings, the plant lot,
the harvest window, and the agreement, plus post-recall referential lockout."""
from test_helpers import (
    validate_error,
    ApiErrorId, TEST_USERS,
    create_plant_lot_payload,
    set_clock, create_released_variety, create_grower, create_active_agreement,
    create_harvest_window, create_plant_lot, plan_planting, confirm_planting,
    recall_variety, enforce_recall, get_planting, get_plant_lot,
    get_harvest_window, get_agreement,
)

NURSERY = TEST_USERS["nursery_manager_headers"]


def _recall_scenario(api):
    """V3 BLACKBERRY released; G5/A5 (WA-SKAGIT, max 10000); W9
    [2026-10-26, 2026-11-02) target 5000 covering the 90-day first harvest;
    lot L9 1000 plants; PA planned+confirmed 600 (yield 1200 booked); PB
    planned 200, never confirmed; V3 recalled with the default 22c/plant."""
    set_clock("2026-06-01T00:00:00Z")
    variety = create_released_variety(variety_code="BRB-BLK-01",
                                      berry_type="BLACKBERRY",
                                      name="Midnight Canyon")
    grower = create_grower(legal_name="Skagit Delta Berries",
                           region_code="WA-SKAGIT")
    agreement = create_active_agreement(
        grower, variety, region_code="WA-SKAGIT", max_planting_units=10000,
        cultural_practice_codes=["CONVENTIONAL"])
    window = create_harvest_window(variety, region_code="WA-SKAGIT",
                                   week_start="2026-10-26T00:00:00Z",
                                   week_end="2026-11-02T00:00:00Z",
                                   target_volume_kg=5000)
    lot = create_plant_lot(agreement, variety, quantity_plants=1000,
                           nursery_code="NUR-WA-01")
    pa = plan_planting(agreement, lot, grower, planned_plants=600)
    pb = plan_planting(agreement, lot, grower, planned_plants=200)
    set_clock("2026-08-02T00:00:00Z")
    confirm_planting(pa, grower, 600)
    order = recall_variety(variety["id"])  # default compensation 22c/plant
    return {"variety": variety, "grower": grower, "agreement": agreement,
            "window": window, "lot": lot, "pa": pa, "pb": pb, "order": order}


def test_recall_enforce_recalls_plantings_and_compensates(api):
    """PRD section 3.1: "Every planting whose plant lot's variety is the
    recalled variety and which is still `PLANNED` moves `PLANNED → RECALLED`:
    its reservation is released back to the lot (the lot's `plants_reserved`
    decreases by the planting's `planned_plants`), its
    `recall_compensation_cents` is set to 0 because those plants never entered
    the ground, and its `recalled_at` is stamped from the logical clock."
    PRD section 3.1: "the planting's `recall_compensation_cents` is set to
    `plants_planted_actual` multiplied by the order's
    `compensation_per_plant_cents`".
    PRD section 3.1: "The order then records `plantings_recalled_count` — the
    number of plantings the enforcement transitioned — and
    `total_compensation_cents` — the sum of the per-planting compensation
    amounts it produced".

    Design: Difficulty/transitive_cascade/recall_enforce_depth_cascade
    """
    s = _recall_scenario(api)
    order = enforce_recall(s["order"]["id"])
    assert order["status"] == "COMPLETE"
    assert order["plantings_recalled_count"] == 2
    assert order["total_compensation_cents"] == 13200, "600 planted x 22c"
    assert order["enforced_at"] is not None
    pa = get_planting(s["pa"]["id"])
    assert pa["status"] == "RECALLED"
    assert pa["recall_compensation_cents"] == 13200
    assert pa["recalled_at"] is not None
    pb = get_planting(s["pb"]["id"])
    assert pb["status"] == "RECALLED"
    assert pb["recall_compensation_cents"] == 0


def test_recall_enforce_cascades_lot_window_agreement(api):
    """PRD section 3.1: "A touched lot that still has `plants_available`
    greater than zero moves to `RECALLED`: its unplanted remainder is added to
    `plants_destroyed`".
    PRD section 3.1: "the booked harvest window's `booked_volume_kg` decreases
    by the planting's `expected_yield_kg`, the agreement's `units_planted`
    decreases by `plants_planted_actual`".
    PRD section 3.1: "from that moment, any attempt to create an agreement,
    ship a plant lot, or plan a planting that references a `RECALLED` variety
    is rejected with `ERR_VARIETY_RECALLED`."

    Design: Difficulty/transitive_cascade/recall_enforce_depth_cascade
    """
    s = _recall_scenario(api)
    enforce_recall(s["order"]["id"])
    lot = get_plant_lot(s["lot"]["id"])
    assert lot["status"] == "RECALLED"
    assert lot["plants_planted"] == 0
    assert lot["plants_reserved"] == 0
    assert lot["plants_destroyed"] == 1000, "600 in-ground + 400 remainder"
    assert lot["plants_available"] == 0
    window = get_harvest_window(s["window"]["id"])
    assert window["booked_volume_kg"] == 0, "the 1200 kg booking unwound"
    agreement = get_agreement(s["agreement"]["id"])
    assert agreement["units_planted"] == 0
    assert agreement["status"] == "ACTIVE", "issuance/enforcement leaves it ACTIVE"
    resp = api.create_plant_lot(
        create_plant_lot_payload(agreement["id"], s["variety"]["id"],
                                 quantity_plants=100, nursery_code="NUR-WA-01"),
        NURSERY)
    validate_error(resp, ApiErrorId.ERR_VARIETY_RECALLED)
