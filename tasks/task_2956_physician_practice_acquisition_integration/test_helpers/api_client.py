"""HTTP client for the Practice Acquisition Integration API.

One method per endpoint declared by the PRD. Every method takes the caller's
auth headers explicitly, because the PRD requires `X-User-ID` and
`X-User-Role` on every endpoint including the reads.

Also exposes `canonical_instant()`: the PRD renders instants with exactly
three fractional digits, and this helper normalises any accepted rendering of
the same instant to a single canonical string so sub-second width can never
decide a comparison.
"""

import re
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

Headers = Dict[str, str]
Payload = Optional[Dict[str, Any]]
Params = Optional[Dict[str, Any]]

_INSTANT_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[T ]"
    r"(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?"
    r"(?P<tz>Z|[+-]\d{2}:?\d{2})?$"
)


def canonical_instant(value: Any) -> Any:
    """Normalise an ISO-8601 instant to `YYYY-MM-DDTHH:MM:SS.mmmZ`.

    Any sub-second width — absent, three digits, six digits — collapses to the
    same three-digit rendering, so a comparison never turns on precision.
    Values that are not instant-shaped are returned unchanged.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    frac = (match.group("frac") or "")[:3].ljust(3, "0")
    return f"{match.group('date')}T{match.group('time')}.{frac}Z"


def _canonical_query(value: Any) -> Any:
    """Render a query-string filter value the way the wire renders JSON.

    A Python `True` would otherwise reach the server as the string `"True"`.
    Exact-match boolean filters are sent as `true` / `false`, matching the JSON
    spelling the same fields carry in a request body and a response.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


class ApiClient(GenericApiClient):
    """Endpoint-per-method client for the Practice Acquisition Integration API."""

    def _request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ) -> requests.Response:
        """Delegate to the runner client, canonicalising query booleans only.

        Request bodies keep genuine JSON booleans; only the values that travel
        in a query string are rewritten, so a filter never depends on Python's
        capitalisation of `True`.
        """
        if method.upper() in ("GET", "DELETE") and isinstance(payload, dict):
            payload = {key: _canonical_query(val) for key, val in payload.items()}
        if isinstance(params, dict):
            params = {key: _canonical_query(val) for key, val in params.items()}
        return super()._request(method, path, payload, headers, params)

    # --- Logical clock -----------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Acquisitions ------------------------------------------------------

    def create_acquisition(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/acquisitions", payload, headers)

    def list_acquisitions(
        self, params: Params, headers: Headers
    ) -> requests.Response:
        return self._request("GET", "/acquisitions", params, headers)

    def get_acquisition(
        self, acquisition_id: str, headers: Headers
    ) -> requests.Response:
        return self._request("GET", f"/acquisitions/{acquisition_id}", None, headers)

    def set_acquisition_status(
        self, acquisition_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/acquisitions/{acquisition_id}/status", payload, headers
        )

    def set_compliance_clearance(
        self, acquisition_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/acquisitions/{acquisition_id}/compliance-clearance",
            payload,
            headers,
        )

    # --- Physicians --------------------------------------------------------

    def create_physician(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/physicians", payload, headers)

    def list_physicians(
        self, params: Params, headers: Headers
    ) -> requests.Response:
        return self._request("GET", "/physicians", params, headers)

    def get_physician(self, physician_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/physicians/{physician_id}", None, headers)

    # --- Valuation opinions ------------------------------------------------

    def create_valuation_opinion(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/valuation-opinions", payload, headers)

    def list_valuation_opinions(
        self, params: Params, headers: Headers
    ) -> requests.Response:
        return self._request("GET", "/valuation-opinions", params, headers)

    def get_valuation_opinion(
        self, opinion_id: str, headers: Headers
    ) -> requests.Response:
        return self._request("GET", f"/valuation-opinions/{opinion_id}", None, headers)

    def set_valuation_opinion_status(
        self, opinion_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/valuation-opinions/{opinion_id}/status", payload, headers
        )

    # --- Compensation plans ------------------------------------------------

    def create_compensation_plan(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/compensation-plans", payload, headers)

    def list_compensation_plans(
        self, params: Params, headers: Headers
    ) -> requests.Response:
        return self._request("GET", "/compensation-plans", params, headers)

    def get_compensation_plan(self, plan_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/compensation-plans/{plan_id}", None, headers)

    def set_compensation_plan_status(
        self, plan_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/compensation-plans/{plan_id}/status", payload, headers
        )

    # --- Payer contracts ---------------------------------------------------

    def create_payer_contract(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/payer-contracts", payload, headers)

    def list_payer_contracts(
        self, params: Params, headers: Headers
    ) -> requests.Response:
        return self._request("GET", "/payer-contracts", params, headers)

    def get_payer_contract(self, contract_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/payer-contracts/{contract_id}", None, headers)

    def act_on_novation(
        self, contract_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/payer-contracts/{contract_id}/novation", payload, headers
        )

    # --- Credentialing packages -------------------------------------------

    def create_credentialing_package(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/credentialing-packages", payload, headers)

    def list_credentialing_packages(
        self, params: Params, headers: Headers
    ) -> requests.Response:
        return self._request("GET", "/credentialing-packages", params, headers)

    def get_credentialing_package(
        self, package_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/credentialing-packages/{package_id}", None, headers
        )

    def set_credentialing_package_status(
        self, package_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/credentialing-packages/{package_id}/status", payload, headers
        )

    # --- EHR migration batches --------------------------------------------

    def create_ehr_migration_batch(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/ehr-migration-batches", payload, headers)

    def list_ehr_migration_batches(
        self, params: Params, headers: Headers
    ) -> requests.Response:
        return self._request("GET", "/ehr-migration-batches", params, headers)

    def get_ehr_migration_batch(
        self, batch_id: str, headers: Headers
    ) -> requests.Response:
        return self._request("GET", f"/ehr-migration-batches/{batch_id}", None, headers)

    def progress_ehr_migration_batch(
        self, batch_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/ehr-migration-batches/{batch_id}/progress", payload, headers
        )

    # --- Staff transition offers ------------------------------------------

    def create_staff_transition_offer(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/staff-transition-offers", payload, headers)

    def list_staff_transition_offers(
        self, params: Params, headers: Headers
    ) -> requests.Response:
        return self._request("GET", "/staff-transition-offers", params, headers)

    def get_staff_transition_offer(
        self, offer_id: str, headers: Headers
    ) -> requests.Response:
        return self._request("GET", f"/staff-transition-offers/{offer_id}", None, headers)

    def set_staff_transition_offer_status(
        self, offer_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/staff-transition-offers/{offer_id}/status", payload, headers
        )

    # --- Billing conversions ----------------------------------------------

    def create_billing_conversion(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/billing-conversions", payload, headers)

    def list_billing_conversions(
        self, params: Params, headers: Headers
    ) -> requests.Response:
        return self._request("GET", "/billing-conversions", params, headers)

    def get_billing_conversion(
        self, conversion_id: str, headers: Headers
    ) -> requests.Response:
        return self._request("GET", f"/billing-conversions/{conversion_id}", None, headers)

    def set_billing_conversion_status(
        self, conversion_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/billing-conversions/{conversion_id}/status", payload, headers
        )

    # --- Readiness tasks ---------------------------------------------------

    def create_readiness_task(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/readiness-tasks", payload, headers)

    def list_readiness_tasks(
        self, params: Params, headers: Headers
    ) -> requests.Response:
        return self._request("GET", "/readiness-tasks", params, headers)

    def get_readiness_task(self, task_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/readiness-tasks/{task_id}", None, headers)

    def set_readiness_task_status(
        self, task_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/readiness-tasks/{task_id}/status", payload, headers
        )

    # --- Liability items ---------------------------------------------------

    def create_liability_item(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/liability-items", payload, headers)

    def list_liability_items(
        self, params: Params, headers: Headers
    ) -> requests.Response:
        return self._request("GET", "/liability-items", params, headers)

    def get_liability_item(self, item_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/liability-items/{item_id}", None, headers)

    def set_liability_disposition(
        self, item_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/liability-items/{item_id}/disposition", payload, headers
        )

    # --- Performance reports ----------------------------------------------

    def create_performance_report(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/performance-reports", payload, headers)

    def list_performance_reports(
        self, params: Params, headers: Headers
    ) -> requests.Response:
        return self._request("GET", "/performance-reports", params, headers)

    def get_performance_report(self, report_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/performance-reports/{report_id}", None, headers)
