"""Compensating invariant: per-lot plant accounting conserves quantity_plants
across a forward reservation and its compensating cancellation."""
from test_helpers import (
    set_clock, create_released_variety, create_grower, create_active_agreement,
    create_plant_lot, plan_planting, exit_grower, get_plant_lot, get_planting,
    assert_plant_lot_conservation,
)


def _conservation_scenario(api):
    """V1 released; G10 with ACTIVE A10 (max 10000); lot L10 of 1000 plants;
    planting P10 planned 400 (never confirmed)."""
    set_clock("2026-06-01T00:00:00Z")
    variety = create_released_variety()
    grower = create_grower(legal_name="Aromas Fields Cooperative")
    agreement = create_active_agreement(grower, variety, max_planting_units=10000,
                                        cultural_practice_codes=["ORGANIC"])
    lot = create_plant_lot(agreement, variety, quantity_plants=1000,
                           nursery_code="NUR-CA-03")
    planting = plan_planting(agreement, lot, grower, planned_plants=400)
    return variety, grower, agreement, lot, planting


def test_plant_lot_conservation_at_create_and_reserve(api):
    """PRD section 3.4: "Thereafter `plants_available` is always exactly
    `quantity_plants` minus `plants_reserved`, minus `plants_planted`, minus
    `plants_destroyed`."
    PRD section 3.5: "A created planting starts `PLANNED`: it immediately
    reserves its intended count on the lot, increasing `plants_reserved` by
    `planned_plants`".

    Design: Difficulty/compensating_invariant/plant_lot_quantity_conservation
    """
    _, _, _, lot, _ = _conservation_scenario(api)
    fresh = get_plant_lot(lot["id"])
    assert fresh["plants_reserved"] == 400
    assert fresh["plants_planted"] == 0
    assert fresh["plants_destroyed"] == 0
    assert fresh["plants_available"] == 600
    assert_plant_lot_conservation(fresh)
    assert fresh["quantity_plants"] == 1000


def test_plant_lot_conservation_after_compensating_cancel(api):
    """PRD section 3.2: "every planting of each terminated agreement that is
    still `PLANNED` moves to `CANCELLED`; third, each cancelled planting
    releases its reservation, decreasing its plant lot's `plants_reserved` by
    its `planned_plants`."

    Design: Difficulty/compensating_invariant/plant_lot_quantity_conservation
    """
    _, grower, _, lot, planting = _conservation_scenario(api)
    exited = exit_grower(grower["id"])
    assert exited["status"] == "EXITED"
    cancelled = get_planting(planting["id"])
    assert cancelled["status"] == "CANCELLED"
    restored = get_plant_lot(lot["id"])
    assert restored["plants_reserved"] == 0
    assert restored["plants_planted"] == 0
    assert restored["plants_destroyed"] == 0
    assert restored["plants_available"] == 1000, "forward action fully compensated"
    assert_plant_lot_conservation(restored)
