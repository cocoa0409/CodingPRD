"""HTTP client exposing exactly one method per documented endpoint.

Every method returns the raw `requests.Response` so tests can assert status
codes as well as bodies. List methods accept arbitrary query parameters so a
test can exercise filters and pagination in the same call.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO-8601 UTC instant to exactly three fractional digits.

    Comparing emitted instants literally is brittle only because of fractional
    width, so tests compare canonical forms of both sides instead.
    """
    if value is None:
        return None
    text = str(value)
    if text.endswith("Z"):
        core = text[:-1]
        suffix = "Z"
    elif "+" in text[10:]:
        core, offset = text[:10], text[10:]
        plus = offset.index("+")
        core = text[: 10 + plus]
        suffix = offset[plus:]
    else:
        core, suffix = text, ""
    if "." in core:
        head, frac = core.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = core, "000"
    return f"{head}.{frac}{suffix}"


class ApiClient(GenericApiClient):
    """One method per endpoint of the Emerging Contaminant Compliance API."""

    # ---------------------------------------------------------------- clock --
    def set_clock(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --------------------------------------------------------- contaminants --
    def create_contaminant(self, payload, headers) -> requests.Response:
        return self._request("POST", "/contaminants", payload, headers)

    def get_contaminant(self, contaminant_id, headers) -> requests.Response:
        return self._request("GET", f"/contaminants/{contaminant_id}", None, headers)

    # --------------------------------------------------------- laboratories --
    def create_laboratory(self, payload, headers) -> requests.Response:
        return self._request("POST", "/laboratories", payload, headers)

    def get_laboratory(self, laboratory_id, headers) -> requests.Response:
        return self._request("GET", f"/laboratories/{laboratory_id}", None, headers)

    # ---------------------------------------------------------- entry points --
    def create_entry_point(self, payload, headers) -> requests.Response:
        return self._request("POST", "/entry-points", payload, headers)

    def list_entry_points(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/entry-points", params, headers)

    def get_entry_point(self, entry_point_id, headers) -> requests.Response:
        return self._request("GET", f"/entry-points/{entry_point_id}", None, headers)

    def set_monitoring_status(self, entry_point_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/entry-points/{entry_point_id}/monitoring-status", payload, headers
        )

    def request_monitoring_reduction(self, entry_point_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"/entry-points/{entry_point_id}/monitoring-reduction-requests",
            payload,
            headers,
        )

    def decide_monitoring_reduction(self, entry_point_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"/entry-points/{entry_point_id}/monitoring-reduction-decisions",
            payload,
            headers,
        )

    # -------------------------------------------------------------- samples --
    def create_sample(self, payload, headers) -> requests.Response:
        return self._request("POST", "/samples", payload, headers)

    def list_samples(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/samples", params, headers)

    def get_sample(self, sample_id, headers) -> requests.Response:
        return self._request("GET", f"/samples/{sample_id}", None, headers)

    def ship_sample(self, sample_id, payload, headers) -> requests.Response:
        return self._request("POST", f"/samples/{sample_id}/ship", payload, headers)

    def receive_sample(self, sample_id, payload, headers) -> requests.Response:
        return self._request("POST", f"/samples/{sample_id}/receive", payload, headers)

    def invalidate_sample(self, sample_id, payload, headers) -> requests.Response:
        return self._request("POST", f"/samples/{sample_id}/invalidate", payload, headers)

    def reinstate_sample(self, sample_id, payload, headers) -> requests.Response:
        return self._request("POST", f"/samples/{sample_id}/reinstate", payload, headers)

    # ---------------------------------------------------------- lab results --
    def create_lab_result(self, payload, headers) -> requests.Response:
        return self._request("POST", "/lab-results", payload, headers)

    def list_lab_results(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/lab-results", params, headers)

    def get_lab_result(self, lab_result_id, headers) -> requests.Response:
        return self._request("GET", f"/lab-results/{lab_result_id}", None, headers)

    def review_lab_result(self, lab_result_id, payload, headers) -> requests.Response:
        return self._request("POST", f"/lab-results/{lab_result_id}/review", payload, headers)

    # ------------------------------------------------------- determinations --
    def create_determination(self, payload, headers) -> requests.Response:
        return self._request("POST", "/compliance-determinations", payload, headers)

    def list_determinations(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/compliance-determinations", params, headers)

    def get_determination(self, determination_id, headers) -> requests.Response:
        return self._request(
            "GET", f"/compliance-determinations/{determination_id}", None, headers
        )

    def issue_determination(self, determination_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/compliance-determinations/{determination_id}/issue", payload, headers
        )

    def rescind_determination(self, determination_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/compliance-determinations/{determination_id}/rescind", payload, headers
        )

    # -------------------------------------------------------- notifications --
    def list_notifications(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/public-notifications", params, headers)

    def get_notification(self, notification_id, headers) -> requests.Response:
        return self._request("GET", f"/public-notifications/{notification_id}", None, headers)

    def submit_notification(self, notification_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/public-notifications/{notification_id}/submit", payload, headers
        )

    def review_notification(self, notification_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/public-notifications/{notification_id}/review", payload, headers
        )

    def certify_notification_distribution(self, notification_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"/public-notifications/{notification_id}/certify-distribution",
            payload,
            headers,
        )

    # -------------------------------------------------- treatment evaluations --
    def create_treatment_evaluation(self, payload, headers) -> requests.Response:
        return self._request("POST", "/treatment-evaluations", payload, headers)

    def list_treatment_evaluations(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/treatment-evaluations", params, headers)

    def get_treatment_evaluation(self, evaluation_id, headers) -> requests.Response:
        return self._request("GET", f"/treatment-evaluations/{evaluation_id}", None, headers)

    def decide_treatment_evaluation(self, evaluation_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/treatment-evaluations/{evaluation_id}/decision", payload, headers
        )

    # ---------------------------------------------------------- pilot tests --
    def create_pilot_test(self, payload, headers) -> requests.Response:
        return self._request("POST", "/pilot-tests", payload, headers)

    def list_pilot_tests(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/pilot-tests", params, headers)

    def get_pilot_test(self, pilot_id, headers) -> requests.Response:
        return self._request("GET", f"/pilot-tests/{pilot_id}", None, headers)

    def start_pilot_test(self, pilot_id, payload, headers) -> requests.Response:
        return self._request("POST", f"/pilot-tests/{pilot_id}/start", payload, headers)

    def complete_pilot_test(self, pilot_id, payload, headers) -> requests.Response:
        return self._request("POST", f"/pilot-tests/{pilot_id}/complete", payload, headers)

    # --------------------------------------------------- residuals manifests --
    def create_residuals_manifest(self, payload, headers) -> requests.Response:
        return self._request("POST", "/residuals-manifests", payload, headers)

    def list_residuals_manifests(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/residuals-manifests", params, headers)

    def get_residuals_manifest(self, manifest_id, headers) -> requests.Response:
        return self._request("GET", f"/residuals-manifests/{manifest_id}", None, headers)

    def classify_residuals_manifest(self, manifest_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/residuals-manifests/{manifest_id}/classify", payload, headers
        )

    def ship_residuals_manifest(self, manifest_id, payload, headers) -> requests.Response:
        return self._request("POST", f"/residuals-manifests/{manifest_id}/ship", payload, headers)

    def void_residuals_manifest(self, manifest_id, payload, headers) -> requests.Response:
        return self._request("POST", f"/residuals-manifests/{manifest_id}/void", payload, headers)

    # ------------------------------------------------------ capital projects --
    def list_capital_projects(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/capital-projects", params, headers)

    def get_capital_project(self, project_id, headers) -> requests.Response:
        return self._request("GET", f"/capital-projects/{project_id}", None, headers)

    def patch_capital_project(self, project_id, payload, headers) -> requests.Response:
        return self._request("PATCH", f"/capital-projects/{project_id}", payload, headers)

    def advance_construction(self, project_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/capital-projects/{project_id}/construction-status", payload, headers
        )

    def create_funding_application(self, project_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/capital-projects/{project_id}/funding-applications", payload, headers
        )

    # -------------------------------------------------- funding applications --
    def list_funding_applications(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/funding-applications", params, headers)

    def get_funding_application(self, application_id, headers) -> requests.Response:
        return self._request("GET", f"/funding-applications/{application_id}", None, headers)

    def decide_funding_application(self, application_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/funding-applications/{application_id}/decision", payload, headers
        )

    def withdraw_funding_application(self, application_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/funding-applications/{application_id}/withdraw", payload, headers
        )

    # ------------------------------------------------- cost recovery claims --
    def create_cost_recovery_claim(self, payload, headers) -> requests.Response:
        return self._request("POST", "/cost-recovery-claims", payload, headers)

    def list_cost_recovery_claims(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/cost-recovery-claims", params, headers)

    def get_cost_recovery_claim(self, claim_id, headers) -> requests.Response:
        return self._request("GET", f"/cost-recovery-claims/{claim_id}", None, headers)

    def file_cost_recovery_claim(self, claim_id, payload, headers) -> requests.Response:
        return self._request("POST", f"/cost-recovery-claims/{claim_id}/file", payload, headers)

    def resolve_cost_recovery_claim(self, claim_id, payload, headers) -> requests.Response:
        return self._request("POST", f"/cost-recovery-claims/{claim_id}/resolve", payload, headers)
