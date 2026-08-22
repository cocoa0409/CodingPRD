"""Participation, release, appeals and the family report distribution pass."""
from test_helpers import (
    ApiErrorId,
    advance_window_to_scoring,
    assert_participation_precision,
    close_out_lot,
    create_appeal_decision_payload,
    create_score_appeal_payload,
    create_session,
    create_transition_payload,
    file_appeal,
    make_district_coordinator_headers,
    make_officer_headers,
    make_school_coordinator_headers,
    read_registration,
    read_window,
    reconcile_lot,
    record_score,
    register_student,
    release_window,
    run_session_to_closed,
    set_clock,
    setup_lot_awaiting_reconciliation,
    setup_participation_dual_variant_window,
    setup_program,
    setup_program_with_certified_proctor,
    setup_released_window_with_scores,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_provisional_participation_counts_who_showed_up_in_live_sessions(api):
    """PRD §3.8: "Its denominator is the count of distinct `student_state_id`
    values across all registrations reachable from the window through their
    session, restricted to registrations whose session `status` is `SCHEDULED`,
    `ACTIVE`, or `CLOSED` and whose `attendance_status` is `PENDING`, `PRESENT`,
    `ABSENT`, or `EXCUSED`. Its numerator is the count of distinct
    `student_state_id` values within that very same restricted set whose
    `attendance_status` is `PRESENT`. The rate is the numerator divided by the
    denominator, multiplied by 100, and rounded half up to one decimal place; if
    the denominator is 0, the rate is exactly 0.0."
    PRD §3.8: "The result is written to `participation_rate_provisional_pct`,
    and the denominator and numerator are recorded as
    `registered_distinct_count` and `present_distinct_count` respectively."

    Design: Difficulty/dual_variant_calc/participation_provisional_vs_final_diverges_on_window
    """
    ctx = setup_participation_dual_variant_window()

    window = read_window(ctx["window"]["id"])
    assert window["participation_rate_provisional_pct"] == 66.7, (
        "two of three live seats were PRESENT: 2/3 x 100 rounds to 66.7")
    assert_participation_precision(window["participation_rate_provisional_pct"])
    assert window["registered_distinct_count"] == 3, (
        "the cancelled session's withdrawn seat is excluded from the provisional set")
    assert window["present_distinct_count"] == 2
    assert window["participation_rate_final_pct"] is None


def test_final_participation_counts_usable_scores_over_every_seat(api):
    """PRD §3.9: "Its denominator is the count of distinct `student_state_id`
    values across registrations whose session `status` is `SCHEDULED`,
    `ACTIVE`, `CLOSED`, `CANCELLED`, or `INVALIDATED` and whose
    `attendance_status` is `PENDING`, `PRESENT`, `ABSENT`, `EXCUSED`, or
    `WITHDRAWN` — every seat the provisional variant dropped is restored here.
    Its numerator is the count of distinct `student_state_id` values within that
    same set whose `score_status` is `FINAL`."
    PRD §3.9: "The order of the finalization side effects is pinned: **first**,
    every registration in the window whose `score_status` is `RELEASED` or
    `CORRECTED` moves to `FINAL`, along `RELEASED → FINAL` and
    `CORRECTED → FINAL` respectively; **then** the final participation rate is
    computed over the resulting state; **then** the window's `status` becomes
    `FINALIZED` and its `version` increments."
    PRD §3.7: "A disposition of `INVALIDATE_REGISTRATION` requires that the
    report actually name a `registration_id`, and that the window it is scoped
    to has not already reached `FINALIZED`. It drives that one registration's
    `score_status` to `INVALIDATED` from whichever of `SCORED`, `RELEASED`,
    `UNDER_APPEAL`, or `CORRECTED` it currently holds — that is,
    `SCORED → INVALIDATED`, `RELEASED → INVALIDATED`,
    `UNDER_APPEAL → INVALIDATED`, or `CORRECTED → INVALIDATED`."

    Design: Difficulty/dual_variant_calc/participation_provisional_vs_final_diverges_on_window
    """
    ctx = setup_participation_dual_variant_window()
    r1, r2, r3, r4 = ctx["registrations"]

    validate_success(api.transition_irregularity_report(
        ctx["report"]["id"],
        create_transition_payload("ADJUDICATED",
                                  disposition="INVALIDATE_REGISTRATION",
                                  note="Timing defect confirmed."),
        make_officer_headers()))

    set_clock("2026-10-06T08:00:00Z")
    finalized = validate_success(api.transition_test_window(
        ctx["window"]["id"], create_transition_payload("FINALIZED"),
        make_officer_headers()))

    assert finalized["status"] == "FINALIZED"
    assert finalized["appeal_window_closes_at"] == "2026-10-06T08:00:00.000Z"
    assert finalized["participation_rate_final_pct"] == 25.0, (
        "one FINAL score against four restored seats: 1/4 x 100")
    assert_participation_precision(finalized["participation_rate_final_pct"])
    assert finalized["registered_distinct_count"] == 4
    assert finalized["present_distinct_count"] == 1
    assert finalized["participation_rate_provisional_pct"] == 66.7, (
        "the two variants report different percentages from the same rows")

    assert read_registration(r1["id"])["score_status"] == "FINAL"
    assert read_registration(r2["id"])["score_status"] == "INVALIDATED"
    assert read_registration(r3["id"])["score_status"] == "NOT_SCORED"
    assert read_registration(r4["id"])["attendance_status"] == "WITHDRAWN"


def test_distribution_run_over_a_window_with_no_seats_returns_three_zeros(api):
    """PRD §3.9: "The pass reports what it did as `distributed_count`,
    `suppressed_count`, and `skipped_count`, alongside the `window_id` it ran
    against, and it increments the `version` of every registration it actually
    touched."
    PRD §3.9: "A run that finds no candidates at all is not an error — it
    returns three zeros with HTTP 200."

    Design: Difficulty/boundary_precision_check/distribution_run_over_empty_candidate_set_returns_zero_counts
    """
    ctx = setup_lot_awaiting_reconciliation(
        district_code="NG-0012", school_code="LH-01", lot_code="LOT-K1",
        lot_quantity=10, seal_start=2100, max_concurrent_seats=40,
        open_the_window=True,
        window_overrides={"name": "Fall SOC G3-5", "subject": "SOCIAL_STUDIES",
                          "grade_band": "G3_5", "appeal_window_days": 10,
                          "min_participation_pct": 0.0})
    reconcile_lot(ctx["lot"]["id"], ctx["district"]["id"], 10, 0, 0)
    advance_window_to_scoring(ctx)
    release_window(ctx)

    counts = validate_success(api.run_report_distribution(
        ctx["window"]["id"], make_officer_headers()))

    assert counts["distributed_count"] == 0
    assert counts["suppressed_count"] == 0
    assert counts["skipped_count"] == 0
    assert counts["window_id"] == ctx["window"]["id"]


def test_a_window_with_no_seats_scores_zero_participation_and_releases(api):
    """PRD §3.8: "The rate is the numerator divided by the denominator,
    multiplied by 100, and rounded half up to one decimal place; if the
    denominator is 0, the rate is exactly 0.0."
    PRD §3.9: "The window's provisional participation must be at least
    `min_participation_pct` — the comparison is inclusive, so a window that
    lands exactly on its floor passes — and a shortfall is
    `ERR_PARTICIPATION_BELOW_MINIMUM`."
    PRD §3.5: "If `missing_count` is 0 **and** `chain_vs_declared_delta` is 0
    **and** the declared broken-seal count is 0, the lot moves
    `RETURNED_PENDING → RECONCILED`, its `replacement_charge_cents` is set to 0,
    and the matter is closed."

    Design: Difficulty/boundary_precision_check/distribution_run_over_empty_candidate_set_returns_zero_counts
    """
    ctx = setup_lot_awaiting_reconciliation(
        district_code="NG-0012", school_code="LH-01", lot_code="LOT-K1",
        lot_quantity=10, seal_start=2100, max_concurrent_seats=40,
        open_the_window=True,
        window_overrides={"name": "Fall SOC G3-5", "subject": "SOCIAL_STUDIES",
                          "grade_band": "G3_5", "appeal_window_days": 10,
                          "min_participation_pct": 0.0})
    lot = reconcile_lot(ctx["lot"]["id"], ctx["district"]["id"], 10, 0, 0)
    assert lot["status"] == "RECONCILED"
    assert lot["replacement_charge_cents"] == 0

    scoring = advance_window_to_scoring(ctx)
    assert scoring["participation_rate_provisional_pct"] == 0.0
    assert scoring["registered_distinct_count"] == 0
    assert scoring["present_distinct_count"] == 0

    released = release_window(ctx)
    assert released["status"] == "RELEASED", (
        "0.0 meets a floor of 0.0 because the comparison is inclusive")


def test_distribution_run_splits_seats_and_a_rerun_only_skips(api):
    """PRD §3.9: "Otherwise, a registration whose `score_status` is `RELEASED`
    or `CORRECTED` is deliverable, and is marked `SUPPRESSED` with
    `report_suppressed_reason` of `MISSING_GUARDIAN_EMAIL` when its
    `guardian_email` is null or empty, or `DELIVERED` with `report_delivered_at`
    stamped from the logical clock when a `guardian_email` is present."
    PRD §3.9: "Otherwise, a registration whose `score_status` is `UNDER_APPEAL`
    is marked `SUPPRESSED` with `report_suppressed_reason` of `UNDER_APPEAL`."
    PRD §3.9: "A registration whose `report_delivery_status` is anything other
    than `NOT_QUEUED` was already handled by an earlier pass and is counted as
    skipped, untouched."

    Design: Corner/calculations/distribution_run_splits_registrations_into_delivered_suppressed_and_skipped
    """
    ctx = setup_released_window_with_scores(
        students=[{"student_state_id": "S00000001", "grade": 10},
                  {"student_state_id": "S00000002", "grade": 10,
                   "guardian_email": "g2@fam.example"},
                  {"student_state_id": "S00000003", "grade": 10,
                   "guardian_email": None}],
        attendance=["PRESENT", "PRESENT", "PRESENT"],
        scores={0: 90, 1: 70, 2: 60},
        district_code="NG-1021", school_code="HK-01", lot_code="LOT-X4",
        seal_start=3800)
    r1, r2, r3 = ctx["registrations"]

    appeal = file_appeal(
        r2["id"], make_school_coordinator_headers(ctx["school"]["id"]),
        reason_code="IRREGULARITY_IMPACT",
        narrative="Fire alarm interrupted the constructed-response section.")
    assert appeal["status"] == "FILED"

    first_run = validate_success(api.run_report_distribution(
        ctx["window"]["id"], make_officer_headers()))
    assert first_run["distributed_count"] == 1
    assert first_run["suppressed_count"] == 2
    assert first_run["skipped_count"] == 0

    delivered = read_registration(r1["id"])
    assert delivered["report_delivery_status"] == "DELIVERED"
    assert delivered["report_delivered_at"] == "2026-09-26T08:00:00.000Z"
    assert delivered["report_suppressed_reason"] is None

    appealed = read_registration(r2["id"])
    assert appealed["report_delivery_status"] == "SUPPRESSED"
    assert appealed["report_suppressed_reason"] == "UNDER_APPEAL"
    assert appealed["score_status"] == "UNDER_APPEAL"

    no_address = read_registration(r3["id"])
    assert no_address["report_delivery_status"] == "SUPPRESSED"
    assert no_address["report_suppressed_reason"] == "MISSING_GUARDIAN_EMAIL"

    second_run = validate_success(api.run_report_distribution(
        ctx["window"]["id"], make_officer_headers()))
    assert second_run["distributed_count"] == 0
    assert second_run["suppressed_count"] == 0
    assert second_run["skipped_count"] == 3

    assert read_window(ctx["window"]["id"])[
        "participation_rate_provisional_pct"] == 100.0


def test_short_participation_blocks_release_and_the_back_edge_extends_makeup(api):
    """PRD §3.9: "The window's provisional participation must be at least
    `min_participation_pct` — the comparison is inclusive, so a window that
    lands exactly on its floor passes — and a shortfall is
    `ERR_PARTICIPATION_BELOW_MINIMUM`."
    PRD §3.8: "**`SCORING → MAKEUP`** is permitted exactly when
    `participation_rate_provisional_pct` is strictly below
    `min_participation_pct`. It returns the `status` to `MAKEUP`, extends
    `makeup_end` in place by 7 days — without that extension the reopened phase
    would already lie in the past and no make-up session could be scheduled
    inside it — clears `participation_rate_provisional_pct` back to null, and
    increments the window's `version`."

    Design: Corner/validations/participation_below_minimum_blocks_release_and_reopens_makeup
    """
    ctx = setup_program_with_certified_proctor(
        district_code="NG-1032", school_code="RB-01", lot_code="LOT-V4",
        seal_start=4800)
    ran = run_session_to_closed(
        ctx,
        students=[{"student_state_id": "S00000001", "grade": 10},
                  {"student_state_id": "S00000002", "grade": 10,
                   "guardian_email": "g2@fam.example"}],
        attendance=["PRESENT", "ABSENT"], checkout_quantity=4)
    close_out_lot(ctx)
    scoring = advance_window_to_scoring(ctx)
    record_score(ran["registrations"][0]["id"], 85)

    assert scoring["participation_rate_provisional_pct"] == 50.0
    assert scoring["min_participation_pct"] == 95.0

    blocked = api.transition_test_window(
        ctx["window"]["id"], create_transition_payload("RELEASED"),
        make_officer_headers())
    validate_error(blocked, ApiErrorId.ERR_PARTICIPATION_BELOW_MINIMUM.value, 422)
    assert read_window(ctx["window"]["id"])["status"] == "SCORING"

    reopened = validate_success(api.transition_test_window(
        ctx["window"]["id"],
        create_transition_payload(
            "MAKEUP", reason="Reopen make-up to lift participation."),
        make_officer_headers()))
    assert reopened["status"] == "MAKEUP"
    assert reopened["makeup_end"] == "2026-10-02T18:00:00.000Z", (
        "the reopened phase is pushed out by seven days")
    assert reopened["participation_rate_provisional_pct"] is None
    assert read_registration(ran["registrations"][0]["id"])["score_status"] == \
        "SCORED"


def test_an_appeal_filed_at_the_closing_instant_is_too_late(api):
    """PRD §3.9: "Three gates apply: the governing window must be `RELEASED`, or
    the filing is `ERR_WINDOW_PHASE_INVALID`; the registration's `score_status`
    must be exactly `RELEASED`, or the filing is `ERR_SCORE_NOT_RELEASED`; and
    the logical clock must be strictly before `appeal_window_closes_at`, since
    an appeal filed at the very instant the window closes is too late and earns
    `ERR_APPEAL_WINDOW_CLOSED`."
    PRD §3.9: "Filing drives the registration `RELEASED → UNDER_APPEAL` and
    increments its `version`."
    PRD §3.9: "Denying moves the appeal `FILED → DENIED`, stamps `decided_at`,
    and returns the registration `UNDER_APPEAL → RELEASED`, exactly where it was
    before the appeal, closing the loop."

    Design: Corner/validations/appeal_filed_after_the_window_closes_is_rejected
    """
    ctx = setup_released_window_with_scores(
        students=[{"student_state_id": "S00000001", "grade": 10}],
        attendance=["PRESENT"], scores={0: 72},
        district_code="NG-1034", school_code="TP-01", lot_code="LOT-V6",
        seal_start=5100)
    registration = ctx["registrations"][0]
    assert ctx["window"]["appeal_window_closes_at"] == "2026-10-06T08:00:00.000Z"

    set_clock("2026-10-06T08:00:00Z")
    too_late = api.create_score_appeal(
        create_score_appeal_payload(
            registration["id"], reason_code="ACCOMMODATION_NOT_PROVIDED",
            narrative="Approved read-aloud was not delivered; filed a moment too late."),
        make_district_coordinator_headers(ctx["district"]["id"]))
    validate_error(too_late, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED.value, 422)

    set_clock("2026-10-06T07:00:00Z")
    appeal = validate_success(api.create_score_appeal(
        create_score_appeal_payload(registration["id"],
                                    reason_code="SCORING_ERROR",
                                    narrative="Filed within the window."),
        make_district_coordinator_headers(ctx["district"]["id"])),
        expected_status=201)
    assert appeal["status"] == "FILED"
    assert read_registration(registration["id"])["score_status"] == "UNDER_APPEAL"

    decided = validate_success(api.decide_score_appeal(
        appeal["id"],
        create_appeal_decision_payload("DENIED",
                                       note="Score confirmed on rescore."),
        make_officer_headers()))
    assert decided["status"] == "DENIED"
    assert decided["decided_at"] == "2026-10-06T07:00:00.000Z"

    restored = read_registration(registration["id"])
    assert restored["score_status"] == "RELEASED"
    assert restored["raw_score"] == 72


def test_appealing_an_unscored_seat_answers_score_not_released(api):
    """PRD §3.9: "Three gates apply: the governing window must be `RELEASED`, or
    the filing is `ERR_WINDOW_PHASE_INVALID`; the registration's `score_status`
    must be exactly `RELEASED`, or the filing is `ERR_SCORE_NOT_RELEASED`; and
    the logical clock must be strictly before `appeal_window_closes_at`, since
    an appeal filed at the very instant the window closes is too late and earns
    `ERR_APPEAL_WINDOW_CLOSED`."
    PRD §2.7: "Checks are evaluated in strictly ascending order and **the first
    check that fails determines both the `error_id` and the HTTP status**; no
    later check may mask an earlier one."
    PRD §2.7: "**The target resource's own status** permits the operation.
    Failure: `ERR_SESSION_NOT_ACCEPTING_REGISTRATIONS`,
    `ERR_LOT_NOT_AWAITING_RECONCILIATION`, `ERR_SCORE_NOT_RELEASED`, or
    `ERR_INVALID_STATE_TRANSITION`, each with HTTP 409."

    Design: Corner/errors/appeal_against_an_unreleased_score_returns_score_not_released
    """
    ctx = setup_program(district_code="NG-1037", school_code="XY-01",
                        lot_code="LOT-U3", seal_start=5400,
                        max_concurrent_seats=40)
    session = create_session(ctx["window"]["id"], ctx["school"]["id"],
                             room_code="R101", seat_capacity=20)
    registration = register_student(session["id"], ctx["school"]["id"],
                                    student_state_id="S00000001")
    assert registration["score_status"] == "NOT_SCORED"

    response = api.create_score_appeal(
        create_score_appeal_payload(
            registration["id"], reason_code="ROSTER_ERROR",
            narrative="Student should not have been rostered."),
        make_school_coordinator_headers(ctx["school"]["id"]))
    validate_error(response, ApiErrorId.ERR_SCORE_NOT_RELEASED.value, 409)

    data, meta = validate_paginated(api.list_score_appeals(
        make_officer_headers(), params={"registration_id": registration["id"]}))
    assert meta["total_count"] == 0
    assert read_registration(registration["id"])["score_status"] == "NOT_SCORED"
