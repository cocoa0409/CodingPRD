"""Request payload builders.

Every builder emits only the fields the PRD declares for its endpoint, with
numbers as JSON numbers and booleans as JSON booleans — never as strings.
Optional fields are omitted entirely unless a caller supplies them, so that
"optional configuration omitted" tests can exercise the server's own defaults.
"""

from typing import Any, Dict, List, Optional

from . import constants as C


def _prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is the sentinel ``None`` (field omitted)."""
    return {key: value for key, value in payload.items() if value is not None}


# ─── Newsrooms, journalists, reviewers (PRD §3.1) ─────


def newsroom_payload(
    name: str = "Metro Ledger",
    correction_response_sla_hours: Optional[int] = None,
    high_severity_open_threshold: Optional[int] = None,
    required_module_codes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return _prune(
        {
            "name": name,
            "correction_response_sla_hours": correction_response_sla_hours,
            "high_severity_open_threshold": high_severity_open_threshold,
            "required_module_codes": required_module_codes,
        }
    )


def journalist_payload(
    newsroom_id: str,
    full_name: str,
    email: str,
    role_title: str,
) -> Dict[str, Any]:
    return {
        "newsroom_id": newsroom_id,
        "full_name": full_name,
        "email": email,
        "role_title": role_title,
    }


def executive_editor_payload(
    newsroom_id: str,
    full_name: str = "Dana Ruiz",
    email: str = "dana@ledger.test",
) -> Dict[str, Any]:
    return journalist_payload(
        newsroom_id, full_name, email, C.TITLE_EXECUTIVE_EDITOR
    )


def standards_editor_payload(
    newsroom_id: str,
    full_name: str = "Sam Okoye",
    email: str = "sam@ledger.test",
) -> Dict[str, Any]:
    return journalist_payload(
        newsroom_id, full_name, email, C.TITLE_STANDARDS_EDITOR
    )


def reporter_payload(
    newsroom_id: str,
    full_name: str = "Rae Lindqvist",
    email: str = "rae@ledger.test",
) -> Dict[str, Any]:
    return journalist_payload(newsroom_id, full_name, email, C.TITLE_REPORTER)


def reviewer_payload(
    newsroom_id: str,
    full_name: str = "Lee Park",
    discipline: str = C.DISCIPLINE_STANDARDS,
    weekly_capacity_minutes: Optional[int] = None,
) -> Dict[str, Any]:
    return _prune(
        {
            "newsroom_id": newsroom_id,
            "full_name": full_name,
            "discipline": discipline,
            "weekly_capacity_minutes": weekly_capacity_minutes,
        }
    )


# ─── Stories (PRD §3.2) ───────────────────────────────


def story_payload(
    newsroom_id: str,
    lead_journalist_id: str,
    headline: str = "A working headline",
    defamation_claim_count: Optional[int] = None,
    privacy_subject_count: Optional[int] = None,
    unverified_document_count: Optional[int] = None,
) -> Dict[str, Any]:
    return _prune(
        {
            "newsroom_id": newsroom_id,
            "lead_journalist_id": lead_journalist_id,
            "headline": headline,
            "defamation_claim_count": defamation_claim_count,
            "privacy_subject_count": privacy_subject_count,
            "unverified_document_count": unverified_document_count,
        }
    )


def unpublish_payload(
    removal_reason: str = "The record no longer supports the central claim.",
    editors_note_text: str = "This story has been removed from the site.",
) -> Dict[str, Any]:
    return {
        "removal_reason": removal_reason,
        "editors_note_text": editors_note_text,
    }


# ─── Anonymous-source approvals (PRD §3.2) ────────────


def source_approval_payload(
    story_id: str,
    source_alias: str = "permit-clerk",
    source_category: str = C.SOURCE_CATEGORY_GOVERNMENT,
    harm_risk: str = C.HARM_ELEVATED,
    identity_known_to_editor: bool = True,
    corroboration_count: Optional[int] = None,
    justification_text: Optional[str] = (
        "Custodian of the permit ledger for four years."
    ),
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "story_id": story_id,
        "source_alias": source_alias,
        "source_category": source_category,
        "harm_risk": harm_risk,
        "identity_known_to_editor": identity_known_to_editor,
    }
    if corroboration_count is not None:
        payload["corroboration_count"] = corroboration_count
    if justification_text is not None:
        payload["justification_text"] = justification_text
    return payload


def source_decision_payload(
    decision: str, decision_note: Optional[str] = "Identity verified."
) -> Dict[str, Any]:
    return _prune({"decision": decision, "decision_note": decision_note})


def source_revocation_payload(
    revocation_reason: str = "The source withdrew their account.",
) -> Dict[str, Any]:
    return {"revocation_reason": revocation_reason}


# ─── Pre-publication reviews (PRD §3.3) ───────────────


def review_payload(
    story_id: str,
    expected_story_version: int,
    high_risk_declared: Optional[bool] = None,
    submission_note: Optional[str] = "Standards read requested.",
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "story_id": story_id,
        "expected_story_version": expected_story_version,
    }
    if high_risk_declared is not None:
        payload["high_risk_declared"] = high_risk_declared
    if submission_note is not None:
        payload["submission_note"] = submission_note
    return payload


def legal_verdict_payload(
    legal_verdict: str,
    defamation_findings: int = 0,
    privacy_findings: int = 0,
    findings_note: Optional[str] = "Legal read complete.",
) -> Dict[str, Any]:
    return _prune(
        {
            "legal_verdict": legal_verdict,
            "defamation_findings": defamation_findings,
            "privacy_findings": privacy_findings,
            "findings_note": findings_note,
        }
    )


def standards_verdict_payload(
    standards_verdict: str,
    findings_note: Optional[str] = "Nothing outstanding.",
) -> Dict[str, Any]:
    return _prune(
        {"standards_verdict": standards_verdict, "findings_note": findings_note}
    )


def resubmit_payload(
    revision_note: Optional[str] = "Revised per the desk's notes.",
) -> Dict[str, Any]:
    return _prune({"revision_note": revision_note})


# ─── Review assignments (PRD §3.4) ────────────────────


def assignment_payload(
    review_id: str,
    reviewer_id: str,
    starts_at: str,
    ends_at: str,
    expected_reviewer_version: int,
) -> Dict[str, Any]:
    return {
        "review_id": review_id,
        "reviewer_id": reviewer_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "expected_reviewer_version": expected_reviewer_version,
    }


def cancellation_payload(
    cancellation_reason: str = "The reviewer is unavailable.",
) -> Dict[str, Any]:
    return {"cancellation_reason": cancellation_reason}


# ─── Correction requests (PRD §3.6) ───────────────────


def correction_request_payload(
    story_id: str,
    submitter_type: str = C.SUBMITTER_READER,
    submitter_email: str = "reader@example.test",
    claim_text: str = "The figure in the third paragraph is wrong.",
    claimed_error_category: str = C.CATEGORY_FACTUAL,
    reader_reported_reach: Optional[int] = None,
    subject_named: Optional[bool] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "story_id": story_id,
        "submitter_type": submitter_type,
        "submitter_email": submitter_email,
        "claim_text": claim_text,
        "claimed_error_category": claimed_error_category,
    }
    if reader_reported_reach is not None:
        payload["reader_reported_reach"] = reader_reported_reach
    if subject_named is not None:
        payload["subject_named"] = subject_named
    return payload


def start_investigation_payload(
    assigned_note: Optional[str] = "Pulling the desk records.",
) -> Dict[str, Any]:
    return _prune({"assigned_note": assigned_note})


def subject_outreach_payload(
    outreach_channel: str = "EMAIL",
    outreach_note: Optional[str] = "Wrote to the subject's counsel.",
) -> Dict[str, Any]:
    return _prune(
        {"outreach_channel": outreach_channel, "outreach_note": outreach_note}
    )


def adjudication_payload(
    outcome_type: str,
    adjudicated_error_category: str,
    verified_reach: int,
    notice_text: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "outcome_type": outcome_type,
        "adjudicated_error_category": adjudicated_error_category,
        "verified_reach": verified_reach,
    }
    if notice_text is not None:
        payload["notice_text"] = notice_text
    return payload


def resolution_payload(
    resolution_note: Optional[str] = "The notice is live.",
) -> Dict[str, Any]:
    return _prune({"resolution_note": resolution_note})


# ─── Misconduct investigations (PRD §3.7) ─────────────


def investigation_payload(
    journalist_id: str,
    allegation_type: str = C.ALLEGATION_PLAGIARISM,
    severity: str = C.SEVERITY_SERIOUS,
    allegation_summary: str = (
        "Two paragraphs match a trade publication verbatim."
    ),
    story_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "journalist_id": journalist_id,
        "allegation_type": allegation_type,
        "severity": severity,
        "allegation_summary": allegation_summary,
    }
    if story_id is not None:
        payload["story_id"] = story_id
    return payload


def advance_payload(
    advance_note: Optional[str] = "Collecting the source documents.",
) -> Dict[str, Any]:
    return _prune({"advance_note": advance_note})


def disposition_payload(
    disposition: str, decision_note: Optional[str] = "The record is clear."
) -> Dict[str, Any]:
    return _prune({"disposition": disposition, "decision_note": decision_note})


def appeal_payload(
    appeal_outcome: str, appeal_note: Optional[str] = "Appeal heard in full."
) -> Dict[str, Any]:
    return _prune({"appeal_outcome": appeal_outcome, "appeal_note": appeal_note})


# ─── Conflicts, outside work, training (PRD §3.8) ─────


def disclosure_payload(
    journalist_id: str,
    disclosure_type: str = C.DISCLOSURE_FINANCIAL,
    subject_entity_name: str = "Harbourline Holdings",
    description: str = "A holding in a company on the reporter's beat.",
) -> Dict[str, Any]:
    return {
        "journalist_id": journalist_id,
        "disclosure_type": disclosure_type,
        "subject_entity_name": subject_entity_name,
        "description": description,
    }


def disclosure_review_payload(
    review_outcome: str, restricted_beats: Optional[List[str]] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"review_outcome": review_outcome}
    if restricted_beats is not None:
        payload["restricted_beats"] = restricted_beats
    return payload


def activity_request_payload(
    journalist_id: str,
    starts_on: str,
    ends_on: str,
    activity_type: str = C.ACTIVITY_SPEAKING,
    compensated: bool = True,
    related_beat: str = "city-hall",
    host_organization: str = "Riverside Civic Forum",
) -> Dict[str, Any]:
    return {
        "journalist_id": journalist_id,
        "activity_type": activity_type,
        "compensated": compensated,
        "starts_on": starts_on,
        "ends_on": ends_on,
        "related_beat": related_beat,
        "host_organization": host_organization,
    }


def activity_decision_payload(
    decision: str, decision_note: Optional[str] = "Reviewed by the desk."
) -> Dict[str, Any]:
    return _prune({"decision": decision, "decision_note": decision_note})


def training_record_payload(
    journalist_id: str,
    module_code: str = C.MODULE_SOURCING,
    case_study_reference: Optional[str] = "CS-2025-01",
) -> Dict[str, Any]:
    return _prune(
        {
            "journalist_id": journalist_id,
            "module_code": module_code,
            "case_study_reference": case_study_reference,
        }
    )


# ─── Logical clock (PRD §2.5) ─────────────────────────


def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}
