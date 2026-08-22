"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Station ──────────────────────────────────────────────────────────

    def create_station(self, payload, headers):
        return self._request("POST", "/stations", payload, headers)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/stations/{station_id}", headers=headers)

    def list_stations(self, headers, params=None):
        return self._request("GET", "/stations", headers=headers, params=params)

    def station_lifecycle(self, station_id, payload, headers):
        return self._request(
            "POST", f"/stations/{station_id}/lifecycle", payload, headers)

    def season_rollover(self, station_id, payload, headers):
        return self._request(
            "POST", f"/stations/{station_id}/season-rollovers", payload, headers)

    # ─── Subcontractor ────────────────────────────────────────────────────

    def create_subcontractor(self, payload, headers):
        return self._request("POST", "/subcontractors", payload, headers)

    def get_subcontractor(self, subcontractor_id, headers):
        return self._request(
            "GET", f"/subcontractors/{subcontractor_id}", headers=headers)

    def list_subcontractors(self, headers, params=None):
        return self._request("GET", "/subcontractors", headers=headers, params=params)

    def oversight_decision(self, subcontractor_id, payload, headers):
        return self._request(
            "POST", f"/subcontractors/{subcontractor_id}/oversight-decisions",
            payload, headers)

    # ─── FlightBank ───────────────────────────────────────────────────────

    def create_flight_bank(self, payload, headers):
        return self._request("POST", "/flight-banks", payload, headers)

    def get_flight_bank(self, flight_bank_id, headers):
        return self._request(
            "GET", f"/flight-banks/{flight_bank_id}", headers=headers)

    def list_flight_banks(self, headers, params=None):
        return self._request("GET", "/flight-banks", headers=headers, params=params)

    def flight_bank_lifecycle(self, flight_bank_id, payload, headers):
        return self._request(
            "POST", f"/flight-banks/{flight_bank_id}/lifecycle", payload, headers)

    def staffing_transition(self, flight_bank_id, payload, headers):
        return self._request(
            "POST", f"/flight-banks/{flight_bank_id}/staffing-transitions",
            payload, headers)

    # ─── Turn ─────────────────────────────────────────────────────────────

    def create_turn(self, payload, headers):
        return self._request("POST", "/turns", payload, headers)

    def get_turn(self, turn_id, headers):
        return self._request("GET", f"/turns/{turn_id}", headers=headers)

    def list_turns(self, headers, params=None):
        return self._request("GET", "/turns", headers=headers, params=params)

    def turn_lifecycle(self, turn_id, payload, headers):
        return self._request(
            "POST", f"/turns/{turn_id}/lifecycle", payload, headers)

    # ─── Agent ────────────────────────────────────────────────────────────

    def create_agent(self, payload, headers):
        return self._request("POST", "/agents", payload, headers)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"/agents/{agent_id}", headers=headers)

    def list_agents(self, headers, params=None):
        return self._request("GET", "/agents", headers=headers, params=params)

    # ─── Certification ────────────────────────────────────────────────────

    def create_certification(self, payload, headers):
        return self._request("POST", "/certifications", payload, headers)

    def get_certification(self, certification_id, headers):
        return self._request(
            "GET", f"/certifications/{certification_id}", headers=headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/certifications", headers=headers, params=params)

    def revoke_certification(self, certification_id, payload, headers):
        return self._request(
            "POST", f"/certifications/{certification_id}/revoke", payload, headers)

    # ─── GSE unit ─────────────────────────────────────────────────────────

    def create_gse_unit(self, payload, headers):
        return self._request("POST", "/gse-units", payload, headers)

    def get_gse_unit(self, gse_unit_id, headers):
        return self._request("GET", f"/gse-units/{gse_unit_id}", headers=headers)

    def list_gse_units(self, headers, params=None):
        return self._request("GET", "/gse-units", headers=headers, params=params)

    def gse_service_event(self, gse_unit_id, payload, headers):
        return self._request(
            "POST", f"/gse-units/{gse_unit_id}/service-events", payload, headers)

    # ─── TurnResource ─────────────────────────────────────────────────────

    def create_turn_resource(self, payload, headers):
        return self._request("POST", "/turn-resources", payload, headers)

    def get_turn_resource(self, turn_resource_id, headers):
        return self._request(
            "GET", f"/turn-resources/{turn_resource_id}", headers=headers)

    def list_turn_resources(self, headers, params=None):
        return self._request("GET", "/turn-resources", headers=headers, params=params)

    def release_turn_resource(self, turn_resource_id, payload, headers):
        return self._request(
            "POST", f"/turn-resources/{turn_resource_id}/release", payload, headers)

    # ─── Incident ─────────────────────────────────────────────────────────

    def create_incident(self, payload, headers):
        return self._request("POST", "/incidents", payload, headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/incidents/{incident_id}", headers=headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/incidents", headers=headers, params=params)

    def incident_transition(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/incidents/{incident_id}/transitions", payload, headers)

    # ─── BillingPeriod ────────────────────────────────────────────────────

    def create_billing_period(self, payload, headers):
        return self._request("POST", "/billing-periods", payload, headers)

    def get_billing_period(self, billing_period_id, headers):
        return self._request(
            "GET", f"/billing-periods/{billing_period_id}", headers=headers)

    def list_billing_periods(self, headers, params=None):
        return self._request("GET", "/billing-periods", headers=headers, params=params)

    def billing_period_transition(self, billing_period_id, payload, headers):
        return self._request(
            "POST", f"/billing-periods/{billing_period_id}/transitions",
            payload, headers)

    # ─── BillingLine ──────────────────────────────────────────────────────

    def create_billing_line(self, payload, headers):
        return self._request("POST", "/billing-lines", payload, headers)

    def get_billing_line(self, billing_line_id, headers):
        return self._request(
            "GET", f"/billing-lines/{billing_line_id}", headers=headers)

    def list_billing_lines(self, headers, params=None):
        return self._request("GET", "/billing-lines", headers=headers, params=params)

    def void_billing_line(self, billing_line_id, payload, headers):
        return self._request(
            "POST", f"/billing-lines/{billing_line_id}/void", payload, headers)

    # ─── Logical clock ────────────────────────────────────────────────────

    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
