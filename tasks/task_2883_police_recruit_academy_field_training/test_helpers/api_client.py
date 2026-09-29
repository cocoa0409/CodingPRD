"""Typed client over the Police Recruit Academy & Field Training API.

ENVELOPE CONTRACT -- decided once, here, and honoured everywhere:

    Every method on this client returns the RAW ``requests.Response``.  This
    client never unwraps the ``{meta, response_type, data}`` envelope.  The
    envelope is stripped in exactly one place, the framework validators:
    ``validate_success`` returns the ``data`` object, ``validate_paginated``
    returns the ``data`` list with the ``meta`` block, and ``validate_error``
    returns the error object.  Test code therefore never indexes ``["data"]``
    on the result of a validator.

There is no URL prefix: paths are mounted at the service root exactly as the
contract writes them.
"""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class AcademyApiClient(GenericApiClient):
    """One method per declared endpoint, in the contract's own order."""

    # ------------------------------------------------------------------
    # Certification standards
    # ------------------------------------------------------------------
    def create_certification_standard(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/certification-standards", payload, headers)

    def get_certification_standard(self, standard_id: str, headers=None):
        return self._request("GET", f"/certification-standards/{standard_id}",
                             None, headers)

    def list_certification_standards(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/certification-standards", params, headers)

    # ------------------------------------------------------------------
    # Academy classes (cohorts)
    # ------------------------------------------------------------------
    def create_academy_class(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/academy-classes", payload, headers)

    def get_academy_class(self, class_id: str, headers=None):
        return self._request("GET", f"/academy-classes/{class_id}", None, headers)

    def list_academy_classes(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/academy-classes", params, headers)

    def certify_graduates(self, class_id: str, headers=None,
                          payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/academy-classes/{class_id}/certify-graduates",
                             payload if payload is not None else {}, headers)

    def get_attrition_analysis(self, class_id: str, headers=None,
                               params: Optional[Dict] = None):
        return self._request("GET", f"/academy-classes/{class_id}/attrition-analysis",
                             params, headers)

    def get_pipeline_forecast(self, class_id: str, headers=None,
                              params: Optional[Dict] = None):
        return self._request("GET", f"/academy-classes/{class_id}/pipeline-forecast",
                             params, headers)

    # ------------------------------------------------------------------
    # Recruits
    # ------------------------------------------------------------------
    def create_recruit(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/recruits", payload, headers)

    def get_recruit(self, recruit_id: str, headers=None):
        return self._request("GET", f"/recruits/{recruit_id}", None, headers)

    def list_recruits(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/recruits", params, headers)

    def advance_stage(self, recruit_id: str, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"/recruits/{recruit_id}/advance-stage",
                             payload, headers)

    def dismiss_recruit(self, recruit_id: str, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"/recruits/{recruit_id}/dismiss", payload, headers)

    def create_probation_decision(self, recruit_id: str, payload: Dict[str, Any],
                                  headers=None):
        return self._request("POST", f"/recruits/{recruit_id}/probation-decisions",
                             payload, headers)

    def get_certification_progress(self, recruit_id: str, headers=None,
                                   params: Optional[Dict] = None):
        return self._request("GET", f"/recruits/{recruit_id}/certification-progress",
                             params, headers)

    def order_screening(self, recruit_id: str, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"/recruits/{recruit_id}/screenings",
                             payload, headers)

    # ------------------------------------------------------------------
    # Screening records
    # ------------------------------------------------------------------
    def get_screening_record(self, screening_record_id: str, headers=None):
        return self._request("GET", f"/screening-records/{screening_record_id}",
                             None, headers)

    def list_screening_records(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/screening-records", params, headers)

    def record_findings(self, screening_record_id: str, payload: Dict[str, Any],
                        headers=None):
        return self._request("POST",
                             f"/screening-records/{screening_record_id}/findings",
                             payload, headers)

    def adjudicate_screening(self, screening_record_id: str, payload: Dict[str, Any],
                             headers=None):
        return self._request("POST",
                             f"/screening-records/{screening_record_id}/adjudicate",
                             payload, headers)

    # ------------------------------------------------------------------
    # Instructors
    # ------------------------------------------------------------------
    def create_instructor(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/instructors", payload, headers)

    def get_instructor(self, instructor_id: str, headers=None):
        return self._request("GET", f"/instructors/{instructor_id}", None, headers)

    def list_instructors(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/instructors", params, headers)

    def certify_instructor(self, instructor_id: str, payload: Dict[str, Any],
                           headers=None):
        return self._request("POST", f"/instructors/{instructor_id}/certify",
                             payload, headers)

    def revoke_instructor_certification(self, instructor_id: str,
                                        payload: Dict[str, Any], headers=None):
        return self._request("POST",
                             f"/instructors/{instructor_id}/revoke-certification",
                             payload, headers)

    # ------------------------------------------------------------------
    # Lesson plans
    # ------------------------------------------------------------------
    def create_lesson_plan(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/lesson-plans", payload, headers)

    def get_lesson_plan(self, lesson_plan_id: str, headers=None):
        return self._request("GET", f"/lesson-plans/{lesson_plan_id}", None, headers)

    def list_lesson_plans(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/lesson-plans", params, headers)

    def create_lesson_plan_revision(self, lesson_plan_id: str,
                                    payload: Dict[str, Any], headers=None):
        return self._request("POST", f"/lesson-plans/{lesson_plan_id}/revisions",
                             payload, headers)

    def approve_lesson_plan(self, lesson_plan_id: str, headers=None,
                            payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/lesson-plans/{lesson_plan_id}/approve",
                             payload if payload is not None else {}, headers)

    def request_lesson_plan_revision(self, lesson_plan_id: str,
                                     payload: Dict[str, Any], headers=None):
        return self._request("POST",
                             f"/lesson-plans/{lesson_plan_id}/request-revision",
                             payload, headers)

    # ------------------------------------------------------------------
    # Course sessions and attendance
    # ------------------------------------------------------------------
    def create_course_session(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/course-sessions", payload, headers)

    def get_course_session(self, course_session_id: str, headers=None):
        return self._request("GET", f"/course-sessions/{course_session_id}",
                             None, headers)

    def list_course_sessions(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/course-sessions", params, headers)

    def record_attendance(self, course_session_id: str, payload: Dict[str, Any],
                          headers=None):
        return self._request("POST",
                             f"/course-sessions/{course_session_id}/attendance",
                             payload, headers)

    def get_attendance_record(self, attendance_record_id: str, headers=None):
        return self._request("GET", f"/attendance-records/{attendance_record_id}",
                             None, headers)

    def list_attendance_records(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/attendance-records", params, headers)

    def deliver_course_session(self, course_session_id: str, headers=None,
                               payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/course-sessions/{course_session_id}/deliver",
                             payload if payload is not None else {}, headers)

    def void_course_session_delivery(self, course_session_id: str,
                                     payload: Dict[str, Any], headers=None):
        return self._request("POST",
                             f"/course-sessions/{course_session_id}/void-delivery",
                             payload, headers)

    # ------------------------------------------------------------------
    # Examinations
    # ------------------------------------------------------------------
    def create_examination(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/examinations", payload, headers)

    def get_examination(self, examination_id: str, headers=None):
        return self._request("GET", f"/examinations/{examination_id}", None, headers)

    def list_examinations(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/examinations", params, headers)

    def grade_examination(self, examination_id: str, payload: Dict[str, Any],
                          headers=None):
        return self._request("POST", f"/examinations/{examination_id}/grade",
                             payload, headers)

    def assign_remediation(self, examination_id: str, payload: Dict[str, Any],
                           headers=None):
        return self._request("POST",
                             f"/examinations/{examination_id}/assign-remediation",
                             payload, headers)

    # ------------------------------------------------------------------
    # Field training rotations and observation reports
    # ------------------------------------------------------------------
    def create_field_training_rotation(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/field-training-rotations", payload, headers)

    def get_field_training_rotation(self, rotation_id: str, headers=None):
        return self._request("GET", f"/field-training-rotations/{rotation_id}",
                             None, headers)

    def list_field_training_rotations(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/field-training-rotations", params, headers)

    def activate_rotation(self, rotation_id: str, headers=None,
                          payload: Optional[Dict[str, Any]] = None):
        return self._request("POST",
                             f"/field-training-rotations/{rotation_id}/activate",
                             payload if payload is not None else {}, headers)

    def complete_rotation(self, rotation_id: str, payload: Dict[str, Any],
                          headers=None):
        return self._request("POST",
                             f"/field-training-rotations/{rotation_id}/complete",
                             payload, headers)

    def abort_rotation(self, rotation_id: str, payload: Dict[str, Any], headers=None):
        return self._request("POST",
                             f"/field-training-rotations/{rotation_id}/abort",
                             payload, headers)

    def create_observation_report(self, rotation_id: str, payload: Dict[str, Any],
                                  headers=None):
        return self._request(
            "POST",
            f"/field-training-rotations/{rotation_id}/observation-reports",
            payload, headers)

    def get_observation_report(self, observation_report_id: str, headers=None):
        return self._request("GET", f"/observation-reports/{observation_report_id}",
                             None, headers)

    def list_observation_reports(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/observation-reports", params, headers)

    # ------------------------------------------------------------------
    # Training record entries
    # ------------------------------------------------------------------
    def get_training_record_entry(self, entry_id: str, headers=None):
        return self._request("GET", f"/training-record-entries/{entry_id}",
                             None, headers)

    def list_training_record_entries(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/training-record-entries", params, headers)

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers=None):
        return self._request("POST", "/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    def set_clock_raw(self, payload: Dict[str, Any], headers=None):
        """Post an arbitrary body to the clock endpoint (shape probes)."""
        return self._request("POST", "/_clock/set_current_utc", payload, headers)
