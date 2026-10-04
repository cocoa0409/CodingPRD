"""Entity assertions and domain invariant checkers.

Each assert_<entity>() checks the fields PRD declares for that resource:
system-managed common fields (uuid id, ISO-8601 created_at/updated_at,
integer version) plus the entity's own declared fields and enum memberships.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    ActivityCode, CareerStage, FoaStatus, ApplicationStatus, StudySectionStatus,
    ReviewerStatus, AssignmentRole, AssignmentStatus, CouncilRecommendation,
    JitStatus, AwardStatus, ProgressReportStatus, AwardModificationType,
    AwardModificationStatus, TransferStatus, ProrationVariant,
)


def _assert_common(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_funding_opportunity(data: dict):
    _assert_common(data, "FundingOpportunity")
    assert isinstance(data["pa_number"], str) and data["pa_number"]
    assert isinstance(data["title"], str) and data["title"]
    assert data["activity_code"] in {c.value for c in ActivityCode}
    assert isinstance(data["research_strategy_page_limit"], int) and data["research_strategy_page_limit"] >= 1
    assert isinstance(data["min_direct_cents_per_year"], int) and data["min_direct_cents_per_year"] >= 0
    assert isinstance(data["max_direct_cents_per_year"], int)
    assert data["max_direct_cents_per_year"] >= data["min_direct_cents_per_year"]
    assert isinstance(data["max_years"], int) and 1 <= data["max_years"] <= 5
    assert isinstance(data["open_date"], str) and data["open_date"]
    assert isinstance(data["receipt_deadline"], str) and data["receipt_deadline"]
    assert data["status"] in {s.value for s in FoaStatus}


def assert_institute(data: dict):
    _assert_common(data, "Institute")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["appropriation_cents"], int) and data["appropriation_cents"] >= 0
    assert isinstance(data["reserve_cents"], int) and data["reserve_cents"] >= 0
    assert isinstance(data["indirect_cost_rate"], (int, float))
    assert 0 <= data["indirect_cost_rate"] <= 1
    assert isinstance(data["select_pay_cap_pct"], (int, float))
    assert 0 <= data["select_pay_cap_pct"] <= 1
    assert isinstance(data["select_pay_extension_percentile"], (int, float))
    assert data["select_pay_extension_percentile"] >= 0
    assert isinstance(data["committed_cents"], int) and data["committed_cents"] >= 0
    assert isinstance(data["disbursed_cents"], int) and data["disbursed_cents"] >= 0
    assert isinstance(data["select_pay_spent_cents"], int) and data["select_pay_spent_cents"] >= 0
    assert data.get("current_payline_percentile") is None or isinstance(
        data["current_payline_percentile"], (int, float)
    )


def assert_institution(data: dict):
    _assert_common(data, "Institution")
    assert isinstance(data["name"], str) and data["name"]
    assert "human_subjects_certification_expiry" in data
    assert "animal_welfare_assurance_expiry" in data


def assert_applicant(data: dict):
    _assert_common(data, "Applicant")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["career_stage"] in {c.value for c in CareerStage}


def assert_application(data: dict):
    _assert_common(data, "Application")
    assert is_valid_uuid(data.get("foa_id", "")), "Application.foa_id must be a UUID"
    assert is_valid_uuid(data.get("applicant_id", "")), "Application.applicant_id must be a UUID"
    assert is_valid_uuid(data.get("institution_id", "")), "Application.institution_id must be a UUID"
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["research_strategy_page_count"], int) and data["research_strategy_page_count"] >= 1
    assert isinstance(data["direct_cents_per_year"], list)
    assert all(isinstance(c, int) and c >= 0 for c in data["direct_cents_per_year"])
    assert isinstance(data["requested_years"], int) and 1 <= data["requested_years"] <= 5
    assert len(data["direct_cents_per_year"]) == data["requested_years"]
    assert isinstance(data["human_subjects_involved"], bool)
    assert isinstance(data["vertebrate_animals_involved"], bool)
    assert isinstance(data["excluded_reviewer_ids"], list)
    assert data.get("requested_study_section_id") is None or isinstance(data["requested_study_section_id"], str)
    assert data.get("requested_institute_id") is None or isinstance(data["requested_institute_id"], str)
    assert data.get("study_section_id") is None or isinstance(data["study_section_id"], str)
    assert data.get("institute_id") is None or isinstance(data["institute_id"], str)
    assert isinstance(data["live_assignment_count"], int) and data["live_assignment_count"] >= 0
    assert data.get("impact_score") is None or isinstance(data["impact_score"], int)
    for mean_field in ("approach_mean", "significance_mean", "innovation_mean"):
        assert data.get(mean_field) is None or isinstance(data[mean_field], (int, float))
    assert data.get("percentile_raw") is None or isinstance(data["percentile_raw"], (int, float))
    assert data.get("percentile_normalized") is None or isinstance(data["percentile_normalized"], (int, float))
    assert data["status"] in {s.value for s in ApplicationStatus}


def assert_study_section(data: dict):
    _assert_common(data, "StudySection")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["meeting_date"], str) and data["meeting_date"]
    assert isinstance(data["application_quota"], int) and data["application_quota"] >= 1
    assert isinstance(data["assigned_application_count"], int) and data["assigned_application_count"] >= 0
    assert data["status"] in {s.value for s in StudySectionStatus}


def assert_reviewer(data: dict):
    _assert_common(data, "Reviewer")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert is_valid_uuid(data.get("institution_id", "")), "Reviewer.institution_id must be a UUID"
    assert isinstance(data["expertise_keywords"], list)
    assert isinstance(data["declared_conflicts"], list)
    assert isinstance(data["active_assignment_count"], int) and data["active_assignment_count"] >= 0
    assert data["status"] in {s.value for s in ReviewerStatus}


def assert_assignment(data: dict):
    _assert_common(data, "Assignment")
    assert is_valid_uuid(data.get("application_id", "")), "Assignment.application_id must be a UUID"
    assert is_valid_uuid(data.get("reviewer_id", "")), "Assignment.reviewer_id must be a UUID"
    assert data["role"] in {r.value for r in AssignmentRole}
    for score_field in (
        "significance_score", "innovation_score", "approach_score",
        "investigator_score", "environment_score", "overall_impact_score",
    ):
        value = data.get(score_field)
        assert value is None or (isinstance(value, int) and 1 <= value <= 9), (
            f"Assignment.{score_field} must be null or an integer 1..9, got {value!r}"
        )
    assert data["status"] in {s.value for s in AssignmentStatus}


def assert_council_review(data: dict):
    _assert_common(data, "CouncilReview")
    assert is_valid_uuid(data.get("application_id", "")), "CouncilReview.application_id must be a UUID"
    assert data["recommendation"] in {r.value for r in CouncilRecommendation}
    assert data.get("priority_alignment_score") is None or (
        isinstance(data["priority_alignment_score"], int)
        and 1 <= data["priority_alignment_score"] <= 5
    )
    assert isinstance(data.get("recorded_by"), str) and data["recorded_by"]


def assert_jit_request(data: dict):
    _assert_common(data, "JitRequest")
    assert is_valid_uuid(data.get("application_id", "")), "JitRequest.application_id must be a UUID"
    assert isinstance(data["required_items"], list) and len(data["required_items"]) >= 2
    assert isinstance(data["submitted_items"], list)
    assert isinstance(data["due_date"], str) and data["due_date"]
    assert isinstance(data["budget_cut_pct"], (int, float))
    assert 0 <= data["budget_cut_pct"] <= 0.30
    assert data["status"] in {s.value for s in JitStatus}


def assert_award(data: dict):
    _assert_common(data, "Award")
    assert is_valid_uuid(data.get("application_id", "")), "Award.application_id must be a UUID"
    assert is_valid_uuid(data.get("institute_id", "")), "Award.institute_id must be a UUID"
    assert is_valid_uuid(data.get("institution_id", "")), "Award.institution_id must be a UUID"
    assert isinstance(data["start_date"], str) and data["start_date"]
    assert isinstance(data["end_date"], str) and data["end_date"]
    assert isinstance(data["period_total_cents"], list) and len(data["period_total_cents"]) >= 1
    assert all(isinstance(c, int) and c >= 0 for c in data["period_total_cents"])
    assert isinstance(data["total_awarded_cents"], int) and data["total_awarded_cents"] >= 0
    assert isinstance(data["disbursed_cents"], int) and data["disbursed_cents"] >= 0
    assert isinstance(data["disbursed_per_period_cents"], list)
    assert len(data["disbursed_per_period_cents"]) == len(data["period_total_cents"])
    assert isinstance(data["carried_out_per_period_cents"], list)
    assert len(data["carried_out_per_period_cents"]) == len(data["period_total_cents"])
    assert isinstance(data["current_period"], int) and data["current_period"] >= 1
    assert isinstance(data["terms_and_conditions"], list) and "STANDARD_TERMS_V1" in data["terms_and_conditions"]
    assert data.get("originating_transfer_id") is None or isinstance(data["originating_transfer_id"], str)
    assert data["status"] in {s.value for s in AwardStatus}


def assert_progress_report(data: dict):
    _assert_common(data, "ProgressReport")
    assert is_valid_uuid(data.get("award_id", "")), "ProgressReport.award_id must be a UUID"
    assert isinstance(data["period_year"], int) and data["period_year"] >= 1
    assert isinstance(data["actual_expenditure_cents"], int) and data["actual_expenditure_cents"] >= 0
    assert isinstance(data["publications_count"], int) and data["publications_count"] >= 0
    assert isinstance(data["submitted_late"], bool)
    assert data["status"] in {s.value for s in ProgressReportStatus}


def assert_award_modification(data: dict):
    _assert_common(data, "AwardModification")
    assert is_valid_uuid(data.get("award_id", "")), "AwardModification.award_id must be a UUID"
    assert data["type"] in {t.value for t in AwardModificationType}
    assert isinstance(data["auto_approved"], bool)
    assert data["status"] in {s.value for s in AwardModificationStatus}


def assert_transfer_request(data: dict):
    _assert_common(data, "TransferRequest")
    assert is_valid_uuid(data.get("award_id", "")), "TransferRequest.award_id must be a UUID"
    assert is_valid_uuid(data.get("to_institution_id", "")), "TransferRequest.to_institution_id must be a UUID"
    assert isinstance(data["effective_date"], str) and data["effective_date"]
    assert data.get("proration_variant") is None or data["proration_variant"] in {
        v.value for v in ProrationVariant
    }
    assert data.get("relinquished_amount_cents") is None or (
        isinstance(data["relinquished_amount_cents"], int)
        and data["relinquished_amount_cents"] >= 0
    )
    assert data["status"] in {s.value for s in TransferStatus}


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_institute_ledger_invariants(institute: dict):
    """The institute ledger must never over-commit its committable authority.

    PRD: "The commitment authority available to any funding decision is the
    appropriation reduced by outstanding commitments, cumulative
    disbursements, and the reserve."
    """
    appropriation = institute["appropriation_cents"]
    committed = institute["committed_cents"]
    disbursed = institute["disbursed_cents"]
    reserve = institute["reserve_cents"]
    assert committed >= 0, f"committed_cents negative: {committed}"
    assert disbursed >= 0, f"disbursed_cents negative: {disbursed}"
    assert committed + disbursed + reserve <= appropriation, (
        f"ledger over-committed: committed {committed} + disbursed {disbursed} "
        f"+ reserve {reserve} > appropriation {appropriation}"
    )


def assert_award_budget_conserved(award: dict):
    """PRD: the carryover effects keep "the award's total budget ... conserved":
    total_awarded_cents always equals the sum of the live period totals."""
    assert sum(award["period_total_cents"]) == award["total_awarded_cents"], (
        f"period_total_cents {award['period_total_cents']} does not sum to "
        f"total_awarded_cents {award['total_awarded_cents']}"
    )


def assert_transfer_conservation(original_award: dict, successor_award: dict, relinquished_cents: int):
    """PRD: "the retained amount is whatever neither moved nor was spent — the
    total minus the disbursed minus the relinquished — and the three parts
    always re-sum to the award's total_awarded_cents."""
    total = original_award["total_awarded_cents"]
    disbursed = original_award["disbursed_cents"]
    retained = total - disbursed - relinquished_cents
    assert retained >= 0, f"retained portion negative: {retained}"
    assert disbursed + retained + relinquished_cents == total
    assert successor_award["total_awarded_cents"] == relinquished_cents
