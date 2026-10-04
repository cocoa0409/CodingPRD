"""API client: one method per endpoint defined in the PRD (§4).

Base URL comes from the API_BASE_URL env var via GenericApiClient; the runner
injects it. All methods return the raw requests.Response so callers can assert
status codes; envelope handling lives in the framework validators.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock (PRD §2.4) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/foundry/_clock/set_current_utc", payload, headers)

    # ---- products (PRD §3.1) ----
    def create_product(self, payload, headers):
        return self._request("POST", "/foundry/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/foundry/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/foundry/products/{product_id}", headers=headers)

    def discontinue_product(self, product_id, headers):
        return self._request("POST", f"/foundry/products/{product_id}/discontinue", {}, headers)

    def list_product_outlet_sales(self, product_id, headers, params=None):
        return self._request("GET", f"/foundry/products/{product_id}/outlet-sales",
                             headers=headers, params=params)

    # ---- production orders (PRD §3.2) ----
    def create_production_order(self, payload, headers):
        return self._request("POST", "/foundry/production-orders", payload, headers)

    def list_production_orders(self, headers, params=None):
        return self._request("GET", "/foundry/production-orders", headers=headers, params=params)

    def get_production_order(self, order_id, headers):
        return self._request("GET", f"/foundry/production-orders/{order_id}", headers=headers)

    def release_production_order(self, order_id, headers):
        return self._request("POST", f"/foundry/production-orders/{order_id}/release", {}, headers)

    def complete_production_order(self, order_id, payload, headers):
        return self._request("POST", f"/foundry/production-orders/{order_id}/complete",
                             payload, headers)

    def cancel_production_order(self, order_id, headers):
        return self._request("POST", f"/foundry/production-orders/{order_id}/cancel", {}, headers)

    def list_order_molds(self, order_id, headers, params=None):
        return self._request("GET", f"/foundry/production-orders/{order_id}/molds",
                             headers=headers, params=params)

    # ---- melt batches (PRD §3.3) ----
    def create_melt_batch(self, payload, headers):
        return self._request("POST", "/foundry/melt-batches", payload, headers)

    def list_melt_batches(self, headers, params=None):
        return self._request("GET", "/foundry/melt-batches", headers=headers, params=params)

    def get_melt_batch(self, batch_id, headers):
        return self._request("GET", f"/foundry/melt-batches/{batch_id}", headers=headers)

    def charge_melt_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/foundry/melt-batches/{batch_id}/charge", payload, headers)

    def record_chemistry_readings(self, batch_id, payload, headers):
        return self._request("POST", f"/foundry/melt-batches/{batch_id}/chemistry-readings",
                             payload, headers)

    def certify_chemistry(self, batch_id, payload, headers):
        return self._request("POST", f"/foundry/melt-batches/{batch_id}/certify-chemistry",
                             payload, headers)

    def tap_melt_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/foundry/melt-batches/{batch_id}/tap", payload, headers)

    def pour_melt_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/foundry/melt-batches/{batch_id}/pour", payload, headers)

    # ---- molds (PRD §3.4) ----
    def create_mold(self, payload, headers):
        return self._request("POST", "/foundry/molds", payload, headers)

    def shakeout_mold(self, mold_id, headers):
        return self._request("POST", f"/foundry/molds/{mold_id}/shakeout", {}, headers)

    def reclaim_mold(self, mold_id, payload, headers):
        return self._request("POST", f"/foundry/molds/{mold_id}/reclaim", payload, headers)

    # ---- casting units (PRD §3.5) ----
    def list_casting_units(self, headers, params=None):
        return self._request("GET", "/foundry/casting-units", headers=headers, params=params)

    def get_casting_unit(self, unit_id, headers):
        return self._request("GET", f"/foundry/casting-units/{unit_id}", headers=headers)

    def inspect_casting_unit(self, unit_id, payload, headers):
        return self._request("POST", f"/foundry/casting-units/{unit_id}/inspect", payload, headers)

    def complete_rework(self, unit_id, headers):
        return self._request("POST", f"/foundry/casting-units/{unit_id}/complete-rework",
                             {}, headers)

    def list_unit_defect_reports(self, unit_id, headers, params=None):
        return self._request("GET", f"/foundry/casting-units/{unit_id}/defect-reports",
                             headers=headers, params=params)

    # ---- defect reports (PRD §3.5) ----
    def list_defect_reports(self, headers, params=None):
        return self._request("GET", "/foundry/defect-reports", headers=headers, params=params)

    def disposition_defect_report(self, report_id, payload, headers):
        return self._request("POST", f"/foundry/defect-reports/{report_id}/disposition",
                             payload, headers)

    # ---- seasoning batches (PRD §3.6) ----
    def create_seasoning_batch(self, payload, headers):
        return self._request("POST", "/foundry/seasoning-batches", payload, headers)

    def list_seasoning_batches(self, headers, params=None):
        return self._request("GET", "/foundry/seasoning-batches", headers=headers, params=params)

    def get_seasoning_batch(self, batch_id, headers):
        return self._request("GET", f"/foundry/seasoning-batches/{batch_id}", headers=headers)

    def start_bake(self, batch_id, payload, headers):
        return self._request("POST", f"/foundry/seasoning-batches/{batch_id}/start-bake",
                             payload, headers)

    def qa_release_seasoning_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/foundry/seasoning-batches/{batch_id}/qa-release",
                             payload, headers)

    # ---- environmental permits (PRD §3.7) ----
    def create_environmental_permit(self, payload, headers):
        return self._request("POST", "/foundry/environmental-permits", payload, headers)

    def list_environmental_permits(self, headers, params=None):
        return self._request("GET", "/foundry/environmental-permits",
                             headers=headers, params=params)

    def get_environmental_permit(self, permit_id, headers):
        return self._request("GET", f"/foundry/environmental-permits/{permit_id}",
                             headers=headers)

    def record_emissions_reading(self, permit_id, payload, headers):
        return self._request("POST", f"/foundry/environmental-permits/{permit_id}/readings",
                             payload, headers)

    def list_emissions_readings(self, permit_id, headers, params=None):
        return self._request("GET", f"/foundry/environmental-permits/{permit_id}/readings",
                             headers=headers, params=params)

    def acknowledge_breach(self, permit_id, headers):
        return self._request("POST",
                             f"/foundry/environmental-permits/{permit_id}/acknowledge-breach",
                             {}, headers)

    def certify_remediation(self, permit_id, headers):
        return self._request("POST",
                             f"/foundry/environmental-permits/{permit_id}/certify-remediation",
                             {}, headers)

    # ---- inventory records (PRD §3.8) ----
    def list_inventory_records(self, headers, params=None):
        return self._request("GET", "/foundry/inventory-records", headers=headers, params=params)

    def get_inventory_record(self, record_id, headers):
        return self._request("GET", f"/foundry/inventory-records/{record_id}", headers=headers)

    def get_allocation_plan(self, record_id, build_qty, headers):
        return self._request("GET",
                             f"/foundry/inventory-records/{record_id}/allocation-plan",
                             headers=headers, params={"build_qty": build_qty})

    # ---- retail allocations (PRD §3.8) ----
    def create_retail_allocation(self, payload, headers):
        return self._request("POST", "/foundry/retail-allocations", payload, headers)

    def list_retail_allocations(self, headers, params=None):
        return self._request("GET", "/foundry/retail-allocations", headers=headers, params=params)

    def get_retail_allocation(self, allocation_id, headers):
        return self._request("GET", f"/foundry/retail-allocations/{allocation_id}",
                             headers=headers)

    def confirm_retail_allocation(self, allocation_id, headers):
        return self._request("POST", f"/foundry/retail-allocations/{allocation_id}/confirm",
                             {}, headers)

    def cancel_retail_allocation(self, allocation_id, headers):
        return self._request("POST", f"/foundry/retail-allocations/{allocation_id}/cancel",
                             {}, headers)

    def ship_retail_allocation(self, allocation_id, headers):
        return self._request("POST", f"/foundry/retail-allocations/{allocation_id}/ship",
                             {}, headers)

    # ---- outlet sales (PRD §3.8) ----
    def create_outlet_sale(self, payload, headers):
        return self._request("POST", "/foundry/outlet-sales", payload, headers)


api_client = ApiClient()
