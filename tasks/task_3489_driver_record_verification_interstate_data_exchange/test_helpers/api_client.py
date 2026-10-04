"""HTTP client for the Driver Record Exchange API.

One method per endpoint the PRD declares. Every method returns the raw
response so a test can assert the status code as well as the body; request
bodies go as ``payload`` and query filters/pagination as ``params``.

All routes live under the ``/driver-exchange`` prefix exactly as the PRD
writes them, including the logical-clock endpoint.

No module-level client instance is created here: the module name must keep
resolving to the module. Tests construct a client through ``make_api_client``
(or instantiate ``ApiClient`` directly) inside their own fixtures.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

API_PREFIX = "/driver-exchange"


class ApiClient(GenericApiClient):
    """Endpoint methods for every route the PRD declares."""

    # ── Logical clock ──────────────────────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers)

    # ── Jurisdictions ──────────────────────────────────────────────────────

    def create_jurisdiction(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/jurisdictions/{jurisdiction_id}", None, headers)

    def update_jurisdiction(self, jurisdiction_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("PATCH", f"{API_PREFIX}/jurisdictions/{jurisdiction_id}", payload, headers)

    def list_jurisdiction_participations(
        self, jurisdiction_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/jurisdictions/{jurisdiction_id}/system-participations", headers=headers, params=params)

    def list_jurisdiction_fee_invoices(
        self, jurisdiction_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/jurisdictions/{jurisdiction_id}/fee-invoices", headers=headers, params=params)

    def list_jurisdiction_vehicle_titles(
        self, jurisdiction_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/jurisdictions/{jurisdiction_id}/vehicle-titles", headers=headers, params=params)

    # ── System participations ──────────────────────────────────────────────

    def create_participation(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/system-participations", payload, headers)

    def grant_certification(self, participation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/system-participations/{participation_id}/grant-certification", {}, headers)

    # ── Connection certifications ──────────────────────────────────────────

    def create_certification(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/connection-certifications", payload, headers)

    def get_certification(self, certification_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/connection-certifications/{certification_id}", None, headers)

    def list_certifications(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/connection-certifications", headers=headers, params=params)

    def complete_certification(self, certification_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/connection-certifications/{certification_id}/complete", payload, headers)

    # ── Driver identities and records ──────────────────────────────────────

    def create_driver(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/drivers", payload, headers)

    def get_driver(self, driver_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/drivers/{driver_id}", None, headers)

    def create_driver_record(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/driver-records", payload, headers)

    def get_driver_record(self, record_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/driver-records/{record_id}", None, headers)

    def list_driver_records(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/driver-records", headers=headers, params=params)

    def list_record_convictions(
        self, record_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/driver-records/{record_id}/convictions", headers=headers, params=params)

    def list_record_disqualifications(
        self, record_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/driver-records/{record_id}/disqualifications", headers=headers, params=params)

    # ── Convictions and disqualifications ──────────────────────────────────

    def create_conviction(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/convictions", payload, headers)

    def create_disqualification(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/disqualifications", payload, headers)

    def overturn_disqualification(self, disqualification_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/disqualifications/{disqualification_id}/overturn", {}, headers)

    # ── Licenses ───────────────────────────────────────────────────────────

    def create_license(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/licenses", payload, headers)

    def get_license(self, license_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/licenses/{license_id}", None, headers)

    def list_licenses(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/licenses", headers=headers, params=params)

    def post_verification_result(self, license_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/licenses/{license_id}/verification-results", payload, headers)

    def reinstate_license(self, license_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/licenses/{license_id}/reinstate", {}, headers)

    # ── License transfers ──────────────────────────────────────────────────

    def create_license_transfer(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/license-transfers", payload, headers)

    def get_license_transfer(self, transfer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/license-transfers/{transfer_id}", None, headers)

    def list_license_transfers(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/license-transfers", headers=headers, params=params)

    def record_surrender(self, transfer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/license-transfers/{transfer_id}/record-surrender", {}, headers)

    def contest_transfer(self, transfer_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/license-transfers/{transfer_id}/contest", payload, headers)

    def complete_transfer(self, transfer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/license-transfers/{transfer_id}/complete", {}, headers)

    # ── Vehicle titles and title transfers ─────────────────────────────────

    def create_vehicle_title(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/vehicle-titles", payload, headers)

    def create_title_transfer(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/title-transfers", payload, headers)

    def get_title_transfer(self, transfer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/title-transfers/{transfer_id}", None, headers)

    def list_title_transfers(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/title-transfers", headers=headers, params=params)

    def complete_title_transfer(self, transfer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/title-transfers/{transfer_id}/complete", {}, headers)

    # ── Fee invoices ───────────────────────────────────────────────────────

    def create_fee_invoice(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/fee-invoices", payload, headers)

    def dispute_invoice(self, invoice_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/fee-invoices/{invoice_id}/dispute", payload, headers)

    def reissue_invoice(self, invoice_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/fee-invoices/{invoice_id}/reissue", payload, headers)

    def settle_invoice(self, invoice_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/fee-invoices/{invoice_id}/settle", payload, headers)

    def finalize_audit(self, invoice_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/fee-invoices/{invoice_id}/finalize-audit", payload, headers)

    # ── Raw escape hatch ───────────────────────────────────────────────────

    def raw(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ) -> requests.Response:
        """Send an arbitrary request, for probes that need a route by hand."""
        return self._request(method, path, payload, headers, params)


def make_api_client(base_url: Optional[str] = None) -> ApiClient:
    """Construct an API client. ``base_url`` defaults to the API_BASE_URL
    environment variable handled by the base class."""
    return ApiClient(base_url)
