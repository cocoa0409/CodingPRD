"""HTTP client for the Retail Shopper Insights API.

One method per endpoint declared in the contract. Every method returns the raw
response so tests can assert on status codes and envelopes. List endpoints take
``params`` for pagination/filtering; write endpoints take ``payload``. All
paths are mounted under the ``/shopper-insights`` prefix.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for every route the contract declares."""

    # ── Logical clock ──────────────────────────────────────────────────────

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST",
            "/shopper-insights/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    # ── Supplier accounts ──────────────────────────────────────────────────

    def create_supplier_account(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/shopper-insights/supplier-accounts", payload, headers)

    def get_supplier_account(self, account_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/shopper-insights/supplier-accounts/{account_id}", None, headers)

    def list_account_contracts(self, account_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request(
            "GET", f"/shopper-insights/supplier-accounts/{account_id}/subscription-contracts", params, headers
        )

    def list_account_grants(self, account_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request(
            "GET", f"/shopper-insights/supplier-accounts/{account_id}/clean-room-grants", params, headers
        )

    # ── Subscription contracts ─────────────────────────────────────────────

    def create_subscription_contract(self, account_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/shopper-insights/supplier-accounts/{account_id}/subscription-contracts", payload, headers
        )

    def get_contract(self, contract_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/shopper-insights/subscription-contracts/{contract_id}", None, headers)

    def amend_contract(self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/shopper-insights/subscription-contracts/{contract_id}/amend", payload, headers
        )

    def suspend_contract(self, contract_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/shopper-insights/subscription-contracts/{contract_id}/suspend", None, headers
        )

    def terminate_contract(self, contract_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/shopper-insights/subscription-contracts/{contract_id}/terminate", None, headers
        )

    # ── Category scopes ────────────────────────────────────────────────────

    def add_category_scope(self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/shopper-insights/subscription-contracts/{contract_id}/category-scopes", payload, headers
        )

    def list_category_scopes(self, contract_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request(
            "GET", f"/shopper-insights/subscription-contracts/{contract_id}/category-scopes", params, headers
        )

    def list_contract_reports(self, contract_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request(
            "GET", f"/shopper-insights/subscription-contracts/{contract_id}/insight-reports", params, headers
        )

    def list_contract_segments(self, contract_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request(
            "GET", f"/shopper-insights/subscription-contracts/{contract_id}/audience-segments", params, headers
        )

    def list_contract_deliverables(self, contract_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request(
            "GET", f"/shopper-insights/subscription-contracts/{contract_id}/review-deliverables", params, headers
        )

    def list_contract_forecasts(self, contract_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request(
            "GET", f"/shopper-insights/subscription-contracts/{contract_id}/new-item-forecasts", params, headers
        )

    # ── Panel households ───────────────────────────────────────────────────

    def ingest_households(self, households: list, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/shopper-insights/panel-households", {"households": households}, headers)

    # ── Insight reports ────────────────────────────────────────────────────

    def create_insight_report(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/shopper-insights/insight-reports", payload, headers)

    def get_insight_report(self, report_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/shopper-insights/insight-reports/{report_id}", None, headers)

    def list_report_deliverables(self, report_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request(
            "GET", f"/shopper-insights/insight-reports/{report_id}/review-deliverables", params, headers
        )

    def generate_report(self, report_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/shopper-insights/insight-reports/{report_id}/generate", None, headers)

    def cancel_report(self, report_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/shopper-insights/insight-reports/{report_id}/cancel", None, headers)

    def export_report(self, report_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/shopper-insights/insight-reports/{report_id}/export", None, headers)

    # ── Audience segments ──────────────────────────────────────────────────

    def create_segment(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/shopper-insights/audience-segments", payload, headers)

    def get_segment(self, segment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/shopper-insights/audience-segments/{segment_id}", None, headers)

    def list_segment_activations(self, segment_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request(
            "GET", f"/shopper-insights/audience-segments/{segment_id}/activations", params, headers
        )

    def submit_segment(self, segment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/shopper-insights/audience-segments/{segment_id}/submit", None, headers)

    def approve_segment(self, segment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/shopper-insights/audience-segments/{segment_id}/approve", None, headers)

    def reject_segment(self, segment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/shopper-insights/audience-segments/{segment_id}/reject", None, headers)

    # ── Segment activations ────────────────────────────────────────────────

    def create_activation(self, segment_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/shopper-insights/audience-segments/{segment_id}/activations", payload, headers
        )

    def launch_activation(self, activation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/shopper-insights/segment-activations/{activation_id}/launch", None, headers
        )

    def halt_activation(self, activation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/shopper-insights/segment-activations/{activation_id}/halt", None, headers
        )

    # ── Incrementality studies ─────────────────────────────────────────────

    def create_study(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/shopper-insights/incrementality-studies", payload, headers)

    def get_study(self, study_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/shopper-insights/incrementality-studies/{study_id}", None, headers)

    def start_study(self, study_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/shopper-insights/incrementality-studies/{study_id}/start", None, headers
        )

    def submit_review_study(self, study_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/shopper-insights/incrementality-studies/{study_id}/submit-review", None, headers
        )

    def publish_study(self, study_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/shopper-insights/incrementality-studies/{study_id}/publish", None, headers
        )

    def revise_study(self, study_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/shopper-insights/incrementality-studies/{study_id}/revise", None, headers
        )

    # ── Clean-room grants and queries ──────────────────────────────────────

    def create_grant(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/shopper-insights/clean-room-grants", payload, headers)

    def get_grant(self, grant_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/shopper-insights/clean-room-grants/{grant_id}", None, headers)

    def approve_grant(self, grant_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/shopper-insights/clean-room-grants/{grant_id}/approve", None, headers)

    def deny_grant(self, grant_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/shopper-insights/clean-room-grants/{grant_id}/deny", payload, headers)

    def revoke_grant(self, grant_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/shopper-insights/clean-room-grants/{grant_id}/revoke", None, headers)

    def submit_query(self, grant_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/shopper-insights/clean-room-grants/{grant_id}/queries", payload, headers
        )

    def list_grant_queries(self, grant_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request(
            "GET", f"/shopper-insights/clean-room-grants/{grant_id}/queries", params, headers
        )

    # ── Line review cycles ─────────────────────────────────────────────────

    def create_cycle(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/shopper-insights/line-review-cycles", payload, headers)

    def get_cycle(self, cycle_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/shopper-insights/line-review-cycles/{cycle_id}", None, headers)

    def lock_cycle(self, cycle_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/shopper-insights/line-review-cycles/{cycle_id}/lock", None, headers)

    def complete_cycle(self, cycle_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/shopper-insights/line-review-cycles/{cycle_id}/complete", None, headers
        )

    # ── Review deliverables ────────────────────────────────────────────────

    def create_deliverable(self, cycle_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/shopper-insights/line-review-cycles/{cycle_id}/deliverables", payload, headers
        )

    def list_cycle_deliverables(self, cycle_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request(
            "GET", f"/shopper-insights/line-review-cycles/{cycle_id}/deliverables", params, headers
        )

    def submit_deliverable(self, deliverable_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/shopper-insights/review-deliverables/{deliverable_id}/submit", None, headers
        )

    def accept_deliverable(self, deliverable_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/shopper-insights/review-deliverables/{deliverable_id}/accept", None, headers
        )

    def reject_deliverable(self, deliverable_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/shopper-insights/review-deliverables/{deliverable_id}/reject", None, headers
        )

    # ── New-item forecasts ─────────────────────────────────────────────────

    def create_forecast(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/shopper-insights/new-item-forecasts", payload, headers)

    # ── Audit events ───────────────────────────────────────────────────────

    def list_audit_events(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/shopper-insights/audit-events", params, headers)


api_client = ApiClient()
