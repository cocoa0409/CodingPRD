"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_seq = itertools.count(1)


def _suffix() -> str:
    return f"{next(_seq):06d}"


def create_health_plan_payload(**overrides) -> dict:
    s = _suffix()
    defaults = {
        "name": f"{TEST_DEFAULTS['PLAN_NAME']} {s}",
        "plan_code": f"{TEST_DEFAULTS['PLAN_CODE']}-{s}",
    }
    defaults.update(overrides)
    return defaults


def create_standards_edition_payload(**overrides) -> dict:
    defaults = {
        "edition_year": TEST_DEFAULTS["EDITION_YEAR"],
        "effective_from": TEST_DEFAULTS["EFFECTIVE_FROM"],
        "effective_until": TEST_DEFAULTS["EFFECTIVE_UNTIL"],
        "min_file_sample_per_category": TEST_DEFAULTS["MIN_FILE_SAMPLE_PER_CATEGORY"],
        "timeliness_threshold": TEST_DEFAULTS["TIMELINESS_THRESHOLD"],
    }
    defaults.update(overrides)
    return defaults


def create_standard_element_payload(**overrides) -> dict:
    defaults = {
        "element_code": f"EL-{_suffix()}",
        "category": "UM",
        "max_points": 4,
        "is_must_pass": False,
        "evidence_required_count": 0,
    }
    defaults.update(overrides)
    return defaults


def create_product_line_scope_payload(**overrides) -> dict:
    defaults = {
        "product_line": "COMMERCIAL",
        "state_codes": ["OR", "WA"],
        "member_count": 120000,
    }
    defaults.update(overrides)
    return defaults


def create_surveyor_payload(**overrides) -> dict:
    defaults = {
        "name": f"Surveyor {_suffix()}",
        "credential_level": "LEAD",
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(product_line_scope_id, standards_edition_id, **overrides) -> dict:
    defaults = {
        "product_line_scope_id": product_line_scope_id,
        "standards_edition_id": standards_edition_id,
        "review_period_start": TEST_DEFAULTS["REVIEW_PERIOD_START"],
        "review_period_end": TEST_DEFAULTS["REVIEW_PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def create_evidence_item_payload(standard_element_id, expected_application_version, **overrides) -> dict:
    defaults = {
        "standard_element_id": standard_element_id,
        "title": f"Evidence {_suffix()}",
        "expected_application_version": expected_application_version,
    }
    defaults.update(overrides)
    return defaults


def create_file_review_sample_payload(**overrides) -> dict:
    defaults = {
        "sample_type": "DENIAL",
        "required_size": TEST_DEFAULTS["MIN_FILE_SAMPLE_PER_CATEGORY"],
        "timeliness_basis": "DECISION_DATE",
    }
    defaults.update(overrides)
    return defaults


def create_file_review_case_payload(**overrides) -> dict:
    defaults = {
        "case_reference": f"CASE-{_suffix()}",
        "service_date": "2025-03-01T00:00:00Z",
        "decision_date": "2025-03-10T00:00:00Z",
        "resolution_date": "2025-03-10T00:00:00Z",
        "required_turnaround_days": 30,
    }
    defaults.update(overrides)
    return defaults


def create_survey_payload(expected_application_version, **overrides) -> dict:
    defaults = {
        "survey_type": "FULL",
        "mode": "VIRTUAL",
        "start_date": TEST_DEFAULTS["SURVEY_START"],
        "end_date": TEST_DEFAULTS["SURVEY_END"],
        "budgeted_surveyor_hours": 8,
        "expected_application_version": expected_application_version,
    }
    defaults.update(overrides)
    return defaults


def create_survey_session_payload(surveyor_id, **overrides) -> dict:
    defaults = {
        "surveyor_id": surveyor_id,
        "session_date": TEST_DEFAULTS["SURVEY_START"],
        "start_minute": 540,
        "end_minute": 660,
        "is_onsite": False,
    }
    defaults.update(overrides)
    return defaults


def create_surveyor_question_payload(standard_element_id, **overrides) -> dict:
    defaults = {
        "standard_element_id": standard_element_id,
        "question_text": f"Probe question {_suffix()}",
        "raises_gap": True,
    }
    defaults.update(overrides)
    return defaults


def create_element_score_payload(standard_element_id, **overrides) -> dict:
    defaults = {"standard_element_id": standard_element_id}
    defaults.update(overrides)
    return defaults


def create_quality_measure_result_payload(**overrides) -> dict:
    defaults = {
        "measure_code": f"M-{_suffix()}",
        "measurement_year": 2025,
        "percentile": 100,
        "is_reportable": True,
    }
    defaults.update(overrides)
    return defaults


def create_consumer_survey_score_payload(**overrides) -> dict:
    defaults = {
        "survey_year": 2025,
        "composite_score": 100.00,
        "response_count": 900,
    }
    defaults.update(overrides)
    return defaults


def create_corrective_action_plan_payload(standard_element_id, **overrides) -> dict:
    defaults = {
        "standard_element_id": standard_element_id,
        "gap_description": f"Element-level gap {_suffix()}",
        "due_date": "2027-06-30",
    }
    defaults.update(overrides)
    return defaults


def create_annual_report_payload(**overrides) -> dict:
    defaults = {
        "reporting_year": 2027,
        "attestation": "We attest the data submitted is complete and accurate.",
    }
    defaults.update(overrides)
    return defaults
