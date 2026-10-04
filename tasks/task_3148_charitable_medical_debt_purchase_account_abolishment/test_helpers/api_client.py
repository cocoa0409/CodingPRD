"""Typed HTTP client for the charitable medical debt abolishment API.

One method per endpoint named in the PRD endpoint table (§4). The base
``_request`` ships GET query params for GET/DELETE and JSON bodies for
writes; list endpoints therefore pass their filters as ``payload``.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving logical clock ---
    def set_clock(self, to_iso8601: str, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- source organizations ---
    def create_source_organization(self, payload, headers):
        return self._request("POST", "/api/source-organizations", payload, headers)

    def get_source_organization(self, org_id, headers):
        return self._request(
            "GET", f"/api/source-organizations/{org_id}", headers=headers
        )

    def list_source_organizations(self, headers, params=None):
        return self._request("GET", "/api/source-organizations", params, headers)

    def suspend_source_organization(self, org_id, headers):
        return self._request(
            "POST", f"/api/source-organizations/{org_id}/suspend", {}, headers
        )

    def reactivate_source_organization(self, org_id, headers):
        return self._request(
            "POST", f"/api/source-organizations/{org_id}/reactivate", {}, headers
        )

    # --- eligibility policies ---
    def create_eligibility_policy(self, payload, headers):
        return self._request("POST", "/api/eligibility-policies", payload, headers)

    def get_eligibility_policy(self, policy_id, headers):
        return self._request(
            "GET", f"/api/eligibility-policies/{policy_id}", headers=headers
        )

    def list_eligibility_policies(self, headers, params=None):
        return self._request("GET", "/api/eligibility-policies", params, headers)

    def activate_eligibility_policy(self, policy_id, headers):
        return self._request(
            "POST", f"/api/eligibility-policies/{policy_id}/activate", {}, headers
        )

    def retire_eligibility_policy(self, policy_id, headers):
        return self._request(
            "POST", f"/api/eligibility-policies/{policy_id}/retire", {}, headers
        )

    # --- portfolios ---
    def create_portfolio(self, payload, headers):
        return self._request("POST", "/api/portfolios", payload, headers)

    def get_portfolio(self, portfolio_id, headers):
        return self._request("GET", f"/api/portfolios/{portfolio_id}", headers=headers)

    def list_portfolios(self, headers, params=None):
        return self._request("GET", "/api/portfolios", params, headers)

    def submit_portfolio(self, portfolio_id, headers):
        return self._request(
            "POST", f"/api/portfolios/{portfolio_id}/submit", {}, headers
        )

    def cancel_portfolio(self, portfolio_id, headers):
        return self._request(
            "POST", f"/api/portfolios/{portfolio_id}/cancel", {}, headers
        )

    def price_quote_portfolio(self, portfolio_id, headers):
        return self._request(
            "POST", f"/api/portfolios/{portfolio_id}/price-quote", {}, headers
        )

    def import_accounts(self, portfolio_id, accounts, headers):
        return self._request(
            "POST",
            f"/api/portfolios/{portfolio_id}/accounts",
            {"accounts": accounts},
            headers,
        )

    # --- accounts ---
    def get_account(self, account_id, headers):
        return self._request("GET", f"/api/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/api/accounts", params, headers)

    def review_account(self, account_id, decision, headers):
        return self._request(
            "POST",
            f"/api/accounts/{account_id}/review",
            {"decision": decision},
            headers,
        )

    # --- screening runs ---
    def create_screening_run(self, portfolio_id, policy_id, headers):
        return self._request(
            "POST",
            f"/api/portfolios/{portfolio_id}/screening-runs",
            {"policy_id": policy_id},
            headers,
        )

    def get_screening_run(self, run_id, headers):
        return self._request("GET", f"/api/screening-runs/{run_id}", headers=headers)

    def list_screening_runs(self, headers, params=None):
        return self._request("GET", "/api/screening-runs", params, headers)

    def execute_screening_run(self, run_id, headers):
        return self._request(
            "POST", f"/api/screening-runs/{run_id}/execute", {}, headers
        )

    # --- purchase contracts ---
    def create_contract(self, portfolio_id, payload, headers):
        return self._request(
            "POST", f"/api/portfolios/{portfolio_id}/contracts", payload, headers
        )

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/api/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/api/contracts", params, headers)

    def execute_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/api/contracts/{contract_id}/execute", {}, headers
        )

    def settle_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/api/contracts/{contract_id}/settle", {}, headers
        )

    def terminate_contract(self, contract_id, reason, headers):
        return self._request(
            "POST",
            f"/api/contracts/{contract_id}/terminate",
            {"reason": reason},
            headers,
        )

    # --- donor campaigns / donations ---
    def create_donor_campaign(self, payload, headers):
        return self._request("POST", "/api/donor-campaigns", payload, headers)

    def get_donor_campaign(self, campaign_id, headers):
        return self._request(
            "GET", f"/api/donor-campaigns/{campaign_id}", headers=headers
        )

    def list_donor_campaigns(self, headers, params=None):
        return self._request("GET", "/api/donor-campaigns", params, headers)

    def close_donor_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"/api/donor-campaigns/{campaign_id}/close", {}, headers
        )

    def create_donation(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"/api/donor-campaigns/{campaign_id}/donations", payload, headers
        )

    def get_donation(self, donation_id, headers):
        return self._request("GET", f"/api/donations/{donation_id}", headers=headers)

    def list_donations(self, headers, params=None):
        return self._request("GET", "/api/donations", params, headers)

    def receive_donation(self, donation_id, headers):
        return self._request(
            "POST", f"/api/donations/{donation_id}/receive", {}, headers
        )

    def refund_donation(self, donation_id, headers):
        return self._request(
            "POST", f"/api/donations/{donation_id}/refund", {}, headers
        )

    # --- abolishment batches ---
    def create_abolishment_batch(self, portfolio_id, payload, headers):
        return self._request(
            "POST",
            f"/api/portfolios/{portfolio_id}/abolishment-batches",
            payload,
            headers,
        )

    def get_abolishment_batch(self, batch_id, headers):
        return self._request(
            "GET", f"/api/abolishment-batches/{batch_id}", headers=headers
        )

    def list_abolishment_batches(self, headers, params=None):
        return self._request("GET", "/api/abolishment-batches", params, headers)

    def commit_abolishment_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/api/abolishment-batches/{batch_id}/commit", {}, headers
        )

    def uncommit_abolishment_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/api/abolishment-batches/{batch_id}/uncommit", {}, headers
        )

    def finalize_abolishment_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/api/abolishment-batches/{batch_id}/finalize", {}, headers
        )

    def reverse_abolishment_batch(self, batch_id, reason, headers):
        return self._request(
            "POST",
            f"/api/abolishment-batches/{batch_id}/reverse",
            {"reason": reason},
            headers,
        )

    # --- notification letters ---
    def get_notification_letter(self, letter_id, headers):
        return self._request(
            "GET", f"/api/notification-letters/{letter_id}", headers=headers
        )

    def list_notification_letters(self, headers, params=None):
        return self._request("GET", "/api/notification-letters", params, headers)

    def send_notification_letter(self, letter_id, headers):
        return self._request(
            "POST", f"/api/notification-letters/{letter_id}/send", {}, headers
        )

    def mark_notification_letter_bounced(self, letter_id, headers):
        return self._request(
            "POST", f"/api/notification-letters/{letter_id}/mark-bounced", {}, headers
        )

    def requeue_notification_letter(self, letter_id, headers, corrected_address=None):
        payload = {}
        if corrected_address is not None:
            payload["corrected_address"] = corrected_address
        return self._request(
            "POST",
            f"/api/notification-letters/{letter_id}/requeue",
            payload,
            headers,
        )

    def mark_notification_letter_delivered(self, letter_id, headers):
        return self._request(
            "POST",
            f"/api/notification-letters/{letter_id}/mark-delivered",
            {},
            headers,
        )

    # --- credit deletion requests ---
    def create_credit_deletion_request(self, account_id, bureau, headers):
        return self._request(
            "POST",
            f"/api/accounts/{account_id}/credit-deletion-requests",
            {"bureau": bureau},
            headers,
        )

    def get_credit_deletion_request(self, cdr_id, headers):
        return self._request(
            "GET", f"/api/credit-deletion-requests/{cdr_id}", headers=headers
        )

    def list_credit_deletion_requests(self, headers, params=None):
        return self._request("GET", "/api/credit-deletion-requests", params, headers)

    def submit_credit_deletion_request(self, cdr_id, headers):
        return self._request(
            "POST", f"/api/credit-deletion-requests/{cdr_id}/submit", {}, headers
        )

    def acknowledge_credit_deletion_request(self, cdr_id, headers):
        return self._request(
            "POST", f"/api/credit-deletion-requests/{cdr_id}/acknowledge", {}, headers
        )

    def reject_credit_deletion_request(self, cdr_id, rejection_reason, headers):
        return self._request(
            "POST",
            f"/api/credit-deletion-requests/{cdr_id}/reject",
            {"rejection_reason": rejection_reason},
            headers,
        )

    def resubmit_credit_deletion_request(self, cdr_id, headers):
        return self._request(
            "POST", f"/api/credit-deletion-requests/{cdr_id}/resubmit", {}, headers
        )

    # --- tax relief records ---
    def get_tax_relief_record(self, record_id, headers):
        return self._request(
            "GET", f"/api/tax-relief-records/{record_id}", headers=headers
        )

    def list_tax_relief_records(self, headers, params=None):
        return self._request("GET", "/api/tax-relief-records", params, headers)

    def assess_tax_relief_record(self, record_id, insolvency_exclusion_cents, headers):
        return self._request(
            "POST",
            f"/api/tax-relief-records/{record_id}/assess",
            {"insolvency_exclusion_cents": insolvency_exclusion_cents},
            headers,
        )

    def file_tax_relief_record(self, record_id, headers):
        return self._request(
            "POST", f"/api/tax-relief-records/{record_id}/file", {}, headers
        )

    # --- hospital partnerships / milestones ---
    def create_hospital_partnership(self, payload, headers):
        return self._request("POST", "/api/hospital-partnerships", payload, headers)

    def get_hospital_partnership(self, partnership_id, headers):
        return self._request(
            "GET", f"/api/hospital-partnerships/{partnership_id}", headers=headers
        )

    def list_hospital_partnerships(self, headers, params=None):
        return self._request("GET", "/api/hospital-partnerships", params, headers)

    def activate_hospital_partnership(self, partnership_id, headers):
        return self._request(
            "POST",
            f"/api/hospital-partnerships/{partnership_id}/activate",
            {},
            headers,
        )

    def suspend_hospital_partnership(self, partnership_id, headers):
        return self._request(
            "POST",
            f"/api/hospital-partnerships/{partnership_id}/suspend",
            {},
            headers,
        )

    def resume_hospital_partnership(self, partnership_id, headers):
        return self._request(
            "POST",
            f"/api/hospital-partnerships/{partnership_id}/resume",
            {},
            headers,
        )

    def complete_hospital_partnership(self, partnership_id, headers):
        return self._request(
            "POST",
            f"/api/hospital-partnerships/{partnership_id}/complete",
            {},
            headers,
        )

    def create_partnership_milestone(self, partnership_id, payload, headers):
        return self._request(
            "POST",
            f"/api/hospital-partnerships/{partnership_id}/milestones",
            payload,
            headers,
        )

    def get_partnership_milestone(self, milestone_id, headers):
        return self._request(
            "GET", f"/api/partnership-milestones/{milestone_id}", headers=headers
        )

    def list_partnership_milestones(self, headers, params=None):
        return self._request("GET", "/api/partnership-milestones", params, headers)

    def mark_milestone_met(self, milestone_id, headers):
        return self._request(
            "POST", f"/api/partnership-milestones/{milestone_id}/mark-met", {}, headers
        )

    def mark_milestone_missed(self, milestone_id, headers):
        return self._request(
            "POST",
            f"/api/partnership-milestones/{milestone_id}/mark-missed",
            {},
            headers,
        )

    def waive_milestone(self, milestone_id, headers):
        return self._request(
            "POST", f"/api/partnership-milestones/{milestone_id}/waive", {}, headers
        )

    # --- impact reports ---
    def create_impact_report(self, payload, headers):
        return self._request("POST", "/api/impact-reports", payload, headers)

    def get_impact_report(self, report_id, headers):
        return self._request("GET", f"/api/impact-reports/{report_id}", headers=headers)

    def list_impact_reports(self, headers, params=None):
        return self._request("GET", "/api/impact-reports", params, headers)

    def publish_impact_report(self, report_id, headers):
        return self._request(
            "POST", f"/api/impact-reports/{report_id}/publish", {}, headers
        )


api_client = ApiClient()
