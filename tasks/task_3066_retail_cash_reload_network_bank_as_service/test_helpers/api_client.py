"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Admin: logical clock (PRD §2.9) ---
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    # --- BankSponsor ---
    def create_bank_sponsor(self, payload, headers):
        return self._request("POST", "/v1/bank-sponsors", payload, headers)

    def get_bank_sponsor(self, bank_id, headers):
        return self._request("GET", f"/v1/bank-sponsors/{bank_id}", headers=headers)

    def list_bank_sponsors(self, headers, params=None):
        return self._request("GET", "/v1/bank-sponsors", headers=headers, params=params)

    # --- Program ---
    def create_program(self, payload, headers):
        return self._request("POST", "/v1/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/v1/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/v1/programs", headers=headers, params=params)

    def set_program_state(self, program_id, payload, headers):
        return self._request("POST", f"/v1/programs/{program_id}/state", payload, headers)

    def oversight_review(self, program_id, payload, headers):
        return self._request("POST", f"/v1/programs/{program_id}/oversight-review",
                             payload, headers)

    # --- BrandPartner ---
    def create_brand_partner(self, payload, headers):
        return self._request("POST", "/v1/brand-partners", payload, headers)

    def get_brand_partner(self, brand_id, headers):
        return self._request("GET", f"/v1/brand-partners/{brand_id}", headers=headers)

    def list_brand_partners(self, headers, params=None):
        return self._request("GET", "/v1/brand-partners", headers=headers, params=params)

    def set_brand_partner_state(self, brand_id, payload, headers):
        return self._request("POST", f"/v1/brand-partners/{brand_id}/state", payload, headers)

    # --- RetailerAgreement ---
    def create_retailer_agreement(self, payload, headers):
        return self._request("POST", "/v1/retailer-agreements", payload, headers)

    def get_retailer_agreement(self, agreement_id, headers):
        return self._request("GET", f"/v1/retailer-agreements/{agreement_id}", headers=headers)

    def list_retailer_agreements(self, headers, params=None):
        return self._request("GET", "/v1/retailer-agreements", headers=headers, params=params)

    def set_retailer_agreement_state(self, agreement_id, payload, headers):
        return self._request("POST", f"/v1/retailer-agreements/{agreement_id}/state",
                             payload, headers)

    # --- ReloadLocation ---
    def create_reload_location(self, payload, headers):
        return self._request("POST", "/v1/reload-locations", payload, headers)

    def get_reload_location(self, location_id, headers):
        return self._request("GET", f"/v1/reload-locations/{location_id}", headers=headers)

    def list_reload_locations(self, headers, params=None):
        return self._request("GET", "/v1/reload-locations", headers=headers, params=params)

    def set_reload_location_state(self, location_id, payload, headers):
        return self._request("POST", f"/v1/reload-locations/{location_id}/state",
                             payload, headers)

    # --- CardAccount ---
    def create_card_account(self, payload, headers):
        return self._request("POST", "/v1/card-accounts", payload, headers)

    def get_card_account(self, account_id, headers):
        return self._request("GET", f"/v1/card-accounts/{account_id}", headers=headers)

    def list_card_accounts(self, headers, params=None):
        return self._request("GET", "/v1/card-accounts", headers=headers, params=params)

    def set_card_account_hold(self, account_id, payload, headers):
        return self._request("POST", f"/v1/card-accounts/{account_id}/hold", payload, headers)

    # --- LoadTransaction ---
    def create_load(self, payload, headers):
        return self._request("POST", "/v1/load-transactions", payload, headers)

    def get_load(self, load_id, headers):
        return self._request("GET", f"/v1/load-transactions/{load_id}", headers=headers)

    def list_loads(self, headers, params=None):
        return self._request("GET", "/v1/load-transactions", headers=headers, params=params)

    def fund_load(self, load_id, headers):
        return self._request("POST", f"/v1/load-transactions/{load_id}/fund", {}, headers)

    def decline_load(self, load_id, payload, headers):
        return self._request("POST", f"/v1/load-transactions/{load_id}/decline", payload, headers)

    def reverse_load(self, load_id, payload, headers):
        return self._request("POST", f"/v1/load-transactions/{load_id}/reverse", payload, headers)

    def reinstate_load(self, load_id, payload, headers):
        return self._request("POST", f"/v1/load-transactions/{load_id}/reinstate", payload, headers)

    # --- AmlAlert ---
    def create_aml_alert(self, payload, headers):
        return self._request("POST", "/v1/aml-alerts", payload, headers)

    def get_aml_alert(self, alert_id, headers):
        return self._request("GET", f"/v1/aml-alerts/{alert_id}", headers=headers)

    def list_aml_alerts(self, headers, params=None):
        return self._request("GET", "/v1/aml-alerts", headers=headers, params=params)

    def review_aml_alert(self, alert_id, payload, headers):
        return self._request("POST", f"/v1/aml-alerts/{alert_id}/review", payload, headers)

    def return_aml_alert(self, alert_id, headers):
        return self._request("POST", f"/v1/aml-alerts/{alert_id}/return", {}, headers)

    def confirm_aml_alert(self, alert_id, headers):
        return self._request("POST", f"/v1/aml-alerts/{alert_id}/confirm", {}, headers)

    def reopen_aml_alert(self, alert_id, headers):
        return self._request("POST", f"/v1/aml-alerts/{alert_id}/reopen", {}, headers)

    def dismiss_aml_alert(self, alert_id, headers):
        return self._request("POST", f"/v1/aml-alerts/{alert_id}/dismiss", {}, headers)

    # --- DisputeCase ---
    def create_dispute(self, payload, headers):
        return self._request("POST", "/v1/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/v1/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/v1/disputes", headers=headers, params=params)

    def dispute_retailer_response(self, dispute_id, payload, headers):
        return self._request("POST", f"/v1/disputes/{dispute_id}/retailer-response",
                             payload, headers)

    def dispute_program_review(self, dispute_id, payload, headers):
        return self._request("POST", f"/v1/disputes/{dispute_id}/program-review",
                             payload, headers)

    def dispute_return_to_retailer(self, dispute_id, headers):
        return self._request("POST", f"/v1/disputes/{dispute_id}/return-to-retailer", {}, headers)

    def dispute_resolve(self, dispute_id, payload, headers):
        return self._request("POST", f"/v1/disputes/{dispute_id}/resolve", payload, headers)

    def dispute_escalate(self, dispute_id, payload, headers):
        return self._request("POST", f"/v1/disputes/{dispute_id}/escalate", payload, headers)

    def dispute_close(self, dispute_id, headers):
        return self._request("POST", f"/v1/disputes/{dispute_id}/close", {}, headers)

    # --- LossAllocation ---
    def create_loss_allocation(self, payload, headers):
        return self._request("POST", "/v1/loss-allocations", payload, headers)

    def get_loss_allocation(self, allocation_id, headers):
        return self._request("GET", f"/v1/loss-allocations/{allocation_id}", headers=headers)

    def list_loss_allocations(self, headers, params=None):
        return self._request("GET", "/v1/loss-allocations", headers=headers, params=params)

    def post_loss_allocation(self, allocation_id, headers):
        return self._request("POST", f"/v1/loss-allocations/{allocation_id}/post", {}, headers)

    def recover_loss_allocation(self, allocation_id, headers):
        return self._request("POST", f"/v1/loss-allocations/{allocation_id}/recover", {}, headers)

    # --- SettlementBatch ---
    def create_settlement_batch(self, payload, headers):
        return self._request("POST", "/v1/settlement-batches", payload, headers)

    def get_settlement_batch(self, batch_id, headers):
        return self._request("GET", f"/v1/settlement-batches/{batch_id}", headers=headers)

    def list_settlement_batches(self, headers, params=None):
        return self._request("GET", "/v1/settlement-batches", headers=headers, params=params)

    def open_settlement_batch(self, batch_id, headers):
        return self._request("POST", f"/v1/settlement-batches/{batch_id}/open", {}, headers)

    def settle_settlement_batch(self, batch_id, headers):
        return self._request("POST", f"/v1/settlement-batches/{batch_id}/settle", {}, headers)

    def clawback_settlement_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/v1/settlement-batches/{batch_id}/clawback",
                             payload, headers)

    # --- FloatWindow ---
    def create_float_window(self, payload, headers):
        return self._request("POST", "/v1/float-windows", payload, headers)

    def get_float_window(self, window_id, headers):
        return self._request("GET", f"/v1/float-windows/{window_id}", headers=headers)

    def list_float_windows(self, headers, params=None):
        return self._request("GET", "/v1/float-windows", headers=headers, params=params)

    def confirm_float_window(self, window_id, headers):
        return self._request("POST", f"/v1/float-windows/{window_id}/confirm", {}, headers)

    def cancel_float_window(self, window_id, headers):
        return self._request("POST", f"/v1/float-windows/{window_id}/cancel", {}, headers)

    def complete_float_window(self, window_id, headers):
        return self._request("POST", f"/v1/float-windows/{window_id}/complete", {}, headers)


api_client = ApiClient()