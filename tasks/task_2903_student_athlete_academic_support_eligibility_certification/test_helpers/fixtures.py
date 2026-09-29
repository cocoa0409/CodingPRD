"""Composite setup helpers.

The harness restarts the API server before every individual test, so each test
begins against an empty database.  Everything a test needs is therefore built
here from scratch through public PRD endpoints; nothing reaches into storage.

The helpers are layered:

* tier 1 - thin single-call wrappers returning the created row;
* tier 2 - short two- or three-call compositions (a trained tutor, a
  travel-approved event, an active assignment, a closed term);
* tier 3 - catalogue bundles (terms + program + courses + applicability);
* tier 4 - student journeys (completed credits, draft/submitted/decided
  certifications, appeals in committee review);
* tier 5 - whole-scenario worlds combining the above.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import OMIT, AthleticsApiClient
from .constants import (
    APPLICABILITY_CORE,
    CERT_ACTION_CERTIFY,
    CERT_ACTION_DENY,
    CERT_ACTION_REVOKE,
    CERT_ACTION_SUBMIT,
    CERT_TYPE_CONTINUING,
    CERT_TYPE_INITIAL,
    DEFAULT_CLOCK,
    EVENT_ACTION_APPROVE_TRAVEL,
    INCIDENT_ACTION_OPEN,
    MCR_ACTION_NOTIFY,
    SEVERITY_LEVEL_III,
    TUTOR_ACTION_COMPLETE_TRAINING,
)
from .test_users import (
    ADVISOR,
    CERT_OFFICER,
    CERT_OFFICER_ALT,
    COMMITTEE,
    COMPLIANCE,
    OPERATIONS,
    REGISTRAR,
    SPECIALIST,
    instructor_headers,
)
from .types import EntityId, Headers, JsonObject, Payload

# ---------------------------------------------------------------------------
# The standard academic calendar used by most scenarios.  Windows never
# overlap, and every term shares catalog year 2026 so that the two audit
# variants coincide unless a test deliberately diverges them.
# ---------------------------------------------------------------------------
STANDARD_TERMS: List[Dict[str, Any]] = [
    {
        "code": "2026FA",
        "term_index": 1,
        "term_type": "FALL",
        "start_date": "2026-08-24T00:00:00Z",
        "end_date": "2026-12-18T00:00:00Z",
    },
    {
        "code": "2027SP",
        "term_index": 2,
        "term_type": "SPRING",
        "start_date": "2027-01-11T00:00:00Z",
        "end_date": "2027-05-14T00:00:00Z",
    },
    {
        "code": "2027SU",
        "term_index": 3,
        "term_type": "SUMMER",
        "start_date": "2027-06-01T00:00:00Z",
        "end_date": "2027-07-30T00:00:00Z",
    },
    {
        "code": "2027FA",
        "term_index": 4,
        "term_type": "FALL",
        "start_date": "2027-08-23T00:00:00Z",
        "end_date": "2027-12-17T00:00:00Z",
    },
    {
        "code": "2028SP",
        "term_index": 5,
        "term_type": "SPRING",
        "start_date": "2028-01-10T00:00:00Z",
        "end_date": "2028-05-12T00:00:00Z",
    },
    {
        "code": "2028SU",
        "term_index": 6,
        "term_type": "SUMMER",
        "start_date": "2028-06-05T00:00:00Z",
        "end_date": "2028-08-04T00:00:00Z",
    },
]


class Ctx:
    """A tiny attribute bag for scenario output."""

    def __init__(self, **kwargs: Any):
        self.__dict__.update(kwargs)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        keys = ", ".join(sorted(self.__dict__))
        return f"Ctx({keys})"


# ===========================================================================
# Tier 1 - single-call wrappers
# ===========================================================================
def set_clock(
    api: AthleticsApiClient, when: str, headers: Headers = REGISTRAR
) -> JsonObject:
    return get_success_data(api.set_clock(when, headers))


def make_term(
    api: AthleticsApiClient,
    index: int = 1,
    catalog_year: int = 2026,
    headers: Headers = REGISTRAR,
    **overrides: Any,
) -> JsonObject:
    """Create the ``index``-th standard term, optionally overriding fields."""
    spec = dict(STANDARD_TERMS[index - 1])
    payload = f.term(
        code=spec["code"],
        term_index=spec["term_index"],
        start_date=spec["start_date"],
        end_date=spec["end_date"],
        term_type=spec["term_type"],
        catalog_year=catalog_year,
        **overrides,
    )
    return get_success_data(api.create_term(payload, headers))


def make_term_raw(
    api: AthleticsApiClient, payload: Payload, headers: Headers = REGISTRAR
) -> JsonObject:
    return get_success_data(api.create_term(payload, headers))


def make_program(
    api: AthleticsApiClient, headers: Headers = REGISTRAR, **overrides: Any
) -> JsonObject:
    return get_success_data(
        api.create_degree_program(f.degree_program(**overrides), headers)
    )


def make_course(
    api: AthleticsApiClient, headers: Headers = REGISTRAR, **overrides: Any
) -> JsonObject:
    if "course_number" not in overrides:
        overrides["course_number"] = str(300 + f.next_seq())
    return get_success_data(api.create_course(f.course(**overrides), headers))


def make_rule(
    api: AthleticsApiClient,
    degree_program_id: EntityId,
    course_id: EntityId,
    effective_catalog_year: int = 2026,
    applicability: str = APPLICABILITY_CORE,
    headers: Headers = REGISTRAR,
    **overrides: Any,
) -> JsonObject:
    payload = f.applicability_rule(
        degree_program_id,
        course_id,
        effective_catalog_year=effective_catalog_year,
        applicability=applicability,
        **overrides,
    )
    return get_success_data(api.create_applicability_rule(payload, headers))


def make_student(
    api: AthleticsApiClient, headers: Headers = REGISTRAR, **overrides: Any
) -> JsonObject:
    return get_success_data(api.create_student(f.student(**overrides), headers))


def make_enrollment(
    api: AthleticsApiClient,
    student_athlete_id: EntityId,
    course_id: EntityId,
    term_id: EntityId,
    headers: Headers = REGISTRAR,
    **overrides: Any,
) -> JsonObject:
    payload = f.enrollment(student_athlete_id, course_id, term_id, **overrides)
    return get_success_data(api.create_enrollment(payload, headers))


def record_grade(
    api: AthleticsApiClient,
    enrollment_id: EntityId,
    grade: str,
    headers: Headers = REGISTRAR,
) -> JsonObject:
    return get_success_data(
        api.record_outcome(enrollment_id, f.record_grade(grade), headers)
    )


def record_outcome(
    api: AthleticsApiClient,
    enrollment_id: EntityId,
    action: str,
    headers: Headers = REGISTRAR,
) -> JsonObject:
    return get_success_data(
        api.record_outcome(enrollment_id, f.action(action), headers)
    )


def declare_major(
    api: AthleticsApiClient,
    student_athlete_id: EntityId,
    declared_program_id: EntityId,
    term_id: EntityId,
    headers: Headers = REGISTRAR,
) -> JsonObject:
    payload = f.major_declaration(declared_program_id, term_id)
    return get_success_data(api.declare_major(student_athlete_id, payload, headers))


def read_student(
    api: AthleticsApiClient, student_athlete_id: EntityId, headers: Headers = REGISTRAR
) -> JsonObject:
    return get_success_data(api.get_student(student_athlete_id, headers))


def read_tutor(
    api: AthleticsApiClient, tutor_id: EntityId, headers: Headers = SPECIALIST
) -> JsonObject:
    return get_success_data(api.get_tutor(tutor_id, headers))


def read_certification(
    api: AthleticsApiClient,
    certification_id: EntityId,
    headers: Headers = CERT_OFFICER,
) -> JsonObject:
    return get_success_data(api.get_certification(certification_id, headers))


def student_version(
    api: AthleticsApiClient, student_athlete_id: EntityId
) -> int:
    """Read the student's current ``version`` for optimistic concurrency."""
    return read_student(api, student_athlete_id)["version"]


def make_tutor(
    api: AthleticsApiClient, headers: Headers = SPECIALIST, **overrides: Any
) -> JsonObject:
    return get_success_data(api.create_tutor(f.tutor(**overrides), headers))


def make_assignment(
    api: AthleticsApiClient,
    tutor_id: EntityId,
    enrollment_id: EntityId,
    weekly_hours: float = 2.0,
    headers: Headers = SPECIALIST,
) -> JsonObject:
    payload = f.assignment(tutor_id, enrollment_id, weekly_hours)
    return get_success_data(api.create_assignment(payload, headers))


def assignment_action(
    api: AthleticsApiClient,
    assignment_id: EntityId,
    action: str,
    headers: Headers = SPECIALIST,
    **extra: Any,
) -> JsonObject:
    return get_success_data(
        api.assignment_status(assignment_id, f.action(action, **extra), headers)
    )


def tutor_action(
    api: AthleticsApiClient,
    tutor_id: EntityId,
    action: str,
    headers: Headers = SPECIALIST,
    **extra: Any,
) -> JsonObject:
    return get_success_data(
        api.tutor_status(tutor_id, f.action(action, **extra), headers)
    )


def make_session(
    api: AthleticsApiClient,
    student_athlete_id: EntityId,
    start_at: str,
    end_at: str,
    headers: Headers = SPECIALIST,
    **overrides: Any,
) -> JsonObject:
    payload = f.session(student_athlete_id, start_at, end_at, **overrides)
    return get_success_data(api.create_session(payload, headers))


def make_event(
    api: AthleticsApiClient,
    term_id: EntityId,
    departure_at: str,
    return_at: str,
    headers: Headers = OPERATIONS,
    **overrides: Any,
) -> JsonObject:
    payload = f.event(term_id, departure_at, return_at, **overrides)
    return get_success_data(api.create_event(payload, headers))


def event_action(
    api: AthleticsApiClient,
    event_id: EntityId,
    action: str,
    headers: Headers = OPERATIONS,
) -> JsonObject:
    return get_success_data(api.event_status(event_id, f.action(action), headers))


def make_request(
    api: AthleticsApiClient,
    competition_event_id: EntityId,
    enrollment_id: EntityId,
    headers: Headers = ADVISOR,
) -> JsonObject:
    payload = f.missed_class_request(competition_event_id, enrollment_id)
    return get_success_data(api.create_missed_class_request(payload, headers))


def request_action(
    api: AthleticsApiClient,
    request_id: EntityId,
    action: str,
    headers: Headers = ADVISOR,
    **extra: Any,
) -> JsonObject:
    return get_success_data(
        api.missed_class_request_status(request_id, f.action(action, **extra), headers)
    )


def make_appeal(
    api: AthleticsApiClient,
    certification_id: EntityId,
    headers: Headers = ADVISOR,
    **overrides: Any,
) -> JsonObject:
    payload = f.appeal(certification_id, **overrides)
    return get_success_data(api.create_appeal(payload, headers))


def appeal_action(
    api: AthleticsApiClient,
    appeal_id: EntityId,
    action: str,
    headers: Headers = COMMITTEE,
    **extra: Any,
) -> JsonObject:
    return get_success_data(
        api.appeal_status(appeal_id, f.action(action, **extra), headers)
    )


def make_incident(
    api: AthleticsApiClient,
    student_athlete_id: EntityId,
    headers: Headers = COMPLIANCE,
    **overrides: Any,
) -> JsonObject:
    payload = f.incident(student_athlete_id, **overrides)
    return get_success_data(api.create_incident(payload, headers))


def incident_action(
    api: AthleticsApiClient,
    incident_id: EntityId,
    action: str,
    headers: Headers = COMPLIANCE,
    **extra: Any,
) -> JsonObject:
    return get_success_data(
        api.incident_status(incident_id, f.action(action, **extra), headers)
    )


# ===========================================================================
# Tier 2 - short compositions
# ===========================================================================
def make_trained_tutor(
    api: AthleticsApiClient,
    term_id: EntityId,
    subject_codes: Optional[Sequence[str]] = None,
    headers: Headers = SPECIALIST,
    **overrides: Any,
) -> JsonObject:
    """Register a tutor and complete its compliance training in ``term_id``."""
    tutor_row = make_tutor(
        api,
        headers=headers,
        subject_codes=list(subject_codes) if subject_codes else ["KINE"],
        **overrides,
    )
    return tutor_action(
        api,
        tutor_row["id"],
        TUTOR_ACTION_COMPLETE_TRAINING,
        headers=headers,
        term_id=term_id,
    )


def make_active_assignment(
    api: AthleticsApiClient,
    tutor_id: EntityId,
    enrollment_id: EntityId,
    weekly_hours: float = 2.0,
    headers: Headers = SPECIALIST,
) -> JsonObject:
    """Propose an assignment and activate it so it reserves capacity."""
    row = make_assignment(api, tutor_id, enrollment_id, weekly_hours, headers)
    return assignment_action(api, row["id"], "ACTIVATE", headers)


def make_approved_event(
    api: AthleticsApiClient,
    term_id: EntityId,
    departure_at: str,
    return_at: str,
    headers: Headers = OPERATIONS,
    **overrides: Any,
) -> JsonObject:
    """Schedule an event and approve its travel so requests may be filed."""
    row = make_event(api, term_id, departure_at, return_at, headers, **overrides)
    return event_action(api, row["id"], EVENT_ACTION_APPROVE_TRAVEL, headers)


def make_notified_request(
    api: AthleticsApiClient,
    competition_event_id: EntityId,
    enrollment_id: EntityId,
    headers: Headers = ADVISOR,
) -> JsonObject:
    """Open a missed-class request and notify the instructor of record."""
    row = make_request(api, competition_event_id, enrollment_id, headers)
    return request_action(api, row["id"], MCR_ACTION_NOTIFY, headers)


def close_term(
    api: AthleticsApiClient,
    term_id: EntityId,
    at_or_after: str,
    headers: Headers = COMPLIANCE,
) -> JsonObject:
    """Advance the clock to ``at_or_after`` and close the term for reporting."""
    set_clock(api, at_or_after, headers)
    return get_success_data(api.apr_close(term_id, headers))


def substantiate_incident(
    api: AthleticsApiClient,
    incident_id: EntityId,
    severity: str = SEVERITY_LEVEL_III,
    headers: Headers = COMPLIANCE,
) -> JsonObject:
    """Open an investigation and substantiate it at the given severity."""
    incident_action(api, incident_id, INCIDENT_ACTION_OPEN, headers)
    return get_success_data(
        api.incident_status(incident_id, f.substantiate(severity), headers)
    )


# ===========================================================================
# Tier 3 - catalogue bundles
# ===========================================================================
def catalogue(
    api: AthleticsApiClient,
    term_count: int = 1,
    clock: str = DEFAULT_CLOCK,
    catalog_year: int = 2026,
    **program_overrides: Any,
) -> Ctx:
    """Set the clock, register ``term_count`` standard terms and one program."""
    set_clock(api, clock)
    terms = [
        make_term(api, index=i, catalog_year=catalog_year)
        for i in range(1, term_count + 1)
    ]
    program = make_program(api, catalog_year=catalog_year, **program_overrides)
    return Ctx(
        terms=terms,
        term=terms[0],
        term_id=terms[0]["id"],
        program=program,
        program_id=program["id"],
        catalog_year=catalog_year,
    )


def catalogue_with_course(
    api: AthleticsApiClient,
    term_count: int = 1,
    clock: str = DEFAULT_CLOCK,
    catalog_year: int = 2026,
    subject_code: str = "KINE",
    credit_hours: float = 4.0,
    applicability: str = APPLICABILITY_CORE,
    course_overrides: Optional[Dict[str, Any]] = None,
    **program_overrides: Any,
) -> Ctx:
    """A catalogue plus one course and its applicability rule."""
    ctx = catalogue(
        api,
        term_count=term_count,
        clock=clock,
        catalog_year=catalog_year,
        **program_overrides,
    )
    course_row = make_course(
        api,
        subject_code=subject_code,
        credit_hours=credit_hours,
        **(course_overrides or {}),
    )
    rule = make_rule(
        api,
        ctx.program_id,
        course_row["id"],
        effective_catalog_year=catalog_year,
        applicability=applicability,
    )
    ctx.course = course_row
    ctx.course_id = course_row["id"]
    ctx.rule = rule
    return ctx


# ===========================================================================
# Tier 4 - student journeys
# ===========================================================================
def enrolled_student(
    api: AthleticsApiClient,
    term_count: int = 1,
    clock: str = DEFAULT_CLOCK,
    catalog_year: int = 2026,
    subject_code: str = "KINE",
    credit_hours: float = 4.0,
    applicability: str = APPLICABILITY_CORE,
    declare_major_in_term: Optional[int] = None,
    student_overrides: Optional[Dict[str, Any]] = None,
    course_overrides: Optional[Dict[str, Any]] = None,
    **program_overrides: Any,
) -> Ctx:
    """A catalogue, a course, a student and one ``ENROLLED`` enrollment."""
    ctx = catalogue_with_course(
        api,
        term_count=term_count,
        clock=clock,
        catalog_year=catalog_year,
        subject_code=subject_code,
        credit_hours=credit_hours,
        applicability=applicability,
        course_overrides=course_overrides,
        **program_overrides,
    )
    student_row = make_student(api, **(student_overrides or {}))
    ctx.student = student_row
    ctx.student_id = student_row["id"]
    if declare_major_in_term is not None:
        ctx.student = declare_major(
            api,
            ctx.student_id,
            ctx.program_id,
            ctx.terms[declare_major_in_term - 1]["id"],
        )
    enrollment_row = make_enrollment(
        api, ctx.student_id, ctx.course_id, ctx.term_id
    )
    ctx.enrollment = enrollment_row
    ctx.enrollment_id = enrollment_row["id"]
    return ctx


def add_graded_course(
    api: AthleticsApiClient,
    ctx: Ctx,
    term: JsonObject,
    grade: str = "A",
    credit_hours: float = 4.0,
    subject_code: str = "KINE",
    applicability: str = APPLICABILITY_CORE,
    catalog_year: Optional[int] = None,
    credit_source: Any = OMIT,
    course_overrides: Optional[Dict[str, Any]] = None,
) -> JsonObject:
    """Add one course, enrol the student in ``term`` and grade it.

    Returns the graded enrollment row.
    """
    year = catalog_year if catalog_year is not None else ctx.catalog_year
    course_row = make_course(
        api,
        subject_code=subject_code,
        credit_hours=credit_hours,
        **(course_overrides or {}),
    )
    if applicability is not None:
        make_rule(
            api,
            ctx.program_id,
            course_row["id"],
            effective_catalog_year=year,
            applicability=applicability,
        )
    enrollment_row = make_enrollment(
        api,
        ctx.student_id,
        course_row["id"],
        term["id"],
        credit_source=credit_source,
    )
    if credit_source == "TRANSFER":
        # A transfer row is created directly in COMPLETED, which is terminal
        # for the outcome operation, so no grade is recorded against it.
        return enrollment_row
    return record_grade(api, enrollment_row["id"], grade)


def complete_full_time_term(
    api: AthleticsApiClient,
    ctx: Ctx,
    term: JsonObject,
    grade: str = "A",
    credits: float = 12.0,
    subject_code: str = "KINE",
    applicability: str = APPLICABILITY_CORE,
) -> JsonObject:
    """Give the student enough completed resident credit for a full-time term."""
    return add_graded_course(
        api,
        ctx,
        term,
        grade=grade,
        credit_hours=credits,
        subject_code=subject_code,
        applicability=applicability,
    )


def make_draft_certification(
    api: AthleticsApiClient,
    student_athlete_id: EntityId,
    term_id: EntityId,
    certification_type: str = CERT_TYPE_INITIAL,
    headers: Headers = CERT_OFFICER,
    **overrides: Any,
) -> JsonObject:
    """Create a ``DRAFT`` certification, reading the student version first."""
    payload = f.certification(
        student_athlete_id,
        term_id,
        student_version(api, student_athlete_id),
        certification_type=certification_type,
        **overrides,
    )
    return get_success_data(api.create_certification(payload, headers))


def submit_certification(
    api: AthleticsApiClient, certification_id: EntityId, headers: Headers = ADVISOR
) -> JsonObject:
    return get_success_data(
        api.certification_status(
            certification_id, f.action(CERT_ACTION_SUBMIT), headers
        )
    )


def certify(
    api: AthleticsApiClient,
    certification_id: EntityId,
    headers: Headers = CERT_OFFICER_ALT,
) -> JsonObject:
    return get_success_data(
        api.certification_status(
            certification_id, f.action(CERT_ACTION_CERTIFY), headers
        )
    )


def deny_certification(
    api: AthleticsApiClient,
    certification_id: EntityId,
    headers: Headers = CERT_OFFICER_ALT,
) -> JsonObject:
    return get_success_data(
        api.certification_status(certification_id, f.action(CERT_ACTION_DENY), headers)
    )


def revoke_certification(
    api: AthleticsApiClient,
    certification_id: EntityId,
    headers: Headers = CERT_OFFICER_ALT,
) -> JsonObject:
    return get_success_data(
        api.certification_status(
            certification_id, f.action(CERT_ACTION_REVOKE), headers
        )
    )


def make_certified_certification(
    api: AthleticsApiClient,
    student_athlete_id: EntityId,
    term_id: EntityId,
    certification_type: str = CERT_TYPE_INITIAL,
    requester: Headers = CERT_OFFICER,
    decider: Headers = CERT_OFFICER_ALT,
    **overrides: Any,
) -> JsonObject:
    """Drive a certification all the way to ``CERTIFIED``.

    The benchmark must already pass for the student, since certifying a
    submitted certification carrying ``FAIL`` is refused.
    """
    draft = make_draft_certification(
        api, student_athlete_id, term_id, certification_type, requester, **overrides
    )
    submit_certification(api, draft["id"])
    return certify(api, draft["id"], decider)


def make_denied_certification(
    api: AthleticsApiClient,
    student_athlete_id: EntityId,
    term_id: EntityId,
    certification_type: str = CERT_TYPE_INITIAL,
    requester: Headers = CERT_OFFICER,
    decider: Headers = CERT_OFFICER_ALT,
    **overrides: Any,
) -> JsonObject:
    """Drive a certification to ``DENIED`` (no benchmark condition applies)."""
    draft = make_draft_certification(
        api, student_athlete_id, term_id, certification_type, requester, **overrides
    )
    submit_certification(api, draft["id"])
    return deny_certification(api, draft["id"], decider)


def make_revoked_certification(
    api: AthleticsApiClient,
    student_athlete_id: EntityId,
    term_id: EntityId,
    certification_type: str = CERT_TYPE_INITIAL,
    requester: Headers = CERT_OFFICER,
    decider: Headers = CERT_OFFICER_ALT,
    **overrides: Any,
) -> JsonObject:
    """Certify then revoke, leaving the certification in ``REVOKED``."""
    certified = make_certified_certification(
        api,
        student_athlete_id,
        term_id,
        certification_type,
        requester,
        decider,
        **overrides,
    )
    return revoke_certification(api, certified["id"], decider)


def make_appeal_in_review(
    api: AthleticsApiClient,
    certification_id: EntityId,
    requested_credit_relief: Any = OMIT,
    filer: Headers = ADVISOR,
    committee: Headers = COMMITTEE,
    **overrides: Any,
) -> JsonObject:
    """File, submit and open review on an appeal, leaving it in review."""
    appeal_row = make_appeal(
        api,
        certification_id,
        headers=filer,
        requested_credit_relief=requested_credit_relief,
        **overrides,
    )
    appeal_action(api, appeal_row["id"], "SUBMIT", filer)
    return appeal_action(api, appeal_row["id"], "OPEN_REVIEW", committee)


# ===========================================================================
# Tier 5 - whole-scenario worlds
# ===========================================================================
def provisional_passing_student(
    api: AthleticsApiClient,
    clock: str = "2026-09-01T00:00:00Z",
    grade: str = "B",
    credit_hours: float = 4.0,
) -> Ctx:
    """A student with no declared major whose provisional benchmark passes.

    With no declared major the benchmark short-circuits to the provisional
    grade-point test against a floor of 1.80, so a single completed course
    graded ``B`` is enough for an ``INITIAL`` certification to pass.
    """
    ctx = enrolled_student(api, term_count=1, clock=clock, credit_hours=credit_hours)
    ctx.graded_enrollment = record_grade(api, ctx.enrollment_id, grade)
    ctx.student = read_student(api, ctx.student_id)
    return ctx


def declared_passing_student(
    api: AthleticsApiClient,
    clock: str = "2026-09-01T00:00:00Z",
    term_count: int = 2,
) -> Ctx:
    """A student with a declared major, one graded term and a passing benchmark.

    One completed full-time term keeps ``required_progress_pct`` at 0.0000
    (the first two full-time terms are a grace period), so the progress test
    passes while the grade-point test clears the program minimum of 2.0.
    """
    ctx = enrolled_student(
        api,
        term_count=term_count,
        clock=clock,
        credit_hours=12.0,
        declare_major_in_term=1,
    )
    ctx.graded_enrollment = record_grade(api, ctx.enrollment_id, "A")
    ctx.student = read_student(api, ctx.student_id)
    return ctx


def tutoring_world(
    api: AthleticsApiClient,
    clock: str = "2026-09-01T00:00:00Z",
    weekly_hours: float = 2.0,
    subject_code: str = "KINE",
    tutor_overrides: Optional[Dict[str, Any]] = None,
    activate: bool = True,
) -> Ctx:
    """A trained tutor holding one assignment against an enrolled student."""
    ctx = enrolled_student(api, term_count=1, clock=clock, subject_code=subject_code)
    tutor_row = make_trained_tutor(
        api,
        ctx.term_id,
        subject_codes=[subject_code],
        **(tutor_overrides or {}),
    )
    ctx.tutor = tutor_row
    ctx.tutor_id = tutor_row["id"]
    if activate:
        ctx.assignment = make_active_assignment(
            api, ctx.tutor_id, ctx.enrollment_id, weekly_hours
        )
    else:
        ctx.assignment = make_assignment(
            api, ctx.tutor_id, ctx.enrollment_id, weekly_hours
        )
    ctx.assignment_id = ctx.assignment["id"]
    ctx.tutor = read_tutor(api, ctx.tutor_id)
    return ctx


def travel_world(
    api: AthleticsApiClient,
    clock: str = "2026-09-01T00:00:00Z",
    meeting_days: Optional[Sequence[int]] = None,
    meeting_start_minute_utc: int = 600,
    meeting_duration_minutes: int = 50,
    event_type: str = "REGULAR_SEASON",
    departure_at: str = "2026-10-15T08:00:00Z",
    return_at: str = "2026-10-17T20:00:00Z",
    sport_code: str = "SOC",
    approve: bool = True,
) -> Ctx:
    """An enrolled student plus a competition event ready for a request."""
    ctx = enrolled_student(
        api,
        term_count=1,
        clock=clock,
        student_overrides={"sport_code": sport_code},
        course_overrides={
            "meeting_days": list(meeting_days) if meeting_days else [4],
            "meeting_start_minute_utc": meeting_start_minute_utc,
            "meeting_duration_minutes": meeting_duration_minutes,
        },
    )
    maker = make_approved_event if approve else make_event
    ctx.event = maker(
        api,
        ctx.term_id,
        departure_at,
        return_at,
        sport_code=sport_code,
        event_type=event_type,
    )
    ctx.event_id = ctx.event["id"]
    return ctx


def instructor_of(ctx: Ctx) -> Headers:
    """Headers for the instructor of record behind ``ctx.course``."""
    return instructor_headers(ctx.course["instructor_user_id"])
