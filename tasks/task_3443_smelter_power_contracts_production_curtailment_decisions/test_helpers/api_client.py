"""API client: one method per endpoint defined in the PRD (§4).

The logical-clock capability is mounted outside the /smelter-ops business
surface (PRD §2.4); every business endpoint sits under /smelter-ops.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/smelter-ops"


class ApiClient(GenericApiClient):
    # --- Logical clock (unprefixed, PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Smelters ---
    def create_smelter(self, payload, headers):
        return self._request("POST", f"{PREFIX}/smelters", payload, headers)

    def get_smelter(self, smelter_id, headers):
        return self._request("GET", f"{PREFIX}/smelters/{smelter_id}", headers=headers)

    # --- Potlines ---
    def create_potline(self, payload, headers):
        return self._request("POST", f"{PREFIX}/potlines", payload, headers)

    def get_potline(self, potline_id, headers):
        return self._request("GET", f"{PREFIX}/potlines/{potline_id}", headers=headers)

    def curtail_potline(self, potline_id, payload, headers):
        return self._request("POST", f"{PREFIX}/potlines/{potline_id}/curtail", payload, headers)

    def shutdown_potline(self, potline_id, headers):
        return self._request("POST", f"{PREFIX}/potlines/{potline_id}/shutdown", {}, headers)

    # --- Power contracts ---
    def create_power_contract(self, payload, headers):
        return self._request("POST", f"{PREFIX}/power-contracts", payload, headers)

    def get_power_contract(self, contract_id, headers):
        return self._request("GET", f"{PREFIX}/power-contracts/{contract_id}", headers=headers)

    def activate_power_contract(self, contract_id, headers):
        return self._request("POST", f"{PREFIX}/power-contracts/{contract_id}/activate", {}, headers)

    # --- Interrupt events ---
    def create_interrupt_event(self, payload, headers):
        return self._request("POST", f"{PREFIX}/interrupt-events", payload, headers)

    # --- Price observations ---
    def create_price_observation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/price-observations", payload, headers)

    # --- Hedge positions ---
    def create_hedge_position(self, payload, headers):
        return self._request("POST", f"{PREFIX}/hedge-positions", payload, headers)

    def close_hedge_position(self, hedge_id, payload, headers):
        return self._request("POST", f"{PREFIX}/hedge-positions/{hedge_id}/close", payload, headers)

    # --- Alumina supply agreements ---
    def create_alumina_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/alumina-agreements", payload, headers)

    # --- Curtailment decisions ---
    def create_curtailment_decision(self, payload, headers):
        return self._request("POST", f"{PREFIX}/curtailment-decisions", payload, headers)

    def economic_approve_decision(self, decision_id, headers):
        return self._request(
            "POST", f"{PREFIX}/curtailment-decisions/{decision_id}/economic-approve", {}, headers
        )

    def labor_approve_decision(self, decision_id, headers):
        return self._request(
            "POST", f"{PREFIX}/curtailment-decisions/{decision_id}/labor-approve", {}, headers
        )

    def reject_decision(self, decision_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/curtailment-decisions/{decision_id}/reject", payload, headers
        )

    def revise_decision(self, decision_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/curtailment-decisions/{decision_id}/revise", payload, headers
        )

    def execute_decision(self, decision_id, headers):
        return self._request(
            "POST", f"{PREFIX}/curtailment-decisions/{decision_id}/execute", {}, headers
        )

    def reverse_decision(self, decision_id, headers):
        return self._request(
            "POST", f"{PREFIX}/curtailment-decisions/{decision_id}/reverse", {}, headers
        )

    # --- Restart plans ---
    def create_restart_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/restart-plans", payload, headers)

    def start_restart_plan(self, plan_id, headers):
        return self._request("POST", f"{PREFIX}/restart-plans/{plan_id}/start", {}, headers)

    def complete_restart_plan(self, plan_id, headers):
        return self._request("POST", f"{PREFIX}/restart-plans/{plan_id}/complete", {}, headers)

    # --- Environmental permits ---
    def create_environmental_permit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/environmental-permits", payload, headers)

    def suspend_environmental_permit(self, permit_id, headers):
        return self._request(
            "POST", f"{PREFIX}/environmental-permits/{permit_id}/suspend", {}, headers
        )

    # --- Labor agreements ---
    def create_labor_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/labor-agreements", payload, headers)

    def expire_labor_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/labor-agreements/{agreement_id}/expire", {}, headers
        )

    # --- Production plans ---
    def create_production_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/production-plans", payload, headers)

    # --- List endpoints ---
    def list_potlines(self, smelter_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/smelters/{smelter_id}/potlines", headers=headers, params=params
        )

    def list_power_contracts(self, smelter_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/smelters/{smelter_id}/power-contracts", headers=headers, params=params
        )

    def list_hedge_positions(self, smelter_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/smelters/{smelter_id}/hedge-positions", headers=headers, params=params
        )

    def list_alumina_agreements(self, smelter_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/smelters/{smelter_id}/alumina-agreements", headers=headers, params=params
        )

    def list_environmental_permits(self, smelter_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/smelters/{smelter_id}/environmental-permits", headers=headers, params=params
        )

    def list_labor_agreements(self, smelter_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/smelters/{smelter_id}/labor-agreements", headers=headers, params=params
        )

    def list_production_plans(self, smelter_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/smelters/{smelter_id}/production-plans", headers=headers, params=params
        )

    def list_curtailment_decisions(self, potline_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/potlines/{potline_id}/curtailment-decisions", headers=headers, params=params
        )

    def list_restart_plans(self, potline_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/potlines/{potline_id}/restart-plans", headers=headers, params=params
        )

    def list_interrupt_events(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/power-contracts/{contract_id}/interrupt-events", headers=headers, params=params
        )


api_client = ApiClient()
