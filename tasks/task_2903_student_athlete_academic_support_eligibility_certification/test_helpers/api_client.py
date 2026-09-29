"""Domain client for the Athletics Academic Eligibility API.

Wraps the framework's :class:`GenericApiClient` with one method per endpoint of
PRD section 4.  Every method returns the raw ``requests.Response`` so that a
test can hand it either to ``validate_success`` or to ``validate_error``; the
envelope is unwrapped in exactly one place (the validators), never twice.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import BASE
from .types import EntityId, Headers, JsonObject, Params, Payload


def canonical_instant(value: Any) -> Any:
    """Normalise an ISO-8601 UTC instant to exactly three fractional digits.

    Server echoes and test literals must compare equal regardless of whether
    the wire form carried ``Z``, ``.0Z`` or ``.000000Z``; only the sub-second
    width is touched, never the instant itself.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text.endswith("Z"):
        return value
    body = text[:-1]
    if "." in body:
        head, frac = body.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = body, "000"
    return f"{head}.{frac}Z"


def strip_fraction(value: Any) -> Any:
    """Render an instant without any fractional part (``2026-09-01T00:00:00Z``)."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text.endswith("Z"):
        return value
    body = text[:-1]
    if "." in body:
        body = body.split(".", 1)[0]
    return f"{body}Z"


def _compact(payload: Optional[Payload]) -> Optional[Payload]:
    """Drop keys whose value is the sentinel ``OMIT``."""
    if payload is None:
        return None
    return {k: v for k, v in payload.items() if v is not OMIT}


class _Omit:
    """Sentinel for "do not send this key at all"."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "OMIT"


OMIT = _Omit()


class AthleticsApiClient:
    """One method per endpoint under the ``/athletics`` prefix."""

    def __init__(self, base_url: Optional[str] = None):
        self._c = GenericApiClient(base_url)

    # -- raw escape hatches -------------------------------------------------
    @property
    def base_url(self) -> str:
        return self._c.base_url

    def raw_get(
        self,
        path: str,
        headers: Optional[Headers] = None,
        params: Optional[Params] = None,
    ) -> requests.Response:
        return self._c.get(f"{BASE}{path}", headers=headers, params=params)

    def raw_post(
        self,
        path: str,
        payload: Optional[Payload] = None,
        headers: Optional[Headers] = None,
    ) -> requests.Response:
        return self._c.post(f"{BASE}{path}", json=_compact(payload), headers=headers)

    # -- logical clock ------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Headers) -> requests.Response:
        """POST /athletics/_clock/set_current_utc"""
        return self.raw_post(
            "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.raw_post("/_clock/set_current_utc", payload, headers)

    # -- terms --------------------------------------------------------------
    def create_term(self, payload: Payload, headers: Headers) -> requests.Response:
        return self.raw_post("/terms", payload, headers)

    def get_term(self, term_id: EntityId, headers: Headers) -> requests.Response:
        return self.raw_get(f"/terms/{term_id}", headers)

    def list_terms(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.raw_get("/terms", headers, params)

    def apr_close(self, term_id: EntityId, headers: Headers) -> requests.Response:
        return self.raw_post(f"/terms/{term_id}/apr-close", None, headers)

    # -- degree programs ----------------------------------------------------
    def create_degree_program(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.raw_post("/degree-programs", payload, headers)

    def get_degree_program(
        self, degree_program_id: EntityId, headers: Headers
    ) -> requests.Response:
        return self.raw_get(f"/degree-programs/{degree_program_id}", headers)

    def list_degree_programs(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.raw_get("/degree-programs", headers, params)

    # -- courses ------------------------------------------------------------
    def create_course(self, payload: Payload, headers: Headers) -> requests.Response:
        return self.raw_post("/courses", payload, headers)

    def get_course(self, course_id: EntityId, headers: Headers) -> requests.Response:
        return self.raw_get(f"/courses/{course_id}", headers)

    def list_courses(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.raw_get("/courses", headers, params)

    # -- degree applicability rules ----------------------------------------
    def create_applicability_rule(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.raw_post("/degree-applicability-rules", payload, headers)

    def get_applicability_rule(
        self, rule_id: EntityId, headers: Headers
    ) -> requests.Response:
        return self.raw_get(f"/degree-applicability-rules/{rule_id}", headers)

    def list_applicability_rules(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.raw_get("/degree-applicability-rules", headers, params)

    # -- student athletes ---------------------------------------------------
    def create_student(self, payload: Payload, headers: Headers) -> requests.Response:
        return self.raw_post("/student-athletes", payload, headers)

    def get_student(
        self, student_athlete_id: EntityId, headers: Headers
    ) -> requests.Response:
        return self.raw_get(f"/student-athletes/{student_athlete_id}", headers)

    def list_students(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.raw_get("/student-athletes", headers, params)

    def eligibility_summary(
        self,
        student_athlete_id: EntityId,
        headers: Headers,
        params: Optional[Params] = None,
    ) -> requests.Response:
        return self.raw_get(
            f"/student-athletes/{student_athlete_id}/eligibility-summary",
            headers,
            params,
        )

    def declare_major(
        self, student_athlete_id: EntityId, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.raw_post(
            f"/student-athletes/{student_athlete_id}/major-declaration",
            payload,
            headers,
        )

    # -- enrollments --------------------------------------------------------
    def create_enrollment(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.raw_post("/enrollments", payload, headers)

    def get_enrollment(
        self, enrollment_id: EntityId, headers: Headers
    ) -> requests.Response:
        return self.raw_get(f"/enrollments/{enrollment_id}", headers)

    def list_enrollments(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.raw_get("/enrollments", headers, params)

    def record_outcome(
        self, enrollment_id: EntityId, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.raw_post(f"/enrollments/{enrollment_id}/outcome", payload, headers)

    # -- certifications -----------------------------------------------------
    def create_certification(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.raw_post("/certifications", payload, headers)

    def get_certification(
        self, certification_id: EntityId, headers: Headers
    ) -> requests.Response:
        return self.raw_get(f"/certifications/{certification_id}", headers)

    def list_certifications(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.raw_get("/certifications", headers, params)

    def certification_status(
        self, certification_id: EntityId, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.raw_post(
            f"/certifications/{certification_id}/status", payload, headers
        )

    # -- tutors -------------------------------------------------------------
    def create_tutor(self, payload: Payload, headers: Headers) -> requests.Response:
        return self.raw_post("/tutors", payload, headers)

    def get_tutor(self, tutor_id: EntityId, headers: Headers) -> requests.Response:
        return self.raw_get(f"/tutors/{tutor_id}", headers)

    def list_tutors(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.raw_get("/tutors", headers, params)

    def tutor_status(
        self, tutor_id: EntityId, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.raw_post(f"/tutors/{tutor_id}/status", payload, headers)

    # -- tutor assignments --------------------------------------------------
    def create_assignment(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.raw_post("/tutor-assignments", payload, headers)

    def get_assignment(
        self, assignment_id: EntityId, headers: Headers
    ) -> requests.Response:
        return self.raw_get(f"/tutor-assignments/{assignment_id}", headers)

    def list_assignments(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.raw_get("/tutor-assignments", headers, params)

    def assignment_status(
        self, assignment_id: EntityId, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.raw_post(
            f"/tutor-assignments/{assignment_id}/status", payload, headers
        )

    # -- support sessions ---------------------------------------------------
    def create_session(self, payload: Payload, headers: Headers) -> requests.Response:
        return self.raw_post("/support-sessions", payload, headers)

    def get_session(self, session_id: EntityId, headers: Headers) -> requests.Response:
        return self.raw_get(f"/support-sessions/{session_id}", headers)

    def list_sessions(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.raw_get("/support-sessions", headers, params)

    # -- competition events -------------------------------------------------
    def create_event(self, payload: Payload, headers: Headers) -> requests.Response:
        return self.raw_post("/competition-events", payload, headers)

    def get_event(self, event_id: EntityId, headers: Headers) -> requests.Response:
        return self.raw_get(f"/competition-events/{event_id}", headers)

    def list_events(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.raw_get("/competition-events", headers, params)

    def event_status(
        self, event_id: EntityId, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.raw_post(
            f"/competition-events/{event_id}/status", payload, headers
        )

    # -- missed class requests ---------------------------------------------
    def create_missed_class_request(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.raw_post("/missed-class-requests", payload, headers)

    def get_missed_class_request(
        self, request_id: EntityId, headers: Headers
    ) -> requests.Response:
        return self.raw_get(f"/missed-class-requests/{request_id}", headers)

    def list_missed_class_requests(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.raw_get("/missed-class-requests", headers, params)

    def missed_class_request_status(
        self, request_id: EntityId, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.raw_post(
            f"/missed-class-requests/{request_id}/status", payload, headers
        )

    # -- appeals ------------------------------------------------------------
    def create_appeal(self, payload: Payload, headers: Headers) -> requests.Response:
        return self.raw_post("/appeals", payload, headers)

    def get_appeal(self, appeal_id: EntityId, headers: Headers) -> requests.Response:
        return self.raw_get(f"/appeals/{appeal_id}", headers)

    def list_appeals(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.raw_get("/appeals", headers, params)

    def appeal_status(
        self, appeal_id: EntityId, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.raw_post(f"/appeals/{appeal_id}/status", payload, headers)

    # -- compliance incidents ----------------------------------------------
    def create_incident(self, payload: Payload, headers: Headers) -> requests.Response:
        return self.raw_post("/compliance-incidents", payload, headers)

    def get_incident(
        self, incident_id: EntityId, headers: Headers
    ) -> requests.Response:
        return self.raw_get(f"/compliance-incidents/{incident_id}", headers)

    def list_incidents(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.raw_get("/compliance-incidents", headers, params)

    def incident_status(
        self, incident_id: EntityId, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.raw_post(
            f"/compliance-incidents/{incident_id}/status", payload, headers
        )
