"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Editors ---
    def create_editor(self, payload, headers):
        return self._request("POST", "/wiki/editors", payload, headers)

    def get_editor(self, editor_id, headers):
        return self._request("GET", f"/wiki/editors/{editor_id}", headers=headers)

    def list_editors(self, headers, params=None):
        return self._request("GET", "/wiki/editors", headers=headers, params=params)

    def suspend_editor(self, editor_id, headers):
        return self._request("POST", f"/wiki/editors/{editor_id}/suspend", headers=headers)

    def reinstate_editor(self, editor_id, headers):
        return self._request("POST", f"/wiki/editors/{editor_id}/reinstate", headers=headers)

    def block_editor(self, editor_id, headers):
        return self._request("POST", f"/wiki/editors/{editor_id}/block", headers=headers)

    def disclose_coi(self, editor_id, payload, headers):
        return self._request("POST", f"/wiki/editors/{editor_id}/disclose-coi", payload, headers)

    # --- Pages ---
    def create_page(self, payload, headers):
        return self._request("POST", "/wiki/pages", payload, headers)

    def get_page(self, page_id, headers):
        return self._request("GET", f"/wiki/pages/{page_id}", headers=headers)

    def list_pages(self, headers, params=None):
        return self._request("GET", "/wiki/pages", headers=headers, params=params)

    # --- Revisions ---
    def create_revision(self, page_id, payload, headers):
        return self._request("POST", f"/wiki/pages/{page_id}/revisions", payload, headers)

    def get_revision(self, revision_id, headers):
        return self._request("GET", f"/wiki/revisions/{revision_id}", headers=headers)

    def list_revisions(self, headers, params=None):
        return self._request("GET", "/wiki/revisions", headers=headers, params=params)

    def accept_revision(self, revision_id, payload, headers):
        return self._request("POST", f"/wiki/revisions/{revision_id}/accept", payload, headers)

    def flag_revision(self, revision_id, payload, headers):
        return self._request("POST", f"/wiki/revisions/{revision_id}/flag", payload, headers)

    def revert_revision(self, revision_id, payload, headers):
        return self._request("POST", f"/wiki/revisions/{revision_id}/revert", payload, headers)

    # --- Disputes ---
    def create_dispute(self, page_id, payload, headers):
        return self._request("POST", f"/wiki/pages/{page_id}/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/wiki/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/wiki/disputes", headers=headers, params=params)

    def escalate_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/wiki/disputes/{dispute_id}/escalate", payload, headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/wiki/disputes/{dispute_id}/resolve", payload, headers)

    def close_dispute(self, dispute_id, headers):
        return self._request("POST", f"/wiki/disputes/{dispute_id}/close", headers=headers)

    # --- Protection Requests ---
    def create_protection_request(self, page_id, payload, headers):
        return self._request("POST", f"/wiki/pages/{page_id}/protection-requests", payload, headers)

    def get_protection_request(self, request_id, headers):
        return self._request("GET", f"/wiki/protection-requests/{request_id}", headers=headers)

    def list_protection_requests(self, headers, params=None):
        return self._request("GET", "/wiki/protection-requests", headers=headers, params=params)

    def approve_protection_request(self, request_id, headers):
        return self._request("POST", f"/wiki/protection-requests/{request_id}/approve", headers=headers)

    def deny_protection_request(self, request_id, headers):
        return self._request("POST", f"/wiki/protection-requests/{request_id}/deny", headers=headers)

    # --- Vandalism Reports ---
    def get_vandalism_report(self, report_id, headers):
        return self._request("GET", f"/wiki/vandalism-reports/{report_id}", headers=headers)

    def list_vandalism_reports(self, headers, params=None):
        return self._request("GET", "/wiki/vandalism-reports", headers=headers, params=params)

    def confirm_vandalism_report(self, report_id, headers):
        return self._request("POST", f"/wiki/vandalism-reports/{report_id}/confirm", headers=headers)

    def dismiss_vandalism_report(self, report_id, headers):
        return self._request("POST", f"/wiki/vandalism-reports/{report_id}/dismiss", headers=headers)

    # --- Campaigns ---
    def create_campaign(self, payload, headers):
        return self._request("POST", "/wiki/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/wiki/campaigns/{campaign_id}", headers=headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/wiki/campaigns", headers=headers, params=params)

    def activate_campaign(self, campaign_id, payload, headers):
        return self._request("POST", f"/wiki/campaigns/{campaign_id}/activate", payload, headers)

    def pause_campaign(self, campaign_id, payload, headers):
        return self._request("POST", f"/wiki/campaigns/{campaign_id}/pause", payload, headers)

    def complete_campaign(self, campaign_id, payload, headers):
        return self._request("POST", f"/wiki/campaigns/{campaign_id}/complete", payload, headers)

    def cancel_campaign(self, campaign_id, payload, headers):
        return self._request("POST", f"/wiki/campaigns/{campaign_id}/cancel", payload, headers)

    # --- Banners ---
    def create_banner(self, campaign_id, payload, headers):
        return self._request("POST", f"/wiki/campaigns/{campaign_id}/banners", payload, headers)

    def get_banner(self, banner_id, headers):
        return self._request("GET", f"/wiki/banners/{banner_id}", headers=headers)

    def list_banners(self, headers, params=None):
        return self._request("GET", "/wiki/banners", headers=headers, params=params)

    def record_impression(self, banner_id, payload, headers):
        return self._request("POST", f"/wiki/banners/{banner_id}/impressions", payload, headers)

    def list_impressions(self, headers, params=None):
        return self._request("GET", "/wiki/impressions", headers=headers, params=params)

    def get_impression(self, impression_id, headers):
        return self._request("GET", f"/wiki/impressions/{impression_id}", headers=headers)

    # --- Donations ---
    def create_donation(self, campaign_id, payload, headers):
        return self._request("POST", f"/wiki/campaigns/{campaign_id}/donations", payload, headers)

    def get_donation(self, donation_id, headers):
        return self._request("GET", f"/wiki/donations/{donation_id}", headers=headers)

    def list_donations(self, headers, params=None):
        return self._request("GET", "/wiki/donations", headers=headers, params=params)

    def process_donation(self, donation_id, headers):
        return self._request("POST", f"/wiki/donations/{donation_id}/process", headers=headers)

    def fail_donation(self, donation_id, headers):
        return self._request("POST", f"/wiki/donations/{donation_id}/fail", headers=headers)

    def refund_donation(self, donation_id, headers):
        return self._request("POST", f"/wiki/donations/{donation_id}/refund", headers=headers)

    # --- Grants ---
    def create_grant_program(self, payload, headers):
        return self._request("POST", "/wiki/grant-programs", payload, headers)

    def get_grant_program(self, program_id, headers):
        return self._request("GET", f"/wiki/grant-programs/{program_id}", headers=headers)

    def list_grant_programs(self, headers, params=None):
        return self._request("GET", "/wiki/grant-programs", headers=headers, params=params)

    def close_grant_program(self, program_id, payload, headers):
        return self._request("POST", f"/wiki/grant-programs/{program_id}/close", payload, headers)

    def create_grant_application(self, program_id, payload, headers):
        return self._request("POST", f"/wiki/grant-programs/{program_id}/applications", payload, headers)

    def get_grant_application(self, application_id, headers):
        return self._request("GET", f"/wiki/grant-applications/{application_id}", headers=headers)

    def list_grant_applications(self, headers, params=None):
        return self._request("GET", "/wiki/grant-applications", headers=headers, params=params)

    def start_review_grant_application(self, application_id, headers):
        return self._request("POST", f"/wiki/grant-applications/{application_id}/start-review", headers=headers)

    def score_grant_application(self, application_id, payload, headers):
        return self._request("POST", f"/wiki/grant-applications/{application_id}/score", payload, headers)

    def approve_grant_application(self, application_id, payload, headers):
        return self._request("POST", f"/wiki/grant-applications/{application_id}/approve", payload, headers)

    def reject_grant_application(self, application_id, headers):
        return self._request("POST", f"/wiki/grant-applications/{application_id}/reject", headers=headers)

    def withdraw_grant_application(self, application_id, headers):
        return self._request("POST", f"/wiki/grant-applications/{application_id}/withdraw", headers=headers)

    # --- Legal Requests ---
    def create_legal_request(self, payload, headers):
        return self._request("POST", "/wiki/legal-requests", payload, headers)

    def get_legal_request(self, request_id, headers):
        return self._request("GET", f"/wiki/legal-requests/{request_id}", headers=headers)

    def list_legal_requests(self, headers, params=None):
        return self._request("GET", "/wiki/legal-requests", headers=headers, params=params)

    def start_review_legal_request(self, request_id, headers):
        return self._request("POST", f"/wiki/legal-requests/{request_id}/start-review", headers=headers)

    def comply_legal_request(self, request_id, headers):
        return self._request("POST", f"/wiki/legal-requests/{request_id}/comply", headers=headers)

    def partially_comply_legal_request(self, request_id, headers):
        return self._request("POST", f"/wiki/legal-requests/{request_id}/partially-comply", headers=headers)

    def reject_legal_request(self, request_id, headers):
        return self._request("POST", f"/wiki/legal-requests/{request_id}/reject", headers=headers)

    # --- Transparency Reports ---
    def create_transparency_report(self, payload, headers):
        return self._request("POST", "/wiki/transparency-reports", payload, headers)

    def get_transparency_report(self, report_id, headers):
        return self._request("GET", f"/wiki/transparency-reports/{report_id}", headers=headers)

    def list_transparency_reports(self, headers, params=None):
        return self._request("GET", "/wiki/transparency-reports", headers=headers, params=params)

    def publish_transparency_report(self, report_id, payload, headers):
        return self._request("POST", f"/wiki/transparency-reports/{report_id}/publish", payload, headers)


api_client = ApiClient()
