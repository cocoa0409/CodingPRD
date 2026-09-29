"""Request-payload builders.

Each builder returns a plain dict carrying the fields the contract declares for
that endpoint, with every numeric value sent as a JSON number: acreages and
percentages at two decimals, per-acre rates at four, tonnages at three, and
monetary amounts as whole cents. Keyword arguments override any default, and a
value of ``None`` passed explicitly is preserved so that a test can exercise the
null-field branch of the request-shape rung.

The defaults describe the reference scenario used throughout the suite: a
1000.00-acre field of loam, a five-year cover-crop commitment starting in the
2026 crop year, and a published methodology whose parameters are chosen so that
every derived figure downstream is a clean, hand-checkable number.
"""

import uuid
from typing import Any, Dict, List, Optional

from .constants import (
    BASELINE_HISTORICAL_DATA,
    EVIDENCE_EQUIPMENT_TELEMETRY,
    EVIDENCE_FARM_RECORD,
    EVIDENCE_REMOTE_SENSING,
    METHOD_MODEL,
    OPINION_POSITIVE,
    PAYMENT_MODEL_PER_ACRE,
    PAYMENT_MODEL_PER_CREDIT,
    PRACTICE_COVER_CROP,
    REVERSAL_UNINTENTIONAL,
    SOIL_LOAM,
)

# ─── The reference methodology (§3.2) ──────────────────────────────────────
STANDARD_LOOKBACK_YEARS = 5
STANDARD_MAX_PRIOR_ADOPTION_PCT = 20.00
STANDARD_MIN_DOCUMENTED_YEARS = 4
STANDARD_MIN_ADOPTION_YEARS = 3
STANDARD_UNCERTAINTY_BASE_PCT = 15.00
STANDARD_SEQUESTRATION_RATE = 0.3500
STANDARD_MODELED_BASELINE_RATE = 0.2000
STANDARD_BUFFER_BASE_PCT = 10.00
STANDARD_EFFECTIVE_FROM = "2020-01-01"

# ─── The reference field and commitment (§3.1, §3.3) ───────────────────────
FIELD_MIN_X = 0
FIELD_MIN_Y = 0
FIELD_MAX_X = 2000
FIELD_MAX_Y = 2000
FIELD_MAPPED_ACRES = 1000.00
FIELD_GROSS_ACRES = 1010.00
ENROLLED_ACRES = 1000.00
COMMITMENT_YEARS = 5
START_CROP_YEAR = 2026
PER_CREDIT_SHARE_PCT = 60.00
PER_ACRE_RATE_CENTS = 1000.00

# ─── The reference field observations (§3.5) ───────────────────────────────
PACKET_REPORTED_ACRES = 1000.00
PACKET_COVERAGE_PCT = 92.00
PACKET_MEASURED_VALUE = 0.3000

# ─── The reference verification window (§3.6) ─────────────────────────────
SAMPLE_PCT = 10.00
VISIT_START = "2026-09-01"
VISIT_END = "2026-09-05"


def unique_suffix() -> str:
    """A short unique token for fields the contract requires to be unique."""
    return uuid.uuid4().hex[:10]


def _payload(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Merge overrides into a default payload, honouring explicit nulls."""
    merged = dict(base)
    merged.update(overrides)
    return merged


# ─── The logical clock (§2.4) ──────────────────────────────────────────────
def clock_payload(current_utc: str) -> Dict[str, Any]:
    """Body for repositioning the logical programme clock."""
    return {"current_utc": current_utc}


# ─── Growers and fields (§3.1) ─────────────────────────────────────────────
def grower_payload(**overrides: Any) -> Dict[str, Any]:
    """Registration body for a farm operator."""
    token = unique_suffix()
    return _payload(
        {
            "legal_name": f"Prairie Ridge Farms {token}",
            "operator_type": "LLC",
            "tax_id": f"TAX-{token}",
            "mailing_state": "IA",
        },
        overrides,
    )


def field_payload(**overrides: Any) -> Dict[str, Any]:
    """Registration body for a field, whose acreage the server derives."""
    return _payload(
        {
            "field_name": f"North Quarter {unique_suffix()}",
            "boundary_min_x": FIELD_MIN_X,
            "boundary_min_y": FIELD_MIN_Y,
            "boundary_max_x": FIELD_MAX_X,
            "boundary_max_y": FIELD_MAX_Y,
            "gross_acres": FIELD_GROSS_ACRES,
            "soil_group": SOIL_LOAM,
            "county_code": "IA-113",
        },
        overrides,
    )


def boundary_payload(min_x: int, min_y: int, max_x: int, max_y: int,
                     **overrides: Any) -> Dict[str, Any]:
    """Registration body for a field with an explicit boundary rectangle."""
    return field_payload(
        boundary_min_x=min_x,
        boundary_min_y=min_y,
        boundary_max_x=max_x,
        boundary_max_y=max_y,
        **overrides,
    )


def map_confirm_payload(**overrides: Any) -> Dict[str, Any]:
    """Body confirming a draft field's boundary survey."""
    return _payload({"surveyor_reference": f"SURVEY-{unique_suffix()}"}, overrides)


def suspend_grower_payload(**overrides: Any) -> Dict[str, Any]:
    """Body suspending a grower for programme non-compliance."""
    return _payload({"suspension_reason": "Programme non-compliance"}, overrides)


# ─── Practice history and methodologies (§3.2) ─────────────────────────────
def practice_history_payload(crop_year: int, **overrides: Any) -> Dict[str, Any]:
    """Body filing one crop year of historical practice evidence."""
    return _payload(
        {
            "crop_year": crop_year,
            "practice_code": PRACTICE_COVER_CROP,
            "adopted": False,
            "evidence_source": EVIDENCE_FARM_RECORD,
            "acres": 0.00,
            "observed_emissions_per_acre": 0.1500,
        },
        overrides,
    )


def practice_standard_payload(**overrides: Any) -> Dict[str, Any]:
    """Publication body for a versioned methodology."""
    return _payload(
        {
            "practice_code": PRACTICE_COVER_CROP,
            "standard_version": 1,
            "additionality_lookback_years": STANDARD_LOOKBACK_YEARS,
            "max_prior_adoption_pct": STANDARD_MAX_PRIOR_ADOPTION_PCT,
            "min_documented_years": STANDARD_MIN_DOCUMENTED_YEARS,
            "min_adoption_years": STANDARD_MIN_ADOPTION_YEARS,
            "uncertainty_base_pct": STANDARD_UNCERTAINTY_BASE_PCT,
            "sequestration_rate_per_acre": STANDARD_SEQUESTRATION_RATE,
            "modeled_baseline_rate_per_acre": STANDARD_MODELED_BASELINE_RATE,
            "buffer_base_pct": STANDARD_BUFFER_BASE_PCT,
            "telemetry_required": True,
            "effective_from": STANDARD_EFFECTIVE_FROM,
        },
        overrides,
    )


def revision_payload(**overrides: Any) -> Dict[str, Any]:
    """Body publishing a revision of a methodology in place."""
    return _payload({"revision_note": "Coefficient review 2026"}, overrides)


# ─── Enrollment and screening (§3.3) ──────────────────────────────────────
def enrollment_payload(field_id: str, practice_standard_id: str,
                       **overrides: Any) -> Dict[str, Any]:
    """Creation body for a per-credit enrollment."""
    return _payload(
        {
            "field_id": field_id,
            "practice_standard_id": practice_standard_id,
            "commitment_years": COMMITMENT_YEARS,
            "start_crop_year": START_CROP_YEAR,
            "enrolled_acres": ENROLLED_ACRES,
            "payment_model": PAYMENT_MODEL_PER_CREDIT,
            "per_credit_share_pct": PER_CREDIT_SHARE_PCT,
        },
        overrides,
    )


def per_acre_enrollment_payload(field_id: str, practice_standard_id: str,
                                **overrides: Any) -> Dict[str, Any]:
    """Creation body for a per-acre enrollment, which omits the credit share."""
    payload = enrollment_payload(field_id, practice_standard_id, **overrides)
    payload.pop("per_credit_share_pct", None)
    payload["payment_model"] = overrides.get("payment_model", PAYMENT_MODEL_PER_ACRE)
    payload["per_acre_rate_cents"] = overrides.get("per_acre_rate_cents", PER_ACRE_RATE_CENTS)
    return payload


def request_info_payload(missing_items: Optional[List[str]] = None,
                         **overrides: Any) -> Dict[str, Any]:
    """Body returning an enrollment to the applicant with missing items."""
    return _payload(
        {"missing_items": missing_items if missing_items is not None
         else ["Signed field map", "Seed purchase receipts"]},
        overrides,
    )


def screen_payload(decision: str = "ACCEPT", **overrides: Any) -> Dict[str, Any]:
    """Adjudication body for a screened enrollment."""
    payload: Dict[str, Any] = {"decision": decision}
    if decision == "REJECT":
        payload["rejection_reason"] = "Prior adoption indicates business as usual"
    return _payload(payload, overrides)


# ─── Baselines (§3.4) ─────────────────────────────────────────────────────
def baseline_payload(expected_enrollment_version: int,
                     method: str = BASELINE_HISTORICAL_DATA,
                     **overrides: Any) -> Dict[str, Any]:
    """Proposal body for a baseline, carrying the observed enrollment version."""
    return _payload(
        {"method": method, "expected_enrollment_version": expected_enrollment_version},
        overrides,
    )


def baseline_rejection_payload(**overrides: Any) -> Dict[str, Any]:
    """Body rejecting a proposed baseline with a note."""
    return _payload({"rejection_note": "Historical records inconsistent"}, overrides)


# ─── Data packets and quality control (§3.5) ──────────────────────────────
def data_packet_payload(crop_year: int = START_CROP_YEAR, **overrides: Any) -> Dict[str, Any]:
    """Filing body for one crop year of field observations."""
    return _payload(
        {
            "crop_year": crop_year,
            "source": EVIDENCE_EQUIPMENT_TELEMETRY,
            "reported_acres": PACKET_REPORTED_ACRES,
            "coverage_pct": PACKET_COVERAGE_PCT,
            "measured_value": PACKET_MEASURED_VALUE,
        },
        overrides,
    )


def farm_record_packet_payload(crop_year: int = START_CROP_YEAR,
                               **overrides: Any) -> Dict[str, Any]:
    """Filing body for a farm-record observation."""
    return data_packet_payload(crop_year, source=EVIDENCE_FARM_RECORD, **overrides)


def remote_sensing_packet_payload(crop_year: int = START_CROP_YEAR,
                                  **overrides: Any) -> Dict[str, Any]:
    """Filing body for a remote-sensing observation."""
    return data_packet_payload(crop_year, source=EVIDENCE_REMOTE_SENSING, **overrides)


def qc_payload(decision: str = "PASS", **overrides: Any) -> Dict[str, Any]:
    """Quality-control decision body."""
    payload: Dict[str, Any] = {"decision": decision}
    if decision == "FLAG":
        payload["flag_reason"] = "Reported acreage inconsistent with coverage"
    return _payload(payload, overrides)


def correction_payload(**overrides: Any) -> Dict[str, Any]:
    """Correction body for a flagged packet."""
    return _payload(
        {
            "reported_acres": PACKET_REPORTED_ACRES,
            "coverage_pct": PACKET_COVERAGE_PCT,
            "measured_value": PACKET_MEASURED_VALUE,
        },
        overrides,
    )


def packet_rejection_payload(**overrides: Any) -> Dict[str, Any]:
    """Body permanently rejecting a flagged packet."""
    return _payload({"flag_reason": "Evidence withdrawn by grower"}, overrides)


# ─── Quantification and verification (§3.6) ───────────────────────────────
def quantification_run_payload(enrollment_id: str, baseline_id: str,
                               expected_enrollment_version: int,
                               crop_year: int = START_CROP_YEAR,
                               method: str = METHOD_MODEL,
                               **overrides: Any) -> Dict[str, Any]:
    """Creation body for a quantification run."""
    return _payload(
        {
            "enrollment_id": enrollment_id,
            "baseline_id": baseline_id,
            "crop_year": crop_year,
            "method": method,
            "expected_enrollment_version": expected_enrollment_version,
        },
        overrides,
    )


def verification_body_payload(**overrides: Any) -> Dict[str, Any]:
    """Accreditation body for a third-party verification body."""
    token = unique_suffix()
    return _payload(
        {
            "name": f"Midwest Carbon Assurance {token}",
            "accreditation_id": f"ACC-{token}",
            "accredited_practices": [PRACTICE_COVER_CROP],
            "max_concurrent_visits": 1,
        },
        overrides,
    )


def verification_payload(quantification_run_id: str, verification_body_id: str,
                         **overrides: Any) -> Dict[str, Any]:
    """Commissioning body for a verification of a submitted run."""
    return _payload(
        {
            "quantification_run_id": quantification_run_id,
            "verification_body_id": verification_body_id,
            "sample_pct": SAMPLE_PCT,
            "site_visit_start": VISIT_START,
            "site_visit_end": VISIT_END,
        },
        overrides,
    )


def opinion_payload(opinion: str = OPINION_POSITIVE, **overrides: Any) -> Dict[str, Any]:
    """Body issuing a verification opinion."""
    return _payload({"opinion": opinion}, overrides)


def resample_payload(**overrides: Any) -> Dict[str, Any]:
    """Body reopening a qualified verification for a fresh sample."""
    return _payload(
        {
            "sample_pct": SAMPLE_PCT,
            "site_visit_start": VISIT_START,
            "site_visit_end": VISIT_END,
        },
        overrides,
    )


# ─── Issuance and the registry (§3.7, §3.8) ───────────────────────────────
def issue_payload(vintage_year: int = START_CROP_YEAR, **overrides: Any) -> Dict[str, Any]:
    """Body minting a credit batch from a verified run."""
    return _payload({"vintage_year": vintage_year}, overrides)


def registry_listing_payload(**overrides: Any) -> Dict[str, Any]:
    """Body listing a batch on the public registry."""
    return _payload({"registry_account_ref": f"REG-{unique_suffix()}"}, overrides)


def retirement_payload(**overrides: Any) -> Dict[str, Any]:
    """Body retiring a listed batch for a named beneficiary."""
    return _payload({"retirement_beneficiary": "Northwind Logistics plc"}, overrides)


def cancellation_payload(expected_credit_batch_version: int, **overrides: Any) -> Dict[str, Any]:
    """Body cancelling an issued batch, carrying the observed batch version."""
    return _payload(
        {
            "cancellation_reason": "Issued against superseded evidence",
            "expected_credit_batch_version": expected_credit_batch_version,
        },
        overrides,
    )


def reversal_payload(credit_batch_id: str, affected_acres: float,
                     detected_crop_year: int = START_CROP_YEAR,
                     reversal_type: str = REVERSAL_UNINTENTIONAL,
                     **overrides: Any) -> Dict[str, Any]:
    """Body reporting a carbon reversal against an issued batch."""
    return _payload(
        {
            "credit_batch_id": credit_batch_id,
            "reversal_type": reversal_type,
            "affected_acres": affected_acres,
            "detected_crop_year": detected_crop_year,
        },
        overrides,
    )


def resolution_payload(**overrides: Any) -> Dict[str, Any]:
    """Body closing an assessed reversal with a remediation note."""
    return _payload({"resolution_note": "Cover re-established and re-surveyed"}, overrides)


# ─── Payments, exit and termination (§3.9) ────────────────────────────────
def accrual_payload(crop_year: int = START_CROP_YEAR, **overrides: Any) -> Dict[str, Any]:
    """Body accruing the per-acre annual incentive for one crop year."""
    return _payload({"crop_year": crop_year}, overrides)


def exit_request_payload(requested_exit_year: int, exit_reason: str = "VOLUNTARY",
                         **overrides: Any) -> Dict[str, Any]:
    """Body filing a contract exit request."""
    return _payload(
        {"exit_reason": exit_reason, "requested_exit_year": requested_exit_year},
        overrides,
    )


def exit_decision_payload(decision: str = "APPROVE", **overrides: Any) -> Dict[str, Any]:
    """Body adjudicating an exit request."""
    payload: Dict[str, Any] = {"decision": decision}
    if decision == "DENY":
        payload["rejection_reason"] = "Commitment must be served"
    return _payload(payload, overrides)
