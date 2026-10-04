"""HTTP client for the Product Certification Followup API.

One method per endpoint the PRD section 4 routing table declares. Every method
returns the raw ``requests.Response`` so tests can assert on the status code as
well as the body. Request bodies go as ``payload``; query filters and
pagination go as ``params`` (for GET calls the framework forwards the payload
argument as query parameters, so list methods pass their filters there).

All paths live under the API's ``/certification`` prefix.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

__all__ = ["ApiClient", "api_client", "canonical_instant"]

PREFIX = "/certification"


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant so two spellings of one instant match.

    The contract renders instants with three fractional digits, but an equal
    instant may legitimately arrive with none or with trailing zeroes.
    Comparisons therefore run on the canonical form
    ``YYYY-MM-DDTHH:MM:SS.mmmZ`` so that ``2026-09-01T00:00:00Z`` and
    ``2026-09-01T00:00:00.000Z`` compare equal.
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
    """Endpoint methods for every route the PRD declares."""

    # ── Logical clock (PRD 2.5) ────────────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ── Configuration: standards and jurisdictions ─────────────────────────

    def create_standard(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/standards", payload, headers)

    def create_jurisdiction(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/jurisdictions", payload, headers)

    # ── Manufacturers and factories ────────────────────────────────────────

    def create_manufacturer(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/manufacturers", payload, headers)

    def get_manufacturer(
        self, manufacturer_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/manufacturers/{manufacturer_id}", None, headers)

    def suspend_manufacturer(
        self, manufacturer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/manufacturers/{manufacturer_id}/suspend", payload, headers
        )

    def create_factory(
        self, manufacturer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/manufacturers/{manufacturer_id}/factories", payload, headers
        )

    def list_factories(
        self, manufacturer_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/manufacturers/{manufacturer_id}/factories", params, headers
        )

    def get_factory(self, factory_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/factories/{factory_id}", None, headers)

    # ── Certification projects, samples, construction records ──────────────

    def create_project(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/projects", payload, headers)

    def list_projects(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/projects", params, headers)

    def get_project(self, project_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/projects/{project_id}", None, headers)

    def decide_project(
        self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/projects/{project_id}/decide", payload, headers)

    def submit_sample(
        self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/projects/{project_id}/samples", payload, headers)

    def list_samples(
        self, project_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/projects/{project_id}/samples", params, headers)

    def triage_sample(
        self, sample_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/samples/{sample_id}/triage", payload, headers)

    def record_result(
        self, sample_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/samples/{sample_id}/results", payload, headers)

    def create_construction_record(
        self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/construction-records", payload, headers
        )

    def list_construction_records(
        self, project_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/projects/{project_id}/construction-records", params, headers
        )

    # ── Certifications (listing reports) ───────────────────────────────────

    def list_certifications(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/certifications", params, headers)

    def get_certification(
        self, certification_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/certifications/{certification_id}", None, headers)

    def suspend_certification(
        self, certification_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/certifications/{certification_id}/suspend", payload, headers
        )

    def reinstate_certification(
        self, certification_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/certifications/{certification_id}/reinstate", {}, headers
        )

    # ── Substitution requests ──────────────────────────────────────────────

    def create_substitution_request(
        self, certification_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/certifications/{certification_id}/substitution-requests",
            payload,
            headers,
        )

    def list_substitution_requests(
        self, certification_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/certifications/{certification_id}/substitution-requests",
            params,
            headers,
        )

    def decide_substitution_request(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/substitution-requests/{request_id}/decide", payload, headers
        )

    def implement_substitution_request(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/substitution-requests/{request_id}/implement", payload, headers
        )

    # ── Follow-up inspections ──────────────────────────────────────────────

    def schedule_inspection(
        self, factory_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/factories/{factory_id}/inspections", payload, headers
        )

    def list_inspections(
        self, factory_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/factories/{factory_id}/inspections", params, headers
        )

    def complete_inspection(
        self, inspection_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/inspections/{inspection_id}/complete", payload, headers
        )

    def void_inspection(
        self, inspection_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/inspections/{inspection_id}/void", payload, headers)

    # ── Mark licenses and label batches ────────────────────────────────────

    def create_mark_license(
        self, certification_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/certifications/{certification_id}/mark-licenses", payload, headers
        )

    def list_mark_licenses(
        self, certification_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/certifications/{certification_id}/mark-licenses", params, headers
        )

    def get_mark_license(self, license_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/mark-licenses/{license_id}", None, headers)

    def issue_label_batch(
        self, license_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/mark-licenses/{license_id}/label-batches", payload, headers
        )

    def list_label_batches(
        self, license_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/mark-licenses/{license_id}/label-batches", params, headers
        )

    def void_label_batch(
        self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/label-batches/{batch_id}/void", payload, headers)

    # ── Field evaluations ──────────────────────────────────────────────────

    def create_field_evaluation(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/field-evaluations", payload, headers)

    def list_field_evaluations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/field-evaluations", params, headers)

    def get_field_evaluation(
        self, evaluation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/field-evaluations/{evaluation_id}", None, headers)

    def evaluate_field_evaluation(
        self, evaluation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/field-evaluations/{evaluation_id}/evaluate", payload, headers
        )

    def decide_field_evaluation_acceptance(
        self, evaluation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/field-evaluations/{evaluation_id}/decide-acceptance",
            payload,
            headers,
        )

    # ── Withdrawal notices ─────────────────────────────────────────────────

    def create_withdrawal_notice(
        self, certification_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/certifications/{certification_id}/withdrawal-notices",
            payload,
            headers,
        )

    def list_withdrawal_notices(
        self, certification_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/certifications/{certification_id}/withdrawal-notices",
            params,
            headers,
        )

    def publish_withdrawal_notice(
        self, notice_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/withdrawal-notices/{notice_id}/publish", {}, headers
        )


api_client = ApiClient()
