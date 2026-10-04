"""API client: one method per endpoint defined in the PRD (§4, 40 endpoints).

All business endpoints live under /federal-aid. The logical-clock capability
POST /_clock/set_current_utc is the sole platform endpoint mounted OUTSIDE
that prefix (PRD §2.4) and is therefore called without the prefix here.

Base URL resolution: API_BASE_URL (injected by the runner) first, then a
localhost URL built from $PORT, then the framework default.
"""
import os
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/federal-aid"


class ApiClient(GenericApiClient):
    def __init__(self, base_url: Optional[str] = None):
        if base_url is None:
            base_url = os.environ.get("API_BASE_URL")
        if base_url is None:
            port = os.environ.get("PORT")
            base_url = f"http://localhost:{port}" if port else None
        super().__init__(base_url)

    # ------------------------------------------------------------------
    # Platform: logical clock (UNPREFIXED — PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        """POST /_clock/set_current_utc. `payload` may be the clock string
        itself or {"current_utc": ...}."""
        if isinstance(payload, str):
            payload = {"current_utc": payload}
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Funding programs
    # ------------------------------------------------------------------
    def create_funding_program(self, payload, headers):
        return self._request("POST", f"{PREFIX}/funding-programs", payload, headers)

    # ------------------------------------------------------------------
    # Apportionments
    # ------------------------------------------------------------------
    def create_apportionment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/apportionments", payload, headers)

    def get_apportionment(self, apportionment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/apportionments/{apportionment_id}", headers=headers
        )

    def list_apportionments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/apportionments", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # STIPs (StateProgram) and public comments
    # ------------------------------------------------------------------
    def create_stip(self, payload, headers):
        return self._request("POST", f"{PREFIX}/stips", payload, headers)

    def get_stip(self, stip_id, headers):
        return self._request("GET", f"{PREFIX}/stips/{stip_id}", headers=headers)

    def submit_stip(self, stip_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/stips/{stip_id}/submit", payload or {}, headers
        )

    def decide_stip(self, stip_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/stips/{stip_id}/decide", payload, headers
        )

    def open_stip_amendment(self, stip_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/stips/{stip_id}/open-amendment", payload or {}, headers
        )

    def create_stip_comment(self, stip_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/stips/{stip_id}/comments", payload, headers
        )

    def list_stip_comments(self, stip_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/stips/{stip_id}/comments", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------
    def create_project(self, payload, headers):
        return self._request("POST", f"{PREFIX}/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"{PREFIX}/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/projects", headers=headers, params=params)

    def patch_project(self, project_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/projects/{project_id}", payload, headers
        )

    def determine_eligibility(self, project_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/projects/{project_id}/determine-eligibility",
            payload,
            headers,
        )

    def advertise_project(self, project_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/advertise", payload or {}, headers
        )

    def open_bids(self, project_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/open-bids", payload, headers
        )

    def award_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/award", payload, headers
        )

    def list_project_bids(self, project_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/projects/{project_id}/bids", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Clearances
    # ------------------------------------------------------------------
    def create_clearance(self, payload, headers):
        return self._request("POST", f"{PREFIX}/clearances", payload, headers)

    def decide_clearance(self, clearance_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/clearances/{clearance_id}/decide", payload, headers
        )

    def list_project_clearances(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/projects/{project_id}/clearances",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Authorizations
    # ------------------------------------------------------------------
    def create_authorization(self, payload, headers):
        return self._request("POST", f"{PREFIX}/authorizations", payload, headers)

    def get_authorization(self, authorization_id, headers):
        return self._request(
            "GET", f"{PREFIX}/authorizations/{authorization_id}", headers=headers
        )

    def list_authorizations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/authorizations", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Vouchers
    # ------------------------------------------------------------------
    def create_voucher(self, payload, headers):
        return self._request("POST", f"{PREFIX}/vouchers", payload, headers)

    def submit_voucher(self, voucher_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/vouchers/{voucher_id}/submit", payload or {}, headers
        )

    def decide_voucher(self, voucher_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/vouchers/{voucher_id}/decide", payload, headers
        )

    def list_authorization_vouchers(self, authorization_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/authorizations/{authorization_id}/vouchers",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Change orders
    # ------------------------------------------------------------------
    def create_change_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/change-orders", payload, headers)

    def state_concur_change_order(self, change_order_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/change-orders/{change_order_id}/state-concur",
            payload or {},
            headers,
        )

    def federal_decide_change_order(self, change_order_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/change-orders/{change_order_id}/federal-decide",
            payload,
            headers,
        )

    def list_authorization_change_orders(self, authorization_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/authorizations/{authorization_id}/change-orders",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Audits
    # ------------------------------------------------------------------
    def create_audit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/audits", payload, headers)

    def issue_audit_findings(self, audit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/audits/{audit_id}/issue-findings", payload, headers
        )

    def finalize_audit(self, audit_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/audits/{audit_id}/finalize", payload or {}, headers
        )

    def record_repayment(self, audit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/audits/{audit_id}/record-repayment", payload, headers
        )

    def list_project_audits(self, project_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/projects/{project_id}/audits", headers=headers,
            params=params,
        )


api_client = ApiClient()
