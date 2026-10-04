"""Training institute: courses, enrollments, and certification lifecycle."""
import pytest
from test_helpers import (
    TEST_USERS, ApiErrorId, validate_success, validate_error, validate_error_is_one_of, get_success_data,
    create_member, create_counselor, create_course, set_clock, enroll, grade,
    complete_course_enrollment, create_certification, certify,
    setup_chartered_member_with_counselor,
    make_member_admin_headers,
)
from test_helpers.factories import create_course_payload
from test_helpers.assertions import assert_course, assert_enrollment

DIRECTOR = TEST_USERS["network_director_headers"]
REGISTRAR = TEST_USERS["training_registrar_headers"]


class TestCourseCreation:
    def test_course_system_fields_ignore_input(self, api):
        """PRD §2.4: "`version` is an integer starting at its initial value on
        creation and incrementing by exactly one on every mutation"
        PRD §3.2: "Courses begin `SCHEDULED`; the logical clock moves them to
        `IN_SESSION` when it reaches the delivery start"

        Design: Corner/entities/course_system_fields_ignore_input
        """
        payload = create_course_payload(
            course_code="XX-999", title="SysFields", program_area="RENTAL", capacity=3)
        resp = api.create_course(payload, REGISTRAR)
        data = validate_success(resp, expected_status=201)
        assert_course(data)
        assert data["version"] == 1
        assert data["seats_taken"] == 0
        assert data["course_status"] == "SCHEDULED"

    def test_invalid_enum_rejected(self, api):
        """PRD §2.9: "then payload shape, enum validity, and range checks
        (`ERR_INVALID_REQUEST`)"
        PRD §3.3: "a `TrainingRegistrar` creates it for a counselor in one of the five program areas"

        Design: Corner/validations/invalid_enum_rejected
        """
        payload = create_course_payload(
            course_code="ZZ-100", title="Bad", program_area="MORTGAGE_MAGIC")
        resp = api.create_course(payload, REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestEnrollmentGates:
    def test_course_capacity_full_boundary(self, api):
        """PRD §3.2: "a course at capacity rejects further enrollments with
        `ERR_COURSE_FULL`"
        PRD §3.2: "enrollment is only possible while the clock is within the
        window and while `seats_taken` remains strictly below `capacity`"

        Design: Corner/validations/course_capacity_full_boundary
        """
        member = create_member(legal_name="Cap Org", ein="400000002",
                               state_code="CA", service_regions=["06044"])
        c1 = create_counselor(member["id"], full_name="Ccap1", email="ccap1@x.com")
        c2 = create_counselor(member["id"], full_name="Ccap2", email="ccap2@x.com")
        course = create_course(course_code="HO-312", title="Tiny", capacity=1,
                               delivery_end="2026-09-30T00:00:00Z")
        set_clock("2026-09-10T00:00:00Z")
        enroll(course["id"], c1["id"])
        resp = api.create_enrollment(course["id"], {"counselor_id": c2["id"]}, REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_COURSE_FULL)
        course_after = validate_success(api.get_course(course["id"], REGISTRAR))
        assert course_after["seats_taken"] == 1

    def test_enrollment_prerequisite_enforced(self, api):
        """PRD §3.2: "Where a prerequisite is declared, the counselor must hold
        a `COMPLETED` enrollment in that prerequisite course, failing which the
        enrollment is rejected with `ERR_PREREQUISITE_NOT_MET`"

        Design: Corner/validations/enrollment_prerequisite_enforced
        """
        member = create_member(legal_name="Prereq Org", ein="400000001",
                               state_code="CA", service_regions=["06043"])
        counselor = create_counselor(member["id"], full_name="Cpre", email="cpre@x.com")
        base = create_course(course_code="HO-310", title="Base",
                             delivery_end="2026-09-30T00:00:00Z")
        adv = create_course(course_code="HO-311", title="Adv",
                            delivery_end="2026-09-30T00:00:00Z",
                            prerequisite_course_id=base["id"])
        set_clock("2026-09-10T00:00:00Z")
        resp = api.create_enrollment(adv["id"], {"counselor_id": counselor["id"]}, REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_PREREQUISITE_NOT_MET)
        adv_after = validate_success(api.get_course(adv["id"], REGISTRAR))
        assert adv_after["seats_taken"] == 0

    def test_enrollment_window_within_course_delivery(self, api):
        """PRD §3.2: "Seat occupation follows half-open semantics over the delivery window: enrollment is only possible while the clock is within the window"
        PRD §3.2: "an enrollment attempted outside the delivery window is rejected with `ERR_WINDOW_CLOSED`"
        PRD §2.5: "courses whose delivery window has closed move from
        `IN_SESSION` to `CONCLUDED`, and any enrollment still `REGISTERED` at
        that moment fails with no score recorded and no continuing-education
        credit"

        Design: Difficulty/resource_temporal_overlap/enrollment_window_within_course_delivery
        """
        member = create_member(legal_name="Window Housing", ein="123450003",
                               state_code="OR", service_regions=["41003"])
        c1 = create_counselor(member["id"], full_name="Cw", email="cw@x.com")
        course = create_course(course_code="HO-801", title="HO",
                               delivery_start="2026-09-10T00:00:00Z",
                               delivery_end="2026-09-20T00:00:00Z")
        set_clock("2026-09-10T00:00:00Z")
        e1 = enroll(course["id"], c1["id"])
        assert e1["enrollment_status"] == "REGISTERED"

        c2 = create_counselor(member["id"], full_name="Cw2", email="cw2@x.com")
        set_clock("2026-09-20T00:00:00Z")
        resp = api.create_enrollment(course["id"], {"counselor_id": c2["id"]}, REGISTRAR)
        # PRD §2.9 puts ERR_INVALID_STATE (state gate) ahead of ERR_WINDOW_CLOSED
        # (window gate); at delivery_end the clock cascade has moved the course to
        # CONCLUDED, so either error is a faithful reading.
        validate_error_is_one_of(resp, [ApiErrorId.ERR_WINDOW_CLOSED, ApiErrorId.ERR_INVALID_STATE])

        course_after = validate_success(api.get_course(course["id"], REGISTRAR))
        assert course_after["course_status"] == "CONCLUDED"
        e1_after = validate_success(api.get_enrollment(e1["id"], REGISTRAR))
        assert e1_after["enrollment_status"] == "FAILED"

    def test_enrollment_at_delivery_start_inclusive_succeeds(self, api):
        """PRD §3.2: "a `capacity` of between 1 and 500 seats"
        PRD §3.2: "a delivery window from `delivery_start` (inclusive) to `delivery_end` (exclusive, strictly after the start)"
        PRD §3.2: "Each successful enrollment names its `course_id` and
        `counselor_id`, increments the course's `seats_taken` by one, and
        starts the enrollment in `REGISTERED`."

        Design: Difficulty/resource_temporal_overlap/enrollment_window_within_course_delivery
        """
        member = create_member(legal_name="Window Two Housing", ein="123450013",
                               state_code="OR", service_regions=["41013"])
        counselor = create_counselor(member["id"], full_name="Cw3", email="cw3@x.com")
        course = create_course(course_code="HO-803", title="HO III",
                               delivery_start="2026-09-10T00:00:00Z",
                               delivery_end="2026-09-20T00:00:00Z")
        # Exactly at delivery_start: inclusive lower bound.
        set_clock("2026-09-10T00:00:00Z")
        enrollment = enroll(course["id"], counselor["id"])
        assert_enrollment(enrollment)
        assert enrollment["enrollment_status"] == "REGISTERED"
        course_after = validate_success(api.get_course(course["id"], REGISTRAR))
        assert course_after["seats_taken"] == 1
        assert course_after["course_status"] == "IN_SESSION"


class TestCourseConclusionCascade:
    def test_course_conclusion_auto_fails_registered_enrollments(self, api):
        """PRD §2.5: "courses whose delivery window has closed move from
        `IN_SESSION` to `CONCLUDED`, and any enrollment still `REGISTERED` at
        that moment fails with no score recorded and no continuing-education
        credit"

        Design: Corner/state_machines/course_conclusion_auto_fails_registered_enrollments
        """
        member = create_member(legal_name="AutoFail Org", ein="200000004",
                               state_code="CA", service_regions=["06041"])
        counselor = create_counselor(member["id"], full_name="Caf", email="caf@x.com")
        course = create_course(course_code="HO-113", ce_eligible=True, ce_credits=10)
        set_clock("2026-09-10T00:00:00Z")
        enrollment = enroll(course["id"], counselor["id"])
        set_clock("2026-09-21T00:00:00Z")

        course_after = validate_success(api.get_course(course["id"], REGISTRAR))
        assert course_after["course_status"] == "CONCLUDED"
        enrollment_after = validate_success(api.get_enrollment(enrollment["id"], REGISTRAR))
        assert enrollment_after["enrollment_status"] == "FAILED"
        assert enrollment_after["score"] is None
        counselor_after = validate_success(api.get_counselor(counselor["id"], REGISTRAR))
        assert counselor_after["ce_credits_accumulated"] == 0


class TestSeatConservation:
    def test_enrollment_withdrawal_conserves_seats(self, api):
        """PRD §3.2: "A registration may also be withdrawn by a
        `TrainingRegistrar` or a `MemberAdmin`, which likewise decrements
        `seats_taken` by one."
        PRD §3.2: "A score below the threshold fails the enrollment and frees
        the seat, decrementing `seats_taken` by one."

        Design: Difficulty/compensating_invariant/enrollment_withdrawal_conserves_seats
        """
        member = create_member(legal_name="Seat Housing", ein="123450006",
                               state_code="OR", service_regions=["41006"])
        c1 = create_counselor(member["id"], full_name="S1", email="s1@x.com")
        c2 = create_counselor(member["id"], full_name="S2", email="s2@x.com")
        c3 = create_counselor(member["id"], full_name="S3", email="s3@x.com")
        course = create_course(course_code="HO-902", capacity=2,
                               delivery_end="2026-12-20T00:00:00Z")
        set_clock("2026-09-10T00:00:00Z")
        e1 = enroll(course["id"], c1["id"])
        e2 = enroll(course["id"], c2["id"])

        resp = api.withdraw_enrollment(e1["id"], REGISTRAR)
        validate_success(resp)
        course_after = validate_success(api.get_course(course["id"], REGISTRAR))
        assert course_after["seats_taken"] == 1

        # Released seat re-usable without hitting ERR_COURSE_FULL
        e3 = enroll(course["id"], c3["id"])
        assert e3["enrollment_status"] == "REGISTERED"
        course_after = validate_success(api.get_course(course["id"], REGISTRAR))
        assert course_after["seats_taken"] == 2

        grade(e2["id"], score=50)
        course_final = validate_success(api.get_course(course["id"], REGISTRAR))
        assert course_final["seats_taken"] == 1

    def test_completed_enrollment_does_not_free_seat(self, api):
        """PRD §3.2: "A score at or above the threshold completes the
        enrollment"
        PRD §3.2: "A score below the threshold fails the enrollment and frees
        the seat, decrementing `seats_taken` by one."

        Design: Difficulty/compensating_invariant/enrollment_withdrawal_conserves_seats
        """
        member = create_member(legal_name="Seat Two Housing", ein="123450016",
                               state_code="OR", service_regions=["41016"])
        counselor = create_counselor(member["id"], full_name="S9", email="s9@x.com")
        course = create_course(course_code="HO-903", capacity=3,
                               delivery_end="2026-12-20T00:00:00Z")
        set_clock("2026-09-10T00:00:00Z")
        enrollment = enroll(course["id"], counselor["id"])
        graded = grade(enrollment["id"], score=90)
        assert graded["enrollment_status"] == "COMPLETED"
        course_after = validate_success(api.get_course(course["id"], REGISTRAR))
        assert course_after["seats_taken"] == 1


class TestCertificationLapseCycle:
    def test_certification_lapse_reinstate_cycle(self, api):
        """PRD §3.3: "A lapsed certification can be reinstated — the loop back
        to `CERTIFIED` — once the counselor has accumulated at least 30 CE
        credits and is `ACTIVE`"
        PRD §3.3: "Reinstatement restamps `certified_at` and resets the
        `lapse_deadline` to a fresh window."

        Design: Difficulty/non_linear_state_machine/certification_lapse_reinstate_cycle
        """
        member, counselor, certification = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Cycle Housing", "ein": "666666661",
                              "state_code": "FL", "service_regions": ["12001"]},
            course_code="HO-301")
        assert certification["certification_status"] == "CERTIFIED"

        # Advance past lapse_deadline with zero CE credits -> evaluate lapses.
        set_clock("2028-10-01T00:00:00Z")
        resp = api.evaluate_continuing_requirement(certification["id"], REGISTRAR)
        lapsed = validate_success(resp)
        assert lapsed["certification_status"] == "LAPSED"

        # Earn 30 CE credits via a CE-eligible course completion.
        course = create_course(course_code="HO-302", title="HO CE", ce_eligible=True,
                               ce_credits=30, delivery_start="2028-10-02T00:00:00Z",
                               delivery_end="2028-10-20T00:00:00Z")
        set_clock("2028-10-05T00:00:00Z")
        e2 = enroll(course["id"], counselor["id"])
        grade(e2["id"], score=90)
        counselor_after = validate_success(api.get_counselor(counselor["id"], REGISTRAR))
        assert counselor_after["ce_credits_accumulated"] == 30

        resp = api.reinstate_certification(certification["id"], REGISTRAR)
        reinstated = validate_success(resp)
        assert reinstated["certification_status"] == "CERTIFIED"
        assert reinstated["certified_at"].startswith("2028-10-05")

    def test_certification_lapse_requires_deadline_passed(self, api):
        """PRD §3.3: "After the lapse deadline passes, a `TrainingRegistrar`
        may evaluate the continuing requirement; evaluation before the deadline
        is rejected with `ERR_WINDOW_CLOSED`."

        Design: Difficulty/non_linear_state_machine/certification_lapse_reinstate_cycle
        """
        member, counselor, certification = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Early Eval Housing", "ein": "666666663",
                              "state_code": "FL", "service_regions": ["12003"]},
            course_code="HO-303")
        # Clock still at 2026-09-10 (certified today): deadline is 24 months out.
        resp = api.evaluate_continuing_requirement(certification["id"], REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_WINDOW_CLOSED)
        cert_after = validate_success(api.get_certification(certification["id"], REGISTRAR))
        assert cert_after["certification_status"] == "CERTIFIED"


class TestCounselorSeparationCascade:
    def test_cascade_partial_failure_ordering(self, api):
        """PRD §3.2: "separating an `ACTIVE` or `SUSPENDED` counselor moves
        them to `SEPARATED`, withdraws every enrollment of theirs still in
        `REGISTERED` status — each withdrawal decrementing the owning course's
        `seats_taken` by one — and revokes every certification of theirs not
        already in a terminal state."

        Design: Corner/cross_cutting_layers/cascade_partial_failure_ordering
        """
        member = create_member(legal_name="Sep Org", ein="800000004",
                               state_code="CA", service_regions=["06058"])
        counselor = create_counselor(member["id"], full_name="Csep", email="csep@x.com")
        course1 = create_course(course_code="HO-811", title="Early", ce_eligible=True,
                                ce_credits=10)
        e1 = complete_course_enrollment(course1["id"], counselor["id"])
        assert e1["enrollment_status"] == "COMPLETED"

        course2 = create_course(course_code="HO-812", title="Late",
                                delivery_start="2026-10-01T00:00:00Z",
                                delivery_end="2026-10-30T00:00:00Z")
        set_clock("2026-10-05T00:00:00Z")
        e2 = enroll(course2["id"], counselor["id"])
        cert = create_certification(counselor["id"], "HOMEOWNERSHIP")

        resp = api.separate_counselor(counselor["id"], DIRECTOR)
        separated = validate_success(resp)
        assert separated["counselor_status"] == "SEPARATED"

        e1_after = validate_success(api.get_enrollment(e1["id"], REGISTRAR))
        assert e1_after["enrollment_status"] == "COMPLETED"
        e2_after = validate_success(api.get_enrollment(e2["id"], REGISTRAR))
        assert e2_after["enrollment_status"] == "WITHDRAWN"
        course2_after = validate_success(api.get_course(course2["id"], REGISTRAR))
        assert course2_after["seats_taken"] == 0
        cert_after = validate_success(api.get_certification(cert["id"], REGISTRAR))
        assert cert_after["certification_status"] == "REVOKED"
