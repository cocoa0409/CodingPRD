"""API client: one method per operation defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Logical clock ────────────────────────────────
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    # ─── Branches ─────────────────────────────────────
    def create_branch(self, payload, headers):
        return self._request("POST", "/branches", payload, headers)

    def list_branches(self, headers, params=None):
        return self._request("GET", "/branches", headers=headers, params=params)

    def get_branch(self, branch_id, headers):
        return self._request("GET", f"/branches/{branch_id}", headers=headers)

    def patch_branch(self, branch_id, payload, headers):
        return self._request("PATCH", f"/branches/{branch_id}", payload, headers)

    def list_branch_advisor_links(self, branch_id, headers):
        return self._request("GET", f"/branches/{branch_id}/advisor-links",
                             headers=headers)

    def list_branch_payout_periods(self, branch_id, headers):
        return self._request("GET", f"/branches/{branch_id}/payout-periods",
                             headers=headers)

    def list_branch_supervisor_enrollments(self, branch_id, headers):
        return self._request("GET", f"/branches/{branch_id}/supervisor-enrollments",
                             headers=headers)

    # ─── Supervisory enrollments ──────────────────────
    def create_supervisor_enrollment(self, payload, headers):
        return self._request("POST", "/branch-supervisor-enrollments", payload, headers)

    def set_supervisor_enrollment_state(self, enrollment_id, payload, headers):
        return self._request("POST",
                             f"/branch-supervisor-enrollments/{enrollment_id}/state",
                             payload, headers)

    # ─── Advisor links ────────────────────────────────
    def list_advisor_links(self, headers, params=None):
        return self._request("GET", "/advisor-links", headers=headers, params=params)

    def get_advisor_link(self, link_id, headers):
        return self._request("GET", f"/advisor-links/{link_id}", headers=headers)

    def create_advisor_link(self, payload, headers):
        return self._request("POST", "/advisor-links", payload, headers)

    def set_advisor_link_state(self, link_id, payload, headers):
        return self._request("POST", f"/advisor-links/{link_id}/state", payload, headers)

    # ─── Advisors ─────────────────────────────────────
    def create_advisor(self, payload, headers):
        return self._request("POST", "/advisors", payload, headers)

    def list_advisors(self, headers, params=None):
        return self._request("GET", "/advisors", headers=headers, params=params)

    def get_advisor(self, advisor_id, headers):
        return self._request("GET", f"/advisors/{advisor_id}", headers=headers)

    def patch_advisor(self, advisor_id, payload, headers):
        return self._request("PATCH", f"/advisors/{advisor_id}", payload, headers)

    def enroll_advisor(self, advisor_id, payload, headers):
        return self._request("POST", f"/advisors/{advisor_id}/enrollment", payload, headers)

    def affiliate_advisor(self, advisor_id, payload, headers):
        return self._request("POST", f"/advisors/{advisor_id}/affiliation", payload, headers)

    def set_advisor_state(self, advisor_id, payload, headers):
        return self._request("POST", f"/advisors/{advisor_id}/state", payload, headers)

    def start_departure(self, advisor_id, payload, headers):
        return self._request("POST", f"/advisors/{advisor_id}/departure", payload, headers)

    def settle_departure(self, advisor_id, payload, headers):
        return self._request("POST", f"/advisors/{advisor_id}/departure/settle",
                             payload, headers)

    def reinstate_departure(self, advisor_id, payload, headers):
        return self._request("POST", f"/advisors/{advisor_id}/departure/reinstate",
                             payload, headers)

    def open_payout_line(self, advisor_id, payload, headers):
        return self._request("POST", f"/advisors/{advisor_id}/payout-lines",
                             payload, headers)

    def change_crd(self, advisor_id, payload, headers):
        return self._request("POST", f"/advisors/{advisor_id}/crd-change",
                             payload, headers)

    def bulk_import_advisors(self, payload, headers):
        return self._request("POST", "/advisors/bulk-import", payload, headers)

    def start_book_transfer(self, advisor_id, payload, headers):
        return self._request("POST", f"/advisors/{advisor_id}/book-transfer",
                             payload, headers)

    # ─── Accounts ─────────────────────────────────────
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_account_advisory_splits(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}/advisory-splits",
                             headers=headers)

    def list_account_revenue_entries(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}/revenue-entries",
                             headers=headers)

    def confirm_transfer(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/transfer/confirm",
                             headers=headers)

    # ─── Revenue entries ──────────────────────────────
    def create_revenue_entry(self, payload, headers):
        return self._request("POST", "/revenue-entries", payload, headers)

    def list_revenue_entries(self, headers, params=None):
        return self._request("GET", "/revenue-entries", headers=headers, params=params)

    def get_revenue_entry(self, entry_id, headers):
        return self._request("GET", f"/revenue-entries/{entry_id}", headers=headers)

    def release_revenue_entry(self, entry_id, headers):
        return self._request("POST", f"/revenue-entries/{entry_id}/release",
                             headers=headers)

    # ─── Payout periods ───────────────────────────────
    def create_payout_period(self, payload, headers):
        return self._request("POST", "/payout-periods", payload, headers)

    def list_payout_periods(self, headers, params=None):
        return self._request("GET", "/payout-periods", headers=headers, params=params)

    def get_payout_period(self, period_id, headers):
        return self._request("GET", f"/payout-periods/{period_id}", headers=headers)

    def set_payout_period_state(self, period_id, payload, headers):
        return self._request("POST", f"/payout-periods/{period_id}/state",
                             payload, headers)

    def true_up_period(self, period_id, payload, headers):
        return self._request("POST", f"/payout-periods/{period_id}/true-up",
                             payload, headers)

    def net_settlement(self, period_id, payload, headers):
        return self._request("POST", f"/payout-periods/{period_id}/net-settlement",
                             payload, headers)

    def list_period_payout_lines(self, period_id, headers):
        return self._request("GET", f"/payout-periods/{period_id}/payout-lines",
                             headers=headers)

    def list_period_expense_pass_throughs(self, period_id, headers):
        return self._request("GET",
                             f"/payout-periods/{period_id}/expense-pass-throughs",
                             headers=headers)

    # ─── Advisor payout lines ─────────────────────────
    def list_payout_lines(self, headers, params=None):
        return self._request("GET", "/advisor-payout-lines", headers=headers,
                             params=params)

    def get_payout_line(self, line_id, headers):
        return self._request("GET", f"/advisor-payout-lines/{line_id}", headers=headers)

    def settle_payout_line(self, line_id, payload, headers):
        return self._request("POST", f"/advisor-payout-lines/{line_id}/settlement",
                             payload, headers)

    # ─── Payout loans ─────────────────────────────────
    def create_payout_loan(self, payload, headers):
        return self._request("POST", "/payout-loans", payload, headers)

    def list_payout_loans(self, headers, params=None):
        return self._request("GET", "/payout-loans", headers=headers, params=params)

    def get_payout_loan(self, loan_id, headers):
        return self._request("GET", f"/payout-loans/{loan_id}", headers=headers)

    def list_loan_amortization_entries(self, loan_id, headers):
        return self._request("GET", f"/payout-loans/{loan_id}/amortization-entries",
                             headers=headers)

    def loan_forgiveness_audit(self, loan_id, headers):
        return self._request("GET", f"/payout-loans/{loan_id}/forgiveness-audit",
                             headers=headers)

    def loan_amortization_schedule(self, loan_id, headers):
        return self._request("GET", f"/payout-loans/{loan_id}/amortization-schedule",
                             headers=headers)

    def amortize_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/payout-loans/{loan_id}/amortize",
                             payload, headers)

    def forgive_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/payout-loans/{loan_id}/forgive",
                             payload, headers)

    def list_all_amortization_entries(self, headers, params=None):
        return self._request("GET", "/loan-amortization-entries", headers=headers,
                             params=params)

    def get_amortization_entry(self, entry_id, headers):
        return self._request("GET", f"/loan-amortization-entries/{entry_id}",
                             headers=headers)

    # ─── Expense pass-throughs ────────────────────────
    def create_expense_pass_through(self, payload, headers):
        return self._request("POST", "/expense-pass-throughs", payload, headers)

    def list_expense_pass_throughs(self, headers, params=None):
        return self._request("GET", "/expense-pass-throughs", headers=headers,
                             params=params)

    def get_expense_pass_through(self, row_id, headers):
        return self._request("GET", f"/expense-pass-throughs/{row_id}", headers=headers)

    def set_expense_pass_through_state(self, row_id, payload, headers):
        return self._request("POST", f"/expense-pass-throughs/{row_id}/state",
                             payload, headers)

    # ─── Advisory splits ──────────────────────────────
    def levelize_advisory_splits(self, payload, headers):
        return self._request("POST", "/advisory-splits/levelize", payload, headers)

    def list_advisory_splits(self, headers, params=None):
        return self._request("GET", "/advisory-splits", headers=headers, params=params)

    def get_advisory_split(self, split_id, headers):
        return self._request("GET", f"/advisory-splits/{split_id}", headers=headers)

    # ─── Transitions and retention ────────────────────
    def create_transition(self, payload, headers):
        return self._request("POST", "/transitions", payload, headers)

    def list_transitions(self, headers, params=None):
        return self._request("GET", "/transitions", headers=headers, params=params)

    def get_transition(self, transition_id, headers):
        return self._request("GET", f"/transitions/{transition_id}", headers=headers)

    def list_transition_retention_rows(self, transition_id, headers):
        return self._request("GET", f"/transitions/{transition_id}/retention-rows",
                             headers=headers)

    def contest_retention(self, transition_id, payload, headers):
        return self._request("POST", f"/transitions/{transition_id}/retention/contest",
                             payload, headers)

    def settle_retention(self, transition_id, payload, headers):
        return self._request("POST", f"/transitions/{transition_id}/retention/settle",
                             payload, headers)

    def lose_retention(self, transition_id, payload, headers):
        return self._request("POST", f"/transitions/{transition_id}/retention/lose",
                             payload, headers)

    def list_account_retentions(self, headers, params=None):
        return self._request("GET", "/account-retentions", headers=headers,
                             params=params)

    def get_account_retention(self, retention_id, headers):
        return self._request("GET", f"/account-retentions/{retention_id}",
                             headers=headers)

    def set_account_retention_state(self, retention_id, payload, headers):
        return self._request("POST", f"/account-retentions/{retention_id}/state",
                             payload, headers)


api_client = ApiClient()