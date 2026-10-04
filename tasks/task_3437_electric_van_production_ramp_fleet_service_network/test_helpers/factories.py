"""Payload factories — one per create/action endpoint, input fields only.

System and computed fields (status, version, counters, provenance fields) are
never part of a payload. Required foreign keys are mandatory arguments; fields
the PRD marks optional are omitted from the payload when left as None so the
"absent" branch is what the server sees.
"""

DEFAULTS = {
    "COMPANY_NAME": "Acme Logistics",
    "CONTACT_EMAIL": "ops@acme.test",
    "ACCOUNT_TIER": "STANDARD",
    "DEPOT_NAME": "Acme Depot CA",
    "DEPOT_STATE": "CA",
    "DEPOT_ADDRESS": "1 Depot Way",
    "DEPOT_CAPACITY_KW": 500,
    "SUPPLIER_NAME": "VoltCore",
    "SUPPLIER_EMAIL": "s@voltcore.test",
    "MODULE_SERIAL": "M-001",
    "PACK_KWH": 77,
    "ORDER_QUANTITY": 2,
    "TELEMATICS_TIER": "STANDARD",
    "DELIVERY_METHOD": "DIRECT_DELIVERY",
    "REQUIRES_DEPOT_CHARGING": False,
    "PROJECT_CAPACITY_KW": 40,
    "INSTALL_WINDOW_START": "2026-10-01T00:00:00Z",
    "INSTALL_WINDOW_END": "2026-10-10T00:00:00Z",
    "CREW_COUNT": 1,
    "CENTER_NAME": "SC Bay 1",
    "REGION_CODE": "CA-N",
    "CENTER_STATE": "CA",
    "BAY_COUNT": 4,
    "VAN_CODE": "VAN-1",
    "VISIT_WINDOW_START": "2026-09-10T09:00:00Z",
    "VISIT_WINDOW_END": "2026-09-10T10:00:00Z",
    "VISIT_PURPOSE": "MAINTENANCE",
    "SKU": "BRK-1",
    "QTY_DELTA": 5,
    "REORDER_THRESHOLD": 1,
    "TARGET_VERSION": "2.0.0",
    "TELEMATICS_TIER_SCOPE": "ALL",
    "COMMITTED_UPTIME_PCT": 97.0,
    "MONTHLY_SERVICE_FEE_CENTS": 2000000,
    "PRO_RATING": "ROUTE_DAY",
    "MEASUREMENT_START_DATE": "2026-09-01",
    "DIAGNOSIS_NOTES": "Inspected on bench.",
    "DENIAL_REASON": "Not a covered defect.",
    "VIN_PREFIX": "VIN-ACME",
}


def create_fleet_customer_payload(**overrides) -> dict:
    payload = {
        "company_name": DEFAULTS["COMPANY_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
        "account_tier": DEFAULTS["ACCOUNT_TIER"],
    }
    payload.update(overrides)
    return payload


def create_depot_payload(fleet_customer_id, **overrides) -> dict:
    payload = {
        "fleet_customer_id": fleet_customer_id,
        "name": DEFAULTS["DEPOT_NAME"],
        "state_code": DEFAULTS["DEPOT_STATE"],
        "address": DEFAULTS["DEPOT_ADDRESS"],
        "total_capacity_kw": DEFAULTS["DEPOT_CAPACITY_KW"],
    }
    payload.update(overrides)
    return payload


def create_charging_project_payload(depot_id, expected_depot_version, **overrides) -> dict:
    payload = {
        "depot_id": depot_id,
        "requested_capacity_kw": DEFAULTS["PROJECT_CAPACITY_KW"],
        "install_window_start": DEFAULTS["INSTALL_WINDOW_START"],
        "install_window_end": DEFAULTS["INSTALL_WINDOW_END"],
        "crew_count": DEFAULTS["CREW_COUNT"],
        "expected_depot_version": expected_depot_version,
    }
    payload.update(overrides)
    return payload


def create_supplier_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["SUPPLIER_NAME"],
        "contact_email": DEFAULTS["SUPPLIER_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_battery_module_payload(supplier_id, **overrides) -> dict:
    payload = {
        "supplier_id": supplier_id,
        "module_serial": DEFAULTS["MODULE_SERIAL"],
        "pack_kwh": DEFAULTS["PACK_KWH"],
    }
    payload.update(overrides)
    return payload


def create_vehicle_order_payload(fleet_customer_id, depot_id, battery_supplier_id, **overrides) -> dict:
    payload = {
        "fleet_customer_id": fleet_customer_id,
        "depot_id": depot_id,
        "battery_supplier_id": battery_supplier_id,
        "quantity": DEFAULTS["ORDER_QUANTITY"],
        "battery_pack_kwh": DEFAULTS["PACK_KWH"],
        "telematics_tier": DEFAULTS["TELEMATICS_TIER"],
        "delivery_method": DEFAULTS["DELIVERY_METHOD"],
        "requires_depot_charging": DEFAULTS["REQUIRES_DEPOT_CHARGING"],
    }
    payload.update(overrides)
    return payload


def create_vehicle_payload(vehicle_order_id, battery_module_id, vin, expected_vehicle_order_version) -> dict:
    return {
        "vehicle_order_id": vehicle_order_id,
        "battery_module_id": battery_module_id,
        "vin": vin,
        "expected_vehicle_order_version": expected_vehicle_order_version,
    }


def create_service_center_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["CENTER_NAME"],
        "region_code": DEFAULTS["REGION_CODE"],
        "state_code": DEFAULTS["CENTER_STATE"],
        "bay_count": DEFAULTS["BAY_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_mobile_van_payload(service_center_id, **overrides) -> dict:
    payload = {
        "service_center_id": service_center_id,
        "van_code": DEFAULTS["VAN_CODE"],
    }
    payload.update(overrides)
    return payload


def create_service_visit_payload(vehicle_id, service_center_id=None, mobile_van_id=None, **overrides) -> dict:
    """Exactly one of service_center_id / mobile_van_id should be passed for a
    valid booking; pass both or neither to exercise the ERR_VALIDATION shape."""
    payload = {
        "vehicle_id": vehicle_id,
        "window_start": DEFAULTS["VISIT_WINDOW_START"],
        "window_end": DEFAULTS["VISIT_WINDOW_END"],
        "purpose": DEFAULTS["VISIT_PURPOSE"],
        "parts_lines": [],
    }
    if service_center_id is not None:
        payload["service_center_id"] = service_center_id
    if mobile_van_id is not None:
        payload["mobile_van_id"] = mobile_van_id
    payload.update(overrides)
    return payload


def create_parts_stock_payload(service_center_id, **overrides) -> dict:
    payload = {
        "service_center_id": service_center_id,
        "sku": DEFAULTS["SKU"],
        "qty_delta": DEFAULTS["QTY_DELTA"],
        "reorder_threshold": DEFAULTS["REORDER_THRESHOLD"],
    }
    payload.update(overrides)
    return payload


def create_software_campaign_payload(**overrides) -> dict:
    payload = {
        "target_version": DEFAULTS["TARGET_VERSION"],
        "telematics_tier_scope": DEFAULTS["TELEMATICS_TIER_SCOPE"],
    }
    payload.update(overrides)
    return payload


def create_uptime_contract_payload(fleet_customer_id, **overrides) -> dict:
    payload = {
        "fleet_customer_id": fleet_customer_id,
        "committed_uptime_pct": DEFAULTS["COMMITTED_UPTIME_PCT"],
        "monthly_service_fee_cents": DEFAULTS["MONTHLY_SERVICE_FEE_CENTS"],
        "pro_rating": DEFAULTS["PRO_RATING"],
        "measurement_start_date": DEFAULTS["MEASUREMENT_START_DATE"],
    }
    payload.update(overrides)
    return payload


def create_warranty_claim_payload(vehicle_id, claim_lines=None, service_visit_id=None, **overrides) -> dict:
    payload = {
        "vehicle_id": vehicle_id,
        "claim_lines": claim_lines if claim_lines is not None else [
            {"component_class": "POWERTRAIN", "part_cost_cents": 50000, "labor_hours": 2.0}
        ],
    }
    if service_visit_id is not None:
        payload["service_visit_id"] = service_visit_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Action payloads (non-create endpoints)
# ---------------------------------------------------------------------------

def clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}


def readiness_audit_payload(on_time_pct, first_pass_yield_pct, open_corrective_actions) -> dict:
    return {
        "on_time_pct": on_time_pct,
        "first_pass_yield_pct": first_pass_yield_pct,
        "open_corrective_actions": open_corrective_actions,
    }


def battery_health_payload(measured_soh_pct, measured_at) -> dict:
    return {"measured_soh_pct": measured_soh_pct, "measured_at": measured_at}


def campaign_result_payload(vehicle_id, result) -> dict:
    return {"vehicle_id": vehicle_id, "result": result}


def downtime_event_payload(vehicle_id, started_at, expected_uptime_contract_version, ended_at=None) -> dict:
    payload = {
        "vehicle_id": vehicle_id,
        "started_at": started_at,
        "expected_uptime_contract_version": expected_uptime_contract_version,
    }
    if ended_at is not None:
        payload["ended_at"] = ended_at
    return payload


def close_month_payload(month) -> dict:
    return {"month": month}


def diagnose_payload(diagnosis_notes=None) -> dict:
    return {"diagnosis_notes": DEFAULTS["DIAGNOSIS_NOTES"] if diagnosis_notes is None else diagnosis_notes}


def adjudicate_payload(decision, denial_reason=None) -> dict:
    payload = {"decision": decision}
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    return payload


def transition_payload(to_state, **extra) -> dict:
    """Generic transition body for order / project / module / visit / campaign
    endpoints; extra carries per-transition inputs such as
    exemption_document_ref or utility_denial_reason (omitted when None)."""
    payload = {"to_state": to_state}
    for key, value in extra.items():
        if value is not None:
            payload[key] = value
    return payload


def vehicle_transition_payload(dimension, to_state) -> dict:
    return {"dimension": dimension, "to_state": to_state}


def make_vin(seq: int) -> str:
    """Deterministic, globally unique VIN within a test run."""
    return f"{DEFAULTS['VIN_PREFIX']}-{seq:03d}"
