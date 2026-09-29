"""Composite fixtures: reusable state built entirely through the declared API.

Every fixture creates all of its own state through public endpoints, so no test
depends on state left behind by another test.  The helpers are layered:

* tier 1 -- a bare standard, cohort, recruit or instructor;
* tier 2 -- an entity hierarchy: a cohort with a certified instructor and an
  approved lesson plan;
* tier 3 -- lifecycle shortcuts: a recruit whose four screenings are cleared, a
  recruit in the academy, a delivered session with credited attendance;
* tier 4 -- accumulation and threshold targeting: a recruit whose curriculum is
  satisfied, a rotation carrying observation reports;
* tier 5 -- finalization: a recruit in field training, a recruit on probation.

The logical clock is a first-class part of setup: sessions cannot be closed out
before they have finished and reports cannot be filed ahead of the clock, so the
helpers move the clock forward deliberately and monotonically.
"""
from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories as f
from .api_client import AcademyApiClient
from .constants import CLOCK_EPOCH
from .test_users import (
    coordinator_headers,
    director_headers,
    make_fto_headers,
    screening_adjudicate_headers,
    screening_findings_headers,
)
from .types import ALL_SCREENING_TYPES


# Instants used across the composite fixtures.  They advance monotonically:
# the academy session finishes first, then field training runs in September.
SESSION_STARTS_AT = "2026-08-03T09:00:00Z"
SESSION_ENDS_AT = "2026-08-03T13:00:00Z"
SESSION_HOURS = 4.0
AFTER_SESSION = "2026-08-03T13:00:00Z"

ROTATION_START_DATE = "2026-09-01"
ROTATION_END_DATE = "2026-09-10"
ROTATION_OBSERVED_ON = "2026-09-02"
DURING_ROTATION = "2026-09-02T18:00:00Z"
AFTER_ROTATION = "2026-09-10T18:00:00Z"

PROBATION_START = "2026-09-11"
INSTRUCTOR_EXPIRES_AT = "2027-12-31T00:00:00Z"


class AcademyWorld:
    """A thin scenario builder over the API client.

    Each method performs exactly the declared calls a real caller would make
    and returns the created entity, so a test can assert against the same rows
    the fixture built.
    """

    def __init__(self, client: AcademyApiClient):
        self.client = client

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str) -> Dict[str, Any]:
        response = self.client.set_clock(current_utc, director_headers())
        return validate_success(response)

    # ------------------------------------------------------------------
    # Tier 1 -- single entities
    # ------------------------------------------------------------------
    def create_standard(self, **kwargs) -> Dict[str, Any]:
        payload = f.certification_standard_payload(**kwargs)
        response = self.client.create_certification_standard(payload,
                                                             director_headers())
        return validate_success(response, 201)

    def create_cohort(self, standard_id: str, **kwargs) -> Dict[str, Any]:
        payload = f.academy_class_payload(standard_id, **kwargs)
        response = self.client.create_academy_class(payload, director_headers())
        return validate_success(response, 201)

    def create_recruit(self, cohort_id: str, **kwargs) -> Dict[str, Any]:
        payload = f.recruit_payload(cohort_id, **kwargs)
        response = self.client.create_recruit(payload, coordinator_headers())
        return validate_success(response, 201)

    def create_instructor(self, **kwargs) -> Dict[str, Any]:
        payload = f.instructor_payload(**kwargs)
        response = self.client.create_instructor(payload, director_headers())
        return validate_success(response, 201)

    def certify_instructor(self, instructor_id: str, **kwargs) -> Dict[str, Any]:
        payload = f.certify_instructor_payload(**kwargs)
        response = self.client.certify_instructor(instructor_id, payload,
                                                 director_headers())
        return validate_success(response)

    def create_certified_instructor(self,
                                    topics: Optional[List[str]] = None,
                                    expires_at: str = INSTRUCTOR_EXPIRES_AT,
                                    fto_certified: bool = False,
                                    **create_kwargs) -> Dict[str, Any]:
        """Register an instructor and grant them a live credential."""
        instructor = self.create_instructor(**create_kwargs)
        return self.certify_instructor(
            instructor["id"],
            certification_expires_at=expires_at,
            authorized_topic_codes=topics if topics is not None else [f.TOPIC_LAW],
            fto_certified=fto_certified,
        )

    def create_certified_fto(self, expires_at: str = INSTRUCTOR_EXPIRES_AT,
                             **create_kwargs) -> Dict[str, Any]:
        return self.create_certified_instructor(
            topics=[f.TOPIC_LAW], expires_at=expires_at,
            fto_certified=True, **create_kwargs)

    # ------------------------------------------------------------------
    # Tier 2 -- entity hierarchy
    # ------------------------------------------------------------------
    def create_lesson_plan(self, instructor_id: str, **kwargs) -> Dict[str, Any]:
        payload = f.lesson_plan_payload(instructor_id, **kwargs)
        response = self.client.create_lesson_plan(payload, coordinator_headers())
        return validate_success(response, 201)

    def approve_lesson_plan(self, lesson_plan_id: str) -> Dict[str, Any]:
        # The approving director is never the authoring instructor's user.
        response = self.client.approve_lesson_plan(lesson_plan_id,
                                                   director_headers())
        return validate_success(response)

    def create_approved_lesson_plan(self, instructor_id: str,
                                    topic_code: str = f.TOPIC_LAW,
                                    contact_hours: float = SESSION_HOURS) -> Dict[str, Any]:
        plan = self.create_lesson_plan(instructor_id, topic_code=topic_code,
                                       contact_hours=contact_hours)
        return self.approve_lesson_plan(plan["id"])

    def curriculum(self, topic_code: str = f.TOPIC_LAW,
                   required_hours: float = SESSION_HOURS,
                   exam_required: bool = True,
                   min_total_hours: float = SESSION_HOURS,
                   session_starts_at: str = SESSION_STARTS_AT,
                   session_ends_at: str = SESSION_ENDS_AT,
                   after_session: str = AFTER_SESSION,
                   **standard_kwargs) -> Dict[str, Any]:
        """A standard, a cohort on it, a certified instructor and an approved plan."""
        standard = self.create_standard(
            min_total_hours=min_total_hours,
            topic_requirements=[f.topic_requirement(topic_code, required_hours,
                                                    exam_required)],
            **standard_kwargs)
        cohort = self.create_cohort(standard["id"])
        instructor = self.create_certified_instructor(topics=[topic_code])
        plan = self.create_approved_lesson_plan(instructor["id"], topic_code)
        return {
            "standard": standard,
            "cohort": cohort,
            "instructor": instructor,
            "lesson_plan": plan,
            "topic_code": topic_code,
            "session_starts_at": session_starts_at,
            "session_ends_at": session_ends_at,
            "after_session": after_session,
        }

    # ------------------------------------------------------------------
    # Tier 3 -- screening lifecycle shortcuts
    # ------------------------------------------------------------------
    def order_screening(self, recruit_id: str,
                        screening_type: str = "BACKGROUND") -> Dict[str, Any]:
        response = self.client.order_screening(
            recruit_id, f.screening_payload(screening_type), coordinator_headers())
        return validate_success(response, 201)

    def record_findings(self, screening_id: str, screening_type: str,
                        disqualifier_codes: Optional[List[str]] = None,
                        raw_metrics: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = f.findings_payload_for(screening_type, disqualifier_codes,
                                         raw_metrics)
        response = self.client.record_findings(
            screening_id, payload, screening_findings_headers(screening_type))
        return validate_success(response)

    def adjudicate(self, screening_id: str, screening_type: str,
                   decision: str = "CLEAR",
                   waiver_justification: Optional[str] = None) -> Dict[str, Any]:
        payload = f.adjudicate_payload(decision, waiver_justification)
        response = self.client.adjudicate_screening(
            screening_id, payload, screening_adjudicate_headers(screening_type))
        return validate_success(response)

    def screening_at_findings_recorded(self, recruit_id: str,
                                       screening_type: str = "BACKGROUND",
                                       disqualifier_codes: Optional[List[str]] = None,
                                       raw_metrics: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        record = self.order_screening(recruit_id, screening_type)
        return self.record_findings(record["id"], screening_type,
                                    disqualifier_codes, raw_metrics)

    def clear_screening(self, recruit_id: str,
                        screening_type: str = "BACKGROUND") -> Dict[str, Any]:
        record = self.screening_at_findings_recorded(recruit_id, screening_type)
        return self.adjudicate(record["id"], screening_type, "CLEAR")

    def clear_all_four_screenings(self, recruit_id: str) -> List[Dict[str, Any]]:
        """Order, record and clear one screening of every declared type."""
        return [self.clear_screening(recruit_id, screening_type)
                for screening_type in ALL_SCREENING_TYPES]

    # ------------------------------------------------------------------
    # Tier 3 -- pipeline hops
    # ------------------------------------------------------------------
    def advance(self, recruit_id: str, to_stage: str,
                probation_start: Optional[str] = None,
                probation_base_days: Optional[int] = None) -> Dict[str, Any]:
        payload = f.advance_stage_payload(to_stage, probation_start,
                                          probation_base_days)
        response = self.client.advance_stage(recruit_id, payload,
                                            coordinator_headers())
        return validate_success(response)

    def read_recruit(self, recruit_id: str) -> Dict[str, Any]:
        response = self.client.get_recruit(recruit_id, coordinator_headers())
        return validate_success(response)

    def recruit_in_screening(self, cohort_id: str, **recruit_kwargs) -> Dict[str, Any]:
        """A recruit whose first screening has been ordered, so the stage hopped."""
        recruit = self.create_recruit(cohort_id, **recruit_kwargs)
        self.order_screening(recruit["id"], "BACKGROUND")
        return self.read_recruit(recruit["id"])

    def recruit_cleared(self, cohort_id: str, **recruit_kwargs) -> Dict[str, Any]:
        """A recruit at SCREENING whose clearance_status has reached CLEARED."""
        recruit = self.create_recruit(cohort_id, **recruit_kwargs)
        self.clear_all_four_screenings(recruit["id"])
        return self.read_recruit(recruit["id"])

    def recruit_in_academy(self, cohort_id: str, **recruit_kwargs) -> Dict[str, Any]:
        recruit = self.recruit_cleared(cohort_id, **recruit_kwargs)
        return self.advance(recruit["id"], "ACADEMY")

    # ------------------------------------------------------------------
    # Tier 3 -- sessions, attendance and delivery
    # ------------------------------------------------------------------
    def schedule_session(self, cohort_id: str, lesson_plan_id: str,
                         instructor_id: str, **kwargs) -> Dict[str, Any]:
        kwargs.setdefault("starts_at", SESSION_STARTS_AT)
        kwargs.setdefault("ends_at", SESSION_ENDS_AT)
        payload = f.course_session_payload(cohort_id, lesson_plan_id,
                                           instructor_id, **kwargs)
        response = self.client.create_course_session(payload, coordinator_headers())
        return validate_success(response, 201)

    def record_attendance(self, session_id: str, recruit_id: str,
                          status: str = "PRESENT",
                          present_hours: float = SESSION_HOURS) -> Dict[str, Any]:
        payload = f.attendance_payload(recruit_id, status, present_hours)
        response = self.client.record_attendance(session_id, payload,
                                                 coordinator_headers())
        return validate_success(response, 201)

    def deliver_session(self, session_id: str) -> Dict[str, Any]:
        response = self.client.deliver_course_session(session_id,
                                                      coordinator_headers())
        return validate_success(response)

    def void_delivery(self, session_id: str, reason: str = "Credential audit finding") -> Dict[str, Any]:
        response = self.client.void_course_session_delivery(
            session_id, f.void_delivery_payload(reason), director_headers())
        return validate_success(response)

    def delivered_session_with_attendance(self, cohort_id: str, lesson_plan_id: str,
                                          instructor_id: str,
                                          attendees: List[Dict[str, Any]],
                                          starts_at: str = SESSION_STARTS_AT,
                                          ends_at: str = SESSION_ENDS_AT,
                                          min_enrollment: Optional[int] = 0,
                                          clock_after: str = AFTER_SESSION) -> Dict[str, Any]:
        """Schedule, roster, advance the clock past the end, and close out.

        ``attendees`` is a list of ``{"recruit_id": ..., "status": ...,
        "present_hours": ...}`` mappings; the status and hours default to a full
        presence for the whole scheduled block.
        """
        session = self.schedule_session(cohort_id, lesson_plan_id, instructor_id,
                                        starts_at=starts_at, ends_at=ends_at,
                                        min_enrollment=min_enrollment)
        scheduled_hours = session["scheduled_hours"]
        rows = []
        for attendee in attendees:
            rows.append(self.record_attendance(
                session["id"], attendee["recruit_id"],
                attendee.get("status", "PRESENT"),
                attendee.get("present_hours", scheduled_hours)))
        self.set_clock(clock_after)
        delivered = self.deliver_session(session["id"])
        return {"session": delivered, "attendance": rows}

    # ------------------------------------------------------------------
    # Tier 3 -- examinations
    # ------------------------------------------------------------------
    def schedule_examination(self, recruit_id: str,
                             topic_code: str = f.TOPIC_LAW) -> Dict[str, Any]:
        response = self.client.create_examination(
            f.examination_payload(recruit_id, topic_code), coordinator_headers())
        return validate_success(response, 201)

    def grade_examination(self, examination_id: str,
                          raw_score: float = 80.0) -> Dict[str, Any]:
        response = self.client.grade_examination(
            examination_id, f.grade_payload(raw_score), coordinator_headers())
        return validate_success(response)

    def assign_remediation(self, examination_id: str,
                           remediation_hours: float = 4.0) -> Dict[str, Any]:
        response = self.client.assign_remediation(
            examination_id, f.assign_remediation_payload(remediation_hours),
            coordinator_headers())
        return validate_success(response)

    def failed_examination(self, recruit_id: str, topic_code: str = f.TOPIC_LAW,
                           raw_score: float = 10.0) -> Dict[str, Any]:
        exam = self.schedule_examination(recruit_id, topic_code)
        return self.grade_examination(exam["id"], raw_score)

    # ------------------------------------------------------------------
    # Tier 4 -- curriculum satisfied
    # ------------------------------------------------------------------
    def recruit_with_academy_complete(self, world: Dict[str, Any],
                                      **recruit_kwargs) -> Dict[str, Any]:
        """Credit the whole curriculum and pass the topic examination.

        ``world`` is the mapping returned by :meth:`curriculum`.  The recruit
        attends one delivered session covering the topic's whole requirement and
        then passes that topic's examination, which is what moves
        ``academy_status`` to ``COMPLETE``.
        """
        recruit = self.recruit_in_academy(world["cohort"]["id"], **recruit_kwargs)
        self.delivered_session_with_attendance(
            world["cohort"]["id"], world["lesson_plan"]["id"],
            world["instructor"]["id"],
            [{"recruit_id": recruit["id"]}],
            starts_at=world.get("session_starts_at", SESSION_STARTS_AT),
            ends_at=world.get("session_ends_at", SESSION_ENDS_AT),
            clock_after=world.get("after_session", AFTER_SESSION))
        requirements = world["standard"]["topic_requirements"]
        if requirements[0]["exam_required"]:
            exam = self.schedule_examination(recruit["id"], world["topic_code"])
            self.grade_examination(exam["id"], 80.0)
        return self.read_recruit(recruit["id"])

    def recruit_in_field_training(self, world: Dict[str, Any],
                                  **recruit_kwargs) -> Dict[str, Any]:
        recruit = self.recruit_with_academy_complete(world, **recruit_kwargs)
        return self.advance(recruit["id"], "FIELD_TRAINING")

    # ------------------------------------------------------------------
    # Tier 4 -- rotations and observation reports
    # ------------------------------------------------------------------
    def plan_rotation(self, recruit: Dict[str, Any], fto_instructor_id: str,
                      **kwargs) -> Dict[str, Any]:
        """Plan a rotation using the recruit's current version as the OCC guard."""
        kwargs.setdefault("start_date", ROTATION_START_DATE)
        kwargs.setdefault("end_date", ROTATION_END_DATE)
        payload = f.rotation_payload(recruit["id"], fto_instructor_id,
                                     recruit["version"], **kwargs)
        response = self.client.create_field_training_rotation(
            payload, coordinator_headers())
        return validate_success(response, 201)

    def activate_rotation(self, rotation_id: str) -> Dict[str, Any]:
        response = self.client.activate_rotation(rotation_id, coordinator_headers())
        return validate_success(response)

    def file_report(self, rotation_id: str, fto_instructor_id: str,
                    observed_on: str = ROTATION_OBSERVED_ON,
                    ratings: Optional[Dict[str, int]] = None,
                    not_responding_to_training: Optional[bool] = None,
                    narrative: str = "Trainee handled a domestic call competently") -> Dict[str, Any]:
        payload = f.observation_report_payload(
            fto_instructor_id, observed_on, ratings, narrative,
            not_responding_to_training)
        response = self.client.create_observation_report(
            rotation_id, payload, make_fto_headers(fto_instructor_id))
        return validate_success(response, 201)

    def read_rotation(self, rotation_id: str) -> Dict[str, Any]:
        response = self.client.get_field_training_rotation(rotation_id,
                                                          coordinator_headers())
        return validate_success(response)

    def complete_rotation(self, rotation_id: str,
                          final_narrative: str = "Phase completed satisfactorily") -> Dict[str, Any]:
        response = self.client.complete_rotation(
            rotation_id, f.complete_rotation_payload(final_narrative),
            coordinator_headers())
        return validate_success(response)

    def abort_rotation(self, rotation_id: str,
                       reason: str = "Officer reassigned to patrol") -> Dict[str, Any]:
        response = self.client.abort_rotation(
            rotation_id, f.abort_rotation_payload(reason), coordinator_headers())
        return validate_success(response)

    def active_rotation(self, world: Dict[str, Any],
                        recruit: Optional[Dict[str, Any]] = None,
                        fto: Optional[Dict[str, Any]] = None,
                        **rotation_kwargs) -> Dict[str, Any]:
        """A recruit in field training with one ACTIVE rotation under a live FTO."""
        if recruit is None:
            recruit = self.recruit_in_field_training(world)
        if fto is None:
            fto = self.create_certified_fto()
        rotation = self.plan_rotation(recruit, fto["id"], **rotation_kwargs)
        rotation = self.activate_rotation(rotation["id"])
        return {"recruit": recruit, "fto": fto, "rotation": rotation}

    def completed_rotation(self, world: Dict[str, Any],
                           recruit: Optional[Dict[str, Any]] = None,
                           fto: Optional[Dict[str, Any]] = None,
                           rating: int = 5,
                           observed_on: str = ROTATION_OBSERVED_ON,
                           clock_during: str = DURING_ROTATION,
                           clock_after: str = AFTER_ROTATION,
                           **rotation_kwargs) -> Dict[str, Any]:
        """An ACTIVE rotation carrying one report, closed out after its end date."""
        built = self.active_rotation(world, recruit, fto, **rotation_kwargs)
        self.set_clock(clock_during)
        report = self.file_report(built["rotation"]["id"], built["fto"]["id"],
                                 observed_on, f.dimension_ratings(rating))
        self.set_clock(clock_after)
        rotation = self.complete_rotation(built["rotation"]["id"])
        built["report"] = report
        built["rotation"] = rotation
        return built

    # ------------------------------------------------------------------
    # Tier 5 -- probation and certification
    # ------------------------------------------------------------------
    def recruit_in_probation(self, world: Dict[str, Any],
                             probation_start: str = PROBATION_START,
                             probation_base_days: Optional[int] = None,
                             rating: int = 5,
                             **kwargs) -> Dict[str, Any]:
        """A recruit whose field training closed and whose probation is ACTIVE."""
        built = self.completed_rotation(world, rating=rating, **kwargs)
        recruit = self.advance(built["recruit"]["id"], "PROBATION",
                               probation_start=probation_start,
                               probation_base_days=probation_base_days)
        built["recruit"] = recruit
        return built

    def probation_decision(self, recruit_id: str, decision: str = "PASS",
                           justification: str = "Milestone review complete") -> Dict[str, Any]:
        payload = f.probation_decision_payload(decision, justification)
        response = self.client.create_probation_decision(recruit_id, payload,
                                                         director_headers())
        return validate_success(response)

    def dismiss(self, recruit_id: str, reason_code: str = "INTEGRITY",
                justification: str = "Sustained integrity finding") -> Dict[str, Any]:
        payload = f.dismiss_payload(reason_code, justification)
        response = self.client.dismiss_recruit(recruit_id, payload,
                                               director_headers())
        return validate_success(response)

    def certify_graduates(self, cohort_id: str) -> Dict[str, Any]:
        response = self.client.certify_graduates(cohort_id, director_headers())
        return validate_success(response)

    def training_record_entries(self, recruit_id: Optional[str] = None,
                                academy_class_id: Optional[str] = None,
                                limit: int = 100) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"limit": limit}
        if recruit_id is not None:
            params["recruit_id"] = recruit_id
        if academy_class_id is not None:
            params["academy_class_id"] = academy_class_id
        response = self.client.list_training_record_entries(director_headers(),
                                                           params)
        return get_success_data(response)


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def client() -> AcademyApiClient:
    """A client against the service under test."""
    return AcademyApiClient()


@pytest.fixture
def world(client: AcademyApiClient) -> AcademyWorld:
    """The scenario builder; every helper on it uses only declared endpoints."""
    return AcademyWorld(client)


@pytest.fixture
def clock_epoch() -> str:
    """The instant a fresh service reports as its logical clock."""
    return CLOCK_EPOCH


@pytest.fixture
def standard(world: AcademyWorld) -> Dict[str, Any]:
    return world.create_standard()


@pytest.fixture
def cohort(world: AcademyWorld, standard: Dict[str, Any]) -> Dict[str, Any]:
    return world.create_cohort(standard["id"])


@pytest.fixture
def recruit(world: AcademyWorld, cohort: Dict[str, Any]) -> Dict[str, Any]:
    return world.create_recruit(cohort["id"])


@pytest.fixture
def instructor(world: AcademyWorld) -> Dict[str, Any]:
    return world.create_instructor()


@pytest.fixture
def certified_instructor(world: AcademyWorld) -> Dict[str, Any]:
    return world.create_certified_instructor()


@pytest.fixture
def certified_fto(world: AcademyWorld) -> Dict[str, Any]:
    return world.create_certified_fto()


@pytest.fixture
def curriculum(world: AcademyWorld) -> Dict[str, Any]:
    """A standard with one four-hour examined topic, a cohort, a certified
    instructor authorized for that topic and an approved lesson plan."""
    return world.curriculum()


@pytest.fixture
def academy_recruit(world: AcademyWorld, curriculum: Dict[str, Any]) -> Dict[str, Any]:
    """A recruit cleared through screening and advanced into the academy."""
    return world.recruit_in_academy(curriculum["cohort"]["id"])


@pytest.fixture
def academy_complete_recruit(world: AcademyWorld,
                             curriculum: Dict[str, Any]) -> Dict[str, Any]:
    """A recruit whose curriculum is satisfied and whose examination passed."""
    return world.recruit_with_academy_complete(curriculum)


@pytest.fixture
def field_training_recruit(world: AcademyWorld,
                           curriculum: Dict[str, Any]) -> Dict[str, Any]:
    return world.recruit_in_field_training(curriculum)


@pytest.fixture
def active_rotation(world: AcademyWorld, curriculum: Dict[str, Any]) -> Dict[str, Any]:
    """A recruit in field training with one ACTIVE rotation and its FTO."""
    return world.active_rotation(curriculum)


@pytest.fixture
def probation_recruit(world: AcademyWorld, curriculum: Dict[str, Any]) -> Dict[str, Any]:
    """A recruit whose first rotation completed and whose probation is ACTIVE."""
    return world.recruit_in_probation(curriculum)
