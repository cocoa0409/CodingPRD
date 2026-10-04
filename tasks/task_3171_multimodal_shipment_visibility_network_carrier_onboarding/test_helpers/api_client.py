"""HTTP client for the Multimodal Shipment Visibility API.

One method per endpoint the contract declares. Every method returns the raw
response so a test can assert on the status code as well as the body. Query
filters and pagination travel as ``params``; request bodies as ``payload``.

The API is mounted at the root with no prefix, so paths are used exactly as
the contract writes them.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant so two spellings of one instant match.

    The contract renders instants with three fractional digits, but an equal
    instant may legitimately arrive with none, with fewer digits, or with
    trailing zeroes. Comparisons therefore run on the canonical form -
    ``YYYY-MM-DDTHH:MM:SS.mmmZ`` - instead of on the raw strings, so that
    ``2026-09-03T00:00:00Z`` and ``2026-09-03T00:00:00.000Z`` compare equal.
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

    # ── Logical clock and ops-run checkpoint ───────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_checkpoint(self, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_ops/run-checkpoint", {}, headers)

    # ── Carriers ───────────────────────────────────────────────────────────

    def create_carrier(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/carriers", payload, headers)

    def get_carrier(self, carrier_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/carriers/{carrier_id}", None, headers)

    def list_carrier_connections(
        self, carrier_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/carriers/{carrier_id}/connections", headers=headers, params=params)

    def list_carrier_shipments(
        self, carrier_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/carriers/{carrier_id}/shipments", headers=headers, params=params)

    # ── Shippers ───────────────────────────────────────────────────────────

    def create_shipper(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/shippers", payload, headers)

    def get_shipper(self, shipper_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/shippers/{shipper_id}", None, headers)

    def list_shipper_consignees(
        self, shipper_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/shippers/{shipper_id}/consignees", headers=headers, params=params)

    def list_shipper_purchase_orders(
        self, shipper_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/shippers/{shipper_id}/purchase-orders", headers=headers, params=params)

    def list_shipper_shipments(
        self, shipper_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/shippers/{shipper_id}/shipments", headers=headers, params=params)

    def list_shipper_data_share_grants(
        self, shipper_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/shippers/{shipper_id}/data-share-grants", headers=headers, params=params)

    # ── Consignees ─────────────────────────────────────────────────────────

    def create_consignee(
        self, shipper_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/shippers/{shipper_id}/consignees", payload, headers)

    # ── Carrier connections ────────────────────────────────────────────────

    def create_connection(
        self, carrier_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/carriers/{carrier_id}/connections", payload, headers)

    def get_connection(self, connection_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/connections/{connection_id}", None, headers)

    def submit_credentials(
        self, connection_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/connections/{connection_id}/submit-credentials", payload, headers)

    def begin_testing(
        self, connection_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/connections/{connection_id}/begin-testing", payload, headers)

    def activate_connection(self, connection_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/connections/{connection_id}/activate", {}, headers)

    def suspend_connection(
        self, connection_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/connections/{connection_id}/suspend", payload, headers)

    def resume_connection(self, connection_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/connections/{connection_id}/resume", {}, headers)

    def retire_connection(self, connection_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/connections/{connection_id}/retire", {}, headers)

    def post_heartbeat(
        self, connection_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/connections/{connection_id}/heartbeats", payload, headers)

    def list_heartbeats(
        self, connection_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/connections/{connection_id}/heartbeats", headers=headers, params=params)

    # ── Purchase orders ────────────────────────────────────────────────────

    def create_purchase_order(
        self, shipper_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/shippers/{shipper_id}/purchase-orders", payload, headers)

    def get_purchase_order(
        self, purchase_order_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/purchase-orders/{purchase_order_id}", None, headers)

    def list_purchase_order_identity_links(
        self, purchase_order_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/purchase-orders/{purchase_order_id}/identity-links", headers=headers, params=params
        )

    # ── Facilities ─────────────────────────────────────────────────────────

    def create_facility(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/facilities", payload, headers)

    def get_facility(self, facility_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/facilities/{facility_id}", None, headers)

    def patch_facility(
        self, facility_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"/facilities/{facility_id}", payload, headers)

    # ── Shipments ──────────────────────────────────────────────────────────

    def create_shipment(
        self, shipper_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/shippers/{shipper_id}/shipments", payload, headers)

    def list_shipments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/shipments/{shipment_id}", None, headers)

    def ingest_event(
        self, shipment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/shipments/{shipment_id}/events", payload, headers)

    def list_events(
        self, shipment_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/shipments/{shipment_id}/events", headers=headers, params=params)

    def void_event(
        self, shipment_id: str, event_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/shipments/{shipment_id}/events/{event_id}/void", {}, headers)

    def recompute_eta(self, shipment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/shipments/{shipment_id}/recompute-eta", {}, headers)

    def cancel_shipment(self, shipment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/shipments/{shipment_id}/cancel", {}, headers)

    # ── Identity links ─────────────────────────────────────────────────────

    def propose_identity_link(
        self, shipment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/shipments/{shipment_id}/identity-links", payload, headers)

    def list_shipment_identity_links(
        self, shipment_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/shipments/{shipment_id}/identity-links", headers=headers, params=params)

    def confirm_identity_link(self, link_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/identity-links/{link_id}/confirm", {}, headers)

    def reject_identity_link(self, link_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/identity-links/{link_id}/reject", {}, headers)

    # ── Exception alerts ───────────────────────────────────────────────────

    def list_alerts(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/alerts", headers=headers, params=params)

    def list_shipment_alerts(
        self, shipment_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/shipments/{shipment_id}/alerts", headers=headers, params=params)

    def acknowledge_alert(self, alert_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/alerts/{alert_id}/acknowledge", {}, headers)

    def resolve_alert(
        self, alert_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/alerts/{alert_id}/resolve", payload, headers)

    # ── Appointments ───────────────────────────────────────────────────────

    def book_appointment(
        self, facility_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/facilities/{facility_id}/appointments", payload, headers)

    def list_facility_appointments(
        self, facility_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/facilities/{facility_id}/appointments", headers=headers, params=params)

    def list_appointments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/appointments/{appointment_id}", None, headers)

    def complete_appointment(
        self, appointment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/appointments/{appointment_id}/complete", payload, headers)

    def void_completion(self, appointment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/appointments/{appointment_id}/void-completion", {}, headers)

    # ── Data-share grants ──────────────────────────────────────────────────

    def create_data_share_grant(
        self, shipper_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/shippers/{shipper_id}/data-share-grants", payload, headers)

    def revoke_data_share_grant(
        self, grant_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/data-share-grants/{grant_id}/revoke", {}, headers)


api_client = ApiClient()
