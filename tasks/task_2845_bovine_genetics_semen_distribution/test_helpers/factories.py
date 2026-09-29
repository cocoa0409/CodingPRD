"""Request-payload factories.

Every factory returns the PRD's required fields with valid defaults and lets a
caller override any of them with keyword arguments.  Passing `OMIT` as a value
removes the key from the payload entirely, which is how the optional-field and
missing-field cases are built.

Type discipline (PRD 2.8 / 2.4):
  * every monetary amount is an integer number of cents, sent as a JSON number;
  * `birth_date` and `sample_date` are calendar dates (`YYYY-MM-DD`);
  * `start_at`, `end_at`, `effective_at`, `current_utc` and
    `technician_cert_expiry_at` are full ISO-8601 UTC instants.
"""

from typing import Any, Dict

from .constants import (
    CLOCK_DEFAULT,
    TANK_DEFAULT_INITIAL_FILL_PCT,
    TANK_DEFAULT_SERVICE_INTERVAL_DAYS,
)


class _Omit:
    """Sentinel meaning 'leave this optional field out of the payload'."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<OMIT>"


_OMIT = _Omit()
OMIT = _OMIT


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    for key, value in overrides.items():
        if value is _OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ------------------------------------------------------------------- clock
def clock_payload(current_utc: str = CLOCK_DEFAULT, **overrides: Any) -> Dict[str, Any]:
    return _merge({"current_utc": current_utc}, overrides)


# -------------------------------------------------------------- facilities
def facility_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "code": "F-MAIN",
            "name": "Prairie Bull Centre",
            "country_code": "US",
            "housing_capacity": 10,
            "bench_capacity": 3,
            "approved_export_countries": ["CA"],
        },
        overrides,
    )


def facility_approval_payload(
    approval_status: str = "SUSPENDED", **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"approval_status": approval_status, "suspension_reason": "REGULATOR_AUDIT_FINDING"},
        overrides,
    )


# ------------------------------------------------------ country requirements
def country_requirement_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "country_code": "CA",
            "required_test_types": ["IBR"],
            "max_test_age_days": 400,
            "min_isolation_days": 21,
            "sexed_semen_allowed": True,
            "embryo_allowed": True,
        },
        overrides,
    )


# ------------------------------------------------------------------- sires
def sire_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "registration_code": "REG-A",
            "name": "Prairie Anchor",
            "breed": "HOLSTEIN",
            "birth_date": "2022-03-15",
            "acquisition_cost_cents": 500000,
        },
        overrides,
    )


def contract_payload(contract_price_cents: int = 655000, **overrides: Any) -> Dict[str, Any]:
    return _merge({"contract_price_cents": contract_price_cents}, overrides)


def house_payload(facility_id: str, isolation_days: int = 30, **overrides: Any) -> Dict[str, Any]:
    return _merge({"facility_id": facility_id, "isolation_days": isolation_days}, overrides)


def clearance_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"clearance_note": "isolation served, assays current"}, overrides)


def collection_status_payload(collection_status: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"collection_status": collection_status}, overrides)


def retire_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"retirement_reason": "commercial retirement"}, overrides)


def pedigree_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({}, overrides)


# ------------------------------------------------------------- health tests
def health_test_payload(
    facility_id: str,
    test_type: str = "IBR",
    sample_date: str = "2026-07-28",
    validity_days: int = 365,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "facility_id": facility_id,
            "test_type": test_type,
            "sample_date": sample_date,
            "validity_days": validity_days,
        },
        overrides,
    )


def health_test_result_payload(result: str = "NEGATIVE", **overrides: Any) -> Dict[str, Any]:
    return _merge({"result": result}, overrides)


# --------------------------------------------------------------- bookings
def booking_payload(
    sire_id: str,
    facility_id: str,
    start_at: str = "2026-09-10T08:00:00Z",
    end_at: str = "2026-09-10T10:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "sire_id": sire_id,
            "facility_id": facility_id,
            "start_at": start_at,
            "end_at": end_at,
        },
        overrides,
    )


def booking_cancel_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"cancel_reason": "bench maintenance"}, overrides)


def booking_complete_payload(
    volume_ml: float = 6.0,
    concentration_m_per_ml: float = 1200,
    motility_pct: float = 68.0,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "volume_ml": volume_ml,
            "concentration_m_per_ml": concentration_m_per_ml,
            "motility_pct": motility_pct,
        },
        overrides,
    )


# ------------------------------------------------------------- ejaculate QC
def qc_evaluation_payload(
    verdict: str = "ACCEPTED",
    post_thaw_motility_pct: float = 55.0,
    morphology_normal_pct: float = 82.0,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "verdict": verdict,
            "post_thaw_motility_pct": post_thaw_motility_pct,
            "morphology_normal_pct": morphology_normal_pct,
        },
        overrides,
    )


# ---------------------------------------------------------------- straw lots
def straw_lot_payload(
    product_line: str = "CONVENTIONAL",
    straw_count: int = 200,
    processing_cost_cents: int = 250000,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "product_line": product_line,
            "straw_count": straw_count,
            "processing_cost_cents": processing_cost_cents,
        },
        overrides,
    )


def lot_release_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"release_note": "quarantine cleared"}, overrides)


def lot_reject_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"rejected_reason": "post-thaw failure on the retained straw"}, overrides)


# -------------------------------------------------------------- evaluations
def genomic_evaluation_payload(
    expected_sire_version: int,
    milk_kg: float = 1100,
    fat_kg: float = 45.0,
    protein_kg: float = 36.0,
    somatic_cell_score: float = 2.90,
    fertility_pct: float = 2.0,
    longevity_months: float = 3.0,
    reliability_pct: float = 68.0,
    progeny_daughter_count: int = 50,
    effective_at: str = "2026-08-15T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "milk_kg": milk_kg,
            "fat_kg": fat_kg,
            "protein_kg": protein_kg,
            "somatic_cell_score": somatic_cell_score,
            "fertility_pct": fertility_pct,
            "longevity_months": longevity_months,
            "reliability_pct": reliability_pct,
            "progeny_daughter_count": progeny_daughter_count,
            "effective_at": effective_at,
            "expected_sire_version": expected_sire_version,
        },
        overrides,
    )


def publish_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"publication_note": "quarterly proof run"}, overrides)


def rollback_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"rollback_reason": "proof withdrawn by the evaluation body"}, overrides)


# ------------------------------------------------------------- certificates
def export_certificate_payload(
    sire_id: str, straw_lot_id: str, country_requirement_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "sire_id": sire_id,
            "straw_lot_id": straw_lot_id,
            "country_requirement_id": country_requirement_id,
        },
        overrides,
    )


def certificate_submit_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"submission_note": "dossier lodged with the authority"}, overrides)


def certificate_issue_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"issue_note": "signed by the attending veterinarian"}, overrides)


def certificate_reject_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"rejection_reason": "dossier incomplete"}, overrides)


def certificate_revoke_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"revocation_reason": "regulator withdrew the approval"}, overrides)


# -------------------------------------------------------------- distributors
def distributor_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": "D-ALPHA",
            "country_code": "US",
            "credit_limit_cents": 100000000,
        },
        overrides,
    )


# --------------------------------------------------------------------- tanks
def tank_payload(distributor_id: str, serial: str = "TK-A", **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "distributor_id": distributor_id,
            "serial": serial,
            "capacity_straws": 500,
        },
        overrides,
    )


def tank_service_payload(fill_pct: float = 95.0, **overrides: Any) -> Dict[str, Any]:
    return _merge({"fill_pct": fill_pct}, overrides)


# ------------------------------------------------------ consignment transfers
def consignment_request_payload(
    distributor_id: str,
    tank_id: str,
    expected_straw_lot_version: int,
    doses: int = 40,
    unit_price_cents: int = 4000,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "distributor_id": distributor_id,
            "tank_id": tank_id,
            "doses": doses,
            "unit_price_cents": unit_price_cents,
            "expected_straw_lot_version": expected_straw_lot_version,
        },
        overrides,
    )


def transfer_approve_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"approval_note": "credit and health checks cleared"}, overrides)


def transfer_reject_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"rejection_reason": "partner asked to defer the shipment"}, overrides)


def transfer_dispatch_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"dispatch_note": "loaded into the courier dewar"}, overrides)


def transfer_receive_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"receipt_note": "received into the home tank"}, overrides)


def report_usage_payload(doses_used: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"doses_used": doses_used}, overrides)


def transfer_return_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"return_reason": "programme cancelled by the herd owner"}, overrides)


# ------------------------------------------------------------ customer herds
def customer_herd_payload(distributor_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "herd_name": "H-MAIN",
            "distributor_id": distributor_id,
            "country_code": "US",
            "target_product_line": "CONVENTIONAL",
        },
        overrides,
    )


def mating_recommendation_payload(
    dam_ref: str = "DAM-001",
    requested_product_line: str = "CONVENTIONAL",
    doses_requested: int = 5,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "dam_ref": dam_ref,
            "requested_product_line": requested_product_line,
            "doses_requested": doses_requested,
        },
        overrides,
    )


def decision_payload(decision: str = "ACCEPTED", **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


# --------------------------------------------------------------- tank helper
DEFAULT_TANK_SERVICE_INTERVAL_DAYS = TANK_DEFAULT_SERVICE_INTERVAL_DAYS
DEFAULT_TANK_INITIAL_FILL_PCT = TANK_DEFAULT_INITIAL_FILL_PCT
