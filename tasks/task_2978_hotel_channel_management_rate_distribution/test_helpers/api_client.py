"""HTTP client for the Hotel Channel Distribution API.

One method per declared endpoint. Every method returns the raw response so a
test can assert on the status code as well as on the body. Query filters and
pagination go through ``params``; request bodies through ``payload``.

Every route is mounted under ``/distribution`` except the clock-setting route,
which the contract places outside that mount.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

# Transition endpoints take no body; an empty object is what "no body" means on
# the wire, so every such call sends one.
NO_BODY: Dict[str, Any] = {}


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant so two spellings of one instant match.

    The contract renders instants with exactly three fractional digits, but an
    equal instant may legitimately arrive with none, with fewer digits, or with
    trailing zeroes. Comparisons therefore run on the canonical form -
    ``YYYY-MM-DDTHH:MM:SS.mmmZ`` - instead of on the raw strings, so that
    ``2026-08-01T00:00:00Z`` and ``2026-08-01T00:00:00.000Z`` compare equal.
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
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Properties ─────────────────────────────────────────────────────────

    def create_property(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/distribution/properties", payload, headers)

    def list_properties(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/distribution/properties", params, headers)

    def get_property(self, property_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/distribution/properties/{property_id}", None, headers)

    def get_channel_mix(
        self, property_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/distribution/properties/{property_id}/channel-mix", params, headers
        )

    # ── Room types ─────────────────────────────────────────────────────────

    def create_room_type(
        self, property_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/distribution/properties/{property_id}/room-types", payload, headers
        )

    def patch_room_type(
        self, room_type_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"/distribution/room-types/{room_type_id}", payload, headers)

    def list_room_types(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/distribution/room-types", params, headers)

    def get_room_type(self, room_type_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/distribution/room-types/{room_type_id}", None, headers)

    def get_pace(
        self, room_type_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/distribution/room-types/{room_type_id}/pace", params, headers)

    # ── Inventory days ─────────────────────────────────────────────────────

    def create_inventory_day(
        self, room_type_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/distribution/room-types/{room_type_id}/inventory-days", payload, headers
        )

    def list_inventory_days(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/distribution/inventory-days", params, headers)

    def get_inventory_day(self, inventory_day_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"/distribution/inventory-days/{inventory_day_id}", None, headers
        )

    # ── Channels ───────────────────────────────────────────────────────────

    def create_channel(
        self, property_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/distribution/properties/{property_id}/channels", payload, headers
        )

    def list_channels(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/distribution/channels", params, headers)

    def get_channel(self, channel_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/distribution/channels/{channel_id}", None, headers)

    def get_channel_performance(
        self, channel_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/distribution/channels/{channel_id}/performance", params, headers
        )

    # ── Channel connections ────────────────────────────────────────────────

    def create_connection(
        self, channel_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/distribution/channels/{channel_id}/connections", payload, headers
        )

    def activate_connection(
        self, connection_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/distribution/channel-connections/{connection_id}/activate",
            NO_BODY if payload is None else payload,
            headers,
        )

    def record_heartbeat(
        self, connection_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/distribution/channel-connections/{connection_id}/heartbeats", payload, headers
        )

    def revalidate_connection(
        self, connection_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/distribution/channel-connections/{connection_id}/revalidate",
            NO_BODY if payload is None else payload,
            headers,
        )

    def retire_connection(
        self, connection_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/distribution/channel-connections/{connection_id}/retire",
            NO_BODY if payload is None else payload,
            headers,
        )

    def create_freeze_window(
        self, connection_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/distribution/channel-connections/{connection_id}/freeze-windows",
            payload,
            headers,
        )

    def list_connections(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/distribution/channel-connections", params, headers)

    def get_connection(self, connection_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"/distribution/channel-connections/{connection_id}", None, headers
        )

    def list_freeze_windows(
        self, connection_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/distribution/channel-connections/{connection_id}/freeze-windows",
            params,
            headers,
        )

    # ── Rate plans ─────────────────────────────────────────────────────────

    def create_rate_plan(
        self, property_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/distribution/properties/{property_id}/rate-plans", payload, headers
        )

    def activate_rate_plan(
        self, rate_plan_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/distribution/rate-plans/{rate_plan_id}/activate",
            NO_BODY if payload is None else payload,
            headers,
        )

    def patch_rate_plan(
        self, rate_plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"/distribution/rate-plans/{rate_plan_id}", payload, headers)

    def close_rate_plan(
        self, rate_plan_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/distribution/rate-plans/{rate_plan_id}/close",
            NO_BODY if payload is None else payload,
            headers,
        )

    def list_rate_plans(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/distribution/rate-plans", params, headers)

    def get_rate_plan(self, rate_plan_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/distribution/rate-plans/{rate_plan_id}", None, headers)

    # ── Channel mappings ───────────────────────────────────────────────────

    def create_mapping(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/distribution/channel-mappings", payload, headers)

    def verify_mapping(
        self, mapping_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/distribution/channel-mappings/{mapping_id}/verify",
            NO_BODY if payload is None else payload,
            headers,
        )

    def disable_mapping(
        self, mapping_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/distribution/channel-mappings/{mapping_id}/disable",
            NO_BODY if payload is None else payload,
            headers,
        )

    def patch_mapping_content(
        self, mapping_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PATCH", f"/distribution/channel-mappings/{mapping_id}/content", payload, headers
        )

    def record_observed_rate(
        self, mapping_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/distribution/channel-mappings/{mapping_id}/observed-rates", payload, headers
        )

    def list_mappings(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/distribution/channel-mappings", params, headers)

    def get_mapping(self, mapping_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/distribution/channel-mappings/{mapping_id}", None, headers)

    def get_quoted_rate(
        self, mapping_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/distribution/channel-mappings/{mapping_id}/quoted-rate", params, headers
        )

    # ── Allotments ─────────────────────────────────────────────────────────

    def create_allocation(
        self, room_type_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/distribution/room-types/{room_type_id}/allocations", payload, headers
        )

    def release_allocation(
        self, allocation_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/distribution/allocations/{allocation_id}/release",
            NO_BODY if payload is None else payload,
            headers,
        )

    def list_allocations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/distribution/allocations", params, headers)

    def get_allocation(self, allocation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/distribution/allocations/{allocation_id}", None, headers)

    # ── Restrictions ───────────────────────────────────────────────────────

    def create_restriction(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/distribution/restrictions", payload, headers)

    def lift_restriction(
        self, restriction_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/distribution/restrictions/{restriction_id}/lift",
            NO_BODY if payload is None else payload,
            headers,
        )

    def list_restrictions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/distribution/restrictions", params, headers)

    def get_restriction(self, restriction_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/distribution/restrictions/{restriction_id}", None, headers)

    # ── Promotions ─────────────────────────────────────────────────────────

    def create_promotion(
        self, rate_plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/distribution/rate-plans/{rate_plan_id}/promotions", payload, headers
        )

    def submit_promotion(
        self, promotion_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/distribution/promotions/{promotion_id}/submit",
            NO_BODY if payload is None else payload,
            headers,
        )

    def approve_promotion(
        self, promotion_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/distribution/promotions/{promotion_id}/approve",
            NO_BODY if payload is None else payload,
            headers,
        )

    def reject_promotion(
        self, promotion_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/distribution/promotions/{promotion_id}/reject",
            NO_BODY if payload is None else payload,
            headers,
        )

    def revise_promotion(
        self, promotion_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/distribution/promotions/{promotion_id}/revise",
            NO_BODY if payload is None else payload,
            headers,
        )

    def load_promotion(
        self, promotion_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/distribution/promotions/{promotion_id}/load",
            NO_BODY if payload is None else payload,
            headers,
        )

    def list_promotions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/distribution/promotions", params, headers)

    def get_promotion(self, promotion_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/distribution/promotions/{promotion_id}", None, headers)

    # ── Distribution batches and jobs ──────────────────────────────────────

    def dispatch_batch(
        self, batch_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/distribution/distribution-batches/{batch_id}/dispatch",
            NO_BODY if payload is None else payload,
            headers,
        )

    def retry_job(
        self, job_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/distribution/distribution-jobs/{job_id}/retry",
            NO_BODY if payload is None else payload,
            headers,
        )

    def list_batches(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/distribution/distribution-batches", params, headers)

    def get_batch(self, batch_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/distribution/distribution-batches/{batch_id}", None, headers)

    def list_jobs(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/distribution/distribution-jobs", params, headers)

    def get_job(self, job_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/distribution/distribution-jobs/{job_id}", None, headers)

    # ── Reservations ───────────────────────────────────────────────────────

    def create_reservation(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/distribution/reservations", payload, headers)

    def cancel_reservation(
        self, reservation_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/distribution/reservations/{reservation_id}/cancel",
            NO_BODY if payload is None else payload,
            headers,
        )

    def list_reservations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/distribution/reservations", params, headers)

    def get_reservation(self, reservation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/distribution/reservations/{reservation_id}", None, headers)

    # ── Raw request escape hatch ───────────────────────────────────────────

    def raw(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Send an arbitrary request, for probes that need a route by hand."""
        return self._request(method, path, payload, headers)
