"""Heat creation and charge-apply corners (PRD §3.4, §2.7)."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    validate_success, validate_error, validate_paginated,
    set_clock, make_mill, make_grade, make_heat, apply_charge, setup_supply_pool,
    get_heat, get_lot,
)

MO = TEST_USERS["mill_operator_headers"]
PM = TEST_USERS["plant_manager_headers"]


def test_heat_create_target_weight_above_furnace_capacity_returns_invalid_request():
    """PRD §3.4: "a `target_tap_weight_tons` that is strictly positive and no greater
    than the mill's `furnace_capacity_tons`"
    PRD §2.7: "(3) request well-formedness — malformed body, missing required field,
    out-of-enum value, or out-of-range number ... yields `ERR_INVALID_REQUEST`"

    Design: Corner/entities/heat_create_target_weight_above_furnace_capacity_returns_invalid_request
    """
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY",
                     furnace_capacity_tons=150)
    grade = make_grade(mill["id"])
    resp = api_client.create_heat(
        mill["id"],
        {"heat_number": "H-FAT", "grade_id": grade["id"],
         "target_tap_weight_tons": 151, "planned_tap_at": "2026-09-15T12:00:00Z"},
        MO,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_heat_create_unknown_grade_returns_grade_not_found():
    """PRD §2.7: "(4) resource existence — path resources validated left to right from
    the mill down through contract, lot, heat, campaign, account, order, window, event,
    scorecard, or sheet, and body foreign keys such as `grade_id`, `heat_id`,
    `scrap_lot_id`, and `scope_id`, yield the matching `ERR_*_NOT_FOUND` (each at
    HTTP 404)"

    Design: Corner/entities/flat_topology_body_fk_checked_in_declared_input_order
    """
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    resp = api_client.create_heat(
        mill["id"],
        {"heat_number": "H-NOGRADE",
         "grade_id": "00000000-0000-4000-8000-000000000001",
         "target_tap_weight_tons": 8, "planned_tap_at": "2026-09-15T12:00:00Z"},
        MO,
    )
    validate_error(resp, ApiErrorId.ERR_GRADE_NOT_FOUND, 404)


def test_heats_list_paginates_and_filters_by_status():
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` block, where `total_count` is the full matching row count
    before pagination and `has_more` reports whether rows exist beyond the returned
    page."
    PRD §2.3: "`limit` defaults to 10, must be at least 1, and must not exceed 100"

    Design: Corner/endpoints/heats_list_paginates_and_filters_by_status
    """
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    contract, lots = setup_supply_pool(
        mill["id"], price=39000, committed=100,
        lots=[{"received_on": "2026-09-03", "tons_received": 40, "moisture_pct": 0.0}],
    )
    grade = make_grade(mill["id"])
    h1 = make_heat(mill["id"], grade["id"], planned_tap_at="2026-09-15T08:00:00Z")
    h2 = make_heat(mill["id"], grade["id"], planned_tap_at="2026-09-15T10:00:00Z")
    h3 = make_heat(mill["id"], grade["id"], planned_tap_at="2026-09-15T12:00:00Z")
    apply_charge(mill["id"], h3["id"], lots[0]["id"], 8)

    rows, meta = validate_paginated(
        api_client.list_heats(mill["id"], TEST_USERS["scheduler_headers"],
                              params={"limit": 2, "offset": 0})
    )
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    charged, _ = validate_paginated(
        api_client.list_heats(mill["id"], TEST_USERS["scheduler_headers"],
                              params={"status": "CHARGED"})
    )
    assert [h["id"] for h in charged] == [h3["id"]]

    all_rows, all_meta = validate_paginated(
        api_client.list_heats(mill["id"], TEST_USERS["scheduler_headers"])
    )
    assert len(all_rows) == 3
    assert all_meta["limit"] == 10
    assert all_meta["offset"] == 0
