"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- capacity weeks ---
    def create_capacity_week(self, payload, headers):
        return self._request("POST", "/capacity-weeks", payload, headers)

    def allocate_capacity_week(self, capacity_week_id, payload, headers):
        return self._request(
            "POST", f"/capacity-weeks/{capacity_week_id}/allocate", payload, headers
        )

    def close_capacity_week(self, capacity_week_id, headers):
        return self._request(
            "POST", f"/capacity-weeks/{capacity_week_id}/close", {}, headers
        )

    # --- products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    # --- price index entries ---
    def create_price_index_entry(self, payload, headers):
        return self._request("POST", "/price-index-entries", payload, headers)

    # --- branches ---
    def create_branch(self, payload, headers):
        return self._request("POST", "/branches", payload, headers)

    def get_branch_valuation(self, branch_id, headers):
        return self._request("GET", f"/branches/{branch_id}/valuation", headers=headers)

    def receive_inventory_lot(self, branch_id, payload, headers):
        return self._request(
            "POST", f"/branches/{branch_id}/inventory-lots", payload, headers
        )

    # --- inventory lots ---
    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/inventory-lots/{lot_id}", headers=headers)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/inventory-lots", headers=headers, params=params)

    # --- builders ---
    def create_builder(self, payload, headers):
        return self._request("POST", "/builders", payload, headers)

    def get_builder(self, builder_id, headers):
        return self._request("GET", f"/builders/{builder_id}", headers=headers)

    def credit_review(self, builder_id, payload, headers):
        return self._request(
            "POST", f"/builders/{builder_id}/credit-review", payload, headers
        )

    def get_builder_exposure(self, builder_id, headers):
        return self._request("GET", f"/builders/{builder_id}/exposure", headers=headers)

    # --- jobs ---
    def create_job(self, builder_id, payload, headers):
        return self._request("POST", f"/builders/{builder_id}/jobs", payload, headers)

    def get_job(self, job_id, headers):
        return self._request("GET", f"/jobs/{job_id}", headers=headers)

    def list_builder_jobs(self, builder_id, headers, params=None):
        return self._request(
            "GET", f"/builders/{builder_id}/jobs", headers=headers, params=params
        )

    # --- takeoff requests ---
    def create_takeoff_request(self, job_id, payload, headers):
        return self._request(
            "POST", f"/jobs/{job_id}/takeoff-requests", payload, headers
        )

    def get_takeoff_request(self, takeoff_id, headers):
        return self._request("GET", f"/takeoff-requests/{takeoff_id}", headers=headers)

    def submit_design(self, takeoff_id, payload, headers):
        return self._request(
            "POST", f"/takeoff-requests/{takeoff_id}/submit-design", payload, headers
        )

    def revise_takeoff(self, takeoff_id, payload, headers):
        return self._request(
            "POST", f"/takeoff-requests/{takeoff_id}/revise", payload, headers
        )

    def accept_takeoff(self, takeoff_id, payload, headers):
        return self._request(
            "POST", f"/takeoff-requests/{takeoff_id}/accept", payload, headers
        )

    def list_job_takeoff_requests(self, job_id, headers, params=None):
        return self._request(
            "GET", f"/jobs/{job_id}/takeoff-requests", headers=headers, params=params
        )

    # --- sales orders ---
    def create_sales_order(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/sales-orders", payload, headers)

    def get_sales_order(self, order_id, headers):
        return self._request("GET", f"/sales-orders/{order_id}", headers=headers)

    def list_sales_orders(self, headers, params=None):
        return self._request("GET", "/sales-orders", headers=headers, params=params)

    def confirm_sales_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/confirm", {}, headers)

    def cancel_sales_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/cancel", {}, headers)

    def create_delivery(self, order_id, payload, headers):
        return self._request(
            "POST", f"/sales-orders/{order_id}/deliveries", payload, headers
        )

    # --- deliveries ---
    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"/deliveries/{delivery_id}", headers=headers)

    def list_deliveries(self, headers, params=None):
        return self._request("GET", "/deliveries", headers=headers, params=params)

    def schedule_delivery(self, delivery_id, payload, headers):
        return self._request(
            "POST", f"/deliveries/{delivery_id}/schedule", payload, headers
        )

    def complete_delivery(self, delivery_id, payload, headers):
        return self._request(
            "POST", f"/deliveries/{delivery_id}/complete", payload, headers
        )

    # --- truck shifts ---
    def create_truck_shift(self, payload, headers):
        return self._request("POST", "/truck-shifts", payload, headers)

    def get_truck_shift(self, shift_id, headers):
        return self._request("GET", f"/truck-shifts/{shift_id}", headers=headers)

    # --- lien filings ---
    def create_lien_filing(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/lien-filings", {}, headers)

    def release_lien_filing(self, lien_id, headers):
        return self._request("POST", f"/lien-filings/{lien_id}/release", {}, headers)

    def list_job_lien_filings(self, job_id, headers, params=None):
        return self._request(
            "GET", f"/jobs/{job_id}/lien-filings", headers=headers, params=params
        )


api_client = ApiClient()
