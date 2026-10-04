"""Payload factories — one per creatable entity, input fields only."""
from .constants import (
    DEFAULT_LANGUAGE,
    DEFAULT_PERIOD,
    DEFAULT_PROGRAM,
    DEFAULT_TZ,
    FAR_FUTURE_VALID_UNTIL,
)


def create_contract_payload(**overrides):
    defaults = {
        "agency_name": "State Benefits Agency",
        "measurement_tz": DEFAULT_TZ,
        "cap_absolutes": False,
    }
    defaults.update(overrides)
    return defaults


def create_service_level_payload(contract_id, metric="ASA", **overrides):
    targets = {"ASA": 30, "ABANDON": 0.05, "QA_AVG": 80}
    defaults = {
        "contract_id": contract_id,
        "program_code": DEFAULT_PROGRAM,
        "metric": metric,
        "target": targets[metric],
        "cap_pct_of_gross": 1.0,
        "remedy_fee_cents": 1000,
        "effective_from": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_agent_payload(**overrides):
    defaults = {"full_name": "Agent One", "languages": [DEFAULT_LANGUAGE]}
    defaults.update(overrides)
    return defaults


def create_training_course_payload(**overrides):
    defaults = {"program_code": DEFAULT_PROGRAM, "required": True}
    defaults.update(overrides)
    return defaults


def complete_course_payload(agent_id, **overrides):
    defaults = {"agent_id": agent_id, "valid_until": FAR_FUTURE_VALID_UNTIL}
    defaults.update(overrides)
    return defaults


def create_queue_payload(contract_id, **overrides):
    defaults = {
        "contract_id": contract_id,
        "program_code": DEFAULT_PROGRAM,
        "language_code": DEFAULT_LANGUAGE,
        "queue_type": "GENERAL",
    }
    defaults.update(overrides)
    return defaults


def create_call_payload(contract_id, **overrides):
    defaults = {
        "contract_id": contract_id,
        "program_code": DEFAULT_PROGRAM,
        "language_code": DEFAULT_LANGUAGE,
        "enqueued_at": "2026-09-05T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_quality_review_payload(call_id, **overrides):
    defaults = {"call_id": call_id, "accuracy_score": 80, "compliance_score": 80}
    defaults.update(overrides)
    return defaults


def create_coaching_plan_payload(agent_id, **overrides):
    defaults = {"agent_id": agent_id, "due_date": "2026-10-01T00:00:00Z"}
    defaults.update(overrides)
    return defaults


def create_knowledge_article_payload(**overrides):
    defaults = {
        "program_code": DEFAULT_PROGRAM,
        "title": "Rule change",
        "body": "rule body",
        "effective_at": "2026-09-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_surge_window_payload(contract_id, **overrides):
    defaults = {
        "contract_id": contract_id,
        "program_code": DEFAULT_PROGRAM,
        "surge_type": "ENROLLMENT_PERIOD",
        "starts_on": "2026-09-15T00:00:00Z",
        "ends_on": "2026-09-30T00:00:00Z",
        "expected_volume_factor": 1.5,
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(contract_id, **overrides):
    defaults = {
        "contract_id": contract_id,
        "severity": "HIGH",
        "category": "PRIVACY_BREACH",
        "occurred_at": "2026-09-04T12:00:00Z",
        "description": "incident description",
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(contract_id, **overrides):
    defaults = {"contract_id": contract_id, "period": DEFAULT_PERIOD}
    defaults.update(overrides)
    return defaults
