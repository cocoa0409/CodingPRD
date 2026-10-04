"""API client: one method per endpoint defined in the PRD (Instant-Needs MFC, /mfc prefix)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/mfc/_clock/set_current_utc", payload, headers)

    # --- Site ---
    def create_site(self, payload, headers):
        return self._request("POST", "/mfc/sites", payload, headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/mfc/sites", headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/mfc/sites/{site_id}", headers=headers)

    def update_capacity_profile(self, site_id, payload, headers):
        return self._request("PUT", f"/mfc/sites/{site_id}/capacity-profile", payload, headers)

    def suspend_site(self, site_id, headers):
        return self._request("POST", f"/mfc/sites/{site_id}/suspend", headers=headers)

    def resume_site(self, site_id, headers):
        return self._request("POST", f"/mfc/sites/{site_id}/resume", headers=headers)

    def get_demand_forecast(self, site_id, headers, params=None):
        return self._request("GET", f"/mfc/sites/{site_id}/demand-forecast", headers=headers, params=params)

    # --- Product ---
    def create_product(self, payload, headers):
        return self._request("POST", "/mfc/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/mfc/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/mfc/products/{product_id}", headers=headers)

    def retire_product(self, product_id, headers):
        return self._request("POST", f"/mfc/products/{product_id}/retire", headers=headers)

    # --- InventoryBalance ---
    def create_inventory_balance(self, payload, headers):
        return self._request("POST", "/mfc/inventory-balances", payload, headers)

    def list_inventory_balances(self, headers, params=None):
        return self._request("GET", "/mfc/inventory-balances", headers=headers, params=params)

    def get_inventory_balance(self, balance_id, headers):
        return self._request("GET", f"/mfc/inventory-balances/{balance_id}", headers=headers)

    def create_stock_adjustment(self, balance_id, payload, headers):
        return self._request("POST", f"/mfc/inventory-balances/{balance_id}/adjustments", payload, headers)

    # --- StockLot ---
    def list_stock_lots(self, headers, params=None):
        return self._request("GET", "/mfc/stock-lots", headers=headers, params=params)

    def get_stock_lot(self, lot_id, headers):
        return self._request("GET", f"/mfc/stock-lots/{lot_id}", headers=headers)

    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/mfc/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/mfc/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/mfc/customers/{customer_id}", headers=headers)

    def create_wallet_adjustment(self, customer_id, payload, headers):
        return self._request("POST", f"/mfc/customers/{customer_id}/wallet/adjustments", payload, headers)

    # --- Membership ---
    def create_membership(self, payload, headers):
        return self._request("POST", "/mfc/memberships", payload, headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/mfc/memberships", headers=headers, params=params)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/mfc/memberships/{membership_id}", headers=headers)

    def close_membership_period(self, membership_id, payload, headers):
        return self._request("POST", f"/mfc/memberships/{membership_id}/close-period", payload, headers)

    def renew_membership(self, membership_id, payload, headers):
        return self._request("POST", f"/mfc/memberships/{membership_id}/renew", payload, headers)

    def cancel_membership(self, membership_id, payload, headers):
        return self._request("POST", f"/mfc/memberships/{membership_id}/cancel", payload, headers)

    # --- ReplenishOrder ---
    def create_replenish_order(self, payload, headers):
        return self._request("POST", "/mfc/replenish-orders", payload, headers)

    def list_replenish_orders(self, headers, params=None):
        return self._request("GET", "/mfc/replenish-orders", headers=headers, params=params)

    def get_replenish_order(self, replenish_order_id, headers):
        return self._request("GET", f"/mfc/replenish-orders/{replenish_order_id}", headers=headers)

    def place_replenish_order(self, replenish_order_id, headers):
        return self._request("POST", f"/mfc/replenish-orders/{replenish_order_id}/place", headers=headers)

    def finalize_replenish_order(self, replenish_order_id, payload, headers):
        return self._request("POST", f"/mfc/replenish-orders/{replenish_order_id}/finalize", payload, headers)

    def cancel_replenish_order(self, replenish_order_id, headers):
        return self._request("POST", f"/mfc/replenish-orders/{replenish_order_id}/cancel", headers=headers)

    # --- Picker / Driver rosters ---
    def create_picker(self, payload, headers):
        return self._request("POST", "/mfc/pickers", payload, headers)

    def list_pickers(self, headers, params=None):
        return self._request("GET", "/mfc/pickers", headers=headers, params=params)

    def get_picker(self, picker_id, headers):
        return self._request("GET", f"/mfc/pickers/{picker_id}", headers=headers)

    def create_driver(self, payload, headers):
        return self._request("POST", "/mfc/drivers", payload, headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/mfc/drivers", headers=headers, params=params)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/mfc/drivers/{driver_id}", headers=headers)

    # --- Order ---
    def create_order(self, payload, headers):
        return self._request("POST", "/mfc/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/mfc/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/mfc/orders/{order_id}", headers=headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/mfc/orders/{order_id}/cancel", payload, headers)

    # --- PickBatch ---
    def create_pick_batch(self, payload, headers):
        return self._request("POST", "/mfc/pick-batches", payload, headers)

    def list_pick_batches(self, headers, params=None):
        return self._request("GET", "/mfc/pick-batches", headers=headers, params=params)

    def get_pick_batch(self, batch_id, headers):
        return self._request("GET", f"/mfc/pick-batches/{batch_id}", headers=headers)

    def append_order_to_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/mfc/pick-batches/{batch_id}/orders", payload, headers)

    def seal_pick_batch(self, batch_id, headers):
        return self._request("POST", f"/mfc/pick-batches/{batch_id}/seal", headers=headers)

    # --- DeliveryBag ---
    def create_delivery_bag(self, payload, headers):
        return self._request("POST", "/mfc/delivery-bags", payload, headers)

    def list_delivery_bags(self, headers, params=None):
        return self._request("GET", "/mfc/delivery-bags", headers=headers, params=params)

    def get_delivery_bag(self, bag_id, headers):
        return self._request("GET", f"/mfc/delivery-bags/{bag_id}", headers=headers)

    def assign_delivery_bag(self, bag_id, payload, headers):
        return self._request("POST", f"/mfc/delivery-bags/{bag_id}/assign", payload, headers)

    def handoff_scan(self, bag_id, payload, headers):
        return self._request("POST", f"/mfc/delivery-bags/{bag_id}/handoff-scan", payload, headers)

    def depart_delivery_bag(self, bag_id, headers):
        return self._request("POST", f"/mfc/delivery-bags/{bag_id}/depart", headers=headers)

    def complete_delivery_bag(self, bag_id, headers):
        return self._request("POST", f"/mfc/delivery-bags/{bag_id}/complete", headers=headers)

    def fail_handoff(self, bag_id, headers):
        return self._request("POST", f"/mfc/delivery-bags/{bag_id}/fail-handoff", headers=headers)


api_client = ApiClient()


import re
from typing import Optional

_INSTANT_RE = re.compile(
    r"^(?P<base>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?P<frac>\.\d+)?(?P<tz>Z|[+-]\d{2}:?\d{2})?$"
)


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO-8601 instant to `YYYY-MM-DDTHH:MM:SSZ` so that
    `...T00:00:00Z`, `...T00:00:00.000Z` and `...T00:00:00+00:00` compare equal."""
    if value is None:
        return None
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    return match.group("base") + "Z"


def instants_equal(left: Optional[str], right: Optional[str]) -> bool:
    """True when two ISO-8601 instants name the same second."""
    return canonical_instant(left) == canonical_instant(right)
