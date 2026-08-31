"""Entity assertions and domain invariant checkers for the nutrition API."""
from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

TEXTURE_LEVELS = ["REGULAR", "MINCED_MOIST", "PUREED", "LIQUIDISED"]
LIQUID_LEVELS = ["THIN", "MILDLY_THICK", "MODERATELY_THICK", "EXTREMELY_THICK"]


# --- Instant comparison ------------------------------------------------------

def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, with or without fractional seconds."""
    assert isinstance(value, str) and value, f"Expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected_iso: str, label: str = "instant") -> None:
    """Assert two ISO 8601 instants name the same moment, ignoring formatting."""
    assert actual is not None, f"{label} must not be null"
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"Expected {label} == {expected_iso}, got {actual}"
    )


# --- Common audit fields -----------------------------------------------------

def assert_common_fields(data: dict, entity_name: str = "resource") -> None:
    """id / created_at / updated_at / version, per PRD 2.4."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a bare UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: dict, entity_name: str = "resource") -> None:
    """id + created_at only -- no updated_at, no version (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, f"{entity_name} must not carry updated_at"
    assert "version" not in data, f"{entity_name} must not carry version"


# --- Per-entity assertions ---------------------------------------------------

def assert_ward(data: dict) -> None:
    assert_common_fields(data, "Ward")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["code"], str) and 2 <= len(data["code"]) <= 8
    assert isinstance(data["tray_line_capacity_per_window"], int)
    assert data["tray_line_capacity_per_window"] >= 1
    assert isinstance(data["delivery_lead_minutes"], int)
    assert data["delivery_lead_minutes"] >= 0
    assert isinstance(data["temperature_probe_required"], bool)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["active_patient_census"], int)
    assert data["active_patient_census"] >= 0


def assert_patient(data: dict) -> None:
    assert_common_fields(data, "Patient")
    assert is_valid_uuid(data["ward_id"])
    assert isinstance(data["mrn"], str) and data["mrn"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["age_years"], int) and 0 <= data["age_years"] <= 120
    assert isinstance(data["allergen_codes"], list)
    assert data["texture_level"] in TEXTURE_LEVELS
    assert data["liquid_level"] in LIQUID_LEVELS
    assert data["status"] in ("ADMITTED", "DISCHARGED")
    assert data["npo_status"] in ("NONE", "NPO_STRICT", "NPO_CLEAR_LIQUIDS")
    assert isinstance(data["missed_meal_count"], int) and data["missed_meal_count"] >= 0
    assert data["protein_deficit_g"] >= 0
    assert isinstance(data["daily_supplement_cost_cents"], int)
    assert data["daily_supplement_cost_cents"] >= 0
    assert isinstance(data["survey_count"], int) and data["survey_count"] >= 0
    if data["survey_count"] == 0:
        assert data["satisfaction_score_avg"] is None, (
            "satisfaction_score_avg reads null while survey_count is 0"
        )


def assert_diet_rule(data: dict) -> None:
    assert_common_fields(data, "TherapeuticDietRule")
    assert isinstance(data["diet_code"], str) and data["diet_code"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["precedence_rank"], int)
    assert 1 <= data["precedence_rank"] <= 999
    assert isinstance(data["forbidden_tag_codes"], list)
    assert isinstance(data["requires_dietitian_cosign"], bool)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_diet_order(data: dict) -> None:
    assert_common_fields(data, "DietOrder")
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["primary_diet_rule_id"])
    assert data["status"] in (
        "DRAFT",
        "PENDING_COSIGN",
        "REVISION_REQUESTED",
        "ACTIVE",
        "SUPERSEDED",
        "DISCONTINUED",
    )
    assert isinstance(data["revision_round"], int) and 0 <= data["revision_round"] <= 3
    assert data["texture_level"] in TEXTURE_LEVELS
    assert data["liquid_level"] in LIQUID_LEVELS
    assert isinstance(data["linked_meal_order_count"], int)
    assert data["linked_meal_order_count"] >= 0
    assert isinstance(data["forbidden_tag_codes_effective"], list)


def assert_meal_period(data: dict) -> None:
    assert_common_fields(data, "MealPeriod")
    assert is_valid_uuid(data["ward_id"])
    assert data["period_code"] in ("BREAKFAST", "LUNCH", "DINNER", "LATE_SNACK")
    assert isinstance(data["service_date"], str) and len(data["service_date"]) == 10
    assert data["status"] in ("PLANNED", "FORECAST_LOCKED", "IN_SERVICE", "CLOSED")
    assert isinstance(data["production_capacity_trays"], int)
    assert data["production_capacity_trays"] >= 1
    assert isinstance(data["committed_tray_count"], int)
    assert isinstance(data["committed_food_cost_cents"], int)
    assert isinstance(data["delivered_tray_count"], int)
    assert isinstance(data["period_overhead_cents"], int)
    assert isinstance(data["period_bulk_discount_cents"], int)
    assert isinstance(data["period_total_cost_cents"], int)
    if data["forecast_variant"] is not None:
        assert data["forecast_variant"] in ("ROLLING_AVERAGE", "CENSUS_BASED")


def assert_menu_item(data: dict) -> None:
    assert_common_fields(data, "MenuItem")
    assert isinstance(data["item_code"], str) and data["item_code"]
    assert isinstance(data["sodium_mg"], int) and data["sodium_mg"] >= 0
    assert isinstance(data["potassium_mg"], int) and data["potassium_mg"] >= 0
    assert data["carb_g"] >= 0
    assert data["protein_g"] >= 0
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert data["texture_level"] in TEXTURE_LEVELS
    assert data["service_temp_class"] in ("HOT", "COLD", "AMBIENT")
    assert isinstance(data["allergen_codes"], list)
    assert isinstance(data["tag_codes"], list)
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_meal_order(data: dict) -> None:
    assert_common_fields(data, "MealOrder")
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["meal_period_id"])
    assert is_valid_uuid(data["diet_order_id"])
    assert data["fulfillment_status"] in (
        "PENDING_VALIDATION",
        "VALIDATED",
        "IN_PRODUCTION",
        "PLATED",
        "DELIVERED",
        "CANCELLED",
        "MISSED",
    )
    assert data["qa_status"] in (
        "NOT_CHECKED",
        "ACCURACY_PASSED",
        "ACCURACY_FAILED",
        "TEMP_PASSED",
        "TEMP_FAILED",
    )
    assert isinstance(data["revalidation_required"], bool)
    assert isinstance(data["pinned_diet_order_version"], int)
    assert isinstance(data["total_sodium_mg"], int)
    assert isinstance(data["total_potassium_mg"], int)
    assert isinstance(data["food_cost_cents"], int)
    assert isinstance(data["requires_hot_probe"], bool)
    assert isinstance(data["requires_cold_probe"], bool)
    assert isinstance(data["accuracy_retry_count"], int)
    assert isinstance(data["temperature_retry_count"], int)
    if data["fulfillment_status"] != "DELIVERED":
        assert data["delivery_window_compliance"] is None, (
            "delivery_window_compliance reads null until the tray is DELIVERED"
        )
        assert data["service_compliance_score"] is None, (
            "service_compliance_score reads null until the tray is DELIVERED"
        )
    else:
        assert data["delivery_window_compliance"] in ("EARLY", "ON_TIME", "LATE")
        assert 0 <= data["service_compliance_score"] <= 100


def assert_meal_order_line(data: dict) -> None:
    assert_common_fields(data, "MealOrderLine")
    assert is_valid_uuid(data["meal_order_id"])
    assert is_valid_uuid(data["menu_item_id"])
    assert isinstance(data["quantity"], int) and 1 <= data["quantity"] <= 10
    assert data["line_status"] in ("REQUESTED", "SUBSTITUTED")
    assert isinstance(data["line_cost_cents"], int) and data["line_cost_cents"] >= 0


def assert_procedure_hold(data: dict) -> None:
    assert_common_fields(data, "ProcedureHold")
    assert is_valid_uuid(data["patient_id"])
    assert data["npo_kind"] in ("NPO_STRICT", "NPO_CLEAR_LIQUIDS")
    assert data["status"] in ("SCHEDULED", "ACTIVE", "RELEASED", "CANCELLED")
    assert isinstance(data["buffer_before_minutes"], int)
    assert 0 <= data["buffer_before_minutes"] <= 720
    assert isinstance(data["buffer_after_minutes"], int)
    assert 0 <= data["buffer_after_minutes"] <= 720
    assert parse_instant(data["hold_start_at"]) < parse_instant(data["hold_end_at"])
    assert parse_instant(data["buffered_start_at"]) <= parse_instant(data["hold_start_at"])
    assert parse_instant(data["buffered_end_at"]) >= parse_instant(data["hold_end_at"])
    assert isinstance(data["missed_meal_order_count"], int)


def assert_consult(data: dict) -> None:
    assert_common_fields(data, "NutritionConsult")
    assert is_valid_uuid(data["patient_id"])
    assert data["acuity"] in ("ROUTINE", "URGENT")
    assert isinstance(data["reason_code"], str) and data["reason_code"]
    assert isinstance(data["requested_by_user_id"], str)
    assert data["status"] in ("REQUESTED", "ASSIGNED", "ASSESSED", "SIGNED", "CANCELLED")
    assert isinstance(data["auto_generated"], bool)
    assert isinstance(data["is_overdue"], bool)
    assert isinstance(data["linked_supplement_order_count"], int)
    assert is_iso8601_timestamp(data["due_at"])
    if data["malnutrition_risk_score"] is None:
        assert data["risk_tier"] is None, "risk_tier reads null before an assessment"
    else:
        assert 0 <= data["malnutrition_risk_score"] <= 100
        assert data["risk_tier"] in ("LOW", "MODERATE", "HIGH")


def assert_supplement_order(data: dict) -> None:
    assert_common_fields(data, "SupplementOrder")
    assert is_valid_uuid(data["consult_id"])
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["menu_item_id"])
    assert isinstance(data["doses_per_day"], int) and 1 <= data["doses_per_day"] <= 6
    assert data["status"] in ("PENDING", "ACTIVE", "CANCELLED")
    assert isinstance(data["daily_cost_cents"], int) and data["daily_cost_cents"] >= 0


def assert_satisfaction_survey(data: dict) -> None:
    assert_append_only_fields(data, "SatisfactionSurvey")
    assert is_valid_uuid(data["meal_order_id"])
    assert is_valid_uuid(data["patient_id"])
    for field in ("taste_score", "temperature_score", "accuracy_score"):
        assert isinstance(data[field], int) and 1 <= data[field] <= 5
    assert 1.0 <= data["composite_score"] <= 5.0


# --- Domain invariants -------------------------------------------------------

def assert_period_cost_rollup(data: dict) -> None:
    """The six pinned rollup steps must be internally consistent (PRD 3.5)."""
    subtotal = data["committed_food_cost_cents"]
    overhead = data["period_overhead_cents"]
    discount = data["period_bulk_discount_cents"]
    total = data["period_total_cost_cents"]
    assert total == subtotal + overhead - discount, (
        "period_total_cost_cents must equal the gross minus the bulk discount: "
        f"{subtotal} + {overhead} - {discount} != {total}"
    )
    assert overhead >= 0 and discount >= 0 and total >= 0


def assert_risk_tier_matches_score(data: dict) -> None:
    """risk_tier follows directly from malnutrition_risk_score (PRD 3.9)."""
    score = data["malnutrition_risk_score"]
    if score is None:
        assert data["risk_tier"] is None
        return
    if score < 30:
        expected = "LOW"
    elif score < 60:
        expected = "MODERATE"
    else:
        expected = "HIGH"
    assert data["risk_tier"] == expected, (
        f"Score {score} must land in tier {expected}, got {data['risk_tier']}"
    )


def approx2(value: float):
    """Comparison helper for a 2-decimal-place quantity."""
    return pytest.approx(value, abs=0.005)


def approx1(value: float):
    """Comparison helper for a 1-decimal-place quantity."""
    return pytest.approx(value, abs=0.05)
