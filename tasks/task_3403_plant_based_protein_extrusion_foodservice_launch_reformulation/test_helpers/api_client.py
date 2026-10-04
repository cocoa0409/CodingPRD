"""API client: one method per endpoint defined in PRD section 4.

The base GenericApiClient reads the server URL from the API_BASE_URL
environment variable exported by the per-test-server runner; nothing here
hardcodes a host or port.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving capability) -----------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload,
                             headers)

    # --- Suppliers -----------------------------------------------------------
    def create_supplier(self, payload, headers):
        return self._request("POST", "/protein-ops/suppliers", payload,
                             headers)

    def list_suppliers(self, headers, params=None):
        return self._request("GET", "/protein-ops/suppliers", headers=headers,
                             params=params)

    def transition_supplier(self, supplier_id, payload, headers):
        return self._request(
            "POST", f"/protein-ops/suppliers/{supplier_id}/transitions",
            payload, headers)

    # --- Ingredient lots -----------------------------------------------------
    def create_ingredient_lot(self, payload, headers):
        return self._request("POST", "/protein-ops/ingredient-lots", payload,
                             headers)

    def list_ingredient_lots(self, headers, params=None):
        return self._request("GET", "/protein-ops/ingredient-lots",
                             headers=headers, params=params)

    def get_ingredient_lot(self, lot_id, headers):
        return self._request("GET", f"/protein-ops/ingredient-lots/{lot_id}",
                             headers=headers)

    def qc_decision(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/protein-ops/ingredient-lots/{lot_id}/qc-decision",
            payload, headers)

    # --- Production lines ----------------------------------------------------
    def create_production_line(self, payload, headers):
        return self._request("POST", "/protein-ops/production-lines", payload,
                             headers)

    def list_production_lines(self, headers, params=None):
        return self._request("GET", "/protein-ops/production-lines",
                             headers=headers, params=params)

    def line_operational_transition(self, line_id, payload, headers):
        return self._request(
            "POST",
            f"/protein-ops/production-lines/{line_id}/operational-transitions",
            payload, headers)

    def create_certification_audit(self, line_id, payload, headers):
        return self._request(
            "POST",
            f"/protein-ops/production-lines/{line_id}/certification-audits",
            payload, headers)

    # --- Products ------------------------------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", "/protein-ops/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/protein-ops/products", headers=headers,
                             params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/protein-ops/products/{product_id}",
                             headers=headers)

    def product_lifecycle_transition(self, product_id, payload, headers):
        return self._request(
            "POST",
            f"/protein-ops/products/{product_id}/lifecycle-transitions",
            payload, headers)

    # --- Label versions ------------------------------------------------------
    def create_label_version(self, product_id, payload, headers):
        return self._request(
            "POST", f"/protein-ops/products/{product_id}/label-versions",
            payload, headers)

    def list_label_versions(self, headers, params=None):
        return self._request("GET", "/protein-ops/label-versions",
                             headers=headers, params=params)

    def get_label_version(self, label_id, headers):
        return self._request("GET", f"/protein-ops/label-versions/{label_id}",
                             headers=headers)

    def label_version_transition(self, label_id, payload, headers):
        return self._request(
            "POST", f"/protein-ops/label-versions/{label_id}/transitions",
            payload, headers)

    # --- Production runs -----------------------------------------------------
    def create_production_run(self, payload, headers):
        return self._request("POST", "/protein-ops/production-runs", payload,
                             headers)

    def list_production_runs(self, headers, params=None):
        return self._request("GET", "/protein-ops/production-runs",
                             headers=headers, params=params)

    def get_production_run(self, run_id, headers):
        return self._request("GET", f"/protein-ops/production-runs/{run_id}",
                             headers=headers)

    def production_run_transition(self, run_id, payload, headers):
        return self._request(
            "POST", f"/protein-ops/production-runs/{run_id}/transitions",
            payload, headers)

    # --- Growth programs -----------------------------------------------------
    def create_program(self, payload, headers):
        return self._request("POST", "/protein-ops/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/protein-ops/programs", headers=headers,
                             params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/protein-ops/programs/{program_id}",
                             headers=headers)

    def program_lifecycle(self, program_id, payload, headers):
        return self._request(
            "POST", f"/protein-ops/programs/{program_id}/lifecycle", payload,
            headers)

    # --- Finished goods batches ----------------------------------------------
    def list_finished_goods_batches(self, headers, params=None):
        return self._request("GET", "/protein-ops/finished-goods-batches",
                             headers=headers, params=params)

    def get_finished_goods_batch(self, batch_id, headers):
        return self._request(
            "GET", f"/protein-ops/finished-goods-batches/{batch_id}",
            headers=headers)

    def reserve_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/protein-ops/finished-goods-batches/{batch_id}/reserve",
            payload, headers)

    # --- Demand forecasts ----------------------------------------------------
    def create_demand_forecast(self, payload, headers):
        return self._request("POST", "/protein-ops/demand-forecasts", payload,
                             headers)

    def list_demand_forecasts(self, headers, params=None):
        return self._request("GET", "/protein-ops/demand-forecasts",
                             headers=headers, params=params)

    def get_demand_forecast(self, forecast_id, headers):
        return self._request(
            "GET", f"/protein-ops/demand-forecasts/{forecast_id}",
            headers=headers)

    def demand_forecast_transition(self, forecast_id, payload, headers):
        return self._request(
            "POST", f"/protein-ops/demand-forecasts/{forecast_id}/transitions",
            payload, headers)

    # --- Inventory write-downs -----------------------------------------------
    def create_inventory_write_down(self, payload, headers):
        return self._request("POST", "/protein-ops/inventory-write-downs",
                             payload, headers)

    def list_inventory_write_downs(self, headers, params=None):
        return self._request("GET", "/protein-ops/inventory-write-downs",
                             headers=headers, params=params)

    def get_inventory_write_down(self, write_down_id, headers):
        return self._request(
            "GET", f"/protein-ops/inventory-write-downs/{write_down_id}",
            headers=headers)

    def decide_write_down(self, write_down_id, payload, headers):
        return self._request(
            "POST",
            f"/protein-ops/inventory-write-downs/{write_down_id}/decision",
            payload, headers)


api_client = ApiClient()
