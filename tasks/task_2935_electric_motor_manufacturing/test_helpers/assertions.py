"""Domain assertions and independent reference arithmetic.

Every derived figure the contract promises is recomputed here from the
documented rules, in exact decimal arithmetic with half-up rounding, so a
test compares the server's answer against an independently derived one
rather than against a hand-copied literal.
"""

import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from . import constants as C
from .types import (
    COMMON_FIELDS,
    COST_SUMMARY_FIELDS,
    IMMUTABLE_COMMON_FIELDS,
    PAGINATION_META_KEYS,
)


# ── Exact decimal helpers ─────────────────────────────────────────────────────


def dec(value: Any) -> Decimal:
    """Decimal for a value, reading floats through their decimal literal."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value: Any, places: int) -> Decimal:
    """Round half away from zero to the given number of decimal places."""
    exponent = Decimal(1).scaleb(-places)
    return dec(value).quantize(exponent, rounding=ROUND_HALF_UP)


def to_float(value: Decimal) -> float:
    return float(value)


def approx_equal(actual: Any, expected: Any, places: int) -> bool:
    return round_half_up(actual, places) == round_half_up(expected, places)


def assert_rounded_to(actual: Any, expected: Any, places: int, label: str) -> None:
    assert actual is not None, "%s is missing" % label
    assert approx_equal(actual, expected, places), "%s: expected %s, got %s" % (
        label,
        round_half_up(expected, places),
        actual,
    )


def assert_decimal_width(actual: Any, places: int, label: str) -> None:
    """Assert a numeric figure carries no more than ``places`` decimals."""
    assert actual is not None, "%s is missing" % label
    assert dec(actual) == round_half_up(actual, places), (
        "%s: %s carries more than %d decimal places" % (label, actual, places)
    )


# ── Envelope and common-field assertions ─────────────────────────────────────


def assert_meta_envelope(response) -> Dict[str, Any]:
    body = response.json()
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        "meta.api_request_id must be prefixed 'req_', got %r" % meta["api_request_id"]
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
        "meta.api_request_timestamp is not an ISO 8601 UTC instant: %r"
        % meta["api_request_timestamp"]
    )
    assert_three_fractional_digits(
        meta["api_request_timestamp"], "meta.api_request_timestamp"
    )
    return meta


def assert_three_fractional_digits(timestamp: str, label: str) -> None:
    assert isinstance(timestamp, str), "%s must be a string" % label
    assert timestamp.endswith("Z"), "%s must end with Z: %r" % (label, timestamp)
    assert "." in timestamp, "%s must carry fractional digits: %r" % (label, timestamp)
    fraction = timestamp.split(".")[1][:-1]
    assert len(fraction) == 3, "%s must carry exactly three fractional digits: %r" % (
        label,
        timestamp,
    )


def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None):
    for field in COMMON_FIELDS:
        assert field in row, "row is missing the system field %r" % field
    assert is_valid_uuid(row["id"]), "id is not a bare UUID: %r" % row["id"]
    assert_three_fractional_digits(row["created_at"], "created_at")
    assert_three_fractional_digits(row["updated_at"], "updated_at")
    assert isinstance(row["version"], int), "version must be an integer"
    assert row["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert row["version"] == expected_version, "expected version %d, got %d" % (
            expected_version,
            row["version"],
        )
    return row


def assert_immutable_common_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    for field in IMMUTABLE_COMMON_FIELDS:
        assert field in row, "row is missing the system field %r" % field
    assert is_valid_uuid(row["id"])
    assert_three_fractional_digits(row["created_at"], "created_at")
    assert "updated_at" not in row, "an immutable row must not carry updated_at"
    assert "version" not in row, "an immutable row must not carry version"
    return row


def assert_pagination_meta(response):
    data, meta = validate_paginated(response)
    for key in PAGINATION_META_KEYS:
        assert key in meta, "pagination meta is missing %r" % key
    return data, meta


def assert_created(response) -> Dict[str, Any]:
    assert_meta_envelope(response)
    return validate_success(response, 201)


def assert_ok(response) -> Dict[str, Any]:
    assert_meta_envelope(response)
    return validate_success(response, 200)


def assert_ascending_by(rows: Iterable[Dict[str, Any]], field: str) -> None:
    values = [row[field] for row in rows]
    assert values == sorted(values), "rows are not ascending by %s: %s" % (
        field,
        values,
    )


# ── Predicted loss model (PRD 3.2) ───────────────────────────────────────────


def expected_loss_components(design: Dict[str, Any]) -> Dict[str, Decimal]:
    output_w = dec(design["rated_output_kw"]) * 1000
    base = output_w * dec(C.BASE_LOSS_FRACTION_BY_POLES[design["poles"]])
    core = (
        base
        * dec(C.CORE_SHARE)
        * dec(C.LAMINATION_FACTOR[design["lamination_grade"]])
        * (dec(C.REFERENCE_STACK_LENGTH_MM) / dec(design["lamination_stack_length_mm"]))
    )
    copper = (
        base
        * dec(C.COPPER_SHARE)
        * dec(C.WINDING_FACTOR[design["winding_type"]])
        * (dec(C.REFERENCE_COPPER_KG) / dec(design["winding_copper_kg"]))
    )
    rotor = base * dec(C.ROTOR_SHARE) * dec(C.ROTOR_FACTOR[design["rotor_construction"]])
    friction = base * dec(C.FRICTION_SHARE)
    stray = base * dec(C.STRAY_SHARE)
    components = {
        "core_loss_w": round_half_up(core, 1),
        "copper_loss_w": round_half_up(copper, 1),
        "rotor_loss_w": round_half_up(rotor, 1),
        "friction_windage_loss_w": round_half_up(friction, 1),
        "stray_loss_w": round_half_up(stray, 1),
    }
    components["total_predicted_loss_w"] = (
        components["core_loss_w"]
        + components["copper_loss_w"]
        + components["rotor_loss_w"]
        + components["friction_windage_loss_w"]
        + components["stray_loss_w"]
    )
    return components


def expected_predicted_efficiency_pct(design: Dict[str, Any]) -> Decimal:
    output_w = dec(design["rated_output_kw"]) * 1000
    total_loss = expected_loss_components(design)["total_predicted_loss_w"]
    return round_half_up(dec(100) * output_w / (output_w + total_loss), 2)


def expected_guaranteed_efficiency_pct(design: Dict[str, Any]) -> Decimal:
    predicted = expected_predicted_efficiency_pct(design)
    shortfall = (dec(100) - predicted) * (dec(1) + dec(C.TOLERANCE_COEFFICIENT))
    return round_half_up(dec(100) - shortfall, 2)


def class_for_efficiency(efficiency_pct: Any, poles: int) -> str:
    value = dec(efficiency_pct)
    verdict = C.CLASS_BELOW_IE2
    for name in C.EFFICIENCY_CLASSES:
        if value >= dec(C.CLASS_FLOORS[name][poles]):
            verdict = name
    return verdict


def expected_design_verdicts(design: Dict[str, Any]) -> Dict[str, Any]:
    predicted = expected_predicted_efficiency_pct(design)
    guaranteed = expected_guaranteed_efficiency_pct(design)
    out = dict(expected_loss_components(design))
    out["predicted_efficiency_pct"] = predicted
    out["guaranteed_efficiency_pct"] = guaranteed
    out["design_estimate_class"] = class_for_efficiency(predicted, design["poles"])
    out["predicted_class"] = class_for_efficiency(guaranteed, design["poles"])
    return out


def assert_design_loss_model(row: Dict[str, Any], design: Dict[str, Any]) -> None:
    """Check the five figures the contract names as recomputed design outputs."""
    expected = expected_design_verdicts(design)
    assert_rounded_to(
        row["total_predicted_loss_w"],
        expected["total_predicted_loss_w"],
        1,
        "total_predicted_loss_w",
    )
    for field in ("predicted_efficiency_pct", "guaranteed_efficiency_pct"):
        assert_rounded_to(row[field], expected[field], 2, field)
    assert row["design_estimate_class"] == expected["design_estimate_class"], (
        "design_estimate_class: expected %s, got %s"
        % (expected["design_estimate_class"], row["design_estimate_class"])
    )
    assert row["predicted_class"] == expected["predicted_class"], (
        "predicted_class: expected %s, got %s"
        % (expected["predicted_class"], row["predicted_class"])
    )


# ── Lead time (PRD 3.4) ──────────────────────────────────────────────────────


def expected_lead_time_days(
    order_type: str,
    jurisdiction: str,
    tier: str,
    quantity: int,
    stock_buffer_units: int = 0,
    special_requirements: Optional[Dict[str, bool]] = None,
) -> int:
    total = C.ORDER_TYPE_BASE_DAYS[order_type]
    flags = special_requirements or {}
    for key, adder in C.SPECIAL_REQUIREMENT_ADDERS:
        if flags.get(key) is True:
            total += adder
    if order_type == "STOCK_REPLENISH" and quantity > stock_buffer_units:
        total += C.STOCK_SHORTFALL_PENALTY_DAYS
    total += C.JURISDICTION_ADDER_DAYS[jurisdiction]
    total -= C.TIER_REDUCTION_DAYS[tier]
    return max(C.LEAD_TIME_FLOOR_DAYS, total)


def add_days(iso_date: str, days: int) -> str:
    base = datetime.date.fromisoformat(iso_date)
    return (base + datetime.timedelta(days=days)).isoformat()


def add_months(iso_date: str, months: int) -> str:
    base = datetime.date.fromisoformat(iso_date)
    month_index = base.month - 1 + months
    year = base.year + month_index // 12
    month = month_index % 12 + 1
    day = min(base.day, _days_in_month(year, month))
    return datetime.date(year, month, day).isoformat()


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        nxt = datetime.date(year + 1, 1, 1)
    else:
        nxt = datetime.date(year, month + 1, 1)
    return (nxt - datetime.date(year, month, 1)).days


def service_age_months(shipped_date: str, current_date: str) -> int:
    months = 0
    while add_months(shipped_date, months + 1) <= current_date:
        months += 1
    return months


def date_of(instant: str) -> str:
    return instant.split("T")[0]


# ── Work order cost roll-up (PRD 3.5) ────────────────────────────────────────


def expected_per_unit_direct_cost_cents(design: Dict[str, Any]) -> int:
    copper = round_half_up(
        dec(design["winding_copper_kg"]) * dec(C.COPPER_RATE_CENTS_PER_KG), 0
    )
    lamination = round_half_up(
        dec(design["lamination_stack_length_mm"])
        * dec(C.LAMINATION_RATE_CENTS_PER_MM[design["lamination_grade"]]),
        0,
    )
    rotor = dec(C.ROTOR_PROCESS_COST_CENTS[design["rotor_construction"]])
    labour = dec(C.LABOUR_CENTS_PER_UNIT)
    return int(copper + lamination + rotor + labour)


def expected_overhead_band(direct_cost_cents: int) -> str:
    if direct_cost_cents >= C.OVERHEAD_BAND_ENGINEERED_MIN_CENTS:
        return "ENGINEERED"
    if direct_cost_cents >= C.OVERHEAD_BAND_COMPLEX_MIN_CENTS:
        return "COMPLEX"
    return "STANDARD"


def expected_cost_rollup(
    design: Dict[str, Any], unit_count: int, rework_reject_count: int = 0
) -> Dict[str, Any]:
    per_unit = expected_per_unit_direct_cost_cents(design)
    direct = per_unit * unit_count
    band = expected_overhead_band(direct)
    overhead = int(round_half_up(dec(direct) * dec(C.OVERHEAD_RATE[band]), 0))
    standard = direct + overhead
    actual = standard + C.REWORK_SURCHARGE_CENTS * rework_reject_count
    return {
        "unit_count": unit_count,
        "per_unit_direct_cost_cents": per_unit,
        "direct_cost_cents": direct,
        "overhead_band": band,
        "overhead_cents": overhead,
        "standard_cost_cents": standard,
        "actual_cost_cents": actual,
        "cost_variance_cents": actual - standard,
        "rework_reject_count": rework_reject_count,
        "unit_standard_cost_cents": int(round_half_up(dec(standard) / dec(unit_count), 0)),
    }


def assert_cost_rollup(
    row: Dict[str, Any],
    design: Dict[str, Any],
    unit_count: int,
    rework_reject_count: int = 0,
) -> None:
    expected = expected_cost_rollup(design, unit_count, rework_reject_count)
    for field in (
        "unit_count",
        "direct_cost_cents",
        "overhead_band",
        "overhead_cents",
        "standard_cost_cents",
        "actual_cost_cents",
        "cost_variance_cents",
        "rework_reject_count",
    ):
        assert row[field] == expected[field], "%s: expected %s, got %s" % (
            field,
            expected[field],
            row[field],
        )


def assert_cost_summary_shape(row: Dict[str, Any]) -> None:
    for field in COST_SUMMARY_FIELDS:
        assert field in row, "cost read-out is missing %r" % field


def assert_cost_summary_figures(
    row: Dict[str, Any],
    design: Dict[str, Any],
    unit_count: int,
    rework_reject_count: int = 0,
    work_order_id: str = None,
) -> None:
    """All eleven declared read-out fields, including the two derived on read."""
    assert_cost_summary_shape(row)
    expected = expected_cost_rollup(design, unit_count, rework_reject_count)
    for field in COST_SUMMARY_FIELDS:
        if field == "work_order_id":
            continue
        assert row[field] == expected[field], "%s: expected %s, got %s" % (
            field,
            expected[field],
            row[field],
        )
    if work_order_id is not None:
        assert row["work_order_id"] == work_order_id


# ── Surge envelope (PRD 3.6) ─────────────────────────────────────────────────


def expected_required_surge_kv(rated_voltage_v: int, insulation_class: str) -> Decimal:
    raw = (dec(rated_voltage_v) * 2 + dec(C.SURGE_BASE_V)) * dec(
        C.INSULATION_CLASS_FACTOR[insulation_class]
    ) / dec(1000)
    return round_half_up(raw, 2)


def expected_cycle_bonus(varnish_cycles: int) -> Decimal:
    bonus = dec(C.CYCLE_BONUS_PER_EXTRA_CYCLE) * dec(varnish_cycles - 1)
    cap = dec(C.CYCLE_BONUS_CAP)
    return bonus if bonus < cap else cap


def expected_achieved_capability_kv(
    rated_voltage_v: int,
    insulation_class: str,
    varnish_process: str,
    varnish_cycles: int,
) -> Decimal:
    required = expected_required_surge_kv(rated_voltage_v, insulation_class)
    raw = (
        required
        * dec(C.VARNISH_PROCESS_FACTOR[varnish_process])
        * (dec(1) + expected_cycle_bonus(varnish_cycles))
    )
    return round_half_up(raw, 2)


def expected_insulation_margin_kv(
    surge_test_kv: Any, rated_voltage_v: int, insulation_class: str
) -> Decimal:
    required = expected_required_surge_kv(rated_voltage_v, insulation_class)
    return round_half_up(dec(surge_test_kv) - required, 2)


def minutes_between(start: str, end: str) -> int:
    fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
    begin = datetime.datetime.strptime(start, fmt)
    finish = datetime.datetime.strptime(end, fmt)
    return int((finish - begin).total_seconds() // 60)


# ── Rotor geometry and balance (PRD 3.7) ─────────────────────────────────────


def expected_air_gap_mm(stator_bore_id_mm: Any, measured_rotor_od_mm: Any) -> Decimal:
    diametral = dec(stator_bore_id_mm) - dec(measured_rotor_od_mm)
    return round_half_up(diametral / dec(2), 3)


def expected_air_gap_deviation_mm(
    stator_bore_id_mm: Any, measured_rotor_od_mm: Any, design_air_gap_mm: Any
) -> Decimal:
    gap = expected_air_gap_mm(stator_bore_id_mm, measured_rotor_od_mm)
    return round_half_up(gap - dec(design_air_gap_mm), 3)


def rotor_od_for_deviation(
    stator_bore_id_mm: Any, design_air_gap_mm: Any, deviation_mm: Any
) -> Decimal:
    """The rotor outer diameter that produces the requested gap deviation."""
    gap = dec(design_air_gap_mm) + dec(deviation_mm)
    return round_half_up(dec(stator_bore_id_mm) - gap * dec(2), 3)


def expected_permissible_unbalance_g_mm(
    balance_grade: str, rotor_mass_kg: Any, poles: int
) -> Decimal:
    raw = (
        dec(C.ISO_BALANCE_CONSTANT)
        * dec(C.BALANCE_GRADE_VELOCITY[balance_grade])
        * dec(rotor_mass_kg)
        / dec(C.SYNCHRONOUS_RPM_BY_POLES[poles])
    )
    return round_half_up(raw, 1)


# ── Assembly metrology (PRD 3.8) ─────────────────────────────────────────────


def expected_shaft_fit_deviation_um(
    shaft_measured_diameter_mm: Any, shaft_diameter_mm: Any
) -> int:
    delta = dec(shaft_measured_diameter_mm) - dec(shaft_diameter_mm)
    return int(round_half_up(delta * dec(1000), 0))


def shaft_diameter_for_fit_um(shaft_diameter_mm: Any, fit_um: int) -> Decimal:
    return round_half_up(dec(shaft_diameter_mm) + dec(fit_um) / dec(1000), 3)


# ── Efficiency verification (PRD 3.8) ────────────────────────────────────────


def expected_stator_loss_corrected_w(stator_loss_w: Any, ambient_temp_c: Any) -> Decimal:
    ambient = dec(ambient_temp_c)
    reference = dec(C.STATOR_TEMP_REFERENCE_C)
    if ambient <= reference:
        return round_half_up(dec(stator_loss_w), 1)
    factor = dec(1) + dec(C.STATOR_TEMP_CORRECTION_PER_C) * (ambient - reference)
    return round_half_up(dec(stator_loss_w) * factor, 1)


def expected_stray_load_loss_w(input_power_kw: Any) -> Decimal:
    input_w = dec(input_power_kw) * 1000
    return round_half_up(input_w * dec(C.STRAY_LOAD_FRACTION), 1)


def expected_total_loss_w(measurements: Dict[str, Any]) -> Decimal:
    corrected = expected_stator_loss_corrected_w(
        measurements["stator_loss_w"], measurements["ambient_temp_c"]
    )
    stray = expected_stray_load_loss_w(measurements["input_power_kw"])
    return (
        corrected
        + round_half_up(measurements["rotor_loss_w"], 1)
        + round_half_up(measurements["core_loss_w"], 1)
        + round_half_up(measurements["friction_windage_w"], 1)
        + stray
    )


def expected_measured_efficiency_pct(
    measurements: Dict[str, Any], test_method: str
) -> Decimal:
    if test_method == "IEEE_112_B_DYNAMOMETER":
        return round_half_up(
            dec(100)
            * dec(measurements["output_power_kw"])
            / dec(measurements["input_power_kw"]),
            2,
        )
    input_w = dec(measurements["input_power_kw"]) * 1000
    total_loss = expected_total_loss_w(measurements)
    return round_half_up(dec(100) * (input_w - total_loss) / input_w, 2)


def assert_performance_test_figures(
    row: Dict[str, Any], measurements: Dict[str, Any], test_method: str, poles: int
) -> None:
    assert_rounded_to(
        row["stator_loss_corrected_w"],
        expected_stator_loss_corrected_w(
            measurements["stator_loss_w"], measurements["ambient_temp_c"]
        ),
        1,
        "stator_loss_corrected_w",
    )
    assert_rounded_to(
        row["stray_load_loss_w"],
        expected_stray_load_loss_w(measurements["input_power_kw"]),
        1,
        "stray_load_loss_w",
    )
    assert_rounded_to(
        row["total_loss_w"], expected_total_loss_w(measurements), 1, "total_loss_w"
    )
    efficiency = expected_measured_efficiency_pct(measurements, test_method)
    assert_rounded_to(
        row["measured_efficiency_pct"], efficiency, 2, "measured_efficiency_pct"
    )
    assert row["achieved_class"] == class_for_efficiency(efficiency, poles), (
        "achieved_class: expected %s, got %s"
        % (class_for_efficiency(efficiency, poles), row["achieved_class"])
    )


# ── Warranty adjudication (PRD 3.10) ─────────────────────────────────────────


def _clamped(numerator: Decimal, span: Decimal) -> Decimal:
    score = numerator / span
    if score < dec(0):
        return dec(0)
    if score > dec(1):
        return dec(1)
    return score


def expected_application_subscores(
    claim: Dict[str, Any], duty_type: str
) -> Dict[str, Decimal]:
    starts_reference = dec(C.STARTS_REFERENCE_BY_DUTY[duty_type])
    return {
        "overload": _clamped(
            dec(claim["measured_load_pct"]) - dec(C.OVERLOAD_REFERENCE_PCT),
            dec(C.OVERLOAD_SPAN),
        ),
        "thermal": _clamped(
            dec(claim["measured_ambient_c"]) - dec(C.THERMAL_REFERENCE_C),
            dec(C.THERMAL_SPAN),
        ),
        "voltage": _clamped(
            dec(claim["measured_voltage_unbalance_pct"]) - dec(C.VOLTAGE_REFERENCE_PCT),
            dec(C.VOLTAGE_SPAN),
        ),
        "starts": _clamped(
            dec(claim["measured_starts_per_hour"]) - starts_reference, starts_reference
        ),
    }


def expected_misuse_index(
    claim: Dict[str, Any],
    duty_type: str,
    analysis_basis: str,
    teardown_defect_evidence_pct: Optional[Any] = None,
) -> Decimal:
    scores = expected_application_subscores(claim, duty_type)
    if analysis_basis == "FIELD_DATA":
        total = sum(
            (dec(C.FIELD_DATA_WEIGHTS[key]) * scores[key] for key in scores),
            dec(0),
        )
        return round_half_up(total, 4)
    total = sum(
        (dec(C.TEARDOWN_WEIGHTS[key]) * scores[key] for key in scores), dec(0)
    )
    evidence_term = dec(1) - dec(teardown_defect_evidence_pct) / dec(100)
    total += dec(C.TEARDOWN_WEIGHTS["evidence"]) * evidence_term
    return round_half_up(total, 4)


def expected_adjudication(misuse_index: Any) -> str:
    return (
        "MISUSE_DETERMINED"
        if dec(misuse_index) >= dec(C.MISUSE_THRESHOLD)
        else "DEFECT_CONFIRMED"
    )


def expected_pro_rata_factor(service_age: int) -> Decimal:
    window = dec(C.PRO_RATA_WINDOW_MONTHS)
    capped = dec(min(service_age, C.PRO_RATA_WINDOW_MONTHS))
    factor = (window - capped) / window
    return factor if factor > dec(0) else dec(0)


def expected_warranty_credit_cents(
    claim_unit_standard_cost_cents: int,
    claimed_parts_cents: int,
    claimed_labor_cents: int,
    claimed_freight_cents: int,
    service_age_months_value: int,
) -> Dict[str, int]:
    unit_cost = dec(claim_unit_standard_cost_cents)
    ceiling = int(
        round_half_up(
            unit_cost
            * dec(C.CREDIT_CEILING_FRACTION)
            * expected_pro_rata_factor(service_age_months_value),
            0,
        )
    )
    parts_cap = int(round_half_up(unit_cost * dec(C.PARTS_CAP_FRACTION), 0))
    parts = min(claimed_parts_cents, parts_cap, ceiling)
    remaining = ceiling - parts
    labour = min(claimed_labor_cents, C.LABOUR_CAP_CENTS, remaining)
    remaining -= labour
    freight = min(claimed_freight_cents, C.FREIGHT_CAP_CENTS, remaining)
    return {
        "ceiling_cents": ceiling,
        "parts_cents": parts,
        "labor_cents": labour,
        "freight_cents": freight,
        "warranty_credit_cents": parts + labour + freight,
    }
