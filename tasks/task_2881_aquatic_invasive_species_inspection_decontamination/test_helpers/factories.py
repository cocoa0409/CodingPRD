"""Payload factories — one per endpoint body, input fields only.

Every monetary amount is emitted as a JSON number in whole cents, and every
instant is emitted as a full ISO 8601 UTC instant, never a bare date.
"""
import itertools

from .constants import (
    BASE_INSPECTION_FEE_CENTS,
    DEFAULT_CLOCK_UTC,
    SEASON_CLOSES_AT,
    SEASON_OPENS_AT,
)

_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


DEFAULTS = {
    "WATER_BODY_NAME": "Flathead Lake",
    "STATE_CODE": "MT",
    "STATION_NAME": "Somers Access",
    "INSPECTOR_NAME": "Ada Field",
    "MODULE_CODE": "AIS-101",
    "SPECIES_CODE": "DREISSENA",
    "CAMPAIGN_NAME": "Clean Drain Dry",
    "CAMPAIGN_BUDGET_CENTS": 100000,
    "HULL_LENGTH_FT": 22.5,
}


# --- WaterBody -----------------------------------------------------------
def water_body_payload(**overrides) -> dict:
    payload = {
        "name": f"{DEFAULTS['WATER_BODY_NAME']} {_next()}",
        "state_code": DEFAULTS["STATE_CODE"],
        "water_body_class": "LAKE",
    }
    payload.update(overrides)
    return payload


def water_body_patch_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


# --- InspectionStation ---------------------------------------------------
def station_payload(**overrides) -> dict:
    payload = {
        "name": f"{DEFAULTS['STATION_NAME']} {_next()}",
        "station_type": "WATERBODY_ACCESS",
    }
    payload.update(overrides)
    return payload


def station_status_payload(target_status, **overrides) -> dict:
    payload = {"target_status": target_status}
    payload.update(overrides)
    return payload


def station_hours_payload(**overrides) -> dict:
    payload = {
        "opens_at": SEASON_OPENS_AT,
        "closes_at": SEASON_CLOSES_AT,
    }
    payload.update(overrides)
    return payload


# --- Inspector -----------------------------------------------------------
def inspector_payload(home_station_id, **overrides) -> dict:
    payload = {
        "full_name": f"{DEFAULTS['INSPECTOR_NAME']} {_next()}",
        "home_station_id": home_station_id,
    }
    payload.update(overrides)
    return payload


def inspector_status_payload(target_status, **overrides) -> dict:
    payload = {"target_status": target_status}
    payload.update(overrides)
    return payload


def training_record_payload(hours, passed=True, **overrides) -> dict:
    payload = {
        "module_code": f"{DEFAULTS['MODULE_CODE']}-{_next()}",
        "hours": hours,
        "passed": passed,
        "completed_at": DEFAULT_CLOCK_UTC,
    }
    payload.update(overrides)
    return payload


# --- Watercraft ----------------------------------------------------------
def watercraft_payload(**overrides) -> dict:
    payload = {
        "registration_number": f"MT-{9000 + _next()}",
        "home_state_code": "MT",
        "vessel_type": "OPEN_HULL",
        "hull_length_ft": DEFAULTS["HULL_LENGTH_FT"],
    }
    payload.update(overrides)
    return payload


# --- ReciprocityAgreement -----------------------------------------------
def reciprocity_agreement_payload(partner_state_code="ID",
                                  accepted_seal_prefix="ID-",
                                  **overrides) -> dict:
    payload = {
        "partner_state_code": partner_state_code,
        "accepted_seal_prefix": accepted_seal_prefix,
    }
    payload.update(overrides)
    return payload


def reciprocity_status_payload(target_status, **overrides) -> dict:
    payload = {"target_status": target_status}
    payload.update(overrides)
    return payload


# --- InspectionRecord ----------------------------------------------------
def inspection_record_payload(station_id, watercraft_id, arrived_at, **overrides) -> dict:
    payload = {
        "station_id": station_id,
        "watercraft_id": watercraft_id,
        "arrived_at": arrived_at,
    }
    payload.update(overrides)
    return payload


def screening_payload(expected_watercraft_version,
                      residual_water_present=False,
                      **overrides) -> dict:
    payload = {
        "expected_watercraft_version": expected_watercraft_version,
        "residual_water_present": residual_water_present,
    }
    payload.update(overrides)
    return payload


def disposition_payload(disposition, **overrides) -> dict:
    payload = {"disposition": disposition}
    payload.update(overrides)
    return payload


def enforcement_payload(action, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


# --- DeconOrder ----------------------------------------------------------
def decon_order_payload(inspection_record_id,
                        expected_inspection_record_version,
                        **overrides) -> dict:
    payload = {
        "inspection_record_id": inspection_record_id,
        "expected_inspection_record_version": expected_inspection_record_version,
    }
    payload.update(overrides)
    return payload


def treatment_payload(water_temp_f=140, pressure_psi=3000, dwell_seconds=120,
                      **overrides) -> dict:
    payload = {
        "water_temp_f": water_temp_f,
        "pressure_psi": pressure_psi,
        "dwell_seconds": dwell_seconds,
    }
    payload.update(overrides)
    return payload


def dry_verification_payload(outcome, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


# --- QuarantineOrder -----------------------------------------------------
def quarantine_order_payload(inspection_record_id, seal_number, **overrides) -> dict:
    payload = {
        "inspection_record_id": inspection_record_id,
        "seal_number": seal_number,
    }
    payload.update(overrides)
    return payload


def release_request_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def release_decision_payload(outcome, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def breach_report_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


# --- DetectionReport -----------------------------------------------------
def detection_report_payload(inspection_record_id,
                             detection_class="LIVE_ORGANISM",
                             **overrides) -> dict:
    payload = {
        "inspection_record_id": inspection_record_id,
        "species_code": DEFAULTS["SPECIES_CODE"],
        "detection_class": detection_class,
    }
    payload.update(overrides)
    return payload


def submission_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def acknowledgement_payload(verdict, **overrides) -> dict:
    payload = {"verdict": verdict}
    payload.update(overrides)
    return payload


# --- EducationCampaign ---------------------------------------------------
def campaign_payload(target_water_body_id, start_at, end_at,
                     budget_cents=DEFAULTS["CAMPAIGN_BUDGET_CENTS"],
                     **overrides) -> dict:
    payload = {
        "name": f"{DEFAULTS['CAMPAIGN_NAME']} {_next()}",
        "target_water_body_id": target_water_body_id,
        "start_at": start_at,
        "end_at": end_at,
        "budget_cents": budget_cents,
    }
    payload.update(overrides)
    return payload


def campaign_status_payload(target_status, **overrides) -> dict:
    payload = {"target_status": target_status}
    payload.update(overrides)
    return payload


def campaign_evaluation_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


# --- Logical clock -------------------------------------------------------
def clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}


BASE_FEE_CENTS = BASE_INSPECTION_FEE_CENTS
