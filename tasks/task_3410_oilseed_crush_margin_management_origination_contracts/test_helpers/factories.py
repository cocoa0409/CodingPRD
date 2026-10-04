"""Payload factories — one per creatable resource, input fields only.

Defaults are canonical test inputs shared across the fixture preambles (they
are request payloads, not server rules). **overrides on every factory let a
test replace, add, or null out any field — including sending computed fields
to prove the server ignores them, or omitting required fields by passing
None and stripping in the caller.
"""
from .constants import LOGICAL_CLOCK_START

# Canonical futures months used across scenarios.
FUTURES_MONTH_NOV = "2026-11"
FUTURES_MONTH_DEC = "2026-12"

# Canonical crush-board quote triple (PRD §2.6 units: BEAN cents/bu, OIL and
# MEAL cents/lb). 55 x 11 + 17 x 47 - 1200 = 204.00 spread.
CANONICAL_BEAN_PRICE_CENTS = 1200
CANONICAL_OIL_PRICE_CENTS = 55
CANONICAL_MEAL_PRICE_CENTS = 17

DEFAULTS = {
    "FARMER_LEGAL_NAME": "A. Farmer",
    "FARMER_COUNTY": "Macoupin",
    "BUYER_COMPANY_NAME": "Continental Oils Co",
    "ELEVATOR_NAME": "Riverbend",
    "ELEVATOR_REGION": "IL",
    "ELEVATOR_CAPACITY_BUSHELS": 100000,
    "PLANT_NAME": "Decatur",
    "PLANT_DAILY_CRUSH_CAPACITY_BUSHELS": 50000,
    "PLANT_DAILY_REFINERY_CAPACITY_LBS": 1000000,
    "PLANT_BIODIESEL_FEEDSTOCK_SHARE_PCT": 10,
    "PROGRAM_NAME": "Regen Prairies",
    "PROGRAM_CERT_STANDARD": "REGEN",
    "PROGRAM_PREMIUM_CENTS_PER_BUSHEL": 25,
    "CONTRACT_QUANTITY_BUSHELS": 100,
    "CASH_PRICE_CENTS_PER_BUSHEL": 1000,
    "DEFERRED_PRICING_DEADLINE": "2026-12-15T00:00:00Z",
    "DEFERRED_STORAGE_RATE_CENTS": 1,
    "TICKET_GROSS_BUSHELS": 100,
    "TICKET_MOISTURE_PCT": 13.0,
    "TICKET_DAMAGE_PCT": 0,
    "TICKET_FOREIGN_MATERIAL_PCT": 0,
    "LANE_FREIGHT_CENTS_PER_BUSHEL": 12,
    "LANE_TRANSIT_DAYS": 2,
    "LANE_DAILY_CAPACITY_BUSHELS": 50000,
    "SHIPMENT_DEPARTURE_DATE": "2026-09-10T00:00:00Z",
    "RUN_DATE": "2026-09-10T00:00:00Z",
    "RUN_PLANNED_BUSHELS": 1000,
    "POSITION_BEAN_LOTS_LONG": 2,
    "POSITION_OIL_LOTS_SHORT": 2,
    "POSITION_MEAL_LOTS_SHORT": 2,
    "POSITION_EXPIRY_DATE": "2026-11-13T00:00:00Z",
    "SALE_QUANTITY_LBS": 1000,
    "SALE_PRICE_CENTS_PER_LB": 20,
    "SALE_WINDOW_START": "2026-09-15T00:00:00Z",
    "SALE_WINDOW_END": "2026-09-30T00:00:00Z",
    "SALE_MAX_FFA_PCT": 0.5,
    "SALE_MIN_PROTEIN_PCT": 46.0,
    "DELIVERY_QUANTITY_LBS": 100,
    "DELIVERY_ACTUAL_FFA_PCT": 0.3,
    "DELIVERY_ACTUAL_PROTEIN_PCT": 47.5,
}


# --------------------------------------------------------------------- clock

def set_clock_payload(to_iso8601: str = LOGICAL_CLOCK_START, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------- farmers

def create_farmer_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["FARMER_LEGAL_NAME"],
        "county": DEFAULTS["FARMER_COUNTY"],
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------ elevators

def create_elevator_payload(active_discount_schedule_id, **overrides) -> dict:
    payload = {
        "name": DEFAULTS["ELEVATOR_NAME"],
        "region": DEFAULTS["ELEVATOR_REGION"],
        "storage_capacity_bushels": DEFAULTS["ELEVATOR_CAPACITY_BUSHELS"],
        "active_discount_schedule_id": active_discount_schedule_id,
    }
    payload.update(overrides)
    return payload


def create_carry_assessment_params(nearby_month, deferred_month, **overrides) -> dict:
    params = {"nearby_month": nearby_month, "deferred_month": deferred_month}
    params.update(overrides)
    return params


# ------------------------------------------------- quality discount schedules

def create_schedule_payload(**overrides) -> dict:
    """Canonical grading grid shared by the scenario fixtures: moisture base
    13.0 with 1.3%/point shrink and 4c/point discount, damage free 2.0 at
    3c/point, foreign material free 1.0 at 3c/point, reject above 18.0."""
    payload = {
        "name": "Fall Std",
        "moisture_base_pct": 13.0,
        "moisture_shrink_pct_per_point": 1.3,
        "moisture_discount_cents_per_point": 4,
        "damage_free_pct": 2.0,
        "damage_discount_cents_per_point": 3,
        "fm_free_pct": 1.0,
        "fm_discount_cents_per_point": 3,
        "reject_moisture_pct": 18.0,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------- sustainability programs

def create_program_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["PROGRAM_NAME"],
        "cert_standard": DEFAULTS["PROGRAM_CERT_STANDARD"],
        "premium_cents_per_bushel": DEFAULTS["PROGRAM_PREMIUM_CENTS_PER_BUSHEL"],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------- market quotes

def create_market_quote_payload(
    commodity="BEAN",
    quote_month=FUTURES_MONTH_NOV,
    price_cents=CANONICAL_BEAN_PRICE_CENTS,
    quote_date=LOGICAL_CLOCK_START,
    **overrides,
) -> dict:
    payload = {
        "commodity": commodity,
        "quote_month": quote_month,
        "price_cents": price_cents,
        "quote_date": quote_date,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------- crush plants

def create_crush_plant_payload(**overrides) -> dict:
    """Default plant is ACTIVE (the server default); pass status="MAINTENANCE"
    to register a site directly in maintenance."""
    payload = {
        "name": DEFAULTS["PLANT_NAME"],
        "daily_crush_capacity_bushels": DEFAULTS["PLANT_DAILY_CRUSH_CAPACITY_BUSHELS"],
        "daily_refinery_capacity_lbs": DEFAULTS["PLANT_DAILY_REFINERY_CAPACITY_LBS"],
        "biodiesel_feedstock_share_pct": DEFAULTS["PLANT_BIODIESEL_FEEDSTOCK_SHARE_PCT"],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------- buyers

def create_buyer_payload(**overrides) -> dict:
    payload = {"company_name": DEFAULTS["BUYER_COMPANY_NAME"]}
    payload.update(overrides)
    return payload


# ------------------------------------------------------ origination contracts

def create_cash_contract_payload(farmer_id, elevator_id, **overrides) -> dict:
    payload = {
        "farmer_id": farmer_id,
        "elevator_id": elevator_id,
        "contract_type": "CASH",
        "quantity_bushels": DEFAULTS["CONTRACT_QUANTITY_BUSHELS"],
        "cash_price_cents_per_bushel": DEFAULTS["CASH_PRICE_CENTS_PER_BUSHEL"],
    }
    payload.update(overrides)
    return payload


def create_basis_contract_payload(farmer_id, elevator_id, **overrides) -> dict:
    payload = {
        "farmer_id": farmer_id,
        "elevator_id": elevator_id,
        "contract_type": "BASIS",
        "quantity_bushels": DEFAULTS["CONTRACT_QUANTITY_BUSHELS"],
        "basis_cents_per_bushel": -25,
        "futures_month": FUTURES_MONTH_DEC,
    }
    payload.update(overrides)
    return payload


def create_deferred_contract_payload(farmer_id, elevator_id, **overrides) -> dict:
    payload = {
        "farmer_id": farmer_id,
        "elevator_id": elevator_id,
        "contract_type": "DEFERRED",
        "quantity_bushels": DEFAULTS["CONTRACT_QUANTITY_BUSHELS"],
        "futures_month": FUTURES_MONTH_DEC,
        "pricing_deadline": DEFAULTS["DEFERRED_PRICING_DEADLINE"],
        "storage_rate_cents_per_bushel_day": DEFAULTS["DEFERRED_STORAGE_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_origination_contract_payload(farmer_id, elevator_id, **overrides) -> dict:
    """Generic factory; defaults to a CASH contract. Prefer the type-named
    factories above in scenario code."""
    return create_cash_contract_payload(farmer_id, elevator_id, **overrides)


def create_pricing_election_payload(bushels, expected_contract_version, **overrides) -> dict:
    payload = {
        "bushels": bushels,
        "expected_contract_version": expected_contract_version,
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------------- delivery tickets

def create_delivery_ticket_payload(contract_id, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "gross_bushels": DEFAULTS["TICKET_GROSS_BUSHELS"],
        "moisture_pct": DEFAULTS["TICKET_MOISTURE_PCT"],
        "damage_pct": DEFAULTS["TICKET_DAMAGE_PCT"],
        "foreign_material_pct": DEFAULTS["TICKET_FOREIGN_MATERIAL_PCT"],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------- freight lanes

def create_freight_lane_payload(origin_elevator_id, destination_plant_id, **overrides) -> dict:
    payload = {
        "origin_elevator_id": origin_elevator_id,
        "destination_plant_id": destination_plant_id,
        "mode": "TRUCK",
        "freight_cents_per_bushel": DEFAULTS["LANE_FREIGHT_CENTS_PER_BUSHEL"],
        "transit_days": DEFAULTS["LANE_TRANSIT_DAYS"],
        "daily_capacity_bushels": DEFAULTS["LANE_DAILY_CAPACITY_BUSHELS"],
    }
    payload.update(overrides)
    return payload


def create_routing_quote_payload(origin_elevator_id, bushels=100, **overrides) -> dict:
    payload = {"origin_elevator_id": origin_elevator_id, "bushels": bushels}
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------ shipments

def create_shipment_payload(lane_id, bushels, **overrides) -> dict:
    payload = {
        "lane_id": lane_id,
        "bushels": bushels,
        "departure_date": DEFAULTS["SHIPMENT_DEPARTURE_DATE"],
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------ crush runs

def create_crush_run_payload(plant_id, **overrides) -> dict:
    payload = {
        "plant_id": plant_id,
        "run_date": DEFAULTS["RUN_DATE"],
        "planned_bushels": DEFAULTS["RUN_PLANNED_BUSHELS"],
        "futures_month": FUTURES_MONTH_NOV,
    }
    payload.update(overrides)
    return payload


def schedule_crush_run_payload(expected_run_version, **overrides) -> dict:
    payload = {"expected_run_version": expected_run_version}
    payload.update(overrides)
    return payload


def transition_crush_run_payload(to_status, **overrides) -> dict:
    payload = {"to_status": to_status}
    payload.update(overrides)
    return payload


# -------------------------------------------------------- board crush positions

def create_board_position_payload(**overrides) -> dict:
    payload = {
        "futures_month": FUTURES_MONTH_NOV,
        "bean_lots_long": DEFAULTS["POSITION_BEAN_LOTS_LONG"],
        "oil_lots_short": DEFAULTS["POSITION_OIL_LOTS_SHORT"],
        "meal_lots_short": DEFAULTS["POSITION_MEAL_LOTS_SHORT"],
        "expiry_date": DEFAULTS["POSITION_EXPIRY_DATE"],
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------- product sales contracts

def create_sales_contract_payload(buyer_id, plant_id, product="SOY_OIL", **overrides) -> dict:
    """Product-matched quality spec included by default: max_ffa_pct for
    SOY_OIL / BIODIESEL_FEEDSTOCK, min_protein_pct for SOY_MEAL."""
    payload = {
        "buyer_id": buyer_id,
        "plant_id": plant_id,
        "product": product,
        "quantity_lbs": DEFAULTS["SALE_QUANTITY_LBS"],
        "price_cents_per_lb": DEFAULTS["SALE_PRICE_CENTS_PER_LB"],
        "delivery_window_start": DEFAULTS["SALE_WINDOW_START"],
        "delivery_window_end": DEFAULTS["SALE_WINDOW_END"],
    }
    if product == "SOY_MEAL":
        payload["min_protein_pct"] = DEFAULTS["SALE_MIN_PROTEIN_PCT"]
    else:
        payload["max_ffa_pct"] = DEFAULTS["SALE_MAX_FFA_PCT"]
    payload.update(overrides)
    return payload


def create_sales_delivery_payload(
    delivery_date, quantity_lbs, product="SOY_OIL", **overrides
) -> dict:
    payload = {"delivery_date": delivery_date, "quantity_lbs": quantity_lbs}
    if product == "SOY_MEAL":
        payload["actual_protein_pct"] = DEFAULTS["DELIVERY_ACTUAL_PROTEIN_PCT"]
    else:
        payload["actual_ffa_pct"] = DEFAULTS["DELIVERY_ACTUAL_FFA_PCT"]
    payload.update(overrides)
    return payload


__all__ = [
    "DEFAULTS",
    "FUTURES_MONTH_NOV",
    "FUTURES_MONTH_DEC",
    "CANONICAL_BEAN_PRICE_CENTS",
    "CANONICAL_OIL_PRICE_CENTS",
    "CANONICAL_MEAL_PRICE_CENTS",
    "set_clock_payload",
    "create_farmer_payload",
    "create_elevator_payload",
    "create_carry_assessment_params",
    "create_schedule_payload",
    "create_program_payload",
    "create_market_quote_payload",
    "create_crush_plant_payload",
    "create_buyer_payload",
    "create_cash_contract_payload",
    "create_basis_contract_payload",
    "create_deferred_contract_payload",
    "create_origination_contract_payload",
    "create_pricing_election_payload",
    "create_delivery_ticket_payload",
    "create_freight_lane_payload",
    "create_routing_quote_payload",
    "create_shipment_payload",
    "create_crush_run_payload",
    "schedule_crush_run_payload",
    "transition_crush_run_payload",
    "create_board_position_payload",
    "create_sales_contract_payload",
    "create_sales_delivery_payload",
]
