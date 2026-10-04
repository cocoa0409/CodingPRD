"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Brands ---
    def create_brand(self, payload, headers):
        return self._request("POST", "/franchise/brands", payload, headers)

    def list_brands(self, headers, params=None):
        return self._request("GET", "/franchise/brands", headers=headers, params=params)

    def get_brand(self, brand_id, headers):
        return self._request("GET", f"/franchise/brands/{brand_id}", headers=headers)

    def get_brand_ad_fund_balance(self, brand_id, headers):
        return self._request("GET", f"/franchise/brands/{brand_id}/ad-fund-balance", headers=headers)

    def list_brand_ad_fund_ledger(self, brand_id, headers, params=None):
        return self._request("GET", f"/franchise/brands/{brand_id}/ad-fund-ledger", headers=headers, params=params)

    def list_brand_advisory_councils(self, brand_id, headers, params=None):
        return self._request("GET", f"/franchise/brands/{brand_id}/advisory-councils", headers=headers, params=params)

    # --- Markets ---
    def create_market(self, payload, headers):
        return self._request("POST", "/franchise/markets", payload, headers)

    def list_markets(self, headers, params=None):
        return self._request("GET", "/franchise/markets", headers=headers, params=params)

    # --- Brokerages ---
    def create_brokerage(self, payload, headers):
        return self._request("POST", "/franchise/brokerages", payload, headers)

    def list_brokerages(self, headers, params=None):
        return self._request("GET", "/franchise/brokerages", headers=headers, params=params)

    def get_brokerage(self, brokerage_id, headers):
        return self._request("GET", f"/franchise/brokerages/{brokerage_id}", headers=headers)

    def list_brokerage_agreements(self, brokerage_id, headers, params=None):
        return self._request("GET", f"/franchise/brokerages/{brokerage_id}/agreements", headers=headers, params=params)

    # --- Agents ---
    def create_agent(self, brokerage_id, payload, headers):
        return self._request("POST", f"/franchise/brokerages/{brokerage_id}/agents", payload, headers)

    def list_agents(self, brokerage_id, headers, params=None):
        return self._request("GET", f"/franchise/brokerages/{brokerage_id}/agents", headers=headers, params=params)

    def deactivate_agent(self, agent_id, headers):
        return self._request("POST", f"/franchise/agents/{agent_id}/deactivate", {}, headers)

    def reactivate_agent(self, agent_id, headers):
        return self._request("POST", f"/franchise/agents/{agent_id}/reactivate", {}, headers)

    # --- Agreements ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/franchise/agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/franchise/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/franchise/agreements/{agreement_id}", headers=headers)

    def amend_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/franchise/agreements/{agreement_id}/amend", payload, headers)

    def activate_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/franchise/agreements/{agreement_id}/activate", payload, headers)

    def suspend_agreement(self, agreement_id, headers):
        return self._request("POST", f"/franchise/agreements/{agreement_id}/suspend", {}, headers)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/franchise/agreements/{agreement_id}/terminate", {}, headers)

    # --- Conversion plans ---
    def create_conversion_plan(self, agreement_id, payload, headers):
        return self._request("POST", f"/franchise/agreements/{agreement_id}/conversion-plans", payload, headers)

    def list_conversion_plans(self, agreement_id, headers, params=None):
        return self._request("GET", f"/franchise/agreements/{agreement_id}/conversion-plans", headers=headers, params=params)

    def complete_milestone(self, plan_id, payload, headers):
        return self._request("POST", f"/franchise/conversion-plans/{plan_id}/milestones/complete", payload, headers)

    # --- Reports ---
    def create_agent_count_report(self, agreement_id, payload, headers):
        return self._request("POST", f"/franchise/agreements/{agreement_id}/agent-count-reports", payload, headers)

    def list_agent_count_reports(self, agreement_id, headers, params=None):
        return self._request("GET", f"/franchise/agreements/{agreement_id}/agent-count-reports", headers=headers, params=params)

    def create_gci_report(self, agreement_id, payload, headers):
        return self._request("POST", f"/franchise/agreements/{agreement_id}/gci-reports", payload, headers)

    def list_gci_reports(self, agreement_id, headers, params=None):
        return self._request("GET", f"/franchise/agreements/{agreement_id}/gci-reports", headers=headers, params=params)

    # --- Royalty periods ---
    def assess_royalty_period(self, agreement_id, payload, headers):
        return self._request("POST", f"/franchise/agreements/{agreement_id}/royalty-periods", payload, headers)

    def list_royalty_periods(self, agreement_id, headers, params=None):
        return self._request("GET", f"/franchise/agreements/{agreement_id}/royalty-periods", headers=headers, params=params)

    def get_royalty_period(self, period_id, headers):
        return self._request("GET", f"/franchise/royalty-periods/{period_id}", headers=headers)

    def settle_royalty_period(self, period_id, headers):
        return self._request("POST", f"/franchise/royalty-periods/{period_id}/settle", {}, headers)

    def waive_royalty_period(self, period_id, headers):
        return self._request("POST", f"/franchise/royalty-periods/{period_id}/waive", {}, headers)

    def list_agreement_ad_fund_ledger(self, agreement_id, headers, params=None):
        return self._request("GET", f"/franchise/agreements/{agreement_id}/ad-fund-ledger", headers=headers, params=params)

    def list_period_ad_fund_ledger(self, period_id, headers, params=None):
        return self._request("GET", f"/franchise/royalty-periods/{period_id}/ad-fund-ledger", headers=headers, params=params)

    # --- Default cases ---
    def create_default_case(self, agreement_id, payload, headers):
        return self._request("POST", f"/franchise/agreements/{agreement_id}/default-cases", payload, headers)

    def list_default_cases(self, agreement_id, headers, params=None):
        return self._request("GET", f"/franchise/agreements/{agreement_id}/default-cases", headers=headers, params=params)

    def start_cure_default_case(self, case_id, headers):
        return self._request("POST", f"/franchise/default-cases/{case_id}/start-cure", {}, headers)

    def escalate_default_case(self, case_id, headers):
        return self._request("POST", f"/franchise/default-cases/{case_id}/escalate", {}, headers)

    def resolve_default_case(self, case_id, headers):
        return self._request("POST", f"/franchise/default-cases/{case_id}/resolve", {}, headers)

    # --- Advisory councils ---
    def create_advisory_council(self, payload, headers):
        return self._request("POST", "/franchise/advisory-councils", payload, headers)

    def list_advisory_councils(self, headers, params=None):
        return self._request("GET", "/franchise/advisory-councils", headers=headers, params=params)

    def replace_council_member(self, council_id, payload, headers):
        return self._request("POST", f"/franchise/advisory-councils/{council_id}/replace-member", payload, headers)

    # --- Ad fund spend proposals ---
    def create_ad_fund_proposal(self, payload, headers):
        return self._request("POST", "/franchise/ad-fund-proposals", payload, headers)

    def list_ad_fund_proposals(self, headers, params=None):
        return self._request("GET", "/franchise/ad-fund-proposals", headers=headers, params=params)

    def get_ad_fund_proposal(self, proposal_id, headers):
        return self._request("GET", f"/franchise/ad-fund-proposals/{proposal_id}", headers=headers)

    def submit_ad_fund_proposal(self, proposal_id, headers):
        return self._request("POST", f"/franchise/ad-fund-proposals/{proposal_id}/submit", {}, headers)

    def cast_vote(self, proposal_id, payload, headers):
        return self._request("POST", f"/franchise/ad-fund-proposals/{proposal_id}/votes", payload, headers)

    def execute_ad_fund_proposal(self, proposal_id, headers):
        return self._request("POST", f"/franchise/ad-fund-proposals/{proposal_id}/execute", {}, headers)

    # --- Compliance audits ---
    def create_compliance_audit(self, agreement_id, payload, headers):
        return self._request("POST", f"/franchise/agreements/{agreement_id}/compliance-audits", payload, headers)

    def list_compliance_audits(self, agreement_id, headers, params=None):
        return self._request("GET", f"/franchise/agreements/{agreement_id}/compliance-audits", headers=headers, params=params)

    def start_compliance_audit(self, audit_id, headers):
        return self._request("POST", f"/franchise/compliance-audits/{audit_id}/start", {}, headers)

    def complete_compliance_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/franchise/compliance-audits/{audit_id}/complete", payload, headers)

    def cancel_compliance_audit(self, audit_id, headers):
        return self._request("POST", f"/franchise/compliance-audits/{audit_id}/cancel", {}, headers)

    # --- De-identification tasks ---
    def list_deidentification_tasks(self, agreement_id, headers, params=None):
        return self._request("GET", f"/franchise/agreements/{agreement_id}/deidentification-tasks", headers=headers, params=params)

    def complete_deidentification_task(self, task_id, headers):
        return self._request("POST", f"/franchise/deidentification-tasks/{task_id}/complete", {}, headers)

    def verify_deidentification_task(self, task_id, headers):
        return self._request("POST", f"/franchise/deidentification-tasks/{task_id}/verify", {}, headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/franchise/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
