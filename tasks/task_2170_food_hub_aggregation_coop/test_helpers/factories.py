"""Payload factories, one per creatable resource, carrying input fields only."""

from .constants import TEST_DEFAULTS


def create_producer_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Green Acres Farm",
        "region_code": "NEV",
        "contact_email": "ga@example.org",
    }
    payload.update(overrides)
    return payload


def create_producer_document_payload(**overrides) -> dict:
    payload = {
        "doc_type": "GAP_AUDIT",
        "issued_on": TEST_DEFAULTS["DOC_ISSUED_ON"],
        "expires_on": TEST_DEFAULTS["DOC_EXPIRES_ON"],
    }
    payload.update(overrides)
    return payload


def create_product_payload(producer_id: str, **overrides) -> dict:
    payload = {
        "producer_id": producer_id,
        "commodity_code": TEST_DEFAULTS["COMMODITY_CODE"],
        "unit_of_measure": TEST_DEFAULTS["UNIT_OF_MEASURE"],
        "storage_class": TEST_DEFAULTS["STORAGE_CLASS"],
        "pack_weight_lb": TEST_DEFAULTS["PACK_WEIGHT_LB"],
        "units_per_pallet": TEST_DEFAULTS["UNITS_PER_PALLET"],
        "producer_unit_price_cents": TEST_DEFAULTS["PRODUCER_UNIT_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def publish_offer_payload(expected_product_version: int, **overrides) -> dict:
    payload = {
        "quantity_offered": TEST_DEFAULTS["QUANTITY_OFFERED"],
        "offer_window_start": TEST_DEFAULTS["OFFER_WINDOW_START"],
        "offer_window_end": TEST_DEFAULTS["OFFER_WINDOW_END"],
        "expected_product_version": expected_product_version,
    }
    payload.update(overrides)
    return payload


def create_buyer_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Metro School District",
        "buyer_type": "SCHOOL_DISTRICT",
        "dock_zone_code": "Z1",
        "payment_terms_days": TEST_DEFAULTS["PAYMENT_TERMS_DAYS"],
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_buyer_order_payload(buyer_id: str, **overrides) -> dict:
    payload = {
        "buyer_id": buyer_id,
        "requested_delivery_date": TEST_DEFAULTS["REQUESTED_DELIVERY_DATE"],
    }
    payload.update(overrides)
    return payload


def create_order_line_payload(**overrides) -> dict:
    payload = {
        "commodity_code": TEST_DEFAULTS["COMMODITY_CODE"],
        "storage_class": TEST_DEFAULTS["STORAGE_CLASS"],
        "unit_of_measure": TEST_DEFAULTS["UNIT_OF_MEASURE"],
        "quantity_requested": TEST_DEFAULTS["LINE_QUANTITY"],
        "max_unit_price_cents": TEST_DEFAULTS["MAX_UNIT_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_dock_slot_payload(**overrides) -> dict:
    payload = {
        "door_code": "D1",
        "storage_class": TEST_DEFAULTS["STORAGE_CLASS"],
        "window_start": TEST_DEFAULTS["DOCK_WINDOW_START"],
        "window_end": TEST_DEFAULTS["DOCK_WINDOW_END"],
        "pallet_capacity": TEST_DEFAULTS["DOCK_PALLET_CAPACITY"],
        "temp_setpoint_c": TEST_DEFAULTS["TEMP_SETPOINT_C"],
        "sanitation_buffer_minutes": 45,
    }
    payload.update(overrides)
    return payload


def create_dock_appointment_payload(
    dock_slot_id: str, producer_id: str, expected_dock_slot_version: int, **overrides
) -> dict:
    payload = {
        "dock_slot_id": dock_slot_id,
        "producer_id": producer_id,
        "arrival_start": TEST_DEFAULTS["ARRIVAL_START"],
        "arrival_end": TEST_DEFAULTS["ARRIVAL_END"],
        "pallets": TEST_DEFAULTS["APPOINTMENT_PALLETS"],
        "risk_class": TEST_DEFAULTS["RISK_CLASS"],
        "expected_dock_slot_version": expected_dock_slot_version,
    }
    payload.update(overrides)
    return payload


def create_delivery_route_payload(**overrides) -> dict:
    payload = {
        "route_date": TEST_DEFAULTS["ROUTE_DATE"],
        "vehicle_code": "REEF-1",
        "storage_class": TEST_DEFAULTS["STORAGE_CLASS"],
        "pallet_capacity": TEST_DEFAULTS["ROUTE_PALLET_CAPACITY"],
        "depot_departure_at": TEST_DEFAULTS["DEPOT_DEPARTURE_AT"],
    }
    payload.update(overrides)
    return payload


def create_route_stop_payload(
    order_id: str, expected_route_version: int, **overrides
) -> dict:
    payload = {
        "order_id": order_id,
        "sequence_no": 1,
        "planned_arrival_at": TEST_DEFAULTS["PLANNED_ARRIVAL_AT"],
        "service_minutes": TEST_DEFAULTS["SERVICE_MINUTES"],
        "expected_route_version": expected_route_version,
    }
    payload.update(overrides)
    return payload


def create_rejection_claim_payload(allocation_id: str, **overrides) -> dict:
    payload = {
        "allocation_id": allocation_id,
        "quantity_rejected": 5,
        "reason_code": "DAMAGE",
    }
    payload.update(overrides)
    return payload


def create_patronage_cycle_payload(**overrides) -> dict:
    payload = {"fiscal_year": 2026, "distributable_pool_cents": 1_000_000}
    payload.update(overrides)
    return payload


__all__ = [
    "create_producer_payload",
    "create_producer_document_payload",
    "create_product_payload",
    "publish_offer_payload",
    "create_buyer_payload",
    "create_buyer_order_payload",
    "create_order_line_payload",
    "create_dock_slot_payload",
    "create_dock_appointment_payload",
    "create_delivery_route_payload",
    "create_route_stop_payload",
    "create_rejection_claim_payload",
    "create_patronage_cycle_payload",
]
