"""Class boundaries: the 90.00 points threshold and the distance radii."""
import pytest

from test_helpers import (
    TEST_USERS,
    activate_classification,
    create_property,
    create_score_sheet,
    get_success_data,
    publish_classification,
    reject_credit,
    setup_classification_review,
    setup_scoring_cycle,
    verify_credit,
)

ANALYST = TEST_USERS["field_analyst_headers"]


def _boundaryville_kwargs():
    """Engineered for subtotal 85.00 (fd 40.00, water 35.00, comms 10.00)."""
    return dict(
        name="Boundaryville", population=12000, area_sq_miles=25, rural_area_pct=30,
        dept_type="CAREER", needed_fire_flow_gpm=2000, storage_capacity_gal=0,
        supply_works_capacity_gpm=2500, daily_consumption_gpm=300,
        dept_data={
            "career_on_duty_per_shift": 6, "volunteers_on_duty_avg": 0,
            "training_hours_per_firefighter_annual": 240, "training_facility_level": "B",
            "live_fire_training": True, "coverage_pct_within_5mi": 50,
        },
        apparatus=[
            {"kind": "ENGINE", "pump_capacity_gpm": 1800},
            {"kind": "LADDER", "ladder_height_ft": 80},
        ],
        hydrant_count=2,
        flow_tests=[
            {"hydrant": 0, "measured_flow_gpm": 1200, "outcome": "certified"},
            {"hydrant": 1, "measured_flow_gpm": 900, "outcome": "certified"},
        ],
        comms={"operators_on_duty_min": 2, "avg_alarm_to_dispatch_seconds": 55,
               "redundant_circuits": True, "backup_power": True},
    )


def _credits_kwargs():
    return [
        {"program_type": "PREVENTION_INSPECTION", "activity_points": 2.5, "outcome": "verified"},
        {"program_type": "CODE_ENFORCEMENT", "activity_points": 3.0, "outcome": "verified"},
        {"program_type": "PUBLIC_EDUCATION", "activity_points": 1.0, "outcome": "verified"},
    ]


def test_class_boundary_exactly_90_earns_class_1(api):
    """PRD §3.6: "The sheet's `base_class` reads off fixed thresholds: an
    adjusted total of 90 or more earns class 1, 80 or more class 2, 70 or
    more class 3, 60 or more class 4, 50 or more class 5, 40 or more class 6,
    30 or more class 7, 20 or more class 8, 10 or more class 9, and anything
    below 10 earns class 10."

    Design: Difficulty/boundary_precision_check/class_boundary_90_00_vs_89_99
    """
    ctx = setup_scoring_cycle(api, credits=_credits_kwargs(), **_boundaryville_kwargs())
    sheet = create_score_sheet(api, ctx["cycle"]["id"])
    assert sheet["adjusted_total_points"] == pytest.approx(90.00, abs=0.005)
    assert sheet["base_class"] == 1, "90.00 is inside class 1"
    assert sheet["split_class_beyond_hydrant"] == 4, "split total 65.00"


def test_class_boundary_89_99_falls_to_class_2(api):
    """PRD §3.6: "The sheet's `base_class` reads off fixed thresholds: an
    adjusted total of 90 or more earns class 1, 80 or more class 2" — moving
    the raw CRR from 5.00 to 4.99 drops the adjusted total to 89.99.

    Design: Difficulty/boundary_precision_check/class_boundary_90_00_vs_89_99
    """
    credits = _credits_kwargs() + [
        {"program_type": "FIRE_INVESTIGATION", "activity_points": 0.99, "outcome": "pending"}
    ]
    ctx = setup_scoring_cycle(api, credits=credits, **_boundaryville_kwargs())
    sheet1 = create_score_sheet(api, ctx["cycle"]["id"])
    assert sheet1["adjusted_total_points"] == pytest.approx(90.00, abs=0.005)
    credit_c = ctx["credits"][2]["id"]
    credit_d = ctx["credits"][3]["id"]
    reject_credit(api, credit_c)
    verify_credit(api, credit_d)
    sheet2 = create_score_sheet(api, ctx["cycle"]["id"])
    assert sheet2["crr_raw_points"] == pytest.approx(4.99, abs=0.005)
    assert sheet2["adjusted_total_points"] == pytest.approx(89.99, abs=0.005)
    assert sheet2["base_class"] == 2, "89.99 falls to class 2"
    superseded = get_success_data(api.get_score_sheet(sheet1["id"], ANALYST))
    assert superseded["status"] == "SUPERSEDED"


def _classified_boundaryville(api):
    """EFFECTIVE classification with base class 1 and split class 4."""
    ctx = setup_classification_review(api, credits=_credits_kwargs(), **_boundaryville_kwargs())
    classification = publish_classification(api, ctx["cycle"]["id"], ctx["sheet"]["id"])
    activate_classification(api, classification["id"])
    return ctx


def test_hydrant_distance_boundary_1000ft(api):
    """PRD §3.8: "a property within that radius but more than 1000 feet from
    the nearest `ACTIVE` hydrant takes the classification's
    `split_class_beyond_hydrant`; every other property takes the
    `base_class`. The boundaries are inclusive toward the better class:
    exactly 1000 feet and exactly 5.0 miles both count as within."

    Design: Difficulty/boundary_precision_check/hydrant_distance_boundary_1000ft_and_station_5mi
    """
    ctx = _classified_boundaryville(api)
    community_id = ctx["community"]["id"]
    within = create_property(
        api, community_id, address="Within-1000", distance_to_nearest_hydrant_ft=1000,
        distance_to_nearest_station_road_miles=3.0, construction_type="MASONRY",
        insured_value_cents=100000000,
    )
    beyond = create_property(
        api, community_id, address="Beyond-1001", distance_to_nearest_hydrant_ft=1001,
        distance_to_nearest_station_road_miles=3.0, construction_type="MASONRY",
        insured_value_cents=100000000,
    )
    assert within["applicable_class"] == 1, "exactly 1000 ft is within hydrant distance"
    assert beyond["applicable_class"] == 4, "1001 ft takes the split class"
    assert beyond["applicable_premium_modifier"] == pytest.approx(0.80), "class 4 modifier"


def test_station_distance_boundary_5_miles(api):
    """PRD §3.8: "A property more than 5.0 road miles from the nearest active
    station takes `applicable_class` 10 regardless of hydrants" and "The
    boundaries are inclusive toward the better class: exactly 1000 feet and
    exactly 5.0 miles both count as within."

    Design: Difficulty/boundary_precision_check/hydrant_distance_boundary_1000ft_and_station_5mi
    """
    ctx = _classified_boundaryville(api)
    community_id = ctx["community"]["id"]
    within = create_property(
        api, community_id, address="Exactly-5mi", distance_to_nearest_hydrant_ft=500,
        distance_to_nearest_station_road_miles=5.0, construction_type="MASONRY",
        insured_value_cents=100000000,
    )
    beyond = create_property(
        api, community_id, address="Beyond-5mi", distance_to_nearest_hydrant_ft=500,
        distance_to_nearest_station_road_miles=5.1, construction_type="MASONRY",
        insured_value_cents=100000000,
    )
    assert within["applicable_class"] == 1, "exactly 5.0 road miles is within station distance"
    assert beyond["applicable_class"] == 10, "beyond 5 miles is unprotected regardless of hydrants"
