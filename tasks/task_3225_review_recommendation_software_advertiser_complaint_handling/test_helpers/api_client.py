"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Ops / logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/platform/_clock/set_current_utc", payload, headers)

    # --- Users ---
    def create_user(self, payload, headers):
        return self._request("POST", "/platform/users", payload, headers)

    def list_users(self, headers, params=None):
        return self._request("GET", "/platform/users", headers=headers, params=params)

    def get_user(self, user_id, headers):
        return self._request("GET", f"/platform/users/{user_id}", headers=headers)

    def list_user_reviews(self, user_id, headers):
        return self._request("GET", f"/platform/users/{user_id}/reviews", headers=headers)

    def list_user_identity_requests(self, user_id, headers):
        return self._request("GET", f"/platform/users/{user_id}/identity-requests", headers=headers)

    def suspend_user(self, user_id, headers):
        return self._request("POST", f"/platform/users/{user_id}/suspend", {}, headers)

    def purge_user(self, user_id, headers):
        return self._request("POST", f"/platform/users/{user_id}/purge", {}, headers)

    def adjust_trust(self, user_id, payload, headers):
        return self._request("POST", f"/platform/users/{user_id}/trust-adjustments", payload, headers)

    # --- Business pages ---
    def create_business_page(self, payload, headers):
        return self._request("POST", "/platform/business-pages", payload, headers)

    def list_business_pages(self, headers, params=None):
        return self._request("GET", "/platform/business-pages", headers=headers, params=params)

    def get_business_page(self, page_id, headers):
        return self._request("GET", f"/platform/business-pages/{page_id}", headers=headers)

    def update_business_page(self, page_id, payload, headers):
        return self._request("PATCH", f"/platform/business-pages/{page_id}", payload, headers)

    def close_business_page(self, page_id, headers):
        return self._request("POST", f"/platform/business-pages/{page_id}/close", {}, headers)

    def list_page_reviews(self, page_id, headers, params=None):
        return self._request("GET", f"/platform/business-pages/{page_id}/reviews", headers=headers, params=params)

    def list_page_claims(self, page_id, headers):
        return self._request("GET", f"/platform/business-pages/{page_id}/claims", headers=headers)

    def list_page_complaints(self, page_id, headers):
        return self._request("GET", f"/platform/business-pages/{page_id}/complaints", headers=headers)

    def list_page_solicitation_cases(self, page_id, headers):
        return self._request("GET", f"/platform/business-pages/{page_id}/solicitation-cases", headers=headers)

    def list_page_consumer_alerts(self, page_id, headers):
        return self._request("GET", f"/platform/business-pages/{page_id}/consumer-alerts", headers=headers)

    # --- Reviews ---
    def create_review(self, page_id, payload, headers):
        return self._request("POST", f"/platform/business-pages/{page_id}/reviews", payload, headers)

    def list_reviews(self, headers, params=None):
        return self._request("GET", "/platform/reviews", headers=headers, params=params)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/platform/reviews/{review_id}", headers=headers)

    def edit_review(self, review_id, payload, headers):
        return self._request("PATCH", f"/platform/reviews/{review_id}", payload, headers)

    def evaluate_review(self, review_id, headers):
        return self._request("POST", f"/platform/reviews/{review_id}/evaluate", {}, headers)

    # --- Page claims ---
    def create_page_claim(self, page_id, payload, headers):
        return self._request("POST", f"/platform/business-pages/{page_id}/claims", payload, headers)

    def list_page_claims_global(self, headers, params=None):
        return self._request("GET", "/platform/page-claims", headers=headers, params=params)

    def get_page_claim(self, claim_id, headers):
        return self._request("GET", f"/platform/page-claims/{claim_id}", headers=headers)

    def verify_page_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/platform/page-claims/{claim_id}/verify", payload, headers)

    def approve_page_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/platform/page-claims/{claim_id}/approve", payload, headers)

    def reject_page_claim(self, claim_id, headers):
        return self._request("POST", f"/platform/page-claims/{claim_id}/reject", {}, headers)

    # --- Ad accounts ---
    def create_ad_account(self, page_id, payload, headers):
        return self._request("POST", f"/platform/business-pages/{page_id}/ad-account", payload, headers)

    def list_ad_accounts(self, headers, params=None):
        return self._request("GET", "/platform/ad-accounts", headers=headers, params=params)

    def get_ad_account(self, account_id, headers):
        return self._request("GET", f"/platform/ad-accounts/{account_id}", headers=headers)

    def suspend_ad_account(self, account_id, headers):
        return self._request("POST", f"/platform/ad-accounts/{account_id}/suspend", {}, headers)

    def reactivate_ad_account(self, account_id, headers):
        return self._request("POST", f"/platform/ad-accounts/{account_id}/reactivate", {}, headers)

    def close_ad_account(self, account_id, headers):
        return self._request("POST", f"/platform/ad-accounts/{account_id}/close", {}, headers)

    def list_account_campaigns(self, account_id, headers):
        return self._request("GET", f"/platform/ad-accounts/{account_id}/campaigns", headers=headers)

    def list_account_impressions(self, account_id, headers):
        return self._request("GET", f"/platform/ad-accounts/{account_id}/impressions", headers=headers)

    def list_account_call_events(self, account_id, headers):
        return self._request("GET", f"/platform/ad-accounts/{account_id}/call-events", headers=headers)

    def list_account_attribution_reports(self, account_id, headers):
        return self._request("GET", f"/platform/ad-accounts/{account_id}/attribution-reports", headers=headers)

    # --- Campaigns ---
    def create_campaign(self, account_id, payload, headers):
        return self._request("POST", f"/platform/ad-accounts/{account_id}/campaigns", payload, headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/platform/ad-campaigns", headers=headers, params=params)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/platform/ad-campaigns/{campaign_id}", headers=headers)

    def activate_campaign(self, campaign_id, headers):
        return self._request("POST", f"/platform/ad-campaigns/{campaign_id}/activate", {}, headers)

    def pause_campaign(self, campaign_id, headers):
        return self._request("POST", f"/platform/ad-campaigns/{campaign_id}/pause", {}, headers)

    def cancel_campaign(self, campaign_id, headers):
        return self._request("POST", f"/platform/ad-campaigns/{campaign_id}/cancel", {}, headers)

    # --- Impressions / calls / reports ---
    def create_impression(self, account_id, payload, headers):
        return self._request("POST", f"/platform/ad-accounts/{account_id}/impressions", payload, headers)

    def list_impression_events(self, headers, params=None):
        return self._request("GET", "/platform/ad-impression-events", headers=headers, params=params)

    def get_impression_event(self, event_id, headers):
        return self._request("GET", f"/platform/ad-impression-events/{event_id}", headers=headers)

    def create_call_event(self, account_id, payload, headers):
        return self._request("POST", f"/platform/ad-accounts/{account_id}/call-events", payload, headers)

    def list_call_track_events(self, headers, params=None):
        return self._request("GET", "/platform/call-track-events", headers=headers, params=params)

    def get_call_track_event(self, event_id, headers):
        return self._request("GET", f"/platform/call-track-events/{event_id}", headers=headers)

    def create_attribution_report(self, account_id, payload, headers):
        return self._request("POST", f"/platform/ad-accounts/{account_id}/attribution-reports", payload, headers)

    def list_attribution_reports(self, headers, params=None):
        return self._request("GET", "/platform/attribution-reports", headers=headers, params=params)

    def get_attribution_report(self, report_id, headers):
        return self._request("GET", f"/platform/attribution-reports/{report_id}", headers=headers)

    # --- Complaints ---
    def create_complaint(self, page_id, payload, headers):
        return self._request("POST", f"/platform/business-pages/{page_id}/complaints", payload, headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/platform/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/platform/complaints/{complaint_id}", headers=headers)

    def start_review_complaint(self, complaint_id, headers):
        return self._request("POST", f"/platform/complaints/{complaint_id}/start-review", {}, headers)

    def escalate_complaint(self, complaint_id, headers):
        return self._request("POST", f"/platform/complaints/{complaint_id}/escalate", {}, headers)

    def resolve_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/platform/complaints/{complaint_id}/resolve", payload, headers)

    def reject_complaint(self, complaint_id, headers):
        return self._request("POST", f"/platform/complaints/{complaint_id}/reject", {}, headers)

    # --- Solicitation cases ---
    def create_solicitation_case(self, page_id, payload, headers):
        return self._request("POST", f"/platform/business-pages/{page_id}/solicitation-cases", payload, headers)

    def list_solicitation_cases(self, headers, params=None):
        return self._request("GET", "/platform/solicitation-cases", headers=headers, params=params)

    def get_solicitation_case(self, case_id, headers):
        return self._request("GET", f"/platform/solicitation-cases/{case_id}", headers=headers)

    def investigate_case(self, case_id, headers):
        return self._request("POST", f"/platform/solicitation-cases/{case_id}/investigate", {}, headers)

    def confirm_case(self, case_id, headers):
        return self._request("POST", f"/platform/solicitation-cases/{case_id}/confirm", {}, headers)

    def dismiss_case(self, case_id, headers):
        return self._request("POST", f"/platform/solicitation-cases/{case_id}/dismiss", {}, headers)

    # --- Consumer alerts ---
    def create_consumer_alert(self, page_id, payload, headers):
        return self._request("POST", f"/platform/business-pages/{page_id}/consumer-alerts", payload, headers)

    def list_consumer_alerts(self, headers, params=None):
        return self._request("GET", "/platform/consumer-alerts", headers=headers, params=params)

    def get_consumer_alert(self, alert_id, headers):
        return self._request("GET", f"/platform/consumer-alerts/{alert_id}", headers=headers)

    def lift_consumer_alert(self, alert_id, headers):
        return self._request("POST", f"/platform/consumer-alerts/{alert_id}/lift", {}, headers)

    # --- Identity requests ---
    def create_identity_request(self, payload, headers):
        return self._request("POST", "/platform/identity-requests", payload, headers)

    def list_identity_requests(self, headers, params=None):
        return self._request("GET", "/platform/identity-requests", headers=headers, params=params)

    def get_identity_request(self, request_id, headers):
        return self._request("GET", f"/platform/identity-requests/{request_id}", headers=headers)

    def start_review_identity_request(self, request_id, headers):
        return self._request("POST", f"/platform/identity-requests/{request_id}/start-review", {}, headers)

    def send_notice_identity_request(self, request_id, headers):
        return self._request("POST", f"/platform/identity-requests/{request_id}/send-notice", {}, headers)

    def release_identity_request(self, request_id, headers):
        return self._request("POST", f"/platform/identity-requests/{request_id}/release", {}, headers)

    def decline_identity_request(self, request_id, headers):
        return self._request("POST", f"/platform/identity-requests/{request_id}/decline", {}, headers)

    def withdraw_identity_request(self, request_id, headers):
        return self._request("POST", f"/platform/identity-requests/{request_id}/withdraw", {}, headers)

    # --- Merge requests ---
    def create_merge_request(self, payload, headers):
        return self._request("POST", "/platform/merge-requests", payload, headers)

    def list_merge_requests(self, headers, params=None):
        return self._request("GET", "/platform/merge-requests", headers=headers, params=params)

    def get_merge_request(self, merge_request_id, headers):
        return self._request("GET", f"/platform/merge-requests/{merge_request_id}", headers=headers)

    def execute_merge_request(self, merge_request_id, payload, headers):
        return self._request("POST", f"/platform/merge-requests/{merge_request_id}/execute", payload, headers)

    def reject_merge_request(self, merge_request_id, headers):
        return self._request("POST", f"/platform/merge-requests/{merge_request_id}/reject", {}, headers)


api_client = ApiClient()
