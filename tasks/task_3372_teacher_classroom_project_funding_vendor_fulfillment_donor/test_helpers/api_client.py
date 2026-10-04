"""HTTP client for the teacher-classroom-funding API.

One method per endpoint the PRD declares. Every method returns the raw
response so a test can assert on the status code as well as the body. Query
filters and pagination go through ``params``; request bodies through
``payload``.

Also hosts ``canonical_instant``: instants are rendered by the contract as
ISO 8601 UTC with three fractional digits, but an equal instant may
legitimately arrive with none, so timestamp comparisons run on a canonical
three-digit form instead of on raw strings.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant so two spellings of one instant match.

    Both sides are reduced to ``YYYY-MM-DDTHH:MM:SS.mmmZ`` so that
    ``2026-10-01T00:00:00Z`` and ``2026-10-01T00:00:00.000Z`` compare equal.
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

    # ── Test-driving (outside the /giving business surface) ────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_expiration_sweep(self, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_sweeps/expiration_run", {}, headers)

    # ── Schools ────────────────────────────────────────────────────────────

    def create_school(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/giving/schools", payload, headers)

    def get_school(self, school_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/giving/schools/{school_id}", None, headers)

    # ── Teachers ───────────────────────────────────────────────────────────

    def create_teacher(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/giving/teachers", payload, headers)

    def get_teacher(self, teacher_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/giving/teachers/{teacher_id}", None, headers)

    def list_teachers(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/giving/teachers", params, headers)

    def review_teacher_employment(
        self, teacher_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/giving/teachers/{teacher_id}/employment-review", payload, headers)

    # ── Vendors and catalog ────────────────────────────────────────────────

    def create_vendor(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/giving/vendors", payload, headers)

    def get_vendor(self, vendor_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/giving/vendors/{vendor_id}", None, headers)

    def suspend_vendor(self, vendor_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/giving/vendors/{vendor_id}/suspend", {}, headers)

    def create_catalog_item(
        self, vendor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/giving/vendors/{vendor_id}/catalog-items", payload, headers)

    def list_catalog_items(
        self, vendor_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/giving/vendors/{vendor_id}/catalog-items", params, headers)

    def patch_catalog_item(
        self, vendor_id: str, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"/giving/vendors/{vendor_id}/catalog-items/{item_id}", payload, headers)

    # ── Projects and items ─────────────────────────────────────────────────

    def create_project(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/giving/projects", payload, headers)

    def list_projects(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/giving/projects", params, headers)

    def get_project(self, project_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/giving/projects/{project_id}", None, headers)

    def add_project_item(
        self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/giving/projects/{project_id}/items", payload, headers)

    def get_project_item(self, item_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/giving/project-items/{item_id}", None, headers)

    def list_project_items(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/giving/project-items", params, headers)

    def submit_project(
        self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/giving/projects/{project_id}/submit", payload, headers)

    def review_project(
        self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/giving/projects/{project_id}/review", payload, headers)

    # ── Donors and donations ───────────────────────────────────────────────

    def create_donor(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/giving/donors", payload, headers)

    def get_donor(self, donor_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/giving/donors/{donor_id}", None, headers)

    def create_donation(
        self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/giving/projects/{project_id}/donations", payload, headers)

    def get_donation(self, donation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/giving/donations/{donation_id}", None, headers)

    def list_donations(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/giving/donations", params, headers)

    def reallocation_choice(
        self, donation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/giving/donations/{donation_id}/reallocation-choice", payload, headers)

    # ── Match campaigns ────────────────────────────────────────────────────

    def create_match_campaign(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/giving/match-campaigns", payload, headers)

    def get_match_campaign(self, campaign_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/giving/match-campaigns/{campaign_id}", None, headers)

    # ── Purchase orders ────────────────────────────────────────────────────

    def get_purchase_order(self, po_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/giving/purchase-orders/{po_id}", None, headers)

    def list_purchase_orders(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/giving/purchase-orders", params, headers)

    def advance_purchase_order(
        self, po_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/giving/purchase-orders/{po_id}/advance", payload, headers)

    # ── Thank-you packages ─────────────────────────────────────────────────

    def submit_thank_you_package(
        self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/giving/projects/{project_id}/thank-you-package", payload, headers)

    def get_thank_you_package(self, project_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/giving/projects/{project_id}/thank-you-package", None, headers)

    # ── Fraud cases ────────────────────────────────────────────────────────

    def get_fraud_case(self, case_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/giving/fraud-cases/{case_id}", None, headers)

    def list_fraud_cases(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/giving/fraud-cases", params, headers)

    def resolve_fraud_case(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/giving/fraud-cases/{case_id}/resolve", payload, headers)

    # ── Equity funds ───────────────────────────────────────────────────────

    def create_equity_fund(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/giving/equity-funds", payload, headers)

    def get_equity_fund(self, fund_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/giving/equity-funds/{fund_id}", None, headers)

    def allocate_equity_fund(
        self, fund_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/giving/equity-funds/{fund_id}/allocate", payload, headers)


api_client = ApiClient()
