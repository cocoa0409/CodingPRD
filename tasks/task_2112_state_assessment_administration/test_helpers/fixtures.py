"""Composite setup helpers — multi-step PRD workflow preambles.

Every helper drives the public API only, starting from an empty database, and
uses get_success_data() so a broken precondition surfaces as a clear
"Setup step failed" assertion rather than a confusing downstream error.

Identity threading: DistrictTestCoordinator, SchoolTestCoordinator and Proctor
are entity-backed roles (PRD §2.1), so every ownership-gated call below passes
the real District / School / Proctor id through make_*_headers().
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_CALENDAR, TEST_DEFAULTS
from .factories import (
    create_accommodation_coding_payload,
    create_accommodation_decision_payload,
    create_appeal_decision_payload,
    create_attendance_payload,
    create_custody_event_payload,
    create_district_payload,
    create_irregularity_report_payload,
    create_material_lot_payload,
    create_proctor_assignment_payload,
    create_proctor_payload,
    create_reconciliation_payload,
    create_registration_payload,
    create_school_payload,
    create_score_appeal_payload,
    create_score_payload,
    create_security_affidavit_payload,
    create_session_payload,
    create_test_window_payload,
    create_training_completion_payload,
    create_transition_payload,
)
from .test_users import (
    make_district_coordinator_headers,
    make_officer_headers,
    make_proctor_headers,
    make_school_coordinator_headers,
)


# ─── Tier 0: single-step API steps ────────────────────────────────────────

def set_clock(to_iso8601):
    """Move the logical clock. Returns the clock payload."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, make_officer_headers()))


def create_district(**overrides):
    return get_success_data(api_client.create_district(
        create_district_payload(**overrides), make_officer_headers()))


def create_school(district_id, **overrides):
    return get_success_data(api_client.create_school(
        create_school_payload(district_id, **overrides), make_officer_headers()))


def create_window(**overrides):
    return get_success_data(api_client.create_test_window(
        create_test_window_payload(**overrides), make_officer_headers()))


def ship_lot(window_id, district_id, **overrides):
    return get_success_data(api_client.create_material_lot(
        create_material_lot_payload(window_id, district_id, **overrides),
        make_officer_headers()))


def move_window(window_id, to_status, **extra):
    return get_success_data(api_client.transition_test_window(
        window_id, create_transition_payload(to_status, **extra),
        make_officer_headers()))


def read_window(window_id):
    return get_success_data(
        api_client.get_test_window(window_id, make_officer_headers()))


def read_session(session_id):
    return get_success_data(
        api_client.get_session(session_id, make_officer_headers()))


def read_registration(registration_id):
    return get_success_data(
        api_client.get_registration(registration_id, make_officer_headers()))


def read_lot(material_lot_id):
    return get_success_data(
        api_client.get_material_lot(material_lot_id, make_officer_headers()))


def read_district(district_id):
    return get_success_data(
        api_client.get_district(district_id, make_officer_headers()))


def read_proctor(proctor_id):
    return get_success_data(
        api_client.get_proctor(proctor_id, make_officer_headers()))


def read_affidavit(security_affidavit_id):
    return get_success_data(
        api_client.get_security_affidavit(security_affidavit_id,
                                          make_officer_headers()))


def read_report(irregularity_report_id):
    return get_success_data(
        api_client.get_irregularity_report(irregularity_report_id,
                                           make_officer_headers()))


def read_appeal(score_appeal_id):
    return get_success_data(
        api_client.get_score_appeal(score_appeal_id, make_officer_headers()))


def read_custody_event(custody_event_id):
    return get_success_data(
        api_client.get_custody_event(custody_event_id, make_officer_headers()))


def add_proctor(school_id, **overrides):
    return get_success_data(api_client.create_proctor(
        create_proctor_payload(school_id, **overrides),
        make_school_coordinator_headers(school_id)))


def complete_training(proctor_id, school_id, quiz_score_pct=92.0, **overrides):
    return get_success_data(api_client.record_training_completion(
        proctor_id,
        create_training_completion_payload(quiz_score_pct, **overrides),
        make_school_coordinator_headers(school_id)))


def sign_affidavit(proctor_id, window_id, expected_proctor_version=None, **overrides):
    """Sign the window's affidavit, pinning the proctor version last observed."""
    if expected_proctor_version is None:
        expected_proctor_version = read_proctor(proctor_id)["version"]
    return get_success_data(api_client.create_security_affidavit(
        create_security_affidavit_payload(
            proctor_id, window_id, expected_proctor_version, **overrides),
        make_proctor_headers(proctor_id)))


def create_session(window_id, school_id, **overrides):
    return get_success_data(api_client.create_session(
        create_session_payload(window_id, school_id, **overrides),
        make_school_coordinator_headers(school_id)))


def assign_proctor_to_session(session, proctor_id, school_id,
                              expected_session_version=None):
    """Assign a proctor, pinning the session version the caller last observed."""
    if expected_session_version is None:
        expected_session_version = session["version"]
    return get_success_data(api_client.assign_proctor(
        session["id"],
        create_proctor_assignment_payload(proctor_id, expected_session_version),
        make_school_coordinator_headers(school_id)))


def move_session(session_id, to_status, school_id=None, proctor_id=None, **extra):
    """Drive a session transition with the role that owns the requested edge."""
    if to_status in ("SCHEDULED", "CANCELLED"):
        headers = make_school_coordinator_headers(school_id)
    else:
        headers = make_proctor_headers(proctor_id)
    return get_success_data(api_client.transition_session(
        session_id, create_transition_payload(to_status, **extra), headers))


def register_student(session_id, school_id, student_state_id="S00000001",
                     grade=10, **overrides):
    return get_success_data(api_client.create_registration(
        create_registration_payload(session_id, student_state_id, grade, **overrides),
        make_school_coordinator_headers(school_id)))


def code_accommodations(registration_id, codes, school_id):
    return get_success_data(api_client.code_accommodations(
        registration_id, create_accommodation_coding_payload(codes),
        make_school_coordinator_headers(school_id)))


def decide_accommodations(registration_id, decision, district_id, **overrides):
    return get_success_data(api_client.decide_accommodations(
        registration_id,
        create_accommodation_decision_payload(decision, **overrides),
        make_district_coordinator_headers(district_id)))


def record_attendance(registration_id, attendance_status, proctor_id):
    return get_success_data(api_client.record_attendance(
        registration_id, create_attendance_payload(attendance_status),
        make_proctor_headers(proctor_id)))


def record_score(registration_id, raw_score):
    return get_success_data(api_client.record_score(
        registration_id, create_score_payload(raw_score), make_officer_headers()))


# ─── Tier 0b: chain-of-custody steps ──────────────────────────────────────

def receipt(lot_id, district_id, quantity, **overrides):
    return get_success_data(api_client.create_custody_event(
        lot_id, create_custody_event_payload("RECEIPT", quantity, **overrides),
        make_district_coordinator_headers(district_id)))


def transfer_to_school(lot_id, school_id, quantity, **overrides):
    return get_success_data(api_client.create_custody_event(
        lot_id,
        create_custody_event_payload("TRANSFER_TO_SCHOOL", quantity, **overrides),
        make_school_coordinator_headers(school_id)))


def session_checkout(lot_id, proctor_id, session_id, quantity, **overrides):
    return get_success_data(api_client.create_custody_event(
        lot_id,
        create_custody_event_payload("SESSION_CHECKOUT", quantity,
                                     session_id=session_id, **overrides),
        make_proctor_headers(proctor_id)))


def session_checkin(lot_id, proctor_id, session_id, quantity, **overrides):
    return get_success_data(api_client.create_custody_event(
        lot_id,
        create_custody_event_payload("SESSION_CHECKIN", quantity,
                                     session_id=session_id, **overrides),
        make_proctor_headers(proctor_id)))


def return_to_district(lot_id, school_id, quantity, **overrides):
    return get_success_data(api_client.create_custody_event(
        lot_id,
        create_custody_event_payload("RETURN_TO_DISTRICT", quantity, **overrides),
        make_school_coordinator_headers(school_id)))


def reconcile_lot(lot_id, district_id, declared_returned_count,
                  declared_destroyed_count=0, broken_seal_count=0):
    return get_success_data(api_client.reconcile_material_lot(
        lot_id,
        create_reconciliation_payload(declared_returned_count,
                                      declared_destroyed_count, broken_seal_count),
        make_district_coordinator_headers(district_id)))


# ─── Tier 0c: irregularity and appeal steps ───────────────────────────────

def file_report(session_id, proctor_id, **overrides):
    return get_success_data(api_client.create_irregularity_report(
        create_irregularity_report_payload(session_id, **overrides),
        make_proctor_headers(proctor_id)))


def move_report_as_proctor(report_id, to_status, proctor_id, **extra):
    return get_success_data(api_client.transition_irregularity_report(
        report_id, create_transition_payload(to_status, **extra),
        make_proctor_headers(proctor_id)))


def move_report_as_officer(report_id, to_status, **extra):
    return get_success_data(api_client.transition_irregularity_report(
        report_id, create_transition_payload(to_status, **extra),
        make_officer_headers()))


def find_system_report_for_lot(lot_id):
    """The system-raised breach report is only discoverable through the list."""
    data, meta = _paginated(api_client.list_irregularity_reports(
        make_officer_headers(), params={"material_lot_id": lot_id}))
    assert data, f"Setup step failed: no system report found for lot {lot_id}"
    return data[0], meta


def _paginated(response):
    if not (200 <= response.status_code < 300):
        raise AssertionError(
            f"Setup step failed with HTTP {response.status_code}: {response.text}")
    body = response.json()
    return body["data"], body["meta"]


def file_appeal(registration_id, headers, **overrides):
    return get_success_data(api_client.create_score_appeal(
        create_score_appeal_payload(registration_id, **overrides), headers))


def decide_appeal(appeal_id, decision, **overrides):
    return get_success_data(api_client.decide_score_appeal(
        appeal_id, create_appeal_decision_payload(decision, **overrides),
        make_officer_headers()))


# ─── Tier 1: the program skeleton ─────────────────────────────────────────

def setup_program(district_code="NG-0001", school_code="AH-01",
                  lot_code="LOT-A1", lot_quantity=None, seal_start=3000,
                  max_concurrent_seats=None, open_the_window=True,
                  clock=None, window_overrides=None, ship_a_lot=True):
    """District + school + window (+ lot), optionally opened.

    Returns {"district", "school", "window", "lot"}. `lot` is None when
    ship_a_lot is False.
    """
    set_clock(clock or TEST_CALENDAR["CLOCK_SETUP"])
    district = create_district(district_code=district_code)
    school = create_school(
        district["id"], school_code=school_code,
        max_concurrent_seats=(max_concurrent_seats
                              or TEST_DEFAULTS["SCHOOL_MAX_SEATS"]))
    window = create_window(**(window_overrides or {}))
    lot = None
    if ship_a_lot:
        lot = ship_lot(window["id"], district["id"], lot_code=lot_code,
                       quantity_shipped=(lot_quantity
                                         or TEST_DEFAULTS["LOT_QUANTITY"]),
                       seal_range_start=seal_start)
    if open_the_window:
        window = move_window(window["id"], "OPEN")
    return {"district": district, "school": school, "window": window, "lot": lot}


def setup_program_with_certified_proctor(full_name="Ada Proctor",
                                         email="ada@ng.gov",
                                         quiz_score_pct=92.0, **program_kwargs):
    """Program skeleton plus one trained proctor holding an ACTIVE affidavit.

    Returns the setup_program dict extended with "proctor" and "affidavit".
    """
    ctx = setup_program(**program_kwargs)
    proctor = add_proctor(ctx["school"]["id"], full_name=full_name, email=email)
    proctor = complete_training(proctor["id"], ctx["school"]["id"], quiz_score_pct)
    affidavit = sign_affidavit(proctor["id"], ctx["window"]["id"],
                               expected_proctor_version=proctor["version"])
    ctx["proctor"] = read_proctor(proctor["id"])
    ctx["affidavit"] = affidavit
    return ctx


def add_certified_proctor(ctx, full_name="Ben Proctor", email="ben@ng.gov",
                          quiz_score_pct=88.0):
    """Add a second trained, affidavit-holding proctor to an existing program."""
    proctor = add_proctor(ctx["school"]["id"], full_name=full_name, email=email)
    proctor = complete_training(proctor["id"], ctx["school"]["id"], quiz_score_pct)
    affidavit = sign_affidavit(proctor["id"], ctx["window"]["id"],
                               expected_proctor_version=proctor["version"])
    return read_proctor(proctor["id"]), affidavit


# ─── Tier 2: sessions with rosters ────────────────────────────────────────

def setup_staffed_session(ctx, room_code="R101", seat_capacity=None,
                          students=(), session_overrides=None,
                          proctor=None, schedule=True):
    """Create a session, assign the program's proctor, seat students, schedule.

    `students` is a sequence of dicts forwarded to register_student()
    (e.g. {"student_state_id": "S00000001", "grade": 10}).
    Returns {"session", "registrations"}.
    """
    proctor = proctor or ctx["proctor"]
    overrides = dict(session_overrides or {})
    overrides.setdefault("room_code", room_code)
    if seat_capacity is not None:
        overrides["seat_capacity"] = seat_capacity
    session = create_session(ctx["window"]["id"], ctx["school"]["id"], **overrides)
    session = assign_proctor_to_session(session, proctor["id"], ctx["school"]["id"])
    registrations = [
        register_student(session["id"], ctx["school"]["id"], **student)
        for student in students
    ]
    if schedule:
        session = move_session(session["id"], "SCHEDULED",
                               school_id=ctx["school"]["id"])
    return {"session": session, "registrations": registrations}


def deliver_lot_to_school(ctx, quantity=None):
    """RECEIPT + TRANSFER_TO_SCHOOL for the program's lot."""
    quantity = quantity or ctx["lot"]["quantity_shipped"]
    receipt(ctx["lot"]["id"], ctx["district"]["id"], quantity)
    transfer_to_school(ctx["lot"]["id"], ctx["school"]["id"], quantity)
    return read_lot(ctx["lot"]["id"])


def open_the_room(ctx, session, checkout_quantity, proctor=None,
                  clock=None):
    """Check booklets out, move the clock to the start instant, go ACTIVE."""
    proctor = proctor or ctx["proctor"]
    session_checkout(ctx["lot"]["id"], proctor["id"], session["id"],
                     checkout_quantity)
    set_clock(clock or session["scheduled_start"])
    return move_session(session["id"], "ACTIVE", proctor_id=proctor["id"])


def close_the_room(ctx, session, checkin_quantity, proctor=None):
    """Check every outstanding booklet back in and close the session."""
    proctor = proctor or ctx["proctor"]
    session_checkin(ctx["lot"]["id"], proctor["id"], session["id"], checkin_quantity)
    return move_session(session["id"], "CLOSED", proctor_id=proctor["id"])


# ─── Tier 3: full session lifecycle ───────────────────────────────────────

def run_session_to_closed(ctx, students, attendance, room_code="R101",
                          seat_capacity=None, checkout_quantity=None,
                          proctor=None, session_overrides=None,
                          deliver_lot=True):
    """Deliver booklets, run one session end to end and close it.

    `students` is a sequence of register_student() kwargs; `attendance` is the
    matching sequence of PRESENT / ABSENT / EXCUSED values.
    Returns {"session", "registrations"} with both re-read after the close.
    """
    if deliver_lot:
        deliver_lot_to_school(ctx)
    built = setup_staffed_session(ctx, room_code=room_code,
                                  seat_capacity=seat_capacity, students=students,
                                  session_overrides=session_overrides,
                                  proctor=proctor)
    session, registrations = built["session"], built["registrations"]
    quantity = checkout_quantity if checkout_quantity is not None else len(students)
    session = open_the_room(ctx, session, quantity, proctor=proctor)
    actor = (proctor or ctx["proctor"])["id"]
    for registration, status in zip(registrations, attendance):
        record_attendance(registration["id"], status, actor)
    session = close_the_room(ctx, session, quantity, proctor=proctor)
    return {"session": session,
            "registrations": [read_registration(r["id"]) for r in registrations]}


def close_out_lot(ctx, declared_returned_count=None, declared_destroyed_count=0,
                  broken_seal_count=0, return_quantity=None):
    """Return every booklet to the district and reconcile the lot."""
    lot = read_lot(ctx["lot"]["id"])
    quantity = return_quantity if return_quantity is not None \
        else lot["quantity_at_school"]
    if quantity:
        return_to_district(lot["id"], ctx["school"]["id"], quantity)
    declared = (declared_returned_count if declared_returned_count is not None
                else lot["quantity_shipped"])
    return reconcile_lot(lot["id"], ctx["district"]["id"], declared,
                         declared_destroyed_count, broken_seal_count)


# ─── Tier 4: window phase progression ─────────────────────────────────────

def advance_window_to_scoring(ctx, after_window_end=None, after_makeup_end=None):
    """OPEN -> MAKEUP -> SCORING, moving the clock past each gate."""
    set_clock(after_window_end or TEST_CALENDAR["AFTER_WINDOW_END"])
    move_window(ctx["window"]["id"], "MAKEUP")
    set_clock(after_makeup_end or TEST_CALENDAR["AFTER_MAKEUP_END"])
    return move_window(ctx["window"]["id"], "SCORING")


def advance_window_to_makeup(ctx, after_window_end=None):
    """OPEN -> MAKEUP only, for fixtures that then build make-up sessions."""
    set_clock(after_window_end or TEST_CALENDAR["AFTER_WINDOW_END"])
    return move_window(ctx["window"]["id"], "MAKEUP")


def release_window(ctx):
    return move_window(ctx["window"]["id"], "RELEASED")


def finalize_window(ctx, clock=None):
    if clock:
        set_clock(clock)
    return move_window(ctx["window"]["id"], "FINALIZED")


# ─── Tier 5: end-to-end scenario shortcuts ────────────────────────────────

def setup_released_window_with_scores(students, attendance, scores,
                                      window_overrides=None, **program_kwargs):
    """One closed session, a clean lot, scores recorded and the window RELEASED.

    `scores` maps the zero-based registration index to the raw score to record.
    Returns the program context extended with "session" and "registrations".
    """
    overrides = {"min_participation_pct": 50.0, "appeal_window_days": 10}
    overrides.update(window_overrides or {})
    ctx = setup_program_with_certified_proctor(window_overrides=overrides,
                                               **program_kwargs)
    ran = run_session_to_closed(ctx, students, attendance)
    close_out_lot(ctx)
    advance_window_to_scoring(ctx)
    for index, raw_score in scores.items():
        record_score(ran["registrations"][index]["id"], raw_score)
    ctx["window"] = release_window(ctx)
    ctx["session"] = read_session(ran["session"]["id"])
    ctx["registrations"] = [read_registration(r["id"]) for r in ran["registrations"]]
    return ctx


def setup_lot_awaiting_reconciliation(lot_quantity=10, **program_kwargs):
    """A lot received, transferred to the school and returned in full.

    Returns the program context; the lot sits in RETURNED_PENDING.
    """
    program_kwargs.setdefault("open_the_window", False)
    ctx = setup_program(lot_quantity=lot_quantity, **program_kwargs)
    deliver_lot_to_school(ctx)
    return_to_district(ctx["lot"]["id"], ctx["school"]["id"], lot_quantity)
    ctx["lot"] = read_lot(ctx["lot"]["id"])
    return ctx


def setup_report_under_review(ctx, session_id, proctor_id, category="ADMIN_ERROR",
                              severity="MEDIUM", narrative=None,
                              registration_id=None):
    """File a report and walk it DRAFT -> SUBMITTED -> UNDER_REVIEW."""
    extras = {"category": category, "severity": severity}
    if narrative:
        extras["narrative"] = narrative
    if registration_id:
        extras["registration_id"] = registration_id
    report = file_report(session_id, proctor_id, **extras)
    move_report_as_proctor(report["id"], "SUBMITTED", proctor_id)
    return move_report_as_officer(report["id"], "UNDER_REVIEW")


# ─── Tier 5b: named multi-entity scenarios ────────────────────────────────

def setup_two_lots_awaiting_reconciliation(lot_quantity=10, **program_kwargs):
    """One district holding two lots, both received, distributed and returned.

    Returns the program context with "lot_one" and "lot_two", both sitting in
    RETURNED_PENDING.
    """
    program_kwargs.setdefault("open_the_window", False)
    ctx = setup_program(lot_code="LOT-D1", lot_quantity=lot_quantity,
                        seal_start=6000, **program_kwargs)
    lot_two = ship_lot(ctx["window"]["id"], ctx["district"]["id"],
                       lot_code="LOT-D2", quantity_shipped=lot_quantity,
                       seal_range_start=6100)
    for lot in (ctx["lot"], lot_two):
        receipt(lot["id"], ctx["district"]["id"], lot_quantity)
        transfer_to_school(lot["id"], ctx["school"]["id"], lot_quantity)
        return_to_district(lot["id"], ctx["school"]["id"], lot_quantity)
    ctx["lot_one"] = read_lot(ctx["lot"]["id"])
    ctx["lot_two"] = read_lot(lot_two["id"])
    return ctx


def setup_seat_pressure_session(seat_capacity=10, max_concurrent_seats=60):
    """A DRAFT session holding three seats, two of them separate-setting.

    seats_consumed is 7 and effective_seat_capacity is 10, one separate-setting
    coding short of the proctor-span penalty.
    Returns the program context with "session" and "registrations".
    """
    ctx = setup_program(max_concurrent_seats=max_concurrent_seats)
    session = create_session(ctx["window"]["id"], ctx["school"]["id"],
                             room_code="R101", seat_capacity=seat_capacity)
    registrations = []
    for index, student in enumerate(("S00000001", "S00000002", "S00000003")):
        registration = register_student(session["id"], ctx["school"]["id"],
                                        student_state_id=student, grade=11)
        if index < 2:
            registration = code_accommodations(registration["id"], ["SMALL_GROUP"],
                                               ctx["school"]["id"])
        registrations.append(registration)
    ctx["session"] = read_session(session["id"])
    ctx["registrations"] = registrations
    return ctx


def setup_active_session_at_capacity():
    """An ACTIVE session whose single declared seat is already taken.

    Returns the program context with "session" and "registrations".
    """
    ctx = setup_program_with_certified_proctor()
    deliver_lot_to_school(ctx)
    built = setup_staffed_session(
        ctx, room_code="R101", seat_capacity=1,
        students=[{"student_state_id": "S00000001", "grade": 10}])
    session = open_the_room(ctx, built["session"], 4)
    ctx["session"] = session
    ctx["registrations"] = built["registrations"]
    return ctx


def setup_two_windows_one_affidavit():
    """Two OPEN windows sharing dates; the proctor has signed only the first.

    Session A sits in window one with the proctor assigned; session B sits in
    window two, overlaps A in time and has no proctor yet.
    Returns the program context with "window_two", "session_a" and "session_b".
    """
    ctx = setup_program(lot_code="LOT-J1", seal_start=1400)
    window_two = create_window(name="Fall MATH G9-12", subject="MATH")
    ship_lot(window_two["id"], ctx["district"]["id"], lot_code="LOT-J2",
             seal_range_start=1500)
    window_two = move_window(window_two["id"], "OPEN")

    proctor = add_proctor(ctx["school"]["id"])
    proctor = complete_training(proctor["id"], ctx["school"]["id"], 92.0)
    sign_affidavit(proctor["id"], ctx["window"]["id"],
                   expected_proctor_version=proctor["version"])
    ctx["proctor"] = read_proctor(proctor["id"])

    session_a = create_session(ctx["window"]["id"], ctx["school"]["id"],
                               room_code="R101", seat_capacity=25)
    session_a = assign_proctor_to_session(session_a, ctx["proctor"]["id"],
                                          ctx["school"]["id"])
    session_b = create_session(window_two["id"], ctx["school"]["id"],
                               room_code="R202", seat_capacity=25,
                               scheduled_start="2026-09-08T11:00:00Z",
                               scheduled_end="2026-09-08T14:00:00Z")
    ctx["window_two"] = window_two
    ctx["session_a"] = session_a
    ctx["session_b"] = session_b
    return ctx


def setup_two_scheduled_sessions_under_review_breach():
    """One proctor holding two SCHEDULED sessions and an open breach report.

    Session A (R101, 2026-09-08) and session B (R102, 2026-09-15) each hold one
    PENDING registration; a SECURITY_BREACH report against session A sits in
    UNDER_REVIEW, so the window's security hold is already raised.
    Returns the program context with "session_a", "session_b", "registrations"
    and "report".
    """
    ctx = setup_program_with_certified_proctor(lot_quantity=20, seal_start=9000)
    built_a = setup_staffed_session(
        ctx, room_code="R101",
        students=[{"student_state_id": "S00000001", "grade": 10}])
    built_b = setup_staffed_session(
        ctx, room_code="R102",
        students=[{"student_state_id": "S00000002", "grade": 10}],
        session_overrides={"scheduled_start": "2026-09-15T09:00:00Z",
                           "scheduled_end": "2026-09-15T12:00:00Z"})
    report = setup_report_under_review(
        ctx, built_a["session"]["id"], ctx["proctor"]["id"],
        category="SECURITY_BREACH", severity="HIGH",
        narrative="A sealed booklet was opened before the start signal.")
    ctx["session_a"] = built_a["session"]
    ctx["session_b"] = built_b["session"]
    ctx["registrations"] = built_a["registrations"] + built_b["registrations"]
    ctx["report"] = report
    return ctx


def setup_participation_dual_variant_window():
    """The window whose two participation variants disagree.

    Session A closes with two PRESENT seats and one ABSENT seat; session B is
    cancelled while DRAFT, withdrawing its single seat. The lot reconciles
    clean, both PRESENT seats are scored and the window is RELEASED, with a
    student-specific ADMIN_ERROR report on the second PRESENT seat sitting in
    UNDER_REVIEW.
    Returns the program context with "session_a", "session_b", "registrations"
    (r1..r4 in order) and "report".
    """
    ctx = setup_program_with_certified_proctor(
        lot_quantity=20, seal_start=3000,
        window_overrides={"min_participation_pct": 50.0, "appeal_window_days": 10})
    deliver_lot_to_school(ctx)

    session_b = create_session(ctx["window"]["id"], ctx["school"]["id"],
                               room_code="R102", seat_capacity=25)
    built_a = setup_staffed_session(
        ctx, room_code="R101", seat_capacity=25,
        students=[{"student_state_id": "S00000001", "grade": 10,
                   "guardian_email": "g1@fam.example"},
                  {"student_state_id": "S00000002", "grade": 10,
                   "guardian_email": "g2@fam.example"},
                  {"student_state_id": "S00000003", "grade": 10,
                   "guardian_email": "g3@fam.example"}],
        schedule=False)
    r4 = register_student(session_b["id"], ctx["school"]["id"],
                          student_state_id="S00000004", grade=10,
                          guardian_email="g4@fam.example")
    session_a = move_session(built_a["session"]["id"], "SCHEDULED",
                             school_id=ctx["school"]["id"])
    session_a = open_the_room(ctx, session_a, 6)
    for registration, status in zip(built_a["registrations"],
                                    ("PRESENT", "PRESENT", "ABSENT")):
        record_attendance(registration["id"], status, ctx["proctor"]["id"])
    session_a = close_the_room(ctx, session_a, 6)
    session_b = move_session(session_b["id"], "CANCELLED",
                             school_id=ctx["school"]["id"])

    close_out_lot(ctx)
    advance_window_to_scoring(ctx)
    record_score(built_a["registrations"][0]["id"], 88)
    record_score(built_a["registrations"][1]["id"], 91)
    ctx["window"] = release_window(ctx)

    # The report names the second PRESENT registration.
    report = setup_report_under_review(
        ctx, session_a["id"], ctx["proctor"]["id"],
        category="ADMIN_ERROR", severity="MEDIUM",
        narrative="Timing script misread for one test taker.",
        registration_id=built_a["registrations"][1]["id"])
    ctx["session_a"] = read_session(session_a["id"])
    ctx["session_b"] = read_session(session_b["id"])
    ctx["registrations"] = [read_registration(r["id"])
                            for r in built_a["registrations"]] + \
        [read_registration(r4["id"])]
    ctx["report"] = report
    return ctx


def setup_makeup_ready_program():
    """An initial session closed with one ABSENT and one PRESENT seat, then two
    make-up sessions run by different proctors.

    Returns the program context with "proctor_two", "session_a", "session_b"
    (make-up, proctor one), "session_c" (make-up, proctor two) and
    "registrations" (the two initial seats).
    """
    ctx = setup_program_with_certified_proctor(
        lot_quantity=20, seal_start=4600,
        window_overrides={"min_participation_pct": 50.0})
    proctor_two, _ = add_certified_proctor(ctx)
    ctx["proctor_two"] = proctor_two

    ran = run_session_to_closed(
        ctx,
        students=[{"student_state_id": "S00000001", "grade": 10},
                  {"student_state_id": "S00000002", "grade": 10,
                   "guardian_email": "g2@fam.example"}],
        attendance=["ABSENT", "PRESENT"],
        room_code="R101", checkout_quantity=6)

    advance_window_to_makeup(ctx)
    session_b = create_session(ctx["window"]["id"], ctx["school"]["id"],
                               room_code="R101", seat_capacity=20,
                               session_type="MAKEUP",
                               scheduled_start=TEST_CALENDAR["MAKEUP_SESSION_START"],
                               scheduled_end=TEST_CALENDAR["MAKEUP_SESSION_END"])
    session_b = assign_proctor_to_session(session_b, ctx["proctor"]["id"],
                                          ctx["school"]["id"])
    session_c = create_session(ctx["window"]["id"], ctx["school"]["id"],
                               room_code="R102", seat_capacity=20,
                               session_type="MAKEUP",
                               scheduled_start=TEST_CALENDAR["MAKEUP_SESSION_START"],
                               scheduled_end=TEST_CALENDAR["MAKEUP_SESSION_END"])
    session_c = assign_proctor_to_session(session_c, proctor_two["id"],
                                          ctx["school"]["id"])
    ctx["session_a"] = ran["session"]
    ctx["session_b"] = session_b
    ctx["session_c"] = session_c
    ctx["registrations"] = ran["registrations"]
    return ctx


def setup_scored_session_with_open_breach():
    """A CLOSED session with two scored seats and an open breach report.

    The window sits in SCORING and the SECURITY_BREACH report naming the session
    is UNDER_REVIEW.
    Returns the program context with "session", "registrations" and "report".
    """
    ctx = setup_program_with_certified_proctor(
        window_overrides={"min_participation_pct": 50.0})
    ran = run_session_to_closed(
        ctx,
        students=[{"student_state_id": "S00000001", "grade": 10},
                  {"student_state_id": "S00000002", "grade": 10,
                   "guardian_email": "g2@fam.example"}],
        attendance=["PRESENT", "PRESENT"],
        checkout_quantity=4)
    close_out_lot(ctx)
    advance_window_to_scoring(ctx)
    record_score(ran["registrations"][0]["id"], 81)
    record_score(ran["registrations"][1]["id"], 64)
    report = setup_report_under_review(
        ctx, ran["session"]["id"], ctx["proctor"]["id"],
        category="SECURITY_BREACH", severity="HIGH",
        narrative="Room was left unattended with booklets out.")
    ctx["session"] = read_session(ran["session"]["id"])
    ctx["registrations"] = [read_registration(r["id"]) for r in ran["registrations"]]
    ctx["report"] = report
    return ctx
