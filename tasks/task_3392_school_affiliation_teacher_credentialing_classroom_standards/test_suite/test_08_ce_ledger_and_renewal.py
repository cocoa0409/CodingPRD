"""Continuing-education ledger and credential renewal: event-completion
gating, earned_at anchoring, duplicate suppression, the void compensating
action, the CYCLE-vs-ROLLING divergence, the exact-CE boundary, and the fee
check.
"""

import datetime

import pytest

from test_helpers import (
    REGISTRAR,
    RENEWAL_BASE_FEE_CENTS,
    SOCIETY_ADMIN,
    ApiErrorId,
    create_pd_event,
    create_verified_placement,
    date_of,
    enroll_learner,
    issue_credential,
    make_adult_learner_headers,
    read_credential,
    read_ce_entry,
    record_attendance,
    record_attendance_payload,
    renew_credential,
    renew_credential_payload,
    reset_clock,
    set_clock,
    setup_credentialed_teacher,
    validate_error,
    validate_paginated,
    validate_success,
    void_ce_entry,
)


def _teacher_with_30_ce_hours():
    """Credentialed teacher plus exactly 30 CE hours (18 + 12) earned in
    February 2027 — CYCLE total sits exactly at the edition requirement."""
    teacher = setup_credentialed_teacher()
    event18 = create_pd_event()
    event12 = create_pd_event(
        start_at="2027-02-27T09:00:00Z", end_at="2027-03-01T17:00:00Z", ce_hours=12
    )
    set_clock("2027-03-02T00:00:00Z")
    record_attendance(event18["id"], teacher.credential["id"])
    record_attendance(event12["id"], teacher.credential["id"])
    return teacher


def test_renewal_fee_mismatch_rejected(api):
    """PRD section 3.5: "Fourth, the fee: the expected amount is 8500 cents,
    plus a 5000-cent late fee when the credential is `LAPSED`, and the supplied
    `fee_cents` must equal that expectation exactly, failing with
    `ERR_FEE_MISMATCH` (HTTP 422)."

    Design: Corner/validations/renewal_fee_mismatch_rejected
    """
    reset_clock()
    teacher = _teacher_with_30_ce_hours()
    set_clock("2029-06-01T00:00:00Z")
    rejected = api.renew_credential(
        teacher.credential["id"],
        renew_credential_payload(8000),
        headers=make_adult_learner_headers(teacher.learner["id"]),
    )
    validate_error(rejected, ApiErrorId.ERR_FEE_MISMATCH)
    credential = read_credential(teacher.credential["id"])
    assert credential["renewed_count"] == 0
    assert credential["status"] == "ACTIVE"


def test_pd_attendance_requires_completed_event_and_no_duplicates(api):
    """PRD section 3.5: "Attendance is recorded by a `SocietyAdmin` only on a
    `COMPLETED` event — a `SCHEDULED` one fails with `ERR_INVALID_STATE`
    (HTTP 409)"; each entry's "`earned_at` is set to the event's `end_at` —
    credit is earned when the event completes, not when the posting lands";
    "At most one non-`VOID` entry may exist per credential and event; a second
    posting fails with `ERR_DUPLICATE_ATTENDANCE` (HTTP 409)."

    Design: Corner/cross_cutting_layers/pd_attendance_requires_completed_event_and_no_duplicates
    """
    reset_clock()
    teacher = setup_credentialed_teacher(learner_name="PD Learner")
    event = create_pd_event(title="PD Session")

    set_clock("2027-01-31T12:00:00Z")
    too_early = api.record_event_attendance(
        event["id"],
        record_attendance_payload(teacher.credential["id"]),
        headers=SOCIETY_ADMIN,
    )
    validate_error(too_early, ApiErrorId.ERR_INVALID_STATE)

    set_clock("2027-02-02T00:00:00Z")
    entry = record_attendance(event["id"], teacher.credential["id"])
    earned = datetime.datetime.fromisoformat(entry["earned_at"].replace("Z", "+00:00"))
    expected_end = datetime.datetime.fromisoformat(event["end_at"].replace("Z", "+00:00"))
    assert earned == expected_end, "earned_at is the event's end_at, not the posting time"

    duplicate = api.record_event_attendance(
        event["id"],
        record_attendance_payload(teacher.credential["id"]),
        headers=SOCIETY_ADMIN,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_ATTENDANCE)

    credential = read_credential(teacher.credential["id"])
    assert credential["ce_hours_cycle_credited"] == pytest.approx(18.0)


def _cycle_vs_rolling_setup():
    """30 CE hours earned 2027-02/03, renewal at the 2029-06-01 window opening
    (rebasing cycle_start), then 10 more hours earned 2030-01-10; read at
    2030-01-15."""
    teacher = _teacher_with_30_ce_hours()
    late_event = create_pd_event(
        start_at="2030-01-09T09:00:00Z", end_at="2030-01-10T17:00:00Z", ce_hours=10
    )
    set_clock("2029-06-01T00:00:00Z")
    renew_credential(
        teacher.credential["id"],
        learner_id=teacher.learner["id"],
        fee_cents=RENEWAL_BASE_FEE_CENTS,
    )
    set_clock("2030-01-11T00:00:00Z")
    record_attendance(late_event["id"], teacher.credential["id"])
    set_clock("2030-01-15T00:00:00Z")
    return teacher


def test_ce_cycle_vs_rolling_window_diverge_after_renewal(api):
    """PRD section 3.5: "`ce_hours_cycle_credited` sums `hours` over the
    credential's `ACTIVE` entries whose `earned_at` date falls on or after
    `cycle_start` — the CYCLE variant." PRD section 3.5:
    "`ce_hours_rolling_credited` sums `hours` over `ACTIVE` entries whose
    `earned_at` date falls inside the trailing window of the `ACTIVE` catalog's
    `credential_validity_months` ending today — the ROLLING variant, a
    provisional estimate that ignores cycle boundaries, so prior-cycle hours
    still inside the window can inflate ROLLING above CYCLE."

    Design: Difficulty/dual_variant_calc/credential_ce_cycle_vs_rolling_window
    """
    reset_clock()
    teacher = _cycle_vs_rolling_setup()
    credential = read_credential(teacher.credential["id"], headers=REGISTRAR)
    assert credential["ce_hours_cycle_credited"] == pytest.approx(10.0), (
        "only the 2030-01-10 entry is on/after cycle_start 2029-06-01"
    )
    assert credential["ce_hours_rolling_credited"] == pytest.approx(40.0), (
        "18 + 12 + 10 all earned within the trailing 36 months of 2030-01-15"
    )


def test_renewal_rebase_side_effects(api):
    """PRD section 3.5: "A successful renewal from `ACTIVE` — or a late renewal
    from `LAPSED` inside the grace window — returns the credential to `ACTIVE`,
    sets `cycle_start` to the current logical date, recomputes `expires_at` as
    today plus the `ACTIVE` catalog's `credential_validity_months`, increments
    `renewed_count`, refreshes `issued_at` to now, and rebases
    `ce_hours_cycle_credited` so prior-cycle entries fall out of the CYCLE
    window."

    Design: Difficulty/dual_variant_calc/credential_ce_cycle_vs_rolling_window
    """
    reset_clock()
    teacher = _cycle_vs_rolling_setup()
    credential = read_credential(teacher.credential["id"], headers=REGISTRAR)
    assert credential["status"] == "ACTIVE"
    assert credential["renewed_count"] == 1
    assert credential["cycle_start"] == "2029-06-01"
    assert date_of(credential["expires_at"]) == "2032-06-01"


def _two_learners_at_ce_boundary():
    """Learner A with exactly 30 CE hours (18 + 12) and learner B with 29
    (18 + 11), both credentialed from the same program; clock at the renewal
    window opening 2029-06-01."""
    teacher_a = setup_credentialed_teacher(learner_name="Learner A")
    learner_b = enroll_learner(teacher_a.program["id"], full_name="Learner B")
    create_verified_placement(
        learner_b["id"], teacher_a.program["id"], teacher_a.host.school["id"]
    )
    credential_b = issue_credential(learner_b["id"])
    event18 = create_pd_event(title="CE 18h")
    event12 = create_pd_event(
        title="CE 12h", start_at="2027-02-25T09:00:00Z", end_at="2027-02-26T17:00:00Z", ce_hours=12
    )
    event11 = create_pd_event(
        title="CE 11h", start_at="2027-02-26T09:00:00Z", end_at="2027-02-27T17:00:00Z", ce_hours=11
    )
    set_clock("2027-03-02T00:00:00Z")
    record_attendance(event18["id"], teacher_a.credential["id"])
    record_attendance(event12["id"], teacher_a.credential["id"])
    record_attendance(event18["id"], credential_b["id"])
    record_attendance(event11["id"], credential_b["id"])
    set_clock("2029-06-01T00:00:00Z")
    return teacher_a, learner_b, credential_b


def test_ce_hours_exactly_at_requirement_renews(api):
    """PRD section 3.5: "Third, continuing education: the credential's CYCLE
    hours must meet or exceed the `ACTIVE` catalog's `ce_hours_required` —
    exact equality qualifies — failing with `ERR_INSUFFICIENT_CE_HOURS`
    (HTTP 422)."

    Design: Difficulty/boundary_precision_check/ce_hours_exactly_at_requirement_renews
    """
    reset_clock()
    teacher_a, _, _ = _two_learners_at_ce_boundary()
    renewed = renew_credential(
        teacher_a.credential["id"],
        learner_id=teacher_a.learner["id"],
        fee_cents=RENEWAL_BASE_FEE_CENTS,
    )
    assert renewed["status"] == "ACTIVE", "CYCLE total exactly 30.0 qualifies"
    assert renewed["renewed_count"] == 1
    assert date_of(renewed["expires_at"]) == "2032-06-01"


def test_ce_hours_one_below_requirement_rejected(api):
    """PRD section 3.5: "the credential's CYCLE hours must meet or exceed the
    `ACTIVE` catalog's `ce_hours_required` — exact equality qualifies —
    failing with `ERR_INSUFFICIENT_CE_HOURS` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/ce_hours_exactly_at_requirement_renews
    """
    reset_clock()
    _, learner_b, credential_b = _two_learners_at_ce_boundary()
    rejected = api.renew_credential(
        credential_b["id"],
        renew_credential_payload(RENEWAL_BASE_FEE_CENTS),
        headers=make_adult_learner_headers(learner_b["id"]),
    )
    validate_error(rejected, ApiErrorId.ERR_INSUFFICIENT_CE_HOURS)
    credential = read_credential(credential_b["id"])
    assert credential["renewed_count"] == 0
    assert credential["status"] == "ACTIVE"


def _ledger_at_30_hours():
    """Credentialed teacher with two CE entries (18 + 12) posted at
    2027-03-02; returns (teacher, event12, entry12)."""
    teacher = setup_credentialed_teacher(learner_name="Ledger Learner")
    event18 = create_pd_event(title="CE 18")
    event12 = create_pd_event(
        title="CE 12", start_at="2027-02-27T09:00:00Z", end_at="2027-03-01T17:00:00Z", ce_hours=12
    )
    set_clock("2027-03-02T00:00:00Z")
    record_attendance(event18["id"], teacher.credential["id"])
    entry12 = record_attendance(event12["id"], teacher.credential["id"])
    return teacher, event12, entry12


def test_ce_void_drops_cycle_cache_to_ledger_sum(api):
    """PRD section 3.5: "A `SocietyAdmin` may later void an `ACTIVE` entry,
    moving it to `VOID`; voiding is the ledger's only compensating action, and
    both posting and voiding recompute the credential's cached totals." PRD
    section 3.5: "Voided rows count in neither."

    Design: Difficulty/compensating_invariant/ce_ledger_void_conserves_credential_cache
    """
    reset_clock()
    teacher, _, entry12 = _ledger_at_30_hours()
    credential = read_credential(teacher.credential["id"], headers=REGISTRAR)
    assert credential["ce_hours_cycle_credited"] == pytest.approx(30.0)

    void_ce_entry(entry12["id"])
    credential = read_credential(teacher.credential["id"], headers=REGISTRAR)
    assert credential["ce_hours_cycle_credited"] == pytest.approx(18.0)

    rows, meta = validate_paginated(
        api.list_ce_entries(
            headers=REGISTRAR,
            params={"credential_id": teacher.credential["id"], "status": "ACTIVE"},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["hours"] == pytest.approx(18.0)
    assert read_ce_entry(entry12["id"])["status"] == "VOID", "compensating entry preserved"


def test_ce_reattendance_after_void_restores_cache(api):
    """PRD section 3.5: "At most one non-`VOID` entry may exist per credential
    and event; a second posting fails with `ERR_DUPLICATE_ATTENDANCE`
    (HTTP 409)." — after the void, no non-`VOID` entry remains for the pair,
    so a fresh posting is admitted and the cache returns to the ledger sum.

    Design: Difficulty/compensating_invariant/ce_ledger_void_conserves_credential_cache
    """
    reset_clock()
    teacher, event12, entry12 = _ledger_at_30_hours()
    void_ce_entry(entry12["id"])

    re_posted = record_attendance(event12["id"], teacher.credential["id"])
    assert re_posted["status"] == "ACTIVE"
    credential = read_credential(teacher.credential["id"], headers=REGISTRAR)
    assert credential["ce_hours_cycle_credited"] == pytest.approx(30.0)
