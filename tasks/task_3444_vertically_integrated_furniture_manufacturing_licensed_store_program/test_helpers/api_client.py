"""API client: one method per endpoint defined in PRD §4.

PRD §2.5: "This clock endpoint deliberately lives outside the /api mount that
hosts every other endpoint." — set_clock therefore targets the UNPREFIXED path
/_clock/set_current_utc; every other method lives under /api.
"""
from prd_bench_local_runner.testing import GenericApiClient

API = "/api"


class ApiClient(GenericApiClient):
    # ---- logical clock (UNPREFIXED — outside the /api mount, PRD §2.5) ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- factories ------------------------------------------------------
    def create_factory(self, payload, headers):
        return self._request("POST", f"{API}/factories", payload, headers)

    def get_factory(self, factory_id, headers):
        return self._request("GET", f"{API}/factories/{factory_id}", headers=headers)

    def transition_factory(self, factory_id, payload, headers):
        return self._request(
            "POST", f"{API}/factories/{factory_id}/transition", payload, headers
        )

    # ---- product lines ----------------------------------------------------
    def create_product_line(self, payload, headers):
        return self._request("POST", f"{API}/product-lines", payload, headers)

    def get_product_line(self, line_id, headers):
        return self._request(
            "GET", f"{API}/product-lines/{line_id}", headers=headers
        )

    def advance_product_line(self, line_id, headers):
        return self._request(
            "POST", f"{API}/product-lines/{line_id}/advance", {}, headers
        )

    def update_product_line_price(self, line_id, payload, headers):
        return self._request(
            "PUT", f"{API}/product-lines/{line_id}/price", payload, headers
        )

    # ---- licensees --------------------------------------------------------
    def create_licensee(self, payload, headers):
        return self._request("POST", f"{API}/licensees", payload, headers)

    def get_licensee(self, licensee_id, headers):
        return self._request("GET", f"{API}/licensees/{licensee_id}", headers=headers)

    def update_licensee_terms(self, licensee_id, payload, headers):
        return self._request(
            "PUT", f"{API}/licensees/{licensee_id}/terms", payload, headers
        )

    def transition_licensee(self, licensee_id, payload, headers):
        return self._request(
            "POST", f"{API}/licensees/{licensee_id}/transition", payload, headers
        )

    def list_licensee_territories(self, licensee_id, headers, params=None):
        return self._request(
            "GET",
            f"{API}/licensees/{licensee_id}/territories",
            headers=headers,
            params=params,
        )

    # ---- territories --------------------------------------------------------
    def create_territory(self, payload, headers):
        return self._request("POST", f"{API}/territories", payload, headers)

    def get_territory(self, territory_id, headers):
        return self._request(
            "GET", f"{API}/territories/{territory_id}", headers=headers
        )

    def transition_territory(self, territory_id, payload, headers):
        return self._request(
            "POST", f"{API}/territories/{territory_id}/transition", payload, headers
        )

    # ---- retail accounts ----------------------------------------------------
    def create_retail_account(self, payload, headers):
        return self._request("POST", f"{API}/retail-accounts", payload, headers)

    def get_retail_account(self, account_id, headers):
        return self._request(
            "GET", f"{API}/retail-accounts/{account_id}", headers=headers
        )

    def transition_retail_account(self, account_id, payload, headers):
        return self._request(
            "POST", f"{API}/retail-accounts/{account_id}/transition", payload, headers
        )

    # ---- distribution centers ------------------------------------------------
    def create_distribution_center(self, payload, headers):
        return self._request("POST", f"{API}/distribution-centers", payload, headers)

    def get_distribution_center(self, dc_id, headers):
        return self._request(
            "GET", f"{API}/distribution-centers/{dc_id}", headers=headers
        )

    # ---- allocation cycles -----------------------------------------------------
    def create_allocation_cycle(self, payload, headers):
        return self._request("POST", f"{API}/allocation-cycles", payload, headers)

    def get_allocation_cycle(self, cycle_id, headers):
        return self._request(
            "GET", f"{API}/allocation-cycles/{cycle_id}", headers=headers
        )

    def list_allocation_cycles(self, headers, params=None):
        return self._request(
            "GET", f"{API}/allocation-cycles", headers=headers, params=params
        )

    def run_allocation(self, cycle_id, headers):
        return self._request(
            "POST", f"{API}/allocation-cycles/{cycle_id}/run-allocation", {}, headers
        )

    def close_cycle(self, cycle_id, headers):
        return self._request(
            "POST", f"{API}/allocation-cycles/{cycle_id}/close", {}, headers
        )

    # ---- supply orders -----------------------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", f"{API}/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"{API}/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", f"{API}/orders", headers=headers, params=params)

    def transition_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{API}/orders/{order_id}/transition", payload, headers
        )

    # ---- delivery appointments -----------------------------------------------------
    def create_delivery_appointment(self, payload, headers):
        return self._request("POST", f"{API}/delivery-appointments", payload, headers)

    def get_delivery_appointment(self, appointment_id, headers):
        return self._request(
            "GET", f"{API}/delivery-appointments/{appointment_id}", headers=headers
        )

    def list_delivery_appointments(self, headers, params=None):
        return self._request(
            "GET", f"{API}/delivery-appointments", headers=headers, params=params
        )

    def transition_delivery_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST",
            f"{API}/delivery-appointments/{appointment_id}/transition",
            payload,
            headers,
        )

    # ---- warranty claims -------------------------------------------------------------
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", f"{API}/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request(
            "GET", f"{API}/warranty-claims/{claim_id}", headers=headers
        )

    def list_warranty_claims(self, headers, params=None):
        return self._request(
            "GET", f"{API}/warranty-claims", headers=headers, params=params
        )

    def transition_warranty_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{API}/warranty-claims/{claim_id}/transition", payload, headers
        )

    # ---- parts orders -------------------------------------------------------------------
    def get_parts_order(self, parts_order_id, headers):
        return self._request(
            "GET", f"{API}/parts-orders/{parts_order_id}", headers=headers
        )

    def list_parts_orders(self, headers, params=None):
        return self._request("GET", f"{API}/parts-orders", headers=headers, params=params)

    def transition_parts_order(self, parts_order_id, payload, headers):
        return self._request(
            "POST", f"{API}/parts-orders/{parts_order_id}/transition", payload, headers
        )


api_client = ApiClient()
