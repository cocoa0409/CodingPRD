"""HTTP client for the CCR Closure & Groundwater Monitoring API.

One method per route declared in the contract's endpoint table. Every method
returns the raw response so a test can assert on the status code as well as on
the body; unwrapping the success envelope is the job of the shared
``validate_success`` / ``get_success_data`` helpers, which already return
``data``, so no call site indexes ``["data"]`` a second time.

Every resource lives under the ``/ccr`` mount. The logical-clock control is the
one exception and sits at the server root.
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
    ``2026-08-01T00:00:00Z`` and ``2026-08-01T00:00:00.000Z`` compare equal.
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

    # ── Logical clock (server root, §2.5) ─────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Disposal units (§3.1) ─────────────────────────────────────────────

    def create_unit(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/ccr/units", payload, headers)

    def get_unit(self, unit_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/ccr/units/{unit_id}", None, headers)

    def list_units(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/ccr/units", params, headers)

    def get_compliance_summary(self, unit_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/ccr/units/{unit_id}/compliance-summary", None, headers)

    def begin_closure(
        self, unit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/ccr/units/{unit_id}/begin-closure", payload, headers)

    def complete_closure(
        self, unit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/ccr/units/{unit_id}/complete-closure", payload, headers)

    def certify_care_complete(
        self, unit_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/ccr/units/{unit_id}/certify-care-complete", payload, headers)

    # ── Qualified professionals (§3.2) ────────────────────────────────────

    def create_professional(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/ccr/professionals", payload, headers)

    def get_professional(self, professional_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/ccr/professionals/{professional_id}", None, headers)

    def list_professionals(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/ccr/professionals", params, headers)

    def set_license_status(
        self, professional_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/ccr/professionals/{professional_id}/license-status", payload, headers
        )

    # ── Structural stability assessments (§3.2) ───────────────────────────

    def create_stability_assessment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/ccr/stability-assessments", payload, headers)

    def get_stability_assessment(self, assessment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/ccr/stability-assessments/{assessment_id}", None, headers)

    def list_stability_assessments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/ccr/stability-assessments", params, headers)

    # ── Monitoring wells (§3.3) ───────────────────────────────────────────

    def create_well(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/ccr/wells", payload, headers)

    def get_well(self, well_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/ccr/wells/{well_id}", None, headers)

    def list_wells(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/ccr/wells", params, headers)

    def decommission_well(
        self, well_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/ccr/wells/{well_id}/decommission", payload, headers)

    # ── Monitoring programs (§3.3) ────────────────────────────────────────

    def get_program(self, program_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/ccr/monitoring-programs/{program_id}", None, headers)

    def list_programs(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/ccr/monitoring-programs", params, headers)

    def patch_program(
        self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"/ccr/monitoring-programs/{program_id}", payload, headers)

    def certify_network(
        self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/ccr/monitoring-programs/{program_id}/certify-network", payload, headers
        )

    def file_corrective_action_assurance(
        self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/ccr/monitoring-programs/{program_id}/corrective-action-assurance",
            payload,
            headers,
        )

    # ── Sampling rounds and laboratory results (§3.4) ─────────────────────

    def create_sampling_event(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/ccr/sampling-events", payload, headers)

    def get_sampling_event(self, event_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/ccr/sampling-events/{event_id}", None, headers)

    def list_sampling_events(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/ccr/sampling-events", params, headers)

    def validate_sampling_event(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/ccr/sampling-events/{event_id}/validate", payload, headers)

    def reopen_sampling_event(
        self, event_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/ccr/sampling-events/{event_id}/reopen", payload, headers)

    def create_analytical_result(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/ccr/analytical-results", payload, headers)

    def get_analytical_result(self, result_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/ccr/analytical-results/{result_id}", None, headers)

    def list_analytical_results(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/ccr/analytical-results", params, headers)

    # ── Statistical evaluations (§3.5) ────────────────────────────────────

    def create_statistical_evaluation(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/ccr/statistical-evaluations", payload, headers)

    def get_statistical_evaluation(self, evaluation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/ccr/statistical-evaluations/{evaluation_id}", None, headers)

    def list_statistical_evaluations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/ccr/statistical-evaluations", params, headers)

    def submit_asd(
        self, evaluation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/ccr/statistical-evaluations/{evaluation_id}/asd-submission", payload, headers
        )

    def decide_asd(
        self, evaluation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/ccr/statistical-evaluations/{evaluation_id}/asd-decision", payload, headers
        )

    # ── Closure plans (§3.6) ──────────────────────────────────────────────

    def create_closure_plan(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/ccr/closure-plans", payload, headers)

    def get_closure_plan(self, plan_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/ccr/closure-plans/{plan_id}", None, headers)

    def list_closure_plans(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/ccr/closure-plans", params, headers)

    def certify_plan_engineering(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/ccr/closure-plans/{plan_id}/engineering-certification", payload, headers
        )

    def certify_plan_cost(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/ccr/closure-plans/{plan_id}/cost-certification", payload, headers)

    def approve_closure_plan(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/ccr/closure-plans/{plan_id}/approve", payload, headers)

    def return_plan_to_draft(
        self, plan_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/ccr/closure-plans/{plan_id}/return-to-draft", payload, headers)

    # ── Closure extension requests (§3.6) ─────────────────────────────────

    def create_extension_request(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/ccr/extension-requests", payload, headers)

    def get_extension_request(self, request_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/ccr/extension-requests/{request_id}", None, headers)

    def list_extension_requests(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/ccr/extension-requests", params, headers)

    def decide_extension_request(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/ccr/extension-requests/{request_id}/decision", payload, headers)

    def rescind_extension_request(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/ccr/extension-requests/{request_id}/rescind", payload, headers)

    # ── Beneficial reuse agreements and shipments (§3.7) ──────────────────

    def create_reuse_agreement(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/ccr/reuse-agreements", payload, headers)

    def get_reuse_agreement(self, agreement_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/ccr/reuse-agreements/{agreement_id}", None, headers)

    def list_reuse_agreements(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/ccr/reuse-agreements", params, headers)

    def qualify_reuse_agreement(
        self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/ccr/reuse-agreements/{agreement_id}/qualify", payload, headers)

    def activate_reuse_agreement(
        self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/ccr/reuse-agreements/{agreement_id}/activate", payload, headers)

    def create_reuse_shipment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/ccr/reuse-shipments", payload, headers)

    def get_reuse_shipment(self, shipment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/ccr/reuse-shipments/{shipment_id}", None, headers)

    def list_reuse_shipments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/ccr/reuse-shipments", params, headers)

    def return_reuse_shipment(
        self, shipment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/ccr/reuse-shipments/{shipment_id}/return", payload, headers)

    # ── Cap inspections (§3.8) ────────────────────────────────────────────

    def create_cap_inspection(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/ccr/cap-inspections", payload, headers)

    def get_cap_inspection(self, inspection_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/ccr/cap-inspections/{inspection_id}", None, headers)

    def list_cap_inspections(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/ccr/cap-inspections", params, headers)

    # ── Public postings (§3.9) ────────────────────────────────────────────

    def create_public_posting(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/ccr/public-postings", payload, headers)

    def get_public_posting(self, posting_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/ccr/public-postings/{posting_id}", None, headers)

    def list_public_postings(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/ccr/public-postings", params, headers)

    def withdraw_public_posting(
        self, posting_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/ccr/public-postings/{posting_id}/withdraw", payload, headers)

    # ── Raw request escape hatch ──────────────────────────────────────────

    def raw(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Send an arbitrary request, for probes that need a route by hand."""
        return self._request(method, path, payload, headers)
