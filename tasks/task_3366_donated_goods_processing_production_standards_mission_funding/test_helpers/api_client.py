"""API client: one method per endpoint defined in the PRD (section 4).
All resources are mounted under /donated-goods."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/donated-goods"


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Member organizations ------------------------------------------------
    def create_member_org(self, payload, headers):
        return self._request("POST", f"{PREFIX}/member-orgs", payload, headers)

    def get_member_org(self, org_id, headers):
        return self._request("GET", f"{PREFIX}/member-orgs/{org_id}", headers=headers)

    def suspend_member_org(self, org_id, headers):
        return self._request(
            "POST", f"{PREFIX}/member-orgs/{org_id}/suspend", {}, headers)

    def reinstate_member_org(self, org_id, headers):
        return self._request(
            "POST", f"{PREFIX}/member-orgs/{org_id}/reinstate", {}, headers)

    # --- Territories ----------------------------------------------------------
    def create_territory(self, payload, headers):
        return self._request("POST", f"{PREFIX}/territories", payload, headers)

    def list_territories(self, org_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/member-orgs/{org_id}/territories",
            headers=headers, params=params)

    # --- Donation sites --------------------------------------------------------
    def create_donation_site(self, payload, headers):
        return self._request("POST", f"{PREFIX}/donation-sites", payload, headers)

    def list_donation_sites(self, org_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/member-orgs/{org_id}/donation-sites",
            headers=headers, params=params)

    # --- Donations -------------------------------------------------------------
    def create_donation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/donations", payload, headers)

    def list_donations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/donations", headers=headers, params=params)

    def get_donation(self, donation_id, headers):
        return self._request("GET", f"{PREFIX}/donations/{donation_id}", headers=headers)

    def sort_donation(self, donation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/donations/{donation_id}/sort", payload, headers)

    # --- Donated items -----------------------------------------------------------
    def list_donated_items(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/donated-items", headers=headers, params=params)

    def get_donated_item(self, item_id, headers):
        return self._request("GET", f"{PREFIX}/donated-items/{item_id}", headers=headers)

    def price_item(self, item_id, headers):
        return self._request(
            "POST", f"{PREFIX}/donated-items/{item_id}/price", {}, headers)

    def sell_item(self, item_id, headers):
        return self._request(
            "POST", f"{PREFIX}/donated-items/{item_id}/sell", {}, headers)

    # --- Production standards -----------------------------------------------------
    def create_production_standard(self, payload, headers):
        return self._request("POST", f"{PREFIX}/production-standards", payload, headers)

    def list_production_standards(self, org_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/member-orgs/{org_id}/production-standards",
            headers=headers, params=params)

    # --- Processing runs ------------------------------------------------------------
    def create_processing_run(self, payload, headers):
        return self._request("POST", f"{PREFIX}/processing-runs", payload, headers)

    def list_processing_runs(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/processing-runs", headers=headers, params=params)

    def get_processing_run(self, run_id, headers):
        return self._request(
            "GET", f"{PREFIX}/processing-runs/{run_id}", headers=headers)

    def close_processing_run(self, run_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/processing-runs/{run_id}/close", payload, headers)

    # --- Markdown events --------------------------------------------------------------
    def create_markdown_event(self, org_id, headers):
        return self._request(
            "POST", f"{PREFIX}/member-orgs/{org_id}/markdown-events", {}, headers)

    # --- Salvage lots --------------------------------------------------------------------
    def create_salvage_lot(self, payload, headers):
        return self._request("POST", f"{PREFIX}/salvage-lots", payload, headers)

    def list_salvage_lots(self, org_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/member-orgs/{org_id}/salvage-lots",
            headers=headers, params=params)

    def add_items_to_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/salvage-lots/{lot_id}/add-items", payload, headers)

    def sell_salvage_lot(self, lot_id, headers):
        return self._request(
            "POST", f"{PREFIX}/salvage-lots/{lot_id}/sell", {}, headers)

    # --- Mission programs ------------------------------------------------------------------
    def create_mission_program(self, payload, headers):
        return self._request("POST", f"{PREFIX}/mission-programs", payload, headers)

    def list_mission_programs(self, org_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/member-orgs/{org_id}/mission-programs",
            headers=headers, params=params)

    # --- Funding allocations ------------------------------------------------------------------
    def create_funding_allocation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/funding-allocations", payload, headers)

    def list_funding_allocations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/funding-allocations", headers=headers, params=params)

    def get_funding_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/funding-allocations/{allocation_id}", headers=headers)

    def approve_allocation(self, allocation_id, headers):
        return self._request(
            "POST", f"{PREFIX}/funding-allocations/{allocation_id}/approve", {}, headers)

    def cancel_allocation(self, allocation_id, headers):
        return self._request(
            "POST", f"{PREFIX}/funding-allocations/{allocation_id}/cancel", {}, headers)

    def disburse_allocation(self, allocation_id, headers):
        return self._request(
            "POST", f"{PREFIX}/funding-allocations/{allocation_id}/disburse", {}, headers)

    # --- Workforce contracts ----------------------------------------------------------------------
    def create_workforce_contract(self, payload, headers):
        return self._request("POST", f"{PREFIX}/workforce-contracts", payload, headers)

    def list_workforce_contracts(self, org_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/member-orgs/{org_id}/workforce-contracts",
            headers=headers, params=params)

    def create_review(self, contract_id, action, headers):
        return self._request(
            "POST", f"{PREFIX}/workforce-contracts/{contract_id}/reviews",
            {"action": action}, headers)

    # --- Contract milestones -------------------------------------------------------------------------
    def list_milestones(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/milestones", headers=headers, params=params)

    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"{PREFIX}/milestones/{milestone_id}", headers=headers)

    def attest_milestone(self, milestone_id, headers):
        return self._request(
            "POST", f"{PREFIX}/milestones/{milestone_id}/attest", {}, headers)

    # --- Disposal tickets -------------------------------------------------------------------------------
    def create_disposal_ticket(self, payload, headers):
        return self._request("POST", f"{PREFIX}/disposal-tickets", payload, headers)

    def list_disposal_tickets(self, org_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/member-orgs/{org_id}/disposal-tickets",
            headers=headers, params=params)


api_client = ApiClient()
