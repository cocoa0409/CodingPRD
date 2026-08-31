"""Entity assertions and domain invariant checkers."""

import re

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AppealStatus, ArtifactStatus, ArtifactType, CalibrationOutcome,
    CertificationStatus, CompositeRating, CompositeVariant, CycleStatus,
    CycleType, DisputeState, DomainCode, GrievanceRemedy, GrievanceStatus,
    GrowthMeasureStatus, MeasureCode, ObservationStatus, ObservationType,
    PlanStatus, PlanTriggerReason, SchoolLevel, SubmittedByRole, TenureStatus,
)

_MS_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _values(enum_cls):
    return [m.value for m in enum_cls]


# ─── Shared envelope-level assertions ─────────────────────────────────────

def assert_common_fields(data: dict, entity_name: str = "resource"):
    """Every resource the API mints carries a bare UUID id, created_at,
    updated_at and version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a server-generated UUID, got {data.get('id')!r}"
    )
    assert "_" not in str(data.get("id", "")), f"{entity_name}.id must carry no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an integer that begins at 1"
    )


def assert_millisecond_timestamp(value: str, label: str = "timestamp"):
    """ISO 8601 UTC timestamp with three fractional digits (PRD §2.4)."""
    assert _MS_TIMESTAMP_RE.match(value or ""), (
        f"{label} must be an ISO 8601 UTC timestamp with three fractional digits, got {value!r}"
    )


def assert_two_decimals(value, label="value"):
    assert value is not None, f"{label} must not be null"
    assert round(float(value), 2) == pytest.approx(float(value)), (
        f"{label} must carry at most 2 decimal places, got {value}"
    )


def assert_four_decimals(value, label="value"):
    assert value is not None, f"{label} must not be null"
    assert round(float(value), 4) == pytest.approx(float(value)), (
        f"{label} must carry at most 4 decimal places, got {value}"
    )


# ─── Per-entity assertions ────────────────────────────────────────────────

def assert_evaluation_policy(data: dict):
    assert_common_fields(data, "EvaluationPolicy")
    assert isinstance(data["school_year"], str) and data["school_year"]
    for field in ("observation_weight_pct", "growth_weight_pct", "planning_weight_pct",
                  "environment_weight_pct", "instruction_weight_pct",
                  "professionalism_weight_pct"):
        assert 0 <= float(data[field]) <= 100, f"{field} must lie between 0 and 100"
    assert float(data["observation_weight_pct"]) + float(data["growth_weight_pct"]) == pytest.approx(100)
    domain_sum = sum(float(data[f]) for f in (
        "planning_weight_pct", "environment_weight_pct",
        "instruction_weight_pct", "professionalism_weight_pct"))
    assert domain_sum == pytest.approx(100), "the four rubric domain weights must sum to 100"
    assert int(data["required_formal_count"]) >= 1
    assert int(data["required_informal_count"]) >= 0


def assert_school(data: dict):
    assert_common_fields(data, "School")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["code"], str) and data["code"]
    assert data["level"] in _values(SchoolLevel)
    assert int(data["evaluation_budget_allocated_cents"]) >= 0
    assert_school_budget_invariants(data)


def assert_school_budget_invariants(data: dict):
    """evaluation_budget_remaining_cents is always the allocation minus the
    committed total, and every monetary amount is integer cents (PRD §2.10)."""
    allocated = data["evaluation_budget_allocated_cents"]
    committed = data["evaluation_budget_committed_cents"]
    remaining = data["evaluation_budget_remaining_cents"]
    for label, amount in (("allocated", allocated), ("committed", committed),
                          ("remaining", remaining)):
        assert isinstance(amount, int), f"evaluation_budget_{label}_cents must be integer cents"
    assert remaining == allocated - committed, (
        f"remaining ({remaining}) must equal allocated ({allocated}) minus committed ({committed})"
    )
    assert committed >= 0, "committed cents must never go negative"


def assert_educator(data: dict):
    assert_common_fields(data, "Educator")
    assert isinstance(data["school_id"], str)
    assert isinstance(data["employee_number"], str) and data["employee_number"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert _DATE_RE.match(data["service_start_date"]), "service_start_date is a plain YYYY-MM-DD date"
    assert data["tenure_status"] in _values(TenureStatus)
    assert isinstance(data["completed_service_years"], int)
    assert isinstance(data["consecutive_effective_years"], int)
    assert isinstance(data["tenure_track_hold"], bool)
    assert data["last_composite_rating"] is None or data["last_composite_rating"] in _values(CompositeRating)


def assert_evaluator(data: dict):
    assert_common_fields(data, "Evaluator")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["certification_status"] in _values(CertificationStatus)
    assert data["certification_expires_on"] is None or _DATE_RE.match(data["certification_expires_on"])
    assert isinstance(data["consecutive_failed_calibrations"], int)
    assert_two_decimals(data["calibration_drift_rolling"], "calibration_drift_rolling")
    assert_two_decimals(data["calibration_drift_anchor"], "calibration_drift_anchor")


def assert_evaluation_cycle(data: dict):
    assert_common_fields(data, "EvaluationCycle")
    assert data["status"] in _values(CycleStatus)
    assert data["dispute_state"] in _values(DisputeState)
    assert data["cycle_type"] in _values(CycleType)
    assert isinstance(data["completed_formal_count"], int)
    assert isinstance(data["completed_informal_count"], int)
    assert isinstance(data["evidence_artifact_count"], int)
    if data["observation_component"] is not None:
        assert_four_decimals(data["observation_component"], "observation_component")
    if data["growth_component"] is not None:
        assert_four_decimals(data["growth_component"], "growth_component")
    if data["composite_score"] is not None:
        assert_two_decimals(data["composite_score"], "composite_score")
        assert 1.00 <= float(data["composite_score"]) <= 4.00, (
            "composite_score is clamped to the four-point scale"
        )
    assert data["composite_rating"] is None or data["composite_rating"] in _values(CompositeRating)
    assert data["composite_variant"] is None or data["composite_variant"] in _values(CompositeVariant)


def assert_observation(data: dict):
    assert_common_fields(data, "Observation")
    assert data["status"] in _values(ObservationStatus)
    assert data["observation_type"] in _values(ObservationType)
    assert isinstance(data["announced"], bool)
    assert isinstance(data["scored_domain_count"], int)
    assert isinstance(data["evidence_count"], int)
    assert isinstance(data["stipend_cents"], int), "stipend_cents is an integer number of cents"
    assert isinstance(data["return_count"], int)
    if data["weighted_score"] is not None:
        assert_two_decimals(data["weighted_score"], "weighted_score")
        assert 1.00 <= float(data["weighted_score"]) <= 4.00


def assert_rubric_score(data: dict):
    assert_common_fields(data, "RubricScore")
    assert data["domain_code"] in _values(DomainCode)
    assert isinstance(data["raw_score"], int) and 1 <= data["raw_score"] <= 4
    assert_two_decimals(data["weighted_contribution"], "weighted_contribution")
    assert isinstance(data["superseded"], bool)
    assert isinstance(data["observation_version_after"], int)


def assert_evidence_artifact(data: dict):
    assert_common_fields(data, "EvidenceArtifact")
    assert data["artifact_type"] in _values(ArtifactType)
    assert isinstance(data["title"], str) and data["title"]
    assert data["status"] in _values(ArtifactStatus)
    assert data["submitted_by_role"] in _values(SubmittedByRole)


def assert_growth_measure(data: dict):
    assert_common_fields(data, "GrowthMeasure")
    assert data["measure_code"] in _values(MeasureCode)
    assert 1.00 <= float(data["index_value"]) <= 4.00
    assert 0 < float(data["coverage_pct"]) <= 100
    assert data["status"] in _values(GrowthMeasureStatus)
    assert isinstance(data["cycle_version_after"], int)


def assert_improvement_plan(data: dict):
    assert_common_fields(data, "ImprovementPlan")
    assert data["status"] in _values(PlanStatus)
    assert data["trigger_reason"] in _values(PlanTriggerReason)
    assert isinstance(data["extension_days_used"], int)
    assert data["escalation_level"] in (1, 2)


def assert_appeal(data: dict):
    assert_common_fields(data, "Appeal")
    assert data["status"] in _values(AppealStatus)
    assert isinstance(data["statement"], str) and data["statement"]
    if data["adjusted_composite"] is not None:
        assert 1.00 <= float(data["adjusted_composite"]) <= 4.00


def assert_grievance(data: dict):
    assert_common_fields(data, "Grievance")
    assert data["status"] in _values(GrievanceStatus)
    assert data["remedy"] in _values(GrievanceRemedy)


def assert_calibration_review(data: dict):
    assert_common_fields(data, "CalibrationReview")
    assert data["outcome"] in _values(CalibrationOutcome)
    assert_two_decimals(data["deviation"], "deviation")
    assert 1.00 <= float(data["anchor_score"]) <= 4.00
    assert 1.00 <= float(data["evaluator_score"]) <= 4.00


# ─── Domain invariants ────────────────────────────────────────────────────

def assert_evidence_ledger(cycle: dict, observations: list):
    """A cycle's evidence_artifact_count is the sum of evidence_count across
    the cycle's observations whose status is not VOIDED (PRD §2.10)."""
    expected = sum(o["evidence_count"] for o in observations
                   if o["status"] != ObservationStatus.VOIDED.value)
    assert cycle["evidence_artifact_count"] == expected, (
        f"cycle evidence_artifact_count {cycle['evidence_artifact_count']} "
        f"must equal the non-voided observation total {expected}"
    )


def assert_stipend_ledger(school: dict, observations: list):
    """A school's evaluation_budget_committed_cents equals the sum of
    stipend_cents over observations in SUBMITTED or ACCEPTED (PRD §2.10)."""
    counted = (ObservationStatus.SUBMITTED.value, ObservationStatus.ACCEPTED.value)
    expected = sum(o["stipend_cents"] for o in observations if o["status"] in counted)
    assert school["evaluation_budget_committed_cents"] == expected, (
        f"school committed cents {school['evaluation_budget_committed_cents']} "
        f"must equal the SUBMITTED/ACCEPTED stipend total {expected}"
    )
    assert_school_budget_invariants(school)
