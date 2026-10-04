"""Payload factories — one per create/action endpoint, input fields only.

Field names, required/optional splits, and defaults follow the PRD section 3
narratives exactly. Optional fields are omitted from the payload when not
supplied (the server applies its declared defaults). Unique-looking
identifiers (tin, ptin, office_code, model_version, bank fingerprints) are
auto-generated from high counter ranges so they never collide with literal
values a test picks deliberately.
"""
import itertools
from typing import Optional

from .constants import DEFAULT_TAX_YEAR, OCC_FIELD

# ─── Unique-value generators ─────────────────────────
# High start ranges avoid collisions with literal 9-digit TINs / PTINs a
# test writes by hand (which conventionally sit in the 1000000xx /
# 9000000xx / P0000000x ranges).
_tin_seq = itertools.count(500000000)
_dependent_tin_seq = itertools.count(600000000)
_ptin_seq = itertools.count(90000000)
_office_code_seq = itertools.count(500)
_model_version_seq = itertools.count(1)
_fingerprint_seq = itertools.count(1)
_name_seq = itertools.count(1)


def next_tin() -> str:
    """A fresh, exactly-9-digit taxpayer TIN."""
    return str(next(_tin_seq))


def next_dependent_tin() -> str:
    """A fresh, exactly-9-digit dependent TIN."""
    return str(next(_dependent_tin_seq))


def next_ptin() -> str:
    """A fresh preparer PTIN in the P######## shape."""
    return f"P{next(_ptin_seq):08d}"


def next_office_code() -> str:
    return f"OFC-{next(_office_code_seq):03d}"


def next_model_version() -> str:
    return f"MV-AUTO-{next(_model_version_seq):04d}"


def next_fingerprint() -> str:
    return f"fp-auto-{next(_fingerprint_seq):04d}"


def next_full_name() -> str:
    return f"Test Taxpayer {next(_name_seq)}"


# ─── Taxpayer (PRD section 3.1) ──────────────────────

def create_taxpayer_payload(**overrides) -> dict:
    """Required: tin, full_name, date_of_birth. Optional:
    prior_year_refund_cents (default 0), pin_delivery_channel
    (default POSTAL_MAIL)."""
    payload = {
        "tin": next_tin(),
        "full_name": next_full_name(),
        "date_of_birth": "1980-01-01",
    }
    payload.update(overrides)
    return payload


def update_taxpayer_payload(expected_taxpayer_version: int, **overrides) -> dict:
    """OCC-guarded profile update. `expected_taxpayer_version` is a
    non-optional input field (PRD section 2.7); the updatable fields are
    full_name, date_of_birth, prior_year_refund_cents, pin_delivery_channel."""
    payload = {OCC_FIELD: expected_taxpayer_version}
    payload.update(overrides)
    return payload


# ─── Preparer / office / config registries (PRD section 3.1, 3.4) ──

def create_preparer_payload(**overrides) -> dict:
    """Required: ptin (unique), firm_name."""
    payload = {
        "ptin": next_ptin(),
        "firm_name": "Test Prep Firm",
    }
    payload.update(overrides)
    return payload


def create_service_office_payload(**overrides) -> dict:
    """Required: office_code (unique), name, capacity (>= 1)."""
    payload = {
        "office_code": next_office_code(),
        "name": "Test Assistance Center",
        "capacity": 2,
    }
    payload.update(overrides)
    return payload


def create_filter_model_config_payload(**overrides) -> dict:
    """Required: model_version plus all nine integer knobs (PRD section 3.4).
    Defaults are a pass-through config: every weight 0, gray_zone_threshold 1,
    hold_threshold 50, so an unweighted return scores 0 and passes."""
    payload = {
        "model_version": next_model_version(),
        "w_victim_flagged": 0,
        "w_refund_delta": 0,
        "w_bank_product": 0,
        "w_preparer_flagged": 0,
        "w_dependent_conflict": 0,
        "interaction_bonus": 0,
        "gray_zone_threshold": 1,
        "hold_threshold": 50,
    }
    payload.update(overrides)
    return payload


# ─── IP PIN program (PRD section 3.2) ────────────────

def opt_in_payload(tax_year: int = DEFAULT_TAX_YEAR,
                   delivery_channel: Optional[str] = None) -> dict:
    """Required: tax_year. Optional: delivery_channel override."""
    payload = {"tax_year": tax_year}
    if delivery_channel is not None:
        payload["delivery_channel"] = delivery_channel
    return payload


def reissue_protection_pin_payload(taxpayer_id: str,
                                   expected_taxpayer_version: int,
                                   tax_year: int = DEFAULT_TAX_YEAR,
                                   delivery_channel: Optional[str] = None) -> dict:
    """OCC-guarded manual reissue. Required: taxpayer_id, tax_year,
    expected_taxpayer_version. Optional: delivery_channel (PRD section 3.2)."""
    payload = {
        "taxpayer_id": taxpayer_id,
        "tax_year": tax_year,
        OCC_FIELD: expected_taxpayer_version,
    }
    if delivery_channel is not None:
        payload["delivery_channel"] = delivery_channel
    return payload


def annual_pin_regeneration_payload(tax_year: int) -> dict:
    return {"tax_year": tax_year}


# ─── Identity theft reports (PRD section 3.3) ────────

def create_identity_theft_report_payload(source: str = "TAXPAYER_REPORT",
                                         description: Optional[str] = None) -> dict:
    """Required: source. Optional: description (defaults to empty string)."""
    payload = {"source": source}
    if description is not None:
        payload["description"] = description
    return payload


def confirm_report_payload(tax_year: int = DEFAULT_TAX_YEAR) -> dict:
    return {"tax_year": tax_year}


# ─── Tax returns (PRD section 3.4) ───────────────────

def create_dependent_payload(dependent_tin: Optional[str] = None,
                             relationship: str = "CHILD") -> dict:
    """One entry of the filing payload's dependents array."""
    return {
        "dependent_tin": dependent_tin or next_dependent_tin(),
        "relationship": relationship,
    }


def create_return_payload(taxpayer_id: str,
                          claimed_refund_cents: int = 100000,
                          tax_year: int = DEFAULT_TAX_YEAR,
                          filing_status: str = "SINGLE",
                          preparer_id: Optional[str] = None,
                          ip_pin_submitted: Optional[str] = None,
                          bank_product: Optional[str] = None,
                          bank_account_fingerprint: Optional[str] = None,
                          dependents: Optional[list] = None,
                          **overrides) -> dict:
    """Required: taxpayer_id, tax_year, filing_status, claimed_refund_cents.
    Optional: preparer_id, ip_pin_submitted (default null), bank_product
    (default NONE), bank_account_fingerprint (default null), dependents.
    Optionals left as None are omitted so the server applies its defaults."""
    payload = {
        "taxpayer_id": taxpayer_id,
        "tax_year": tax_year,
        "filing_status": filing_status,
        "claimed_refund_cents": claimed_refund_cents,
    }
    if preparer_id is not None:
        payload["preparer_id"] = preparer_id
    if ip_pin_submitted is not None:
        payload["ip_pin_submitted"] = ip_pin_submitted
    if bank_product is not None:
        payload["bank_product"] = bank_product
    if bank_account_fingerprint is not None:
        payload["bank_account_fingerprint"] = bank_account_fingerprint
    if dependents is not None:
        payload["dependents"] = dependents
    payload.update(overrides)
    return payload


# ─── Verification cases / documents / appointments (PRD section 3.5) ──

def create_verification_case_payload(taxpayer_id: str,
                                     channel: str = "ONLINE",
                                     return_id: Optional[str] = None) -> dict:
    """Required: taxpayer_id, channel. Optional: return_id (omitting it opens
    an enrollment-verification case)."""
    payload = {"taxpayer_id": taxpayer_id, "channel": channel}
    if return_id is not None:
        payload["return_id"] = return_id
    return payload


def submit_document_payload(doc_type: str = "PHOTO_ID") -> dict:
    return {"doc_type": doc_type}


def book_appointment_payload(case_id: str,
                             start_at: str = "2027-03-02T10:00:00Z",
                             end_at: str = "2027-03-02T11:00:00Z") -> dict:
    """Required: case_id, start_at, end_at (end strictly after start;
    half-open interval)."""
    return {"case_id": case_id, "start_at": start_at, "end_at": end_at}


# ─── Dependent conflicts (PRD section 3.6) ───────────

def submit_evidence_payload(side: str = "A", note: Optional[str] = None) -> dict:
    """Required: side (which filer the evidence supports). Optional: note."""
    payload = {"side": side}
    if note is not None:
        payload["note"] = note
    return payload


def resolve_conflict_payload(winner: str = "FIRST_FILER") -> dict:
    """Required: winner — FIRST_FILER or SECOND_FILER."""
    return {"winner": winner}


# ─── Disbursement release (PRD section 3.8) ──────────

def release_disbursement_payload(expected_amount_cents: int) -> dict:
    """Required: expected_amount_cents — must equal base_cents + computed
    final_interest_cents."""
    return {"expected_amount_cents": expected_amount_cents}


# ─── Advocate cases (PRD section 3.9) ────────────────

def create_advocate_case_payload(taxpayer_id: str,
                                 hardship_type: str = "MEDICAL",
                                 return_id: Optional[str] = None) -> dict:
    """Required: taxpayer_id, hardship_type. Optional: return_id (omitting it
    opens an account-level hardship case)."""
    payload = {"taxpayer_id": taxpayer_id, "hardship_type": hardship_type}
    if return_id is not None:
        payload["return_id"] = return_id
    return payload


def resolve_advocate_case_payload(resolution_note: Optional[str] = None) -> dict:
    """Optional: resolution_note (defaults to empty string)."""
    payload: dict = {}
    if resolution_note is not None:
        payload["resolution_note"] = resolution_note
    return payload


# ─── Platform clock (PRD section 2.4) ────────────────

def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
