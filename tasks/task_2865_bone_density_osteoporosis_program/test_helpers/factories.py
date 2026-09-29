"""Request-body builders.

Every builder returns a plain dict with the specification's required fields
filled in with valid values, and accepts keyword overrides. Numeric quantities
are emitted as JSON numbers, never as strings.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    BMD_FEMORAL_NECK_OSTEOPENIC,
    BMD_LUMBAR_OSTEOPENIC,
    BMD_TOTAL_HIP_OSTEOPENIC,
    FEMORAL_NECK_REFERENCE,
    FOREARM_REFERENCE,
    LUMBAR_REFERENCE,
    PHANTOM_BASELINE_BMD,
    PHANTOM_BASELINE_SD,
    TOTAL_HIP_REFERENCE,
)

_serial_counter = itertools.count(1)
_mrn_counter = itertools.count(1)
_payer_counter = itertools.count(1)


def unique_serial_number(prefix: str = "HLG") -> str:
    return f"{prefix}-{next(_serial_counter):04d}"


def unique_mrn(prefix: str = "MRN") -> str:
    return f"{prefix}-{next(_mrn_counter):04d}"


def unique_payer_code(prefix: str = "PAY") -> str:
    return f"{prefix}-{next(_payer_counter):04d}"


# ── Program foundations ─────────────────────────────────────────────────────


def payer_policy_payload(**overrides: Any) -> Dict[str, Any]:
    """A fully specified policy: every optional field stated explicitly."""
    payload: Dict[str, Any] = {
        "payer_code": overrides.pop("payer_code", unique_payer_code()),
        "name": "Standard Bone Health",
        "baseline_screening_min_interval_months": 24,
        "high_risk_min_interval_months": 12,
        "treatment_monitoring_min_interval_months": 12,
        "vfa_covered": True,
        "vfa_requires_height_loss_cm": 4.0,
        "repeat_scan_grace_days": 30,
        "max_lifetime_screening_scans": 6,
        "appeal_allowed": False,
    }
    payload.update(overrides)
    return payload


def minimal_payer_policy_payload(**overrides: Any) -> Dict[str, Any]:
    """Only the two required policy fields, so every default can be observed."""
    payload: Dict[str, Any] = {
        "payer_code": overrides.pop("payer_code", unique_payer_code()),
        "name": "Defaults Only Policy",
    }
    payload.update(overrides)
    return payload


def patient_payload(policy_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "mrn": overrides.pop("mrn", unique_mrn()),
        "primary_payer_policy_id": policy_id,
        "birth_date": "1958-05-12",
        "sex": "FEMALE",
        "postmenopausal": True,
        "baseline_height_cm": 165.0,
    }
    payload.update(overrides)
    return payload


def minimal_patient_payload(policy_id: str, **overrides: Any) -> Dict[str, Any]:
    """Only the required patient fields, so optional defaults can be observed."""
    payload: Dict[str, Any] = {
        "mrn": overrides.pop("mrn", unique_mrn()),
        "primary_payer_policy_id": policy_id,
        "birth_date": "1958-05-12",
        "sex": "FEMALE",
        "baseline_height_cm": 165.0,
    }
    payload.update(overrides)
    return payload


def risk_profile_payload(expected_patient_version: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_patient_version": expected_patient_version,
        "height_cm": 165.0,
        "weight_kg": 58.0,
    }
    payload.update(overrides)
    return payload


# ── Equipment ───────────────────────────────────────────────────────────────


def densitometer_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "serial_number": overrides.pop("serial_number", unique_serial_number()),
        "manufacturer": "HOLOGIC",
        "model": "Horizon A",
        "site_code": "MAIN",
        "phantom_baseline_bmd_g_cm2": PHANTOM_BASELINE_BMD,
        "phantom_baseline_sd_g_cm2": PHANTOM_BASELINE_SD,
        "appointment_buffer_minutes": 15,
        "daily_scan_capacity": 12,
    }
    payload.update(overrides)
    return payload


def minimal_densitometer_payload(**overrides: Any) -> Dict[str, Any]:
    """Only the required device fields, so scheduling defaults can be observed."""
    payload: Dict[str, Any] = {
        "serial_number": overrides.pop("serial_number", unique_serial_number()),
        "manufacturer": "HOLOGIC",
        "model": "Horizon A",
        "site_code": "MAIN",
        "phantom_baseline_bmd_g_cm2": PHANTOM_BASELINE_BMD,
        "phantom_baseline_sd_g_cm2": PHANTOM_BASELINE_SD,
    }
    payload.update(overrides)
    return payload


def precision_assessment_payload(
    expected_densitometer_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_densitometer_version": expected_densitometer_version,
        "technologist_user_id": "tech-001",
        "patient_count": 30,
        "scans_per_patient": 2,
        "rms_sd_g_cm2": 0.0100,
    }
    payload.update(overrides)
    return payload


def qc_run_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "purpose": "DAILY_QC",
        "phantom_bmd_g_cm2": 1.0050,
        "scan_mode": "ARRAY",
    }
    payload.update(overrides)
    return payload


def cross_cal_run_payload(
    purpose: str, calibration_event_id: str, phantom_bmd_g_cm2: float, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "purpose": purpose,
        "phantom_bmd_g_cm2": phantom_bmd_g_cm2,
        "scan_mode": "ARRAY",
        "calibration_event_id": calibration_event_id,
    }
    payload.update(overrides)
    return payload


def calibration_event_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"change_type": "SOFTWARE_UPGRADE"}
    payload.update(overrides)
    return payload


# ── Scheduling ──────────────────────────────────────────────────────────────


def scan_order_payload(patient_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "patient_id": patient_id,
        "indication": "BASELINE_SCREENING",
        "requested_sites": ["FEMORAL_NECK"],
        "requested_scan_date": "2026-03-10",
        "vfa_requested": False,
    }
    payload.update(overrides)
    return payload


def appointment_payload(
    scan_order_id: str, densitometer_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "scan_order_id": scan_order_id,
        "densitometer_id": densitometer_id,
        "start_utc": "2026-03-10T09:00:00Z",
        "end_utc": "2026-03-10T09:30:00Z",
    }
    payload.update(overrides)
    return payload


def scan_session_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"scan_mode": "ARRAY"}
    payload.update(overrides)
    return payload


# ── Acquisition ─────────────────────────────────────────────────────────────

_SITE_DEFAULTS = {
    "FEMORAL_NECK": (BMD_FEMORAL_NECK_OSTEOPENIC, 5.1, 3.32, FEMORAL_NECK_REFERENCE),
    "LUMBAR_SPINE": (BMD_LUMBAR_OSTEOPENIC, 58.2, 52.38, LUMBAR_REFERENCE),
    "TOTAL_HIP": (BMD_TOTAL_HIP_OSTEOPENIC, 34.1, 23.87, TOTAL_HIP_REFERENCE),
    "FOREARM_33": (0.5500, 3.9, 2.15, FOREARM_REFERENCE),
}


def site_measurement_payload(
    site_code: str = "FEMORAL_NECK",
    bmd_g_cm2: Optional[float] = None,
    included_vertebrae: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A measurement for one skeletal site with its vendor reference figures."""
    default_bmd, area, bmc, reference = _SITE_DEFAULTS[site_code]
    payload: Dict[str, Any] = {
        "site_code": site_code,
        "bmd_g_cm2": default_bmd if bmd_g_cm2 is None else bmd_g_cm2,
        "area_cm2": area,
        "bmc_g": bmc,
    }
    payload.update(reference)
    if site_code == "LUMBAR_SPINE":
        payload["included_vertebrae"] = (
            ["L1", "L2", "L3", "L4"] if included_vertebrae is None else included_vertebrae
        )
    elif included_vertebrae is not None:
        payload["included_vertebrae"] = included_vertebrae
    payload.update(overrides)
    return payload


def vfa_payload(genant_grades: Optional[List[int]] = None, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "genant_grades": [0, 1, 2] if genant_grades is None else genant_grades
    }
    payload.update(overrides)
    return payload


def positioning_review_payload(
    defect_codes: Optional[List[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "defect_codes": [] if defect_codes is None else defect_codes
    }
    payload.update(overrides)
    return payload


# ── Interpretation ──────────────────────────────────────────────────────────


def frax_payload(
    patient_id: str,
    risk_factor_profile_id: str,
    scan_session_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "patient_id": patient_id,
        "risk_factor_profile_id": risk_factor_profile_id,
    }
    if scan_session_id is not None:
        payload["scan_session_id"] = scan_session_id
    payload.update(overrides)
    return payload


def diagnostic_report_payload(scan_session_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"scan_session_id": scan_session_id}
    payload.update(overrides)
    return payload


def report_patch_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def amendment_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"amendment_reason": "Vertebral findings revised"}
    payload.update(overrides)
    return payload


# ── Therapy ─────────────────────────────────────────────────────────────────


def treatment_plan_payload(
    patient_id: str, initiating_report_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "patient_id": patient_id,
        "initiating_report_id": initiating_report_id,
        "drug_class": "BISPHOSPHONATE_ORAL",
        "start_date": "2026-04-01",
    }
    payload.update(overrides)
    return payload


def refill_payload(
    dispensed_date: str = "2026-04-01",
    days_supplied: int = 30,
    source: str = "PHARMACY_CLAIM",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "dispensed_date": dispensed_date,
        "days_supplied": days_supplied,
        "source": source,
    }
    payload.update(overrides)
    return payload


def adherence_review_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload
