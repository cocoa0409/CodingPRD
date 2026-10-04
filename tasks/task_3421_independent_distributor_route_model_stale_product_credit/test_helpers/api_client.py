"""API client: one method per endpoint defined in the PRD (§4 routing table).

All endpoints are mounted at the service root. State-changing POSTs with no
declared input send an empty JSON object body.
"""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) -------------------------------------------
    def set_clock(self, payload: dict, headers: dict):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Bakeries and production days (PRD §3.1, §3.3) -----------------------
    def create_bakery(self, payload: dict, headers: dict):
        return self._request("POST", "/bakeries", payload, headers)

    def get_bakery(self, bakery_id: str, headers: dict):
        return self._request("GET", f"/bakeries/{bakery_id}", headers=headers)

    def create_production_day(self, bakery_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/bakeries/{bakery_id}/production-days", payload, headers
        )

    def list_production_days(self, bakery_id: str, headers: dict,
                             params: Optional[dict] = None):
        return self._request(
            "GET", f"/bakeries/{bakery_id}/production-days",
            headers=headers, params=params,
        )

    def close_production_day(self, production_day_id: str, headers: dict):
        return self._request(
            "POST", f"/production-days/{production_day_id}/close", {}, headers
        )

    # --- Territories (PRD §3.1) ----------------------------------------------
    def create_territory(self, payload: dict, headers: dict):
        return self._request("POST", "/territories", payload, headers)

    def get_territory(self, territory_id: str, headers: dict):
        return self._request("GET", f"/territories/{territory_id}", headers=headers)

    def list_territory_for_sale(self, territory_id: str, headers: dict):
        return self._request(
            "POST", f"/territories/{territory_id}/list-for-sale", {}, headers
        )

    # --- Distributors and settlement (PRD §3.1, §3.4) --------------------------
    def create_distributor(self, payload: dict, headers: dict):
        return self._request("POST", "/distributors", payload, headers)

    def get_distributor(self, distributor_id: str, headers: dict):
        return self._request(
            "GET", f"/distributors/{distributor_id}", headers=headers
        )

    def get_settlement(self, distributor_id: str, headers: dict,
                       params: Optional[dict] = None):
        return self._request(
            "GET", f"/distributors/{distributor_id}/settlement",
            headers=headers, params=params,
        )

    # --- Route agreements (PRD §3.1, §3.7, §3.8) --------------------------------
    def create_agreement(self, payload: dict, headers: dict):
        return self._request("POST", "/agreements", payload, headers)

    def list_agreements(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id: str, headers: dict):
        return self._request("GET", f"/agreements/{agreement_id}", headers=headers)

    def activate_agreement(self, agreement_id: str, headers: dict):
        return self._request(
            "POST", f"/agreements/{agreement_id}/activate", {}, headers
        )

    def suspend_agreement(self, agreement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/agreements/{agreement_id}/suspend", payload, headers
        )

    def reinstate_agreement(self, agreement_id: str, payload: Optional[dict],
                            headers: dict):
        return self._request(
            "POST", f"/agreements/{agreement_id}/reinstate", payload or {}, headers
        )

    def exit_agreement(self, agreement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/agreements/{agreement_id}/exit", payload, headers
        )

    # --- Financing plans (PRD §3.2) ---------------------------------------------
    def create_financing_plan(self, agreement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/agreements/{agreement_id}/financing-plans", payload, headers
        )

    def list_financing_plans(self, agreement_id: str, headers: dict,
                             params: Optional[dict] = None):
        return self._request(
            "GET", f"/agreements/{agreement_id}/financing-plans",
            headers=headers, params=params,
        )

    def disburse_financing_plan(self, plan_id: str, headers: dict):
        return self._request(
            "POST", f"/financing-plans/{plan_id}/disburse", {}, headers
        )

    def record_financing_payment(self, plan_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/financing-plans/{plan_id}/payments", payload, headers
        )

    # --- Retail accounts and audits (PRD §3.5) -------------------------------------
    def create_retail_account(self, distributor_id: str, payload: dict,
                              headers: dict):
        return self._request(
            "POST", f"/distributors/{distributor_id}/retail-accounts",
            payload, headers,
        )

    def list_retail_accounts(self, distributor_id: str, headers: dict,
                             params: Optional[dict] = None):
        return self._request(
            "GET", f"/distributors/{distributor_id}/retail-accounts",
            headers=headers, params=params,
        )

    def post_audit(self, account_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/retail-accounts/{account_id}/audits", payload, headers
        )

    # --- Daily orders (PRD §3.3, §3.4) ------------------------------------------------
    def create_order(self, distributor_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/distributors/{distributor_id}/orders", payload, headers
        )

    def list_orders(self, distributor_id: str, headers: dict,
                    params: Optional[dict] = None):
        return self._request(
            "GET", f"/distributors/{distributor_id}/orders",
            headers=headers, params=params,
        )

    def submit_order(self, order_id: str, headers: dict):
        return self._request("POST", f"/orders/{order_id}/submit", {}, headers)

    def confirm_order(self, order_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/orders/{order_id}/confirm", payload, headers)

    def cancel_order(self, order_id: str, headers: dict):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    def record_delivery(self, order_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/orders/{order_id}/record-delivery", payload, headers
        )

    def reconcile_order(self, order_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/orders/{order_id}/reconcile", payload, headers
        )

    # --- Stale return claims (PRD §3.6) --------------------------------------------------
    def create_stale_claim(self, distributor_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/distributors/{distributor_id}/stale-claims", payload, headers
        )

    def list_stale_claims(self, distributor_id: str, headers: dict,
                          params: Optional[dict] = None):
        return self._request(
            "GET", f"/distributors/{distributor_id}/stale-claims",
            headers=headers, params=params,
        )

    def decide_claim(self, claim_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/stale-claims/{claim_id}/decide", payload, headers
        )

    def resubmit_claim(self, claim_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/stale-claims/{claim_id}/resubmit", payload, headers
        )

    def issue_credit(self, claim_id: str, headers: dict):
        return self._request(
            "POST", f"/stale-claims/{claim_id}/issue-credit", {}, headers
        )

    # --- Territory transfers (PRD §3.8) ------------------------------------------------------
    def list_transfers(self, agreement_id: str, headers: dict,
                       params: Optional[dict] = None):
        return self._request(
            "GET", f"/agreements/{agreement_id}/transfers",
            headers=headers, params=params,
        )

    def settle_transfer(self, transfer_id: str, headers: dict):
        return self._request(
            "POST", f"/transfers/{transfer_id}/settle", {}, headers
        )


api_client = ApiClient()
