"""Score-sheet formula branches: equipment min/max, CRR cap order, comms tiers."""
import pytest

from test_helpers import (
    add_apparatus,
    attest_comms,
    create_score_sheet,
    set_apparatus_status,
    setup_scoring_cycle,
    verify_credit,
)


def _gear_town(api):
    return setup_scoring_cycle(
        api, name="GearTown", population=8000, area_sq_miles=15, rural_area_pct=10,
        apparatus=[
            {"kind": "ENGINE", "pump_capacity_gpm": 1800},
            {"kind": "LADDER", "ladder_height_ft": 74},
            {"kind": "ENGINE", "pump_capacity_gpm": 1000, "status": "RESERVE"},
            {"kind": "TANKER", "tank_capacity_gal": 1500},
        ],
    )


def test_equipment_credit_74ft_ladder_contributes_nothing(api):
    """PRD §3.6: "aerial credit is 6 points when at least one `FRONTLINE`
    `LADDER` or `QUINT` has a `ladder_height_ft` of 75 feet or more, else 0"
    — a 74-ft ladder earns 0, so equipment is pump 8.00 + aerial 0.00 +
    reserve 3.00 + tanker 3.00 = 14.00.

    Design: Difficulty/combinatorial_formula/equipment_credit_nested_minmax_branches
    """
    ctx = _gear_town(api)
    sheet = create_score_sheet(api, ctx["cycle"]["id"])
    assert sheet["equipment_points"] == pytest.approx(14.00, abs=0.005)


def test_equipment_credit_75ft_ladder_crosses_threshold(api):
    """PRD §3.6: "aerial credit is 6 points when at least one `FRONTLINE`
    `LADDER` or `QUINT` has a `ladder_height_ft` of 75 feet or more, else 0"
    — swapping the 74-ft ladder out for a 75-ft one moves equipment to
    20.00 with every other input unchanged.

    Design: Difficulty/combinatorial_formula/equipment_credit_nested_minmax_branches
    """
    ctx = _gear_town(api)
    sheet1 = create_score_sheet(api, ctx["cycle"]["id"])
    ladder74 = ctx["apparatus"][1]["id"]
    set_apparatus_status(api, ctx["department"]["id"], ladder74, "OUT_OF_SERVICE")
    add_apparatus(api, ctx["department"]["id"], "LADDER", ladder_height_ft=75)
    sheet2 = create_score_sheet(api, ctx["cycle"]["id"])
    assert sheet2["equipment_points"] == pytest.approx(20.00, abs=0.005)
    assert sheet2["equipment_points"] - sheet1["equipment_points"] == pytest.approx(6.00, abs=0.005)


def _prevburg(api):
    """COMBINATION community engineered for subtotal 44.48 with three
    VERIFIED credits capped at 2.0 each (raw CRR 6.00)."""
    return setup_scoring_cycle(
        api, name="Prevburg", population=6000, area_sq_miles=30, rural_area_pct=40,
        dept_type="COMBINATION", needed_fire_flow_gpm=3000, storage_capacity_gal=0,
        supply_works_capacity_gpm=1800, daily_consumption_gpm=150,
        dept_data={
            "career_on_duty_per_shift": 2, "volunteers_on_duty_avg": 4,
            "training_hours_per_firefighter_annual": 120, "training_facility_level": "C",
            "live_fire_training": False, "coverage_pct_within_5mi": 50,
        },
        apparatus=[{"kind": "ENGINE", "pump_capacity_gpm": 1800}],
        hydrant_count=1,
        flow_tests=[{"measured_flow_gpm": 850, "outcome": "certified"}],
        comms={"operators_on_duty_min": 1, "avg_alarm_to_dispatch_seconds": 75,
               "redundant_circuits": True, "backup_power": False},
        credits=[
            {"program_type": "PREVENTION_INSPECTION", "activity_points": 2.5, "outcome": "verified"},
            {"program_type": "CODE_ENFORCEMENT", "activity_points": 3.0, "outcome": "verified"},
            {"program_type": "PUBLIC_EDUCATION", "activity_points": 2.0, "outcome": "verified"},
        ],
    )


def test_crr_cap_percentage_beats_raw_sum_and_flat_cap(api):
    """PRD §3.6: "a percentage cap is computed as one-tenth of
    `subtotal_points` rounded half-up to 2 decimal places, and
    `crr_effective_points` is the smallest of the raw sum, an absolute cap of
    5.5 points, and that percentage cap."

    Design: Difficulty/combinatorial_formula/crr_cap_circular_evaluation_order
    """
    ctx = _prevburg(api)
    sheet = create_score_sheet(api, ctx["cycle"]["id"])
    assert sheet["subtotal_points"] == pytest.approx(44.48, abs=0.005)
    assert sheet["crr_raw_points"] == pytest.approx(6.00, abs=0.005)
    assert sheet["crr_effective_points"] == pytest.approx(4.45, abs=0.005), (
        "10% of 44.48 rounds to 4.45 and beats both the raw 6.00 and the flat 5.5"
    )


def test_crr_cap_adjusted_total_and_class(api):
    """PRD §3.6: "`adjusted_total_points` is then the subtotal plus
    `crr_effective_points` minus `divergence_penalty_points`." — 44.48 + 4.45
    = 48.93, which maps to class 6 under the fixed thresholds.

    Design: Difficulty/combinatorial_formula/crr_cap_circular_evaluation_order
    """
    ctx = _prevburg(api)
    sheet = create_score_sheet(api, ctx["cycle"]["id"])
    assert sheet["adjusted_total_points"] == pytest.approx(48.93, abs=0.005)
    assert sheet["base_class"] == 6


def test_comms_alarm_threshold_60_vs_61(api):
    """PRD §3.6: "4 points when `comms_avg_alarm_to_dispatch_seconds` is at
    most 60 seconds, 2 points when at most 90 seconds, else 0" — the
    60-second boundary is inclusive.

    Design: Corner/calculations/comms_alarm_threshold_60_vs_61
    """
    ctx = setup_scoring_cycle(
        api, name="Dispatchburg",
        comms={"operators_on_duty_min": 2, "avg_alarm_to_dispatch_seconds": 60,
               "redundant_circuits": True, "backup_power": True},
    )
    sheet1 = create_score_sheet(api, ctx["cycle"]["id"])
    assert sheet1["comms_points"] == 10, "alarm 60s earns the full 4 points"
    attest_comms(
        api, ctx["community"]["id"],
        operators_on_duty_min=2, avg_alarm_to_dispatch_seconds=61,
        redundant_circuits=True, backup_power=True,
    )
    sheet2 = create_score_sheet(api, ctx["cycle"]["id"])
    assert sheet2["comms_points"] == 8, "alarm 61s drops the alarm tier to 2 points"


def test_crr_item_cap_applied_on_verify(api):
    """PRD §3.5: "Verifying a credit (`PENDING` → `VERIFIED`) caps the
    recognized value at two points per program: `credited_points` becomes
    the lesser of the claimed `activity_points` and 2.0".

    Design: Corner/calculations/crr_item_cap_applied_on_verify
    """
    ctx = setup_scoring_cycle(
        api, name="Capville", target_state="FIELD_VERIFICATION",
        credits=[{"program_type": "PUBLIC_EDUCATION", "activity_points": 3.5,
                  "evidence_note": "school program"}],
    )
    credit_id = ctx["credits"][0]["id"]
    verified = verify_credit(api, credit_id)
    assert verified["status"] == "VERIFIED"
    assert verified["credited_points"] == pytest.approx(2.00, abs=0.005)
