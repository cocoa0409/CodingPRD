"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- rate filings ---
    def create_rate_filing(self, payload, headers):
        return self._request("POST", "/rate-filings", payload, headers)

    def list_rate_filings(self, headers, params=None):
        return self._request("GET", "/rate-filings", headers=headers, params=params)

    def get_rate_filing(self, filing_id, headers):
        return self._request("GET", f"/rate-filings/{filing_id}", headers=headers)

    def approve_rate_filing(self, filing_id, headers):
        return self._request("POST", f"/rate-filings/{filing_id}/approve", {}, headers)

    def reject_rate_filing(self, filing_id, headers):
        return self._request("POST", f"/rate-filings/{filing_id}/reject", {}, headers)

    # --- fee configs ---
    def create_fee_config(self, payload, headers):
        return self._request("POST", "/fee-configs", payload, headers)

    def list_fee_configs(self, headers, params=None):
        return self._request("GET", "/fee-configs", headers=headers, params=params)

    def get_fee_config(self, fee_config_id, headers):
        return self._request("GET", f"/fee-configs/{fee_config_id}", headers=headers)

    def list_fee_config_policies(self, fee_config_id, headers, params=None):
        return self._request(
            "GET", f"/fee-configs/{fee_config_id}/policies", headers=headers, params=params
        )

    def update_fee_config(self, fee_config_id, payload, headers):
        return self._request("POST", f"/fee-configs/{fee_config_id}/update", payload, headers)

    def activate_fee_config(self, fee_config_id, headers):
        return self._request("POST", f"/fee-configs/{fee_config_id}/activate", {}, headers)

    def retire_fee_config(self, fee_config_id, headers):
        return self._request("POST", f"/fee-configs/{fee_config_id}/retire", {}, headers)

    # --- reinsurance treaties ---
    def create_treaty(self, payload, headers):
        return self._request("POST", "/reinsurance-treaties", payload, headers)

    def list_treaties(self, headers, params=None):
        return self._request("GET", "/reinsurance-treaties", headers=headers, params=params)

    def activate_treaty(self, treaty_id, headers):
        return self._request("POST", f"/reinsurance-treaties/{treaty_id}/activate", {}, headers)

    def retire_treaty(self, treaty_id, headers):
        return self._request("POST", f"/reinsurance-treaties/{treaty_id}/retire", {}, headers)

    # --- causes ---
    def create_cause(self, payload, headers):
        return self._request("POST", "/causes", payload, headers)

    def list_causes(self, headers, params=None):
        return self._request("GET", "/causes", headers=headers, params=params)

    def get_cause(self, cause_id, headers):
        return self._request("GET", f"/causes/{cause_id}", headers=headers)

    def retire_cause(self, cause_id, headers):
        return self._request("POST", f"/causes/{cause_id}/retire", {}, headers)

    # --- cohorts ---
    def create_cohort(self, payload, headers):
        return self._request("POST", "/cohorts", payload, headers)

    def list_cause_cohorts(self, cause_id, headers, params=None):
        return self._request("GET", f"/causes/{cause_id}/cohorts", headers=headers, params=params)

    def list_cause_policies(self, cause_id, headers, params=None):
        return self._request("GET", f"/causes/{cause_id}/policies", headers=headers, params=params)

    def list_cohorts(self, headers, params=None):
        return self._request("GET", "/cohorts", headers=headers, params=params)

    def get_cohort(self, cohort_id, headers):
        return self._request("GET", f"/cohorts/{cohort_id}", headers=headers)

    def attach_cohort_reinsurance(self, cohort_id, payload, headers):
        return self._request("POST", f"/cohorts/{cohort_id}/reinsurance", payload, headers)

    def run_giveback(self, cohort_id, headers):
        return self._request("POST", f"/cohorts/{cohort_id}/run-giveback", {}, headers)

    def close_cohort(self, cohort_id, headers):
        return self._request("POST", f"/cohorts/{cohort_id}/close", {}, headers)

    # --- policyholders ---
    def create_policyholder(self, payload, headers):
        return self._request("POST", "/policyholders", payload, headers)

    def get_policyholder(self, policyholder_id, headers):
        return self._request("GET", f"/policyholders/{policyholder_id}", headers=headers)

    def list_policyholder_applications(self, policyholder_id, headers, params=None):
        return self._request(
            "GET", f"/policyholders/{policyholder_id}/applications", headers=headers, params=params
        )

    def list_policyholder_quotes(self, policyholder_id, headers, params=None):
        return self._request(
            "GET", f"/policyholders/{policyholder_id}/quotes", headers=headers, params=params
        )

    def list_policyholder_policies(self, policyholder_id, headers, params=None):
        return self._request(
            "GET", f"/policyholders/{policyholder_id}/policies", headers=headers, params=params
        )

    # --- quotes ---
    def create_quote(self, payload, headers):
        return self._request("POST", "/quotes", payload, headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def list_quote_policies(self, quote_id, headers, params=None):
        return self._request("GET", f"/quotes/{quote_id}/policies", headers=headers, params=params)

    def bind_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/bind", payload, headers)

    # --- applications ---
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_quote_applications(self, quote_id, headers, params=None):
        return self._request(
            "GET", f"/quotes/{quote_id}/applications", headers=headers, params=params
        )

    def approve_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/approve", {}, headers)

    def decline_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/decline", {}, headers)

    def resubmit_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/resubmit", payload, headers)

    # --- policies ---
    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def list_cohort_policies(self, cohort_id, headers, params=None):
        return self._request("GET", f"/cohorts/{cohort_id}/policies", headers=headers, params=params)

    def elect_cause(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/cause-election", payload, headers)

    def pay_premium(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/premium-payments", payload, headers)

    def cancel_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/cancel", {}, headers)

    def lapse_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/lapse", {}, headers)

    def list_policy_ledger(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/ledger", headers=headers, params=params)

    def list_policy_claims(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/claims", headers=headers, params=params)

    # --- claims ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def list_claim_payments(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/payments", headers=headers, params=params)

    def list_claim_ledger(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/ledger", headers=headers, params=params)

    def approve_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/approve", payload, headers)

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/deny", payload, headers)

    def create_appeal(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/appeals", payload, headers)

    # --- appeals ---
    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def list_claim_appeals(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/appeals", headers=headers, params=params)

    def uphold_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/uphold", payload, headers)

    def overturn_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/overturn", payload, headers)


api_client = ApiClient()
