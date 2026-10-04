"""API client: one method per endpoint declared in the PRD §4 table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # --- Logical clock ---------------------------------------------------
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Member ----------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", "/benefits/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/benefits/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/benefits/members/{member_id}", headers=headers)

    def get_tier_projection(self, member_id, headers):
        return self._request("GET", f"/benefits/members/{member_id}/tier-projection", headers=headers)

    def get_churn_breakdown(self, member_id, headers):
        return self._request("GET", f"/benefits/members/{member_id}/churn-breakdown", headers=headers)

    def get_deposit_rate_projection(self, member_id, headers):
        return self._request("GET", f"/benefits/members/{member_id}/deposit-rate-projection", headers=headers)

    def get_benefit_summary(self, member_id, headers):
        return self._request("GET", f"/benefits/members/{member_id}/benefit-summary", headers=headers)

    def get_rewards_balance(self, member_id, headers):
        return self._request("GET", f"/benefits/members/{member_id}/rewards-balance", headers=headers)

    def post_deposit(self, member_id, payload, headers):
        return self._request("POST", f"/benefits/members/{member_id}/deposits", payload, headers)

    def reverse_deposit(self, member_id, payload, headers):
        return self._request("POST", f"/benefits/members/{member_id}/deposits/reverse", payload, headers)

    def open_requalification_cycle(self, member_id, payload, headers):
        return self._request("POST", f"/benefits/members/{member_id}/requalification-cycles", payload, headers)

    def reinstate_member(self, member_id, headers):
        return self._request("POST", f"/benefits/members/{member_id}/reinstate", {}, headers)

    def reset_member_to_prospect(self, member_id, headers):
        return self._request("POST", f"/benefits/members/{member_id}/reset-to-prospect", {}, headers)

    def detect_churn(self, member_id, headers):
        return self._request("POST", f"/benefits/members/{member_id}/detect-churn", {}, headers)

    def create_entitlement(self, member_id, payload, headers):
        return self._request("POST", f"/benefits/members/{member_id}/entitlements", payload, headers)

    def reconcile_entitlements(self, member_id, headers):
        return self._request("POST", f"/benefits/members/{member_id}/entitlements/reconcile", {}, headers)

    def redeem_principal(self, member_id, payload, headers):
        return self._request("POST", f"/benefits/members/{member_id}/rewards/redeem-principal", payload, headers)

    def reconcile_rewards(self, member_id, headers):
        return self._request("POST", f"/benefits/members/{member_id}/rewards/reconcile", {}, headers)

    def adjust_rewards(self, member_id, payload, headers):
        return self._request("POST", f"/benefits/members/{member_id}/rewards/adjust", payload, headers)

    # --- ProductHolding ---------------------------------------------------
    def create_holding(self, payload, headers):
        return self._request("POST", "/benefits/holdings", payload, headers)

    def list_holdings(self, headers, params=None):
        return self._request("GET", "/benefits/holdings", headers=headers, params=params)

    def get_holding(self, holding_id, headers):
        return self._request("GET", f"/benefits/holdings/{holding_id}", headers=headers)

    def adopt_holding(self, holding_id, headers):
        return self._request("POST", f"/benefits/holdings/{holding_id}/adopt", {}, headers)

    def suspend_holding(self, holding_id, headers):
        return self._request("POST", f"/benefits/holdings/{holding_id}/suspend", {}, headers)

    def close_holding(self, holding_id, headers):
        return self._request("POST", f"/benefits/holdings/{holding_id}/close", {}, headers)

    # --- LoanAccount ------------------------------------------------------
    def create_loan_account(self, payload, headers):
        return self._request("POST", "/benefits/loan-accounts", payload, headers)

    def list_loan_accounts(self, headers, params=None):
        return self._request("GET", "/benefits/loan-accounts", headers=headers, params=params)

    def get_loan_account(self, loan_account_id, headers):
        return self._request("GET", f"/benefits/loan-accounts/{loan_account_id}", headers=headers)

    def enroll_autopay(self, loan_account_id, headers):
        return self._request("POST", f"/benefits/loan-accounts/{loan_account_id}/autopay-enrollment", {}, headers)

    def suspend_autopay(self, loan_account_id, headers):
        return self._request("POST", f"/benefits/loan-accounts/{loan_account_id}/autopay-suspend", {}, headers)

    def finalize_pricing(self, loan_account_id, headers):
        return self._request("POST", f"/benefits/loan-accounts/{loan_account_id}/finalize-pricing", {}, headers)

    def create_application(self, loan_account_id, payload, headers):
        return self._request("POST", f"/benefits/loan-accounts/{loan_account_id}/applications", payload, headers)

    def list_loan_applications(self, loan_account_id, headers, params=None):
        return self._request("GET", f"/benefits/loan-accounts/{loan_account_id}/applications", headers=headers, params=params)

    def get_pricing_breakdown(self, loan_account_id, headers):
        return self._request("GET", f"/benefits/loan-accounts/{loan_account_id}/pricing-breakdown", headers=headers)

    # --- DiscountApplication ---------------------------------------------
    def list_applications(self, headers, params=None):
        return self._request("GET", "/benefits/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/benefits/applications/{application_id}", headers=headers)

    def rollback_application(self, application_id, headers):
        return self._request("POST", f"/benefits/applications/{application_id}/rollback", {}, headers)

    # --- RateDiscountRule -------------------------------------------------
    def list_rules(self, headers, params=None):
        return self._request("GET", "/benefits/rate-discount-rules", headers=headers, params=params)

    def get_rule(self, rule_id, headers):
        return self._request("GET", f"/benefits/rate-discount-rules/{rule_id}", headers=headers)

    def create_rule(self, payload, headers):
        return self._request("POST", "/benefits/rate-discount-rules", payload, headers)

    def update_rule(self, rule_id, payload, headers):
        return self._request("PUT", f"/benefits/rate-discount-rules/{rule_id}", payload, headers)

    def activate_rule(self, rule_id, headers):
        return self._request("POST", f"/benefits/rate-discount-rules/{rule_id}/activate", {}, headers)

    def retire_rule(self, rule_id, headers):
        return self._request("POST", f"/benefits/rate-discount-rules/{rule_id}/retire", {}, headers)

    # --- DirectDepositEnrollment -----------------------------------------
    def create_deposit_enrollment(self, payload, headers):
        return self._request("POST", "/benefits/deposit-enrollments", payload, headers)

    def list_deposit_enrollments(self, headers, params=None):
        return self._request("GET", "/benefits/deposit-enrollments", headers=headers, params=params)

    def get_deposit_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/benefits/deposit-enrollments/{enrollment_id}", headers=headers)

    def activate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/benefits/deposit-enrollments/{enrollment_id}/activate", {}, headers)

    def lapse_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/benefits/deposit-enrollments/{enrollment_id}/lapse", {}, headers)

    # --- BenefitEntitlement ----------------------------------------------
    def list_entitlements(self, headers, params=None):
        return self._request("GET", "/benefits/benefit-entitlements", headers=headers, params=params)

    def get_entitlement(self, entitlement_id, headers):
        return self._request("GET", f"/benefits/benefit-entitlements/{entitlement_id}", headers=headers)

    def step_down_entitlement(self, entitlement_id, headers):
        return self._request("POST", f"/benefits/benefit-entitlements/{entitlement_id}/step-down", {}, headers)

    def restore_entitlement(self, entitlement_id, headers):
        return self._request("POST", f"/benefits/benefit-entitlements/{entitlement_id}/restore", {}, headers)

    def request_override(self, entitlement_id, payload, headers):
        return self._request("POST", f"/benefits/benefit-entitlements/{entitlement_id}/request-override", payload, headers)

    def approve_override(self, entitlement_id, headers):
        return self._request("POST", f"/benefits/benefit-entitlements/{entitlement_id}/approve-override", {}, headers)

    # --- RewardsLedgerEntry ----------------------------------------------
    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/benefits/rewards-ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/benefits/rewards-ledger-entries/{entry_id}", headers=headers)

    def reverse_ledger_entry(self, entry_id, headers):
        return self._request("POST", f"/benefits/rewards-ledger-entries/{entry_id}/reverse", {}, headers)

    # --- RequalificationCycle ---------------------------------------------
    def list_requalification_cycles(self, headers, params=None):
        return self._request("GET", "/benefits/requalification-cycles", headers=headers, params=params)

    def get_requalification_cycle(self, cycle_id, headers):
        return self._request("GET", f"/benefits/requalification-cycles/{cycle_id}", headers=headers)

    def evaluate_cycle(self, cycle_id, headers):
        return self._request("POST", f"/benefits/requalification-cycles/{cycle_id}/evaluate", {}, headers)

    def open_remediation(self, cycle_id, headers):
        return self._request("POST", f"/benefits/requalification-cycles/{cycle_id}/open-remediation", {}, headers)

    def close_cycle(self, cycle_id, headers):
        return self._request("POST", f"/benefits/requalification-cycles/{cycle_id}/close", {}, headers)

    # --- ChurnNotice ------------------------------------------------------
    def list_churn_notices(self, headers, params=None):
        return self._request("GET", "/benefits/churn-notices", headers=headers, params=params)

    def get_churn_notice(self, notice_id, headers):
        return self._request("GET", f"/benefits/churn-notices/{notice_id}", headers=headers)

    def send_churn_notice(self, notice_id, headers):
        return self._request("POST", f"/benefits/churn-notices/{notice_id}/send", {}, headers)

    def acknowledge_churn_notice(self, notice_id, headers):
        return self._request("POST", f"/benefits/churn-notices/{notice_id}/acknowledge", {}, headers)

    # --- CoachingSession --------------------------------------------------
    def list_coaching_sessions(self, headers, params=None):
        return self._request("GET", "/benefits/coaching-sessions", headers=headers, params=params)

    def get_coaching_session(self, session_id, headers):
        return self._request("GET", f"/benefits/coaching-sessions/{session_id}", headers=headers)

    def book_coaching_session(self, payload, headers):
        return self._request("POST", "/benefits/coaching-sessions", payload, headers)

    def confirm_coaching_session(self, session_id, headers):
        return self._request("POST", f"/benefits/coaching-sessions/{session_id}/confirm", {}, headers)

    def complete_coaching_session(self, session_id, headers):
        return self._request("POST", f"/benefits/coaching-sessions/{session_id}/complete", {}, headers)

    def cancel_coaching_session(self, session_id, headers):
        return self._request("POST", f"/benefits/coaching-sessions/{session_id}/cancel", {}, headers)

    # --- CrossSellCheck ---------------------------------------------------
    def list_cross_sell_checks(self, headers, params=None):
        return self._request("GET", "/benefits/cross-sell-checks", headers=headers, params=params)

    def get_cross_sell_check(self, check_id, headers):
        return self._request("GET", f"/benefits/cross-sell-checks/{check_id}", headers=headers)

    def create_cross_sell_check(self, payload, headers):
        return self._request("POST", "/benefits/cross-sell-checks", payload, headers)

    def decide_cross_sell_check(self, check_id, payload, headers):
        return self._request("POST", f"/benefits/cross-sell-checks/{check_id}/decide", payload, headers)


api_client = ApiClient()