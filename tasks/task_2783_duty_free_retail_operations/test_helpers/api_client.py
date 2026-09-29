"""One method per endpoint of PRD section 4.

Every collection sits at the URL root, so each method is a thin, explicit wrapper:
the path, the verb and the body shape are what the PRD declares, and nothing is
computed here. Responses are returned raw so tests can assert status codes.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class DutyFreeApiClient(GenericApiClient):
    """HTTP client for the Duty-Free Retail Operations API."""

    # ------------------------------------------------------------------
    # The logical clock (PRD 2.4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Terminals (PRD 3.1)
    # ------------------------------------------------------------------
    def create_terminal(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/terminals", payload, headers)

    def get_terminal(self, terminal_id: str, headers) -> requests.Response:
        return self._request("GET", f"/terminals/{terminal_id}", None, headers)

    def list_terminals(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/terminals", None, headers, params)

    def get_nationality_mix(self, terminal_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"/terminals/{terminal_id}/nationality-mix", None, headers
        )

    # ------------------------------------------------------------------
    # Brands (PRD 3.1)
    # ------------------------------------------------------------------
    def create_brand(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/brands", payload, headers)

    def get_brand(self, brand_id: str, headers) -> requests.Response:
        return self._request("GET", f"/brands/{brand_id}", None, headers)

    def list_brands(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/brands", None, headers, params)

    def suspend_brand(self, brand_id: str, headers) -> requests.Response:
        return self._request("POST", f"/brands/{brand_id}/suspend", {}, headers)

    # ------------------------------------------------------------------
    # Arrival-allowance rules (PRD 3.1)
    # ------------------------------------------------------------------
    def create_allowance_rule(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/allowance-rules", payload, headers)

    def get_allowance_rule(self, allowance_rule_id: str, headers) -> requests.Response:
        return self._request("GET", f"/allowance-rules/{allowance_rule_id}", None, headers)

    def list_allowance_rules(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/allowance-rules", None, headers, params)

    # ------------------------------------------------------------------
    # Exclusivity grants (PRD 3.1)
    # ------------------------------------------------------------------
    def create_grant(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/exclusivity-grants", payload, headers)

    def get_grant(self, grant_id: str, headers) -> requests.Response:
        return self._request("GET", f"/exclusivity-grants/{grant_id}", None, headers)

    def list_grants(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/exclusivity-grants", None, headers, params)

    def revoke_grant(self, grant_id: str, headers) -> requests.Response:
        return self._request("POST", f"/exclusivity-grants/{grant_id}/revoke", {}, headers)

    # ------------------------------------------------------------------
    # Products (PRD 3.2)
    # ------------------------------------------------------------------
    def create_product(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id: str, headers) -> requests.Response:
        return self._request("GET", f"/products/{product_id}", None, headers)

    def list_products(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/products", None, headers, params)

    def list_product(self, product_id: str, headers) -> requests.Response:
        """Admit a product into the assortment (POST /products/{id}/list)."""
        return self._request("POST", f"/products/{product_id}/list", {}, headers)

    # ------------------------------------------------------------------
    # Bonded stock items and movements (PRD 3.3)
    # ------------------------------------------------------------------
    def create_stock_item(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/bonded-stock-items", payload, headers)

    def get_stock_item(self, stock_item_id: str, headers) -> requests.Response:
        return self._request("GET", f"/bonded-stock-items/{stock_item_id}", None, headers)

    def list_stock_items(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/bonded-stock-items", None, headers, params)

    def create_movement(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/bonded-movements", payload, headers)

    def get_movement(self, movement_id: str, headers) -> requests.Response:
        return self._request("GET", f"/bonded-movements/{movement_id}", None, headers)

    def list_movements(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/bonded-movements", None, headers, params)

    def reverse_movement(self, movement_id: str, headers) -> requests.Response:
        return self._request("POST", f"/bonded-movements/{movement_id}/reverse", {}, headers)

    # ------------------------------------------------------------------
    # Passenger itineraries (PRD 3.4)
    # ------------------------------------------------------------------
    def create_itinerary(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/itineraries", payload, headers)

    def get_itinerary(self, itinerary_id: str, headers) -> requests.Response:
        return self._request("GET", f"/itineraries/{itinerary_id}", None, headers)

    def list_itineraries(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/itineraries", None, headers, params)

    def scan_boarding_pass(self, itinerary_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"/itineraries/{itinerary_id}/scan-boarding-pass", payload, headers
        )

    def amend_itinerary(self, itinerary_id: str, payload: Dict[str, Any], headers):
        return self._request("POST", f"/itineraries/{itinerary_id}/amend", payload, headers)

    # ------------------------------------------------------------------
    # Sales and sale lines (PRD 3.5, 3.7)
    # ------------------------------------------------------------------
    def create_sale(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/sales", payload, headers)

    def get_sale(self, sale_id: str, headers) -> requests.Response:
        return self._request("GET", f"/sales/{sale_id}", None, headers)

    def list_sales(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/sales", None, headers, params)

    def add_sale_line(self, sale_id: str, payload: Dict[str, Any], headers):
        return self._request("POST", f"/sales/{sale_id}/lines", payload, headers)

    def get_sale_line(self, sale_line_id: str, headers) -> requests.Response:
        return self._request("GET", f"/sale-lines/{sale_line_id}", None, headers)

    def list_sale_lines(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/sale-lines", None, headers, params)

    def clear_eligibility(self, sale_id: str, headers) -> requests.Response:
        return self._request("POST", f"/sales/{sale_id}/clear-eligibility", {}, headers)

    def pickup_sale(self, sale_id: str, headers) -> requests.Response:
        return self._request("POST", f"/sales/{sale_id}/pickup", {}, headers)

    def void_sale(self, sale_id: str, headers) -> requests.Response:
        return self._request("POST", f"/sales/{sale_id}/void", {}, headers)

    # ------------------------------------------------------------------
    # Sealed bags (PRD 3.6)
    # ------------------------------------------------------------------
    def create_sealed_bag(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/sealed-bags", payload, headers)

    def get_sealed_bag(self, sealed_bag_id: str, headers) -> requests.Response:
        return self._request("GET", f"/sealed-bags/{sealed_bag_id}", None, headers)

    def list_sealed_bags(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/sealed-bags", None, headers, params)

    def verify_sealed_bag(self, sealed_bag_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"/sealed-bags/{sealed_bag_id}/verify", payload, headers
        )

    # ------------------------------------------------------------------
    # Pre-orders (PRD 3.8)
    # ------------------------------------------------------------------
    def create_pre_order(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/pre-orders", payload, headers)

    def get_pre_order(self, pre_order_id: str, headers) -> requests.Response:
        return self._request("GET", f"/pre-orders/{pre_order_id}", None, headers)

    def list_pre_orders(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/pre-orders", None, headers, params)

    def convert_pre_order(self, pre_order_id: str, headers) -> requests.Response:
        return self._request("POST", f"/pre-orders/{pre_order_id}/convert", {}, headers)

    def cancel_pre_order(self, pre_order_id: str, headers) -> requests.Response:
        return self._request("POST", f"/pre-orders/{pre_order_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Concession agreements (PRD 3.10)
    # ------------------------------------------------------------------
    def create_agreement(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/concession-agreements", payload, headers)

    def get_agreement(self, agreement_id: str, headers) -> requests.Response:
        return self._request("GET", f"/concession-agreements/{agreement_id}", None, headers)

    def list_agreements(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/concession-agreements", None, headers, params)

    def activate_agreement(self, agreement_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"/concession-agreements/{agreement_id}/activate", {}, headers
        )

    def close_agreement_period(self, agreement_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"/concession-agreements/{agreement_id}/close-period", {}, headers
        )

    def get_rent_projection(self, agreement_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"/concession-agreements/{agreement_id}/rent-projection", None, headers
        )

    # ------------------------------------------------------------------
    # Customs audits (PRD 3.9)
    # ------------------------------------------------------------------
    def create_audit(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/customs-audits", payload, headers)

    def get_audit(self, audit_id: str, headers) -> requests.Response:
        return self._request("GET", f"/customs-audits/{audit_id}", None, headers)

    def list_audits(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/customs-audits", None, headers, params)

    def submit_audit(self, audit_id: str, payload: Dict[str, Any], headers):
        return self._request("POST", f"/customs-audits/{audit_id}/submit", payload, headers)

    def request_audit_info(self, audit_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"/customs-audits/{audit_id}/request-info", payload, headers
        )

    def close_audit(self, audit_id: str, headers) -> requests.Response:
        return self._request("POST", f"/customs-audits/{audit_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Raw escape hatches, for probes the PRD declares no route for
    # ------------------------------------------------------------------
    def raw_request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(method, path, payload, headers)
