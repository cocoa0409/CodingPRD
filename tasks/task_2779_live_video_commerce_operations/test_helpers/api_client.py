"""API client: one method per endpoint the PRD defines."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------- logical clock
    def set_current_utc(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # -------------------------------------------------------------- hosts
    def create_host(self, payload, headers):
        return self._request("POST", "/hosts", payload, headers)

    def get_host(self, host_id, headers):
        return self._request("GET", f"/hosts/{host_id}", headers=headers)

    def certify_host(self, host_id, payload, headers):
        return self._request(
            "POST", f"/hosts/{host_id}/disclosure-certifications", payload, headers
        )

    def get_host_performance(self, host_id, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/hosts/{host_id}/performance", headers=headers, params=params
        )

    # ----------------------------------------------------------- products
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def adjust_inventory(self, product_id, payload, headers):
        return self._request(
            "POST", f"/products/{product_id}/inventory-adjustments", payload, headers
        )

    def substantiate_claim(self, product_id, payload, headers):
        return self._request(
            "POST", f"/products/{product_id}/claim-substantiations", payload, headers
        )

    # ------------------------------------------------------------ viewers
    def create_viewer(self, payload, headers):
        return self._request("POST", "/viewers", payload, headers)

    def get_viewer(self, viewer_id, headers):
        return self._request("GET", f"/viewers/{viewer_id}", headers=headers)

    # -------------------------------------------------------------- shows
    def create_show(self, payload, headers):
        return self._request("POST", "/shows", payload, headers)

    def get_show(self, show_id, headers):
        return self._request("GET", f"/shows/{show_id}", headers=headers)

    def ready_show(self, show_id, headers, payload: Optional[Dict] = None):
        return self._request("POST", f"/shows/{show_id}/ready", payload or {}, headers)

    def go_live_show(self, show_id, headers, payload: Optional[Dict] = None):
        return self._request("POST", f"/shows/{show_id}/go-live", payload or {}, headers)

    def end_show(self, show_id, headers, payload: Optional[Dict] = None):
        return self._request("POST", f"/shows/{show_id}/end", payload or {}, headers)

    def compliance_signoff_show(self, show_id, headers, payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/shows/{show_id}/compliance-signoff", payload or {}, headers
        )

    def get_show_analytics(self, show_id, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/shows/{show_id}/analytics", headers=headers, params=params
        )

    # ----------------------------------------------- simulcast destinations
    def create_stream_channel(self, payload, headers):
        return self._request("POST", "/stream-channels", payload, headers)

    def get_stream_channel(self, channel_id, headers):
        return self._request("GET", f"/stream-channels/{channel_id}", headers=headers)

    def list_stream_channels(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/stream-channels", headers=headers, params=params)

    def provision_stream_channel(self, channel_id, headers, payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/stream-channels/{channel_id}/provision", payload or {}, headers
        )

    def report_channel_health(self, channel_id, payload, headers):
        return self._request(
            "POST", f"/stream-channels/{channel_id}/health-reports", payload, headers
        )

    # ------------------------------------------------------ host bookings
    def create_host_booking(self, payload, headers):
        return self._request("POST", "/host-bookings", payload, headers)

    def get_host_booking(self, booking_id, headers):
        return self._request("GET", f"/host-bookings/{booking_id}", headers=headers)

    def list_host_bookings(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/host-bookings", headers=headers, params=params)

    def confirm_host_booking(self, booking_id, headers, payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/host-bookings/{booking_id}/confirm", payload or {}, headers
        )

    def cancel_host_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/host-bookings/{booking_id}/cancel", payload, headers
        )

    # -------------------------------------------------------- lineup slots
    def create_lineup_slot(self, payload, headers):
        return self._request("POST", "/lineup-slots", payload, headers)

    def get_lineup_slot(self, slot_id, headers):
        return self._request("GET", f"/lineup-slots/{slot_id}", headers=headers)

    def list_lineup_slots(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/lineup-slots", headers=headers, params=params)

    def set_replay_marker(self, slot_id, payload, headers):
        return self._request(
            "POST", f"/lineup-slots/{slot_id}/replay-marker", payload, headers
        )

    def publish_replay_marker(self, slot_id, headers, payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/lineup-slots/{slot_id}/replay-marker/publish", payload or {}, headers
        )

    def record_replay_conversion(self, slot_id, payload, headers):
        return self._request(
            "POST", f"/lineup-slots/{slot_id}/replay-conversions", payload, headers
        )

    # -------------------------------------------------------- flash offers
    def create_flash_offer(self, payload, headers):
        return self._request("POST", "/flash-offers", payload, headers)

    def get_flash_offer(self, offer_id, headers):
        return self._request("GET", f"/flash-offers/{offer_id}", headers=headers)

    def list_flash_offers(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/flash-offers", headers=headers, params=params)

    def activate_flash_offer(self, offer_id, headers, payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/flash-offers/{offer_id}/activate", payload or {}, headers
        )

    # --------------------------------------------------- disclosure records
    def create_disclosure_record(self, payload, headers):
        return self._request("POST", "/disclosure-records", payload, headers)

    def get_disclosure_record(self, record_id, headers):
        return self._request("GET", f"/disclosure-records/{record_id}", headers=headers)

    def list_disclosure_records(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/disclosure-records", headers=headers, params=params)

    def acknowledge_disclosure_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"/disclosure-records/{record_id}/acknowledge", payload, headers
        )

    # -------------------------------------------------------------- carts
    def create_cart(self, payload, headers):
        return self._request("POST", "/carts", payload, headers)

    def get_cart(self, cart_id, headers):
        return self._request("GET", f"/carts/{cart_id}", headers=headers)

    def list_carts(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/carts", headers=headers, params=params)

    def add_cart_item(self, cart_id, payload, headers):
        return self._request("POST", f"/carts/{cart_id}/items", payload, headers)

    def abandon_cart(self, cart_id, headers, payload: Optional[Dict] = None):
        return self._request("POST", f"/carts/{cart_id}/abandon", payload or {}, headers)

    def recover_cart(self, cart_id, headers, payload: Optional[Dict] = None):
        return self._request("POST", f"/carts/{cart_id}/recover", payload or {}, headers)

    def checkout_cart(self, cart_id, payload, headers):
        return self._request("POST", f"/carts/{cart_id}/checkout", payload, headers)

    # ---------------------------------------------------------- cart lines
    def get_cart_item(self, item_id, headers):
        return self._request("GET", f"/cart-items/{item_id}", headers=headers)

    def list_cart_items(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/cart-items", headers=headers, params=params)

    # ------------------------------------------------------------- orders
    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def capture_order(self, order_id, headers, payload: Optional[Dict] = None):
        return self._request("POST", f"/orders/{order_id}/capture", payload or {}, headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", payload, headers)

    # ------------------------------------------------------- interactions
    def create_interaction(self, payload, headers):
        return self._request("POST", "/interactions", payload, headers)

    def get_interaction(self, interaction_id, headers):
        return self._request("GET", f"/interactions/{interaction_id}", headers=headers)

    def list_interactions(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/interactions", headers=headers, params=params)

    def moderate_interaction(self, interaction_id, payload, headers):
        return self._request(
            "POST", f"/interactions/{interaction_id}/moderate", payload, headers
        )

    def route_interaction(self, interaction_id, headers, payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/interactions/{interaction_id}/route", payload or {}, headers
        )

    def host_action_interaction(self, interaction_id, payload, headers):
        return self._request(
            "POST", f"/interactions/{interaction_id}/host-action", payload, headers
        )

    def cast_vote(self, interaction_id, payload, headers):
        return self._request(
            "POST", f"/interactions/{interaction_id}/votes", payload, headers
        )


api_client = ApiClient()
