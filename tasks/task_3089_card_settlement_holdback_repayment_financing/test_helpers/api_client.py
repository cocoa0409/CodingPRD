"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock control ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Merchants ---
    def create_merchant(self, payload, headers):
        return self._request("POST", "/lending/merchants", payload, headers)

    def get_merchant(self, merchant_id, headers):
        return self._request("GET", f"/lending/merchants/{merchant_id}", headers=headers)

    def list_merchants(self, headers, params=None):
        return self._request("GET", "/lending/merchants", headers=headers, params=params)

    def activate_merchant(self, merchant_id, headers):
        return self._request("POST", f"/lending/merchants/{merchant_id}/activate", headers=headers)

    def reinstate_merchant(self, merchant_id, headers):
        return self._request("POST", f"/lending/merchants/{merchant_id}/reinstate", headers=headers)

    # --- Processing batches ---
    def create_batch(self, merchant_id, payload, headers):
        return self._request("POST", f"/lending/merchants/{merchant_id}/processing_batches", payload, headers)

    def finalize_batch(self, batch_id, headers):
        return self._request("POST", f"/lending/processing_batches/{batch_id}/finalize", headers=headers)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/lending/processing_batches/{batch_id}", headers=headers)

    def list_batches(self, merchant_id, headers, params=None):
        return self._request("GET", f"/lending/merchants/{merchant_id}/processing_batches", headers=headers, params=params)

    # --- Offers ---
    def create_offer(self, merchant_id, headers):
        return self._request("POST", f"/lending/merchants/{merchant_id}/offers", headers=headers)

    def issue_offer(self, offer_id, headers):
        return self._request("POST", f"/lending/offers/{offer_id}/issue", headers=headers)

    def withdraw_offer(self, offer_id, headers):
        return self._request("POST", f"/lending/offers/{offer_id}/withdraw", headers=headers)

    def renew_offer(self, offer_id, headers):
        return self._request("POST", f"/lending/offers/{offer_id}/renew", headers=headers)

    def accept_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/lending/offers/{offer_id}/accept", payload, headers)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/lending/offers/{offer_id}", headers=headers)

    def list_offers(self, merchant_id, headers, params=None):
        return self._request("GET", f"/lending/merchants/{merchant_id}/offers", headers=headers, params=params)

    # --- Loans ---
    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/lending/loans/{loan_id}", headers=headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/lending/loans", headers=headers, params=params)

    def list_merchant_loans(self, merchant_id, headers, params=None):
        return self._request("GET", f"/lending/merchants/{merchant_id}/loans", headers=headers, params=params)

    def activate_loan(self, loan_id, headers):
        return self._request("POST", f"/lending/loans/{loan_id}/activate", headers=headers)

    def charge_off_loan(self, loan_id, headers):
        return self._request("POST", f"/lending/loans/{loan_id}/charge_off", headers=headers)

    def evaluate_period(self, loan_id, headers):
        return self._request("POST", f"/lending/loans/{loan_id}/evaluate_period", headers=headers)

    # --- Guarantors ---
    def get_guarantor(self, guarantor_id, headers):
        return self._request("GET", f"/lending/guarantors/{guarantor_id}", headers=headers)

    def list_guarantors(self, loan_id, headers, params=None):
        return self._request("GET", f"/lending/loans/{loan_id}/guarantors", headers=headers, params=params)

    def acknowledge_guarantor(self, guarantor_id, headers):
        return self._request("POST", f"/lending/guarantors/{guarantor_id}/acknowledge", headers=headers)

    # --- Disclosures ---
    def get_disclosure(self, disclosure_id, headers):
        return self._request("GET", f"/lending/disclosures/{disclosure_id}", headers=headers)

    def list_disclosures(self, loan_id, headers, params=None):
        return self._request("GET", f"/lending/loans/{loan_id}/disclosures", headers=headers, params=params)

    def deliver_disclosure(self, disclosure_id, headers):
        return self._request("POST", f"/lending/disclosures/{disclosure_id}/deliver", headers=headers)

    def acknowledge_disclosure(self, disclosure_id, headers):
        return self._request("POST", f"/lending/disclosures/{disclosure_id}/acknowledge", headers=headers)

    # --- Sweeps ---
    def create_sweep(self, loan_id, payload, headers):
        return self._request("POST", f"/lending/loans/{loan_id}/sweeps", payload, headers)

    def get_sweep(self, sweep_id, headers):
        return self._request("GET", f"/lending/sweeps/{sweep_id}", headers=headers)

    def list_loan_sweeps(self, loan_id, headers, params=None):
        return self._request("GET", f"/lending/loans/{loan_id}/sweeps", headers=headers, params=params)

    def list_sweeps(self, headers, params=None):
        return self._request("GET", "/lending/sweeps", headers=headers, params=params)

    def reverse_sweep(self, sweep_id, headers):
        return self._request("POST", f"/lending/sweeps/{sweep_id}/reverse", headers=headers)

    # --- Catch-up payments ---
    def create_catch_up(self, loan_id, payload, headers):
        return self._request("POST", f"/lending/loans/{loan_id}/catch_up_payments", payload, headers)

    def settle_catch_up(self, payment_id, headers):
        return self._request("POST", f"/lending/catch_up_payments/{payment_id}/settle", headers=headers)

    def fail_catch_up(self, payment_id, headers):
        return self._request("POST", f"/lending/catch_up_payments/{payment_id}/fail", headers=headers)

    def reverse_catch_up(self, payment_id, headers):
        return self._request("POST", f"/lending/catch_up_payments/{payment_id}/reverse", headers=headers)

    def get_catch_up(self, payment_id, headers):
        return self._request("GET", f"/lending/catch_up_payments/{payment_id}", headers=headers)

    def list_catch_ups(self, loan_id, headers, params=None):
        return self._request("GET", f"/lending/loans/{loan_id}/catch_up_payments", headers=headers, params=params)

    # --- Enforcement actions ---
    def demand_enforcement(self, action_id, headers):
        return self._request("POST", f"/lending/enforcement_actions/{action_id}/demand", headers=headers)

    def escalate_enforcement(self, action_id, headers):
        return self._request("POST", f"/lending/enforcement_actions/{action_id}/escalate", headers=headers)

    def draw_enforcement(self, action_id, headers):
        return self._request("POST", f"/lending/enforcement_actions/{action_id}/draw", headers=headers)

    def release_enforcement(self, action_id, headers):
        return self._request("POST", f"/lending/enforcement_actions/{action_id}/release", headers=headers)

    def get_enforcement_action(self, action_id, headers):
        return self._request("GET", f"/lending/enforcement_actions/{action_id}", headers=headers)

    def list_loan_enforcement_actions(self, loan_id, headers, params=None):
        return self._request("GET", f"/lending/loans/{loan_id}/enforcement_actions", headers=headers, params=params)

    def list_enforcement_actions(self, headers, params=None):
        return self._request("GET", "/lending/enforcement_actions", headers=headers, params=params)

    # --- Migration signals ---
    def evaluate_migration(self, merchant_id, headers):
        return self._request("POST", f"/lending/merchants/{merchant_id}/migration_signals/evaluate", headers=headers)

    def confirm_migration_signal(self, signal_id, headers):
        return self._request("POST", f"/lending/migration_signals/{signal_id}/confirm", headers=headers)

    def dismiss_migration_signal(self, signal_id, headers):
        return self._request("POST", f"/lending/migration_signals/{signal_id}/dismiss", headers=headers)

    def clear_migration_signal(self, signal_id, headers):
        return self._request("POST", f"/lending/migration_signals/{signal_id}/clear", headers=headers)

    def get_migration_signal(self, signal_id, headers):
        return self._request("GET", f"/lending/migration_signals/{signal_id}", headers=headers)

    def list_migration_signals(self, merchant_id, headers, params=None):
        return self._request("GET", f"/lending/merchants/{merchant_id}/migration_signals", headers=headers, params=params)

    # --- Funding partner banks ---
    def create_bank(self, payload, headers):
        return self._request("POST", "/lending/funding_banks", payload, headers)

    def suspend_bank(self, bank_id, headers):
        return self._request("POST", f"/lending/funding_banks/{bank_id}/suspend", headers=headers)

    def get_bank(self, bank_id, headers):
        return self._request("GET", f"/lending/funding_banks/{bank_id}", headers=headers)

    # --- Loan sales ---
    def quote_sale(self, loan_id, payload, headers):
        return self._request("POST", f"/lending/loans/{loan_id}/sales/quote", payload, headers)

    def commit_sale(self, sale_id, headers):
        return self._request("POST", f"/lending/sales/{sale_id}/commit", headers=headers)

    def settle_sale(self, sale_id, headers):
        return self._request("POST", f"/lending/sales/{sale_id}/settle", headers=headers)

    def fail_sale(self, sale_id, headers):
        return self._request("POST", f"/lending/sales/{sale_id}/fail", headers=headers)

    def requote_sale(self, sale_id, headers):
        return self._request("POST", f"/lending/sales/{sale_id}/requote", headers=headers)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/lending/sales/{sale_id}", headers=headers)

    def list_loan_sales(self, loan_id, headers, params=None):
        return self._request("GET", f"/lending/loans/{loan_id}/sales", headers=headers, params=params)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/lending/sales", headers=headers, params=params)


api_client = ApiClient()
