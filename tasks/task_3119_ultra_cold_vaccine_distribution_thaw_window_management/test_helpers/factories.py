"""Payload factories — one per resource, input fields only."""

DEFAULTS = {
    "PRODUCT_CODE": "PZ-UCV-2026",
    "PRESENTATION": "MULTI_DOSE_VIAL",
    "DOSES_PER_VIAL": 6,
    "VIALS_PER_CARTON": 195,
    "MIN_ORDER_CARTONS": 1,
    "JURISDICTION_CODE": "MI",
    "REGULATORY_BODY": "MI Department of Health",
    "WEEKLY_ALLOCATION_CAP": 20,
    "PROGRAM_MIN_ORDER_CARTONS": 2,
    "RESERVABLE_CARTON_PCT": 0.5,
    "ACCEPTANCE_WINDOW_HOURS": 48,
    "SHIPPING_CUTOFF_UTC": "14:00:00",
    "QUARANTINE_ON_REVIEW": True,
    "ADJUDICATION_SLA_HOURS": 72,
    "SEGMENT_RULE": "TIE_CONTINUE",
    "REPORTING_PERIOD_DAYS": 30,
    "BATCH_CODE": "UCV-BATCH-0001",
    "RELEASED_CARTONS": 12,
    "RELEASE_DATE": "2026-09-01T00:00:00Z",
    "EXPIRY_DATE": "2027-09-01T00:00:00Z",
    "OPENS_AT": "2026-09-01T00:00:00Z",
    "CLOSES_AT": "2026-09-03T00:00:00Z",
    "SITE_CODE": "MI-RIV-01",
    "SITE_NAME": "Riverbend Clinic",
    "ULTRA_COLD_CAPACITY": 10,
    "REFRIGERATED_CAPACITY": 10,
    "EXPECTED_WEEKLY_DOSES": 3000,
    "CERT_EXPIRES_AT": "2027-01-01T00:00:00Z",
    "CERT_NUMBER": "CERT-MI-0001",
    "VERIFIED_AT": "2026-09-01T00:00:00Z",
    "SHIPPER_SERIAL": "SH-0001",
    "LOGGER_SERIAL": "LG-0001",
    "DRY_ICE_KG": 20,
    "PACKING_STARTED_AT": "2026-09-01T00:00:00Z",
    "CARTON_SERIAL": "C-01",
}

SHIPPING_DAYS = ["TUESDAY", "WEDNESDAY", "FRIDAY"]


def create_product_configuration_payload(**overrides) -> dict:
    payload = {
        "product_code": DEFAULTS["PRODUCT_CODE"],
        "presentation": DEFAULTS["PRESENTATION"],
        "doses_per_vial": DEFAULTS["DOSES_PER_VIAL"],
        "vials_per_carton": DEFAULTS["VIALS_PER_CARTON"],
        "min_order_cartons": DEFAULTS["MIN_ORDER_CARTONS"],
        "ultra_cold_min_c": -90,
        "ultra_cold_max_c": -60,
        "refrigerated_min_c": 2,
        "refrigerated_max_c": 8,
        "thaw_stability_hours": 120,
        "refrigerated_shelf_life_hours": 720,
        "excursion_tolerance_min_c": -50,
        "excursion_max_single_breach_minutes": 180,
        "excursion_max_cumulative_minutes": 360,
        "refreeze_prohibited": True,
        "punctured_bud_hours": 6,
        "wastage_threshold_pct": 0.05,
    }
    payload.update(overrides)
    return payload


def create_jurisdiction_program_payload(**overrides) -> dict:
    payload = {
        "jurisdiction_code": DEFAULTS["JURISDICTION_CODE"],
        "regulatory_body": DEFAULTS["REGULATORY_BODY"],
        "allocation_basis": "FIXED_QUANTITY",
        "fixed_weekly_cartons": 20,
        "weekly_allocation_cap_cartons": DEFAULTS["WEEKLY_ALLOCATION_CAP"],
        "min_order_cartons": DEFAULTS["PROGRAM_MIN_ORDER_CARTONS"],
        "reservable_carton_pct": DEFAULTS["RESERVABLE_CARTON_PCT"],
        "acceptance_window_hours": DEFAULTS["ACCEPTANCE_WINDOW_HOURS"],
        "shipping_days": list(SHIPPING_DAYS),
        "shipping_cutoff_utc": DEFAULTS["SHIPPING_CUTOFF_UTC"],
        "quarantine_on_review": DEFAULTS["QUARANTINE_ON_REVIEW"],
        "adjudication_sla_hours": DEFAULTS["ADJUDICATION_SLA_HOURS"],
        "segment_rule": DEFAULTS["SEGMENT_RULE"],
        "reporting_period_days": DEFAULTS["REPORTING_PERIOD_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_allocation_batch_payload(product_configuration_id: str,
                                    jurisdiction_program_id: str,
                                    **overrides) -> dict:
    payload = {
        "batch_code": DEFAULTS["BATCH_CODE"],
        "product_configuration_id": product_configuration_id,
        "jurisdiction_program_id": jurisdiction_program_id,
        "released_cartons": DEFAULTS["RELEASED_CARTONS"],
        "release_date": DEFAULTS["RELEASE_DATE"],
        "expiry_date": DEFAULTS["EXPIRY_DATE"],
    }
    payload.update(overrides)
    return payload


def create_carton_payload(**overrides) -> dict:
    payload = {
        "carton_serial": DEFAULTS["CARTON_SERIAL"],
        "vials_per_carton": DEFAULTS["VIALS_PER_CARTON"],
    }
    payload.update(overrides)
    return payload


def create_allocation_window_payload(allocation_batch_id: str,
                                     jurisdiction_program_id: str,
                                     **overrides) -> dict:
    payload = {
        "allocation_batch_id": allocation_batch_id,
        "jurisdiction_program_id": jurisdiction_program_id,
        "opens_at": DEFAULTS["OPENS_AT"],
        "closes_at": DEFAULTS["CLOSES_AT"],
    }
    payload.update(overrides)
    return payload


def create_storage_site_payload(jurisdiction_program_id: str, **overrides) -> dict:
    payload = {
        "site_code": DEFAULTS["SITE_CODE"],
        "site_name": DEFAULTS["SITE_NAME"],
        "jurisdiction_program_id": jurisdiction_program_id,
        "storage_capability": "ULTRA_COLD",
        "ultra_cold_capacity_cartons": DEFAULTS["ULTRA_COLD_CAPACITY"],
        "refrigerated_capacity_cartons": DEFAULTS["REFRIGERATED_CAPACITY"],
        "cold_chain_equipment_type": "ULTRA_COLD_FREEZER",
        "equipment_certificate_expires_at": DEFAULTS["CERT_EXPIRES_AT"],
        "expected_weekly_doses": DEFAULTS["EXPECTED_WEEKLY_DOSES"],
    }
    payload.update(overrides)
    return payload


def create_equipment_verification_payload(storage_site_id: str, **overrides) -> dict:
    payload = {
        "storage_site_id": storage_site_id,
        "equipment_type": "ULTRA_COLD_FREEZER",
        "certificate_number": DEFAULTS["CERT_NUMBER"],
        "certificate_expires_at": DEFAULTS["CERT_EXPIRES_AT"],
        "verified_at": DEFAULTS["VERIFIED_AT"],
        "outcome": "PASSED",
    }
    payload.update(overrides)
    return payload


def create_site_order_payload(allocation_entitlement_id: str,
                              storage_site_id: str,
                              **overrides) -> dict:
    payload = {
        "allocation_entitlement_id": allocation_entitlement_id,
        "storage_site_id": storage_site_id,
        "requested_cartons": 2,
        "requested_doses": 1000,
    }
    payload.update(overrides)
    return payload


def create_dispatch_payload(site_order_id: str, storage_site_id: str, **overrides) -> dict:
    payload = {
        "site_order_id": site_order_id,
        "storage_site_id": storage_site_id,
        "entry_route": "DIRECT_ULTRA_COLD",
    }
    payload.update(overrides)
    return payload


def create_shipper_payload(dispatch_order_id: str, **overrides) -> dict:
    payload = {
        "dispatch_order_id": dispatch_order_id,
        "shipper_serial": DEFAULTS["SHIPPER_SERIAL"],
        "dry_ice_kg": DEFAULTS["DRY_ICE_KG"],
        "packing_started_at": DEFAULTS["PACKING_STARTED_AT"],
        "logger_serial": DEFAULTS["LOGGER_SERIAL"],
    }
    payload.update(overrides)
    return payload


def create_logger_reading_payload(cold_chain_shipper_id: str, **overrides) -> dict:
    payload = {
        "cold_chain_shipper_id": cold_chain_shipper_id,
        "recorded_at": "2026-09-01T01:00:00Z",
        "temperature_c": -75,
        "source": "LOGGER",
    }
    payload.update(overrides)
    return payload


def create_transfer_payload(from_site_id: str, to_site_id: str, carton_id: str,
                            **overrides) -> dict:
    payload = {
        "from_site_id": from_site_id,
        "to_site_id": to_site_id,
        "carton_id": carton_id,
        "requested_at": "2026-09-01T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_excursion_payload(carton_id: str, storage_site_id: str, **overrides) -> dict:
    payload = {
        "carton_id": carton_id,
        "storage_site_id": storage_site_id,
        "first_breach_at": "2026-09-01T09:00:00Z",
        "last_breach_at": "2026-09-01T10:00:00Z",
        "min_temperature_c": -55,
        "reported_at": "2026-09-01T10:05:00Z",
    }
    payload.update(overrides)
    return payload


def create_slice_payload(**overrides) -> dict:
    payload = {
        "closure_state": "OPEN",
        "time_slice_c": -65,
        "doses_upper_bound": 200,
    }
    payload.update(overrides)
    return payload


def create_ledger_entry_payload(carton_id: str, entry_type: str, quantity_doses: int,
                                **overrides) -> dict:
    payload = {
        "carton_id": carton_id,
        "entry_type": entry_type,
        "quantity_doses": quantity_doses,
        "occurred_at": "2026-09-01T09:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_reservation_payload(storage_site_id: str, carton_id: str, **overrides) -> dict:
    payload = {
        "storage_site_id": storage_site_id,
        "carton_id": carton_id,
        "entry_type": "ULTRA_COLD",
        "temp_state": "FROZEN",
        "reserved_capacity_cartons": 6,
        "start_at": "2026-09-01T09:00:00Z",
        "end_at": "2026-09-01T12:00:00Z",
        "resolve_method": "RESERVATION_BOUNDARY",
    }
    payload.update(overrides)
    return payload


def create_carton_family_payload(site_id: str, member_site_id: str, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "member_site_id": member_site_id,
        "linked_at": "2026-09-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_reporting_period_payload(jurisdiction_program_id: str, **overrides) -> dict:
    payload = {
        "jurisdiction_program_id": jurisdiction_program_id,
        "period_start": "2026-09-01T00:00:00Z",
        "period_end": "2026-09-08T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_wastage_report_payload(excursion_adjudication_id: str, **overrides) -> dict:
    payload = {
        "excursion_adjudication_id": excursion_adjudication_id,
        "accounting_period_start": "2026-09-01T00:00:00Z",
        "accounting_period_end": "2026-09-08T00:00:00Z",
        "reported_at": "2026-09-02T00:00:00Z",
        "attributed_cause": "TEMPERATURE_EXCURSION",
        "doses_reported": 117,
    }
    payload.update(overrides)
    return payload