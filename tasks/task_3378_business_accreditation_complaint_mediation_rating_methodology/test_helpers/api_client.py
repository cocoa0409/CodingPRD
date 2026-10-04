"""API client: one method per endpoint defined in PRD §4.

All paths are relative to the server root (no URL prefix — PRD §2.6).
Creation endpoints return 201; transition/decision endpoints and reads
return 200 (PRD §4). Callers pass the expected status explicitly to
validate_success(); fixtures use get_success_data() (lenient).
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Bureaus & operations ---
    def create_bureau(self, payload, headers):
        return self._request("POST", "/bureaus", payload, headers)

    def run_daily_close(self, bureau_id, headers):
        return self._request(
            "POST", f"/bureaus/{bureau_id}/run_daily_close", {}, headers)

    # --- Consumers ---
    def create_consumer(self, payload, headers):
        return self._request("POST", "/consumers", payload, headers)

    # --- Businesses ---
    def create_business(self, payload, headers):
        return self._request("POST", "/businesses", payload, headers)

    def get_business(self, business_id, headers):
        return self._request("GET", f"/businesses/{business_id}",
                             headers=headers)

    def list_businesses(self, headers, params=None):
        return self._request("GET", "/businesses", headers=headers,
                             params=params)

    # --- Accreditation applications ---
    def create_accreditation_application(self, business_id, payload, headers):
        return self._request(
            "POST", f"/businesses/{business_id}/accreditation-applications",
            payload, headers)

    def list_accreditation_applications(self, business_id, headers,
                                        params=None):
        return self._request(
            "GET", f"/businesses/{business_id}/accreditation-applications",
            headers=headers, params=params)

    def submit_application(self, application_id, headers):
        return self._request(
            "POST", f"/accreditation-applications/{application_id}/submit",
            {}, headers)

    def decide_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/accreditation-applications/{application_id}/decision",
            payload, headers)

    # --- Dues invoices ---
    def list_dues_invoices(self, business_id, headers, params=None):
        return self._request("GET", f"/businesses/{business_id}/dues-invoices",
                             headers=headers, params=params)

    def post_ledger_entry(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/dues-invoices/{invoice_id}/ledger-entries",
            payload, headers)

    # --- Complaints ---
    def create_complaint(self, payload, headers):
        return self._request("POST", "/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/complaints/{complaint_id}",
                             headers=headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/complaints", headers=headers,
                             params=params)

    def forward_complaint(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/forward",
                             {}, headers)

    def add_complaint_response(self, complaint_id, payload, headers):
        return self._request("POST", f"/complaints/{complaint_id}/responses",
                             payload, headers)

    def reopen_complaint(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/reopen",
                             {}, headers)

    # --- Mediation ---
    def create_mediation_case(self, complaint_id, headers):
        return self._request(
            "POST", f"/complaints/{complaint_id}/mediation-cases", {}, headers)

    def list_mediation_cases(self, complaint_id, headers, params=None):
        return self._request(
            "GET", f"/complaints/{complaint_id}/mediation-cases",
            headers=headers, params=params)

    def mediation_party_response(self, mediation_case_id, payload, headers):
        return self._request(
            "POST", f"/mediation-cases/{mediation_case_id}/party-response",
            payload, headers)

    def schedule_mediation(self, mediation_case_id, payload, headers):
        return self._request(
            "POST", f"/mediation-cases/{mediation_case_id}/schedule",
            payload, headers)

    def conclude_mediation(self, mediation_case_id, payload, headers):
        return self._request(
            "POST", f"/mediation-cases/{mediation_case_id}/conclude",
            payload, headers)

    # --- Arbitration ---
    def create_arbitration_case(self, complaint_id, headers):
        return self._request(
            "POST", f"/complaints/{complaint_id}/arbitration-cases",
            {}, headers)

    def list_arbitration_cases(self, complaint_id, headers, params=None):
        return self._request(
            "GET", f"/complaints/{complaint_id}/arbitration-cases",
            headers=headers, params=params)

    def schedule_hearing(self, arbitration_case_id, payload, headers):
        return self._request(
            "POST",
            f"/arbitration-cases/{arbitration_case_id}/schedule-hearing",
            payload, headers)

    def render_arbitration_decision(self, arbitration_case_id, payload,
                                    headers):
        return self._request(
            "POST",
            f"/arbitration-cases/{arbitration_case_id}/render-decision",
            payload, headers)

    # --- Rating ---
    def create_rating_snapshot(self, business_id, payload, headers):
        return self._request(
            "POST", f"/businesses/{business_id}/rating-snapshots",
            payload, headers)

    def list_rating_snapshots(self, business_id, headers, params=None):
        return self._request(
            "GET", f"/businesses/{business_id}/rating-snapshots",
            headers=headers, params=params)

    def create_rating_dispute(self, business_id, payload, headers):
        return self._request(
            "POST", f"/businesses/{business_id}/rating-disputes",
            payload, headers)

    def decide_appeal(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/rating-disputes/{dispute_id}/appeal-decision",
            payload, headers)

    def list_rating_disputes(self, business_id, headers, params=None):
        return self._request(
            "GET", f"/businesses/{business_id}/rating-disputes",
            headers=headers, params=params)

    # --- Advertising reviews ---
    def create_advertising_review(self, business_id, payload, headers):
        return self._request(
            "POST", f"/businesses/{business_id}/advertising-reviews",
            payload, headers)

    def conclude_advertising_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/advertising-reviews/{review_id}/conclude",
            payload, headers)

    def list_advertising_reviews(self, business_id, headers, params=None):
        return self._request(
            "GET", f"/businesses/{business_id}/advertising-reviews",
            headers=headers, params=params)

    # --- Scam reports & patterns ---
    def create_scam_report(self, payload, headers):
        return self._request("POST", "/scam-reports", payload, headers)

    def list_scam_reports(self, business_id, headers, params=None):
        return self._request(
            "GET", f"/businesses/{business_id}/scam-reports",
            headers=headers, params=params)

    def publish_scam_report(self, report_id, headers):
        return self._request("POST", f"/scam-reports/{report_id}/publish",
                             {}, headers)

    def list_scam_patterns(self, headers, params=None):
        return self._request("GET", "/scam-patterns", headers=headers,
                             params=params)

    # --- Test-driving: logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             payload, headers)


api_client = ApiClient()
