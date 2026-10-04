"""Entity assertions and domain invariant checkers.

``assert_<entity>(data)`` checks the structural contract of one resource:
field presence, primitive types, enum membership, and the common-fields
rules of PRD §2.5 (every primary resource carries id / created_at /
updated_at / version; the review finding carries only id and created_at and
MUST NOT carry updated_at or version).

Value-level expectations (an exact score, an exact grant) belong in tests,
not here — these helpers only pin shape and cross-field invariants.
"""

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import REVIEWER_ALIAS_PREFIX, SCORE_DECIMAL_PLACES
from .types import (
    AllocationPolicy,
    ApplicationPurpose,
    ApplicationStatus,
    AssignmentStatus,
    BudgetDocType,
    ChecklistStatus,
    CommentResolution,
    CommentSeverity,
    CyclePosture,
    FundStatus,
    GovType,
    PopulationBand,
    ProgramLabel,
    ProgramType,
    PublicationStatus,
    ReviewerStatus,
    SubmissionStatus,
)

__all__ = [
    "assert_common_fields",
    "assert_optional_timestamp",
    "assert_score_precision",
    "assert_government",
    "assert_member",
    "assert_reviewer_profile",
    "assert_checklist_version",
    "assert_standards_reference",
    "assert_award_cycle",
    "assert_report_submission",
    "assert_review_assignment",
    "assert_review_finding",
    "assert_publication",
    "assert_member_comment",
    "assert_scholarship_fund",
    "assert_scholarship_application",
    "assert_reviewer_alias",
    "assert_fund_money_invariant",
    "assert_reviewer_count_invariant",
]


def _enum_values(enum_cls):
    return [member.value for member in enum_cls]


def assert_common_fields(data):
    """PRD §2.5: id / created_at / updated_at / version on primary resources."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_optional_timestamp(data, field):
    value = data.get(field)
    assert field in data, "field {0} must be present (null until set)".format(field)
    if value is not None:
        assert is_iso8601_timestamp(value), (
            "{0} must be an ISO 8601 UTC timestamp when set".format(field)
        )


def assert_score_precision(value):
    """All review scores are carried to exactly 2 decimal places (PRD §2.9)."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        "score must be numeric, got {0!r}".format(value)
    )
    assert_cost_precision(value, SCORE_DECIMAL_PLACES)


def _assert_int(data, field, minimum=None):
    assert isinstance(data.get(field), int) and not isinstance(data.get(field), bool), (
        "{0} must be an integer".format(field)
    )
    if minimum is not None:
        assert data[field] >= minimum, "{0} must be >= {1}".format(field, minimum)


def _assert_bool(data, field):
    assert isinstance(data.get(field), bool), "{0} must be a boolean".format(field)


def _assert_enum(data, field, enum_cls):
    assert data.get(field) in _enum_values(enum_cls), (
        "{0} must be one of {1}, got {2!r}".format(
            field, _enum_values(enum_cls), data.get(field)
        )
    )


# ─── Per-entity structural assertions ───────────────────────────────────────


def assert_government(data):
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    _assert_enum(data, "gov_type", GovType)
    _assert_enum(data, "population_band", PopulationBand)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    _assert_int(data, "lifetime_award_count", 0)


def assert_member(data):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    _assert_enum(data, "government_size_band", PopulationBand)
    _assert_bool(data, "independent_finance_officer")
    _assert_int(data, "annual_dues_cents", 0)


def assert_reviewer_profile(data):
    assert_common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["employer_government_id"])
    assert isinstance(data["conflicted_government_ids"], list)
    assert isinstance(data["unavailability_windows"], list)
    for window in data["unavailability_windows"]:
        assert set(window.keys()) >= {"start_date", "end_date"}
    _assert_bool(data, "independence_attested")
    _assert_enum(data, "status", ReviewerStatus)
    assert_optional_timestamp(data, "trained_at")
    _assert_int(data, "open_assignment_count", 0)
    _assert_int(data, "completed_review_count", 0)
    _assert_int(data, "declined_assignment_count", 0)


def assert_checklist_version(data):
    assert_common_fields(data)
    _assert_enum(data, "program_type", ProgramType)
    assert isinstance(data["version_label"], str) and data["version_label"]
    assert_score_precision(data["pass_score"])
    assert isinstance(data["criteria"], list) and data["criteria"]
    for entry in data["criteria"]:
        assert isinstance(entry["criterion_code"], str) and entry["criterion_code"]
        assert isinstance(entry["weight"], (int, float))
    _assert_enum(data, "status", ChecklistStatus)


def assert_standards_reference(data):
    assert_common_fields(data)
    assert isinstance(data["topic_code"], str) and data["topic_code"]
    assert isinstance(data["title"], str) and data["title"]
    _assert_enum(data, "program_type", ProgramType)
    assert is_iso8601_timestamp(data["effective_date"])
    _assert_enum(data, "status", StandardStatus)


def assert_award_cycle(data):
    assert_common_fields(data)
    _assert_enum(data, "program_type", ProgramType)
    _assert_int(data, "fiscal_year")
    for field in ("submission_opens_at", "submission_deadline_at", "review_close_at"):
        assert is_iso8601_timestamp(data[field]), "{0} must be ISO 8601".format(field)
    assert is_valid_uuid(data["checklist_version_id"])
    _assert_enum(data, "posture", CyclePosture)
    _assert_int(data, "submitted_count", 0)
    _assert_int(data, "decision_ready_count", 0)
    _assert_int(data, "conferred_count", 0)


def assert_report_submission(data):
    assert_common_fields(data)
    assert is_valid_uuid(data["government_id"])
    assert is_valid_uuid(data["cycle_id"])
    assert isinstance(data["budget_documents"], list)
    for doc in data["budget_documents"]:
        assert doc["doc_type"] in _enum_values(BudgetDocType)
        assert isinstance(doc["title"], str)
        assert isinstance(doc["page_count"], int) and doc["page_count"] > 0
    _assert_enum(data, "program_type", ProgramType)
    assert is_valid_uuid(data["pinned_checklist_version_id"])
    _assert_bool(data, "pinned_checklist_stale")
    _assert_int(data, "appeal_round", 1)
    _assert_enum(data, "status", SubmissionStatus)
    assert "provisional_score" in data
    if data["provisional_score"] is not None:
        assert_score_precision(data["provisional_score"])
    assert "final_score" in data
    if data["final_score"] is not None:
        assert_score_precision(data["final_score"])
    _assert_int(data, "major_deficiency_total", 0)
    assert isinstance(data["required_improvements"], list)
    _assert_bool(data, "award_conferred")
    assert_optional_timestamp(data, "submitted_at")
    assert_optional_timestamp(data, "decided_at")
    assert_optional_timestamp(data, "conferred_at")


def assert_review_assignment(data, expect_masked=None):
    """``expect_masked=True`` asserts the GovernmentContact blind-review view
    (reviewer_id null, alias present); ``False`` asserts the privileged view
    (reviewer_id is the reviewer's UUID)."""
    assert_common_fields(data)
    assert is_valid_uuid(data["submission_id"])
    assert "reviewer_id" in data, "reviewer_id key must be present even when masked"
    if expect_masked is True:
        assert data["reviewer_id"] is None, (
            "reviewer_id must be masked to null for GovernmentContact readers"
        )
    elif expect_masked is False:
        assert is_valid_uuid(data["reviewer_id"]), (
            "reviewer_id must be the reviewer profile UUID for privileged readers"
        )
    else:
        assert data["reviewer_id"] is None or is_valid_uuid(data["reviewer_id"])
    assert isinstance(data["reviewer_alias"], str) and data["reviewer_alias"].startswith(
        REVIEWER_ALIAS_PREFIX
    )
    _assert_int(data, "appeal_round", 1)
    _assert_enum(data, "status", AssignmentStatus)


def assert_review_finding(data):
    """Immutable record: only id + created_at from the common set (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, "findings are immutable: updated_at absent"
    assert "version" not in data, "findings are immutable: version absent"
    assert is_valid_uuid(data["assignment_id"])
    _assert_int(data, "appeal_round", 1)
    assert isinstance(data["criterion_scores"], list) and data["criterion_scores"]
    for entry in data["criterion_scores"]:
        assert isinstance(entry["criterion_code"], str) and entry["criterion_code"]
        assert_score_precision(entry["score"])
        assert 0 <= entry["score"] <= 100
    assert isinstance(data["comments"], list)
    for comment in data["comments"]:
        assert isinstance(comment["criterion_code"], str)
        assert comment["severity"] in _enum_values(CommentSeverity)
        assert isinstance(comment["text"], str)
    assert_score_precision(data["weighted_score"])
    _assert_int(data, "major_deficiency_count", 0)


def assert_publication(data):
    assert_common_fields(data)
    assert isinstance(data["committee_name"], str) and data["committee_name"]
    assert is_valid_uuid(data["chair_member_id"])
    assert isinstance(data["member_ids"], list) and data["member_ids"]
    assert data["chair_member_id"] in data["member_ids"], (
        "chair_member_id must be an element of member_ids"
    )
    assert is_valid_uuid(data["created_by_member_id"])
    assert data["created_by_member_id"] in data["member_ids"], (
        "creator must be an element of member_ids"
    )
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["topic_code"], str) and data["topic_code"]
    assert "pinned_standards_reference_id" in data
    if data["pinned_standards_reference_id"] is not None:
        assert is_valid_uuid(data["pinned_standards_reference_id"])
    assert_optional_timestamp(data, "comment_window_opens_at")
    assert_optional_timestamp(data, "comment_window_closes_at")
    _assert_int(data, "draft_number", 1)
    _assert_int(data, "pending_comment_count", 0)
    _assert_int(data, "resolved_comment_count", 0)
    _assert_enum(data, "status", PublicationStatus)
    assert_optional_timestamp(data, "published_at")


def assert_member_comment(data):
    assert_common_fields(data)
    assert is_valid_uuid(data["publication_id"])
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["body"], str) and data["body"]
    _assert_enum(data, "resolution", CommentResolution)
    assert "resolution_note" in data


def assert_scholarship_fund(data):
    assert_common_fields(data)
    _assert_int(data, "fiscal_year")
    _assert_enum(data, "program_label", ProgramLabel)
    _assert_int(data, "pool_total_cents", 1)
    _assert_int(data, "per_applicant_cap_cents", 1)
    _assert_enum(data, "allocation_policy", AllocationPolicy)
    _assert_int(data, "remaining_cents", 0)
    _assert_enum(data, "status", FundStatus)
    # Derived status (PRD §3.9): EXHAUSTED exactly when remaining hits zero.
    if data["remaining_cents"] == 0:
        assert data["status"] == FundStatus.EXHAUSTED.value, (
            "fund with remaining_cents == 0 must read EXHAUSTED"
        )
    else:
        assert data["status"] == FundStatus.ALLOCATING.value, (
            "fund with remaining_cents > 0 must read ALLOCATING"
        )


def assert_scholarship_application(data):
    assert_common_fields(data)
    assert is_valid_uuid(data["fund_id"])
    assert is_valid_uuid(data["government_id"])
    _assert_enum(data, "purpose", ApplicationPurpose)
    _assert_int(data, "requested_cents", 1)
    _assert_int(data, "granted_cents", 0)
    _assert_enum(data, "status", ApplicationStatus)


# ─── Domain invariant checkers ──────────────────────────────────────────────


def assert_reviewer_alias(alias, appeal_round, seq):
    """Alias shape is R{appeal_round}-{seq}; the sequence is never reused."""
    assert alias == "{0}{1}-{2}".format(REVIEWER_ALIAS_PREFIX, appeal_round, seq), (
        "expected alias R{0}-{1}, got {2!r}".format(appeal_round, seq, alias)
    )


def assert_fund_money_invariant(fund, granted_total_cents):
    """Pool conservation (PRD §3.9): remaining + granted-out == pool total."""
    assert fund["remaining_cents"] + granted_total_cents == fund["pool_total_cents"], (
        "pool not conserved: remaining {0} + granted {1} != pool {2}".format(
            fund["remaining_cents"], granted_total_cents, fund["pool_total_cents"]
        )
    )


def assert_reviewer_count_invariant(profile, non_cancelled_assignment_count):
    """Counter conservation (PRD §3.3/§3.5): open + completed + declined equals
    the reviewer's number of non-CANCELLED assignments."""
    total = (
        profile["open_assignment_count"]
        + profile["completed_review_count"]
        + profile["declined_assignment_count"]
    )
    assert total == non_cancelled_assignment_count, (
        "reviewer counters {0} != non-cancelled assignments {1}".format(
            total, non_cancelled_assignment_count
        )
    )
