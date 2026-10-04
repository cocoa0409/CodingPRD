"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Agency ---
    def create_agency(self, payload, headers):
        return self._request("POST", "/agencies", payload, headers)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/agencies/{agency_id}", headers=headers)

    # --- AgencyPolicy ---
    def create_policy(self, agency_id, payload, headers):
        return self._request("POST", f"/agencies/{agency_id}/policies", payload, headers)

    def activate_policy(self, agency_id, policy_id, headers):
        return self._request("POST", f"/agencies/{agency_id}/policies/{policy_id}/activate",
                             headers=headers)

    def supersede_policy(self, agency_id, policy_id, headers):
        return self._request("POST", f"/agencies/{agency_id}/policies/{policy_id}/supersede",
                             headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/agencies/policies", headers=headers, params=params)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/agencies/policies/{policy_id}", headers=headers)

    # --- StorageBudgetPlan ---
    def create_budget_plan(self, agency_id, payload, headers):
        return self._request("POST", f"/agencies/{agency_id}/storage-budget-plans",
                             payload, headers)

    def get_budget_projection(self, agency_id, headers, params=None):
        return self._request("GET", f"/agencies/{agency_id}/storage/budget-projection",
                             headers=headers, params=params)

    def list_budget_plans(self, headers, params=None):
        return self._request("GET", "/agencies/budget-plans", headers=headers, params=params)

    def get_budget_plan(self, plan_id, headers):
        return self._request("GET", f"/agencies/budget-plans/{plan_id}", headers=headers)

    # --- Officer ---
    def create_officer(self, agency_id, payload, headers):
        return self._request("POST", f"/agencies/{agency_id}/officers", payload, headers)

    def list_officers(self, headers, params=None):
        return self._request("GET", "/agencies/officers", headers=headers, params=params)

    def get_officer(self, agency_id, officer_id, headers):
        return self._request("GET", f"/agencies/{agency_id}/officers/{officer_id}",
                             headers=headers)

    def get_officer_flat(self, officer_id, headers):
        return self._request("GET", f"/agencies/officers/{officer_id}", headers=headers)

    def suspend_officer(self, agency_id, officer_id, headers):
        return self._request("POST", f"/agencies/{agency_id}/officers/{officer_id}/suspend",
                             headers=headers)

    def reinstate_officer(self, agency_id, officer_id, headers):
        return self._request("POST", f"/agencies/{agency_id}/officers/{officer_id}/reinstate",
                             headers=headers)

    def retire_officer(self, agency_id, officer_id, headers):
        return self._request("POST", f"/agencies/{agency_id}/officers/{officer_id}/retire",
                             headers=headers)

    # --- Device ---
    def create_device(self, agency_id, payload, headers):
        return self._request("POST", f"/agencies/{agency_id}/devices", payload, headers)

    def get_device(self, agency_id, device_id, headers):
        return self._request("GET", f"/agencies/{agency_id}/devices/{device_id}",
                             headers=headers)

    def get_device_flat(self, device_id, headers):
        return self._request("GET", f"/agencies/devices/{device_id}", headers=headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", "/agencies/devices", headers=headers, params=params)

    def assign_device(self, agency_id, device_id, payload, headers):
        return self._request("POST", f"/agencies/{agency_id}/devices/{device_id}/assign",
                             payload, headers)

    def unassign_device(self, agency_id, device_id, headers):
        return self._request("POST", f"/agencies/{agency_id}/devices/{device_id}/unassign",
                             headers=headers)

    def dock_device(self, agency_id, device_id, headers):
        return self._request("POST", f"/agencies/{agency_id}/devices/{device_id}/dock",
                             headers=headers)

    def undock_device(self, agency_id, device_id, headers):
        return self._request("POST", f"/agencies/{agency_id}/devices/{device_id}/undock",
                             headers=headers)

    def retire_device(self, agency_id, device_id, headers):
        return self._request("POST", f"/agencies/{agency_id}/devices/{device_id}/retire",
                             headers=headers)

    # --- Recording ---
    def create_recording(self, agency_id, payload, headers):
        return self._request("POST", f"/agencies/{agency_id}/recordings", payload, headers)

    def list_recordings(self, headers, params=None):
        return self._request("GET", "/agencies/recordings", headers=headers, params=params)

    def get_recording(self, agency_id, recording_id, headers):
        return self._request("GET", f"/agencies/{agency_id}/recordings/{recording_id}",
                             headers=headers)

    def get_recording_flat(self, recording_id, headers):
        return self._request("GET", f"/agencies/recordings/{recording_id}", headers=headers)

    def reverify_recording(self, agency_id, recording_id, payload, headers):
        return self._request("POST",
                             f"/agencies/{agency_id}/recordings/{recording_id}/reverify",
                             payload, headers)

    def categorize_recording(self, agency_id, recording_id, payload, headers):
        return self._request("PATCH",
                             f"/agencies/{agency_id}/recordings/{recording_id}/categorize",
                             payload, headers)

    def mark_reviewed(self, agency_id, recording_id, headers):
        return self._request("POST",
                             f"/agencies/{agency_id}/recordings/{recording_id}/mark-reviewed",
                             headers=headers)

    def list_custody_events_for_recording(self, agency_id, recording_id, headers, params=None):
        return self._request("GET",
                             f"/agencies/{agency_id}/recordings/{recording_id}/custody-events",
                             headers=headers, params=params)

    # --- retention ---
    def run_retention(self, agency_id, headers):
        return self._request("POST", f"/agencies/{agency_id}/retention/run", headers=headers)

    # --- CaseEntity ---
    def create_case(self, agency_id, payload, headers):
        return self._request("POST", f"/agencies/{agency_id}/cases", payload, headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/agencies/cases", headers=headers, params=params)

    def get_case(self, agency_id, case_id, headers):
        return self._request("GET", f"/agencies/{agency_id}/cases/{case_id}", headers=headers)

    def get_case_flat(self, case_id, headers):
        return self._request("GET", f"/agencies/cases/{case_id}", headers=headers)

    def submit_case_review(self, agency_id, case_id, headers):
        return self._request("POST", f"/agencies/{agency_id}/cases/{case_id}/submit-review",
                             headers=headers)

    def close_case(self, agency_id, case_id, headers):
        return self._request("POST", f"/agencies/{agency_id}/cases/{case_id}/close",
                             headers=headers)

    def reopen_case(self, agency_id, case_id, headers):
        return self._request("POST", f"/agencies/{agency_id}/cases/{case_id}/reopen",
                             headers=headers)

    def archive_case(self, agency_id, case_id, headers):
        return self._request("POST", f"/agencies/{agency_id}/cases/{case_id}/archive",
                             headers=headers)

    # --- CaseEvidenceLink ---
    def link_evidence(self, agency_id, case_id, payload, headers):
        return self._request("POST", f"/agencies/{agency_id}/cases/{case_id}/evidence",
                             payload, headers)

    def list_case_evidence(self, agency_id, case_id, headers, params=None):
        return self._request("GET", f"/agencies/{agency_id}/cases/{case_id}/evidence",
                             headers=headers, params=params)

    def unlink_evidence(self, agency_id, case_id, link_id, headers):
        return self._request("DELETE",
                             f"/agencies/{agency_id}/cases/{case_id}/evidence/{link_id}",
                             headers=headers)

    def list_evidence_links(self, headers, params=None):
        return self._request("GET", "/agencies/evidence-links", headers=headers, params=params)

    def get_evidence_link(self, link_id, headers):
        return self._request("GET", f"/agencies/evidence-links/{link_id}", headers=headers)

    # --- RedactionJob ---
    def create_redaction_job(self, agency_id, recording_id, payload, headers):
        return self._request("POST",
                             f"/agencies/{agency_id}/recordings/{recording_id}/redaction-jobs",
                             payload, headers)

    def list_redaction_jobs(self, headers, params=None):
        return self._request("GET", "/agencies/redaction-jobs", headers=headers, params=params)

    def get_redaction_job(self, job_id, headers):
        return self._request("GET", f"/agencies/redaction-jobs/{job_id}", headers=headers)

    def start_redaction_job(self, agency_id, job_id, headers):
        return self._request("POST", f"/agencies/{agency_id}/redaction-jobs/{job_id}/start",
                             headers=headers)

    def submit_redaction_job(self, agency_id, job_id, payload, headers):
        return self._request("POST", f"/agencies/{agency_id}/redaction-jobs/{job_id}/submit",
                             payload, headers)

    def approve_redaction_job(self, agency_id, job_id, headers):
        return self._request("POST", f"/agencies/{agency_id}/redaction-jobs/{job_id}/approve",
                             headers=headers)

    def return_redaction_job(self, agency_id, job_id, headers):
        return self._request("POST", f"/agencies/{agency_id}/redaction-jobs/{job_id}/return",
                             headers=headers)

    def release_redaction_job(self, agency_id, job_id, headers):
        return self._request("POST", f"/agencies/{agency_id}/redaction-jobs/{job_id}/release",
                             headers=headers)

    def cancel_redaction_job(self, agency_id, job_id, headers):
        return self._request("POST", f"/agencies/{agency_id}/redaction-jobs/{job_id}/cancel",
                             headers=headers)

    # --- ShareGrant ---
    def create_share_grant(self, agency_id, case_id, payload, headers):
        return self._request("POST", f"/agencies/{agency_id}/cases/{case_id}/share-grants",
                             payload, headers)

    def list_case_share_grants(self, agency_id, case_id, headers, params=None):
        return self._request("GET", f"/agencies/{agency_id}/cases/{case_id}/share-grants",
                             headers=headers, params=params)

    def list_share_grants(self, headers, params=None):
        return self._request("GET", "/agencies/share-grants", headers=headers, params=params)

    def get_share_grant(self, grant_id, headers):
        return self._request("GET", f"/agencies/share-grants/{grant_id}", headers=headers)

    def revoke_share_grant(self, agency_id, grant_id, headers):
        return self._request("POST", f"/agencies/{agency_id}/share-grants/{grant_id}/revoke",
                             headers=headers)

    def sweep_share_grants(self, agency_id, headers):
        return self._request("POST", f"/agencies/{agency_id}/share-grants/sweep",
                             headers=headers)

    def share_access(self, agency_id, payload, headers):
        return self._request("POST", f"/agencies/{agency_id}/share-access", payload, headers)

    # --- LegalHold ---
    def create_legal_hold(self, agency_id, payload, headers):
        return self._request("POST", f"/agencies/{agency_id}/legal-holds", payload, headers)

    def list_legal_holds(self, headers, params=None):
        return self._request("GET", "/agencies/legal-holds", headers=headers, params=params)

    def get_legal_hold(self, hold_id, headers):
        return self._request("GET", f"/agencies/legal-holds/{hold_id}", headers=headers)

    def release_legal_hold(self, agency_id, hold_id, headers):
        return self._request("POST", f"/agencies/{agency_id}/legal-holds/{hold_id}/release",
                             headers=headers)

    # --- compliance ledgers ---
    def list_audit_log(self, headers, params=None):
        return self._request("GET", "/agencies/audit-log", headers=headers, params=params)

    def get_audit_log_entry(self, entry_id, headers):
        return self._request("GET", f"/agencies/audit-log/{entry_id}", headers=headers)

    def list_custody_events(self, headers, params=None):
        return self._request("GET", "/agencies/custody-events", headers=headers, params=params)

    def get_custody_event(self, event_id, headers):
        return self._request("GET", f"/agencies/custody-events/{event_id}", headers=headers)


api_client = ApiClient()
