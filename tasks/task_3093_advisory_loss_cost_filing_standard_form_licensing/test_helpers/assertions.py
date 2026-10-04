"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

PRIMARY_STATUSES = {
    "insurer": ["ACTIVE", "SUSPENDED", "WITHDRAWN"],
    "plan": ["DRAFT", "ACTIVE", "RETIRED"],
    "submission": ["RECEIVED", "EDITING", "ACCEPTED", "ACCEPTED_WITH_WARNINGS", "REJECTED"],
    "filing": ["DRAFT", "IN_ACTUARIAL_REVIEW", "REVIEWED", "FILED", "OBJECTED", "EFFECTIVE", "WITHDRAWN"],
    "adoption": ["PENDING", "AUTHORIZED", "REJECTED_BAND", "WITHDRAWN"],
    "form": ["DRAFTING", "IN_REVIEW", "APPROVED", "PUBLISHED", "WITHDRAWN"],
    "variant_review": ["PENDING", "CLEARED", "BLOCKED"],
    "variant_publication": ["UNPUBLISHED", "SCHEDULED", "LIVE", "RETIRED"],
    "circular": ["DRAFT", "PUBLISHED", "SUPERSEDED"],
    "agreement": ["ACTIVE", "LAPSED", "TERMINATED"],
    "class_plan": ["OPEN", "LOCKED"],
    "revision": ["STAGED", "ACTIVATED", "SUPERSEDED"],
}


def _assert_primary_common(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, f"{label}.version must be an int >= 1"


def _assert_leaf_common(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"


def assert_insurer(data: dict):
    _assert_primary_common(data, "MemberInsurer")
    assert isinstance(data.get("insurer_code"), str) and data["insurer_code"]
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert data.get("insurer_status") in PRIMARY_STATUSES["insurer"]
    score = data.get("quality_score_bps")
    assert isinstance(score, int) and 0 <= score <= 10000, "quality_score_bps must be 0..10000"


def assert_statistical_plan(data: dict):
    _assert_primary_common(data, "StatisticalPlan")
    assert isinstance(data.get("plan_code"), str) and data["plan_code"]
    assert isinstance(data.get("line_of_business"), str) and data["line_of_business"]
    assert isinstance(data.get("min_premium_cents"), int)
    assert isinstance(data.get("max_record_age_months"), int)
    assert data.get("plan_status") in PRIMARY_STATUSES["plan"]


def assert_submission(data: dict):
    _assert_primary_common(data, "StatisticalSubmission")
    assert isinstance(data.get("insurer_id"), str) and data["insurer_id"]
    assert isinstance(data.get("plan_id"), str) and data["plan_id"]
    assert isinstance(data.get("period_start"), str)
    assert isinstance(data.get("period_end"), str)
    assert isinstance(data.get("record_count"), int) and data["record_count"] >= 1
    assert isinstance(data.get("written_premium_cents"), int) and data["written_premium_cents"] >= 0
    assert data.get("submission_status") in PRIMARY_STATUSES["submission"]


def assert_finding(data: dict):
    _assert_leaf_common(data, "SubmissionEditFinding")
    assert isinstance(data.get("submission_id"), str)
    assert isinstance(data.get("edit_code"), str) and data["edit_code"]
    assert data.get("severity") in ["ERROR", "WARNING"]
    assert isinstance(data.get("affected_records"), int) and data["affected_records"] >= 1


def assert_filing(data: dict):
    _assert_primary_common(data, "LossCostFiling")
    assert isinstance(data.get("filing_code"), str) and data["filing_code"]
    assert isinstance(data.get("state_code"), str) and len(data["state_code"]) == 2
    assert isinstance(data.get("line_of_business"), str) and data["line_of_business"]
    assert isinstance(data.get("filing_version"), int) and data["filing_version"] >= 1
    assert data.get("trend_selection") in ["EXPONENTIAL_LEAST_SQUARES", "LINEAR_LEAST_SQUARES"]
    assert data.get("filing_status") in PRIMARY_STATUSES["filing"]


def assert_cell(data: dict):
    _assert_leaf_common(data, "LossCostCell")
    assert isinstance(data.get("filing_id"), str)
    assert isinstance(data.get("class_code"), str) and data["class_code"]
    assert isinstance(data.get("earned_premium_cents"), int) and data["earned_premium_cents"] > 0
    assert isinstance(data.get("incurred_loss_cents"), int) and data["incurred_loss_cents"] >= 0
    assert isinstance(data.get("weight_pct"), int) and 1 <= data["weight_pct"] <= 100
    assert isinstance(data.get("current_loss_cost_cents"), int) and data["current_loss_cost_cents"] > 0


def assert_department(data: dict):
    _assert_primary_common(data, "StateDepartment")
    assert isinstance(data.get("state_code"), str) and len(data["state_code"]) == 2
    assert isinstance(data.get("department_name"), str) and data["department_name"]
    assert isinstance(data.get("objection_window_days"), int) and data["objection_window_days"] > 0
    assert isinstance(data.get("max_lcm_deviation_pct"), int) and data["max_lcm_deviation_pct"] >= 0


def assert_objection(data: dict):
    _assert_leaf_common(data, "RegulatoryObjection")
    assert isinstance(data.get("filing_id"), str)
    assert isinstance(data.get("department_id"), str)
    assert isinstance(data.get("objection_code"), str) and data["objection_code"]
    assert isinstance(data.get("objection_text"), str)
    assert isinstance(data.get("raised_at"), str) and data["raised_at"]


def assert_adoption(data: dict):
    _assert_primary_common(data, "LossCostMultiplierAdoption")
    assert isinstance(data.get("insurer_id"), str)
    assert isinstance(data.get("filing_id"), str)
    assert isinstance(data.get("multiplier_pct"), int) and data["multiplier_pct"] >= 1
    assert data.get("adoption_status") in PRIMARY_STATUSES["adoption"]


def assert_form(data: dict):
    _assert_primary_common(data, "PolicyForm")
    assert isinstance(data.get("form_number"), str) and data["form_number"]
    assert isinstance(data.get("form_title"), str) and data["form_title"]
    assert data.get("form_kind") in ["POLICY_FORM", "ENDORSEMENT"]
    assert data.get("form_status") in PRIMARY_STATUSES["form"]


def assert_variant(data: dict):
    _assert_primary_common(data, "FormVariant")
    assert isinstance(data.get("form_id"), str)
    assert isinstance(data.get("state_code"), str) and data["state_code"]
    assert isinstance(data.get("variant_text_ref"), str)
    assert data.get("review_status") in PRIMARY_STATUSES["variant_review"]
    assert data.get("publication_status") in PRIMARY_STATUSES["variant_publication"]
    assert isinstance(data.get("effective_from"), str)


def assert_circular(data: dict):
    _assert_primary_common(data, "Circular")
    assert isinstance(data.get("circular_number"), str) and data["circular_number"]
    assert isinstance(data.get("subject"), str)
    assert isinstance(data.get("implementation_date"), str)
    assert data.get("circular_status") in PRIMARY_STATUSES["circular"]


def assert_agreement(data: dict):
    _assert_primary_common(data, "LicenseAgreement")
    assert isinstance(data.get("insurer_id"), str)
    assert isinstance(data.get("coverage_start"), str)
    assert isinstance(data.get("coverage_end"), str)
    assert isinstance(data.get("royalty_rate_bps"), int) and 0 <= data["royalty_rate_bps"] <= 5000
    assert data.get("agreement_status") in PRIMARY_STATUSES["agreement"]


def assert_class_plan(data: dict):
    _assert_primary_common(data, "ClassPlan")
    assert isinstance(data.get("class_plan_code"), str) and data["class_plan_code"]
    assert isinstance(data.get("line_of_business"), str) and data["line_of_business"]
    assert data.get("plan_status") in PRIMARY_STATUSES["class_plan"]


def assert_revision(data: dict):
    _assert_primary_common(data, "ClassPlanRevision")
    assert isinstance(data.get("class_plan_id"), str)
    assert isinstance(data.get("revision_number"), int) and data["revision_number"] >= 1
    assert isinstance(data.get("class_count"), int) and data["class_count"] >= 1
    assert data.get("revision_status") in PRIMARY_STATUSES["revision"]
    assert isinstance(data.get("activates_at"), str)


def assert_quality_score_invariants(data: dict):
    """Insurer quality score invariants after any disposition (PRD §3.1-§3.2)."""
    score = data.get("quality_score_bps")
    assert isinstance(score, int), "quality_score_bps must be an integer number of basis points"
    assert 0 <= score <= 10000, f"quality_score_bps must be clamped to [0, 10000], got {score}"
