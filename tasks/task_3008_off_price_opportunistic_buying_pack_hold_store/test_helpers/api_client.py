"""API client: one method per endpoint defined in the PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- MerchandiseSeason ---
    def create_season(self, payload, headers):
        return self._request("POST", "/merchandise-seasons", payload, headers)

    def list_seasons(self, headers, params=None):
        return self._request("GET", "/merchandise-seasons", headers=headers, params=params)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/merchandise-seasons/{season_id}", headers=headers)

    def open_season(self, season_id, headers):
        return self._request("POST", f"/merchandise-seasons/{season_id}/open", headers=headers)

    def close_season(self, season_id, headers):
        return self._request("POST", f"/merchandise-seasons/{season_id}/close", headers=headers)

    def list_season_lots(self, season_id, headers, params=None):
        return self._request("GET", f"/merchandise-seasons/{season_id}/lots", headers=headers, params=params)

    def list_season_packaway_holds(self, season_id, headers, params=None):
        return self._request("GET", f"/merchandise-seasons/{season_id}/packaway-holds", headers=headers, params=params)

    def list_season_allocation_plans(self, season_id, headers, params=None):
        return self._request("GET", f"/merchandise-seasons/{season_id}/allocation-plans", headers=headers, params=params)

    def list_season_store_skus(self, season_id, headers, params=None):
        return self._request("GET", f"/merchandise-seasons/{season_id}/store-skus", headers=headers, params=params)

    # --- Vendor ---
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/vendors", headers=headers, params=params)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def list_vendor_lots(self, vendor_id, headers, params=None):
        return self._request("GET", f"/vendors/{vendor_id}/lots", headers=headers, params=params)

    # --- PriceZone ---
    def create_price_zone(self, payload, headers):
        return self._request("POST", "/price-zones", payload, headers)

    def list_price_zones(self, headers, params=None):
        return self._request("GET", "/price-zones", headers=headers, params=params)

    def get_price_zone(self, zone_id, headers):
        return self._request("GET", f"/price-zones/{zone_id}", headers=headers)

    # --- Lot ---
    def create_lot(self, payload, headers):
        return self._request("POST", "/lots", payload, headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def evaluate_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/evaluate", payload, headers)

    def accept_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/accept", payload, headers)

    def pass_lot(self, lot_id, headers):
        return self._request("POST", f"/lots/{lot_id}/pass", headers=headers)

    def cancel_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/cancel", payload, headers)

    def list_lot_lines_of_lot(self, lot_id, headers, params=None):
        return self._request("GET", f"/lots/{lot_id}/lot-lines", headers=headers, params=params)

    def list_lot_packaway_holds(self, lot_id, headers, params=None):
        return self._request("GET", f"/lots/{lot_id}/packaway-holds", headers=headers, params=params)

    def list_lot_allocation_plans(self, lot_id, headers, params=None):
        return self._request("GET", f"/lots/{lot_id}/allocation-plans", headers=headers, params=params)

    def list_lot_receipts(self, lot_id, headers, params=None):
        return self._request("GET", f"/lots/{lot_id}/receipts", headers=headers, params=params)

    def list_lot_shrink_cases(self, lot_id, headers, params=None):
        return self._request("GET", f"/lots/{lot_id}/shrink-cases", headers=headers, params=params)

    def list_lot_liquidation_orders(self, lot_id, headers, params=None):
        return self._request("GET", f"/lots/{lot_id}/liquidation-orders", headers=headers, params=params)

    # --- LotLine ---
    def create_lot_line(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/lot-lines", payload, headers)

    def get_lot_line(self, line_id, headers):
        return self._request("GET", f"/lot-lines/{line_id}", headers=headers)

    def list_lot_line_tickets(self, line_id, headers, params=None):
        return self._request("GET", f"/lot-lines/{line_id}/tickets", headers=headers, params=params)

    def list_lot_line_store_skus(self, line_id, headers, params=None):
        return self._request("GET", f"/lot-lines/{line_id}/store-skus", headers=headers, params=params)

    def list_lot_line_receipt_lines(self, line_id, headers, params=None):
        return self._request("GET", f"/lot-lines/{line_id}/receipt-lines", headers=headers, params=params)

    # --- Warehouse ---
    def create_warehouse(self, payload, headers):
        return self._request("POST", "/warehouses", payload, headers)

    def list_warehouses(self, headers, params=None):
        return self._request("GET", "/warehouses", headers=headers, params=params)

    def get_warehouse(self, warehouse_id, headers):
        return self._request("GET", f"/warehouses/{warehouse_id}", headers=headers)

    def list_warehouse_packaway_holds(self, warehouse_id, headers, params=None):
        return self._request("GET", f"/warehouses/{warehouse_id}/packaway-holds", headers=headers, params=params)

    def list_warehouse_receipts(self, warehouse_id, headers, params=None):
        return self._request("GET", f"/warehouses/{warehouse_id}/receipts", headers=headers, params=params)

    # --- PackawayHold ---
    def create_packaway_hold(self, payload, headers):
        return self._request("POST", "/packaway-holds", payload, headers)

    def list_packaway_holds(self, headers, params=None):
        return self._request("GET", "/packaway-holds", headers=headers, params=params)

    def get_packaway_hold(self, hold_id, headers):
        return self._request("GET", f"/packaway-holds/{hold_id}", headers=headers)

    def aging_review(self, hold_id, payload, headers):
        return self._request("POST", f"/packaway-holds/{hold_id}/aging-review", payload, headers)

    def liquidate_hold(self, hold_id, headers):
        return self._request("POST", f"/packaway-holds/{hold_id}/liquidate", headers=headers)

    def release_hold(self, hold_id, payload, headers):
        return self._request("POST", f"/packaway-holds/{hold_id}/release", payload, headers)

    # --- Store ---
    def create_store(self, payload, headers):
        return self._request("POST", "/stores", payload, headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", "/stores", headers=headers, params=params)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    def list_store_store_skus(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/store-skus", headers=headers, params=params)

    def list_store_shrink_cases(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/shrink-cases", headers=headers, params=params)

    def list_store_liquidation_orders(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/liquidation-orders", headers=headers, params=params)

    # --- AllocationPlan ---
    def create_allocation_plan(self, payload, headers):
        return self._request("POST", "/allocation-plans", payload, headers)

    def list_allocation_plans(self, headers, params=None):
        return self._request("GET", "/allocation-plans", headers=headers, params=params)

    def get_allocation_plan(self, plan_id, headers):
        return self._request("GET", f"/allocation-plans/{plan_id}", headers=headers)

    def approve_allocation_plan(self, plan_id, headers):
        return self._request("POST", f"/allocation-plans/{plan_id}/approve", headers=headers)

    def execute_allocation_plan(self, plan_id, headers):
        return self._request("POST", f"/allocation-plans/{plan_id}/execute", headers=headers)

    def cancel_allocation_plan(self, plan_id, headers):
        return self._request("POST", f"/allocation-plans/{plan_id}/cancel", headers=headers)

    def list_allocation_plan_store_skus(self, plan_id, headers, params=None):
        return self._request("GET", f"/allocation-plans/{plan_id}/store-skus", headers=headers, params=params)

    # --- StoreSku ---
    def create_store_sku(self, payload, headers):
        return self._request("POST", "/store-skus", payload, headers)

    def list_store_skus(self, headers, params=None):
        return self._request("GET", "/store-skus", headers=headers, params=params)

    def get_store_sku(self, sku_id, headers):
        return self._request("GET", f"/store-skus/{sku_id}", headers=headers)

    def list_store_sku_markdown_events(self, sku_id, headers, params=None):
        return self._request("GET", f"/store-skus/{sku_id}/markdown-events", headers=headers, params=params)

    def list_store_sku_shrink_cases(self, sku_id, headers, params=None):
        return self._request("GET", f"/store-skus/{sku_id}/shrink-cases", headers=headers, params=params)

    def deplete_store_sku(self, sku_id, payload, headers):
        return self._request("POST", f"/store-skus/{sku_id}/deplete", payload, headers)

    # --- Ticket ---
    def create_ticket(self, payload, headers):
        return self._request("POST", "/tickets", payload, headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/tickets", headers=headers, params=params)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/tickets/{ticket_id}", headers=headers)

    def void_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/void", headers=headers)

    def list_ticket_store_skus(self, ticket_id, headers, params=None):
        return self._request("GET", f"/tickets/{ticket_id}/store-skus", headers=headers, params=params)

    # --- Receipt ---
    def create_receipt(self, payload, headers):
        return self._request("POST", "/receipts", payload, headers)

    def list_receipts(self, headers, params=None):
        return self._request("GET", "/receipts", headers=headers, params=params)

    def get_receipt(self, receipt_id, headers):
        return self._request("GET", f"/receipts/{receipt_id}", headers=headers)

    def list_receipt_lines(self, receipt_id, headers, params=None):
        return self._request("GET", f"/receipts/{receipt_id}/receipt-lines", headers=headers, params=params)

    def update_receipt_line(self, receipt_id, line_id, payload, headers):
        return self._request("PATCH", f"/receipts/{receipt_id}/lines/{line_id}", payload, headers)

    def complete_receipt(self, receipt_id, headers):
        return self._request("POST", f"/receipts/{receipt_id}/complete", headers=headers)

    # --- ShrinkCase ---
    def create_shrink_case(self, payload, headers):
        return self._request("POST", "/shrink-cases", payload, headers)

    def list_shrink_cases(self, headers, params=None):
        return self._request("GET", "/shrink-cases", headers=headers, params=params)

    def get_shrink_case(self, case_id, headers):
        return self._request("GET", f"/shrink-cases/{case_id}", headers=headers)

    def confirm_shrink_case(self, case_id, headers):
        return self._request("POST", f"/shrink-cases/{case_id}/confirm", headers=headers)

    def void_shrink_case(self, case_id, headers):
        return self._request("POST", f"/shrink-cases/{case_id}/void", headers=headers)

    # --- LiquidationOrder ---
    def create_liquidation_order(self, payload, headers):
        return self._request("POST", "/liquidation-orders", payload, headers)

    def list_liquidation_orders(self, headers, params=None):
        return self._request("GET", "/liquidation-orders", headers=headers, params=params)

    def get_liquidation_order(self, order_id, headers):
        return self._request("GET", f"/liquidation-orders/{order_id}", headers=headers)

    def approve_liquidation_order(self, order_id, headers):
        return self._request("POST", f"/liquidation-orders/{order_id}/approve", headers=headers)

    def execute_liquidation_order(self, order_id, payload, headers):
        return self._request("POST", f"/liquidation-orders/{order_id}/execute", payload, headers)

    def cancel_liquidation_order(self, order_id, headers):
        return self._request("POST", f"/liquidation-orders/{order_id}/cancel", headers=headers)


api_client = ApiClient()
