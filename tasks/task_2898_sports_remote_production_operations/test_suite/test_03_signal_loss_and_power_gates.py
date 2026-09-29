"""The coax loss budget and the venue power budget as submit and assignment gates.

Every test starts against an empty database with the logical clock at its
startup value and lays in its own camera plot.
"""

import pytest

from test_helpers import (
    assert_camera_position,
    assert_status,
    assert_two_decimal_places,
    assert_venue_survey,
    validate_error,
    validate_success,
)
from test_helpers.constants import MAX_SIGNAL_LOSS_BUDGET_DB
from test_helpers.factories import (
    create_venue_survey_payload,
    truck_assignment_payload,
)
from test_helpers.fixtures import (
    add_camera_position,
    create_approved_survey,
    new_production,
    new_truck,
    read_production,
    read_survey,
    read_truck,
)
from test_helpers.test_users import TECHNICAL_DIRECTOR_ID


def _empty_draft_survey(api, production_id, headers, **overrides):
    """A DRAFT survey with no camera positions yet."""
    return validate_success(
        api.create_venue_survey(
            create_venue_survey_payload(production_id, **overrides), headers
        ),
        201,
    )


def _plot(api, survey_id, headers, runs):
    """Lay in one 20 A position per (label, position_type, cable_run_feet) triple."""
    return [
        add_camera_position(
            api, survey_id, headers=headers, label=label,
            position_type=position_type, cable_run_feet=feet, power_draw_amps=20,
        )
        for label, position_type, feet in runs
    ]


# ---------------------------------------------------------------------------
# Rounding order inside the loss budget
# ---------------------------------------------------------------------------
def test_each_camera_position_rounds_its_own_loss_half_up_to_two_decimals(
    api, pm_headers, td_headers
):
    """Runs of 150, 250 and 350 feet all land exactly on a half-hundredth of a decibel,
    and each row is rounded half up on its own before anything is summed.

    PRD: "`signal_loss_db` is the cable loss on that run: the coax budget is **1.35 dB per 100 feet**, so the position's loss is its cable run in feet multiplied by 1.35, divided by 100, and rounded half up to two decimal places."
    PRD: "Each position's loss is rounded to two decimal places **first**, on its own row; the already-rounded per-position values are then summed in `created_at` ascending order; and the sum is finally rounded half up to two decimal places again, which is a no-op given two-decimal addends."
    Design: Difficulty/combinatorial_formula/survey_signal_loss_rounds_per_position_before_summing
    """
    production = new_production(api, pm_headers)
    survey = _empty_draft_survey(api, production["id"], td_headers)

    first, second, third = _plot(
        api, survey["id"], td_headers,
        [
            ("HIGH_HOME", "HARD", 150),
            ("LOW_FIRST", "HANDHELD", 250),
            ("CENTER_FIELD", "ROBO", 350),
        ],
    )

    for position in (first, second, third):
        assert_camera_position(position)
        assert_two_decimal_places(position["signal_loss_db"], "signal_loss_db")

    assert first["signal_loss_db"] == pytest.approx(2.03, abs=0.005), (
        "150 feet is 2.025 dB exactly, which rounds half up to 2.03"
    )
    assert second["signal_loss_db"] == pytest.approx(3.38, abs=0.005), (
        "250 feet is 3.375 dB exactly, which rounds half up to 3.38"
    )
    assert third["signal_loss_db"] == pytest.approx(4.73, abs=0.005), (
        "350 feet is 4.725 dB exactly, which rounds half up to 4.73"
    )


def test_survey_total_sums_the_already_rounded_per_position_losses(
    api, pm_headers, td_headers
):
    """The survey total is the sum of the rounded rows, 10.14 dB, and not the 10.13 dB a
    sum-then-round order would produce.

    PRD: "The rounding order of the loss budget is pinned and it matters."
    PRD: "Summing the unrounded products and rounding once at the end is the wrong order and yields a smaller total for runs whose exact product ends on a half-hundredth of a decibel."
    Design: Difficulty/combinatorial_formula/survey_signal_loss_rounds_per_position_before_summing
    """
    production = new_production(api, pm_headers)
    survey = _empty_draft_survey(api, production["id"], td_headers)
    _plot(
        api, survey["id"], td_headers,
        [
            ("HIGH_HOME", "HARD", 150),
            ("LOW_FIRST", "HANDHELD", 250),
            ("CENTER_FIELD", "ROBO", 350),
        ],
    )

    plotted = read_survey(api, survey["id"], td_headers)
    assert_venue_survey(plotted)
    assert plotted["camera_position_count"] == 3
    assert plotted["total_cable_run_feet"] == 750
    assert plotted["total_signal_loss_db"] == pytest.approx(10.14, abs=0.005), (
        "2.03 + 3.38 + 4.73 is 10.14"
    )
    assert plotted["total_signal_loss_db"] != pytest.approx(10.13, abs=0.005), (
        "summing the raw products gives 10.125 and rounds to 10.13, the wrong order"
    )
    assert plotted["total_power_draw_amps"] == 60
    assert plotted["power_headroom_amps"] == 340, "power is not the binding constraint"


def test_submit_refused_when_the_rounded_total_passes_the_loss_budget(
    api, pm_headers, td_headers
):
    """10.14 dB is strictly greater than the 10.13 dB budget, so the submission is refused
    and the survey stays in DRAFT.

    PRD: "Third, the loss budget must hold: submission is refused with `ERR_SIGNAL_LOSS_BUDGET_EXCEEDED` when `total_signal_loss_db` is strictly greater than **10.13 dB**, with a total of exactly 10.13 accepted."
    PRD: "Each position's loss is rounded to two decimal places **first**, on its own row; the already-rounded per-position values are then summed in `created_at` ascending order; and the sum is finally rounded half up to two decimal places again, which is a no-op given two-decimal addends."
    Design: Difficulty/combinatorial_formula/survey_signal_loss_rounds_per_position_before_summing
    """
    production = new_production(api, pm_headers)
    survey = _empty_draft_survey(api, production["id"], td_headers)
    _plot(
        api, survey["id"], td_headers,
        [
            ("HIGH_HOME", "HARD", 150),
            ("LOW_FIRST", "HANDHELD", 250),
            ("CENTER_FIELD", "ROBO", 350),
        ],
    )

    validate_error(
        api.submit_venue_survey(survey["id"], td_headers),
        "ERR_SIGNAL_LOSS_BUDGET_EXCEEDED",
    )

    after = read_survey(api, survey["id"], td_headers)
    assert_status(after, "DRAFT", "survey status")
    assert after["submitted_by_user_id"] is None, "a refused submit stamps no submitter"
    assert after["total_signal_loss_db"] == pytest.approx(10.14, abs=0.005)
    assert after["total_signal_loss_db"] > MAX_SIGNAL_LOSS_BUDGET_DB


# ---------------------------------------------------------------------------
# The smallest admissible camera plot
# ---------------------------------------------------------------------------
def test_submit_refused_when_the_camera_plot_is_still_empty(api, pm_headers, td_headers):
    """An empty plot passes every decibel check, because an empty sum is 0.0, and must
    still be refused on the position count alone.

    PRD: "Second, an empty plot can never be approved, so a survey whose `camera_position_count` is zero is refused with `ERR_SURVEY_NO_CAMERA_POSITIONS`."
    PRD: "Third, the loss budget must hold: submission is refused with `ERR_SIGNAL_LOSS_BUDGET_EXCEEDED` when `total_signal_loss_db` is strictly greater than **10.13 dB**, with a total of exactly 10.13 accepted."
    Design: Difficulty/boundary_precision_check/survey_submit_at_zero_versus_one_camera_position
    """
    production = new_production(api, pm_headers)
    survey = _empty_draft_survey(api, production["id"], td_headers)
    assert survey["camera_position_count"] == 0
    assert survey["total_signal_loss_db"] == pytest.approx(0.0, abs=0.005)

    validate_error(
        api.submit_venue_survey(survey["id"], td_headers),
        "ERR_SURVEY_NO_CAMERA_POSITIONS",
    )

    after = read_survey(api, survey["id"], td_headers)
    assert_status(after, "DRAFT", "survey status")
    assert after["camera_position_count"] == 0
    assert after["total_signal_loss_db"] == pytest.approx(0.0, abs=0.005)
    assert after["submitted_by_user_id"] is None


def test_submit_accepted_at_exactly_one_camera_position(api, pm_headers, td_headers):
    """One position is the smallest admissible plot, so the same submission succeeds and
    stamps the submitter without advancing the production.

    PRD: "Second, an empty plot can never be approved, so a survey whose `camera_position_count` is zero is refused with `ERR_SURVEY_NO_CAMERA_POSITIONS`."
    PRD: "On success the survey moves `DRAFT → SUBMITTED` and its `submitted_by_user_id` is stamped with the submitting operator's `X-User-ID`."
    PRD: "A request for changes moves the survey `SUBMITTED → CHANGES_REQUESTED` and leaves the production's stage exactly where it was."
    Design: Difficulty/boundary_precision_check/survey_submit_at_zero_versus_one_camera_position
    """
    production = new_production(api, pm_headers)
    survey = _empty_draft_survey(api, production["id"], td_headers)
    _plot(api, survey["id"], td_headers, [("HIGH_HOME", "HARD", 150)])

    submitted = validate_success(api.submit_venue_survey(survey["id"], td_headers), 200)

    assert_status(submitted, "SUBMITTED", "survey status")
    assert submitted["camera_position_count"] == 1
    assert submitted["total_signal_loss_db"] == pytest.approx(2.03, abs=0.005)
    assert submitted["submitted_by_user_id"] == TECHNICAL_DIRECTOR_ID
    assert_status(
        read_production(api, production["id"]), "PLANNED", "production stage"
    )


# ---------------------------------------------------------------------------
# Equality with the loss budget
# ---------------------------------------------------------------------------
def test_survey_total_exactly_at_the_loss_budget_submits(api, pm_headers, td_headers):
    """A 150 ft run at 2.03 dB and a 600 ft run at 8.10 dB total exactly 10.13 dB, and the
    gate refuses only strictly greater totals.

    PRD: "Third, the loss budget must hold: submission is refused with `ERR_SIGNAL_LOSS_BUDGET_EXCEEDED` when `total_signal_loss_db` is strictly greater than **10.13 dB**, with a total of exactly 10.13 accepted."
    PRD: "`signal_loss_db` is the cable loss on that run: the coax budget is **1.35 dB per 100 feet**, so the position's loss is its cable run in feet multiplied by 1.35, divided by 100, and rounded half up to two decimal places."
    Design: Corner/calculations/survey_signal_loss_exactly_at_budget_is_accepted
    """
    production = new_production(api, pm_headers)
    survey = _empty_draft_survey(api, production["id"], td_headers)
    short_run, long_run = _plot(
        api, survey["id"], td_headers,
        [("HIGH_HOME", "HARD", 150), ("TIGHT_END_ZONE", "HARD", 600)],
    )
    assert short_run["signal_loss_db"] == pytest.approx(2.03, abs=0.005)
    assert long_run["signal_loss_db"] == pytest.approx(8.10, abs=0.005)

    at_budget = read_survey(api, survey["id"], td_headers)
    assert at_budget["total_signal_loss_db"] == pytest.approx(
        MAX_SIGNAL_LOSS_BUDGET_DB, abs=0.005
    )
    assert at_budget["total_cable_run_feet"] == 750
    assert at_budget["total_power_draw_amps"] == 40
    assert at_budget["power_headroom_amps"] == 360

    submitted = validate_success(api.submit_venue_survey(survey["id"], td_headers), 200)
    assert_status(submitted, "SUBMITTED", "survey status")
    assert submitted["total_signal_loss_db"] == pytest.approx(10.13, abs=0.005)


# ---------------------------------------------------------------------------
# The venue power budget, policed at two endpoints
# ---------------------------------------------------------------------------
def test_submit_refused_when_the_plot_alone_outdraws_the_venue(
    api, pm_headers, td_headers
):
    """A plot drawing 410 A from a 400 A building leaves negative headroom, and the
    submission is refused on power rather than on the loss budget.

    PRD: "Fourth, the building must be able to power the plot: submission is refused with `ERR_VENUE_POWER_INSUFFICIENT` when `power_headroom_amps` is negative, with a headroom of exactly zero accepted."
    PRD: "Either way, five aggregates on the survey are recomputed after the position lands: `camera_position_count` is the number of positions on the survey; `total_cable_run_feet` is the sum of their cable runs; `total_power_draw_amps` is the sum of their amp draws; `power_headroom_amps` is the production's `venue_power_capacity_amps` minus that amp total, and may be negative; and `total_signal_loss_db` is the survey's loss budget."
    Design: Corner/validations/venue_power_headroom_enforced_from_both_directions
    """
    production = new_production(api, pm_headers)
    survey = _empty_draft_survey(api, production["id"], td_headers)
    add_camera_position(
        api, survey["id"], headers=td_headers, label="HIGH_HOME",
        position_type="HARD", cable_run_feet=100, power_draw_amps=200,
    )
    add_camera_position(
        api, survey["id"], headers=td_headers, label="LOW_HOME",
        position_type="HARD", cable_run_feet=100, power_draw_amps=210,
    )

    hungry = read_survey(api, survey["id"], td_headers)
    assert hungry["total_power_draw_amps"] == 410
    assert hungry["power_headroom_amps"] == -10, "headroom may go negative"
    assert hungry["total_signal_loss_db"] == pytest.approx(2.70, abs=0.005), (
        "the loss budget is comfortably satisfied, so power is the binding gate"
    )

    validate_error(
        api.submit_venue_survey(survey["id"], td_headers),
        "ERR_VENUE_POWER_INSUFFICIENT",
    )

    after = read_survey(api, survey["id"], td_headers)
    assert_status(after, "DRAFT", "survey status")
    assert after["submitted_by_user_id"] is None


def test_truck_assignment_refused_when_the_truck_plus_the_approved_plot_outdraws_the_venue(
    api, pm_headers, td_headers
):
    """The same 400 A building is policed again at assignment, where the truck's own draw
    is added to the approved plot's, so 60 A on top of 360 A is refused.

    PRD: "The first is venue power: the truck's own `power_draw_amps` plus the approved survey's `total_power_draw_amps` must be no greater than the production's `venue_power_capacity_amps`, with equality accepted; exceeding it is `ERR_VENUE_POWER_INSUFFICIENT`."
    PRD: "Among the assignment's business gates the venue-power check is reported first, then the tier rating, then the channel capacity, and the travel-window conflict last of the four."
    Design: Corner/validations/venue_power_headroom_enforced_from_both_directions
    """
    production = new_production(api, pm_headers)
    truck = new_truck(api, pm_headers, truck_code="TRK-01", power_draw_amps=60)
    approved = create_approved_survey(
        api, production["id"],
        [
            {"label": "HIGH_HOME", "position_type": "HARD",
             "cable_run_feet": 100, "power_draw_amps": 180},
            {"label": "SLASH_LEFT", "position_type": "HARD",
             "cable_run_feet": 100, "power_draw_amps": 180},
        ],
    )
    assert_status(approved, "APPROVED", "survey status")
    assert approved["total_power_draw_amps"] == 360
    assert approved["power_headroom_amps"] == 40, "the plot alone fits the building"

    surveyed = read_production(api, production["id"])
    assert_status(surveyed, "SURVEYED", "production stage")

    validate_error(
        api.assign_truck(
            production["id"],
            truck_assignment_payload(truck["id"], surveyed["version"]),
            pm_headers,
        ),
        "ERR_VENUE_POWER_INSUFFICIENT",
    )

    unchanged = read_production(api, production["id"])
    assert unchanged["truck_id"] is None, "the refused assignment holds no truck"
    assert_status(unchanged, "SURVEYED", "production stage")
    assert unchanged["version"] == surveyed["version"], (
        "a refused assignment writes nothing"
    )
    assert_status(read_truck(api, truck["id"]), "AVAILABLE", "truck status")
