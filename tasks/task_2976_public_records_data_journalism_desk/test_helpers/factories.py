"""Request-payload builders.

Every builder emits the JSON types the PRD declares:

* money is always an ``int`` number of cents (PRD S2.10: "Every monetary amount
  in this system is an integer number of cents");
* ``search_hours``, ``labor_hours`` and ``null_rate_pct`` are JSON *numbers*,
  because the PRD calls them decimals, not strings;
* counters, day counts, page counts, record counts and risk scores are ``int``;
* every instant is a full ISO-8601 UTC instant, never a date-only string --
  except ``holiday_dates``, which PRD S2.6 declares "as ISO-8601 date strings in
  ``YYYY-MM-DD`` form".

Keyword overrides let a test bend one field without restating the rest, and a
value of :data:`OMIT` removes a key entirely so an optional-default or
missing-required-field probe can be expressed without a second builder.
"""

from typing import Any, Dict, List, Optional

from . import constants as C

# Sentinel meaning "leave this key out of the payload entirely".
OMIT = object()


def _clean(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in payload.items() if v is not OMIT}


# --------------------------------------------------------------------------
# Desk (PRD S3.1)
# --------------------------------------------------------------------------


def desk_payload(**overrides: Any) -> Dict[str, Any]:
    """A registrable desk: 1-120 char name, integer budget, 365-3650 days."""
    payload: Dict[str, Any] = {
        "name": "Metro Investigations Desk",
        "fee_budget_total_cents": 500000,
        "retention_policy_days": 1095,
    }
    payload.update(overrides)
    return _clean(payload)


def budget_adjustment_payload(delta_cents: int, **overrides: Any) -> Dict[str, Any]:
    """A signed budget delta with its free-text reason (PRD S3.1)."""
    payload: Dict[str, Any] = {
        "delta_cents": delta_cents,
        "reason": "Quarterly records-fee top-up approved by the editor.",
    }
    payload.update(overrides)
    return _clean(payload)


def source_exposure_incident_payload(**overrides: Any) -> Dict[str, Any]:
    """A confirmed source-exposure incident (PRD S3.1)."""
    payload: Dict[str, Any] = {
        "incident_summary": "A source-identifying column reached an external analyst.",
        "severity_code": "HIGH",
    }
    payload.update(overrides)
    return _clean(payload)


# --------------------------------------------------------------------------
# Agency (PRD S3.1)
# --------------------------------------------------------------------------


def agency_payload(**overrides: Any) -> Dict[str, Any]:
    """The standard statutory profile used across the suite.

    Ten initial response days on the ``BUSINESS_DAYS`` basis with
    ``2026-09-07`` declared as a holiday -- the exact profile PRD S3.2 works
    through when it derives the two deadline variants.
    """
    payload: Dict[str, Any] = {
        "name": "State Housing Authority",
        "jurisdiction_code": "CA-STATE",
        "statute_name": "CPRA",
        "initial_response_days": 10,
        "deadline_basis": C.BUSINESS_DAYS,
        "tolling_allowed": True,
        "appeal_venue": C.VENUE_OMBUDS,
        "appeal_decision_days": 20,
        "search_fee_cents_per_hour": 3500,
        "page_fee_cents": 25,
        "max_waiver_cents": 10000,
        "holiday_dates": ["2026-09-07"],
    }
    payload.update(overrides)
    return _clean(payload)


def calendar_agency_payload(**overrides: Any) -> Dict[str, Any]:
    """The same profile on the ``CALENDAR_DAYS`` basis (PRD S2.6)."""
    payload = agency_payload(
        name="County Assessor Office",
        jurisdiction_code="CA-COUNTY",
        deadline_basis=C.CALENDAR_DAYS,
        holiday_dates=[],
    )
    payload.update(overrides)
    return _clean(payload)


def no_tolling_agency_payload(**overrides: Any) -> Dict[str, Any]:
    """A statute that grants no tolling at all (PRD S3.4)."""
    payload = agency_payload(
        name="City Transit Authority",
        jurisdiction_code="CA-CITY",
        tolling_allowed=False,
    )
    payload.update(overrides)
    return _clean(payload)


# --------------------------------------------------------------------------
# RecordsRequest (PRD S3.2, S3.3, S3.4)
# --------------------------------------------------------------------------


def records_request_payload(
    desk_id: str,
    agency_id: str,
    expected_desk_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """A drafted records request under desk optimistic concurrency."""
    payload: Dict[str, Any] = {
        "desk_id": desk_id,
        "agency_id": agency_id,
        "subject_summary": "All housing inspection records for calendar year 2025.",
        "requested_format": C.FORMAT_CSV,
        "estimated_page_count": 500,
        "waiver_requested": True,
        "public_interest_score": 85,
        "expected_desk_version": expected_desk_version,
    }
    payload.update(overrides)
    return _clean(payload)


def fee_determination_payload(
    search_hours: float = 3.5, billed_page_count: int = 120, **overrides: Any
) -> Dict[str, Any]:
    """The agency's bill: decimal search hours and an integer page count."""
    payload: Dict[str, Any] = {
        "search_hours": search_hours,
        "billed_page_count": billed_page_count,
    }
    payload.update(overrides)
    return _clean(payload)


def clarification_request_payload(**overrides: Any) -> Dict[str, Any]:
    """The agency's request that the desk narrow its ask (PRD S3.4)."""
    payload: Dict[str, Any] = {
        "question_text": "Which inspection districts should the search cover?",
    }
    payload.update(overrides)
    return _clean(payload)


def clarification_response_payload(**overrides: Any) -> Dict[str, Any]:
    """The desk's answer, closing the round (PRD S3.4)."""
    payload: Dict[str, Any] = {
        "answer_text": "Districts 3 and 4 only, for the 2025 calendar year.",
    }
    payload.update(overrides)
    return _clean(payload)


def agency_decision_payload(outcome: str, **overrides: Any) -> Dict[str, Any]:
    """The agency's disposition; a denial also names the exemption cited."""
    payload: Dict[str, Any] = {"outcome": outcome}
    if outcome == C.OUTCOME_DENIED:
        payload["denial_reason_code"] = "EXEMPT_PRIVACY"
    payload.update(overrides)
    return _clean(payload)


def withdrawal_payload(**overrides: Any) -> Dict[str, Any]:
    """A request withdrawal and its reason (PRD S3.4)."""
    payload: Dict[str, Any] = {"reason": "The story moved on; the ask is abandoned."}
    payload.update(overrides)
    return _clean(payload)


# --------------------------------------------------------------------------
# Appeal (PRD S3.5)
# --------------------------------------------------------------------------


def appeal_payload(
    request_id: str,
    venue: str = C.VENUE_OMBUDS,
    filing_fee_cents: int = 4500,
    **overrides: Any,
) -> Dict[str, Any]:
    """An administrative appeal filing."""
    payload: Dict[str, Any] = {
        "request_id": request_id,
        "venue": venue,
        "grounds": "The claimed privacy exemption does not reach aggregate totals.",
        "filing_fee_cents": filing_fee_cents,
    }
    payload.update(overrides)
    return _clean(payload)


def appeal_decision_payload(outcome: str, **overrides: Any) -> Dict[str, Any]:
    """The venue's decision on a filed appeal (PRD S3.5)."""
    payload: Dict[str, Any] = {
        "outcome": outcome,
        "decision_rationale": "The venue reviewed the withheld material in camera.",
    }
    payload.update(overrides)
    return _clean(payload)


# --------------------------------------------------------------------------
# Dataset and FieldDefinition (PRD S3.6)
# --------------------------------------------------------------------------

_dataset_slug_counter = {"n": 0}


def unique_dataset_name(prefix: str = "housing-inspections") -> str:
    """A fresh globally unique slug of lowercase letters, digits and hyphens.

    PRD S3.6 makes the slug "globally unique across the whole API", so every
    dataset a test creates needs its own.
    """
    _dataset_slug_counter["n"] += 1
    return f"{prefix}-{_dataset_slug_counter['n']:03d}"


def dataset_payload(
    request_id: str,
    investigation_id: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """A dataset registered against the request it was acquired under."""
    payload: Dict[str, Any] = {
        "request_id": request_id,
        "investigation_id": investigation_id,
        "name": unique_dataset_name(),
        "negotiated_format": C.FORMAT_CSV,
        "expected_field_count": 2,
        "sensitivity_tier": "RESTRICTED",
    }
    payload.update(overrides)
    return _clean(payload)


def delivery_payload(
    delivered_format: str = C.FORMAT_CSV, record_count: int = 500, **overrides: Any
) -> Dict[str, Any]:
    """The agency's actual delivery (PRD S3.6)."""
    payload: Dict[str, Any] = {
        "delivered_format": delivered_format,
        "record_count": record_count,
    }
    payload.update(overrides)
    return _clean(payload)


def field_definition_payload(
    field_name: str,
    reidentification_risk: int = 4,
    is_source_identifying: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    """One documented column: snake_case name, integer risk in points 0-10."""
    payload: Dict[str, Any] = {
        "field_name": field_name,
        "data_type": "STRING",
        "null_rate_pct": 1.5,
        "reidentification_risk": reidentification_risk,
        "is_source_identifying": is_source_identifying,
    }
    payload.update(overrides)
    return _clean(payload)


def field_suppression_payload(field_definition_id: str, **overrides: Any) -> Dict[str, Any]:
    """A suppression of one documented column (PRD S3.6)."""
    payload: Dict[str, Any] = {
        "field_definition_id": field_definition_id,
        "suppression_method": "HASH_REDACT",
    }
    payload.update(overrides)
    return _clean(payload)


def cleaning_lock_payload(**overrides: Any) -> Dict[str, Any]:
    """The cleaning lock and its notes (PRD S3.6)."""
    payload: Dict[str, Any] = {
        "cleaning_notes": "Deduplicated on permit id; normalised inspection dates.",
    }
    payload.update(overrides)
    return _clean(payload)


def quarantine_payload(
    quarantine_reason_code: str = "MISMATCHED_TOTALS", **overrides: Any
) -> Dict[str, Any]:
    """A quarantine and the data-quality reason for it (PRD S3.6)."""
    payload: Dict[str, Any] = {"quarantine_reason_code": quarantine_reason_code}
    payload.update(overrides)
    return _clean(payload)


def requalification_payload(**overrides: Any) -> Dict[str, Any]:
    """A requalification back to cleaning (PRD S3.6)."""
    payload: Dict[str, Any] = {
        "remediation_notes": "The agency resupplied the missing quarter.",
    }
    payload.update(overrides)
    return _clean(payload)


# --------------------------------------------------------------------------
# Investigation and AnalysisRun (PRD S3.7)
# --------------------------------------------------------------------------


def investigation_payload(
    desk_id: str,
    publication_mode: str = C.MODE_FULL_DATA_RELEASE,
    **overrides: Any,
) -> Dict[str, Any]:
    """An investigation with its publication mode declared up front."""
    payload: Dict[str, Any] = {
        "desk_id": desk_id,
        "headline": "Housing inspectors cleared buildings they never entered",
        "publication_mode": publication_mode,
    }
    payload.update(overrides)
    return _clean(payload)


# A 40-character lowercase hex commit sha and a sha256 container digest
# (PRD S3.7 pins both widths exactly).
COMMIT_SHA = "a3f1c0d9e8b7a6958473625140f9e8d7c6b5a493"
COMMIT_SHA_ALT = "b4e2d1a8f7c6b5a49382716059e8d7c6b5a49382"
CONTAINER_DIGEST = (
    "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
)


def analysis_run_payload(
    investigation_id: str,
    expected_investigation_version: int,
    compute_cost_cents: int = 12000,
    labor_hours: float = 3.5,
    **overrides: Any,
) -> Dict[str, Any]:
    """A reproducible run pinned to a commit and a container digest."""
    payload: Dict[str, Any] = {
        "investigation_id": investigation_id,
        "code_repo_ref": "github.com/metro-desk/housing-inspections",
        "code_commit_sha": COMMIT_SHA,
        "container_digest": CONTAINER_DIGEST,
        "compute_cost_cents": compute_cost_cents,
        "labor_hours": labor_hours,
        "expected_investigation_version": expected_investigation_version,
    }
    payload.update(overrides)
    return _clean(payload)


def peer_review_payload(
    decision: str = C.REVIEW_APPROVED, **overrides: Any
) -> Dict[str, Any]:
    """A methodology peer review (PRD S3.7)."""
    payload: Dict[str, Any] = {
        "decision": decision,
        "peer_review_note": "Reproduced the notebook end to end against the digest.",
    }
    payload.update(overrides)
    return _clean(payload)


# --------------------------------------------------------------------------
# Finding, ExpertReviewer and ReviewAssignment (PRD S3.8)
# --------------------------------------------------------------------------


def finding_payload(
    investigation_id: str, analysis_run_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A publishable claim asserted against the run that produced it."""
    payload: Dict[str, Any] = {
        "investigation_id": investigation_id,
        "analysis_run_id": analysis_run_id,
        "claim_text": "Twelve percent of 2025 inspections logged no site visit.",
    }
    payload.update(overrides)
    return _clean(payload)


def document_match_payload(matched_page: int = 14, **overrides: Any) -> Dict[str, Any]:
    """A documentary match against a specific page (PRD S3.8)."""
    payload: Dict[str, Any] = {
        "source_document_ref": "HOU-INSP-2025-AUDIT-PACKET",
        "matched_page": matched_page,
    }
    payload.update(overrides)
    return _clean(payload)


def verification_revocation_payload(**overrides: Any) -> Dict[str, Any]:
    """A revocation of a finding's verification (PRD S3.8)."""
    payload: Dict[str, Any] = {
        "reason": "The cited page does not support the claim as written.",
    }
    payload.update(overrides)
    return _clean(payload)


def expert_reviewer_payload(**overrides: Any) -> Dict[str, Any]:
    """A registered subject-matter expert (PRD S3.8)."""
    payload: Dict[str, Any] = {
        "name": "Dr. Ana Reyes",
        "affiliation": "State University Housing Lab",
        "expertise_code": "HOUSING",
        "max_concurrent_assignments": 2,
    }
    payload.update(overrides)
    return _clean(payload)


def review_assignment_payload(
    reviewer_id: str,
    finding_id: str,
    window_start: str = "2026-09-01T00:00:00Z",
    window_end: str = "2026-09-05T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """An assignment with its closed committed window (PRD S3.8)."""
    payload: Dict[str, Any] = {
        "reviewer_id": reviewer_id,
        "finding_id": finding_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return _clean(payload)


def verdict_payload(
    verdict: str = C.VERDICT_CONFIRMED, **overrides: Any
) -> Dict[str, Any]:
    """The expert's verdict on an assigned finding (PRD S3.8)."""
    payload: Dict[str, Any] = {
        "verdict": verdict,
        "rationale": "The inspection logs corroborate the stated proportion.",
    }
    payload.update(overrides)
    return _clean(payload)


# --------------------------------------------------------------------------
# Right of reply, enclaves and publication (PRD S3.9)
# --------------------------------------------------------------------------


def subject_response_request_payload(
    investigation_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A right-of-reply record for a named subject (PRD S3.9)."""
    payload: Dict[str, Any] = {
        "investigation_id": investigation_id,
        "subject_name": "Metro Housing Inspection Bureau",
        "contact_channel": "EMAIL",
    }
    payload.update(overrides)
    return _clean(payload)


def attempt_payload(
    channel: str = "EMAIL", deliverable: bool = True, **overrides: Any
) -> Dict[str, Any]:
    """One documented attempt to reach the subject (PRD S3.9)."""
    payload: Dict[str, Any] = {
        "channel": channel,
        "deliverable": deliverable,
        "note": "Notice letter sent to the bureau's press office.",
    }
    payload.update(overrides)
    return _clean(payload)


def subject_response_payload(
    on_the_record: bool = True, **overrides: Any
) -> Dict[str, Any]:
    """The subject's reply (PRD S3.9)."""
    payload: Dict[str, Any] = {
        "response_text": "The bureau disputes the characterisation of its logs.",
        "on_the_record": on_the_record,
    }
    payload.update(overrides)
    return _clean(payload)


def secure_enclave_payload(**overrides: Any) -> Dict[str, Any]:
    """A secure reading room (PRD S3.9)."""
    payload: Dict[str, Any] = {
        "name": "Reading Room A",
        "max_documents": 20,
        "sanitization_buffer_minutes": 30,
    }
    payload.update(overrides)
    return _clean(payload)


def enclave_session_payload(
    enclave_id: str,
    dataset_id: str,
    start_at: str = "2026-08-20T09:00:00Z",
    end_at: str = "2026-08-20T11:00:00Z",
    document_count: int = 5,
    **overrides: Any,
) -> Dict[str, Any]:
    """A half-open supervised reading session (PRD S3.9)."""
    payload: Dict[str, Any] = {
        "enclave_id": enclave_id,
        "dataset_id": dataset_id,
        "start_at": start_at,
        "end_at": end_at,
        "document_count": document_count,
        "purpose": "Review the unredacted inspector notes with counsel present.",
    }
    payload.update(overrides)
    return _clean(payload)


def session_closure_payload(documents_returned_count: int, **overrides: Any) -> Dict[str, Any]:
    """A session closure accounting for every document (PRD S3.9)."""
    payload: Dict[str, Any] = {
        "documents_returned_count": documents_returned_count,
    }
    payload.update(overrides)
    return _clean(payload)


def legal_clearance_payload(**overrides: Any) -> Dict[str, Any]:
    """A legal clearance and its note (PRD S3.9)."""
    payload: Dict[str, Any] = {
        "clearance_note": "Counsel reviewed the release set and the notice record.",
    }
    payload.update(overrides)
    return _clean(payload)


def publication_payload(
    release_dataset_id: Any = OMIT, **overrides: Any
) -> Dict[str, Any]:
    """A publication naming the methodology write-up (PRD S3.9)."""
    payload: Dict[str, Any] = {
        "methodology_doc_ref": "METHOD-HOU-INSP-2025-v3",
        "release_dataset_id": release_dataset_id,
    }
    payload.update(overrides)
    return _clean(payload)
