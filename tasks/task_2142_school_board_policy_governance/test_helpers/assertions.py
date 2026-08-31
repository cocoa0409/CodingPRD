"""Entity assertions, instant comparison and governance-ledger invariant checkers."""

import re
from datetime import datetime, timezone
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

BARE_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating a trailing Z and optional fraction."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: Optional[str], expected_iso: str, label: str = "instant"):
    """Assert a stamped timestamp names exactly the expected UTC instant."""
    assert actual is not None, f"{label} must be stamped, got null"
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected {expected_iso}, got {actual}"
    )


def assert_bare_uuid(value: str, label: str = "id"):
    assert isinstance(value, str), f"{label} must be a string"
    assert BARE_UUID_RE.match(value), f"{label} must be a bare UUID with no type prefix, got {value!r}"
    assert is_valid_uuid(value), f"{label} must be a valid UUID, got {value!r}"


def assert_record_identity(data: dict, entity: str = "record"):
    """Every resource family carries id, created_at, updated_at and version."""
    assert_bare_uuid(data.get("id", ""), f"{entity}.id")
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version starts at 1, got {data['version']}"


def assert_board_member(data: dict):
    assert_record_identity(data, "BoardMember")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["seat_number"], int) and 1 <= data["seat_number"] <= 15
    assert data["office"] in ("PRESIDENT", "VICE_PRESIDENT", "MEMBER")
    assert data["status"] in ("SEATED", "RESIGNED", "TERM_EXPIRED")
    assert isinstance(data["open_recusal_count"], int) and data["open_recusal_count"] >= 0
    assert isinstance(data["active_committee_count"], int) and data["active_committee_count"] >= 0


def assert_committee(data: dict):
    assert_record_identity(data, "Committee")
    assert data["charter_type"] in ("POLICY", "FINANCE", "PERSONNEL", "AUDIT")
    assert 3 <= data["seat_capacity"] <= 9
    assert data["quorum_size"] >= 2
    assert data["quorum_size"] <= data["seat_capacity"]
    assert data["status"] in ("ACTIVE", "INQUORATE")
    assert_committee_seat_conservation(data)


def assert_committee_seat_conservation(data: dict):
    """seat_capacity always equals filled_seat_count plus vacant_seat_count."""
    assert data["seat_capacity"] == data["filled_seat_count"] + data["vacant_seat_count"], (
        "seat_capacity must equal filled_seat_count + vacant_seat_count, got "
        f"{data['seat_capacity']} != {data['filled_seat_count']} + {data['vacant_seat_count']}"
    )
    assert 0 <= data["voting_seat_count"] <= data["filled_seat_count"]


def assert_committee_assignment(data: dict):
    assert_record_identity(data, "CommitteeAssignment")
    assert data["role_on_committee"] in ("CHAIR", "MEMBER")
    assert data["status"] in ("ACTIVE", "RECUSED", "REMOVED")
    assert is_iso8601_timestamp(data.get("assigned_on", ""))


def assert_conflict_disclosure(data: dict):
    assert_record_identity(data, "ConflictDisclosure")
    assert data["nature"] in ("FINANCIAL", "VENDOR", "EMPLOYMENT", "FAMILIAL")
    assert data["status"] in ("RECUSAL_REQUIRED", "ADVISORY_ONLY", "CLEARED")
    assert is_iso8601_timestamp(data.get("disclosed_on", ""))


def assert_policy(data: dict):
    assert_record_identity(data, "Policy")
    assert isinstance(data["code"], str) and 3 <= len(data["code"]) <= 20
    assert data["category"] in ("GOVERNANCE", "INSTRUCTION", "PERSONNEL", "STUDENTS", "BUSINESS")
    assert data["legal_requirement_level"] in (
        "REQUIRED_BY_LAW",
        "RECOMMENDED",
        "LOCAL_DISCRETION",
    )
    assert data["status"] in ("UNADOPTED", "ADOPTED")
    assert data["compliance_state"] in ("COMPLIANT", "ACTION_REQUIRED", "NON_COMPLIANT")
    for counter in (
        "version_count",
        "open_mandate_count",
        "overdue_mandate_count",
        "active_waiver_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, f"Policy.{counter} must be >= 0"


def assert_policy_version(data: dict):
    assert_record_identity(data, "PolicyVersion")
    assert isinstance(data["version_no"], int) and data["version_no"] >= 1
    assert data["status"] in (
        "DRAFT",
        "FIRST_READING_PASSED",
        "ADOPTED",
        "SUPERSEDED",
        "WITHDRAWN",
    )
    assert data["reading_count"] in (0, 1, 2)


def assert_legal_mandate(data: dict):
    assert_record_identity(data, "LegalMandate")
    assert data["required_action"] in ("ADOPT_NEW", "REVISE_EXISTING", "RESCIND")
    assert data["status"] in ("OPEN", "IN_PROGRESS", "OVERDUE", "SATISFIED")
    assert isinstance(data["days_past_deadline"], int) and data["days_past_deadline"] >= 0


def assert_meeting(data: dict):
    assert_record_identity(data, "Meeting")
    assert data["scope"] in ("FULL_BOARD", "COMMITTEE")
    assert data["meeting_type"] in ("REGULAR", "SPECIAL", "EMERGENCY")
    assert data["status"] in ("DRAFT", "NOTICED", "OPEN", "ADJOURNED")
    assert data["minutes_status"] in ("NOT_DRAFTED", "DRAFTED", "APPROVED")
    assert data["public_comment_rule"] in ("FIRST_COME_CAPPED", "EQUAL_SPLIT")
    assert isinstance(data["attending_member_ids"], list)
    assert data["public_comment_minutes_remaining"] >= 0


def assert_agenda_item(data: dict):
    assert_record_identity(data, "AgendaItem")
    assert data["item_type"] in (
        "POLICY_FIRST_READING",
        "POLICY_SECOND_READING",
        "WAIVER_DECISION",
        "SUPERINTENDENT_EVALUATION",
        "CONSENT",
    )
    assert data["status"] in ("PROPOSED", "POSTED", "ACTED", "TABLED", "WITHDRAWN")
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert isinstance(data["requires_public_comment"], bool)


def assert_public_comment(data: dict):
    assert_record_identity(data, "PublicComment")
    assert data["speaker_affiliation"] in ("PARENT", "STAFF", "STUDENT", "COMMUNITY", "VENDOR")
    assert 1 <= data["requested_minutes"] <= 5
    assert data["status"] in ("REQUESTED", "GRANTED", "DENIED", "RELEASED")
    assert data["allotted_minutes"] >= 0


def assert_waiver_request(data: dict):
    assert_record_identity(data, "WaiverRequest")
    assert data["status"] in ("SUBMITTED", "BOARD_PENDING", "GRANTED", "DENIED", "REVOKED", "EXPIRED")
    assert data["granted_days"] >= 0, "granted_days is never below zero"
    assert data["max_allowed_days"] in (90, 180, 365)


def assert_superintendent_evaluation(data: dict):
    assert_record_identity(data, "SuperintendentEvaluation")
    assert 2020 <= data["cycle_year"] <= 2100
    assert 1 <= data["goal_count"] <= 10
    assert data["status"] in (
        "PLANNING",
        "GOALS_SET",
        "MIDYEAR_REVIEW",
        "SUMMATIVE_DRAFT",
        "ADOPTED",
    )
    total = (
        data["weight_instructional"]
        + data["weight_fiscal"]
        + data["weight_community"]
        + data["weight_governance"]
    )
    assert abs(total - 1.00) < 0.005, f"the four rubric weights must sum to 1.00, got {total}"


def assert_evaluation_rating(data: dict):
    assert_record_identity(data, "EvaluationRating")
    assert data["domain"] in (
        "INSTRUCTIONAL_LEADERSHIP",
        "FISCAL_STEWARDSHIP",
        "COMMUNITY_RELATIONS",
        "GOVERNANCE_SUPPORT",
    )
    assert 1 <= data["score"] <= 5
    assert data["phase"] in ("FORMATIVE", "SUMMATIVE")
    assert isinstance(data["counted_in_summative"], bool)


def assert_manual_publication(data: dict):
    assert_record_identity(data, "ManualPublication")
    assert data["status"] in ("BUILDING", "PUBLISHED", "SUPERSEDED")
    assert data["certification_state"] in ("PENDING", "CERTIFIED", "LAPSED")
    assert isinstance(data["pinned_entries"], list)
    assert data["entry_count"] == len(data["pinned_entries"])
    assert data["compliance_gap_count"] >= 0


# ---------------------------------------------------------------------------
# Conservation ledgers
# ---------------------------------------------------------------------------


def assert_public_comment_minute_conservation(meeting: dict, granted_cards: list):
    """budget == remaining + the sum of allotted_minutes over GRANTED cards."""
    granted_total = sum(c["allotted_minutes"] for c in granted_cards if c["status"] == "GRANTED")
    assert meeting["public_comment_minutes_budget"] == (
        meeting["public_comment_minutes_remaining"] + granted_total
    ), (
        "public_comment_minutes_budget must equal remaining plus every granted minute: "
        f"{meeting['public_comment_minutes_budget']} != "
        f"{meeting['public_comment_minutes_remaining']} + {granted_total}"
    )


def assert_vote_ledger_balances(item: dict, seated_member_count_snapshot: int):
    """yes + no + abstain + recused + absent equals the frozen seated snapshot."""
    total = (
        item["vote_yes"]
        + item["vote_no"]
        + item["vote_abstain"]
        + item["recused_member_count"]
        + item["absent_member_count"]
    )
    assert total == seated_member_count_snapshot, (
        "the vote ledger must sum to seated_member_count_snapshot: "
        f"{total} != {seated_member_count_snapshot}"
    )
