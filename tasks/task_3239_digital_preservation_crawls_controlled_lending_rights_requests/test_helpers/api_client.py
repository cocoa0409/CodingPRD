"""API client: one method per endpoint defined in the PRD (mounted under /archive)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving / system ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/archive/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def run_sweep(self, headers):
        return self._request("POST", "/archive/_sweeps/run", {}, headers)

    # --- patrons & accessibility ---
    def create_patron(self, payload, headers):
        return self._request("POST", "/archive/patrons", payload, headers)

    def get_patron(self, patron_id, headers):
        return self._request("GET", f"/archive/patrons/{patron_id}", headers=headers)

    def create_accessibility_credential(self, payload, headers):
        return self._request("POST", "/archive/accessibility-credentials", payload, headers)

    def list_patron_credentials(self, patron_id, headers, params=None):
        return self._request("GET", f"/archive/patrons/{patron_id}/accessibility-credentials",
                             headers=headers, params=params)

    def get_accessibility_credential(self, credential_id, headers):
        return self._request("GET", f"/archive/accessibility-credentials/{credential_id}",
                             headers=headers)

    def decide_accessibility_credential(self, credential_id, payload, headers):
        return self._request("POST",
                             f"/archive/accessibility-credentials/{credential_id}/decide",
                             payload, headers)

    # --- partner libraries ---
    def create_partner_library(self, payload, headers):
        return self._request("POST", "/archive/partner-libraries", payload, headers)

    def get_partner_library(self, library_id, headers):
        return self._request("GET", f"/archive/partner-libraries/{library_id}",
                             headers=headers)

    def withdraw_partner_library(self, library_id, headers):
        return self._request("POST", f"/archive/partner-libraries/{library_id}/withdraw",
                             {}, headers)

    def list_library_items(self, library_id, headers, params=None):
        return self._request("GET", f"/archive/partner-libraries/{library_id}/items",
                             headers=headers, params=params)

    # --- works ---
    def create_work(self, payload, headers):
        return self._request("POST", "/archive/works", payload, headers)

    def get_work(self, work_id, headers):
        return self._request("GET", f"/archive/works/{work_id}", headers=headers)

    def list_work_items(self, work_id, headers, params=None):
        return self._request("GET", f"/archive/works/{work_id}/items",
                             headers=headers, params=params)

    def list_work_waitlist_entries(self, work_id, headers, params=None):
        return self._request("GET", f"/archive/works/{work_id}/waitlist-entries",
                             headers=headers, params=params)

    def list_work_rights_requests(self, work_id, headers, params=None):
        return self._request("GET", f"/archive/works/{work_id}/rights-requests",
                             headers=headers, params=params)

    # --- scan batches & items ---
    def create_scan_batch(self, payload, headers):
        return self._request("POST", "/archive/scan-batches", payload, headers)

    def get_scan_batch(self, batch_id, headers):
        return self._request("GET", f"/archive/scan-batches/{batch_id}", headers=headers)

    def seal_scan_batch(self, batch_id, headers):
        return self._request("POST", f"/archive/scan-batches/{batch_id}/seal", {}, headers)

    def reject_scan_batch(self, batch_id, headers):
        return self._request("POST", f"/archive/scan-batches/{batch_id}/reject", {}, headers)

    def list_batch_items(self, batch_id, headers, params=None):
        return self._request("GET", f"/archive/scan-batches/{batch_id}/items",
                             headers=headers, params=params)

    def create_item(self, payload, headers):
        return self._request("POST", "/archive/items", payload, headers)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/archive/items/{item_id}", headers=headers)

    def retire_item(self, item_id, headers):
        return self._request("POST", f"/archive/items/{item_id}/retire", {}, headers)

    def list_item_loans(self, item_id, headers, params=None):
        return self._request("GET", f"/archive/items/{item_id}/loans",
                             headers=headers, params=params)

    # --- loans ---
    def create_loan(self, payload, headers):
        return self._request("POST", "/archive/loans", payload, headers)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/archive/loans/{loan_id}", headers=headers)

    def list_patron_loans(self, patron_id, headers, params=None):
        return self._request("GET", f"/archive/patrons/{patron_id}/loans",
                             headers=headers, params=params)

    def return_loan(self, loan_id, headers):
        return self._request("POST", f"/archive/loans/{loan_id}/return", {}, headers)

    def renew_loan(self, loan_id, headers):
        return self._request("POST", f"/archive/loans/{loan_id}/renew", {}, headers)

    # --- waitlist ---
    def create_waitlist_entry(self, payload, headers):
        return self._request("POST", "/archive/waitlist-entries", payload, headers)

    def get_waitlist_entry(self, entry_id, headers):
        return self._request("GET", f"/archive/waitlist-entries/{entry_id}", headers=headers)

    def list_patron_waitlist_entries(self, patron_id, headers, params=None):
        return self._request("GET", f"/archive/patrons/{patron_id}/waitlist-entries",
                             headers=headers, params=params)

    def claim_waitlist_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/archive/waitlist-entries/{entry_id}/claim",
                             payload, headers)

    def cancel_waitlist_entry(self, entry_id, headers):
        return self._request("POST", f"/archive/waitlist-entries/{entry_id}/cancel",
                             {}, headers)

    # --- crawl jobs, captures, playback, exclusions ---
    def create_crawl_job(self, payload, headers):
        return self._request("POST", "/archive/crawl-jobs", payload, headers)

    def get_crawl_job(self, job_id, headers):
        return self._request("GET", f"/archive/crawl-jobs/{job_id}", headers=headers)

    def start_crawl_job(self, job_id, headers):
        return self._request("POST", f"/archive/crawl-jobs/{job_id}/start", {}, headers)

    def complete_crawl_job(self, job_id, headers):
        return self._request("POST", f"/archive/crawl-jobs/{job_id}/complete", {}, headers)

    def cancel_crawl_job(self, job_id, headers):
        return self._request("POST", f"/archive/crawl-jobs/{job_id}/cancel", {}, headers)

    def list_job_captures(self, job_id, headers, params=None):
        return self._request("GET", f"/archive/crawl-jobs/{job_id}/captures",
                             headers=headers, params=params)

    def create_capture(self, payload, headers):
        return self._request("POST", "/archive/captures", payload, headers)

    def get_capture(self, capture_id, headers):
        return self._request("GET", f"/archive/captures/{capture_id}", headers=headers)

    def get_playback(self, headers, params=None):
        return self._request("GET", "/archive/playback", headers=headers, params=params)

    def create_exclusion_directive(self, payload, headers):
        return self._request("POST", "/archive/exclusion-directives", payload, headers)

    def retract_exclusion_directive(self, directive_id, headers):
        return self._request("POST",
                             f"/archive/exclusion-directives/{directive_id}/retract",
                             {}, headers)

    # --- rights requests ---
    def create_rights_request(self, payload, headers):
        return self._request("POST", "/archive/rights-requests", payload, headers)

    def get_rights_request(self, request_id, headers):
        return self._request("GET", f"/archive/rights-requests/{request_id}", headers=headers)

    def begin_review_rights_request(self, request_id, headers):
        return self._request("POST",
                             f"/archive/rights-requests/{request_id}/begin-review",
                             {}, headers)

    def escalate_hold_rights_request(self, request_id, headers):
        return self._request("POST",
                             f"/archive/rights-requests/{request_id}/escalate-hold",
                             {}, headers)

    def decide_rights_request(self, request_id, payload, headers):
        return self._request("POST", f"/archive/rights-requests/{request_id}/decide",
                             payload, headers)

    # --- funding grants & budget lines ---
    def create_funding_grant(self, payload, headers):
        return self._request("POST", "/archive/funding-grants", payload, headers)

    def get_funding_grant(self, grant_id, headers):
        return self._request("GET", f"/archive/funding-grants/{grant_id}", headers=headers)

    def list_grant_budget_lines(self, grant_id, headers, params=None):
        return self._request("GET", f"/archive/funding-grants/{grant_id}/budget-lines",
                             headers=headers, params=params)

    def create_budget_line(self, payload, headers):
        return self._request("POST", "/archive/budget-lines", payload, headers)

    def get_budget_line(self, line_id, headers):
        return self._request("GET", f"/archive/budget-lines/{line_id}", headers=headers)

    def settle_budget_line(self, line_id, payload, headers):
        return self._request("POST", f"/archive/budget-lines/{line_id}/settle",
                             payload, headers)

    def release_budget_line(self, line_id, payload, headers):
        return self._request("POST", f"/archive/budget-lines/{line_id}/release",
                             payload, headers)


api_client = ApiClient()
