"""HTTP client for the Inter-Plan Claim Routing API.

One method per endpoint declared in the contract. Every method returns the
raw response so a test can assert on the status code as well as the body.
Query filters and pagination are passed as ``params``; request bodies as
``payload``. All paths are mounted under the ``/v1`` prefix.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/v1"


class ApiClient(GenericApiClient):
    """Endpoint methods for every route the contract declares."""

    # ── Logical clock ───────────────────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ── Plans ───────────────────────────────────────────────────────────

    def create_plan(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/plans", payload, headers)

    def get_plan(self, plan_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/plans/{plan_id}", None, headers)

    def list_plans(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/plans", None, headers, params=params)

    def activate_license(self, plan_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/plans/{plan_id}/activate-license", {}, headers)

    def suspend_license(self, plan_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/plans/{plan_id}/suspend-license", {}, headers)

    def reinstate_license(self, plan_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/plans/{plan_id}/reinstate-license", {}, headers)

    def revoke_license(self, plan_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/plans/{plan_id}/revoke-license", {}, headers)

    # ── Members ─────────────────────────────────────────────────────────

    def create_member(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/members", payload, headers)

    def get_member(self, member_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/members/{member_id}", None, headers)

    def list_members(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/members", None, headers, params=params)

    def terminate_member(self, member_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/members/{member_id}/terminate", {}, headers)

    # ── National accounts ───────────────────────────────────────────────

    def create_national_account(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/national-accounts", payload, headers)

    def get_national_account(self, account_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/national-accounts/{account_id}", None, headers)

    def list_national_accounts(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/national-accounts", None, headers, params=params)

    def activate_national_account(self, account_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/national-accounts/{account_id}/activate", {}, headers)

    def suspend_national_account(self, account_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/national-accounts/{account_id}/suspend", {}, headers)

    def reactivate_national_account(self, account_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/national-accounts/{account_id}/reactivate", {}, headers)

    def terminate_national_account(self, account_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/national-accounts/{account_id}/terminate", {}, headers)

    # ── Rate schedules ──────────────────────────────────────────────────

    def create_rate_schedule(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/rate-schedules", payload, headers)

    def get_rate_schedule(self, schedule_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/rate-schedules/{schedule_id}", None, headers)

    def list_rate_schedules(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/rate-schedules", None, headers, params=params)

    # ── Access fee schedules ────────────────────────────────────────────

    def create_access_fee_schedule(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/access-fee-schedules", payload, headers)

    def get_access_fee_schedule(self, schedule_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/access-fee-schedules/{schedule_id}", None, headers)

    def list_access_fee_schedules(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/access-fee-schedules", None, headers, params=params)

    # ── Claims ──────────────────────────────────────────────────────────

    def create_claim(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/claims", payload, headers)

    def get_claim(self, claim_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/claims/{claim_id}", None, headers)

    def list_claims(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/claims", None, headers, params=params)

    def price_claim(self, claim_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/price", {}, headers)

    def route_claim(self, claim_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/route", {}, headers)

    def determine_benefit(self, claim_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/determine-benefit", {}, headers)

    def deny_claim(self, claim_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/deny", {}, headers)

    def pay_claim(self, claim_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/pay", {}, headers)

    # ── Adjustments ─────────────────────────────────────────────────────

    def create_adjustment(self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/adjustments", payload, headers)

    def get_adjustment(self, adjustment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/adjustments/{adjustment_id}", None, headers)

    def list_adjustments(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/adjustments", None, headers, params=params)

    def validate_adjustment(self, adjustment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/adjustments/{adjustment_id}/validate", {}, headers)

    def propagate_adjustment(self, adjustment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/adjustments/{adjustment_id}/propagate", {}, headers)

    def apply_adjustment(self, adjustment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/adjustments/{adjustment_id}/apply", {}, headers)

    def reject_adjustment(self, adjustment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/adjustments/{adjustment_id}/reject", {}, headers)

    # ── Settlement batches ──────────────────────────────────────────────

    def create_settlement_batch(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/settlement-batches", payload, headers)

    def get_settlement_batch(self, batch_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/settlement-batches/{batch_id}", None, headers)

    def list_settlement_batches(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/settlement-batches", None, headers, params=params)

    def finalize_batch(self, batch_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/settlement-batches/{batch_id}/finalize", {}, headers)

    def acknowledge_batch(self, batch_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/settlement-batches/{batch_id}/acknowledge", {}, headers)

    def dispute_batch(self, batch_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/settlement-batches/{batch_id}/dispute", {}, headers)

    def refinalize_batch(self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/settlement-batches/{batch_id}/refinalize", payload, headers)

    def disburse_batch(self, batch_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/settlement-batches/{batch_id}/disburse", {}, headers)

    def reconcile_batch(self, batch_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/settlement-batches/{batch_id}/reconcile", {}, headers)

    # ── Eligibility inquiries ───────────────────────────────────────────

    def create_eligibility_inquiry(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/eligibility-inquiries", payload, headers)

    def get_eligibility_inquiry(self, inquiry_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/eligibility-inquiries/{inquiry_id}", None, headers)

    def list_eligibility_inquiries(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/eligibility-inquiries", None, headers, params=params)

    def answer_eligibility_inquiry(self, inquiry_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/eligibility-inquiries/{inquiry_id}/answer", {}, headers)

    def reject_eligibility_inquiry(self, inquiry_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/eligibility-inquiries/{inquiry_id}/reject", {}, headers)


api_client = ApiClient()
