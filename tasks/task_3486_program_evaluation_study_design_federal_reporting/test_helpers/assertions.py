"""Entity assertions and domain invariant checkers.

validate_success here REQUIRES an explicit expected_status — create endpoints
return 201 while transitions/reads return 200, and a silent default would
mis-check one of the two. Framework validators are used internally.
"""
from typing import List

from prd_bench_local_runner.testing import (
    validate_success as _fw_validate_success,
    is_valid_uuid,
    is_iso8601_timestamp,
)
from .types import (
    AnalysisPlanStatus,
    ContractStatus,
    DesignPlanStatus,
    DesignType,
    DisseminationStatus,
    DisseminationType,
    IRBProtocolStatus,
    ParticipantStatus,
    RecordStatus,
    ReportStatus,
    ReportType,
    RestrictedUseFileStatus,
    SampleAdequacy,
    SiteStatus,
    StudyStatus,
    WaveStatus,
    WaveType,
    WithdrawalReason,
)

__all__ = [
    "validate_success",
    "assert_contract",
    "assert_study",
    "assert_design_plan",
    "assert_irb_protocol",
    "assert_site",
    "assert_participant",
    "assert_wave",
    "assert_record",
    "assert_analysis_plan",
    "assert_report",
    "assert_restricted_use_file",
    "assert_dissemination_activity",
    "assert_contract_funds_invariant",
    "assert_enrollment_reconciliation",
    "assert_burden_within_cap",
    "assert_risk_scores_consistent",
]


def validate_success(response, expected_status):
    """Explicit-status success validator. Pass 201 for creates, 200 otherwise."""
    return _fw_validate_success(response, expected_status)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1


def _enum_values(enum_cls) -> List[str]:
    return [m.value for m in enum_cls]


def assert_contract(data: dict):
    _assert_common(data)
    assert isinstance(data["agency_code"], str) and data["agency_code"]
    assert isinstance(data["title"], str)
    assert isinstance(data["award_amount_cents"], int) and data["award_amount_cents"] > 0
    assert isinstance(data["deliverable_report_count"], int) and data["deliverable_report_count"] >= 1
    assert isinstance(data["disbursed_cents"], int)
    assert isinstance(data["forfeited_cents"], int)
    assert isinstance(data["remaining_cents"], int)
    assert data["status"] in _enum_values(ContractStatus)
    assert data["terminated_reason"] is None or isinstance(data["terminated_reason"], str)


def assert_study(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("contract_id", ""))
    assert isinstance(data["title"], str)
    assert isinstance(data["research_question"], str)
    assert data["status"] in _enum_values(StudyStatus)
    for counter in ("committed_projected_n", "pipeline_projected_n",
                    "enrolled_total", "quarantined_record_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0
    assert data["sample_adequacy"] in _enum_values(SampleAdequacy)


def assert_design_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("study_id", ""))
    assert data["design_type"] in _enum_values(DesignType)
    assert data["mde"] > 0
    assert isinstance(data["cluster_size"], int) and data["cluster_size"] >= 1
    assert 0 <= data["icc"] <= 1
    assert 0 <= data["attrition_rate"] < 1
    assert isinstance(data["n_per_arm"], int) and data["n_per_arm"] >= 1
    assert data["required_total_n"] == 2 * data["n_per_arm"]
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert data["status"] in _enum_values(DesignPlanStatus)


def assert_irb_protocol(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("study_id", ""))
    assert isinstance(data["title"], str)
    assert isinstance(data["estimated_burden_minutes"], int) and data["estimated_burden_minutes"] >= 0
    assert data["status"] in _enum_values(IRBProtocolStatus)
    assert data["approval_start"] is None or is_iso8601_timestamp(data["approval_start"])
    assert data["approval_end"] is None or is_iso8601_timestamp(data["approval_end"])
    assert isinstance(data["consent_form_version"], int) and data["consent_form_version"] >= 1


def assert_site(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("study_id", ""))
    assert isinstance(data["name"], str)
    assert isinstance(data["max_participants"], int) and data["max_participants"] >= 1
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert isinstance(data["randomized_count"], int) and data["randomized_count"] >= 0
    assert data["status"] in _enum_values(SiteStatus)


def assert_participant(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("site_id", ""))
    assert isinstance(data["external_ref"], str)
    assert data["status"] in _enum_values(ParticipantStatus)
    assert data["consent_form_version"] is None or isinstance(data["consent_form_version"], int)
    assert data["consented_at"] is None or is_iso8601_timestamp(data["consented_at"])
    assert isinstance(data["burden_total_minutes"], int) and data["burden_total_minutes"] >= 0
    assert data["withdrawal_reason"] is None or data["withdrawal_reason"] in _enum_values(WithdrawalReason)


def assert_wave(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("study_id", ""))
    assert data["wave_type"] in _enum_values(WaveType)
    assert data["site_id"] is None or is_valid_uuid(data["site_id"])
    assert is_iso8601_timestamp(data.get("open_at", ""))
    assert is_iso8601_timestamp(data.get("close_at", ""))
    assert data["status"] in _enum_values(WaveStatus)


def assert_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("wave_id", ""))
    assert is_valid_uuid(data.get("participant_id", ""))
    assert isinstance(data["instrument_minutes"], int) and data["instrument_minutes"] >= 1
    assert isinstance(data["payload_ref"], str)
    assert isinstance(data["billed_minutes"], int) and data["billed_minutes"] >= 1
    assert data["linkage_key"] is None or isinstance(data["linkage_key"], str)
    assert data["status"] in _enum_values(RecordStatus)


def assert_analysis_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("study_id", ""))
    assert isinstance(data["primary_outcomes"], list) and len(data["primary_outcomes"]) > 0
    assert isinstance(data["secondary_outcomes"], list)
    assert isinstance(data["amendment_count"], int) and data["amendment_count"] >= 0
    assert data["registered_at"] is None or is_iso8601_timestamp(data["registered_at"])
    assert data["status"] in _enum_values(AnalysisPlanStatus)


def assert_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("study_id", ""))
    assert isinstance(data["title"], str)
    assert data["report_type"] in _enum_values(ReportType)
    assert isinstance(data["addressed_primary_outcomes"], list)
    assert isinstance(data["payment_milestone_cents"], int) and data["payment_milestone_cents"] >= 0
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    for ts_field in ("submitted_at", "accepted_at", "peer_review_due",
                     "revision_due", "publication_due"):
        assert data[ts_field] is None or is_iso8601_timestamp(data[ts_field])
    assert data["status"] in _enum_values(ReportStatus)


def assert_restricted_use_file(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("study_id", ""))
    assert isinstance(data["title"], str)
    assert isinstance(data["cell_counts"], list) and len(data["cell_counts"]) > 0
    assert all(isinstance(c, int) and c >= 1 for c in data["cell_counts"])
    assert isinstance(data["sensitivity_weights"], list)
    assert len(data["sensitivity_weights"]) == len(data["cell_counts"])
    assert all(0 < w <= 1 for w in data["sensitivity_weights"])
    assert data["status"] in _enum_values(RestrictedUseFileStatus)


def assert_dissemination_activity(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("study_id", ""))
    assert data["activity_type"] in _enum_values(DisseminationType)
    assert isinstance(data["title"], str)
    assert is_iso8601_timestamp(data.get("scheduled_at", ""))
    assert isinstance(data["operator_count"], int) and data["operator_count"] >= 1
    assert data["status"] in _enum_values(DisseminationStatus)


def assert_contract_funds_invariant(data: dict):
    """Ledger invariant: disbursed + forfeited + remaining == award, always."""
    assert data["disbursed_cents"] + data["forfeited_cents"] + data["remaining_cents"] \
        == data["award_amount_cents"], (
        f"Ledger invariant broken: {data['disbursed_cents']} + {data['forfeited_cents']} "
        f"+ {data['remaining_cents']} != {data['award_amount_cents']}"
    )
    assert data["disbursed_cents"] >= 0
    assert data["forfeited_cents"] >= 0
    assert data["remaining_cents"] >= 0


def assert_enrollment_reconciliation(study: dict, sites: List[dict]):
    """Sum of site enrolled_count equals the study's enrolled_total."""
    total = sum(s["enrolled_count"] for s in sites)
    assert total == study["enrolled_total"], (
        f"Enrollment reconciliation broken: sum of site enrolled_count {total} "
        f"!= study enrolled_total {study['enrolled_total']}"
    )


def assert_burden_within_cap(participant: dict, cap: int):
    assert participant["burden_total_minutes"] <= cap, (
        f"burden_total_minutes {participant['burden_total_minutes']} exceeds cap {cap}"
    )


def assert_risk_scores_consistent(data: dict):
    """Risk scores, once computed, sit in [0, 1] with mean <= max."""
    if data.get("max_risk") is None:
        return
    assert 0 <= data["max_risk"] <= 1
    assert 0 <= data["mean_risk"] <= 1
    assert data["mean_risk"] <= data["max_risk"] + 1e-9
    assert isinstance(data["suppressed_cell_count"], int) and data["suppressed_cell_count"] >= 0
