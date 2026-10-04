"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Institutions, agreements, reporting periods (PRD section 3.1/3.2) ---
    def create_institution(self, payload, headers):
        return self._request("POST", "/institutions", payload, headers)

    def get_institution(self, institution_id, headers):
        return self._request("GET", f"/institutions/{institution_id}", headers=headers)

    def suspend_institution(self, institution_id, headers):
        return self._request("POST", f"/institutions/{institution_id}/suspend", {}, headers)

    def reinstate_institution(self, institution_id, headers):
        return self._request("POST", f"/institutions/{institution_id}/reinstate", {}, headers)

    def create_agreement(self, institution_id, payload, headers):
        return self._request("POST", f"/institutions/{institution_id}/agreements", payload, headers)

    def list_agreements(self, institution_id, headers, params=None):
        return self._request("GET", f"/institutions/{institution_id}/agreements", headers=headers, params=params)

    def create_reporting_period(self, institution_id, payload, headers):
        return self._request("POST", f"/institutions/{institution_id}/reporting-periods", payload, headers)

    def list_reporting_periods(self, institution_id, headers, params=None):
        return self._request("GET", f"/institutions/{institution_id}/reporting-periods", headers=headers, params=params)

    def list_institution_users(self, institution_id, headers, params=None):
        return self._request("GET", f"/institutions/{institution_id}/users", headers=headers, params=params)

    def list_institution_research_datasets(self, institution_id, headers, params=None):
        return self._request("GET", f"/institutions/{institution_id}/research-datasets", headers=headers, params=params)

    # --- Enrollment files and entries (PRD section 3.3/3.4) ---
    def create_enrollment_file(self, payload, headers):
        return self._request("POST", "/enrollment-files", payload, headers)

    def get_enrollment_file(self, file_id, headers):
        return self._request("GET", f"/enrollment-files/{file_id}", headers=headers)

    def list_enrollment_files(self, headers, params=None):
        return self._request("GET", "/enrollment-files", headers=headers, params=params)

    def certify_enrollment_file(self, file_id, headers):
        return self._request("POST", f"/enrollment-files/{file_id}/certify", {}, headers)

    def get_enrollment_entry(self, entry_id, headers):
        return self._request("GET", f"/enrollment-entries/{entry_id}", headers=headers)

    def list_enrollment_entries(self, headers, params=None):
        return self._request("GET", "/enrollment-entries", headers=headers, params=params)

    # --- Correction cases (PRD section 3.5) ---
    def create_correction_case(self, payload, headers):
        return self._request("POST", "/correction-cases", payload, headers)

    def get_correction_case(self, case_id, headers):
        return self._request("GET", f"/correction-cases/{case_id}", headers=headers)

    def list_correction_cases(self, headers, params=None):
        return self._request("GET", "/correction-cases", headers=headers, params=params)

    def decide_correction_case(self, case_id, payload, headers):
        return self._request("POST", f"/correction-cases/{case_id}/decision", payload, headers)

    # --- Degree records (PRD section 3.6) ---
    def create_degree_record(self, payload, headers):
        return self._request("POST", "/degree-records", payload, headers)

    def get_degree_record(self, degree_id, headers):
        return self._request("GET", f"/degree-records/{degree_id}", headers=headers)

    def list_degree_records(self, headers, params=None):
        return self._request("GET", "/degree-records", headers=headers, params=params)

    def seal_degree_record(self, degree_id, headers):
        return self._request("POST", f"/degree-records/{degree_id}/seal", {}, headers)

    def revoke_degree_record(self, degree_id, headers):
        return self._request("POST", f"/degree-records/{degree_id}/revoke", {}, headers)

    # --- Requesters (PRD section 3.7) ---
    def create_requester(self, payload, headers):
        return self._request("POST", "/requesters", payload, headers)

    def get_requester(self, requester_id, headers):
        return self._request("GET", f"/requesters/{requester_id}", headers=headers)

    def vet_requester(self, requester_id, payload, headers):
        return self._request("POST", f"/requesters/{requester_id}/vet", payload, headers)

    def suspend_requester(self, requester_id, headers):
        return self._request("POST", f"/requesters/{requester_id}/suspend", {}, headers)

    # --- Verification requests (PRD section 3.7) ---
    def create_verification_request(self, payload, headers):
        return self._request("POST", "/verification-requests", payload, headers)

    def get_verification_request(self, request_id, headers):
        return self._request("GET", f"/verification-requests/{request_id}", headers=headers)

    def list_verification_requests(self, headers, params=None):
        return self._request("GET", "/verification-requests", headers=headers, params=params)

    def pay_verification_request(self, request_id, headers):
        return self._request("POST", f"/verification-requests/{request_id}/pay", {}, headers)

    def fulfill_verification_request(self, request_id, headers):
        return self._request("POST", f"/verification-requests/{request_id}/fulfill", {}, headers)

    # --- Students and privacy directives (PRD section 3.8) ---
    def create_privacy_directive(self, student_id, payload, headers):
        return self._request("POST", f"/students/{student_id}/privacy-directives", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def list_privacy_directives(self, student_id, headers, params=None):
        return self._request("GET", f"/students/{student_id}/privacy-directives", headers=headers, params=params)

    # --- Servicer notifications (PRD section 3.4) ---
    def get_servicer_notification(self, notification_id, headers):
        return self._request("GET", f"/servicer-notifications/{notification_id}", headers=headers)

    def list_servicer_notifications(self, headers, params=None):
        return self._request("GET", "/servicer-notifications", headers=headers, params=params)

    def acknowledge_servicer_notification(self, notification_id, headers):
        return self._request("POST", f"/servicer-notifications/{notification_id}/acknowledge", {}, headers)

    # --- Research datasets (PRD section 3.9) ---
    def create_research_dataset(self, payload, headers):
        return self._request("POST", "/research-datasets", payload, headers)

    def generate_research_dataset(self, dataset_id, headers):
        return self._request("POST", f"/research-datasets/{dataset_id}/generate", {}, headers)

    # --- Logical clock (PRD section 2.4) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
