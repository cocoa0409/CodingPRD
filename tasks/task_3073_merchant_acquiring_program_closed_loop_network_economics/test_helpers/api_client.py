"""API client: one method per endpoint exposed by the network API.

Every method returns the raw ``requests.Response`` so tests can assert on
status codes and error bodies directly.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Clock ────────────────────────────────────────
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/network/_clock/set_current_utc", payload, headers)

    # ─── Industry categories ──────────────────────────
    def create_industry_category(self, payload, headers):
        return self._request("POST", "/network/industry-categories", payload, headers)

    def get_industry_category(self, industry_category_id, headers):
        return self._request(
            "GET", f"/network/industry-categories/{industry_category_id}", headers=headers)

    def list_industry_categories(self, headers, params=None):
        return self._request("GET", "/network/industry-categories", headers=headers, params=params)

    # ─── Sweep index ──────────────────────────────────
    def stamp_sweep_index(self, payload, headers):
        return self._request("POST", "/network/_sweep-index/stamp", payload, headers)

    def list_sweep_index_stamps(self, headers, params=None):
        return self._request("GET", "/network/sweep-index-stamps", headers=headers, params=params)

    # ─── Merchants ────────────────────────────────────
    def create_merchant(self, payload, headers):
        return self._request("POST", "/network/merchants", payload, headers)

    def get_merchant(self, merchant_id, headers):
        return self._request("GET", f"/network/merchants/{merchant_id}", headers=headers)

    def list_merchants(self, headers, params=None):
        return self._request("GET", "/network/merchants", headers=headers, params=params)

    def accept_merchant(self, merchant_id, payload, headers):
        return self._request(
            "POST", f"/network/merchants/{merchant_id}/accept", payload, headers)

    def activate_merchant(self, merchant_id, headers):
        return self._request("POST", f"/network/merchants/{merchant_id}/activate", headers=headers)

    def mark_merchant_dormant(self, merchant_id, headers):
        return self._request(
            "POST", f"/network/merchants/{merchant_id}/mark-dormant", headers=headers)

    def suppress_merchant(self, merchant_id, headers):
        return self._request("POST", f"/network/merchants/{merchant_id}/suppress", headers=headers)

    def archive_merchant(self, merchant_id, headers):
        return self._request("DELETE", f"/network/merchants/{merchant_id}", headers=headers)

    def create_declined_attempt(self, merchant_id, payload, headers):
        return self._request(
            "POST", f"/network/merchants/{merchant_id}/declined-attempts", payload, headers)

    def list_merchant_declined_attempts(self, merchant_id, headers, params=None):
        return self._request(
            "GET", f"/network/merchants/{merchant_id}/declined-attempts",
            headers=headers, params=params)

    def list_merchant_acceptance_gaps(self, merchant_id, headers, params=None):
        return self._request(
            "GET", f"/network/merchants/{merchant_id}/acceptance-gaps",
            headers=headers, params=params)

    def get_merchant_risk_state(self, merchant_id, headers):
        return self._request(
            "GET", f"/network/merchants/{merchant_id}/risk-state", headers=headers)

    # ─── Acceptance gaps ──────────────────────────────
    def rollup_acceptance_gaps(self, payload, headers):
        return self._request("POST", "/network/acceptance-gaps/rollup", payload, headers)

    def list_acceptance_gaps(self, headers, params=None):
        return self._request("GET", "/network/acceptance-gaps", headers=headers, params=params)

    def get_acceptance_gap(self, gap_id, headers):
        return self._request("GET", f"/network/acceptance-gaps/{gap_id}", headers=headers)

    # ─── Offers ───────────────────────────────────────
    def create_offer(self, payload, headers):
        return self._request("POST", "/network/offers", payload, headers)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/network/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/network/offers", headers=headers, params=params)

    def submit_offer_review(self, offer_id, headers):
        return self._request("POST", f"/network/offers/{offer_id}/submit-review", headers=headers)

    def request_offer_consent(self, offer_id, headers):
        return self._request("POST", f"/network/offers/{offer_id}/request-consent", headers=headers)

    def consent_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/network/offers/{offer_id}/consent", payload, headers)

    def return_offer_to_draft(self, offer_id, headers):
        return self._request("POST", f"/network/offers/{offer_id}/return-to-draft", headers=headers)

    def suspend_offer(self, offer_id, headers):
        return self._request("POST", f"/network/offers/{offer_id}/suspend", headers=headers)

    def accept_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/network/offers/{offer_id}/accept", payload, headers)

    def list_offer_acceptances(self, offer_id, headers, params=None):
        return self._request(
            "GET", f"/network/offers/{offer_id}/acceptances", headers=headers, params=params)

    def create_redemption_pool(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/network/offers/{offer_id}/redemption-pool", payload, headers)

    def topup_redemption_pool(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/network/offers/{offer_id}/redemption-pool/topup", payload, headers)

    def get_offer_redemption_pool(self, offer_id, headers):
        return self._request(
            "GET", f"/network/offers/{offer_id}/redemption-pool", headers=headers)

    # ─── Offer acceptances ────────────────────────────
    def get_offer_acceptance(self, acceptance_id, headers):
        return self._request(
            "GET", f"/network/offer-acceptances/{acceptance_id}", headers=headers)

    def list_offer_acceptances_global(self, headers, params=None):
        return self._request("GET", "/network/offer-acceptances", headers=headers, params=params)

    def approve_offer_acceptance(self, acceptance_id, headers):
        return self._request(
            "POST", f"/network/offer-acceptances/{acceptance_id}/approve", headers=headers)

    def pay_offer_acceptance(self, acceptance_id, headers):
        return self._request(
            "POST", f"/network/offer-acceptances/{acceptance_id}/pay", headers=headers)

    def reverse_offer_acceptance(self, acceptance_id, headers):
        return self._request(
            "POST", f"/network/offer-acceptances/{acceptance_id}/reverse", headers=headers)

    # ─── Redemption pools (collection reads) ──────────
    def get_redemption_pool(self, pool_id, headers):
        return self._request("GET", f"/network/redemption-pools/{pool_id}", headers=headers)

    def list_redemption_pools(self, headers, params=None):
        return self._request("GET", "/network/redemption-pools", headers=headers, params=params)

    # ─── Card members ─────────────────────────────────
    def create_cardmember(self, payload, headers):
        return self._request("POST", "/network/cardmembers", payload, headers)

    def get_cardmember(self, cardmember_id, headers):
        return self._request("GET", f"/network/cardmembers/{cardmember_id}", headers=headers)

    def list_cardmembers(self, headers, params=None):
        return self._request("GET", "/network/cardmembers", headers=headers, params=params)

    def activate_cardmember(self, cardmember_id, headers):
        return self._request(
            "POST", f"/network/cardmembers/{cardmember_id}/activate", headers=headers)

    def set_cardmember_monthly_spend(self, cardmember_id, payload, headers):
        return self._request(
            "POST", f"/network/cardmembers/{cardmember_id}/set-monthly-spend", payload, headers)

    def grant_lounge_access(self, cardmember_id, payload, headers):
        return self._request(
            "POST", f"/network/cardmembers/{cardmember_id}/grant-lounge-access", payload, headers)

    def mark_cardmember_delinquent(self, cardmember_id, headers):
        return self._request(
            "POST", f"/network/cardmembers/{cardmember_id}/mark-delinquent", headers=headers)

    def close_cardmember(self, cardmember_id, headers):
        return self._request("POST", f"/network/cardmembers/{cardmember_id}/close", headers=headers)

    # ─── Annual fee statements / value fund ───────────
    def create_annual_fee_statement(self, payload, headers):
        return self._request("POST", "/network/annual-fee-statements", payload, headers)

    def get_annual_fee_statement(self, statement_id, headers):
        return self._request(
            "GET", f"/network/annual-fee-statements/{statement_id}", headers=headers)

    def list_annual_fee_statements(self, headers, params=None):
        return self._request(
            "GET", "/network/annual-fee-statements", headers=headers, params=params)

    def assess_annual_fee_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/network/annual-fee-statements/{statement_id}/assess", headers=headers)

    def disburse_annual_fee_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/network/annual-fee-statements/{statement_id}/disburse", headers=headers)

    def void_annual_fee_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/network/annual-fee-statements/{statement_id}/void", headers=headers)

    def list_value_fund_ledger(self, headers, params=None):
        return self._request("GET", "/network/value-fund/ledger", headers=headers, params=params)

    def list_value_fund_ledger_entries(self, headers, params=None):
        return self._request(
            "GET", "/network/value-fund-ledger-entries", headers=headers, params=params)

    def get_value_fund_ledger_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/network/value-fund-ledger-entries/{entry_id}", headers=headers)

    # ─── Settlements / funding ────────────────────────
    def create_settlement(self, merchant_id, payload, headers):
        return self._request(
            "POST", f"/network/merchants/{merchant_id}/settlements", payload, headers)

    def list_merchant_settlements(self, merchant_id, headers, params=None):
        return self._request(
            "GET", f"/network/merchants/{merchant_id}/settlements", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/network/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/network/settlements", headers=headers, params=params)

    def finalize_funding_batch(self, merchant_id, batch_seq, headers):
        return self._request(
            "POST", f"/network/merchants/{merchant_id}/funding/batches/{batch_seq}/finalize",
            headers=headers)

    def posting_reversal(self, settlement_id, headers):
        return self._request(
            "POST", f"/network/settlements/{settlement_id}/posting-reversal", headers=headers)

    def reinstate_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"/network/settlements/{settlement_id}/reinstate", headers=headers)

    # ─── Disputes ─────────────────────────────────────
    def create_dispute(self, payload, headers):
        return self._request("POST", "/network/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/network/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/network/disputes", headers=headers, params=params)

    def respond_to_dispute(self, dispute_id, headers):
        return self._request("POST", f"/network/disputes/{dispute_id}/respond", headers=headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/network/disputes/{dispute_id}/resolve", payload, headers)

    def withdraw_dispute(self, dispute_id, headers):
        return self._request("POST", f"/network/disputes/{dispute_id}/withdraw", headers=headers)

    # ─── Acceptance complaints ────────────────────────
    def create_complaint(self, payload, headers):
        return self._request("POST", "/network/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/network/complaints/{complaint_id}", headers=headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/network/complaints", headers=headers, params=params)

    def take_up_complaint(self, complaint_id, headers):
        return self._request("POST", f"/network/complaints/{complaint_id}/take-up", headers=headers)

    def uphold_complaint(self, complaint_id, headers):
        return self._request("POST", f"/network/complaints/{complaint_id}/uphold", headers=headers)

    def dismiss_complaint(self, complaint_id, headers):
        return self._request("POST", f"/network/complaints/{complaint_id}/dismiss", headers=headers)

    def reopen_complaint(self, complaint_id, headers):
        return self._request("POST", f"/network/complaints/{complaint_id}/reopen", headers=headers)

    # ─── Reverse-reachability collection reads ────────
    def list_declined_attempts(self, headers, params=None):
        return self._request("GET", "/network/declined-attempts", headers=headers, params=params)

    def get_declined_attempt(self, declined_attempt_id, headers):
        return self._request(
            "GET", f"/network/declined-attempts/{declined_attempt_id}", headers=headers)

    def list_merchant_risk_states(self, headers, params=None):
        return self._request(
            "GET", "/network/merchant-risk-states", headers=headers, params=params)

    def get_merchant_risk_state_by_id(self, risk_state_id, headers):
        return self._request(
            "GET", f"/network/merchant-risk-states/{risk_state_id}", headers=headers)


api_client = ApiClient()