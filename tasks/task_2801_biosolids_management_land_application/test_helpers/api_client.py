"""Endpoint client for the Biosolids Management & Land Application API.

One method per declared route. Every method returns the raw ``requests.Response``
so tests can assert on status codes and the envelope directly.

Timestamp canonicalisation: the contract renders instants as ISO 8601 UTC with
exactly three fractional digits, but request payloads are written with whatever
width is convenient. ``canonical_iso`` normalises any accepted width to the
declared three-digit form so comparisons never depend on the server's choice of
sub-second precision.
"""

import re
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_ROOT

_TS_RE = re.compile(
    r"^(?P<base>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?Z$"
)


def canonical_iso(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant to exactly three fractional digits."""
    if not isinstance(value, str):
        return value
    match = _TS_RE.match(value)
    if not match:
        return value
    frac = (match.group("frac") or "")[:3].ljust(3, "0")
    return f"{match.group('base')}.{frac}Z"


class BiosolidsApiClient(GenericApiClient):
    """Typed access to every route declared by the contract."""

    # ------------------------------------------------------------ plumbing
    def _call(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ) -> requests.Response:
        return self._request(method, f"{API_ROOT}{path}", payload, headers, params)

    # ------------------------------------------------------------ clock
    def set_clock(self, payload, headers):
        return self._call("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------ weather
    def post_weather_observation(self, payload, headers):
        return self._call("POST", "/_weather/observations", payload, headers)

    # ------------------------------------------------------------ facilities
    def create_facility(self, payload, headers):
        return self._call("POST", "/treatment-facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._call("GET", f"/treatment-facilities/{facility_id}", None, headers)

    def list_facilities(self, headers, params=None):
        return self._call("GET", "/treatment-facilities", None, headers, params)

    def get_storage_projection(self, facility_id, headers):
        return self._call(
            "GET", f"/treatment-facilities/{facility_id}/storage-projection",
            None, headers,
        )

    # ------------------------------------------------------------ pollutant limits
    def create_pollutant_limit(self, payload, headers):
        return self._call("POST", "/pollutant-limits", payload, headers)

    def get_pollutant_limit(self, limit_id, headers):
        return self._call("GET", f"/pollutant-limits/{limit_id}", None, headers)

    def list_pollutant_limits(self, headers, params=None):
        return self._call("GET", "/pollutant-limits", None, headers, params)

    # ------------------------------------------------------------ solids batches
    def create_batch(self, payload, headers):
        return self._call("POST", "/solids-batches", payload, headers)

    def get_batch(self, batch_id, headers):
        return self._call("GET", f"/solids-batches/{batch_id}", None, headers)

    def list_batches(self, headers, params=None):
        return self._call("GET", "/solids-batches", None, headers, params)

    def advance_process(self, batch_id, payload, headers):
        return self._call(
            "POST", f"/solids-batches/{batch_id}/advance-process", payload, headers
        )

    def create_lab_result(self, batch_id, payload, headers):
        return self._call(
            "POST", f"/solids-batches/{batch_id}/lab-results", payload, headers
        )

    def list_batch_lab_results(self, batch_id, headers, params=None):
        return self._call(
            "GET", f"/solids-batches/{batch_id}/lab-results", None, headers, params
        )

    def certify_batch(self, batch_id, headers, payload=None):
        return self._call(
            "POST", f"/solids-batches/{batch_id}/certify", payload or {}, headers
        )

    def request_retest(self, batch_id, headers, payload=None):
        return self._call(
            "POST", f"/solids-batches/{batch_id}/retest-request", payload or {}, headers
        )

    # ------------------------------------------------------------ lab results
    def get_lab_result(self, result_id, headers):
        return self._call("GET", f"/lab-results/{result_id}", None, headers)

    def list_lab_results(self, headers, params=None):
        return self._call("GET", "/lab-results", None, headers, params)

    # ------------------------------------------------------------ sites
    def create_site(self, payload, headers):
        return self._call("POST", "/land-application-sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._call("GET", f"/land-application-sites/{site_id}", None, headers)

    def list_sites(self, headers, params=None):
        return self._call("GET", "/land-application-sites", None, headers, params)

    def submit_permit(self, site_id, headers, payload=None):
        return self._call(
            "POST", f"/land-application-sites/{site_id}/submit-permit",
            payload or {}, headers,
        )

    def permit_decision(self, site_id, payload, headers):
        return self._call(
            "POST", f"/land-application-sites/{site_id}/permit-decision",
            payload, headers,
        )

    def restrict_site(self, site_id, payload, headers):
        return self._call(
            "POST", f"/land-application-sites/{site_id}/restrict", payload, headers
        )

    def reinstate_site(self, site_id, headers, payload=None):
        return self._call(
            "POST", f"/land-application-sites/{site_id}/reinstate",
            payload or {}, headers,
        )

    def close_site(self, site_id, headers, payload=None):
        return self._call(
            "POST", f"/land-application-sites/{site_id}/close", payload or {}, headers
        )

    def get_loading_summary(self, site_id, headers):
        return self._call(
            "GET", f"/land-application-sites/{site_id}/loading-summary", None, headers
        )

    # ------------------------------------------------------------ ledger
    def get_ledger_entry(self, entry_id, headers):
        return self._call("GET", f"/loading-ledger-entries/{entry_id}", None, headers)

    def list_ledger_entries(self, headers, params=None):
        return self._call("GET", "/loading-ledger-entries", None, headers, params)

    # ------------------------------------------------------------ agreements
    def create_agreement(self, payload, headers):
        return self._call("POST", "/farmer-agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._call("GET", f"/farmer-agreements/{agreement_id}", None, headers)

    def list_agreements(self, headers, params=None):
        return self._call("GET", "/farmer-agreements", None, headers, params)

    def propose_agreement(self, agreement_id, headers, payload=None):
        return self._call(
            "POST", f"/farmer-agreements/{agreement_id}/propose", payload or {}, headers
        )

    def counter_agreement(self, agreement_id, payload, headers):
        return self._call(
            "POST", f"/farmer-agreements/{agreement_id}/counter", payload, headers
        )

    def sign_agreement(self, agreement_id, headers, payload=None):
        return self._call(
            "POST", f"/farmer-agreements/{agreement_id}/sign", payload or {}, headers
        )

    def activate_agreement(self, agreement_id, headers, payload=None):
        return self._call(
            "POST", f"/farmer-agreements/{agreement_id}/activate", payload or {}, headers
        )

    def withdraw_agreement(self, agreement_id, headers, payload=None):
        return self._call(
            "POST", f"/farmer-agreements/{agreement_id}/withdraw", payload or {}, headers
        )

    def terminate_agreement(self, agreement_id, payload, headers):
        return self._call(
            "POST", f"/farmer-agreements/{agreement_id}/terminate", payload, headers
        )

    # ------------------------------------------------------------ events
    def create_event(self, payload, headers):
        return self._call("POST", "/application-events", payload, headers)

    def get_event(self, event_id, headers):
        return self._call("GET", f"/application-events/{event_id}", None, headers)

    def list_events(self, headers, params=None):
        return self._call("GET", "/application-events", None, headers, params)

    def weather_hold(self, event_id, payload, headers):
        return self._call(
            "POST", f"/application-events/{event_id}/weather-hold", payload, headers
        )

    def reschedule_event(self, event_id, payload, headers):
        return self._call(
            "POST", f"/application-events/{event_id}/reschedule", payload, headers
        )

    def start_event(self, event_id, headers, payload=None):
        return self._call(
            "POST", f"/application-events/{event_id}/start", payload or {}, headers
        )

    def complete_event(self, event_id, headers, payload=None):
        return self._call(
            "POST", f"/application-events/{event_id}/complete", payload or {}, headers
        )

    def cancel_event(self, event_id, headers, payload=None):
        return self._call(
            "POST", f"/application-events/{event_id}/cancel", payload or {}, headers
        )

    def void_event(self, event_id, headers, payload=None):
        return self._call(
            "POST", f"/application-events/{event_id}/void", payload or {}, headers
        )

    def create_haul_ticket(self, event_id, payload, headers):
        return self._call(
            "POST", f"/application-events/{event_id}/haul-tickets", payload, headers
        )

    def list_event_haul_tickets(self, event_id, headers, params=None):
        return self._call(
            "GET", f"/application-events/{event_id}/haul-tickets", None, headers, params
        )

    def get_haul_ticket(self, ticket_id, headers):
        return self._call("GET", f"/haul-tickets/{ticket_id}", None, headers)

    def list_haul_tickets(self, headers, params=None):
        return self._call("GET", "/haul-tickets", None, headers, params)

    # ------------------------------------------------------------ outlets
    def create_outlet(self, payload, headers):
        return self._call("POST", "/alternative-outlets", payload, headers)

    def get_outlet(self, outlet_id, headers):
        return self._call("GET", f"/alternative-outlets/{outlet_id}", None, headers)

    def list_outlets(self, headers, params=None):
        return self._call("GET", "/alternative-outlets", None, headers, params)

    def set_outlet_status(self, outlet_id, payload, headers):
        return self._call(
            "POST", f"/alternative-outlets/{outlet_id}/set-status", payload, headers
        )

    # ------------------------------------------------------------ diversion orders
    def create_diversion_order(self, payload, headers):
        return self._call("POST", "/diversion-orders", payload, headers)

    def get_diversion_order(self, order_id, headers):
        return self._call("GET", f"/diversion-orders/{order_id}", None, headers)

    def list_diversion_orders(self, headers, params=None):
        return self._call("GET", "/diversion-orders", None, headers, params)

    def commit_order(self, order_id, headers, payload=None):
        return self._call(
            "POST", f"/diversion-orders/{order_id}/commit", payload or {}, headers
        )

    def settle_order(self, order_id, headers, payload=None):
        return self._call(
            "POST", f"/diversion-orders/{order_id}/settle", payload or {}, headers
        )

    def void_order(self, order_id, headers, payload=None):
        return self._call(
            "POST", f"/diversion-orders/{order_id}/void", payload or {}, headers
        )

    def get_cost_comparison(self, order_id, headers):
        return self._call(
            "GET", f"/diversion-orders/{order_id}/cost-comparison", None, headers
        )

    # ------------------------------------------------------------ complaints
    def create_complaint(self, payload, headers):
        return self._call("POST", "/odor-complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._call("GET", f"/odor-complaints/{complaint_id}", None, headers)

    def list_complaints(self, headers, params=None):
        return self._call("GET", "/odor-complaints", None, headers, params)

    def investigate_complaint(self, complaint_id, headers, payload=None):
        return self._call(
            "POST", f"/odor-complaints/{complaint_id}/investigate",
            payload or {}, headers,
        )

    def resolve_complaint(self, complaint_id, payload, headers):
        return self._call(
            "POST", f"/odor-complaints/{complaint_id}/resolve", payload, headers
        )

    def close_complaint(self, complaint_id, headers, payload=None):
        return self._call(
            "POST", f"/odor-complaints/{complaint_id}/close", payload or {}, headers
        )

    # ------------------------------------------------------------ annual reports
    def create_annual_report(self, payload, headers):
        return self._call("POST", "/annual-reports", payload, headers)

    def get_annual_report(self, report_id, headers):
        return self._call("GET", f"/annual-reports/{report_id}", None, headers)

    def list_annual_reports(self, headers, params=None):
        return self._call("GET", "/annual-reports", None, headers, params)

    def submit_annual_report(self, report_id, headers, payload=None):
        return self._call(
            "POST", f"/annual-reports/{report_id}/submit", payload or {}, headers
        )

    def amend_annual_report(self, report_id, headers, payload=None):
        return self._call(
            "POST", f"/annual-reports/{report_id}/amend", payload or {}, headers
        )
