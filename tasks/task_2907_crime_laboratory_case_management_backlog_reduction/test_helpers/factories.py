"""Payload factories.

Each builder produces a request body that satisfies the PRD's schema layer, so a
test only states the fields its own scenario turns on. Two conventions matter:

* money is always an integer number of cents, sent as a JSON number, never a string;
* every instant is a full ISO-8601 UTC timestamp, never a bare date, because the PRD
  declares these fields as instants and compares them against the logical clock.
"""

import itertools
from typing import Any, Dict, List, Optional

from .api_client import OMIT
from .constants import CLOCK_START_UTC

_counter = itertools.count(1)


def _seq() -> int:
    """Monotonic suffix source for values the PRD requires to be unique."""
    return next(_counter)


def instant(
    year: int = 2026,
    month: int = 8,
    day: int = 1,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
) -> str:
    """Compose a full ISO-8601 UTC instant."""
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}Z"


def shift_days(base: str, days: int) -> str:
    """Return the instant ``days`` whole days after ``base``, preserving the time of day."""
    from datetime import datetime, timedelta, timezone

    parsed = datetime.fromisoformat(base.replace("Z", "+00:00")).astimezone(timezone.utc)
    moved = parsed + timedelta(days=days)
    return moved.strftime("%Y-%m-%dT%H:%M:%SZ")


def shift_minutes(base: str, minutes: int) -> str:
    """Return the instant ``minutes`` minutes after ``base``."""
    from datetime import datetime, timedelta, timezone

    parsed = datetime.fromisoformat(base.replace("Z", "+00:00")).astimezone(timezone.utc)
    moved = parsed + timedelta(minutes=minutes)
    return moved.strftime("%Y-%m-%dT%H:%M:%SZ")


def shift_seconds(base: str, seconds: int) -> str:
    """Return the instant ``seconds`` seconds after ``base``."""
    from datetime import datetime, timedelta, timezone

    parsed = datetime.fromisoformat(base.replace("Z", "+00:00")).astimezone(timezone.utc)
    moved = parsed + timedelta(seconds=seconds)
    return moved.strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── Analyst (PRD §3.4) ───────────────────────────────

def analyst_payload(
    full_name: Optional[str] = None,
    disciplines: Optional[List[str]] = None,
    competency_level: Any = OMIT,
    weekly_capacity_hours: float = 40.00,
    training_hours_per_week: Any = OMIT,
    employment_status: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name or f"Examiner {_seq()}",
        "disciplines": list(disciplines) if disciplines else ["BIOLOGY"],
        "weekly_capacity_hours": weekly_capacity_hours,
        "competency_level": competency_level,
        "training_hours_per_week": training_hours_per_week,
        "employment_status": employment_status,
    }
    payload.update(overrides)
    return payload


# ─── Method (PRD §3.2) ────────────────────────────────

def method_payload(
    name: Optional[str] = None,
    discipline: str = "BIOLOGY",
    standard_hours_per_item: float = 3.00,
    min_competency_level: int = 1,
    accreditation_scope_code: Optional[str] = None,
    max_items_per_request: Any = OMIT,
    is_consumptive: Any = OMIT,
    validation_study_item_count: Any = OMIT,
    precision_cv_pct: Any = OMIT,
    validation_expires_at_utc: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    seq = _seq()
    payload: Dict[str, Any] = {
        "name": name or f"Method {seq}",
        "discipline": discipline,
        "standard_hours_per_item": standard_hours_per_item,
        "min_competency_level": min_competency_level,
        "accreditation_scope_code": accreditation_scope_code or f"SCOPE-{seq}",
        "max_items_per_request": max_items_per_request,
        "is_consumptive": is_consumptive,
        "validation_study_item_count": validation_study_item_count,
        "precision_cv_pct": precision_cv_pct,
        "validation_expires_at_utc": validation_expires_at_utc,
    }
    payload.update(overrides)
    return payload


def method_validation_payload(
    validation_study_item_count: int = 24,
    precision_cv_pct: float = 2.50,
    expires_at_utc: str = "2027-08-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "validation_study_item_count": validation_study_item_count,
        "precision_cv_pct": precision_cv_pct,
        "expires_at_utc": expires_at_utc,
    }
    payload.update(overrides)
    return payload


def method_retirement_payload(
    retirement_reason: str = "Superseded by a revised protocol",
) -> Dict[str, Any]:
    return {"retirement_reason": retirement_reason}


# ─── Case (PRD §3.1) ──────────────────────────────────

def case_payload(
    agency_case_number: Optional[str] = None,
    submitting_agency: str = "Metro Police Department",
    offense_category: str = "BURGLARY",
    suspect_in_custody: Any = OMIT,
    statutory_deadline_utc: Any = OMIT,
    court_date_utc: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "agency_case_number": agency_case_number or f"AC-{_seq():05d}",
        "submitting_agency": submitting_agency,
        "offense_category": offense_category,
        "suspect_in_custody": suspect_in_custody,
        "statutory_deadline_utc": statutory_deadline_utc,
        "court_date_utc": court_date_utc,
    }
    payload.update(overrides)
    return payload


def case_acceptance_payload(acceptance_note: Any = OMIT) -> Dict[str, Any]:
    return {"acceptance_note": acceptance_note}


def case_rejection_payload(
    rejection_reason: str = "Chain of custody documentation incomplete",
) -> Dict[str, Any]:
    return {"rejection_reason": rejection_reason}


def priority_override_payload(
    priority_override_class: str,
    expected_case_version: int,
    priority_override_reason: str = "Directed by the laboratory director",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "priority_override_class": priority_override_class,
        "priority_override_reason": priority_override_reason,
        "expected_case_version": expected_case_version,
    }
    payload.update(overrides)
    return payload


def case_report_payload(report_note: Any = OMIT) -> Dict[str, Any]:
    return {"report_note": report_note}


def discovery_request_payload(
    discovery_requesting_party: str = "Office of the Public Defender",
) -> Dict[str, Any]:
    return {"discovery_requesting_party": discovery_requesting_party}


def discovery_response_payload(
    decision: str = "FULFILL", response_note: Any = OMIT
) -> Dict[str, Any]:
    return {"decision": decision, "response_note": response_note}


# ─── Evidence item (PRD §3.1) ─────────────────────────

def evidence_item_payload(
    case_id: str,
    item_number: Optional[str] = None,
    item_type: str = "BIOLOGICAL",
    seal_intact: bool = True,
    item_description: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    seq = _seq()
    payload: Dict[str, Any] = {
        "case_id": case_id,
        "item_number": item_number or f"E{seq:03d}",
        "item_description": item_description or f"Sealed exhibit {seq}",
        "item_type": item_type,
        "seal_intact": seal_intact,
    }
    payload.update(overrides)
    return payload


def evidence_return_payload(return_note: Any = OMIT) -> Dict[str, Any]:
    return {"return_note": return_note}


# ─── Examination request (PRD §3.3) ───────────────────

def examination_request_payload(
    case_id: str,
    evidence_item_id: str,
    method_id: str,
    item_count: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "case_id": case_id,
        "evidence_item_id": evidence_item_id,
        "method_id": method_id,
        "item_count": item_count,
    }
    payload.update(overrides)
    return payload


# ─── Assignment (PRD §3.4) ────────────────────────────

def assignment_payload(
    analyst_id: str,
    expected_examination_request_version: int,
    assignment_reason: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "analyst_id": analyst_id,
        "expected_examination_request_version": expected_examination_request_version,
        "assignment_reason": assignment_reason,
    }
    payload.update(overrides)
    return payload


# ─── Bench work (PRD §3.5) ────────────────────────────

def complete_analysis_payload(
    actual_hours: float = 4.00, evidence_consumed: Any = OMIT, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "actual_hours": actual_hours,
        "evidence_consumed": evidence_consumed,
    }
    payload.update(overrides)
    return payload


# ─── Reviews (PRD §3.6) ───────────────────────────────

def review_payload(decision: str, rationale: Optional[str] = None) -> Dict[str, Any]:
    return {
        "decision": decision,
        "rationale": rationale or f"Reviewed and recorded ({decision})",
    }


def technical_review_payload(
    decision: str = "AGREE", rationale: Optional[str] = None
) -> Dict[str, Any]:
    return review_payload(decision, rationale)


def administrative_review_payload(
    decision: str = "APPROVE", rationale: Optional[str] = None
) -> Dict[str, Any]:
    return review_payload(decision, rationale)


def disagreement_resolution_payload(
    decision: str = "UPHOLD_ANALYST", rationale: Optional[str] = None
) -> Dict[str, Any]:
    return review_payload(decision, rationale)


# ─── Vendor (PRD §3.7) ────────────────────────────────

def vendor_payload(
    name: Optional[str] = None,
    accredited_disciplines: Optional[List[str]] = None,
    accreditation_expires_at_utc: str = "2027-08-01T00:00:00Z",
    concurrent_case_capacity: int = 5,
    unit_price_cents: int = 50000,
    contract_ceiling_cents: int = 10000000,
    rush_surcharge_pct: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name or f"Reference Laboratory {_seq()}",
        "accredited_disciplines": list(accredited_disciplines)
        if accredited_disciplines
        else ["BIOLOGY"],
        "accreditation_expires_at_utc": accreditation_expires_at_utc,
        "concurrent_case_capacity": concurrent_case_capacity,
        "unit_price_cents": unit_price_cents,
        "contract_ceiling_cents": contract_ceiling_cents,
        "rush_surcharge_pct": rush_surcharge_pct,
    }
    payload.update(overrides)
    return payload


def vendor_status_payload(
    status: str, suspension_reason: Any = OMIT, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "status": status,
        "suspension_reason": suspension_reason,
    }
    payload.update(overrides)
    return payload


def vendor_engagement_payload(
    vendor_id: str,
    window_start_utc: str = "2026-08-05T00:00:00Z",
    window_end_utc: str = "2026-08-15T00:00:00Z",
    rush_flag: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "vendor_id": vendor_id,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
        "rush_flag": rush_flag,
    }
    payload.update(overrides)
    return payload


def shipment_payload(shipment_note: Any = OMIT) -> Dict[str, Any]:
    return {"shipment_note": shipment_note}


def record_return_payload(final_invoice_cents: int) -> Dict[str, Any]:
    return {"final_invoice_cents": final_invoice_cents}


def engagement_cancellation_payload(
    cancellation_reason: str = "Casework returned to the in-house bench",
) -> Dict[str, Any]:
    return {"cancellation_reason": cancellation_reason}


# ─── Proficiency testing (PRD §3.8) ───────────────────

def proficiency_test_payload(
    analyst_id: str,
    method_id: str,
    test_cycle: Optional[str] = None,
    due_utc: str = "2026-08-31T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "analyst_id": analyst_id,
        "method_id": method_id,
        "test_cycle": test_cycle or f"2026-C{_seq()}",
        "due_utc": due_utc,
    }
    payload.update(overrides)
    return payload


def score_payload(score_pct: float) -> Dict[str, Any]:
    return {"score_pct": score_pct}


def reinstatement_payload(
    rationale: str = "Remediation complete and a passing proficiency test on file",
) -> Dict[str, Any]:
    return {"rationale": rationale}


# ─── Nonconformances (PRD §3.8) ───────────────────────

def nonconformance_payload(
    source: str = "INTERNAL_QA",
    severity: str = "MINOR",
    description: Optional[str] = None,
    examination_request_id: Any = OMIT,
    analyst_id: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "source": source,
        "severity": severity,
        "description": description or f"Finding {_seq()} raised by quality assurance",
        "examination_request_id": examination_request_id,
        "analyst_id": analyst_id,
    }
    payload.update(overrides)
    return payload


def root_cause_payload(
    root_cause_category: str = "TRAINING",
    corrective_action_plan: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "root_cause_category": root_cause_category,
        "corrective_action_plan": corrective_action_plan
        or "Retrain the examiner and re-verify the protocol",
    }
    payload.update(overrides)
    return payload


def capa_decision_payload(
    decision: str = "APPROVE", rationale: Optional[str] = None
) -> Dict[str, Any]:
    return {
        "decision": decision,
        "rationale": rationale or f"Corrective action plan {decision.lower()}d",
    }


def closure_payload(closure_note: Any = OMIT) -> Dict[str, Any]:
    return {"closure_note": closure_note}


# ─── Court events (PRD §3.9) ──────────────────────────

def court_event_payload(
    examination_request_id: str,
    analyst_id: str,
    start_utc: str = "2026-09-10T14:00:00Z",
    end_utc: str = "2026-09-10T16:00:00Z",
    court_name: str = "County Superior Court",
    docket_number: Optional[str] = None,
    subpoena_received: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "examination_request_id": examination_request_id,
        "analyst_id": analyst_id,
        "court_name": court_name,
        "docket_number": docket_number or f"DK-{_seq():05d}",
        "start_utc": start_utc,
        "end_utc": end_utc,
        "subpoena_received": subpoena_received,
    }
    payload.update(overrides)
    return payload


def testimony_completion_payload(
    testimony_note: str = "Testimony given and the transcript filed",
) -> Dict[str, Any]:
    return {"testimony_note": testimony_note}


def court_event_cancellation_payload(
    cancellation_reason: str = "Hearing vacated by the court",
) -> Dict[str, Any]:
    return {"cancellation_reason": cancellation_reason}


# ─── Logical clock (PRD §2.5) ─────────────────────────

def clock_payload(current_utc: str = CLOCK_START_UTC) -> Dict[str, Any]:
    return {"current_utc": current_utc}
