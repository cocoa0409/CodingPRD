"""API client: one method per endpoint declared in the PRD (all under /valet)."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/valet"


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- clock
    def set_clock(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers
        )

    # ------------------------------------------------------------ properties
    def create_property(self, payload, headers):
        return self._request("POST", f"{PREFIX}/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request(
            "GET", f"{PREFIX}/properties/{property_id}", headers=headers
        )

    def list_properties(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/properties", headers=headers, params=params)

    # ------------------------------------------------------------- contracts
    def create_contract(self, property_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/properties/{property_id}/contracts", payload, headers
        )

    def get_contract(self, contract_id, headers):
        return self._request(
            "GET", f"{PREFIX}/contracts/{contract_id}", headers=headers
        )

    def list_contracts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/contracts", headers=headers, params=params)

    def activate_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/contracts/{contract_id}/activate", payload or {}, headers
        )

    def terminate_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/contracts/{contract_id}/terminate", payload or {}, headers
        )

    # ------------------------------------------------------------- residents
    def create_resident(self, property_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/properties/{property_id}/residents", payload, headers
        )

    def get_resident(self, resident_id, headers):
        return self._request(
            "GET", f"{PREFIX}/residents/{resident_id}", headers=headers
        )

    def list_residents(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/residents", headers=headers, params=params)

    def move_out_resident(self, resident_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/residents/{resident_id}/move-out", payload, headers
        )

    # ----------------------------------------------------------- contractors
    def create_contractor(self, payload, headers):
        return self._request("POST", f"{PREFIX}/contractors", payload, headers)

    def get_contractor(self, contractor_id, headers):
        return self._request(
            "GET", f"{PREFIX}/contractors/{contractor_id}", headers=headers
        )

    def list_contractors(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/contractors", headers=headers, params=params
        )

    def submit_contractor_documents(self, contractor_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/contractors/{contractor_id}/documents", payload, headers
        )

    def record_background_check(self, contractor_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/contractors/{contractor_id}/background-check",
            payload,
            headers,
        )

    def run_classification(self, contractor_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/contractors/{contractor_id}/classification",
            payload,
            headers,
        )

    def deactivate_contractor(self, contractor_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/contractors/{contractor_id}/deactivate", payload, headers
        )

    # --------------------------------------------------------- service nights
    def create_service_night(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/contracts/{contract_id}/service-nights", payload, headers
        )

    def get_service_night(self, night_id, headers):
        return self._request(
            "GET", f"{PREFIX}/service-nights/{night_id}", headers=headers
        )

    def list_service_nights(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/service-nights", headers=headers, params=params
        )

    def close_service_night(self, night_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/service-nights/{night_id}/close", payload or {}, headers
        )

    def reschedule_service_night(self, night_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/service-nights/{night_id}/reschedule", payload, headers
        )

    # ------------------------------------------------------ route assignments
    def create_route_assignment(self, night_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/service-nights/{night_id}/route-assignments",
            payload,
            headers,
        )

    def get_route_assignment(self, route_id, headers):
        return self._request(
            "GET", f"{PREFIX}/route-assignments/{route_id}", headers=headers
        )

    def list_route_assignments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/route-assignments", headers=headers, params=params
        )

    def accept_route(self, route_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/route-assignments/{route_id}/accept", payload or {}, headers
        )

    def complete_route(self, route_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/route-assignments/{route_id}/complete",
            payload or {},
            headers,
        )

    def abandon_route(self, route_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/route-assignments/{route_id}/abandon", payload, headers
        )

    # ----------------------------------------------------------------- scans
    def record_scan(self, route_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/route-assignments/{route_id}/scans", payload, headers
        )

    def get_scan(self, scan_id, headers):
        return self._request(
            "GET", f"{PREFIX}/service-scans/{scan_id}", headers=headers
        )

    def list_scans(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/service-scans", headers=headers, params=params
        )

    def assess_fine(self, scan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/service-scans/{scan_id}/fine", payload, headers
        )

    def void_tag(self, scan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/service-scans/{scan_id}/void-tag", payload, headers
        )

    # ----------------------------------------------------------------- fines
    def get_fine(self, fine_id, headers):
        return self._request(
            "GET", f"{PREFIX}/resident-fines/{fine_id}", headers=headers
        )

    def list_fines(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/resident-fines", headers=headers, params=params
        )

    def dispute_fine(self, fine_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/resident-fines/{fine_id}/dispute", payload, headers
        )

    def adjudicate_fine(self, fine_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/resident-fines/{fine_id}/adjudicate", payload, headers
        )

    # ---------------------------------------------------- compactor incidents
    def create_compactor_incident(self, property_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/properties/{property_id}/compactor-incidents",
            payload,
            headers,
        )

    def get_compactor_incident(self, incident_id, headers):
        return self._request(
            "GET", f"{PREFIX}/compactor-incidents/{incident_id}", headers=headers
        )

    def list_compactor_incidents(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/compactor-incidents", headers=headers, params=params
        )

    def acknowledge_incident(self, incident_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/compactor-incidents/{incident_id}/acknowledge",
            payload or {},
            headers,
        )

    def escalate_incident(self, incident_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/compactor-incidents/{incident_id}/escalate",
            payload or {},
            headers,
        )

    def resolve_incident(self, incident_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/compactor-incidents/{incident_id}/resolve",
            payload,
            headers,
        )

    # ------------------------------------------------------------ statements
    def create_statement(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/contracts/{contract_id}/statements", payload, headers
        )

    def get_statement(self, statement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/statements/{statement_id}", headers=headers
        )

    def list_statements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/statements", headers=headers, params=params
        )

    def issue_statement(self, statement_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/statements/{statement_id}/issue", payload or {}, headers
        )

    def void_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/statements/{statement_id}/void", payload, headers
        )


api_client = ApiClient()
