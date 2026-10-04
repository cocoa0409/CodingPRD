"""API client: one method per endpoint defined in the PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/fleet/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- accounts ---
    def create_account(self, payload, headers):
        return self._request("POST", "/fleet/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/fleet/accounts/{account_id}", headers=headers)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/fleet/accounts/{account_id}/suspend", {}, headers)

    def reinstate_account(self, account_id, headers):
        return self._request("POST", f"/fleet/accounts/{account_id}/reinstate", {}, headers)

    def record_payment(self, account_id, amount_cents, headers):
        return self._request("POST", f"/fleet/accounts/{account_id}/payments",
                             {"amount_cents": amount_cents}, headers)

    # --- rate cards & catalog ---
    def create_rate_card(self, payload, headers):
        return self._request("POST", "/fleet/rate-cards", payload, headers)

    def create_tool_model(self, payload, headers):
        return self._request("POST", "/fleet/tool-models", payload, headers)

    # --- agreements ---
    def create_agreement(self, account_id, payload, headers):
        return self._request("POST", f"/fleet/accounts/{account_id}/agreements",
                             payload, headers)

    def list_agreements(self, account_id, headers):
        return self._request("GET", f"/fleet/accounts/{account_id}/agreements",
                             headers=headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/fleet/agreements/{agreement_id}", headers=headers)

    def activate_agreement(self, account_id, agreement_id, headers):
        return self._request("POST",
                             f"/fleet/accounts/{account_id}/agreements/{agreement_id}/activate",
                             {}, headers)

    def adjust_fleet(self, account_id, agreement_id, payload, headers):
        return self._request("POST",
                             f"/fleet/accounts/{account_id}/agreements/{agreement_id}/adjust-fleet",
                             payload, headers)

    def elect_end_of_term(self, account_id, agreement_id, payload, headers):
        return self._request("POST",
                             f"/fleet/accounts/{account_id}/agreements/{agreement_id}/elect-end-of-term",
                             payload, headers)

    def finalize_settlement(self, account_id, agreement_id, assessed_damage_cents, headers):
        return self._request("POST",
                             f"/fleet/accounts/{account_id}/agreements/{agreement_id}/finalize-settlement",
                             {"assessed_damage_cents": assessed_damage_cents}, headers)

    def get_utilization(self, agreement_id, headers, mode=None):
        params = {"mode": mode} if mode is not None else None
        return self._request("GET", f"/fleet/agreements/{agreement_id}/utilization",
                             headers=headers, params=params)

    def get_settlement(self, agreement_id, headers):
        return self._request("GET", f"/fleet/agreements/{agreement_id}/settlement",
                             headers=headers)

    # --- jobsites ---
    def create_jobsite(self, account_id, payload, headers):
        return self._request("POST", f"/fleet/accounts/{account_id}/jobsites",
                             payload, headers)

    def list_jobsites(self, account_id, headers):
        return self._request("GET", f"/fleet/accounts/{account_id}/jobsites",
                             headers=headers)

    def get_jobsite(self, jobsite_id, headers):
        return self._request("GET", f"/fleet/jobsites/{jobsite_id}", headers=headers)

    # --- assets ---
    def list_assets(self, headers, params=None):
        return self._request("GET", "/fleet/assets", headers=headers, params=params)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/fleet/assets/{asset_id}", headers=headers)

    def deploy_asset(self, asset_id, jobsite_id, headers):
        return self._request("POST", f"/fleet/assets/{asset_id}/deploy",
                             {"jobsite_id": jobsite_id}, headers)

    def transfer_asset(self, asset_id, target_jobsite_id, headers):
        return self._request("POST", f"/fleet/assets/{asset_id}/transfer",
                             {"target_jobsite_id": target_jobsite_id}, headers)

    def confirm_arrival(self, asset_id, headers):
        return self._request("POST", f"/fleet/assets/{asset_id}/confirm-arrival",
                             {}, headers)

    def cancel_transfer(self, asset_id, headers):
        return self._request("POST", f"/fleet/assets/{asset_id}/cancel-transfer",
                             {}, headers)

    def check_in_asset(self, asset_id, headers):
        return self._request("POST", f"/fleet/assets/{asset_id}/check-in", {}, headers)

    def record_usage_event(self, asset_id, payload, headers):
        return self._request("POST", f"/fleet/assets/{asset_id}/usage-events",
                             payload, headers)

    def list_usage_events(self, asset_id, headers):
        return self._request("GET", f"/fleet/assets/{asset_id}/usage-events",
                             headers=headers)

    # --- repair tickets ---
    def create_repair_ticket(self, asset_id, loaner_requested, headers):
        return self._request("POST", f"/fleet/assets/{asset_id}/repair-tickets",
                             {"loaner_requested": loaner_requested}, headers)

    def list_repair_tickets_for_asset(self, asset_id, headers):
        return self._request("GET", f"/fleet/assets/{asset_id}/repair-tickets",
                             headers=headers)

    def get_repair_ticket(self, ticket_id, headers):
        return self._request("GET", f"/fleet/repair-tickets/{ticket_id}",
                             headers=headers)

    def schedule_pickup(self, ticket_id, headers):
        return self._request("POST", f"/fleet/repair-tickets/{ticket_id}/schedule-pickup",
                             {}, headers)

    def receive_ticket(self, ticket_id, headers):
        return self._request("POST", f"/fleet/repair-tickets/{ticket_id}/receive",
                             {}, headers)

    def dispatch_loaner(self, ticket_id, headers):
        return self._request("POST", f"/fleet/repair-tickets/{ticket_id}/dispatch-loaner",
                             {}, headers)

    def complete_repair(self, ticket_id, headers):
        return self._request("POST", f"/fleet/repair-tickets/{ticket_id}/complete-repair",
                             {}, headers)

    def close_ticket(self, ticket_id, headers):
        return self._request("POST", f"/fleet/repair-tickets/{ticket_id}/close",
                             {}, headers)

    def reopen_ticket(self, ticket_id, headers):
        return self._request("POST", f"/fleet/repair-tickets/{ticket_id}/reopen",
                             {}, headers)

    # --- loaner units ---
    def create_loaner_unit(self, payload, headers):
        return self._request("POST", "/fleet/loaner-units", payload, headers)

    def list_loaner_units(self, headers, params=None):
        return self._request("GET", "/fleet/loaner-units", headers=headers, params=params)

    def get_loaner_unit(self, loaner_id, headers):
        return self._request("GET", f"/fleet/loaner-units/{loaner_id}", headers=headers)

    def decommission_loaner(self, loaner_id, headers):
        return self._request("POST", f"/fleet/loaner-units/{loaner_id}/decommission",
                             {}, headers)

    # --- theft claims ---
    def create_theft_claim(self, asset_id, headers):
        return self._request("POST", f"/fleet/assets/{asset_id}/theft-claims",
                             {}, headers)

    def list_theft_claims_for_asset(self, asset_id, headers):
        return self._request("GET", f"/fleet/assets/{asset_id}/theft-claims",
                             headers=headers)

    def verify_police_report(self, claim_id, payload, headers):
        return self._request("POST",
                             f"/fleet/theft-claims/{claim_id}/verify-police-report",
                             payload, headers)

    def decide_theft_claim(self, claim_id, decision, headers):
        return self._request("POST", f"/fleet/theft-claims/{claim_id}/decide",
                             {"decision": decision}, headers)

    # --- consumables ---
    def create_consumable_product(self, payload, headers):
        return self._request("POST", "/fleet/consumable-products", payload, headers)

    def create_consumable_order(self, account_id, lines, headers):
        return self._request("POST", f"/fleet/accounts/{account_id}/consumable-orders",
                             {"lines": lines}, headers)

    def list_consumable_orders(self, account_id, headers):
        return self._request("GET", f"/fleet/accounts/{account_id}/consumable-orders",
                             headers=headers)

    def get_consumable_order(self, order_id, headers):
        return self._request("GET", f"/fleet/consumable-orders/{order_id}",
                             headers=headers)

    def submit_consumable_order(self, account_id, order_id, headers):
        return self._request("POST",
                             f"/fleet/accounts/{account_id}/consumable-orders/{order_id}/submit",
                             {}, headers)

    def decide_consumable_order(self, account_id, order_id, decision, headers):
        return self._request("POST",
                             f"/fleet/accounts/{account_id}/consumable-orders/{order_id}/decide",
                             {"decision": decision}, headers)

    def fulfill_consumable_order(self, account_id, order_id, headers):
        return self._request("POST",
                             f"/fleet/accounts/{account_id}/consumable-orders/{order_id}/fulfill",
                             {}, headers)

    # --- support cases ---
    def create_support_case(self, account_id, payload, headers):
        return self._request("POST", f"/fleet/accounts/{account_id}/support-cases",
                             payload, headers)

    def list_support_cases(self, headers, params=None):
        return self._request("GET", "/fleet/support-cases", headers=headers, params=params)

    def get_support_case(self, case_id, headers):
        return self._request("GET", f"/fleet/support-cases/{case_id}", headers=headers)

    def review_support_case(self, account_id, case_id, payload, headers):
        return self._request("POST",
                             f"/fleet/accounts/{account_id}/support-cases/{case_id}/review",
                             payload, headers)


api_client = ApiClient()
