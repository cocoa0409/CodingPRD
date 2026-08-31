"""Payload factories -- input fields only, one per resource the PRD creates."""
from typing import Dict, List, Optional

# --- Reusable menu catalogue -------------------------------------------------
# Each entry is a complete POST /nutrition/menu-items payload.
MENU_ITEM_SPECS: Dict[str, dict] = {
    "SOU-BRO": {
        "item_code": "SOU-BRO",
        "display_name": "Clear Broth",
        "sodium_mg": 760,
        "potassium_mg": 180,
        "carb_g": 3.0,
        "protein_g": 4.0,
        "unit_cost_cents": 135,
        "texture_level": "LIQUIDISED",
        "service_temp_class": "HOT",
        "liquid_level": "THIN",
    },
    "SID-RIC": {
        "item_code": "SID-RIC",
        "display_name": "Steamed Rice",
        "sodium_mg": 5,
        "potassium_mg": 55,
        "carb_g": 28.0,
        "protein_g": 2.5,
        "unit_cost_cents": 65,
        "texture_level": "REGULAR",
        "service_temp_class": "HOT",
    },
    "SUP-ORS": {
        "item_code": "SUP-ORS",
        "display_name": "Oral Supplement",
        "sodium_mg": 200,
        "potassium_mg": 300,
        "carb_g": 30.0,
        "protein_g": 16.0,
        "unit_cost_cents": 260,
        "texture_level": "LIQUIDISED",
        "service_temp_class": "COLD",
        "liquid_level": "MILDLY_THICK",
        "allergen_codes": ["MILK"],
    },
    "DES-PUD": {
        "item_code": "DES-PUD",
        "display_name": "Vanilla Pudding",
        "sodium_mg": 150,
        "potassium_mg": 210,
        "carb_g": 22.0,
        "protein_g": 3.0,
        "unit_cost_cents": 110,
        "texture_level": "PUREED",
        "service_temp_class": "COLD",
        "allergen_codes": ["MILK"],
    },
    "ENT-CHK": {
        "item_code": "ENT-CHK",
        "display_name": "Roast Chicken",
        "sodium_mg": 480,
        "potassium_mg": 320,
        "carb_g": 12.0,
        "protein_g": 28.0,
        "unit_cost_cents": 340,
        "texture_level": "REGULAR",
        "service_temp_class": "HOT",
    },
    "SID-PNB": {
        "item_code": "SID-PNB",
        "display_name": "Peanut Butter Cup",
        "sodium_mg": 90,
        "potassium_mg": 200,
        "carb_g": 6.0,
        "protein_g": 7.0,
        "unit_cost_cents": 95,
        "texture_level": "REGULAR",
        "service_temp_class": "AMBIENT",
        "allergen_codes": ["PEANUT"],
        "tag_codes": ["HIGH_FAT"],
    },
}

# --- Reusable therapeutic diet rules ----------------------------------------
DIET_RULE_SPECS: Dict[str, dict] = {
    "REGULAR_STD": {
        "diet_code": "REGULAR_STD",
        "display_name": "Regular",
        "precedence_rank": 90,
        "requires_dietitian_cosign": True,
    },
    "RENAL_2G_NA": {
        "diet_code": "RENAL_2G_NA",
        "display_name": "Renal 2g Sodium",
        "precedence_rank": 10,
        "requires_dietitian_cosign": True,
        "max_sodium_mg_per_meal": 700,
        "max_potassium_mg_per_meal": 600,
        "forbidden_tag_codes": ["HIGH_FAT"],
    },
    "CARB_MOD": {
        "diet_code": "CARB_MOD",
        "display_name": "Carbohydrate Modified",
        "precedence_rank": 20,
        "requires_dietitian_cosign": False,
        "max_sodium_mg_per_meal": 1200,
        "max_carb_g_per_meal": 45.0,
    },
}


def create_ward_payload(**overrides) -> dict:
    payload = {
        "name": "Ward 5 East",
        "code": "W5E",
        "tray_line_capacity_per_window": 20,
        "delivery_lead_minutes": 20,
    }
    payload.update(overrides)
    return payload


def create_patient_payload(ward_id: str, **overrides) -> dict:
    payload = {
        "ward_id": ward_id,
        "mrn": "MRN-1001",
        "full_name": "Ada Kern",
        "age_years": 71,
    }
    payload.update(overrides)
    return payload


def create_diet_rule_payload(spec_key: str = "REGULAR_STD", **overrides) -> dict:
    payload = dict(DIET_RULE_SPECS[spec_key])
    payload.update(overrides)
    return payload


def create_menu_item_payload(spec_key: str = "SOU-BRO", **overrides) -> dict:
    payload = dict(MENU_ITEM_SPECS[spec_key])
    payload.update(overrides)
    return payload


def create_diet_order_payload(patient_id: str, primary_diet_rule_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "primary_diet_rule_id": primary_diet_rule_id,
    }
    payload.update(overrides)
    return payload


def create_meal_period_payload(ward_id: str, **overrides) -> dict:
    payload = {
        "ward_id": ward_id,
        "period_code": "LUNCH",
        "service_date": "2026-08-02",
        "order_cutoff_at": "2026-08-02T10:30:00Z",
        "window_start_at": "2026-08-02T11:30:00Z",
        "window_end_at": "2026-08-02T13:00:00Z",
        "production_capacity_trays": 20,
    }
    payload.update(overrides)
    return payload


DINNER_PERIOD_DEFAULTS = {
    "period_code": "DINNER",
    "service_date": "2026-08-02",
    "order_cutoff_at": "2026-08-02T16:30:00Z",
    "window_start_at": "2026-08-02T17:30:00Z",
    "window_end_at": "2026-08-02T19:00:00Z",
    "production_capacity_trays": 20,
}


def create_dinner_period_payload(ward_id: str, **overrides) -> dict:
    payload = {"ward_id": ward_id}
    payload.update(DINNER_PERIOD_DEFAULTS)
    payload.update(overrides)
    return payload


def create_meal_order_payload(
    patient_id: str,
    meal_period_id: str,
    diet_order_id: str,
    expected_diet_order_version: int,
    lines: List[dict],
    **overrides,
) -> dict:
    payload = {
        "patient_id": patient_id,
        "meal_period_id": meal_period_id,
        "diet_order_id": diet_order_id,
        "expected_diet_order_version": expected_diet_order_version,
        "lines": lines,
    }
    payload.update(overrides)
    return payload


def line(menu_item_id: str, quantity: int = 1) -> dict:
    """One entry of the meal order `lines` array."""
    return {"menu_item_id": menu_item_id, "quantity": quantity}


def create_procedure_hold_payload(patient_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "procedure_code": "ENDO-01",
        "npo_kind": "NPO_STRICT",
        "hold_start_at": "2026-08-02T08:00:00Z",
        "hold_end_at": "2026-08-02T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_consult_payload(patient_id: str, **overrides) -> dict:
    payload = {"patient_id": patient_id, "reason_code": "POOR_INTAKE"}
    payload.update(overrides)
    return payload


def assess_consult_payload(
    assessment_variant: str = "SCREENING",
    weight_loss_pct: float = 8.0,
    intake_pct: float = 60.0,
    bmi: float = 17.0,
    albumin_g_dl: Optional[float] = None,
    recommended_supplement_item_id: Optional[str] = None,
    **overrides,
) -> dict:
    payload = {
        "assessment_variant": assessment_variant,
        "weight_loss_pct": weight_loss_pct,
        "intake_pct": intake_pct,
        "bmi": bmi,
    }
    if albumin_g_dl is not None:
        payload["albumin_g_dl"] = albumin_g_dl
    if recommended_supplement_item_id is not None:
        payload["recommended_supplement_item_id"] = recommended_supplement_item_id
    payload.update(overrides)
    return payload


def create_supplement_order_payload(
    consult_id: str, menu_item_id: str, expected_consult_version: int, doses_per_day: int = 2, **overrides
) -> dict:
    payload = {
        "consult_id": consult_id,
        "menu_item_id": menu_item_id,
        "doses_per_day": doses_per_day,
        "expected_consult_version": expected_consult_version,
    }
    payload.update(overrides)
    return payload


def create_survey_payload(
    meal_order_id: str,
    taste_score: int = 4,
    temperature_score: int = 4,
    accuracy_score: int = 4,
    **overrides,
) -> dict:
    payload = {
        "meal_order_id": meal_order_id,
        "taste_score": taste_score,
        "temperature_score": temperature_score,
        "accuracy_score": accuracy_score,
    }
    payload.update(overrides)
    return payload
