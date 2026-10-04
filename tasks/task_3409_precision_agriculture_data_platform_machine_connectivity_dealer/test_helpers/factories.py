"""Payload factories — one per creatable resource, input fields only.

Defaults mirror the shared anchor scenario used across the design instances
(org "Prairie View Farms" in US-IA, dealer "D-100", machine model "M8R"
manufactured 2025-09-01).  Fields the platform declares unique
(serial_number, modem_imei, dealer_code, package_code, batch_id) get an
auto-incremented suffix so multiple creates inside one test never collide;
pass explicit overrides when a test needs a specific value.
"""

import itertools

from .constants import CLOCK_START_UTC

_counter = itertools.count(1)


def _next(tag):
    return "{0}-{1}".format(tag, next(_counter))


# --- Organizations ---------------------------------------------------------


def create_organization_payload(**overrides):
    defaults = {
        "name": "Prairie View Farms",
        "region_code": "US-IA",
    }
    defaults.update(overrides)
    return defaults


# --- Dealers ---------------------------------------------------------------


def create_dealer_payload(**overrides):
    defaults = {
        "dealer_code": _next("D"),
        "name": "River Valley Equipment",
        "region_code": "US-IA",
        "service_tier": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


# --- Machines ---------------------------------------------------------------


def create_machine_payload(organization_id, selling_dealer_id, **overrides):
    defaults = {
        "organization_id": organization_id,
        "serial_number": _next("SN"),
        "model_code": "M8R",
        "selling_dealer_id": selling_dealer_id,
        "modem_imei": _next("IMEI"),
        "manufacture_date": "2025-09-01",
    }
    defaults.update(overrides)
    return defaults


def telemetry_batch_payload(**overrides):
    defaults = {
        "batch_id": _next("batch"),
        "start_hour_iso": CLOCK_START_UTC,
        "hour_count": 1,
        "payload_mb": 100,
    }
    defaults.update(overrides)
    return defaults


# --- Data plans ---------------------------------------------------------------


def create_data_plan_payload(organization_id, machine_id, **overrides):
    defaults = {
        "organization_id": organization_id,
        "machine_id": machine_id,
        "tier": "STANDARD",
        "proration_method": "CALENDAR_DAY",
    }
    defaults.update(overrides)
    return defaults


def change_tier_payload(new_tier, expected_plan_version):
    return {"new_tier": new_tier, "expected_plan_version": expected_plan_version}


# --- Field boundaries ------------------------------------------------------------


def create_field_boundary_payload(organization_id, **overrides):
    defaults = {
        "organization_id": organization_id,
        "name": "North 40",
        "season_year": 2026,
        "area_hectares": 50.00,
    }
    defaults.update(overrides)
    return defaults


# --- Prescriptions ------------------------------------------------------------------


def prescription_zone(zone_id="z1", rate_l_per_ha=3.00, area_ha=10.00):
    return {"zone_id": zone_id, "rate_l_per_ha": rate_l_per_ha, "area_ha": area_ha}


def create_prescription_payload(
    organization_id,
    field_boundary_id,
    machine_id,
    expected_field_boundary_version,
    **overrides
):
    defaults = {
        "organization_id": organization_id,
        "field_boundary_id": field_boundary_id,
        "machine_id": machine_id,
        "crop_type": "CORN",
        "zones": [prescription_zone()],
        "valid_from": "2026-09-01T00:00:00Z",
        "valid_until": "2026-09-30T00:00:00Z",
        "expected_field_boundary_version": expected_field_boundary_version,
    }
    defaults.update(overrides)
    return defaults


def as_applied_payload(**overrides):
    defaults = {"applied_total_liters": 29.50, "applied_coverage_ha": 9.80}
    defaults.update(overrides)
    return defaults


# --- Data share grants -----------------------------------------------------------------


def create_data_share_grant_payload(organization_id, **overrides):
    defaults = {
        "organization_id": organization_id,
        "grantee_type": "AGRONOMIST",
        "grantee_ref_id": "agron-ada",
        "scopes": ["TELEMATICS"],
        "valid_from": "2026-01-01T00:00:00Z",
        "valid_until": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# --- Consent tickets ---------------------------------------------------------------------


def create_consent_ticket_payload(organization_id, machine_id, requester_ref_id, **overrides):
    defaults = {
        "organization_id": organization_id,
        "machine_id": machine_id,
        "ticket_type": "REMOTE_DIAGNOSTIC",
        "requester_ref_id": requester_ref_id,
    }
    defaults.update(overrides)
    return defaults


# --- Diagnostic sessions --------------------------------------------------------------------


def create_diagnostic_session_payload(machine_id, consent_ticket_id, **overrides):
    defaults = {"machine_id": machine_id, "consent_ticket_id": consent_ticket_id}
    defaults.update(overrides)
    return defaults


def close_session_payload(**overrides):
    defaults = {"fault_found": False}
    defaults.update(overrides)
    return defaults


# --- Software packages --------------------------------------------------------------------------


def create_software_package_payload(**overrides):
    defaults = {
        "package_code": _next("FW"),
        "target_model_code": "M8R",
        "firmware_version": "10.2.0",
        "size_mb": 800,
        "mandatory": False,
    }
    defaults.update(overrides)
    return defaults


# --- Update deliveries -----------------------------------------------------------------------------


def create_update_delivery_payload(machine_id, package_id, **overrides):
    defaults = {"machine_id": machine_id, "package_id": package_id}
    defaults.update(overrides)
    return defaults


# --- Feature licenses ---------------------------------------------------------------------------------


def create_feature_license_payload(machine_id, expected_machine_version, **overrides):
    defaults = {
        "machine_id": machine_id,
        "feature_code": "AUTO_GUIDANCE",
        "license_type": "PERPETUAL",
        "expected_machine_version": expected_machine_version,
    }
    defaults.update(overrides)
    return defaults


# --- Warranty claims --------------------------------------------------------------------------------------


def create_warranty_claim_payload(machine_id, **overrides):
    defaults = {
        "machine_id": machine_id,
        "claim_amount_cents": 500000,
        "parts_amount_cents": 200000,
        "description": "Alternator failure",
    }
    defaults.update(overrides)
    return defaults


# --- Integration partners ------------------------------------------------------------------------------------


def create_integration_partner_payload(**overrides):
    defaults = {"name": "AgriSight Analytics", "api_quota_calls_per_day": 100}
    defaults.update(overrides)
    return defaults


def data_pull_payload(organization_id, scope="TELEMATICS"):
    return {"organization_id": organization_id, "scope": scope}
