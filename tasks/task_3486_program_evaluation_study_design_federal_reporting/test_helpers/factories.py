"""Payload factories — one per request body, input fields only.

Field names and required/optional split follow the PRD endpoint narratives
verbatim. Optional fields are omitted unless explicitly overridden.
"""
from .constants import (
    CLOCK_WITHIN_WAVE,
    IRB_APPROVAL_END,
    IRB_APPROVAL_START,
    WAVE_CLOSE_AT,
    WAVE_OPEN_AT,
    WORKED_ATTRITION_RATE,
    WORKED_CLUSTER_SIZE,
    WORKED_ICC,
    WORKED_MDE,
)

# Standard operator ids mirror the shared role headers.
DEFAULT_AWARD_AMOUNT_CENTS = 90_000_000
DEFAULT_PAYMENT_MILESTONE_CENTS = 30_000_000
DEFAULT_PRIMARY_OUTCOMES = ["employment_q4", "earnings_q4"]


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "agency_code": "ACF-OPRE",
        "title": "Evaluation Contract",
        "award_amount_cents": DEFAULT_AWARD_AMOUNT_CENTS,
    }
    defaults.update(overrides)
    return defaults


def terminate_contract_payload(reason="No longer funded", **overrides) -> dict:
    defaults = {"reason": reason}
    defaults.update(overrides)
    return defaults


def create_study_payload(**overrides) -> dict:
    defaults = {
        "title": "Impact Study",
        "research_question": "Does the program raise employment?",
    }
    defaults.update(overrides)
    return defaults


def create_design_plan_payload(expected_study_version, **overrides) -> dict:
    """expected_study_version is non-optional on this OCC-guarded create."""
    defaults = {
        "design_type": "RCT",
        "mde": WORKED_MDE,
        "cluster_size": WORKED_CLUSTER_SIZE,
        "icc": WORKED_ICC,
        "attrition_rate": WORKED_ATTRITION_RATE,
        "expected_study_version": expected_study_version,
    }
    defaults.update(overrides)
    return defaults


def design_plan_decision_payload(decision="APPROVED", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_irb_protocol_payload(**overrides) -> dict:
    defaults = {
        "title": "IRB Protocol",
        "estimated_burden_minutes": 300,
    }
    defaults.update(overrides)
    return defaults


def irb_decision_payload(decision="APPROVED", **overrides) -> dict:
    defaults = {"decision": decision}
    if decision == "APPROVED":
        defaults.setdefault("approval_start", IRB_APPROVAL_START)
        defaults.setdefault("approval_end", IRB_APPROVAL_END)
    defaults.update(overrides)
    return defaults


def irb_continuing_review_payload(new_approval_end, **overrides) -> dict:
    defaults = {"new_approval_end": new_approval_end}
    defaults.update(overrides)
    return defaults


def create_site_payload(**overrides) -> dict:
    defaults = {"name": "Site A", "max_participants": 250}
    defaults.update(overrides)
    return defaults


def site_outreach_payload(outcome="CONTACTED", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_participant_payload(**overrides) -> dict:
    defaults = {"external_ref": "P001"}
    defaults.update(overrides)
    return defaults


def consent_payload(consent_form_version=1, **overrides) -> dict:
    defaults = {"consent_form_version": consent_form_version}
    defaults.update(overrides)
    return defaults


def withdraw_participant_payload(**overrides) -> dict:
    return dict(overrides)


def create_wave_payload(wave_type="SURVEY", **overrides) -> dict:
    defaults = {
        "wave_type": wave_type,
        "open_at": WAVE_OPEN_AT,
        "close_at": WAVE_CLOSE_AT,
    }
    defaults.update(overrides)
    return defaults


def create_record_payload(participant_id, instrument_minutes=45, **overrides) -> dict:
    defaults = {
        "participant_id": participant_id,
        "instrument_minutes": instrument_minutes,
        "payload_ref": "payload-1",
    }
    defaults.update(overrides)
    return defaults


def create_analysis_plan_payload(**overrides) -> dict:
    defaults = {"primary_outcomes": list(DEFAULT_PRIMARY_OUTCOMES)}
    defaults.update(overrides)
    return defaults


def amend_analysis_plan_payload(**overrides) -> dict:
    defaults = {"secondary_outcomes": ["employment_q8"]}
    defaults.update(overrides)
    return defaults


def create_report_payload(**overrides) -> dict:
    defaults = {
        "title": "Findings Report",
        "report_type": "FINAL",
        "addressed_primary_outcomes": list(DEFAULT_PRIMARY_OUTCOMES),
        "payment_milestone_cents": DEFAULT_PAYMENT_MILESTONE_CENTS,
    }
    defaults.update(overrides)
    return defaults


def report_review_payload(**overrides) -> dict:
    return dict(overrides)


def report_decision_payload(decision="ACCEPTED", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_restricted_use_file_payload(**overrides) -> dict:
    defaults = {
        "title": "Restricted-Use File",
        "cell_counts": [5, 4, 12, 30],
        "sensitivity_weights": [1.0, 1.0, 0.5, 0.5],
    }
    defaults.update(overrides)
    return defaults


def ruf_review_decision_payload(decision="APPROVE", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_dissemination_activity_payload(**overrides) -> dict:
    defaults = {
        "activity_type": "WEBINAR",
        "title": "Findings webinar",
        "scheduled_at": "2026-11-15T00:00:00Z",
        "operator_count": 12,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601=CLOCK_WITHIN_WAVE, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
