"""
Request payload builders.

Every builder emits exactly the field types the PRD declares: counts, monetary
cent amounts, percentages and reported values travel as JSON numbers rather than
strings; census_date and the two coverage dates are calendar dates in YYYY-MM-DD
form; collection_deadline, the effective window and every clock instant are full
ISO 8601 UTC instants. Free-text fields default to strings that satisfy the
declared length bounds so that a test only overrides what it is actually probing.
"""

import itertools
from typing import Any, Dict, List, Optional

from .api_client import OMIT
from .constants import (
    AVOIDANCE_SMALL_CELL_SUPPRESSION,
    CENSUS_DATE,
    COHORT_GRAD_RATE_150,
    COLLECTION_DEADLINE,
    COLLECTION_YEAR,
    COVERAGE_END,
    COVERAGE_START,
    CYCLE_CODE,
    DECISION_ACCEPT,
    DECISION_APPROVE,
    DEFAULT_MIN_CELL_SIZE,
    DOMAIN_ENROLLMENT,
    EFFECTIVE_FROM,
    ENTRY_FULL_TIME,
    EXCLUSION_CODE_DECEASED,
    LOCAL_SYSTEM_SIS,
    METRIC_TOTAL_HEADCOUNT,
    OUTCOME_STILL_ENROLLED,
    REQUESTER_MEDIA,
    TARGET_CONSORTIUM,
)

_checksum_counter = itertools.count(1)


def next_checksum(prefix: str = "a1b2c3d4e5f6") -> str:
    """A distinct 16-character extract fingerprint, inside the 8-64 character bound."""
    return f"{prefix}{next(_checksum_counter):04d}"


# ─── Reporting cycles ─────────────────────────────────────────────


def make_reporting_cycle_payload(
    cycle_code: str = CYCLE_CODE,
    collection_year: int = COLLECTION_YEAR,
    census_date: str = CENSUS_DATE,
    collection_deadline: str = COLLECTION_DEADLINE,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cycle_code": cycle_code,
        "collection_year": collection_year,
        "census_date": census_date,
        "collection_deadline": collection_deadline,
    }
    payload.update(overrides)
    return payload


def make_reopen_payload(
    reopen_reason: str = "State auditors identified a late residency reclassification affecting the fall census.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reopen_reason": reopen_reason}
    payload.update(overrides)
    return payload


# ─── Census extracts ──────────────────────────────────────────────


def make_frozen_file_payload(
    expected_cycle_version: int,
    domain: str = DOMAIN_ENROLLMENT,
    record_count: int = 1000,
    coverage_start_date: str = COVERAGE_START,
    coverage_end_date: str = COVERAGE_END,
    checksum: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "domain": domain,
        "record_count": record_count,
        "coverage_start_date": coverage_start_date,
        "coverage_end_date": coverage_end_date,
        "checksum": checksum or next_checksum(),
        "expected_cycle_version": expected_cycle_version,
    }
    payload.update(overrides)
    return payload


# ─── Survey components ────────────────────────────────────────────


def make_survey_component_payload(
    cycle_id: str,
    frozen_file_id: str,
    component_code: str = DOMAIN_ENROLLMENT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cycle_id": cycle_id,
        "frozen_file_id": frozen_file_id,
        "component_code": component_code,
    }
    payload.update(overrides)
    return payload


def make_metric_payload(
    metric_key: str = METRIC_TOTAL_HEADCOUNT,
    reported_value: float = 1000,
    prior_year_value: Any = OMIT,
    source_field_path: str = "sis.enrollment.total_headcount",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "metric_key": metric_key,
        "reported_value": reported_value,
        "prior_year_value": prior_year_value,
        "source_field_path": source_field_path,
    }
    payload.update(overrides)
    return payload


def make_metric_correction_payload(
    reported_value: float,
    restatement_note: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "reported_value": reported_value,
        "restatement_note": restatement_note,
    }
    payload.update(overrides)
    return payload


def make_certification_payload(
    certification_statement: str = "I certify the fall enrollment component as reported to the federal collection.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"certification_statement": certification_statement}
    payload.update(overrides)
    return payload


def make_revert_payload(
    decertify_reason: str = "Decertified for a post-freeze review of the residency coding.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decertify_reason": decertify_reason}
    payload.update(overrides)
    return payload


# ─── Edit checks ──────────────────────────────────────────────────


def make_explanation_payload(
    explanation_text: str = "Headcount rose because the new nursing programme enrolled its first cohort.",
    prior_year_comparison_note: str = "Prior year 1000, current year 1100, all growth in the nursing programme.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "explanation_text": explanation_text,
        "prior_year_comparison_note": prior_year_comparison_note,
    }
    payload.update(overrides)
    return payload


def make_adjudication_payload(
    decision: str = DECISION_ACCEPT,
    adjudication_note: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": decision,
        "adjudication_note": adjudication_note,
    }
    payload.update(overrides)
    return payload


# ─── Cohorts, members and exclusions ──────────────────────────────


def make_cohort_payload(
    cohort_type: str = COHORT_GRAD_RATE_150,
    entry_term: str = "FALL2020",
    publication_metric_key: str = "GRAD_RATE_150_FALL2020",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cohort_type": cohort_type,
        "entry_term": entry_term,
        "publication_metric_key": publication_metric_key,
    }
    payload.update(overrides)
    return payload


def make_member_payload(
    student_local_id: str,
    entry_status: str = ENTRY_FULL_TIME,
    outcome: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "student_local_id": student_local_id,
        "entry_status": entry_status,
        "outcome": outcome,
    }
    payload.update(overrides)
    return payload


def make_outcome_payload(outcome: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    payload.update(overrides)
    return payload


def make_exclusion_claim_payload(
    exclusion_code: str = EXCLUSION_CODE_DECEASED,
    exclusion_evidence_note: str = "Death certificate on file, dated 2021-03-04.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "exclusion_code": exclusion_code,
        "exclusion_evidence_note": exclusion_evidence_note,
    }
    payload.update(overrides)
    return payload


def make_exclusion_review_payload(
    decision: str = DECISION_APPROVE,
    review_note: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision, "review_note": review_note}
    payload.update(overrides)
    return payload


# ─── Federal definitions and element mappings ─────────────────────


def make_federal_definition_payload(
    definition_code: str = "EF_TOTAL_HEADCOUNT",
    survey_component: str = DOMAIN_ENROLLMENT,
    value_domain: Optional[List[str]] = None,
    unit_of_measure: str = "HEADCOUNT",
    effective_cycle_code: str = CYCLE_CODE,
    required: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "definition_code": definition_code,
        "survey_component": survey_component,
        "value_domain": value_domain if value_domain is not None else ["FULL_TIME", "PART_TIME"],
        "unit_of_measure": unit_of_measure,
        "effective_cycle_code": effective_cycle_code,
        "required": required,
    }
    payload.update(overrides)
    return payload


def make_element_mapping_payload(
    cycle_id: str,
    definition_id: str,
    local_system_code: str = LOCAL_SYSTEM_SIS,
    local_field_path: str = "SIS.STUDENT.ENROLLMENT_STATUS",
    transform_expression: str = "UPPER(TRIM(x))",
    value_map: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cycle_id": cycle_id,
        "definition_id": definition_id,
        "local_system_code": local_system_code,
        "local_field_path": local_field_path,
        "transform_expression": transform_expression,
        "value_map": value_map if value_map is not None else {"FT": "FULL_TIME", "PT": "PART_TIME"},
    }
    payload.update(overrides)
    return payload


def make_mapping_verdict_payload(
    decision: str = DECISION_APPROVE,
    rejection_reason: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": decision,
        "rejection_reason": rejection_reason,
    }
    payload.update(overrides)
    return payload


def make_mapping_revision_payload(
    transform_expression: str = "UPPER(TRIM(COALESCE(x, 'UNKNOWN')))",
    value_map: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "transform_expression": transform_expression,
        "value_map": value_map if value_map is not None else {"FT": "FULL_TIME"},
    }
    payload.update(overrides)
    return payload


# ─── External submissions ─────────────────────────────────────────


def make_external_submission_payload(
    cycle_id: str,
    component_id: str,
    target_type: str = TARGET_CONSORTIUM,
    target_name: str = "Regional Higher-Ed Consortium",
    metric_key: str = METRIC_TOTAL_HEADCOUNT,
    reported_value: float = 1014,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cycle_id": cycle_id,
        "component_id": component_id,
        "target_type": target_type,
        "target_name": target_name,
        "metric_key": metric_key,
        "reported_value": reported_value,
    }
    payload.update(overrides)
    return payload


def make_variance_override_payload(
    override_reason: str = "The ranking publisher's definition of full-time equivalent enrollment differs materially from the federal one.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"override_reason": override_reason}
    payload.update(overrides)
    return payload


def make_transmission_payload(
    transmission_reference: str = "RNK-2027-0001",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"transmission_reference": transmission_reference}
    payload.update(overrides)
    return payload


# ─── Publications and restatements ────────────────────────────────


def make_publication_payload(
    component_id: str,
    metric_key: str = "TOTAL_HEADCOUNT_FALL",
    published_value: float = 1000.0,
    effective_from: str = EFFECTIVE_FROM,
    effective_to: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "component_id": component_id,
        "metric_key": metric_key,
        "published_value": published_value,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    payload.update(overrides)
    return payload


def make_withdrawal_payload(
    withdrawal_reason: str = "Superseded by the corrected fall headcount series.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"withdrawal_reason": withdrawal_reason}
    payload.update(overrides)
    return payload


def make_restatement_payload(
    proposed_value: float,
    expected_publication_version: int,
    justification: str = "Twenty-five late-conferred degrees were omitted from the original extract.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "proposed_value": proposed_value,
        "justification": justification,
        "expected_publication_version": expected_publication_version,
    }
    payload.update(overrides)
    return payload


def make_restatement_approval_payload(
    public_notice_reference: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"public_notice_reference": public_notice_reference}
    payload.update(overrides)
    return payload


def make_restatement_rejection_payload(
    rejection_reason: str = "The proposed figure is not supported by the certified extract.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"rejection_reason": rejection_reason}
    payload.update(overrides)
    return payload


# ─── Data requests and disclosure cells ───────────────────────────


def make_data_request_payload(
    requester_org: str = "State Capital Press Bureau",
    requester_type: str = REQUESTER_MEDIA,
    requested_metric_key: str = "HEADCOUNT_BY_RACE",
    avoidance_method: Any = OMIT,
    min_cell_size: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "requester_org": requester_org,
        "requester_type": requester_type,
        "requested_metric_key": requested_metric_key,
        "avoidance_method": avoidance_method,
        "min_cell_size": min_cell_size,
    }
    payload.update(overrides)
    return payload


def make_disclosure_cell_payload(
    dimension_group: str,
    dimension_key: str,
    raw_count: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "dimension_group": dimension_group,
        "dimension_key": dimension_key,
        "raw_count": raw_count,
    }
    payload.update(overrides)
    return payload


def make_release_payload(release_note: Any = OMIT, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"release_note": release_note}
    payload.update(overrides)
    return payload


DEFAULT_MIN_CELL_SIZE_LITERAL = DEFAULT_MIN_CELL_SIZE
DEFAULT_AVOIDANCE_METHOD_LITERAL = AVOIDANCE_SMALL_CELL_SUPPRESSION
DEFAULT_OUTCOME_LITERAL = OUTCOME_STILL_ENROLLED
