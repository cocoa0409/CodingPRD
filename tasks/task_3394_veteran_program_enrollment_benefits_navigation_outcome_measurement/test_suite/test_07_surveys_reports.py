"""Outcome surveys, wellbeing scoring, clock-sweep windows, and donor reports."""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    validate_error, validate_paginated, validate_success,
)
from test_helpers import factories, fixtures

INTAKE = TEST_USERS["intake_coordinator_headers"]
ANALYST = TEST_USERS["outcome_analyst_headers"]


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_donor_report_itt_vs_completer(api):
    """PRD section 3.8: "Under `ITT` (intent-to-treat), every cohort member
    counts; a missing baseline score is imputed as 50, and a missing exit score
    is imputed as that member's baseline — the actual baseline if submitted,
    otherwise the imputed 50 — which dilutes the measured effect relative to
    completer analysis on identical data."
    PRD section 3.8: "Under `COMPLETER`, only members whose enrollment has both
    a submitted baseline and a submitted exit are counted."
    PRD section 3.8: "Each track's effect is the mean of its counted members'
    deltas, rounded half-up to two decimal places under decimal arithmetic — and
    this per-track rounding happens **before** any weighting"

    Design: Difficulty/dual_variant_calc/donor_report_itt_vs_completer
    """
    fixtures.reset_clock()
    track = fixtures.create_program_track(track_code="MENTAL_HEALTH", capacity=10)
    member1 = fixtures.create_verified_member(full_name="Member One", branch_of_service="NAVY")
    enrollment1 = fixtures.create_active_enrollment(member1["id"], track["id"], (5, 5, 5, 5))
    member2 = fixtures.create_verified_member(full_name="Member Two")
    enrollment2 = fixtures.create_active_enrollment(member2["id"], track["id"], (5, 5, 5, 5))

    fixtures.set_clock("2026-09-02T00:00:00Z")  # opens the BASELINE waves
    baseline1 = fixtures.get_survey_by_wave(enrollment1["id"], "BASELINE")
    fixtures.submit_survey_as_member(baseline1["id"], member1["id"], 3, 3, 2, 3, 3)  # 56
    baseline2 = fixtures.get_survey_by_wave(enrollment2["id"], "BASELINE")
    fixtures.submit_survey_as_member(baseline2["id"], member2["id"], 2, 2, 2, 2, 2)  # 40

    fixtures.set_clock("2026-10-01T00:00:00Z")
    fixtures.complete_enrollment(enrollment1["id"])
    fixtures.complete_enrollment(enrollment2["id"])

    fixtures.set_clock("2026-10-02T00:00:00Z")  # opens the EXIT waves
    exit1 = fixtures.get_survey_by_wave(enrollment1["id"], "EXIT")
    fixtures.submit_survey_as_member(exit1["id"], member1["id"], 5, 4, 4, 3, 4)  # 80

    fixtures.set_clock("2026-11-01T00:00:00Z")  # expires member2's EXIT wave

    report_itt = fixtures.create_donor_report(
        "2026-09-15T00:00:00Z", "2026-10-15T00:00:00Z", "ITT")
    assert report_itt["overall_effect"] == 12.0, "m1 delta +24 plus m2 imputed delta 0 over 2"
    per_track_itt = {row["track_code"]: row for row in report_itt["per_track"]}
    assert per_track_itt["MENTAL_HEALTH"]["cohort_size"] == 2

    report_comp = fixtures.create_donor_report(
        "2026-09-15T00:00:00Z", "2026-10-15T00:00:00Z", "COMPLETER")
    assert report_comp["overall_effect"] == 24.0, "only m1 has both waves submitted"
    per_track_comp = {row["track_code"]: row for row in report_comp["per_track"]}
    assert per_track_comp["MENTAL_HEALTH"]["cohort_size"] == 1

    assert report_itt["overall_effect"] != report_comp["overall_effect"]


def test_survey_window_close_inclusive(api):
    """PRD section 3.8: "Both window bounds — `window_open_at` and
    `window_close_at` — are inclusive for submission."
    PRD section 3.8: "Submission is allowed only while the survey is `OPEN` —
    submitting in any other state is `ERR_INVALID_STATE`"
    PRD section 2.5: "Each `OutcomeSurvey` in `OPEN` whose `window_close_at` is
    strictly before the clock moves to `EXPIRED`."

    Design: Difficulty/boundary_precision_check/survey_window_close_inclusive
    """
    fixtures.reset_clock()
    track = fixtures.create_program_track(track_code="MENTAL_HEALTH", capacity=10)
    member1 = fixtures.create_verified_member(full_name="Early Bird")
    enrollment1 = fixtures.create_active_enrollment(member1["id"], track["id"], (5, 5, 5, 5))
    member2 = fixtures.create_verified_member(full_name="Late Bird", branch_of_service="NAVY")
    enrollment2 = fixtures.create_active_enrollment(member2["id"], track["id"], (5, 5, 5, 5))

    fixtures.set_clock("2026-10-01T00:00:00Z")
    fixtures.complete_enrollment(enrollment1["id"])
    fixtures.complete_enrollment(enrollment2["id"])
    # Both EXIT windows: [2026-10-01T00:00:00Z, 2026-10-31T00:00:00Z]

    fixtures.set_clock("2026-10-31T00:00:00Z")  # exactly window_close_at
    survey1 = fixtures.get_survey_by_wave(enrollment1["id"], "EXIT")
    submitted = fixtures.submit_survey_as_member(
        survey1["id"], member1["id"], 4, 4, 4, 4, 4)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["wellbeing_score"] == 80, "submission at exactly window_close_at succeeds"

    fixtures.set_clock("2026-10-31T00:00:01Z")  # one second past close
    survey2 = fixtures.get_survey_by_wave(enrollment2["id"], "EXIT")
    assert survey2["status"] == "EXPIRED"
    assert survey2["wellbeing_score"] is None

    err_resp = api.submit_survey(
        survey2["id"], factories.survey_submission_payload(4, 4, 4, 4, 4),
        fixtures.make_program_member_headers(member2["id"]))
    validate_error(err_resp, ApiErrorId.ERR_INVALID_STATE)


def test_wellbeing_score_is_sum_times_four(api):
    """PRD section 3.8: "the five item scores are summed and the sum multiplied
    by 4, yielding an integer from 20 to 100."

    Design: Corner/calculations/wellbeing_score_is_sum_times_four
    """
    fixtures.reset_clock()
    track = fixtures.create_program_track(track_code="MENTAL_HEALTH", capacity=5)
    member = fixtures.create_verified_member(full_name="Sum Vet")
    enrollment = fixtures.create_enrollment(member["id"], track["id"])

    fixtures.set_clock("2026-09-02T00:00:00Z")  # opens the BASELINE wave
    survey = fixtures.get_survey_by_wave(enrollment["id"], "BASELINE")
    submitted = fixtures.submit_survey_as_member(survey["id"], member["id"], 3, 1, 5, 2, 4)
    assert submitted["wellbeing_score"] == 60, "(3+1+5+2+4) * 4"


def test_baseline_impute_score_applies_when_baseline_missing(api):
    """PRD section 3.8: "Under `ITT` (intent-to-treat), every cohort member
    counts; a missing baseline score is imputed as 50, and a missing exit score
    is imputed as that member's baseline — the actual baseline if submitted,
    otherwise the imputed 50"

    Design: Corner/calculations/baseline_impute_score_applies_when_baseline_missing
    """
    fixtures.reset_clock()
    track = fixtures.create_program_track(track_code="MENTAL_HEALTH", capacity=5)
    member = fixtures.create_verified_member(full_name="Impute Vet")
    enrollment = fixtures.create_active_enrollment(member["id"], track["id"], (5, 5, 5, 5))

    fixtures.set_clock("2026-10-01T00:00:00Z")  # the never-submitted BASELINE expires
    fixtures.complete_enrollment(enrollment["id"])

    fixtures.set_clock("2026-10-02T00:00:00Z")  # opens the EXIT wave
    exit_survey = fixtures.get_survey_by_wave(enrollment["id"], "EXIT")
    fixtures.submit_survey_as_member(exit_survey["id"], member["id"], 4, 4, 4, 4, 4)  # 80

    report = fixtures.create_donor_report(
        "2026-09-15T00:00:00Z", "2026-10-15T00:00:00Z", "ITT")
    assert report["cohort_size_total"] == 1
    assert report["overall_effect"] == 30.0, "exit 80 minus imputed baseline 50"
    assert report["overall_effect"] != 80.0, "an implementation imputing 0 would diverge"


def test_surveys_filter_by_wave_returns_only_that_wave(api):
    """PRD section 3.8: "The `BASELINE` wave is created at enrollment creation,
    with a window from the enrollment's `created_at` through 14 days later."
    PRD section 3.8: "The `EXIT` wave is created when an enrollment completes,
    with a window from the enrollment's `exit_at` through 30 days later."
    PRD section 3.8: "The `FOLLOWUP_90` wave is created at the same time, with a
    window centered 90 days after exit and a 7-day grace on each side — that is,
    from `exit_at` plus 83 days through `exit_at` plus 97 days."
    PRD section 2.9: "List endpoints accept the filter parameters named against
    them in §4 (for example `status`, `member_id`, `program_track_id`,
    `employer_partner_id`, `community_event_id`, `partner_site_id`, `region`,
    `specialty`, `service_category`, `wave`, or `track_code`) in addition to the
    pagination parameters of §2.3."

    Design: Corner/endpoints/surveys_filter_by_wave_returns_only_that_wave
    """
    fixtures.reset_clock()
    track = fixtures.create_program_track(track_code="MENTAL_HEALTH", capacity=5)
    member = fixtures.create_verified_member(full_name="Waves Vet")
    enrollment = fixtures.create_active_enrollment(member["id"], track["id"], (5, 5, 5, 5))

    fixtures.set_clock("2026-10-01T00:00:00Z")
    fixtures.complete_enrollment(enrollment["id"])

    filtered = fixtures.list_surveys(enrollment["id"], wave="EXIT")
    assert len(filtered) == 1
    assert filtered[0]["wave"] == "EXIT"

    all_surveys = fixtures.list_surveys(enrollment["id"])
    assert len(all_surveys) == 3
    assert {s["wave"] for s in all_surveys} == {"BASELINE", "EXIT", "FOLLOWUP_90"}

    assert _ts(filtered[0]["window_open_at"]) == datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert _ts(filtered[0]["window_close_at"]) == datetime(2026, 10, 31, tzinfo=timezone.utc)
    followup = next(s for s in all_surveys if s["wave"] == "FOLLOWUP_90")
    assert _ts(followup["window_open_at"]) == datetime(2026, 12, 23, tzinfo=timezone.utc)
    assert _ts(followup["window_close_at"]) == datetime(2027, 1, 6, tzinfo=timezone.utc)


def test_external_record_auto_closes_after_end_date(api):
    """PRD section 2.5: "Each `ExternalServiceRecord` in `ACTIVE` whose
    `end_date` is set and strictly before the clock moves to `CLOSED`; once
    closed, the record no longer counts toward any duplication-avoidance check."

    Design: Corner/state_machines/external_record_auto_closes_after_end_date
    """
    fixtures.reset_clock()
    member = fixtures.create_member(full_name="External Vet")
    record = fixtures.create_external_service_record(
        member["id"], service_category="BENEFITS",
        end_date="2026-10-01T00:00:00Z")

    fixtures.set_clock("2026-10-01T00:00:00Z")  # exactly end_date: not strictly before
    rows_exact = fixtures.list_external_service_records(member["id"])
    assert rows_exact[0]["status"] == "ACTIVE"

    fixtures.set_clock("2026-10-01T00:00:01Z")
    rows_after = fixtures.list_external_service_records(member["id"])
    assert rows_after[0]["status"] == "CLOSED"


def test_donor_report_empty_cohort_rejected(api):
    """PRD section 3.8: "If every track's counted cohort is empty, report
    creation is rejected with `ERR_EMPTY_COHORT` (HTTP 422)."

    Design: Corner/errors/donor_report_empty_cohort_rejected
    """
    fixtures.reset_clock()
    resp = api.create_donor_report(
        factories.create_donor_report_payload(
            "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z", "ITT"),
        ANALYST)
    validate_error(resp, ApiErrorId.ERR_EMPTY_COHORT)


def test_report_track_weights_must_sum_to_one(api):
    """PRD section 2.7: "a supplied `track_weights` map sums to exactly 1.0 —
    otherwise `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD section 3.8: "The weights come from the optional `track_weights` map,
    whose values must sum to exactly 1.0 when supplied"

    Design: Corner/errors/report_track_weights_must_sum_to_one
    """
    fixtures.reset_clock()
    resp = api.create_donor_report(
        factories.create_donor_report_payload(
            "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z", "ITT",
            track_weights={"MENTAL_HEALTH": 0.5, "CAREER": 0.4}),
        ANALYST)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert resp.json()["data"]["error_id"] != "ERR_EMPTY_COHORT", (
        "request shape is checked before the cohort aggregate")


def test_error_envelope_shape_on_404(api):
    """PRD section 2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD section 2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error. The `message` provides a human-readable
    explanation of what went wrong."
    PRD section 2.7: "A missing reference yields the matching 404 identifier"

    Design: Corner/errors/error_envelope_shape_on_404
    """
    fixtures.reset_clock()
    resp = api.get_donor_report(NON_EXISTENT_UUID, ANALYST)
    validate_error(resp, ApiErrorId.ERR_REPORT_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_REPORT_NOT_FOUND"
    assert body["data"]["message"], "error data must carry a non-empty message"
    assert body["meta"].get("api_request_id")
    assert body["meta"].get("api_request_timestamp")


def test_survey_submit_unknown_id_returns_survey_not_found(api):
    """PRD section 2.7: "A missing reference yields the matching 404 identifier"

    Design: Corner/entities/survey_submit_unknown_id_returns_survey_not_found
    """
    fixtures.reset_clock()
    resp = api.submit_survey(
        NON_EXISTENT_UUID, factories.survey_submission_payload(), INTAKE)
    validate_error(resp, ApiErrorId.ERR_SURVEY_NOT_FOUND)
