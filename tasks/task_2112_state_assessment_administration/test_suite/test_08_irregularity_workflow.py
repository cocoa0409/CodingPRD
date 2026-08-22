"""Irregularity reports: the return-for-information cycle, the four
dispositions and the breach accounting that gates a window's release."""
from test_helpers import (
    ApiErrorId,
    TEST_CALENDAR,
    add_proctor,
    create_attendance_payload,
    create_session,
    create_transition_payload,
    file_report,
    make_officer_headers,
    make_proctor_headers,
    move_report_as_officer,
    move_report_as_proctor,
    move_window,
    read_affidavit,
    read_district,
    read_proctor,
    read_registration,
    read_report,
    read_session,
    read_window,
    reconcile_lot,
    register_student,
    set_clock,
    setup_lot_awaiting_reconciliation,
    setup_program,
    setup_program_with_certified_proctor,
    setup_scored_session_with_open_breach,
    setup_staffed_session,
    setup_two_scheduled_sessions_under_review_breach,
    validate_error,
    validate_paginated,
    validate_success,
)


# ─── The return-for-information cycle ─────────────────────────────────────

def test_a_report_may_be_returned_for_information_twice(api):
    """PRD §3.7: "`UNDER_REVIEW → RETURNED_FOR_INFO` sends the report back to
    its filer and increases `return_count` by one. It is available only for
    reports the system did not generate itself — a `system_generated` report has
    no human filer to return it to — and only while `return_count` is still
    below 2."
    PRD §3.7: "The filing proctor closes the loop with
    `RETURNED_FOR_INFO → SUBMITTED`, and review may begin again."

    Design: Difficulty/non_linear_state_machine/irregularity_report_return_for_info_cycle_capped_at_two
    """
    ctx = setup_program_with_certified_proctor(
        district_code="NG-0005", school_code="EH-01", lot_code="LOT-E1",
        seal_start=7000)
    built = setup_staffed_session(
        ctx, room_code="R101", seat_capacity=25, students=[])
    report = file_report(built["session"]["id"], ctx["proctor"]["id"],
                         narrative="Seating chart did not match the roster.")

    move_report_as_proctor(report["id"], "SUBMITTED", ctx["proctor"]["id"])
    move_report_as_officer(report["id"], "UNDER_REVIEW")
    first_return = move_report_as_officer(report["id"], "RETURNED_FOR_INFO",
                                          note="Attach the seat map.")
    assert first_return["status"] == "RETURNED_FOR_INFO"
    assert first_return["return_count"] == 1

    move_report_as_proctor(report["id"], "SUBMITTED", ctx["proctor"]["id"])
    move_report_as_officer(report["id"], "UNDER_REVIEW")
    second_return = move_report_as_officer(
        report["id"], "RETURNED_FOR_INFO",
        note="Attach the booklet serials too.")
    assert second_return["status"] == "RETURNED_FOR_INFO"
    assert second_return["return_count"] == 2


def test_a_third_return_for_information_is_refused(api):
    """PRD §3.7: "It is available only for reports the system did not generate
    itself — a `system_generated` report has no human filer to return it to —
    and only while `return_count` is still below 2. A report that has already
    been returned twice cannot be returned a third time; the attempt is rejected
    with `ERR_RETURN_CYCLE_LIMIT` and the report stays in `UNDER_REVIEW`."

    Design: Difficulty/non_linear_state_machine/irregularity_report_return_for_info_cycle_capped_at_two
    """
    ctx = setup_program_with_certified_proctor(
        district_code="NG-0005", school_code="EH-01", lot_code="LOT-E1",
        seal_start=7000)
    built = setup_staffed_session(
        ctx, room_code="R101", seat_capacity=25, students=[])
    report = file_report(built["session"]["id"], ctx["proctor"]["id"],
                         narrative="Seating chart did not match the roster.")

    for note in ("Attach the seat map.", "Attach the booklet serials too."):
        move_report_as_proctor(report["id"], "SUBMITTED", ctx["proctor"]["id"])
        move_report_as_officer(report["id"], "UNDER_REVIEW")
        move_report_as_officer(report["id"], "RETURNED_FOR_INFO", note=note)
    move_report_as_proctor(report["id"], "SUBMITTED", ctx["proctor"]["id"])
    move_report_as_officer(report["id"], "UNDER_REVIEW")

    response = api.transition_irregularity_report(
        report["id"],
        create_transition_payload("RETURNED_FOR_INFO", note="One more time."),
        make_officer_headers())
    validate_error(response, ApiErrorId.ERR_RETURN_CYCLE_LIMIT.value, 409)

    stuck = read_report(report["id"])
    assert stuck["status"] == "UNDER_REVIEW", "the report stays under review"
    assert stuck["return_count"] == 2


# ─── The BREACH_CONFIRMED cascade ─────────────────────────────────────────

def test_breach_confirmation_revokes_the_affidavit_and_the_proctor(api):
    """PRD §3.7: "A disposition of `BREACH_CONFIRMED` requires that the report
    name a `session_id` and that the named session have a non-null
    `proctor_id`, and it produces the deepest cascade in the system, five hops
    long."
    PRD §3.7: "The `ACTIVE` affidavit for that session's proctor and that
    session's window moves `ACTIVE → REVOKED` with `revoked_reason` set to
    `BREACH_CONFIRMED`."
    PRD §3.7: "The proctor then takes `revoked_at` stamped from the logical
    clock, has `strike_count` increased by one, and has `certification_status`
    re-derived to `REVOKED`."

    Design: Difficulty/transitive_cascade/breach_confirmed_revokes_affidavit_decertifies_proctor_cancels_sessions_withdraws_registrations
    """
    ctx = setup_two_scheduled_sessions_under_review_breach()

    adjudicated = validate_success(api.transition_irregularity_report(
        ctx["report"]["id"],
        create_transition_payload("ADJUDICATED", disposition="BREACH_CONFIRMED",
                                  note="Seal log confirms early access."),
        make_officer_headers()))

    assert adjudicated["status"] == "ADJUDICATED"
    assert adjudicated["disposition"] == "BREACH_CONFIRMED"

    affidavit = read_affidavit(ctx["affidavit"]["id"])
    assert affidavit["status"] == "REVOKED"
    assert affidavit["revoked_reason"] == "BREACH_CONFIRMED"

    proctor = read_proctor(ctx["proctor"]["id"])
    assert proctor["certification_status"] == "REVOKED"
    assert proctor["strike_count"] == 1
    assert proctor["revoked_at"] is not None


def test_breach_confirmation_cancels_scheduled_sessions_and_withdraws_seats(api):
    """PRD §3.7: "Every session anywhere in the program assigned to that proctor
    and still sitting in `SCHEDULED` moves to `CANCELLED`. And every
    registration on those newly cancelled sessions whose `attendance_status` is
    `PENDING` moves to `WITHDRAWN`. Each entity touched at each hop takes its
    own `version` increment."
    PRD §3.7: "A window's `open_breach_count` is the number of reports scoped to
    that window — reached either through the session that owns them or through
    the material lot that raised them — whose `category` is `SECURITY_BREACH`
    and whose `status` is `SUBMITTED`, `UNDER_REVIEW`, or `RETURNED_FOR_INFO`."
    PRD §3.7: "The window's `security_hold` is true exactly when that count is
    greater than zero, and false otherwise."

    Design: Difficulty/transitive_cascade/breach_confirmed_revokes_affidavit_decertifies_proctor_cancels_sessions_withdraws_registrations
    """
    ctx = setup_two_scheduled_sessions_under_review_breach()
    before = read_window(ctx["window"]["id"])
    assert before["open_breach_count"] == 1
    assert before["security_hold"] is True

    validate_success(api.transition_irregularity_report(
        ctx["report"]["id"],
        create_transition_payload("ADJUDICATED", disposition="BREACH_CONFIRMED",
                                  note="Seal log confirms early access."),
        make_officer_headers()))

    assert read_session(ctx["session_a"]["id"])["status"] == "CANCELLED"
    assert read_session(ctx["session_b"]["id"])["status"] == "CANCELLED", (
        "every SCHEDULED session of that proctor is cancelled, in any room")
    for registration in ctx["registrations"]:
        assert read_registration(registration["id"])["attendance_status"] == \
            "WITHDRAWN"

    after = read_window(ctx["window"]["id"])
    assert after["open_breach_count"] == 0, (
        "an adjudicated report is no longer an open breach")
    assert after["security_hold"] is False


# ─── The lot-discrepancy cascade ──────────────────────────────────────────

def test_a_discrepant_lot_raises_a_system_breach_report_and_the_hold(api):
    """PRD §3.5: "Third, the system files an irregularity report of its own
    accord — `system_generated` true, `material_lot_id` set to this lot,
    `session_id` null, `category` `SECURITY_BREACH`, `severity` `HIGH`, and
    `status` `SUBMITTED`, skipping the draft stage entirely."
    PRD §3.5: "Fourth, because that report is an open security breach, the
    governing window's `open_breach_count` is recomputed and its `security_hold`
    is raised."
    PRD §2.3: "Irregularity reports may be narrowed by `session_id`,
    `registration_id`, `reporter_proctor_id`, `material_lot_id`, `status`, and
    `category` — and listing reports is the only way to discover the report that
    a discrepant lot reconciliation raises on the system's own initiative."

    Design: Difficulty/transitive_cascade/lot_discrepancy_raises_system_breach_report_and_freezes_score_release
    """
    ctx = setup_lot_awaiting_reconciliation(
        district_code="NG-0008", school_code="HH-01", lot_code="LOT-H1",
        lot_quantity=10, seal_start=1200, max_concurrent_seats=40,
        open_the_window=True,
        window_overrides={"name": "Fall SCI G3-5", "subject": "SCIENCE",
                          "grade_band": "G3_5", "min_participation_pct": 0.0})

    settled = reconcile_lot(ctx["lot"]["id"], ctx["district"]["id"], 7, 0, 0)
    assert settled["status"] == "DISCREPANT"
    assert settled["missing_count"] == 3
    assert settled["replacement_charge_cents"] == 4688

    reports, meta = validate_paginated(api.list_irregularity_reports(
        make_officer_headers(), params={"material_lot_id": ctx["lot"]["id"]}))
    assert meta["total_count"] == 1
    system_report = reports[0]
    assert system_report["system_generated"] is True
    assert system_report["category"] == "SECURITY_BREACH"
    assert system_report["severity"] == "HIGH"
    assert system_report["status"] == "SUBMITTED"
    assert system_report["session_id"] is None
    assert system_report["material_lot_id"] == ctx["lot"]["id"]

    window = read_window(ctx["window"]["id"])
    assert window["open_breach_count"] == 1
    assert window["security_hold"] is True

    district = read_district(ctx["district"]["id"])
    assert district["replacement_charge_total_cents"] == 4688
    assert district["security_assessment_cents"] == 4688, (
        "a gross below 5000 cents earns no waiver")
    assert district["open_discrepancy_count"] == 1


def test_the_security_hold_from_a_discrepant_lot_blocks_the_release(api):
    """PRD §3.9: "The window's `security_hold` must be false, and an unresolved
    breach is `ERR_SECURITY_HOLD_ACTIVE`."
    PRD §3.8: "The rate is the numerator divided by the denominator, multiplied
    by 100, and rounded half up to one decimal place; if the denominator is 0,
    the rate is exactly 0.0."
    PRD §3.7: "This is the mechanism by which one unresolved breach anywhere in
    a window blocks the release of every score in it, and by which dismissing or
    adjudicating the last open breach clears the block."

    Design: Difficulty/transitive_cascade/lot_discrepancy_raises_system_breach_report_and_freezes_score_release
    """
    ctx = setup_lot_awaiting_reconciliation(
        district_code="NG-0008", school_code="HH-01", lot_code="LOT-H1",
        lot_quantity=10, seal_start=1200, max_concurrent_seats=40,
        open_the_window=True,
        window_overrides={"name": "Fall SCI G3-5", "subject": "SCIENCE",
                          "grade_band": "G3_5", "min_participation_pct": 0.0})
    reconcile_lot(ctx["lot"]["id"], ctx["district"]["id"], 7, 0, 0)

    set_clock(TEST_CALENDAR["AFTER_WINDOW_END"])
    move_window(ctx["window"]["id"], "MAKEUP")
    set_clock(TEST_CALENDAR["AFTER_MAKEUP_END"])
    scoring = move_window(ctx["window"]["id"], "SCORING")
    assert scoring["participation_rate_provisional_pct"] == 0.0, (
        "a zero denominator yields exactly 0.0")

    response = api.transition_test_window(
        ctx["window"]["id"], create_transition_payload("RELEASED"),
        make_officer_headers())
    validate_error(response, ApiErrorId.ERR_SECURITY_HOLD_ACTIVE.value, 422)

    held = read_window(ctx["window"]["id"])
    assert held["status"] == "SCORING"
    assert held["security_hold"] is True


# ─── Corner cases on the report state machine and its roles ───────────────

def test_submitting_an_already_submitted_report_is_refused(api):
    """PRD §3.7: "The filing proctor — and only the proctor whose `X-User-ID`
    equals the report's `reporter_proctor_id` — may move `DRAFT → SUBMITTED` to
    put it in front of the state, or `DRAFT → WITHDRAWN` to abandon it."
    PRD §2.7: "**The target resource's own status** permits the operation.
    Failure: `ERR_SESSION_NOT_ACCEPTING_REGISTRATIONS`,
    `ERR_LOT_NOT_AWAITING_RECONCILIATION`, `ERR_SCORE_NOT_RELEASED`, or
    `ERR_INVALID_STATE_TRANSITION`, each with HTTP 409."
    PRD §2.4: "**`version`** (integer): a server-managed counter that increases
    by exactly one on every mutation of the resource, including recomputations
    of derived fields such as a session's seat pressure or a district's charge
    ledger."

    Design: Corner/state_machines/repeating_report_submission_is_rejected_on_the_second_attempt
    """
    ctx = setup_program_with_certified_proctor(
        district_code="NG-1012", school_code="YH-01",
        lot_code="LOT-Z8", seal_start=2900)
    proctor = ctx["proctor"]
    session = setup_staffed_session(ctx, room_code="R101", seat_capacity=20,
                                    schedule=False)["session"]
    report = file_report(session["id"], proctor["id"],
                         category="STUDENT_MISCONDUCT", severity="MEDIUM",
                         narrative="A phone was visible during the setup period.")
    version_at_draft = report["version"]

    submitted = validate_success(api.transition_irregularity_report(
        report["id"], create_transition_payload("SUBMITTED"),
        make_proctor_headers(proctor["id"])))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["version"] == version_at_draft + 1

    replay = api.transition_irregularity_report(
        report["id"], create_transition_payload("SUBMITTED"),
        make_proctor_headers(proctor["id"]))
    validate_error(replay, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    unchanged = read_report(report["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["version"] == version_at_draft + 1, (
        "the refused repeat must not bump the version")

    window = read_window(ctx["window"]["id"])
    assert window["open_breach_count"] == 0
    assert window["security_hold"] is False


def test_invalidating_a_session_flips_its_scores_but_spares_the_proctor(api):
    """PRD §3.7: "A disposition of `INVALIDATE_SESSION` requires that the report
    name a `session_id`, that the named session's `status` be exactly `CLOSED`,
    and that the window not already be `FINALIZED`. It drives the session
    `CLOSED → INVALIDATED` and, with it, every registration on that session
    whose `score_status` is `NOT_SCORED`, `SCORED`, `RELEASED`, `UNDER_APPEAL`,
    or `CORRECTED` to `INVALIDATED` — `NOT_SCORED → INVALIDATED`,
    `SCORED → INVALIDATED`, `RELEASED → INVALIDATED`,
    `UNDER_APPEAL → INVALIDATED`, and `CORRECTED → INVALIDATED` respectively."
    PRD §3.7: "The four dispositions have disjoint consequences."

    Design: Corner/state_machines/session_invalidation_disposition_cascades_registration_scores
    """
    ctx = setup_scored_session_with_open_breach()

    adjudicated = validate_success(api.transition_irregularity_report(
        ctx["report"]["id"],
        create_transition_payload("ADJUDICATED", disposition="INVALIDATE_SESSION",
                                  note="Whole room compromised."),
        make_officer_headers()))
    assert adjudicated["disposition"] == "INVALIDATE_SESSION"

    assert read_session(ctx["session"]["id"])["status"] == "INVALIDATED"
    for registration in ctx["registrations"]:
        settled = read_registration(registration["id"])
        assert settled["score_status"] == "INVALIDATED"
    first = read_registration(ctx["registrations"][0]["id"])
    assert first["attendance_status"] == "PRESENT", (
        "the attendance axis is untouched by a score invalidation")

    assert read_affidavit(ctx["affidavit"]["id"])["status"] == "ACTIVE", (
        "INVALIDATE_SESSION touches no affidavit")
    proctor = read_proctor(ctx["proctor"]["id"])
    assert proctor["certification_status"] == "CERTIFIED"
    assert proctor["strike_count"] == 0
    assert read_window(ctx["window"]["id"])["security_hold"] is False


def test_report_adjudication_and_attendance_belong_to_different_roles(api):
    """PRD §2.1: "On irregularity-report transitions, a `Proctor` may request
    only `SUBMITTED` or `WITHDRAWN`, and a `StateAssessmentOfficer` may request
    only `UNDER_REVIEW`, `RETURNED_FOR_INFO`, or `ADJUDICATED`."
    PRD §2.1: "Role authorization has two layers. The first layer asks whether
    the caller's role is listed for the endpoint at all."
    PRD §2.1: "A failure at either layer produces `ERR_ROLE_NOT_PERMITTED`."
    PRD §3.6: "Attendance is recorded one registration at a time by the proctor
    running the room, and only while that room is `ACTIVE`; the caller's
    `X-User-ID` must equal the owning session's `proctor_id`."

    Design: Corner/rbac/proctor_cannot_adjudicate_and_officer_cannot_record_attendance
    """
    ctx = setup_program_with_certified_proctor(
        district_code="NG-1039", school_code="ZK-01",
        lot_code="LOT-T2", seal_start=5600)
    proctor = ctx["proctor"]
    built = setup_staffed_session(
        ctx, room_code="R101", seat_capacity=20,
        students=[{"student_state_id": "S00000001", "grade": 10}],
        schedule=False)
    session = built["session"]
    registration = built["registrations"][0]
    report = file_report(session["id"], proctor["id"], category="TECH_FAILURE",
                         severity="LOW",
                         narrative="Projector failed during instructions.")
    move_report_as_proctor(report["id"], "SUBMITTED", proctor["id"])

    proctor_adjudicates = api.transition_irregularity_report(
        report["id"],
        create_transition_payload("ADJUDICATED", disposition="DISMISSED"),
        make_proctor_headers(proctor["id"]))
    validate_error(proctor_adjudicates, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    untouched = read_report(report["id"])
    assert untouched["status"] == "SUBMITTED"
    assert untouched["disposition"] is None

    officer_records_attendance = api.record_attendance(
        registration["id"], create_attendance_payload("PRESENT"),
        make_officer_headers())
    validate_error(officer_records_attendance,
                   ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    assert read_registration(registration["id"])["attendance_status"] == "PENDING"
