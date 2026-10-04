"""Entity shape assertions, domain invariants, and PRD calculation oracles.

Shape assertions check structure and vocabulary only (field presence, types,
enum membership, system-field formats) — never business values. Business-value
expectations belong in the tests.

API MANIFEST (frozen for Phase B):
  Shape assertions (each takes the entity dict from `data`):
    assert_candidate(data)
    assert_program_enrollment(data)
    assert_exam_level(data)
    assert_curriculum_cycle(data)
    assert_exam_window(data)
    assert_test_center(data)
    assert_exam_appointment(data)
    assert_exam_attempt(data)
    assert_work_experience_submission(data)
    assert_reference_contact(data)
    assert_misconduct_case(data)
    assert_society(data)
    assert_society_membership(data)
  Domain invariants:
    assert_enrollment_ledger_invariants(data)
      — net_billed == charges - credits_posted exactly; outstanding ==
        max(0, charges - payments - credits_applied); credit_balance covers at
        least credits_posted - credits_applied (overpayments may add); all
        ledger fields are ints (PRD §2.8).
  Calculation oracles (independent reimplementations of the PRD formulas, for
  tests that compute expected values instead of hard-coding them):
    months_between(start_date, end_date) -> int
      — PRD §2.9 whole-calendar-month convention (subtract one when the end
        day-of-month is earlier than the start day-of-month).
    compute_provisional_months(segments) -> int
      — PRD §3.6 cumulative variant: sum months_between over segments with
        qualifying_activity_pct >= 50; overlaps double-counted.
    compute_committee_months(segments) -> int
      — PRD §3.6 contiguous variant: sort qualifying segments by start_date
        (ties: earlier end_date, then array order), merge runs where the next
        start is on or before run_end + 1 day, sum months_between over runs.
    compute_reschedule_fee_cents(days_before_exam, prior_reschedules) -> int
      — PRD §3.4 tiered quote: base 25000, +25000 when days < 14,
        +10000 * min(priors, 2), capped at 60000.
    compute_ce_credit_totals(records, current_date) -> (calendar, rolling)
      — PRD §3.9: calendar-year credits for the clock's year, and trailing-
        365-day credits (completed_on strictly after current date - 365 days).
"""
from datetime import date, datetime, timedelta

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    APPROVED_CALCULATOR_MODELS,
    LATE_THRESHOLD_DAYS,
    LEVEL_CODES_IN_ORDER,
    MIN_QUALIFYING_PCT,
    PER_PRIOR_RESCHEDULE_CENTS,
    PRIOR_CAP_COUNT,
    RESCHEDULE_BASE_CENTS,
    RESCHEDULE_FEE_CAP_CENTS,
    RESCHEDULE_LATE_SURCHARGE_CENTS,
    ROLLING_WINDOW_DAYS,
)


# ---------------------------------------------------------------------------
# Internal shape helpers
# ---------------------------------------------------------------------------
def _assert_common_fields(data: dict, label: str):
    """PRD §2.5: every resource carries id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer"
    )


def _assert_enum_member(value, allowed, field, label):
    assert value in allowed, f"{label}.{field} must be one of {allowed}, got {value!r}"


def _assert_nullable_iso(value, field, label):
    if value is not None:
        assert isinstance(value, str), f"{label}.{field} must be a string when set"


# ---------------------------------------------------------------------------
# Per-entity shape assertions
# ---------------------------------------------------------------------------
def assert_candidate(data: dict):
    _assert_common_fields(data, "Candidate")
    for field in ("email", "full_name", "date_of_birth", "gov_id_number"):
        assert isinstance(data.get(field), str) and data[field], (
            f"Candidate.{field} must be a non-empty string"
        )
    assert isinstance(data.get("charter_awarded"), bool)
    assert isinstance(data.get("conduct_revoked"), bool)
    _assert_enum_member(
        data.get("highest_level_passed_code"),
        list(LEVEL_CODES_IN_ORDER) + [None],
        "highest_level_passed_code",
        "Candidate",
    )
    _assert_nullable_iso(data.get("suspended_until"), "suspended_until", "Candidate")
    _assert_enum_member(
        data.get("conduct_standing"),
        ["GOOD_STANDING", "SUSPENDED", "REVOKED"],
        "conduct_standing",
        "Candidate",
    )
    assert isinstance(data.get("conduct_statements"), list), (
        "Candidate.conduct_statements must be a list"
    )


def assert_program_enrollment(data: dict):
    _assert_common_fields(data, "ProgramEnrollment")
    assert is_valid_uuid(data.get("candidate_id", "")), (
        "ProgramEnrollment.candidate_id must be a UUID"
    )
    _assert_enum_member(
        data.get("pathway"), ["EDUCATION", "WORK_EXPERIENCE"], "pathway", "ProgramEnrollment"
    )
    _assert_enum_member(
        data.get("status"),
        ["PENDING_PAYMENT", "ENROLLED", "CHARTER_AWARDED"],
        "status",
        "ProgramEnrollment",
    )
    ledger_fields = (
        "lifetime_charges_cents",
        "lifetime_payments_cents",
        "lifetime_credits_posted_cents",
        "lifetime_credits_applied_cents",
        "credit_balance_cents",
        "outstanding_balance_cents",
        "net_billed_cents",
    )
    for field in ledger_fields:
        assert isinstance(data.get(field), int), (
            f"ProgramEnrollment.{field} must be an integer (cents)"
        )
    assert isinstance(data.get("curriculum_access_cycle_ids"), list)
    _assert_nullable_iso(data.get("chartered_at"), "chartered_at", "ProgramEnrollment")


def assert_exam_level(data: dict):
    _assert_common_fields(data, "ExamLevel")
    _assert_enum_member(
        data.get("level_code"), list(LEVEL_CODES_IN_ORDER), "level_code", "ExamLevel"
    )
    assert isinstance(data.get("mps_scaled_score"), int)
    assert isinstance(data.get("max_attempts"), int)
    assert isinstance(data.get("early_fee_cents"), int)
    assert isinstance(data.get("standard_fee_cents"), int)


def assert_curriculum_cycle(data: dict):
    _assert_common_fields(data, "CurriculumCycle")
    assert isinstance(data.get("cycle_year"), int)
    for field in ("effective_from", "effective_to", "content_version"):
        assert isinstance(data.get(field), str), f"CurriculumCycle.{field} must be a string"
    _assert_enum_member(
        data.get("status"), ["PUBLISHED", "ARCHIVED"], "status", "CurriculumCycle"
    )


def assert_exam_window(data: dict):
    _assert_common_fields(data, "ExamWindow")
    for field in (
        "window_opens_at",
        "window_closes_at",
        "scheduling_deadline_at",
        "reschedule_deadline_at",
        "early_fee_deadline_at",
    ):
        assert isinstance(data.get(field), str), f"ExamWindow.{field} must be a string"
    _assert_enum_member(
        data.get("status"),
        ["OPEN", "RESULTS_PUBLISHED", "CANCELLED"],
        "status",
        "ExamWindow",
    )


def assert_test_center(data: dict):
    _assert_common_fields(data, "TestCenter")
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("city"), str) and data["city"]
    assert isinstance(data.get("daily_seat_capacity"), int)
    assert data["daily_seat_capacity"] >= 1
    assert isinstance(data.get("blackout_windows"), list)


def assert_exam_appointment(data: dict):
    _assert_common_fields(data, "ExamAppointment")
    for field in ("program_enrollment_id", "exam_window_id", "test_center_id", "candidate_id"):
        assert is_valid_uuid(data.get(field, "")), (
            f"ExamAppointment.{field} must be a UUID"
        )
    assert isinstance(data.get("exam_date"), str)
    _assert_enum_member(
        data.get("calculator_model"),
        list(APPROVED_CALCULATOR_MODELS),
        "calculator_model",
        "ExamAppointment",
    )
    _assert_enum_member(
        data.get("fee_tier"), ["EARLY", "STANDARD"], "fee_tier", "ExamAppointment"
    )
    assert isinstance(data.get("exam_fee_cents"), int)
    assert isinstance(data.get("reschedule_count"), int) and data["reschedule_count"] >= 0
    assert isinstance(data.get("reschedule_fees_total_cents"), int)
    _assert_enum_member(
        data.get("booking_status"),
        ["SCHEDULED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW"],
        "booking_status",
        "ExamAppointment",
    )
    _assert_enum_member(
        data.get("compliance_status"),
        ["CLEAR", "POLICY_FLAGGED", "CONFIRMED_VIOLATION", "CLEARED"],
        "compliance_status",
        "ExamAppointment",
    )


def assert_exam_attempt(data: dict):
    _assert_common_fields(data, "ExamAttempt")
    assert is_valid_uuid(data.get("exam_appointment_id", ""))
    assert is_valid_uuid(data.get("candidate_id", ""))
    _assert_enum_member(
        data.get("exam_level_code"),
        list(LEVEL_CODES_IN_ORDER),
        "exam_level_code",
        "ExamAttempt",
    )
    assert isinstance(data.get("attempt_sequence"), int) and data["attempt_sequence"] >= 1
    if data.get("scaled_score") is not None:
        assert isinstance(data["scaled_score"], int)
        assert 0 <= data["scaled_score"] <= 1000
    _assert_enum_member(
        data.get("result"), ["PASS", "FAIL", None], "result", "ExamAttempt"
    )
    _assert_enum_member(
        data.get("score_status"), ["AWAITING_SCORE", "SCORED"], "score_status", "ExamAttempt"
    )
    _assert_enum_member(
        data.get("validity"),
        ["VALID", "INVALIDATED", "REINSTATED"],
        "validity",
        "ExamAttempt",
    )


def assert_work_experience_submission(data: dict):
    _assert_common_fields(data, "WorkExperienceSubmission")
    assert is_valid_uuid(data.get("candidate_id", ""))
    assert isinstance(data.get("segments"), list)
    for segment in data["segments"]:
        assert_experience_segment_shape(segment)
    for field in ("provisional_months", "committee_months"):
        value = data.get(field)
        if value is not None:
            assert isinstance(value, int), (
                f"WorkExperienceSubmission.{field} must be an integer when set"
            )
    _assert_enum_member(
        data.get("status"),
        ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "RETURNED_FOR_REVISION"],
        "status",
        "WorkExperienceSubmission",
    )
    if data.get("reviewer_user_id") is not None:
        assert isinstance(data["reviewer_user_id"], str)


def assert_experience_segment_shape(segment: dict):
    for field in ("employer_name", "role_title", "start_date", "end_date"):
        assert isinstance(segment.get(field), str) and segment[field], (
            f"segment.{field} must be a non-empty string"
        )
    pct = segment.get("qualifying_activity_pct")
    assert isinstance(pct, (int, float)) and 0 <= pct <= 100
    hours = segment.get("hours")
    assert isinstance(hours, (int, float)) and hours > 0


def assert_reference_contact(data: dict):
    _assert_common_fields(data, "ReferenceContact")
    assert is_valid_uuid(data.get("experience_submission_id", ""))
    assert isinstance(data.get("referee_name"), str) and data["referee_name"]
    assert isinstance(data.get("referee_email"), str) and data["referee_email"]
    _assert_enum_member(
        data.get("status"),
        ["PENDING", "VERIFIED", "DECLINED", "EXPIRED"],
        "status",
        "ReferenceContact",
    )
    assert isinstance(data.get("expires_at"), str)
    _assert_nullable_iso(data.get("verified_at"), "verified_at", "ReferenceContact")


def assert_misconduct_case(data: dict):
    _assert_common_fields(data, "MisconductCase")
    assert is_valid_uuid(data.get("candidate_id", ""))
    if data.get("appointment_id") is not None:
        assert is_valid_uuid(data["appointment_id"])
    _assert_enum_member(
        data.get("origin"),
        ["EXAM_INCIDENT", "CONDUCT_STATEMENT", "EXTERNAL_REPORT"],
        "origin",
        "MisconductCase",
    )
    assert isinstance(data.get("allegation"), str) and data["allegation"]
    _assert_enum_member(
        data.get("status"),
        ["OPENED", "SANCTIONED", "DISMISSED", "APPEALED"],
        "status",
        "MisconductCase",
    )
    _assert_enum_member(
        data.get("sanction_type"),
        ["WARNING", "SUSPENSION_12M", "EXAM_INVALIDATION", "CHARTER_REVOCATION", None],
        "sanction_type",
        "MisconductCase",
    )
    for field in ("investigator_user_id", "adjudicator_user_id", "appeal_reason"):
        if data.get(field) is not None:
            assert isinstance(data[field], str)
    _assert_nullable_iso(data.get("sanctioned_at"), "sanctioned_at", "MisconductCase")


def assert_society(data: dict):
    _assert_common_fields(data, "Society")
    for field in ("society_code", "name", "region"):
        assert isinstance(data.get(field), str) and data[field]
    assert isinstance(data.get("annual_dues_cents"), int) and data["annual_dues_cents"] > 0
    assert isinstance(data.get("ce_credits_required_per_year"), int)


def assert_society_membership(data: dict):
    _assert_common_fields(data, "SocietyMembership")
    assert is_valid_uuid(data.get("candidate_id", ""))
    assert is_valid_uuid(data.get("society_id", ""))
    _assert_enum_member(
        data.get("status"), ["ACTIVE", "TERMINATED"], "status", "SocietyMembership"
    )
    assert isinstance(data.get("paid_through_year"), int)
    assert isinstance(data.get("ce_records"), list)
    for record in data["ce_records"]:
        assert isinstance(record.get("activity_title"), str)
        assert isinstance(record.get("credit_hours"), (int, float))
        assert isinstance(record.get("completed_on"), str)
    for field in ("calendar_year_credits", "rolling_12m_credits"):
        assert isinstance(data.get(field), (int, float)), (
            f"SocietyMembership.{field} must be numeric"
        )
    assert isinstance(data.get("ce_standing_met"), bool)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_enrollment_ledger_invariants(data: dict):
    """PRD §2.8 ledger identities that must hold after every operation.

    - net_billed_cents == lifetime_charges_cents - lifetime_credits_posted_cents
      (the compensating-invariant anchor).
    - outstanding is what is still owed: charges - payments - credits_applied,
      floored at zero (overpayments land in credit_balance instead).
    - credit_balance covers at least the unabsorbed credits
      (credits_posted - credits_applied); overpayments may add to it.
    """
    charges = data["lifetime_charges_cents"]
    payments = data["lifetime_payments_cents"]
    credits_posted = data["lifetime_credits_posted_cents"]
    credits_applied = data["lifetime_credits_applied_cents"]
    credit_balance = data["credit_balance_cents"]
    outstanding = data["outstanding_balance_cents"]
    net_billed = data["net_billed_cents"]

    assert net_billed == charges - credits_posted, (
        f"net_billed_cents {net_billed} != charges {charges} - credits_posted {credits_posted}"
    )
    assert outstanding == max(0, charges - payments - credits_applied), (
        f"outstanding_balance_cents {outstanding} != max(0, {charges} - {payments} - {credits_applied})"
    )
    assert credit_balance >= credits_posted - credits_applied, (
        f"credit_balance_cents {credit_balance} < unabsorbed credits {credits_posted - credits_applied}"
    )
    assert 0 <= credits_applied <= credits_posted


# ---------------------------------------------------------------------------
# Calculation oracles (PRD §2.9 and §3.6)
# ---------------------------------------------------------------------------
def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def months_between(start_date: str, end_date: str) -> int:
    """PRD §2.9 whole-calendar-month convention: difference in calendar years
    times twelve, plus difference in month numbers, minus one when the end
    date's day-of-month is earlier than the start date's day-of-month."""
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months


def compute_provisional_months(segments) -> int:
    """PRD §3.6 cumulative variant: sum months_between over segments whose
    qualifying_activity_pct is at least 50; overlaps are double-counted."""
    return sum(
        months_between(s["start_date"], s["end_date"])
        for s in segments
        if s["qualifying_activity_pct"] >= MIN_QUALIFYING_PCT
    )


def compute_committee_months(segments) -> int:
    """PRD §3.6 contiguous variant: sort qualifying segments by start_date
    (ties broken by earlier end_date, then array order), merge into runs
    wherever the next segment starts on or before one day after the current
    run's end (touching counts as contiguous), then sum the runs' months."""
    qualifying = [
        (index, s)
        for index, s in enumerate(segments)
        if s["qualifying_activity_pct"] >= MIN_QUALIFYING_PCT
    ]
    qualifying.sort(
        key=lambda pair: (
            _parse_date(pair[1]["start_date"]),
            _parse_date(pair[1]["end_date"]),
            pair[0],
        )
    )
    runs = []
    for _, segment in qualifying:
        start = _parse_date(segment["start_date"])
        end = _parse_date(segment["end_date"])
        if runs and start <= runs[-1][1] + timedelta(days=1):
            if end > runs[-1][1]:
                runs[-1] = (runs[-1][0], end)
        else:
            runs.append((start, end))
    return sum(
        months_between(start.isoformat(), end.isoformat()) for start, end in runs
    )


def compute_reschedule_fee_cents(days_before_exam: int, prior_reschedules: int) -> int:
    """PRD §3.4 reschedule fee: base 25,000 cents; +25,000 when the notice
    period is strictly shorter than 14 days; +10,000 per prior reschedule
    counting at most two; capped at 60,000 cents. Never discounted."""
    fee = RESCHEDULE_BASE_CENTS
    if days_before_exam < LATE_THRESHOLD_DAYS:
        fee += RESCHEDULE_LATE_SURCHARGE_CENTS
    fee += PER_PRIOR_RESCHEDULE_CENTS * min(prior_reschedules, PRIOR_CAP_COUNT)
    return min(fee, RESCHEDULE_FEE_CAP_CENTS)


def compute_ce_credit_totals(records, current_date) -> tuple:
    """PRD §3.9: (calendar_year_credits, rolling_12m_credits) for a membership
    observed at `current_date` (ISO YYYY-MM-DD). Calendar variant counts
    records completed within the clock's calendar year; rolling variant counts
    records with completed_on strictly after current date minus 365 days."""
    today = (
        _parse_date(current_date) if isinstance(current_date, str) else current_date
    )
    calendar = sum(
        r["credit_hours"] for r in records if _parse_date(r["completed_on"]).year == today.year
    )
    cutoff = today - timedelta(days=ROLLING_WINDOW_DAYS)
    rolling = sum(
        r["credit_hours"] for r in records if _parse_date(r["completed_on"]) > cutoff
    )
    return calendar, rolling


__all__ = [
    "assert_candidate",
    "assert_program_enrollment",
    "assert_exam_level",
    "assert_curriculum_cycle",
    "assert_exam_window",
    "assert_test_center",
    "assert_exam_appointment",
    "assert_exam_attempt",
    "assert_work_experience_submission",
    "assert_experience_segment_shape",
    "assert_reference_contact",
    "assert_misconduct_case",
    "assert_society",
    "assert_society_membership",
    "assert_enrollment_ledger_invariants",
    "months_between",
    "compute_provisional_months",
    "compute_committee_months",
    "compute_reschedule_fee_cents",
    "compute_ce_credit_totals",
]
