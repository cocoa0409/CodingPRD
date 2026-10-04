"""Dual scoring variants: staffing by department type, water by rural verification."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_score_sheet,
    get_success_data,
    setup_scoring_cycle,
    verify_alternate_supply,
)

ANALYST = TEST_USERS["field_analyst_headers"]

_IDENTICAL_ROSTER = {"career_on_duty_per_shift": 4, "volunteers_on_duty_avg": 3}


def test_staffing_variant_combination_department_career_equivalent(api):
    """PRD §3.6: "for `VOLUNTEER` or `COMBINATION` departments the
    `CAREER_EQUIVALENT` variant counts each average responding volunteer
    (`volunteers_on_duty_avg`) at half weight" — 4 career + 3 volunteers is
    an effective strength of 5.5, scoring 15 * (5.5/6) = 13.75.

    Design: Difficulty/dual_variant_calc/staffing_variant_career_equivalent_vs_raw_headcount
    """
    ctx = setup_scoring_cycle(
        api, name="ComboTown", dept_type="COMBINATION", dept_data=dict(_IDENTICAL_ROSTER),
    )
    sheet = create_score_sheet(api, ctx["cycle"]["id"])
    assert sheet["staffing_variant_used"] == "CAREER_EQUIVALENT"
    assert sheet["staffing_points"] == pytest.approx(13.75, abs=0.005)


def test_staffing_variant_career_department_raw_headcount(api):
    """PRD §3.6: "for `CAREER` departments the `RAW_HEADCOUNT` variant counts
    every head fully — so an identical roster never scores lower under
    `RAW_HEADCOUNT`." The identical 4+3 roster scores 15 * min(1, 7/6) =
    15.00 here versus 13.75 under the discounted variant.

    Design: Difficulty/dual_variant_calc/staffing_variant_career_equivalent_vs_raw_headcount
    """
    ctx = setup_scoring_cycle(
        api, name="CareerCity", dept_type="CAREER", dept_data=dict(_IDENTICAL_ROSTER),
    )
    sheet = create_score_sheet(api, ctx["cycle"]["id"])
    assert sheet["staffing_variant_used"] == "RAW_HEADCOUNT"
    assert sheet["staffing_points"] == pytest.approx(15.00, abs=0.005)


def _rural_haven(api):
    """rural_area_pct 60 community with certified hydrants (2172/1629) and an
    unverified alternate shuttle supply of 1500 gpm / 1 site."""
    return setup_scoring_cycle(
        api, name="RuralHaven", population=3000, area_sq_miles=60, rural_area_pct=60,
        dept_type="CAREER", needed_fire_flow_gpm=2000, storage_capacity_gal=0,
        supply_works_capacity_gpm=2500, daily_consumption_gpm=200,
        dept_data={
            "career_on_duty_per_shift": 6, "volunteers_on_duty_avg": 0,
            "training_hours_per_firefighter_annual": 240, "training_facility_level": "B",
            "live_fire_training": True, "coverage_pct_within_5mi": 50,
        },
        apparatus=[
            {"kind": "ENGINE", "pump_capacity_gpm": 1800},
            {"kind": "LADDER", "ladder_height_ft": 80},
        ],
        alternate_supply={"alternate_shuttle_capacity_gpm": 1500, "alternate_sites_count": 1},
        verify_alternate=False,
        hydrant_count=2,
        flow_tests=[
            {"hydrant": 0, "measured_flow_gpm": 1200, "outcome": "certified"},
            {"hydrant": 1, "measured_flow_gpm": 900, "outcome": "certified"},
        ],
        comms={"operators_on_duty_min": 2, "avg_alarm_to_dispatch_seconds": 55,
               "redundant_circuits": True, "backup_power": True},
    )


def test_water_variant_municipal_when_alternate_unverified(api):
    """PRD §3.6: "The `RURAL_SHUTTLE` variant applies when the community's
    `rural_area_pct` exceeds 50 and its water system's `alternate_verified`
    is true; otherwise the `MUNICIPAL` variant applies."

    Design: Difficulty/dual_variant_calc/water_variant_municipal_vs_rural_shuttle
    """
    ctx = _rural_haven(api)
    sheet = create_score_sheet(api, ctx["cycle"]["id"])
    assert sheet["water_variant_used"] == "MUNICIPAL"
    assert sheet["water_total_points"] == pytest.approx(35.00, abs=0.005)
    assert sheet["adjusted_total_points"] == pytest.approx(85.00, abs=0.005)
    assert sheet["base_class"] == 2
    assert sheet["split_class_beyond_hydrant"] == 4


def test_water_variant_rural_shuttle_after_alternate_verified(api):
    """PRD §3.6: "Under `RURAL_SHUTTLE`, hydrant data is ignored entirely:
    `flow_points` is 18 times the lesser of 1 and the ratio of
    `alternate_shuttle_capacity_gpm` to the NFF, and `distribution_points`
    is 7 times the lesser of 1 and the ratio of `alternate_sites_count` to a
    target of 2 sites".

    Design: Difficulty/dual_variant_calc/water_variant_municipal_vs_rural_shuttle
    """
    ctx = _rural_haven(api)
    sheet1 = create_score_sheet(api, ctx["cycle"]["id"])
    assert sheet1["water_variant_used"] == "MUNICIPAL"
    verify_alternate_supply(api, ctx["system"]["id"])
    sheet2 = create_score_sheet(api, ctx["cycle"]["id"])
    assert sheet2["water_variant_used"] == "RURAL_SHUTTLE"
    assert sheet2["flow_points"] == pytest.approx(13.50, abs=0.005)
    assert sheet2["distribution_points"] == pytest.approx(3.50, abs=0.005)
    assert sheet2["water_total_points"] == pytest.approx(27.00, abs=0.005)
    assert sheet2["adjusted_total_points"] == pytest.approx(77.00, abs=0.005)
    assert sheet2["base_class"] == 3
    assert sheet2["split_class_beyond_hydrant"] == 3
    superseded = get_success_data(api.get_score_sheet(sheet1["id"], ANALYST))
    assert superseded["status"] == "SUPERSEDED", "the second create supersedes the first DRAFT"
