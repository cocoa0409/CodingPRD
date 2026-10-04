"""HTTP client for the Toy Licensing API.

One method per endpoint declared in PRD §4. Every method returns the raw
response so a test can assert on status code as well as body. All endpoints
are mounted under ``/toy-licensing``.
"""
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/toy-licensing"


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant so two spellings of one instant match.

    The contract renders instants in ISO 8601 UTC with three fractional
    digits; an equal instant may legitimately arrive without the fractional
    part. Comparisons therefore run on a canonical
    ``YYYY-MM-DDTHH:MM:SS.mmmZ`` form so that ``2026-10-01T00:00:00Z`` and
    ``2026-10-01T00:00:00.000Z`` compare equal.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if len(text) > 10 and "+" in text[10:]:
        text = text[: 10 + text[10:].index("+")]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = text, "000"
    return f"{head}.{frac}Z"


class ApiClient(GenericApiClient):
    """Endpoint methods for every route the contract declares."""

    # ── Logical clock ────────────────────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ── Studios ──────────────────────────────────────────────────────────

    def create_studio(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/studios", payload, headers)

    def get_studio(self, studio_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/studios/{studio_id}", headers=headers)

    # ── Properties ───────────────────────────────────────────────────────

    def create_property(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/properties", payload, headers)

    def get_property(self, property_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/properties/{property_id}", headers=headers)

    def list_properties(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/properties", headers=headers, params=params)

    def shift_release(self, property_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/properties/{property_id}/shift_release", payload, headers)

    # ── License agreements ───────────────────────────────────────────────

    def create_license_agreement(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/license-agreements", payload, headers)

    def get_license_agreement(self, agreement_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/license-agreements/{agreement_id}", headers=headers)

    def list_license_agreements(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/license-agreements", headers=headers, params=params)

    def activate_license_agreement(self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/license-agreements/{agreement_id}/activate", payload, headers)

    def amend_license_agreement(self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/license-agreements/{agreement_id}/amend", payload, headers)

    def approve_amendment(self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/license-agreements/{agreement_id}/amendments/approve", payload, headers)

    def reject_amendment(self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/license-agreements/{agreement_id}/amendments/reject", payload, headers)

    def close_quarter(self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/license-agreements/{agreement_id}/close_quarter", payload, headers)

    def royalty_projection(self, agreement_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/license-agreements/{agreement_id}/royalty_projection", headers=headers)

    # ── Toy lines ────────────────────────────────────────────────────────

    def create_toy_line(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/toy-lines", payload, headers)

    def get_toy_line(self, line_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/toy-lines/{line_id}", headers=headers)

    def list_toy_lines(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/toy-lines", headers=headers, params=params)

    def advance_toy_line(self, line_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/toy-lines/{line_id}/advance", payload, headers)

    def revert_toy_line(self, line_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/toy-lines/{line_id}/revert", payload, headers)

    def enter_closeout(self, line_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/toy-lines/{line_id}/enter_closeout", payload, headers)

    def exit_closeout(self, line_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/toy-lines/{line_id}/exit_closeout", payload, headers)

    def retire_toy_line(self, line_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/toy-lines/{line_id}/retire", payload, headers)

    # ── SKUs ─────────────────────────────────────────────────────────────

    def create_sku(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/skus", payload, headers)

    def get_sku(self, sku_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/skus/{sku_id}", headers=headers)

    def list_skus(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/skus", headers=headers, params=params)

    def patch_sku(self, sku_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("PATCH", f"{PREFIX}/skus/{sku_id}", payload, headers)

    # ── Factories ────────────────────────────────────────────────────────

    def create_factory(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/factories", payload, headers)

    def get_factory(self, factory_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/factories/{factory_id}", headers=headers)

    # ── Tooling orders ───────────────────────────────────────────────────

    def create_tooling_order(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/tooling-orders", payload, headers)

    def get_tooling_order(self, order_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/tooling-orders/{order_id}", headers=headers)

    def list_tooling_orders(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/tooling-orders", headers=headers, params=params)

    def scrap_tooling_order(self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/tooling-orders/{order_id}/scrap", payload, headers)

    def complete_tooling_order(self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/tooling-orders/{order_id}/complete", payload, headers)

    # ── Retailers ────────────────────────────────────────────────────────

    def create_retailer(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/retailers", payload, headers)

    def get_retailer(self, retailer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/retailers/{retailer_id}", headers=headers)

    # ── Line reviews ─────────────────────────────────────────────────────

    def create_line_review(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/line-reviews", payload, headers)

    def approve_line_review(self, review_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/line-reviews/{review_id}/approve", payload, headers)

    def get_line_review(self, review_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/line-reviews/{review_id}", headers=headers)

    def list_line_reviews(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/line-reviews", headers=headers, params=params)

    # ── Assortment commitments ───────────────────────────────────────────

    def create_commitment(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/assortment-commitments", payload, headers)

    def get_commitment(self, commitment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/assortment-commitments/{commitment_id}", headers=headers)

    def list_commitments(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/assortment-commitments", headers=headers, params=params)

    def cancel_commitment(self, commitment_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/assortment-commitments/{commitment_id}/cancel", payload, headers)

    def reinstate_commitment(self, commitment_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/assortment-commitments/{commitment_id}/reinstate", payload, headers)

    # ── Shipments ────────────────────────────────────────────────────────

    def create_shipment(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/shipments", payload, headers)

    def get_shipment(self, shipment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/shipments", headers=headers, params=params)

    def record_sale(self, shipment_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/shipments/{shipment_id}/record_sale", payload, headers)

    def waive_penalty(self, shipment_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/shipments/{shipment_id}/waive_penalty", payload, headers)

    # ── Safety tests ─────────────────────────────────────────────────────

    def create_safety_test(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/safety-tests", payload, headers)

    def get_safety_test(self, test_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/safety-tests/{test_id}", headers=headers)

    def list_safety_tests(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/safety-tests", headers=headers, params=params)

    def record_safety_result(self, test_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/safety-tests/{test_id}/record_result", payload, headers)


api_client = ApiClient()
