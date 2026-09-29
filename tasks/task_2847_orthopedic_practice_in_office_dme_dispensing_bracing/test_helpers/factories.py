"""Payload builders for every write endpoint.

Money fields are emitted as integers counting cents. Instant fields are
emitted as full ISO-8601 UTC instants; only `accreditation_expires_on`,
`credential_expires_on`, `service_date` and `dob` are calendar dates, because
the contract defines those as dates rather than instants.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    CATEGORY_CUSTOM_FABRICATED,
    CATEGORY_CUSTOM_FITTED_PREFAB,
    CATEGORY_OFF_SHELF_PREFAB,
    SCOPE_CUSTOM_AND_OFF_SHELF,
    SCOPE_OFF_SHELF_ONLY,
    SUPERVISION_DIRECT,
    SUPERVISION_GENERAL,
)

_npi_counter = itertools.count(1)
_member_counter = itertools.count(1)


def next_npi() -> str:
    """A ten-digit identifier unique within one test run."""
    return "17{}".format(str(next(_npi_counter)).zfill(8))


def next_member_id() -> str:
    return "CM-{}".format(next(_member_counter))


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not _OMIT}


class _Omit:
    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<omit>"


_OMIT = _Omit()
OMIT = _OMIT


# ---------------------------------------------------------------------------
# Clinics, physicians, fitters, patients
# ---------------------------------------------------------------------------
def clinic_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": "North Ortho",
            "state_code": "OH",
            "accreditation_body": "ABC",
            "accreditation_expires_on": "2027-06-30",
            "ioas_supervision_level": SUPERVISION_DIRECT,
            "dispensing_specialties": ["SPORTS_MEDICINE", "SPINE", "FOOT_ANKLE", "HAND", "TOTAL_JOINT"],
        },
        overrides,
    )


def physician_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "full_name": "Ora Vance",
            "npi": next_npi(),
            "specialty": "SPINE",
            "group_member": True,
            "stark_disclosure_on_file": True,
        },
        overrides,
    )


def fitter_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "full_name": "Kai Lund",
            "credential": "CO",
            "credential_expires_on": "2027-12-31",
            "privilege_scope": SCOPE_CUSTOM_AND_OFF_SHELF,
        },
        overrides,
    )


def off_shelf_fitter_payload(**overrides: Any) -> Dict[str, Any]:
    variant: Dict[str, Any] = {
        "full_name": "Rae Ellis",
        "privilege_scope": SCOPE_OFF_SHELF_ONLY,
    }
    variant.update(overrides)
    return fitter_payload(**variant)


def patient_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "full_name": "Ida Moss",
            "dob": "1961-03-04",
            "payer_type": "COMMERCIAL",
            "member_id": next_member_id(),
            "medicare_beneficiary": False,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Suppliers and products
# ---------------------------------------------------------------------------
def supplier_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": "Bracewell Ortho",
            "accreditation_body": "ABC",
            "accreditation_expires_on": "2027-12-31",
            "promised_turnaround_days": 10,
            "dmepos_standards_attested": True,
            "custom_fab_capable": True,
            "quality_hold": False,
        },
        overrides,
    )


def product_payload(supplier_id: str, **overrides: Any) -> Dict[str, Any]:
    """A prefabricated lumbar-sacral orthosis: the default catalog item."""
    return _merge(
        {
            "supplier_id": supplier_id,
            "hcpcs_code": "L0650",
            "description": "LSO brace, prefabricated",
            "category": CATEGORY_OFF_SHELF_PREFAB,
            "specialty": "SPINE",
            "same_or_similar_group": "LSO_BRACE",
            "reasonable_useful_lifetime_months": 60,
            "allowed_amount_cents": 20600,
            "cash_price_cents": 11765,
            "unit_cost_cents": 6000,
            "requires_prior_auth": False,
            "ioas_supervision_required": SUPERVISION_GENERAL,
        },
        overrides,
    )


def _variant_product_payload(
    supplier_id: str, variant: Dict[str, Any], overrides: Dict[str, Any]
) -> Dict[str, Any]:
    """A named catalog variant, with the caller's overrides taking precedence.

    The variant's own defaults are merged before the call so that a caller may
    override any of them by name without colliding with the variant's value.
    """
    merged = dict(variant)
    merged.update(overrides)
    return product_payload(supplier_id, **merged)


def knee_brace_product_payload(supplier_id: str, **overrides: Any) -> Dict[str, Any]:
    return _variant_product_payload(
        supplier_id,
        {
            "hcpcs_code": "L1832",
            "description": "Knee orthosis, adjustable range of motion",
            "specialty": "SPORTS_MEDICINE",
            "same_or_similar_group": "KNEE_ROM",
            "reasonable_useful_lifetime_months": 36,
            "allowed_amount_cents": 22000,
            "cash_price_cents": 19999,
            "unit_cost_cents": 9000,
        },
        overrides,
    )


def custom_afo_product_payload(supplier_id: str, **overrides: Any) -> Dict[str, Any]:
    return _variant_product_payload(
        supplier_id,
        {
            "hcpcs_code": "L1940",
            "description": "Ankle foot orthosis, custom fabricated",
            "category": CATEGORY_CUSTOM_FABRICATED,
            "specialty": "FOOT_ANKLE",
            "same_or_similar_group": "AFO_CUSTOM",
            "reasonable_useful_lifetime_months": 36,
            "allowed_amount_cents": 42000,
            "cash_price_cents": 49999,
            "unit_cost_cents": 20000,
        },
        overrides,
    )


def custom_fitted_product_payload(supplier_id: str, **overrides: Any) -> Dict[str, Any]:
    return _variant_product_payload(
        supplier_id,
        {
            "hcpcs_code": "L0637",
            "description": "LSO brace, custom fitted prefabricated",
            "category": CATEGORY_CUSTOM_FITTED_PREFAB,
            "specialty": "SPINE",
            "same_or_similar_group": "LSO_BRACE_FITTED",
            "allowed_amount_cents": 31000,
            "cash_price_cents": 17500,
            "unit_cost_cents": 9000,
        },
        overrides,
    )


def wrist_splint_product_payload(supplier_id: str, **overrides: Any) -> Dict[str, Any]:
    return _variant_product_payload(
        supplier_id,
        {
            "hcpcs_code": "L3908",
            "description": "Wrist hand orthosis, prefabricated",
            "specialty": "HAND",
            "same_or_similar_group": "WRIST_SPLINT",
            "reasonable_useful_lifetime_months": 12,
            "allowed_amount_cents": 9000,
            "cash_price_cents": 5000,
            "unit_cost_cents": 2000,
        },
        overrides,
    )


def cervical_collar_product_payload(supplier_id: str, **overrides: Any) -> Dict[str, Any]:
    return _variant_product_payload(
        supplier_id,
        {
            "hcpcs_code": "L0172",
            "description": "Cervical collar, semi-rigid",
            "specialty": "SPINE",
            "same_or_similar_group": "CERVICAL_COLLAR",
            "reasonable_useful_lifetime_months": 24,
            "allowed_amount_cents": 12000,
            "cash_price_cents": 7000,
            "unit_cost_cents": 3000,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Shelves
# ---------------------------------------------------------------------------
def par_level_payload(clinic_id: str, product_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "clinic_id": clinic_id,
            "product_id": product_id,
            "par_min_qty": 4,
            "par_max_qty": 20,
        },
        overrides,
    )


def stock_receipt_payload(received_qty: int = 10, **overrides: Any) -> Dict[str, Any]:
    return _merge({"received_qty": received_qty}, overrides)


# ---------------------------------------------------------------------------
# Encounters and their subordinate records
# ---------------------------------------------------------------------------
def encounter_payload(
    clinic_id: str,
    patient_id: str,
    product_id: str,
    ordering_physician_id: str,
    quantity: int = 1,
    **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "clinic_id": clinic_id,
            "patient_id": patient_id,
            "product_id": product_id,
            "ordering_physician_id": ordering_physician_id,
            "quantity": quantity,
        },
        overrides,
    )


def medical_necessity_note_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "mn_diagnosis_code": "M54.50",
            "mn_functional_deficit": "lumbar instability limiting ambulation",
            "mn_expected_duration_months": 6,
        },
        overrides,
    )


def ioas_attestation_payload(level: str = SUPERVISION_DIRECT, **overrides: Any) -> Dict[str, Any]:
    return _merge({"ioas_supervision_level_observed": level}, overrides)


def coverage_verification_payload(
    covered: bool = True,
    deductible_remaining_cents: int = 0,
    coinsurance_pct: float = 0.2,
    valid_for_days: int = 30,
    **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "covered": covered,
            "deductible_remaining_cents": deductible_remaining_cents,
            "coinsurance_pct": coinsurance_pct,
            "valid_for_days": valid_for_days,
        },
        overrides,
    )


def reservation_payload(expected_par_level_version: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"expected_par_level_version": expected_par_level_version}, overrides)


def custom_fab_order_payload(supplier_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"supplier_id": supplier_id}, overrides)


def fitting_record_payload(
    fitting_start_at: str = "2026-08-01T09:00:00Z",
    fitting_end_at: str = "2026-08-01T09:30:00Z",
    fit_outcome: str = "ACCEPTABLE",
    measurement_set: Optional[Dict[str, Any]] = None,
    **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "fitting_start_at": fitting_start_at,
            "fitting_end_at": fitting_end_at,
            "measurement_set": measurement_set or {"waist_cm": 96},
            "fit_outcome": fit_outcome,
        },
        overrides,
    )


def dispense_payload(delivery_signature_role: str = "PATIENT", **overrides: Any) -> Dict[str, Any]:
    return _merge({"delivery_signature_role": delivery_signature_role}, overrides)


def prior_auth_request_payload(requested_units: int = 1, **overrides: Any) -> Dict[str, Any]:
    return _merge({"requested_units": requested_units}, overrides)


def prior_auth_decision_payload(
    decision: str = "APPROVED",
    approved_units: Optional[int] = 1,
    auth_number: Optional[str] = "AUTH-77001",
    valid_for_days: Optional[int] = 30,
    **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if approved_units is not None:
        payload["approved_units"] = approved_units
    if auth_number is not None:
        payload["auth_number"] = auth_number
    if valid_for_days is not None:
        payload["valid_for_days"] = valid_for_days
    return _merge(payload, overrides)


def prior_auth_appeal_payload(appeal_note: str = "additional imaging attached", **overrides: Any):
    return _merge({"appeal_note": appeal_note}, overrides)


def abn_notice_payload(
    expected_encounter_version: int,
    reason_non_covered: str = "NON_COVERED_ITEM",
    **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "reason_non_covered": reason_non_covered,
            "expected_encounter_version": expected_encounter_version,
        },
        overrides,
    )


def abn_signature_payload(
    option_selected: str = "OPTION_1", signed_by: str = "PATIENT", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"option_selected": option_selected, "signed_by": signed_by}, overrides)


def abn_decline_payload(**overrides: Any) -> Dict[str, Any]:
    """Omitting the option declines the notice."""
    return _merge({}, overrides)


def fabrication_event_payload(event: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"event": event}, overrides)


def fitting_check_payload(
    outcome: str = "ACCEPT", note: str = "device conforms to the measurement set", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"outcome": outcome, "note": note}, overrides)


def return_payload(reason: str = "POOR_FIT", return_note: str = "pressure at the iliac crest", **overrides: Any):
    return _merge({"reason": reason, "return_note": return_note}, overrides)


def inspection_payload(condition: str = "SELLABLE", **overrides: Any) -> Dict[str, Any]:
    return _merge({"condition": condition}, overrides)


def standards_attestation_payload(
    dmepos_standards_attested: bool = True, quality_hold: bool = False, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "dmepos_standards_attested": dmepos_standards_attested,
            "quality_hold": quality_hold,
        },
        overrides,
    )


def clock_payload(current_utc: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"current_utc": current_utc}, overrides)


def without(payload: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    """A copy of `payload` with the named keys removed."""
    return {k: v for k, v in payload.items() if k not in keys}


def with_extra(payload: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
    merged = dict(payload)
    merged.update(extra)
    return merged
