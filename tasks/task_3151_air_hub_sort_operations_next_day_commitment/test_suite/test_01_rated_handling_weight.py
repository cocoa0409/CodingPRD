"""Rated handling weight: the manifest path against the volumetric path.

Both readings of the rated-weight rule must hold at once, and the dimensional
minimum binds a light package before any manifest or volumetric comparison runs.
"""
import pytest

from test_helpers import (
    CLOCK_1400,
    advance_clock,
    assert_package,
    create_package,
    get_package,
    induct,
    set_clock,
    setup_six_lane_night,
)


@pytest.fixture
def night():
    """The standard night with six lanes; each test throws its own packages at it."""
    return setup_six_lane_night()


def test_manifest_path_collapses_to_the_planned_weight(night):
    """PRD §3.1: "when the caller supplies a dimension weight equal to the planned weight — the
    manifest path — the maximum collapses to the planned weight and the rated
    weight is simply that weight rounded half up to the nearest 100;"

    Design: Difficulty/dual_variant_calc/package_rated_weight_manifest_vs_volumetric_variant
    """
    pkg = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-RW-0001",
                         planned_weight_grams=2600, dimension_weight_grams=2600)
    induct(pkg["id"])

    read = get_package(pkg["id"])
    assert read["rated_weight_grams"] == 2600, (
        "max(2600, 2600, 2000) == 2600, so no dimensional uplift occurs"
    )


def test_volumetric_path_lifts_a_light_package_clear_of_the_floor(night):
    """PRD §3.1: "when the caller supplies a dimension weight above the planned weight —
    the volumetric path — the larger figure wins before rounding, so a light but bulky
    package rates well above what it was manifested at."

    Design: Difficulty/dual_variant_calc/package_rated_weight_manifest_vs_volumetric_variant
    """
    pkg = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-RW-0002",
                         planned_weight_grams=1910, dimension_weight_grams=2600)
    result = induct(pkg["id"])

    assert result["rated_weight_grams"] == 2600, (
        "max(1910, 2600, 2000) == 2600 — the volumetric weight wins"
    )

    read = get_package(pkg["id"])
    assert read["rated_weight_grams"] != 2000, "the same declared weight as the floor case rates differently"
    assert_package(read)


def test_dimensional_minimum_binds_and_rounding_is_half_up(night):
    """PRD §3.1: "Take the largest of three quantities: the package's
    `planned_weight_grams`, its `dimension_weight_grams`, and a dimensional minimum of
    2000 grams."
    PRD §3.1: "a package manifested at one gram still occupies 2000 grams of capacity."

    Design: Difficulty/dual_variant_calc/package_rated_weight_manifest_vs_volumetric_variant
    """
    at_floor = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-RW-0003",
                              planned_weight_grams=1910, dimension_weight_grams=1910)
    induct(at_floor["id"])

    rounding_case = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-RW-0004",
                                   planned_weight_grams=1910, dimension_weight_grams=2050)
    induct(rounding_case["id"])

    floor_read = get_package(at_floor["id"])
    rounding_read = get_package(rounding_case["id"])

    assert floor_read["rated_weight_grams"] == 2000, (
        "max(1910, 1910, 2000) == 2000 — the dimensional minimum binds"
    )
    assert floor_read["rated_weight_grams"] != 1910, "the DIM floor rounds it up"
    assert rounding_read["rated_weight_grams"] == 2100, (
        "2050 divided by 100 is 20.5, rounded half up to 21, multiplied back by 100"
    )
    assert floor_read["rated_weight_grams"] != rounding_read["rated_weight_grams"], (
        "two packages carrying the same manifest weight rate differently"
    )


def test_rated_weight_is_independent_of_the_clock_inside_the_window(night):
    """PRD §3.1: "The minimum and the rounding are both applied before any lane or
    container comparison, so a package manifested at one gram still occupies 2000 grams
    of capacity."

    Design: Difficulty/dual_variant_calc/package_rated_weight_manifest_vs_volumetric_variant
    """
    assert set_clock(CLOCK_1400).status_code == 200
    pkg = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-RW-0005",
                         planned_weight_grams=1, dimension_weight_grams=1)
    induct(pkg["id"])
    assert get_package(pkg["id"])["rated_weight_grams"] == 2000

    advance_clock("2026-09-01T23:40:00Z")  # minute 1420, still inside the window
    read = get_package(pkg["id"])
    assert read["rated_weight_grams"] == 2000, (
        "the rated weight is a function of the package alone, not of the clock"
    )