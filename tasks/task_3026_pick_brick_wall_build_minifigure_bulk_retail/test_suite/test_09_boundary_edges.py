"""Boundary precision on the wall fullness ladder and the posture edge."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_element,
    add_member,
    api_client,
    draw_from_bin,
    load_bin,
    make_member_headers,
    open_cup,
    open_store,
    reset_clock,
    setup_store_with_wall,
    validate_success,
)


def test_wall_fill_boundaries_are_strictly_less_than(api):
    """PRD §3.1: "Below fifteen percent the bin is `EMPTY`; at fifteen percent or
    above but below fifty percent it is `LOW`; at fifty percent or above it is
    `OPEN`. The boundaries are inclusive at the lower edge of each upper band — a
    bin reading exactly 15.0 is `LOW` rather than `EMPTY`, and a bin reading
    exactly 50.0 is `OPEN` rather than `LOW`."
    PRD §3.1: "Every time a bin's mass changes, its fullness is recomputed:
    `fill_pct` is the bin's mass multiplied by one hundred and divided by its
    capacity, rounded half up to one decimal place."

    Design: Difficulty/boundary_precision_check/wall_fill_boundaries_are_strictly_less_than
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    element = add_element(element_code="3070", element_name="Brick 1x4",
                          cost_basis_cents=4)
    member = add_member(store["id"])
    bin_row = load_bin(store["id"], element["id"], bin_label="L01",
                       bin_capacity_grams=1000, bin_mass_grams=600)

    order = open_cup(store["id"], member["id"], cup_size="SMALL",
                     pricing_model="CUP_FILL", declared_mass_grams=100)

    order = draw_from_bin(order["id"], bin_row["id"], 100)
    at_fifty = validate_success(api.get_wall_bin(
        bin_row["id"], TEST_USERS["associate_headers"]), 200)
    assert at_fifty["bin_mass_grams"] == 500
    assert at_fifty["fill_pct"] == pytest.approx(50.0), (
        "500 g of 1000 g reads exactly 50.0 percent")
    assert at_fifty["status"] == "OPEN", (
        "exactly at the lower edge of the OPEN band the bin stays OPEN")

    order = draw_from_bin(order["id"], bin_row["id"], 1)
    at_forty_nine = validate_success(api.get_wall_bin(
        bin_row["id"], TEST_USERS["associate_headers"]), 200)
    assert at_forty_nine["bin_mass_grams"] == 499
    assert at_forty_nine["fill_pct"] == pytest.approx(49.9), (
        "499 g reads 49.9 percent after the one-decimal rounding")
    assert at_forty_nine["status"] == "LOW", (
        "one gram below the edge drops the bin into the LOW band")

    order = draw_from_bin(order["id"], bin_row["id"], 350)
    at_fourteen_nine = validate_success(api.get_wall_bin(
        bin_row["id"], TEST_USERS["associate_headers"]), 200)
    assert at_fourteen_nine["bin_mass_grams"] == 149
    assert at_fourteen_nine["fill_pct"] == pytest.approx(14.9), (
        "149 g reads 14.9 percent")
    assert at_fourteen_nine["status"] == "EMPTY", (
        "just below fifteen percent the bin reads EMPTY")


def test_fifteen_percent_exactly_is_low_rather_than_empty(api):
    """PRD §3.1: "The boundaries are inclusive at the lower edge of each upper
    band — a bin reading exactly 15.0 is `LOW` rather than `EMPTY`"

    Design: Difficulty/boundary_precision_check/wall_fill_boundaries_are_strictly_less_than
    """
    store, element, _member, bin_row = setup_store_with_wall(
        store_overrides={"wall_bin_capacity_grams": 1000},
        bin_overrides={"bin_capacity_grams": 1000, "bin_mass_grams": 150})

    at_fifteen = validate_success(api.get_wall_bin(
        bin_row["id"], TEST_USERS["associate_headers"]), 200)
    assert at_fifteen["fill_pct"] == pytest.approx(15.0)
    assert at_fifteen["status"] == "LOW", (
        "exactly fifteen percent sits in the upper band, not the EMPTY band")


def test_the_restricted_edge_is_read_as_an_exact_decimal(api):
    """PRD §2.5: "The one-tenth edge is computed against the declared capacity,
    not against a rounded approximation of it: at the default capacity of 20000
    grams the edge sits at 2000 grams exactly, so an engine holding exactly 2000
    grams reads as `TRADING` while 1999 grams reads as `RESTRICTED`."
    PRD §2.5: "Comparisons against these edges are made as exact decimals and are
    never rounded first."

    Design: Difficulty/boundary_precision_check/wall_fill_boundaries_are_strictly_less_than
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=20000)
    element = add_element(element_code="3071", element_name="Brick 1x6")
    load_bin(store["id"], element["id"], bin_label="L02",
             bin_capacity_grams=20000, bin_mass_grams=2000)

    exactly_on_edge = validate_success(api.get_store(
        store["id"], TEST_USERS["associate_headers"]), 200)
    assert exactly_on_edge["bin_engine_mass_grams"] == 2000
    assert exactly_on_edge["stage"] == "TRADING", (
        "exactly one tenth of the declared capacity reads TRADING")


def test_one_gram_under_the_restricted_edge_reads_restricted(api):
    """PRD §2.5: "at the default capacity of 20000 grams the edge sits at 2000
    grams exactly, so an engine holding exactly 2000 grams reads as `TRADING`
    while 1999 grams reads as `RESTRICTED`."

    Design: Difficulty/boundary_precision_check/wall_fill_boundaries_are_strictly_less_than
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=20000)
    element = add_element(element_code="3072", element_name="Brick 1x8")
    load_bin(store["id"], element["id"], bin_label="L03",
             bin_capacity_grams=20000, bin_mass_grams=1999)

    under_edge = validate_success(api.get_store(
        store["id"], TEST_USERS["associate_headers"]), 200)
    assert under_edge["bin_engine_mass_grams"] == 1999
    assert under_edge["stage"] == "RESTRICTED", (
        "one gram below the edge compresses the store's posture")