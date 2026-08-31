"""API client: one method per endpoint the PRD declares."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Employees ----------------
    def create_employee(self, payload, headers):
        return self._request("POST", "/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/employees/{employee_id}", headers=headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/employees", headers=headers, params=params)

    # ---------------- Job profiles ----------------
    def create_job_profile(self, payload, headers):
        return self._request("POST", "/job-profiles", payload, headers)

    def get_job_profile(self, profile_id, headers):
        return self._request("GET", f"/job-profiles/{profile_id}", headers=headers)

    def publish_job_profile(self, profile_id, payload, headers):
        return self._request(
            "POST", f"/job-profiles/{profile_id}/publish", payload, headers
        )

    # ---------------- Essential functions ----------------
    def create_essential_function(self, profile_id, payload, headers):
        return self._request(
            "POST", f"/job-profiles/{profile_id}/essential-functions", payload, headers
        )

    def list_essential_functions(self, profile_id, headers, params=None):
        return self._request(
            "GET",
            f"/job-profiles/{profile_id}/essential-functions",
            headers=headers,
            params=params,
        )

    def update_essential_function(self, function_id, payload, headers):
        return self._request(
            "PATCH", f"/essential-functions/{function_id}", payload, headers
        )

    # ---------------- Accommodation cases ----------------
    def create_accommodation_request(self, payload, headers):
        return self._request("POST", "/accommodation-requests", payload, headers)

    def get_accommodation_request(self, request_id, headers):
        return self._request(
            "GET", f"/accommodation-requests/{request_id}", headers=headers
        )

    def list_accommodation_requests(self, headers, params=None):
        return self._request(
            "GET", "/accommodation-requests", headers=headers, params=params
        )

    def update_accommodation_request(self, request_id, payload, headers):
        return self._request(
            "PATCH", f"/accommodation-requests/{request_id}", payload, headers
        )

    def advance_accommodation_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/accommodation-requests/{request_id}/advance", payload, headers
        )

    def decide_accommodation_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/accommodation-requests/{request_id}/decide", payload, headers
        )

    def renewal_review(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"/accommodation-requests/{request_id}/renewal-review",
            payload,
            headers,
        )

    def set_confidentiality(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"/accommodation-requests/{request_id}/confidentiality",
            payload,
            headers,
        )

    # ---------------- Medical documentation rounds ----------------
    def create_medical_doc_request(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"/accommodation-requests/{request_id}/medical-doc-requests",
            payload,
            headers,
        )

    def list_medical_doc_requests(self, request_id, headers, params=None):
        return self._request(
            "GET",
            f"/accommodation-requests/{request_id}/medical-doc-requests",
            headers=headers,
            params=params,
        )

    def respond_medical_doc_request(self, doc_request_id, payload, headers):
        return self._request(
            "POST", f"/medical-doc-requests/{doc_request_id}/respond", payload, headers
        )

    def adjudicate_medical_doc_request(self, doc_request_id, payload, headers):
        return self._request(
            "POST",
            f"/medical-doc-requests/{doc_request_id}/adjudicate",
            payload,
            headers,
        )

    def withdraw_medical_doc_request(self, doc_request_id, headers):
        return self._request(
            "POST", f"/medical-doc-requests/{doc_request_id}/withdraw", {}, headers
        )

    # ---------------- Function analyses ----------------
    def create_function_analysis(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"/accommodation-requests/{request_id}/function-analyses",
            payload,
            headers,
        )

    def get_function_analysis(self, analysis_id, headers):
        return self._request(
            "GET", f"/function-analyses/{analysis_id}", headers=headers
        )

    def list_function_analyses(self, headers, params=None):
        return self._request(
            "GET", "/function-analyses", headers=headers, params=params
        )

    def update_function_analysis(self, analysis_id, payload, headers):
        return self._request(
            "PATCH", f"/function-analyses/{analysis_id}", payload, headers
        )

    # ---------------- Accommodation options ----------------
    def create_accommodation_option(self, request_id, payload, headers):
        return self._request(
            "POST", f"/accommodation-requests/{request_id}/options", payload, headers
        )

    def list_request_options(self, request_id, headers, params=None):
        return self._request(
            "GET",
            f"/accommodation-requests/{request_id}/options",
            headers=headers,
            params=params,
        )

    def get_accommodation_option(self, option_id, headers):
        return self._request(
            "GET", f"/accommodation-options/{option_id}", headers=headers
        )

    def update_accommodation_option(self, option_id, payload, headers):
        return self._request(
            "PATCH", f"/accommodation-options/{option_id}", payload, headers
        )

    # ---------------- Undue-hardship assessments ----------------
    def create_hardship_assessment(self, option_id, payload, headers):
        return self._request(
            "POST",
            f"/accommodation-options/{option_id}/hardship-assessments",
            payload,
            headers,
        )

    def list_hardship_assessments(self, option_id, headers, params=None):
        return self._request(
            "GET",
            f"/accommodation-options/{option_id}/hardship-assessments",
            headers=headers,
            params=params,
        )

    # ---------------- Trial periods ----------------
    def create_trial_period(self, payload, headers):
        return self._request("POST", "/trial-periods", payload, headers)

    def get_trial_period(self, trial_id, headers):
        return self._request("GET", f"/trial-periods/{trial_id}", headers=headers)

    def list_trial_periods(self, headers, params=None):
        return self._request("GET", "/trial-periods", headers=headers, params=params)

    def create_effectiveness_review(self, trial_id, payload, headers):
        return self._request(
            "POST", f"/trial-periods/{trial_id}/effectiveness-reviews", payload, headers
        )

    def list_effectiveness_reviews(self, trial_id, headers, params=None):
        return self._request(
            "GET",
            f"/trial-periods/{trial_id}/effectiveness-reviews",
            headers=headers,
            params=params,
        )

    def resolve_trial_period(self, trial_id, payload, headers):
        return self._request(
            "POST", f"/trial-periods/{trial_id}/resolve", payload, headers
        )

    # ---------------- Denials and appeals ----------------
    def get_denial_record(self, denial_id, headers):
        return self._request("GET", f"/denial-records/{denial_id}", headers=headers)

    def list_denial_records(self, headers, params=None):
        return self._request("GET", "/denial-records", headers=headers, params=params)

    def create_appeal(self, denial_id, payload, headers):
        return self._request(
            "POST", f"/denial-records/{denial_id}/appeals", payload, headers
        )

    def list_denial_appeals(self, denial_id, headers, params=None):
        return self._request(
            "GET", f"/denial-records/{denial_id}/appeals", headers=headers, params=params
        )

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def transition_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/transition", payload, headers)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/decide", payload, headers)

    # ---------------- Medical disclosure log ----------------
    def create_medical_disclosure(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"/accommodation-requests/{request_id}/medical-disclosures",
            payload,
            headers,
        )

    def list_medical_disclosures(self, request_id, headers, params=None):
        return self._request(
            "GET",
            f"/accommodation-requests/{request_id}/medical-disclosures",
            headers=headers,
            params=params,
        )

    # ---------------- Absence records ----------------
    def create_absence_record(self, payload, headers):
        return self._request("POST", "/absence-records", payload, headers)

    def get_absence_record(self, absence_id, headers):
        return self._request("GET", f"/absence-records/{absence_id}", headers=headers)

    def list_absence_records(self, headers, params=None):
        return self._request("GET", "/absence-records", headers=headers, params=params)

    def transition_absence_record(self, absence_id, payload, headers):
        return self._request(
            "POST", f"/absence-records/{absence_id}/transition", payload, headers
        )

    # ---------------- Operational endpoints ----------------
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def daily_sweep(self, headers):
        return self._request("POST", "/_ops/daily-sweep", {}, headers)


api_client = ApiClient()
