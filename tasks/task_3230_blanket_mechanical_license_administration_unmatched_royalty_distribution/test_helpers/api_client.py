"""API client: one method per endpoint defined in the PRD (all mounted under /mlc)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/mlc/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- service providers ---
    def create_service_provider(self, payload, headers):
        return self._request("POST", "/mlc/service-providers", payload, headers)

    def list_service_providers(self, headers, params=None):
        return self._request("GET", "/mlc/service-providers", headers=headers, params=params)

    def get_service_provider(self, sp_id, headers):
        return self._request("GET", f"/mlc/service-providers/{sp_id}", headers=headers)

    def activate_service_provider(self, sp_id, headers):
        return self._request("POST", f"/mlc/service-providers/{sp_id}/activate", {}, headers)

    def suspend_service_provider(self, sp_id, headers):
        return self._request("POST", f"/mlc/service-providers/{sp_id}/suspend", {}, headers)

    def reinstate_service_provider(self, sp_id, headers):
        return self._request("POST", f"/mlc/service-providers/{sp_id}/reinstate", {}, headers)

    def terminate_service_provider(self, sp_id, headers):
        return self._request("POST", f"/mlc/service-providers/{sp_id}/terminate", {}, headers)

    # --- members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/mlc/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/mlc/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/mlc/members/{member_id}", headers=headers)

    def suspend_member(self, member_id, headers):
        return self._request("POST", f"/mlc/members/{member_id}/suspend", {}, headers)

    def reinstate_member(self, member_id, headers):
        return self._request("POST", f"/mlc/members/{member_id}/reinstate", {}, headers)

    def terminate_member(self, member_id, headers):
        return self._request("POST", f"/mlc/members/{member_id}/terminate", {}, headers)

    # --- payees ---
    def create_payee(self, member_id, payload, headers):
        return self._request("POST", f"/mlc/members/{member_id}/payees", payload, headers)

    def list_payees(self, member_id, headers, params=None):
        return self._request("GET", f"/mlc/members/{member_id}/payees", headers=headers, params=params)

    def get_payee(self, member_id, payee_id, headers):
        return self._request("GET", f"/mlc/members/{member_id}/payees/{payee_id}", headers=headers)

    def get_payee_flat(self, payee_id, headers):
        return self._request("GET", f"/mlc/payees/{payee_id}", headers=headers)

    def suspend_payee(self, member_id, payee_id, headers):
        return self._request("POST", f"/mlc/members/{member_id}/payees/{payee_id}/suspend", {}, headers)

    def reinstate_payee(self, member_id, payee_id, headers):
        return self._request("POST", f"/mlc/members/{member_id}/payees/{payee_id}/reinstate", {}, headers)

    def terminate_payee(self, member_id, payee_id, headers):
        return self._request("POST", f"/mlc/members/{member_id}/payees/{payee_id}/terminate", {}, headers)

    # --- works ---
    def create_work(self, payload, headers):
        return self._request("POST", "/mlc/works", payload, headers)

    def list_works(self, headers, params=None):
        return self._request("GET", "/mlc/works", headers=headers, params=params)

    def get_work(self, work_id, headers):
        return self._request("GET", f"/mlc/works/{work_id}", headers=headers)

    def withdraw_work(self, work_id, headers):
        return self._request("POST", f"/mlc/works/{work_id}/withdraw", {}, headers)

    # --- work shares ---
    def create_share(self, work_id, payload, headers):
        return self._request("POST", f"/mlc/works/{work_id}/shares", payload, headers)

    def list_shares(self, work_id, headers, params=None):
        return self._request("GET", f"/mlc/works/{work_id}/shares", headers=headers, params=params)

    def get_share(self, work_id, share_id, headers):
        return self._request("GET", f"/mlc/works/{work_id}/shares/{share_id}", headers=headers)

    def get_share_flat(self, share_id, headers):
        return self._request("GET", f"/mlc/shares/{share_id}", headers=headers)

    def list_shares_flat(self, headers, params=None):
        return self._request("GET", "/mlc/shares", headers=headers, params=params)

    def withdraw_share(self, work_id, share_id, headers):
        return self._request("POST", f"/mlc/works/{work_id}/shares/{share_id}/withdraw", {}, headers)

    # --- rate schedules ---
    def create_rate_schedule(self, payload, headers):
        return self._request("POST", "/mlc/rate-schedules", payload, headers)

    def list_rate_schedules(self, headers, params=None):
        return self._request("GET", "/mlc/rate-schedules", headers=headers, params=params)

    def get_rate_schedule(self, rs_id, headers):
        return self._request("GET", f"/mlc/rate-schedules/{rs_id}", headers=headers)

    def activate_rate_schedule(self, rs_id, headers):
        return self._request("POST", f"/mlc/rate-schedules/{rs_id}/activate", {}, headers)

    # --- usage reports ---
    def create_usage_report(self, sp_id, payload, headers):
        return self._request("POST", f"/mlc/service-providers/{sp_id}/usage-reports", payload, headers)

    def list_usage_reports(self, sp_id, headers, params=None):
        return self._request("GET", f"/mlc/service-providers/{sp_id}/usage-reports", headers=headers, params=params)

    def get_usage_report(self, sp_id, report_id, headers):
        return self._request("GET", f"/mlc/service-providers/{sp_id}/usage-reports/{report_id}", headers=headers)

    def submit_usage_report(self, sp_id, report_id, accepted_rate_schedule_version, headers):
        return self._request("POST", f"/mlc/service-providers/{sp_id}/usage-reports/{report_id}/submit",
                             {"accepted_rate_schedule_version": accepted_rate_schedule_version}, headers)

    def accept_usage_report(self, sp_id, report_id, accepted_rate_schedule_version, headers):
        return self._request("POST", f"/mlc/service-providers/{sp_id}/usage-reports/{report_id}/accept",
                             {"accepted_rate_schedule_version": accepted_rate_schedule_version}, headers)

    def reject_usage_report(self, sp_id, report_id, headers):
        return self._request("POST", f"/mlc/service-providers/{sp_id}/usage-reports/{report_id}/reject", {}, headers)

    def reopen_usage_report(self, sp_id, report_id, headers):
        return self._request("POST", f"/mlc/service-providers/{sp_id}/usage-reports/{report_id}/reopen", {}, headers)

    # --- usage lines ---
    def create_usage_line(self, sp_id, report_id, payload, headers):
        return self._request("POST", f"/mlc/service-providers/{sp_id}/usage-reports/{report_id}/lines",
                             payload, headers)

    def list_usage_lines(self, sp_id, report_id, headers, params=None):
        return self._request("GET", f"/mlc/service-providers/{sp_id}/usage-reports/{report_id}/lines",
                             headers=headers, params=params)

    def get_usage_line(self, line_id, headers):
        return self._request("GET", f"/mlc/usage-lines/{line_id}", headers=headers)

    def list_usage_lines_flat(self, headers, params=None):
        return self._request("GET", "/mlc/usage-lines", headers=headers, params=params)

    def list_line_accruals(self, line_id, headers, params=None):
        return self._request("GET", f"/mlc/usage-lines/{line_id}/accruals", headers=headers, params=params)

    # --- match runs ---
    def create_match_run(self, headers):
        return self._request("POST", "/mlc/match-runs", {}, headers)

    def list_match_runs(self, headers, params=None):
        return self._request("GET", "/mlc/match-runs", headers=headers, params=params)

    def get_match_run(self, run_id, headers):
        return self._request("GET", f"/mlc/match-runs/{run_id}", headers=headers)

    # --- accruals ---
    def list_accruals(self, headers, params=None):
        return self._request("GET", "/mlc/accruals", headers=headers, params=params)

    def get_accrual(self, accrual_id, headers):
        return self._request("GET", f"/mlc/accruals/{accrual_id}", headers=headers)

    def list_accrual_claims(self, accrual_id, headers, params=None):
        return self._request("GET", f"/mlc/accruals/{accrual_id}/claims", headers=headers, params=params)

    # --- claims ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/mlc/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/mlc/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/mlc/claims", headers=headers, params=params)

    def validate_claim(self, claim_id, headers):
        return self._request("POST", f"/mlc/claims/{claim_id}/validate", {}, headers)

    def reject_claim(self, claim_id, headers):
        return self._request("POST", f"/mlc/claims/{claim_id}/reject", {}, headers)

    def withdraw_claim(self, claim_id, headers):
        return self._request("POST", f"/mlc/claims/{claim_id}/withdraw", {}, headers)

    # --- disputes ---
    def create_dispute(self, payload, headers):
        return self._request("POST", "/mlc/disputes", payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/mlc/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/mlc/disputes/{dispute_id}", headers=headers)

    def list_work_disputes(self, work_id, headers, params=None):
        return self._request("GET", f"/mlc/works/{work_id}/disputes", headers=headers, params=params)

    def resolve_dispute(self, dispute_id, winning_claim_id, resolution_note, headers):
        return self._request("POST", f"/mlc/disputes/{dispute_id}/resolve",
                             {"winning_claim_id": winning_claim_id,
                              "resolution_note": resolution_note}, headers)

    def escalate_dispute(self, dispute_id, headers):
        return self._request("POST", f"/mlc/disputes/{dispute_id}/escalate", {}, headers)

    # --- statements ---
    def create_statement(self, member_id, period_month, headers):
        return self._request("POST", f"/mlc/members/{member_id}/statements",
                             {"period_month": period_month}, headers)

    def list_statements(self, member_id, headers, params=None):
        return self._request("GET", f"/mlc/members/{member_id}/statements", headers=headers, params=params)

    def get_statement(self, member_id, statement_id, headers):
        return self._request("GET", f"/mlc/members/{member_id}/statements/{statement_id}", headers=headers)

    def get_statement_flat(self, statement_id, headers):
        return self._request("GET", f"/mlc/statements/{statement_id}", headers=headers)

    def list_statement_lines(self, member_id, statement_id, headers, params=None):
        return self._request("GET", f"/mlc/members/{member_id}/statements/{statement_id}/lines",
                             headers=headers, params=params)

    def list_statement_lines_flat(self, headers, params=None):
        return self._request("GET", "/mlc/statement-lines", headers=headers, params=params)

    def get_statement_line(self, line_id, headers):
        return self._request("GET", f"/mlc/statement-lines/{line_id}", headers=headers)

    def finalize_statement(self, member_id, statement_id, headers):
        return self._request("POST", f"/mlc/members/{member_id}/statements/{statement_id}/finalize", {}, headers)

    def reopen_statement(self, member_id, statement_id, headers):
        return self._request("POST", f"/mlc/members/{member_id}/statements/{statement_id}/reopen", {}, headers)

    def deliver_statement(self, member_id, statement_id, headers):
        return self._request("POST", f"/mlc/members/{member_id}/statements/{statement_id}/deliver", {}, headers)

    # --- audits ---
    def create_audit(self, sp_id, auditor_member_id, scope_months, headers):
        return self._request("POST", f"/mlc/service-providers/{sp_id}/audits",
                             {"auditor_member_id": auditor_member_id,
                              "scope_months": scope_months}, headers)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/mlc/audits/{audit_id}", headers=headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/mlc/audits", headers=headers, params=params)

    def list_dsp_audits(self, sp_id, headers, params=None):
        return self._request("GET", f"/mlc/service-providers/{sp_id}/audits", headers=headers, params=params)

    def issue_audit_findings(self, audit_id, findings_note, headers):
        return self._request("POST", f"/mlc/audits/{audit_id}/issue-findings",
                             {"findings_note": findings_note}, headers)

    def close_audit(self, audit_id, adjustment_cents, headers):
        return self._request("POST", f"/mlc/audits/{audit_id}/close",
                             {"adjustment_cents": adjustment_cents}, headers)

    def withdraw_audit(self, audit_id, headers):
        return self._request("POST", f"/mlc/audits/{audit_id}/withdraw", {}, headers)

    # --- cycle runs ---
    def create_cycle_run(self, payload, headers):
        return self._request("POST", "/mlc/cycle-runs", payload, headers)

    def list_cycle_runs(self, headers, params=None):
        return self._request("GET", "/mlc/cycle-runs", headers=headers, params=params)

    def get_cycle_run(self, cycle_id, headers):
        return self._request("GET", f"/mlc/cycle-runs/{cycle_id}", headers=headers)

    def close_cycle_run(self, cycle_id, headers):
        return self._request("POST", f"/mlc/cycle-runs/{cycle_id}/close", {}, headers)

    def list_cycle_distribution_lines(self, cycle_id, headers, params=None):
        return self._request("GET", f"/mlc/cycle-runs/{cycle_id}/distribution-lines",
                             headers=headers, params=params)

    def list_distribution_lines(self, headers, params=None):
        return self._request("GET", "/mlc/distribution-lines", headers=headers, params=params)

    def get_distribution_line(self, line_id, headers):
        return self._request("GET", f"/mlc/distribution-lines/{line_id}", headers=headers)


api_client = ApiClient()
