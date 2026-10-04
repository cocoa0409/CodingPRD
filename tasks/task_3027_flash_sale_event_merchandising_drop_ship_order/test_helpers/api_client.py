"""API client: one method per endpoint in the PRD's endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Logical clock ────────────────────────────────
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock/current_utc", headers=headers)

    # ─── Vendor ───────────────────────────────────────
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/vendors", headers=headers, params=params)

    def list_vendor_shops(self, vendor_id, headers, params=None):
        return self._request("GET", f"/vendors/{vendor_id}/shops",
                             headers=headers, params=params)

    def list_vendor_purchase_orders(self, vendor_id, headers, params=None):
        return self._request("GET", f"/vendors/{vendor_id}/purchase-orders",
                             headers=headers, params=params)

    def get_fill_rate_report(self, vendor_id, headers, params=None):
        return self._request("GET", f"/vendors/{vendor_id}/fill-rate-report",
                             headers=headers, params=params)

    # ─── Shop ─────────────────────────────────────────
    def create_shop(self, payload, headers):
        return self._request("POST", "/shops", payload, headers)

    def get_shop(self, shop_id, headers):
        return self._request("GET", f"/shops/{shop_id}", headers=headers)

    def list_shops(self, headers, params=None):
        return self._request("GET", "/shops", headers=headers, params=params)

    def list_shop_events(self, shop_id, headers, params=None):
        return self._request("GET", f"/shops/{shop_id}/events",
                             headers=headers, params=params)

    # ─── Event ────────────────────────────────────────
    def create_event(self, payload, headers):
        return self._request("POST", "/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/events", headers=headers, params=params)

    def list_event_listings(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/listings",
                             headers=headers, params=params)

    def schedule_event(self, event_id, headers, payload=None):
        return self._request("POST", f"/events/{event_id}/schedule",
                             payload or {}, headers)

    def launch_event(self, event_id, headers, payload=None):
        return self._request("POST", f"/events/{event_id}/launch",
                             payload or {}, headers)

    def close_event(self, event_id, headers, payload=None):
        return self._request("POST", f"/events/{event_id}/close",
                             payload or {}, headers)

    def cancel_event(self, event_id, headers, payload=None):
        return self._request("POST", f"/events/{event_id}/cancel",
                             payload or {}, headers)

    def run_event_checkpoint(self, event_id, headers, payload=None):
        return self._request("POST", f"/events/{event_id}/run-event-checkpoint",
                             payload or {}, headers)

    # ─── Listing ──────────────────────────────────────
    def create_listing(self, payload, headers):
        return self._request("POST", "/listings", payload, headers)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/listings/{listing_id}", headers=headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/listings", headers=headers, params=params)

    def get_oversell_preview(self, listing_id, headers):
        return self._request("GET", f"/listings/{listing_id}/oversell-preview",
                             headers=headers)

    def reallocate_listing(self, listing_id, payload, headers):
        return self._request("POST", f"/listings/{listing_id}/reallocate",
                             payload, headers)

    def withdraw_listing(self, listing_id, headers, payload=None):
        return self._request("POST", f"/listings/{listing_id}/withdraw",
                             payload or {}, headers)

    def list_listing_purchase_order_lines(self, listing_id, headers, params=None):
        return self._request("GET", f"/listings/{listing_id}/purchase-order-lines",
                             headers=headers, params=params)

    # ─── Customer ─────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def list_customer_orders(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/orders",
                             headers=headers, params=params)

    def get_credit_ledger(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/credit-ledger",
                             headers=headers, params=params)

    def create_credit(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/credits",
                             payload, headers)

    def create_payout(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/payouts",
                             payload, headers)

    def restore_customer(self, customer_id, headers, payload=None):
        return self._request("POST", f"/customers/{customer_id}/restore",
                             payload or {}, headers)

    def close_customer(self, customer_id, headers, payload=None):
        return self._request("POST", f"/customers/{customer_id}/close",
                             payload or {}, headers)

    # ─── CustomerOrder ────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/lines",
                             headers=headers, params=params)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def submit_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/submit",
                             payload or {}, headers)

    def cancel_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines/cancel",
                             payload, headers)

    def reprice_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/reprice", payload, headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", payload, headers)

    def capture_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/capture",
                             payload or {}, headers)

    def refund_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/refunds", payload, headers)

    def consolidate_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/consolidate", payload, headers)

    def list_order_parcels(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/parcels",
                             headers=headers, params=params)

    # ─── Confirmation ─────────────────────────────────
    def get_confirmation(self, confirmation_id, headers):
        return self._request("GET", f"/confirmations/{confirmation_id}", headers=headers)

    def list_confirmations(self, headers, params=None):
        return self._request("GET", "/confirmations", headers=headers, params=params)

    def confirm_line(self, confirmation_id, payload, headers):
        return self._request("POST", f"/confirmations/{confirmation_id}/confirm",
                             payload, headers)

    def list_confirmation_returns(self, confirmation_id, headers, params=None):
        return self._request("GET", f"/confirmations/{confirmation_id}/returns",
                             headers=headers, params=params)

    # ─── PurchaseOrder ────────────────────────────────
    def create_purchase_order(self, payload, headers):
        return self._request("POST", "/purchase-orders", payload, headers)

    def get_purchase_order(self, po_id, headers):
        return self._request("GET", f"/purchase-orders/{po_id}", headers=headers)

    def list_purchase_orders(self, headers, params=None):
        return self._request("GET", "/purchase-orders", headers=headers, params=params)

    def list_po_lines(self, po_id, headers, params=None):
        return self._request("GET", f"/purchase-orders/{po_id}/lines",
                             headers=headers, params=params)

    def list_po_shipments(self, po_id, headers, params=None):
        return self._request("GET", f"/purchase-orders/{po_id}/shipments",
                             headers=headers, params=params)

    def add_po_line(self, po_id, payload, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/add-line",
                             payload, headers)

    def issue_purchase_order(self, po_id, payload, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/issue", payload, headers)

    def close_short_purchase_order(self, po_id, payload, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/close-short",
                             payload, headers)

    def reopen_purchase_order(self, po_id, headers, payload=None):
        return self._request("POST", f"/purchase-orders/{po_id}/reopen",
                             payload or {}, headers)

    def cancel_purchase_order(self, po_id, payload, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/cancel", payload, headers)

    # ─── VendorShipment ───────────────────────────────
    def create_shipment(self, payload, headers):
        return self._request("POST", "/vendor-shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/vendor-shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/vendor-shipments", headers=headers, params=params)

    def receive_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/vendor-shipments/{shipment_id}/receive",
                             payload, headers)

    def reject_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/vendor-shipments/{shipment_id}/reject",
                             payload, headers)

    # ─── Parcel ───────────────────────────────────────
    def get_parcel(self, parcel_id, headers):
        return self._request("GET", f"/parcels/{parcel_id}", headers=headers)

    def list_parcels(self, headers, params=None):
        return self._request("GET", "/parcels", headers=headers, params=params)

    def seal_parcel(self, parcel_id, headers, payload=None):
        return self._request("POST", f"/parcels/{parcel_id}/seal",
                             payload or {}, headers)

    def dispatch_parcel(self, parcel_id, headers, payload=None):
        return self._request("POST", f"/parcels/{parcel_id}/dispatch",
                             payload or {}, headers)

    def deliver_parcel(self, parcel_id, headers, payload=None):
        return self._request("POST", f"/parcels/{parcel_id}/deliver",
                             payload or {}, headers)

    # ─── ReturnRequest ────────────────────────────────
    def create_return(self, payload, headers):
        return self._request("POST", "/returns", payload, headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/returns/{return_id}", headers=headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/returns", headers=headers, params=params)

    def adjudicate_return(self, return_id, headers, payload=None):
        return self._request("POST", f"/returns/{return_id}/adjudicate",
                             payload or {}, headers)

    def escalate_return(self, return_id, headers, payload=None):
        return self._request("POST", f"/returns/{return_id}/escalate",
                             payload or {}, headers)

    def decide_return(self, return_id, payload, headers):
        return self._request("POST", f"/returns/{return_id}/decide", payload, headers)

    def receive_return(self, return_id, headers, payload=None):
        return self._request("POST", f"/returns/{return_id}/receive",
                             payload or {}, headers)

    def settle_return(self, return_id, payload, headers):
        return self._request("POST", f"/returns/{return_id}/settle", payload, headers)

    # ─── Monolith composition read ────────────────────
    def get_vendor_order_view(self, order_id, headers):
        return self._request("GET", f"/vendor-orders/{order_id}", headers=headers)


api_client = ApiClient()