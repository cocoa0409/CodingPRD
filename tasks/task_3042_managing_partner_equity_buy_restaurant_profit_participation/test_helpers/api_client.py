"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # --- partners ---
    def create_partner(self, payload, headers):
        return self._request("POST", "/api/partners", payload, headers)

    def list_partners(self, headers, params=None):
        return self._request("GET", "/api/partners", headers=headers, params=params)

    def get_partner(self, partner_id, headers):
        return self._request("GET", f"/api/partners/{partner_id}", headers=headers)

    def start_training(self, partner_id, headers):
        return self._request(
            "POST", f"/api/partners/{partner_id}/start-training", {}, headers
        )

    def certify_partner(self, partner_id, headers):
        return self._request("POST", f"/api/partners/{partner_id}/certify", {}, headers)

    def withdraw_partner(self, partner_id, headers):
        return self._request("POST", f"/api/partners/{partner_id}/withdraw", {}, headers)

    # --- market groups ---
    def create_market_group(self, payload, headers):
        return self._request("POST", "/api/market-groups", payload, headers)

    def list_market_groups(self, headers, params=None):
        return self._request("GET", "/api/market-groups", headers=headers, params=params)

    def get_market_group(self, group_id, headers):
        return self._request("GET", f"/api/market-groups/{group_id}", headers=headers)

    def activate_market_group(self, group_id, headers):
        return self._request(
            "POST", f"/api/market-groups/{group_id}/activate", {}, headers
        )

    # --- restaurants ---
    def create_restaurant(self, payload, headers):
        return self._request("POST", "/api/restaurants", payload, headers)

    def list_restaurants(self, headers, params=None):
        return self._request("GET", "/api/restaurants", headers=headers, params=params)

    def get_restaurant(self, restaurant_id, headers):
        return self._request(
            "GET", f"/api/restaurants/{restaurant_id}", headers=headers
        )

    def activate_restaurant(self, restaurant_id, headers):
        return self._request(
            "POST", f"/api/restaurants/{restaurant_id}/activate", {}, headers
        )

    def close_restaurant(self, restaurant_id, headers):
        return self._request(
            "POST", f"/api/restaurants/{restaurant_id}/close", {}, headers
        )

    # --- managing partner contracts ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/api/managing-partner-contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request(
            "GET", "/api/managing-partner-contracts", headers=headers, params=params
        )

    def get_contract(self, contract_id, headers):
        return self._request(
            "GET", f"/api/managing-partner-contracts/{contract_id}", headers=headers
        )

    def submit_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/api/managing-partner-contracts/{contract_id}/submit", {}, headers
        )

    def post_buy_in_payment(self, contract_id, payload, headers):
        return self._request(
            "POST",
            f"/api/managing-partner-contracts/{contract_id}/buy-in-payments",
            payload,
            headers,
        )

    def list_buy_in_payments(self, contract_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/managing-partner-contracts/{contract_id}/buy-in-payments",
            headers=headers,
            params=params,
        )

    def activate_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/api/managing-partner-contracts/{contract_id}/activate", {}, headers
        )

    def offer_renewal(self, contract_id, headers):
        return self._request(
            "POST",
            f"/api/managing-partner-contracts/{contract_id}/offer-renewal",
            {},
            headers,
        )

    def accept_renewal(self, contract_id, headers):
        return self._request(
            "POST",
            f"/api/managing-partner-contracts/{contract_id}/accept-renewal",
            {},
            headers,
        )

    def depart_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/api/managing-partner-contracts/{contract_id}/depart", {}, headers
        )

    def transfer_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/api/managing-partner-contracts/{contract_id}/transfer", payload, headers
        )

    def create_buyout_order(self, contract_id, payload, headers):
        return self._request(
            "POST",
            f"/api/managing-partner-contracts/{contract_id}/buyout-orders",
            payload,
            headers,
        )

    # --- buyout orders ---
    def list_buyout_orders(self, headers, params=None):
        return self._request("GET", "/api/buyout-orders", headers=headers, params=params)

    def get_buyout_order(self, order_id, headers):
        return self._request("GET", f"/api/buyout-orders/{order_id}", headers=headers)

    def approve_buyout_order(self, order_id, headers):
        return self._request(
            "POST", f"/api/buyout-orders/{order_id}/approve", {}, headers
        )

    def pay_buyout_order(self, order_id, headers):
        return self._request("POST", f"/api/buyout-orders/{order_id}/pay", {}, headers)

    # --- market partner agreements ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/api/market-partner-agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request(
            "GET", "/api/market-partner-agreements", headers=headers, params=params
        )

    def get_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/api/market-partner-agreements/{agreement_id}", headers=headers
        )

    def activate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/api/market-partner-agreements/{agreement_id}/activate", {}, headers
        )

    def terminate_agreement(self, agreement_id, headers):
        return self._request(
            "POST",
            f"/api/market-partner-agreements/{agreement_id}/terminate",
            {},
            headers,
        )

    # --- profit periods / line items ---
    def create_profit_period(self, payload, headers):
        return self._request("POST", "/api/profit-periods", payload, headers)

    def list_profit_periods(self, headers, params=None):
        return self._request("GET", "/api/profit-periods", headers=headers, params=params)

    def get_profit_period(self, period_id, headers):
        return self._request("GET", f"/api/profit-periods/{period_id}", headers=headers)

    def post_line_item(self, period_id, payload, headers):
        return self._request(
            "POST", f"/api/profit-periods/{period_id}/line-items", payload, headers
        )

    def list_line_items(self, period_id, headers, params=None):
        return self._request(
            "GET", f"/api/profit-periods/{period_id}/line-items", headers=headers, params=params
        )

    def finalize_line_item(self, line_item_id, payload, headers):
        return self._request(
            "POST", f"/api/line-items/{line_item_id}/finalize", payload, headers
        )

    def compute_period(self, period_id, payload, headers):
        return self._request(
            "POST", f"/api/profit-periods/{period_id}/compute", payload, headers
        )

    def finalize_period(self, period_id, headers):
        return self._request(
            "POST", f"/api/profit-periods/{period_id}/finalize", {}, headers
        )

    def lock_period(self, period_id, headers):
        return self._request("POST", f"/api/profit-periods/{period_id}/lock", {}, headers)

    # --- yield standards ---
    def create_yield_standard(self, payload, headers):
        return self._request("POST", "/api/yield-standards", payload, headers)

    def list_yield_standards(self, headers, params=None):
        return self._request("GET", "/api/yield-standards", headers=headers, params=params)

    def get_yield_standard(self, standard_id, headers):
        return self._request("GET", f"/api/yield-standards/{standard_id}", headers=headers)

    def deactivate_yield_standard(self, standard_id, headers):
        return self._request(
            "POST", f"/api/yield-standards/{standard_id}/deactivate", {}, headers
        )

    # --- meat cut batches ---
    def create_meat_cut_batch(self, payload, headers):
        return self._request("POST", "/api/meat-cut-batches", payload, headers)

    def list_meat_cut_batches(self, headers, params=None):
        return self._request("GET", "/api/meat-cut-batches", headers=headers, params=params)

    def get_meat_cut_batch(self, batch_id, headers):
        return self._request("GET", f"/api/meat-cut-batches/{batch_id}", headers=headers)

    def audit_meat_cut_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/api/meat-cut-batches/{batch_id}/audit", payload, headers
        )

    def waive_meat_cut_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/api/meat-cut-batches/{batch_id}/waive", {}, headers
        )

    # --- award programs / grants ---
    def create_award_program(self, payload, headers):
        return self._request("POST", "/api/award-programs", payload, headers)

    def list_award_programs(self, headers, params=None):
        return self._request("GET", "/api/award-programs", headers=headers, params=params)

    def get_award_program(self, program_id, headers):
        return self._request("GET", f"/api/award-programs/{program_id}", headers=headers)

    def close_award_program(self, program_id, headers):
        return self._request(
            "POST", f"/api/award-programs/{program_id}/close", {}, headers
        )

    def create_award_grant(self, program_id, payload, headers):
        return self._request(
            "POST", f"/api/award-programs/{program_id}/grants", payload, headers
        )

    def list_award_grants(self, headers, params=None):
        return self._request("GET", "/api/award-grants", headers=headers, params=params)

    def get_award_grant(self, grant_id, headers):
        return self._request("GET", f"/api/award-grants/{grant_id}", headers=headers)

    def vest_award_grant(self, grant_id, headers):
        return self._request("POST", f"/api/award-grants/{grant_id}/vest", {}, headers)

    # --- dispute cases ---
    def create_dispute_case(self, payload, headers):
        return self._request("POST", "/api/dispute-cases", payload, headers)

    def list_dispute_cases(self, headers, params=None):
        return self._request("GET", "/api/dispute-cases", headers=headers, params=params)

    def get_dispute_case(self, dispute_id, headers):
        return self._request("GET", f"/api/dispute-cases/{dispute_id}", headers=headers)

    def request_evidence(self, dispute_id, headers):
        return self._request(
            "POST", f"/api/dispute-cases/{dispute_id}/request-evidence", {}, headers
        )

    def submit_evidence(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/api/dispute-cases/{dispute_id}/submit-evidence", payload, headers
        )

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/api/dispute-cases/{dispute_id}/resolve", payload, headers
        )

    def withdraw_dispute(self, dispute_id, headers):
        return self._request(
            "POST", f"/api/dispute-cases/{dispute_id}/withdraw", {}, headers
        )


api_client = ApiClient()
