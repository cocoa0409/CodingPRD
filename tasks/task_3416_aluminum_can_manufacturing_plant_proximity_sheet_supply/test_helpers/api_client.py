"""API client: one method per endpoint defined in the PRD (§4).

All paths are root-relative; the API declares no path prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving logical clock ---
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    # --- Plant ---
    def create_plant(self, payload, headers):
        return self._request("POST", "/plants", payload, headers)

    def get_plant(self, plant_id, headers):
        return self._request("GET", f"/plants/{plant_id}", headers=headers)

    def run_ops(self, plant_id, headers):
        return self._request("POST", f"/plants/{plant_id}/run-ops", {}, headers)

    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    # --- SupplyAgreement ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/supply-agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/supply-agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/supply-agreements/{agreement_id}", headers=headers)

    def sign_agreement(self, agreement_id, headers):
        return self._request("POST", f"/supply-agreements/{agreement_id}/sign", {}, headers)

    def open_renegotiation(self, agreement_id, headers):
        return self._request("POST", f"/supply-agreements/{agreement_id}/open-renegotiation",
                             {}, headers)

    def amend_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/supply-agreements/{agreement_id}/amend",
                             payload, headers)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/supply-agreements/{agreement_id}/terminate",
                             {}, headers)

    # --- MetalPriceIndex ---
    def publish_index(self, payload, headers):
        return self._request("POST", "/metal-price-indices", payload, headers)

    # --- ProductionLine ---
    def create_line(self, plant_id, payload, headers):
        return self._request("POST", f"/plants/{plant_id}/lines", payload, headers)

    def list_lines(self, plant_id, headers, params=None):
        return self._request("GET", f"/plants/{plant_id}/lines",
                             headers=headers, params=params)

    # --- CanFormat ---
    def create_format(self, plant_id, payload, headers):
        return self._request("POST", f"/plants/{plant_id}/formats", payload, headers)

    def get_format(self, format_id, headers):
        return self._request("GET", f"/formats/{format_id}", headers=headers)

    def list_formats(self, headers, params=None):
        return self._request("GET", "/formats", headers=headers, params=params)

    def tool_format(self, format_id, headers):
        return self._request("POST", f"/formats/{format_id}/tool", {}, headers)

    def qualify_format(self, format_id, headers):
        return self._request("POST", f"/formats/{format_id}/qualify", {}, headers)

    def retire_format(self, format_id, headers):
        return self._request("POST", f"/formats/{format_id}/retire", {}, headers)

    # --- ProductionRun ---
    def create_run(self, agreement_id, payload, headers):
        return self._request("POST", f"/supply-agreements/{agreement_id}/production-runs",
                             payload, headers)

    def list_runs(self, headers, params=None):
        return self._request("GET", "/production-runs", headers=headers, params=params)

    def get_run(self, run_id, headers):
        return self._request("GET", f"/production-runs/{run_id}", headers=headers)

    def start_run(self, run_id, headers):
        return self._request("POST", f"/production-runs/{run_id}/start", {}, headers)

    def complete_run(self, run_id, payload, headers):
        return self._request("POST", f"/production-runs/{run_id}/complete",
                             payload, headers)

    def settle_run(self, run_id, headers):
        return self._request("POST", f"/production-runs/{run_id}/settle", {}, headers)

    def cancel_run(self, run_id, headers):
        return self._request("POST", f"/production-runs/{run_id}/cancel", {}, headers)

    def void_run(self, run_id, headers):
        return self._request("POST", f"/production-runs/{run_id}/void", {}, headers)

    # --- CustomerForecast ---
    def create_forecast(self, agreement_id, payload, headers):
        return self._request("POST", f"/supply-agreements/{agreement_id}/forecasts",
                             payload, headers)

    def list_forecasts(self, agreement_id, headers, params=None):
        return self._request("GET", f"/supply-agreements/{agreement_id}/forecasts",
                             headers=headers, params=params)

    def close_forecast(self, forecast_id, payload, headers):
        return self._request("POST", f"/forecasts/{forecast_id}/close", payload, headers)

    # --- ScrapReturn ---
    def create_scrap_return(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/scrap-returns",
                             payload, headers)

    def list_scrap_returns(self, headers, params=None):
        return self._request("GET", "/scrap-returns", headers=headers, params=params)

    def get_scrap_return(self, scrap_id, headers):
        return self._request("GET", f"/scrap-returns/{scrap_id}", headers=headers)

    def credit_scrap_return(self, scrap_id, payload, headers):
        return self._request("POST", f"/scrap-returns/{scrap_id}/credit",
                             payload, headers)

    # --- QualityIncident ---
    def create_incident(self, run_id, payload, headers):
        return self._request("POST", f"/production-runs/{run_id}/quality-incidents",
                             payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/quality-incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/quality-incidents/{incident_id}", headers=headers)

    def escalate_incident(self, incident_id, headers):
        return self._request("POST", f"/quality-incidents/{incident_id}/escalate",
                             {}, headers)

    def resolve_incident(self, incident_id, headers):
        return self._request("POST", f"/quality-incidents/{incident_id}/resolve",
                             {}, headers)


api_client = ApiClient()
