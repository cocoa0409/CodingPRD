"""
Endpoint client for the State Fish Hatchery Stocking Program API.

One method per row of the PRD's endpoint table. Every endpoint is mounted at the
root of the service, so paths are written literally. Methods return the raw
requests.Response so tests can assert on status codes as well as bodies.

This module also owns instant canonicalisation. The PRD specifies that all
instants are "ISO 8601 UTC timestamps with three fractional digits", so a
literal a test supplies as "2026-09-01T08:00:00Z" and a server value of
"2026-09-01T08:00:00.000Z" denote the same instant; canonical_instant() puts
both into the three-fractional-digit form before they are compared.
"""

import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[Tt](\d{2}:\d{2}:\d{2})(?:\.(\d+))?"
    r"(?:[Zz]|([+-]\d{2}):?(\d{2}))?$"
)


def canonical_instant(value: Any) -> Any:
    """
    Normalise an ISO 8601 UTC instant to the three-fractional-digit form the PRD
    mandates. Non-string and unrecognised values are returned untouched so that
    a None or a malformed value still fails its assertion loudly.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    date_part, time_part, fraction, tz_hours, tz_minutes = match.groups()
    if tz_hours is not None and (int(tz_hours) != 0 or int(tz_minutes or 0) != 0):
        # A non-UTC offset is not the form the PRD describes; leave it visible.
        return value
    millis = (fraction or "")[:3].ljust(3, "0")
    return f"{date_part}T{time_part}.{millis}Z"


class ApiClient(GenericApiClient):
    """HTTP client exposing every endpoint in the PRD's endpoint table."""

    # ─── Logical clock ────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Hatcheries and discharge monitoring ──────────

    def create_hatchery(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/hatcheries", payload, headers)

    def get_hatchery(self, hatchery_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/hatcheries/{hatchery_id}", None, headers)

    def list_hatchery_effluent_readings(
        self,
        hatchery_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/hatcheries/{hatchery_id}/effluent-readings", params, headers
        )

    def create_effluent_reading(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/effluent-readings", payload, headers)

    # ─── Waters ───────────────────────────────────────

    def create_water(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/waters", payload, headers)

    def get_water(self, water_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/waters/{water_id}", None, headers)

    def list_waters(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/waters", params, headers)

    def close_water(self, water_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/waters/{water_id}/close", None, headers)

    # ─── Brood groups ─────────────────────────────────

    def create_brood_stock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/brood-stocks", payload, headers)

    def get_brood_stock(self, brood_stock_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/brood-stocks/{brood_stock_id}", None, headers)

    def list_brood_stocks(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/brood-stocks", params, headers)

    def open_spawning_window(self, brood_stock_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/brood-stocks/{brood_stock_id}/open-spawning-window", None, headers
        )

    # ─── Egg takes ────────────────────────────────────

    def create_spawn_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/spawn-events", payload, headers)

    def get_spawn_event(self, spawn_event_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/spawn-events/{spawn_event_id}", None, headers)

    def list_spawn_events(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/spawn-events", params, headers)

    def record_take(
        self, spawn_event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/spawn-events/{spawn_event_id}/record-take", payload, headers
        )

    def cancel_spawn_event(self, spawn_event_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/spawn-events/{spawn_event_id}/cancel", None, headers
        )

    # ─── Rearing lots ─────────────────────────────────

    def get_rearing_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/rearing-lots/{lot_id}", None, headers)

    def list_rearing_lots(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/rearing-lots", params, headers)

    def record_feeding(
        self, lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/rearing-lots/{lot_id}/feedings", payload, headers
        )

    def advance_stage(
        self, lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/rearing-lots/{lot_id}/advance-stage", payload, headers
        )

    # ─── Fish health ──────────────────────────────────

    def create_health_inspection(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/health-inspections", payload, headers)

    def get_health_inspection(self, inspection_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/health-inspections/{inspection_id}", None, headers
        )

    def list_health_inspections(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/health-inspections", params, headers)

    def record_result(
        self, inspection_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/health-inspections/{inspection_id}/record-result",
            payload,
            headers,
        )

    def record_treatment(
        self, inspection_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/health-inspections/{inspection_id}/record-treatment",
            payload,
            headers,
        )

    def certify_inspection(self, inspection_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/health-inspections/{inspection_id}/certify", None, headers
        )

    # ─── Stocking requests ────────────────────────────

    def create_stocking_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/stocking-requests", payload, headers)

    def get_stocking_request(self, request_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/stocking-requests/{request_id}", None, headers)

    def list_stocking_requests(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/stocking-requests", params, headers)

    def withdraw_stocking_request(self, request_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/stocking-requests/{request_id}/withdraw", None, headers
        )

    def attach_to_plan(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/stocking-requests/{request_id}/attach-to-plan", payload, headers
        )

    # ─── Allocation plans ─────────────────────────────

    def create_allocation_plan(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/allocation-plans", payload, headers)

    def get_allocation_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/allocation-plans/{plan_id}", None, headers)

    def list_allocation_plans(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/allocation-plans", params, headers)

    def run_allocation_plan(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/allocation-plans/{plan_id}/run", payload, headers
        )

    # ─── Transport fleet ──────────────────────────────

    def create_transport_unit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/transport-units", payload, headers)

    def get_transport_unit(self, unit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/transport-units/{unit_id}", None, headers)

    def list_transport_units(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/transport-units", params, headers)

    # ─── Stocking trips ───────────────────────────────

    def create_stocking_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/stocking-events", payload, headers)

    def get_stocking_event(self, event_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/stocking-events/{event_id}", None, headers)

    def list_stocking_events(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/stocking-events", params, headers)

    def load_stocking_event(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/stocking-events/{event_id}/load", payload, headers
        )

    def release_stocking_event(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/stocking-events/{event_id}/release", payload, headers
        )

    def abort_stocking_event(self, event_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/stocking-events/{event_id}/abort", None, headers
        )

    def record_event_recoveries(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/stocking-events/{event_id}/recoveries", payload, headers
        )
