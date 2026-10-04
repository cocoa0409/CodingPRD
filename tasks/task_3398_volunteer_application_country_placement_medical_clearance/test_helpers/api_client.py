"""API client: one method per endpoint defined in the PRD.

All resources live under the /volunteer-portal prefix; the logical clock is
exposed separately under /_clock. Methods return the raw requests.Response so
tests can assert status codes and envelope bodies.
"""

from prd_bench_local_runner.testing import GenericApiClient

PORTAL = "/volunteer-portal"


class ApiClient(GenericApiClient):
    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            payload={"to_iso8601": to_iso8601}, headers=headers,
        )

    # --- Applicants ---
    def create_applicant(self, payload, headers):
        return self._request("POST", f"{PORTAL}/applicants", payload, headers)

    # --- Country programs ---
    def create_country_program(self, payload, headers):
        return self._request("POST", f"{PORTAL}/country-programs", payload, headers)

    def get_country_program(self, program_id, headers):
        return self._request("GET", f"{PORTAL}/country-programs/{program_id}", headers=headers)

    def update_country_program(self, program_id, payload, headers):
        return self._request("PATCH", f"{PORTAL}/country-programs/{program_id}", payload, headers)

    # --- Assignment openings ---
    def create_assignment_opening(self, payload, headers):
        return self._request("POST", f"{PORTAL}/assignment-openings", payload, headers)

    def get_assignment_opening(self, opening_id, headers):
        return self._request("GET", f"{PORTAL}/assignment-openings/{opening_id}", headers=headers)

    def list_assignment_openings(self, headers, params=None):
        return self._request("GET", f"{PORTAL}/assignment-openings", headers=headers, params=params)

    def cancel_assignment_opening(self, opening_id, headers):
        return self._request("POST", f"{PORTAL}/assignment-openings/{opening_id}/cancel", headers=headers)

    # --- Applications ---
    def create_application(self, payload, headers):
        return self._request("POST", f"{PORTAL}/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"{PORTAL}/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", f"{PORTAL}/applications", headers=headers, params=params)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"{PORTAL}/applications/{application_id}/submit", headers=headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"{PORTAL}/applications/{application_id}/withdraw", headers=headers)

    def begin_review_application(self, application_id, headers):
        return self._request("POST", f"{PORTAL}/applications/{application_id}/begin-review", headers=headers)

    def reject_application(self, application_id, headers):
        return self._request("POST", f"{PORTAL}/applications/{application_id}/reject", headers=headers)

    def get_application_matches(self, application_id, headers):
        return self._request("GET", f"{PORTAL}/applications/{application_id}/matches", headers=headers)

    # --- Interviews ---
    def create_interview(self, application_id, payload, headers):
        return self._request("POST", f"{PORTAL}/applications/{application_id}/interviews", payload, headers)

    def list_interviews(self, application_id, headers):
        return self._request("GET", f"{PORTAL}/applications/{application_id}/interviews", headers=headers)

    def complete_interview(self, interview_id, payload, headers):
        return self._request("POST", f"{PORTAL}/interviews/{interview_id}/complete", payload, headers)

    def cancel_interview(self, interview_id, headers):
        return self._request("POST", f"{PORTAL}/interviews/{interview_id}/cancel", headers=headers)

    # --- Invitations ---
    def create_invitation(self, payload, headers):
        return self._request("POST", f"{PORTAL}/invitations", payload, headers)

    def get_invitation(self, invitation_id, headers):
        return self._request("GET", f"{PORTAL}/invitations/{invitation_id}", headers=headers)

    def list_invitations(self, headers, params=None):
        return self._request("GET", f"{PORTAL}/invitations", headers=headers, params=params)

    def accept_invitation(self, invitation_id, headers):
        return self._request("POST", f"{PORTAL}/invitations/{invitation_id}/accept", headers=headers)

    def decline_invitation(self, invitation_id, headers):
        return self._request("POST", f"{PORTAL}/invitations/{invitation_id}/decline", headers=headers)

    # --- Medical clearances ---
    def create_medical_clearance(self, payload, headers):
        return self._request("POST", f"{PORTAL}/medical-clearances", payload, headers)

    def list_medical_clearances(self, application_id, headers):
        return self._request("GET", f"{PORTAL}/applications/{application_id}/medical-clearances", headers=headers)

    def determine_medical_clearance(self, clearance_id, payload, headers):
        return self._request("POST", f"{PORTAL}/medical-clearances/{clearance_id}/determine", payload, headers)

    def resubmit_medical_clearance(self, clearance_id, payload, headers):
        return self._request("POST", f"{PORTAL}/medical-clearances/{clearance_id}/resubmit", payload, headers)

    # --- Legal clearances ---
    def list_legal_clearances(self, application_id, headers):
        return self._request("GET", f"{PORTAL}/applications/{application_id}/legal-clearances", headers=headers)

    def adjudicate_background(self, clearance_id, payload, headers):
        return self._request("POST", f"{PORTAL}/legal-clearances/{clearance_id}/adjudicate-background", payload, headers)

    def determine_suitability(self, clearance_id, payload, headers):
        return self._request("POST", f"{PORTAL}/legal-clearances/{clearance_id}/determine-suitability", payload, headers)

    # --- Training cohorts ---
    def create_training_cohort(self, payload, headers):
        return self._request("POST", f"{PORTAL}/training-cohorts", payload, headers)

    def get_training_cohort(self, cohort_id, headers):
        return self._request("GET", f"{PORTAL}/training-cohorts/{cohort_id}", headers=headers)

    def list_training_cohorts(self, headers, params=None):
        return self._request("GET", f"{PORTAL}/training-cohorts", headers=headers, params=params)

    # --- Training enrollments ---
    def create_training_enrollment(self, payload, headers):
        return self._request("POST", f"{PORTAL}/training-enrollments", payload, headers)

    def get_training_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"{PORTAL}/training-enrollments/{enrollment_id}", headers=headers)

    def list_training_enrollments(self, headers, params=None):
        return self._request("GET", f"{PORTAL}/training-enrollments", headers=headers, params=params)

    def assess_training_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"{PORTAL}/training-enrollments/{enrollment_id}/assess", payload, headers)

    def remediate_training_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"{PORTAL}/training-enrollments/{enrollment_id}/remediate", headers=headers)

    def swear_in_training_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"{PORTAL}/training-enrollments/{enrollment_id}/swear-in", headers=headers)

    # --- Volunteer services ---
    def get_volunteer_service(self, service_id, headers):
        return self._request("GET", f"{PORTAL}/volunteer-services/{service_id}", headers=headers)

    def list_volunteer_services(self, headers, params=None):
        return self._request("GET", f"{PORTAL}/volunteer-services", headers=headers, params=params)

    def create_service_event(self, service_id, payload, headers):
        return self._request("POST", f"{PORTAL}/volunteer-services/{service_id}/events", payload, headers)

    def list_service_events(self, service_id, headers):
        return self._request("GET", f"{PORTAL}/volunteer-services/{service_id}/events", headers=headers)

    def early_terminate_service(self, service_id, payload, headers):
        return self._request("POST", f"{PORTAL}/volunteer-services/{service_id}/early-terminate", payload, headers)

    def complete_service(self, service_id, headers):
        return self._request("POST", f"{PORTAL}/volunteer-services/{service_id}/complete", headers=headers)

    def get_completion_record(self, service_id, headers):
        return self._request("GET", f"{PORTAL}/volunteer-services/{service_id}/completion-record", headers=headers)

    # --- Site placements ---
    def create_site_placement(self, service_id, payload, headers):
        return self._request("POST", f"{PORTAL}/volunteer-services/{service_id}/site-placements", payload, headers)

    def list_site_placements(self, service_id, headers):
        return self._request("GET", f"{PORTAL}/volunteer-services/{service_id}/site-placements", headers=headers)

    def review_site_placement(self, placement_id, payload, headers):
        return self._request("POST", f"{PORTAL}/site-placements/{placement_id}/review", payload, headers)


api_client = ApiClient()
