"""Payload factories — one per creatable resource, input fields only.

Unique-constrained fields (site_code, account_number, protocol_number,
strain_code) get a fresh UUID suffix on every call so repeated creates inside
one test never collide. Default instants are drawn from the constants module
and are all reachable from the logical-clock default 2026-09-01T00:00:00Z.
"""
import uuid

from .constants import (
    COHORT_BIRTH_DATE_ISO,
    STANDARD_REQUIRED_DELIVERY_DATE_ISO,
    STANDARD_DEPARTURE_DATE_ISO,
    STANDARD_PLANNED_ARRIVAL_DATE_ISO,
    STANDARD_SANITIZED_AT_ISO,
    STANDARD_REGISTRATION_EXPIRES_AT_ISO,
    STANDARD_PROTOCOL_EFFECTIVE_DATE_ISO,
    STANDARD_PROTOCOL_EXPIRATION_DATE_ISO,
    STANDARD_SCREEN_SCHEDULED_AT_ISO,
    STANDARD_INSPECTION_DATE_ISO,
)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


DEFAULTS = {
    "FACILITY_NAME": "Site Alpha",
    "REGISTRATION_NUMBER": "REG-001",
    "ROOM_CODE_PREFIX": "R",
    "ROOM_BARRIER_LEVEL": "VF",
    "ROOM_EXCLUDED_AGENTS": ["MHV", "MPV"],
    "ROOM_CAGE_CAPACITY": 100,
    "STRAIN_SPECIES": "MOUSE",
    "STRAIN_IMMUNE_CLASS": "IMMUNOCOMPETENT",
    "STRAIN_BREEDING_TYPE": "INBRED",
    "STRAIN_MIN_BARRIER_LEVEL": "MPF",
    "STRAIN_GESTATION_DAYS": 21,
    "STRAIN_WEAN_AGE_DAYS": 21,
    "STRAIN_TYPICAL_LITTER_SIZE": 6,
    "STRAIN_BASE_PRICE_CENTS": 1000,
    "PROTOCOL_PI_NAME": "Dr. Xu",
    "PROTOCOL_SPECIES": "MOUSE",
    "PROTOCOL_QUOTA": 1000,
    "COLONY_BREEDING_PAIRS": 10,
    "COHORT_COUNT_MALE": 10,
    "COHORT_COUNT_FEMALE": 10,
    "COHORT_AVG_WEIGHT_G_MALE": 20.0,
    "COHORT_AVG_WEIGHT_G_FEMALE": 20.0,
    "CUSTOMER_INSTITUTION": "Inst A",
    "CUSTOMER_CREDIT_LIMIT_CENTS": 1000000,
    "CUSTOMER_ACCEPTED_MIN_HEALTH_STATUS": "MPF",
    "CUSTOMER_IS_COMMERCIAL": False,
    "ORDER_QUANTITY_MALE": 10,
    "ORDER_QUANTITY_FEMALE": 10,
    "ORDER_MIN_AGE_WEEKS": 4,
    "ORDER_MAX_AGE_WEEKS": 6,
    "ORDER_MIN_WEIGHT_G": 18.0,
    "ORDER_MAX_WEIGHT_G": 22.0,
    "SHIPMENT_VEHICLE_BARRIER_CERT": "VF",
    "SCREEN_PANEL_TYPE": "QUARTERLY_SENTINEL",
    "INSPECTION_TYPE": "ROUTINE",
}


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["FACILITY_NAME"],
        "site_code": _uniq("SITE"),
        "registration_number": _uniq(DEFAULTS["REGISTRATION_NUMBER"]),
        "registration_expires_at": STANDARD_REGISTRATION_EXPIRES_AT_ISO,
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "room_code": _uniq(DEFAULTS["ROOM_CODE_PREFIX"]),
        "barrier_level": DEFAULTS["ROOM_BARRIER_LEVEL"],
        "excluded_agents": list(DEFAULTS["ROOM_EXCLUDED_AGENTS"]),
        "cage_capacity": DEFAULTS["ROOM_CAGE_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_strain_payload(**overrides) -> dict:
    defaults = {
        "strain_code": _uniq("STRAIN"),
        "species": DEFAULTS["STRAIN_SPECIES"],
        "immune_class": DEFAULTS["STRAIN_IMMUNE_CLASS"],
        "breeding_type": DEFAULTS["STRAIN_BREEDING_TYPE"],
        "min_barrier_level": DEFAULTS["STRAIN_MIN_BARRIER_LEVEL"],
        "gestation_days": DEFAULTS["STRAIN_GESTATION_DAYS"],
        "wean_age_days": DEFAULTS["STRAIN_WEAN_AGE_DAYS"],
        "typical_litter_size": DEFAULTS["STRAIN_TYPICAL_LITTER_SIZE"],
        "base_price_cents": DEFAULTS["STRAIN_BASE_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_protocol_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "protocol_number": _uniq("P"),
        "pi_name": DEFAULTS["PROTOCOL_PI_NAME"],
        "species": DEFAULTS["PROTOCOL_SPECIES"],
        "approved_animal_quota": DEFAULTS["PROTOCOL_QUOTA"],
        "effective_date": STANDARD_PROTOCOL_EFFECTIVE_DATE_ISO,
        "expiration_date": STANDARD_PROTOCOL_EXPIRATION_DATE_ISO,
    }
    defaults.update(overrides)
    return defaults


def create_colony_payload(room_id: str, strain_id: str, protocol_id: str, **overrides) -> dict:
    defaults = {
        "room_id": room_id,
        "strain_id": strain_id,
        "protocol_id": protocol_id,
        "breeding_pair_count": DEFAULTS["COLONY_BREEDING_PAIRS"],
    }
    defaults.update(overrides)
    return defaults


def create_cohort_payload(colony_id: str, **overrides) -> dict:
    defaults = {
        "colony_id": colony_id,
        "birth_date": COHORT_BIRTH_DATE_ISO,
        "count_male": DEFAULTS["COHORT_COUNT_MALE"],
        "count_female": DEFAULTS["COHORT_COUNT_FEMALE"],
        "avg_weight_g_male": DEFAULTS["COHORT_AVG_WEIGHT_G_MALE"],
        "avg_weight_g_female": DEFAULTS["COHORT_AVG_WEIGHT_G_FEMALE"],
    }
    defaults.update(overrides)
    return defaults


def create_health_screen_payload(room_id: str, **overrides) -> dict:
    defaults = {
        "room_id": room_id,
        "panel_type": DEFAULTS["SCREEN_PANEL_TYPE"],
        "scheduled_at": STANDARD_SCREEN_SCHEDULED_AT_ISO,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "institution_name": DEFAULTS["CUSTOMER_INSTITUTION"],
        "account_number": _uniq("ACCT"),
        "credit_limit_cents": DEFAULTS["CUSTOMER_CREDIT_LIMIT_CENTS"],
        "accepted_min_health_status": DEFAULTS["CUSTOMER_ACCEPTED_MIN_HEALTH_STATUS"],
        "is_commercial": DEFAULTS["CUSTOMER_IS_COMMERCIAL"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(strain_id: str, **overrides) -> dict:
    """Order intake payload; customer_id comes from X-User-ID, never the body."""
    defaults = {
        "strain_id": strain_id,
        "quantity_male": DEFAULTS["ORDER_QUANTITY_MALE"],
        "quantity_female": DEFAULTS["ORDER_QUANTITY_FEMALE"],
        "min_age_weeks": DEFAULTS["ORDER_MIN_AGE_WEEKS"],
        "max_age_weeks": DEFAULTS["ORDER_MAX_AGE_WEEKS"],
        "min_weight_g": DEFAULTS["ORDER_MIN_WEIGHT_G"],
        "max_weight_g": DEFAULTS["ORDER_MAX_WEIGHT_G"],
        "required_delivery_date": STANDARD_REQUIRED_DELIVERY_DATE_ISO,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(order_id: str, cohort_id: str, expected_order_version: int, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "cohort_id": cohort_id,
        "qty_male": 5,
        "qty_female": 5,
        "expected_order_version": expected_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(order_id: str, expected_order_version: int, **overrides) -> dict:
    """Shipment plan payload; vehicle_code defaults to a fresh value per call so
    independent shipments never collide on the vehicle schedule."""
    defaults = {
        "order_id": order_id,
        "vehicle_code": _uniq("VH"),
        "vehicle_barrier_cert": DEFAULTS["SHIPMENT_VEHICLE_BARRIER_CERT"],
        "sanitized_at": STANDARD_SANITIZED_AT_ISO,
        "departure_date": STANDARD_DEPARTURE_DATE_ISO,
        "planned_arrival_date": STANDARD_PLANNED_ARRIVAL_DATE_ISO,
        "expected_order_version": expected_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(**overrides) -> dict:
    """Inspection payload. Exactly one of facility_id / customer_id must be set
    (pass via overrides); neither is defaulted here."""
    defaults = {
        "inspection_type": DEFAULTS["INSPECTION_TYPE"],
        "scheduled_date": STANDARD_INSPECTION_DATE_ISO,
    }
    defaults.update(overrides)
    return defaults


def create_finding(deficiency: str = "cage overcrowding", severity: str = "SIGNIFICANT") -> dict:
    return {"deficiency": deficiency, "severity": severity}


def create_screen_result_entry(agent: str = "MHV", positive: bool = True) -> dict:
    return {"agent": agent, "positive": positive}


def create_new_strain_spec(**overrides) -> dict:
    """Complete strain definition object for a CUSTOM_GENERATION contract."""
    defaults = {
        "strain_code": _uniq("TG"),
        "species": "MOUSE",
        "immune_class": "IMMUNOCOMPETENT",
        "breeding_type": "INBRED",
        "min_barrier_level": "VF",
        "gestation_days": 21,
        "wean_age_days": 21,
        "typical_litter_size": 5,
        "base_price_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(customer_id: str, source_strain_id: str, **overrides) -> dict:
    """Service contract payload. Type-specific fields (new_strain_spec /
    straw_count) and IP-term fields are left to overrides so each test states
    them explicitly."""
    defaults = {
        "customer_id": customer_id,
        "contract_type": "CUSTOM_GENERATION",
        "source_strain_id": source_strain_id,
        "ip_ownership": "VENDOR_RETAINED",
        "royalty_rate_pct": 10.0,
    }
    defaults.update(overrides)
    return defaults


__all__ = [
    "DEFAULTS",
    "create_facility_payload",
    "create_room_payload",
    "create_strain_payload",
    "create_protocol_payload",
    "create_colony_payload",
    "create_cohort_payload",
    "create_health_screen_payload",
    "create_customer_payload",
    "create_order_payload",
    "create_allocation_payload",
    "create_shipment_payload",
    "create_inspection_payload",
    "create_finding",
    "create_screen_result_entry",
    "create_new_strain_spec",
    "create_contract_payload",
]
