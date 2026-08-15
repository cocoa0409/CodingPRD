"""Program-day open/close gates, tag-audited check-in/check-out, and the
late-pickup cutoff (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    check_in_child,
    check_out_child,
    close_day,
    close_registration,
    create_day,
    create_program,
    create_volunteer_with_assignment,
    decide_check,
    get_day,
    list_security_tags_for,
    open_day,
    open_day_with_clock,
    open_registration,
    register_child,
    set_clock,
    setup_family_with_children,
    setup_in_session_program,
    setup_open_program_with_classroom,
    start_session,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

_DIRECTOR = TEST_USERS["program_director_headers"]
_DESK = TEST_USERS["check_in_staff_headers"]


class TestDayOpenStaffingGate:
    def _setup(self):
        """IN_SESSION program; classroom with 1 ENROLLED child (required_adults
        2); v1 CLEARED + auto-CONFIRMED LEAD_TEACHER (1 confirmed adult);
        v2's ASSISTANT_TEACHER still PROPOSED with checks undecided. Day
        SCHEDULED; logical clock on the day's date."""
        program, classroom = setup_open_program_with_classroom(capacity=10)
        day = create_day(program["id"], program["start_date"])
        family, children = setup_family_with_children(count=1)
        register_child(children[0]["id"], classroom["id"], family["id"])
        create_volunteer_with_assignment(
            program["id"], classroom["id"], "LEAD_TEACHER", decide_count=3
        )
        second = create_volunteer_with_assignment(
            program["id"], classroom["id"], "ASSISTANT_TEACHER", decide_count=0
        )
        close_registration(program["id"])
        start_session(program["id"])
        set_clock(f"{day['date']}T08:30:00Z")
        return program, classroom, day, second

    def test_open_rejected_while_understaffed(self, api):
        """PRD §3.7: "every classroom of the program with `enrolled_count`
        above zero must show `staffing_status` `ADEQUATE`
        (`ERR_STAFFING_INADEQUATE`)" — one confirmed adult against the
        two-adult minimum falls short.

        Design: Difficulty/cross_entity_state_dependency/day_open_gated_by_classroom_staffing
        """
        _program, _classroom, day, _second = self._setup()
        resp = api.open_program_day(day["id"], _DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_STAFFING_INADEQUATE, 409)

    def test_open_succeeds_after_second_adult_confirms(self, api):
        """PRD §3.7: "A successful open moves `SCHEDULED` → `OPEN`, sets the
        program's `current_day_index` to the day's `day_index`, and pre-creates
        an attendance record in `NOT_ARRIVED` for every `ENROLLED` registration
        of the program." Once the second adult's clearance auto-confirms (the
        cascade of §3.4), the identical open succeeds.

        Design: Difficulty/cross_entity_state_dependency/day_open_gated_by_classroom_staffing
        """
        program, _classroom, day, second = self._setup()
        for check in second["checks"]:
            decide_check(check["id"], "CLEARED")

        opened = open_day(day["id"])
        assert opened["status"] == "OPEN"
        assert get_program_current_day_index(program["id"]) == day["day_index"]

        data, meta = validate_paginated(
            api.list_attendance(_DIRECTOR, params={"program_day_id": day["id"]})
        )
        assert meta["total_count"] == 1
        assert data[0]["status"] == "NOT_ARRIVED", (
            "open auto-created the enrollee's attendance record"
        )


def get_program_current_day_index(program_id) -> int:
    from test_helpers import get_program
    return get_program(program_id)["current_day_index"]


class TestDayOpenTemporalGate:
    def test_open_wrong_date_returns_day_not_today(self, api):
        """PRD §3.7: "the day's `date` must equal the current logical date
        (`ERR_DAY_NOT_TODAY`)".

        Design: Corner/validations/day_open_wrong_date_returns_day_not_today
        """
        program = create_program()
        create_day(program["id"], "2026-08-17")
        day2 = create_day(program["id"], "2026-08-18")
        open_registration(program["id"])
        close_registration(program["id"])
        start_session(program["id"])
        set_clock("2026-08-17T08:30:00Z")

        resp = api.open_program_day(day2["id"], _DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_DAY_NOT_TODAY, 409)
        assert get_day(day2["id"])["status"] == "SCHEDULED"


class TestCheckInEnrollmentGate:
    def test_checkin_without_enrollment_returns_not_enrolled(self, api):
        """PRD §3.7: "then enrollment — the child must hold an `ENROLLED`
        registration for the day's program, failing with `ERR_NOT_ENROLLED`.
        When no attendance record exists for the child on that day at all, it
        is the enrollment check that decides the error."

        Design: Corner/validations/checkin_without_enrollment_returns_not_enrolled
        """
        program = create_program()
        day = create_day(program["id"], "2026-08-17")
        open_registration(program["id"])
        family, children = setup_family_with_children(count=1)
        close_registration(program["id"])
        start_session(program["id"])
        open_day_with_clock(day)

        resp = api.check_in(
            {"child_id": children[0]["id"], "program_day_id": day["id"]}, _DESK
        )
        validate_error(resp, ApiErrorId.ERR_NOT_ENROLLED, 409)
        assert list_security_tags_for(
            child_id=children[0]["id"], program_day_id=day["id"]
        ) == [], "no tag was minted"


class TestAttendanceHappyPath:
    def test_two_children_sequential_tags_and_counters(self, api):
        """PRD §3.7: "Tag codes are six digits, zero-padded, assigned
        deterministically per program day in issuance order starting at
        000001, and unique among the day's non-`VOIDED` tags."; "A successful
        checkout moves the record `CHECKED_IN` → `CHECKED_OUT`, stamps
        `checked_out_at`, `checked_out_by`, and `pickup_person`, computes
        `late_pickup`, and redeems the matched tag — `ISSUED` → `REDEEMED` with
        `redeemed_at` stamped."; "`checked_in_count` counts
        the day's records in `CHECKED_IN` or `CHECKED_OUT`, `checked_out_count`
        counts those in `CHECKED_OUT`". Both checkouts at 11:59 are before the
        12:00 cutoff, so "a checkout strictly after the cutoff is late; a
        checkout exactly at the cutoff is not late" leaves late_pickup false.

        Design: Corner/state_machines/attendance_happy_path_two_children_sequential_tags
        """
        ctx = setup_in_session_program(child_count=2)
        day = ctx["days"][0]
        k1, k2 = ctx["children"]
        open_day_with_clock(day)

        rec1 = check_in_child(k1["id"], day["id"])
        rec2 = check_in_child(k2["id"], day["id"])
        assert rec1["tag_code"] == "000001"
        assert rec2["tag_code"] == "000002"
        assert rec1["status"] == "CHECKED_IN"

        set_clock(f"{day['date']}T11:59:00Z")
        out1 = check_out_child(k1["id"], day["id"], rec1["tag_code"], "Maria Alvarez")
        out2 = check_out_child(k2["id"], day["id"], rec2["tag_code"], "Maria Alvarez")
        assert out1["status"] == "CHECKED_OUT"
        assert out2["status"] == "CHECKED_OUT"
        assert out1["late_pickup"] is False

        redeemed = list_security_tags_for(program_day_id=day["id"], status="REDEEMED")
        assert len(redeemed) == 2

        day_after = get_day(day["id"])
        assert day_after["checked_in_count"] == 2
        assert day_after["checked_out_count"] == 2


class TestLatePickupBoundary:
    def test_cutoff_is_strict(self, api):
        """PRD §3.7: "`late_pickup` compares the checkout instant against the
        cutoff formed by the day's `date` and the program's
        `pickup_cutoff_time`: a checkout strictly after the cutoff is late; a
        checkout exactly at the cutoff is not late."

        Design: Corner/calculations/late_pickup_strict_boundary
        """
        ctx = setup_in_session_program(child_count=2)
        day = ctx["days"][0]
        k1, k2 = ctx["children"]
        open_day_with_clock(day)
        rec1 = check_in_child(k1["id"], day["id"])
        rec2 = check_in_child(k2["id"], day["id"])

        set_clock(f"{day['date']}T12:00:00Z")
        out1 = check_out_child(k1["id"], day["id"], rec1["tag_code"], "Maria Alvarez")
        assert out1["late_pickup"] is False, "exactly AT the 12:00 cutoff is not late"

        set_clock(f"{day['date']}T12:00:01Z")
        out2 = check_out_child(k2["id"], day["id"], rec2["tag_code"], "Maria Alvarez")
        assert out2["late_pickup"] is True, "one second past the cutoff is late"


class TestTagReprint:
    def test_reprint_voids_old_code_and_issues_next(self, api):
        """PRD §3.7: "staff reprint it for a `CHECKED_IN` child: the active tag
        moves `ISSUED` → `VOIDED` with `void_reason` `REPRINT`, a replacement
        `ISSUED` tag takes the next sequence value for the day, and the
        record's `tag_code` updates to the new code."; and at checkout
        "matching a `VOIDED` or `REDEEMED` tag fails with `ERR_TAG_NOT_ACTIVE`;
        matching no tag at all fails with `ERR_TAG_MISMATCH`; only a code on an
        `ISSUED` tag proceeds."

        Design: Corner/state_machines/security_tag_reprint_voids_old_code
        """
        ctx = setup_in_session_program(child_count=1)
        day = ctx["days"][0]
        child = ctx["children"][0]
        open_day_with_clock(day)
        record = check_in_child(child["id"], day["id"])
        old_code = record["tag_code"]
        assert old_code == "000001"

        reprinted = validate_success(
            api.reprint_tag(
                {"child_id": child["id"], "program_day_id": day["id"]}, _DESK
            )
        )
        new_code = reprinted["tag_code"]
        assert new_code == "000002", "reprint consumes the next sequence value"

        voided = list_security_tags_for(
            child_id=child["id"], program_day_id=day["id"], status="VOIDED"
        )
        assert len(voided) == 1
        assert voided[0]["tag_code"] == "000001"
        assert voided[0]["void_reason"] == "REPRINT"

        resp_old = api.check_out(
            {"child_id": child["id"], "program_day_id": day["id"],
             "tag_code": old_code, "pickup_person": "Maria Alvarez"},
            _DESK,
        )
        validate_error(resp_old, ApiErrorId.ERR_TAG_NOT_ACTIVE, 409)

        out = check_out_child(child["id"], day["id"], new_code, "Maria Alvarez")
        assert out["status"] == "CHECKED_OUT"


class TestCheckOutTagMatching:
    def test_unknown_code_returns_tag_mismatch(self, api):
        """PRD §3.7: "matching a `VOIDED` or `REDEEMED` tag fails with
        `ERR_TAG_NOT_ACTIVE`; matching no tag at all fails with
        `ERR_TAG_MISMATCH`; only a code on an `ISSUED` tag proceeds." — an
        unknown code matches no tag, and the failed attempt changes nothing.

        Design: Corner/validations/checkout_with_unknown_code_returns_tag_mismatch
        """
        ctx = setup_in_session_program(child_count=1)
        day = ctx["days"][0]
        child = ctx["children"][0]
        open_day_with_clock(day)
        record = check_in_child(child["id"], day["id"])
        assert record["tag_code"] == "000001"

        resp = api.check_out(
            {"child_id": child["id"], "program_day_id": day["id"],
             "tag_code": "004242", "pickup_person": "Maria Alvarez"},
            _DESK,
        )
        validate_error(resp, ApiErrorId.ERR_TAG_MISMATCH, 409)

        from test_helpers import list_attendance_for
        records = list_attendance_for(child_id=child["id"], program_day_id=day["id"])
        assert records[0]["status"] == "CHECKED_IN"
        issued = list_security_tags_for(
            child_id=child["id"], program_day_id=day["id"], status="ISSUED"
        )
        assert [t["tag_code"] for t in issued] == ["000001"]


class TestDayClose:
    def test_close_marks_not_arrived_children_absent(self, api):
        """PRD §3.7: closing "moves `OPEN` → `CLOSED`, transitions every record
        still `NOT_ARRIVED` to `ABSENT`"; "`absent_count` counts those in
        `ABSENT`" and "`checked_out_count` counts those in `CHECKED_OUT`" — a
        CHECKED_OUT record is untouched by the cascade.

        Design: Corner/state_machines/day_close_marks_absent_children
        """
        ctx = setup_in_session_program(child_count=2)
        day = ctx["days"][0]
        k1, k2 = ctx["children"]
        open_day_with_clock(day)
        rec1 = check_in_child(k1["id"], day["id"])
        check_out_child(k1["id"], day["id"], rec1["tag_code"], "Maria Alvarez")
        set_clock(f"{day['date']}T12:30:00Z")

        closed = close_day(day["id"])
        assert closed["status"] == "CLOSED"
        assert closed["absent_count"] == 1
        assert closed["checked_out_count"] == 1

        from test_helpers import list_attendance_for
        k2_records = list_attendance_for(child_id=k2["id"], program_day_id=day["id"])
        assert k2_records[0]["status"] == "ABSENT", (
            "conditional cascade: only NOT_ARRIVED records flip"
        )

    def test_close_blocked_while_child_checked_in(self, api):
        """PRD §3.7: "Closing the day requires that no child remain on site —
        any record in `CHECKED_IN` blocks the close with
        `ERR_CHILDREN_ON_SITE`".

        Design: Corner/validations/day_close_with_checked_in_child_returns_children_on_site
        """
        ctx = setup_in_session_program(child_count=1)
        day = ctx["days"][0]
        child = ctx["children"][0]
        open_day_with_clock(day)
        check_in_child(child["id"], day["id"])

        resp = api.close_program_day(day["id"], _DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_CHILDREN_ON_SITE, 409)
        assert get_day(day["id"])["status"] == "OPEN"

        from test_helpers import list_attendance_for
        records = list_attendance_for(child_id=child["id"], program_day_id=day["id"])
        assert records[0]["status"] == "CHECKED_IN"
