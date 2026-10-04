"""API client: one method per endpoint in the service contract.

All paths are mounted under the `/api` prefix described in the PRD.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Employer ─────────────────────────────────────
    def create_employer(self, payload, headers):
        return self._request("POST", "/api/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/api/employers/{employer_id}", headers=headers)

    def suspend_employer(self, employer_id, payload, headers):
        return self._request("POST", f"/api/employers/{employer_id}/suspend", payload, headers)

    def reinstate_employer(self, employer_id, headers):
        return self._request("POST", f"/api/employers/{employer_id}/reinstate", headers=headers)

    def list_employer_campaigns(self, employer_id, headers, params=None):
        return self._request("GET", f"/api/employers/{employer_id}/campaigns",
                             headers=headers, params=params)

    # ─── JobSeeker ────────────────────────────────────
    def create_job_seeker(self, payload, headers):
        return self._request("POST", "/api/job-seekers", payload, headers)

    def get_job_seeker(self, seeker_id, headers):
        return self._request("GET", f"/api/job-seekers/{seeker_id}", headers=headers)

    def list_seeker_alert_subscriptions(self, seeker_id, headers, params=None):
        return self._request("GET", f"/api/job-seekers/{seeker_id}/alert-subscriptions",
                             headers=headers, params=params)

    def get_seeker_matches(self, seeker_id, headers, params=None):
        return self._request("GET", f"/api/job-seekers/{seeker_id}/matches",
                             headers=headers, params=params)

    def list_seeker_applications(self, seeker_id, headers, params=None):
        return self._request("GET", f"/api/job-seekers/{seeker_id}/applications",
                             headers=headers, params=params)

    # ─── Campaign ─────────────────────────────────────
    def create_campaign(self, payload, headers):
        return self._request("POST", "/api/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/api/campaigns/{campaign_id}", headers=headers)

    def activate_campaign(self, campaign_id, headers):
        return self._request("POST", f"/api/campaigns/{campaign_id}/activate", headers=headers)

    def pause_campaign(self, campaign_id, headers):
        return self._request("POST", f"/api/campaigns/{campaign_id}/pause", headers=headers)

    def resume_campaign(self, campaign_id, headers):
        return self._request("POST", f"/api/campaigns/{campaign_id}/resume", headers=headers)

    def list_campaign_events(self, campaign_id, headers, params=None):
        return self._request("GET", f"/api/campaigns/{campaign_id}/events",
                             headers=headers, params=params)

    def list_campaign_budget_ledger(self, campaign_id, headers, params=None):
        return self._request("GET", f"/api/campaigns/{campaign_id}/budget-ledger",
                             headers=headers, params=params)

    # ─── SponsoredJob ─────────────────────────────────
    def create_sponsored_job(self, payload, headers):
        return self._request("POST", "/api/sponsored-jobs", payload, headers)

    def list_sponsored_jobs(self, headers, params=None):
        return self._request("GET", "/api/sponsored-jobs", headers=headers, params=params)

    def get_sponsored_job(self, sponsored_job_id, headers):
        return self._request("GET", f"/api/sponsored-jobs/{sponsored_job_id}", headers=headers)

    def create_pacing_hold(self, sponsored_job_id, payload, headers):
        return self._request("POST", f"/api/sponsored-jobs/{sponsored_job_id}/pacing-holds",
                             payload, headers)

    def resume_sponsored_job(self, sponsored_job_id, headers):
        return self._request("POST", f"/api/sponsored-jobs/{sponsored_job_id}/resume",
                             headers=headers)

    def list_pacing_holds(self, sponsored_job_id, headers, params=None):
        return self._request("GET", f"/api/sponsored-jobs/{sponsored_job_id}/pacing-holds",
                             headers=headers, params=params)

    # ─── JobPosting ───────────────────────────────────
    def create_job_posting(self, payload, headers):
        return self._request("POST", "/api/job-postings", payload, headers)

    def list_job_postings(self, headers, params=None):
        return self._request("GET", "/api/job-postings", headers=headers, params=params)

    def get_job_posting(self, posting_id, headers):
        return self._request("GET", f"/api/job-postings/{posting_id}", headers=headers)

    def ingest_job_posting_version(self, posting_id, payload, headers):
        return self._request("POST", f"/api/job-postings/{posting_id}/versions",
                             payload, headers)

    def list_job_posting_versions(self, posting_id, headers, params=None):
        return self._request("GET", f"/api/job-postings/{posting_id}/versions",
                             headers=headers, params=params)

    def list_posting_assessments(self, posting_id, headers, params=None):
        return self._request("GET", f"/api/job-postings/{posting_id}/assessments",
                             headers=headers, params=params)

    # ─── Assessment ───────────────────────────────────
    def create_assessment(self, payload, headers):
        return self._request("POST", "/api/assessments", payload, headers)

    # ─── Application ──────────────────────────────────
    def create_application(self, payload, headers):
        return self._request("POST", "/api/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/api/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/api/applications/{application_id}", headers=headers)

    def complete_application(self, application_id, payload, headers):
        return self._request("POST", f"/api/applications/{application_id}/complete",
                             payload, headers)

    def close_application(self, application_id, headers):
        return self._request("POST", f"/api/applications/{application_id}/close",
                             headers=headers)

    def disposition_application(self, application_id, payload, headers):
        return self._request("POST", f"/api/applications/{application_id}/disposition",
                             payload, headers)

    def list_application_apply_events(self, application_id, headers, params=None):
        return self._request("GET", f"/api/applications/{application_id}/apply-events",
                             headers=headers, params=params)

    # ─── Sponsor events / billing ─────────────────────
    def record_event(self, payload, headers):
        return self._request("POST", "/api/events", payload, headers)

    def refund_event(self, event_id, payload, headers):
        return self._request("POST", f"/api/events/{event_id}/refund", payload, headers)

    # ─── Alerts ───────────────────────────────────────
    def create_alert_subscription(self, payload, headers):
        return self._request("POST", "/api/job-alert-subscriptions", payload, headers)

    def dispatch_alerts(self, payload, headers):
        return self._request("POST", "/api/alerts/dispatch", payload, headers)

    # ─── Logical clock ────────────────────────────────
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)


api_client = ApiClient()