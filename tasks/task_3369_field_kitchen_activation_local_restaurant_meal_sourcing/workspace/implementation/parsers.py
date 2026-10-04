"""Rule-1 request-body parsing: shape, declared enum members and numeric ranges.

These run before the auth checks (PRD 2.5 puts request-shape validation first),
so a malformed body is reported even when the auth headers are also missing.
"""

import re

from errors import fail
from validations import (
    ACCESS_CONSTRAINTS, ASSESSMENT_MODES, COMMITMENT_STATES, CONTRACT_STATES,
    DIETARY_TAGS, DISASTER_TYPES, EARMARKS, FIELD_KITCHEN_STATES, INCIDENT_STATES,
    MEAL_ORDER_STATES, POWER_SOURCES, PRODUCTION_STATES, PURCHASE_STATES, RUN_STATES,
    SITE_TYPES, STOP_STATES, VEHICLE_TYPES, WATER_SOURCES,
    opt_datetime, opt_enum, opt_int, opt_str, req_bool, req_datetime, req_enum,
    req_int, req_num, req_str, req_str_list,
)

_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def parse_incident_create(body):
    data = {
        "name": req_str(body, "name"),
        "country_code": req_str(body, "country_code"),
        "disaster_type": req_enum(body, "disaster_type", DISASTER_TYPES),
        "severity_level": req_int(body, "severity_level", 1, 5),
        "target_daily_meals": req_int(body, "target_daily_meals", 1),
        "funding_ceiling_cents": req_int(body, "funding_ceiling_cents", 0),
        "currency_code": opt_str(body, "currency_code"),
        "population_dietary_requirements": req_str_list(
            body, "population_dietary_requirements", DIETARY_TAGS, default=[]),
    }
    if not _COUNTRY_RE.match(data["country_code"]):
        fail("ERR_INVALID_REQUEST", "country_code must be exactly two uppercase letters.")
    return data


def parse_assessment_create(body):
    return {
        "incident_id": req_str(body, "incident_id"),
        "assessed_at": req_datetime(body, "assessed_at"),
        "population_affected": req_int(body, "population_affected", 0),
        "estimated_daily_meal_need": req_int(body, "estimated_daily_meal_need", 0),
        "access_constraint": req_enum(body, "access_constraint", ACCESS_CONSTRAINTS),
        "water_available": req_bool(body, "water_available"),
        "power_available": req_bool(body, "power_available"),
        "partner_kitchens_identified": req_int(body, "partner_kitchens_identified", 0),
        "assessment_mode": opt_enum(body, "assessment_mode", ASSESSMENT_MODES, "RAPID"),
    }


def parse_field_kitchen_create(body):
    return {
        "incident_id": req_str(body, "incident_id"),
        "assessment_id": req_str(body, "assessment_id"),
        "site_name": req_str(body, "site_name"),
        "latitude": req_num(body, "latitude", -90.0, 90.0),
        "longitude": req_num(body, "longitude", -180.0, 180.0),
        "power_source": req_enum(body, "power_source", POWER_SOURCES),
        "water_source": req_enum(body, "water_source", WATER_SOURCES),
        "refrigeration_hours_available": req_int(body, "refrigeration_hours_available", 0),
        "daily_capacity_meals": req_int(body, "daily_capacity_meals", 0),
    }


def parse_partner_kitchen_create(body):
    return {
        "incident_id": req_str(body, "incident_id"),
        "business_name": req_str(body, "business_name"),
        "owner_name": req_str(body, "owner_name"),
        "cuisine_tags": req_str_list(body, "cuisine_tags", None, default=[]),
        "daily_capacity_meals": req_int(body, "daily_capacity_meals", 1),
        "per_meal_price_cents": req_int(body, "per_meal_price_cents", 1),
        "bank_verified": req_bool(body, "bank_verified"),
    }


def parse_meal_order_create(body):
    return {
        "incident_id": req_str(body, "incident_id"),
        "partner_kitchen_id": req_str(body, "partner_kitchen_id"),
        "menu_name": req_str(body, "menu_name"),
        "dietary_tags": req_str_list(body, "dietary_tags", DIETARY_TAGS, default=[]),
        "ordered_meals": req_int(body, "ordered_meals", 1),
        "scheduled_start": req_datetime(body, "scheduled_start"),
        "production_hours": req_int(body, "production_hours", 1),
        "expected_partner_kitchen_version": req_int(body, "expected_partner_kitchen_version"),
    }


def parse_supplier_create(body):
    return {
        "incident_id": req_str(body, "incident_id"),
        "producer_name": req_str(body, "producer_name"),
        "locality": req_str(body, "locality"),
        "product_categories": req_str_list(body, "product_categories", None, default=[]),
        "payment_terms_days": opt_int(body, "payment_terms_days", 7, 0),
    }


def parse_ingredient_purchase_create(body):
    return {
        "incident_id": req_str(body, "incident_id"),
        "supplier_id": req_str(body, "supplier_id"),
        "partner_kitchen_id": req_str(body, "partner_kitchen_id"),
        "item_description": req_str(body, "item_description"),
        "quantity_kg": req_num(body, "quantity_kg", 0, exclusive_min=True),
        "unit_price_cents_per_kg": req_int(body, "unit_price_cents_per_kg", 1),
    }


def parse_distribution_site_create(body):
    return {
        "incident_id": req_str(body, "incident_id"),
        "site_name": req_str(body, "site_name"),
        "site_type": req_enum(body, "site_type", SITE_TYPES),
        "population_served": req_int(body, "population_served", 0),
        "daily_meal_request": req_int(body, "daily_meal_request", 0),
        "access_constraint": req_enum(body, "access_constraint", ACCESS_CONSTRAINTS),
    }


def parse_distribution_run_create(body):
    data = {
        "incident_id": req_str(body, "incident_id"),
        "field_kitchen_id": req_str(body, "field_kitchen_id"),
        "driver_name": req_str(body, "driver_name"),
        "driver_phone": req_str(body, "driver_phone"),
        "driver_safety_training_completed": req_bool(body, "driver_safety_training_completed"),
        "vehicle_type": req_enum(body, "vehicle_type", VEHICLE_TYPES),
        "planned_date": req_datetime(body, "planned_date"),
        "window_start": req_datetime(body, "window_start"),
        "window_end": req_datetime(body, "window_end"),
        "fuel_cost_cents": req_int(body, "fuel_cost_cents", 0),
        "handling_cost_cents": req_int(body, "handling_cost_cents", 0),
    }
    if data["window_end"] <= data["window_start"]:
        fail("ERR_INVALID_REQUEST", "window_end must be strictly after window_start.")
    return data


def parse_distribution_stop_create(body):
    return {
        "distribution_run_id": req_str(body, "distribution_run_id"),
        "distribution_site_id": req_str(body, "distribution_site_id"),
        "stop_sequence": req_int(body, "stop_sequence", 1),
        "planned_meals": req_int(body, "planned_meals", 0),
        "expected_distribution_run_version": req_int(body, "expected_distribution_run_version"),
    }


def parse_donor_commitment_create(body):
    return {
        "incident_id": req_str(body, "incident_id"),
        "donor_name": req_str(body, "donor_name"),
        "amount_cents": req_int(body, "amount_cents", 1),
        "earmark": req_enum(body, "earmark", EARMARKS),
    }


def parse_inspection(body):
    return {
        "power_source": req_enum(body, "power_source", POWER_SOURCES),
        "water_source": req_enum(body, "water_source", WATER_SOURCES),
        "refrigeration_hours_available": req_int(body, "refrigeration_hours_available", 0),
        "daily_capacity_meals": req_int(body, "daily_capacity_meals", 0),
    }


def parse_clock(body):
    return {"to_iso8601": req_datetime(body, "to_iso8601")}


# --------------------------------------------------------------------------
# Transition payloads
# --------------------------------------------------------------------------

def parse_transition(body, states):
    return {"to_state": req_enum(body, "to_state", states)}


def parse_incident_transition(body):
    return parse_transition(body, INCIDENT_STATES)


def parse_field_kitchen_transition(body):
    return parse_transition(body, FIELD_KITCHEN_STATES)


def parse_partner_kitchen_transition(body):
    dimension = req_enum(body, "dimension", {"CONTRACT", "PRODUCTION"})
    states = CONTRACT_STATES if dimension == "CONTRACT" else PRODUCTION_STATES
    return {
        "dimension": dimension,
        "to_state": req_enum(body, "to_state", states),
        "vetting_score": opt_int(body, "vetting_score", None, 0, 100),
    }


def parse_meal_order_transition(body):
    return {
        "to_state": req_enum(body, "to_state", MEAL_ORDER_STATES),
        "produced_meals": opt_int(body, "produced_meals", None, 0),
        "quality_check_score": opt_int(body, "quality_check_score", None, 0, 100),
        "rejected_meals": opt_int(body, "rejected_meals", None, 0),
        "distribution_run_id": opt_str(body, "distribution_run_id"),
        "cancel_reason": opt_str(body, "cancel_reason"),
    }


def parse_run_transition(body):
    data = {
        "to_state": req_enum(body, "to_state", RUN_STATES),
        "loaded_meals": opt_int(body, "loaded_meals", None, 0),
        "abort_reason": opt_str(body, "abort_reason"),
    }
    if data["to_state"] == "EN_ROUTE" and data["loaded_meals"] is not None \
            and data["loaded_meals"] <= 0:
        fail("ERR_INVALID_REQUEST", "loaded_meals must be greater than 0.")
    return data


def parse_stop_transition(body):
    return {
        "to_state": req_enum(body, "to_state", STOP_STATES),
        "delivered_meals": opt_int(body, "delivered_meals", None, 0),
        "failure_reason": opt_str(body, "failure_reason"),
    }


def parse_purchase_transition(body):
    return {
        "to_state": req_enum(body, "to_state", PURCHASE_STATES),
        "dispute_reason": opt_str(body, "dispute_reason"),
    }


def parse_commitment_transition(body):
    return {
        "to_state": req_enum(body, "to_state", COMMITMENT_STATES),
        "disbursement_cents": opt_int(body, "disbursement_cents", None, 1),
    }
