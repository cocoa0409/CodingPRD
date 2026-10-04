"""API client: one method per endpoint declared in the PRD's §4 surface.

The API is mounted under the `/produce` prefix; the test-driving logical-clock
endpoint is the single exception and lives at `/_clock/set_current_utc`.

GET requests pass their query parameters through the client's `payload`
argument, which the base class forwards as query params for GET/DELETE.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # --- Logical clock ------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Customers ----------------------------------------------------------
    def register_customer(self, payload, headers):
        return self._request("POST", "/produce/customers/register", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/produce/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/produce/customers", payload=params, headers=headers)

    def list_customer_box_orders(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/produce/customers/{customer_id}/box-orders", payload=params, headers=headers
        )

    def list_customer_subscriptions(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/produce/customers/{customer_id}/subscriptions", payload=params, headers=headers
        )

    # --- Subscriptions ------------------------------------------------------
    def create_subscription(self, payload, headers):
        return self._request("POST", "/produce/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/produce/subscriptions/{subscription_id}", headers=headers)

    def list_subscription_box_orders(self, subscription_id, headers, params=None):
        return self._request(
            "GET", f"/produce/subscriptions/{subscription_id}/box-orders",
            payload=params, headers=headers,
        )

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/produce/subscriptions", payload=params, headers=headers)

    def skip_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/produce/subscriptions/{subscription_id}/skip", payload, headers
        )

    def pause_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/produce/subscriptions/{subscription_id}/pause", payload, headers
        )

    def resume_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/produce/subscriptions/{subscription_id}/resume", payload, headers
        )

    def cancel_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/produce/subscriptions/{subscription_id}/cancel", payload, headers
        )

    # --- Fulfillment centers -------------------------------------------------
    def create_fulfillment_center(self, payload, headers):
        return self._request("POST", "/produce/fulfillment-centers", payload, headers)

    def get_fulfillment_center(self, center_id, headers):
        return self._request("GET", f"/produce/fulfillment-centers/{center_id}", headers=headers)

    def list_fulfillment_centers(self, headers, params=None):
        return self._request(
            "GET", "/produce/fulfillment-centers", payload=params, headers=headers
        )

    def update_fulfillment_center(self, center_id, payload, headers):
        return self._request("PUT", f"/produce/fulfillment-centers/{center_id}", payload, headers)

    def advance_center_cycle(self, center_id, payload, headers):
        return self._request(
            "POST", f"/produce/fulfillment-centers/{center_id}/advance-cycle", payload, headers
        )

    def list_center_lots(self, center_id, headers, params=None):
        return self._request(
            "GET", f"/produce/fulfillment-centers/{center_id}/lots", payload=params, headers=headers
        )

    def list_center_cold_chain_packs(self, center_id, headers, params=None):
        return self._request(
            "GET", f"/produce/fulfillment-centers/{center_id}/cold-chain-packs",
            payload=params, headers=headers,
        )

    def list_center_customers(self, center_id, headers, params=None):
        return self._request(
            "GET", f"/produce/fulfillment-centers/{center_id}/customers",
            payload=params, headers=headers,
        )

    def list_center_subscriptions(self, center_id, headers, params=None):
        return self._request(
            "GET", f"/produce/fulfillment-centers/{center_id}/subscriptions",
            payload=params, headers=headers,
        )

    def list_center_sourcing_bids(self, center_id, headers, params=None):
        return self._request(
            "GET", f"/produce/fulfillment-centers/{center_id}/sourcing-bids",
            payload=params, headers=headers,
        )

    def list_center_box_orders(self, center_id, headers, params=None):
        return self._request(
            "GET", f"/produce/fulfillment-centers/{center_id}/box-orders",
            payload=params, headers=headers,
        )

    # --- Suppliers ----------------------------------------------------------
    def create_supplier(self, payload, headers):
        return self._request("POST", "/produce/suppliers", payload, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/produce/suppliers/{supplier_id}", headers=headers)

    def list_suppliers(self, headers, params=None):
        return self._request("GET", "/produce/suppliers", payload=params, headers=headers)

    def list_supplier_bids(self, supplier_id, headers, params=None):
        return self._request(
            "GET", f"/produce/suppliers/{supplier_id}/sourcing-bids",
            payload=params, headers=headers,
        )

    # --- Supply lots --------------------------------------------------------
    def create_lot(self, supplier_id, payload, headers):
        return self._request("POST", f"/produce/suppliers/{supplier_id}/lots", payload, headers)

    def list_supplier_lots(self, supplier_id, headers, params=None):
        return self._request(
            "GET", f"/produce/suppliers/{supplier_id}/lots", payload=params, headers=headers
        )

    def list_supply_lots(self, headers, params=None):
        return self._request("GET", "/produce/supply-lots", payload=params, headers=headers)

    def get_supply_lot(self, lot_id, headers):
        return self._request("GET", f"/produce/supply-lots/{lot_id}", headers=headers)

    def list_lot_bids(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/produce/supply-lots/{lot_id}/sourcing-bids", payload=params, headers=headers
        )

    def list_lot_quotes(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/produce/supply-lots/{lot_id}/conventional-quotes",
            payload=params, headers=headers,
        )

    def list_lot_build_items(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/produce/supply-lots/{lot_id}/build-items", payload=params, headers=headers
        )

    def list_lot_quality_claims(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/produce/supply-lots/{lot_id}/quality-claims",
            payload=params, headers=headers,
        )

    # --- Sourcing bids ------------------------------------------------------
    def create_bid(self, payload, headers):
        return self._request("POST", "/produce/sourcing-bids", payload, headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", "/produce/sourcing-bids", payload=params, headers=headers)

    def withdraw_bid(self, bid_id, payload, headers):
        return self._request("POST", f"/produce/sourcing-bids/{bid_id}/withdraw", payload, headers)

    # --- Award, make-ready, substantiation ------------------------------------
    def award_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/produce/supply-lots/{lot_id}/award", payload, headers)

    def make_lot_ready(self, lot_id, payload, headers):
        return self._request("POST", f"/produce/supply-lots/{lot_id}/make-ready", payload, headers)

    def create_quote(self, payload, headers):
        return self._request("POST", "/produce/conventional-quotes", payload, headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/produce/conventional-quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/produce/conventional-quotes", payload=params, headers=headers)

    def substantiate_quote(self, quote_id, payload, headers):
        return self._request(
            "POST", f"/produce/conventional-quotes/{quote_id}/substantiate", payload, headers
        )

    # --- Box orders ---------------------------------------------------------
    def create_box_order(self, payload, headers):
        return self._request("POST", "/produce/box-orders", payload, headers)

    def list_box_orders(self, headers, params=None):
        return self._request("GET", "/produce/box-orders", payload=params, headers=headers)

    def get_box_order(self, order_id, headers):
        return self._request("GET", f"/produce/box-orders/{order_id}", headers=headers)

    def finalize_box_order(self, order_id, payload, headers):
        return self._request("POST", f"/produce/box-orders/{order_id}/finalize", payload, headers)

    def build_box_order(self, order_id, payload, headers):
        return self._request("POST", f"/produce/box-orders/{order_id}/build", payload, headers)

    def reroute_back_box_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/produce/box-orders/{order_id}/reroute-back", payload, headers
        )

    def crash_out_box_order(self, order_id, payload, headers):
        return self._request("POST", f"/produce/box-orders/{order_id}/crash-out", payload, headers)

    def list_box_order_items(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/produce/box-orders/{order_id}/items", payload=params, headers=headers
        )

    def pack_box_order(self, order_id, payload, headers):
        return self._request("POST", f"/produce/box-orders/{order_id}/pack", payload, headers)

    def list_box_order_cold_chain_packs(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/produce/box-orders/{order_id}/cold-chain-packs",
            payload=params, headers=headers,
        )

    # --- Build items --------------------------------------------------------
    def get_build_item(self, item_id, headers):
        return self._request("GET", f"/produce/box-build-items/{item_id}", headers=headers)

    def list_build_item_quality_claims(self, item_id, headers, params=None):
        return self._request(
            "GET", f"/produce/box-build-items/{item_id}/quality-claims",
            payload=params, headers=headers,
        )

    # --- Quality claims -----------------------------------------------------
    def create_quality_claim(self, order_id, payload, headers):
        return self._request(
            "POST", f"/produce/box-orders/{order_id}/quality-claims", payload, headers
        )

    def list_order_quality_claims(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/produce/box-orders/{order_id}/quality-claims",
            payload=params, headers=headers,
        )

    def list_quality_claims(self, headers, params=None):
        return self._request("GET", "/produce/quality-claims", payload=params, headers=headers)

    def review_quality_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/produce/quality-claims/{claim_id}/review", payload, headers
        )

    def reopen_quality_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/produce/quality-claims/{claim_id}/reopen", payload, headers
        )


api_client = ApiClient()