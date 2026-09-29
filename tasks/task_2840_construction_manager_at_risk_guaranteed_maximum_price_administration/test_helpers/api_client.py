"""HTTP client for the CMAR guaranteed-maximum-price administration API.

One method per endpoint of the published table. Paths are flat and sit at the
server root; a child resource is created against its parent by supplying the
parent's identifier in the request body rather than in the path. Every method
returns the raw response so a test can assert either a success envelope or an
error envelope from the same call.
"""

from typing import Any, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .types import Headers, Payload


class ApiClient(GenericApiClient):
    """Typed wrapper over the generic client, one method per endpoint."""

    # --- logical clock ----------------------------------------------------

    def set_clock(self, current_utc: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # --- projects ---------------------------------------------------------

    def create_project(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/projects", payload, headers)

    def list_projects(
        self, headers: Headers, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/projects", params or {}, headers)

    def get_project(self, project_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/projects/{project_id}", None, headers)

    def request_audit(self, project_id: str, headers: Headers) -> requests.Response:
        return self._request("POST", f"/projects/{project_id}/audit-request", {}, headers)

    def audit_action(
        self, project_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/projects/{project_id}/audit-actions", payload, headers
        )

    def shared_savings(
        self, project_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/projects/{project_id}/shared-savings", payload, headers
        )

    # --- progressive estimates -------------------------------------------

    def create_estimate(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/estimates", payload, headers)

    def submit_estimate(
        self, estimate_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"/estimates/{estimate_id}/submit", payload, headers)

    def reconcile_estimate(
        self, estimate_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/estimates/{estimate_id}/reconcile", payload, headers
        )

    def list_estimates(
        self, headers: Headers, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/estimates", params or {}, headers)

    def get_estimate(self, estimate_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/estimates/{estimate_id}", None, headers)

    # --- guaranteed-maximum-price proposals ------------------------------

    def create_gmp_proposal(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/gmp-proposals", payload, headers)

    def submit_gmp_proposal(
        self, proposal_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/gmp-proposals/{proposal_id}/submit", payload or {}, headers
        )

    def decide_gmp_proposal(
        self, proposal_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/gmp-proposals/{proposal_id}/decide", payload, headers
        )

    def list_gmp_proposals(
        self, headers: Headers, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/gmp-proposals", params or {}, headers)

    def get_gmp_proposal(self, proposal_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/gmp-proposals/{proposal_id}", None, headers)

    # --- qualification items ---------------------------------------------

    def create_qualification_item(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/qualification-items", payload, headers)

    def reconcile_allowance(
        self, item_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/qualification-items/{item_id}/allowance-reconciliation",
            payload,
            headers,
        )

    def list_qualification_items(
        self, headers: Headers, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/qualification-items", params or {}, headers)

    def get_qualification_item(self, item_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/qualification-items/{item_id}", None, headers)

    # --- work packages ----------------------------------------------------

    def create_work_package(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/work-packages", payload, headers)

    def solicit_work_package(
        self, package_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/work-packages/{package_id}/solicit", payload, headers
        )

    def set_transparency(
        self, package_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/work-packages/{package_id}/transparency", payload, headers
        )

    def award_work_package(
        self, package_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/work-packages/{package_id}/award", payload, headers
        )

    def list_work_packages(
        self, headers: Headers, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/work-packages", params or {}, headers)

    def get_work_package(self, package_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/work-packages/{package_id}", None, headers)

    # --- self-perform bids ------------------------------------------------

    def create_bid(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/self-perform-bids", payload, headers)

    def open_bid(
        self, bid_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/self-perform-bids/{bid_id}/open", payload or {}, headers
        )

    def list_bids(
        self, headers: Headers, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/self-perform-bids", params or {}, headers)

    def get_bid(self, bid_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/self-perform-bids/{bid_id}", None, headers)

    # --- subcontracts -----------------------------------------------------

    def create_subcontract(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/subcontracts", payload, headers)

    def progress_payment(
        self, subcontract_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/subcontracts/{subcontract_id}/progress-payment", payload, headers
        )

    def subcontract_status_action(
        self, subcontract_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/subcontracts/{subcontract_id}/status-action", payload, headers
        )

    def bond_claim(
        self, subcontract_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/subcontracts/{subcontract_id}/bond-claim", payload, headers
        )

    def list_subcontracts(
        self, headers: Headers, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/subcontracts", params or {}, headers)

    def get_subcontract(self, subcontract_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/subcontracts/{subcontract_id}", None, headers)

    # --- change events ----------------------------------------------------

    def create_change_event(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/change-events", payload, headers)

    def submit_change_event(
        self, event_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/change-events/{event_id}/submit", payload or {}, headers
        )

    def review_change_event(
        self, event_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/change-events/{event_id}/review", payload, headers
        )

    def classify_change_event(
        self, event_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/change-events/{event_id}/classify", payload, headers
        )

    def list_change_events(
        self, headers: Headers, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/change-events", params or {}, headers)

    def get_change_event(self, event_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/change-events/{event_id}", None, headers)

    # --- contingency draws ------------------------------------------------

    def approve_draw(
        self, draw_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/contingency-draws/{draw_id}/approve", payload, headers
        )

    def post_draw(
        self, draw_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/contingency-draws/{draw_id}/post", payload or {}, headers
        )

    def void_draw(
        self, draw_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/contingency-draws/{draw_id}/void", payload, headers
        )

    def list_draws(
        self, headers: Headers, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/contingency-draws", params or {}, headers)

    def get_draw(self, draw_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/contingency-draws/{draw_id}", None, headers)

    # --- monthly cost reports ---------------------------------------------

    def create_cost_report(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/cost-reports", payload, headers)

    def append_cost_line(
        self, report_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"/cost-reports/{report_id}/lines", payload, headers)

    def reconcile_cost_report(
        self, report_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/cost-reports/{report_id}/reconcile", payload, headers
        )

    def release_hold(
        self, report_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/cost-reports/{report_id}/release-hold", payload or {}, headers
        )

    def list_cost_reports(
        self, headers: Headers, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/cost-reports", params or {}, headers)

    def get_cost_report(self, report_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/cost-reports/{report_id}", None, headers)

    # --- escape hatch -----------------------------------------------------

    def raw(
        self,
        method: str,
        path: str,
        payload: Optional[Any] = None,
        headers: Optional[Headers] = None,
    ) -> requests.Response:
        """Issue an arbitrary request, for shape checks the typed methods forbid."""
        return self._request(method, path, payload, headers)
