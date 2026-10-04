"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- specialty societies ---
    def create_specialty_society(self, payload, headers):
        return self._request("POST", "/cpt/specialty-societies", payload, headers)

    def list_specialty_societies(self, headers, params=None):
        return self._request("GET", "/cpt/specialty-societies", headers=headers, params=params)

    def get_specialty_society(self, society_id, headers):
        return self._request("GET", f"/cpt/specialty-societies/{society_id}", headers=headers)

    def assign_specialty_society_seats(self, society_id, payload, headers):
        return self._request("POST", f"/cpt/specialty-societies/{society_id}/seat-assignments", payload, headers)

    def list_society_applicants(self, society_id, headers, params=None):
        return self._request("GET", f"/cpt/specialty-societies/{society_id}/applicants", headers=headers, params=params)

    def list_society_code_changes(self, society_id, headers, params=None):
        return self._request("GET", f"/cpt/specialty-societies/{society_id}/code-changes", headers=headers, params=params)

    def list_society_value_recommendations(self, society_id, headers, params=None):
        return self._request("GET", f"/cpt/specialty-societies/{society_id}/value-recommendations", headers=headers, params=params)

    # --- applicants ---
    def create_applicant(self, payload, headers):
        return self._request("POST", "/cpt/applicants", payload, headers)

    def list_applicants(self, headers, params=None):
        return self._request("GET", "/cpt/applicants", headers=headers, params=params)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/cpt/applicants/{applicant_id}", headers=headers)

    # --- code changes ---
    def create_code_change(self, payload, headers):
        return self._request("POST", "/cpt/code-changes", payload, headers)

    def list_code_changes(self, headers, params=None):
        return self._request("GET", "/cpt/code-changes", headers=headers, params=params)

    def get_code_change(self, change_id, headers):
        return self._request("GET", f"/cpt/code-changes/{change_id}", headers=headers)

    def administrative_return_code_change(self, change_id, payload, headers):
        return self._request("POST", f"/cpt/code-changes/{change_id}/administrative-returns", payload, headers)

    def post_code_change(self, change_id, payload, headers):
        return self._request("POST", f"/cpt/code-changes/{change_id}/postings", payload, headers)

    def return_code_change(self, change_id, payload, headers):
        return self._request("POST", f"/cpt/code-changes/{change_id}/returns", payload, headers)

    def supplementary_report_code_change(self, change_id, payload, headers):
        return self._request("POST", f"/cpt/code-changes/{change_id}/supplementary-reports", payload, headers)

    def refer_code_change(self, change_id, payload, headers):
        return self._request("POST", f"/cpt/code-changes/{change_id}/referrals", payload, headers)

    def determine_code_change(self, change_id, payload, headers):
        return self._request("POST", f"/cpt/code-changes/{change_id}/determinations", payload, headers)

    def revert_code_change_to_draft(self, change_id, payload, headers):
        return self._request("POST", f"/cpt/code-changes/{change_id}/revert-to-draft", payload, headers)

    def withdraw_code_change(self, change_id, payload, headers):
        return self._request("DELETE", f"/cpt/code-changes/{change_id}", payload, headers)

    def list_change_committee_reviews(self, change_id, headers, params=None):
        return self._request("GET", f"/cpt/code-changes/{change_id}/committee-reviews", headers=headers, params=params)

    def list_change_code_values(self, change_id, headers, params=None):
        return self._request("GET", f"/cpt/code-changes/{change_id}/code-values", headers=headers, params=params)

    # --- advisory committee reviews ---
    def create_advisory_committee_review(self, payload, headers):
        return self._request("POST", "/cpt/advisory-committee-reviews", payload, headers)

    def list_advisory_committee_reviews(self, headers, params=None):
        return self._request("GET", "/cpt/advisory-committee-reviews", headers=headers, params=params)

    def get_advisory_committee_review(self, review_id, headers):
        return self._request("GET", f"/cpt/advisory-committee-reviews/{review_id}", headers=headers)

    def get_committee_review(self, review_id, headers):
        return self._request("GET", f"/cpt/committee-reviews/{review_id}", headers=headers)

    def decide_committee_review(self, review_id, payload, headers):
        return self._request("POST", f"/cpt/committee-reviews/{review_id}/decisions", payload, headers)

    def record_committee_comment_consideration(self, review_id, payload, headers):
        return self._request("POST", f"/cpt/advisory-committee-reviews/{review_id}/comment-records", payload, headers)

    # --- meetings ---
    def create_meeting(self, payload, headers):
        return self._request("POST", "/cpt/meetings", payload, headers)

    def list_meetings(self, headers, params=None):
        return self._request("GET", "/cpt/meetings", headers=headers, params=params)

    def get_meeting(self, meeting_id, headers):
        return self._request("GET", f"/cpt/meetings/{meeting_id}", headers=headers)

    def set_meeting_agenda(self, meeting_id, payload, headers):
        return self._request("POST", f"/cpt/meetings/{meeting_id}/agenda", payload, headers)

    def open_meeting_comment_window(self, meeting_id, payload, headers):
        return self._request("POST", f"/cpt/meetings/{meeting_id}/comment-windows", payload, headers)

    def close_meeting_comment_window(self, meeting_id, headers):
        return self._request("POST", f"/cpt/meetings/{meeting_id}/comment-closures", {}, headers)

    def reverse_meeting_comment_window(self, meeting_id, payload, headers):
        return self._request("POST", f"/cpt/meetings/{meeting_id}/comment-window-reversals", payload, headers)

    def open_meeting(self, meeting_id, headers):
        return self._request("POST", f"/cpt/meetings/{meeting_id}/openings", {}, headers)

    def recess_meeting(self, meeting_id, payload, headers):
        return self._request("POST", f"/cpt/meetings/{meeting_id}/recesses", payload, headers)

    def reopen_meeting(self, meeting_id, headers):
        return self._request("POST", f"/cpt/meetings/{meeting_id}/reopenings", {}, headers)

    def open_addendum(self, meeting_id, payload, headers):
        return self._request("POST", f"/cpt/meetings/{meeting_id}/addenda", payload, headers)

    def close_addendum(self, meeting_id, headers):
        return self._request("POST", f"/cpt/meetings/{meeting_id}/addendum-closures", {}, headers)

    def close_meeting(self, meeting_id, headers):
        return self._request("POST", f"/cpt/meetings/{meeting_id}/closures", {}, headers)

    def list_meeting_votes(self, meeting_id, headers, params=None):
        return self._request("GET", f"/cpt/meetings/{meeting_id}/votes", headers=headers, params=params)

    # --- public comments ---
    def create_public_comment(self, payload, headers):
        return self._request("POST", "/cpt/public-comments", payload, headers)

    def list_public_comments(self, headers, params=None):
        return self._request("GET", "/cpt/public-comments", headers=headers, params=params)

    def get_public_comment(self, comment_id, headers):
        return self._request("GET", f"/cpt/public-comments/{comment_id}", headers=headers)

    def withdraw_public_comment(self, comment_id, payload, headers):
        return self._request("POST", f"/cpt/public-comments/{comment_id}/withdrawals", payload, headers)

    # --- editorial votes ---
    def create_editorial_vote(self, payload, headers):
        return self._request("POST", "/cpt/editorial-votes", payload, headers)

    def list_editorial_votes(self, headers, params=None):
        return self._request("GET", "/cpt/editorial-votes", headers=headers, params=params)

    def get_editorial_vote(self, vote_id, headers):
        return self._request("GET", f"/cpt/editorial-votes/{vote_id}", headers=headers)

    # --- value recommendations ---
    def create_value_recommendation(self, payload, headers):
        return self._request("POST", "/cpt/ruc-value-recommendations", payload, headers)

    def list_value_recommendations(self, headers, params=None):
        return self._request("GET", "/cpt/ruc-value-recommendations", headers=headers, params=params)

    def get_value_recommendation(self, recommendation_id, headers):
        return self._request("GET", f"/cpt/ruc-value-recommendations/{recommendation_id}", headers=headers)

    def vote_value_recommendation(self, recommendation_id, payload, headers):
        return self._request("POST", f"/cpt/ruc-value-recommendations/{recommendation_id}/votes", payload, headers)

    def publish_value_recommendation(self, recommendation_id, payload, headers):
        return self._request("POST", f"/cpt/ruc-value-recommendations/{recommendation_id}/recommendations", payload, headers)

    def refuse_value_recommendation(self, recommendation_id, payload, headers):
        return self._request("POST", f"/cpt/ruc-value-recommendations/{recommendation_id}/refusals", payload, headers)

    def forward_value_recommendation(self, recommendation_id, headers):
        return self._request("POST", f"/cpt/ruc-value-recommendations/{recommendation_id}/forwards", {}, headers)

    def release_value_recommendation(self, recommendation_id, payload, headers):
        return self._request("POST", f"/cpt/ruc-value-recommendations/{recommendation_id}/releases", payload, headers)

    def reconsider_value_recommendation(self, recommendation_id, payload, headers):
        return self._request("POST", f"/cpt/ruc-value-recommendations/{recommendation_id}/reconsiderations", payload, headers)

    # --- code values ---
    def create_code_value(self, payload, headers):
        return self._request("POST", "/cpt/code-values", payload, headers)

    def list_code_values(self, headers, params=None):
        return self._request("GET", "/cpt/code-values", headers=headers, params=params)

    def get_code_value(self, code_value_id, headers):
        return self._request("GET", f"/cpt/code-values/{code_value_id}", headers=headers)

    def restamp_code_value_effective_date(self, code_value_id, payload, headers):
        return self._request("POST", f"/cpt/code-values/{code_value_id}/effective-dates", payload, headers)

    def supersede_code_value(self, code_value_id, payload, headers):
        return self._request("POST", f"/cpt/code-values/{code_value_id}/supersessions", payload, headers)

    # --- release cycles ---
    def create_release_cycle(self, payload, headers):
        return self._request("POST", "/cpt/release-cycles", payload, headers)

    def list_release_cycles(self, headers, params=None):
        return self._request("GET", "/cpt/release-cycles", headers=headers, params=params)

    def get_release_cycle(self, cycle_id, headers):
        return self._request("GET", f"/cpt/release-cycles/{cycle_id}", headers=headers)

    def submit_release_cycle_changes(self, cycle_id, payload, headers):
        return self._request("POST", f"/cpt/release-cycles/{cycle_id}/submissions", payload, headers)

    def open_release_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cpt/release-cycles/{cycle_id}/openings", {}, headers)

    def return_release_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/cpt/release-cycles/{cycle_id}/returns", payload, headers)

    def close_release_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cpt/release-cycles/{cycle_id}/closures", {}, headers)

    def release_release_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cpt/release-cycles/{cycle_id}/releases", {}, headers)

    def list_release_cycle_code_changes(self, cycle_id, headers, params=None):
        return self._request("GET", f"/cpt/release-cycles/{cycle_id}/code-changes", headers=headers, params=params)

    # --- errata ---
    def create_errata_notice(self, payload, headers):
        return self._request("POST", "/cpt/errata-notices", payload, headers)

    def list_errata_notices(self, headers, params=None):
        return self._request("GET", "/cpt/errata-notices", headers=headers, params=params)

    def get_errata_notice(self, notice_id, headers):
        return self._request("GET", f"/cpt/errata-notices/{notice_id}", headers=headers)

    def publish_errata_notice(self, notice_id, headers):
        return self._request("POST", f"/cpt/errata-notices/{notice_id}/publications", {}, headers)

    def withdraw_errata_notice(self, notice_id, payload, headers):
        return self._request("POST", f"/cpt/errata-notices/{notice_id}/withdrawals", payload, headers)

    def list_code_value_errata_notices(self, code_value_id, headers, params=None):
        return self._request("GET", f"/cpt/code-values/{code_value_id}/errata-notices", headers=headers, params=params)

    def create_errata_review(self, payload, headers):
        return self._request("POST", "/cpt/errata-reviews", payload, headers)

    def list_errata_reviews(self, headers, params=None):
        return self._request("GET", "/cpt/errata-reviews", headers=headers, params=params)

    def get_errata_review(self, review_id, headers):
        return self._request("GET", f"/cpt/errata-reviews/{review_id}", headers=headers)

    def decide_errata_review_outcome(self, review_id, payload, headers):
        return self._request("POST", f"/cpt/errata-reviews/{review_id}/outcomes", payload, headers)

    def list_errata_notice_reviews(self, notice_id, headers, params=None):
        return self._request("GET", f"/cpt/errata-notices/{notice_id}/reviews", headers=headers, params=params)

    # --- distribution territories ---
    def create_distribution_territory(self, payload, headers):
        return self._request("POST", "/cpt/distribution-territories", payload, headers)

    def list_distribution_territories(self, headers, params=None):
        return self._request("GET", "/cpt/distribution-territories", headers=headers, params=params)

    def get_distribution_territory(self, territory_id, headers):
        return self._request("GET", f"/cpt/distribution-territories/{territory_id}", headers=headers)

    def reserve_distribution_territory(self, territory_id, payload, headers):
        return self._request("POST", f"/cpt/distribution-territories/{territory_id}/reservations", payload, headers)

    def correct_distribution_territory_method(self, territory_id, payload, headers):
        return self._request("POST", f"/cpt/distribution-territories/{territory_id}/method-corrections", payload, headers)

    def withdraw_distribution_territory(self, territory_id, payload, headers):
        return self._request("POST", f"/cpt/distribution-territories/{territory_id}/withdrawals", payload, headers)

    def list_territory_licensing_agreements(self, territory_id, headers, params=None):
        return self._request("GET", f"/cpt/distribution-territories/{territory_id}/licensing-agreements", headers=headers, params=params)

    # --- licensing agreements ---
    def create_licensing_agreement(self, payload, headers):
        return self._request("POST", "/cpt/licensing-agreements", payload, headers)

    def list_licensing_agreements(self, headers, params=None):
        return self._request("GET", "/cpt/licensing-agreements", headers=headers, params=params)

    def get_licensing_agreement(self, license_id, headers):
        return self._request("GET", f"/cpt/licensing-agreements/{license_id}", headers=headers)

    def activate_licensing_agreement(self, license_id, headers):
        return self._request("POST", f"/cpt/licensing-agreements/{license_id}/activations", {}, headers)

    def suspend_licensing_agreement(self, license_id, payload, headers):
        return self._request("POST", f"/cpt/licensing-agreements/{license_id}/suspensions", payload, headers)

    def reactivate_licensing_agreement(self, license_id, headers):
        return self._request("POST", f"/cpt/licensing-agreements/{license_id}/reactivations", {}, headers)

    def terminate_licensing_agreement(self, license_id, payload, headers):
        return self._request("POST", f"/cpt/licensing-agreements/{license_id}/terminations", payload, headers)

    def list_license_delivery_orders(self, license_id, headers, params=None):
        return self._request("GET", f"/cpt/licensing-agreements/{license_id}/content-delivery-orders", headers=headers, params=params)

    def list_license_education_activities(self, license_id, headers, params=None):
        return self._request("GET", f"/cpt/licensing-agreements/{license_id}/education-activities", headers=headers, params=params)

    def list_license_interpretation_requests(self, license_id, headers, params=None):
        return self._request("GET", f"/cpt/licensing-agreements/{license_id}/interpretation-requests", headers=headers, params=params)

    # --- content delivery orders ---
    def create_content_delivery_order(self, payload, headers):
        return self._request("POST", "/cpt/content-delivery-orders", payload, headers)

    def list_content_delivery_orders(self, headers, params=None):
        return self._request("GET", "/cpt/content-delivery-orders", headers=headers, params=params)

    def get_content_delivery_order(self, order_id, headers):
        return self._request("GET", f"/cpt/content-delivery-orders/{order_id}", headers=headers)

    def mark_delivery_ready(self, order_id, payload, headers):
        return self._request("POST", f"/cpt/content-delivery-orders/{order_id}/readiness", payload, headers)

    def release_delivery(self, order_id, headers):
        return self._request("POST", f"/cpt/content-delivery-orders/{order_id}/releases", {}, headers)

    def withdraw_delivery(self, order_id, payload, headers):
        return self._request("POST", f"/cpt/content-delivery-orders/{order_id}/withdrawals", payload, headers)

    # --- education activities ---
    def create_education_activity(self, payload, headers):
        return self._request("POST", "/cpt/education-activities", payload, headers)

    def list_education_activities(self, headers, params=None):
        return self._request("GET", "/cpt/education-activities", headers=headers, params=params)

    def get_education_activity(self, activity_id, headers):
        return self._request("GET", f"/cpt/education-activities/{activity_id}", headers=headers)

    def complete_education_activity(self, activity_id, headers):
        return self._request("POST", f"/cpt/education-activities/{activity_id}/completions", {}, headers)

    # --- interpretation requests ---
    def create_interpretation_request(self, payload, headers):
        return self._request("POST", "/cpt/interpretation-requests", payload, headers)

    def list_interpretation_requests(self, headers, params=None):
        return self._request("GET", "/cpt/interpretation-requests", headers=headers, params=params)

    def get_interpretation_request(self, request_id, headers):
        return self._request("GET", f"/cpt/interpretation-requests/{request_id}", headers=headers)

    def answer_interpretation_request(self, request_id, payload, headers):
        return self._request("POST", f"/cpt/interpretation-requests/{request_id}/answers", payload, headers)

    # --- test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/cpt/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()