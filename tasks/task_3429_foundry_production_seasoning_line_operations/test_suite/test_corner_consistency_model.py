"""Corner queue (consistency_model): read-after-write returns the stored
representation immediately."""
from test_helpers import (
    TEST_USERS,
    validate_success,
)

_RP = TEST_USERS["retail_planner_headers"]


def test_immediate_consistency_create_then_read(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data field."
    PRD §2.5: "A resource's `version` starts at 1 upon creation and increments by
    exactly 1 on every mutation of that resource, including mutations caused by
    cascades from another resource's transition; `updated_at` refreshes to the
    logical clock at the same instant."
    The GET returns the same stored field values as the 201 response, with
    version 1 and updated_at identical to created_at before any mutation.

    Design: Corner/consistency_model/immediate_consistency_create_then_read
    """
    created = validate_success(
        api.create_product(
            {"sku_code": "L8SK3", "name": "Skillet 10.25in", "category": "SKILLET",
             "target_weight_oz": 128.0, "weight_tolerance_oz": 6.0,
             "target_diameter_in": 10.25, "diameter_tolerance_in": 0.125,
             "min_wall_thickness_in": 0.1875, "wholesale_price_cents": 2400,
             "msrp_cents": 4000, "import_landed_cost_cents": 2000,
             "peak_season_start_week": 44, "peak_season_end_week": 52},
            TEST_USERS["foundry_manager_headers"]),
        expected_status=201)
    read = validate_success(api.get_product(created["id"], _RP))
    for field in ("sku_code", "name", "category", "wholesale_price_cents",
                  "msrp_cents", "import_landed_cost_cents", "status"):
        assert read[field] == created[field]
    assert read["sku_code"] == "L8SK3"
    assert read["wholesale_price_cents"] == 2400
    assert read["status"] == "ACTIVE"
    assert read["version"] == 1
    assert read["updated_at"] == read["created_at"]
