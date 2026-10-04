"""HTTP client for the Protective Coating Specification & Applicator Approval API.

One method per route the PRD declares (§4). Every method returns the raw
``requests.Response`` so tests can assert on status code as well as body.
For GET routes the third positional argument of ``_request`` is forwarded as
query parameters, so list methods pass their filters there.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant so two spellings of one moment match.

    ``2026-09-01T00:00:00Z`` and ``2026-09-01T00:00:00.000Z`` denote the same
    instant; comparisons reduce both sides to a three-fractional-digit form.
    """
    if value is None or not isinstance(value, str):
        return value
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = text, "000"
    return f"{head}.{frac}Z"


class ApiClient(GenericApiClient):
    """Endpoint methods for every route the PRD declares."""

    # ── Logical clock ──────────────────────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/coating/_clock/set_current_utc", payload, headers)

    # ── Coating systems ────────────────────────────────────────────────────

    def create_coating_system(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/coating/coating-systems", payload, headers)

    def list_coating_systems(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/coating/coating-systems", params, headers)

    def get_coating_system(self, system_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/coating/coating-systems/{system_id}", None, headers)

    def revise_coating_system(self, system_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/coating/coating-systems/{system_id}/revise", {}, headers)

    def obsolete_coating_system(self, system_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/coating/coating-systems/{system_id}/obsolete", {}, headers)

    # ── VOC regulations ────────────────────────────────────────────────────

    def create_voc_regulation(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/coating/voc-regulations", payload, headers)

    def list_voc_regulations(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/coating/voc-regulations", params, headers)

    def get_voc_regulation(self, regulation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/coating/voc-regulations/{regulation_id}", None, headers)

    def supersede_voc_regulation(
        self, regulation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/coating/voc-regulations/{regulation_id}/supersede", payload, headers)

    # ── Applicators ────────────────────────────────────────────────────────

    def create_applicator(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/coating/applicators", payload, headers)

    def list_applicators(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/coating/applicators", params, headers)

    def get_applicator(self, applicator_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/coating/applicators/{applicator_id}", None, headers)

    # ── Qualification programs ─────────────────────────────────────────────

    def create_qualification_program(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/coating/qualification-programs", payload, headers)

    def list_qualification_programs(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/coating/qualification-programs", params, headers)

    def get_qualification_program(self, program_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/coating/qualification-programs/{program_id}", None, headers)

    def list_program_qualifications(
        self, program_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/coating/qualification-programs/{program_id}/qualifications", params, headers)

    # ── Applicator qualifications ──────────────────────────────────────────

    def enroll_qualification(
        self, applicator_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/coating/applicators/{applicator_id}/qualifications", payload, headers)

    def list_qualifications(
        self, applicator_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/coating/applicators/{applicator_id}/qualifications", params, headers)

    def get_qualification(
        self, applicator_id: str, qualification_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/coating/applicators/{applicator_id}/qualifications/{qualification_id}", None, headers
        )

    def certify_qualification(
        self, applicator_id: str, qualification_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/coating/applicators/{applicator_id}/qualifications/{qualification_id}/certify",
            payload, headers,
        )

    def suspend_qualification(
        self, applicator_id: str, qualification_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/coating/applicators/{applicator_id}/qualifications/{qualification_id}/suspend",
            {}, headers,
        )

    def reinstate_qualification(
        self, applicator_id: str, qualification_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/coating/applicators/{applicator_id}/qualifications/{qualification_id}/reinstate",
            {}, headers,
        )

    def revoke_qualification(
        self, applicator_id: str, qualification_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/coating/applicators/{applicator_id}/qualifications/{qualification_id}/revoke",
            {}, headers,
        )

    # ── Projects ───────────────────────────────────────────────────────────

    def create_project(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/coating/projects", payload, headers)

    def list_projects(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/coating/projects", params, headers)

    def get_project(self, project_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/coating/projects/{project_id}", None, headers)

    def complete_project(self, project_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/coating/projects/{project_id}/complete", {}, headers)

    def cancel_project(self, project_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/coating/projects/{project_id}/cancel", {}, headers)

    # ── Project specifications ─────────────────────────────────────────────

    def create_specification(
        self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/coating/projects/{project_id}/specifications", payload, headers)

    def list_specifications(
        self, project_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/coating/projects/{project_id}/specifications", params, headers)

    def get_specification(
        self, project_id: str, spec_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/coating/projects/{project_id}/specifications/{spec_id}", None, headers)

    def issue_specification(
        self, project_id: str, spec_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/coating/projects/{project_id}/specifications/{spec_id}/issue", payload, headers
        )

    def withdraw_specification(
        self, project_id: str, spec_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/coating/projects/{project_id}/specifications/{spec_id}/withdraw", {}, headers
        )

    def list_all_specifications(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/coating/specifications", params, headers)

    def get_specification_flat(self, spec_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/coating/specifications/{spec_id}", None, headers)

    # ── Substitution requests ──────────────────────────────────────────────

    def create_substitution_request(
        self, spec_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/coating/specifications/{spec_id}/substitution-requests", payload, headers)

    def list_substitution_requests(
        self, spec_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/coating/specifications/{spec_id}/substitution-requests", params, headers)

    def get_substitution_request(
        self, spec_id: str, request_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/coating/specifications/{spec_id}/substitution-requests/{request_id}", None, headers
        )

    def start_substitution_review(
        self, spec_id: str, request_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/coating/specifications/{spec_id}/substitution-requests/{request_id}/start-review",
            {}, headers,
        )

    def request_substitution_info(
        self, spec_id: str, request_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/coating/specifications/{spec_id}/substitution-requests/{request_id}/request-info",
            {}, headers,
        )

    def resubmit_substitution_request(
        self, spec_id: str, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/coating/specifications/{spec_id}/substitution-requests/{request_id}/resubmit",
            payload, headers,
        )

    def decide_substitution_request(
        self, spec_id: str, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/coating/specifications/{spec_id}/substitution-requests/{request_id}/decide",
            payload, headers,
        )

    def list_all_substitution_requests(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/coating/substitution-requests", params, headers)

    def get_substitution_request_flat(self, request_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/coating/substitution-requests/{request_id}", None, headers)

    # ── Work orders ────────────────────────────────────────────────────────

    def create_work_order(
        self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/coating/projects/{project_id}/work-orders", payload, headers)

    def list_work_orders(
        self, project_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/coating/projects/{project_id}/work-orders", params, headers)

    def get_work_order(
        self, project_id: str, work_order_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/coating/projects/{project_id}/work-orders/{work_order_id}", None, headers)

    def begin_prep_inspection(
        self, project_id: str, work_order_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/coating/projects/{project_id}/work-orders/{work_order_id}/begin-prep-inspection",
            {}, headers,
        )

    def complete_work_order(
        self, project_id: str, work_order_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/coating/projects/{project_id}/work-orders/{work_order_id}/complete", {}, headers
        )

    def cancel_work_order(
        self, project_id: str, work_order_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/coating/projects/{project_id}/work-orders/{work_order_id}/cancel", {}, headers
        )

    def list_all_work_orders(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/coating/work-orders", params, headers)

    def get_work_order_flat(self, work_order_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/coating/work-orders/{work_order_id}", None, headers)

    # ── Surface preparation inspections ────────────────────────────────────

    def create_prep_inspection(
        self, work_order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/coating/work-orders/{work_order_id}/prep-inspections", payload, headers)

    def list_prep_inspections(
        self, work_order_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/coating/work-orders/{work_order_id}/prep-inspections", params, headers)

    def get_prep_inspection(self, inspection_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/coating/prep-inspections/{inspection_id}", None, headers)

    # ── Coating applications ───────────────────────────────────────────────

    def create_application(
        self, work_order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/coating/work-orders/{work_order_id}/applications", payload, headers)

    def list_applications(
        self, work_order_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/coating/work-orders/{work_order_id}/applications", params, headers)

    def get_application(self, application_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/coating/applications/{application_id}", None, headers)

    def mark_application_cured(
        self, work_order_id: str, application_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/coating/work-orders/{work_order_id}/applications/{application_id}/mark-cured",
            {}, headers,
        )

    def waive_application_testing(
        self, work_order_id: str, application_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/coating/work-orders/{work_order_id}/applications/{application_id}/waive-testing",
            {}, headers,
        )

    # ── Inspection reports ─────────────────────────────────────────────────

    def create_inspection_report(
        self, work_order_id: str, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/coating/work-orders/{work_order_id}/applications/{application_id}/inspection-reports",
            payload, headers,
        )

    def list_inspection_reports(
        self, work_order_id: str, application_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/coating/work-orders/{work_order_id}/applications/{application_id}/inspection-reports",
            params, headers,
        )

    def get_inspection_report(self, report_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/coating/inspection-reports/{report_id}", None, headers)

    def list_all_inspection_reports(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/coating/inspection-reports", params, headers)

    # ── Warranties ─────────────────────────────────────────────────────────

    def create_warranty(
        self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/coating/projects/{project_id}/warranties", payload, headers)

    def list_warranties(
        self, project_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/coating/projects/{project_id}/warranties", params, headers)

    def get_warranty(
        self, project_id: str, warranty_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/coating/projects/{project_id}/warranties/{warranty_id}", None, headers)

    def claim_warranty(
        self, project_id: str, warranty_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/coating/projects/{project_id}/warranties/{warranty_id}/claim", payload, headers
        )

    def void_warranty(
        self, project_id: str, warranty_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/coating/projects/{project_id}/warranties/{warranty_id}/void", payload, headers
        )

    def list_all_warranties(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/coating/warranties", params, headers)

    def get_warranty_flat(self, warranty_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/coating/warranties/{warranty_id}", None, headers)

    # ── Failure investigations ─────────────────────────────────────────────

    def list_investigations(
        self, warranty_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/coating/warranties/{warranty_id}/investigations", params, headers)

    def get_investigation(
        self, warranty_id: str, investigation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/coating/warranties/{warranty_id}/investigations/{investigation_id}", None, headers
        )

    def begin_investigation_evidence(
        self, warranty_id: str, investigation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/coating/warranties/{warranty_id}/investigations/{investigation_id}/begin-evidence",
            {}, headers,
        )

    def adjudicate_investigation(
        self, warranty_id: str, investigation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/coating/warranties/{warranty_id}/investigations/{investigation_id}/adjudicate",
            payload, headers,
        )

    # ── Raw escape hatch ───────────────────────────────────────────────────

    def raw(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Send an arbitrary request, for probes that need a route by hand."""
        return self._request(method, path, payload, headers)


api_client = ApiClient()
