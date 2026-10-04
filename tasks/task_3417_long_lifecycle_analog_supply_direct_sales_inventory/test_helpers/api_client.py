"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Parts & inventory ---
    def create_part(self, payload, headers):
        return self._request("POST", "/parts", payload, headers)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/parts/{part_id}", headers=headers)

    def patch_part(self, part_id, payload, headers):
        return self._request("PATCH", f"/parts/{part_id}", payload, headers)

    def get_inventory_position(self, part_id, headers):
        return self._request(
            "GET", f"/parts/{part_id}/inventory-position", headers=headers
        )

    def list_part_pricing_schedules(self, part_id, headers, params=None):
        return self._request(
            "GET", f"/parts/{part_id}/pricing-schedules", headers=headers, params=params
        )

    def list_part_eol_notices(self, part_id, headers, params=None):
        return self._request(
            "GET", f"/parts/{part_id}/eol-notices", headers=headers, params=params
        )

    def create_receipt(self, part_id, payload, headers):
        return self._request("POST", f"/parts/{part_id}/receipts", payload, headers)

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def patch_customer(self, customer_id, payload, headers):
        return self._request("PATCH", f"/customers/{customer_id}", payload, headers)

    # --- Published pricing ---
    def create_pricing_schedule(self, payload, headers):
        return self._request("POST", "/pricing-schedules", payload, headers)

    def quote_price(self, payload, headers):
        return self._request("POST", "/pricing/quote", payload, headers)

    # --- Orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/submit", {}, headers)

    def ship_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/ship", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    # --- Capacity ---
    def create_capacity_pool(self, payload, headers):
        return self._request("POST", "/capacity-pools", payload, headers)

    def invest_capacity_pool(self, pool_id, payload, headers):
        return self._request("PATCH", f"/capacity-pools/{pool_id}", payload, headers)

    def get_capacity_pool(self, pool_id, headers):
        return self._request("GET", f"/capacity-pools/{pool_id}", headers=headers)

    # --- Shortage allocation ---
    def create_allocation_run(self, payload, headers):
        return self._request("POST", "/allocation-runs", payload, headers)

    def publish_allocation_run(self, run_id, headers):
        return self._request(
            "POST", f"/allocation-runs/{run_id}/publish", {}, headers
        )

    # --- End-of-life program ---
    def create_eol_notice(self, part_id, payload, headers):
        return self._request("POST", f"/parts/{part_id}/eol-notices", payload, headers)

    def rescind_eol_notice(self, notice_id, headers):
        return self._request("POST", f"/eol-notices/{notice_id}/rescind", {}, headers)

    # --- Lifetime buys ---
    def create_lifetime_buy(self, payload, headers):
        return self._request("POST", "/lifetime-buys", payload, headers)

    def get_lifetime_buy(self, ltb_id, headers):
        return self._request("GET", f"/lifetime-buys/{ltb_id}", headers=headers)

    def list_lifetime_buys(self, headers, params=None):
        return self._request("GET", "/lifetime-buys", headers=headers, params=params)

    def cancel_lifetime_buy(self, ltb_id, headers):
        return self._request("POST", f"/lifetime-buys/{ltb_id}/cancel", {}, headers)

    # --- Site qualification ---
    def create_site_qualification(self, payload, headers):
        return self._request("POST", "/site-qualifications", payload, headers)

    def transition_site_qualification(self, qual_id, payload, headers):
        return self._request(
            "POST", f"/site-qualifications/{qual_id}/transition", payload, headers
        )

    # --- Reference designs & design wins ---
    def create_reference_design(self, payload, headers):
        return self._request("POST", "/reference-designs", payload, headers)

    def publish_reference_design(self, design_id, headers):
        return self._request(
            "POST", f"/reference-designs/{design_id}/publish", {}, headers
        )

    def create_design_win(self, payload, headers):
        return self._request("POST", "/design-wins", payload, headers)

    def get_design_win(self, win_id, headers):
        return self._request("GET", f"/design-wins/{win_id}", headers=headers)

    def list_design_wins(self, headers, params=None):
        return self._request("GET", "/design-wins", headers=headers, params=params)

    def activate_design_win(self, win_id, headers):
        return self._request("POST", f"/design-wins/{win_id}/activate", {}, headers)

    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
