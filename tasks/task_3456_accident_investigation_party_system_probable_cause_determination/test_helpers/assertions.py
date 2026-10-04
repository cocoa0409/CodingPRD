"""Entity assertions and domain invariant checkers.

Field names and enum sets follow the PRD resource descriptions (§2.5, §3.1–§3.8).
The score calculators re-implement the PRD-pinned formulas (§3.1) so tests can
verify computed fields against independently derived expectations.
"""
from decimal import ROUND_HALF_UP, Decimal

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    CATASTROPHIC_FATALITY_BONUS,
    CATASTROPHIC_FATALITY_THRESHOLD,
    CATEGORY_DAMAGE_MULTIPLIER,
    DAMAGE_POINTS_HIGH,
    DAMAGE_POINTS_LOW,
    DAMAGE_POINTS_MID,
    DAMAGE_TIER_HIGH_MIN_CENTS,
    DAMAGE_TIER_MID_MIN_CENTS,
    FATALITY_BASE_POINTS,
    FATALITY_WEIGHT,
    FULL_LAUNCH_THRESHOLD,
    INJURY_CAP,
    INJURY_WEIGHT,
    LIMITED_LAUNCH_THRESHOLD,
    MODAL_BUMP_CATEGORIES,
    MODAL_BUMP_POINTS,
    PUBLIC_INTEREST_WEIGHT,
    PUBLIC_TRANSPORT_POINTS,
    SCORE_MAX,
)
from .types import (
    AccidentCategory,
    AccidentCaseStatus,
    AgingBucket,
    BoardMeetingStatus,
    BoardOutcome,
    DocketStatus,
    FactualReportStatus,
    GroupSeatStatus,
    GroupSpecialty,
    InvestigationPhase,
    InvestigativeGroupStatus,
    LaunchDecisionStatus,
    LaunchMode,
    OrgType,
    PartyDesignationStatus,
    RecorderCondition,
    RecorderPackageStatus,
    RecorderType,
    ReadoutSessionStatus,
    ReportKind,
    SafetyRecommendationStatus,
    ViolationKind,
)


def _values(enum_cls):
    return [member.value for member in enum_cls]


def assert_common_fields(data: dict):
    """Standard system-managed fields on every top-level resource (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an int >= 1, got {data.get('version')!r}"
    )


# ---------------------------------------------------------------------------
# Embedded records
# ---------------------------------------------------------------------------

def assert_launch_decision(decision: dict):
    assert is_valid_uuid(decision.get("decision_id", "")), "decision_id must be a UUID"
    assert decision["mode"] in _values(LaunchMode)
    assert decision["status"] in _values(LaunchDecisionStatus)
    assert isinstance(decision["proposed_by_user_id"], str) and decision["proposed_by_user_id"]
    assert is_iso8601_timestamp(decision.get("proposed_at", "")), "proposed_at must be ISO 8601"
    adopted_at = decision.get("adopted_at")
    if adopted_at is not None:
        assert is_iso8601_timestamp(adopted_at), "adopted_at must be ISO 8601 when present"
    assert isinstance(decision["snapshot_statutory_score"], (int, float))
    assert isinstance(decision["snapshot_risk_adjusted_score"], (int, float))
    # rationale is optional free text; when present it must be a string.
    rationale = decision.get("rationale")
    assert rationale is None or isinstance(rationale, str)
    # Embedded records carry no updated_at / version of their own (PRD §2.5).
    assert "updated_at" not in decision, "embedded records must not carry updated_at"
    assert "version" not in decision, "embedded records must not carry version"


def assert_group_seat(seat: dict):
    assert is_valid_uuid(seat.get("seat_id", "")), "seat_id must be a UUID"
    assert is_valid_uuid(seat.get("group_id", "")), "group_id must be a UUID"
    assert seat["status"] in _values(GroupSeatStatus)
    assert isinstance(seat["strike_count"], int) and seat["strike_count"] >= 0
    conduct_log = seat["conduct_log"]
    assert isinstance(conduct_log, list)
    assert seat["strike_count"] == len(conduct_log), (
        "strike_count must equal the length of conduct_log (PRD §3.4)"
    )
    for entry in conduct_log:
        assert entry["violation_kind"] in _values(ViolationKind)
        assert isinstance(entry["detail"], str)
        assert is_iso8601_timestamp(entry.get("recorded_at", "")), (
            "conduct_log.recorded_at must be ISO 8601"
        )
    assert "updated_at" not in seat and "version" not in seat


def assert_factual_report(report: dict):
    assert is_valid_uuid(report.get("report_id", "")), "report_id must be a UUID"
    assert report["report_kind"] in _values(ReportKind)
    assert isinstance(report["content"], str) and len(report["content"]) > 0
    recorder_id = report.get("recorder_id")
    if report["report_kind"] == "RECORDER_TRANSCRIPT":
        assert is_valid_uuid(recorder_id or ""), (
            "recorder_id is required for RECORDER_TRANSCRIPT reports (PRD §3.5)"
        )
    else:
        assert recorder_id is None, (
            "recorder_id must be absent for non-transcript reports (PRD §3.5)"
        )
    assert report["status"] in _values(FactualReportStatus)
    assert isinstance(report["submitted_by_user_id"], str) and report["submitted_by_user_id"]
    assert is_iso8601_timestamp(report.get("submitted_at", "")), "submitted_at must be ISO 8601"
    verified_at = report.get("verified_at")
    if verified_at is not None:
        assert is_iso8601_timestamp(verified_at), "verified_at must be ISO 8601 when present"
    assert "updated_at" not in report and "version" not in report


def assert_readout_session(session: dict):
    assert is_valid_uuid(session.get("session_id", "")), "session_id must be a UUID"
    assert isinstance(session["bench_id"], str) and session["bench_id"]
    assert is_iso8601_timestamp(session.get("window_start_utc", ""))
    assert is_iso8601_timestamp(session.get("window_end_utc", ""))
    assert session["status"] in _values(ReadoutSessionStatus)
    assert "updated_at" not in session and "version" not in session


# ---------------------------------------------------------------------------
# Top-level resources
# ---------------------------------------------------------------------------

def assert_accident_case(data: dict):
    assert_common_fields(data)
    assert isinstance(data["report_number"], str) and data["report_number"]
    assert data["category"] in _values(AccidentCategory)
    assert is_iso8601_timestamp(data.get("occurred_at", "")), "occurred_at must be ISO 8601"
    assert isinstance(data["location_state"], str) and len(data["location_state"]) == 2
    assert isinstance(data["fatalities_count"], int) and data["fatalities_count"] >= 0
    assert isinstance(data["injuries_count"], int) and data["injuries_count"] >= 0
    assert isinstance(data["damage_estimate_cents"], int) and data["damage_estimate_cents"] >= 0
    assert isinstance(data["is_public_transport"], bool)
    assert isinstance(data["statutory_score"], (int, float))
    assert 0 <= data["statutory_score"] <= SCORE_MAX
    assert isinstance(data["risk_adjusted_score"], (int, float))
    assert 0 <= data["risk_adjusted_score"] <= SCORE_MAX
    assert data["suggested_mode"] in _values(LaunchMode)
    assert data["status"] in _values(AccidentCaseStatus)
    assert isinstance(data["launch_decisions"], list)
    for decision in data["launch_decisions"]:
        assert_launch_decision(decision)


def assert_investigation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("accident_case_id", "")), "accident_case_id must be a UUID"
    assert isinstance(data["iic_user_id"], str) and data["iic_user_id"]
    assert data["phase"] in _values(InvestigationPhase)
    assert data["docket_status"] in _values(DocketStatus)
    pct = data["docket_completeness_pct"]
    assert isinstance(pct, int) and 0 <= pct <= 100, (
        f"docket_completeness_pct must be an int in 0..100, got {pct!r}"
    )


def assert_party_organization(data: dict):
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["org_type"] in _values(OrgType)


def assert_party_designation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("investigation_id", "")), "investigation_id must be a UUID"
    assert is_valid_uuid(data.get("organization_id", "")), "organization_id must be a UUID"
    assert data["status"] in _values(PartyDesignationStatus)
    assert is_iso8601_timestamp(data.get("designated_at", "")), "designated_at must be ISO 8601"
    reason = data.get("expulsion_reason")
    assert reason is None or isinstance(reason, str)
    assert isinstance(data["group_seats"], list)
    for seat in data["group_seats"]:
        assert_group_seat(seat)


def assert_investigative_group(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("investigation_id", "")), "investigation_id must be a UUID"
    assert data["specialty"] in _values(GroupSpecialty)
    assert isinstance(data["chairman_user_id"], str) and data["chairman_user_id"]
    assert data["status"] in _values(InvestigativeGroupStatus)
    assert isinstance(data["seated_count"], int) and data["seated_count"] >= 0
    assert isinstance(data["factual_reports"], list)
    for report in data["factual_reports"]:
        assert_factual_report(report)


def assert_recorder_package(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("investigation_id", "")), "investigation_id must be a UUID"
    assert data["recorder_type"] in _values(RecorderType)
    assert data["condition"] in _values(RecorderCondition)
    assert data["status"] in _values(RecorderPackageStatus)
    assert isinstance(data["readout_sessions"], list)
    for session in data["readout_sessions"]:
        assert_readout_session(session)


def assert_safety_recommendation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("investigation_id", "")), "investigation_id must be a UUID"
    assert is_valid_uuid(data.get("addressee_org_id", "")), "addressee_org_id must be a UUID"
    assert isinstance(data["recommendation_text"], str) and data["recommendation_text"]
    assert data["status"] in _values(SafetyRecommendationStatus)
    assert is_iso8601_timestamp(data.get("issued_at", "")), "issued_at must be ISO 8601"
    assert isinstance(data["response_log"], list)
    for entry in data["response_log"]:
        assert is_valid_uuid(entry.get("response_id", "")), "response_id must be a UUID"
        assert isinstance(entry["response_text"], str)
        assert is_iso8601_timestamp(entry.get("responded_at", "")), (
            "responded_at must be ISO 8601"
        )
        assert isinstance(entry["classification_pending"], bool)
        classification = entry.get("classification")
        assert classification is None or classification in ("ACCEPTABLE", "UNACCEPTABLE")
        classified_at = entry.get("classified_at")
        assert classified_at is None or is_iso8601_timestamp(classified_at)
    pending = [e for e in data["response_log"] if e["classification_pending"]]
    assert len(pending) <= 1, "at most one response may await classification (PRD §3.7)"
    assert isinstance(data["unacceptable_streak"], int) and data["unacceptable_streak"] >= 0
    assert isinstance(data["calendar_elapsed_days"], int) and data["calendar_elapsed_days"] >= 0
    assert isinstance(data["business_elapsed_days"], int) and data["business_elapsed_days"] >= 0
    assert isinstance(data["overdue"], bool)
    assert data["aging_bucket"] in _values(AgingBucket)


def assert_board_meeting(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("investigation_id", "")), "investigation_id must be a UUID"
    assert isinstance(data["room_id"], str) and data["room_id"]
    assert is_iso8601_timestamp(data.get("window_start_utc", ""))
    assert is_iso8601_timestamp(data.get("window_end_utc", ""))
    sitting = data["sitting_member_ids"]
    assert isinstance(sitting, list) and all(isinstance(m, str) for m in sitting)
    assert data["status"] in _values(BoardMeetingStatus)
    assert isinstance(data["member_votes"], list)
    for vote in data["member_votes"]:
        assert isinstance(vote["member_user_id"], str) and vote["member_user_id"]
        assert vote["position"] in ("ADOPT", "REJECT", "ABSTAIN"), (
            "stored vote positions are ADOPT/REJECT/ABSTAIN (RETRACT removes the entry)"
        )
        dissent = vote.get("dissent_text")
        assert dissent is None or isinstance(dissent, str)
        assert is_iso8601_timestamp(vote.get("cast_at", "")), "cast_at must be ISO 8601"
    for field in ("adopt_count", "reject_count", "abstain_count"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert isinstance(data["dissenting_member_ids"], list)
    outcome = data.get("outcome")
    assert outcome is None or outcome in _values(BoardOutcome)


# ---------------------------------------------------------------------------
# Domain invariant checkers / score calculators (PRD §3.1, §3.8)
# ---------------------------------------------------------------------------

def compute_statutory_score(
    fatalities_count: int,
    injuries_count: int,
    damage_estimate_cents: int,
    is_public_transport: bool,
    category: str,
) -> int:
    """Flat integer statutory sum with clamp (PRD §3.1)."""
    if fatalities_count == 0:
        fatality_points = 0
    else:
        fatality_points = FATALITY_BASE_POINTS + (
            CATASTROPHIC_FATALITY_BONUS
            if fatalities_count >= CATASTROPHIC_FATALITY_THRESHOLD
            else 0
        )
    if damage_estimate_cents == 0:
        damage_points = 0
    elif damage_estimate_cents < DAMAGE_TIER_MID_MIN_CENTS:
        damage_points = DAMAGE_POINTS_LOW
    elif damage_estimate_cents < DAMAGE_TIER_HIGH_MIN_CENTS:
        damage_points = DAMAGE_POINTS_MID
    else:
        damage_points = DAMAGE_POINTS_HIGH
    injury_points = min(injuries_count, INJURY_CAP)
    public_points = (PUBLIC_TRANSPORT_POINTS if is_public_transport else 0) + (
        MODAL_BUMP_POINTS if category in MODAL_BUMP_CATEGORIES else 0
    )
    return max(
        0, min(SCORE_MAX, fatality_points + damage_points + injury_points + public_points)
    )


def compute_risk_adjusted_score(
    fatalities_count: int,
    injuries_count: int,
    damage_estimate_cents: int,
    is_public_transport: bool,
    category: str,
) -> float:
    """Weighted variant: each component rounded half-up to 1 decimal BEFORE
    summation, then clamped (PRD §3.1 — the rounding order is pinned)."""
    if fatalities_count == 0:
        fatality_points = 0
    else:
        fatality_points = FATALITY_BASE_POINTS + (
            CATASTROPHIC_FATALITY_BONUS
            if fatalities_count >= CATASTROPHIC_FATALITY_THRESHOLD
            else 0
        )
    if damage_estimate_cents == 0:
        damage_points = 0
    elif damage_estimate_cents < DAMAGE_TIER_MID_MIN_CENTS:
        damage_points = DAMAGE_POINTS_LOW
    elif damage_estimate_cents < DAMAGE_TIER_HIGH_MIN_CENTS:
        damage_points = DAMAGE_POINTS_MID
    else:
        damage_points = DAMAGE_POINTS_HIGH
    injury_points = min(injuries_count, INJURY_CAP)
    public_points = (PUBLIC_TRANSPORT_POINTS if is_public_transport else 0) + (
        MODAL_BUMP_POINTS if category in MODAL_BUMP_CATEGORIES else 0
    )

    def round1(value) -> Decimal:
        return Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

    # Components are rounded half-up to 1 decimal BEFORE summation (pinned
    # order); the sum is accumulated exactly in Decimal so the published
    # expectation (e.g. 62.6) compares equal, then clamped.
    c_fatality = round1(fatality_points * FATALITY_WEIGHT)
    c_damage = round1(damage_points * CATEGORY_DAMAGE_MULTIPLIER[category])
    c_injury = round1(injury_points * INJURY_WEIGHT)
    c_public = round1(public_points * PUBLIC_INTEREST_WEIGHT)
    total = c_fatality + c_damage + c_injury + c_public
    return float(max(Decimal("0"), min(Decimal(SCORE_MAX), total)))


def compute_suggested_mode(statutory_score) -> str:
    """Suggested disposition derived from the statutory score alone (PRD §3.1)."""
    if statutory_score >= FULL_LAUNCH_THRESHOLD:
        return "FULL_GO_TEAM"
    if statutory_score >= LIMITED_LAUNCH_THRESHOLD:
        return "LIMITED"
    return "DECLINED"


def assert_case_scores(case: dict):
    """Recompute both launch scores and suggested_mode from the case's stored
    severity fields and require the stored computed fields to match (PRD §3.1)."""
    expected_statutory = compute_statutory_score(
        case["fatalities_count"],
        case["injuries_count"],
        case["damage_estimate_cents"],
        case["is_public_transport"],
        case["category"],
    )
    assert case["statutory_score"] == expected_statutory, (
        f"statutory_score {case['statutory_score']} != recomputed {expected_statutory} "
        f"for severity {case['fatalities_count']}/{case['injuries_count']}/"
        f"{case['damage_estimate_cents']}/{case['is_public_transport']}/{case['category']}"
    )
    expected_risk = compute_risk_adjusted_score(
        case["fatalities_count"],
        case["injuries_count"],
        case["damage_estimate_cents"],
        case["is_public_transport"],
        case["category"],
    )
    assert case["risk_adjusted_score"] == pytest.approx(expected_risk, abs=1e-6), (
        f"risk_adjusted_score {case['risk_adjusted_score']} != recomputed {expected_risk}"
    )
    assert case["suggested_mode"] == compute_suggested_mode(expected_statutory)


def assert_meeting_tallies(meeting: dict):
    """Vote tallies and the dissent roster must recount exactly from
    member_votes (PRD §3.8): adopt/reject/abstain counts, at most one entry per
    member, and dissenting_member_ids as the REJECT voters ordered by cast_at
    ascending with append-order tie-break."""
    votes = meeting["member_votes"]
    member_ids = [v["member_user_id"] for v in votes]
    assert len(member_ids) == len(set(member_ids)), (
        "at most one member_votes entry per sitting member"
    )
    adopt = sum(1 for v in votes if v["position"] == "ADOPT")
    reject = sum(1 for v in votes if v["position"] == "REJECT")
    abstain = sum(1 for v in votes if v["position"] == "ABSTAIN")
    assert meeting["adopt_count"] == adopt, (
        f"adopt_count {meeting['adopt_count']} != recount {adopt}"
    )
    assert meeting["reject_count"] == reject, (
        f"reject_count {meeting['reject_count']} != recount {reject}"
    )
    assert meeting["abstain_count"] == abstain, (
        f"abstain_count {meeting['abstain_count']} != recount {abstain}"
    )
    # Stable sort by cast_at reproduces "cast_at ascending, ties broken by
    # append order" because member_votes is itself in append order.
    expected_dissenters = [
        v["member_user_id"]
        for v in sorted(
            (v for v in votes if v["position"] == "REJECT"), key=lambda v: v["cast_at"]
        )
    ]
    assert meeting["dissenting_member_ids"] == expected_dissenters


__all__ = [
    "assert_common_fields",
    "assert_launch_decision",
    "assert_group_seat",
    "assert_factual_report",
    "assert_readout_session",
    "assert_accident_case",
    "assert_investigation",
    "assert_party_organization",
    "assert_party_designation",
    "assert_investigative_group",
    "assert_recorder_package",
    "assert_safety_recommendation",
    "assert_board_meeting",
    "compute_statutory_score",
    "compute_risk_adjusted_score",
    "compute_suggested_mode",
    "assert_case_scores",
    "assert_meeting_tallies",
]
