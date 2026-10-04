"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/farm-network"


class ApiClient(GenericApiClient):
    # --- Farms (PRD §3.1) ---
    def create_farm(self, payload, headers):
        return self._request("POST", f"{PREFIX}/farms", payload, headers)

    def get_farm(self, farm_id, headers):
        return self._request("GET", f"{PREFIX}/farms/{farm_id}", headers=headers)

    def patch_farm(self, farm_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/farms/{farm_id}", payload, headers)

    def activate_farm(self, farm_id, headers):
        return self._request("POST", f"{PREFIX}/farms/{farm_id}/activate", {}, headers)

    def reinstate_farm(self, farm_id, headers):
        return self._request("POST", f"{PREFIX}/farms/{farm_id}/reinstate", {}, headers)

    def remove_farm(self, farm_id, payload, headers):
        return self._request("POST", f"{PREFIX}/farms/{farm_id}/remove", payload, headers)

    # --- Contracts (PRD §3.1) ---
    def create_contract(self, farm_id, payload, headers):
        return self._request("POST", f"{PREFIX}/farms/{farm_id}/contracts", payload, headers)

    def list_contracts(self, farm_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/farms/{farm_id}/contracts", headers=headers, params=params)

    # --- Audits (PRD §3.2) ---
    def schedule_audit(self, farm_id, payload, headers):
        return self._request("POST", f"{PREFIX}/farms/{farm_id}/audits", payload, headers)

    def list_farm_audits(self, farm_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/farms/{farm_id}/audits", headers=headers, params=params)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"{PREFIX}/audits/{audit_id}", headers=headers)

    def complete_audit(self, audit_id, payload, headers):
        return self._request("POST", f"{PREFIX}/audits/{audit_id}/complete", payload, headers)

    # --- Corrective actions (PRD §3.3) ---
    def list_corrective_actions(self, audit_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/audits/{audit_id}/corrective-actions", headers=headers, params=params)

    def submit_corrective_action(self, ca_id, payload, headers):
        return self._request("POST", f"{PREFIX}/corrective-actions/{ca_id}/submit", payload, headers)

    def verify_corrective_action(self, ca_id, payload, headers):
        return self._request("POST", f"{PREFIX}/corrective-actions/{ca_id}/verify", payload, headers)

    # --- Welfare incidents (PRD §3.4) ---
    def report_incident(self, farm_id, payload, headers):
        return self._request("POST", f"{PREFIX}/farms/{farm_id}/incidents", payload, headers)

    def list_incidents(self, farm_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/farms/{farm_id}/incidents", headers=headers, params=params)

    def resolve_incident(self, incident_id, payload, headers):
        return self._request("POST", f"{PREFIX}/incidents/{incident_id}/resolve", payload, headers)

    # --- Collection routes (PRD §3.5) ---
    def create_route(self, payload, headers):
        return self._request("POST", f"{PREFIX}/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"{PREFIX}/routes/{route_id}", headers=headers)

    def add_stop(self, route_id, payload, headers):
        return self._request("POST", f"{PREFIX}/routes/{route_id}/stops", payload, headers)

    def collect_stop(self, route_id, stop_sequence, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/routes/{route_id}/stops/{stop_sequence}/collect", payload, headers
        )

    def skip_stop(self, route_id, stop_sequence, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/routes/{route_id}/stops/{stop_sequence}/skip", payload, headers
        )

    def complete_route(self, route_id, headers):
        return self._request("POST", f"{PREFIX}/routes/{route_id}/complete", {}, headers)

    # --- Egg lots and cartons (PRD §3.6) ---
    def list_lots(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"{PREFIX}/lots/{lot_id}", headers=headers)

    def grade_lot(self, lot_id, payload, headers):
        return self._request("POST", f"{PREFIX}/lots/{lot_id}/grade", payload, headers)

    def resolve_hold(self, lot_id, payload, headers):
        return self._request("POST", f"{PREFIX}/lots/{lot_id}/resolve-hold", payload, headers)

    def pack_cartons(self, lot_id, payload, headers):
        return self._request("POST", f"{PREFIX}/lots/{lot_id}/cartons", payload, headers)

    def list_cartons(self, lot_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/lots/{lot_id}/cartons", headers=headers, params=params)

    def get_carton(self, carton_code, headers):
        return self._request("GET", f"{PREFIX}/cartons/{carton_code}", headers=headers)

    # --- Retailers, forecasts, commitments (PRD §3.7) ---
    def create_retailer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/retailers", payload, headers)

    def create_commitment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/commitments", payload, headers)

    def list_commitments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/commitments", headers=headers, params=params)

    def get_commitment(self, commitment_id, headers):
        return self._request("GET", f"{PREFIX}/commitments/{commitment_id}", headers=headers)

    def create_forecast(self, farm_id, payload, headers):
        return self._request("POST", f"{PREFIX}/farms/{farm_id}/forecasts", payload, headers)

    def list_forecasts(self, farm_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/farms/{farm_id}/forecasts", headers=headers, params=params)

    # --- Settlement runs (PRD §3.8) ---
    def create_settlement_run(self, payload, headers):
        return self._request("POST", f"{PREFIX}/settlement-runs", payload, headers)

    def get_settlement_run(self, run_id, headers):
        return self._request("GET", f"{PREFIX}/settlement-runs/{run_id}", headers=headers)

    def finalize_settlement(self, run_id, payload, headers):
        return self._request("POST", f"{PREFIX}/settlement-runs/{run_id}/finalize", payload, headers)

    # --- Logical clock (PRD §2.5) ---
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
