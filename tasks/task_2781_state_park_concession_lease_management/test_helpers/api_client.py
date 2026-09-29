"""API client: one method per endpoint defined in the PRD (§4).

Every endpoint is served under the ``/api/v1`` prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

API_PREFIX = "/api/v1"


class ApiClient(GenericApiClient):
    # ─── Logical clock (PRD §2.4) ──────────────────────────────────────────
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc}, headers,
        )

    def set_clock_raw(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers)

    # ─── Parks ─────────────────────────────────────────────────────────────
    def create_park(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/parks", payload, headers)

    def list_parks(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/parks", headers=headers, params=params)

    def get_park(self, park_id, headers):
        return self._request("GET", f"{API_PREFIX}/parks/{park_id}", headers=headers)

    # ─── Concession opportunities ──────────────────────────────────────────
    def create_opportunity(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/concession-opportunities", payload, headers)

    def record_market_analysis(self, opportunity_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/concession-opportunities/{opportunity_id}/market-analysis",
            payload, headers,
        )

    def approve_solicitation(self, opportunity_id, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/concession-opportunities/{opportunity_id}/approve-solicitation",
            payload if payload is not None else {}, headers,
        )

    def list_opportunities(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/concession-opportunities", headers=headers, params=params)

    def get_opportunity(self, opportunity_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/concession-opportunities/{opportunity_id}", headers=headers)

    # ─── Prospectuses ──────────────────────────────────────────────────────
    def create_prospectus(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/prospectuses", payload, headers)

    def issue_prospectus(self, prospectus_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/prospectuses/{prospectus_id}/issue",
            payload if payload is not None else {}, headers)

    def close_prospectus(self, prospectus_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/prospectuses/{prospectus_id}/close",
            payload if payload is not None else {}, headers)

    def award_prospectus(self, prospectus_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/prospectuses/{prospectus_id}/award", payload, headers)

    def list_prospectuses(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/prospectuses", headers=headers, params=params)

    def get_prospectus(self, prospectus_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/prospectuses/{prospectus_id}", headers=headers)

    # ─── Offerors ──────────────────────────────────────────────────────────
    def create_offeror(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/offerors", payload, headers)

    def debar_offeror(self, offeror_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/offerors/{offeror_id}/debar",
            payload if payload is not None else {}, headers)

    def list_offerors(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/offerors", headers=headers, params=params)

    def get_offeror(self, offeror_id, headers):
        return self._request("GET", f"{API_PREFIX}/offerors/{offeror_id}", headers=headers)

    # ─── Proposals ─────────────────────────────────────────────────────────
    def create_proposal(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/proposals", payload, headers)

    def begin_review(self, proposal_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/proposals/{proposal_id}/begin-review",
            payload if payload is not None else {}, headers)

    def file_evaluation(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/proposals/{proposal_id}/evaluations", payload, headers)

    def request_revision(self, proposal_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/proposals/{proposal_id}/request-revision",
            payload if payload is not None else {}, headers)

    def resubmit_proposal(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/proposals/{proposal_id}/resubmit", payload, headers)

    def withdraw_proposal(self, proposal_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/proposals/{proposal_id}/withdraw",
            payload if payload is not None else {}, headers)

    def list_proposals(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/proposals", headers=headers, params=params)

    def get_proposal(self, proposal_id, headers):
        return self._request("GET", f"{API_PREFIX}/proposals/{proposal_id}", headers=headers)

    # ─── Panel score sheets ────────────────────────────────────────────────
    def list_proposal_evaluations(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/proposal-evaluations", headers=headers, params=params)

    def get_proposal_evaluation(self, evaluation_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/proposal-evaluations/{evaluation_id}", headers=headers)

    # ─── Leases ────────────────────────────────────────────────────────────
    def execute_lease(self, lease_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/leases/{lease_id}/execute", payload, headers)

    def record_insurance_certificate(self, lease_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/leases/{lease_id}/insurance-certificate", payload, headers)

    def enter_holdover(self, lease_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/leases/{lease_id}/enter-holdover",
            payload if payload is not None else {}, headers)

    def expire_lease(self, lease_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/leases/{lease_id}/expire",
            payload if payload is not None else {}, headers)

    def close_out_lease(self, lease_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/leases/{lease_id}/close-out",
            payload if payload is not None else {}, headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/leases", headers=headers, params=params)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"{API_PREFIX}/leases/{lease_id}", headers=headers)

    # ─── Performance bonds ─────────────────────────────────────────────────
    def post_bond(self, bond_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/performance-bonds/{bond_id}/post", payload, headers)

    def reinstate_bond(self, bond_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/performance-bonds/{bond_id}/reinstate", payload, headers)

    def list_bonds(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/performance-bonds", headers=headers, params=params)

    def get_bond(self, bond_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/performance-bonds/{bond_id}", headers=headers)

    # ─── Capital improvements ──────────────────────────────────────────────
    def create_improvement(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/capital-improvements", payload, headers)

    def approve_improvement(self, improvement_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/capital-improvements/{improvement_id}/approve",
            payload, headers)

    def return_improvement(self, improvement_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/capital-improvements/{improvement_id}/return",
            payload, headers)

    def resubmit_improvement(self, improvement_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/capital-improvements/{improvement_id}/resubmit",
            payload, headers)

    def place_improvement_in_service(self, improvement_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/capital-improvements/{improvement_id}/place-in-service",
            payload, headers)

    def list_improvements(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/capital-improvements", headers=headers, params=params)

    def get_improvement(self, improvement_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/capital-improvements/{improvement_id}", headers=headers)

    # ─── Operating plans ───────────────────────────────────────────────────
    def create_operating_plan(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/operating-plans", payload, headers)

    def approve_operating_plan(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/operating-plans/{plan_id}/approve",
            payload if payload is not None else {}, headers)

    def return_operating_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/operating-plans/{plan_id}/return", payload, headers)

    def resubmit_operating_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/operating-plans/{plan_id}/resubmit", payload, headers)

    def list_operating_plans(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/operating-plans", headers=headers, params=params)

    def get_operating_plan(self, plan_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/operating-plans/{plan_id}", headers=headers)

    # ─── Gross receipts reports ────────────────────────────────────────────
    def create_report(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/gross-receipts-reports", payload, headers)

    def accept_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/gross-receipts-reports/{report_id}/accept",
            payload, headers)

    def reject_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/gross-receipts-reports/{report_id}/reject",
            payload, headers)

    def amend_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/gross-receipts-reports/{report_id}/amend",
            payload, headers)

    def list_reports(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/gross-receipts-reports", headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/gross-receipts-reports/{report_id}", headers=headers)

    # ─── Fee reconciliations ───────────────────────────────────────────────
    def create_reconciliation(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/fee-reconciliations", payload, headers)

    def settle_reconciliation(self, reconciliation_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/fee-reconciliations/{reconciliation_id}/settle",
            payload, headers)

    def list_reconciliations(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/fee-reconciliations", headers=headers, params=params)

    def get_reconciliation(self, reconciliation_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/fee-reconciliations/{reconciliation_id}", headers=headers)

    # ─── Audit engagements ─────────────────────────────────────────────────
    def create_audit(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/audit-engagements", payload, headers)

    def begin_fieldwork(self, audit_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/audit-engagements/{audit_id}/begin-fieldwork",
            payload if payload is not None else {}, headers)

    def issue_findings(self, audit_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/audit-engagements/{audit_id}/issue-findings",
            payload, headers)

    def contest_findings(self, audit_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/audit-engagements/{audit_id}/contest", payload, headers)

    def finalize_audit(self, audit_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/audit-engagements/{audit_id}/finalize",
            payload if payload is not None else {}, headers)

    def withdraw_findings(self, audit_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/audit-engagements/{audit_id}/withdraw-findings",
            payload, headers)

    def list_audits(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/audit-engagements", headers=headers, params=params)

    def get_audit(self, audit_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/audit-engagements/{audit_id}", headers=headers)

    # ─── Compliance actions ────────────────────────────────────────────────
    def create_compliance_action(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/compliance-actions", payload, headers)

    def accept_cure(self, action_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/compliance-actions/{action_id}/accept-cure",
            payload, headers)

    def order_bond_draw(self, action_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/compliance-actions/{action_id}/order-bond-draw",
            payload, headers)

    def list_compliance_actions(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/compliance-actions", headers=headers, params=params)

    def get_compliance_action(self, action_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/compliance-actions/{action_id}", headers=headers)


api_client = ApiClient()
