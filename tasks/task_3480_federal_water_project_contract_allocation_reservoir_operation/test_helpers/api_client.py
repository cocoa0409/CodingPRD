"""HTTP client for the Federal Water Allocation API.

One method per endpoint the contract declares (PRD §4). Every method returns
the raw response so a test can assert on the status code as well as the body.
Query filters and pagination are passed as ``params``; request bodies as
``payload``.

All routes live under the ``/water`` prefix with a single exception: the
test-driving clock is mounted outside the prefix at
``POST /_clock/set_current_utc`` (PRD §2.4).

A module-level singleton ``api_client`` is provided for convenience; the
pytest ``api`` fixture returns it. Because ``GenericApiClient`` reads
``API_BASE_URL`` from the environment at construction and the runner sets
that variable before pytest starts, the singleton always points at the
server under test.
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
    ``2027-01-15T00:00:00Z`` and ``2027-01-15T00:00:00.000Z`` compare equal.
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

    # ── Logical clock (outside the /water prefix, PRD §2.4) ───────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Districts ──────────────────────────────────────────────────────────

    def create_district(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/water/districts", payload, headers)

    def get_district(self, district_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/water/districts/{district_id}", None, headers)

    # ── Contracts ──────────────────────────────────────────────────────────

    def create_contract(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/water/contracts", payload, headers)

    def get_contract(self, contract_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/water/contracts/{contract_id}", None, headers)

    def list_contracts(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/water/contracts", params, headers)

    def suspend_contract(self, contract_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/water/contracts/{contract_id}/suspend", {}, headers)

    # ── Water years ────────────────────────────────────────────────────────

    def create_water_year(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/water/water-years", payload, headers)

    def get_water_year(self, year_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/water/water-years/{year_id}", None, headers)

    def finalize_water_year(self, year_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/water/water-years/{year_id}/finalize", {}, headers)

    # ── Hydrology observations ─────────────────────────────────────────────

    def create_hydrology_observation(self, year_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/water/water-years/{year_id}/hydrology-observations", payload, headers)

    def list_hydrology_observations(self, year_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/water/water-years/{year_id}/hydrology-observations", params, headers)

    # ── Allocation announcements ───────────────────────────────────────────

    def create_allocation_announcement(self, year_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/water/water-years/{year_id}/allocation-announcements", payload, headers)

    def list_allocation_announcements(self, year_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/water/water-years/{year_id}/allocation-announcements", params, headers)

    def publish_allocation_announcement(self, announcement_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/water/allocation-announcements/{announcement_id}/publish", {}, headers)

    # ── Allocation lines ───────────────────────────────────────────────────

    def list_allocation_lines(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/water/allocation-lines", params, headers)

    def get_allocation_line(self, line_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/water/allocation-lines/{line_id}", None, headers)

    # ── Reservoir ──────────────────────────────────────────────────────────

    def create_reservoir(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/water/reservoirs", payload, headers)

    def get_reservoir(self, reservoir_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/water/reservoirs/{reservoir_id}", None, headers)

    # ── Release orders ─────────────────────────────────────────────────────

    def create_release_order(self, reservoir_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/water/reservoirs/{reservoir_id}/release-orders", payload, headers)

    def list_release_orders(self, reservoir_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/water/reservoirs/{reservoir_id}/release-orders", params, headers)

    def execute_release_order(self, release_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/water/release-orders/{release_id}/execute", {}, headers)

    # ── Environmental constraints ──────────────────────────────────────────

    def create_environmental_constraint(self, reservoir_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/water/reservoirs/{reservoir_id}/environmental-constraints", payload, headers)

    def list_environmental_constraints(self, reservoir_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/water/reservoirs/{reservoir_id}/environmental-constraints", params, headers)

    # ── Compliance incidents ───────────────────────────────────────────────

    def list_compliance_incidents(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/water/compliance-incidents", params, headers)

    def get_compliance_incident(self, incident_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/water/compliance-incidents/{incident_id}", None, headers)

    def resolve_compliance_incident(self, incident_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/water/compliance-incidents/{incident_id}/resolve", payload, headers)

    # ── Delivery orders ────────────────────────────────────────────────────

    def create_delivery_order(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/water/delivery-orders", payload, headers)

    def list_delivery_orders(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/water/delivery-orders", params, headers)

    def get_delivery_order(self, order_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/water/delivery-orders/{order_id}", None, headers)

    def record_delivery(self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/water/delivery-orders/{order_id}/record-delivery", payload, headers)

    # ── Revenue periods ────────────────────────────────────────────────────

    def create_revenue_period(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/water/revenue-periods", payload, headers)

    def list_revenue_periods(self, reservoir_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/water/reservoirs/{reservoir_id}/revenue-periods", params, headers)

    def settle_revenue_period(self, period_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/water/revenue-periods/{period_id}/settle", {}, headers)

    # ── Transfer requests ──────────────────────────────────────────────────

    def create_transfer_request(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/water/transfer-requests", payload, headers)

    def list_transfer_requests(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/water/transfer-requests", params, headers)

    def get_transfer_request(self, transfer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/water/transfer-requests/{transfer_id}", None, headers)

    def decide_transfer_request(self, transfer_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/water/transfer-requests/{transfer_id}/decide", payload, headers)

    def resubmit_transfer_request(self, transfer_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/water/transfer-requests/{transfer_id}/resubmit", payload, headers)

    def execute_transfer_request(self, transfer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/water/transfer-requests/{transfer_id}/execute", {}, headers)

    # ── Impact reviews ─────────────────────────────────────────────────────

    def create_impact_review(self, transfer_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/water/transfer-requests/{transfer_id}/impact-reviews", payload, headers)

    def list_impact_reviews(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/water/impact-reviews", params, headers)

    def get_impact_review(self, review_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/water/impact-reviews/{review_id}", None, headers)

    def resolve_impact_review(self, review_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/water/impact-reviews/{review_id}/resolve", payload, headers)

    # ── Shortage agreements ────────────────────────────────────────────────

    def create_shortage_agreement(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/water/shortage-agreements", payload, headers)

    def get_shortage_agreement(self, agreement_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/water/shortage-agreements/{agreement_id}", None, headers)

    def ratify_shortage_agreement(self, agreement_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/water/shortage-agreements/{agreement_id}/ratify", {}, headers)

    def activate_shortage_agreement(self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/water/shortage-agreements/{agreement_id}/activate", payload, headers)


# Module-level singleton. The pytest ``api`` fixture returns this instance;
# tests can also import it directly. Fixtures always receive the client as an
# explicit parameter, so nothing in the fixture layer depends on this binding.
api_client = ApiClient()
