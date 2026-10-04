"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def renew_member(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/renew", payload, headers)

    def cancel_member(self, member_id, headers, payload=None):
        return self._request("POST", f"/members/{member_id}/cancel", payload or {}, headers)

    # --- Trade accounts ---
    def create_trade_account(self, payload, headers):
        return self._request("POST", "/trade-accounts", payload, headers)

    def verify_trade_account(self, account_id, payload, headers):
        return self._request("POST", f"/trade-accounts/{account_id}/verify", payload, headers)

    # --- Galleries ---
    def create_gallery(self, payload, headers):
        return self._request("POST", "/galleries", payload, headers)

    def get_gallery(self, gallery_id, headers):
        return self._request("GET", f"/galleries/{gallery_id}", headers=headers)

    def list_gallery_production_slots(self, gallery_id, headers, params=None):
        return self._request("GET", f"/galleries/{gallery_id}/production-slots", headers=headers, params=params)

    # --- Products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_product_order_lines(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/order-lines", headers=headers, params=params)

    # --- Source books ---
    def create_source_book(self, payload, headers):
        return self._request("POST", "/source-books", payload, headers)

    # --- Orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def remove_order_line(self, order_id, line_id, payload, headers):
        import requests

        url = f"{self.base_url}/orders/{order_id}/lines/{line_id}"
        return self.session.request("DELETE", url, json=payload, headers=headers or {})

    def list_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/lines", headers=headers, params=params)

    def schedule_production(self, order_id, line_id, payload, headers):
        return self._request(
            "POST", f"/orders/{order_id}/lines/{line_id}/schedule-production", payload, headers
        )

    def confirm_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/confirm", payload, headers)

    def cancel_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/cancel", payload or {}, headers)

    # --- Production slots ---
    def create_production_slot(self, payload, headers):
        return self._request("POST", "/production-slots", payload, headers)

    def get_production_slot(self, slot_id, headers):
        return self._request("GET", f"/production-slots/{slot_id}", headers=headers)

    def advance_production_slot(self, slot_id, payload, headers):
        return self._request("POST", f"/production-slots/{slot_id}/advance", payload, headers)

    # --- Design consultations ---
    def create_design_consultation(self, payload, headers):
        return self._request("POST", "/design-consultations", payload, headers)

    def get_design_consultation(self, consultation_id, headers):
        return self._request("GET", f"/design-consultations/{consultation_id}", headers=headers)

    def list_design_consultations(self, headers, params=None):
        return self._request("GET", "/design-consultations", headers=headers, params=params)

    def complete_design_consultation(self, consultation_id, payload, headers):
        return self._request(
            "POST", f"/design-consultations/{consultation_id}/complete", payload, headers
        )

    # --- Delivery appointments ---
    def create_delivery_appointment(self, payload, headers):
        return self._request("POST", "/delivery-appointments", payload, headers)

    def get_delivery_appointment(self, appointment_id, headers):
        return self._request("GET", f"/delivery-appointments/{appointment_id}", headers=headers)

    def list_delivery_appointments(self, headers, params=None):
        return self._request("GET", "/delivery-appointments", headers=headers, params=params)

    def record_appointment_outcome(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/delivery-appointments/{appointment_id}/record-outcome", payload, headers
        )

    # --- Returns ---
    def create_return(self, payload, headers):
        return self._request("POST", "/returns", payload, headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/returns/{return_id}", headers=headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/returns", headers=headers, params=params)

    def settle_return(self, return_id, payload, headers):
        return self._request("POST", f"/returns/{return_id}/settle", payload, headers)

    # --- Test-driving ops / clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def run_daily_cycle(self, headers):
        return self._request("POST", "/_ops/run_daily_cycle", {}, headers)


api_client = ApiClient()
