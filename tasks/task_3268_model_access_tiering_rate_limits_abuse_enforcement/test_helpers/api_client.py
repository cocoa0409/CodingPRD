"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock & system ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- organizations ---
    def create_organization(self, payload, headers):
        return self._request("POST", "/organizations", payload, headers)

    def list_organizations(self, headers, params=None):
        return self._request("GET", "/organizations", headers=headers, params=params)

    def get_organization(self, organization_id, headers, params=None):
        return self._request("GET", f"/organizations/{organization_id}", headers=headers, params=params)

    def activate_organization(self, organization_id, headers):
        return self._request("POST", f"/organizations/{organization_id}/activate", {}, headers)

    def list_organization_payment_events(self, organization_id, headers, params=None):
        return self._request("GET", f"/organizations/{organization_id}/payment-events", headers=headers, params=params)

    def list_organization_usage_records(self, organization_id, headers, params=None):
        return self._request("GET", f"/organizations/{organization_id}/usage-records", headers=headers, params=params)

    def list_organization_invoices(self, organization_id, headers, params=None):
        return self._request("GET", f"/organizations/{organization_id}/invoices", headers=headers, params=params)

    def list_organization_rate_limit_windows(self, organization_id, headers, params=None):
        return self._request("GET", f"/organizations/{organization_id}/rate-limit-windows", headers=headers, params=params)

    def list_organization_queued_requests(self, organization_id, headers, params=None):
        return self._request("GET", f"/organizations/{organization_id}/queued-requests", headers=headers, params=params)

    def list_organization_abuse_cases(self, organization_id, headers, params=None):
        return self._request("GET", f"/organizations/{organization_id}/abuse-cases", headers=headers, params=params)

    # --- payments ---
    def create_payment_event(self, payload, headers):
        return self._request("POST", "/payment-events", payload, headers)

    def settle_payment_event(self, payment_event_id, headers):
        return self._request("POST", f"/payment-events/{payment_event_id}/settle", {}, headers)

    # --- models ---
    def create_model_version(self, payload, headers):
        return self._request("POST", "/model-versions", payload, headers)

    def list_model_versions(self, headers, params=None):
        return self._request("GET", "/model-versions", headers=headers, params=params)

    def get_model_version(self, model_version_id, headers):
        return self._request("GET", f"/model-versions/{model_version_id}", headers=headers)

    def deprecate_model_version(self, model_version_id, headers):
        return self._request("POST", f"/model-versions/{model_version_id}/deprecate", {}, headers)

    def list_model_version_safety_evaluations(self, model_version_id, headers, params=None):
        return self._request("GET", f"/model-versions/{model_version_id}/safety-evaluations", headers=headers, params=params)

    def list_model_version_usage_records(self, model_version_id, headers, params=None):
        return self._request("GET", f"/model-versions/{model_version_id}/usage-records", headers=headers, params=params)

    # --- safety ---
    def create_safety_evaluation(self, model_version_id, payload, headers):
        return self._request("POST", f"/model-versions/{model_version_id}/safety-evaluations", payload, headers)

    def submit_safety_verdict(self, evaluation_id, payload, headers):
        return self._request("POST", f"/safety-evaluations/{evaluation_id}/submit-verdict", payload, headers)

    # --- usage / rate limits ---
    def create_usage_record(self, payload, headers):
        return self._request("POST", "/usage-records", payload, headers)

    def create_queued_request(self, payload, headers):
        return self._request("POST", "/queued-requests", payload, headers)

    # --- billing ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def list_invoice_lines(self, headers, params=None):
        return self._request("GET", "/invoice-lines", headers=headers, params=params)

    def get_invoice_line(self, invoice_line_id, headers):
        return self._request("GET", f"/invoice-lines/{invoice_line_id}", headers=headers)

    def finalize_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/finalize", {}, headers)

    # --- enterprise agreements ---
    def create_enterprise_agreement(self, payload, headers):
        return self._request("POST", "/enterprise-agreements", payload, headers)

    def list_enterprise_agreements(self, headers, params=None):
        return self._request("GET", "/enterprise-agreements", headers=headers, params=params)

    def get_enterprise_agreement(self, agreement_id, headers):
        return self._request("GET", f"/enterprise-agreements/{agreement_id}", headers=headers)

    def countersign_enterprise_agreement(self, agreement_id, headers):
        return self._request("POST", f"/enterprise-agreements/{agreement_id}/countersign", {}, headers)

    # --- abuse enforcement ---
    def create_abuse_case(self, payload, headers):
        return self._request("POST", "/abuse-cases", payload, headers)

    def get_abuse_case(self, abuse_case_id, headers):
        return self._request("GET", f"/abuse-cases/{abuse_case_id}", headers=headers)

    def claim_abuse_case(self, abuse_case_id, headers):
        return self._request("POST", f"/abuse-cases/{abuse_case_id}/claim", {}, headers)

    def create_abuse_action(self, abuse_case_id, payload, headers):
        return self._request("POST", f"/abuse-cases/{abuse_case_id}/actions", payload, headers)

    def list_abuse_case_actions(self, abuse_case_id, headers, params=None):
        return self._request("GET", f"/abuse-cases/{abuse_case_id}/actions", headers=headers, params=params)

    def list_abuse_case_appeals(self, abuse_case_id, headers, params=None):
        return self._request("GET", f"/abuse-cases/{abuse_case_id}/appeals", headers=headers, params=params)

    # --- appeals ---
    def create_appeal(self, payload, headers):
        return self._request("POST", "/appeals", payload, headers)

    def grant_appeal(self, appeal_id, headers):
        return self._request("POST", f"/appeals/{appeal_id}/grant", {}, headers)


api_client = ApiClient()
