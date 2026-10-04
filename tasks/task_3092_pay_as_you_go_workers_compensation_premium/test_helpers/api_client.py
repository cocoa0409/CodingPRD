"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Logical clock ────────────────────────────────
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    # ─── Employer ─────────────────────────────────────
    def create_employer(self, payload, headers):
        return self._request("POST", "/wc/employers", payload, headers)

    def list_employers(self, headers, params=None):
        return self._request("GET", "/wc/employers", headers=headers, params=params)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/wc/employers/{employer_id}", headers=headers)

    def list_employer_policies(self, employer_id, headers, params=None):
        return self._request("GET", f"/wc/employers/{employer_id}/policies",
                             headers=headers, params=params)

    # ─── StateRatingTable ─────────────────────────────
    def create_state_rating_table(self, payload, headers):
        return self._request("POST", "/wc/state-rating-tables", payload, headers)

    def list_state_rating_tables(self, headers, params=None):
        return self._request("GET", "/wc/state-rating-tables",
                             headers=headers, params=params)

    def get_state_rating_table(self, table_id, headers):
        return self._request("GET", f"/wc/state-rating-tables/{table_id}",
                             headers=headers)

    # ─── Policy ───────────────────────────────────────
    def create_policy(self, payload, headers):
        return self._request("POST", "/wc/policies", payload, headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/wc/policies", headers=headers, params=params)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/wc/policies/{policy_id}", headers=headers)

    def bind_policy(self, policy_id, headers, payload=None):
        return self._request("POST", f"/wc/policies/{policy_id}/bind",
                             payload or {}, headers)

    def cancel_policy(self, policy_id, headers, payload=None):
        return self._request("POST", f"/wc/policies/{policy_id}/cancel",
                             payload or {}, headers)

    def list_policy_class_codes(self, policy_id, headers, params=None):
        return self._request("GET", f"/wc/policies/{policy_id}/class-codes",
                             headers=headers, params=params)

    def list_policy_reports(self, policy_id, headers, params=None):
        return self._request("GET", f"/wc/policies/{policy_id}/reports",
                             headers=headers, params=params)

    def list_policy_invoices(self, policy_id, headers, params=None):
        return self._request("GET", f"/wc/policies/{policy_id}/invoices",
                             headers=headers, params=params)

    def list_policy_disputes(self, policy_id, headers, params=None):
        return self._request("GET", f"/wc/policies/{policy_id}/disputes",
                             headers=headers, params=params)

    def list_policy_audits(self, policy_id, headers, params=None):
        return self._request("GET", f"/wc/policies/{policy_id}/audits",
                             headers=headers, params=params)

    def list_policy_tax_filings(self, policy_id, headers, params=None):
        return self._request("GET", f"/wc/policies/{policy_id}/tax-filings",
                             headers=headers, params=params)

    def get_policy_integration(self, policy_id, headers):
        return self._request("GET", f"/wc/policies/{policy_id}/integration",
                             headers=headers)

    # ─── PayrollReport ────────────────────────────────
    def submit_payroll_report(self, payload, headers):
        return self._request("POST", "/wc/payroll-reports", payload, headers)

    def get_payroll_report(self, report_id, headers):
        return self._request("GET", f"/wc/payroll-reports/{report_id}", headers=headers)

    def list_report_lines(self, report_id, headers, params=None):
        return self._request("GET", f"/wc/payroll-reports/{report_id}/lines",
                             headers=headers, params=params)

    def list_report_invoices(self, report_id, headers, params=None):
        return self._request("GET", f"/wc/payroll-reports/{report_id}/invoices",
                             headers=headers, params=params)

    # ─── PremiumInvoice ───────────────────────────────
    def list_invoices(self, headers, params=None):
        return self._request("GET", "/wc/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/wc/invoices/{invoice_id}", headers=headers)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/wc/invoices/{invoice_id}/payments",
                             payload, headers)

    def void_invoice(self, invoice_id, headers, payload=None):
        return self._request("POST", f"/wc/invoices/{invoice_id}/void",
                             payload or {}, headers)

    # ─── ClassCodeDispute ─────────────────────────────
    def file_dispute(self, payload, headers):
        return self._request("POST", "/wc/disputes", payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/wc/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/wc/disputes/{dispute_id}", headers=headers)

    def open_dispute_review(self, dispute_id, headers, payload=None):
        return self._request("POST", f"/wc/disputes/{dispute_id}/open-review",
                             payload or {}, headers)

    def return_dispute_to_filed(self, dispute_id, headers, payload=None):
        return self._request("POST", f"/wc/disputes/{dispute_id}/return-to-filed",
                             payload or {}, headers)

    def decide_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/wc/disputes/{dispute_id}/decide",
                             payload, headers)

    # ─── TaxFilingRecord ──────────────────────────────
    def create_tax_filing(self, payload, headers):
        return self._request("POST", "/wc/tax-filings", payload, headers)

    # ─── AuditReconciliation ──────────────────────────
    def open_audit(self, payload, headers):
        return self._request("POST", "/wc/audits", payload, headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/wc/audits", headers=headers, params=params)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/wc/audits/{audit_id}", headers=headers)

    def file_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/wc/audits/{audit_id}/file", payload, headers)

    def verify_audit(self, audit_id, headers, payload=None):
        return self._request("POST", f"/wc/audits/{audit_id}/verify",
                             payload or {}, headers)

    def waive_audit(self, audit_id, headers, payload=None):
        return self._request("POST", f"/wc/audits/{audit_id}/waive",
                             payload or {}, headers)

    # ─── PayrollIntegration ───────────────────────────
    def heartbeat_integration(self, integration_id, payload, headers):
        return self._request("POST", f"/wc/integrations/{integration_id}/heartbeat",
                             payload, headers)


api_client = ApiClient()
