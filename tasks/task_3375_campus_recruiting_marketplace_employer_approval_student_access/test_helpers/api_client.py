"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock --------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- universities ---------------------------------------------------
    def create_university(self, payload, headers):
        return self._request("POST", "/universities", payload, headers)

    def transition_university(self, university_id, payload, headers):
        return self._request(
            "POST", f"/universities/{university_id}/transition", payload, headers
        )

    def get_outcome_report(self, university_id, headers):
        return self._request(
            "GET", f"/universities/{university_id}/outcome-report", headers=headers
        )

    # ---- students -------------------------------------------------------
    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def patch_student(self, student_id, payload, headers):
        return self._request("PATCH", f"/students/{student_id}", payload, headers)

    # ---- employers ------------------------------------------------------
    def create_employer(self, payload, headers):
        return self._request("POST", "/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/employers/{employer_id}", headers=headers)

    def verify_domain(self, employer_id, payload, headers):
        return self._request(
            "POST", f"/employers/{employer_id}/verify-domain", payload, headers
        )

    def screen_employer(self, employer_id, payload, headers):
        return self._request(
            "POST", f"/employers/{employer_id}/screen", payload, headers
        )

    # ---- employer approvals ---------------------------------------------
    def create_employer_approval(self, payload, headers):
        return self._request("POST", "/employer-approvals", payload, headers)

    def list_employer_approvals(self, headers, params=None):
        return self._request("GET", "/employer-approvals", headers=headers, params=params)

    def get_employer_approval(self, approval_id, headers):
        return self._request(
            "GET", f"/employer-approvals/{approval_id}", headers=headers
        )

    def decide_employer_approval(self, approval_id, payload, headers):
        return self._request(
            "POST", f"/employer-approvals/{approval_id}/decide", payload, headers
        )

    # ---- job postings ---------------------------------------------------
    def create_job_posting(self, payload, headers):
        return self._request("POST", "/job-postings", payload, headers)

    def list_job_postings(self, headers, params=None):
        return self._request("GET", "/job-postings", headers=headers, params=params)

    def get_job_posting(self, posting_id, headers):
        return self._request("GET", f"/job-postings/{posting_id}", headers=headers)

    def transition_job_posting(self, posting_id, payload, headers):
        return self._request(
            "POST", f"/job-postings/{posting_id}/transition", payload, headers
        )

    def clearance_job_posting(self, posting_id, payload, headers):
        return self._request(
            "POST", f"/job-postings/{posting_id}/clearance", payload, headers
        )

    # ---- career events and sessions -------------------------------------
    def create_career_event(self, payload, headers):
        return self._request("POST", "/career-events", payload, headers)

    def list_career_events(self, headers, params=None):
        return self._request("GET", "/career-events", headers=headers, params=params)

    def get_career_event(self, event_id, headers):
        return self._request("GET", f"/career-events/{event_id}", headers=headers)

    def transition_career_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/career-events/{event_id}/transition", payload, headers
        )

    def create_event_session(self, event_id, payload, headers):
        return self._request(
            "POST", f"/career-events/{event_id}/sessions", payload, headers
        )

    def list_event_sessions(self, event_id, headers, params=None):
        return self._request(
            "GET", f"/career-events/{event_id}/sessions", headers=headers, params=params
        )

    # ---- event signups --------------------------------------------------
    def create_event_signup(self, payload, headers):
        return self._request("POST", "/event-signups", payload, headers)

    def list_event_signups(self, headers, params=None):
        return self._request("GET", "/event-signups", headers=headers, params=params)

    def get_event_signup(self, signup_id, headers):
        return self._request("GET", f"/event-signups/{signup_id}", headers=headers)

    def transition_event_signup(self, signup_id, payload, headers):
        return self._request(
            "POST", f"/event-signups/{signup_id}/transition", payload, headers
        )

    # ---- applications ---------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def transition_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/transition", payload, headers
        )

    # ---- interviews -----------------------------------------------------
    def create_interview(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/interviews", payload, headers
        )

    def list_interviews(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/applications/{application_id}/interviews",
            headers=headers, params=params,
        )

    # ---- outreach messages ----------------------------------------------
    def create_outreach_message(self, payload, headers):
        return self._request("POST", "/outreach-messages", payload, headers)

    def list_outreach_messages(self, headers, params=None):
        return self._request(
            "GET", "/outreach-messages", headers=headers, params=params
        )

    def get_outreach_message(self, message_id, headers):
        return self._request(
            "GET", f"/outreach-messages/{message_id}", headers=headers
        )


api_client = ApiClient()
