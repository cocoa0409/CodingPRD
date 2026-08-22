"""API client: one method per endpoint defined in the PRD (§4)."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Wire & Cable Distribution API.

    Every collection is mounted at the root of the service.
    """

    # ── Branches ──────────────────────────────────────────────────────────
    def create_branch(self, payload, headers):
        return self._request("POST", "/branches", payload, headers)

    def get_branch(self, branch_id, headers):
        return self._request("GET", f"/branches/{branch_id}", headers=headers)

    # ── Trucks ────────────────────────────────────────────────────────────
    def create_truck(self, payload, headers):
        return self._request("POST", "/trucks", payload, headers)

    def get_truck(self, truck_id, headers):
        return self._request("GET", f"/trucks/{truck_id}", headers=headers)

    def list_trucks(self, headers, params=None):
        return self._request("GET", "/trucks", headers=headers, params=params)

    # ── Customers ─────────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def create_credit_adjustment(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/customers/{customer_id}/credit-adjustments", payload, headers
        )

    # ── Catalog parts ─────────────────────────────────────────────────────
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    # ── Copper index ──────────────────────────────────────────────────────
    def create_copper_index_entry(self, payload, headers):
        return self._request("POST", "/copper-index-entries", payload, headers)

    def get_copper_index_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/copper-index-entries/{entry_id}", headers=headers
        )

    def list_copper_index_entries(self, headers, params=None):
        return self._request(
            "GET", "/copper-index-entries", headers=headers, params=params
        )

    # ── Reels ─────────────────────────────────────────────────────────────
    def create_reel(self, payload, headers):
        return self._request("POST", "/reels", payload, headers)

    def get_reel(self, reel_id, headers):
        return self._request("GET", f"/reels/{reel_id}", headers=headers)

    def list_reels(self, headers, params=None):
        return self._request("GET", "/reels", headers=headers, params=params)

    # ── Quotes ────────────────────────────────────────────────────────────
    def create_quote(self, payload, headers):
        return self._request("POST", "/quotes", payload, headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def create_quote_line(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/lines", payload, headers)

    def get_quote_line(self, quote_line_id, headers):
        return self._request("GET", f"/quote-lines/{quote_line_id}", headers=headers)

    def list_quote_lines(self, headers, params=None):
        return self._request("GET", "/quote-lines", headers=headers, params=params)

    def issue_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/issue", None, headers)

    def reprice_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/reprice", None, headers)

    def convert_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/convert", None, headers)

    # ── Sales orders ──────────────────────────────────────────────────────
    def get_sales_order(self, order_id, headers):
        return self._request("GET", f"/sales-orders/{order_id}", headers=headers)

    def list_sales_orders(self, headers, params=None):
        return self._request("GET", "/sales-orders", headers=headers, params=params)

    def get_order_line(self, order_line_id, headers):
        return self._request("GET", f"/order-lines/{order_line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def allocate_sales_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/sales-orders/{order_id}/allocate", payload, headers
        )

    def release_allocations(self, order_id, headers):
        return self._request(
            "POST", f"/sales-orders/{order_id}/release-allocations", None, headers
        )

    # ── Allocations ───────────────────────────────────────────────────────
    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/allocations/{allocation_id}", headers=headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/allocations", headers=headers, params=params)

    def cut_allocation(self, allocation_id, payload, headers):
        return self._request(
            "POST", f"/allocations/{allocation_id}/cut", payload, headers
        )

    def pick_allocation(self, allocation_id, headers):
        return self._request(
            "POST", f"/allocations/{allocation_id}/pick", None, headers
        )

    # ── Delivery runs ─────────────────────────────────────────────────────
    def create_delivery_run(self, payload, headers):
        return self._request("POST", "/delivery-runs", payload, headers)

    def get_delivery_run(self, run_id, headers):
        return self._request("GET", f"/delivery-runs/{run_id}", headers=headers)

    def list_delivery_runs(self, headers, params=None):
        return self._request("GET", "/delivery-runs", headers=headers, params=params)

    def dispatch_delivery_run(self, run_id, headers):
        return self._request(
            "POST", f"/delivery-runs/{run_id}/dispatch", None, headers
        )

    def deliver_delivery_run(self, run_id, headers):
        return self._request("POST", f"/delivery-runs/{run_id}/deliver", None, headers)

    # ── Reel return ───────────────────────────────────────────────────────
    def return_order_line_reel(self, order_line_id, payload, headers):
        return self._request(
            "POST", f"/order-lines/{order_line_id}/return", payload, headers
        )

    # ── Logical clock ─────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Raw escape hatch (used for header-less authentication tests) ──────
    def raw_get(self, path, headers=None, params=None):
        return self._request("GET", path, headers=headers, params=params)


api_client = ApiClient()
