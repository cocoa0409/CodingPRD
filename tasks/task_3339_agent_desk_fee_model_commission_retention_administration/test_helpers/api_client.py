"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    # --- Office ---
    def create_office(self, payload, headers):
        return self._request("POST", "/offices", payload, headers)

    def get_office(self, office_id, headers):
        return self._request("GET", f"/offices/{office_id}", headers=headers)

    def list_offices(self, headers, params=None):
        return self._request("GET", "/offices", headers=headers, params=params)

    def close_office(self, office_id, headers):
        return self._request("POST", f"/offices/{office_id}/close", headers=headers)

    # --- FeeSchedule ---
    def create_fee_schedule(self, payload, headers):
        return self._request("POST", "/fee-schedules", payload, headers)

    def get_fee_schedule(self, schedule_id, headers):
        return self._request("GET", f"/fee-schedules/{schedule_id}", headers=headers)

    def list_fee_schedules(self, headers, params=None):
        return self._request("GET", "/fee-schedules", headers=headers, params=params)

    # --- Agent ---
    def create_agent(self, office_id, payload, headers):
        return self._request("POST", f"/offices/{office_id}/agents", payload, headers)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"/agents/{agent_id}", headers=headers)

    def list_agents(self, headers, params=None):
        return self._request("GET", "/agents", headers=headers, params=params)

    def terminate_agent(self, agent_id, headers):
        return self._request("POST", f"/agents/{agent_id}/terminate", headers=headers)

    def complete_termination(self, agent_id, headers):
        return self._request("POST", f"/agents/{agent_id}/complete-termination", headers=headers)

    def advance_commission(self, agent_id, payload, headers):
        return self._request("POST", f"/agents/{agent_id}/advance-commission", payload, headers)

    def return_advance(self, agent_id, payload, headers):
        return self._request("POST", f"/agents/{agent_id}/return-advance", payload, headers)

    # --- FeeAssignment ---
    def create_fee_assignment(self, agent_id, payload, headers):
        return self._request("POST", f"/agents/{agent_id}/fee-assignments", payload, headers)

    def get_fee_assignment(self, assignment_id, headers):
        return self._request("GET", f"/fee-assignments/{assignment_id}", headers=headers)

    def list_agent_fee_assignments(self, agent_id, headers, params=None):
        return self._request("GET", f"/agents/{agent_id}/fee-assignments",
                             headers=headers, params=params)

    def list_fee_assignments(self, headers, params=None):
        return self._request("GET", "/fee-assignments", headers=headers, params=params)

    def accept_fee_assignment(self, assignment_id, headers):
        return self._request("POST", f"/fee-assignments/{assignment_id}/accept", headers=headers)

    def reject_fee_assignment(self, assignment_id, headers):
        return self._request("POST", f"/fee-assignments/{assignment_id}/reject", headers=headers)

    def cancel_fee_assignment(self, assignment_id, headers):
        return self._request("POST", f"/fee-assignments/{assignment_id}/cancel", headers=headers)

    # --- Offer ---
    def create_offer(self, office_id, payload, headers):
        return self._request("POST", f"/offices/{office_id}/offers", payload, headers)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/offers", headers=headers, params=params)

    def counter_offer(self, offer_id, headers):
        return self._request("POST", f"/offers/{offer_id}/counter", headers=headers)

    def reoffer(self, offer_id, headers):
        return self._request("POST", f"/offers/{offer_id}/reoffer", headers=headers)

    def accept_offer(self, offer_id, headers, payload=None):
        return self._request("POST", f"/offers/{offer_id}/accept", payload, headers)

    def reject_offer(self, offer_id, headers):
        return self._request("POST", f"/offers/{offer_id}/reject", headers=headers)

    def withdraw_offer(self, offer_id, headers):
        return self._request("POST", f"/offers/{offer_id}/withdraw", headers=headers)

    # --- Transaction ---
    def create_transaction(self, office_id, payload, headers):
        return self._request("POST", f"/offices/{office_id}/transactions", payload, headers)

    def get_transaction(self, transaction_id, headers):
        return self._request("GET", f"/transactions/{transaction_id}", headers=headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", "/transactions", headers=headers, params=params)

    def request_close(self, transaction_id, headers):
        return self._request("POST", f"/transactions/{transaction_id}/request-close", headers=headers)

    def close_transaction(self, transaction_id, headers):
        return self._request("POST", f"/transactions/{transaction_id}/close", headers=headers)

    def mark_fell_through(self, transaction_id, headers):
        return self._request("POST", f"/transactions/{transaction_id}/mark-fell-through", headers=headers)

    def relist_transaction(self, transaction_id, headers):
        return self._request("POST", f"/transactions/{transaction_id}/relist", headers=headers)

    def recontract_transaction(self, transaction_id, headers):
        return self._request("POST", f"/transactions/{transaction_id}/recontract", headers=headers)

    # --- CDA ---
    def create_cda(self, transaction_id, payload, headers):
        return self._request("POST", f"/transactions/{transaction_id}/cdas", payload, headers)

    def get_cda(self, cda_id, headers):
        return self._request("GET", f"/cdas/{cda_id}", headers=headers)

    def list_transaction_cdas(self, transaction_id, headers, params=None):
        return self._request("GET", f"/transactions/{transaction_id}/cdas",
                             headers=headers, params=params)

    def list_cdas(self, headers, params=None):
        return self._request("GET", "/cdas", headers=headers, params=params)

    def review_cda(self, cda_id, payload, headers):
        return self._request("POST", f"/cdas/{cda_id}/review", payload, headers)

    # --- ClosingStatementLine ---
    def get_closing_statement_line(self, line_id, headers):
        return self._request("GET", f"/closing-statement-lines/{line_id}", headers=headers)

    def list_closing_statement_lines(self, headers, params=None):
        return self._request("GET", "/closing-statement-lines", headers=headers, params=params)

    def list_transaction_closing_lines(self, transaction_id, headers, params=None):
        return self._request("GET", f"/transactions/{transaction_id}/closing-statement-lines",
                             headers=headers, params=params)

    # --- Invoice ---
    def generate_invoices(self, office_id, payload, headers):
        return self._request("POST", f"/offices/{office_id}/generate-invoices", payload, headers)

    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", headers=headers)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", payload, headers)

    def cancel_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/cancel", headers=headers)

    def write_off_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/write-off", headers=headers)

    # --- InvoiceLine ---
    def get_invoice_line(self, line_id, headers):
        return self._request("GET", f"/invoice-lines/{line_id}", headers=headers)

    def list_invoice_lines(self, headers, params=None):
        return self._request("GET", "/invoice-lines", headers=headers, params=params)

    def list_invoice_lines_for_invoice(self, invoice_id, headers, params=None):
        return self._request("GET", f"/invoices/{invoice_id}/lines",
                             headers=headers, params=params)

    # --- CommissionEntry ---
    def get_commission_entry(self, entry_id, headers):
        return self._request("GET", f"/commission-entries/{entry_id}", headers=headers)

    def list_commission_entries(self, headers, params=None):
        return self._request("GET", "/commission-entries", headers=headers, params=params)

    def reconcile_office(self, office_id, headers):
        return self._request("POST", f"/offices/{office_id}/reconcile", headers=headers)

    # --- ReferralAgreement ---
    def create_referral_agreement(self, payload, headers):
        return self._request("POST", "/referral-agreements", payload, headers)

    def get_referral_agreement(self, agreement_id, headers):
        return self._request("GET", f"/referral-agreements/{agreement_id}", headers=headers)

    def list_referral_agreements(self, headers, params=None):
        return self._request("GET", "/referral-agreements", headers=headers, params=params)

    def accept_referral_agreement(self, agreement_id, headers):
        return self._request("POST", f"/referral-agreements/{agreement_id}/accept", headers=headers)

    def decline_referral_agreement(self, agreement_id, headers):
        return self._request("POST", f"/referral-agreements/{agreement_id}/decline", headers=headers)

    def withdraw_referral_agreement(self, agreement_id, headers):
        return self._request("POST", f"/referral-agreements/{agreement_id}/withdraw", headers=headers)

    # --- AgentRetentionReport ---
    def compute_retention_report(self, office_id, payload, headers):
        return self._request("POST", f"/offices/{office_id}/retention-reports/compute",
                             payload, headers)

    def get_retention_report(self, report_id, headers):
        return self._request("GET", f"/retention-reports/{report_id}", headers=headers)

    def list_retention_reports(self, headers, params=None):
        return self._request("GET", "/retention-reports", headers=headers, params=params)

    def list_office_retention_reports(self, office_id, headers, params=None):
        return self._request("GET", f"/offices/{office_id}/retention-reports",
                             headers=headers, params=params)


api_client = ApiClient()
