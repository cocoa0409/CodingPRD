"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def _request(self, method, path, payload=None, headers=None, params=None):
        # per-test-server isolation restarts the server before every test;
        # forcing Connection: close prevents the session-scoped client from
        # reusing a stale keep-alive connection to the previous server
        # process (RemoteDisconnected flakes on the first request of a test).
        hdrs = dict(headers or {})
        hdrs.setdefault("Connection", "close")
        return super()._request(method, path, payload, hdrs, params)

    # --- Logical clock (test-driving) ---
    def set_logical_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Stores ---
    def create_store(self, payload, headers):
        return self._request("POST", "/stores", payload, headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", "/stores", headers=headers, params=params)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    def update_store(self, store_id, payload, headers):
        return self._request("PATCH", f"/stores/{store_id}", payload, headers)

    # --- Rebate programs / program items ---
    def create_program(self, store_id, payload, headers):
        return self._request(
            "POST", f"/stores/{store_id}/rebate-programs", payload, headers
        )

    def list_programs(self, store_id, headers, params=None):
        return self._request(
            "GET", f"/stores/{store_id}/rebate-programs", headers=headers, params=params
        )

    def get_program(self, store_id, program_id, headers):
        return self._request(
            "GET", f"/stores/{store_id}/rebate-programs/{program_id}", headers=headers
        )

    def create_program_item(self, store_id, program_id, payload, headers):
        return self._request(
            "POST", f"/stores/{store_id}/rebate-programs/{program_id}/items",
            payload, headers,
        )

    def list_program_items(self, store_id, program_id, headers, params=None):
        return self._request(
            "GET", f"/stores/{store_id}/rebate-programs/{program_id}/items",
            headers=headers, params=params,
        )

    def activate_program(self, store_id, program_id, headers):
        return self._request(
            "POST", f"/stores/{store_id}/rebate-programs/{program_id}/activate",
            headers=headers,
        )

    def close_program(self, store_id, program_id, headers):
        return self._request(
            "POST", f"/stores/{store_id}/rebate-programs/{program_id}/close",
            headers=headers,
        )

    # --- Credit accounts / job purchases / contractor summary ---
    def create_account(self, store_id, payload, headers):
        return self._request(
            "POST", f"/stores/{store_id}/credit-accounts", payload, headers
        )

    def get_account(self, store_id, account_id, headers):
        return self._request(
            "GET", f"/stores/{store_id}/credit-accounts/{account_id}", headers=headers
        )

    def freeze_account(self, store_id, account_id, headers):
        return self._request(
            "POST", f"/stores/{store_id}/credit-accounts/{account_id}/freeze",
            headers=headers,
        )

    def unfreeze_account(self, store_id, account_id, headers):
        return self._request(
            "POST", f"/stores/{store_id}/credit-accounts/{account_id}/unfreeze",
            headers=headers,
        )

    def close_account(self, store_id, account_id, headers):
        return self._request(
            "POST", f"/stores/{store_id}/credit-accounts/{account_id}/close",
            headers=headers,
        )

    def create_job_purchase(self, store_id, account_id, payload, headers):
        return self._request(
            "POST",
            f"/stores/{store_id}/credit-accounts/{account_id}/job-purchases",
            payload, headers,
        )

    def list_jobs(self, store_id, account_id, headers, params=None):
        return self._request(
            "GET", f"/stores/{store_id}/credit-accounts/{account_id}/jobs",
            headers=headers, params=params,
        )

    def settle_job(self, store_id, job_id, headers):
        return self._request(
            "POST", f"/stores/{store_id}/job-purchases/{job_id}/settle", headers=headers
        )

    def get_contractor_summary(self, store_id, account_id, headers):
        return self._request(
            "GET",
            f"/stores/{store_id}/credit-accounts/{account_id}/contractor-summary",
            headers=headers,
        )

    # --- Receipts / lines / returns ---
    def create_receipt(self, store_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/receipts", payload, headers)

    def list_receipts(self, store_id, headers, params=None):
        return self._request(
            "GET", f"/stores/{store_id}/receipts", headers=headers, params=params
        )

    def get_receipt(self, store_id, receipt_id, headers):
        return self._request(
            "GET", f"/stores/{store_id}/receipts/{receipt_id}", headers=headers
        )

    def list_receipt_lines(self, store_id, receipt_id, headers):
        return self._request(
            "GET", f"/stores/{store_id}/receipts/{receipt_id}/lines", headers=headers
        )

    def create_return(self, store_id, receipt_id, payload, headers):
        return self._request(
            "POST", f"/stores/{store_id}/receipts/{receipt_id}/returns",
            payload, headers,
        )

    # --- Rebate submissions / lines ---
    def create_submission(self, store_id, payload, headers):
        return self._request(
            "POST", f"/stores/{store_id}/rebate-submissions", payload, headers
        )

    def list_submissions(self, store_id, headers, params=None):
        return self._request(
            "GET", f"/stores/{store_id}/rebate-submissions", headers=headers,
            params=params,
        )

    def get_submission(self, store_id, submission_id, headers):
        return self._request(
            "GET", f"/stores/{store_id}/rebate-submissions/{submission_id}",
            headers=headers,
        )

    def list_submission_lines(self, store_id, submission_id, headers):
        return self._request(
            "GET", f"/stores/{store_id}/rebate-submissions/{submission_id}/lines",
            headers=headers,
        )

    def adjudicate_submission(self, store_id, submission_id, payload, headers):
        return self._request(
            "POST",
            f"/stores/{store_id}/rebate-submissions/{submission_id}/adjudicate",
            payload, headers,
        )

    def resubmit_submission(self, store_id, submission_id, headers):
        return self._request(
            "POST",
            f"/stores/{store_id}/rebate-submissions/{submission_id}/resubmit",
            headers=headers,
        )

    def issue_certificate(self, store_id, submission_id, headers):
        return self._request(
            "POST",
            f"/stores/{store_id}/rebate-submissions/{submission_id}/issue-certificate",
            headers=headers,
        )

    # --- Certificates ---
    def get_certificate(self, store_id, certificate_id, headers):
        return self._request(
            "GET", f"/stores/{store_id}/certificates/{certificate_id}", headers=headers
        )

    def list_certificates(self, store_id, headers, params=None):
        return self._request(
            "GET", f"/stores/{store_id}/certificates", headers=headers, params=params
        )

    def redeem_certificate(self, store_id, certificate_id, payload, headers):
        return self._request(
            "POST", f"/stores/{store_id}/certificates/{certificate_id}/redeem",
            payload, headers,
        )

    def reissue_certificate(self, store_id, certificate_id, headers):
        return self._request(
            "POST", f"/stores/{store_id}/certificates/{certificate_id}/reissue",
            headers=headers,
        )

    def hold_certificate(self, store_id, certificate_id, headers):
        return self._request(
            "POST", f"/stores/{store_id}/certificates/{certificate_id}/hold",
            headers=headers,
        )

    def release_certificate(self, store_id, certificate_id, headers):
        return self._request(
            "POST", f"/stores/{store_id}/certificates/{certificate_id}/release",
            headers=headers,
        )

    # --- Ledger / breakage / fraud ---
    def list_ledger(self, store_id, account_id, headers, params=None):
        return self._request(
            "GET", f"/stores/{store_id}/credit-accounts/{account_id}/ledger",
            headers=headers, params=params,
        )

    def create_breakage_run(self, store_id, payload, headers):
        return self._request(
            "POST", f"/stores/{store_id}/breakage-runs", payload, headers
        )

    def get_breakage_run(self, store_id, run_id, headers):
        return self._request(
            "GET", f"/stores/{store_id}/breakage-runs/{run_id}", headers=headers
        )

    def list_fraud_flags(self, store_id, headers, params=None):
        return self._request(
            "GET", f"/stores/{store_id}/fraud-flags", headers=headers, params=params
        )

    def resolve_fraud_flag(self, store_id, flag_id, payload, headers):
        return self._request(
            "POST", f"/stores/{store_id}/fraud-flags/{flag_id}/resolve",
            payload, headers,
        )

    def reopen_fraud_flag(self, store_id, flag_id, headers):
        return self._request(
            "POST", f"/stores/{store_id}/fraud-flags/{flag_id}/reopen", headers=headers
        )


api_client = ApiClient()
