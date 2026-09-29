"""Domain API client: one method per endpoint in §4.

Unwrap convention
-----------------
Every method returns the raw `requests.Response`. Tests unwrap it exactly once,
through `validate_success` / `validate_error` / `validate_paginated`; fixtures
unwrap it exactly once through `get_success_data`. No method in this module
reaches into `body["data"]` itself, so there is no second unwrap anywhere.

Timestamp canonicalisation
--------------------------
§2.4 fixes `created_at` at "ISO 8601 UTC notation with exactly three
fractional-second digits", but the instants a test pins are written the way the
clock endpoint takes them (`2026-06-15T00:00:00Z`). `canonical_instant` folds
both spellings onto one comparable form so a sub-second width difference can
never masquerade as a business-logic defect. Use it — or the
`assert_instant_equals` helper in assertions.py — for every timestamp assertion.
"""

import re
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[Tt](\d{2}:\d{2}:\d{2})(?:\.(\d+))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Fold an ISO-8601 UTC instant onto `YYYY-MM-DDTHH:MM:SS.mmmZ`.

    Trailing fractional digits are padded or truncated to exactly three so that
    `2026-06-15T00:00:00Z`, `...:00.000Z` and `...:00.000000Z` all compare equal.
    A value that is not an instant (None, or a plain calendar date) is returned
    unchanged so date fields stay comparable too.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    date_part, time_part, frac, offset = match.groups()
    frac = (frac or "")[:3].ljust(3, "0")
    suffix = "Z"
    if offset and offset not in ("Z", "z"):
        suffix = offset  # non-UTC offsets are preserved rather than silently shifted
    return "{}T{}.{}{}".format(date_part, time_part, frac, suffix)


class ApiClient(GenericApiClient):
    """One method per endpoint of the Nutrient Trading & Watershed Load API."""

    # ------------------------------------------------------------------ clock
    def set_clock(self, current_utc: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # -------------------------------------------------------------- watersheds
    def create_watershed(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/watersheds", payload, headers)

    def set_program_status(
        self, watershed_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/watersheds/{}/program-status".format(watershed_id), payload, headers
        )

    def get_watershed(self, watershed_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", "/watersheds/{}".format(watershed_id), None, headers)

    # ------------------------------------------------------------------ reaches
    def create_reach(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/reaches", payload, headers)

    def get_reach(self, reach_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", "/reaches/{}".format(reach_id), None, headers)

    def list_reaches(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/reaches", params, headers)

    # -------------------------------------------------------- monitoring samples
    def create_monitoring_sample(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/monitoring-samples", payload, headers)

    def get_monitoring_sample(self, sample_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", "/monitoring-samples/{}".format(sample_id), None, headers)

    def list_monitoring_samples(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/monitoring-samples", params, headers)

    # ---------------------------------------------------------- tmdl assessments
    def create_tmdl_assessment(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/tmdl-assessments", payload, headers)

    def set_assessment_status(
        self, assessment_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/tmdl-assessments/{}/status".format(assessment_id), payload, headers
        )

    def get_tmdl_assessment(self, assessment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", "/tmdl-assessments/{}".format(assessment_id), None, headers)

    def list_tmdl_assessments(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/tmdl-assessments", params, headers)

    # --------------------------------------------------------- source assessments
    def create_source_assessment(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/source-assessments", payload, headers)

    def get_source_assessment(self, source_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", "/source-assessments/{}".format(source_id), None, headers)

    def list_source_assessments(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/source-assessments", params, headers)

    # ------------------------------------------------------------ allocation runs
    def create_allocation_run(
        self, assessment_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/tmdl-assessments/{}/allocation-runs".format(assessment_id),
            payload,
            headers,
        )

    def rescind_allocation_run(
        self, run_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/allocation-runs/{}/rescind".format(run_id), payload, headers
        )

    def get_allocation_run(self, run_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", "/allocation-runs/{}".format(run_id), None, headers)

    def list_allocation_runs(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/allocation-runs", params, headers)

    # ------------------------------------------------------------------- permits
    def create_permit(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/permits", payload, headers)

    def derive_limits(self, permit_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", "/permits/{}/derive-limits".format(permit_id), {}, headers
        )

    def finalize_limits(self, permit_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", "/permits/{}/finalize-limits".format(permit_id), {}, headers
        )

    def file_annual_report(
        self, permit_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/permits/{}/annual-report".format(permit_id), payload, headers
        )

    def get_permit(self, permit_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", "/permits/{}".format(permit_id), None, headers)

    def list_permits(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/permits", params, headers)

    # ----------------------------------------------------------------- producers
    def create_producer(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/producers", payload, headers)

    def get_producer(self, producer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", "/producers/{}".format(producer_id), None, headers)

    # ---------------------------------------------------------- practice projects
    def create_practice_project(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/practice-projects", payload, headers)

    def certify_practice_project(self, project_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", "/practice-projects/{}/certify".format(project_id), {}, headers
        )

    def get_practice_project(self, project_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", "/practice-projects/{}".format(project_id), None, headers)

    def list_practice_projects(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/practice-projects", params, headers)

    # -------------------------------------------------------- verification events
    def create_verification_event(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/verification-events", payload, headers)

    def get_verification_event(self, event_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", "/verification-events/{}".format(event_id), None, headers)

    def list_verification_events(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/verification-events", params, headers)

    # ------------------------------------------------------------- credit batches
    def list_credit_batch(self, batch_id: str, headers: Dict[str, str]) -> requests.Response:
        """POST /credit-batches/{id}/list — advances an ISSUED batch to LISTED."""
        return self._request(
            "POST", "/credit-batches/{}/list".format(batch_id), {}, headers
        )

    def retire_credit_batch(
        self, batch_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/credit-batches/{}/retire".format(batch_id), payload, headers
        )

    def get_credit_batch(self, batch_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", "/credit-batches/{}".format(batch_id), None, headers)

    def list_credit_batches(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/credit-batches", params, headers)

    # --------------------------------------------------------- credit transactions
    def propose_credit_transaction(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/credit-transactions", payload, headers)

    def approve_credit_transaction(self, txn_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", "/credit-transactions/{}/approve".format(txn_id), {}, headers
        )

    def void_credit_transaction(
        self, txn_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/credit-transactions/{}/void".format(txn_id), payload, headers
        )

    def get_credit_transaction(self, txn_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", "/credit-transactions/{}".format(txn_id), None, headers)

    def list_credit_transactions(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/credit-transactions", params, headers)

    # ------------------------------------------------------------ adaptive reviews
    def create_adaptive_review(
        self, watershed_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/watersheds/{}/adaptive-reviews".format(watershed_id),
            payload,
            headers,
        )

    def finalize_adaptive_review(self, review_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", "/adaptive-reviews/{}/finalize".format(review_id), {}, headers
        )

    def get_adaptive_review(self, review_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", "/adaptive-reviews/{}".format(review_id), None, headers)

    def list_adaptive_reviews(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/adaptive-reviews", params, headers)
