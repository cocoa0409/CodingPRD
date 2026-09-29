"""Request payload builders.

Every builder returns a fresh dict of the fields the contract declares, with
JSON numbers for every numeric field, full ISO-8601 instants with three
fractional digits for every instant field, and ``YYYY-MM-DD`` strings for
every calendar date. Callers override individual fields by keyword.
"""

from typing import Any, Dict, Optional

# ── Instant / date literals ───────────────────────────────────────────────────

CLOCK_DAY = "2026-08-01"
IMPREGNATION_DAY = "2026-08-03"
TEST_DAY = "2026-08-05"
FAR_FUTURE_DATE = "2026-12-01"


def instant(date: str = CLOCK_DAY, hour: int = 0, minute: int = 0) -> str:
    """A full ISO-8601 UTC instant with exactly three fractional digits."""
    return "%sT%02d:%02d:00.000Z" % (date, hour, minute)


CLOCK_START = instant(CLOCK_DAY, 0, 0)

# Default impregnation window: four hours, so 240 impregnation minutes.
IMPREGNATION_WINDOW_START = instant(IMPREGNATION_DAY, 8, 0)
IMPREGNATION_WINDOW_END = instant(IMPREGNATION_DAY, 12, 0)

# A second window on the same oven, clear of the first window's cooldown buffer.
SECOND_IMPREGNATION_WINDOW_START = instant(IMPREGNATION_DAY, 13, 0)
SECOND_IMPREGNATION_WINDOW_END = instant(IMPREGNATION_DAY, 17, 0)

# Default dynamometer window, and an instant inside it for recording.
TEST_WINDOW_START = instant(TEST_DAY, 9, 0)
TEST_WINDOW_END = instant(TEST_DAY, 11, 0)
RECORD_CLOCK = instant(TEST_DAY, 9, 30)


def second_impregnation_payload(oven_id: str, **overrides) -> Dict[str, Any]:
    """The same booking, moved clear of the first window's cooldown buffer."""
    return impregnation_payload(
        oven_id,
        impregnation_window_start=SECOND_IMPREGNATION_WINDOW_START,
        impregnation_window_end=SECOND_IMPREGNATION_WINDOW_END,
        **overrides
    )


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    for key, value in overrides.items():
        if value is None and key in payload:
            payload.pop(key)
        else:
            payload[key] = value
    return payload


# ── Reference data ────────────────────────────────────────────────────────────


def clock_payload(current_utc: str = CLOCK_START, **overrides) -> Dict[str, Any]:
    return _merge({"current_utc": current_utc}, overrides)


def regulatory_standard_payload(**overrides) -> Dict[str, Any]:
    """An EU IE3 four-pole standard covering the default design's rating."""
    return _merge(
        {
            "standard_code": "IEC_60034_30_1_EU_IE3_4P",
            "jurisdiction": "EU",
            "efficiency_class": "IE3",
            "poles": 4,
            "rated_output_kw_min": 5.5,
            "rated_output_kw_max": 11.0,
            "minimum_efficiency_pct": 89.60,
            "effective_from": "2021-07-01",
        },
        overrides,
    )


def distributor_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "name": "Northwind Motor Distribution",
            "tier": "GOLD",
            "jurisdiction": "EU",
            "stocking_program_enrolled": True,
            "committed_annual_units": 500,
            "stock_buffer_units": 10,
        },
        overrides,
    )


def curing_oven_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "oven_code": "OVEN-VPI-01",
            "max_temp_c": 180.0,
            "cooldown_buffer_minutes": 60,
            "status": "AVAILABLE",
        },
        overrides,
    )


def test_cell_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "cell_code": "DYNO-CELL-01",
            "max_concurrent_kw": 20.0,
            "status": "AVAILABLE",
        },
        overrides,
    )


# ── Motor designs ─────────────────────────────────────────────────────────────


def motor_design_payload(**overrides) -> Dict[str, Any]:
    """Baseline four-pole 7.5 kW design: M330_35A steel, cast aluminium cage."""
    return _merge(
        {
            "model_code": "WM-132M-7K5-IE3",
            "frame_size": "132M",
            "poles": 4,
            "rated_output_kw": 7.5,
            "rated_voltage_v": 400,
            "target_efficiency_class": "IE3",
            "lamination_grade": "M330_35A",
            "lamination_stack_length_mm": 180,
            "winding_copper_kg": 12.0,
            "winding_type": "LAP",
            "insulation_class": "F",
            "stator_bore_id_mm": 135.400,
            "design_air_gap_mm": 0.450,
            "air_gap_tolerance_mm": 0.050,
            "rotor_construction": "DIE_CAST_ALUMINUM",
            "rotor_bar_count": 34,
            "shaft_diameter_mm": 38.000,
            "shaft_tolerance_class": "k6",
            "bearing_spec_de": "6208-2Z",
            "bearing_spec_nde": "6206-2Z",
            "lubrication_spec": "GREASE_REGREASABLE",
            "duty_type": "S1",
            "enclosure": "IP55",
            "mounting": "B3",
        },
        overrides,
    )


def premium_motor_design_payload(**overrides) -> Dict[str, Any]:
    """Premium variant: thinner steel, more copper, brazed copper cage.

    The larger frame carries its own bore, air gap, tolerance and shaft, so a
    rotor machined for the baseline design can never satisfy this one.
    """
    return motor_design_payload(
        **_merge(
            {
                "model_code": "WM-160M-7K5-IE4",
                "frame_size": "160M",
                "target_efficiency_class": "IE4",
                "lamination_grade": "M235_35A",
                "lamination_stack_length_mm": 200,
                "winding_copper_kg": 14.5,
                "rotor_construction": "FABRICATED_COPPER",
                "rotor_bar_count": 40,
                "stator_bore_id_mm": 148.000,
                "design_air_gap_mm": 0.500,
                "air_gap_tolerance_mm": 0.060,
                "shaft_diameter_mm": 42.000,
                "bearing_spec_de": "6210-2Z",
                "bearing_spec_nde": "6208-2Z",
            },
            overrides,
        )
    )


def economy_motor_design_payload(**overrides) -> Dict[str, Any]:
    """Economy variant: coarse steel and a short stack, cast aluminium cage."""
    return motor_design_payload(
        **_merge(
            {
                "model_code": "WM-132S-7K5-IE3B",
                "frame_size": "132S",
                "lamination_grade": "M400_50A",
                "lamination_stack_length_mm": 160,
            },
            overrides,
        )
    )


def submit_review_payload(**overrides) -> Dict[str, Any]:
    return _merge({}, overrides)


def review_decision_payload(decision: str = "APPROVE", **overrides) -> Dict[str, Any]:
    return _merge(
        {"decision": decision, "review_notes": "Reviewed against the design brief."},
        overrides,
    )


def open_revision_payload(**overrides) -> Dict[str, Any]:
    return _merge({"revision_reason": "Customer requested a longer stack."}, overrides)


# ── Customer orders ───────────────────────────────────────────────────────────


def customer_order_payload(
    distributor_id: str, design_id: str, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "distributor_id": distributor_id,
            "design_id": design_id,
            "order_type": "MADE_TO_ORDER",
            "quantity": 12,
            "requested_ship_date": FAR_FUTURE_DATE,
            "jurisdiction": "EU",
        },
        overrides,
    )


def confirm_order_payload(**overrides) -> Dict[str, Any]:
    return _merge({}, overrides)


def cancel_order_payload(**overrides) -> Dict[str, Any]:
    return _merge({"cancellation_reason": "Customer withdrew the programme."}, overrides)


# ── Work orders ───────────────────────────────────────────────────────────────


def work_order_payload(
    order_id: str, design_id: str, expected_design_version: int, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "order_id": order_id,
            "design_id": design_id,
            "unit_count": 12,
            "expected_design_version": expected_design_version,
        },
        overrides,
    )


def ship_payload(**overrides) -> Dict[str, Any]:
    return _merge({}, overrides)


# ── Stator builds ─────────────────────────────────────────────────────────────


def stator_build_payload(work_order_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "work_order_id": work_order_id,
            "insulation_system": "CLASS_F_POLYESTERIMIDE",
            "slot_fill_pct": 82.00,
        },
        overrides,
    )


def impregnation_payload(oven_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "oven_id": oven_id,
            "impregnation_window_start": IMPREGNATION_WINDOW_START,
            "impregnation_window_end": IMPREGNATION_WINDOW_END,
            "varnish_process": "VPI",
            "varnish_cycles": 2,
            "cure_temp_c": 160.0,
        },
        overrides,
    )


def surge_test_payload(surge_test_kv: float = 2.40, **overrides) -> Dict[str, Any]:
    return _merge({"surge_test_kv": surge_test_kv}, overrides)


def disposition_payload(disposition: str = "ACCEPTED", **overrides) -> Dict[str, Any]:
    return _merge(
        {"disposition": disposition, "disposition_notes": "Shop-floor disposition."},
        overrides,
    )


# ── Rotor builds ──────────────────────────────────────────────────────────────


def rotor_build_payload(work_order_id: str, **overrides) -> Dict[str, Any]:
    return _merge({"work_order_id": work_order_id}, overrides)


def die_cast_cage_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {"cage_method": "DIE_CAST", "melt_temp_c": 720.0, "die_preheat_c": 300.0},
        overrides,
    )


def brazed_bar_cage_payload(bar_count: int = 40, **overrides) -> Dict[str, Any]:
    return _merge(
        {"cage_method": "BRAZED_BAR", "braze_alloy": "AgCu-45", "bar_count": bar_count},
        overrides,
    )


def machine_payload(
    measured_rotor_od_mm: float = 134.500, rotor_mass_kg: float = 18.6, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "measured_rotor_od_mm": measured_rotor_od_mm,
            "rotor_mass_kg": rotor_mass_kg,
        },
        overrides,
    )


def balance_disposition_payload(
    disposition: str = "ACCEPTED",
    balance_grade: str = "G2_5",
    initial_unbalance_g_mm: float = 480.0,
    residual_unbalance_g_mm: float = 120.0,
    **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "disposition": disposition,
            "balance_grade": balance_grade,
            "initial_unbalance_g_mm": initial_unbalance_g_mm,
            "residual_unbalance_g_mm": residual_unbalance_g_mm,
        },
        overrides,
    )


# ── Assembly records ──────────────────────────────────────────────────────────


def assembly_record_payload(
    work_order_id: str, stator_build_id: str, rotor_build_id: str, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "work_order_id": work_order_id,
            "stator_build_id": stator_build_id,
            "rotor_build_id": rotor_build_id,
            "de_bearing_lot": "LOT-DE-4417",
            "nde_bearing_lot": "LOT-NDE-4418",
            "bearing_install_method": "INDUCTION_HEAT",
            "shaft_measured_diameter_mm": 38.010,
            "grease_fill_pct": 50.00,
        },
        overrides,
    )


# ── Performance tests ─────────────────────────────────────────────────────────


def performance_test_payload(
    work_order_id: str,
    test_cell_id: str,
    expected_work_order_version: int,
    **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "work_order_id": work_order_id,
            "test_cell_id": test_cell_id,
            "window_start": TEST_WINDOW_START,
            "window_end": TEST_WINDOW_END,
            "dyno_draw_kw": 9.0,
            "test_method": "IEC_60034_2_1_SUMMATION",
            "expected_work_order_version": expected_work_order_version,
        },
        overrides,
    )


def record_results_payload(**overrides) -> Dict[str, Any]:
    """Bench measurements at a 40 degree ambient, so the correction is live."""
    return _merge(
        {
            "input_power_kw": 8.02,
            "output_power_kw": 7.5,
            "stator_loss_w": 210.0,
            "rotor_loss_w": 95.0,
            "core_loss_w": 128.0,
            "friction_windage_w": 44.0,
            "ambient_temp_c": 40.0,
        },
        overrides,
    )


# ── Nameplates ────────────────────────────────────────────────────────────────


def nameplate_payload(
    work_order_id: str, performance_test_id: str, jurisdiction: str = "EU", **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "work_order_id": work_order_id,
            "performance_test_id": performance_test_id,
            "jurisdiction": jurisdiction,
        },
        overrides,
    )


def revoke_nameplate_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {"revocation_reason": "Post-shipment audit found a stamping error."}, overrides
    )


# ── Warranty claims ───────────────────────────────────────────────────────────


def warranty_claim_payload(
    work_order_id: str, distributor_id: str, **overrides
) -> Dict[str, Any]:
    """Application data whose four sub-scores sit either side of the threshold."""
    return _merge(
        {
            "work_order_id": work_order_id,
            "distributor_id": distributor_id,
            "failure_mode": "WINDING_SHORT",
            "operating_hours": 4200,
            "measured_load_pct": 124.0,
            "measured_ambient_c": 55.0,
            "measured_voltage_unbalance_pct": 2.8,
            "measured_starts_per_hour": 10,
            "claimed_parts_cents": 200000,
            "claimed_labor_cents": 60000,
            "claimed_freight_cents": 20000,
        },
        overrides,
    )


def analyze_field_data_payload(**overrides) -> Dict[str, Any]:
    return _merge({"analysis_basis": "FIELD_DATA"}, overrides)


def analyze_teardown_payload(
    teardown_defect_evidence_pct: float = 90.0, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "analysis_basis": "TEARDOWN",
            "teardown_defect_evidence_pct": teardown_defect_evidence_pct,
        },
        overrides,
    )


def dispute_payload(**overrides) -> Dict[str, Any]:
    return _merge({"dispute_reason": "Field telemetry was misread."}, overrides)


def close_claim_payload(**overrides) -> Dict[str, Any]:
    return _merge({"closure_notes": "Settled with the distributor."}, overrides)


# ── Convenience derived payloads ──────────────────────────────────────────────


def cage_payload_for_design(design: Dict[str, Any], **overrides) -> Dict[str, Any]:
    """The cage payload the design's construction route dictates."""
    if design["rotor_construction"] == "DIE_CAST_ALUMINUM":
        return die_cast_cage_payload(**overrides)
    return brazed_bar_cage_payload(bar_count=design["rotor_bar_count"], **overrides)


def window_payload(
    start: str, end: str, prefix: str = "impregnation_window"
) -> Dict[str, Any]:
    return {"%s_start" % prefix: start, "%s_end" % prefix: end}


def shift_instant(base: str, minutes: int) -> str:
    """Move an ISO-8601 instant by whole minutes, keeping millisecond width."""
    import datetime

    fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
    moment = datetime.datetime.strptime(base, fmt) + datetime.timedelta(minutes=minutes)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (moment.microsecond // 1000)


def optional_only(**fields: Optional[Any]) -> Dict[str, Any]:
    return {key: value for key, value in fields.items() if value is not None}
