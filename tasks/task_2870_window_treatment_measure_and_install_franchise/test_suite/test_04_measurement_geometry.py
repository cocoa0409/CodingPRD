"""Mount type as the branch selector: the deduction set and the rounding direction."""

from test_helpers.assertions import (
    assert_eighth_multiple,
    assert_inches_equal,
)
from test_helpers.fixtures import (
    book_consultation,
    charter_territory,
    configure_opening,
    hire_designer,
    intake_lead,
    record_opening,
)

READINGS = {
    "width_top_in": 36.400,
    "width_middle_in": 36.750,
    "width_bottom_in": 36.900,
    "height_left_in": 60.100,
    "height_center_in": 60.300,
    "height_right_in": 60.200,
    "depth_in": 3.000,
}


def _one_wall_two_mounts(api):
    """Two openings recorded from byte-identical readings, one INSIDE and one OUTSIDE.

    Both are then configured `BO-THERMAL` / `CORDLESS`, so the 1280-cent fabric rate
    and the 1800-cent cordless uplift are common to the pair and only the mount
    branch can move the price. The dwelling has children and the room is a nursery,
    so a cordless lift is the only storable choice anyway.
    """
    territory = charter_territory(api, royalty_rate_pct=0.055,
                                 lead_capacity_per_week=5,
                                 credit_limit_cents=2000000,
                                 liability_window="ROLLING_180D")
    designer = hire_designer(api, territory)
    lead = intake_lead(api, territory, customer_name="Ana Ruiz",
                       source="WEB_FORM",
                       requested_at="2026-08-03T00:00:00.000Z",
                       child_occupied_dwelling=True)
    consultation = book_consultation(api, designer, lead)
    inside = record_opening(api, designer, consultation,
                            label="Nursery inside", room_type="NURSERY",
                            mount_type="INSIDE", **READINGS)
    outside = record_opening(api, designer, consultation,
                             label="Nursery outside", room_type="NURSERY",
                             mount_type="OUTSIDE", **READINGS)
    return territory, designer, consultation, inside, outside


def test_the_out_of_square_spread_is_mount_independent(api):
    """Both rows read 0.500 inch of racking, because the spread precedes the branch.

    "The opening's `out_of_square_in` is the larger of the two spreads — widest width
    minus narrowest width, against tallest height minus shortest height — rounded
    half up to three decimal places."

    Design: Difficulty/combinatorial_formula/mount_type_flips_both_the_deduction_set_and_the_rounding_direction
    """
    _territory, _designer, _consultation, inside, outside = _one_wall_two_mounts(api)

    assert_inches_equal(inside["out_of_square_in"], 0.500, "out_of_square_in")
    assert_inches_equal(outside["out_of_square_in"], 0.500, "out_of_square_in")
    assert inside["mount_type"] == "INSIDE"
    assert outside["mount_type"] == "OUTSIDE"


def test_inside_subtracts_and_floors_while_outside_adds_and_ceils(api):
    """35.875 by 59.750 against 40.000 by 64.875 from one set of readings.

    "For an `INSIDE` mount the service starts from the **narrowest** width and the
    **shortest** height, because the blind has to pass the tightest point of the
    pocket: it subtracts a width deduction of 0.500 inches from the narrowest width
    and a height deduction of 0.250 inches from the shortest height, then rounds each
    result **down** to the next lower exact eighth of an inch."

    "For an `OUTSIDE` mount the service starts from the **widest** width and the
    **tallest** height, because the blind has to cover the largest point of the
    opening: it adds an overlap of 1.500 inches on each of the two sides — three
    inches of extra width in total — and adds to the tallest height a header
    allowance of 3.000 inches plus a sill overlap of 1.500 inches, then rounds each
    result **up** to the next higher exact eighth of an inch."

    Design: Difficulty/combinatorial_formula/mount_type_flips_both_the_deduction_set_and_the_rounding_direction
    """
    _territory, _designer, _consultation, inside, outside = _one_wall_two_mounts(api)

    assert_inches_equal(inside["ordered_width_in"], 35.875, "ordered_width_in")
    assert_inches_equal(inside["ordered_height_in"], 59.750, "ordered_height_in")
    assert_inches_equal(outside["ordered_width_in"], 40.000, "ordered_width_in")
    assert_inches_equal(outside["ordered_height_in"], 64.875, "ordered_height_in")

    for row in (inside, outside):
        assert_eighth_multiple(row["ordered_width_in"], "ordered_width_in")
        assert_eighth_multiple(row["ordered_height_in"], "ordered_height_in")


def test_the_mount_branch_alone_moves_the_price_by_4160_cents(api):
    """15.00 square feet at 21000 cents against 18.25 at 25160, same fabric and lift.

    "Their product divided by 144 gives the raw area in square feet, and
    `billable_sqft` is that raw area rounded **up** to the next whole quarter of a
    square foot — the trade's billing unit."

    "The rates per square foot are 620 cents for `LT-SHEER`, 940 cents for
    `CL-LINEN`, 1280 cents for `BO-THERMAL` and 1550 cents for `WD-FAUX`."

    Design: Difficulty/combinatorial_formula/mount_type_flips_both_the_deduction_set_and_the_rounding_direction
    """
    _territory, designer, _consultation, inside, outside = _one_wall_two_mounts(api)

    priced_inside = configure_opening(api, designer, inside,
                                      fabric_code="BO-THERMAL",
                                      lift_system="CORDLESS",
                                      motorization_option="NONE")
    priced_outside = configure_opening(api, designer, outside,
                                       fabric_code="BO-THERMAL",
                                       lift_system="CORDLESS",
                                       motorization_option="NONE")

    assert priced_inside["billable_sqft"] == 15.00
    assert priced_inside["list_price_cents"] == 21000
    assert priced_outside["billable_sqft"] == 18.25
    assert priced_outside["list_price_cents"] == 25160

    assert (priced_outside["list_price_cents"]
            - priced_inside["list_price_cents"]) == 4160
    assert priced_inside["measure_status"] == "CONFIGURED"
    assert priced_outside["measure_status"] == "CONFIGURED"
