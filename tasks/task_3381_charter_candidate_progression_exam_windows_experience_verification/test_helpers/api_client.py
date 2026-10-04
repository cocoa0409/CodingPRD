"""API client: one method per endpoint defined in the PRD (§4 endpoint table).

All methods return the raw requests.Response so tests assert status codes and
envelopes themselves. List endpoints accept `params` (filters/limit/offset);
action endpoints that take no body default `payload=None` (no JSON body sent).

API MANIFEST (frozen for Phase B):
  api_client: ApiClient — module-level shared instance (base URL comes from the
                          API_BASE_URL env var via the framework; no HTTP at import)

  ApiClient methods (payload-first for creates/actions; headers always required):
    set_clock(to_iso8601, headers)
    create_candidate(payload, headers)
    get_candidate(candidate_id, headers)
    create_program_enrollment(candidate_id, payload, headers)
    list_program_enrollments(headers, params=None)
    get_program_enrollment(enrollment_id, headers)
    post_enrollment_payment(enrollment_id, payload, headers)
    award_charter(enrollment_id, headers, payload=None)
    create_exam_level(payload, headers)
    create_curriculum_cycle(level_id, payload, headers)
    list_curriculum_cycles(headers, params=None)
    get_curriculum_cycle(cycle_id, headers)
    create_exam_window(payload, headers)
    list_exam_windows(headers, params=None)
    get_exam_window(window_id, headers)
    cancel_exam_window(window_id, headers, payload=None)
    create_test_center(payload, headers)
    create_appointment(payload, headers)
    list_appointments(headers, params=None)
    get_appointment(appointment_id, headers)
    reschedule_appointment(appointment_id, payload, headers)
    cancel_appointment(appointment_id, headers, payload=None)
    check_in_appointment(appointment_id, payload, headers)
    list_exam_attempts(headers, params=None)
    get_exam_attempt(attempt_id, headers)
    score_exam_attempt(attempt_id, payload, headers)
    create_experience_submission(candidate_id, payload, headers)
    list_experience_submissions(headers, params=None)
    get_experience_submission(submission_id, headers)
    amend_experience_submission(submission_id, payload, headers)
    submit_experience_submission(submission_id, headers, payload=None)
    review_experience_submission(submission_id, payload, headers)
    create_reference(submission_id, payload, headers)
    list_references(headers, params=None)
    get_reference(reference_id, headers)
    respond_reference(reference_id, payload, headers)
    file_conduct_statement(candidate_id, payload, headers)
    create_misconduct_case(payload, headers)
    list_misconduct_cases(headers, params=None)
    get_misconduct_case(case_id, headers)
    adjudicate_misconduct_case(case_id, payload, headers)
    appeal_misconduct_case(case_id, payload, headers)
    create_society(payload, headers)
    create_membership(society_id, payload, headers)
    list_memberships(headers, params=None)
    get_membership(membership_id, headers)
    renew_membership(membership_id, payload, headers)
    append_ce_record(membership_id, payload, headers)
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """PRD-specific endpoint methods (PRD §4); HTTP plumbing is inherited."""

    # --- Logical clock (test-driving capability, ProgramAdmin only) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Candidates ---
    def create_candidate(self, payload, headers):
        return self._request("POST", "/charter/candidates", payload, headers)

    def get_candidate(self, candidate_id, headers):
        return self._request(
            "GET", f"/charter/candidates/{candidate_id}", headers=headers
        )

    # --- Program enrollments ---
    def create_program_enrollment(self, candidate_id, payload, headers):
        return self._request(
            "POST",
            f"/charter/candidates/{candidate_id}/program-enrollments",
            payload,
            headers,
        )

    def list_program_enrollments(self, headers, params=None):
        return self._request(
            "GET", "/charter/program-enrollments", headers=headers, params=params
        )

    def get_program_enrollment(self, enrollment_id, headers):
        return self._request(
            "GET", f"/charter/program-enrollments/{enrollment_id}", headers=headers
        )

    def post_enrollment_payment(self, enrollment_id, payload, headers):
        return self._request(
            "POST",
            f"/charter/program-enrollments/{enrollment_id}/payments",
            payload,
            headers,
        )

    def award_charter(self, enrollment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/charter/program-enrollments/{enrollment_id}/award-charter",
            payload,
            headers,
        )

    # --- Exam levels & curriculum cycles ---
    def create_exam_level(self, payload, headers):
        return self._request("POST", "/charter/exam-levels", payload, headers)

    def create_curriculum_cycle(self, level_id, payload, headers):
        return self._request(
            "POST",
            f"/charter/exam-levels/{level_id}/curriculum-cycles",
            payload,
            headers,
        )

    def list_curriculum_cycles(self, headers, params=None):
        return self._request(
            "GET", "/charter/curriculum-cycles", headers=headers, params=params
        )

    def get_curriculum_cycle(self, cycle_id, headers):
        return self._request(
            "GET", f"/charter/curriculum-cycles/{cycle_id}", headers=headers
        )

    # --- Exam windows ---
    def create_exam_window(self, payload, headers):
        return self._request("POST", "/charter/exam-windows", payload, headers)

    def list_exam_windows(self, headers, params=None):
        return self._request(
            "GET", "/charter/exam-windows", headers=headers, params=params
        )

    def get_exam_window(self, window_id, headers):
        return self._request(
            "GET", f"/charter/exam-windows/{window_id}", headers=headers
        )

    def cancel_exam_window(self, window_id, headers, payload=None):
        return self._request(
            "POST", f"/charter/exam-windows/{window_id}/cancel", payload, headers
        )

    # --- Test centers ---
    def create_test_center(self, payload, headers):
        return self._request("POST", "/charter/test-centers", payload, headers)

    # --- Appointments ---
    def create_appointment(self, payload, headers):
        return self._request("POST", "/charter/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request(
            "GET", "/charter/appointments", headers=headers, params=params
        )

    def get_appointment(self, appointment_id, headers):
        return self._request(
            "GET", f"/charter/appointments/{appointment_id}", headers=headers
        )

    def reschedule_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST",
            f"/charter/appointments/{appointment_id}/reschedule",
            payload,
            headers,
        )

    def cancel_appointment(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/charter/appointments/{appointment_id}/cancel", payload, headers
        )

    def check_in_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST",
            f"/charter/appointments/{appointment_id}/check-in",
            payload,
            headers,
        )

    # --- Exam attempts ---
    def list_exam_attempts(self, headers, params=None):
        return self._request(
            "GET", "/charter/exam-attempts", headers=headers, params=params
        )

    def get_exam_attempt(self, attempt_id, headers):
        return self._request(
            "GET", f"/charter/exam-attempts/{attempt_id}", headers=headers
        )

    def score_exam_attempt(self, attempt_id, payload, headers):
        return self._request(
            "POST", f"/charter/exam-attempts/{attempt_id}/score", payload, headers
        )

    # --- Work experience submissions ---
    def create_experience_submission(self, candidate_id, payload, headers):
        return self._request(
            "POST",
            f"/charter/candidates/{candidate_id}/experience-submissions",
            payload,
            headers,
        )

    def list_experience_submissions(self, headers, params=None):
        return self._request(
            "GET", "/charter/experience-submissions", headers=headers, params=params
        )

    def get_experience_submission(self, submission_id, headers):
        return self._request(
            "GET",
            f"/charter/experience-submissions/{submission_id}",
            headers=headers,
        )

    def amend_experience_submission(self, submission_id, payload, headers):
        return self._request(
            "POST",
            f"/charter/experience-submissions/{submission_id}/amend",
            payload,
            headers,
        )

    def submit_experience_submission(self, submission_id, headers, payload=None):
        return self._request(
            "POST",
            f"/charter/experience-submissions/{submission_id}/submit",
            payload,
            headers,
        )

    def review_experience_submission(self, submission_id, payload, headers):
        return self._request(
            "POST",
            f"/charter/experience-submissions/{submission_id}/review",
            payload,
            headers,
        )

    # --- Reference contacts ---
    def create_reference(self, submission_id, payload, headers):
        return self._request(
            "POST",
            f"/charter/experience-submissions/{submission_id}/references",
            payload,
            headers,
        )

    def list_references(self, headers, params=None):
        return self._request(
            "GET", "/charter/references", headers=headers, params=params
        )

    def get_reference(self, reference_id, headers):
        return self._request(
            "GET", f"/charter/references/{reference_id}", headers=headers
        )

    def respond_reference(self, reference_id, payload, headers):
        return self._request(
            "POST", f"/charter/references/{reference_id}/respond", payload, headers
        )

    # --- Professional conduct statements ---
    def file_conduct_statement(self, candidate_id, payload, headers):
        return self._request(
            "POST",
            f"/charter/candidates/{candidate_id}/conduct-statements",
            payload,
            headers,
        )

    # --- Misconduct cases ---
    def create_misconduct_case(self, payload, headers):
        return self._request("POST", "/charter/misconduct-cases", payload, headers)

    def list_misconduct_cases(self, headers, params=None):
        return self._request(
            "GET", "/charter/misconduct-cases", headers=headers, params=params
        )

    def get_misconduct_case(self, case_id, headers):
        return self._request(
            "GET", f"/charter/misconduct-cases/{case_id}", headers=headers
        )

    def adjudicate_misconduct_case(self, case_id, payload, headers):
        return self._request(
            "POST",
            f"/charter/misconduct-cases/{case_id}/adjudicate",
            payload,
            headers,
        )

    def appeal_misconduct_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/charter/misconduct-cases/{case_id}/appeal", payload, headers
        )

    # --- Societies, memberships, continuing education ---
    def create_society(self, payload, headers):
        return self._request("POST", "/charter/societies", payload, headers)

    def create_membership(self, society_id, payload, headers):
        return self._request(
            "POST", f"/charter/societies/{society_id}/memberships", payload, headers
        )

    def list_memberships(self, headers, params=None):
        return self._request(
            "GET", "/charter/memberships", headers=headers, params=params
        )

    def get_membership(self, membership_id, headers):
        return self._request(
            "GET", f"/charter/memberships/{membership_id}", headers=headers
        )

    def renew_membership(self, membership_id, payload, headers):
        return self._request(
            "POST", f"/charter/memberships/{membership_id}/renew", payload, headers
        )

    def append_ce_record(self, membership_id, payload, headers):
        return self._request(
            "POST",
            f"/charter/memberships/{membership_id}/ce-records",
            payload,
            headers,
        )


api_client = ApiClient()
