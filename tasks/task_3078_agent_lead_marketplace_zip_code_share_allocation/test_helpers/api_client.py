"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock --------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ---- ops runs --------------------------------------------------------
    def run_ops_sweep(self, headers):
        return self._request("POST", "/ops-runs", {}, headers)

    # ---- markets ---------------------------------------------------------
    def create_market(self, payload, headers):
        return self._request("POST", "/markets", payload, headers)

    def list_markets(self, headers, params=None):
        return self._request("GET", "/markets", headers=headers, params=params)

    def get_market(self, market_id, headers):
        return self._request("GET", f"/markets/{market_id}", headers=headers)

    def get_price_quote(self, market_id, headers, share_bps):
        return self._request(
            "GET", f"/markets/{market_id}/price-quote",
            headers=headers, params={"share_bps": share_bps},
        )

    def suspend_market(self, market_id, headers):
        return self._request("POST", f"/markets/{market_id}/suspend", {}, headers)

    def reopen_market(self, market_id, headers):
        return self._request("POST", f"/markets/{market_id}/reopen", {}, headers)

    def list_market_share_orders(self, market_id, headers, params=None):
        return self._request(
            "GET", f"/markets/{market_id}/share-orders", headers=headers, params=params
        )

    def list_market_team_accounts(self, market_id, headers, params=None):
        return self._request(
            "GET", f"/markets/{market_id}/team-accounts", headers=headers, params=params
        )

    def list_market_leads(self, market_id, headers, params=None):
        return self._request(
            "GET", f"/markets/{market_id}/leads", headers=headers, params=params
        )

    def list_market_listings(self, market_id, headers, params=None):
        return self._request(
            "GET", f"/markets/{market_id}/listings", headers=headers, params=params
        )

    # ---- brokerages ------------------------------------------------------
    def create_brokerage(self, payload, headers):
        return self._request("POST", "/brokerages", payload, headers)

    def get_brokerage(self, brokerage_id, headers):
        return self._request("GET", f"/brokerages/{brokerage_id}", headers=headers)

    def list_brokerage_agents(self, brokerage_id, headers, params=None):
        return self._request(
            "GET", f"/brokerages/{brokerage_id}/agents", headers=headers, params=params
        )

    def list_brokerage_listings(self, brokerage_id, headers, params=None):
        return self._request(
            "GET", f"/brokerages/{brokerage_id}/listings", headers=headers, params=params
        )

    def list_brokerage_disputes(self, brokerage_id, headers, params=None):
        return self._request(
            "GET", f"/brokerages/{brokerage_id}/disputes", headers=headers, params=params
        )

    # ---- agents ----------------------------------------------------------
    def create_agent(self, payload, headers):
        return self._request("POST", "/agents", payload, headers)

    def list_agents(self, headers, params=None):
        return self._request("GET", "/agents", headers=headers, params=params)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"/agents/{agent_id}", headers=headers)

    def suspend_agent(self, agent_id, headers):
        return self._request("POST", f"/agents/{agent_id}/suspend", {}, headers)

    def unsuspend_agent(self, agent_id, headers):
        return self._request("POST", f"/agents/{agent_id}/unsuspend", {}, headers)

    def deactivate_agent(self, agent_id, headers):
        return self._request("POST", f"/agents/{agent_id}/deactivate", {}, headers)

    def list_agent_team_accounts(self, agent_id, headers, params=None):
        return self._request(
            "GET", f"/agents/{agent_id}/team-accounts", headers=headers, params=params
        )

    def list_agent_team_memberships(self, agent_id, headers, params=None):
        return self._request(
            "GET", f"/agents/{agent_id}/team-memberships", headers=headers, params=params
        )

    def list_agent_share_orders(self, agent_id, headers, params=None):
        return self._request(
            "GET", f"/agents/{agent_id}/share-orders", headers=headers, params=params
        )

    def list_agent_performance_snapshots(self, agent_id, headers, params=None):
        return self._request(
            "GET", f"/agents/{agent_id}/performance-snapshots", headers=headers, params=params
        )

    def list_agent_listings(self, agent_id, headers, params=None):
        return self._request(
            "GET", f"/agents/{agent_id}/listings", headers=headers, params=params
        )

    def list_agent_credit_claims(self, agent_id, headers, params=None):
        return self._request(
            "GET", f"/agents/{agent_id}/credit-claims", headers=headers, params=params
        )

    # ---- team accounts / memberships ------------------------------------
    def create_team_account(self, payload, headers):
        return self._request("POST", "/team-accounts", payload, headers)

    def get_team_account(self, team_id, headers):
        return self._request("GET", f"/team-accounts/{team_id}", headers=headers)

    def dissolve_team_account(self, team_id, headers):
        return self._request("POST", f"/team-accounts/{team_id}/dissolve", {}, headers)

    def list_team_memberships_of_team(self, team_id, headers, params=None):
        return self._request(
            "GET", f"/team-accounts/{team_id}/memberships", headers=headers, params=params
        )

    def list_team_share_orders(self, team_id, headers, params=None):
        return self._request(
            "GET", f"/team-accounts/{team_id}/share-orders", headers=headers, params=params
        )

    def create_team_membership(self, payload, headers):
        return self._request("POST", "/team-memberships", payload, headers)

    def list_team_memberships(self, headers, params=None):
        return self._request("GET", "/team-memberships", headers=headers, params=params)

    def remove_team_membership(self, membership_id, headers):
        return self._request("POST", f"/team-memberships/{membership_id}/remove", {}, headers)

    # ---- share orders ----------------------------------------------------
    def create_share_order(self, payload, headers):
        return self._request("POST", "/share-orders", payload, headers)

    def list_share_orders(self, headers, params=None):
        return self._request("GET", "/share-orders", headers=headers, params=params)

    def get_share_order(self, order_id, headers):
        return self._request("GET", f"/share-orders/{order_id}", headers=headers)

    def capture_payment(self, order_id, payload, headers):
        return self._request("POST", f"/share-orders/{order_id}/payments", payload, headers)

    def pause_share_order(self, order_id, headers):
        return self._request("POST", f"/share-orders/{order_id}/pause", {}, headers)

    def resume_share_order(self, order_id, headers):
        return self._request("POST", f"/share-orders/{order_id}/resume", {}, headers)

    def cancel_share_order(self, order_id, headers):
        return self._request("POST", f"/share-orders/{order_id}/cancel", {}, headers)

    def list_order_payments(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/share-orders/{order_id}/payments", headers=headers, params=params
        )

    def list_order_leads(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/share-orders/{order_id}/leads", headers=headers, params=params
        )

    def list_order_live_connections(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/share-orders/{order_id}/live-connections", headers=headers, params=params
        )

    # ---- leads -----------------------------------------------------------
    def create_lead(self, payload, headers):
        return self._request("POST", "/leads", payload, headers)

    def list_leads(self, headers, params=None):
        return self._request("GET", "/leads", headers=headers, params=params)

    def get_lead(self, lead_id, headers):
        return self._request("GET", f"/leads/{lead_id}", headers=headers)

    def assign_lead(self, lead_id, payload, headers):
        return self._request("POST", f"/leads/{lead_id}/assign", payload, headers)

    def close_lead(self, lead_id, payload, headers):
        return self._request("POST", f"/leads/{lead_id}/close", payload, headers)

    def cancel_lead(self, lead_id, headers):
        return self._request("POST", f"/leads/{lead_id}/cancel", {}, headers)

    def list_lead_assignments(self, lead_id, headers, params=None):
        return self._request(
            "GET", f"/leads/{lead_id}/assignments", headers=headers, params=params
        )

    def list_lead_ratings(self, lead_id, headers, params=None):
        return self._request(
            "GET", f"/leads/{lead_id}/ratings", headers=headers, params=params
        )

    def list_lead_live_connections(self, lead_id, headers, params=None):
        return self._request(
            "GET", f"/leads/{lead_id}/live-connections", headers=headers, params=params
        )

    def list_lead_credit_claims(self, lead_id, headers, params=None):
        return self._request(
            "GET", f"/leads/{lead_id}/credit-claims", headers=headers, params=params
        )

    def list_lead_disputes(self, lead_id, headers, params=None):
        return self._request(
            "GET", f"/leads/{lead_id}/disputes", headers=headers, params=params
        )

    def list_lead_duplicates(self, lead_id, headers, params=None):
        return self._request(
            "GET", f"/leads/{lead_id}/duplicates", headers=headers, params=params
        )

    def list_lead_duplicate_connections(self, lead_id, headers, params=None):
        return self._request(
            "GET", f"/leads/{lead_id}/duplicate-connections", headers=headers, params=params
        )

    # ---- lead assignments ------------------------------------------------
    def list_assignments(self, headers, params=None):
        return self._request("GET", "/lead-assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/lead-assignments/{assignment_id}", headers=headers)

    def accept_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/lead-assignments/{assignment_id}/accept", payload, headers
        )

    # ---- live connections ------------------------------------------------
    def create_live_connection(self, payload, headers):
        return self._request("POST", "/live-connections", payload, headers)

    def list_live_connections(self, headers, params=None):
        return self._request("GET", "/live-connections", headers=headers, params=params)

    def get_live_connection(self, connection_id, headers):
        return self._request("GET", f"/live-connections/{connection_id}", headers=headers)

    def record_live_connection(self, connection_id, payload, headers):
        return self._request(
            "POST", f"/live-connections/{connection_id}/record", payload, headers
        )

    def list_connection_recordings(self, connection_id, headers, params=None):
        return self._request(
            "GET", f"/live-connections/{connection_id}/recordings", headers=headers, params=params
        )

    # ---- ratings ---------------------------------------------------------
    def create_rating(self, payload, headers):
        return self._request("POST", "/ratings", payload, headers)

    # ---- credit claims ---------------------------------------------------
    def create_credit_claim(self, payload, headers):
        return self._request("POST", "/credit-claims", payload, headers)

    def get_credit_claim(self, claim_id, headers):
        return self._request("GET", f"/credit-claims/{claim_id}", headers=headers)

    def resolve_credit_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/credit-claims/{claim_id}/resolve", payload, headers)

    # ---- listings --------------------------------------------------------
    def create_listing(self, payload, headers):
        return self._request("POST", "/listings", payload, headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/listings", headers=headers, params=params)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/listings/{listing_id}", headers=headers)

    def review_listing(self, listing_id, payload, headers):
        return self._request("POST", f"/listings/{listing_id}/review", payload, headers)

    def withdraw_listing(self, listing_id, payload, headers):
        return self._request("POST", f"/listings/{listing_id}/withdraw", payload, headers)

    def list_listing_leads(self, listing_id, headers, params=None):
        return self._request(
            "GET", f"/listings/{listing_id}/leads", headers=headers, params=params
        )

    def list_listing_disputes(self, listing_id, headers, params=None):
        return self._request(
            "GET", f"/listings/{listing_id}/disputes", headers=headers, params=params
        )

    # ---- disputes --------------------------------------------------------
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/resolve", payload, headers)

    # ---- performance snapshots -------------------------------------------
    def list_performance_snapshots(self, headers, params=None):
        return self._request(
            "GET", "/performance-snapshots", headers=headers, params=params
        )


api_client = ApiClient()
