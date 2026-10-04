"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/pro/_clock/set_current_utc", payload, headers)

    # --- affiliates ---
    def create_affiliate(self, payload, headers):
        return self._request("POST", "/pro/affiliates", payload, headers)

    def list_affiliates(self, headers, params=None):
        return self._request("GET", "/pro/affiliates", headers=headers, params=params)

    def get_affiliate(self, affiliate_id, headers):
        return self._request("GET", f"/pro/affiliates/{affiliate_id}", headers=headers)

    def update_affiliate(self, affiliate_id, payload, headers):
        return self._request("PATCH", f"/pro/affiliates/{affiliate_id}", payload, headers)

    # --- works & share claims ---
    def create_work(self, payload, headers):
        return self._request("POST", "/pro/works", payload, headers)

    def list_works(self, headers, params=None):
        return self._request("GET", "/pro/works", headers=headers, params=params)

    def get_work(self, work_id, headers):
        return self._request("GET", f"/pro/works/{work_id}", headers=headers)

    def confirm_work(self, work_id, headers):
        return self._request("POST", f"/pro/works/{work_id}/confirm", {}, headers)

    def withdraw_work(self, work_id, headers):
        return self._request("POST", f"/pro/works/{work_id}/withdraw", {}, headers)

    def resolve_conflict(self, work_id, payload, headers):
        return self._request("POST", f"/pro/works/{work_id}/resolve-conflict", payload, headers)

    def create_share_claim(self, work_id, payload, headers):
        return self._request("POST", f"/pro/works/{work_id}/share-claims", payload, headers)

    def list_work_share_claims(self, work_id, headers, params=None):
        return self._request("GET", f"/pro/works/{work_id}/share-claims", headers=headers, params=params)

    def list_share_claims(self, headers, params=None):
        return self._request("GET", "/pro/share-claims", headers=headers, params=params)

    def list_affiliate_share_claims(self, affiliate_id, headers, params=None):
        return self._request("GET", f"/pro/affiliates/{affiliate_id}/share-claims", headers=headers, params=params)

    def revoke_share_claim(self, claim_id, headers):
        return self._request("POST", f"/pro/share-claims/{claim_id}/revoke", {}, headers)

    def dispute_share_claim(self, claim_id, headers):
        return self._request("POST", f"/pro/share-claims/{claim_id}/dispute", {}, headers)

    # --- licensees & licenses ---
    def create_licensee(self, payload, headers):
        return self._request("POST", "/pro/licensees", payload, headers)

    def list_licensees(self, headers, params=None):
        return self._request("GET", "/pro/licensees", headers=headers, params=params)

    def get_licensee(self, licensee_id, headers):
        return self._request("GET", f"/pro/licensees/{licensee_id}", headers=headers)

    def update_licensee(self, licensee_id, payload, headers):
        return self._request("PATCH", f"/pro/licensees/{licensee_id}", payload, headers)

    def issue_license(self, licensee_id, payload, headers):
        return self._request("POST", f"/pro/licensees/{licensee_id}/licenses", payload, headers)

    def list_licensee_licenses(self, licensee_id, headers, params=None):
        return self._request("GET", f"/pro/licensees/{licensee_id}/licenses", headers=headers, params=params)

    def list_licenses(self, headers, params=None):
        return self._request("GET", "/pro/licenses", headers=headers, params=params)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/pro/licenses/{license_id}", headers=headers)

    def suspend_license(self, license_id, headers):
        return self._request("POST", f"/pro/licenses/{license_id}/suspend", {}, headers)

    def reinstate_license(self, license_id, headers):
        return self._request("POST", f"/pro/licenses/{license_id}/reinstate", {}, headers)

    def terminate_license(self, license_id, headers):
        return self._request("POST", f"/pro/licenses/{license_id}/terminate", {}, headers)

    # --- disputes & rate court ---
    def open_dispute(self, license_id, payload, headers):
        return self._request("POST", f"/pro/licenses/{license_id}/disputes", payload, headers)

    def list_license_disputes(self, license_id, headers, params=None):
        return self._request("GET", f"/pro/licenses/{license_id}/disputes", headers=headers, params=params)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/pro/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/pro/disputes/{dispute_id}", headers=headers)

    def negotiate_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/pro/disputes/{dispute_id}/negotiate", payload, headers)

    def settle_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/pro/disputes/{dispute_id}/settle", payload, headers)

    def escalate_dispute(self, dispute_id, headers):
        return self._request("POST", f"/pro/disputes/{dispute_id}/escalate", {}, headers)

    def withdraw_dispute(self, dispute_id, headers):
        return self._request("POST", f"/pro/disputes/{dispute_id}/withdraw", {}, headers)

    def list_dispute_rate_court_cases(self, dispute_id, headers, params=None):
        return self._request("GET", f"/pro/disputes/{dispute_id}/rate-court-cases", headers=headers, params=params)

    def open_hearing(self, case_id, headers):
        return self._request("POST", f"/pro/rate-court-cases/{case_id}/open-hearing", {}, headers)

    def decide_case(self, case_id, payload, headers):
        return self._request("POST", f"/pro/rate-court-cases/{case_id}/decide", payload, headers)

    def dismiss_case(self, case_id, headers):
        return self._request("POST", f"/pro/rate-court-cases/{case_id}/dismiss", {}, headers)

    # --- performance ingestion ---
    def ingest_performance(self, payload, headers):
        return self._request("POST", "/pro/performances", payload, headers)

    def ingest_performances_bulk(self, payload, headers):
        return self._request("POST", "/pro/performances/bulk", payload, headers)

    def list_performances(self, headers, params=None):
        return self._request("GET", "/pro/performances", headers=headers, params=params)

    def list_work_performances(self, work_id, headers, params=None):
        return self._request("GET", f"/pro/works/{work_id}/performances", headers=headers, params=params)

    def list_license_performances(self, license_id, headers, params=None):
        return self._request("GET", f"/pro/licenses/{license_id}/performances", headers=headers, params=params)

    def void_performance(self, event_id, headers):
        return self._request("POST", f"/pro/performances/{event_id}/void", {}, headers)

    def capture_performances(self, cycle_id, payload, headers):
        return self._request("POST", f"/pro/cycles/{cycle_id}/performances/capture", payload, headers)

    def list_cycle_performances(self, cycle_id, headers, params=None):
        return self._request("GET", f"/pro/cycles/{cycle_id}/performances", headers=headers, params=params)

    # --- distribution cycles, statements, adjustments ---
    def create_cycle(self, payload, headers):
        return self._request("POST", "/pro/cycles", payload, headers)

    def list_cycles(self, headers, params=None):
        return self._request("GET", "/pro/cycles", headers=headers, params=params)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/pro/cycles/{cycle_id}", headers=headers)

    def open_cycle(self, cycle_id, headers):
        return self._request("POST", f"/pro/cycles/{cycle_id}/open", {}, headers)

    def close_collection(self, cycle_id, payload, headers):
        return self._request("POST", f"/pro/cycles/{cycle_id}/close-collection", payload, headers)

    def distribute_cycle(self, cycle_id, headers):
        return self._request("POST", f"/pro/cycles/{cycle_id}/distribute", {}, headers)

    def list_cycle_statements(self, cycle_id, headers, params=None):
        return self._request("GET", f"/pro/cycles/{cycle_id}/statements", headers=headers, params=params)

    def get_cycle_pool(self, cycle_id, headers):
        return self._request("GET", f"/pro/cycles/{cycle_id}/pool", headers=headers)

    def list_statements(self, headers, params=None):
        return self._request("GET", "/pro/statements", headers=headers, params=params)

    def list_affiliate_statements(self, affiliate_id, headers, params=None):
        return self._request("GET", f"/pro/affiliates/{affiliate_id}/statements", headers=headers, params=params)

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/pro/statements/{statement_id}", headers=headers)

    def finalize_statement(self, statement_id, headers):
        return self._request("POST", f"/pro/statements/{statement_id}/finalize", {}, headers)

    def create_adjustment(self, statement_id, payload, headers):
        return self._request("POST", f"/pro/statements/{statement_id}/adjustments", payload, headers)

    def list_statement_adjustments(self, statement_id, headers, params=None):
        return self._request("GET", f"/pro/statements/{statement_id}/adjustments", headers=headers, params=params)

    def list_adjustments(self, headers, params=None):
        return self._request("GET", "/pro/adjustments", headers=headers, params=params)

    def get_adjustment(self, adjustment_id, headers):
        return self._request("GET", f"/pro/adjustments/{adjustment_id}", headers=headers)

    def approve_adjustment(self, adjustment_id, headers):
        return self._request("POST", f"/pro/adjustments/{adjustment_id}/approve", {}, headers)

    def reject_adjustment(self, adjustment_id, headers):
        return self._request("POST", f"/pro/adjustments/{adjustment_id}/reject", {}, headers)

    def apply_adjustment(self, adjustment_id, headers):
        return self._request("POST", f"/pro/adjustments/{adjustment_id}/apply", {}, headers)

    # --- audits ---
    def create_audit(self, licensee_id, payload, headers):
        return self._request("POST", f"/pro/licensees/{licensee_id}/audits", payload, headers)

    def list_licensee_audits(self, licensee_id, headers, params=None):
        return self._request("GET", f"/pro/licensees/{licensee_id}/audits", headers=headers, params=params)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/pro/audits/{audit_id}", headers=headers)

    def file_findings(self, audit_id, payload, headers):
        return self._request("POST", f"/pro/audits/{audit_id}/file-findings", payload, headers)

    def close_audit(self, audit_id, headers):
        return self._request("POST", f"/pro/audits/{audit_id}/close", {}, headers)

    # --- unclaimed pools ---
    def list_pools(self, headers, params=None):
        return self._request("GET", "/pro/pools", headers=headers, params=params)

    def get_pool(self, pool_id, headers):
        return self._request("GET", f"/pro/pools/{pool_id}", headers=headers)

    def escheat_pool(self, pool_id, payload, headers):
        return self._request("POST", f"/pro/pools/{pool_id}/escheat", payload, headers)


api_client = ApiClient()
