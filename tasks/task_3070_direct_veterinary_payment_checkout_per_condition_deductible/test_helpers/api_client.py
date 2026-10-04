"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/vetpay/_clock/set_current_utc", payload, headers)

    # --- TerritoryRateFiling ---
    def create_rate_filing(self, payload, headers):
        return self._request("POST", "/vetpay/rate-filings", payload, headers)

    def list_rate_filings(self, headers, params=None):
        return self._request("GET", "/vetpay/rate-filings", headers=headers, params=params)

    def get_rate_filing(self, filing_id, headers):
        return self._request("GET", f"/vetpay/rate-filings/{filing_id}", headers=headers)

    def file_rate_filing(self, filing_id, headers):
        return self._request("POST", f"/vetpay/rate-filings/{filing_id}/file", {}, headers)

    # --- Hospital ---
    def create_hospital(self, payload, headers):
        return self._request("POST", "/vetpay/hospitals", payload, headers)

    def list_hospitals(self, headers, params=None):
        return self._request("GET", "/vetpay/hospitals", headers=headers, params=params)

    def get_hospital(self, hospital_id, headers):
        return self._request("GET", f"/vetpay/hospitals/{hospital_id}", headers=headers)

    def approve_hospital(self, hospital_id, payload, headers):
        return self._request("POST", f"/vetpay/hospitals/{hospital_id}/approve", payload, headers)

    def training_complete(self, hospital_id, headers):
        return self._request("POST", f"/vetpay/hospitals/{hospital_id}/training-complete", {}, headers)

    def suspend_hospital(self, hospital_id, headers):
        return self._request("POST", f"/vetpay/hospitals/{hospital_id}/suspend", {}, headers)

    def reinstate_hospital(self, hospital_id, headers):
        return self._request("POST", f"/vetpay/hospitals/{hospital_id}/reinstate", {}, headers)

    def list_hospital_payments(self, hospital_id, headers, params=None):
        return self._request("GET", f"/vetpay/hospitals/{hospital_id}/payments", headers=headers, params=params)

    def create_reconciliation_report(self, hospital_id, payload, headers):
        return self._request("POST", f"/vetpay/hospitals/{hospital_id}/reconciliation-reports", payload, headers)

    def list_hospital_reconciliation_reports(self, hospital_id, headers, params=None):
        return self._request("GET", f"/vetpay/hospitals/{hospital_id}/reconciliation-reports", headers=headers, params=params)

    def get_reconciliation_report(self, report_id, headers):
        return self._request("GET", f"/vetpay/reconciliation-reports/{report_id}", headers=headers)

    def acknowledge_reconciliation_report(self, report_id, headers):
        return self._request("POST", f"/vetpay/reconciliation-reports/{report_id}/acknowledge", {}, headers)

    def dispute_reconciliation_report(self, report_id, headers):
        return self._request("POST", f"/vetpay/reconciliation-reports/{report_id}/dispute", {}, headers)

    def list_reconciliation_reports(self, headers, params=None):
        return self._request("GET", "/vetpay/reconciliation-reports", headers=headers, params=params)

    # --- Policy ---
    def create_policy(self, payload, headers):
        return self._request("POST", "/vetpay/policies", payload, headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/vetpay/policies", headers=headers, params=params)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/vetpay/policies/{policy_id}", headers=headers)

    def cancel_policy(self, policy_id, headers):
        return self._request("POST", f"/vetpay/policies/{policy_id}/cancel", {}, headers)

    def mark_lapsed(self, policy_id, headers):
        return self._request("POST", f"/vetpay/policies/{policy_id}/mark-lapsed", {}, headers)

    def recalculate_premium(self, policy_id, headers):
        return self._request("POST", f"/vetpay/policies/{policy_id}/recalculate-premium", {}, headers)

    def list_policy_conditions_of_policy(self, policy_id, headers, params=None):
        return self._request("GET", f"/vetpay/policies/{policy_id}/conditions", headers=headers, params=params)

    def get_policy_condition(self, condition_id, headers):
        return self._request("GET", f"/vetpay/policy-conditions/{condition_id}", headers=headers)

    def list_policy_conditions(self, headers, params=None):
        return self._request("GET", "/vetpay/policy-conditions", headers=headers, params=params)

    def get_claim_line(self, line_id, headers):
        return self._request("GET", f"/vetpay/claim-lines/{line_id}", headers=headers)

    def list_claim_lines(self, headers, params=None):
        return self._request("GET", "/vetpay/claim-lines", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/vetpay/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/vetpay/payments", headers=headers, params=params)

    # --- Medical records ---
    def create_medical_record(self, policy_id, payload, headers):
        return self._request("POST", f"/vetpay/policies/{policy_id}/medical-records", payload, headers)

    def list_policy_medical_records(self, policy_id, headers, params=None):
        return self._request("GET", f"/vetpay/policies/{policy_id}/medical-records", headers=headers, params=params)

    def get_medical_record(self, record_id, headers):
        return self._request("GET", f"/vetpay/medical-records/{record_id}", headers=headers)

    def list_medical_records(self, headers, params=None):
        return self._request("GET", "/vetpay/medical-records", headers=headers, params=params)

    def list_hospital_medical_records(self, hospital_id, headers, params=None):
        return self._request("GET", f"/vetpay/hospitals/{hospital_id}/medical-records", headers=headers, params=params)

    def list_appeal_medical_records(self, appeal_id, headers, params=None):
        return self._request("GET", f"/vetpay/appeals/{appeal_id}/medical-records", headers=headers, params=params)

    # --- Claim ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/vetpay/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/vetpay/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/vetpay/claims/{claim_id}", headers=headers)

    def list_claim_lines_of_claim(self, claim_id, headers, params=None):
        return self._request("GET", f"/vetpay/claims/{claim_id}/lines", headers=headers, params=params)

    def flag_preexisting_review(self, claim_id, headers):
        return self._request("POST", f"/vetpay/claims/{claim_id}/flag-preexisting-review", {}, headers)

    def clear_preexisting_review(self, claim_id, headers):
        return self._request("POST", f"/vetpay/claims/{claim_id}/clear-preexisting-review", {}, headers)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/vetpay/claims/{claim_id}/adjudicate", payload, headers)

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/vetpay/claims/{claim_id}/deny", payload, headers)

    def checkout_pay(self, claim_id, payload, headers):
        return self._request("POST", f"/vetpay/claims/{claim_id}/checkout-pay", payload, headers)

    def list_claim_payments(self, claim_id, headers, params=None):
        return self._request("GET", f"/vetpay/claims/{claim_id}/payments", headers=headers, params=params)

    # --- ClaimAppeal ---
    def open_appeal(self, claim_id, payload, headers):
        return self._request("POST", f"/vetpay/claims/{claim_id}/appeals", payload, headers)

    def list_claim_appeals(self, claim_id, headers, params=None):
        return self._request("GET", f"/vetpay/claims/{claim_id}/appeals", headers=headers, params=params)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/vetpay/appeals", headers=headers, params=params)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/vetpay/appeals/{appeal_id}", headers=headers)

    def request_records(self, appeal_id, headers):
        return self._request("POST", f"/vetpay/appeals/{appeal_id}/request-records", {}, headers)

    def submit_records(self, appeal_id, payload, headers):
        return self._request("POST", f"/vetpay/appeals/{appeal_id}/submit-records", payload, headers)

    def resolve_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/vetpay/appeals/{appeal_id}/resolve", payload, headers)


api_client = ApiClient()
