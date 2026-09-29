"""HTTP client for the Window Treatment Measure-and-Install Franchise API.

One method per endpoint of the published endpoint table. Every method returns the
raw ``requests.Response`` so tests can assert on HTTP status as well as body.

All resources share the ``/blinds`` prefix; the logical-clock endpoint does not.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import BASE_PATH, CLOCK_PATH
from .types import Headers, Json


def _clean(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Drop unset query parameters so a filter is only sent when asked for."""
    if not params:
        return None
    return {k: v for k, v in params.items() if v is not None}


class BlindsApiClient(GenericApiClient):
    """Endpoint-per-method client for the franchise API."""

    # ── Logical clock ─────────────────────────────────────────────────────────

    def set_clock(self, current_utc: str, headers: Headers) -> requests.Response:
        """Move the server's logical clock to a supplied instant."""
        return self._request("POST", CLOCK_PATH, {"current_utc": current_utc},
                             headers)

    def set_clock_raw(self, payload: Json, headers: Headers) -> requests.Response:
        """Drive the clock endpoint with an arbitrary body."""
        return self._request("POST", CLOCK_PATH, payload, headers)

    # ── Territories ───────────────────────────────────────────────────────────

    def create_territory(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/territories", payload, headers)

    def patch_territory(self, territory_id: str, payload: Json,
                        headers: Headers) -> requests.Response:
        return self._request("PATCH", f"{BASE_PATH}/territories/{territory_id}",
                             payload, headers)

    def get_territory(self, territory_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{BASE_PATH}/territories/{territory_id}",
                             None, headers)

    def list_ledger_entries(self, territory_id: str, headers: Headers,
                            entry_type: Optional[str] = None,
                            source_entity_type: Optional[str] = None,
                            limit: Optional[Any] = None,
                            offset: Optional[Any] = None) -> requests.Response:
        params = _clean({"entry_type": entry_type,
                         "source_entity_type": source_entity_type,
                         "limit": limit, "offset": offset})
        return self._request(
            "GET", f"{BASE_PATH}/territories/{territory_id}/ledger-entries",
            params, headers)

    # ── Designers ─────────────────────────────────────────────────────────────

    def create_designer(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/designers", payload, headers)

    def patch_designer(self, designer_id: str, payload: Json,
                       headers: Headers) -> requests.Response:
        return self._request("PATCH", f"{BASE_PATH}/designers/{designer_id}",
                             payload, headers)

    def get_designer(self, designer_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{BASE_PATH}/designers/{designer_id}",
                             None, headers)

    def list_designers(self, headers: Headers, territory_id: Optional[str] = None,
                       status: Optional[str] = None,
                       limit: Optional[Any] = None,
                       offset: Optional[Any] = None) -> requests.Response:
        params = _clean({"territory_id": territory_id, "status": status,
                         "limit": limit, "offset": offset})
        return self._request("GET", f"{BASE_PATH}/designers", params, headers)

    # ── Sample kits ───────────────────────────────────────────────────────────

    def create_sample_kit(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/sample-kits", payload, headers)

    def get_sample_kit(self, kit_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{BASE_PATH}/sample-kits/{kit_id}", None,
                             headers)

    def list_sample_kits(self, headers: Headers,
                         territory_id: Optional[str] = None,
                         status: Optional[str] = None,
                         limit: Optional[Any] = None,
                         offset: Optional[Any] = None) -> requests.Response:
        params = _clean({"territory_id": territory_id, "status": status,
                         "limit": limit, "offset": offset})
        return self._request("GET", f"{BASE_PATH}/sample-kits", params, headers)

    # ── Leads ─────────────────────────────────────────────────────────────────

    def create_lead(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/leads", payload, headers)

    def get_lead(self, lead_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{BASE_PATH}/leads/{lead_id}", None, headers)

    def list_leads(self, headers: Headers, territory_id: Optional[str] = None,
                   status: Optional[str] = None,
                   postal_code: Optional[str] = None,
                   limit: Optional[Any] = None,
                   offset: Optional[Any] = None) -> requests.Response:
        params = _clean({"territory_id": territory_id, "status": status,
                         "postal_code": postal_code, "limit": limit,
                         "offset": offset})
        return self._request("GET", f"{BASE_PATH}/leads", params, headers)

    # ── Consultations ─────────────────────────────────────────────────────────

    def create_consultation(self, payload: Json,
                            headers: Headers) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/consultations", payload, headers)

    def get_consultation(self, consultation_id: str,
                         headers: Headers) -> requests.Response:
        return self._request("GET", f"{BASE_PATH}/consultations/{consultation_id}",
                             None, headers)

    def list_consultations(self, headers: Headers, lead_id: Optional[str] = None,
                           designer_id: Optional[str] = None,
                           status: Optional[str] = None,
                           limit: Optional[Any] = None,
                           offset: Optional[Any] = None) -> requests.Response:
        params = _clean({"lead_id": lead_id, "designer_id": designer_id,
                         "status": status, "limit": limit, "offset": offset})
        return self._request("GET", f"{BASE_PATH}/consultations", params, headers)

    def complete_consultation(self, consultation_id: str,
                              headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/consultations/{consultation_id}/complete",
            {}, headers)

    def no_show_consultation(self, consultation_id: str,
                             headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/consultations/{consultation_id}/no-show",
            {}, headers)

    # ── Sample check-outs ─────────────────────────────────────────────────────

    def create_sample_checkout(self, payload: Json,
                               headers: Headers) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/sample-checkouts", payload,
                             headers)

    def get_sample_checkout(self, checkout_id: str,
                            headers: Headers) -> requests.Response:
        return self._request("GET", f"{BASE_PATH}/sample-checkouts/{checkout_id}",
                             None, headers)

    def list_sample_checkouts(self, headers: Headers,
                              sample_kit_id: Optional[str] = None,
                              consultation_id: Optional[str] = None,
                              status: Optional[str] = None,
                              limit: Optional[Any] = None,
                              offset: Optional[Any] = None) -> requests.Response:
        params = _clean({"sample_kit_id": sample_kit_id,
                         "consultation_id": consultation_id, "status": status,
                         "limit": limit, "offset": offset})
        return self._request("GET", f"{BASE_PATH}/sample-checkouts", params,
                             headers)

    def return_sample_checkout(self, checkout_id: str,
                               headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/sample-checkouts/{checkout_id}/return",
            {}, headers)

    # ── Openings ──────────────────────────────────────────────────────────────

    def create_opening(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/openings", payload, headers)

    def get_opening(self, opening_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{BASE_PATH}/openings/{opening_id}", None,
                             headers)

    def list_openings(self, headers: Headers,
                      consultation_id: Optional[str] = None,
                      quote_id: Optional[str] = None,
                      replaces_opening_id: Optional[str] = None,
                      measure_status: Optional[str] = None,
                      install_outcome: Optional[str] = None,
                      limit: Optional[Any] = None,
                      offset: Optional[Any] = None) -> requests.Response:
        params = _clean({"consultation_id": consultation_id,
                         "quote_id": quote_id,
                         "replaces_opening_id": replaces_opening_id,
                         "measure_status": measure_status,
                         "install_outcome": install_outcome,
                         "limit": limit, "offset": offset})
        return self._request("GET", f"{BASE_PATH}/openings", params, headers)

    def configure_opening(self, opening_id: str, payload: Json,
                          headers: Headers) -> requests.Response:
        return self._request(
            "PATCH", f"{BASE_PATH}/openings/{opening_id}/configuration",
            payload, headers)

    # ── Quotes ────────────────────────────────────────────────────────────────

    def create_quote(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/quotes", payload, headers)

    def get_quote(self, quote_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{BASE_PATH}/quotes/{quote_id}", None, headers)

    def list_quotes(self, headers: Headers,
                    consultation_id: Optional[str] = None,
                    status: Optional[str] = None,
                    limit: Optional[Any] = None,
                    offset: Optional[Any] = None) -> requests.Response:
        params = _clean({"consultation_id": consultation_id, "status": status,
                         "limit": limit, "offset": offset})
        return self._request("GET", f"{BASE_PATH}/quotes", params, headers)

    def present_quote(self, quote_id: str, headers: Headers) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/quotes/{quote_id}/present",
                             {}, headers)

    def revise_quote(self, quote_id: str, headers: Headers) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/quotes/{quote_id}/revise",
                             {}, headers)

    def accept_quote(self, quote_id: str, headers: Headers) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/quotes/{quote_id}/accept",
                             {}, headers)

    # ── Vendors ───────────────────────────────────────────────────────────────

    def create_vendor(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/vendors", payload, headers)

    def get_vendor(self, vendor_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{BASE_PATH}/vendors/{vendor_id}", None,
                             headers)

    # ── Vendor orders ─────────────────────────────────────────────────────────

    def create_vendor_order(self, payload: Json,
                            headers: Headers) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/vendor-orders", payload, headers)

    def get_vendor_order(self, order_id: str,
                         headers: Headers) -> requests.Response:
        return self._request("GET", f"{BASE_PATH}/vendor-orders/{order_id}", None,
                             headers)

    def list_vendor_orders(self, headers: Headers, quote_id: Optional[str] = None,
                           vendor_id: Optional[str] = None,
                           status: Optional[str] = None,
                           limit: Optional[Any] = None,
                           offset: Optional[Any] = None) -> requests.Response:
        params = _clean({"quote_id": quote_id, "vendor_id": vendor_id,
                         "status": status, "limit": limit, "offset": offset})
        return self._request("GET", f"{BASE_PATH}/vendor-orders", params, headers)

    def ship_vendor_order(self, order_id: str,
                          headers: Headers) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/vendor-orders/{order_id}/ship",
                             {}, headers)

    def receive_vendor_order(self, order_id: str,
                             headers: Headers) -> requests.Response:
        return self._request("POST",
                             f"{BASE_PATH}/vendor-orders/{order_id}/receive",
                             {}, headers)

    def remake_vendor_order(self, order_id: str, payload: Json,
                            headers: Headers) -> requests.Response:
        return self._request("POST",
                             f"{BASE_PATH}/vendor-orders/{order_id}/remake",
                             payload, headers)

    # ── Install jobs ──────────────────────────────────────────────────────────

    def create_install_job(self, payload: Json,
                           headers: Headers) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/install-jobs", payload, headers)

    def get_install_job(self, job_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{BASE_PATH}/install-jobs/{job_id}", None,
                             headers)

    def list_install_jobs(self, headers: Headers,
                          vendor_order_id: Optional[str] = None,
                          designer_id: Optional[str] = None,
                          install_status: Optional[str] = None,
                          commissioning_status: Optional[str] = None,
                          limit: Optional[Any] = None,
                          offset: Optional[Any] = None) -> requests.Response:
        params = _clean({"vendor_order_id": vendor_order_id,
                         "designer_id": designer_id,
                         "install_status": install_status,
                         "commissioning_status": commissioning_status,
                         "limit": limit, "offset": offset})
        return self._request("GET", f"{BASE_PATH}/install-jobs", params, headers)

    def pair_commissioning(self, job_id: str, payload: Json,
                           headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/install-jobs/{job_id}/commissioning/pair",
            payload, headers)

    def verify_commissioning(self, job_id: str,
                             headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/install-jobs/{job_id}/commissioning/verify",
            {}, headers)

    def raise_install_exception(self, job_id: str, payload: Json,
                                headers: Headers) -> requests.Response:
        return self._request("POST",
                             f"{BASE_PATH}/install-jobs/{job_id}/exception",
                             payload, headers)

    def complete_install_job(self, job_id: str,
                             headers: Headers) -> requests.Response:
        return self._request("POST",
                             f"{BASE_PATH}/install-jobs/{job_id}/complete",
                             {}, headers)
