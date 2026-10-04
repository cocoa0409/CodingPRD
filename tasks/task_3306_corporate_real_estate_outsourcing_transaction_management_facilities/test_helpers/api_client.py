"""API client: one method per endpoint in the PRD (§4 table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Accounts ─────────────────────────────────────
    def create_account(self, payload, headers):
        return self._request("POST", "/api/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/api/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/api/accounts/{account_id}", headers=headers)

    def update_account(self, account_id, payload, headers):
        return self._request("PUT", f"/api/accounts/{account_id}", payload, headers)

    def activate_account(self, account_id, headers):
        return self._request("POST", f"/api/accounts/{account_id}/activate", {}, headers)

    def begin_transition(self, account_id, headers):
        return self._request("POST", f"/api/accounts/{account_id}/transitions", {}, headers)

    def abort_transition(self, account_id, headers):
        return self._request(
            "POST", f"/api/accounts/{account_id}/abort-transition", {}, headers
        )

    def close_account(self, account_id, headers):
        return self._request("POST", f"/api/accounts/{account_id}/close", {}, headers)

    def close_converted_account(self, account_id, headers):
        return self._request(
            "POST", f"/api/accounts/{account_id}/close-converted", {}, headers
        )

    def create_assignment(self, account_id, payload, headers):
        return self._request(
            "POST", f"/api/accounts/{account_id}/assignments", payload, headers
        )

    def create_account_assignment(self, payload, headers):
        return self._request("POST", "/api/account-assignments", payload, headers)

    def list_account_leases(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/api/accounts/{account_id}/leases", headers=headers, params=params
        )

    def list_account_commission_records(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/accounts/{account_id}/commission-records",
            headers=headers,
            params=params,
        )

    def list_account_kpis(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/accounts/{account_id}/service-level-kpis",
            headers=headers,
            params=params,
        )

    def list_account_vendors(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/accounts/{account_id}/facilities-vendors",
            headers=headers,
            params=params,
        )

    def list_account_sites(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/accounts/{account_id}/facility-sites",
            headers=headers,
            params=params,
        )

    def list_account_scorecards(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/api/accounts/{account_id}/scorecards", headers=headers, params=params
        )

    def list_account_audits(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/accounts/{account_id}/discipline-audits",
            headers=headers,
            params=params,
        )

    def list_account_data_licenses(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/accounts/{account_id}/data-licenses",
            headers=headers,
            params=params,
        )

    def list_account_transition_tasks(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/accounts/{account_id}/transition-tasks",
            headers=headers,
            params=params,
        )

    def list_account_fee_accruals(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/api/accounts/{account_id}/fee-accruals", headers=headers, params=params
        )

    def list_account_consolidation_projects(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/accounts/{account_id}/consolidation-projects",
            headers=headers,
            params=params,
        )

    def list_account_audit_reviews(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/api/accounts/{account_id}/audit-reviews", headers=headers, params=params
        )

    def list_account_assignments(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/accounts/{account_id}/assignments",
            headers=headers,
            params=params,
        )

    # ─── Leases ───────────────────────────────────────
    def create_lease(self, payload, headers):
        return self._request("POST", "/api/leases", payload, headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/api/leases", headers=headers, params=params)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/api/leases/{lease_id}", headers=headers)

    def submit_lease_for_approval(self, lease_id, headers):
        return self._request(
            "POST", f"/api/leases/{lease_id}/submit-for-approval", {}, headers
        )

    def approve_lease(self, lease_id, headers):
        return self._request("POST", f"/api/leases/{lease_id}/approve", {}, headers)

    def reject_lease(self, lease_id, headers):
        return self._request("POST", f"/api/leases/{lease_id}/reject", {}, headers)

    def revise_lease(self, lease_id, payload, headers):
        return self._request("POST", f"/api/leases/{lease_id}/revise", payload, headers)

    def launch_marketing(self, lease_id, headers):
        return self._request("POST", f"/api/leases/{lease_id}/launch-marketing", {}, headers)

    def open_negotiation(self, lease_id, headers):
        return self._request("POST", f"/api/leases/{lease_id}/open-negotiation", {}, headers)

    def execute_lease(self, lease_id, headers):
        return self._request("POST", f"/api/leases/{lease_id}/execute", {}, headers)

    def expire_lease(self, lease_id, headers):
        return self._request("POST", f"/api/leases/{lease_id}/expire", {}, headers)

    def apply_lease_execution(self, accrual_id, headers):
        return self._request(
            "POST", f"/api/lease-executions/{accrual_id}/apply", {}, headers
        )

    # ─── Transaction requests ─────────────────────────
    def create_transaction_request(self, payload, headers):
        return self._request("POST", "/api/transaction-requests", payload, headers)

    def list_transaction_requests(self, headers, params=None):
        return self._request(
            "GET", "/api/transaction-requests", headers=headers, params=params
        )

    def get_transaction_request(self, request_id, headers):
        return self._request(
            "GET", f"/api/transaction-requests/{request_id}", headers=headers
        )

    def submit_transaction_request(self, request_id, headers):
        return self._request(
            "POST", f"/api/transaction-requests/{request_id}/submit", {}, headers
        )

    def decide_transaction_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/api/transaction-requests/{request_id}/decide", payload, headers
        )

    def withdraw_transaction_request(self, request_id, headers):
        return self._request(
            "POST", f"/api/transaction-requests/{request_id}/withdraw", {}, headers
        )

    def cancel_transaction_request(self, request_id, headers):
        return self._request(
            "POST", f"/api/transaction-requests/{request_id}/cancel", {}, headers
        )

    # ─── Commission records ───────────────────────────
    def create_commission_record(self, payload, headers):
        return self._request("POST", "/api/commission-records", payload, headers)

    def list_commission_records(self, headers, params=None):
        return self._request(
            "GET", "/api/commission-records", headers=headers, params=params
        )

    def get_commission_record(self, record_id, headers):
        return self._request(
            "GET", f"/api/commission-records/{record_id}", headers=headers
        )

    # ─── Broker engagements ───────────────────────────
    def create_broker_engagement(self, payload, headers):
        return self._request("POST", "/api/broker-engagements", payload, headers)

    def list_broker_engagements(self, headers, params=None):
        return self._request(
            "GET", "/api/broker-engagements", headers=headers, params=params
        )

    def get_broker_engagement(self, engagement_id, headers):
        return self._request(
            "GET", f"/api/broker-engagements/{engagement_id}", headers=headers
        )

    def assign_broker_engagement(self, engagement_id, headers):
        return self._request(
            "POST", f"/api/broker-engagements/{engagement_id}/assign", {}, headers
        )

    def execute_broker_engagement(self, engagement_id, headers):
        return self._request(
            "POST", f"/api/broker-engagements/{engagement_id}/execute", {}, headers
        )

    def terminate_broker_engagement(self, engagement_id, headers):
        return self._request(
            "POST", f"/api/broker-engagements/{engagement_id}/terminate", {}, headers
        )

    # ─── Service-level KPIs ───────────────────────────
    def create_kpi(self, payload, headers):
        return self._request("POST", "/api/service-level-kpis", payload, headers)

    def list_kpis(self, headers, params=None):
        return self._request("GET", "/api/service-level-kpis", headers=headers, params=params)

    def get_kpi(self, kpi_id, headers):
        return self._request("GET", f"/api/service-level-kpis/{kpi_id}", headers=headers)

    def evaluate_kpi(self, kpi_id, payload, headers):
        return self._request(
            "POST", f"/api/service-level-kpis/{kpi_id}/evaluate", payload, headers
        )

    # ─── Facilities vendors ───────────────────────────
    def create_vendor(self, payload, headers):
        return self._request("POST", "/api/facilities-vendors", payload, headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/api/facilities-vendors", headers=headers, params=params)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/api/facilities-vendors/{vendor_id}", headers=headers)

    def activate_vendor(self, vendor_id, headers):
        return self._request(
            "POST", f"/api/facilities-vendors/{vendor_id}/activate", {}, headers
        )

    def suspend_vendor(self, vendor_id, headers):
        return self._request(
            "POST", f"/api/facilities-vendors/{vendor_id}/suspend", {}, headers
        )

    def reinstate_vendor(self, vendor_id, headers):
        return self._request(
            "POST", f"/api/facilities-vendors/{vendor_id}/reinstate", {}, headers
        )

    def terminate_vendor(self, vendor_id, headers):
        return self._request(
            "POST", f"/api/facilities-vendors/{vendor_id}/terminate", {}, headers
        )

    # ─── Facility sites ───────────────────────────────
    def create_site(self, payload, headers):
        return self._request("POST", "/api/facility-sites", payload, headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/api/facility-sites", headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/api/facility-sites/{site_id}", headers=headers)

    def vacate_site(self, site_id, headers):
        return self._request("POST", f"/api/facility-sites/{site_id}/vacate", {}, headers)

    def consolidate_site(self, site_id, payload, headers):
        return self._request(
            "POST", f"/api/facility-sites/{site_id}/consolidate", payload, headers
        )

    def dispose_site(self, site_id, headers):
        return self._request("POST", f"/api/facility-sites/{site_id}/dispose", {}, headers)

    # ─── Consolidation projects ───────────────────────
    def create_consolidation_project(self, payload, headers):
        return self._request("POST", "/api/consolidation-projects", payload, headers)

    def list_consolidation_projects(self, headers, params=None):
        return self._request(
            "GET", "/api/consolidation-projects", headers=headers, params=params
        )

    def get_consolidation_project(self, project_id, headers):
        return self._request(
            "GET", f"/api/consolidation-projects/{project_id}", headers=headers
        )

    def submit_consolidation_project(self, project_id, headers):
        return self._request(
            "POST", f"/api/consolidation-projects/{project_id}/submit", {}, headers
        )

    def approve_consolidation_project(self, project_id, headers):
        return self._request(
            "POST", f"/api/consolidation-projects/{project_id}/approve", {}, headers
        )

    def start_consolidation_execution(self, project_id, headers):
        return self._request(
            "POST", f"/api/consolidation-projects/{project_id}/start-execution", {}, headers
        )

    def return_consolidation_to_planning(self, project_id, headers):
        return self._request(
            "POST",
            f"/api/consolidation-projects/{project_id}/return-to-planning",
            {},
            headers,
        )

    def cancel_consolidation_project(self, project_id, headers):
        return self._request(
            "POST", f"/api/consolidation-projects/{project_id}/cancel", {}, headers
        )

    # ─── Scorecards ───────────────────────────────────
    def create_scorecard(self, payload, headers):
        return self._request("POST", "/api/scorecards", payload, headers)

    def list_scorecards(self, headers, params=None):
        return self._request("GET", "/api/scorecards", headers=headers, params=params)

    def get_scorecard(self, scorecard_id, headers):
        return self._request("GET", f"/api/scorecards/{scorecard_id}", headers=headers)

    def publish_scorecard(self, scorecard_id, payload, headers):
        return self._request(
            "POST", f"/api/scorecards/{scorecard_id}/publish", payload, headers
        )

    # ─── Discipline audits ────────────────────────────
    def create_audit(self, payload, headers):
        return self._request("POST", "/api/discipline-audits", payload, headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/api/discipline-audits", headers=headers, params=params)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/api/discipline-audits/{audit_id}", headers=headers)

    def start_audit(self, audit_id, headers):
        return self._request("POST", f"/api/discipline-audits/{audit_id}/start", {}, headers)

    def decide_audit(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/api/discipline-audits/{audit_id}/decide", payload, headers
        )

    def list_audit_reviews(self, audit_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/discipline-audits/{audit_id}/reviews",
            headers=headers,
            params=params,
        )

    def create_audit_review(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/api/discipline-audits/{audit_id}/reviews", payload, headers
        )

    def get_audit_review(self, review_id, headers):
        return self._request("GET", f"/api/audit-reviews/{review_id}", headers=headers)

    # ─── Data licences ────────────────────────────────
    def create_data_license(self, payload, headers):
        return self._request("POST", "/api/data-licenses", payload, headers)

    def list_data_licenses(self, headers, params=None):
        return self._request("GET", "/api/data-licenses", headers=headers, params=params)

    def get_data_license(self, license_id, headers):
        return self._request("GET", f"/api/data-licenses/{license_id}", headers=headers)

    def grant_data_license(self, license_id, payload, headers):
        return self._request(
            "POST", f"/api/data-licenses/{license_id}/grant", payload, headers
        )

    def reject_data_license(self, license_id, headers):
        return self._request(
            "POST", f"/api/data-licenses/{license_id}/reject", {}, headers
        )

    # ─── Transition tasks ─────────────────────────────
    def create_transition_task(self, payload, headers):
        return self._request("POST", "/api/transition-tasks", payload, headers)

    def list_transition_tasks(self, headers, params=None):
        return self._request("GET", "/api/transition-tasks", headers=headers, params=params)

    def get_transition_task(self, task_id, headers):
        return self._request("GET", f"/api/transition-tasks/{task_id}", headers=headers)

    def start_transition_task(self, task_id, headers):
        return self._request("POST", f"/api/transition-tasks/{task_id}/start", {}, headers)

    def complete_transition_task(self, task_id, headers):
        return self._request(
            "POST", f"/api/transition-tasks/{task_id}/complete", {}, headers
        )

    def fail_transition_task(self, task_id, headers):
        return self._request("POST", f"/api/transition-tasks/{task_id}/fail", {}, headers)

    def expire_transition_task(self, task_id, headers):
        return self._request("POST", f"/api/transition-tasks/{task_id}/expire", {}, headers)

    # ─── Fee accruals ─────────────────────────────────
    def create_fee_accrual(self, payload, headers):
        return self._request("POST", "/api/fee-accruals", payload, headers)

    def list_fee_accruals(self, headers, params=None):
        return self._request("GET", "/api/fee-accruals", headers=headers, params=params)

    def get_fee_accrual(self, accrual_id, headers):
        return self._request("GET", f"/api/fee-accruals/{accrual_id}", headers=headers)

    def settle_fee_accrual(self, accrual_id, headers):
        return self._request("POST", f"/api/fee-accruals/{accrual_id}/settle", {}, headers)

    # ─── Logical clock ────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()