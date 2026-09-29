"""Composite setup helpers.

Every test runs against an empty database, so each helper builds its
preconditions from scratch through the public API.  Setup calls use the lenient
``get_success_data`` validator; the strict validators belong in the tests
themselves.

The helpers are layered:

* tier 1 — one call, one row (a school, a centre, a course, a student ...)
* tier 2 — a short chain (a screened referral, an outstanding offer)
* tier 3 — a placed student with coursework under way
* tier 4 — a scenario tuned to a numeric or postural outcome
* tier 5 — a whole district with several actors
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import CLOCK_STARTUP_DATE
from .test_users import (
    ALT_ED_TEACHER_HEADERS,
    DISTRICT_ADMIN_HEADERS,
    REGISTRAR_HEADERS,
    make_home_school_counselor_headers,
    make_placement_coordinator_headers,
    make_support_provider_staff_headers,
)
from .types import (
    CreditPolicy,
    EnrollmentType,
    GradeReplacementPolicy,
    IntegrityResolution,
    Modality,
    Pathway,
    PriorOutcome,
    SubjectArea,
)


# ==========================================================================
# Tier 1 — single rows
# ==========================================================================
def open_home_school(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register one sending school."""
    return get_success_data(
        api.create_home_school(f.home_school_payload(**overrides), DISTRICT_ADMIN_HEADERS)
    )


def open_center(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Open one alternative education centre."""
    return get_success_data(
        api.create_center(f.center_payload(**overrides), DISTRICT_ADMIN_HEADERS)
    )


def publish_course(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Publish one catalogue course; unproctored PACKET unless overridden."""
    return get_success_data(
        api.create_course(f.course_payload(**overrides), DISTRICT_ADMIN_HEADERS)
    )


def publish_online_course(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Publish an ONLINE course, which the catalogue requires to be proctored."""
    return get_success_data(
        api.create_course(f.online_course_payload(**overrides), DISTRICT_ADMIN_HEADERS)
    )


def register_student(
    api: ApiClient, home_school_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Register one student under the given sending school."""
    return get_success_data(
        api.create_student(
            f.student_payload(home_school_id, **overrides), REGISTRAR_HEADERS
        )
    )


def post_prior_record(
    api: ApiClient, student_id: str, course_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Post one historical transcript row; a FAILED row unless overridden."""
    return get_success_data(
        api.create_prior_course_record(
            f.prior_course_record_payload(student_id, course_id, **overrides),
            REGISTRAR_HEADERS,
        )
    )


def open_plan(api: ApiClient, student_id: str, **overrides: Any) -> Dict[str, Any]:
    """Open a graduation plan, which begins in DRAFT."""
    return get_success_data(
        api.create_graduation_plan(
            f.graduation_plan_payload(student_id, **overrides), REGISTRAR_HEADERS
        )
    )


def activate_plan(api: ApiClient, plan_id: str, **payload: Any) -> Dict[str, Any]:
    """Move a DRAFT plan to ACTIVE so credit may be awarded against it."""
    return get_success_data(
        api.activate_graduation_plan(plan_id, dict(payload), REGISTRAR_HEADERS)
    )


def open_active_plan(api: ApiClient, student_id: str, **overrides: Any) -> Dict[str, Any]:
    """Open a plan and activate it in one step, returning the ACTIVE plan."""
    plan = open_plan(api, student_id, **overrides)
    return activate_plan(api, plan["id"])


def register_station(api: ApiClient, center_id: str, **overrides: Any) -> Dict[str, Any]:
    """Register one proctoring station at the centre."""
    return get_success_data(
        api.create_proctor_station(
            f.proctor_station_payload(center_id, **overrides), DISTRICT_ADMIN_HEADERS
        )
    )


def assign_provider(api: ApiClient, center_id: str, **overrides: Any) -> Dict[str, Any]:
    """Assign one on-site support provider to the centre."""
    return get_success_data(
        api.create_support_provider(
            f.support_provider_payload(center_id, **overrides), DISTRICT_ADMIN_HEADERS
        )
    )


def read_center(api: ApiClient, center_id: str) -> Dict[str, Any]:
    """Read the centre with its live derivations."""
    return get_success_data(api.get_center(center_id, DISTRICT_ADMIN_HEADERS))


def center_version(api: ApiClient, center_id: str) -> int:
    """The centre's current version, for the optimistic-concurrency guard."""
    return read_center(api, center_id)["version"]


def read_placement(api: ApiClient, placement_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_placement(placement_id, DISTRICT_ADMIN_HEADERS))


def placement_version(api: ApiClient, placement_id: str) -> int:
    return read_placement(api, placement_id)["version"]


def read_plan(api: ApiClient, plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_graduation_plan(plan_id, REGISTRAR_HEADERS))


def plan_version(api: ApiClient, plan_id: str) -> int:
    return read_plan(api, plan_id)["version"]


def read_student(api: ApiClient, student_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_student(student_id, REGISTRAR_HEADERS))


def read_enrollment(api: ApiClient, enrollment_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_course_enrollment(enrollment_id, REGISTRAR_HEADERS)
    )


def read_referral(api: ApiClient, referral_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_referral(referral_id, DISTRICT_ADMIN_HEADERS))


def read_prior_record(api: ApiClient, record_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_prior_course_record(record_id, REGISTRAR_HEADERS))


def read_award(api: ApiClient, award_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_credit_award(award_id, REGISTRAR_HEADERS))


def read_station(api: ApiClient, station_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_proctor_station(station_id, DISTRICT_ADMIN_HEADERS))


def read_provider(api: ApiClient, provider_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_support_provider(provider_id, DISTRICT_ADMIN_HEADERS)
    )


def read_home_school(api: ApiClient, home_school_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_home_school(home_school_id, DISTRICT_ADMIN_HEADERS))


# ==========================================================================
# Tier 2 — short chains through the referral flow
# ==========================================================================
def submit_referral(
    api: ApiClient,
    student_id: str,
    center_id: str,
    home_school_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Author a referral as the sending school's counsellor."""
    return get_success_data(
        api.create_referral(
            f.referral_payload(student_id, center_id, **overrides),
            make_home_school_counselor_headers(home_school_id),
        )
    )


def screen_referral(api: ApiClient, referral_id: str, center_id: str) -> Dict[str, Any]:
    """Take a SUBMITTED referral into screening at the receiving centre."""
    return get_success_data(
        api.screen_referral(
            referral_id, f.screen_payload(), make_placement_coordinator_headers(center_id)
        )
    )


def screened_referral(
    api: ApiClient,
    student_id: str,
    center_id: str,
    home_school_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """A referral sitting in SCREENING, ready for a seating decision."""
    referral = submit_referral(api, student_id, center_id, home_school_id, **overrides)
    return screen_referral(api, referral["id"], center_id)


def offer_seat(
    api: ApiClient,
    referral_id: str,
    center_id: str,
    expected_center_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Offer a seat, reserving centre capacity."""
    version = (
        expected_center_version
        if expected_center_version is not None
        else center_version(api, center_id)
    )
    return get_success_data(
        api.offer_referral(
            referral_id,
            f.offer_payload(version, **overrides),
            make_placement_coordinator_headers(center_id),
        )
    )


def waitlist_referral(
    api: ApiClient, referral_id: str, center_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Waitlist a screened referral, which reserves no seat."""
    return get_success_data(
        api.waitlist_referral(
            referral_id,
            f.waitlist_payload(**overrides),
            make_placement_coordinator_headers(center_id),
        )
    )


def offered_referral(
    api: ApiClient,
    student_id: str,
    center_id: str,
    home_school_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """A referral holding an outstanding seat offer."""
    referral = screened_referral(
        api, student_id, center_id, home_school_id, **overrides
    )
    return offer_seat(api, referral["id"], center_id)


def accept_seat(
    api: ApiClient,
    referral_id: str,
    home_school_id: str,
    credit_policy: str = CreditPolicy.SEAT_TIME.value,
    **overrides: Any,
) -> Dict[str, Any]:
    """Accept the offer, creating the placement under the chosen credit policy."""
    return get_success_data(
        api.accept_offer(
            referral_id,
            f.accept_offer_payload(credit_policy=credit_policy, **overrides),
            make_home_school_counselor_headers(home_school_id),
        )
    )


# ==========================================================================
# Tier 3 — a placed student with coursework
# ==========================================================================
def place_student(
    api: ApiClient,
    credit_policy: str = CreditPolicy.SEAT_TIME.value,
    center_overrides: Optional[Dict[str, Any]] = None,
    student_overrides: Optional[Dict[str, Any]] = None,
    referral_overrides: Optional[Dict[str, Any]] = None,
    **_: Any,
) -> Dict[str, Any]:
    """Stand up a school, a centre and a student, then walk the referral all
    the way to an ACTIVE placement.

    Returns a dictionary keyed ``home_school``, ``center``, ``student``,
    ``referral`` and ``placement``.
    """
    home_school = open_home_school(api)
    center = open_center(api, **(center_overrides or {}))
    student = register_student(api, home_school["id"], **(student_overrides or {}))
    referral = screened_referral(
        api,
        student["id"],
        center["id"],
        home_school["id"],
        **(referral_overrides or {}),
    )
    offer_seat(api, referral["id"], center["id"])
    placement = accept_seat(
        api, referral["id"], home_school["id"], credit_policy=credit_policy
    )
    return {
        "home_school": home_school,
        "center": center,
        "student": student,
        "referral": read_referral(api, referral["id"]),
        "placement": placement,
    }


def enroll_new_credit(
    api: ApiClient,
    placement_id: str,
    course_id: str,
    expected_placement_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Enrol a placed student in a catalogue course as new credit."""
    version = (
        expected_placement_version
        if expected_placement_version is not None
        else placement_version(api, placement_id)
    )
    return get_success_data(
        api.create_course_enrollment(
            f.new_credit_enrollment_payload(
                placement_id, course_id, version, **overrides
            ),
            ALT_ED_TEACHER_HEADERS,
        )
    )


def enroll_recovery(
    api: ApiClient,
    placement_id: str,
    course_id: str,
    prior_course_record_id: Optional[str],
    expected_placement_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Enrol a placed student in a course they previously failed."""
    version = (
        expected_placement_version
        if expected_placement_version is not None
        else placement_version(api, placement_id)
    )
    return get_success_data(
        api.create_course_enrollment(
            f.recovery_enrollment_payload(
                placement_id, course_id, prior_course_record_id, version, **overrides
            ),
            ALT_ED_TEACHER_HEADERS,
        )
    )


def report_progress(api: ApiClient, enrollment_id: str, **payload: Any) -> Dict[str, Any]:
    """Report modules, seat hours or the running module average."""
    return get_success_data(
        api.report_progress(enrollment_id, dict(payload), ALT_ED_TEACHER_HEADERS)
    )


def log_attendance(
    api: ApiClient, placement_id: str, days_present: int, days_enrolled: int
) -> Dict[str, Any]:
    """Advance the placement's attendance accumulators."""
    return get_success_data(
        api.log_attendance(
            placement_id,
            f.attendance_payload(days_present, days_enrolled),
            ALT_ED_TEACHER_HEADERS,
        )
    )


def submit_work(
    api: ApiClient, enrollment_id: str, final_percent: float, headers: Any = None
) -> Dict[str, Any]:
    """Submit completed work for award, recording the final course percent."""
    return get_success_data(
        api.submit_for_award(
            enrollment_id,
            f.submit_for_award_payload(final_percent),
            headers if headers is not None else ALT_ED_TEACHER_HEADERS,
        )
    )


def award_credit(
    api: ApiClient,
    enrollment_id: str,
    plan_id: str,
    headers: Any = None,
    expected_graduation_plan_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Award credit for a submitted enrollment, posting the transcript row."""
    version = (
        expected_graduation_plan_version
        if expected_graduation_plan_version is not None
        else plan_version(api, plan_id)
    )
    return get_success_data(
        api.award_credit(
            enrollment_id,
            f.award_credit_payload(version),
            headers if headers is not None else REGISTRAR_HEADERS,
        )
    )


def flag_enrollment(api: ApiClient, enrollment_id: str, **overrides: Any) -> Dict[str, Any]:
    """Raise an academic integrity flag, holding progress and award activity."""
    return get_success_data(
        api.flag_integrity(
            enrollment_id, f.flag_integrity_payload(**overrides), DISTRICT_ADMIN_HEADERS
        )
    )


def resolve_enrollment(
    api: ApiClient, enrollment_id: str, resolution: str, **overrides: Any
) -> Dict[str, Any]:
    """Resolve a flagged enrollment as CLEARED or VOIDED_FOR_INTEGRITY."""
    return get_success_data(
        api.resolve_integrity(
            enrollment_id,
            f.resolve_integrity_payload(resolution, **overrides),
            DISTRICT_ADMIN_HEADERS,
        )
    )


def book_proctor_session(
    api: ApiClient,
    enrollment_id: str,
    station_id: str,
    center_id: str,
    scheduled_start: str = "2026-08-10T09:00:00.000Z",
    scheduled_end: str = "2026-08-10T11:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Book a proctored exam slot on the station."""
    return get_success_data(
        api.create_proctor_session(
            f.proctor_session_payload(
                enrollment_id,
                station_id,
                scheduled_start,
                scheduled_end,
                **overrides,
            ),
            make_placement_coordinator_headers(center_id),
        )
    )


def complete_proctor_session(
    api: ApiClient,
    session_id: str,
    center_id: str,
    score_percent: float,
    **overrides: Any,
) -> Dict[str, Any]:
    """Record the proctored exam result and any integrity incident observed."""
    return get_success_data(
        api.complete_proctor_session(
            session_id,
            f.complete_proctor_session_payload(score_percent, **overrides),
            make_placement_coordinator_headers(center_id),
        )
    )


def schedule_support_session(
    api: ApiClient,
    provider_id: str,
    placement_id: str,
    center_id: str,
    start_at: str = "2026-08-10T13:00:00.000Z",
    end_at: str = "2026-08-10T14:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Schedule an on-site support service for the placement."""
    return get_success_data(
        api.create_support_session(
            f.support_session_payload(
                provider_id, placement_id, start_at, end_at, **overrides
            ),
            make_placement_coordinator_headers(center_id),
        )
    )


def complete_support_session(
    api: ApiClient, session_id: str, provider_id: str, minutes_delivered: int = 60
) -> Dict[str, Any]:
    """Record delivery of a support service, which only the provider may do."""
    return get_success_data(
        api.complete_support_session(
            session_id,
            f.complete_support_session_payload(minutes_delivered),
            make_support_provider_staff_headers(provider_id),
        )
    )


def deliver_support_sessions(
    api: ApiClient,
    provider_id: str,
    placement_id: str,
    center_id: str,
    count: int,
) -> List[Dict[str, Any]]:
    """Schedule and complete ``count`` non-overlapping support sessions."""
    delivered = []
    for index in range(count):
        hour = 13 + index * 2
        session = schedule_support_session(
            api,
            provider_id,
            placement_id,
            center_id,
            start_at=f"2026-08-10T{hour:02d}:00:00.000Z",
            end_at=f"2026-08-10T{hour + 1:02d}:00:00.000Z",
        )
        delivered.append(
            complete_support_session(api, session["id"], provider_id)
        )
    return delivered


# ==========================================================================
# Tier 4 — scenarios tuned to a numeric or postural outcome
# ==========================================================================
def recovery_world(
    api: ApiClient,
    credit_policy: str = CreditPolicy.SEAT_TIME.value,
    grade_replacement_policy: str = GradeReplacementPolicy.REPLACE_ON_RECOVERY.value,
    course_overrides: Optional[Dict[str, Any]] = None,
    plan_overrides: Optional[Dict[str, Any]] = None,
    prior_overrides: Optional[Dict[str, Any]] = None,
    referral_overrides: Optional[Dict[str, Any]] = None,
    center_overrides: Optional[Dict[str, Any]] = None,
    student_overrides: Optional[Dict[str, Any]] = None,
    activate: bool = True,
) -> Dict[str, Any]:
    """A placed student enrolled in a course they previously failed.

    Returns ``home_school``, ``center``, ``student``, ``course``,
    ``prior_record``, ``plan``, ``referral``, ``placement`` and ``enrollment``.
    """
    home_school = open_home_school(api)
    center = open_center(api, **(center_overrides or {}))
    course = publish_course(api, **(course_overrides or {}))
    student = register_student(api, home_school["id"], **(student_overrides or {}))
    prior_record = post_prior_record(
        api, student["id"], course["id"], **(prior_overrides or {})
    )
    plan = open_plan(
        api,
        student["id"],
        grade_replacement_policy=grade_replacement_policy,
        **(plan_overrides or {}),
    )
    if activate:
        plan = activate_plan(api, plan["id"])
    referral = screened_referral(
        api,
        student["id"],
        center["id"],
        home_school["id"],
        **(referral_overrides or {}),
    )
    offer_seat(api, referral["id"], center["id"])
    placement = accept_seat(
        api, referral["id"], home_school["id"], credit_policy=credit_policy
    )
    enrollment = enroll_recovery(
        api, placement["id"], course["id"], prior_record["id"]
    )
    return {
        "home_school": home_school,
        "center": center,
        "student": student,
        "course": course,
        "prior_record": prior_record,
        "plan": plan,
        "referral": referral,
        "placement": placement,
        "enrollment": enrollment,
    }


def new_credit_world(
    api: ApiClient,
    credit_policy: str = CreditPolicy.SEAT_TIME.value,
    course_overrides: Optional[Dict[str, Any]] = None,
    plan_overrides: Optional[Dict[str, Any]] = None,
    referral_overrides: Optional[Dict[str, Any]] = None,
    center_overrides: Optional[Dict[str, Any]] = None,
    student_overrides: Optional[Dict[str, Any]] = None,
    activate: bool = True,
) -> Dict[str, Any]:
    """A placed student enrolled in a course as new credit, with an ACTIVE plan."""
    home_school = open_home_school(api)
    center = open_center(api, **(center_overrides or {}))
    course = publish_course(api, **(course_overrides or {}))
    student = register_student(api, home_school["id"], **(student_overrides or {}))
    plan = open_plan(api, student["id"], **(plan_overrides or {}))
    if activate:
        plan = activate_plan(api, plan["id"])
    referral = screened_referral(
        api,
        student["id"],
        center["id"],
        home_school["id"],
        **(referral_overrides or {}),
    )
    offer_seat(api, referral["id"], center["id"])
    placement = accept_seat(
        api, referral["id"], home_school["id"], credit_policy=credit_policy
    )
    enrollment = enroll_new_credit(api, placement["id"], course["id"])
    return {
        "home_school": home_school,
        "center": center,
        "student": student,
        "course": course,
        "plan": plan,
        "referral": referral,
        "placement": placement,
        "enrollment": enrollment,
    }


def submitted_world(
    api: ApiClient,
    final_percent: float = 86.00,
    progress: Optional[Dict[str, Any]] = None,
    recovery: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A world whose enrollment sits in SUBMITTED_FOR_AWARD."""
    world = (
        recovery_world(api, **kwargs) if recovery else new_credit_world(api, **kwargs)
    )
    if progress:
        report_progress(api, world["enrollment"]["id"], **progress)
    world["enrollment"] = submit_work(api, world["enrollment"]["id"], final_percent)
    return world


def awarded_world(
    api: ApiClient,
    final_percent: float = 86.00,
    progress: Optional[Dict[str, Any]] = None,
    recovery: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A world whose enrollment has a POSTED credit award, added under key
    ``award``.  The award is posted by the second registrar so segregation of
    duties is satisfied."""
    world = submitted_world(
        api, final_percent=final_percent, progress=progress, recovery=recovery, **kwargs
    )
    from .test_users import REGISTRAR_ALT_HEADERS

    world["award"] = award_credit(
        api, world["enrollment"]["id"], world["plan"]["id"], REGISTRAR_ALT_HEADERS
    )
    return world


def re_entry_ready_world(
    api: ApiClient, days_present: int = 45, days_enrolled: int = 50
) -> Dict[str, Any]:
    """A SEAT_TIME placement whose attendance rate is exactly 0.9000 and whose
    readiness score is 0.7800, with an ON_TRACK plan, so a re-entry request
    passes every gate.

    Built to the same shape the numeric design expects: a grade-9 student with
    a PASSED prior row worth 1.00 credit against a 4.00-credit plan, one
    enrollment holding all eight modules, one completed support session, the
    clock advanced ten days and attendance of 45 of 50 days.
    """
    home_school = open_home_school(api)
    center = open_center(api)
    course = publish_course(api, total_modules=8, pacing_days=40)
    other_course = publish_course(api, subject_area=SubjectArea.ELA.value)
    student = register_student(api, home_school["id"], grade_level=9, cohort_year=2029)
    passed_record = post_prior_record(
        api,
        student["id"],
        other_course["id"],
        original_percent=81.00,
        credits_attempted=1.00,
        outcome=PriorOutcome.PASSED.value,
    )
    plan = open_active_plan(api, student["id"], required_credits_total=4.00)
    referral = screened_referral(
        api,
        student["id"],
        center["id"],
        home_school["id"],
        deficiency_credits=4.00,
        behavior_incident_count=1,
        days_disengaged=6,
    )
    offer_seat(api, referral["id"], center["id"])
    placement = accept_seat(
        api,
        referral["id"],
        home_school["id"],
        credit_policy=CreditPolicy.SEAT_TIME.value,
    )
    enrollment = enroll_new_credit(api, placement["id"], course["id"])
    report_progress(
        api,
        enrollment["id"],
        modules_passed_delta=8,
        seat_hours_delta=45.00,
        module_avg_percent=86.00,
    )
    provider = assign_provider(api, center["id"])
    session = schedule_support_session(
        api,
        provider["id"],
        placement["id"],
        center["id"],
        start_at="2026-08-04T13:00:00.000Z",
        end_at="2026-08-04T14:00:00.000Z",
    )
    complete_support_session(api, session["id"], provider["id"])
    get_success_data(
        api.advance_clock_to("2026-08-11T00:00:00Z", DISTRICT_ADMIN_HEADERS)
    )
    placement = log_attendance(api, placement["id"], days_present, days_enrolled)
    return {
        "home_school": home_school,
        "center": center,
        "course": course,
        "other_course": other_course,
        "student": student,
        "passed_record": passed_record,
        "plan": plan,
        "referral": referral,
        "placement": placement,
        "enrollment": enrollment,
        "provider": provider,
        "support_session": session,
    }


def proctored_world(
    api: ApiClient,
    credit_policy: str = CreditPolicy.COMPETENCY.value,
    course_overrides: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A placed student on an ONLINE course with a station registered at the
    centre, ready for a proctored exam booking."""
    overrides = {"modality": Modality.ONLINE.value, "proctoring_required": True}
    overrides.update(course_overrides or {})
    world = new_credit_world(
        api, credit_policy=credit_policy, course_overrides=overrides, **kwargs
    )
    world["station"] = register_station(api, world["center"]["id"])
    return world


def support_world(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """A placed student with one on-site support provider at the centre."""
    world = place_student(api, **kwargs)
    world["provider"] = assign_provider(api, world["center"]["id"])
    return world


def frozen_center_world(api: ApiClient) -> Dict[str, Any]:
    """A centre whose intake posture reads FROZEN because a single funded seat
    is already occupied by an ACTIVE placement.

    Capacity 1 with a 0.25 FTE teacher carrying at most four students gives a
    headroom of one seat before the placement, so the acceptance drives both
    available seats and headroom to zero.
    """
    home_school = open_home_school(api)
    center = open_center(
        api,
        seat_capacity=1,
        certified_teacher_fte=0.25,
        support_staff_fte=0.00,
        max_students_per_teacher=4,
    )
    seated_student = register_student(api, home_school["id"])
    referral = screened_referral(
        api, seated_student["id"], center["id"], home_school["id"]
    )
    offer_seat(api, referral["id"], center["id"])
    placement = accept_seat(api, referral["id"], home_school["id"])
    waiting_student = register_student(api, home_school["id"])
    waiting_referral = screened_referral(
        api, waiting_student["id"], center["id"], home_school["id"]
    )
    return {
        "home_school": home_school,
        "center": read_center(api, center["id"]),
        "seated_student": seated_student,
        "placement": placement,
        "waiting_student": waiting_student,
        "waiting_referral": waiting_referral,
    }


def restricted_center_world(api: ApiClient) -> Dict[str, Any]:
    """A centre whose intake posture reads RESTRICTED because its staffing
    headroom has fallen to exactly one seat.

    A 0.50 FTE teacher carrying at most four students gives a headroom of two;
    one ACTIVE placement leaves one, which is the RESTRICTED branch, while ten
    funded seats keep the seat cushion clear.
    """
    home_school = open_home_school(api)
    center = open_center(
        api,
        seat_capacity=10,
        certified_teacher_fte=0.50,
        support_staff_fte=0.00,
        max_students_per_teacher=4,
    )
    seated_student = register_student(api, home_school["id"])
    referral = screened_referral(
        api, seated_student["id"], center["id"], home_school["id"]
    )
    offer_seat(api, referral["id"], center["id"])
    placement = accept_seat(api, referral["id"], home_school["id"])
    return {
        "home_school": home_school,
        "center": read_center(api, center["id"]),
        "seated_student": seated_student,
        "placement": placement,
    }


# ==========================================================================
# Tier 5 — a whole district with several actors
# ==========================================================================
def district_world(api: ApiClient, student_count: int = 2) -> Dict[str, Any]:
    """One school, one centre, one catalogue course and several students, none
    of them referred yet.  Returns ``students`` as a list."""
    home_school = open_home_school(api)
    center = open_center(api)
    course = publish_course(api)
    students = [
        register_student(api, home_school["id"]) for _ in range(student_count)
    ]
    return {
        "home_school": home_school,
        "center": center,
        "course": course,
        "students": students,
    }


def two_center_world(api: ApiClient) -> Dict[str, Any]:
    """Two schools and two centres, each with its own placed student, so a
    scope-bound role can be pointed at a resource it does not own."""
    first = place_student(api)
    second = place_student(api)
    return {"first": first, "second": second}


def waitlist_world(api: ApiClient) -> Dict[str, Any]:
    """A centre with one seat, one ACTIVE placement holding it and one
    WAITLISTED referral queued behind it, so releasing the seat promotes."""
    home_school = open_home_school(api)
    center = open_center(
        api,
        seat_capacity=1,
        certified_teacher_fte=1.00,
        support_staff_fte=0.00,
        max_students_per_teacher=10,
    )
    seated_student = register_student(api, home_school["id"])
    seated_referral = screened_referral(
        api, seated_student["id"], center["id"], home_school["id"]
    )
    offer_seat(api, seated_referral["id"], center["id"])
    placement = accept_seat(api, seated_referral["id"], home_school["id"])
    waiting_student = register_student(api, home_school["id"])
    waiting_referral = screened_referral(
        api,
        waiting_student["id"],
        center["id"],
        home_school["id"],
        pathway=Pathway.BEHAVIOR.value,
        behavior_incident_count=5,
    )
    waiting_referral = waitlist_referral(
        api, waiting_referral["id"], center["id"]
    )
    return {
        "home_school": home_school,
        "center": read_center(api, center["id"]),
        "seated_student": seated_student,
        "placement": placement,
        "waiting_student": waiting_student,
        "waiting_referral": waiting_referral,
    }
