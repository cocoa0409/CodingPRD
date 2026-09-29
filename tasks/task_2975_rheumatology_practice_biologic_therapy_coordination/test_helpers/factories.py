"""Payload factories — one per write operation, input fields only.

Money is always an integer number of whole cents (PRD §2.7). Timestamp inputs
are full ISO 8601 UTC instants with three fractional digits; `date_of_birth` is
the only date-only field in the API.
"""
import itertools

from .constants import ADALIMUMAB, CLOCK_DEFAULT, INFLIXIMAB, MERIDIAN_PLAN, instant

_mrn_counter = itertools.count(1)
_npi_counter = itertools.count(1)
_name_counter = itertools.count(1)


def next_mrn() -> str:
    """A fresh `mrn`: 6 to 12 characters of uppercase A-Z and digits 0-9."""
    return f"RH{next(_mrn_counter):04d}"


def next_npi() -> str:
    """A fresh `npi`: exactly ten digits."""
    return f"12345{next(_npi_counter):05d}"


def _suffix() -> int:
    return next(_name_counter)


# --------------------------------------------------------------------------
# Reference data (PRD §3.1)
# --------------------------------------------------------------------------
def create_patient_payload(**overrides) -> dict:
    payload = {
        "mrn": next_mrn(),
        "full_name": "Pat One",
        "date_of_birth": "1975-04-12",
        "diagnosis_code": "RA_SEROPOSITIVE",
        "registry_consent": True,
    }
    payload.update(overrides)
    return payload


def create_clinician_payload(**overrides) -> dict:
    payload = {
        "npi": next_npi(),
        "full_name": "Ada Rheum",
        "role_type": "RHEUMATOLOGIST",
        "can_attest_formulary_exception": True,
    }
    payload.update(overrides)
    return payload


def create_nurse_payload(**overrides) -> dict:
    payload = {
        "npi": next_npi(),
        "full_name": "Nia Nurse",
        "role_type": "NURSE",
    }
    payload.update(overrides)
    return payload


def create_drug_payload(**overrides) -> dict:
    payload = {
        "name": f"Drug {_suffix()}",
        "molecule_class": "TNFI",
        "route": "IV",
        "formulary_tier": 3,
        "acquisition_cost_cents": 250_050,
        "admin_time_minutes": 150,
        "monitoring_panel_type": "CMP",
        "monitoring_panel_interval_days": 90,
    }
    payload.update(overrides)
    return payload


def infliximab_payload(**overrides) -> dict:
    """The canonical IV TNFI product: 250050 cents, 150 minutes, CMP / 90 days."""
    payload = dict(INFLIXIMAB)
    payload.update(overrides)
    return payload


def adalimumab_payload(**overrides) -> dict:
    """The canonical SC TNFI product: 187333 cents, 0 minutes, CBC / 180 days."""
    payload = dict(ADALIMUMAB)
    payload.update(overrides)
    return payload


def create_payer_plan_payload(**overrides) -> dict:
    payload = dict(MERIDIAN_PLAN)
    payload["name"] = f"Plan {_suffix()}"
    payload.update(overrides)
    return payload


def meridian_plan_payload(**overrides) -> dict:
    """The canonical dual-benefit PREFER_AMBULATORY plan."""
    payload = dict(MERIDIAN_PLAN)
    payload.update(overrides)
    return payload


def create_infusion_chair_payload(**overrides) -> dict:
    payload = {
        "label": f"AIC-{_suffix()}",
        "site_type": "AMBULATORY_INFUSION_CENTER",
        "turnover_buffer_minutes": 30,
    }
    payload.update(overrides)
    return payload


def update_infusion_chair_payload(status: str = "CLOSED", **overrides) -> dict:
    payload = {"status": status}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Visits (PRD §3.2)
# --------------------------------------------------------------------------
def create_visit_payload(patient_id: str, clinician_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "clinician_id": clinician_id,
        "visit_datetime": instant(2026, 8, 3, 14, 0, 0),
        "visit_type": "FOLLOW_UP",
    }
    payload.update(overrides)
    return payload


def score_visit_cdai_payload(**overrides) -> dict:
    """CDAI requires all four components; CRP and ESR are ignored outright."""
    payload = {
        "scoring_instrument": "CDAI",
        "tender_joint_count": 2,
        "swollen_joint_count": 1,
        "patient_global_assessment": 3.0,
        "physician_global_assessment": 3.0,
    }
    payload.update(overrides)
    return payload


def score_visit_das28_payload(**overrides) -> dict:
    """DAS28_CRP requires `crp_mg_dl`; `physician_global_assessment` is ignored."""
    payload = {
        "scoring_instrument": "DAS28_CRP",
        "tender_joint_count": 2,
        "swollen_joint_count": 1,
        "patient_global_assessment": 3.0,
        "crp_mg_dl": 2.5,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Screening records (PRD §3.3)
# --------------------------------------------------------------------------
def create_screening_record_payload(patient_id: str, screen_type: str, result: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "screen_type": screen_type,
        "result": result,
        "collected_at": instant(2026, 7, 20),
        "resulted_at": instant(2026, 7, 21),
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Therapy episodes (PRD §3.4, §3.9)
# --------------------------------------------------------------------------
def create_therapy_episode_payload(
    patient_id: str,
    drug_id: str,
    payer_plan_id: str,
    expected_patient_version: int,
    **overrides,
) -> dict:
    payload = {
        "patient_id": patient_id,
        "drug_id": drug_id,
        "payer_plan_id": payer_plan_id,
        "therapy_start_at": CLOCK_DEFAULT,
        "expected_patient_version": expected_patient_version,
    }
    payload.update(overrides)
    return payload


def hold_episode_payload(hold_reason: str = "SURGERY", **overrides) -> dict:
    payload = {"hold_reason": hold_reason}
    payload.update(overrides)
    return payload


def resume_episode_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


def discontinue_episode_payload(discontinuation_reason: str = "PATIENT_REQUEST", **overrides) -> dict:
    payload = {"discontinuation_reason": discontinuation_reason}
    payload.update(overrides)
    return payload


def record_training_payload(outcome: str = "PASSED", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Monitoring labs (PRD §3.6)
# --------------------------------------------------------------------------
def create_monitoring_lab_payload(episode_id: str, **overrides) -> dict:
    payload = {
        "episode_id": episode_id,
        "panel_type": "CMP",
        "collected_at": instant(2026, 7, 25),
        "alt_u_l": 30.0,
        "neutrophil_k_ul": 3.20,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Authorizations (PRD §3.5)
# --------------------------------------------------------------------------
def create_authorization_payload(
    episode_id: str, expected_episode_version: int, requested_units: int = 6, **overrides
) -> dict:
    payload = {
        "episode_id": episode_id,
        "requested_units": requested_units,
        "expected_episode_version": expected_episode_version,
    }
    payload.update(overrides)
    return payload


def approve_determination_payload(**overrides) -> dict:
    payload = {"decision": "APPROVED"}
    payload.update(overrides)
    return payload


def deny_determination_payload(
    decision_reason: str = "MEDICAL_NECESSITY_NOT_ESTABLISHED", **overrides
) -> dict:
    payload = {"decision": "DENIED", "decision_reason": decision_reason}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Infusion appointments (PRD §3.7)
# --------------------------------------------------------------------------
def create_appointment_payload(episode_id: str, chair_id: str, **overrides) -> dict:
    payload = {
        "episode_id": episode_id,
        "chair_id": chair_id,
        "scheduled_start": instant(2026, 8, 12, 9, 0, 0),
    }
    payload.update(overrides)
    return payload


def cancel_appointment_payload(cancellation_reason: str = "PATIENT_REQUEST", **overrides) -> dict:
    payload = {"cancellation_reason": cancellation_reason}
    payload.update(overrides)
    return payload


def reverse_administration_payload(reversal_reason: str = "DOCUMENTATION_ERROR", **overrides) -> dict:
    payload = {"reversal_reason": reversal_reason}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Assistance enrollments (PRD §3.8)
# --------------------------------------------------------------------------
def create_assistance_enrollment_payload(episode_id: str, **overrides) -> dict:
    payload = {
        "episode_id": episode_id,
        "program_type": "MANUFACTURER_COPAY_CARD",
        "annual_benefit_cents": 500_000,
        "coverage_start": CLOCK_DEFAULT,
    }
    payload.update(overrides)
    return payload


def reauthorize_enrollment_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload
