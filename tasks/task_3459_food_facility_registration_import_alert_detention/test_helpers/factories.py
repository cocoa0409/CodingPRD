"""Payload factories — one per creatable resource, input fields only (PRD §3).

Unique business identifiers (ufi, account_code, lab_code) get an auto-sequence
suffix so repeated calls within one test never collide on the uniqueness
constraints of PRD §3.1/§3.2.
"""

import itertools

from .constants import (
    DEFAULT_INSPECTION_END,
    DEFAULT_INSPECTION_START,
    DEFAULT_Arrival_ETA,
)

_seq = itertools.count(1)


def _n() -> int:
    return next(_seq)


# ---------------------------------------------------------------------------
# Facility (PRD §3.1)
# ---------------------------------------------------------------------------


def create_facility_payload(**overrides) -> dict:
    n = _n()
    payload = {
        "legal_name": f"Test Facility {n}",
        "facility_kind": "FOREIGN",
        "country_code": "DE",
        "ufi": f"UFI-DE-{n:05d}",
    }
    payload.update(overrides)
    return payload


def renew_facility_payload(expected_facility_version: int) -> dict:
    """OCC-guarded renewal payload (PRD §2.7)."""
    return {"expected_facility_version": expected_facility_version}


# ---------------------------------------------------------------------------
# ImporterFirm / Laboratory (PRD §3.2)
# ---------------------------------------------------------------------------


def create_importer_payload(**overrides) -> dict:
    n = _n()
    payload = {
        "firm_name": f"Test Importer {n}",
        "account_code": f"IMP-{n:05d}",
    }
    payload.update(overrides)
    return payload


def create_laboratory_payload(**overrides) -> dict:
    n = _n()
    payload = {
        "lab_code": f"LAB-{n:05d}",
        "daily_sample_capacity": 10,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# PriorNotice (PRD §3.3)
# ---------------------------------------------------------------------------


def create_prior_notice_payload(importer_id: str, facility_id: str, **overrides) -> dict:
    n = _n()
    payload = {
        "importer_id": importer_id,
        "facility_id": facility_id,
        "product_code": f"PC-GEN-{n:05d}",
        "product_risk_class": "STANDARD",
        "transport_mode": "VESSEL",
        "arrival_eta": DEFAULT_Arrival_ETA,
        "declared_units": 10,
        "unit_value_cents": 100,
        "port_code": "US-NYC",
    }
    payload.update(overrides)
    return payload


def amend_prior_notice_payload(
    arrival_eta: str = DEFAULT_Arrival_ETA,
    declared_units=None,
    unit_value_cents=None,
    port_code=None,
    **overrides,
) -> dict:
    """Amendment always carries a fresh arrival_eta; the other three fields are
    optional and inherited from the superseded notice when omitted (PRD §3.3)."""
    payload = {"arrival_eta": arrival_eta}
    if declared_units is not None:
        payload["declared_units"] = declared_units
    if unit_value_cents is not None:
        payload["unit_value_cents"] = unit_value_cents
    if port_code is not None:
        payload["port_code"] = port_code
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ImportEntry (PRD §3.4–§3.6)
# ---------------------------------------------------------------------------


def create_entry_payload(prior_notice_id: str) -> dict:
    return {"prior_notice_id": prior_notice_id}


def record_sample_payload(lab_code: str, sample_units: int, analysis_date: str) -> dict:
    return {
        "lab_code": lab_code,
        "sample_units": sample_units,
        "analysis_date": analysis_date,
    }


def record_sample_result_payload(result: str) -> dict:
    return {"result": result}


def make_lot(quantity: int, unit_value_cents: int) -> dict:
    return {"quantity": quantity, "unit_value_cents": unit_value_cents}


def request_reconditioning_payload(lots) -> dict:
    return {"lots": lots}


def record_reconditioning_outcome_payload(units_passed: int, units_failed: int) -> dict:
    return {"units_passed": units_passed, "units_failed": units_failed}


# ---------------------------------------------------------------------------
# ImportAlert / AlertPetition (PRD §3.7)
# ---------------------------------------------------------------------------


def create_import_alert_payload(
    scope_type: str,
    facility_id=None,
    country_code=None,
    product_code=None,
    reason: str = "",
    **overrides,
) -> dict:
    """Scope-field consistency (PRD §3.7): FIRM carries facility_id only;
    COUNTRY_PRODUCT carries country_code + product_code only. Fields left as
    None are omitted from the payload entirely."""
    payload = {"scope_type": scope_type, "reason": reason}
    if facility_id is not None:
        payload["facility_id"] = facility_id
    if country_code is not None:
        payload["country_code"] = country_code
    if product_code is not None:
        payload["product_code"] = product_code
    payload.update(overrides)
    return payload


def create_alert_petition_payload(
    expected_import_alert_version: int, evidence_links=None, **overrides
) -> dict:
    """OCC-guarded petition filing (PRD §2.7); evidence_links may be empty at filing."""
    payload = {
        "expected_import_alert_version": expected_import_alert_version,
        "evidence_links": list(evidence_links) if evidence_links is not None else [],
    }
    payload.update(overrides)
    return payload


def submit_evidence_payload(evidence_links) -> dict:
    return {"evidence_links": list(evidence_links)}


def adjudicate_petition_payload(decision: str) -> dict:
    return {"decision": decision}


# ---------------------------------------------------------------------------
# Inspection (PRD §3.8)
# ---------------------------------------------------------------------------


def create_inspection_payload(facility_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "scheduled_start_at": DEFAULT_INSPECTION_START,
        "scheduled_end_at": DEFAULT_INSPECTION_END,
    }
    payload.update(overrides)
    return payload


def complete_inspection_payload(findings_violation_count: int) -> dict:
    return {"findings_violation_count": findings_violation_count}


# ---------------------------------------------------------------------------
# Recall (PRD §3.9)
# ---------------------------------------------------------------------------


def create_recall_payload(facility_id: str, **overrides) -> dict:
    n = _n()
    payload = {
        "facility_id": facility_id,
        "product_code": f"PC-RCL-{n:05d}",
        "quantity_distributed": 100,
    }
    payload.update(overrides)
    return payload


def classify_recall_payload(classification: str) -> dict:
    return {"classification": classification}


def record_effectiveness_payload(
    delta_recovered: int,
    delta_corrected: int,
    delta_destroyed: int,
    consignees_contacted: int,
    consignees_total: int,
) -> dict:
    return {
        "delta_recovered": delta_recovered,
        "delta_corrected": delta_corrected,
        "delta_destroyed": delta_destroyed,
        "consignees_contacted": consignees_contacted,
        "consignees_total": consignees_total,
    }


# ---------------------------------------------------------------------------
# Platform clock (PRD §2.4)
# ---------------------------------------------------------------------------


def set_clock_payload(current_utc: str) -> dict:
    return {"current_utc": current_utc}
