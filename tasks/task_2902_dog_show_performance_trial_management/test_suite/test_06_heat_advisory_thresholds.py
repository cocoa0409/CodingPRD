"""The one-tenth of a degree either side of the RED advisory threshold."""

import pytest

from test_helpers.fixtures import (
    read_entry,
    read_show,
    record_reading,
    setup_show_with_class,
)


def _outdoor_performance_show_before_any_reading():
    """An open show day with two confirmed obedience entries and no reading yet."""
    context = setup_show_with_class(
        num_dogs=2,
        confirm_entries=True,
        close_class=True,
        open_show=True,
        class_level="PERFORMANCE",
        discipline="OBEDIENCE",
        show_overrides={"show_type": "COMBINED", "outdoor_venue": True},
        class_overrides={"class_code": "OB-NOVICE-A"},
    )
    assert read_show(context["show"])["temperature_reading_count"] == 0
    return context


def test_a_reading_one_tenth_below_the_red_threshold_stays_amber():
    """28.9 degrees at 65 percent humidity indexes to 31.9, which is AMBER.

    PRD: "The heat index is the recorded temperature plus a humidity adjustment,
    rounded half-up to one decimal place. The adjustment is read from an inclusive
    ladder: humidity at most 40 percent adds nothing, above 40 up to and including
    60 percent adds 1.5 degrees, above 60 up to and including 80 percent adds 3.0
    degrees, and above 80 percent adds 5.0 degrees."

    Design: Difficulty/boundary_precision_check/heat_index_exactly_at_red_threshold
    """
    context = _outdoor_performance_show_before_any_reading()

    record_reading(context["show"], 28.9, 65)

    show = read_show(context["show"])
    assert show["current_heat_index_c"] == pytest.approx(31.9, abs=0.01)
    assert show["current_advisory_level"] == "AMBER"
    assert read_entry(context["entries"][0])["welfare_status"] == "CLEAR"


def test_a_reading_landing_exactly_on_the_threshold_is_red():
    """29.0 degrees at 65 percent humidity indexes to exactly 32.0, which is RED.

    PRD: "The comparisons are inclusive at the bottom of each band, so exactly 32.0
    is `RED` while 31.9 is `AMBER`."

    Design: Difficulty/boundary_precision_check/heat_index_exactly_at_red_threshold
    """
    context = _outdoor_performance_show_before_any_reading()

    record_reading(context["show"], 28.9, 65)
    record_reading(context["show"], 29.0, 65)

    show = read_show(context["show"])
    assert show["current_heat_index_c"] == pytest.approx(32.0, abs=0.01)
    assert show["current_advisory_level"] == "RED"
    assert show["temperature_reading_count"] == 2


def test_the_red_reading_holds_every_performance_entry_without_moving_its_competition_status():
    """A welfare hold is written on the welfare axis alone.

    PRD: "The heat restriction is not active, else `ERR_HEAT_RESTRICTION_ACTIVE`.
    This applies to ring-block publication, ring-block rescheduling, class
    completion and performance-run recording."

    Design: Difficulty/boundary_precision_check/heat_index_exactly_at_red_threshold
    """
    context = _outdoor_performance_show_before_any_reading()

    record_reading(context["show"], 28.9, 65)
    record_reading(context["show"], 29.0, 65)

    first, second = (read_entry(entry) for entry in context["entries"])
    assert first["welfare_status"] == "HEAT_HOLD"
    assert second["welfare_status"] == "HEAT_HOLD"
    assert first["entry_status"] == "CONFIRMED"
