"""Plant lots: creation accounting, provisional vs tiered final royalty,
variety-mismatch and availability gates at planting time."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_plant_lot_payload, create_planting_payload,
    create_variety_payload,
    set_clock, create_variety, create_released_variety, create_grower,
    create_active_agreement, create_plant_lot, get_plant_lot,
    create_harvest_window, plan_planting, confirm_planting, get_agreement,
    setup_active_agreement, make_grower_principal_headers, get_success_data,
    release_variety,
)

BREEDER = TEST_USERS["breeding_manager_headers"]
NURSERY = TEST_USERS["nursery_manager_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_plant_lot_provisional_royalty_and_counters_computed(api):
    """PRD section 3.4: "`royalty_provisional_cents` equals `quantity_plants`
    multiplied by a flat 45 cents per plant, ignoring the tier counter entirely."
    PRD section 3.4: "A lot is created already `SHIPPED`: `shipped_at` is
    stamped from the logical clock at creation, and `season_year` is derived as
    the calendar year of `shipped_at`."

    Design: Corner/entities/plant_lot_provisional_royalty_and_counters_computed
    """
    set_clock("2026-06-01T00:00:00Z")
    variety, grower, agreement = setup_active_agreement()
    resp = api.create_plant_lot(
        create_plant_lot_payload(agreement["id"], variety["id"],
                                 quantity_plants=2000),
        NURSERY)
    data = validate_success(resp, 201)
    assert data["status"] == "SHIPPED"
    assert data["shipped_at"].startswith("2026-06-01T00:00:00")
    assert data["season_year"] == 2026
    assert data["royalty_provisional_cents"] == 90000, "2000 x 45 flat"
    assert data["royalty_final_cents"] is None
    assert data["royalty_adjustment_cents"] is None
    assert data["plants_reserved"] == 0
    assert data["plants_planted"] == 0
    assert data["plants_destroyed"] == 0
    assert data["plants_available"] == 2000
    assert data["depleted_at"] is None


def test_lot_variety_mismatch_rejected(api):
    """PRD section 3.5: "the plant lot's variety must equal the agreement's
    variety (`ERR_LOT_VARIETY_MISMATCH`)".

    Design: Corner/validations/lot_variety_mismatch_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    variety, grower, agreement = setup_active_agreement()  # STRAWBERRY
    v2 = get_success_data(api.create_variety(
        create_variety_payload(variety_code="BRB-BLK-01",
                               berry_type="BLACKBERRY",
                               name="Midnight Canyon"), BREEDER))
    release_variety(v2["id"])
    wrong_lot = get_success_data(api.create_plant_lot(
        create_plant_lot_payload(agreement["id"], v2["id"], quantity_plants=100),
        NURSERY))
    current = get_agreement(agreement["id"])
    resp = api.create_planting(
        create_planting_payload(agreement["id"], wrong_lot["id"],
                                current["version"], planned_plants=10),
        make_grower_principal_headers(grower["id"]))
    validate_error(resp, ApiErrorId.ERR_LOT_VARIETY_MISMATCH)
    rows, meta = validate_paginated(api.list_plantings(
        COMPLIANCE, params={"agreement_id": agreement["id"]}))
    assert rows == [] and meta["total_count"] == 0


def test_planting_create_over_lot_availability_rejected(api):
    """PRD section 3.5: "`planned_plants` must not exceed the lot's
    `plants_available` (`ERR_LOT_QUANTITY_EXCEEDED`)".

    Design: Corner/errors/planting_create_over_lot_availability_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    variety, grower, agreement = setup_active_agreement()
    lot = create_plant_lot(agreement, variety, quantity_plants=500)
    current = get_agreement(agreement["id"])
    resp = api.create_planting(
        create_planting_payload(agreement["id"], lot["id"],
                                current["version"], planned_plants=600),
        make_grower_principal_headers(grower["id"]))
    validate_error(resp, ApiErrorId.ERR_LOT_QUANTITY_EXCEEDED)
    rows, meta = validate_paginated(api.list_plantings(
        COMPLIANCE, params={"agreement_id": agreement["id"]}))
    assert rows == [] and meta["total_count"] == 0
    lot_now = get_plant_lot(lot["id"])
    assert lot_now["plants_reserved"] == 0


def _setup_raspberry_royalty_scenario(api):
    """V2 RASPBERRY released; G3 with ACTIVE A3 (OR-WILLAMETTE, max 200000);
    window W3 [2026-10-12, 2026-10-19) target 300000 covers the 75-day first
    harvest (2026-10-15) of plantings made 2026-08-01. Lot A 100000 plants
    shipped at clock 2026-06-01, fully confirmed; lot B 5000 plants shipped at
    clock 2026-08-03, fully confirmed. Returns (lot_a, lot_b) post-confirm."""
    set_clock("2026-06-01T00:00:00Z")
    variety = create_released_variety(variety_code="BRB-RSP-01",
                                      berry_type="RASPBERRY",
                                      name="Cascadia Gem")
    grower = create_grower(legal_name="Willamette Valley Growers",
                           region_code="OR-WILLAMETTE")
    agreement = create_active_agreement(
        grower, variety, region_code="OR-WILLAMETTE", max_planting_units=200000,
        cultural_practice_codes=["CONVENTIONAL"])
    create_harvest_window(variety, region_code="OR-WILLAMETTE",
                          week_start="2026-10-12T00:00:00Z",
                          week_end="2026-10-19T00:00:00Z",
                          target_volume_kg=300000)
    lot_a = create_plant_lot(agreement, variety, quantity_plants=100000,
                             nursery_code="NUR-OR-01")
    planting_a = plan_planting(agreement, lot_a, grower, planned_plants=100000)
    set_clock("2026-08-02T00:00:00Z")
    confirm_planting(planting_a, grower, 100000)
    set_clock("2026-08-03T00:00:00Z")
    lot_b = create_plant_lot(agreement, variety, quantity_plants=5000,
                             nursery_code="NUR-OR-01")
    planting_b = plan_planting(agreement, lot_b, grower, planned_plants=5000)
    confirm_planting(planting_b, grower, 5000)
    return get_plant_lot(lot_a["id"]), get_plant_lot(lot_b["id"])


def test_royalty_lot_a_all_tier1_no_adjustment(api):
    """PRD section 3.4: "each plant position is charged the rate of the tier it
    falls into: positions 1 through 100,000 at 45 cents per plant, positions
    100,001 through 500,000 at 38 cents per plant, and every position beyond
    500,000 at 30 cents per plant."
    PRD section 3.4: "`royalty_adjustment_cents` is `royalty_final_cents` minus
    `royalty_provisional_cents` — a signed integer in cents with no rounding,
    positive or negative."

    Design: Difficulty/dual_variant_calc/royalty_provisional_vs_tiered_final
    """
    lot_a, _ = _setup_raspberry_royalty_scenario(api)
    assert lot_a["status"] == "DEPLETED"
    assert lot_a["royalty_provisional_cents"] == 4500000, "100000 x 45 flat"
    assert lot_a["royalty_final_cents"] == 4500000, "positions 1..100000 all tier 1"
    assert lot_a["royalty_adjustment_cents"] == 0
    assert lot_a["depleted_at"] is not None


def test_royalty_lot_b_tier2_negative_adjustment(api):
    """PRD section 3.4: "All plant lots of the same `variety_id` and the same
    `season_year` — `RECALLED` lots included, because the material was
    distributed regardless — are ordered by `shipped_at` ascending with ties
    broken by `created_at` ascending, forming one cumulative counter of
    plants."
    PRD section 3.4: "Both `royalty_final_cents` and `royalty_adjustment_cents`
    remain null until the final computation runs, so a lot that crosses a tier
    boundary settles its royalty at a different per-plant rate than its
    provisional charge implied."

    Design: Difficulty/dual_variant_calc/royalty_provisional_vs_tiered_final
    """
    lot_a, lot_b = _setup_raspberry_royalty_scenario(api)
    assert lot_b["status"] == "DEPLETED"
    assert lot_b["royalty_provisional_cents"] == 225000, "5000 x 45 flat"
    assert lot_b["royalty_final_cents"] == 190000, (
        "positions 100001..105000 all in tier 2 at 38c (5000 x 38)")
    assert lot_b["royalty_adjustment_cents"] == -35000
    assert lot_a["royalty_final_cents"] == 4500000
