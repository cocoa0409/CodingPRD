"""Request-payload builders, one per declared input shape.

Every builder follows the same discipline: it assembles a dictionary of
PRD-declared defaults and then applies ``overrides`` with ``dict.update``. No
builder ever accepts a field both positionally and through ``overrides``, so no
call site can raise a duplicate-keyword error. Money is always an integer number
of cents, never a string; basis points are always integers; volumes always carry
exactly two decimals.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    ADJUSTMENT_REASON_RECEIVE,
    CANCEL_REASON_PATIENT_REQUEST,
    CRITERION_CT_OPACIFICATION,
    CRITERION_FAILED_INCS,
    CRITERION_SNOT22_GE_20,
    DECISION_APPROVED,
    DEVICE_TYPE_HEARING_AID,
    DILUTION_BLUE,
    DISCARD_REASON_BEYOND_USE_DATE,
    EAR_LEFT,
    ITEM_TYPE_ALLERGEN_CONCENTRATE,
    LATERALITY_LEFT,
    METHOD_SKIN_PRICK,
    PANEL_MOLD_12,
    PROCEDURE_DIAGNOSTIC_ENDOSCOPY,
    RETURN_REASON_POOR_FIT,
    SINUS_MAXILLARY,
    STUDY_AUDIOMETRY,
    THERAPY_INCS,
    VENUE_IN_OFFICE_SUITE,
    VOID_REASON_DRAWN_IN_ERROR,
    device_serial,
    lot_number,
    make_label_text,
    mrn,
    scope_serial,
)


# ---------------------------------------------------------------------------
# Payer policies (PRD 3.1)
# ---------------------------------------------------------------------------
def payer_policy_payload(**overrides: Any) -> Dict[str, Any]:
    """A payer plan carrying only the two mandatory fields.

    Every threshold is omitted so that the service applies the defaults of
    PRD 3.1; pass overrides to pin any of them explicitly.
    """
    payload: Dict[str, Any] = {
        "payer_name": "Northshore Health Plan",
        "plan_code": "PLAN-2999",
    }
    payload.update(overrides)
    return payload


def payer_policy_patch_payload(**overrides: Any) -> Dict[str, Any]:
    """An amendment body. Amendable terms only; every field is optional."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Patients (PRD 3.1)
# ---------------------------------------------------------------------------
def patient_payload(payer_policy_id: str, **overrides: Any) -> Dict[str, Any]:
    """A patient chart carrying the three mandatory fields."""
    payload: Dict[str, Any] = {
        "payer_policy_id": payer_policy_id,
        "mrn": mrn(10001),
        "full_name": "Rowan Ellery Castellane",
        "date_of_birth": "1990-05-20",
    }
    payload.update(overrides)
    return payload


def patient_patch_payload(**overrides: Any) -> Dict[str, Any]:
    """A chart update over the three mutable fields of PRD 3.1."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Allergy test orders (PRD 3.2, 3.3)
# ---------------------------------------------------------------------------
def allergy_test_order_payload(patient_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "patient_id": patient_id,
        "panel_code": PANEL_MOLD_12,
        "method": METHOD_SKIN_PRICK,
    }
    payload.update(overrides)
    return payload


def allergy_reading_payload(positive_antigen_count: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"positive_antigen_count": positive_antigen_count}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Reaction events (PRD 3.4)
# ---------------------------------------------------------------------------
def reaction_event_payload(
    systemic_grade: int, onset_minutes: int, **overrides: Any
) -> Dict[str, Any]:
    """A reaction event body. Exactly one parent reference must be supplied
    through ``overrides``: ``allergy_test_order_id`` or ``immunotherapy_dose_id``.
    """
    payload: Dict[str, Any] = {
        "systemic_grade": systemic_grade,
        "onset_minutes": onset_minutes,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Immunotherapy vials and doses (PRD 3.5)
# ---------------------------------------------------------------------------
def immunotherapy_vial_payload(
    patient_id: str,
    supply_lot_id: str,
    patient_mrn: str,
    expected_patient_version: int,
    expires_at: str,
    **overrides: Any
) -> Dict[str, Any]:
    """Compound a vial.

    ``label_text`` is always derived from the patient's ``mrn``, the dilution
    code and the calendar date of ``expires_at``, because PRD 3.5 accepts no
    other spelling. Override ``dilution_code`` and the label follows.
    """
    dilution_code = overrides.pop("dilution_code", DILUTION_BLUE)
    payload: Dict[str, Any] = {
        "patient_id": patient_id,
        "supply_lot_id": supply_lot_id,
        "dilution_code": dilution_code,
        "label_text": make_label_text(patient_mrn, dilution_code, expires_at),
        "expires_at": expires_at,
        "expected_patient_version": expected_patient_version,
    }
    payload.update(overrides)
    return payload


def label_verification_payload(label_text_confirmation: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"label_text_confirmation": label_text_confirmation}
    payload.update(overrides)
    return payload


def vial_discard_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"discard_reason": DISCARD_REASON_BEYOND_USE_DATE}
    payload.update(overrides)
    return payload


def immunotherapy_dose_payload(immunotherapy_vial_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"immunotherapy_vial_id": immunotherapy_vial_id}
    payload.update(overrides)
    return payload


def dose_void_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"void_reason": VOID_REASON_DRAWN_IN_ERROR}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Sinuplasty cases (PRD 3.6)
# ---------------------------------------------------------------------------
def sinuplasty_case_payload(patient_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "patient_id": patient_id,
        "laterality": LATERALITY_LEFT,
        "sinuses": [SINUS_MAXILLARY],
    }
    payload.update(overrides)
    return payload


def therapy_course(therapy_code: str, start_date: str, end_date: str) -> Dict[str, str]:
    """One documented medical-management course. Dates carry no time of day."""
    return {
        "therapy_code": therapy_code,
        "start_date": start_date,
        "end_date": end_date,
    }


def documentation_payload(
    documented_therapies: Optional[List[Dict[str, str]]] = None,
    documented_criteria_codes: Optional[List[str]] = None,
    **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "documented_therapies": (
            documented_therapies
            if documented_therapies is not None
            else [therapy_course(THERAPY_INCS, "2026-06-01", "2026-06-28")]
        ),
        "documented_criteria_codes": (
            documented_criteria_codes
            if documented_criteria_codes is not None
            else [
                CRITERION_SNOT22_GE_20,
                CRITERION_CT_OPACIFICATION,
                CRITERION_FAILED_INCS,
            ]
        ),
        "ct_study_date": "2026-07-01",
    }
    payload.update(overrides)
    return payload


def payer_decision_payload(payer_reference: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": DECISION_APPROVED,
        "payer_reference": payer_reference,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Diagnostic studies and device dispenses (PRD 3.7)
# ---------------------------------------------------------------------------
def diagnostic_study_payload(patient_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "patient_id": patient_id,
        "study_type": STUDY_AUDIOMETRY,
    }
    payload.update(overrides)
    return payload


def audiometry_results_payload(
    pta_db_hl: float, word_recognition_pct: float, **overrides: Any
) -> Dict[str, Any]:
    """The metric set an ``AUDIOMETRY`` study demands, and nothing else."""
    payload: Dict[str, Any] = {
        "pta_db_hl": pta_db_hl,
        "word_recognition_pct": word_recognition_pct,
    }
    payload.update(overrides)
    return payload


def sleep_results_payload(ahi: float, **overrides: Any) -> Dict[str, Any]:
    """The metric set a sleep study demands, and nothing else."""
    payload: Dict[str, Any] = {"ahi": ahi}
    payload.update(overrides)
    return payload


def device_dispense_payload(
    diagnostic_study_id: str,
    supply_lot_id: str,
    expected_study_version: int,
    **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "diagnostic_study_id": diagnostic_study_id,
        "supply_lot_id": supply_lot_id,
        "device_type": DEVICE_TYPE_HEARING_AID,
        "device_serial": device_serial("HA", 100001),
        "ear": EAR_LEFT,
        "price_cents": 289000,
        "expected_study_version": expected_study_version,
    }
    payload.update(overrides)
    return payload


def adjustment_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def trial_return_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"return_reason": RETURN_REASON_POOR_FIT}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Endoscopes and supply lots (PRD 3.8)
# ---------------------------------------------------------------------------
def endoscope_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "serial_number": scope_serial(1),
        "model": "Olympus ENF-VH",
    }
    payload.update(overrides)
    return payload


def reprocessing_completion_payload(leak_test_passed: bool, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"leak_test_passed": leak_test_passed}
    payload.update(overrides)
    return payload


def supply_lot_payload(expires_at: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "item_type": ITEM_TYPE_ALLERGEN_CONCENTRATE,
        "lot_number": lot_number(1),
        "quantity_received": 10,
        "expires_at": expires_at,
    }
    payload.update(overrides)
    return payload


def lot_adjustment_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": ADJUSTMENT_REASON_RECEIVE, "quantity": 1}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Blocks and bookings (PRD 3.9)
# ---------------------------------------------------------------------------
def surgery_center_block_payload(
    block_start_at: str, block_end_at: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "center_name": "Lakeside Surgery Center",
        "block_start_at": block_start_at,
        "block_end_at": block_end_at,
    }
    payload.update(overrides)
    return payload


def procedure_booking_payload(
    patient_id: str,
    start_at: str,
    end_at: str,
    physician_user_id: str,
    **overrides: Any
) -> Dict[str, Any]:
    """A booking body.

    The four conditional references of PRD 3.9 are never supplied by default;
    each one is required in exactly one circumstance and forbidden in the
    complement, so every test states them explicitly through ``overrides``.
    """
    payload: Dict[str, Any] = {
        "patient_id": patient_id,
        "procedure_type": PROCEDURE_DIAGNOSTIC_ENDOSCOPY,
        "venue": VENUE_IN_OFFICE_SUITE,
        "start_at": start_at,
        "end_at": end_at,
        "physician_user_id": physician_user_id,
    }
    payload.update(overrides)
    return payload


def booking_completion_payload(devices_used_count: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"devices_used_count": devices_used_count}
    payload.update(overrides)
    return payload


def booking_cancel_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"cancel_reason": CANCEL_REASON_PATIENT_REQUEST}
    payload.update(overrides)
    return payload


def booking_start_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload
