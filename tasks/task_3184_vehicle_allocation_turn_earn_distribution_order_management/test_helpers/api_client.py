"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- test-driving hooks ---------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/wholesale/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def seed_order_at_week(self, payload, headers):
        return self._request("POST", "/wholesale/_seed/order-at-week", payload, headers)

    # ---- regions ----------------------------------------------------------
    def create_region(self, payload, headers):
        return self._request("POST", "/wholesale/regions", payload, headers)

    def list_regions(self, headers, params=None):
        return self._request("GET", "/wholesale/regions", headers=headers, params=params)

    def get_region(self, region_id, headers):
        return self._request("GET", f"/wholesale/regions/{region_id}", headers=headers)

    # ---- dealers ----------------------------------------------------------
    def create_dealer(self, payload, headers):
        return self._request("POST", "/wholesale/dealers", payload, headers)

    def list_dealers(self, headers, params=None):
        return self._request("GET", "/wholesale/dealers", headers=headers, params=params)

    def get_dealer(self, dealer_id, headers):
        return self._request("GET", f"/wholesale/dealers/{dealer_id}", headers=headers)

    def list_dealer_model_lines_for_dealer(self, dealer_id, headers, params=None):
        return self._request(
            "GET", f"/wholesale/dealers/{dealer_id}/model-lines", headers=headers, params=params
        )

    # ---- model lines ------------------------------------------------------
    def create_model_line(self, payload, headers):
        return self._request("POST", "/wholesale/model-lines", payload, headers)

    def list_model_lines(self, headers, params=None):
        return self._request("GET", "/wholesale/model-lines", headers=headers, params=params)

    def get_model_line(self, model_line_id, headers):
        return self._request("GET", f"/wholesale/model-lines/{model_line_id}", headers=headers)

    # ---- commodities ------------------------------------------------------
    def create_commodity(self, payload, headers):
        return self._request("POST", "/wholesale/commodities", payload, headers)

    def list_commodities(self, headers, params=None):
        return self._request("GET", "/wholesale/commodities", headers=headers, params=params)

    def resolve_commodity(self, commodity_id, headers):
        return self._request("POST", f"/wholesale/commodities/{commodity_id}/resolve", {}, headers)

    def constrain_commodity(self, commodity_id, headers):
        return self._request("POST", f"/wholesale/commodities/{commodity_id}/constrain", {}, headers)

    # ---- commodity restrictions -------------------------------------------
    def create_commodity_restriction(self, payload, headers):
        return self._request("POST", "/wholesale/commodity-restrictions", payload, headers)

    def list_commodity_restrictions(self, headers, params=None):
        return self._request(
            "GET", "/wholesale/commodity-restrictions", headers=headers, params=params
        )

    def get_commodity_restriction(self, restriction_id, headers):
        return self._request(
            "GET", f"/wholesale/commodity-restrictions/{restriction_id}", headers=headers
        )

    # ---- dealer-model-line aggregates --------------------------------------
    def list_dealer_model_lines(self, headers, params=None):
        return self._request("GET", "/wholesale/dealer-model-lines", headers=headers, params=params)

    def get_dealer_model_line(self, dml_id, headers):
        return self._request("GET", f"/wholesale/dealer-model-lines/{dml_id}", headers=headers)

    # ---- allocation runs ---------------------------------------------------
    def create_allocation_run(self, payload, headers):
        return self._request("POST", "/wholesale/allocation-runs", payload, headers)

    def list_allocation_runs(self, headers, params=None):
        return self._request("GET", "/wholesale/allocation-runs", headers=headers, params=params)

    def get_allocation_run(self, run_id, headers):
        return self._request("GET", f"/wholesale/allocation-runs/{run_id}", headers=headers)

    def publish_allocation_run(self, run_id, headers):
        return self._request("POST", f"/wholesale/allocation-runs/{run_id}/publish", {}, headers)

    def lock_allocation_run(self, run_id, headers):
        return self._request("POST", f"/wholesale/allocation-runs/{run_id}/lock", {}, headers)

    def list_run_dealer_allocations(self, run_id, headers, params=None):
        return self._request(
            "GET",
            f"/wholesale/allocation-runs/{run_id}/dealer-allocations",
            headers=headers,
            params=params,
        )

    def list_dealer_allocations(self, headers, params=None):
        return self._request(
            "GET", "/wholesale/dealer-allocations", headers=headers, params=params
        )

    def get_dealer_allocation(self, da_id, headers):
        return self._request("GET", f"/wholesale/dealer-allocations/{da_id}", headers=headers)

    def lock_dealer_allocation(self, run_id, da_id, headers):
        return self._request(
            "POST",
            f"/wholesale/allocation-runs/{run_id}/dealer-allocations/{da_id}/lock",
            {},
            headers,
        )

    # ---- orders ------------------------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", "/wholesale/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/wholesale/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/wholesale/orders/{order_id}", headers=headers)

    def cancel_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/wholesale/orders/{order_id}/cancel", payload or {}, headers
        )

    def schedule_order(self, order_id, payload, headers):
        return self._request("POST", f"/wholesale/orders/{order_id}/schedule", payload, headers)

    def build_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/wholesale/orders/{order_id}/build", payload or {}, headers
        )

    def retrofit_order(self, order_id, headers):
        return self._request("POST", f"/wholesale/orders/{order_id}/retrofit", {}, headers)

    # ---- dealer trades ------------------------------------------------------
    def create_dealer_trade(self, payload, headers):
        return self._request("POST", "/wholesale/dealer-trades", payload, headers)

    def list_dealer_trades(self, headers, params=None):
        return self._request("GET", "/wholesale/dealer-trades", headers=headers, params=params)

    def get_dealer_trade(self, trade_id, headers):
        return self._request("GET", f"/wholesale/dealer-trades/{trade_id}", headers=headers)

    def counter_dealer_trade(self, trade_id, payload, headers):
        return self._request(
            "POST", f"/wholesale/dealer-trades/{trade_id}/counter", payload, headers
        )

    def accept_dealer_trade(self, trade_id, headers):
        return self._request(
            "POST", f"/wholesale/dealer-trades/{trade_id}/accept", {}, headers
        )

    def decline_dealer_trade(self, trade_id, headers):
        return self._request(
            "POST", f"/wholesale/dealer-trades/{trade_id}/decline", {}, headers
        )

    def cancel_dealer_trade(self, trade_id, headers):
        return self._request(
            "POST", f"/wholesale/dealer-trades/{trade_id}/cancel", {}, headers
        )

    def execute_dealer_trade(self, trade_id, payload, headers):
        return self._request(
            "POST", f"/wholesale/dealer-trades/{trade_id}/execute", payload, headers
        )

    # ---- appeals -------------------------------------------------------------
    def create_appeal(self, payload, headers):
        return self._request("POST", "/wholesale/appeals", payload, headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/wholesale/appeals", headers=headers, params=params)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/wholesale/appeals/{appeal_id}", headers=headers)

    def review_appeal(self, appeal_id, headers):
        return self._request("POST", f"/wholesale/appeals/{appeal_id}/review", {}, headers)

    def grant_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/wholesale/appeals/{appeal_id}/grant", payload, headers)

    def deny_appeal(self, appeal_id, headers):
        return self._request("POST", f"/wholesale/appeals/{appeal_id}/deny", {}, headers)

    def withdraw_appeal(self, appeal_id, headers):
        return self._request("POST", f"/wholesale/appeals/{appeal_id}/withdraw", {}, headers)

    # ---- incentive programs ---------------------------------------------------
    def create_incentive_program(self, payload, headers):
        return self._request("POST", "/wholesale/incentive-programs", payload, headers)

    def list_incentive_programs(self, headers, params=None):
        return self._request(
            "GET", "/wholesale/incentive-programs", headers=headers, params=params
        )

    def get_incentive_program(self, program_id, headers):
        return self._request(
            "GET", f"/wholesale/incentive-programs/{program_id}", headers=headers
        )

    def close_incentive_program(self, program_id, headers):
        return self._request(
            "POST", f"/wholesale/incentive-programs/{program_id}/close", {}, headers
        )

    def list_program_accruals(self, program_id, headers, params=None):
        return self._request(
            "GET",
            f"/wholesale/incentive-programs/{program_id}/accruals",
            headers=headers,
            params=params,
        )

    # ---- carriers & shipments -------------------------------------------------
    def create_carrier(self, payload, headers):
        return self._request("POST", "/wholesale/carriers", payload, headers)

    def list_carriers(self, headers, params=None):
        return self._request("GET", "/wholesale/carriers", headers=headers, params=params)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/wholesale/carriers/{carrier_id}", headers=headers)

    def create_shipment(self, payload, headers):
        return self._request("POST", "/wholesale/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/wholesale/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/wholesale/shipments/{shipment_id}", headers=headers)

    def pickup_shipment(self, shipment_id, headers):
        return self._request("POST", f"/wholesale/shipments/{shipment_id}/pickup", {}, headers)

    def deliver_shipment(self, shipment_id, headers):
        return self._request("POST", f"/wholesale/shipments/{shipment_id}/deliver", {}, headers)

    def cancel_shipment(self, shipment_id, headers):
        return self._request("POST", f"/wholesale/shipments/{shipment_id}/cancel", {}, headers)


api_client = ApiClient()
