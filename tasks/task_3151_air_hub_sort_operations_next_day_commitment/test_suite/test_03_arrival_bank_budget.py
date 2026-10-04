"""The arrival bank's effective sort budget and the two aircraft that eat into it."""
import pytest

from test_helpers import (
    begin_aircraft_unload,
    cancel_aircraft,
    complete_aircraft_unload,
    depart_and_land,
    get_bank,
    set_clock,
    setup_night_with_second_aircraft,
)

CLOCK_1414_INSTANT = "2026-09-01T23:34:00Z"


@pytest.fixture
def night():
    return setup_night_with_second_aircraft()


def test_a_late_landing_eats_into_the_bank_budget(night):
    """PRD §3.2: "a late arrival increases the slack, which decreases the bank's
    budget."
    PRD §3.2: "an aircraft twelve minutes late contributes thirty-three."

    Design: Difficulty/dual_variant_calc/arrival_bank_unload_budget_with_slack_vs_without_slack_variant
    """
    set_clock("2026-09-01T23:34:00Z")  # minute 1414
    depart_and_land(night["ac2_id"], 50000)
    begin_aircraft_unload(night["ac2_id"])
    complete_aircraft_unload(night["ac2_id"], 1414)

    bank = get_bank(night["bank_id"])
    assert bank["effective_sort_budget_minutes"] == 73, (
        "N701UP contributes 45 - min(1400 - 1395, 45) == 40 and "
        "N702UP contributes 45 - min(1414 - 1402, 45) == 33"
    )


def test_the_budget_is_not_the_without_slack_figure(night):
    """PRD §3.2: "An aircraft that has not landed, or that landed exactly on schedule,
    contributes its full 45 minutes;"

    Design: Difficulty/dual_variant_calc/arrival_bank_unload_budget_with_slack_vs_without_slack_variant
    """
    set_clock("2026-09-01T23:34:00Z")
    depart_and_land(night["ac2_id"], 50000)
    begin_aircraft_unload(night["ac2_id"])
    complete_aircraft_unload(night["ac2_id"], 1414)

    budget = get_bank(night["bank_id"])["effective_sort_budget_minutes"]
    assert budget != 90, "the without-slack reading of the same two aircraft"
    assert budget != 78, "the budget is not a per-aircraft average"


def test_an_unlanded_aircraft_contributes_its_full_budget(night):
    """PRD §3.2: "An aircraft that has not landed, or that landed exactly on schedule,
    contributes its full 45 minutes;"

    Design: Difficulty/dual_variant_calc/arrival_bank_unload_budget_with_slack_vs_without_slack_variant
    """
    # N701UP landed at 1400 against a scheduled 1395: slack 5, contributes 40.
    # N702UP has not landed at all, so it contributes the full 45.
    bank = get_bank(night["bank_id"])
    assert bank["effective_sort_budget_minutes"] == 85, (
        "40 from the five-minute-late arrival plus the full 45 from the unlanded aircraft"
    )


def test_the_budget_is_recomputed_when_another_aircraft_lands(night):
    """PRD §3.2: "The budget is recomputed on every aircraft unload, cancellation,
    maintenance diversion or reinstatement within the bank."

    Design: Difficulty/dual_variant_calc/arrival_bank_unload_budget_with_slack_vs_without_slack_variant
    """
    set_clock("2026-09-01T23:34:00Z")
    depart_and_land(night["ac2_id"], 50000)
    begin_aircraft_unload(night["ac2_id"])
    complete_aircraft_unload(night["ac2_id"], 1414)

    # Cancelling the second aircraft removes it from the sum entirely.
    cancel_aircraft(night["ac2_id"], "MECHANICAL")
    bank = get_bank(night["bank_id"])
    assert bank["effective_sort_budget_minutes"] == 40, (
        "a CANCELLED aircraft contributes nothing at all"
    )


def test_a_fully_cancelled_bank_reports_zero_rather_than_a_negative(night):
    """PRD §3.2: "The resulting sum is clamped to at least zero, so a bank whose every
    aircraft has been cancelled reports exactly zero rather than a negative figure."

    Design: Difficulty/dual_variant_calc/arrival_bank_unload_budget_with_slack_vs_without_slack_variant
    """
    cancel_aircraft(night["ac1_id"], "MECHANICAL")
    cancel_aircraft(night["ac2_id"], "MECHANICAL")
    bank = get_bank(night["bank_id"])
    assert bank["effective_sort_budget_minutes"] == 0