"""API client: one method per endpoint the PRD declares.

All resource endpoints sit under the /retail prefix; the two logical-clock
endpoints sit at the server root.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Shopping centers ────────────────────────────────────────────────
    def create_center(self, payload, headers):
        return self._request("POST", "/retail/centers", payload, headers)

    def get_center(self, center_id, headers):
        return self._request("GET", f"/retail/centers/{center_id}", headers=headers)

    def get_center_sales_trend(self, center_id, headers, params=None):
        return self._request(
            "GET", f"/retail/centers/{center_id}/sales-trend",
            headers=headers, params=params,
        )

    # ─── Tenants ─────────────────────────────────────────────────────────
    def create_tenant(self, payload, headers):
        return self._request("POST", "/retail/tenants", payload, headers)

    def get_tenant(self, tenant_id, headers):
        return self._request("GET", f"/retail/tenants/{tenant_id}", headers=headers)

    def list_tenants(self, headers, params=None):
        return self._request("GET", "/retail/tenants", headers=headers, params=params)

    def set_tenant_status(self, tenant_id, payload, headers):
        return self._request(
            "POST", f"/retail/tenants/{tenant_id}/status", payload, headers)

    # ─── Leases ──────────────────────────────────────────────────────────
    def create_lease(self, payload, headers):
        return self._request("POST", "/retail/leases", payload, headers)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/retail/leases/{lease_id}", headers=headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/retail/leases", headers=headers, params=params)

    def activate_lease(self, lease_id, headers):
        return self._request(
            "POST", f"/retail/leases/{lease_id}/activate", {}, headers)

    def amend_lease(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/retail/leases/{lease_id}/amendments", payload, headers)

    def terminate_lease(self, lease_id, headers):
        return self._request(
            "POST", f"/retail/leases/{lease_id}/terminate", {}, headers)

    # ─── Reporting years ─────────────────────────────────────────────────
    def create_lease_year(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/retail/leases/{lease_id}/lease-years", payload, headers)

    def get_lease_year(self, lease_year_id, headers):
        return self._request(
            "GET", f"/retail/lease-years/{lease_year_id}", headers=headers)

    def list_lease_years(self, headers, params=None):
        return self._request(
            "GET", "/retail/lease-years", headers=headers, params=params)

    def list_ledger_entries(self, lease_year_id, headers, params=None):
        return self._request(
            "GET", f"/retail/lease-years/{lease_year_id}/ledger-entries",
            headers=headers, params=params,
        )

    def close_period(self, lease_year_id, headers):
        return self._request(
            "POST", f"/retail/lease-years/{lease_year_id}/close-period", {}, headers)

    def reconcile_lease_year(self, lease_year_id, headers):
        return self._request(
            "POST", f"/retail/lease-years/{lease_year_id}/reconcile", {}, headers)

    def reopen_lease_year(self, lease_year_id, payload, headers):
        return self._request(
            "POST", f"/retail/lease-years/{lease_year_id}/reopen", payload, headers)

    def close_lease_year(self, lease_year_id, headers):
        return self._request(
            "POST", f"/retail/lease-years/{lease_year_id}/close", {}, headers)

    # ─── Sales reports ───────────────────────────────────────────────────
    def create_sales_report(self, lease_year_id, payload, headers):
        return self._request(
            "POST", f"/retail/lease-years/{lease_year_id}/sales-reports",
            payload, headers,
        )

    def get_sales_report(self, report_id, headers):
        return self._request(
            "GET", f"/retail/sales-reports/{report_id}", headers=headers)

    def list_sales_reports(self, headers, params=None):
        return self._request(
            "GET", "/retail/sales-reports", headers=headers, params=params)

    def list_exclusions(self, report_id, headers, params=None):
        return self._request(
            "GET", f"/retail/sales-reports/{report_id}/exclusions",
            headers=headers, params=params,
        )

    def submit_sales_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/retail/sales-reports/{report_id}/submit", payload, headers)

    def accept_sales_report(self, report_id, headers):
        return self._request(
            "POST", f"/retail/sales-reports/{report_id}/accept", {}, headers)

    def estimate_bill_sales_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/retail/sales-reports/{report_id}/estimate-bill",
            payload, headers,
        )

    def dispute_sales_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/retail/sales-reports/{report_id}/dispute", payload, headers)

    def amend_sales_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/retail/sales-reports/{report_id}/amend", payload, headers)

    # ─── Percentage-rent charges ─────────────────────────────────────────
    def get_charge(self, charge_id, headers):
        return self._request("GET", f"/retail/charges/{charge_id}", headers=headers)

    def list_charges(self, headers, params=None):
        return self._request("GET", "/retail/charges", headers=headers, params=params)

    def issue_charge(self, charge_id, headers):
        return self._request(
            "POST", f"/retail/charges/{charge_id}/issue", {}, headers)

    def void_charge(self, charge_id, payload, headers):
        return self._request(
            "POST", f"/retail/charges/{charge_id}/void", payload, headers)

    def pay_charge(self, charge_id, payload, headers):
        return self._request(
            "POST", f"/retail/charges/{charge_id}/payments", payload, headers)

    # ─── Co-tenancy clauses and events ───────────────────────────────────
    def create_co_tenancy_clause(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/retail/leases/{lease_id}/co-tenancy-clauses", payload, headers)

    def get_co_tenancy_clause(self, clause_id, headers):
        return self._request(
            "GET", f"/retail/co-tenancy-clauses/{clause_id}", headers=headers)

    def list_co_tenancy_clauses(self, headers, params=None):
        return self._request(
            "GET", "/retail/co-tenancy-clauses", headers=headers, params=params)

    def get_co_tenancy_event(self, event_id, headers):
        return self._request(
            "GET", f"/retail/co-tenancy-events/{event_id}", headers=headers)

    def list_co_tenancy_events(self, headers, params=None):
        return self._request(
            "GET", "/retail/co-tenancy-events", headers=headers, params=params)

    def acknowledge_co_tenancy_event(self, event_id, headers):
        return self._request(
            "POST", f"/retail/co-tenancy-events/{event_id}/acknowledge", {}, headers)

    def activate_relief(self, event_id, headers):
        return self._request(
            "POST", f"/retail/co-tenancy-events/{event_id}/activate-relief",
            {}, headers,
        )

    def cure_co_tenancy_event(self, event_id, headers):
        return self._request(
            "POST", f"/retail/co-tenancy-events/{event_id}/cure", {}, headers)

    def elect_termination(self, event_id, headers):
        return self._request(
            "POST", f"/retail/co-tenancy-events/{event_id}/elect-termination",
            {}, headers,
        )

    # ─── Kick-out clauses ────────────────────────────────────────────────
    def create_kick_out_clause(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/retail/leases/{lease_id}/kick-out-clauses", payload, headers)

    def get_kick_out_clause(self, clause_id, headers):
        return self._request(
            "GET", f"/retail/kick-out-clauses/{clause_id}", headers=headers)

    def list_kick_out_clauses(self, headers, params=None):
        return self._request(
            "GET", "/retail/kick-out-clauses", headers=headers, params=params)

    def exercise_kick_out_clause(self, clause_id, headers):
        return self._request(
            "POST", f"/retail/kick-out-clauses/{clause_id}/exercise", {}, headers)

    def waive_kick_out_clause(self, clause_id, payload, headers):
        return self._request(
            "POST", f"/retail/kick-out-clauses/{clause_id}/waive", payload, headers)

    # ─── Sales audits ────────────────────────────────────────────────────
    def create_audit(self, payload, headers):
        return self._request("POST", "/retail/audits", payload, headers)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/retail/audits/{audit_id}", headers=headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/retail/audits", headers=headers, params=params)

    def issue_audit_findings(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/retail/audits/{audit_id}/findings", payload, headers)

    def settle_audit(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/retail/audits/{audit_id}/settle", payload, headers)

    def rescind_audit(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/retail/audits/{audit_id}/rescind", payload, headers)

    # ─── Logical clock ───────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)


api_client = ApiClient()
