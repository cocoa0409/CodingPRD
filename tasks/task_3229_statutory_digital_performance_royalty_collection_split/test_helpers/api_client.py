"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- licensees ---
    def create_licensee(self, payload, headers):
        return self._request("POST", "/licensees", payload, headers)

    def list_licensees(self, headers, params=None):
        return self._request("GET", "/licensees", headers=headers, params=params)

    def get_licensee(self, licensee_id, headers):
        return self._request("GET", f"/licensees/{licensee_id}", headers=headers)

    def activate_licensee(self, licensee_id, headers):
        return self._request("POST", f"/licensees/{licensee_id}/activate", {}, headers)

    def suspend_licensee(self, licensee_id, payload, headers):
        return self._request("POST", f"/licensees/{licensee_id}/suspend", payload, headers)

    def reinstate_licensee(self, licensee_id, headers):
        return self._request("POST", f"/licensees/{licensee_id}/reinstate", {}, headers)

    def terminate_licensee(self, licensee_id, headers):
        return self._request("POST", f"/licensees/{licensee_id}/terminate", {}, headers)

    def list_licensee_usage_reports(self, licensee_id, headers, params=None):
        return self._request("GET", f"/licensees/{licensee_id}/usage-reports",
                             headers=headers, params=params)

    def list_licensee_audit_cases(self, licensee_id, headers, params=None):
        return self._request("GET", f"/licensees/{licensee_id}/audit-cases",
                             headers=headers, params=params)

    # --- rate schedules ---
    def create_rate_schedule(self, payload, headers):
        return self._request("POST", "/rate-schedules", payload, headers)

    def list_rate_schedules(self, headers, params=None):
        return self._request("GET", "/rate-schedules", headers=headers, params=params)

    def get_rate_schedule(self, schedule_id, headers):
        return self._request("GET", f"/rate-schedules/{schedule_id}", headers=headers)

    def activate_rate_schedule(self, schedule_id, headers):
        return self._request("POST", f"/rate-schedules/{schedule_id}/activate", {}, headers)

    # --- rate proceedings ---
    def create_rate_proceeding(self, payload, headers):
        return self._request("POST", "/rate-proceedings", payload, headers)

    def list_rate_proceedings(self, headers, params=None):
        return self._request("GET", "/rate-proceedings", headers=headers, params=params)

    def get_rate_proceeding(self, proceeding_id, headers):
        return self._request("GET", f"/rate-proceedings/{proceeding_id}", headers=headers)

    def decide_rate_proceeding(self, proceeding_id, payload, headers):
        return self._request("POST", f"/rate-proceedings/{proceeding_id}/decide",
                             payload, headers)

    def publish_rate_proceeding(self, proceeding_id, headers):
        return self._request("POST", f"/rate-proceedings/{proceeding_id}/publish",
                             {}, headers)

    def close_rate_proceeding(self, proceeding_id, headers):
        return self._request("POST", f"/rate-proceedings/{proceeding_id}/close",
                             {}, headers)

    # --- usage reports & play lines ---
    def create_usage_report(self, payload, headers):
        return self._request("POST", "/usage-reports", payload, headers)

    def list_usage_reports(self, headers, params=None):
        return self._request("GET", "/usage-reports", headers=headers, params=params)

    def get_usage_report(self, report_id, headers):
        return self._request("GET", f"/usage-reports/{report_id}", headers=headers)

    def submit_usage_report(self, report_id, headers):
        return self._request("POST", f"/usage-reports/{report_id}/submit", {}, headers)

    def accept_usage_report(self, report_id, headers):
        return self._request("POST", f"/usage-reports/{report_id}/accept", {}, headers)

    def reject_usage_report(self, report_id, payload, headers):
        return self._request("POST", f"/usage-reports/{report_id}/reject", payload, headers)

    def amend_usage_report(self, report_id, headers):
        return self._request("POST", f"/usage-reports/{report_id}/amend", {}, headers)

    def list_play_lines(self, report_id, headers, params=None):
        return self._request("GET", f"/usage-reports/{report_id}/play-lines",
                             headers=headers, params=params)

    def add_play_line(self, report_id, payload, headers):
        return self._request("POST", f"/usage-reports/{report_id}/play-lines",
                             payload, headers)

    def delete_play_line(self, play_line_id, headers):
        return self._request("DELETE", f"/play-lines/{play_line_id}", headers=headers)

    def get_play_line(self, play_line_id, headers):
        return self._request("GET", f"/play-lines/{play_line_id}", headers=headers)

    def list_all_play_lines(self, headers, params=None):
        return self._request("GET", "/play-lines", headers=headers, params=params)

    def compute_liability(self, report_id, payload, headers):
        return self._request("POST", f"/usage-reports/{report_id}/compute-liability",
                             payload, headers)

    def get_report_liability(self, report_id, headers):
        return self._request("GET", f"/usage-reports/{report_id}/royalty-liability",
                             headers=headers)

    # --- royalty liabilities ---
    def get_royalty_liability(self, liability_id, headers):
        return self._request("GET", f"/royalty-liabilities/{liability_id}",
                             headers=headers)

    def bill_liability(self, liability_id, headers):
        return self._request("POST", f"/royalty-liabilities/{liability_id}/bill",
                             {}, headers)

    def record_liability_payment(self, liability_id, headers):
        return self._request("POST",
                             f"/royalty-liabilities/{liability_id}/record_payment",
                             {}, headers)

    def write_off_liability(self, liability_id, payload, headers):
        return self._request("POST", f"/royalty-liabilities/{liability_id}/write_off",
                             payload, headers)

    # --- distribution batches & lines ---
    def create_distribution_batch(self, report_id, payload, headers):
        return self._request("POST",
                             f"/usage-reports/{report_id}/distribution-batches",
                             payload, headers)

    def list_distribution_batches(self, report_id, headers, params=None):
        return self._request("GET",
                             f"/usage-reports/{report_id}/distribution-batches",
                             headers=headers, params=params)

    def get_distribution_batch(self, batch_id, headers):
        return self._request("GET", f"/distribution-batches/{batch_id}",
                             headers=headers)

    def execute_distribution_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/distribution-batches/{batch_id}/execute",
                             payload, headers)

    def cancel_distribution_batch(self, batch_id, headers):
        return self._request("POST", f"/distribution-batches/{batch_id}/cancel",
                             {}, headers)

    def list_batch_lines(self, batch_id, headers, params=None):
        return self._request("GET", f"/distribution-batches/{batch_id}/lines",
                             headers=headers, params=params)

    def get_distribution_line(self, line_id, headers):
        return self._request("GET", f"/distribution-lines/{line_id}", headers=headers)

    def list_distribution_lines(self, headers, params=None):
        return self._request("GET", "/distribution-lines", headers=headers,
                             params=params)

    # --- artists & rights owners ---
    def create_artist(self, payload, headers):
        return self._request("POST", "/artists", payload, headers)

    def list_artists(self, headers, params=None):
        return self._request("GET", "/artists", headers=headers, params=params)

    def get_artist(self, artist_id, headers):
        return self._request("GET", f"/artists/{artist_id}", headers=headers)

    def verify_artist(self, artist_id, headers):
        return self._request("POST", f"/artists/{artist_id}/verify", {}, headers)

    def reject_artist_registration(self, artist_id, payload, headers):
        return self._request("POST", f"/artists/{artist_id}/reject_registration",
                             payload, headers)

    def suspend_artist_registration(self, artist_id, headers):
        return self._request("POST", f"/artists/{artist_id}/suspend_registration",
                             {}, headers)

    def create_rights_owner(self, payload, headers):
        return self._request("POST", "/rights-owners", payload, headers)

    def list_rights_owners(self, headers, params=None):
        return self._request("GET", "/rights-owners", headers=headers, params=params)

    def get_rights_owner(self, rights_owner_id, headers):
        return self._request("GET", f"/rights-owners/{rights_owner_id}", headers=headers)

    def verify_rights_owner(self, rights_owner_id, headers):
        return self._request("POST", f"/rights-owners/{rights_owner_id}/verify",
                             {}, headers)

    def reject_rights_owner_registration(self, rights_owner_id, payload, headers):
        return self._request("POST",
                             f"/rights-owners/{rights_owner_id}/reject_registration",
                             payload, headers)

    def suspend_rights_owner_registration(self, rights_owner_id, headers):
        return self._request("POST",
                             f"/rights-owners/{rights_owner_id}/suspend_registration",
                             {}, headers)

    # --- recordings ---
    def create_recording(self, payload, headers):
        return self._request("POST", "/recordings", payload, headers)

    def list_recordings(self, headers, params=None):
        return self._request("GET", "/recordings", headers=headers, params=params)

    def get_recording(self, recording_id, headers):
        return self._request("GET", f"/recordings/{recording_id}", headers=headers)

    def withdraw_recording(self, recording_id, headers):
        return self._request("POST", f"/recordings/{recording_id}/withdraw", {}, headers)

    # --- ownership claims ---
    def create_ownership_claim(self, recording_id, payload, headers):
        return self._request("POST", f"/recordings/{recording_id}/ownership-claims",
                             payload, headers)

    def list_recording_claims(self, recording_id, headers, params=None):
        return self._request("GET", f"/recordings/{recording_id}/ownership-claims",
                             headers=headers, params=params)

    def list_ownership_claims(self, headers, params=None):
        return self._request("GET", "/ownership-claims", headers=headers, params=params)

    def get_ownership_claim(self, claim_id, headers):
        return self._request("GET", f"/ownership-claims/{claim_id}", headers=headers)

    def start_claim_review(self, claim_id, headers):
        return self._request("POST", f"/ownership-claims/{claim_id}/start_review",
                             {}, headers)

    def reopen_claim(self, claim_id, headers):
        return self._request("POST", f"/ownership-claims/{claim_id}/reopen", {}, headers)

    def resolve_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/ownership-claims/{claim_id}/resolve",
                             payload, headers)

    def withdraw_claim(self, claim_id, headers):
        return self._request("POST", f"/ownership-claims/{claim_id}/withdraw",
                             {}, headers)

    # --- unclaimed pools ---
    def create_unclaimed_pool(self, payload, headers):
        return self._request("POST", "/unclaimed-pools", payload, headers)

    def list_unclaimed_pools(self, headers, params=None):
        return self._request("GET", "/unclaimed-pools", headers=headers, params=params)

    def get_unclaimed_pool(self, pool_id, headers):
        return self._request("GET", f"/unclaimed-pools/{pool_id}", headers=headers)

    def start_pool_campaign(self, pool_id, headers):
        return self._request("POST", f"/unclaimed-pools/{pool_id}/start_campaign",
                             {}, headers)

    def complete_pool_campaign(self, pool_id, headers):
        return self._request("POST", f"/unclaimed-pools/{pool_id}/complete_campaign",
                             {}, headers)

    def release_pool(self, pool_id, headers):
        return self._request("POST", f"/unclaimed-pools/{pool_id}/release", {}, headers)

    def expire_pool(self, pool_id, headers):
        return self._request("POST", f"/unclaimed-pools/{pool_id}/expire", {}, headers)

    # --- audit cases ---
    def create_audit_case(self, licensee_id, payload, headers):
        return self._request("POST", f"/licensees/{licensee_id}/audit-cases",
                             payload, headers)

    def get_audit_case(self, audit_id, headers):
        return self._request("GET", f"/audit-cases/{audit_id}", headers=headers)

    def issue_audit_findings(self, audit_id, payload, headers):
        return self._request("POST", f"/audit-cases/{audit_id}/issue_findings",
                             payload, headers)

    def record_audit_recovery(self, audit_id, payload, headers):
        return self._request("POST", f"/audit-cases/{audit_id}/record_recovery",
                             payload, headers)

    def close_audit_case(self, audit_id, headers):
        return self._request("POST", f"/audit-cases/{audit_id}/close", {}, headers)

    def waive_audit_case(self, audit_id, payload, headers):
        return self._request("POST", f"/audit-cases/{audit_id}/waive", payload, headers)


api_client = ApiClient()
