"""API client: one method per endpoint defined in the PRD.

All endpoints are mounted under the ``/glass`` prefix. The base URL comes from
the ``API_BASE_URL`` environment variable via ``GenericApiClient``; the runner
launches a fresh server on a dynamically allocated port for every test, so no
port or host is ever hardcoded here. Every method returns the raw
``requests.Response`` so tests can assert on status codes as well as bodies.
``headers`` may be omitted to model an unauthenticated request.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

Headers = Optional[Dict[str, str]]


class ApiClient(GenericApiClient):
    """Endpoint methods for every route the PRD declares."""

    # ── Device makers ─────────────────────────────────────────────────────

    def create_device_maker(self, payload: Dict[str, Any], headers: Headers = None) -> requests.Response:
        return self._request("POST", "/glass/device-makers", payload, headers)

    def get_device_maker(self, device_maker_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/glass/device-makers/{device_maker_id}", None, headers)

    def list_device_makers(self, headers: Headers = None, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/glass/device-makers", None, headers, params)

    def ip_review_device_maker(self, device_maker_id: str, payload: Dict[str, Any], headers: Headers = None) -> requests.Response:
        return self._request("POST", f"/glass/device-makers/{device_maker_id}/ip-review", payload, headers)

    # ── Programs ──────────────────────────────────────────────────────────

    def create_program(self, payload: Dict[str, Any], headers: Headers = None) -> requests.Response:
        return self._request("POST", "/glass/programs", payload, headers)

    def get_program(self, program_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/glass/programs/{program_id}", None, headers)

    def list_programs(self, headers: Headers = None, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/glass/programs", None, headers, params)

    def execute_nda(self, program_id: str, payload: Dict[str, Any], headers: Headers = None) -> requests.Response:
        return self._request("POST", f"/glass/programs/{program_id}/execute-nda", payload, headers)

    def begin_qualification(self, program_id: str, payload: Dict[str, Any], headers: Headers = None) -> requests.Response:
        return self._request("POST", f"/glass/programs/{program_id}/begin-qualification", payload, headers)

    def rework_program(self, program_id: str, headers: Headers = None, payload: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", f"/glass/programs/{program_id}/rework", payload, headers)

    def freeze_design(self, program_id: str, headers: Headers = None, payload: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", f"/glass/programs/{program_id}/freeze-design", payload, headers)

    def close_program(self, program_id: str, headers: Headers = None, payload: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", f"/glass/programs/{program_id}/close", payload, headers)

    def terminate_program(self, program_id: str, headers: Headers = None, payload: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", f"/glass/programs/{program_id}/terminate", payload, headers)

    # ── Compositions ──────────────────────────────────────────────────────

    def create_composition(self, payload: Dict[str, Any], headers: Headers = None) -> requests.Response:
        return self._request("POST", "/glass/compositions", payload, headers)

    def get_composition(self, composition_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/glass/compositions/{composition_id}", None, headers)

    def list_compositions(self, headers: Headers = None, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/glass/compositions", None, headers, params)

    def lock_composition(self, composition_id: str, headers: Headers = None, payload: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", f"/glass/compositions/{composition_id}/lock", payload, headers)

    def retire_composition(self, composition_id: str, headers: Headers = None, payload: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", f"/glass/compositions/{composition_id}/retire", payload, headers)

    # ── Qualification cycles ──────────────────────────────────────────────

    def create_qual_cycle(self, payload: Dict[str, Any], headers: Headers = None) -> requests.Response:
        return self._request("POST", "/glass/qual-cycles", payload, headers)

    def get_qual_cycle(self, qual_cycle_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/glass/qual-cycles/{qual_cycle_id}", None, headers)

    def list_qual_cycles(self, headers: Headers = None, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/glass/qual-cycles", None, headers, params)

    def begin_testing(self, qual_cycle_id: str, headers: Headers = None, payload: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", f"/glass/qual-cycles/{qual_cycle_id}/begin-testing", payload, headers)

    def record_result(self, qual_cycle_id: str, payload: Dict[str, Any], headers: Headers = None) -> requests.Response:
        return self._request("POST", f"/glass/qual-cycles/{qual_cycle_id}/record-result", payload, headers)

    def resubmit_qual_cycle(self, qual_cycle_id: str, headers: Headers = None, payload: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", f"/glass/qual-cycles/{qual_cycle_id}/resubmit", payload, headers)

    # ── Tanks ─────────────────────────────────────────────────────────────

    def create_tank(self, payload: Dict[str, Any], headers: Headers = None) -> requests.Response:
        return self._request("POST", "/glass/tanks", payload, headers)

    def get_tank(self, tank_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/glass/tanks/{tank_id}", None, headers)

    def list_tanks(self, headers: Headers = None, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/glass/tanks", None, headers, params)

    def commission_tank(self, tank_id: str, headers: Headers = None, payload: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", f"/glass/tanks/{tank_id}/commission", payload, headers)

    # ── Campaigns ─────────────────────────────────────────────────────────

    def create_campaign(self, payload: Dict[str, Any], headers: Headers = None) -> requests.Response:
        return self._request("POST", "/glass/campaigns", payload, headers)

    def get_campaign(self, campaign_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/glass/campaigns/{campaign_id}", None, headers)

    def list_campaigns(self, headers: Headers = None, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/glass/campaigns", None, headers, params)

    def start_campaign(self, campaign_id: str, headers: Headers = None, payload: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", f"/glass/campaigns/{campaign_id}/start", payload, headers)

    def abort_campaign(self, campaign_id: str, headers: Headers = None, payload: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", f"/glass/campaigns/{campaign_id}/abort", payload, headers)

    def complete_campaign(self, campaign_id: str, headers: Headers = None, payload: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", f"/glass/campaigns/{campaign_id}/complete", payload, headers)

    def record_production(self, campaign_id: str, payload: Dict[str, Any], headers: Headers = None) -> requests.Response:
        return self._request("POST", f"/glass/campaigns/{campaign_id}/record-production", payload, headers)

    def auto_allocate(self, campaign_id: str, headers: Headers = None, payload: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", f"/glass/campaigns/{campaign_id}/auto-allocate", payload, headers)

    # ── Commitments ───────────────────────────────────────────────────────

    def create_commitment(self, payload: Dict[str, Any], headers: Headers = None) -> requests.Response:
        return self._request("POST", "/glass/commitments", payload, headers)

    def get_commitment(self, commitment_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/glass/commitments/{commitment_id}", None, headers)

    def list_commitments(self, headers: Headers = None, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/glass/commitments", None, headers, params)

    def sign_commitment(self, commitment_id: str, headers: Headers = None, payload: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", f"/glass/commitments/{commitment_id}/sign", payload, headers)

    def countersign_commitment(self, commitment_id: str, headers: Headers = None, payload: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", f"/glass/commitments/{commitment_id}/countersign", payload, headers)

    def confirm_prepayment(self, commitment_id: str, headers: Headers = None, payload: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", f"/glass/commitments/{commitment_id}/confirm-prepayment", payload, headers)

    def apply_prepayment(self, commitment_id: str, payload: Dict[str, Any], headers: Headers = None) -> requests.Response:
        return self._request("POST", f"/glass/commitments/{commitment_id}/apply-prepayment", payload, headers)

    def release_commitment(self, commitment_id: str, headers: Headers = None, payload: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", f"/glass/commitments/{commitment_id}/release", payload, headers)

    # ── Allocations ───────────────────────────────────────────────────────

    def create_allocation(self, payload: Dict[str, Any], headers: Headers = None) -> requests.Response:
        return self._request("POST", "/glass/allocations", payload, headers)

    def get_allocation(self, allocation_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/glass/allocations/{allocation_id}", None, headers)

    def list_allocations(self, headers: Headers = None, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/glass/allocations", None, headers, params)

    def release_allocation(self, allocation_id: str, headers: Headers = None, payload: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", f"/glass/allocations/{allocation_id}/release", payload, headers)

    def fulfill_allocation(self, allocation_id: str, headers: Headers = None, payload: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", f"/glass/allocations/{allocation_id}/fulfill", payload, headers)

    # ── Licenses ──────────────────────────────────────────────────────────

    def create_license(self, payload: Dict[str, Any], headers: Headers = None) -> requests.Response:
        return self._request("POST", "/glass/licenses", payload, headers)

    def get_license(self, license_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/glass/licenses/{license_id}", None, headers)

    def list_licenses(self, headers: Headers = None, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/glass/licenses", None, headers, params)

    def activate_license(self, license_id: str, headers: Headers = None, payload: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", f"/glass/licenses/{license_id}/activate", payload, headers)

    def suspend_license(self, license_id: str, headers: Headers = None, payload: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", f"/glass/licenses/{license_id}/suspend", payload, headers)

    def reinstate_license(self, license_id: str, headers: Headers = None, payload: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", f"/glass/licenses/{license_id}/reinstate", payload, headers)

    def terminate_license(self, license_id: str, headers: Headers = None, payload: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", f"/glass/licenses/{license_id}/terminate", payload, headers)

    def submit_marketing(self, license_id: str, payload: Dict[str, Any], headers: Headers = None) -> requests.Response:
        return self._request("POST", f"/glass/licenses/{license_id}/submit-marketing", payload, headers)

    def review_marketing(self, license_id: str, payload: Dict[str, Any], headers: Headers = None) -> requests.Response:
        return self._request("POST", f"/glass/licenses/{license_id}/review-marketing", payload, headers)

    # ── Usage reports ─────────────────────────────────────────────────────

    def create_usage_report(self, payload: Dict[str, Any], headers: Headers = None) -> requests.Response:
        return self._request("POST", "/glass/usage-reports", payload, headers)

    def get_usage_report(self, usage_report_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/glass/usage-reports/{usage_report_id}", None, headers)

    def list_usage_reports(self, headers: Headers = None, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/glass/usage-reports", None, headers, params)

    def accept_usage_report(self, usage_report_id: str, headers: Headers = None, payload: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", f"/glass/usage-reports/{usage_report_id}/accept", payload, headers)

    def dispute_usage_report(self, usage_report_id: str, headers: Headers = None, payload: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", f"/glass/usage-reports/{usage_report_id}/dispute", payload, headers)

    # ── Logical clock and operations checkpoint ───────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Headers = None) -> requests.Response:
        return self._request("POST", "/glass/_clock/set_current_utc", payload, headers)

    def ops_checkpoint(self, headers: Headers = None, payload: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", "/glass/ops/checkpoint", payload, headers)


api_client = ApiClient()
