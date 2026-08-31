"""Injury reporting, the graduated return-to-play protocol, and clearance."""
from test_helpers import (
    ApiErrorId,
    assert_injury_report,
    assert_same_instant,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


def test_a_closed_injury_report_cannot_be_cleared_a_second_time(api, medical_third_headers):
    """PRD §3.6: "A `disposition` of `SEASON_ENDED` is declared from both `REPORTED`
    and `RTP_IN_PROGRESS`, carries no stage or interval requirement whatsoever, moves
    the report to `SEASON_ENDED`, stamps `cleared_by_user_id` and `cleared_at`
    identically, and deliberately leaves every `MEDICALLY_SUSPENDED` case of the
    athlete exactly where it is. `CLEARED` and `SEASON_ENDED` are both terminal."
    PRD §2.6: "The target row's current state admits the requested transition —
    otherwise `ERR_INVALID_STATE` (409) on any transition endpoint that has no more
    specific state error."

    Design: Corner/state_machines/clearing_an_already_cleared_injury_report_is_locked_out
    """
    set_clock("2026-09-10T09:00:00Z")
    school = fx.create_school(name="North High")
    student = fx.create_student(school["id"], full_name="Omar Reid",
                                birth_date="2009-05-14", grade_level=11)
    report = fx.file_injury(student["id"], injury_type="CONCUSSION",
                            injury_note="collision in practice")
    fx.clear_injury(report["id"], disposition="SEASON_ENDED",
                    clearance_note="out for the year")

    response = api.clear_injury_report(
        report["id"], {"disposition": "RETURN_TO_PLAY"}, medical_third_headers
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    stored = fx.read_injury(report["id"])
    assert stored["status"] == "SEASON_ENDED"
    assert stored["cleared_by_user_id"] == "med-002", (
        "the first clearing officer stays recorded"
    )


def test_symptom_recurrence_snaps_the_protocol_back_to_stage_one(api, medical_headers):
    """PRD §3.6: "An advance from `RTP_IN_PROGRESS` with `symptom_recurrence` true
    requires no elapsed interval whatsoever: `rtp_stage` snaps back to 1,
    `recurrence_count` increments by 1, and `last_stage_advanced_at` is re-stamped, so
    the 24-hour inter-stage ladder restarts from there."
    PRD §3.6: "What does *not* restart is the total-duration floor, which is still
    measured from the original `reported_at`."

    Design: Corner/state_machines/symptom_recurrence_resets_the_return_to_play_ladder_to_stage_one
    """
    ctx = fx.setup_injury_at_stage(3)
    assert ctx["report"]["rtp_stage"] == 3

    reset = validate_success(
        api.advance_injury_stage(
            ctx["report"]["id"],
            {"symptom_recurrence": True, "stage_note": "headache returned at stage 3"},
            medical_headers,
        ),
        200,
    )

    assert_injury_report(reset)
    assert reset["rtp_stage"] == 1
    assert reset["recurrence_count"] == 1
    assert reset["status"] == "RTP_IN_PROGRESS"
    assert_same_instant(reset["last_stage_advanced_at"], "2026-09-14T09:00:00Z",
                        "last_stage_advanced_at")
    assert_same_instant(reset["reported_at"], "2026-09-10T09:00:00Z", "reported_at")


def test_the_initial_rest_admits_the_boundary_and_refuses_one_minute_earlier(
    api, medical_headers
):
    """PRD §3.6: "The first advance, taken with `symptom_recurrence` false, moves
    the report `REPORTED → RTP_IN_PROGRESS`, sets `rtp_stage` to 1 and stamps
    `last_stage_advanced_at`, and requires that the clock has reached or passed 48
    hours — two full days of initial rest — after `reported_at`; earlier than that and
    the answer is `ERR_RTP_INTERVAL_NOT_ELAPSED`."
    PRD §3.6: "Each of these interval comparisons admits the boundary exactly: an
    advance at precisely `reported_at` plus 48 hours, or at precisely
    `last_stage_advanced_at` plus 24 hours, is accepted, while one second earlier is
    not."

    Design: Corner/calculations/rtp_initial_rest_admits_at_exactly_forty_eight_hours_and_rejects_one_minute_earlier
    """
    set_clock("2026-09-10T09:00:00Z")
    school = fx.create_school(name="North High")
    student = fx.create_student(school["id"], full_name="Dev Rao",
                                birth_date="2009-05-14", grade_level=11)
    report = fx.file_injury(student["id"], injury_type="CONCUSSION")
    fx.set_clock("2026-09-12T08:59:00Z")

    too_early = api.advance_injury_stage(report["id"], {"symptom_recurrence": False},
                                         medical_headers)

    validate_error(too_early, ApiErrorId.ERR_RTP_INTERVAL_NOT_ELAPSED.value, 409)
    held = fx.read_injury(report["id"])
    assert held["status"] == "REPORTED"
    assert held["rtp_stage"] == 0

    fx.set_clock("2026-09-12T09:00:00Z")
    advanced = validate_success(
        api.advance_injury_stage(report["id"], {"symptom_recurrence": False},
                                 medical_headers),
        200,
    )

    assert advanced["status"] == "RTP_IN_PROGRESS"
    assert advanced["rtp_stage"] == 1
    assert_same_instant(advanced["last_stage_advanced_at"], "2026-09-12T09:00:00Z",
                        "last_stage_advanced_at")


def test_injury_suspends_the_eligible_case_and_full_clearance_restores_it(
    api, medical_alt_headers
):
    """PRD §3.6: "Filing stamps `reported_at` with the logical clock instant and
    `reported_by_user_id` with the filing officer's `X-User-ID`, opens the report at
    `REPORTED` with `rtp_stage` 0 and `recurrence_count` 0, and immediately moves
    every one of that athlete's cases standing at `ELIGIBLE` to
    `MEDICALLY_SUSPENDED`."
    PRD §3.6: "A `disposition` of `RETURN_TO_PLAY` is declared only from
    `RTP_IN_PROGRESS` and demands that `rtp_stage` has reached exactly 5 — anything
    lower, including a report still at `REPORTED` with stage 0, is refused with
    `ERR_RTP_STAGE_INCOMPLETE` — and that the logical clock has reached or passed 144
    hours, six full days, after `reported_at`, failing which the answer is
    `ERR_RTP_INTERVAL_NOT_ELAPSED`."
    PRD §3.6: "On success the report moves to `CLEARED`, `cleared_by_user_id`
    records the clearing officer and `cleared_at` the clock instant, and every case of
    that athlete standing at `MEDICALLY_SUSPENDED` returns to `ELIGIBLE` — but only
    when no other injury report of that same athlete is still standing at `REPORTED`
    or `RTP_IN_PROGRESS`."

    Design: Corner/state_machines/injury_suspends_an_eligible_case_and_full_protocol_clearance_restores_it
    """
    ctx = fx.setup_eligible_case(
        clock="2026-09-10T09:00:00Z",
        season_overrides={"required_officials": 1},
        student_overrides={"full_name": "Quin Adeyemi", "residency_verified": True,
                           "residency_verified_on": "2026-08-10"},
    )
    assert ctx["case"]["status"] == "ELIGIBLE"

    report = fx.file_injury(ctx["student"]["id"], injury_type="CONCUSSION")
    assert fx.read_case(ctx["case"]["id"])["status"] == "MEDICALLY_SUSPENDED"
    for day in ("2026-09-12", "2026-09-13", "2026-09-14", "2026-09-15", "2026-09-16"):
        fx.set_clock(f"{day}T09:00:00Z")
        report = fx.advance_rtp_stage(report["id"])
    assert report["rtp_stage"] == 5

    cleared = validate_success(
        api.clear_injury_report(
            report["id"],
            {"disposition": "RETURN_TO_PLAY",
             "clearance_note": "asymptomatic through stage 5"},
            medical_alt_headers,
        ),
        200,
    )

    assert cleared["status"] == "CLEARED"
    assert cleared["cleared_by_user_id"] == "med-002"
    assert_same_instant(cleared["cleared_at"], "2026-09-16T09:00:00Z", "cleared_at")
    restored = fx.read_case(ctx["case"]["id"])
    assert restored["status"] == "ELIGIBLE"
    assert restored["activated_at"] is not None
