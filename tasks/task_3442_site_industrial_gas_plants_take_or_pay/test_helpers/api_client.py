"""API client: one method per endpoint defined in the PRD (section 4).

CRITICAL routing rule (PRD section 2.4): the logical clock is a platform-level
capability mounted at the server ROOT — `/_clock/set_current_utc` is
deliberately OUTSIDE the `/gas-supply` prefix. Every business resource lives
under `/gas-supply`. Do not prefix the clock path.
"""
from prd_bench_local_runner.testing import GenericApiClient

API_PREFIX = "/gas-supply"
# Platform-level endpoint: mounted at server root, NOT under API_PREFIX.
CLOCK_SET_PATH = "/_clock/set_current_utc"


class ApiClient(GenericApiClient):
    """Endpoint methods for the Onsite Gas Take-or-Pay API."""

    # --- Platform / logical clock (unprefixed) ---
    def set_clock(self, payload, headers):
        return self._request("POST", CLOCK_SET_PATH, payload, headers)

    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/customers/{customer_id}", headers=headers
        )

    # --- SupplyModeEvaluation ---
    def create_evaluation(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/supply-mode-evaluations", payload, headers
        )

    def list_customer_evaluations(self, customer_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/customers/{customer_id}/supply-mode-evaluations",
            headers=headers,
            params=params,
        )

    def accept_evaluation(self, evaluation_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/supply-mode-evaluations/{evaluation_id}/accept",
            {},
            headers,
        )

    # --- SupplyContract ---
    def create_contract(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/supply-contracts", payload, headers
        )

    def get_contract(self, contract_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/supply-contracts/{contract_id}", headers=headers
        )

    def list_contracts(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/supply-contracts", headers=headers, params=params
        )

    def activate_contract(self, contract_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/supply-contracts/{contract_id}/activate", {}, headers
        )

    def create_contract_amendment(self, contract_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/supply-contracts/{contract_id}/amendments",
            payload,
            headers,
        )

    def terminate_contract(self, contract_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/supply-contracts/{contract_id}/terminate", {}, headers
        )

    # --- OnsitePlant ---
    def create_plant(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/onsite-plants", payload, headers)

    def get_plant(self, plant_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/onsite-plants/{plant_id}", headers=headers
        )

    def list_plants(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/onsite-plants", headers=headers, params=params
        )

    def advance_plant(self, plant_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/onsite-plants/{plant_id}/advance", {}, headers
        )

    # --- PipelineNetwork ---
    def create_network(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/pipeline-networks", payload, headers
        )

    def get_network(self, network_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/pipeline-networks/{network_id}", headers=headers
        )

    # --- PipelineConnection ---
    def create_connection(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/pipeline-connections", payload, headers
        )

    def get_connection(self, connection_id, headers):
        return self._request(
            "GET",
            f"{API_PREFIX}/pipeline-connections/{connection_id}",
            headers=headers,
        )

    def list_connections(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/pipeline-connections", headers=headers, params=params
        )

    def release_connection(self, connection_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/pipeline-connections/{connection_id}/release",
            {},
            headers,
        )

    # --- StorageTank + Telemetry ---
    def create_tank(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/storage-tanks", payload, headers)

    def get_tank(self, tank_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/storage-tanks/{tank_id}", headers=headers
        )

    def list_tanks(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/storage-tanks", headers=headers, params=params
        )

    def create_telemetry_reading(self, tank_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/storage-tanks/{tank_id}/telemetry", payload, headers
        )

    def list_telemetry_readings(self, tank_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/storage-tanks/{tank_id}/telemetry",
            headers=headers,
            params=params,
        )

    # --- Delivery ---
    def get_delivery(self, delivery_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/deliveries/{delivery_id}", headers=headers
        )

    def list_deliveries(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/deliveries", headers=headers, params=params
        )

    def confirm_delivery(self, delivery_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/deliveries/{delivery_id}/confirm-delivery",
            payload,
            headers,
        )

    # --- QualityCertificate ---
    def create_quality_certificate(self, delivery_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/deliveries/{delivery_id}/quality-certificates",
            payload,
            headers,
        )

    def list_quality_certificates(self, delivery_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/deliveries/{delivery_id}/quality-certificates",
            headers=headers,
            params=params,
        )

    def certify_quality_certificate(self, certificate_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/quality-certificates/{certificate_id}/certify",
            payload,
            headers,
        )

    # --- Turnaround ---
    def create_turnaround(self, plant_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/onsite-plants/{plant_id}/turnarounds",
            payload,
            headers,
        )

    def list_plant_turnarounds(self, plant_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/onsite-plants/{plant_id}/turnarounds",
            headers=headers,
            params=params,
        )

    def respond_to_turnaround(self, turnaround_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/turnarounds/{turnaround_id}/respond",
            payload,
            headers,
        )

    def schedule_turnaround(self, turnaround_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/turnarounds/{turnaround_id}/schedule", {}, headers
        )

    def start_turnaround(self, turnaround_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/turnarounds/{turnaround_id}/start", {}, headers
        )

    # --- SettlementStatement ---
    def create_settlement(self, contract_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/supply-contracts/{contract_id}/settlements",
            payload,
            headers,
        )

    def list_settlements(self, contract_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/supply-contracts/{contract_id}/settlements",
            headers=headers,
            params=params,
        )


api_client = ApiClient()

__all__ = ["ApiClient", "api_client", "API_PREFIX", "CLOCK_SET_PATH"]
