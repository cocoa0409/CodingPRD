"""Entity assertions and domain invariant checkers (PRD §2.5, §2.6, §3).

Field presence/type checks follow the PRD: primary resources carry id,
created_at, updated_at and version; the three append-only resources
(MaintenanceRecord, TelematicsSnapshot, InUseComplianceResult) carry only
id and created_at — updated_at and version are absent entirely (PRD §2.5).
"""
from decimal import Decimal, ROUND_HALF_UP

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ---------------------------------------------------------------------------
# low-level field helpers
# ---------------------------------------------------------------------------
def _assert_common_fields(data: dict):
    """Primary-resource common properties (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and not isinstance(data.get("version"), bool), (
        "version must be an integer"
    )


def _assert_append_only_fields(data: dict):
    """Append-only records carry only id + created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _assert_int(data: dict, field: str):
    assert isinstance(data.get(field), int) and not isinstance(data.get(field), bool), (
        f"{field} must be an integer, got {data.get(field)!r}"
    )


def _assert_number(data: dict, field: str):
    assert _is_number(data.get(field)), f"{field} must be a number, got {data.get(field)!r}"


def _assert_str(data: dict, field: str):
    assert isinstance(data.get(field), str) and len(data[field]) > 0, (
        f"{field} must be a non-empty string, got {data.get(field)!r}"
    )


def _assert_bool(data: dict, field: str):
    assert isinstance(data.get(field), bool), f"{field} must be a boolean, got {data.get(field)!r}"


def _assert_optional_str(data: dict, field: str):
    assert field in data, f"{field} must be present (may be null)"
    assert data[field] is None or isinstance(data[field], str), (
        f"{field} must be null or a string, got {data.get(field)!r}"
    )


def _assert_optional_number(data: dict, field: str):
    assert field in data, f"{field} must be present (may be null)"
    assert data[field] is None or _is_number(data[field]), (
        f"{field} must be null or a number, got {data.get(field)!r}"
    )


def _assert_optional_int(data: dict, field: str):
    assert field in data, f"{field} must be present (may be null)"
    assert data[field] is None or (
        isinstance(data[field], int) and not isinstance(data[field], bool)
    ), f"{field} must be null or an integer, got {data.get(field)!r}"


def _assert_optional_timestamp(data: dict, field: str):
    assert field in data, f"{field} must be present (may be null)"
    assert data[field] is None or is_iso8601_timestamp(data[field]), (
        f"{field} must be null or an ISO 8601 timestamp, got {data.get(field)!r}"
    )


def _assert_enum(data: dict, field: str, allowed):
    assert data.get(field) in allowed, f"{field} must be one of {allowed}, got {data.get(field)!r}"


# ---------------------------------------------------------------------------
# per-entity assertions
# ---------------------------------------------------------------------------
def assert_regulation_standard(data: dict):
    _assert_common_fields(data)
    _assert_str(data, "code")
    _assert_number(data, "nox_limit_g_per_bhp_hr")
    _assert_number(data, "pm_limit_g_per_bhp_hr")
    _assert_int(data, "useful_life_miles")
    _assert_int(data, "useful_life_hours")
    _assert_int(data, "useful_life_years")
    _assert_int(data, "base_warranty_years")
    _assert_int(data, "base_warranty_miles")
    _assert_int(data, "effective_model_year_first")
    _assert_int(data, "effective_model_year_last")
    _assert_optional_str(data, "successor_standard_id")
    _assert_enum(data, "status", ["DRAFT", "PUBLISHED", "SUPERSEDED"])
    _assert_optional_timestamp(data, "published_at")


def assert_engine_family(data: dict):
    _assert_common_fields(data)
    _assert_str(data, "family_code")
    _assert_int(data, "model_year")
    _assert_str(data, "regulation_standard_id")
    _assert_number(data, "displacement_liters")
    _assert_enum(data, "architecture", ["DOC_DPF_SCR", "DOC_DPF_SCR_ASC", "EGR_DOC_DPF_SCR"])
    _assert_enum(data, "certification_status", [
        "DESIGN", "TESTING", "UNDER_REVIEW", "CERTIFIED",
        "IN_PRODUCTION", "COMPLIANCE_HOLD", "PHASED_OUT",
    ])
    _assert_bool(data, "production_entered")
    _assert_enum(data, "in_use_compliance_status", ["NOT_TESTED", "CONFORMING", "NON_CONFORMING"])
    _assert_optional_str(data, "submitted_by_user_id")
    _assert_optional_timestamp(data, "certified_at")


def assert_aftertreatment_spec(data: dict):
    _assert_common_fields(data)
    _assert_str(data, "engine_family_id")
    _assert_int(data, "spec_version")
    _assert_str(data, "scr_catalyst_part")
    _assert_str(data, "dpf_part")
    _assert_str(data, "doser_part")
    _assert_int(data, "nox_sensor_count")
    _assert_optional_number(data, "target_def_dosing_g_per_kwh")
    _assert_optional_number(data, "last_deviation_pct")
    _assert_enum(data, "calibration_status", ["UNCALIBRATED", "CALIBRATED"])
    _assert_enum(data, "status", ["DRAFT", "ACTIVE", "SUPERSEDED"])


def assert_certification_test_run(data: dict):
    _assert_common_fields(data)
    _assert_str(data, "engine_family_id")
    _assert_enum(data, "test_type", ["FTP", "RMC", "SET", "NTE"])
    _assert_str(data, "lab_code")
    assert is_iso8601_timestamp(data.get("scheduled_start", "")), "scheduled_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("scheduled_end", "")), "scheduled_end must be ISO 8601"
    _assert_optional_number(data, "measured_nox_g_per_bhp_hr")
    _assert_optional_number(data, "measured_pm_g_per_bhp_hr")
    _assert_number(data, "deterioration_factor")
    _assert_optional_number(data, "adjusted_nox_g_per_bhp_hr")
    _assert_optional_number(data, "adjusted_pm_g_per_bhp_hr")
    _assert_enum(data, "result", ["UNRECORDED", "PASS", "FAIL"])
    _assert_enum(data, "status", ["SCHEDULED", "COMPLETED", "ACCEPTED", "REJECTED", "INVALIDATED"])
    _assert_optional_str(data, "reviewed_by_user_id")
    _assert_optional_str(data, "invalidated_reason")


def assert_fleet(data: dict):
    _assert_common_fields(data)
    _assert_str(data, "name")
    _assert_str(data, "fleet_code")
    _assert_str(data, "notification_contact")
    _assert_enum(data, "status", ["ACTIVE", "SUSPENDED"])
    _assert_int(data, "neglect_denial_count")


def assert_engine_unit(data: dict):
    _assert_common_fields(data)
    _assert_str(data, "engine_family_id")
    _assert_str(data, "fleet_id")
    _assert_str(data, "serial_number")
    _assert_int(data, "model_year")
    assert is_iso8601_timestamp(data.get("in_service_date", "")), "in_service_date must be ISO 8601"
    _assert_int(data, "accumulated_miles")
    _assert_int(data, "accumulated_hours")
    _assert_enum(data, "lifecycle", ["IN_SERVICE", "DECOMMISSIONED"])
    _assert_enum(data, "campaign_compliance", ["CLEAR", "CAMPAIGN_OPEN", "REMEDIED"])
    _assert_bool(data, "predictive_service_due")
    _assert_optional_timestamp(data, "last_snapshot_at")


def assert_maintenance_record(data: dict):
    _assert_append_only_fields(data)
    _assert_str(data, "engine_unit_id")
    assert is_iso8601_timestamp(data.get("performed_at", "")), "performed_at must be ISO 8601"
    _assert_enum(data, "maintenance_type", [
        "OIL_CHANGE", "DPF_CLEAN", "DEF_SERVICE", "VALVE_ADJUST", "SENSOR_REPLACE",
    ])
    _assert_int(data, "odometer_at_service")
    _assert_bool(data, "def_quality_ok")


def assert_telematics_snapshot(data: dict):
    _assert_append_only_fields(data)
    _assert_str(data, "engine_unit_id")
    assert is_iso8601_timestamp(data.get("recorded_at", "")), "recorded_at must be ISO 8601"
    _assert_int(data, "odometer_miles")
    _assert_int(data, "engine_hours")
    assert isinstance(data.get("fault_codes"), list), "fault_codes must be a list"
    for entry in data["fault_codes"]:
        assert isinstance(entry, dict), "each fault_codes entry must be an object"
        _assert_str(entry, "code")
        _assert_enum(entry, "severity", ["CRITICAL", "MAJOR", "MINOR"])
    _assert_number(data, "def_consumption_gal")
    _assert_number(data, "nox_sensor_drift_ppm")
    _assert_int(data, "fault_risk_score")


def assert_service_center(data: dict):
    _assert_common_fields(data)
    _assert_str(data, "name")
    _assert_str(data, "region")
    _assert_enum(data, "authorization_tier", ["BASIC", "CERTIFIED", "MASTER"])
    _assert_enum(data, "auth_status", ["APPLIED", "AUDITED", "AUTHORIZED", "SUSPENDED", "REVOKED"])
    _assert_int(data, "bay_capacity_per_day")
    _assert_int(data, "core_credit_balance_cents")
    _assert_int(data, "core_reversal_count")


def assert_technician(data: dict):
    _assert_common_fields(data)
    _assert_str(data, "service_center_id")
    _assert_str(data, "full_name")
    _assert_str(data, "badge_id")
    _assert_enum(data, "certification_level", ["LEVEL_1", "LEVEL_2", "LEVEL_3"])
    _assert_bool(data, "emissions_endorsed")
    assert is_iso8601_timestamp(data.get("certified_at", "")), "certified_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("certification_expires_at", "")), (
        "certification_expires_at must be ISO 8601"
    )
    _assert_enum(data, "cert_status", ["CERT_ACTIVE", "EXPIRED"])


def assert_diagnostic_tool(data: dict):
    _assert_common_fields(data)
    _assert_str(data, "service_center_id")
    _assert_str(data, "tool_serial")
    _assert_str(data, "software_version")
    assert is_iso8601_timestamp(data.get("issued_at", "")), "issued_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("calibration_valid_until", "")), (
        "calibration_valid_until must be ISO 8601"
    )
    _assert_enum(data, "tool_status", ["CALIBRATED_ACTIVE", "RECAL_DUE"])


def assert_in_use_compliance_result(data: dict):
    _assert_append_only_fields(data)
    _assert_str(data, "engine_family_id")
    _assert_str(data, "test_period_label")
    _assert_int(data, "sample_size")
    _assert_int(data, "passing_units")
    _assert_number(data, "conformity_ratio")
    _assert_enum(data, "outcome", ["CONFORMING", "NON_CONFORMING"])
    assert is_iso8601_timestamp(data.get("recorded_at", "")), "recorded_at must be ISO 8601"


def assert_warranty_claim(data: dict):
    _assert_common_fields(data)
    _assert_str(data, "engine_unit_id")
    _assert_str(data, "service_center_id")
    _assert_enum(data, "failed_component_class", [
        "AFTERTREATMENT_SCR", "AFTERTREATMENT_DPF", "DOSING_SYSTEM",
        "NOX_SENSOR", "EGR_SYSTEM", "ENGINE_BASE",
    ])
    _assert_str(data, "failure_code")
    _assert_int(data, "claimed_amount_cents")
    _assert_str(data, "submitted_by_role")
    _assert_str(data, "submitted_by_user_id")
    _assert_enum(data, "coverage_variant", ["EXTENDED_EMISSIONS", "BASE_WARRANTY"])
    _assert_optional_int(data, "neglect_score")
    _assert_optional_int(data, "approved_amount_cents")
    _assert_optional_int(data, "customer_share_cents")
    _assert_int(data, "review_round")
    _assert_enum(data, "status", [
        "SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED",
        "APPROVED_FULL", "APPROVED_PARTIAL", "DENIED_NEGLECT", "PAID",
    ])
    _assert_optional_str(data, "decided_by_user_id")
    _assert_optional_timestamp(data, "paid_at")


def assert_field_campaign(data: dict):
    _assert_common_fields(data)
    _assert_str(data, "engine_family_id")
    _assert_str(data, "campaign_code")
    _assert_enum(data, "campaign_type", ["RECALL", "SERVICE_CAMPAIGN"])
    _assert_str(data, "defect_summary")
    _assert_str(data, "remedy_description")
    _assert_int(data, "remedy_bay_days")
    _assert_number(data, "completion_threshold")
    _assert_int(data, "notified_unit_count")
    _assert_int(data, "verified_unit_count")
    _assert_number(data, "completion_rate")
    _assert_enum(data, "status", ["DRAFT", "ANNOUNCED", "IN_PROGRESS", "COMPLETION_REVIEW", "CLOSED"])
    _assert_optional_timestamp(data, "announced_at")


def assert_campaign_work_order(data: dict):
    _assert_common_fields(data)
    _assert_str(data, "campaign_id")
    _assert_str(data, "engine_unit_id")
    _assert_str(data, "service_center_id")
    _assert_str(data, "assigned_technician_id")
    assert is_iso8601_timestamp(data.get("scheduled_start_day", "")), (
        "scheduled_start_day must be ISO 8601"
    )
    _assert_int(data, "bay_days")
    _assert_enum(data, "status", ["SCHEDULED", "IN_BAY", "COMPLETED", "VERIFIED", "CANCELLED"])
    _assert_optional_timestamp(data, "completed_at")
    _assert_optional_timestamp(data, "verified_at")


def assert_reman_order(data: dict):
    _assert_common_fields(data)
    _assert_str(data, "engine_unit_id")
    _assert_str(data, "service_center_id")
    _assert_enum(data, "reman_scope", ["ENGINE", "COMPONENT"])
    _assert_optional_str(data, "component_type")
    _assert_enum(data, "spec_level", ["STANDARD", "PLUS", "PREMIUM"])
    _assert_int(data, "quoted_price_cents")
    _assert_int(data, "quoted_core_value_cents")
    assert is_iso8601_timestamp(data.get("expected_core_return_by", "")), (
        "expected_core_return_by must be ISO 8601"
    )
    _assert_int(data, "provisional_core_credit_cents")
    _assert_enum(data, "core_grade", ["UNGRADED", "A", "B", "C", "REJECT"])
    _assert_optional_int(data, "final_core_credit_cents")
    _assert_int(data, "spec_level_surcharge_cents")
    _assert_optional_int(data, "invoice_total_cents")
    _assert_enum(data, "status", [
        "QUOTED", "AWAITING_CORE", "CORE_RECEIVED", "CREDIT_ISSUED",
        "CLOSED", "CORE_REJECTED", "CORE_FORFEIT",
    ])
    _assert_optional_timestamp(data, "core_returned_at")


def assert_coverage_read(data: dict):
    """Computed coverage read shape (PRD §3.4)."""
    _assert_bool(data, "base_covered")
    _assert_str(data, "base_coverage_end")
    _assert_bool(data, "extended_covered")
    _assert_str(data, "extended_coverage_end")
    _assert_str(data, "extended_applies_to")


# ---------------------------------------------------------------------------
# domain invariant checkers
# ---------------------------------------------------------------------------
def assert_claim_financials_balance(data: dict):
    """After any adjudication the claim's money adds up: approved + customer
    share always equals the claimed amount (PRD §3.7 decision outcomes)."""
    if data.get("status") in ("APPROVED_FULL", "APPROVED_PARTIAL", "DENIED_NEGLECT", "PAID"):
        assert data["approved_amount_cents"] + data["customer_share_cents"] == data["claimed_amount_cents"], (
            f"approved {data['approved_amount_cents']} + share {data['customer_share_cents']} "
            f"must equal claimed {data['claimed_amount_cents']}"
        )


def assert_list_sorted_by_created_at(items: list):
    """List endpoints return resources sorted by created_at ascending (PRD §2.3)."""
    stamps = [item["created_at"] for item in items]
    assert stamps == sorted(stamps), f"list not sorted by created_at ascending: {stamps}"


def assert_pagination_meta(meta: dict, expected_limit=None, expected_offset=None):
    """The meta object of a list response carries limit, offset, total_count,
    has_more (PRD §2.3)."""
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, f"pagination meta missing {field}"
    assert isinstance(meta["limit"], int) and isinstance(meta["offset"], int)
    assert isinstance(meta["total_count"], int) and meta["total_count"] >= 0
    assert isinstance(meta["has_more"], bool)
    if expected_limit is not None:
        assert meta["limit"] == expected_limit, f"limit {meta['limit']} != {expected_limit}"
    if expected_offset is not None:
        assert meta["offset"] == expected_offset, f"offset {meta['offset']} != {expected_offset}"


# ---------------------------------------------------------------------------
# domain calculators — PRD-exact formulas for expected-value computation.
# Rounding is half-up via Decimal (PRD §2.6); monetary steps yield integer
# cents; ratio/emission steps yield floats at the pinned decimal places.
# ---------------------------------------------------------------------------
from .constants import (
    CONFORMITY_RATIO_THRESHOLD,
    CORE_GRADE_PCT,
    CORE_PROVISIONAL_CREDIT_PCT,
    DEF_ZERO_MILES_THRESHOLD,
    DEF_ZERO_PENALTY_POINTS,
    DOSING_BASE_G_PER_KWH,
    DOSING_REFERENCE_DISPLACEMENT_L,
    DOSING_TOLERANCE_PCT,
    EMISSIONS_RESULT_DECIMALS,
    DOSING_TARGET_DECIMALS,
    EXTENDED_WARRANTY_MILES,
    FAULT_RISK_DRIFT_CAP,
    FAULT_RISK_DRIFT_DIVISOR,
    FAULT_RISK_SCORE_CAP,
    FAULT_WEIGHT_CRITICAL,
    FAULT_WEIGHT_MAJOR,
    FAULT_WEIGHT_MINOR,
    MAINTENANCE_INTERVAL_MILES,
    MAX_CORE_CREDIT_PCT_OF_PRICE,
    NEGLECT_BAD_DEF_POINTS,
    NEGLECT_CRITICAL_FAULT_POINTS,
    NEGLECT_MISSED_INTERVAL_POINTS,
    NEGLECT_SCORE_CAP,
    NOX_SENSOR_PPM_MAX,
    PARTIAL_CUSTOMER_SHARE_CAP_PCT,
    SPEC_LEVEL_MULTIPLIER,
)


def round_half_up(value, ndigits: int = 0):
    """Round half-up to ndigits decimal places (PRD §2.6). Returns an int when
    ndigits == 0 (whole cents), otherwise a float."""
    quant = Decimal(1).scaleb(-ndigits)
    result = Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)
    if ndigits == 0:
        return int(result)
    return float(result)


def compute_adjusted_emission(measured, deterioration_factor) -> float:
    """round_half_up(measured * deterioration_factor, 4) (PRD §3.3)."""
    return round_half_up(Decimal(str(measured)) * Decimal(str(deterioration_factor)),
                         EMISSIONS_RESULT_DECIMALS)


def expected_test_result(adjusted_nox, adjusted_pm, nox_limit, pm_limit) -> str:
    """PASS exactly when both adjusted values are at or under the limits —
    equality passes (PRD §3.3)."""
    return "PASS" if (adjusted_nox <= nox_limit and adjusted_pm <= pm_limit) else "FAIL"


def compute_conformity_ratio(passing_units: int, sample_size: int) -> float:
    """round_half_up(passing_units / sample_size, 4) (PRD §3.4)."""
    return round_half_up(Decimal(passing_units) / Decimal(sample_size),
                         EMISSIONS_RESULT_DECIMALS)


def expected_in_use_outcome(passing_units: int, sample_size: int) -> str:
    """CONFORMING when the rounded ratio is at least 0.9 — inclusive (PRD §3.4)."""
    ratio = compute_conformity_ratio(passing_units, sample_size)
    return "CONFORMING" if ratio >= CONFORMITY_RATIO_THRESHOLD else "NON_CONFORMING"


def compute_dosing_target(displacement_liters) -> float:
    """round_half_up(6.0 * displacement / 12.0, 2) (PRD §3.3)."""
    return round_half_up(
        Decimal(str(DOSING_BASE_G_PER_KWH)) * Decimal(str(displacement_liters))
        / Decimal(str(DOSING_REFERENCE_DISPLACEMENT_L)),
        DOSING_TARGET_DECIMALS,
    )


def compute_dosing_deviation(observed_def_consumption_g_per_kwh, target) -> float:
    """round_half_up(|observed - target| / target, 4) (PRD §3.3)."""
    target_d = Decimal(str(target))
    deviation = abs(Decimal(str(observed_def_consumption_g_per_kwh)) - target_d) / target_d
    return round_half_up(deviation, EMISSIONS_RESULT_DECIMALS)


def expected_calibration_status(observed_nox_ppm_avg, observed_def_consumption_g_per_kwh,
                                displacement_liters) -> str:
    """CALIBRATED exactly when the rounded deviation is <= 0.05 (inclusive) and
    the observed NOx average is <= 400 ppm (PRD §3.3)."""
    target = compute_dosing_target(displacement_liters)
    deviation = compute_dosing_deviation(observed_def_consumption_g_per_kwh, target)
    if deviation <= DOSING_TOLERANCE_PCT and observed_nox_ppm_avg <= NOX_SENSOR_PPM_MAX:
        return "CALIBRATED"
    return "UNCALIBRATED"


def compute_fault_risk_score(fault_codes, nox_sensor_drift_ppm, def_consumption_gal,
                             accumulated_miles_before, odometer_miles) -> int:
    """Weighted risk score, integer arithmetic, capped at 100 (PRD §3.5):
    fault points (CRITICAL 40 / MAJOR 20 / MINOR 5) + drift points
    (floor(|drift| / 10), capped at 30) + DEF penalty (25 when consumption is
    exactly 0 and the odometer delta exceeds 500 miles)."""
    weights = {
        "CRITICAL": FAULT_WEIGHT_CRITICAL,
        "MAJOR": FAULT_WEIGHT_MAJOR,
        "MINOR": FAULT_WEIGHT_MINOR,
    }
    fault_points = sum(weights[entry["severity"]] for entry in fault_codes)
    drift_points = min(
        FAULT_RISK_DRIFT_CAP,
        int(abs(Decimal(str(nox_sensor_drift_ppm))) // FAULT_RISK_DRIFT_DIVISOR),
    )
    def_penalty = (
        DEF_ZERO_PENALTY_POINTS
        if (def_consumption_gal == 0
            and (odometer_miles - accumulated_miles_before) > DEF_ZERO_MILES_THRESHOLD)
        else 0
    )
    return min(FAULT_RISK_SCORE_CAP, fault_points + drift_points + def_penalty)


def compute_neglect_score(accumulated_miles: int, oil_change_count: int,
                          bad_def_count: int, critical_snapshot_count: int) -> int:
    """min(100, 25 * missed_oil + 15 * bad_def + 20 * crit_snapshots) where
    missed_oil = max(0, floor(miles / 15000) - oil_changes) (PRD §3.7)."""
    missed_oil = max(0, accumulated_miles // MAINTENANCE_INTERVAL_MILES - oil_change_count)
    return min(
        NEGLECT_SCORE_CAP,
        NEGLECT_MISSED_INTERVAL_POINTS * missed_oil
        + NEGLECT_BAD_DEF_POINTS * bad_def_count
        + NEGLECT_CRITICAL_FAULT_POINTS * critical_snapshot_count,
    )


def compute_partial_proration(coverage_variant: str, claimed_amount_cents: int,
                              base_warranty_years: int = None, elapsed_days: int = None,
                              useful_life_miles: int = None,
                              accumulated_miles: int = None):
    """Pinned rounding order — round the per-unit rate first, then multiply
    (PRD §3.7). Returns (customer_share_cents, approved_amount_cents).

    TIME_BASED (BASE_WARRANTY): rate = round_half_up(claimed / (years * 365));
    raw share = rate * elapsed_days.
    MILEAGE_BASED (EXTENDED_EMISSIONS): rate = round_half_up(claimed /
    min(100000, useful_life_miles)); raw share = rate * accumulated_miles.
    Both: share capped at round_half_up(claimed * 0.5).
    """
    if coverage_variant == "EXTENDED_EMISSIONS":
        term_miles = min(EXTENDED_WARRANTY_MILES, useful_life_miles)
        per_mile_rate = round_half_up(Decimal(claimed_amount_cents) / Decimal(term_miles))
        raw_share = per_mile_rate * accumulated_miles
    else:
        term_days = base_warranty_years * 365
        daily_rate = round_half_up(Decimal(claimed_amount_cents) / Decimal(term_days))
        raw_share = daily_rate * elapsed_days
    share_cap = round_half_up(Decimal(claimed_amount_cents) * Decimal(str(PARTIAL_CUSTOMER_SHARE_CAP_PCT)))
    customer_share = min(raw_share, share_cap)
    return customer_share, claimed_amount_cents - customer_share


def compute_provisional_core_credit(quoted_core_value_cents: int) -> int:
    """round_half_up(quoted_core_value_cents * 0.6) (PRD §3.9)."""
    return round_half_up(Decimal(quoted_core_value_cents) * Decimal(str(CORE_PROVISIONAL_CREDIT_PCT)))


def compute_spec_level_surcharge(quoted_price_cents: int, spec_level: str) -> int:
    """round_half_up(quoted_price_cents * (multiplier - 1)) (PRD §3.9)."""
    multiplier = Decimal(str(SPEC_LEVEL_MULTIPLIER[spec_level]))
    return round_half_up(Decimal(quoted_price_cents) * (multiplier - 1))


def compute_effective_price(quoted_price_cents: int, spec_level: str) -> int:
    """quoted price plus the spec-level surcharge (PRD §3.9 pinned step 2)."""
    return quoted_price_cents + compute_spec_level_surcharge(quoted_price_cents, spec_level)


def compute_final_core_credit(quoted_core_value_cents: int, core_grade: str,
                              quoted_price_cents: int, spec_level: str) -> int:
    """min(round_half_up(core value * grade pct),
           round_half_up(effective price * 0.4)) — the cap is against the
    effective price INCLUDING the surcharge (PRD §3.9)."""
    grade_value = round_half_up(
        Decimal(quoted_core_value_cents) * Decimal(str(CORE_GRADE_PCT[core_grade]))
    )
    credit_cap = round_half_up(
        Decimal(compute_effective_price(quoted_price_cents, spec_level))
        * Decimal(str(MAX_CORE_CREDIT_PCT_OF_PRICE))
    )
    return min(grade_value, credit_cap)


def compute_invoice_total(quoted_price_cents: int, spec_level: str,
                          final_core_credit_cents: int) -> int:
    """effective price minus the final core credit (PRD §3.9 pinned step 4)."""
    return compute_effective_price(quoted_price_cents, spec_level) - final_core_credit_cents


def compute_completion_rate(verified_unit_count: int, notified_unit_count: int) -> float:
    """0 while notified is 0, else round_half_up(verified / notified, 4)
    (PRD §3.8)."""
    if notified_unit_count == 0:
        return 0
    return round_half_up(Decimal(verified_unit_count) / Decimal(notified_unit_count),
                         EMISSIONS_RESULT_DECIMALS)
