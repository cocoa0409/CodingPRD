"""Facility inspection scoring: the two refresh-cycle variants over one franchisee.

Two clubs of the same operator, identical four sub-scores, and a single difference in
opening date. The legacy site is graded against a 42-month refresh cycle and the modern
one against 60 months, which is enough to move the weighted total across the pass mark.
"""

from test_helpers import (
    create_club,
    create_franchisee,
    create_territory,
    inspect_club,
    open_club,
    read_club,
    read_franchisee,
)


def _two_clubs_scored_on_identical_subscores() -> dict:
    """One franchisee owning a 2019 club and a 2021 club, each inspected once with
    78 / 86 / 80 sub-scores against a 54-month-old equipment floor."""
    franchisee = create_franchisee(
        legal_name="Two Coast Fitness LLC", contact_email="ops@twocoastfit.example"
    )
    legacy_territory = create_territory(
        franchisee["id"], center_lat=34.0, center_lng=-118.0, protected_radius_km=5.0
    )
    modern_territory = create_territory(
        franchisee["id"], center_lat=34.5, center_lng=-118.0, protected_radius_km=5.0
    )
    legacy_club = create_club(
        legacy_territory["id"],
        franchisee["id"],
        name="Legacy Fitness Club",
        opened_on="2019-06-01",
    )
    modern_club = create_club(
        modern_territory["id"],
        franchisee["id"],
        name="Modern Fitness Club",
        opened_on="2021-06-01",
    )
    legacy_club = open_club(legacy_club["id"], franchisee["id"])
    modern_club = open_club(modern_club["id"], franchisee["id"])
    legacy_inspection = inspect_club(legacy_club["id"], "2026-07-10", 78, 86, 80, 54)
    modern_inspection = inspect_club(modern_club["id"], "2026-07-20", 78, 86, 80, 54)
    return {
        "franchisee": franchisee,
        "legacy_club": legacy_club,
        "modern_club": modern_club,
        "legacy_inspection": legacy_inspection,
        "modern_inspection": modern_inspection,
    }


def test_club_opened_before_2020_is_graded_on_the_accelerated_refresh_cycle():
    """A 2019 opening selects the 42-month cycle, against which a 54-month-old floor is
    over-age: 100 minus 129 floors at 0 refresh points.

    PRD 3.9: "On the accelerated cycle, `refresh_cycle_months_applied` is 42 months and
    `variant_applied` is `ACCELERATED_CYCLE`; otherwise `refresh_cycle_months_applied` is
    the brand-standard 60 months and `variant_applied` is `STANDARD_CYCLE`."

    Design: Difficulty/dual_variant_calc/inspection_standard_cycle_vs_accelerated_cycle_diverge_on_identical_subscores
    """
    setup = _two_clubs_scored_on_identical_subscores()
    inspection = setup["legacy_inspection"]

    assert inspection["variant_applied"] == "ACCELERATED_CYCLE"
    assert inspection["refresh_cycle_months_applied"] == 42
    assert inspection["refresh_pts"] == 0


def test_club_opened_after_2020_is_graded_on_the_brand_standard_cycle():
    """The 2021 opening keeps the 60-month cycle, where the same 54-month floor still
    earns 10 refresh points.

    PRD 3.9: "On the standard cycle a 54-month-old floor yields 100 minus 90, which is 10
    refresh points; on the accelerated cycle the same 54 months yields 100 minus 129,
    floored to 0."

    Design: Difficulty/dual_variant_calc/inspection_standard_cycle_vs_accelerated_cycle_diverge_on_identical_subscores
    """
    setup = _two_clubs_scored_on_identical_subscores()
    inspection = setup["modern_inspection"]

    assert inspection["variant_applied"] == "STANDARD_CYCLE"
    assert inspection["refresh_cycle_months_applied"] == 60
    assert inspection["refresh_pts"] == 10


def test_identical_subscores_land_one_point_apart_across_the_two_cycles():
    """68.7 rounds to 69 on the accelerated cycle and 70.2 rounds to 70 on the standard
    one, so the same walk-through fails at one club and passes at the other.

    PRD 3.9: "Because the two cycles differ only in the refresh term, one identical set of
    four sub-scores can land on opposite sides of the pass mark depending purely on the
    club's opening date and prior compliance state."

    Design: Difficulty/dual_variant_calc/inspection_standard_cycle_vs_accelerated_cycle_diverge_on_identical_subscores
    """
    setup = _two_clubs_scored_on_identical_subscores()

    assert setup["legacy_inspection"]["score"] == 69
    assert setup["modern_inspection"]["score"] == 70
    assert setup["modern_inspection"]["score"] - setup["legacy_inspection"]["score"] == 1
    assert setup["legacy_inspection"]["status"] == "REMEDIATION_REQUIRED"
    assert setup["modern_inspection"]["status"] == "CLOSED"


def test_failing_club_is_suspended_while_the_passing_club_only_drops_to_watch():
    """69 is below 70 so the legacy club becomes NON_COMPLIANT and is suspended; 70 sits
    in the 70-to-84 band so the modern club is merely on WATCH and keeps trading.

    PRD 3.9: "The club's `last_inspection_score` is set to the new `score`, and its
    `equipment_compliance_state` is re-derived from that score alone: `COMPLIANT` at 85 or
    above, `WATCH` at 70 through 84, and `NON_COMPLIANT` below 70."

    Design: Difficulty/dual_variant_calc/inspection_standard_cycle_vs_accelerated_cycle_diverge_on_identical_subscores
    """
    setup = _two_clubs_scored_on_identical_subscores()

    legacy = read_club(setup["legacy_club"]["id"])
    modern = read_club(setup["modern_club"]["id"])
    assert legacy["last_inspection_score"] == 69
    assert legacy["equipment_compliance_state"] == "NON_COMPLIANT"
    assert legacy["status"] == "SUSPENDED"
    assert modern["last_inspection_score"] == 70
    assert modern["equipment_compliance_state"] == "WATCH"
    assert modern["status"] == "OPEN"


def test_later_passing_inspection_resets_the_trailing_failure_run_to_zero():
    """The streak is the current trailing run, so the 2026-07-20 pass wipes out the
    2026-07-10 failure and the compliance score returns to a full 100.

    PRD 3.9: "`inspection_fail_streak` is found by walking every inspection of every club
    belonging to this franchisee whose `status` is `SCORED`, `REMEDIATION_REQUIRED`,
    `REMEDIATION_WAIVED` or `CLOSED` and whose `score` is not null, in ascending
    `inspection_date` order with ascending `created_at` breaking ties, counting up by one
    for each inspection scoring below 70 and resetting to zero at each inspection scoring
    70 or better — so the figure is the length of the *current trailing* run of failures,
    not the lifetime total."

    Design: Difficulty/dual_variant_calc/inspection_standard_cycle_vs_accelerated_cycle_diverge_on_identical_subscores
    """
    setup = _two_clubs_scored_on_identical_subscores()

    franchisee = read_franchisee(setup["franchisee"]["id"])
    assert franchisee["inspection_fail_streak"] == 0
    assert franchisee["compliance_score"] == 100
    assert franchisee["status"] == "ACTIVE"
