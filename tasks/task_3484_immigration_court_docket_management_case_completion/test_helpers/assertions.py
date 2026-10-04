"""Per-entity structural assertions and domain invariant checkers.

Each ``assert_<entity>(data)`` checks the fields the PRD guarantees on the
resource: system fields, input echoes, enum membership, and presence (not
value) of computed fields.  Tests assert concrete computed values themselves;
these helpers only pin shape and types so a malformed representation fails
close to the read that produced it.

``CaseReassignment`` and ``DocketReview`` are immutable ledger records: their
assertions require ``id``/``created_at`` and FORBID ``updated_at``/``version``.
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AppealStatus,
    CaseStatus,
    ContinuanceReason,
    ContinuanceStatus,
    CustodyStatus,
    DecisionOutcome,
    DecisionStatus,
    HearingStatus,
    HearingType,
    MotionBasis,
    MotionStatus,
    NoticeStatus,
    REASSIGNMENT_REASON,
    RepresentationStatus,
    ServiceMethod,
    VenueMotionStatus,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def _assert_ledger(data: dict):
    """Immutable record: id + created_at only, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ledger record must not carry updated_at"
    assert "version" not in data, "ledger record must not carry version"


def _assert_nullable_instant(data: dict, field: str):
    value = data.get(field)
    if value is not None:
        assert is_iso8601_timestamp(value), "{0} must be ISO 8601 or null".format(field)


def _assert_nullable_id(data: dict, field: str):
    value = data.get(field)
    if value is not None:
        assert isinstance(value, str) and value, "{0} must be a non-empty string or null".format(field)


def assert_court(data: dict):
    _assert_common(data)
    assert isinstance(data["court_code"], str) and data["court_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["city"], str) and data["city"]
    assert isinstance(data["annual_completion_goal"], int) and data["annual_completion_goal"] >= 1
    assert isinstance(data["detained_daily_hearing_capacity"], int)
    assert data["detained_daily_hearing_capacity"] >= 0
    assert isinstance(data["pending_case_count"], int) and data["pending_case_count"] >= 0
    assert isinstance(data["completions_ytd"], int) and data["completions_ytd"] >= 0
    assert isinstance(data["is_backlog_critical"], bool)


def assert_judge(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("court_id", "")), "court_id must be a UUID"
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["max_pending_cases"], int) and data["max_pending_cases"] >= 1
    assert isinstance(data["pending_case_load"], int) and data["pending_case_load"] >= 0


def assert_interpreter(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("court_id", "")), "court_id must be a UUID"
    assert isinstance(data["full_name"], str) and data["full_name"]
    codes = data["language_codes"]
    assert isinstance(codes, list) and len(codes) >= 1, "language_codes must be non-empty"
    assert all(isinstance(c, str) and len(c) == 3 and c.islower() for c in codes)
    assert isinstance(data["daily_hearing_cap"], int) and data["daily_hearing_cap"] >= 1


def assert_orientation_program(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("court_id", "")), "court_id must be a UUID"
    assert isinstance(data["program_name"], str) and data["program_name"]
    assert isinstance(data["coverage_pct"], int) and 0 <= data["coverage_pct"] <= 100
    assert isinstance(data["active"], bool)


def assert_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("court_id", "")), "court_id must be a UUID"
    assert isinstance(data["case_number"], str) and data["case_number"]
    assert isinstance(data["respondent_full_name"], str) and data["respondent_full_name"]
    assert data["custody_status"] in {c.value for c in CustodyStatus}
    code = data["primary_language_code"]
    assert isinstance(code, str) and len(code) == 3 and code.islower()
    assert data["representation_status"] in {r.value for r in RepresentationStatus}
    assert isinstance(data["interpreter_required"], bool)
    _assert_nullable_id(data, "assigned_judge_id")
    assert data["status"] in {s.value for s in CaseStatus}
    assert is_iso8601_timestamp(data.get("filed_at", "")), "filed_at must be ISO 8601"
    _assert_nullable_instant(data, "completed_at")
    _assert_nullable_instant(data, "target_completion_date")
    assert isinstance(data["days_pending_calendar"], int)
    assert isinstance(data["days_pending_court"], int)
    assert isinstance(data["is_past_goal"], bool)
    assert isinstance(data["continuance_count"], int) and data["continuance_count"] >= 0
    assert isinstance(data["priority_score"], int) and data["priority_score"] >= 0


def assert_hearing(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert data["hearing_type"] in {t.value for t in HearingType}
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] > 0
    assert data["duration_minutes"] % 15 == 0, "duration is ceiled to a 15-minute block"
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert isinstance(data["is_remote"], bool)
    _assert_nullable_id(data, "judge_id")
    _assert_nullable_id(data, "interpreter_id")
    _assert_nullable_id(data, "supersedes_hearing_id")
    assert isinstance(data["auto_created"], bool)
    assert data["status"] in {s.value for s in HearingStatus}


def assert_notice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("hearing_id", "")), "hearing_id must be a UUID"
    assert data["service_method"] in {m.value for m in ServiceMethod}
    assert is_iso8601_timestamp(data.get("served_at", ""))
    assert data["status"] in {s.value for s in NoticeStatus}


def assert_continuance_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert is_valid_uuid(data.get("hearing_id", "")), "hearing_id must be a UUID"
    assert data["reason_code"] in {r.value for r in ContinuanceReason}
    assert isinstance(data["is_first_for_case"], bool)
    assert data["status"] in {s.value for s in ContinuanceStatus}
    _assert_nullable_id(data, "decided_by_judge_id")
    _assert_nullable_instant(data, "decided_at")


def assert_venue_motion(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert is_valid_uuid(data.get("destination_court_id", ""))
    assert isinstance(data["reason"], str)
    assert data["status"] in {s.value for s in VenueMotionStatus}
    _assert_nullable_id(data, "decided_by_judge_id")
    _assert_nullable_instant(data, "decided_at")


def assert_case_reassignment(data: dict):
    _assert_ledger(data)
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert is_valid_uuid(data.get("from_court_id", "")), "from_court_id must be a UUID"
    assert is_valid_uuid(data.get("to_court_id", "")), "to_court_id must be a UUID"
    assert data["reason"] == REASSIGNMENT_REASON
    assert is_iso8601_timestamp(data.get("executed_at", ""))


def assert_decision(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    _assert_nullable_id(data, "judge_id")
    assert data["outcome"] in {o.value for o in DecisionOutcome}
    _assert_nullable_id(data, "source_hearing_id")
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    _assert_nullable_instant(data, "appeal_deadline")
    _assert_nullable_instant(data, "reopen_deadline")
    assert data["status"] in {s.value for s in DecisionStatus}
    if data["outcome"] != DecisionOutcome.IN_ABSENTIA_REMOVAL.value:
        assert data.get("reopen_deadline") is None, (
            "reopen_deadline is set only on IN_ABSENTIA_REMOVAL decisions"
        )


def assert_appeal(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("decision_id", "")), "decision_id must be a UUID"
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert data["status"] in {s.value for s in AppealStatus}
    assert is_iso8601_timestamp(data.get("filed_at", ""))
    if data.get("grounds") is not None:
        assert isinstance(data["grounds"], str)
    if data.get("remand_instructions") is not None:
        assert isinstance(data["remand_instructions"], str)
    _assert_nullable_id(data, "decided_by_board_member_id")
    _assert_nullable_instant(data, "decided_at")


def assert_motion_to_reopen(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert is_valid_uuid(data.get("decision_id", "")), "decision_id must be a UUID"
    assert data["basis"] in {b.value for b in MotionBasis}
    assert is_iso8601_timestamp(data.get("filed_at", ""))
    assert data["status"] in {s.value for s in MotionStatus}
    _assert_nullable_id(data, "decided_by_judge_id")
    _assert_nullable_instant(data, "decided_at")


def assert_docket_review(data: dict):
    _assert_ledger(data)
    assert is_valid_uuid(data.get("court_id", "")), "court_id must be a UUID"
    assert isinstance(data["run_index"], int) and data["run_index"] >= 1
    assert is_iso8601_timestamp(data.get("computed_at", ""))
    assert isinstance(data["pending_case_count"], int) and data["pending_case_count"] >= 0
    assert isinstance(data["completions_ytd"], int) and data["completions_ytd"] >= 0
    for field in ("representation_rate_pct", "pace_ratio_calendar", "pace_ratio_hearing_day"):
        assert isinstance(data[field], (int, float)) and not isinstance(data[field], bool), (
            "{0} must be numeric".format(field)
        )
        assert data[field] >= 0
    assert isinstance(data["is_backlog_critical"], bool)
    assert isinstance(data["is_on_pace"], bool)
    assert isinstance(data["cases_finalized_by_lapse"], int)
    assert data["cases_finalized_by_lapse"] >= 0


# ─── Domain invariant checkers ────────────────────────────────────────────


def assert_case_status(case_data: dict, expected_status: str):
    assert case_data["status"] == expected_status, (
        "Expected case status {0}, got {1}".format(expected_status, case_data.get("status"))
    )


def assert_single_scheduled_hearing(hearings: list):
    """At most one SCHEDULED hearing per case — call on a case's hearing list."""
    scheduled = [h for h in hearings if h.get("status") == HearingStatus.SCHEDULED.value]
    assert len(scheduled) <= 1, (
        "case holds {0} SCHEDULED hearings; at most one is allowed".format(len(scheduled))
    )


def assert_backlog_flag(court_data: dict, expected_pending: int, expected_critical: bool):
    """Court counters recomputed live on reads (PRD section 2.9)."""
    assert court_data["pending_case_count"] == expected_pending, (
        "pending_case_count {0} != expected {1}".format(
            court_data["pending_case_count"], expected_pending
        )
    )
    assert court_data["is_backlog_critical"] is expected_critical, (
        "is_backlog_critical {0} != expected {1} at pending {2}".format(
            court_data["is_backlog_critical"], expected_critical, expected_pending
        )
    )
