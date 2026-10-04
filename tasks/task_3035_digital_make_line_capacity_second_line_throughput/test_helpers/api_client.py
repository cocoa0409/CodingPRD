"""HTTP client for the Digital Makeline Capacity API.

One method per declared endpoint. Every method returns the raw response so a
test can assert on the status code as well as the body. Query filters and
pagination are passed as ``params``; request bodies as ``payload``.

Every route in this contract is mounted under the ``/api/v1`` prefix, so each
method prepends it.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


PREFIX = "/api/v1"


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant so two spellings of one instant match.

    The contract renders instants with three fractional digits, but an equal
    instant may legitimately arrive with none, with fewer digits, or with
    trailing zeroes. Comparisons therefore run on the canonical form —
    ``YYYY-MM-DDTHH:MM:SS.mmmZ`` — instead of on the raw strings, so that
    ``2026-09-01T10:30:00Z`` and ``2026-09-01T10:30:00.000Z`` compare equal.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text[10:]:
        text = text[: 10 + text[10:].index("+")]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = text, "000"
    return f"{head}.{frac}Z"


class ApiClient(GenericApiClient):
    """Endpoint methods for every route the contract declares."""

    # ── Logical clock ──────────────────────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ── Stores ─────────────────────────────────────────────────────────────

    def create_store(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/stores", payload, headers)

    def get_store(self, store_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/stores/{store_id}", None, headers)

    def list_stores(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/stores", None, headers, params=params)

    # ── Ingredients and batches ────────────────────────────────────────────

    def create_ingredient(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/ingredients", payload, headers)

    def get_ingredient(self, ingredient_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/ingredients/{ingredient_id}", None, headers)

    def list_ingredients(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/ingredients", None, headers, params=params)

    def create_batch(
        self, ingredient_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/ingredients/{ingredient_id}/batches", payload, headers)

    def list_batches_for_ingredient(
        self, ingredient_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/ingredients/{ingredient_id}/batches", None, headers, params=params
        )

    def get_batch(self, batch_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/batches/{batch_id}", None, headers)

    def list_batches(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/batches", None, headers, params=params)

    # ── Menu items and recipe components ───────────────────────────────────

    def create_menu_item(
        self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/stores/{store_id}/menu-items", payload, headers)

    def list_menu_items_for_store(
        self, store_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/stores/{store_id}/menu-items", None, headers, params=params
        )

    def get_menu_item(self, menu_item_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/menu-items/{menu_item_id}", None, headers)

    def list_menu_items(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/menu-items", None, headers, params=params)

    def create_recipe_component(
        self, menu_item_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/menu-items/{menu_item_id}/recipe-components", payload, headers
        )

    def list_recipe_components_for_item(
        self, menu_item_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/menu-items/{menu_item_id}/recipe-components",
            None,
            headers,
            params=params,
        )

    def list_recipe_components(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/recipe-components", None, headers, params=params)

    def get_recipe_component(self, component_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/recipe-components/{component_id}", None, headers)

    # ── Marketplace channels ───────────────────────────────────────────────

    def create_marketplace_channel(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/marketplace-channels", payload, headers)

    def list_marketplace_channels(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/marketplace-channels", None, headers, params=params)

    def get_marketplace_channel(self, channel_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/marketplace-channels/{channel_id}", None, headers)

    # ── Production windows ─────────────────────────────────────────────────

    def create_production_window(
        self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/stores/{store_id}/production-windows", payload, headers
        )

    def list_production_windows_for_store(
        self, store_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/stores/{store_id}/production-windows", None, headers, params=params
        )

    def get_production_window(self, window_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/production-windows/{window_id}", None, headers)

    def list_production_windows(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/production-windows", None, headers, params=params)

    # ── Orders ─────────────────────────────────────────────────────────────

    def create_order(
        self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/stores/{store_id}/orders", payload, headers)

    def list_orders_for_store(
        self, store_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/stores/{store_id}/orders", None, headers, params=params)

    def get_order(self, order_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/orders/{order_id}", None, headers)

    def list_orders(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/orders", None, headers, params=params)

    def list_order_lines(
        self, order_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/orders/{order_id}/lines", None, headers, params=params)

    def list_order_lines_filtered(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/order-lines", None, headers, params=params)

    def get_order_line(self, line_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/order-lines/{line_id}", None, headers)

    def start_production(
        self, store_id: str, order_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/stores/{store_id}/orders/{order_id}/start-production", {}, headers
        )

    def verify_accuracy(
        self, store_id: str, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/stores/{store_id}/orders/{order_id}/verify-accuracy", payload, headers
        )

    def mark_ready(
        self, store_id: str, order_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/stores/{store_id}/orders/{order_id}/mark-ready", {}, headers
        )

    def pickup_order(
        self, store_id: str, order_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/stores/{store_id}/orders/{order_id}/pickup", {}, headers
        )

    def cancel_order(
        self, store_id: str, order_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/stores/{store_id}/orders/{order_id}/cancel", {}, headers
        )

    # ── Accuracy verifications ─────────────────────────────────────────────

    def list_verifications_for_order(
        self, order_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/orders/{order_id}/verifications", None, headers, params=params
        )

    def list_verifications(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/verifications", None, headers, params=params)

    def get_verification(self, verification_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/verifications/{verification_id}", None, headers)

    # ── Staffing deployments ───────────────────────────────────────────────

    def create_deployment(
        self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/stores/{store_id}/staffing-deployments", payload, headers
        )

    def list_deployments_for_store(
        self, store_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/stores/{store_id}/staffing-deployments", None, headers, params=params
        )

    def get_deployment(self, deployment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/staffing-deployments/{deployment_id}", None, headers)

    def list_deployments(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/staffing-deployments", None, headers, params=params)

    def publish_deployment(
        self, store_id: str, deployment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/stores/{store_id}/staffing-deployments/{deployment_id}/publish",
            {},
            headers,
        )

    def lock_deployment(
        self, store_id: str, deployment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/stores/{store_id}/staffing-deployments/{deployment_id}/lock",
            {},
            headers,
        )

    # ── Suppression events ─────────────────────────────────────────────────

    def list_suppression_events_for_store(
        self, store_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/stores/{store_id}/suppression-events", None, headers, params=params
        )

    def get_suppression_event(self, event_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/suppression-events/{event_id}", None, headers)

    def list_suppression_events(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/suppression-events", None, headers, params=params)

    def resolve_suppression_event(
        self, store_id: str, event_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/stores/{store_id}/suppression-events/{event_id}/resolve",
            {},
            headers,
        )

    # ── Waste events ───────────────────────────────────────────────────────

    def create_waste_event(
        self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/stores/{store_id}/waste-events", payload, headers)

    def list_waste_events_for_store(
        self, store_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/stores/{store_id}/waste-events", None, headers, params=params
        )

    def list_waste_events(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/waste-events", None, headers, params=params)

    def get_waste_event(self, waste_event_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/waste-events/{waste_event_id}", None, headers)

    # ── Day close ──────────────────────────────────────────────────────────

    def close_day(
        self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/stores/{store_id}/day-close", payload, headers)

    def list_day_closes_for_store(
        self, store_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/stores/{store_id}/day-closes", None, headers, params=params
        )

    def list_day_closes(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/day-closes", None, headers, params=params)

    def get_day_close(self, day_close_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/day-closes/{day_close_id}", None, headers)

    # ── Raw request escape hatch ───────────────────────────────────────────

    def raw(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Send an arbitrary request, for probes that need a route by hand."""
        return self._request(method, f"{PREFIX}{path}", payload, headers)


api_client = ApiClient()
