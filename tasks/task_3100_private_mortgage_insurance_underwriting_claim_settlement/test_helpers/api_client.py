"""API client: one method per operation the PRD declares."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/mortgage-insurance"


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, current_utc, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    # --- MasterPolicy ---
    def create_master_policy(self, payload, headers):
        return self._request("POST", f"{PREFIX}/master-policies", payload, headers)

    def list_master_policies(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/master-policies", headers=headers, params=params)

    def get_master_policy(self, policy_id, headers):
        return self._request("GET", f"{PREFIX}/master-policies/{policy_id}", headers=headers)

    # --- RateCard ---
    def create_rate_card(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rate-cards", payload, headers)

    def list_rate_cards(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rate-cards", headers=headers, params=params)

    def get_rate_card(self, rate_card_id, headers):
        return self._request("GET", f"{PREFIX}/rate-cards/{rate_card_id}", headers=headers)

    # --- ReinsuranceTreaty ---
    def create_treaty(self, payload, headers):
        return self._request("POST", f"{PREFIX}/reinsurance-treaties", payload, headers)

    def list_treaties(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/reinsurance-treaties", headers=headers, params=params)

    def get_treaty(self, treaty_id, headers):
        return self._request("GET", f"{PREFIX}/reinsurance-treaties/{treaty_id}", headers=headers)

    def cancel_treaty(self, treaty_id, headers):
        return self._request("POST", f"{PREFIX}/reinsurance-treaties/{treaty_id}/cancel", {},
                             headers)

    # --- Servicer ---
    def create_servicer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/servicers", payload, headers)

    def list_servicers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/servicers", headers=headers, params=params)

    def get_servicer(self, servicer_id, headers):
        return self._request("GET", f"{PREFIX}/servicers/{servicer_id}", headers=headers)

    def suspend_servicer(self, servicer_id, headers):
        return self._request("POST", f"{PREFIX}/servicers/{servicer_id}/suspend", {}, headers)

    # --- Lender ---
    def create_lender(self, payload, headers):
        return self._request("POST", f"{PREFIX}/lenders", payload, headers)

    def list_lenders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/lenders", headers=headers, params=params)

    def get_lender(self, lender_id, headers):
        return self._request("GET", f"{PREFIX}/lenders/{lender_id}", headers=headers)

    def reconcile_lender_exposure(self, lender_id, payload, headers):
        return self._request("POST", f"{PREFIX}/lenders/{lender_id}/exposure-reconciliations",
                             payload, headers)

    # --- CoverageApplication ---
    def create_application(self, payload, headers):
        return self._request("POST", f"{PREFIX}/coverage-applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/coverage-applications", headers=headers,
                             params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"{PREFIX}/coverage-applications/{application_id}",
                             headers=headers)

    def underwrite_application(self, application_id, headers):
        return self._request("POST", f"{PREFIX}/coverage-applications/{application_id}/underwrite",
                             {}, headers)

    def delegated_approve_application(self, application_id, headers):
        return self._request("POST",
                             f"{PREFIX}/coverage-applications/{application_id}/delegated-approve",
                             {}, headers)

    def request_application_info(self, application_id, payload, headers):
        return self._request("POST",
                             f"{PREFIX}/coverage-applications/{application_id}/request-info",
                             payload, headers)

    def submit_application_info(self, application_id, payload, headers):
        return self._request("POST",
                             f"{PREFIX}/coverage-applications/{application_id}/submit-info",
                             payload, headers)

    def approve_application(self, application_id, headers):
        return self._request("POST", f"{PREFIX}/coverage-applications/{application_id}/approve",
                             {}, headers)

    def decline_application(self, application_id, payload, headers):
        return self._request("POST", f"{PREFIX}/coverage-applications/{application_id}/decline",
                             payload, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"{PREFIX}/coverage-applications/{application_id}/withdraw",
                             {}, headers)

    # --- Loan ---
    def create_loan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/loans", payload, headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/loans", headers=headers, params=params)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"{PREFIX}/loans/{loan_id}", headers=headers)

    def record_amortization_milestone(self, loan_id, payload, headers):
        return self._request("POST", f"{PREFIX}/loans/{loan_id}/amortization-milestones",
                             payload, headers)

    def record_rescission_relief(self, loan_id, payload, headers):
        return self._request("POST", f"{PREFIX}/loans/{loan_id}/rescission-relief",
                             payload, headers)

    def create_cancellation_notice(self, loan_id, payload, headers):
        return self._request("POST", f"{PREFIX}/loans/{loan_id}/cancellation-notices",
                             payload, headers)

    def list_cancellation_notices(self, loan_id, headers):
        return self._request("GET", f"{PREFIX}/loans/{loan_id}/cancellation-notices",
                             headers=headers)

    def list_loan_delinquency_reports(self, loan_id, headers):
        return self._request("GET", f"{PREFIX}/loans/{loan_id}/delinquency-reports",
                             headers=headers)

    def list_loan_claims(self, loan_id, headers):
        return self._request("GET", f"{PREFIX}/loans/{loan_id}/claims", headers=headers)

    def list_loan_external_reports(self, loan_id, headers):
        return self._request("GET", f"{PREFIX}/loans/{loan_id}/external-reports", headers=headers)

    def list_loan_coverage_disputes(self, loan_id, headers):
        return self._request("GET", f"{PREFIX}/loans/{loan_id}/coverage-disputes", headers=headers)

    # --- ExternalReport ---
    def create_external_report(self, loan_id, payload, headers):
        return self._request("POST", f"{PREFIX}/loans/{loan_id}/external-reports", payload,
                             headers)

    def get_external_report(self, report_id, headers):
        return self._request("GET", f"{PREFIX}/external-reports/{report_id}", headers=headers)

    # --- DelinquencyReport ---
    def create_delinquency_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/delinquency-reports", payload, headers)

    def list_delinquency_reports(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/delinquency-reports", headers=headers,
                             params=params)

    def get_delinquency_report(self, report_id, headers):
        return self._request("GET", f"{PREFIX}/delinquency-reports/{report_id}", headers=headers)

    # --- Claim ---
    def create_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/claims/{claim_id}", headers=headers)

    def begin_claim_review(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/begin-review", {}, headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/approve", {}, headers)

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/deny", payload, headers)

    def reconsider_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/reconsideration", payload,
                             headers)

    def settle_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/settle", payload, headers)

    def list_settlement_options(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/claims/{claim_id}/settlement-options",
                             headers=headers)

    # --- CurtailmentDispute ---
    def create_dispute(self, payload, headers):
        return self._request("POST", f"{PREFIX}/coverage-disputes", payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/coverage-disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"{PREFIX}/coverage-disputes/{dispute_id}", headers=headers)

    def begin_dispute_review(self, dispute_id, headers):
        return self._request("POST", f"{PREFIX}/coverage-disputes/{dispute_id}/begin-review", {},
                             headers)

    def decide_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"{PREFIX}/coverage-disputes/{dispute_id}/decide", payload,
                             headers)

    # --- ReinsuranceCession ---
    def create_cession(self, payload, headers):
        return self._request("POST", f"{PREFIX}/reinsurance-cessions", payload, headers)

    def list_cessions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/reinsurance-cessions", headers=headers, params=params)

    def get_cession(self, cession_id, headers):
        return self._request("GET", f"{PREFIX}/reinsurance-cessions/{cession_id}", headers=headers)

    # --- PortfolioSnapshot ---
    def create_snapshot(self, payload, headers):
        return self._request("POST", f"{PREFIX}/portfolio-snapshots", payload, headers)

    def list_snapshots(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/portfolio-snapshots", headers=headers, params=params)

    def get_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"{PREFIX}/portfolio-snapshots/{snapshot_id}", headers=headers)


api_client = ApiClient()