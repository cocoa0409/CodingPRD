"""Typed HTTP client — one method per declared endpoint of the parity API."""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import CLOCK_PATH

Headers = Optional[Dict[str, str]]
Payload = Optional[Dict[str, Any]]


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO-8601 UTC instant to exactly three fractional digits.

    The PRD renders every instant with three fractional digits, but comparing
    raw strings would make a `...T00:00:00Z` / `...T00:00:00.000Z` difference
    look like a business defect.  Tests compare canonical forms instead.
    """
    if value is None:
        return None
    text = str(value).strip()
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
    """Endpoint methods for the Mental Health Parity Comparative Analysis API."""

    # ─── Logical clock ────────────────────────────────────────────────────────

    def set_clock(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", CLOCK_PATH, payload, headers)

    # ─── Administrators ───────────────────────────────────────────────────────

    def create_administrator(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/parity/administrators", payload, headers)

    def get_administrator(self, administrator_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/parity/administrators/{administrator_id}", None, headers)

    # ─── Plan years ───────────────────────────────────────────────────────────

    def create_plan_year(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/parity/plan-years", payload, headers)

    def get_plan_year(self, plan_year_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/parity/plan-years/{plan_year_id}", None, headers)

    def list_plan_years(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", "/parity/plan-years", params, headers)

    # ─── Benefit classifications ──────────────────────────────────────────────

    def create_classification(
        self, plan_year_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/parity/plan-years/{plan_year_id}/classifications", payload, headers
        )

    def list_plan_year_classifications(
        self, plan_year_id: str, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/parity/plan-years/{plan_year_id}/classifications", params, headers
        )

    def get_classification(self, classification_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/parity/classifications/{classification_id}", None, headers)

    # ─── Treatment limitations ────────────────────────────────────────────────

    def create_treatment_limitation(
        self, classification_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/parity/classifications/{classification_id}/treatment-limitations",
            payload,
            headers,
        )

    def list_treatment_limitations(
        self, classification_id: str, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/parity/classifications/{classification_id}/treatment-limitations",
            params,
            headers,
        )

    # ─── Parity tests ─────────────────────────────────────────────────────────

    def create_parity_test(
        self, classification_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/parity/classifications/{classification_id}/parity-tests", payload, headers
        )

    def list_parity_tests(
        self, classification_id: str, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/parity/classifications/{classification_id}/parity-tests", params, headers
        )

    # ─── NQTL inventory ───────────────────────────────────────────────────────

    def create_nqtl_item(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/parity/nqtl-items", payload, headers)

    def get_nqtl_item(self, nqtl_item_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/parity/nqtl-items/{nqtl_item_id}", None, headers)

    def list_nqtl_items(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", "/parity/nqtl-items", params, headers)

    def create_determination(
        self, nqtl_item_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/parity/nqtl-items/{nqtl_item_id}/determinations", payload, headers
        )

    def list_participant_notices(
        self, nqtl_item_id: str, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/parity/nqtl-items/{nqtl_item_id}/participant-notices", params, headers
        )

    # ─── Comparative analyses ─────────────────────────────────────────────────

    def create_analysis(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/parity/comparative-analyses", payload, headers)

    def get_analysis(self, analysis_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/parity/comparative-analyses/{analysis_id}", None, headers)

    def list_analyses(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", "/parity/comparative-analyses", params, headers)

    def submit_analysis(
        self, analysis_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/parity/comparative-analyses/{analysis_id}/submit", payload or {}, headers
        )

    def review_analysis(
        self, analysis_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/parity/comparative-analyses/{analysis_id}/review", payload, headers
        )

    def reopen_analysis(
        self, analysis_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/parity/comparative-analyses/{analysis_id}/reopen", payload or {}, headers
        )

    # ─── Vendor data requests ─────────────────────────────────────────────────

    def create_vendor_request(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/parity/vendor-requests", payload, headers)

    def get_vendor_request(self, vendor_request_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/parity/vendor-requests/{vendor_request_id}", None, headers)

    def list_vendor_requests(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", "/parity/vendor-requests", params, headers)

    def escalate_vendor_request(
        self, vendor_request_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/parity/vendor-requests/{vendor_request_id}/escalate", payload or {}, headers
        )

    # ─── Data submissions ─────────────────────────────────────────────────────

    def create_data_submission(
        self, vendor_request_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/parity/vendor-requests/{vendor_request_id}/data-submissions", payload, headers
        )

    def get_data_submission(self, submission_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/parity/data-submissions/{submission_id}", None, headers)

    def list_data_submissions(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", "/parity/data-submissions", params, headers)

    # ─── Corrective action plans ──────────────────────────────────────────────

    def create_corrective_action_plan(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/parity/corrective-action-plans", payload, headers)

    def get_corrective_action_plan(self, cap_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/parity/corrective-action-plans/{cap_id}", None, headers)

    def list_corrective_action_plans(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", "/parity/corrective-action-plans", params, headers)

    def decide_corrective_action_plan(
        self, cap_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/parity/corrective-action-plans/{cap_id}/decision", payload, headers
        )

    def close_corrective_action_plan(
        self, cap_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/parity/corrective-action-plans/{cap_id}/closure", payload, headers
        )

    # ─── Regulator requests ───────────────────────────────────────────────────

    def create_regulator_request(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/parity/regulator-requests", payload, headers)

    def get_regulator_request(self, request_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/parity/regulator-requests/{request_id}", None, headers)

    def list_regulator_requests(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", "/parity/regulator-requests", params, headers)

    def respond_regulator_request(
        self, request_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/parity/regulator-requests/{request_id}/respond", payload, headers
        )

    def adjudicate_regulator_request(
        self, request_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/parity/regulator-requests/{request_id}/adjudicate", payload, headers
        )


api_client = ApiClient()
