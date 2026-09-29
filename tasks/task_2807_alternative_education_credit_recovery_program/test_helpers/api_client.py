"""One method per endpoint of the Alternative Education & Credit Recovery API.

Every method returns the raw response so a test may assert on the status code
as well as the body.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

Headers = Optional[Dict[str, str]]
Payload = Optional[Dict[str, Any]]
Params = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """Endpoint-level client."""

    # ------------------------------------------------------------------
    # Home schools
    # ------------------------------------------------------------------
    def create_home_school(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/home-schools", payload, headers)

    def get_home_school(self, home_school_id: str, headers: Headers = None):
        return self._request("GET", f"/home-schools/{home_school_id}", None, headers)

    def list_home_schools(self, headers: Headers = None, params: Params = None):
        return self._request("GET", "/home-schools", None, headers, params=params)

    # ------------------------------------------------------------------
    # Centers
    # ------------------------------------------------------------------
    def create_center(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/centers", payload, headers)

    def get_center(self, center_id: str, headers: Headers = None):
        return self._request("GET", f"/centers/{center_id}", None, headers)

    def list_centers(self, headers: Headers = None, params: Params = None):
        return self._request("GET", "/centers", None, headers, params=params)

    def revise_staffing(self, center_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "PATCH", f"/centers/{center_id}/staffing", payload, headers
        )

    # ------------------------------------------------------------------
    # Courses
    # ------------------------------------------------------------------
    def create_course(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/courses", payload, headers)

    def get_course(self, course_id: str, headers: Headers = None):
        return self._request("GET", f"/courses/{course_id}", None, headers)

    def list_courses(self, headers: Headers = None, params: Params = None):
        return self._request("GET", "/courses", None, headers, params=params)

    # ------------------------------------------------------------------
    # Students
    # ------------------------------------------------------------------
    def create_student(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/students", payload, headers)

    def get_student(self, student_id: str, headers: Headers = None):
        return self._request("GET", f"/students/{student_id}", None, headers)

    def list_students(self, headers: Headers = None, params: Params = None):
        return self._request("GET", "/students", None, headers, params=params)

    # ------------------------------------------------------------------
    # Prior course records
    # ------------------------------------------------------------------
    def create_prior_course_record(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/prior-course-records", payload, headers)

    def get_prior_course_record(
        self, prior_course_record_id: str, headers: Headers = None
    ):
        return self._request(
            "GET", f"/prior-course-records/{prior_course_record_id}", None, headers
        )

    def list_prior_course_records(self, headers: Headers = None, params: Params = None):
        return self._request(
            "GET", "/prior-course-records", None, headers, params=params
        )

    # ------------------------------------------------------------------
    # Graduation plans
    # ------------------------------------------------------------------
    def create_graduation_plan(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/graduation-plans", payload, headers)

    def get_graduation_plan(self, graduation_plan_id: str, headers: Headers = None):
        return self._request(
            "GET", f"/graduation-plans/{graduation_plan_id}", None, headers
        )

    def list_graduation_plans(self, headers: Headers = None, params: Params = None):
        return self._request("GET", "/graduation-plans", None, headers, params=params)

    def activate_graduation_plan(
        self, graduation_plan_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"/graduation-plans/{graduation_plan_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Referrals
    # ------------------------------------------------------------------
    def create_referral(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/referrals", payload, headers)

    def get_referral(self, referral_id: str, headers: Headers = None):
        return self._request("GET", f"/referrals/{referral_id}", None, headers)

    def list_referrals(self, headers: Headers = None, params: Params = None):
        return self._request("GET", "/referrals", None, headers, params=params)

    def screen_referral(
        self, referral_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"/referrals/{referral_id}/screen",
            payload if payload is not None else {},
            headers,
        )

    def request_referral_info(
        self, referral_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"/referrals/{referral_id}/request-info", payload, headers
        )

    def resubmit_referral(
        self, referral_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"/referrals/{referral_id}/resubmit", payload, headers
        )

    def offer_referral(
        self, referral_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request("POST", f"/referrals/{referral_id}/offer", payload, headers)

    def waitlist_referral(
        self, referral_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"/referrals/{referral_id}/waitlist", payload, headers
        )

    def deny_referral(
        self, referral_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request("POST", f"/referrals/{referral_id}/deny", payload, headers)

    def withdraw_offer(
        self, referral_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"/referrals/{referral_id}/withdraw-offer",
            payload if payload is not None else {},
            headers,
        )

    def accept_offer(
        self, referral_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"/referrals/{referral_id}/accept-offer", payload, headers
        )

    # ------------------------------------------------------------------
    # Placements
    # ------------------------------------------------------------------
    def get_placement(self, placement_id: str, headers: Headers = None):
        return self._request("GET", f"/placements/{placement_id}", None, headers)

    def list_placements(self, headers: Headers = None, params: Params = None):
        return self._request("GET", "/placements", None, headers, params=params)

    def log_attendance(
        self, placement_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"/placements/{placement_id}/attendance", payload, headers
        )

    def request_re_entry(
        self, placement_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"/placements/{placement_id}/request-re-entry", payload, headers
        )

    def approve_re_entry(
        self, placement_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"/placements/{placement_id}/approve-re-entry", payload, headers
        )

    def deny_re_entry(
        self, placement_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"/placements/{placement_id}/deny-re-entry", payload, headers
        )

    def exit_placement(
        self, placement_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"/placements/{placement_id}/exit", payload, headers
        )

    # ------------------------------------------------------------------
    # Course enrollments
    # ------------------------------------------------------------------
    def create_course_enrollment(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/course-enrollments", payload, headers)

    def get_course_enrollment(
        self, course_enrollment_id: str, headers: Headers = None
    ):
        return self._request(
            "GET", f"/course-enrollments/{course_enrollment_id}", None, headers
        )

    def list_course_enrollments(self, headers: Headers = None, params: Params = None):
        return self._request("GET", "/course-enrollments", None, headers, params=params)

    def report_progress(
        self, course_enrollment_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"/course-enrollments/{course_enrollment_id}/progress",
            payload,
            headers,
        )

    def submit_for_award(
        self, course_enrollment_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"/course-enrollments/{course_enrollment_id}/submit-for-award",
            payload,
            headers,
        )

    def award_credit(
        self, course_enrollment_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"/course-enrollments/{course_enrollment_id}/award-credit",
            payload,
            headers,
        )

    def deny_award(
        self, course_enrollment_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"/course-enrollments/{course_enrollment_id}/deny-award",
            payload,
            headers,
        )

    def flag_integrity(
        self, course_enrollment_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"/course-enrollments/{course_enrollment_id}/flag-integrity",
            payload,
            headers,
        )

    def resolve_integrity(
        self, course_enrollment_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"/course-enrollments/{course_enrollment_id}/resolve-integrity",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Credit awards
    # ------------------------------------------------------------------
    def get_credit_award(self, credit_award_id: str, headers: Headers = None):
        return self._request("GET", f"/credit-awards/{credit_award_id}", None, headers)

    def list_credit_awards(self, headers: Headers = None, params: Params = None):
        return self._request("GET", "/credit-awards", None, headers, params=params)

    def void_credit_award(
        self, credit_award_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"/credit-awards/{credit_award_id}/void", payload, headers
        )

    # ------------------------------------------------------------------
    # Proctoring stations
    # ------------------------------------------------------------------
    def create_proctor_station(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/proctor-stations", payload, headers)

    def get_proctor_station(self, proctor_station_id: str, headers: Headers = None):
        return self._request(
            "GET", f"/proctor-stations/{proctor_station_id}", None, headers
        )

    def list_proctor_stations(self, headers: Headers = None, params: Params = None):
        return self._request("GET", "/proctor-stations", None, headers, params=params)

    # ------------------------------------------------------------------
    # Proctored exam sessions
    # ------------------------------------------------------------------
    def create_proctor_session(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/proctor-sessions", payload, headers)

    def get_proctor_session(self, proctor_session_id: str, headers: Headers = None):
        return self._request(
            "GET", f"/proctor-sessions/{proctor_session_id}", None, headers
        )

    def list_proctor_sessions(self, headers: Headers = None, params: Params = None):
        return self._request("GET", "/proctor-sessions", None, headers, params=params)

    def complete_proctor_session(
        self, proctor_session_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"/proctor-sessions/{proctor_session_id}/complete", payload, headers
        )

    def no_show_proctor_session(
        self, proctor_session_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"/proctor-sessions/{proctor_session_id}/no-show",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Support providers
    # ------------------------------------------------------------------
    def create_support_provider(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/support-providers", payload, headers)

    def get_support_provider(self, support_provider_id: str, headers: Headers = None):
        return self._request(
            "GET", f"/support-providers/{support_provider_id}", None, headers
        )

    def list_support_providers(self, headers: Headers = None, params: Params = None):
        return self._request("GET", "/support-providers", None, headers, params=params)

    # ------------------------------------------------------------------
    # Support sessions
    # ------------------------------------------------------------------
    def create_support_session(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/support-sessions", payload, headers)

    def get_support_session(self, support_session_id: str, headers: Headers = None):
        return self._request(
            "GET", f"/support-sessions/{support_session_id}", None, headers
        )

    def list_support_sessions(self, headers: Headers = None, params: Params = None):
        return self._request("GET", "/support-sessions", None, headers, params=params)

    def complete_support_session(
        self, support_session_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"/support-sessions/{support_session_id}/complete",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def advance_clock_to(self, current_utc: str, headers: Headers = None):
        """Convenience wrapper naming the instant the clock should read."""
        return self.set_clock({"current_utc": current_utc}, headers)


#: Module-level singleton the pytest fixtures expose.
api_client = ApiClient()
