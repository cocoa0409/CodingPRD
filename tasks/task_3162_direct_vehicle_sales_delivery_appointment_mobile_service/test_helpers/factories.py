"""Payload factories — one per entity, input fields only."""
from . import constants as C

DEFAULTS = {
    "BUYER_NAME": "Dana V",
    "BUYER_EMAIL": "dana.v@example.com",
    "BUYER_STATE": "TX",
    "CENTER_NAME": "Austin Delivery",
    "JURISDICTION_STATE": "TX",
}


# ─── Buyer ───────────────────────────────────────────
def create_buyer_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["BUYER_NAME"],
        "email": DEFAULTS["BUYER_EMAIL"],
        "residency_state_code": DEFAULTS["BUYER_STATE"],
    }
    payload.update(overrides)
    return payload


# ─── StateJurisdiction ───────────────────────────────
def create_jurisdiction_payload(**overrides) -> dict:
    """TX-shaped regime: direct sales permitted, 60-minute bay buffer."""
    payload = {
        "state_code": DEFAULTS["JURISDICTION_STATE"],
        "direct_sales_permitted": True,
        "gallery_only_required": False,
        "out_of_state_delivery_required": False,
        "cooling_off_days": 3,
        "doc_fee_cap_cents": 7500,
        "mobile_service_permitted": True,
        "delivery_buffer_minutes": C.TEST_DEFAULTS["TX_BUFFER_MINUTES"],
        "allocation_window_days": 14,
        "transport_lead_days": C.TEST_DEFAULTS["TX_TRANSPORT_LEAD_DAYS"],
    }
    payload.update(overrides)
    return payload


# ─── DeliveryCenter ──────────────────────────────────
def create_delivery_center_payload(**overrides) -> dict:
    payload = {
        "center_name": DEFAULTS["CENTER_NAME"],
        "center_kind": "DELIVERY_CENTER",
        "state_code": "TX",
        "home_delivery_radius_miles": 50,
        "bay_count": 4,
        "van_count": 3,
    }
    payload.update(overrides)
    return payload


# ─── VehicleConfiguration & ConfigurationOption ──────
def create_configuration_payload(**overrides) -> dict:
    payload = {
        "model_code": C.TEST_DEFAULTS["MODEL_CODE_Y"],
        "base_price_cents": C.TEST_DEFAULTS["BASE_PRICE_CENTS_Y"],
    }
    payload.update(overrides)
    return payload


def create_option_payload(**overrides) -> dict:
    payload = {
        "option_sku": "PAINT_WHITE",
        "option_category": "PAINT",
        "price_cents": 100000,
    }
    payload.update(overrides)
    return payload


# ─── VehicleOrder ────────────────────────────────────
def create_order_payload(buyer_id, configuration_id, jurisdiction_id,
                         delivery_center_id, **overrides) -> dict:
    payload = {
        "buyer_id": buyer_id,
        "configuration_id": configuration_id,
        "jurisdiction_id": jurisdiction_id,
        "delivery_center_id": delivery_center_id,
        "order_fee_cents": C.ORDER_FEE_CENTS,
    }
    payload.update(overrides)
    return payload


# ─── ProductionBatch & AllocationUnit ────────────────
def create_batch_payload(**overrides) -> dict:
    payload = {
        "factory_code": C.TEST_DEFAULTS["FACTORY_CODE"],
        "model_code": C.TEST_DEFAULTS["MODEL_CODE_Y"],
        "unit_capacity": 2,
        "planned_completion_at": C.TEST_DEFAULTS["PLANNED_COMPLETION_AT"],
    }
    payload.update(overrides)
    return payload


# ─── DeliveryAppointment ─────────────────────────────
def create_appointment_payload(order_id, delivery_center_id,
                               expected_order_version, **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "delivery_center_id": delivery_center_id,
        "delivery_mode": "CENTER",
        "scheduled_start": "2026-09-22T15:00:00Z",
        "scheduled_end": "2026-09-22T16:00:00Z",
        "expected_order_version": expected_order_version,
    }
    payload.update(overrides)
    return payload


def create_completion_payload(expected_order_version, **overrides) -> dict:
    payload = {
        "acceptance_inspection_result": "CLEAN",
        "documented_issues": [],
        "expected_order_version": expected_order_version,
    }
    payload.update(overrides)
    return payload


# ─── TradeInAppraisal ────────────────────────────────
def create_appraisal_payload(**overrides) -> dict:
    payload = {
        "trade_vin": "5YJ3E1EA7PF000901",
        "mileage": 30000,
        "gross_offer_cents": 900000,
        "reconditioning_estimate_cents": 40000,
        "offer_valid_until": "2026-10-15T00:00:00Z",
    }
    payload.update(overrides)
    return payload


# ─── FinancingApplication ────────────────────────────
def create_financing_application_payload(**overrides) -> dict:
    payload = {
        "term_months": 60,
        "down_payment_cents": 0,
        "include_trade_in_credit": False,
    }
    payload.update(overrides)
    return payload


# ─── RemoteDiagnosticReport ──────────────────────────
def create_diagnostic_report_payload(**overrides) -> dict:
    payload = {
        "fault_code": "HVAC-0442",
        "severity": "MEDIUM",
        "is_driveable": True,
    }
    payload.update(overrides)
    return payload


# ─── ServiceAppointment ──────────────────────────────
def create_service_appointment_payload(vehicle_id, diagnostic_report_id,
                                       service_center_id, **overrides) -> dict:
    payload = {
        "vehicle_id": vehicle_id,
        "diagnostic_report_id": diagnostic_report_id,
        "service_center_id": service_center_id,
        "scheduled_start": "2026-09-25T14:00:00Z",
        "scheduled_end": "2026-09-25T16:00:00Z",
    }
    payload.update(overrides)
    return payload


# ─── MobileServiceVisit ──────────────────────────────
def create_mobile_visit_payload(service_appointment_id, parts_hub_id,
                                expected_service_appointment_version,
                                **overrides) -> dict:
    payload = {
        "service_appointment_id": service_appointment_id,
        "parts_hub_id": parts_hub_id,
        "van_code": "VAN-ATX-1",
        "visit_start": "2026-09-26T14:00:00Z",
        "visit_end": "2026-09-26T17:00:00Z",
        "labor_hours": 2.0,
        "parts_cost_cents": 42000,
        "visit_miles": 45,
        "expected_service_appointment_version": expected_service_appointment_version,
    }
    payload.update(overrides)
    return payload


# ─── SoftwareEntitlement ─────────────────────────────
def create_entitlement_payload(feature_entries=None, **overrides) -> dict:
    payload = {
        "feature_entries": feature_entries or [
            {"feature_code": "PREMIUM_CONNECTIVITY", "price_cents": 100000}
        ],
        "entitlement_source": "PURCHASE",
    }
    payload.update(overrides)
    return payload


# ─── VehicleIssueNote / ledger ───────────────────────
def create_waiver_payload(**overrides) -> dict:
    payload = {"waiver_reason": "buyer accepted documented chip"}
    payload.update(overrides)
    return payload


def create_ledger_entry_payload(**overrides) -> dict:
    payload = {
        "entry_type": "DELIVERY_FEE_CHARGE",
        "amount_cents": -2500,
        "reason_code": "HOME_DELIVERY_SURCHARGE",
    }
    payload.update(overrides)
    return payload

__all__ = [name for name in dir() if not name.startswith("_")]