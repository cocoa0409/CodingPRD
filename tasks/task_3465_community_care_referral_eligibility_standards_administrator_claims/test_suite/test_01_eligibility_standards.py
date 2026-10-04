"""Eligibility determination: drive-time variants, choice leg, wait boundary,
and assessment supersession."""
import pytest

from test_helpers import (
    TEST_USERS, api_client, validate_paginated,
    assert_eligibility_assessment,
    create_station, create_veteran, get_veteran, run_assessment,
)

CLERK = TEST_USERS["eligibility_clerk_headers"]


def test_drive_time_urban_rural_divergence_same_coordinates():
    """PRD §3.2: "The urban variant multiplies the distance by a circuity
    factor of 1.4 and assumes 40 miles per hour — that is, distance times 1.4,
    divided by 40, times 60, exactly 2.1000 minutes per crow-fly mile. The
    rural variant multiplies by a circuity factor of 1.2 and assumes 55 miles
    per hour — distance times 1.2, divided by 55, times 60, exactly 1.3091
    minutes per crow-fly mile, so identical coordinates always yield fewer
    rural minutes than urban."
    PRD §3.2: "`drive_standard_failed` is true exactly when `drive_time_minutes`
    is strictly greater than the category standard — 30 minutes for
    `PRIMARY_CARE`, 60 minutes for `SPECIALTY_CARE`; a drive time exactly equal
    to the standard passes."

    Design: Difficulty/dual_variant_calc/drive_time_urban_rural_divergence_same_coordinates
    """
    station = create_station()
    v_urban = create_veteran(station, full_name="V Urban")
    v_rural = create_veteran(station, full_name="V Rural")

    a_urban = run_assessment(v_urban["id"], geo_classification="URBAN")
    a_rural = run_assessment(v_rural["id"], geo_classification="RURAL")

    assert_eligibility_assessment(a_urban)
    assert_eligibility_assessment(a_rural)
    assert a_urban["drive_time_minutes"] == pytest.approx(37.9, abs=0.001), (
        f"URBAN drive time must be 37.9 (18.0266 mi * 1.4 / 40 * 60), "
        f"got {a_urban['drive_time_minutes']}"
    )
    assert a_rural["drive_time_minutes"] == pytest.approx(23.6, abs=0.001), (
        f"RURAL drive time must be 23.6 (18.0266 mi * 1.2 / 55 * 60), "
        f"got {a_rural['drive_time_minutes']}"
    )
    assert a_urban["drive_standard_failed"] is True   # 37.9 > 30
    assert a_rural["drive_standard_failed"] is False  # 23.6 <= 30
    assert a_urban["eligible"] is True
    assert a_rural["eligible"] is False


def test_eligibility_choice_only_path():
    """PRD §3.2: "`choice_granted` is true exactly when `choice_requested` is
    true and the veteran's `priority_group` is at most 4."
    PRD §3.2: "Finally, `eligible` is true when any one leg holds: the service
    is not available at the home station, or the drive-time standard failed, or
    the wait-time standard failed, or the choice element was granted."

    Design: Difficulty/combinatorial_formula/eligibility_branch_composition_choice_only_path
    """
    station = create_station()
    v_yes = create_veteran(station, full_name="V ChoiceYes", priority_group=3)
    v_no = create_veteran(station, full_name="V ChoiceNo", priority_group=5)

    a_yes = run_assessment(v_yes["id"], geo_classification="RURAL",
                           choice_requested=True)
    a_no = run_assessment(v_no["id"], geo_classification="RURAL",
                          choice_requested=True)

    # Every access standard is met for both veterans (RURAL 23.6 <= 30,
    # waits 10 <= 20, station offers PT_EVAL); only the choice leg differs.
    for a in (a_yes, a_no):
        assert a["service_available"] is True
        assert a["drive_standard_failed"] is False
        assert a["wait_standard_failed"] is False
    assert a_yes["choice_granted"] is True and a_yes["eligible"] is True
    assert a_no["choice_granted"] is False and a_no["eligible"] is False


def test_wait_standard_exactly_at_threshold_not_failed():
    """PRD §3.2: "`wait_standard_failed` is true exactly when `wait_days` is
    strictly greater than the category standard — 20 days for `PRIMARY_CARE`,
    28 days for `SPECIALTY_CARE`; a wait exactly equal to the standard passes."

    Design: Difficulty/boundary_precision_check/wait_standard_exactly_at_threshold_not_failed
    """
    st20 = create_station(name="Station W20", primary_wait_days=20)
    st21 = create_station(name="Station W21", primary_wait_days=21)
    v20 = create_veteran(st20, full_name="V Boundary20")
    v21 = create_veteran(st21, full_name="V Boundary21")

    a20 = run_assessment(v20["id"], geo_classification="RURAL")
    a21 = run_assessment(v21["id"], geo_classification="RURAL")

    assert a20["wait_days"] == 20 and a20["wait_standard_failed"] is False
    assert a20["eligible"] is False
    assert a21["wait_days"] == 21 and a21["wait_standard_failed"] is True
    assert a21["eligible"] is True


def test_assessment_supersede_marks_prior_and_bumps_veteran_version():
    """PRD §3.2: "creating a new assessment for the same veteran and the same
    `service_code` supersedes the previous `CURRENT` assessment for that pair,
    moving it to `SUPERSEDED`; supersession is a mutation of the veteran, so
    the veteran's `version` increments by one on every successful assessment
    creation."

    Design: Corner/entities/assessment_supersede_marks_prior_and_bumps_veteran_version
    """
    station = create_station()
    veteran = create_veteran(station, full_name="V Sup")
    assert veteran["version"] == 1

    a1 = run_assessment(veteran["id"])
    assert get_veteran(veteran["id"])["version"] == 2
    a2 = run_assessment(veteran["id"], service_category="SPECIALTY_CARE",
                        geo_classification="RURAL", choice_requested=True)

    assert get_veteran(veteran["id"])["version"] == 3
    items, meta = validate_paginated(
        api_client.list_eligibility_assessments(veteran["id"], CLERK)
    )
    assert meta["total_count"] == 2 and len(items) == 2
    by_id = {a["id"]: a for a in items}
    assert by_id[a1["id"]]["status"] == "SUPERSEDED"
    assert by_id[a2["id"]]["status"] == "CURRENT"
