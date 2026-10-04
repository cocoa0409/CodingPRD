"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock / probe ---
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def probe_no_auth(self, headers=None):
        return self._request("GET", "/_probe/no-auth", headers=headers)

    # --- Jurisdictions ---
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/jurisdictions", payload, headers)

    def list_jurisdictions(self, headers, params=None):
        return self._request("GET", "/jurisdictions", headers=headers, params=params)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request(
            "GET", f"/jurisdictions/{jurisdiction_id}", headers=headers
        )

    # --- Clients ---
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def begin_onboarding(self, client_id, headers):
        return self._request(
            "POST", f"/clients/{client_id}/begin-onboarding", {}, headers
        )

    def activate_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/activate", {}, headers)

    def terminate_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/terminate", {}, headers)

    def reactivate_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/reactivate", {}, headers)

    def set_credit_hold(self, client_id, hold, headers):
        return self._request(
            "POST", f"/clients/{client_id}/credit-hold", {"hold": hold}, headers
        )

    def list_client_funding_failures(self, client_id, headers, params=None):
        return self._request(
            "GET", f"/clients/{client_id}/funding-failures", headers=headers, params=params
        )

    def list_client_credit_assessments(self, client_id, headers, params=None):
        return self._request(
            "GET",
            f"/clients/{client_id}/credit-assessments",
            headers=headers,
            params=params,
        )

    def create_credit_assessment(self, client_id, payload, headers):
        return self._request(
            "POST", f"/clients/{client_id}/credit-assessments", payload, headers
        )

    # --- Registrations ---
    def create_registration(self, client_id, payload, headers):
        return self._request(
            "POST", f"/clients/{client_id}/registrations", payload, headers
        )

    def list_client_registrations(self, client_id, headers, params=None):
        return self._request(
            "GET", f"/clients/{client_id}/registrations", headers=headers, params=params
        )

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/registrations", headers=headers, params=params)

    def get_registration(self, registration_id, headers):
        return self._request(
            "GET", f"/registrations/{registration_id}", headers=headers
        )

    def verify_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/verify", {}, headers
        )

    def reject_registration(self, registration_id, reason, headers):
        return self._request(
            "POST",
            f"/registrations/{registration_id}/reject",
            {"reason": reason},
            headers,
        )

    def resubmit_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/resubmit", {}, headers
        )

    # --- Payroll runs ---
    def create_payroll_run(self, payload, headers):
        return self._request("POST", "/payroll-runs", payload, headers)

    def list_payroll_runs(self, headers, params=None):
        return self._request("GET", "/payroll-runs", headers=headers, params=params)

    def get_payroll_run(self, run_id, headers):
        return self._request("GET", f"/payroll-runs/{run_id}", headers=headers)

    def submit_run(self, run_id, headers):
        return self._request("POST", f"/payroll-runs/{run_id}/submit", {}, headers)

    def initiate_impound(self, run_id, expected_client_version, headers):
        return self._request(
            "POST",
            f"/payroll-runs/{run_id}/initiate-impound",
            {"expected_client_version": expected_client_version},
            headers,
        )

    def cancel_run(self, run_id, headers):
        return self._request("POST", f"/payroll-runs/{run_id}/cancel", {}, headers)

    def reverse_run(self, run_id, headers):
        return self._request("POST", f"/payroll-runs/{run_id}/reverse", {}, headers)

    # --- Impounds ---
    def list_impounds(self, headers, params=None):
        return self._request("GET", "/impounds", headers=headers, params=params)

    def get_impound(self, impound_id, headers):
        return self._request("GET", f"/impounds/{impound_id}", headers=headers)

    def settle_impound(self, impound_id, headers):
        return self._request("POST", f"/impounds/{impound_id}/settle", {}, headers)

    def fail_impound(self, impound_id, headers):
        return self._request("POST", f"/impounds/{impound_id}/fail", {}, headers)

    def return_impound(self, impound_id, headers):
        return self._request("POST", f"/impounds/{impound_id}/return", {}, headers)

    def confirm_wire(self, impound_id, headers):
        return self._request(
            "POST", f"/impounds/{impound_id}/confirm-wire", {}, headers
        )

    def miss_wire(self, impound_id, headers):
        return self._request("POST", f"/impounds/{impound_id}/miss-wire", {}, headers)

    # --- Funding failures ---
    def get_funding_failure(self, event_id, headers):
        return self._request(
            "GET", f"/funding-failures/{event_id}", headers=headers
        )

    def list_funding_failures(self, headers, params=None):
        return self._request(
            "GET", "/funding-failures", headers=headers, params=params
        )

    def resolve_funding_failure(self, event_id, headers):
        return self._request(
            "POST", f"/funding-failures/{event_id}/resolve", {}, headers
        )

    # --- Tax deposits ---
    def create_deposit(self, run_id, payload, headers):
        return self._request(
            "POST", f"/payroll-runs/{run_id}/deposits", payload, headers
        )

    def list_deposits(self, headers, params=None):
        return self._request("GET", "/deposits", headers=headers, params=params)

    def get_deposit(self, deposit_id, headers):
        return self._request("GET", f"/deposits/{deposit_id}", headers=headers)

    def submit_deposit(self, deposit_id, headers):
        return self._request("POST", f"/deposits/{deposit_id}/submit", {}, headers)

    def confirm_deposit(self, deposit_id, headers):
        return self._request("POST", f"/deposits/{deposit_id}/confirm", {}, headers)

    def fail_deposit(self, deposit_id, headers):
        return self._request("POST", f"/deposits/{deposit_id}/fail", {}, headers)

    def reschedule_deposit(self, deposit_id, headers):
        return self._request(
            "POST", f"/deposits/{deposit_id}/reschedule", {}, headers
        )

    def cancel_deposit(self, deposit_id, headers):
        return self._request("POST", f"/deposits/{deposit_id}/cancel", {}, headers)

    # --- Tax returns ---
    def create_return(self, payload, headers):
        return self._request("POST", "/returns", payload, headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/returns", headers=headers, params=params)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/returns/{return_id}", headers=headers)

    def file_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/file", {}, headers)

    def accept_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/accept", {}, headers)

    def reject_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/reject", {}, headers)

    def redraft_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/redraft", {}, headers)

    def reconcile_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/reconcile", {}, headers)

    def list_return_amendments(self, return_id, headers, params=None):
        return self._request(
            "GET", f"/returns/{return_id}/amendments", headers=headers, params=params
        )

    def list_return_notices(self, return_id, headers, params=None):
        return self._request(
            "GET", f"/returns/{return_id}/notices", headers=headers, params=params
        )

    # --- Amendments ---
    def create_amendment(self, payload, headers):
        return self._request("POST", "/amendments", payload, headers)

    def list_amendments(self, headers, params=None):
        return self._request("GET", "/amendments", headers=headers, params=params)

    def get_amendment(self, amendment_id, headers):
        return self._request("GET", f"/amendments/{amendment_id}", headers=headers)

    def file_amendment(self, amendment_id, headers):
        return self._request("POST", f"/amendments/{amendment_id}/file", {}, headers)

    def accept_amendment(self, amendment_id, headers):
        return self._request(
            "POST", f"/amendments/{amendment_id}/accept", {}, headers
        )

    def reject_amendment(self, amendment_id, headers):
        return self._request(
            "POST", f"/amendments/{amendment_id}/reject", {}, headers
        )

    def redraft_amendment(self, amendment_id, headers):
        return self._request(
            "POST", f"/amendments/{amendment_id}/redraft", {}, headers
        )

    # --- Agency notices ---
    def create_notice(self, payload, headers):
        return self._request("POST", "/notices", payload, headers)

    def list_notices(self, headers, params=None):
        return self._request("GET", "/notices", headers=headers, params=params)

    def get_notice(self, notice_id, headers):
        return self._request("GET", f"/notices/{notice_id}", headers=headers)

    def start_notice_review(self, notice_id, headers):
        return self._request(
            "POST", f"/notices/{notice_id}/start-review", {}, headers
        )

    def resolve_notice(self, notice_id, payload, headers):
        return self._request(
            "POST", f"/notices/{notice_id}/resolve", payload, headers
        )

    def escalate_notice(self, notice_id, headers):
        return self._request("POST", f"/notices/{notice_id}/escalate", {}, headers)

    def close_notice(self, notice_id, headers):
        return self._request("POST", f"/notices/{notice_id}/close", {}, headers)

    # --- Wage statements ---
    def create_wage_statement(self, payload, headers):
        return self._request("POST", "/wage-statements", payload, headers)

    def list_wage_statements(self, headers, params=None):
        return self._request(
            "GET", "/wage-statements", headers=headers, params=params
        )

    def get_wage_statement(self, statement_id, headers):
        return self._request(
            "GET", f"/wage-statements/{statement_id}", headers=headers
        )

    def issue_wage_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/wage-statements/{statement_id}/issue", {}, headers
        )

    def void_wage_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/wage-statements/{statement_id}/void", {}, headers
        )

    def wage_statement_summary(self, client_id, headers, params=None):
        return self._request(
            "GET",
            f"/clients/{client_id}/wage-statements/summary",
            headers=headers,
            params=params,
        )

    # --- Credit assessments ---
    def list_credit_assessments(self, headers, params=None):
        return self._request(
            "GET", "/credit-assessments", headers=headers, params=params
        )

    def get_credit_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"/credit-assessments/{assessment_id}", headers=headers
        )


api_client = ApiClient()
