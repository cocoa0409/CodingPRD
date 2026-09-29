"""Request payload factories.

Every money, weight, volume, rate and thickness value is emitted as a JSON
number, never as a string. Every datetime field is emitted as a full ISO-8601
UTC instant, never as a date-only literal, because the PRD requires "datetime
fields parseable as ISO-8601 UTC instants".
"""

from typing import Any, Dict, List, Optional

from .constants import (
    ACTION_RENEW,
    APP_NOZZLE,
    APPROVE,
    DECISION_ACCEPT,
    DESIGN_STANDARD_API_650_BASIC,
    DFT_SPOT_AVERAGE_80_120,
    DISPOSAL_DISCHARGE_TO_POTW,
    DOC_MILL_TEST_REPORTS,
    FOUNDATION_RINGWALL_CONCRETE,
    LOT_ROLLED,
    METHOD_COSINE_BEST_FIT,
    NDE_METHOD_RT,
    PHASE_SHELL_COMPLETE,
    PREP_SSPC_SP6,
    PROCESS_SMAW,
    REVIEW_ACCEPT,
    ROOF_CONE_SUPPORTED,
    SCOPE_INTERNAL_LINING,
    SEAM_VERTICAL,
    SOURCE_MUNICIPAL,
)

Json = Dict[str, Any]


def _merge(payload: Json, overrides: Json) -> Json:
    """Apply overrides; a value of ``_OMIT`` removes the key entirely."""
    result = dict(payload)
    for key, value in overrides.items():
        if value is OMIT:
            result.pop(key, None)
        else:
            result[key] = value
    return result


class _Omit:
    def __repr__(self):
        return "OMIT"


OMIT = _Omit()


# --- Tank --------------------------------------------------------------
def tank_payload(**overrides) -> Json:
    """TK-101: 100 ft diameter, 40 ft shell, filled to 40 ft, SG 0.85.

    Its diameter sits in the "from 50 feet up to but not including 120 feet"
    band, so `min_nominal_thickness_in` is derived as 0.250.
    """
    return _merge(
        {
            "tank_tag": "TK-101",
            "design_standard": DESIGN_STANDARD_API_650_BASIC,
            "diameter_ft": 100.0,
            "shell_height_ft": 40.0,
            "design_liquid_level_ft": 40.0,
            "product_specific_gravity": 0.85,
            "joint_efficiency": 1.00,
            "corrosion_allowance_in": 0.0625,
            "roof_type": ROOF_CONE_SUPPORTED,
            "bottom_thickness_in": 0.25,
            "bottom_minimum_thickness_in": 0.10,
            "assumed_corrosion_rate_ipy": 0.01,
        },
        overrides,
    )


def phase_transition_payload(target_phase=PHASE_SHELL_COMPLETE, **overrides) -> Json:
    return _merge({"target_phase": target_phase}, overrides)


# --- Foundation --------------------------------------------------------
def foundation_package_payload(tank_id: str, **overrides) -> Json:
    """Eight equally spaced monitoring points, differential ratio 0.005.

    Against a 100 ft diameter this freezes `point_spacing_in` at 471.2389 and
    `allowable_differential_in` at 2.356.
    """
    return _merge(
        {
            "tank_id": tank_id,
            "foundation_type": FOUNDATION_RINGWALL_CONCRETE,
            "ringwall_top_elevation_ft": 1.5,
            "permitted_uniform_settlement_in": 6.0,
            "permitted_differential_ratio": 0.005,
            "monitoring_point_count": 8,
            "settlement_evaluation_method": METHOD_COSINE_BEST_FIT,
        },
        overrides,
    )


def point_readings(elevations: List[float]) -> List[Json]:
    """Build a point_readings array with point_index running 1..len(elevations)."""
    return [
        {"point_index": index + 1, "elevation_in": float(value)}
        for index, value in enumerate(elevations)
    ]


def uniform_readings(count: int = 8, elevation: float = 100.0) -> List[Json]:
    return point_readings([elevation] * count)


def settlement_survey_payload(
    foundation_package_id: str,
    elevations: Optional[List[float]] = None,
    fill_percent: float = 0.0,
    **overrides,
) -> Json:
    payload = {
        "foundation_package_id": foundation_package_id,
        "fill_percent": float(fill_percent),
        "point_readings": point_readings(elevations if elevations is not None else [100.0] * 8),
    }
    return _merge(payload, overrides)


def foundation_acceptance_payload(decision=DECISION_ACCEPT, **overrides) -> Json:
    return _merge({"decision": decision}, overrides)


# --- Plate lots --------------------------------------------------------
def plate_lot_payload(tank_id: str, **overrides) -> Json:
    """Lot A: ten plates of 1250.5 lb, so receipt books 12505.00 lb."""
    return _merge(
        {
            "tank_id": tank_id,
            "mill_name": "Nucor Berkeley",
            "heat_number": "H-44821",
            "thickness_in": 0.4375,
            "plate_count": 10,
            "plate_weight_lb": 1250.5,
            "unit_cost_usd_per_lb": 0.62,
        },
        overrides,
    )


def lot_status_payload(target_status=LOT_ROLLED, **overrides) -> Json:
    return _merge({"target_status": target_status}, overrides)


def allocation_payload(shell_course_id: str, allocated_weight_lb: float, **overrides) -> Json:
    return _merge(
        {
            "shell_course_id": shell_course_id,
            "allocated_weight_lb": float(allocated_weight_lb),
        },
        overrides,
    )


def allocation_release_payload(reason: str = "Plate re-cut for a revised layout", **overrides) -> Json:
    return _merge({"reason": reason}, overrides)


# --- Shell courses -----------------------------------------------------
def shell_course_payload(tank_id: str, course_number: int = 1, **overrides) -> Json:
    """Course 1 of TK-101: 8 ft wide, 0.4375 in plate, Sd 23200, St 24900.

    The one-foot method then requires 0.434 in for the design case and 0.407 in
    for the test case, so `governing_case` is DESIGN and the ordered plate is
    ADEQUATE.
    """
    return _merge(
        {
            "tank_id": tank_id,
            "course_number": course_number,
            "course_width_ft": 8.0,
            "plate_thickness_in": 0.4375,
            "material_spec": "A516-70",
            "allowable_stress_design_psi": 23200.0,
            "allowable_stress_test_psi": 24900.0,
        },
        overrides,
    )


# --- Welders -----------------------------------------------------------
def welder_payload(welder_stamp: str = "W-07", **overrides) -> Json:
    """W-07: SMAW, both thickness ceilings 0.75 in, qualified 2026-06-01.

    With the default `continuity_limit_days` of 180 the continuity window
    expires at 2026-11-28T00:00:00Z.
    """
    return _merge(
        {
            "welder_stamp": welder_stamp,
            "full_name": "Dale Rutherford",
            "process": PROCESS_SMAW,
            "qualified_positions": ["3G", "4G"],
            "welder_qualified_thickness_max_in": 0.75,
            "wps_qualified_thickness_max_in": 0.75,
            "wps_number": "WPS-SMAW-001",
            "qualification_date_utc": "2026-06-01T00:00:00Z",
        },
        overrides,
    )


def qualification_action_payload(action=ACTION_RENEW, **overrides) -> Json:
    return _merge({"action": action}, overrides)


# --- Weld seams --------------------------------------------------------
def weld_seam_payload(
    shell_course_id: str, seam_label: str = "V1", sequence_index: int = 1, **overrides
) -> Json:
    return _merge(
        {
            "shell_course_id": shell_course_id,
            "seam_type": SEAM_VERTICAL,
            "seam_label": seam_label,
            "length_in": 96.0,
            "sequence_index": sequence_index,
        },
        overrides,
    )


def weld_log_payload(welder_id: str, **overrides) -> Json:
    return _merge(
        {"welder_id": welder_id, "filler_lot": "FL-2291"},
        overrides,
    )


def repair_start_payload(defect_disposition: str = "EXCAVATE_AND_REWELD", **overrides) -> Json:
    return _merge({"defect_disposition": defect_disposition}, overrides)


# --- Examination reports ----------------------------------------------
def nde_report_payload(
    weld_seam_id: str,
    window_start_utc: str,
    window_end_utc: str,
    method: str = NDE_METHOD_RT,
    coverage_pct: float = 100.0,
    **overrides,
) -> Json:
    return _merge(
        {
            "weld_seam_id": weld_seam_id,
            "method": method,
            "window_start_utc": window_start_utc,
            "window_end_utc": window_end_utc,
            "coverage_pct": float(coverage_pct),
            "technician_stamp": "RT-TECH-11",
        },
        overrides,
    )


def nde_result_payload(
    decision: str,
    indication_count: int,
    film_count: int = 6,
    defect_type: Optional[str] = None,
    **overrides,
) -> Json:
    payload: Json = {
        "decision": decision,
        "indication_count": int(indication_count),
        "film_count": int(film_count),
    }
    if defect_type is not None:
        payload["defect_type"] = defect_type
    return _merge(payload, overrides)


def nde_void_payload(void_reason: str = "Film set mislabelled at the darkroom", **overrides) -> Json:
    return _merge({"void_reason": void_reason}, overrides)


# --- Water sources and plans -------------------------------------------
def water_source_payload(source_name: str = "Ashley River Intake", **overrides) -> Json:
    """2,000,000 gal permit at 900 gpm, water 3.33 and disposal 2.10 per kgal."""
    return _merge(
        {
            "source_name": source_name,
            "source_type": SOURCE_MUNICIPAL,
            "permitted_volume_gal": 2000000.0,
            "max_concurrent_rate_gpm": 900.0,
            "water_cost_usd_per_kgal": 3.33,
            "disposal_cost_usd_per_kgal": 2.10,
            "permit_expiry_utc": "2027-06-30T00:00:00Z",
        },
        overrides,
    )


def hydrotest_plan_payload(
    tank_id: str,
    water_source_id: str,
    expected_tank_version: int,
    fill_volume_gal: float = 400000.0,
    **overrides,
) -> Json:
    return _merge(
        {
            "tank_id": tank_id,
            "water_source_id": water_source_id,
            "fill_volume_gal": float(fill_volume_gal),
            "disposal_method": DISPOSAL_DISCHARGE_TO_POTW,
            "hold_hours": 24,
            "expected_tank_version": int(expected_tank_version),
        },
        overrides,
    )


def plan_approval_payload(decision=APPROVE, **overrides) -> Json:
    return _merge({"decision": decision}, overrides)


def withdrawal_payload(
    hydrotest_plan_id: str,
    water_source_id: str,
    window_start_utc: str,
    window_end_utc: str,
    rate_gpm: float,
    reserved_volume_gal: float,
    expected_water_source_version: int,
    **overrides,
) -> Json:
    return _merge(
        {
            "hydrotest_plan_id": hydrotest_plan_id,
            "water_source_id": water_source_id,
            "window_start_utc": window_start_utc,
            "window_end_utc": window_end_utc,
            "rate_gpm": float(rate_gpm),
            "reserved_volume_gal": float(reserved_volume_gal),
            "expected_water_source_version": int(expected_water_source_version),
        },
        overrides,
    )


def withdrawal_cancellation_payload(
    cancellation_reason: str = "Intake pump taken out of service", **overrides
) -> Json:
    return _merge({"cancellation_reason": cancellation_reason}, overrides)


def fill_advance_payload(
    target_fill_percent: float, settlement_survey_id: Optional[str] = None, **overrides
) -> Json:
    payload: Json = {"target_fill_percent": float(target_fill_percent)}
    if settlement_survey_id is not None:
        payload["settlement_survey_id"] = settlement_survey_id
    return _merge(payload, overrides)


def plan_completion_payload(decision: str, **overrides) -> Json:
    return _merge({"decision": decision}, overrides)


# --- Coating -----------------------------------------------------------
def coating_application_payload(
    tank_id: str, scope: str = SCOPE_INTERNAL_LINING, **overrides
) -> Json:
    return _merge(
        {
            "tank_id": tank_id,
            "scope": scope,
            "surface_area_sqft": 12500.0,
            "specified_prep_standard": PREP_SSPC_SP6,
            "specified_min_dft_mils": 10.0,
            "dft_acceptance_method": DFT_SPOT_AVERAGE_80_120,
            "coating_system": "Two-coat epoxy / polyurethane",
        },
        overrides,
    )


def surface_prep_payload(
    achieved_prep_standard: str = PREP_SSPC_SP6,
    profile_mils: float = 2.5,
    dew_point_spread_f: float = 12.0,
    **overrides,
) -> Json:
    return _merge(
        {
            "achieved_prep_standard": achieved_prep_standard,
            "profile_mils": float(profile_mils),
            "dew_point_spread_f": float(dew_point_spread_f),
        },
        overrides,
    )


def dft_readings_payload(spot_readings: List[List[float]], **overrides) -> Json:
    return _merge(
        {"spot_readings": [[float(v) for v in spot] for spot in spot_readings]},
        overrides,
    )


def holiday_test_payload(holidays_found: int, test_voltage_v: float, **overrides) -> Json:
    return _merge(
        {
            "holidays_found": int(holidays_found),
            "test_voltage_v": float(test_voltage_v),
        },
        overrides,
    )


# --- Appurtenances -----------------------------------------------------
def appurtenance_payload(
    tank_id: str,
    host_shell_course_id: str,
    appurtenance_type: str = APP_NOZZLE,
    nominal_size_in: float = 6.0,
    azimuth_deg: float = 0.0,
    **overrides,
) -> Json:
    return _merge(
        {
            "tank_id": tank_id,
            "host_shell_course_id": host_shell_course_id,
            "appurtenance_type": appurtenance_type,
            "nominal_size_in": float(nominal_size_in),
            "elevation_ft": 4.0,
            "azimuth_deg": float(azimuth_deg),
        },
        overrides,
    )


def installation_payload(installed_at_utc: Optional[str] = None, **overrides) -> Json:
    payload: Json = {}
    if installed_at_utc is not None:
        payload["installed_at_utc"] = installed_at_utc
    return _merge(payload, overrides)


# --- Commissioning -----------------------------------------------------
def commissioning_package_payload(tank_id: str, **overrides) -> Json:
    return _merge({"tank_id": tank_id}, overrides)


def document_payload(
    document_type: str = DOC_MILL_TEST_REPORTS, reference_number: str = "DOC-0001", **overrides
) -> Json:
    return _merge(
        {"document_type": document_type, "reference_number": reference_number},
        overrides,
    )


def submission_payload(**overrides) -> Json:
    return _merge({}, overrides)


def review_payload(decision=REVIEW_ACCEPT, **overrides) -> Json:
    return _merge({"decision": decision}, overrides)
