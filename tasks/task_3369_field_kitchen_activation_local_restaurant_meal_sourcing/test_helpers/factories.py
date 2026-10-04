"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS as D


def create_incident_payload(**overrides) -> dict:
    payload = {
        "name": D["INCIDENT_NAME"],
        "country_code": D["COUNTRY_CODE"],
        "disaster_type": D["DISASTER_TYPE"],
        "severity_level": D["SEVERITY_LEVEL"],
        "target_daily_meals": D["TARGET_DAILY_MEALS"],
        "funding_ceiling_cents": D["FUNDING_CEILING_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_assessment_payload(incident_id: str, **overrides) -> dict:
    payload = {
        "incident_id": incident_id,
        "assessed_at": D["ASSESSED_AT"],
        "population_affected": D["POPULATION_AFFECTED"],
        "estimated_daily_meal_need": D["ESTIMATED_DAILY_MEAL_NEED"],
        "access_constraint": D["ACCESS_CONSTRAINT"],
        "water_available": D["WATER_AVAILABLE"],
        "power_available": D["POWER_AVAILABLE"],
        "partner_kitchens_identified": D["PARTNER_KITCHENS_IDENTIFIED"],
    }
    payload.update(overrides)
    return payload


def create_field_kitchen_payload(incident_id: str, assessment_id: str, **overrides) -> dict:
    payload = {
        "incident_id": incident_id,
        "assessment_id": assessment_id,
        "site_name": D["SITE_NAME"],
        "latitude": D["LATITUDE"],
        "longitude": D["LONGITUDE"],
        "power_source": D["POWER_SOURCE"],
        "water_source": D["WATER_SOURCE"],
        "refrigeration_hours_available": D["REFRIGERATION_HOURS"],
        "daily_capacity_meals": D["DAILY_CAPACITY_MEALS"],
    }
    payload.update(overrides)
    return payload


def inspection_payload(**overrides) -> dict:
    payload = {
        "power_source": D["POWER_SOURCE"],
        "water_source": D["WATER_SOURCE"],
        "refrigeration_hours_available": D["REFRIGERATION_HOURS"],
        "daily_capacity_meals": D["DAILY_CAPACITY_MEALS"],
    }
    payload.update(overrides)
    return payload


def create_partner_kitchen_payload(incident_id: str, **overrides) -> dict:
    payload = {
        "incident_id": incident_id,
        "business_name": D["BUSINESS_NAME"],
        "owner_name": D["OWNER_NAME"],
        "cuisine_tags": ["LOCAL"],
        "daily_capacity_meals": D["PARTNER_DAILY_CAPACITY_MEALS"],
        "per_meal_price_cents": D["PER_MEAL_PRICE_CENTS"],
        "bank_verified": True,
    }
    payload.update(overrides)
    return payload


def create_meal_order_payload(incident_id: str, partner_kitchen_id: str,
                              expected_partner_kitchen_version: int, **overrides) -> dict:
    payload = {
        "incident_id": incident_id,
        "partner_kitchen_id": partner_kitchen_id,
        "menu_name": D["MENU_NAME"],
        "dietary_tags": ["VEGETARIAN"],
        "ordered_meals": D["ORDERED_MEALS"],
        "scheduled_start": D["SCHEDULED_START"],
        "production_hours": D["PRODUCTION_HOURS"],
        "expected_partner_kitchen_version": expected_partner_kitchen_version,
    }
    payload.update(overrides)
    return payload


def create_supplier_payload(incident_id: str, **overrides) -> dict:
    payload = {
        "incident_id": incident_id,
        "producer_name": D["PRODUCER_NAME"],
        "locality": D["LOCALITY"],
        "product_categories": ["PRODUCE"],
        "payment_terms_days": 7,
    }
    payload.update(overrides)
    return payload


def create_ingredient_purchase_payload(incident_id: str, supplier_id: str,
                                       partner_kitchen_id: str, **overrides) -> dict:
    payload = {
        "incident_id": incident_id,
        "supplier_id": supplier_id,
        "partner_kitchen_id": partner_kitchen_id,
        "item_description": "maize flour",
        "quantity_kg": 1000,
        "unit_price_cents_per_kg": 300,
    }
    payload.update(overrides)
    return payload


def create_distribution_site_payload(incident_id: str, **overrides) -> dict:
    payload = {
        "incident_id": incident_id,
        "site_name": "Oak Shelter",
        "site_type": "SHELTER",
        "population_served": 300,
        "daily_meal_request": 600,
        "access_constraint": "OPEN",
    }
    payload.update(overrides)
    return payload


def create_distribution_run_payload(incident_id: str, field_kitchen_id: str,
                                    **overrides) -> dict:
    payload = {
        "incident_id": incident_id,
        "field_kitchen_id": field_kitchen_id,
        "driver_name": D["DRIVER_NAME"],
        "driver_phone": D["DRIVER_PHONE"],
        "driver_safety_training_completed": True,
        "vehicle_type": "VAN",
        "planned_date": D["PLANNED_DATE"],
        "window_start": D["WINDOW_START"],
        "window_end": D["WINDOW_END"],
        "fuel_cost_cents": D["FUEL_COST_CENTS"],
        "handling_cost_cents": D["HANDLING_COST_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_distribution_stop_payload(run_id: str, site_id: str, stop_sequence: int,
                                     planned_meals: int,
                                     expected_distribution_run_version: int,
                                     **overrides) -> dict:
    payload = {
        "distribution_run_id": run_id,
        "distribution_site_id": site_id,
        "stop_sequence": stop_sequence,
        "planned_meals": planned_meals,
        "expected_distribution_run_version": expected_distribution_run_version,
    }
    payload.update(overrides)
    return payload


def create_donor_commitment_payload(incident_id: str, **overrides) -> dict:
    payload = {
        "incident_id": incident_id,
        "donor_name": D["DONOR_NAME"],
        "amount_cents": 1_000_000,
        "earmark": "UNRESTRICTED",
    }
    payload.update(overrides)
    return payload
