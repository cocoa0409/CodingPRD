"""API client: one method per endpoint defined in the PRD section 4 table.

The logical-clock capability is the single endpoint living OUTSIDE the
/crayon-works mount (PRD section 4): POST /_clock/set_current_utc.
"""
from prd_bench_local_runner.testing import GenericApiClient

P = "/crayon-works"


class ApiClient(GenericApiClient):
    # --- Color ---
    def create_color(self, payload, headers):
        return self._request("POST", f"{P}/colors", payload, headers)

    def get_color(self, color_id, headers):
        return self._request("GET", f"{P}/colors/{color_id}", headers=headers)

    def create_vote_campaign(self, color_id, payload, headers):
        return self._request("POST", f"{P}/colors/{color_id}/vote-campaigns", payload, headers)

    def list_vote_campaigns(self, color_id, headers, params=None):
        return self._request("GET", f"{P}/colors/{color_id}/vote-campaigns", headers=headers, params=params)

    def list_color_formulas(self, color_id, headers, params=None):
        return self._request("GET", f"{P}/colors/{color_id}/formulas", headers=headers, params=params)

    # --- PigmentBatch ---
    def create_pigment_batch(self, payload, headers):
        return self._request("POST", f"{P}/pigment-batches", payload, headers)

    def get_pigment_batch(self, batch_id, headers):
        return self._request("GET", f"{P}/pigment-batches/{batch_id}", headers=headers)

    def certification_decision(self, batch_id, payload, headers):
        return self._request("POST", f"{P}/pigment-batches/{batch_id}/certification-decision", payload, headers)

    def list_recall_cases(self, batch_id, headers, params=None):
        return self._request("GET", f"{P}/pigment-batches/{batch_id}/recall-cases", headers=headers, params=params)

    # --- AssortmentSpec ---
    def create_assortment_spec(self, payload, headers):
        return self._request("POST", f"{P}/assortment-specs", payload, headers)

    def get_assortment_spec(self, spec_id, headers):
        return self._request("GET", f"{P}/assortment-specs/{spec_id}", headers=headers)

    def list_spec_allocations(self, spec_id, headers, params=None):
        return self._request("GET", f"{P}/assortment-specs/{spec_id}/retail-allocations", headers=headers, params=params)

    # --- Formula ---
    def create_formula(self, payload, headers):
        return self._request("POST", f"{P}/formulas", payload, headers)

    def get_formula(self, formula_id, headers):
        return self._request("GET", f"{P}/formulas/{formula_id}", headers=headers)

    def formula_transition(self, formula_id, payload, headers):
        return self._request("POST", f"{P}/formulas/{formula_id}/transition", payload, headers)

    def list_safety_tests(self, formula_id, headers, params=None):
        return self._request("GET", f"{P}/formulas/{formula_id}/safety-tests", headers=headers, params=params)

    def list_formula_licensed_lines(self, formula_id, headers, params=None):
        return self._request("GET", f"{P}/formulas/{formula_id}/licensed-lines", headers=headers, params=params)

    # --- ProductionRun ---
    def create_production_run(self, payload, headers):
        return self._request("POST", f"{P}/production-runs", payload, headers)

    def get_production_run(self, run_id, headers):
        return self._request("GET", f"{P}/production-runs/{run_id}", headers=headers)

    def list_production_runs(self, headers, params=None):
        return self._request("GET", f"{P}/production-runs", headers=headers, params=params)

    def production_run_transition(self, run_id, payload, headers):
        return self._request("POST", f"{P}/production-runs/{run_id}/transition", payload, headers)

    def list_inventory_lots(self, run_id, headers, params=None):
        return self._request("GET", f"{P}/production-runs/{run_id}/inventory-lots", headers=headers, params=params)

    # --- RetailAllocation ---
    def create_retail_allocation(self, payload, headers):
        return self._request("POST", f"{P}/retail-allocations", payload, headers)

    def get_retail_allocation(self, alloc_id, headers):
        return self._request("GET", f"{P}/retail-allocations/{alloc_id}", headers=headers)

    def allocation_decision(self, alloc_id, payload, headers):
        return self._request("POST", f"{P}/retail-allocations/{alloc_id}/decision", payload, headers)

    # --- LicensedLine ---
    def create_licensed_line(self, payload, headers):
        return self._request("POST", f"{P}/licensed-lines", payload, headers)

    def get_licensed_line(self, line_id, headers):
        return self._request("GET", f"{P}/licensed-lines/{line_id}", headers=headers)

    def licensed_line_transition(self, line_id, payload, headers):
        return self._request("POST", f"{P}/licensed-lines/{line_id}/transition", payload, headers)

    # --- AttractionSession / Ticket ---
    def create_attraction_session(self, payload, headers):
        return self._request("POST", f"{P}/attraction-sessions", payload, headers)

    def get_attraction_session(self, session_id, headers):
        return self._request("GET", f"{P}/attraction-sessions/{session_id}", headers=headers)

    def list_session_tickets(self, session_id, headers, params=None):
        return self._request("GET", f"{P}/attraction-sessions/{session_id}/tickets", headers=headers, params=params)

    def create_ticket(self, payload, headers):
        return self._request("POST", f"{P}/tickets", payload, headers)

    def ticket_decision(self, ticket_id, payload, headers):
        return self._request("POST", f"{P}/tickets/{ticket_id}/decision", payload, headers)

    # --- SafetyTest ---
    def record_safety_test_result(self, test_id, payload, headers):
        return self._request("POST", f"{P}/safety-tests/{test_id}/record-result", payload, headers)

    # --- Votes ---
    def cast_vote(self, payload, headers):
        return self._request("POST", f"{P}/votes", payload, headers)

    # --- System / test-driving ---
    def set_clock(self, to_iso8601, headers):
        # PRD section 4: this endpoint lives OUTSIDE the /crayon-works mount.
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def run_epoch(self, headers):
        return self._request("POST", f"{P}/ops/run-epoch", {}, headers)


api_client = ApiClient()
