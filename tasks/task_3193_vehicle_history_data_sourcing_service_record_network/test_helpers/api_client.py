"""HTTP client for the Vehicle History Network API.

One method per endpoint declared by the PRD. Every method returns the raw
response so tests can assert on status codes as well as bodies.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for every route the contract declares."""

    # ── Logical clock ────────────────────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Networks ─────────────────────────────────────────────────────────

    def create_network(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/networks", payload, headers)

    def get_network(self, network_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/networks/{network_id}", headers=headers)

    def list_network_corrections(self, network_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/networks/{network_id}/corrections", headers=headers, params=params)

    def list_network_consumers(self, network_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/networks/{network_id}/consumers", headers=headers, params=params)

    def list_network_dealers(self, network_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/networks/{network_id}/dealers", headers=headers, params=params)

    def list_network_records(self, network_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/networks/{network_id}/records", headers=headers, params=params)

    def list_network_listings(self, network_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/networks/{network_id}/listings", headers=headers, params=params)

    def list_network_claims(self, network_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/networks/{network_id}/claims", headers=headers, params=params)

    def list_network_reports(self, network_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/networks/{network_id}/reports", headers=headers, params=params)

    def advance_epoch(self, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/advance_epoch", {}, headers)

    # ── Data sources ─────────────────────────────────────────────────────

    def create_source(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/sources", payload, headers)

    def get_source(self, source_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/sources/{source_id}", headers=headers)

    def list_sources(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/sources", headers=headers, params=params)

    def activate_source(self, source_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/sources/{source_id}/activate", {}, headers)

    def reactivate_source(self, source_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/sources/{source_id}/reactivate", {}, headers)

    def reset_source_streak(self, source_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/sources/{source_id}/reset_streak", {}, headers)

    def terminate_source(self, source_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/sources/{source_id}/terminate", {}, headers)

    def list_source_records(self, source_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/sources/{source_id}/records", headers=headers, params=params)

    # ── Records ──────────────────────────────────────────────────────────

    def create_record(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/records", payload, headers)

    def list_records(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/records", headers=headers, params=params)

    def get_record(self, record_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/records/{record_id}", headers=headers)

    def list_vehicle_records(self, vehicle_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/vehicles/{vehicle_id}/records", headers=headers, params=params)

    # ── Vehicles ─────────────────────────────────────────────────────────

    def get_vehicle(self, vehicle_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/vehicles", headers=headers, params=params)

    # ── Shops ────────────────────────────────────────────────────────────

    def create_shop(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/shops", payload, headers)

    def get_shop(self, shop_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/shops/{shop_id}", headers=headers)

    def list_shops(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/shops", headers=headers, params=params)

    def approve_shop(self, shop_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/shops/{shop_id}/approve", {}, headers)

    def suspend_shop(self, shop_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/shops/{shop_id}/suspend", {}, headers)

    def reactivate_shop(self, shop_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/shops/{shop_id}/reactivate", {}, headers)

    def terminate_shop(self, shop_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/shops/{shop_id}/terminate", {}, headers)

    def create_service_record(self, shop_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/shops/{shop_id}/service-records", payload, headers)

    def list_service_records(self, shop_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/shops/{shop_id}/service-records", headers=headers, params=params)

    # ── Corrections ──────────────────────────────────────────────────────

    def open_correction(self, vehicle_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/vehicles/{vehicle_id}/corrections", payload, headers)

    def get_correction(self, correction_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/corrections/{correction_id}", headers=headers)

    def get_correction_via_vehicle(self, vehicle_id: str, correction_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/vehicles/{vehicle_id}/corrections/{correction_id}", headers=headers)

    def list_vehicle_corrections(self, vehicle_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/vehicles/{vehicle_id}/corrections", headers=headers, params=params)

    def list_corrections(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/corrections", headers=headers, params=params)

    def route_correction(self, correction_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/corrections/{correction_id}/route_to_source", {}, headers)

    def confirm_correction(self, correction_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/corrections/{correction_id}/source_confirm", {}, headers)

    def deny_correction(self, correction_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/corrections/{correction_id}/source_deny", {}, headers)

    def apply_correction(self, correction_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/corrections/{correction_id}/apply", payload, headers)

    # ── Consumers ────────────────────────────────────────────────────────

    def create_consumer(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/consumers", payload, headers)

    def get_consumer(self, consumer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/consumers/{consumer_id}", headers=headers)

    def list_consumers(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/consumers", headers=headers, params=params)

    def top_up_consumer_credit(self, consumer_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/consumers/{consumer_id}/credit", payload, headers)

    # ── Dealers ──────────────────────────────────────────────────────────

    def create_dealer(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/dealers", payload, headers)

    def get_dealer(self, dealer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/dealers/{dealer_id}", headers=headers)

    def list_dealers(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/dealers", headers=headers, params=params)

    def subscribe_dealer(self, dealer_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/dealers/{dealer_id}/subscribe", payload, headers)

    def reinstate_dealer(self, dealer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/dealers/{dealer_id}/reinstate", {}, headers)

    # ── Listings ─────────────────────────────────────────────────────────

    def create_listing(self, dealer_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/dealers/{dealer_id}/listings", payload, headers)

    def list_dealer_listings(self, dealer_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/dealers/{dealer_id}/listings", headers=headers, params=params)

    def get_listing(self, listing_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/listings/{listing_id}", headers=headers)

    def list_listings(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/listings", headers=headers, params=params)

    def publish_listing(self, dealer_id: str, listing_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/dealers/{dealer_id}/listings/{listing_id}/publish", payload, headers)

    def delist_listing(self, dealer_id: str, listing_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/dealers/{dealer_id}/listings/{listing_id}/delist", {}, headers)

    def enroll_guarantee(self, dealer_id: str, listing_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/dealers/{dealer_id}/listings/{listing_id}/enroll_guarantee", payload, headers)

    # ── Claims ───────────────────────────────────────────────────────────

    def create_claim(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/claims", headers=headers, params=params)

    def list_dealer_claims(self, dealer_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/dealers/{dealer_id}/claims", headers=headers, params=params)

    def approve_claim(self, claim_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/claims/{claim_id}/approve", {}, headers)

    def reject_claim(self, claim_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/claims/{claim_id}/reject", {}, headers)

    # ── Reports ──────────────────────────────────────────────────────────

    def purchase_report(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/reports", payload, headers)

    def get_report(self, report_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/reports/{report_id}", headers=headers)

    def list_reports(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/reports", headers=headers, params=params)

    def list_vehicle_reports(self, vehicle_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/vehicles/{vehicle_id}/reports", headers=headers, params=params)

    def list_consumer_reports(self, consumer_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/consumers/{consumer_id}/reports", headers=headers, params=params)

    def list_dealer_reports(self, dealer_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/dealers/{dealer_id}/reports", headers=headers, params=params)


api_client = ApiClient()
