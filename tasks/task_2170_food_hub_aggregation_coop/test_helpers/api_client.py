"""API client: one method per operation the PRD defines."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Producer onboarding ----------------
    def create_producer(self, payload, headers):
        return self._request("POST", "/producers", payload, headers)

    def get_producer(self, producer_id, headers):
        return self._request("GET", f"/producers/{producer_id}", headers=headers)

    def list_producer_documents(self, producer_id, headers, params=None):
        return self._request(
            "GET", f"/producers/{producer_id}/documents", headers=headers, params=params
        )

    def create_producer_document(self, producer_id, payload, headers):
        return self._request(
            "POST", f"/producers/{producer_id}/documents", payload, headers
        )

    def submit_application(self, producer_id, headers, payload=None):
        return self._request(
            "POST", f"/producers/{producer_id}/application", payload or {}, headers
        )

    def review_producer(self, producer_id, payload, headers):
        return self._request("POST", f"/producers/{producer_id}/review", payload, headers)

    def adjudicate_document(self, document_id, payload, headers):
        return self._request(
            "POST", f"/producer-documents/{document_id}/adjudication", payload, headers
        )

    def create_equity_contribution(self, producer_id, payload, headers):
        return self._request(
            "POST", f"/producers/{producer_id}/equity-contributions", payload, headers
        )

    # ---------------- Catalog & availability ----------------
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def publish_offer(self, product_id, payload, headers):
        return self._request("POST", f"/products/{product_id}/offers", payload, headers)

    # ---------------- Buyers & demand ----------------
    def create_buyer(self, payload, headers):
        return self._request("POST", "/buyers", payload, headers)

    def get_buyer(self, buyer_id, headers):
        return self._request("GET", f"/buyers/{buyer_id}", headers=headers)

    def create_buyer_order(self, payload, headers):
        return self._request("POST", "/buyer-orders", payload, headers)

    def get_buyer_order(self, order_id, headers):
        return self._request("GET", f"/buyer-orders/{order_id}", headers=headers)

    def list_buyer_orders(self, headers, params=None):
        return self._request("GET", "/buyer-orders", headers=headers, params=params)

    def create_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/buyer-orders/{order_id}/lines", payload, headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/buyer-orders/{order_id}/lines", headers=headers, params=params
        )

    def aggregate_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/buyer-orders/{order_id}/aggregation", payload or {}, headers
        )

    def invoice_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/buyer-orders/{order_id}/invoice", payload or {}, headers
        )

    def create_payment(self, order_id, payload, headers):
        return self._request(
            "POST", f"/buyer-orders/{order_id}/payments", payload, headers
        )

    def record_delivery(self, order_id, payload, headers):
        return self._request(
            "POST", f"/buyer-orders/{order_id}/delivery-record", payload, headers
        )

    # ---------------- Allocations ----------------
    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/allocations/{allocation_id}", headers=headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/allocations", headers=headers, params=params)

    def list_allocation_rejection_claims(self, allocation_id, headers, params=None):
        return self._request(
            "GET",
            f"/allocations/{allocation_id}/rejection-claims",
            headers=headers,
            params=params,
        )

    # ---------------- Cross-dock & cold storage ----------------
    def create_dock_slot(self, payload, headers):
        return self._request("POST", "/dock-slots", payload, headers)

    def get_dock_slot(self, dock_slot_id, headers):
        return self._request("GET", f"/dock-slots/{dock_slot_id}", headers=headers)

    def create_dock_appointment(self, payload, headers):
        return self._request("POST", "/dock-appointments", payload, headers)

    def get_dock_appointment(self, appointment_id, headers):
        return self._request(
            "GET", f"/dock-appointments/{appointment_id}", headers=headers
        )

    def list_dock_appointments(self, headers, params=None):
        return self._request("GET", "/dock-appointments", headers=headers, params=params)

    def close_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/dock-appointments/{appointment_id}/receipt", payload, headers
        )

    # ---------------- Delivery routing ----------------
    def create_delivery_route(self, payload, headers):
        return self._request("POST", "/delivery-routes", payload, headers)

    def get_delivery_route(self, route_id, headers):
        return self._request("GET", f"/delivery-routes/{route_id}", headers=headers)

    def create_route_stop(self, route_id, payload, headers):
        return self._request(
            "POST", f"/delivery-routes/{route_id}/stops", payload, headers
        )

    def dispatch_route(self, route_id, headers, payload=None):
        return self._request(
            "POST", f"/delivery-routes/{route_id}/dispatch", payload or {}, headers
        )

    # ---------------- Shrink / rejection ----------------
    def create_rejection_claim(self, payload, headers):
        return self._request("POST", "/rejection-claims", payload, headers)

    def adjudicate_rejection_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/rejection-claims/{claim_id}/adjudication", payload, headers
        )

    # ---------------- Member equity & governance ----------------
    def create_patronage_cycle(self, payload, headers):
        return self._request("POST", "/patronage-cycles", payload, headers)

    def get_patronage_cycle(self, cycle_id, headers):
        return self._request("GET", f"/patronage-cycles/{cycle_id}", headers=headers)

    def ratify_patronage_cycle(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/patronage-cycles/{cycle_id}/ratification", payload, headers
        )

    def distribute_patronage_cycle(self, cycle_id, headers, payload=None):
        return self._request(
            "POST", f"/patronage-cycles/{cycle_id}/distribution", payload or {}, headers
        )

    # ---------------- Logical clock ----------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
