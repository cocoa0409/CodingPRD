"""API client: one method per endpoint defined in the PRD (§4).

Base URL comes from the framework (API_BASE_URL env var injected by the
runner); nothing is hardcoded. Note the logical-clock endpoint lives at the
platform root OUTSIDE the /hiring prefix (PRD §2.5).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Platform: logical clock (PRD §2.5; mounted outside /hiring) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Occupational series ----
    def create_series(self, payload, headers):
        return self._request("POST", "/hiring/series", payload, headers)

    def get_series(self, series_id, headers):
        return self._request("GET", f"/hiring/series/{series_id}", headers=headers)

    def list_series_positions(self, series_id, headers, params=None):
        return self._request("GET", f"/hiring/series/{series_id}/positions", headers=headers, params=params)

    # ---- Positions ----
    def create_position(self, payload, headers):
        return self._request("POST", "/hiring/positions", payload, headers)

    def get_position(self, position_id, headers):
        return self._request("GET", f"/hiring/positions/{position_id}", headers=headers)

    def classify_position(self, position_id, headers):
        return self._request("POST", f"/hiring/positions/{position_id}/classify", {}, headers)

    def reclassify_position(self, position_id, payload, headers):
        return self._request("POST", f"/hiring/positions/{position_id}/reclassifications", payload, headers)

    # ---- Announcements ----
    def create_announcement(self, position_id, payload, headers):
        return self._request("POST", f"/hiring/positions/{position_id}/announcements", payload, headers)

    def get_announcement(self, announcement_id, headers):
        return self._request("GET", f"/hiring/announcements/{announcement_id}", headers=headers)

    def list_position_announcements(self, position_id, headers, params=None):
        return self._request("GET", f"/hiring/positions/{position_id}/announcements", headers=headers, params=params)

    def open_announcement(self, announcement_id, headers):
        return self._request("POST", f"/hiring/announcements/{announcement_id}/open", {}, headers)

    def close_announcement(self, announcement_id, headers):
        return self._request("POST", f"/hiring/announcements/{announcement_id}/close", {}, headers)

    def cancel_announcement(self, announcement_id, headers):
        return self._request("POST", f"/hiring/announcements/{announcement_id}/cancel", {}, headers)

    def list_announcement_applications(self, announcement_id, headers, params=None):
        return self._request("GET", f"/hiring/announcements/{announcement_id}/applications", headers=headers, params=params)

    def list_announcement_certificates(self, announcement_id, headers, params=None):
        return self._request("GET", f"/hiring/announcements/{announcement_id}/certificates", headers=headers, params=params)

    # ---- Applicants and eligibility documents ----
    def create_applicant(self, payload, headers):
        return self._request("POST", "/hiring/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/hiring/applicants/{applicant_id}", headers=headers)

    def list_applicant_applications(self, applicant_id, headers, params=None):
        return self._request("GET", f"/hiring/applicants/{applicant_id}/applications", headers=headers, params=params)

    def upload_document(self, applicant_id, payload, headers):
        return self._request("POST", f"/hiring/applicants/{applicant_id}/documents", payload, headers)

    def list_documents(self, applicant_id, headers, params=None):
        return self._request("GET", f"/hiring/applicants/{applicant_id}/documents", headers=headers, params=params)

    def verify_document(self, document_id, headers):
        return self._request("POST", f"/hiring/documents/{document_id}/verify", {}, headers)

    # ---- Applications ----
    def submit_application(self, announcement_id, payload, headers):
        return self._request("POST", f"/hiring/announcements/{announcement_id}/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/hiring/applications/{application_id}", headers=headers)

    def screen_application(self, application_id, headers):
        return self._request("POST", f"/hiring/applications/{application_id}/screen", {}, headers)

    def list_application_assessments(self, application_id, headers, params=None):
        return self._request("GET", f"/hiring/applications/{application_id}/assessments", headers=headers, params=params)

    def list_application_appeals(self, application_id, headers, params=None):
        return self._request("GET", f"/hiring/applications/{application_id}/appeals", headers=headers, params=params)

    def list_application_certificate_entries(self, application_id, headers, params=None):
        return self._request("GET", f"/hiring/applications/{application_id}/certificate-entries", headers=headers, params=params)

    def file_appeal(self, application_id, payload, headers):
        return self._request("POST", f"/hiring/applications/{application_id}/appeals", payload, headers)

    def adjudicate_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/hiring/appeals/{appeal_id}/adjudicate", payload, headers)

    # ---- Assessments ----
    def create_assessment(self, application_id, payload, headers):
        return self._request("POST", f"/hiring/applications/{application_id}/assessments", payload, headers)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/hiring/assessments/{assessment_id}", headers=headers)

    def submit_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/hiring/assessments/{assessment_id}/submit", payload, headers)

    def accept_assessment(self, assessment_id, headers):
        return self._request("POST", f"/hiring/assessments/{assessment_id}/accept", {}, headers)

    def return_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/hiring/assessments/{assessment_id}/return", payload, headers)

    # ---- Certificates and entries ----
    def issue_certificate(self, announcement_id, headers):
        return self._request("POST", f"/hiring/announcements/{announcement_id}/certificates", {}, headers)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/hiring/certificates/{certificate_id}", headers=headers)

    def extend_certificate(self, certificate_id, payload, headers):
        return self._request("POST", f"/hiring/certificates/{certificate_id}/extend", payload, headers)

    def return_certificate(self, certificate_id, payload, headers):
        return self._request("POST", f"/hiring/certificates/{certificate_id}/return", payload, headers)

    def list_certificate_entries(self, certificate_id, headers, params=None):
        return self._request("GET", f"/hiring/certificates/{certificate_id}/entries", headers=headers, params=params)

    def select_entry(self, certificate_id, payload, headers):
        return self._request("POST", f"/hiring/certificates/{certificate_id}/selections", payload, headers)

    def get_entry(self, entry_id, headers):
        return self._request("GET", f"/hiring/entries/{entry_id}", headers=headers)

    # ---- Pass-over requests ----
    def list_entry_pass_over_requests(self, entry_id, headers, params=None):
        return self._request("GET", f"/hiring/entries/{entry_id}/pass-over-requests", headers=headers, params=params)

    def create_pass_over_request(self, entry_id, payload, headers):
        return self._request("POST", f"/hiring/entries/{entry_id}/pass-over-requests", payload, headers)

    def adjudicate_pass_over(self, request_id, payload, headers):
        return self._request("POST", f"/hiring/pass-over-requests/{request_id}/adjudicate", payload, headers)

    # ---- Offers, suitability, clearance, EOD ----
    def list_offers(self, headers, params=None):
        return self._request("GET", "/hiring/offers", headers=headers, params=params)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/hiring/offers/{offer_id}", headers=headers)

    def respond_to_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/hiring/offers/{offer_id}/respond", payload, headers)

    def record_suitability_review(self, offer_id, payload, headers):
        return self._request("POST", f"/hiring/offers/{offer_id}/suitability-reviews", payload, headers)

    def list_suitability_reviews(self, offer_id, headers, params=None):
        return self._request("GET", f"/hiring/offers/{offer_id}/suitability-reviews", headers=headers, params=params)

    def record_security_clearance(self, offer_id, payload, headers):
        return self._request("POST", f"/hiring/offers/{offer_id}/security-clearances", payload, headers)

    def list_security_clearances(self, offer_id, headers, params=None):
        return self._request("GET", f"/hiring/offers/{offer_id}/security-clearances", headers=headers, params=params)

    def schedule_eod(self, offer_id, payload, headers):
        return self._request("POST", f"/hiring/offers/{offer_id}/schedule-eod", payload, headers)

    def confirm_eod(self, offer_id, headers):
        return self._request("POST", f"/hiring/offers/{offer_id}/confirm-eod", {}, headers)

    def list_appointments(self, offer_id, headers, params=None):
        return self._request("GET", f"/hiring/offers/{offer_id}/appointments", headers=headers, params=params)


api_client = ApiClient()
