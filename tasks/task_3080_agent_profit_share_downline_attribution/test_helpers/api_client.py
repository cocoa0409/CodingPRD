"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock --------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- market centers -------------------------------------------------
    def create_market_center(self, payload, headers):
        return self._request("POST", "/market-centers", payload, headers)

    def get_market_center(self, center_id, headers):
        return self._request("GET", f"/market-centers/{center_id}", headers=headers)

    def suspend_market_center(self, center_id, headers, payload=None):
        return self._request(
            "POST", f"/market-centers/{center_id}/suspend", payload or {}, headers
        )

    def reactivate_market_center(self, center_id, headers, payload=None):
        return self._request(
            "POST", f"/market-centers/{center_id}/reactivate", payload or {}, headers
        )

    def list_center_agents(self, center_id, headers, params=None):
        return self._request(
            "GET", f"/market-centers/{center_id}/agents", headers=headers, params=params
        )

    # ---- agents ---------------------------------------------------------
    def create_agent(self, center_id, payload, headers):
        return self._request("POST", f"/market-centers/{center_id}/agents", payload, headers)

    def list_agents(self, headers, params=None):
        return self._request("GET", "/agents", headers=headers, params=params)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"/agents/{agent_id}", headers=headers)

    def create_onboarding_document(self, agent_id, payload, headers):
        return self._request(
            "POST", f"/agents/{agent_id}/onboarding-documents", payload, headers
        )

    def list_onboarding_documents(self, agent_id, headers, params=None):
        return self._request(
            "GET", f"/agents/{agent_id}/onboarding-documents", headers=headers, params=params
        )

    def list_downline(self, agent_id, headers, params=None):
        return self._request(
            "GET", f"/agents/{agent_id}/downline", headers=headers, params=params
        )

    def list_upline(self, agent_id, headers, params=None):
        return self._request(
            "GET", f"/agents/{agent_id}/upline", headers=headers, params=params
        )

    def get_vesting_schedule(self, agent_id, headers):
        return self._request(
            "GET", f"/agents/{agent_id}/vesting-schedule", headers=headers
        )

    def depart_agent(self, agent_id, payload, headers):
        return self._request("POST", f"/agents/{agent_id}/depart", payload, headers)

    def create_transfer_request(self, agent_id, payload, headers):
        return self._request(
            "POST", f"/agents/{agent_id}/transfer-requests", payload, headers
        )

    # ---- sponsorship edges ----------------------------------------------
    def list_sponsorship_edges(self, headers, params=None):
        return self._request("GET", "/sponsorship-edges", headers=headers, params=params)

    # ---- sponsorship disputes -------------------------------------------
    def create_dispute(self, payload, headers):
        return self._request("POST", "/sponsorship-disputes", payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/sponsorship-disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request(
            "GET", f"/sponsorship-disputes/{dispute_id}", headers=headers
        )

    def open_dispute_review(self, dispute_id, headers, payload=None):
        return self._request(
            "POST", f"/sponsorship-disputes/{dispute_id}/open-review", payload or {}, headers
        )

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/sponsorship-disputes/{dispute_id}/resolve", payload, headers
        )

    def appeal_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/sponsorship-disputes/{dispute_id}/appeal", payload, headers
        )

    # ---- commission events ----------------------------------------------
    def create_commission_event(self, payload, headers):
        return self._request("POST", "/commission-events", payload, headers)

    def list_commission_events(self, headers, params=None):
        return self._request("GET", "/commission-events", headers=headers, params=params)

    def get_commission_event(self, event_id, headers):
        return self._request("GET", f"/commission-events/{event_id}", headers=headers)

    def settle_commission_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/commission-events/{event_id}/settle", payload or {}, headers
        )

    def void_commission_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/commission-events/{event_id}/void", payload or {}, headers
        )

    # ---- profit-share periods, ledger, governance -----------------------
    def create_period(self, center_id, payload, headers):
        return self._request(
            "POST", f"/market-centers/{center_id}/profit-share-periods", payload, headers
        )

    def list_periods(self, headers, params=None):
        return self._request("GET", "/profit-share-periods", headers=headers, params=params)

    def get_period(self, period_id, headers):
        return self._request("GET", f"/profit-share-periods/{period_id}", headers=headers)

    def create_ledger_entry(self, period_id, payload, headers):
        return self._request(
            "POST", f"/profit-share-periods/{period_id}/ledger-entries", payload, headers
        )

    def list_ledger_entries(self, period_id, headers, params=None):
        return self._request(
            "GET", f"/profit-share-periods/{period_id}/ledger-entries",
            headers=headers, params=params,
        )

    def preliminary_close_period(self, period_id, headers, payload=None):
        return self._request(
            "POST", f"/profit-share-periods/{period_id}/preliminary-close",
            payload or {}, headers,
        )

    def list_period_distributions(self, period_id, headers, params=None):
        return self._request(
            "GET", f"/profit-share-periods/{period_id}/distributions",
            headers=headers, params=params,
        )

    def create_resolution(self, period_id, payload, headers):
        return self._request(
            "POST", f"/profit-share-periods/{period_id}/governance-resolutions",
            payload, headers,
        )

    def list_period_resolutions(self, period_id, headers, params=None):
        return self._request(
            "GET", f"/profit-share-periods/{period_id}/governance-resolutions",
            headers=headers, params=params,
        )

    def propose_resolution(self, resolution_id, headers, payload=None):
        return self._request(
            "POST", f"/governance-resolutions/{resolution_id}/propose", payload or {}, headers
        )

    def amend_resolution(self, resolution_id, payload, headers):
        return self._request(
            "POST", f"/governance-resolutions/{resolution_id}/amend", payload, headers
        )

    def ratify_resolution(self, resolution_id, headers, payload=None):
        return self._request(
            "POST", f"/governance-resolutions/{resolution_id}/ratify", payload or {}, headers
        )

    def reject_resolution(self, resolution_id, headers, payload=None):
        return self._request(
            "POST", f"/governance-resolutions/{resolution_id}/reject", payload or {}, headers
        )

    def get_resolution(self, resolution_id, headers):
        return self._request(
            "GET", f"/governance-resolutions/{resolution_id}", headers=headers
        )

    # ---- distributions ----------------------------------------------------
    def list_distributions(self, headers, params=None):
        return self._request(
            "GET", "/profit-share-distributions", headers=headers, params=params
        )

    def get_distribution(self, distribution_id, headers):
        return self._request(
            "GET", f"/profit-share-distributions/{distribution_id}", headers=headers
        )

    def mark_distribution_paid(self, distribution_id, headers, payload=None):
        return self._request(
            "POST", f"/profit-share-distributions/{distribution_id}/mark-paid",
            payload or {}, headers,
        )

    # ---- transfer requests -------------------------------------------------
    def list_transfer_requests(self, headers, params=None):
        return self._request("GET", "/transfer-requests", headers=headers, params=params)

    def get_transfer_request(self, transfer_id, headers):
        return self._request("GET", f"/transfer-requests/{transfer_id}", headers=headers)

    def approve_transfer(self, transfer_id, headers, payload=None):
        return self._request(
            "POST", f"/transfer-requests/{transfer_id}/approve", payload or {}, headers
        )

    def reject_transfer(self, transfer_id, headers, payload=None):
        return self._request(
            "POST", f"/transfer-requests/{transfer_id}/reject", payload or {}, headers
        )

    def cancel_transfer(self, transfer_id, headers, payload=None):
        return self._request(
            "POST", f"/transfer-requests/{transfer_id}/cancel", payload or {}, headers
        )

    def complete_transfer(self, transfer_id, headers, payload=None):
        return self._request(
            "POST", f"/transfer-requests/{transfer_id}/complete", payload or {}, headers
        )


api_client = ApiClient()
