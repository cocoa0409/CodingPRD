"""Entity assertions and domain invariant checkers.

Entity assertions validate the shape of a single resource dict (id format,
timestamp formats, enum membership, field presence). Invariant checkers pin
the PRD's conserved quantities (aid-package balancing, slot conservation).

Response-level wrappers (expect_success / expect_created / expect_error)
add the request URL, payload, and response body to every failure message so
a failing test is diagnosable from its output alone.
"""
from typing import Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_success,
)

from .types import (
    AidPackageStatus,
    AidPolicy,
    AidVariant,
    ApplicationStatus,
    CollegeStatus,
    CyclePhase,
    MatchStatus,
    NeedTier,
    OutcomeStatus,
    PrepProgramStatus,
    PrepProgramType,
    ReferralStatus,
    StudentSource,
    StudentStage,
    VerificationFlag,
    VerificationOutcome,
)


# ---------------------------------------------------------------------------
# Response-level helpers (failure messages carry URL, payload, body)
# ---------------------------------------------------------------------------

def describe_response(response) -> str:
    req = getattr(response, "request", None)
    where = f"{req.method} {req.url}" if req is not None else "<unknown request>"
    return f"URL: {where}\nStatus: {response.status_code}\nBody: {response.text}"


def expect_success(response, expected_status: int = 200, payload=None):
    """validate_success with request context attached to failures."""
    try:
        return validate_success(response, expected_status)
    except AssertionError as exc:
        raise AssertionError(
            f"{exc}\nPayload: {payload!r}\n{describe_response(response)}"
        )


def expect_created(response, payload=None):
    """Resource-creation endpoints answer 201 per the PRD response contract."""
    return expect_success(response, 201, payload=payload)


def expect_error(response, expected_error_id, payload=None):
    """validate_error with request context attached; HTTP status is
    auto-checked from the registered error map."""
    try:
        return validate_error(response, expected_error_id)
    except AssertionError as exc:
        raise AssertionError(
            f"{exc}\nPayload: {payload!r}\n{describe_response(response)}"
        )


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------

def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity}.id must be a valid UUID, got {data.get('id')!r}; data={data!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def _assert_enum(value, enum_cls, field: str, data: dict):
    members = [m.value for m in enum_cls]
    assert value in members, (
        f"{field} must be one of {members}, got {value!r}; data={data!r}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_match_cycle(data: dict):
    _assert_common_fields(data, "MatchCycle")
    assert isinstance(data["name"], str) and data["name"]
    for f in ("app_opens_at", "app_closes_at", "ranking_opens_at", "ranking_closes_at"):
        assert is_iso8601_timestamp(data.get(f, "")), f"MatchCycle.{f} must be ISO 8601"
    _assert_enum(data["phase"], CyclePhase, "MatchCycle.phase", data)
    assert isinstance(data["match_run_completed"], bool)


def assert_partner_college(data: dict):
    _assert_common_fields(data, "PartnerCollege")
    assert isinstance(data["name"], str) and data["name"]
    _assert_enum(data["aid_policy"], AidPolicy, "PartnerCollege.aid_policy", data)
    assert isinstance(data["min_academic_index"], int)
    assert isinstance(data["match_slots"], int) and data["match_slots"] >= 0
    assert isinstance(data["coa_cents"], int) and data["coa_cents"] >= 0
    _assert_enum(data["status"], CollegeStatus, "PartnerCollege.status", data)
    assert isinstance(data["slots_committed"], int) and data["slots_committed"] >= 0
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0


def assert_student(data: dict):
    _assert_common_fields(data, "Student")
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["state_code"], str) and data["state_code"]
    _assert_enum(data["source"], StudentSource, "Student.source", data)
    _assert_enum(data["student_stage"], StudentStage, "Student.student_stage", data)


def assert_counselor(data: dict):
    _assert_common_fields(data, "Counselor")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["school_name"], str) and data["school_name"]
    assert isinstance(data["state_code"], str) and data["state_code"]


def assert_community_partner(data: dict):
    _assert_common_fields(data, "CommunityPartner")
    assert isinstance(data["org_name"], str) and data["org_name"]
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert isinstance(data["contact_email"], str) and "@" in data["contact_email"]


def assert_referral(data: dict):
    _assert_common_fields(data, "Referral")
    assert is_valid_uuid(data.get("student_id", "")), "Referral.student_id must be a UUID"
    assert is_valid_uuid(data.get("cycle_id", "")), "Referral.cycle_id must be a UUID"
    # polymorphic referrer: exactly one of counselor_id / partner_id may be set
    counselor_id = data.get("counselor_id")
    partner_id = data.get("partner_id")
    assert not (counselor_id and partner_id), (
        f"Referral must not set both counselor_id and partner_id; data={data!r}"
    )
    assert isinstance(data.get("note", ""), str)
    _assert_enum(data["status"], ReferralStatus, "Referral.status", data)


def assert_prep_program(data: dict):
    _assert_common_fields(data, "PrepProgram")
    assert is_valid_uuid(data.get("student_id", "")), "PrepProgram.student_id must be a UUID"
    _assert_enum(data["program_type"], PrepProgramType, "PrepProgram.program_type", data)
    assert isinstance(data["cohort_label"], str) and data["cohort_label"]
    assert is_iso8601_timestamp(data.get("starts_on", "")), "starts_on must be ISO 8601"
    assert is_iso8601_timestamp(data.get("ends_on", "")), "ends_on must be ISO 8601"
    _assert_enum(data["status"], PrepProgramStatus, "PrepProgram.status", data)


def assert_application(data: dict):
    _assert_common_fields(data, "Application")
    assert is_valid_uuid(data.get("student_id", "")), "Application.student_id must be a UUID"
    assert is_valid_uuid(data.get("cycle_id", "")), "Application.cycle_id must be a UUID"
    assert data.get("referral_id") is None or is_valid_uuid(data["referral_id"])
    assert isinstance(data["household_income_cents"], int)
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert isinstance(data["self_reported_assets_cents"], int)
    assert isinstance(data["gpa_scaled"], int)
    assert data.get("test_score") is None or isinstance(data["test_score"], int)
    assert isinstance(data.get("essay_text", ""), str)
    _assert_enum(data["status"], ApplicationStatus, "Application.status", data)
    assert data.get("academic_index") is None or isinstance(data["academic_index"], int)
    assert data.get("prep_alum") is None or isinstance(data["prep_alum"], bool)
    if data.get("need_tier") is not None:
        _assert_enum(data["need_tier"], NeedTier, "Application.need_tier", data)
    _assert_enum(data["verification_flag"], VerificationFlag,
                 "Application.verification_flag", data)
    assert data.get("matched_college_id") is None or is_valid_uuid(data["matched_college_id"])
    assert data.get("submitted_at") is None or is_iso8601_timestamp(data["submitted_at"])


def assert_ranking_entry(data: dict):
    """RankingEntry is the exception to the common-fields convention: it
    carries id and created_at only — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "RankingEntry.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "RankingEntry.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, (
        f"RankingEntry must not expose updated_at (never mutated in place); data={data!r}"
    )
    assert "version" not in data, (
        f"RankingEntry must not expose version (never mutated in place); data={data!r}"
    )
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_valid_uuid(data.get("college_id", ""))
    assert isinstance(data["rank_position"], int) and data["rank_position"] >= 1
    assert isinstance(data["list_seq"], int) and data["list_seq"] >= 1


def assert_match(data: dict):
    _assert_common_fields(data, "Match")
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_valid_uuid(data.get("college_id", ""))
    assert is_valid_uuid(data.get("cycle_id", ""))
    assert isinstance(data["rank_position_awarded"], int) and data["rank_position_awarded"] >= 1
    _assert_enum(data["status"], MatchStatus, "Match.status", data)
    assert is_iso8601_timestamp(data.get("matched_at", "")), (
        "Match.matched_at must be ISO 8601"
    )


def assert_aid_package(data: dict):
    _assert_common_fields(data, "AidPackage")
    assert data.get("match_id") is None or is_valid_uuid(data["match_id"])
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_valid_uuid(data.get("college_id", ""))
    for f in ("coa_cents", "efc_cents", "need_cents", "work_study_cents",
              "loan_cents", "grant_cents"):
        assert isinstance(data[f], int), f"AidPackage.{f} must be integer cents"
        assert data[f] >= 0, f"AidPackage.{f} must be >= 0, got {data[f]}"
    _assert_enum(data["aid_variant"], AidVariant, "AidPackage.aid_variant", data)
    assert isinstance(data["guaranteed_full_need"], bool)
    _assert_enum(data["status"], AidPackageStatus, "AidPackage.status", data)


def assert_income_verification(data: dict):
    _assert_common_fields(data, "IncomeVerification")
    assert is_valid_uuid(data.get("application_id", ""))
    counselor_id = data.get("submitted_by_counselor_id")
    partner_id = data.get("submitted_by_partner_id")
    assert not (counselor_id and partner_id), (
        "IncomeVerification must not set both submitted_by slots; "
        f"data={data!r}"
    )
    assert isinstance(data["verified_income_cents"], int)
    assert isinstance(data["verified_assets_cents"], int)
    assert isinstance(data["verified_household_size"], int)
    _assert_enum(data["outcome"], VerificationOutcome, "IncomeVerification.outcome", data)
    assert data.get("decided_by_partner_id") is None or isinstance(
        data["decided_by_partner_id"], str
    )


def assert_outcome_record(data: dict):
    _assert_common_fields(data, "OutcomeRecord")
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_valid_uuid(data.get("college_id", ""))
    assert is_valid_uuid(data.get("cycle_id", ""))
    assert data.get("match_id") is None or is_valid_uuid(data["match_id"])
    _assert_enum(data["status"], OutcomeStatus, "OutcomeRecord.status", data)
    assert isinstance(data["credits_completed"], int) and data["credits_completed"] >= 0
    assert is_iso8601_timestamp(data.get("last_checkpoint_at", "")), (
        "OutcomeRecord.last_checkpoint_at must be ISO 8601"
    )


def assert_outcome_summary(data: dict):
    for f in ("enrolled_count", "on_track_numerator", "on_track_denominator",
              "on_track_rate_bp", "cohort150_numerator", "cohort150_denominator",
              "cohort150_rate_bp"):
        assert isinstance(data.get(f), int), (
            f"OutcomeSummary.{f} must be an integer, got {data.get(f)!r}"
        )
        assert data[f] >= 0, f"OutcomeSummary.{f} must be >= 0"


def assert_run_match_result(data: dict):
    assert isinstance(data.get("matched_count"), int) and data["matched_count"] >= 0
    assert isinstance(data.get("unmatched_count"), int) and data["unmatched_count"] >= 0


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_aid_package_balances(data: dict):
    """The package always balances to the cent:
    work_study + loan + grant + efc == coa_cents."""
    total = (data["work_study_cents"] + data["loan_cents"]
             + data["grant_cents"] + data["efc_cents"])
    assert total == data["coa_cents"], (
        "Aid package does not balance: "
        f"{data['work_study_cents']} + {data['loan_cents']} + "
        f"{data['grant_cents']} + {data['efc_cents']} == {total} != "
        f"coa_cents {data['coa_cents']}; data={data!r}"
    )


def assert_slot_conservation(college: dict):
    """match_slots == slots_committed + free slots; equivalently the committed
    counter never exceeds the declared quota and never goes negative."""
    assert 0 <= college["slots_committed"] <= college["match_slots"], (
        "Slot conservation broken: "
        f"slots_committed {college['slots_committed']} outside "
        f"[0, match_slots {college['match_slots']}]; data={college!r}"
    )
