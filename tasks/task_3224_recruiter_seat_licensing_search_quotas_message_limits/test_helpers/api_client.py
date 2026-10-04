"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Contracts ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def activate_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/activate", payload, headers)

    def suspend_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/suspend", headers=headers)

    def resume_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/resume", headers=headers)

    # --- Seats ---
    def list_seats(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/seats", headers=headers, params=params)

    def get_seat_in_contract(self, contract_id, seat_id, headers):
        return self._request("GET", f"/contracts/{contract_id}/seats/{seat_id}", headers=headers)

    def get_seat(self, seat_id, headers):
        return self._request("GET", f"/seats/{seat_id}", headers=headers)

    def assign_seat(self, contract_id, seat_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/seats/{seat_id}/assign", payload, headers)

    def unassign_seat(self, contract_id, seat_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/seats/{seat_id}/unassign", headers=headers)

    def suspend_seat(self, contract_id, seat_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/seats/{seat_id}/suspend", headers=headers)

    def resume_seat(self, contract_id, seat_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/seats/{seat_id}/resume", headers=headers)

    # --- Recruiters ---
    def create_recruiter(self, payload, headers):
        return self._request("POST", "/recruiters", payload, headers)

    def get_recruiter(self, recruiter_id, headers):
        return self._request("GET", f"/recruiters/{recruiter_id}", headers=headers)

    def list_recruiters(self, headers, params=None):
        return self._request("GET", "/recruiters", headers=headers, params=params)

    def deactivate_recruiter(self, recruiter_id, headers):
        return self._request("POST", f"/recruiters/{recruiter_id}/deactivate", headers=headers)

    # --- Seat-scoped introspection ---
    def list_seat_projects(self, seat_id, headers, params=None):
        return self._request("GET", f"/seats/{seat_id}/projects", headers=headers, params=params)

    def list_seat_job_postings(self, seat_id, headers, params=None):
        return self._request("GET", f"/seats/{seat_id}/job-postings", headers=headers, params=params)

    def list_quota_ledgers(self, seat_id, headers, params=None):
        return self._request("GET", f"/seats/{seat_id}/quota-ledgers", headers=headers, params=params)

    def list_credit_pools(self, seat_id, headers, params=None):
        return self._request("GET", f"/seats/{seat_id}/credit-pools", headers=headers, params=params)

    def list_seat_messages(self, seat_id, headers, params=None):
        return self._request("GET", f"/seats/{seat_id}/messages", headers=headers, params=params)

    # --- Candidate profiles & search ---
    def create_candidate_profile(self, payload, headers):
        return self._request("POST", "/candidate-profiles", payload, headers)

    def get_candidate_profile(self, candidate_id, headers):
        return self._request("GET", f"/candidate-profiles/{candidate_id}", headers=headers)

    def list_candidate_messages(self, candidate_id, headers, params=None):
        return self._request("GET", f"/candidate-profiles/{candidate_id}/messages", headers=headers, params=params)

    def candidate_search(self, seat_id, payload, headers):
        return self._request("POST", f"/seats/{seat_id}/candidate-search", payload, headers)

    # --- Projects ---
    def create_project(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/projects", payload, headers)

    def get_project_in_contract(self, contract_id, project_id, headers):
        return self._request("GET", f"/contracts/{contract_id}/projects/{project_id}", headers=headers)

    def list_projects(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def open_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/open", headers=headers)

    def hold_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/hold", headers=headers)

    def close_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/close", headers=headers)

    # --- Messages ---
    def send_message(self, seat_id, payload, headers):
        return self._request("POST", f"/seats/{seat_id}/messages", payload, headers)

    def get_message(self, message_id, headers):
        return self._request("GET", f"/messages/{message_id}", headers=headers)

    def list_messages(self, headers, params=None):
        return self._request("GET", "/messages", headers=headers, params=params)

    def record_response(self, message_id, payload, headers):
        return self._request("POST", f"/messages/{message_id}/record-response", payload, headers)

    # --- Job postings & promoted slots ---
    def create_job_posting(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/job-postings", payload, headers)

    def get_job_posting_in_contract(self, contract_id, job_posting_id, headers):
        return self._request("GET", f"/contracts/{contract_id}/job-postings/{job_posting_id}", headers=headers)

    def list_job_postings(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/job-postings", headers=headers, params=params)

    def get_job_posting(self, job_posting_id, headers):
        return self._request("GET", f"/job-postings/{job_posting_id}", headers=headers)

    def activate_job_posting(self, contract_id, job_posting_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/job-postings/{job_posting_id}/activate", headers=headers)

    def pause_job_posting(self, contract_id, job_posting_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/job-postings/{job_posting_id}/pause", headers=headers)

    def resume_job_posting(self, contract_id, job_posting_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/job-postings/{job_posting_id}/resume", headers=headers)

    def close_job_posting(self, contract_id, job_posting_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/job-postings/{job_posting_id}/close", headers=headers)

    def create_promoted_slot(self, contract_id, job_posting_id, payload, headers):
        return self._request(
            "POST",
            f"/contracts/{contract_id}/job-postings/{job_posting_id}/promoted-slots",
            payload,
            headers,
        )

    def list_promoted_slots(self, contract_id, job_posting_id, headers, params=None):
        return self._request(
            "GET",
            f"/contracts/{contract_id}/job-postings/{job_posting_id}/promoted-slots",
            headers=headers,
            params=params,
        )

    def list_promoted_slots_top_level(self, job_posting_id, headers, params=None):
        return self._request("GET", f"/job-postings/{job_posting_id}/promoted-slots", headers=headers, params=params)

    def record_spend(self, contract_id, job_posting_id, payload, headers):
        return self._request(
            "POST",
            f"/contracts/{contract_id}/job-postings/{job_posting_id}/record-spend",
            payload,
            headers,
        )

    # --- ATS integrations & sync records ---
    def create_ats_integration(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/ats-integrations", payload, headers)

    def get_ats_integration(self, contract_id, integration_id, headers):
        return self._request("GET", f"/contracts/{contract_id}/ats-integrations/{integration_id}", headers=headers)

    def get_ats_integration_top_level(self, integration_id, headers):
        return self._request("GET", f"/ats-integrations/{integration_id}", headers=headers)

    def list_ats_integrations(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/ats-integrations", headers=headers, params=params)

    def connect_ats_integration(self, contract_id, integration_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/ats-integrations/{integration_id}/connect", headers=headers)

    def disable_ats_integration(self, contract_id, integration_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/ats-integrations/{integration_id}/disable", headers=headers)

    def create_ats_sync_record(self, payload, headers):
        return self._request("POST", "/ats-sync-records", payload, headers)

    def get_ats_sync_record(self, record_id, headers):
        return self._request("GET", f"/ats-sync-records/{record_id}", headers=headers)

    def list_ats_sync_records(self, headers, params=None):
        return self._request("GET", "/ats-sync-records", headers=headers, params=params)

    # --- Talent insights ---
    def create_talent_insight(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/talent-insights", payload, headers)

    def get_talent_insight(self, contract_id, report_id, headers):
        return self._request("GET", f"/contracts/{contract_id}/talent-insights/{report_id}", headers=headers)

    def list_talent_insights(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/talent-insights", headers=headers, params=params)

    def generate_talent_insight(self, contract_id, report_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/talent-insights/{report_id}/generate", headers=headers)

    def publish_talent_insight(self, contract_id, report_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/talent-insights/{report_id}/publish", headers=headers)

    # --- Renewal events ---
    def create_renewal_event(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/renewal-events", payload, headers)

    def get_renewal_event(self, renewal_event_id, headers):
        return self._request("GET", f"/renewal-events/{renewal_event_id}", headers=headers)

    def list_renewal_events(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/renewal-events", headers=headers, params=params)

    def approve_renewal_event(self, renewal_event_id, headers):
        return self._request("POST", f"/renewal-events/{renewal_event_id}/approve", headers=headers)

    def reject_renewal_event(self, renewal_event_id, headers):
        return self._request("POST", f"/renewal-events/{renewal_event_id}/reject", headers=headers)

    def apply_renewal_event(self, renewal_event_id, headers):
        return self._request("POST", f"/renewal-events/{renewal_event_id}/apply", headers=headers)

    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
