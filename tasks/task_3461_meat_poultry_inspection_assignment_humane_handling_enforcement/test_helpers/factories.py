"""Request payload factories — one builder per write endpoint.

Only client-suppliable (``source: input``) fields appear in these payloads;
system and computed fields are server-owned. Defaults are chosen so a bare
call succeeds against a fresh deployment whose logical clock still reads the
boot value 2026-09-01T00:00:00Z (PRD §2.4): every observation/collection/check
timestamp below lies strictly BEFORE that instant, so it satisfies the
"must not be after the logical clock" rule without the caller moving the
clock. Shift-window times are not compared to the clock by any rule, so the
default window sits on the following day.

Badge numbers are unique across the agency (PRD §3.2), so the inspector
factory mints a fresh one per call from a process-wide counter — two default
inspectors in one test never collide.
"""

from datetime import datetime, timedelta
from itertools import count
from typing import Any, Dict, List, Optional


# ── ISO 8601 instant arithmetic ──────────────────────────────────────────────

_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


def iso_add_minutes(iso: str, minutes: int) -> str:
    """Return the instant ``minutes`` after ``iso`` (whole-second Zulu form)."""
    return (datetime.strptime(iso, _ISO_FMT) + timedelta(minutes=minutes)).strftime(_ISO_FMT)


def iso_add_days(iso: str, days: int) -> str:
    """Return the instant ``days`` after ``iso`` (whole-second Zulu form)."""
    return (datetime.strptime(iso, _ISO_FMT) + timedelta(days=days)).strftime(_ISO_FMT)


def iso_add_seconds(iso: str, seconds: int) -> str:
    """Return the instant ``seconds`` after ``iso`` (whole-second Zulu form)."""
    return (datetime.strptime(iso, _ISO_FMT) + timedelta(seconds=seconds)).strftime(_ISO_FMT)


# ── Default timestamps (all strictly before the boot clock 2026-09-01) ───────

DEFAULT_OBSERVED_AT = "2026-08-31T06:00:00Z"
DEFAULT_COLLECTED_AT = "2026-08-20T08:00:00Z"
DEFAULT_CHECKED_AT = "2026-08-31T06:00:00Z"

# Default shift window (not compared to the logical clock by any rule).
DEFAULT_SHIFT_START = "2026-09-02T06:00:00Z"
DEFAULT_SHIFT_END = "2026-09-02T14:00:00Z"

_badge_counter = count(1)


def _next_badge_number() -> str:
    return f"B-{next(_badge_counter):04d}"


# ── Platform logical clock ───────────────────────────────────────────────────

def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}


# ── Establishments ───────────────────────────────────────────────────────────

def establishment_payload(
    name: str = "Test Establishment",
    species_classes: Optional[List[str]] = None,
    slaughter_capable: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name,
        "species_classes": list(species_classes) if species_classes is not None else ["CATTLE"],
        "slaughter_capable": slaughter_capable,
    }
    payload.update(overrides)
    return payload


# ── Grant applications ───────────────────────────────────────────────────────

def grant_application_payload(
    establishment_id: str,
    facility_doc_ref: str = "doc-fac-1",
    sanitation_plan_ref: str = "doc-san-1",
    haccp_plan_ref: str = "doc-hac-1",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "establishment_id": establishment_id,
        "facility_doc_ref": facility_doc_ref,
        "sanitation_plan_ref": sanitation_plan_ref,
        "haccp_plan_ref": haccp_plan_ref,
    }
    payload.update(overrides)
    return payload


def adequacy_payload(dimension: str, finding: str) -> Dict[str, Any]:
    """dimension in {FACILITY, SANITATION, HACCP}; finding in {ADEQUATE, DEFICIENT}."""
    return {"dimension": dimension, "finding": finding}


def grant_decision_payload(decision: str) -> Dict[str, Any]:
    """decision in {GRANT, DENY}."""
    return {"decision": decision}


def grant_resubmit_payload(
    facility_doc_ref: str = "doc-fac-2",
    sanitation_plan_ref: str = "doc-san-2",
    haccp_plan_ref: str = "doc-hac-2",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "facility_doc_ref": facility_doc_ref,
        "sanitation_plan_ref": sanitation_plan_ref,
        "haccp_plan_ref": haccp_plan_ref,
    }
    payload.update(overrides)
    return payload


# ── Inspectors ───────────────────────────────────────────────────────────────

def inspector_payload(
    full_name: str = "Ina Inspector",
    badge_number: Optional[str] = None,
    species_qualifications: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "badge_number": badge_number if badge_number is not None else _next_badge_number(),
        "species_qualifications": (
            list(species_qualifications) if species_qualifications is not None else ["CATTLE"]
        ),
    }
    payload.update(overrides)
    return payload


# ── Shift windows and assignments ────────────────────────────────────────────

def shift_window_payload(
    establishment_id: str,
    start_utc: str = DEFAULT_SHIFT_START,
    end_utc: str = DEFAULT_SHIFT_END,
    shift_type: str = "SLAUGHTER",
    planned_line_count: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "establishment_id": establishment_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "shift_type": shift_type,
        "planned_line_count": planned_line_count,
    }
    payload.update(overrides)
    return payload


def assignment_payload(
    inspector_id: str,
    line_index: int,
    start_utc: str,
    end_utc: str,
    expected_shift_window_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """expected_shift_window_version is non-optional on this endpoint (PRD §2.8)."""
    payload: Dict[str, Any] = {
        "inspector_id": inspector_id,
        "line_index": line_index,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "expected_shift_window_version": expected_shift_window_version,
    }
    payload.update(overrides)
    return payload


# ── Noncompliance records ────────────────────────────────────────────────────

def nr_payload(
    establishment_id: str,
    issued_by_inspector_id: str,
    regulation_family: str = "SANITATION",
    description: str = "noncompliance observation",
    observed_at: str = DEFAULT_OBSERVED_AT,
    shift_window_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "establishment_id": establishment_id,
        "issued_by_inspector_id": issued_by_inspector_id,
        "regulation_family": regulation_family,
        "description": description,
        "observed_at": observed_at,
    }
    # shift_window_id is optional input; omit it entirely when not supplied.
    if shift_window_id is not None:
        payload["shift_window_id"] = shift_window_id
    payload.update(overrides)
    return payload


def nr_response_payload(response_text: str = "corrective action taken") -> Dict[str, Any]:
    return {"response_text": response_text}


def verify_response_payload(outcome: str) -> Dict[str, Any]:
    """outcome in {VERIFY, ESCALATE}."""
    return {"outcome": outcome}


# ── Enforcement actions ──────────────────────────────────────────────────────

def enforcement_action_payload(
    action_type: str,
    basis: str,
    expected_establishment_version: int,
    regulation_family: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """expected_establishment_version is non-optional on this endpoint (PRD §2.8).
    regulation_family is required when basis == NR_LINKAGE and omitted otherwise."""
    payload: Dict[str, Any] = {
        "action_type": action_type,
        "basis": basis,
        "expected_establishment_version": expected_establishment_version,
    }
    if regulation_family is not None:
        payload["regulation_family"] = regulation_family
    payload.update(overrides)
    return payload


def lift_payload(abatement_evidence: str = "abatement measures verified on site by district") -> Dict[str, Any]:
    """Default evidence satisfies the >= 20 character minimum (PRD §3.4)."""
    return {"abatement_evidence": abatement_evidence}


# ── Humane handling events ───────────────────────────────────────────────────

def humane_event_payload(
    establishment_id: str,
    reported_by_inspector_id: str,
    species: str = "CATTLE",
    severity: str = "NON_EGREGIOUS",
    observed_at: str = DEFAULT_OBSERVED_AT,
    description: str = "humane handling observation",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "establishment_id": establishment_id,
        "reported_by_inspector_id": reported_by_inspector_id,
        "species": species,
        "severity": severity,
        "observed_at": observed_at,
        "description": description,
    }
    payload.update(overrides)
    return payload


# ── Pathogen samples ─────────────────────────────────────────────────────────

def pathogen_sample_payload(
    establishment_id: str,
    collected_by_inspector_id: str,
    pathogen: str = "SALMONELLA",
    collected_at: str = DEFAULT_COLLECTED_AT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "establishment_id": establishment_id,
        "collected_by_inspector_id": collected_by_inspector_id,
        "pathogen": pathogen,
        "collected_at": collected_at,
    }
    payload.update(overrides)
    return payload


def record_result_payload(result: str) -> Dict[str, Any]:
    """result in {POSITIVE, NEGATIVE}."""
    return {"result": result}


# ── Label applications ───────────────────────────────────────────────────────

def label_application_payload(
    establishment_id: str,
    product_name: str = "Test Product",
    label_claim: str = "BREED_SPECIFIC",
    documentation_refs: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "establishment_id": establishment_id,
        "product_name": product_name,
        "label_claim": label_claim,
        "documentation_refs": (
            list(documentation_refs) if documentation_refs is not None else ["doc-breed-1"]
        ),
    }
    payload.update(overrides)
    return payload


def label_decision_payload(decision: str) -> Dict[str, Any]:
    """decision in {APPROVE, REJECT, RETURN}."""
    return {"decision": decision}


def label_resubmit_payload(
    documentation_refs: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "documentation_refs": (
            list(documentation_refs) if documentation_refs is not None else ["doc-revised-1"]
        ),
    }
    payload.update(overrides)
    return payload


# ── Recalls ──────────────────────────────────────────────────────────────────

def recall_payload(
    establishment_id: str,
    product_description: str = "recalled product lot",
    quantity_lbs: float = 100.0,
    reason_code: str = "PATHOGEN",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "establishment_id": establishment_id,
        "product_description": product_description,
        "quantity_lbs": quantity_lbs,
        "reason_code": reason_code,
    }
    payload.update(overrides)
    return payload


def determine_class_payload(recall_class: str) -> Dict[str, Any]:
    """recall_class in {CLASS_I, CLASS_II, CLASS_III}."""
    return {"recall_class": recall_class}


def effectiveness_check_payload(
    consignee_name: str = "Depot A",
    outcome: str = "EFFECTIVE",
    checked_at: str = DEFAULT_CHECKED_AT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "consignee_name": consignee_name,
        "outcome": outcome,
        "checked_at": checked_at,
    }
    payload.update(overrides)
    return payload


# ── Appeals ──────────────────────────────────────────────────────────────────

def appeal_payload(
    noncompliance_record_id: str,
    grounds: str = "appeal grounds text",
    **overrides: Any,
) -> Dict[str, Any]:
    """Default grounds satisfies the >= 10 character minimum (PRD §3.9)."""
    payload: Dict[str, Any] = {
        "noncompliance_record_id": noncompliance_record_id,
        "grounds": grounds,
    }
    payload.update(overrides)
    return payload


def appeal_decision_payload(outcome: str) -> Dict[str, Any]:
    """outcome in {AFFIRM, REMAND, VACATE}."""
    return {"outcome": outcome}
