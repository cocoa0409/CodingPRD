"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            payload={"current_utc": current_utc}, headers=headers,
        )

    # --- issuer applications ---
    def create_application(self, payload, headers):
        return self._request("POST", "/issuer-applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/issuer-applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/issuer-applications/{application_id}", headers=headers)

    def patch_application(self, application_id, payload, headers):
        return self._request("PATCH", f"/issuer-applications/{application_id}", payload, headers)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/issuer-applications/{application_id}/submit", headers=headers)

    def review_application(self, application_id, headers):
        return self._request("POST", f"/issuer-applications/{application_id}/review", headers=headers)

    def request_revision(self, application_id, headers):
        return self._request("POST", f"/issuer-applications/{application_id}/request-revision", headers=headers)

    def approve_application(self, application_id, headers):
        return self._request("POST", f"/issuer-applications/{application_id}/approve", headers=headers)

    def deny_application(self, application_id, headers):
        return self._request("POST", f"/issuer-applications/{application_id}/deny", headers=headers)

    # --- issuers ---
    def list_issuers(self, headers, params=None):
        return self._request("GET", "/issuers", headers=headers, params=params)

    def get_issuer(self, issuer_id, headers):
        return self._request("GET", f"/issuers/{issuer_id}", headers=headers)

    def patch_issuer_financials(self, issuer_id, payload, headers):
        return self._request("PATCH", f"/issuers/{issuer_id}/financials", payload, headers)

    def default_issuer(self, issuer_id, headers):
        return self._request("POST", f"/issuers/{issuer_id}/default", headers=headers)

    # --- document custodians ---
    def create_custodian(self, payload, headers):
        return self._request("POST", "/document-custodians", payload, headers)

    def list_custodians(self, headers, params=None):
        return self._request("GET", "/document-custodians", headers=headers, params=params)

    def get_custodian(self, custodian_id, headers):
        return self._request("GET", f"/document-custodians/{custodian_id}", headers=headers)

    # --- custodian engagements ---
    def create_engagement(self, payload, headers):
        return self._request("POST", "/custodian-engagements", payload, headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", "/custodian-engagements", headers=headers, params=params)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/custodian-engagements/{engagement_id}", headers=headers)

    def end_engagement(self, engagement_id, headers):
        return self._request("POST", f"/custodian-engagements/{engagement_id}/end", headers=headers)

    # --- pools ---
    def create_pool(self, payload, headers):
        return self._request("POST", "/pools", payload, headers)

    def list_pools(self, headers, params=None):
        return self._request("GET", "/pools", headers=headers, params=params)

    def get_pool(self, pool_id, headers):
        return self._request("GET", f"/pools/{pool_id}", headers=headers)

    def assemble_pool(self, pool_id, headers):
        return self._request("POST", f"/pools/{pool_id}/assemble", headers=headers)

    def create_certification(self, pool_id, payload, headers):
        return self._request("POST", f"/pools/{pool_id}/certifications", payload, headers)

    def list_certifications(self, pool_id, headers, params=None):
        return self._request("GET", f"/pools/{pool_id}/certifications", headers=headers, params=params)

    def activate_pool(self, pool_id, headers):
        return self._request("POST", f"/pools/{pool_id}/activate", headers=headers)

    def terminate_pool(self, pool_id, headers):
        return self._request("POST", f"/pools/{pool_id}/terminate", headers=headers)

    # --- loans ---
    def create_loan(self, payload, headers):
        return self._request("POST", "/loans", payload, headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/loans", headers=headers, params=params)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/loans/{loan_id}", headers=headers)

    def set_loan_delinquency_status(self, loan_id, to_status, headers):
        return self._request(
            "POST", f"/loans/{loan_id}/delinquency-status",
            payload={"to_status": to_status}, headers=headers,
        )

    # --- custodial accounts / transactions ---
    def create_custodial_account(self, payload, headers):
        return self._request("POST", "/custodial-accounts", payload, headers)

    def list_custodial_accounts(self, headers, params=None):
        return self._request("GET", "/custodial-accounts", headers=headers, params=params)

    def get_custodial_account(self, account_id, headers):
        return self._request("GET", f"/custodial-accounts/{account_id}", headers=headers)

    def create_account_transaction(self, account_id, payload, headers):
        return self._request("POST", f"/custodial-accounts/{account_id}/transactions", payload, headers)

    def list_account_transactions(self, account_id, headers, params=None):
        return self._request("GET", f"/custodial-accounts/{account_id}/transactions", headers=headers, params=params)

    # --- investor reports ---
    def create_investor_report(self, payload, headers):
        return self._request("POST", "/investor-reports", payload, headers)

    def list_investor_reports(self, headers, params=None):
        return self._request("GET", "/investor-reports", headers=headers, params=params)

    def get_investor_report(self, report_id, headers):
        return self._request("GET", f"/investor-reports/{report_id}", headers=headers)

    def submit_report(self, report_id, headers):
        return self._request("POST", f"/investor-reports/{report_id}/submit", headers=headers)

    def accept_report(self, report_id, headers):
        return self._request("POST", f"/investor-reports/{report_id}/accept", headers=headers)

    def reject_report(self, report_id, headers):
        return self._request("POST", f"/investor-reports/{report_id}/reject", headers=headers)

    # --- pass-through payments ---
    def list_pass_through_payments(self, headers, params=None):
        return self._request("GET", "/pass-through-payments", headers=headers, params=params)

    def get_pass_through_payment(self, payment_id, headers):
        return self._request("GET", f"/pass-through-payments/{payment_id}", headers=headers)

    def settle_payment(self, payment_id, headers):
        return self._request("POST", f"/pass-through-payments/{payment_id}/settle", headers=headers)

    # --- liquidity advances ---
    def list_liquidity_advances(self, headers, params=None):
        return self._request("GET", "/liquidity-advances", headers=headers, params=params)

    def get_liquidity_advance(self, advance_id, headers):
        return self._request("GET", f"/liquidity-advances/{advance_id}", headers=headers)

    def reimburse_advance(self, advance_id, headers):
        return self._request("POST", f"/liquidity-advances/{advance_id}/reimburse", headers=headers)

    # --- delinquency breaches / corrective action plans ---
    def list_delinquency_breaches(self, headers, params=None):
        return self._request("GET", "/delinquency-breaches", headers=headers, params=params)

    def get_delinquency_breach(self, breach_id, headers):
        return self._request("GET", f"/delinquency-breaches/{breach_id}", headers=headers)

    def close_breach(self, breach_id, headers):
        return self._request("POST", f"/delinquency-breaches/{breach_id}/close", headers=headers)

    def create_corrective_action_plan(self, payload, headers):
        return self._request("POST", "/corrective-action-plans", payload, headers)

    def list_corrective_action_plans(self, headers, params=None):
        return self._request("GET", "/corrective-action-plans", headers=headers, params=params)

    def get_corrective_action_plan(self, plan_id, headers):
        return self._request("GET", f"/corrective-action-plans/{plan_id}", headers=headers)

    def accept_plan(self, plan_id, headers):
        return self._request("POST", f"/corrective-action-plans/{plan_id}/accept", headers=headers)

    def reject_plan(self, plan_id, headers):
        return self._request("POST", f"/corrective-action-plans/{plan_id}/reject", headers=headers)

    # --- portfolio transfers ---
    def create_portfolio_transfer(self, payload, headers):
        return self._request("POST", "/portfolio-transfers", payload, headers)

    def list_portfolio_transfers(self, headers, params=None):
        return self._request("GET", "/portfolio-transfers", headers=headers, params=params)

    def get_portfolio_transfer(self, transfer_id, headers):
        return self._request("GET", f"/portfolio-transfers/{transfer_id}", headers=headers)

    def accept_transfer(self, transfer_id, headers):
        return self._request("POST", f"/portfolio-transfers/{transfer_id}/accept", headers=headers)

    def reject_transfer(self, transfer_id, headers):
        return self._request("POST", f"/portfolio-transfers/{transfer_id}/reject", headers=headers)


api_client = ApiClient()
