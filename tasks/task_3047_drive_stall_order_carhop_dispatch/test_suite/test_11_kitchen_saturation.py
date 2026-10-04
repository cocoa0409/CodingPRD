"""Kitchen admission boundary: exactly eight orders in PREPARING."""
from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    ApiErrorId,
    create_drive_thru_order_with_line,
    place_order,
    set_clock,
    setup_drive_thru_location,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["shift_manager_headers"]
KITCHEN = TEST_USERS["kitchen_staff_headers"]


def _place_n_drive_thru_orders(location_id, item_id, n):
    """Create, line, and place n DRIVE_THRU orders. Returns placed orders."""
    placed = []
    for _ in range(n):
        order = create_drive_thru_order_with_line(location_id, item_id)
        placed.append(place_order(location_id, order["id"]))
    return placed


class TestKitchenSaturationBoundary:
    def test_eighth_preparation_admitted_ninth_rejected(self, api):
        """PRD: "the number of orders currently in `PREPARING` at the location
        must be fewer than eight. Exactly eight orders in preparation rejects
        the ninth with `ERR_KITCHEN_SATURATED`, while seven admits the
        eighth."

        Seven PREPARING orders admit the eighth; with eight in preparation the
        ninth start_preparation is rejected.

        Design: Difficulty/boundary_precision_check/kitchen_saturation_exactly_at_max_preparing
        """
        set_clock(TEST_DEFAULTS["CLOCK_0800_LOCAL"])
        ctx = setup_drive_thru_location(
            code="DIFF-KIT1", target_seconds=300, item_price=500
        )
        location_id = ctx["location"]["id"]
        item_id = ctx["item"]["id"]

        placed = _place_n_drive_thru_orders(location_id, item_id, 9)

        preparing = []
        for order in placed[:8]:
            moved = validate_success(
                api.start_preparation(location_id, order["id"], KITCHEN), 200
            )
            assert moved["status"] == "PREPARING"
            preparing.append(moved)

        resp = api.start_preparation(location_id, placed[8]["id"], KITCHEN)
        validate_error(resp, ApiErrorId.ERR_KITCHEN_SATURATED)

        ninth = validate_success(api.get_order(location_id, placed[8]["id"], MANAGER), 200)
        assert ninth["status"] == "PLACED"

    def test_seventh_preparation_leaves_room_for_eighth(self, api):
        """PRD: "the number of orders currently in `PREPARING` at the location
        must be fewer than eight. Exactly eight orders in preparation rejects
        the ninth with `ERR_KITCHEN_SATURATED`, while seven admits the
        eighth."

        With only seven orders in PREPARING the eighth start_preparation is
        admitted, pinning the boundary at exactly eight.

        Design: Difficulty/boundary_precision_check/kitchen_saturation_exactly_at_max_preparing
        """
        set_clock(TEST_DEFAULTS["CLOCK_0800_LOCAL"])
        ctx = setup_drive_thru_location(
            code="DIFF-KIT2", target_seconds=300, item_price=500
        )
        location_id = ctx["location"]["id"]
        item_id = ctx["item"]["id"]

        placed = _place_n_drive_thru_orders(location_id, item_id, 8)

        for order in placed[:7]:
            moved = validate_success(
                api.start_preparation(location_id, order["id"], KITCHEN), 200
            )
            assert moved["status"] == "PREPARING"

        eighth = validate_success(
            api.start_preparation(location_id, placed[7]["id"], KITCHEN), 200
        )
        assert eighth["status"] == "PREPARING"
