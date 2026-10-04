"""Endpoint client for the SMR Licensing & Early Site Permitting API.

One method per route the PRD's address map (PRD §4) declares. Every method
returns the raw ``requests.Response`` so a test can assert on the status code
as well as the body. All paths carry the ``/licensing`` prefix. Query filters
and pagination are passed as ``params``; request bodies as ``payload``.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/licensing"


class ApiClient(GenericApiClient):
    """Endpoint methods for every route the contract declares."""

    # ── Logical clock ──────────────────────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ── Design Certification Applications ──────────────────────────────────

    def create_dca(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/dcas", payload, headers)

    def get_dca(self, dca_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/dcas/{dca_id}", None, headers)

    def patch_dca(self, dca_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("PATCH", f"{PREFIX}/dcas/{dca_id}", payload, headers)

    def enter_safety_review(self, dca_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/dcas/{dca_id}/enter-safety-review", {}, headers)

    def advance_phase(self, dca_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/dcas/{dca_id}/advance-phase", {}, headers)

    def certify_dca(self, dca_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/dcas/{dca_id}/certify", {}, headers)

    def withdraw_dca(self, dca_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/dcas/{dca_id}/withdraw", {}, headers)

    # ── Safety Analysis Reports ────────────────────────────────────────────

    def create_sar(self, dca_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/dcas/{dca_id}/sars", payload, headers)

    def get_sar(self, sar_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/sars/{sar_id}", None, headers)

    def list_sars(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/sars", params, headers)

    def review_sar(self, sar_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/sars/{sar_id}/review", {}, headers)

    def advance_sar(self, sar_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/sars/{sar_id}/advance", {}, headers)

    # ── RAIs ───────────────────────────────────────────────────────────────

    def create_rai(self, dca_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/dcas/{dca_id}/rais", payload, headers)

    def get_rai(self, rai_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/rais/{rai_id}", None, headers)

    def list_rais(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/rais", params, headers)

    def respond_rai(self, rai_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/rais/{rai_id}/respond", payload, headers)

    def accept_rai(self, rai_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/rais/{rai_id}/accept", {}, headers)

    def reopen_rai(self, rai_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/rais/{rai_id}/reopen", {}, headers)

    def supersede_rai(self, rai_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/rais/{rai_id}/supersede", {}, headers)

    # ── Test programs and results ──────────────────────────────────────────

    def create_test_program(self, dca_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/dcas/{dca_id}/test-programs", payload, headers)

    def get_test_program(self, program_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/test-programs/{program_id}", None, headers)

    def list_test_programs(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/test-programs", params, headers)

    def list_dca_test_programs(self, dca_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/dcas/{dca_id}/test-programs", None, headers)

    def start_test_program(self, program_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/test-programs/{program_id}/start", {}, headers)

    def record_test_result(self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/test-programs/{program_id}/results", payload, headers)

    def restart_test_program(self, program_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/test-programs/{program_id}/restart", {}, headers)

    def get_test_result(self, result_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/test-results/{result_id}", None, headers)

    def list_test_results(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/test-results", params, headers)

    # ── Vendors, qualifications, component lots ────────────────────────────

    def create_vendor(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/vendors", payload, headers)

    def get_vendor(self, vendor_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/vendors/{vendor_id}", None, headers)

    def create_qualification(self, vendor_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/vendors/{vendor_id}/qualifications", payload, headers)

    def get_qualification(self, qual_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/vendor-qualifications/{qual_id}", None, headers)

    def list_qualifications(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/vendor-qualifications", params, headers)

    def complete_audit(self, vendor_id: str, qual_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/vendors/{vendor_id}/qualifications/{qual_id}/complete-audit", {}, headers
        )

    def upgrade_qualification(self, vendor_id: str, qual_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/vendors/{vendor_id}/qualifications/{qual_id}/upgrade", {}, headers
        )

    def disqualify_qualification(self, vendor_id: str, qual_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/vendors/{vendor_id}/qualifications/{qual_id}/disqualify", {}, headers
        )

    def create_component_lot(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/component-lots", payload, headers)

    def get_component_lot(self, lot_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/component-lots/{lot_id}", None, headers)

    def list_component_lots(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/component-lots", params, headers)

    def deliver_component_lot(self, lot_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/component-lots/{lot_id}/deliver", {}, headers)

    def release_component_lot(self, lot_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/component-lots/{lot_id}/release", {}, headers)

    # ── Site permits and public hearings ───────────────────────────────────

    def create_site_permit(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/site-permits", payload, headers)

    def get_site_permit(self, permit_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/site-permits/{permit_id}", None, headers)

    def list_site_permits(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/site-permits", params, headers)

    def submit_site_permit(self, permit_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/site-permits/{permit_id}/submit", {}, headers)

    def advance_to_hearings(self, permit_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/site-permits/{permit_id}/advance-to-hearings", {}, headers)

    def grant_site_permit(self, permit_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/site-permits/{permit_id}/grant", {}, headers)

    def deny_site_permit(self, permit_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/site-permits/{permit_id}/deny", {}, headers)

    def schedule_hearing(self, permit_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/site-permits/{permit_id}/hearings", payload, headers)

    def get_hearing(self, hearing_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/public-hearings/{hearing_id}", None, headers)

    def list_hearings(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/public-hearings", params, headers)

    def mark_hearing_held(self, hearing_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/public-hearings/{hearing_id}/mark-held", {}, headers)

    def contend_hearing(self, hearing_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/public-hearings/{hearing_id}/contend", {}, headers)

    def cancel_hearing(self, hearing_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/public-hearings/{hearing_id}/cancel", {}, headers)

    def reschedule_hearing(self, hearing_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/public-hearings/{hearing_id}/reschedule", payload, headers)

    # ── Subscriptions and cost-share agreements ────────────────────────────

    def create_subscription(self, dca_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/dcas/{dca_id}/subscriptions", payload, headers)

    def get_subscription(self, sub_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/subscriptions/{sub_id}", None, headers)

    def list_subscriptions(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/subscriptions", params, headers)

    def execute_subscription(self, sub_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/subscriptions/{sub_id}/execute", {}, headers)

    def withdraw_subscription(self, sub_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/subscriptions/{sub_id}/withdraw", payload, headers)

    def create_cost_share_agreement(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/cost-share-agreements", payload, headers)

    def get_cost_share_agreement(self, csa_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/cost-share-agreements/{csa_id}", None, headers)

    def list_cost_share_agreements(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/cost-share-agreements", params, headers)

    def escalate_cost_share(self, csa_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/cost-share-agreements/{csa_id}/escalate", payload, headers)

    # ── Workforce pipelines and operator licenses ──────────────────────────

    def create_workforce_pipeline(self, dca_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/dcas/{dca_id}/workforce-pipelines", payload, headers)

    def get_workforce_pipeline(self, pipeline_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/workforce-pipelines/{pipeline_id}", None, headers)

    def list_workforce_pipelines(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/workforce-pipelines", params, headers)

    def start_training(self, pipeline_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/workforce-pipelines/{pipeline_id}/start-training", {}, headers)

    def advance_pipeline(self, pipeline_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/workforce-pipelines/{pipeline_id}/advance", {}, headers)

    def enroll_operator(self, pipeline_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/workforce-pipelines/{pipeline_id}/licenses", payload, headers)

    def get_operator_license(self, license_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/operator-licenses/{license_id}", None, headers)

    def list_operator_licenses(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/operator-licenses", params, headers)

    def license_operator(self, license_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/operator-licenses/{license_id}/license", {}, headers)

    def activate_operator(self, license_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/operator-licenses/{license_id}/activate", {}, headers)

    def revoke_operator(self, license_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/operator-licenses/{license_id}/revoke", {}, headers)


api_client = ApiClient()
