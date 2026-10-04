"""HTTP client for the Donated Medicine Allocation API.

One method per endpoint the PRD declares. Every method returns the raw
``requests.Response`` so tests can assert on status code and body alike.
The base URL is injected via ``API_BASE_URL`` by the test runner.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

API_PREFIX = "/medicine-relief"


class ApiClient(GenericApiClient):
    """Endpoint methods for every route the PRD declares."""

    # ── Logical clock ─────────────────────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers)

    # ── Manufacturer donors ───────────────────────────────────────────────

    def create_donor(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/donors", payload, headers)

    def get_donor(self, donor_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/donors/{donor_id}", headers=headers)

    def list_donors(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/donors", headers=headers, params=params)

    def suspend_donor(self, donor_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/donors/{donor_id}/suspend", {}, headers)

    def deactivate_donor(self, donor_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/donors/{donor_id}/deactivate", {}, headers)

    # ── Product lots ──────────────────────────────────────────────────────

    def create_lot(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/lots", payload, headers)

    def get_lot(self, lot_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/lots/{lot_id}", headers=headers)

    def list_lots(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/lots", headers=headers, params=params)

    def release_lot(self, lot_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/lots/{lot_id}/release", {}, headers)

    def recall_lot(self, lot_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/lots/{lot_id}/recall", {}, headers)

    # ── Recipient sites ───────────────────────────────────────────────────

    def create_site(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/sites", payload, headers)

    def get_site(self, site_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/sites/{site_id}", headers=headers)

    def list_sites(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/sites", headers=headers, params=params)

    def qualify_site(self, site_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/sites/{site_id}/qualify", {}, headers)

    def suspend_site(self, site_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/sites/{site_id}/suspend", payload, headers)

    def reinstate_site(self, site_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/sites/{site_id}/reinstate", {}, headers)

    def revoke_site(self, site_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/sites/{site_id}/revoke", {}, headers)

    # ── Licenses ──────────────────────────────────────────────────────────

    def create_license(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/licenses", payload, headers)

    def get_license(self, license_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/licenses/{license_id}", headers=headers)

    def list_licenses(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/licenses", headers=headers, params=params)

    def verify_license(self, license_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/licenses/{license_id}/verify", {}, headers)

    def reject_license(self, license_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/licenses/{license_id}/reject", {}, headers)

    # ── Allocation requests ───────────────────────────────────────────────

    def create_allocation_request(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/allocation-requests", payload, headers)

    def get_allocation_request(self, request_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/allocation-requests/{request_id}", headers=headers)

    def list_allocation_requests(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/allocation-requests", headers=headers, params=params)

    def begin_review(self, request_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/allocation-requests/{request_id}/begin-review", {}, headers)

    def reject_allocation_request(self, request_id: str, headers: Dict[str, str], rationale: Optional[str] = None) -> requests.Response:
        payload: Dict[str, Any] = {}
        if rationale is not None:
            payload["rationale"] = rationale
        return self._request("POST", f"{API_PREFIX}/allocation-requests/{request_id}/reject", payload, headers)

    def cancel_allocation_request(self, request_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/allocation-requests/{request_id}/cancel", {}, headers)

    # ── Allocation decisions ──────────────────────────────────────────────

    def create_allocation_decision(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/allocation-decisions", payload, headers)

    def get_allocation_decision(self, decision_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/allocation-decisions/{decision_id}", headers=headers)

    def list_allocation_decisions(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/allocation-decisions", headers=headers, params=params)

    def finalize_decision(self, decision_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/allocation-decisions/{decision_id}/finalize", payload, headers)

    def void_decision(self, decision_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/allocation-decisions/{decision_id}/void", {}, headers)

    # ── Allocation lines ──────────────────────────────────────────────────

    def get_allocation_line(self, line_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/allocation-lines/{line_id}", headers=headers)

    def list_allocation_lines(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/allocation-lines", headers=headers, params=params)

    # ── Shipments ─────────────────────────────────────────────────────────

    def create_shipment(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/shipments", payload, headers)

    def get_shipment(self, shipment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/shipments", headers=headers, params=params)

    def pack_complete(self, shipment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/shipments/{shipment_id}/pack-complete", {}, headers)

    def dispatch_shipment(self, shipment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/shipments/{shipment_id}/dispatch", {}, headers)

    def confirm_delivery(self, shipment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/shipments/{shipment_id}/confirm-delivery", {}, headers)

    def mark_delivery_failed(self, shipment_id: str, headers: Dict[str, str], reason: Optional[str] = None) -> requests.Response:
        payload: Dict[str, Any] = {}
        if reason is not None:
            payload["reason"] = reason
        return self._request("POST", f"{API_PREFIX}/shipments/{shipment_id}/mark-delivery-failed", payload, headers)

    def cancel_shipment(self, shipment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/shipments/{shipment_id}/cancel", {}, headers)

    # ── Customs declarations ──────────────────────────────────────────────

    def create_customs_declaration(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/customs-declarations", payload, headers)

    def get_customs_declaration(self, declaration_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/customs-declarations/{declaration_id}", headers=headers)

    def list_customs_declarations(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/customs-declarations", headers=headers, params=params)

    def submit_customs_declaration(self, declaration_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/customs-declarations/{declaration_id}/submit", {}, headers)

    def clear_customs_declaration(self, declaration_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/customs-declarations/{declaration_id}/clear", {}, headers)

    def reject_customs_declaration(self, declaration_id: str, headers: Dict[str, str], reason: Optional[str] = None) -> requests.Response:
        payload: Dict[str, Any] = {}
        if reason is not None:
            payload["reason"] = reason
        return self._request("POST", f"{API_PREFIX}/customs-declarations/{declaration_id}/reject", payload, headers)

    # ── Emergency events ──────────────────────────────────────────────────

    def create_emergency_event(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/emergency-events", payload, headers)

    def get_emergency_event(self, event_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/emergency-events/{event_id}", headers=headers)

    def list_emergency_events(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/emergency-events", headers=headers, params=params)

    def activate_emergency_event(self, event_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/emergency-events/{event_id}/activate", {}, headers)

    def close_emergency_event(self, event_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/emergency-events/{event_id}/close", {}, headers)

    # ── Pre-positioned modules ────────────────────────────────────────────

    def create_module(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/prepositioned-modules", payload, headers)

    def get_module(self, module_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/prepositioned-modules/{module_id}", headers=headers)

    def list_modules(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/prepositioned-modules", headers=headers, params=params)

    def reserve_module(self, module_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/prepositioned-modules/{module_id}/reserve", payload, headers)

    def deploy_module(self, module_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/prepositioned-modules/{module_id}/deploy", {}, headers)

    def consume_module(self, module_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/prepositioned-modules/{module_id}/consume", {}, headers)

    # ── Valuation snapshots ───────────────────────────────────────────────

    def create_valuation_snapshot(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/valuation-snapshots", payload, headers)

    def get_valuation_snapshot(self, snapshot_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/valuation-snapshots/{snapshot_id}", headers=headers)

    def list_valuation_snapshots(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/valuation-snapshots", headers=headers, params=params)

    # ── Distribution reports ──────────────────────────────────────────────

    def create_distribution_report(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/distribution-reports", payload, headers)

    def get_distribution_report(self, report_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/distribution-reports/{report_id}", headers=headers)

    def list_distribution_reports(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/distribution-reports", headers=headers, params=params)

    def submit_distribution_report(self, report_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/distribution-reports/{report_id}/submit", {}, headers)

    def accept_distribution_report(self, report_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/distribution-reports/{report_id}/accept", {}, headers)

    def reject_distribution_report(self, report_id: str, headers: Dict[str, str], reason: Optional[str] = None) -> requests.Response:
        payload: Dict[str, Any] = {}
        if reason is not None:
            payload["reason"] = reason
        return self._request("POST", f"{API_PREFIX}/distribution-reports/{report_id}/reject", payload, headers)


api_client = ApiClient()
