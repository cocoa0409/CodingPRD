"""One method per PRD §4 endpoint, plus the logical-clock driver.

Every method returns the raw ``requests.Response`` so that call sites can assert
on HTTP status codes and pass the response to ``validate_success`` /
``validate_error``. There is exactly one envelope unwrap in the whole stack and
it lives inside those validators, never here.
"""

import contextlib
from typing import Any, Dict, Iterator, Optional

import requests
import requests.utils

from prd_bench_local_runner.testing import GenericApiClient


@contextlib.contextmanager
def allow_blank_header_values() -> Iterator[None]:
    """Let a whitespace-only header value reach the server.

    §2.1 requires a header that "contains only whitespace" to be refused with
    ``ERR_MISSING_AUTH_HEADER``, and that is a rule about what the *server*
    decides. ``requests`` however refuses such a value client-side — its header
    validator admits only ``""`` or a value beginning with a non-whitespace
    character — so the probe would raise ``InvalidHeader`` and never put a byte
    on the wire, leaving the PRD clause unexercised.

    Suspending that client-side guard for the duration of the block hands the
    adjudication back to the server, where the contract places it. A raw socket
    confirms the server sees the unstripped value and answers 401. The original
    validator is always restored on exit.
    """
    original = requests.utils._validate_header_part
    requests.utils._validate_header_part = lambda header, part, index: None
    try:
        yield
    finally:
        requests.utils._validate_header_part = original


class ApiClient(GenericApiClient):
    """Endpoint surface for the Academic Program Review & Discontinuation API."""

    # --- §2.5 the logical clock --------------------------------------------

    def set_clock(self, current_utc: str, headers: Dict[str, str]) -> requests.Response:
        """POST /_clock/set_current_utc"""
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /_clock/set_current_utc with an arbitrary body."""
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- §3.7 the compliance sweep -----------------------------------------

    def run_compliance_sweep(
        self, headers: Dict[str, str], payload: Optional[Any] = None
    ) -> requests.Response:
        """POST /provost/compliance-sweeps"""
        return self._request(
            "POST", "/provost/compliance-sweeps", payload if payload is not None else {}, headers
        )

    # --- §3.1 academic programs -------------------------------------------

    def create_program(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /provost/academic-programs"""
        return self._request("POST", "/provost/academic-programs", payload, headers)

    def list_programs(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        """GET /provost/academic-programs"""
        return self._request(
            "GET", "/provost/academic-programs", headers=headers, params=params
        )

    def get_program(
        self, program_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /provost/academic-programs/{id}"""
        return self._request(
            "GET", f"/provost/academic-programs/{program_id}", headers=headers
        )

    def set_catalog_status(
        self, program_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /provost/academic-programs/{id}/catalog-status"""
        return self._request(
            "POST",
            f"/provost/academic-programs/{program_id}/catalog-status",
            payload,
            headers,
        )

    def create_metric_snapshot(
        self, program_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /provost/academic-programs/{id}/metric-snapshots"""
        return self._request(
            "POST",
            f"/provost/academic-programs/{program_id}/metric-snapshots",
            payload,
            headers,
        )

    def list_metric_snapshots(
        self, program_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        """GET /provost/academic-programs/{id}/metric-snapshots"""
        return self._request(
            "GET",
            f"/provost/academic-programs/{program_id}/metric-snapshots",
            headers=headers,
            params=params,
        )

    def create_review_cycle(
        self, program_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /provost/academic-programs/{id}/review-cycles"""
        return self._request(
            "POST",
            f"/provost/academic-programs/{program_id}/review-cycles",
            payload,
            headers,
        )

    def list_review_cycles(
        self, program_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        """GET /provost/academic-programs/{id}/review-cycles"""
        return self._request(
            "GET",
            f"/provost/academic-programs/{program_id}/review-cycles",
            headers=headers,
            params=params,
        )

    def create_faculty_appointment(
        self, program_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /provost/academic-programs/{id}/faculty-appointments"""
        return self._request(
            "POST",
            f"/provost/academic-programs/{program_id}/faculty-appointments",
            payload,
            headers,
        )

    def list_faculty_appointments(
        self, program_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        """GET /provost/academic-programs/{id}/faculty-appointments"""
        return self._request(
            "GET",
            f"/provost/academic-programs/{program_id}/faculty-appointments",
            headers=headers,
            params=params,
        )

    # --- §3.9 teach-out plans ---------------------------------------------

    def create_teach_out_plan(
        self, program_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /provost/academic-programs/{id}/teach-out-plans"""
        return self._request(
            "POST",
            f"/provost/academic-programs/{program_id}/teach-out-plans",
            payload,
            headers,
        )

    def list_teach_out_plans(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        """GET /provost/teach-out-plans"""
        return self._request(
            "GET", "/provost/teach-out-plans", headers=headers, params=params
        )

    def get_teach_out_plan(
        self, plan_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /provost/teach-out-plans/{id}"""
        return self._request(
            "GET", f"/provost/teach-out-plans/{plan_id}", headers=headers
        )

    def transition_teach_out_plan(
        self, plan_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /provost/teach-out-plans/{id}/transitions"""
        return self._request(
            "POST", f"/provost/teach-out-plans/{plan_id}/transitions", payload, headers
        )

    def create_course_guarantee(
        self, plan_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /provost/teach-out-plans/{id}/course-guarantees"""
        return self._request(
            "POST",
            f"/provost/teach-out-plans/{plan_id}/course-guarantees",
            payload,
            headers,
        )

    def list_course_guarantees(
        self, plan_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        """GET /provost/teach-out-plans/{id}/course-guarantees"""
        return self._request(
            "GET",
            f"/provost/teach-out-plans/{plan_id}/course-guarantees",
            headers=headers,
            params=params,
        )

    def allocate_seats(
        self, guarantee_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /provost/course-guarantees/{id}/seat-allocations"""
        return self._request(
            "POST",
            f"/provost/course-guarantees/{guarantee_id}/seat-allocations",
            payload,
            headers,
        )

    def create_displaced_student(
        self, plan_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /provost/teach-out-plans/{id}/displaced-students"""
        return self._request(
            "POST",
            f"/provost/teach-out-plans/{plan_id}/displaced-students",
            payload,
            headers,
        )

    def list_displaced_students(
        self, plan_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        """GET /provost/teach-out-plans/{id}/displaced-students"""
        return self._request(
            "GET",
            f"/provost/teach-out-plans/{plan_id}/displaced-students",
            headers=headers,
            params=params,
        )

    def record_advising(
        self, student_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /provost/displaced-students/{id}/advising"""
        return self._request(
            "POST", f"/provost/displaced-students/{student_id}/advising", payload, headers
        )

    def record_student_progress(
        self, student_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /provost/displaced-students/{id}/progress"""
        return self._request(
            "POST", f"/provost/displaced-students/{student_id}/progress", payload, headers
        )

    # --- §3.3 review cycles and self-studies ------------------------------

    def get_review_cycle(
        self, cycle_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /provost/review-cycles/{id}"""
        return self._request(
            "GET", f"/provost/review-cycles/{cycle_id}", headers=headers
        )

    def create_self_study(
        self, cycle_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /provost/review-cycles/{id}/self-studies"""
        return self._request(
            "POST", f"/provost/review-cycles/{cycle_id}/self-studies", payload, headers
        )

    def list_self_studies(
        self, cycle_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        """GET /provost/review-cycles/{id}/self-studies"""
        return self._request(
            "GET",
            f"/provost/review-cycles/{cycle_id}/self-studies",
            headers=headers,
            params=params,
        )

    def patch_self_study(
        self, self_study_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        """PATCH /provost/self-studies/{id}"""
        return self._request(
            "PATCH", f"/provost/self-studies/{self_study_id}", payload, headers
        )

    def transition_self_study(
        self, self_study_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /provost/self-studies/{id}/transitions"""
        return self._request(
            "POST",
            f"/provost/self-studies/{self_study_id}/transitions",
            payload,
            headers,
        )

    def file_program_response(
        self, cycle_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /provost/review-cycles/{id}/program-response"""
        return self._request(
            "POST",
            f"/provost/review-cycles/{cycle_id}/program-response",
            payload,
            headers,
        )

    # --- §3.4 reviewer logistics -------------------------------------------

    def create_external_reviewer(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /provost/external-reviewers"""
        return self._request("POST", "/provost/external-reviewers", payload, headers)

    def create_reviewer_visit(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /provost/reviewer-visits"""
        return self._request("POST", "/provost/reviewer-visits", payload, headers)

    def list_reviewer_visits(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        """GET /provost/reviewer-visits"""
        return self._request(
            "GET", "/provost/reviewer-visits", headers=headers, params=params
        )

    def get_reviewer_visit(
        self, visit_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /provost/reviewer-visits/{id}"""
        return self._request(
            "GET", f"/provost/reviewer-visits/{visit_id}", headers=headers
        )

    def complete_reviewer_visit(
        self, visit_id: str, headers: Dict[str, str], payload: Optional[Any] = None
    ) -> requests.Response:
        """POST /provost/reviewer-visits/{id}/complete"""
        return self._request(
            "POST",
            f"/provost/reviewer-visits/{visit_id}/complete",
            payload if payload is not None else {},
            headers,
        )

    # --- §3.5 reviewer reports --------------------------------------------

    def create_reviewer_report(
        self, visit_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /provost/reviewer-visits/{id}/reports"""
        return self._request(
            "POST", f"/provost/reviewer-visits/{visit_id}/reports", payload, headers
        )

    def list_reviewer_reports(
        self, visit_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        """GET /provost/reviewer-visits/{id}/reports"""
        return self._request(
            "GET",
            f"/provost/reviewer-visits/{visit_id}/reports",
            headers=headers,
            params=params,
        )

    # --- §3.6 / §3.8 decision records -------------------------------------

    def create_decision_record(
        self, cycle_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /provost/review-cycles/{id}/decision-records"""
        return self._request(
            "POST",
            f"/provost/review-cycles/{cycle_id}/decision-records",
            payload,
            headers,
        )

    def list_decision_records(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        """GET /provost/decision-records"""
        return self._request(
            "GET", "/provost/decision-records", headers=headers, params=params
        )

    def get_decision_record(
        self, decision_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /provost/decision-records/{id}"""
        return self._request(
            "GET", f"/provost/decision-records/{decision_id}", headers=headers
        )

    def transition_decision_record(
        self, decision_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /provost/decision-records/{id}/transitions"""
        return self._request(
            "POST",
            f"/provost/decision-records/{decision_id}/transitions",
            payload,
            headers,
        )

    # --- §3.7 agency notifications ----------------------------------------

    def create_agency_notification(
        self, decision_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /provost/decision-records/{id}/agency-notifications"""
        return self._request(
            "POST",
            f"/provost/decision-records/{decision_id}/agency-notifications",
            payload,
            headers,
        )

    def list_agency_notifications(
        self, decision_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        """GET /provost/decision-records/{id}/agency-notifications"""
        return self._request(
            "GET",
            f"/provost/decision-records/{decision_id}/agency-notifications",
            headers=headers,
            params=params,
        )

    def transition_agency_notification(
        self, notification_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /provost/agency-notifications/{id}/transitions"""
        return self._request(
            "POST",
            f"/provost/agency-notifications/{notification_id}/transitions",
            payload,
            headers,
        )

    # --- §3.11 faculty appointments ---------------------------------------

    def transition_faculty_appointment(
        self, appointment_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /provost/faculty-appointments/{id}/transitions"""
        return self._request(
            "POST",
            f"/provost/faculty-appointments/{appointment_id}/transitions",
            payload,
            headers,
        )
