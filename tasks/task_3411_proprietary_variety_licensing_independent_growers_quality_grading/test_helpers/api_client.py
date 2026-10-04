"""API client: one method per endpoint defined in the PRD (41 total)."""
from prd_bench_local_runner.testing import GenericApiClient

LIC = "/licensing"


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Variety ---
    def create_variety(self, payload, headers):
        return self._request("POST", f"{LIC}/varieties", payload, headers)

    def get_variety(self, variety_id, headers):
        return self._request("GET", f"{LIC}/varieties/{variety_id}", headers=headers)

    def release_variety(self, variety_id, headers, payload=None):
        return self._request("POST", f"{LIC}/varieties/{variety_id}/release",
                             payload if payload is not None else {}, headers)

    def recall_variety(self, variety_id, payload, headers):
        return self._request("POST", f"{LIC}/varieties/{variety_id}/recall",
                             payload, headers)

    def list_recall_orders(self, variety_id, headers, params=None):
        return self._request("GET", f"{LIC}/varieties/{variety_id}/recall-orders",
                             headers=headers, params=params)

    # --- Grower ---
    def create_grower(self, payload, headers):
        return self._request("POST", f"{LIC}/growers", payload, headers)

    def suspend_grower(self, grower_id, headers, payload=None):
        return self._request("POST", f"{LIC}/growers/{grower_id}/suspend",
                             payload if payload is not None else {}, headers)

    def exit_grower(self, grower_id, headers):
        return self._request("POST", f"{LIC}/growers/{grower_id}/exit", {}, headers)

    # --- GrowerAgreement ---
    def create_agreement(self, payload, headers):
        return self._request("POST", f"{LIC}/agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"{LIC}/agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", f"{LIC}/agreements", headers=headers, params=params)

    def decide_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"{LIC}/agreements/{agreement_id}/decide",
                             payload, headers)

    # --- PlantLot ---
    def create_plant_lot(self, payload, headers):
        return self._request("POST", f"{LIC}/plant-lots", payload, headers)

    def get_plant_lot(self, plant_lot_id, headers):
        return self._request("GET", f"{LIC}/plant-lots/{plant_lot_id}", headers=headers)

    def list_plant_lots(self, headers, params=None):
        return self._request("GET", f"{LIC}/plant-lots", headers=headers, params=params)

    # --- Planting ---
    def create_planting(self, payload, headers):
        return self._request("POST", f"{LIC}/plantings", payload, headers)

    def get_planting(self, planting_id, headers):
        return self._request("GET", f"{LIC}/plantings/{planting_id}", headers=headers)

    def list_plantings(self, headers, params=None):
        return self._request("GET", f"{LIC}/plantings", headers=headers, params=params)

    def confirm_planting(self, planting_id, payload, headers):
        return self._request("POST", f"{LIC}/plantings/{planting_id}/confirm",
                             payload, headers)

    def complete_planting(self, planting_id, headers):
        return self._request("POST", f"{LIC}/plantings/{planting_id}/complete",
                             {}, headers)

    # --- HarvestWindow ---
    def create_harvest_window(self, payload, headers):
        return self._request("POST", f"{LIC}/harvest-windows", payload, headers)

    def get_harvest_window(self, harvest_window_id, headers):
        return self._request("GET", f"{LIC}/harvest-windows/{harvest_window_id}",
                             headers=headers)

    def list_harvest_windows(self, headers, params=None):
        return self._request("GET", f"{LIC}/harvest-windows", headers=headers,
                             params=params)

    # --- HarvestLot ---
    def create_harvest_lot(self, payload, headers):
        return self._request("POST", f"{LIC}/harvest-lots", payload, headers)

    def get_harvest_lot(self, harvest_lot_id, headers):
        return self._request("GET", f"{LIC}/harvest-lots/{harvest_lot_id}",
                             headers=headers)

    def list_harvest_lots(self, headers, params=None):
        return self._request("GET", f"{LIC}/harvest-lots", headers=headers,
                             params=params)

    def receive_harvest_lot(self, harvest_lot_id, payload, headers):
        return self._request("POST", f"{LIC}/harvest-lots/{harvest_lot_id}/receive",
                             payload, headers)

    def grade_harvest_lot(self, harvest_lot_id, payload, headers):
        return self._request("POST", f"{LIC}/harvest-lots/{harvest_lot_id}/grade",
                             payload, headers)

    def certify_grade(self, harvest_lot_id, headers):
        return self._request("POST", f"{LIC}/harvest-lots/{harvest_lot_id}/certify-grade",
                             {}, headers)

    def dispute_grade(self, harvest_lot_id, payload, headers):
        return self._request("POST", f"{LIC}/harvest-lots/{harvest_lot_id}/dispute-grade",
                             payload, headers)

    # --- PoolPeriod ---
    def create_pool_period(self, payload, headers):
        return self._request("POST", f"{LIC}/pool-periods", payload, headers)

    def get_pool_period(self, pool_period_id, headers):
        return self._request("GET", f"{LIC}/pool-periods/{pool_period_id}",
                             headers=headers)

    def close_pool_period(self, pool_period_id, payload, headers):
        return self._request("POST", f"{LIC}/pool-periods/{pool_period_id}/close",
                             payload, headers)

    def settle_pool_period(self, pool_period_id, payload, headers):
        return self._request("POST", f"{LIC}/pool-periods/{pool_period_id}/settle",
                             payload, headers)

    # --- SettlementStatement ---
    def get_settlement_statement(self, settlement_statement_id, headers):
        return self._request(
            "GET", f"{LIC}/settlement-statements/{settlement_statement_id}",
            headers=headers)

    def list_settlement_statements(self, headers, params=None):
        return self._request("GET", f"{LIC}/settlement-statements", headers=headers,
                             params=params)

    def dispute_statement(self, settlement_statement_id, payload, headers):
        return self._request(
            "POST", f"{LIC}/settlement-statements/{settlement_statement_id}/dispute",
            payload, headers)

    def resolve_statement(self, settlement_statement_id, payload, headers):
        return self._request(
            "POST", f"{LIC}/settlement-statements/{settlement_statement_id}/resolve",
            payload, headers)

    def pay_statement(self, settlement_statement_id, headers):
        return self._request(
            "POST", f"{LIC}/settlement-statements/{settlement_statement_id}/pay",
            {}, headers)

    # --- RecallOrder ---
    def enforce_recall_order(self, recall_order_id, headers):
        return self._request("POST",
                             f"{LIC}/recall-orders/{recall_order_id}/enforce",
                             {}, headers)


api_client = ApiClient()
