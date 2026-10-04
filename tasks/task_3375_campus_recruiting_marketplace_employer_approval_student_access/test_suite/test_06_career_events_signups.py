"""Career events, session scheduling, sign-ups, waitlists, and cascades."""
from test_helpers import (
    ApiErrorId,
    add_session,
    create_active_university,
    create_event,
    create_event_session_payload,
    create_student,
    get_event,
    get_session_occupied_seats,
    make_career_center_admin_headers,
    make_student_headers,
    patch_student,
    set_clock,
    setup_base_marketplace,
    setup_interviewing_application,
    signup_student,
    transition_event,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import PA


# ---------------------------------------------------------------------------
# Shared scenario builders
# ---------------------------------------------------------------------------

def _open_event_with_cap1_session(university_id):
    """OPEN event with one capacity-1 IN_PERSON session. Returns (event, session)."""
    event = create_event(university_id, title="Fall Fair")
    event = transition_event(event["id"], university_id, "OPEN")
    session = add_session(
        event["id"], university_id,
        title="Acme Booth", mode="IN_PERSON", room_id="GYM-A",
        starts_at="2026-10-10T10:00:00Z", ends_at="2026-10-10T11:00:00Z",
        signup_deadline="2026-10-09T23:59:59Z", capacity=1,
    )
    return event, session


def _waitlist_scenario(api):
    """University ACTIVE; OPEN event with a capacity-1 session; Sam REGISTERED,
    Wei WAITLISTED behind her. Returns a ctx dict."""
    set_clock()
    university = create_active_university(
        name="State University", primary_domain="stateu.edu",
        employer_daily_message_cap=10,
    )
    sam = create_student(
        university["id"], email="sam@stateu.edu", full_name="Sam Lee",
        major="CS", graduation_year=2027, work_authorization="US_CITIZEN",
        profile_visibility="PUBLIC_TO_APPROVED_EMPLOYERS",
    )
    event, session = _open_event_with_cap1_session(university["id"])
    sg_sam = signup_student(session["id"], sam["id"])
    wei = create_student(
        university["id"], email="wei@stateu.edu", full_name="Wei Chen",
        major="EE", graduation_year=2028, work_authorization="VISA_OPT_CPT",
    )
    sg_wei = signup_student(session["id"], wei["id"])
    return {
        "university": university, "sam": sam, "wei": wei,
        "event": event, "session": session, "sg_sam": sg_sam, "sg_wei": sg_wei,
    }


def _withdrawal_scenario(api):
    """Base marketplace (posting PUBLISHED) plus Sam INTERVIEWING with one
    SCHEDULED interview, plus the capacity-1 session with Sam REGISTERED and Wei
    WAITLISTED."""
    ctx = setup_base_marketplace()
    application, interview = setup_interviewing_application(ctx)
    university_id = ctx["university"]["id"]
    event, session = _open_event_with_cap1_session(university_id)
    sg_sam = signup_student(session["id"], ctx["student"]["id"])
    wei = create_student(
        university_id, email="wei@stateu.edu", full_name="Wei Chen",
        major="CS", graduation_year=2028, work_authorization="VISA_OPT_CPT",
    )
    sg_wei = signup_student(session["id"], wei["id"])
    ctx.update({"application": application, "interview": interview,
                "event": event, "session": session,
                "sg_sam": sg_sam, "wei": wei, "sg_wei": sg_wei})
    return ctx


def _room_scenario(api):
    """DRAFT event (sessions may be added while DRAFT or OPEN) with sessions
    A (IN_PERSON GYM-A 10:00-11:00), B (IN_PERSON GYM-A 11:00-12:00), and
    D (VIRTUAL 10:30-11:30) already accepted."""
    set_clock()
    university = create_active_university(
        name="State University", primary_domain="stateu.edu",
        employer_daily_message_cap=10,
    )
    event = create_event(university["id"], title="Fall Fair")
    a = add_session(
        event["id"], university["id"],
        title="A", mode="IN_PERSON", room_id="GYM-A",
        starts_at="2026-10-10T10:00:00Z", ends_at="2026-10-10T11:00:00Z",
        signup_deadline="2026-10-09T23:59:59Z", capacity=10,
    )
    b = add_session(
        event["id"], university["id"],
        title="B", mode="IN_PERSON", room_id="GYM-A",
        starts_at="2026-10-10T11:00:00Z", ends_at="2026-10-10T12:00:00Z",
        signup_deadline="2026-10-09T23:59:59Z", capacity=10,
    )
    d = add_session(
        event["id"], university["id"],
        title="D", mode="VIRTUAL",
        starts_at="2026-10-10T10:30:00Z", ends_at="2026-10-10T11:30:00Z",
        signup_deadline="2026-10-09T23:59:59Z", capacity=50,
    )
    return university, event, (a, b, d)


# ---------------------------------------------------------------------------
# Student withdrawal cascade (depth 2, two branches)
# ---------------------------------------------------------------------------

class TestStudentWithdrawalCascade:
    def test_withdrawal_cascades_application_and_interview(self, api):
        """PRD §3.1: "In the first hop, every application of the withdrawing student in
        `SUBMITTED`, `UNDER_REVIEW`, `INTERVIEWING`, or `OFFER_EXTENDED` moves to
        `WITHDRAWN`, and each such transition decrements its posting's
        `active_application_count` by 1; in the second hop, every interview still
        `SCHEDULED` on one of those just-withdrawn applications moves to `CANCELLED`."

        Design: Difficulty/transitive_cascade/student_withdrawal_cascades_applications_and_promotes_waitlist
        """
        ctx = _withdrawal_scenario(api)
        student = patch_student(ctx["student"]["id"], ctx["university"]["id"],
                                {"status": "WITHDRAWN"})
        assert student["status"] == "WITHDRAWN"

        application = validate_success(
            api.get_application(ctx["application"]["id"], PA), 200
        )
        assert application["status"] == "WITHDRAWN"
        interviews = validate_success(
            api.list_interviews(ctx["application"]["id"], PA), 200
        )
        assert interviews[0]["id"] == ctx["interview"]["id"]
        assert interviews[0]["status"] == "CANCELLED"
        posting = validate_success(api.get_job_posting(ctx["posting"]["id"], PA), 200)
        assert posting["active_application_count"] == 0

    def test_withdrawal_cancels_signup_and_promotes_waitlist(self, api):
        """PRD §3.1: "A parallel first-hop branch cancels the student's event
        commitments: every sign-up of the student in `REGISTERED` or `WAITLISTED` moves
        to `CANCELLED`, and each `REGISTERED` cancellation fires the waitlist-promotion
        rule of §3.6 on its session."
        PRD §3.6: "The promoted sign-up moves to `REGISTERED`, has its `registered_at`
        stamped from the logical clock, and is marked `promoted_from_waitlist` true."

        Design: Difficulty/transitive_cascade/student_withdrawal_cascades_applications_and_promotes_waitlist
        """
        ctx = _withdrawal_scenario(api)
        patch_student(ctx["student"]["id"], ctx["university"]["id"],
                      {"status": "WITHDRAWN"})

        sg_sam = validate_success(api.get_event_signup(ctx["sg_sam"]["id"], PA), 200)
        assert sg_sam["status"] == "CANCELLED"
        sg_wei = validate_success(api.get_event_signup(ctx["sg_wei"]["id"], PA), 200)
        assert sg_wei["status"] == "REGISTERED"
        assert sg_wei["promoted_from_waitlist"] is True
        assert sg_wei["registered_at"] is not None
        # The cancel+promote pair conserves the seat count.
        assert get_session_occupied_seats(
            ctx["event"]["id"], ctx["university"]["id"], ctx["session"]["id"]
        ) == 1
        # The parent event is untouched by the student cascade.
        event = get_event(ctx["event"]["id"], ctx["university"]["id"])
        assert event["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Sign-up gating on the parent event's state
# ---------------------------------------------------------------------------

class TestSignupEventStateGate:
    def test_signup_rejected_while_event_draft_then_succeeds_when_open(self, api):
        """PRD §3.6: "The session's parent event must be in `OPEN` or `LOCKED` and the
        session itself still `SCHEDULED`; otherwise the attempt fails with
        `ERR_EVENT_NOT_SIGNABLE` (HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/signup_requires_signable_event_state
        """
        set_clock()
        university = create_active_university(
            name="State University", primary_domain="stateu.edu",
            employer_daily_message_cap=10,
        )
        sam = create_student(
            university["id"], email="sam@stateu.edu", full_name="Sam Lee",
            major="CS", graduation_year=2027, work_authorization="US_CITIZEN",
        )
        event = create_event(university["id"], title="Fall Fair")
        session = add_session(
            event["id"], university["id"],
            title="Booth 1", mode="IN_PERSON", room_id="GYM-A",
            starts_at="2026-10-10T10:00:00Z", ends_at="2026-10-10T11:00:00Z",
            signup_deadline="2026-10-09T23:59:59Z", capacity=10,
        )
        response = api.create_event_signup(
            {"event_session_id": session["id"], "student_id": sam["id"]},
            make_student_headers(sam["id"]),
        )
        validate_error(response, ApiErrorId.ERR_EVENT_NOT_SIGNABLE, 409)

        transition_event(event["id"], university["id"], "OPEN")
        signup = signup_student(session["id"], sam["id"])
        assert signup["status"] == "REGISTERED"
        assert signup["registered_at"] is not None

    def test_signup_rejected_after_event_cancelled_and_cascade_applies(self, api):
        """PRD §3.6: "The session's parent event must be in `OPEN` or `LOCKED` and the
        session itself still `SCHEDULED`; otherwise the attempt fails with
        `ERR_EVENT_NOT_SIGNABLE` (HTTP 409)"
        PRD §3.5: "Cancelling an event cascades downward: every session of the event
        still `SCHEDULED` moves to `CANCELLED`, and then every sign-up belonging to one
        of those just-cancelled sessions, while in `REGISTERED` or `WAITLISTED`, moves
        to `CANCELLED`."

        Design: Difficulty/cross_entity_state_dependency/signup_requires_signable_event_state
        """
        set_clock()
        university = create_active_university(
            name="State University", primary_domain="stateu.edu",
            employer_daily_message_cap=10,
        )
        sam = create_student(
            university["id"], email="sam@stateu.edu", full_name="Sam Lee",
            major="CS", graduation_year=2027, work_authorization="US_CITIZEN",
        )
        event = create_event(university["id"], title="Fall Fair")
        event = transition_event(event["id"], university["id"], "OPEN")
        session = add_session(
            event["id"], university["id"],
            title="Booth 1", mode="IN_PERSON", room_id="GYM-A",
            starts_at="2026-10-10T10:00:00Z", ends_at="2026-10-10T11:00:00Z",
            signup_deadline="2026-10-09T23:59:59Z", capacity=10,
        )
        signup = signup_student(session["id"], sam["id"])
        assert signup["status"] == "REGISTERED"

        transition_event(event["id"], university["id"], "CANCELLED")

        sally = create_student(
            university["id"], email="sally@stateu.edu", full_name="Sally Kim",
            major="CS", graduation_year=2027, work_authorization="US_CITIZEN",
        )
        response = api.create_event_signup(
            {"event_session_id": session["id"], "student_id": sally["id"]},
            make_student_headers(sally["id"]),
        )
        validate_error(response, ApiErrorId.ERR_EVENT_NOT_SIGNABLE, 409)

        cc = make_career_center_admin_headers(university["id"])
        sessions = validate_success(api.list_event_sessions(event["id"], cc), 200)
        assert sessions[0]["status"] == "CANCELLED"
        sg = validate_success(api.get_event_signup(signup["id"], PA), 200)
        assert sg["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# Room conflict detection (half-open interval semantics)
# ---------------------------------------------------------------------------

class TestRoomConflict:
    def test_adjacent_and_virtual_sessions_do_not_conflict(self, api):
        """PRD §3.5: "Back-to-back adjacency — the new start exactly equal to an
        existing end, or vice versa — is not a conflict, and `VIRTUAL` sessions never
        conflict because they hold no room."
        PRD §3.5: "Sessions are added to an event while it is in `DRAFT` or `OPEN`."

        Design: Difficulty/resource_temporal_overlap/room_conflict_half_open_interval_semantics
        """
        set_clock()
        university = create_active_university(
            name="State University", primary_domain="stateu.edu",
            employer_daily_message_cap=10,
        )
        cc = make_career_center_admin_headers(university["id"])
        event = create_event(university["id"], title="Fall Fair")
        add_session(
            event["id"], university["id"],
            title="A", mode="IN_PERSON", room_id="GYM-A",
            starts_at="2026-10-10T10:00:00Z", ends_at="2026-10-10T11:00:00Z",
            signup_deadline="2026-10-09T23:59:59Z", capacity=10,
        )
        # Exact adjacency: B starts exactly when A ends — allowed under half-open.
        resp_b = api.create_event_session(
            event["id"],
            create_event_session_payload(
                get_event(event["id"], university["id"])["version"],
                title="B", mode="IN_PERSON", room_id="GYM-A",
                starts_at="2026-10-10T11:00:00Z", ends_at="2026-10-10T12:00:00Z",
                signup_deadline="2026-10-09T23:59:59Z", capacity=10,
            ),
            cc,
        )
        session_b = validate_success(resp_b, 201)
        assert session_b["title"] == "B"
        # VIRTUAL at an overlapping time carries no room — never conflicts.
        resp_d = api.create_event_session(
            event["id"],
            create_event_session_payload(
                get_event(event["id"], university["id"])["version"],
                title="D", mode="VIRTUAL",
                starts_at="2026-10-10T10:30:00Z", ends_at="2026-10-10T11:30:00Z",
                signup_deadline="2026-10-09T23:59:59Z", capacity=50,
            ),
            cc,
        )
        session_d = validate_success(resp_d, 201)
        assert session_d["mode"] == "VIRTUAL"
        assert session_d["room_id"] is None

    def test_overlapping_in_person_session_same_room_conflicts(self, api):
        """PRD §3.5: "A new in-person session conflicts when there exists another
        session of the same event that is not `CANCELLED`, is itself `IN_PERSON`,
        carries the same `room_id`, and whose interval overlaps: the new session's
        `starts_at` strictly before the existing session's `ends_at`, and the existing
        session's `starts_at` strictly before the new session's `ends_at`."
        PRD §3.5: "A conflict is rejected with `ERR_SESSION_ROOM_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/room_conflict_half_open_interval_semantics
        """
        university, event, _existing = _room_scenario(api)
        cc = make_career_center_admin_headers(university["id"])
        response = api.create_event_session(
            event["id"],
            create_event_session_payload(
                get_event(event["id"], university["id"])["version"],
                title="C", mode="IN_PERSON", room_id="GYM-A",
                starts_at="2026-10-10T10:30:00Z", ends_at="2026-10-10T11:30:00Z",
                signup_deadline="2026-10-09T23:59:59Z", capacity=10,
            ),
            cc,
        )
        validate_error(response, ApiErrorId.ERR_SESSION_ROOM_CONFLICT, 409)
        sessions = validate_success(api.list_event_sessions(event["id"], cc), 200)
        assert len(sessions) == 3, "C must not be persisted; only A, B, D exist"
        assert {s["title"] for s in sessions} == {"A", "B", "D"}


# ---------------------------------------------------------------------------
# Waitlist promotion and the occupied_seats conserved quantity
# ---------------------------------------------------------------------------

class TestCancelPromotionConservation:
    def test_cancel_registered_promotes_waitlisted_signup(self, api):
        """PRD §3.6: "Cancelling a `REGISTERED` sign-up, while the session is still
        `SCHEDULED`, fires waitlist promotion: among the session's `WAITLISTED`
        sign-ups, exactly one is promoted — the one with the earliest `created_at`"
        PRD §3.6: "The promoted sign-up moves to `REGISTERED`, has its `registered_at`
        stamped from the logical clock, and is marked `promoted_from_waitlist` true."

        Design: Difficulty/compensating_invariant/signup_cancel_promotion_conserves_occupied_seats
        """
        ctx = _waitlist_scenario(api)
        cancelled = validate_success(
            api.transition_event_signup(
                ctx["sg_sam"]["id"], {"to": "CANCELLED"},
                make_student_headers(ctx["sam"]["id"]),
            ),
            200,
        )
        assert cancelled["status"] == "CANCELLED"
        promoted = validate_success(
            api.get_event_signup(ctx["sg_wei"]["id"], PA), 200
        )
        assert promoted["status"] == "REGISTERED"
        assert promoted["promoted_from_waitlist"] is True
        assert promoted["registered_at"] is not None

    def test_occupied_seats_unchanged_by_cancel_promote_pair(self, api):
        """PRD §3.6: "Because the cancellation removes one occupied seat and the
        promotion fills one, `occupied_seats` is unchanged by the cancel-promote pair"
        PRD §3.6: "The `occupied_seats` counter itself counts exactly the session's
        sign-ups in `REGISTERED` and is recomputed on every sign-up creation,
        cancellation, and promotion."

        Design: Difficulty/compensating_invariant/signup_cancel_promotion_conserves_occupied_seats
        """
        ctx = _waitlist_scenario(api)
        assert get_session_occupied_seats(
            ctx["event"]["id"], ctx["university"]["id"], ctx["session"]["id"]
        ) == 1
        api.transition_event_signup(
            ctx["sg_sam"]["id"], {"to": "CANCELLED"},
            make_student_headers(ctx["sam"]["id"]),
        )
        assert get_session_occupied_seats(
            ctx["event"]["id"], ctx["university"]["id"], ctx["session"]["id"]
        ) == 1, "cancel (-1) and promote (+1) must compensate exactly"
        rows, _meta = validate_paginated(
            api.list_event_signups(
                PA, params={"event_session_id": ctx["session"]["id"],
                            "status": "REGISTERED"})
        )
        assert len(rows) == 1, "the stored counter and the REGISTERED set must agree"
        assert rows[0]["id"] == ctx["sg_wei"]["id"]


# ---------------------------------------------------------------------------
# Corner translations (queue B)
# ---------------------------------------------------------------------------

class TestAttendanceMarking:
    def test_attendance_requires_completed_event(self, api):
        """PRD §3.6: "Once the parent event has reached `COMPLETED`, a
        `CareerCenterAdmin` of the university that owns the event may move a
        `REGISTERED` sign-up to `ATTENDED` or to `NO_SHOW`. Attempting either marking
        before the event is `COMPLETED`, or on a sign-up that is not `REGISTERED`,
        fails with `ERR_INVALID_SIGNUP_TRANSITION`."

        Design: Corner/state_machines/signup_attendance_requires_completed_event
        """
        set_clock()
        university = create_active_university(
            name="State University", primary_domain="stateu.edu",
            employer_daily_message_cap=10,
        )
        sam = create_student(
            university["id"], email="sam@stateu.edu", full_name="Sam Lee",
            major="CS", graduation_year=2027, work_authorization="US_CITIZEN",
        )
        event = create_event(university["id"], title="Fall Fair")
        transition_event(event["id"], university["id"], "OPEN")
        session = add_session(
            event["id"], university["id"],
            title="Acme Booth", mode="IN_PERSON", room_id="GYM-A",
            starts_at="2026-10-10T10:00:00Z", ends_at="2026-10-10T11:00:00Z",
            signup_deadline="2026-10-09T23:59:59Z", capacity=10,
        )
        signup = signup_student(session["id"], sam["id"])
        assert signup["status"] == "REGISTERED"
        response = api.transition_event_signup(
            signup["id"], {"to": "ATTENDED"},
            make_career_center_admin_headers(university["id"]),
        )
        validate_error(response, ApiErrorId.ERR_INVALID_SIGNUP_TRANSITION, 409)
        sg = validate_success(api.get_event_signup(signup["id"], PA), 200)
        assert sg["status"] == "REGISTERED"


class TestWaitlistFifoOrder:
    def test_promotion_is_fifo_by_created_at(self, api):
        """PRD §3.6: "among the session's `WAITLISTED` sign-ups, exactly one is
        promoted — the one with the earliest `created_at`, ties broken by the student's
        `email` in ascending order, never by identifier."

        Design: Corner/calculations/waitlist_promotion_is_fifo_by_created_at
        """
        ctx = _waitlist_scenario(api)
        bo = create_student(
            ctx["university"]["id"], email="bo@stateu.edu", full_name="Bo Rao",
            major="CS", graduation_year=2027, work_authorization="US_CITIZEN",
        )
        sg_bo = signup_student(ctx["session"]["id"], bo["id"])
        assert sg_bo["status"] == "WAITLISTED"

        api.transition_event_signup(
            ctx["sg_sam"]["id"], {"to": "CANCELLED"},
            make_student_headers(ctx["sam"]["id"]),
        )
        wei = validate_success(api.get_event_signup(ctx["sg_wei"]["id"], PA), 200)
        assert wei["status"] == "REGISTERED"
        assert wei["promoted_from_waitlist"] is True
        bo_read = validate_success(api.get_event_signup(sg_bo["id"], PA), 200)
        assert bo_read["status"] == "WAITLISTED", (
            "Wei waitlisted before Bo; Bo must remain WAITLISTED"
        )
        assert get_session_occupied_seats(
            ctx["event"]["id"], ctx["university"]["id"], ctx["session"]["id"]
        ) == 1


class TestSessionCatalogFreeze:
    def test_session_create_on_locked_event_returns_event_not_open(self, api):
        """PRD §3.5: "Locking freezes the session catalog: once an event is `LOCKED`,
        further session creation against it fails with `ERR_EVENT_NOT_OPEN`
        (HTTP 409)."

        Design: Corner/endpoints/session_create_on_locked_event_returns_event_not_open
        """
        set_clock()
        university = create_active_university(
            name="State University", primary_domain="stateu.edu",
            employer_daily_message_cap=10,
        )
        event = create_event(university["id"], title="Fall Fair")
        event = transition_event(event["id"], university["id"], "OPEN")
        locked = transition_event(event["id"], university["id"], "LOCKED")
        cc = make_career_center_admin_headers(university["id"])
        response = api.create_event_session(
            event["id"],
            create_event_session_payload(
                locked["version"],  # current version — the state gate, not OCC, fires
                title="Late Booth", mode="VIRTUAL",
                starts_at="2026-10-10T13:00:00Z", ends_at="2026-10-10T14:00:00Z",
                signup_deadline="2026-10-09T23:59:59Z", capacity=30,
            ),
            cc,
        )
        error = validate_error(response, ApiErrorId.ERR_EVENT_NOT_OPEN, 409)
        assert error["error_id"] != "ERR_STALE_CAREER_EVENT_VERSION"
        sessions = validate_success(api.list_event_sessions(event["id"], cc), 200)
        assert len(sessions) == 0


class TestSignupWindow:
    def test_signup_after_deadline_returns_window_closed(self, api):
        """PRD §3.6: "The sign-up window must still be open: the logical clock must
        read strictly before the session's `signup_deadline`, an exclusive deadline, or
        the attempt fails with `ERR_SIGNUP_WINDOW_CLOSED` (HTTP 409)."

        Design: Corner/errors/signup_after_deadline_returns_window_closed
        """
        set_clock()
        university = create_active_university(
            name="State University", primary_domain="stateu.edu",
            employer_daily_message_cap=10,
        )
        sam = create_student(
            university["id"], email="sam@stateu.edu", full_name="Sam Lee",
            major="CS", graduation_year=2027, work_authorization="US_CITIZEN",
        )
        event = create_event(university["id"], title="Fall Fair")
        transition_event(event["id"], university["id"], "OPEN")
        session = add_session(
            event["id"], university["id"],
            title="Acme Booth", mode="IN_PERSON", room_id="GYM-A",
            starts_at="2026-10-10T10:00:00Z", ends_at="2026-10-10T11:00:00Z",
            signup_deadline="2026-10-09T23:59:59Z", capacity=10,
        )
        set_clock("2026-10-10T00:00:00Z")
        response = api.create_event_signup(
            {"event_session_id": session["id"], "student_id": sam["id"]},
            make_student_headers(sam["id"]),
        )
        validate_error(response, ApiErrorId.ERR_SIGNUP_WINDOW_CLOSED, 409)
        rows, _meta = validate_paginated(
            api.list_event_signups(PA, params={"event_session_id": session["id"]})
        )
        assert len(rows) == 0
        assert get_session_occupied_seats(event["id"], university["id"],
                                        session["id"]) == 0


class TestCrossUniversitySignup:
    def test_cross_university_signup_returns_cross_university_access(self, api):
        """PRD §3.6: "The session must belong to an event of the student's own
        university; a cross-university attempt is rejected with
        `ERR_CROSS_UNIVERSITY_ACCESS` (HTTP 403)."

        Design: Corner/errors/cross_university_signup_returns_cross_university_access
        """
        set_clock()
        university = create_active_university(
            name="State University", primary_domain="stateu.edu",
            employer_daily_message_cap=10,
        )
        event = create_event(university["id"], title="Fall Fair")
        transition_event(event["id"], university["id"], "OPEN")
        session = add_session(
            event["id"], university["id"],
            title="Acme Booth", mode="IN_PERSON", room_id="GYM-A",
            starts_at="2026-10-10T10:00:00Z", ends_at="2026-10-10T11:00:00Z",
            signup_deadline="2026-10-09T23:59:59Z", capacity=10,
        )
        tech = create_active_university(
            name="Tech Institute", primary_domain="tech.edu",
            employer_daily_message_cap=3,
        )
        mia = create_student(
            tech["id"], email="mia@tech.edu", full_name="Mia Torres",
            major="EE", graduation_year=2027, work_authorization="US_CITIZEN",
        )
        response = api.create_event_signup(
            {"event_session_id": session["id"], "student_id": mia["id"]},
            make_student_headers(mia["id"]),
        )
        validate_error(response, ApiErrorId.ERR_CROSS_UNIVERSITY_ACCESS, 403)


class TestSessionCreateOptimisticConcurrency:
    def test_session_create_with_stale_event_version_returns_412(self, api):
        """PRD §2.8: "Session creation on a career event requires a non-optional
        `expected_career_event_version` field equal to the target CareerEvent's current
        `version`. A session is validated against the event window and room plan as
        last observed; if the CareerEvent's `version` has advanced since — for example
        because another session was just accepted onto it — the client's view is stale
        and the create is rejected with `ERR_STALE_CAREER_EVENT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/session_create_with_stale_event_version_returns_412
        """
        set_clock()
        university = create_active_university(
            name="State University", primary_domain="stateu.edu",
            employer_daily_message_cap=10,
        )
        event = create_event(university["id"], title="Fall Fair")
        opened = transition_event(event["id"], university["id"], "OPEN")
        stale_version = opened["version"]
        add_session(
            event["id"], university["id"],
            title="Acme Booth", mode="IN_PERSON", room_id="GYM-A",
            starts_at="2026-10-10T10:00:00Z", ends_at="2026-10-10T11:00:00Z",
            signup_deadline="2026-10-09T23:59:59Z", capacity=10,
        )
        cc = make_career_center_admin_headers(university["id"])
        response = api.create_event_session(
            event["id"],
            create_event_session_payload(
                stale_version,
                title="Second Booth", mode="VIRTUAL",
                starts_at="2026-10-10T13:00:00Z", ends_at="2026-10-10T14:00:00Z",
                signup_deadline="2026-10-09T23:59:59Z", capacity=30,
            ),
            cc,
        )
        validate_error(response, ApiErrorId.ERR_STALE_CAREER_EVENT_VERSION, 412)
        sessions = validate_success(api.list_event_sessions(event["id"], cc), 200)
        assert len(sessions) == 1
