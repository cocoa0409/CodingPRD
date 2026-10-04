"""API client: one method per endpoint defined in the PRD (section 4).

All paths are under the /genomics prefix. Action endpoints accept a payload
dict built by test_helpers.factories (e.g. order_advance_payload("SUBMIT")).
Endpoints with no request body accept payload=None and send an empty object.
"""
from prd_bench_local_runner.testing import GenericApiClient

__all__ = ["ApiClient", "api_client"]


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Accounts
    # ------------------------------------------------------------------
    def create_account(self, payload, headers):
        return self._request("POST", "/genomics/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/genomics/accounts/{account_id}", headers=headers)

    # ------------------------------------------------------------------
    # Vendor catalog: models, kits, software updates
    # ------------------------------------------------------------------
    def create_instrument_model(self, payload, headers):
        return self._request("POST", "/genomics/instrument-models", payload, headers)

    def create_reagent_kit(self, payload, headers):
        return self._request("POST", "/genomics/reagent-kits", payload, headers)

    def update_reagent_kit(self, kit_id, payload, headers):
        return self._request("PATCH", f"/genomics/reagent-kits/{kit_id}", payload, headers)

    def create_software_update(self, payload, headers):
        return self._request("POST", "/genomics/software-updates", payload, headers)

    def withdraw_software_update(self, update_id, headers, payload=None):
        return self._request(
            "POST", f"/genomics/software-updates/{update_id}/withdraw",
            payload if payload is not None else {}, headers,
        )

    # ------------------------------------------------------------------
    # Instruments
    # ------------------------------------------------------------------
    def create_instrument(self, payload, headers):
        return self._request("POST", "/genomics/instruments", payload, headers)

    def get_instrument(self, instrument_id, headers):
        return self._request("GET", f"/genomics/instruments/{instrument_id}", headers=headers)

    def list_instruments(self, headers, params=None):
        return self._request("GET", "/genomics/instruments", headers=headers, params=params)

    def post_instrument_event(self, instrument_id, payload, headers):
        return self._request(
            "POST", f"/genomics/instruments/{instrument_id}/events", payload, headers
        )

    def apply_software_update(self, instrument_id, payload, headers):
        return self._request(
            "POST", f"/genomics/instruments/{instrument_id}/software-updates", payload, headers
        )

    # ------------------------------------------------------------------
    # Placement programs
    # ------------------------------------------------------------------
    def create_placement_program(self, payload, headers):
        return self._request("POST", "/genomics/placement-programs", payload, headers)

    def get_placement_program(self, program_id, headers):
        return self._request(
            "GET", f"/genomics/placement-programs/{program_id}", headers=headers
        )

    def list_placement_programs(self, headers, params=None):
        return self._request("GET", "/genomics/placement-programs", headers=headers, params=params)

    def review_placement_program(self, program_id, payload, headers):
        return self._request(
            "POST", f"/genomics/placement-programs/{program_id}/review", payload, headers
        )

    def post_placement_amendment(self, program_id, payload, headers):
        return self._request(
            "POST", f"/genomics/placement-programs/{program_id}/amendments", payload, headers
        )

    def close_placement_period(self, program_id, headers, payload=None):
        return self._request(
            "POST", f"/genomics/placement-programs/{program_id}/close-period",
            payload if payload is not None else {}, headers,
        )

    # ------------------------------------------------------------------
    # Reagent lots
    # ------------------------------------------------------------------
    def create_reagent_lot(self, payload, headers):
        return self._request("POST", "/genomics/reagent-lots", payload, headers)

    def get_reagent_lot(self, lot_id, headers):
        return self._request("GET", f"/genomics/reagent-lots/{lot_id}", headers=headers)

    def list_reagent_lots(self, headers, params=None):
        return self._request("GET", "/genomics/reagent-lots", headers=headers, params=params)

    def post_lot_qc(self, lot_id, payload, headers):
        return self._request("POST", f"/genomics/reagent-lots/{lot_id}/qc", payload, headers)

    # ------------------------------------------------------------------
    # Reagent orders
    # ------------------------------------------------------------------
    def create_reagent_order(self, payload, headers):
        return self._request("POST", "/genomics/reagent-orders", payload, headers)

    def get_reagent_order(self, order_id, headers):
        return self._request("GET", f"/genomics/reagent-orders/{order_id}", headers=headers)

    def list_reagent_orders(self, headers, params=None):
        return self._request("GET", "/genomics/reagent-orders", headers=headers, params=params)

    def advance_reagent_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/genomics/reagent-orders/{order_id}/advance", payload, headers
        )

    # ------------------------------------------------------------------
    # Service contracts
    # ------------------------------------------------------------------
    def create_service_contract(self, payload, headers):
        return self._request("POST", "/genomics/service-contracts", payload, headers)

    def get_service_contract(self, contract_id, headers):
        return self._request("GET", f"/genomics/service-contracts/{contract_id}", headers=headers)

    def list_service_contracts(self, headers, params=None):
        return self._request("GET", "/genomics/service-contracts", headers=headers, params=params)

    def activate_service_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST", f"/genomics/service-contracts/{contract_id}/activate",
            payload if payload is not None else {}, headers,
        )

    def post_uptime_reconciliation(self, contract_id, payload, headers):
        return self._request(
            "POST",
            f"/genomics/service-contracts/{contract_id}/uptime-reconciliations",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Software licenses
    # ------------------------------------------------------------------
    def create_software_license(self, payload, headers):
        return self._request("POST", "/genomics/software-licenses", payload, headers)

    def get_software_license(self, license_id, headers):
        return self._request("GET", f"/genomics/software-licenses/{license_id}", headers=headers)

    def list_software_licenses(self, headers, params=None):
        return self._request("GET", "/genomics/software-licenses", headers=headers, params=params)

    def set_license_status(self, license_id, payload, headers):
        return self._request(
            "POST", f"/genomics/software-licenses/{license_id}/status", payload, headers
        )

    def post_credit_grant(self, license_id, payload, headers):
        return self._request(
            "POST", f"/genomics/software-licenses/{license_id}/credit-grants", payload, headers
        )

    def close_billing_period(self, license_id, headers, payload=None):
        return self._request(
            "POST", f"/genomics/software-licenses/{license_id}/billing-close",
            payload if payload is not None else {}, headers,
        )

    # ------------------------------------------------------------------
    # Run records
    # ------------------------------------------------------------------
    def create_run_record(self, payload, headers):
        return self._request("POST", "/genomics/run-records", payload, headers)

    def get_run_record(self, run_id, headers):
        return self._request("GET", f"/genomics/run-records/{run_id}", headers=headers)

    def list_run_records(self, headers, params=None):
        return self._request("GET", "/genomics/run-records", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Transition programs
    # ------------------------------------------------------------------
    def create_transition_program(self, payload, headers):
        return self._request("POST", "/genomics/transition-programs", payload, headers)

    def get_transition_program(self, program_id, headers):
        return self._request(
            "GET", f"/genomics/transition-programs/{program_id}", headers=headers
        )

    def list_transition_programs(self, headers, params=None):
        return self._request(
            "GET", "/genomics/transition-programs", headers=headers, params=params
        )

    def advance_transition_program(self, program_id, payload, headers):
        return self._request(
            "POST", f"/genomics/transition-programs/{program_id}/advance", payload, headers
        )

    # ------------------------------------------------------------------
    # Supply forecasts
    # ------------------------------------------------------------------
    def create_supply_forecast(self, payload, headers):
        return self._request("POST", "/genomics/supply-forecasts", payload, headers)

    def get_supply_forecast(self, forecast_id, headers, params=None):
        return self._request(
            "GET", f"/genomics/supply-forecasts/{forecast_id}", headers=headers, params=params
        )

    def list_supply_forecasts(self, headers, params=None):
        return self._request("GET", "/genomics/supply-forecasts", headers=headers, params=params)

    def advance_supply_forecast(self, forecast_id, payload, headers):
        return self._request(
            "POST", f"/genomics/supply-forecasts/{forecast_id}/advance", payload, headers
        )

    # ------------------------------------------------------------------
    # Test-driving logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/genomics/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
