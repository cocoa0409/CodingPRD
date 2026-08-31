"""Payload factories — one per resource, input fields only."""
import itertools

from .constants import CLOCK_EPOCH, TEST_DEFAULTS

_mrn_counter = itertools.count(1)


def next_mrn(prefix: str = "MRN") -> str:
    """Medical record numbers must be unique across every Patient row (PRD §3.1)."""
    return f"{prefix}-{next(_mrn_counter):05d}"


def payer_payload(**overrides) -> dict:
    payload = {
        "name": "Lakeside Choice",
        "coinsurance_pct": TEST_DEFAULTS["COINSURANCE_PCT"],
        "snf_auth_required": False,
        "hh_auth_required": False,
        "auth_expiry_days": TEST_DEFAULTS["AUTH_EXPIRY_DAYS"],
    }
    payload.update(overrides)
    return payload


def patient_payload(primary_payer_id: str, **overrides) -> dict:
    payload = {
        "mrn": next_mrn(),
        "full_name": "Ada Lin",
        "date_of_birth": "1948-03-12",
        "primary_payer_id": primary_payer_id,
        "prior_admissions_180d": 2,
        "lives_alone": False,
        "has_pcp": True,
    }
    payload.update(overrides)
    return payload


def provider_payload(**overrides) -> dict:
    payload = {
        "name": "Cedar SNF",
        "provider_type": "SNF",
        "quality_star_rating": 4,
        "distance_miles_from_hospital": 6,
        "bed_unit_codes": ["UNIT-A", "UNIT-B"],
    }
    payload.update(overrides)
    return payload


def network_contract_payload(payer_id: str, provider_id: str, **overrides) -> dict:
    payload = {
        "payer_id": payer_id,
        "provider_id": provider_id,
        "in_network": True,
        "negotiated_daily_rate_cents": 30000,
    }
    payload.update(overrides)
    return payload


def vehicle_payload(**overrides) -> dict:
    payload = {
        "operator_name": "Valley Medi-Ride",
        "vehicle_type": "WHEELCHAIR_VAN",
        "base_rate_cents": TEST_DEFAULTS["VEHICLE_BASE_RATE_CENTS"],
        "per_mile_cents": TEST_DEFAULTS["VEHICLE_PER_MILE_CENTS"],
    }
    payload.update(overrides)
    return payload


def episode_payload(patient_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "admission_type": "EMERGENT",
        "drg_code": TEST_DEFAULTS["DRG_CODE"],
        "drg_gmlos_days": TEST_DEFAULTS["DRG_GMLOS_DAYS"],
        "attending_unit": TEST_DEFAULTS["ATTENDING_UNIT"],
        "admitted_at": CLOCK_EPOCH,
    }
    payload.update(overrides)
    return payload


def screening_payload(**overrides) -> dict:
    payload = {
        "screening_type": "ADMISSION",
        "functional_score": 8,
        "cognitive_score": 8,
        "social_support_score": 4,
        "medication_count": 10,
    }
    payload.update(overrides)
    return payload


def barrier_payload(**overrides) -> dict:
    payload = {
        "barrier_code": "TRANSPORT",
        "severity": "MEDIUM",
        "delay_reason_code": "AWAITING_TRANSPORT",
    }
    payload.update(overrides)
    return payload


def referral_payload(**overrides) -> dict:
    payload = {
        "requested_level_of_care": "SNF",
        "projected_stay_days": 14,
        "needed_by": "2026-08-20T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def offer_payload(expected_referral_version: int, **overrides) -> dict:
    payload = {
        "expected_referral_version": expected_referral_version,
        "bed_unit_code": "UNIT-A",
        "bed_available_from": "2026-08-05T00:00:00Z",
        "hold_expires_at": "2026-08-12T00:00:00Z",
        "daily_rate_cents": 30000,
    }
    payload.update(overrides)
    return payload


def authorization_payload(provider_id: str, **overrides) -> dict:
    payload = {
        "provider_id": provider_id,
        "level_of_care": "SNF",
        "requested_days": 14,
        "billed_daily_rate_cents": 30000,
    }
    payload.update(overrides)
    return payload


def transport_order_payload(expected_episode_version: int, vehicle_id: str, **overrides) -> dict:
    payload = {
        "expected_episode_version": expected_episode_version,
        "order_type": "PATIENT_TRANSPORT",
        "vehicle_id": vehicle_id,
        "mileage_miles": 12,
        "window_start": "2026-08-02T14:00:00Z",
        "window_end": "2026-08-02T15:00:00Z",
    }
    payload.update(overrides)
    return payload


def dme_order_payload(expected_episode_version: int, supplier_provider_id: str, **overrides) -> dict:
    payload = {
        "expected_episode_version": expected_episode_version,
        "order_type": "DME_DELIVERY",
        "supplier_provider_id": supplier_provider_id,
        "item_code": "HOSPITAL_BED",
        "window_start": "2026-08-02T09:00:00Z",
        "window_end": "2026-08-02T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def document_choice_payload(chosen_bed_offer_id: str, **overrides) -> dict:
    payload = {
        "chosen_bed_offer_id": chosen_bed_offer_id,
        "patient_choice_attested": True,
        "choice_basis": "PATIENT_PREFERENCE",
    }
    payload.update(overrides)
    return payload
