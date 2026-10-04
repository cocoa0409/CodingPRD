"""Reporting extracts: snapshot totals, revision lineage, submission window gate,
escalation priority, and validation-order precedence."""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_reporting_extract,
    create_extract,
    create_student_with_enrollment,
    get_extract,
    get_year_version,
    reset_clock,
    setup_base,
    setup_closed_year_with_enrollment,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_enrollment,
)

TEST_USERS_DISTRICT_ADMIN = TEST_USERS["district_admin_headers"]


def _parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_superseded_extract_rejects_validate_and_records_lineage(
        api, state_reporter_headers):
    """PRD §3.7: "Every prior extract for the same year-and-spec pairing that has not
    been submitted — those standing in `DRAFT`, `VALIDATED`, or `REJECTED` — moves to
    `SUPERSEDED`, while `SUBMITTED` and `ACCEPTED` extracts stand untouched."
    PRD §3.7: "The new extract records, in its `supersedes_extract_id`, the most
    recently created of the extracts it just superseded (null when it supersedes
    nothing)".
    PRD §3.7: "`SUPERSEDED` and `ACCEPTED` extracts accept no further mutation of any
    kind — every attempt is `ERR_EXTRACT_NOT_DRAFT`."

    Design: Corner/state_machines/superseded_extract_rejects_validate_and_records_lineage
    """
    bundle = setup_closed_year_with_enrollment()
    year_id = bundle["year"]["id"]
    spec_id = bundle["spec"]["id"]
    ex1 = create_extract(year_id, spec_id, bundle["year_version"])

    ex2 = create_extract(year_id, spec_id, get_year_version(year_id))
    assert ex2["generation"] == 2, \
        "generation is one plus the count of prior extracts for the pairing"
    assert ex2["supersedes_extract_id"] == ex1["id"]

    ex1_after = get_extract(ex1["id"])
    assert ex1_after["status"] == "SUPERSEDED"

    res = api.validate_extract(ex1["id"], state_reporter_headers)
    validate_error(res, ApiErrorId.ERR_EXTRACT_NOT_DRAFT, expected_status=409)

    data, meta = validate_paginated(
        api.list_reporting_extracts(
            state_reporter_headers, params={"supersedes_extract_id": ex1["id"]}))
    assert meta["total_count"] == 1
    assert [row["id"] for row in data] == [ex2["id"]]


def test_extract_snapshot_includes_withdrawn_enrollments(api, state_reporter_headers):
    """PRD §3.7: "Creation snapshots the year's entire enrollment population — every
    enrollment of the year in any lifecycle, `ACTIVE`, `WITHDRAWN`, or `COMPLETED` —
    and freezes four totals. `record_count` is the size of that population."

    Design: Corner/calculations/extract_snapshot_includes_withdrawn_enrollments
    """
    district, spec, year = setup_base()
    student_a, enrollment_a = create_student_with_enrollment(district["id"], year["id"])
    student_b, enrollment_b = create_student_with_enrollment(
        district["id"], year["id"],
        student_overrides={"student_number": "S002", "first_name": "Bo",
                           "last_name": "Reyes", "birth_date": "2013-09-09T00:00:00Z",
                           "entry_grade_level": "KG"},
        enrollment_overrides={"grade_level": "KG"},
    )
    withdraw_enrollment(enrollment_b["id"], "2026-11-09T00:00:00Z")
    closed_year = validate_success(
        api.close_school_year_for_reporting(year["id"],
                                            TEST_USERS_DISTRICT_ADMIN),
        200)

    extract = create_extract(year["id"], spec["id"], closed_year["version"])
    assert_reporting_extract(extract)
    assert extract["record_count"] == 2, "ACTIVE and WITHDRAWN records are both counted"
    # Full-year ACTIVE record: 1.000 -> 1000 millis; 100-day WITHDRAWN record:
    # 0.556 -> 556 millis.
    assert extract["total_fte_millis"] == 1556


def test_escalation_priority_urgent_at_exactly_48_hours(api, state_reporter_headers):
    """PRD §3.7: "A `REJECTED` verdict recomputes `escalation_priority` from the time
    pressure: the whole hours remaining from the current logical clock until
    `submission_window_closes_at`, truncating partial hours, are compared against the
    escalation window of 48 hours — 48 hours or fewer remaining yields `URGENT`
    (exactly 48 is urgent), anything more yields `STANDARD`."

    Design: Corner/calculations/escalation_priority_urgent_at_exactly_48_hours
    """
    bundle = setup_closed_year_with_enrollment()
    extract = create_extract(
        bundle["year"]["id"], bundle["spec"]["id"], bundle["year_version"])
    validate_success(api.validate_extract(extract["id"], state_reporter_headers), 200)
    # Exactly 48 hours before the 2027-07-15T00:00:00Z close.
    reset_clock("2027-07-13T00:00:00Z")
    validate_success(api.submit_extract(extract["id"], state_reporter_headers), 200)

    resolved = validate_success(
        api.resolve_extract(extract["id"], {"outcome": "REJECTED"},
                            state_reporter_headers),
        200)
    assert resolved["status"] == "REJECTED"
    assert resolved["escalation_priority"] == "URGENT", \
        "exactly 48 hours remaining satisfies the <= 48 urgency rule"


def test_submit_blocked_while_invalid_records(api, state_reporter_headers):
    """PRD §3.7: "`invalid_record_count` counts snapshot records whose
    `membership_days` fall below the spec's `min_membership_days`."
    PRD §3.7: "A `VALIDATED` extract (else `ERR_EXTRACT_NOT_VALIDATED`) may be
    submitted only while the logical clock reads inside the spec's half-open
    submission window ... and only while `invalid_record_count` stands at zero (else
    `ERR_EXTRACT_HAS_ERRORS`)."

    Design: Corner/calculations/submit_blocked_while_invalid_records
    """
    # A 5-day membership (half-open [2026-08-01, 2026-08-06)) is below the spec's
    # min_membership_days of 10.
    bundle = setup_closed_year_with_enrollment(withdraw_exit="2026-08-06T00:00:00Z")
    extract = create_extract(
        bundle["year"]["id"], bundle["spec"]["id"], bundle["year_version"])
    assert extract["invalid_record_count"] == 1

    validated = validate_success(
        api.validate_extract(extract["id"], state_reporter_headers), 200)
    assert validated["invalid_record_count"] == 1, \
        "validation re-derives the count against unchanged data and leaves it at 1"

    # Move the clock inside the submission window — the invalid record still blocks.
    reset_clock("2027-07-01T00:00:00Z")
    res = api.submit_extract(extract["id"], state_reporter_headers)
    validate_error(res, ApiErrorId.ERR_EXTRACT_HAS_ERRORS, expected_status=409)

    after = get_extract(extract["id"])
    assert after["status"] == "VALIDATED", "the blocked submit must not move the extract"


def _setup_two_eighty_day_enrollments(api):
    """Base + two enrollments each withdrawn at exactly 80 membership days; year
    closed. Returns (spec, closed_year)."""
    district, spec, year = setup_base()
    for n in (1, 2):
        student, enrollment = create_student_with_enrollment(
            district["id"], year["id"],
            student_overrides={"student_number": f"S{n:03d}"},
        )
        withdraw_enrollment(enrollment["id"], "2026-10-20T00:00:00Z")
    closed_year = validate_success(
        api.close_school_year_for_reporting(
            year["id"], TEST_USERS_DISTRICT_ADMIN),
        200)
    return spec, closed_year


def test_extract_total_rounds_per_record_then_sums(api, state_reporter_headers):
    """PRD §3.7: "`total_fte_millis` sums, across the population, each record's FTE
    variant — `fte_adm` when the spec's `funding_method` is `ADM`, `fte_count_date`
    when it is `COUNT_DATE` — with each record's value first rounded half-up to three
    decimals and multiplied by one thousand before any summation: two records each
    rounding to 0.444 contribute 888 thousandths in total, never the 889 a
    sum-then-round order could produce, and the per-record order is the required
    one."

    Design: Difficulty/combinatorial_formula/extract_total_rounds_per_record_then_sums
    """
    spec, closed_year = _setup_two_eighty_day_enrollments(api)
    extract = create_extract(closed_year["id"], spec["id"], closed_year["version"])
    # Each 80-day record: round_half_up(80/180, 3) = 0.444 -> 444 millis each.
    assert extract["total_fte_millis"] == 888, \
        "round-per-record then sum: 444 + 444 = 888, not the 889 of sum-then-round"


def test_extract_creation_snapshot_counts_and_generation(api, state_reporter_headers):
    """PRD §3.7: "`record_count` is the size of that population."
    PRD §3.7: "`invalid_record_count` counts snapshot records whose `membership_days`
    fall below the spec's `min_membership_days`."
    PRD §3.7: "The extract's `generation` is one plus the count of prior extracts
    created for the same year-and-spec pairing."
    PRD §3.7: "The new extract begins `DRAFT` with `submitted_at` null and
    `escalation_priority` at `NONE`."

    Design: Difficulty/combinatorial_formula/extract_total_rounds_per_record_then_sums
    """
    spec, closed_year = _setup_two_eighty_day_enrollments(api)
    extract = create_extract(closed_year["id"], spec["id"], closed_year["version"])
    assert extract["record_count"] == 2
    # 80 >= min_membership_days 10 for both records.
    assert extract["invalid_record_count"] == 0
    assert extract["generation"] == 1
    assert extract["status"] == "DRAFT"
    assert extract["submitted_at"] is None
    assert extract["escalation_priority"] == "NONE"


def test_rejected_extract_reopens_for_revision_loop(api, state_reporter_headers):
    """PRD §3.7: "Reopening moves a `VALIDATED` or `REJECTED` extract back to `DRAFT`
    for rework (from anything else, `ERR_EXTRACT_NOT_DRAFT`) and clears
    `escalation_priority` back to `NONE`."
    PRD §3.7: "the whole hours remaining from the current logical clock until
    `submission_window_closes_at`, truncating partial hours, are compared against the
    escalation window of 48 hours — 48 hours or fewer remaining yields `URGENT`
    (exactly 48 is urgent), anything more yields `STANDARD`."

    Design: Difficulty/non_linear_state_machine/extract_rejection_revision_cycle
    """
    bundle = setup_closed_year_with_enrollment()
    extract = create_extract(
        bundle["year"]["id"], bundle["spec"]["id"], bundle["year_version"])
    # 2027-07-01 leaves 336 hours to the 2027-07-15 close — inside the window.
    reset_clock("2027-07-01T00:00:00Z")

    validate_success(api.validate_extract(extract["id"], state_reporter_headers), 200)
    validate_success(api.submit_extract(extract["id"], state_reporter_headers), 200)
    rejected = validate_success(
        api.resolve_extract(extract["id"], {"outcome": "REJECTED"},
                            state_reporter_headers),
        200)
    assert rejected["status"] == "REJECTED"
    assert rejected["escalation_priority"] == "STANDARD", \
        "336 hours remaining is more than the 48-hour escalation window"

    reopened = validate_success(
        api.reopen_extract(extract["id"], state_reporter_headers), 200)
    assert reopened["status"] == "DRAFT"
    assert reopened["escalation_priority"] == "NONE"


def test_reopened_extract_validates_submits_and_is_accepted(api, state_reporter_headers):
    """PRD §3.7: "Resolution records the state authority's verdict: a `SUBMITTED`
    extract (else `ERR_EXTRACT_NOT_SUBMITTED`) moves to `ACCEPTED` or to `REJECTED`
    according to the supplied `outcome`. `ACCEPTED` is terminal."
    PRD §3.7: "Submission stamps `submitted_at` with the current logical clock and
    moves the extract to `SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/extract_rejection_revision_cycle
    """
    bundle = setup_closed_year_with_enrollment()
    extract = create_extract(
        bundle["year"]["id"], bundle["spec"]["id"], bundle["year_version"])
    reset_clock("2027-07-01T00:00:00Z")

    validate_success(api.validate_extract(extract["id"], state_reporter_headers), 200)
    validate_success(api.submit_extract(extract["id"], state_reporter_headers), 200)
    validate_success(
        api.resolve_extract(extract["id"], {"outcome": "REJECTED"},
                            state_reporter_headers), 200)
    validate_success(api.reopen_extract(extract["id"], state_reporter_headers), 200)

    # The revision loop runs the reopened DRAFT through the pipeline a second time.
    validate_success(api.validate_extract(extract["id"], state_reporter_headers), 200)
    submitted = validate_success(
        api.submit_extract(extract["id"], state_reporter_headers), 200)
    assert submitted["status"] == "SUBMITTED"

    accepted = validate_success(
        api.resolve_extract(extract["id"], {"outcome": "ACCEPTED"},
                            state_reporter_headers),
        200)
    assert accepted["status"] == "ACCEPTED"
    assert _parse_instant(accepted["submitted_at"]) == _parse_instant(
        "2027-07-01T00:00:00Z"), "submitted_at stamps the logical clock at submission"


def _setup_draft_extract_with_clock(api, clock_instant):
    """Closed year with one full-year enrollment + DRAFT extract; clock moved to
    `clock_instant`. Returns the extract."""
    bundle = setup_closed_year_with_enrollment()
    extract = create_extract(
        bundle["year"]["id"], bundle["spec"]["id"], bundle["year_version"])
    reset_clock(clock_instant)
    return extract


def test_submit_from_draft_outside_window_reports_state_error(
        api, state_reporter_headers):
    """PRD §2.7: "Every request passes through a fixed sequence of validation stages,
    and the first failing stage determines the error returned — earlier stages mask
    later ones."
    PRD §3.7: "A `VALIDATED` extract (else `ERR_EXTRACT_NOT_VALIDATED`) may be
    submitted only while the logical clock reads inside the spec's half-open
    submission window".

    Design: Difficulty/priority_pair_validation_conflict/submit_state_error_beats_window_error
    """
    # Clock past the window close (2027-07-15); extract still DRAFT: both the stage-5
    # state rule and the stage-7 window rule fail, and the state rule must win.
    extract = _setup_draft_extract_with_clock(api, "2027-08-01T00:00:00Z")
    res = api.submit_extract(extract["id"], state_reporter_headers)
    validate_error(res, ApiErrorId.ERR_EXTRACT_NOT_VALIDATED, expected_status=409)


def test_submit_from_draft_outside_window_is_not_window_error(
        api, state_reporter_headers):
    """PRD §2.7: "Every request passes through a fixed sequence of validation stages,
    and the first failing stage determines the error returned — earlier stages mask
    later ones."
    PRD §3.7: "a reading exactly at the close already failing with
    `ERR_SUBMISSION_WINDOW_CLOSED` — and only while `invalid_record_count` stands at
    zero (else `ERR_EXTRACT_HAS_ERRORS`)."

    Design: Difficulty/priority_pair_validation_conflict/submit_state_error_beats_window_error
    """
    extract = _setup_draft_extract_with_clock(api, "2027-08-01T00:00:00Z")
    res = api.submit_extract(extract["id"], state_reporter_headers)
    assert res.status_code == 409
    error_id = res.json()["data"]["error_id"]
    assert error_id == ApiErrorId.ERR_EXTRACT_NOT_VALIDATED.value
    assert error_id != ApiErrorId.ERR_SUBMISSION_WINDOW_CLOSED.value, \
        "the stage-5 state error masks the stage-7 window error"

    after = get_extract(extract["id"])
    assert after["status"] == "DRAFT", "the rejected submit must not move the extract"
