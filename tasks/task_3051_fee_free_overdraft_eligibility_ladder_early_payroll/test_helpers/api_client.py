"""HTTP client for the Fee-Free Overdraft Early Payroll API.

One method per endpoint declared in the PRD. Every method returns the raw
response so tests can assert on both the status code and the envelope.
All paths are mounted under the ``/banking`` prefix.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Members -------------------------------------------------------
    def create_member(self, payload: Dict, headers: Dict):
        return self._request("POST", "/banking/members", payload, headers)

    def list_members(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/banking/members", headers=headers, params=params)

    def get_member(self, member_id: str, headers: Dict):
        return self._request("GET", f"/banking/members/{member_id}", headers=headers)

    def close_member(self, member_id: str, payload: Optional[Dict], headers: Dict):
        return self._request("POST", f"/banking/members/{member_id}/close", payload or {}, headers)

    # --- Eligibility ---------------------------------------------------
    def create_eligibility_evaluation(self, member_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/banking/members/{member_id}/eligibility-evaluations", payload, headers
        )

    def list_eligibility_profiles(self, member_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/banking/members/{member_id}/eligibility-profiles", headers=headers, params=params
        )

    # --- Abuse events --------------------------------------------------
    def create_abuse_event(self, member_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/banking/members/{member_id}/abuse-events", payload, headers
        )

    def list_abuse_events(self, member_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/banking/members/{member_id}/abuse-events", headers=headers, params=params
        )

    # --- Accounts ------------------------------------------------------
    def create_account(self, member_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/banking/members/{member_id}/accounts", payload, headers)

    def list_accounts(self, member_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/banking/members/{member_id}/accounts", headers=headers, params=params
        )

    def get_account(self, account_id: str, headers: Dict):
        return self._request("GET", f"/banking/accounts/{account_id}", headers=headers)

    # --- Advances and debits -------------------------------------------
    def create_advance(self, account_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/banking/accounts/{account_id}/advances", payload, headers)

    def create_debit(self, account_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/banking/accounts/{account_id}/debits", payload, headers)

    def list_advances(self, account_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/banking/accounts/{account_id}/advances", headers=headers, params=params
        )

    def get_advance(self, advance_id: str, headers: Dict):
        return self._request("GET", f"/banking/advances/{advance_id}", headers=headers)

    def write_off_advance(self, advance_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/banking/advances/{advance_id}/write-off", payload, headers)

    def list_advance_repayment_allocations(
        self, advance_id: str, headers: Dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/banking/advances/{advance_id}/repayment-allocations",
            headers=headers,
            params=params,
        )

    # --- Ledger entries --------------------------------------------------
    def list_account_ledger_entries(
        self, account_id: str, headers: Dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/banking/accounts/{account_id}/ledger-entries", headers=headers, params=params
        )

    # --- Deposits --------------------------------------------------------
    def create_deposit(self, account_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/banking/accounts/{account_id}/deposits", payload, headers)

    def list_deposits(self, account_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/banking/accounts/{account_id}/deposits", headers=headers, params=params
        )

    def get_deposit(self, deposit_id: str, headers: Dict):
        return self._request("GET", f"/banking/deposits/{deposit_id}", headers=headers)

    def post_early(self, deposit_id: str, payload: Optional[Dict], headers: Dict):
        return self._request(
            "POST", f"/banking/deposits/{deposit_id}/post-early", payload or {}, headers
        )

    def settle_deposit(self, deposit_id: str, payload: Optional[Dict], headers: Dict):
        return self._request(
            "POST", f"/banking/deposits/{deposit_id}/settle", payload or {}, headers
        )

    def return_deposit(self, deposit_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/banking/deposits/{deposit_id}/return", payload, headers)

    def list_deposit_returns(self, deposit_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/banking/deposits/{deposit_id}/returns", headers=headers, params=params
        )

    def list_deposit_early_postings(
        self, deposit_id: str, headers: Dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/banking/deposits/{deposit_id}/early-postings", headers=headers, params=params
        )

    def list_deposit_repayment_allocations(
        self, deposit_id: str, headers: Dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/banking/deposits/{deposit_id}/repayment-allocations",
            headers=headers,
            params=params,
        )

    def list_deposit_disputes(self, deposit_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/banking/deposits/{deposit_id}/disputes", headers=headers, params=params
        )

    # --- Limit adjustments -----------------------------------------------
    def list_limit_adjustments(self, member_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/banking/members/{member_id}/limit-adjustments", headers=headers, params=params
        )

    def get_limit_adjustment(self, adjustment_id: str, headers: Dict):
        return self._request(
            "GET", f"/banking/limit-adjustments/{adjustment_id}", headers=headers
        )

    def notify_limit_adjustment(self, adjustment_id: str, payload: Optional[Dict], headers: Dict):
        return self._request(
            "POST", f"/banking/limit-adjustments/{adjustment_id}/notify", payload or {}, headers
        )

    # --- Reconciliation runs ---------------------------------------------
    def create_reconciliation_run(self, payload: Dict, headers: Dict):
        return self._request("POST", "/banking/reconciliation-runs", payload, headers)

    def list_reconciliation_runs(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/banking/reconciliation-runs", headers=headers, params=params)

    def get_reconciliation_run(self, run_id: str, headers: Dict):
        return self._request("GET", f"/banking/reconciliation-runs/{run_id}", headers=headers)

    def resolve_reconciliation_run(self, run_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/banking/reconciliation-runs/{run_id}/resolve", payload, headers
        )

    def list_run_ledger_entries(self, run_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET",
            f"/banking/reconciliation-runs/{run_id}/ledger-entries",
            headers=headers,
            params=params,
        )

    # --- Disputes --------------------------------------------------------
    def create_dispute(self, payload: Dict, headers: Dict):
        return self._request("POST", "/banking/disputes", payload, headers)

    def get_dispute(self, dispute_id: str, headers: Dict):
        return self._request("GET", f"/banking/disputes/{dispute_id}", headers=headers)

    def list_member_disputes(self, member_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/banking/members/{member_id}/disputes", headers=headers, params=params
        )

    def issue_provisional_credit(self, dispute_id: str, payload: Optional[Dict], headers: Dict):
        return self._request(
            "POST",
            f"/banking/disputes/{dispute_id}/issue-provisional-credit",
            payload or {},
            headers,
        )

    def resolve_dispute(self, dispute_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/banking/disputes/{dispute_id}/resolve", payload, headers)

    # --- Logical clock ---------------------------------------------------
    def set_clock(self, payload: Dict, headers: Dict):
        return self._request("POST", "/banking/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
