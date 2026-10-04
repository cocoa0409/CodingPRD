"""Entity assertions and domain invariant checkers.

`assert_instant_equals` compares two ISO 8601 timestamps by the instant they
denote, not by spelling: the PRD pins the logical-clock value a stamp must
record (§2.5) while §2.2/§2.5 render timestamps with fractional digits, so a
fixture expectation like "2026-09-02T00:00:00Z" must match a server
rendering of the same instant such as "2026-09-02T00:00:00.000Z".
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def assert_instant_equals(actual, expected, label="timestamp"):
    """Both arguments are ISO 8601 renderings; assert the same UTC instant."""
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"{label}: expected instant {expected}, got {actual}"
    )


def _assert_common(data):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID: {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')}"
    )


def assert_election_cycle(data: dict):
    _assert_common(data)
    assert isinstance(data["cycle_name"], str) and data["cycle_name"]
    assert isinstance(data["election_date"], str) and data["election_date"]
    assert data["status"] in ("DRAFT", "OPEN", "PUBLISHED", "ARCHIVED")
    assert isinstance(data["distributed_edition_count"], int)
    assert data["distributed_edition_count"] >= 0


def assert_jurisdiction(data: dict):
    _assert_common(data)
    assert isinstance(data["cycle_id"], str) and data["cycle_id"]
    assert isinstance(data["jurisdiction_name"], str) and data["jurisdiction_name"]
    assert isinstance(data["fips_code"], str) and data["fips_code"]
    langs = data["supported_language_codes"]
    assert isinstance(langs, list) and len(langs) > 0
    assert all(code in ("EN", "ES", "ZH", "VI", "TL") for code in langs)
    assert data["reading_level_metric"] in ("FLESCH_KINCAID", "SMOG")


def assert_contest(data: dict):
    _assert_common(data)
    assert isinstance(data["jurisdiction_id"], str) and data["jurisdiction_id"]
    assert data["kind"] in ("CANDIDATE_RACE", "BALLOT_MEASURE")
    assert data["status"] in (
        "FILING_OPEN", "QUESTIONNAIRE_PHASE", "GUIDE_READY", "LOCKED"
    )
    assert isinstance(data["verified_candidate_count"], int)
    assert data["verified_candidate_count"] >= 0
    assert isinstance(data["completion_index"], (int, float))
    assert 0.0 <= float(data["completion_index"]) <= 100.0
    assert isinstance(data["seat_count"], int) and data["seat_count"] >= 1
    assert isinstance(data["vote_for_count"], int) and data["vote_for_count"] >= 1
    assert isinstance(data["questionnaire_word_limit"], int)
    assert data["word_count_policy"] in ("STRICT", "LENIENT")


def assert_filing(data: dict):
    _assert_common(data)
    assert isinstance(data["contest_id"], str) and data["contest_id"]
    assert isinstance(data["candidate_name"], str) and data["candidate_name"]
    assert isinstance(data["party_label"], str)
    assert isinstance(data["filing_reference"], str) and data["filing_reference"]
    assert data["status"] in ("FILED", "VERIFIED", "WITHDRAWN", "DISQUALIFIED")
    assert is_iso8601_timestamp(data.get("filed_at", ""))
    assert isinstance(data["withdrawal_count"], int) and data["withdrawal_count"] >= 0


def assert_questionnaire(data: dict):
    _assert_common(data)
    assert isinstance(data["contest_id"], str) and data["contest_id"]
    assert is_iso8601_timestamp(data.get("due_at", ""))
    assert isinstance(data["questions"], list)
    assert data["status"] in ("DRAFT", "ISSUED", "CLOSED", "PINNED")
    for counter in ("invited_count", "submitted_count", "nonresponse_count", "late_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0, counter
    assert data["submitted_count"] <= data["invited_count"]
    assert data["nonresponse_count"] <= data["invited_count"]
    assert data["late_count"] <= data["invited_count"]


def assert_candidate_response(data: dict):
    _assert_common(data)
    assert isinstance(data["questionnaire_id"], str) and data["questionnaire_id"]
    assert isinstance(data["filing_id"], str) and data["filing_id"]
    assert isinstance(data["answers"], list)
    assert data["status"] in (
        "INVITED", "SUBMITTED", "OVER_LIMIT_RETURNED",
        "NONRESPONSE_MARKED", "LATE_UNPUBLISHED", "WITHDRAWN_HIDDEN",
    )
    assert isinstance(data["per_answer_word_counts"], list)
    assert isinstance(data["over_limit_positions"], list)
    assert data["published_indicator"] in (
        "PENDING", "PUBLISHED_UNEDITED", "DID_NOT_RESPOND", "LATE", "WITHDRAWN"
    )


def assert_ballot_measure(data: dict):
    _assert_common(data)
    assert isinstance(data["contest_id"], str) and data["contest_id"]
    assert isinstance(data["measure_title"], str) and data["measure_title"]
    assert isinstance(data["drafter_volunteer_id"], str)
    assert data["status"] in (
        "DRAFTING", "IN_NEUTRALITY_REVIEW", "REMANDED", "APPROVED_FOR_GUIDE"
    )
    assert isinstance(data["review_round_count"], int)
    assert isinstance(data["approvals_this_round"], int)
    assert isinstance(data["pro_word_total"], int)
    assert isinstance(data["con_word_total"], int)
    assert isinstance(data["balance_ratio"], (int, float))
    assert isinstance(data["balance_flag"], bool)
    assert isinstance(data["grade_fk"], (int, float))
    assert isinstance(data["grade_smog"], (int, float))


def assert_measure_argument(data: dict):
    _assert_common(data)
    assert isinstance(data["measure_id"], str) and data["measure_id"]
    assert data["side"] in ("PRO", "CON")
    assert isinstance(data["argument_text"], str)
    assert isinstance(data["author_credit"], str)
    assert isinstance(data["word_count"], int) and data["word_count"] >= 0
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "REJECTED")


def assert_neutrality_review(data: dict):
    _assert_common(data)
    assert isinstance(data["measure_id"], str) and data["measure_id"]
    assert isinstance(data["reviewer_volunteer_id"], str)
    assert data["verdict"] in ("NEUTRAL", "LOADED_LANGUAGE", "UNBALANCED")
    assert isinstance(data["round_index"], int) and data["round_index"] >= 1


def assert_guide_edition(data: dict):
    _assert_common(data)
    assert isinstance(data["cycle_id"], str) and data["cycle_id"]
    assert data["language_code"] in ("EN", "ES", "ZH", "VI", "TL")
    assert data["channel"] in ("PRINT", "WEB", "PARTNER")
    assert data["accessibility_format"] in ("STANDARD", "LARGE_PRINT", "SCREEN_READER")
    assert data["status"] in ("ASSEMBLING", "READY", "DISTRIBUTED", "RETIRED")
    assert isinstance(data["snapshot_contest_ids"], list)
    assert isinstance(data["pinned_questionnaire_versions"], dict)


def assert_allocation_conservation(edition: dict):
    """The distributed copies and the unallocated remainder sum to the run."""
    if edition.get("status") in ("DISTRIBUTED", "RETIRED"):
        total = sum(a["allocated"] for a in edition["allocations"])
        assert total + edition["unallocated_copies"] == edition["print_run_total"], (
            "allocated + unallocated must conserve print_run_total"
        )


def assert_forum(data: dict):
    _assert_common(data)
    assert isinstance(data["contest_id"], str) and data["contest_id"]
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert isinstance(data["moderator_volunteer_id"], str)
    assert data["status"] in ("PLANNED", "CONFIRMED", "HELD", "CANCELLED")
    assert isinstance(data["eligible_candidate_count"], int)
    assert data["eligible_candidate_count"] >= 0


def assert_forum_question(data: dict):
    _assert_common(data)
    assert isinstance(data["forum_id"], str) and data["forum_id"]
    assert isinstance(data["question_text"], str) and data["question_text"]
    assert data["source"] in ("PUBLIC_SUBMISSION", "MODERATOR_AUTHORED")
    assert data["status"] in ("SUBMITTED", "SELECTED", "REJECTED")


def assert_volunteer(data: dict):
    _assert_common(data)
    assert isinstance(data["volunteer_name"], str) and data["volunteer_name"]
    assert isinstance(data["chapter_code"], str) and data["chapter_code"]
    roles = data["roles"]
    assert isinstance(roles, list) and len(roles) > 0
    assert all(r in ("COORDINATOR", "EDITOR", "REVIEWER", "MODERATOR") for r in roles)
    assert isinstance(data["advocacy_flag"], bool)
    assert data["attestation_status"] in ("CURRENT", "LAPSED")
    assert is_iso8601_timestamp(data.get("attestation_expires_at", ""))
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["substantiated_incident_count"], int)
    assert data["substantiated_incident_count"] >= 0


def assert_policy_incident(data: dict):
    _assert_common(data)
    assert isinstance(data["volunteer_id"], str) and data["volunteer_id"]
    assert data["incident_type"] in (
        "PARTISAN_STATEMENT", "ADVOCACY_ROLE_CONFLICT",
        "MODERATOR_BIAS", "QUESTIONNAIRE_SLANT",
    )
    assert isinstance(data["description"], str)
    assert data["status"] in ("REPORTED", "SUBSTANTIATED", "DISMISSED")
