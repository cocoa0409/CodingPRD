"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- platform clock (test-driving) ------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/ugc/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- users -------------------------------------------------------------
    def create_user(self, payload, headers):
        return self._request("POST", "/ugc/users", payload, headers)

    def get_user(self, user_id, headers):
        return self._request("GET", f"/ugc/users/{user_id}", headers=headers)

    def list_users(self, headers, params=None):
        return self._request("GET", "/ugc/users", headers=headers, params=params)

    def suspend_user(self, user_id, payload, headers):
        return self._request("POST", f"/ugc/users/{user_id}/suspend", payload, headers)

    def reinstate_user(self, user_id, headers):
        return self._request("POST", f"/ugc/users/{user_id}/reinstate", {}, headers)

    def set_parental_controls(self, user_id, payload, headers):
        return self._request(
            "POST", f"/ugc/users/{user_id}/parental-controls", payload, headers
        )

    def get_parental_controls(self, user_id, headers, params=None):
        return self._request(
            "GET", f"/ugc/users/{user_id}/parental-controls", headers=headers, params=params
        )

    # ---- identity & tax ------------------------------------------------------
    def create_identity_verification(self, user_id, payload, headers):
        return self._request(
            "POST", f"/ugc/users/{user_id}/identity-verifications", payload, headers
        )

    def list_identity_verifications(self, user_id, headers, params=None):
        return self._request(
            "GET", f"/ugc/users/{user_id}/identity-verifications", headers=headers, params=params
        )

    def verify_identity(self, iv_id, headers):
        return self._request("POST", f"/ugc/identity-verifications/{iv_id}/verify", {}, headers)

    def reject_identity(self, iv_id, payload, headers):
        return self._request(
            "POST", f"/ugc/identity-verifications/{iv_id}/reject", payload, headers
        )

    def create_tax_document(self, user_id, payload, headers):
        return self._request("POST", f"/ugc/users/{user_id}/tax-documents", payload, headers)

    def list_tax_documents(self, user_id, headers, params=None):
        return self._request(
            "GET", f"/ugc/users/{user_id}/tax-documents", headers=headers, params=params
        )

    def accept_tax_document(self, tax_id, headers):
        return self._request("POST", f"/ugc/tax-documents/{tax_id}/accept", {}, headers)

    def reject_tax_document(self, tax_id, payload, headers):
        return self._request("POST", f"/ugc/tax-documents/{tax_id}/reject", payload, headers)

    # ---- experiences ---------------------------------------------------------
    def create_experience(self, payload, headers):
        return self._request("POST", "/ugc/experiences", payload, headers)

    def get_experience(self, exp_id, headers):
        return self._request("GET", f"/ugc/experiences/{exp_id}", headers=headers)

    def list_experiences(self, headers, params=None):
        return self._request("GET", "/ugc/experiences", headers=headers, params=params)

    def submit_experience_for_review(self, exp_id, headers):
        return self._request(
            "POST", f"/ugc/experiences/{exp_id}/submit-for-review", {}, headers
        )

    def suspend_experience(self, exp_id, payload, headers):
        return self._request("POST", f"/ugc/experiences/{exp_id}/suspend", payload, headers)

    def republish_experience(self, exp_id, headers):
        return self._request("POST", f"/ugc/experiences/{exp_id}/republish", {}, headers)

    def archive_experience(self, exp_id, headers):
        return self._request("POST", f"/ugc/experiences/{exp_id}/archive", {}, headers)

    def list_experience_age_ratings(self, exp_id, headers, params=None):
        return self._request(
            "GET", f"/ugc/experiences/{exp_id}/age-ratings", headers=headers, params=params
        )

    def list_experience_chat_messages(self, exp_id, headers, params=None):
        return self._request(
            "GET", f"/ugc/experiences/{exp_id}/chat-messages", headers=headers, params=params
        )

    # ---- moderation submissions ------------------------------------------------
    def create_moderation_submission(self, payload, headers):
        return self._request("POST", "/ugc/moderation-submissions", payload, headers)

    def get_moderation_submission(self, sub_id, headers):
        return self._request("GET", f"/ugc/moderation-submissions/{sub_id}", headers=headers)

    def list_moderation_submissions(self, headers, params=None):
        return self._request("GET", "/ugc/moderation-submissions", headers=headers, params=params)

    def decide_moderation_submission(self, sub_id, payload, headers):
        return self._request(
            "POST", f"/ugc/moderation-submissions/{sub_id}/decide", payload, headers
        )

    def inject_moderation_score(self, submission_id, score, headers):
        return self._request(
            "POST",
            "/ugc/_moderation/inject_score",
            {"submission_id": submission_id, "score": score},
            headers,
        )

    # ---- moderation appeals --------------------------------------------------
    def create_moderation_appeal(self, payload, headers):
        return self._request("POST", "/ugc/moderation-appeals", payload, headers)

    def get_moderation_appeal(self, appeal_id, headers):
        return self._request("GET", f"/ugc/moderation-appeals/{appeal_id}", headers=headers)

    def list_moderation_appeals(self, headers, params=None):
        return self._request("GET", "/ugc/moderation-appeals", headers=headers, params=params)

    def start_appeal_review(self, appeal_id, headers):
        return self._request(
            "POST", f"/ugc/moderation-appeals/{appeal_id}/start-review", {}, headers
        )

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/ugc/moderation-appeals/{appeal_id}/decide", payload, headers)

    def withdraw_appeal(self, appeal_id, headers):
        return self._request("POST", f"/ugc/moderation-appeals/{appeal_id}/withdraw", {}, headers)

    # ---- currency purchase orders ---------------------------------------------
    def create_currency_purchase_order(self, payload, headers):
        return self._request("POST", "/ugc/currency-purchase-orders", payload, headers)

    def get_currency_purchase_order(self, order_id, headers):
        return self._request("GET", f"/ugc/currency-purchase-orders/{order_id}", headers=headers)

    def list_currency_purchase_orders(self, headers, params=None):
        return self._request("GET", "/ugc/currency-purchase-orders", headers=headers, params=params)

    def confirm_currency_payment(self, order_id, headers):
        return self._request(
            "POST", f"/ugc/currency-purchase-orders/{order_id}/confirm-payment", {}, headers
        )

    def fail_currency_payment(self, order_id, headers):
        return self._request(
            "POST", f"/ugc/currency-purchase-orders/{order_id}/fail-payment", {}, headers
        )

    def refund_currency_purchase_order(self, order_id, headers):
        return self._request(
            "POST", f"/ugc/currency-purchase-orders/{order_id}/refund", {}, headers
        )

    # ---- marketplace items -----------------------------------------------------
    def create_marketplace_item(self, payload, headers):
        return self._request("POST", "/ugc/marketplace-items", payload, headers)

    def get_marketplace_item(self, item_id, headers):
        return self._request("GET", f"/ugc/marketplace-items/{item_id}", headers=headers)

    def list_marketplace_items(self, headers, params=None):
        return self._request("GET", "/ugc/marketplace-items", headers=headers, params=params)

    def submit_marketplace_item(self, item_id, headers):
        return self._request("POST", f"/ugc/marketplace-items/{item_id}/submit", {}, headers)

    def take_item_off_sale(self, item_id, headers):
        return self._request(
            "POST", f"/ugc/marketplace-items/{item_id}/take-off-sale", {}, headers
        )

    def put_item_on_sale(self, item_id, headers):
        return self._request(
            "POST", f"/ugc/marketplace-items/{item_id}/put-on-sale", {}, headers
        )

    # ---- resale listings ---------------------------------------------------------
    def create_resale_listing(self, payload, headers):
        return self._request("POST", "/ugc/resale-listings", payload, headers)

    def get_resale_listing(self, listing_id, headers):
        return self._request("GET", f"/ugc/resale-listings/{listing_id}", headers=headers)

    def list_resale_listings(self, headers, params=None):
        return self._request("GET", "/ugc/resale-listings", headers=headers, params=params)

    def cancel_resale_listing(self, listing_id, headers):
        return self._request("POST", f"/ugc/resale-listings/{listing_id}/cancel", {}, headers)

    # ---- purchase orders ---------------------------------------------------------
    def create_purchase_order(self, payload, headers):
        return self._request("POST", "/ugc/purchase-orders", payload, headers)

    def get_purchase_order(self, order_id, headers):
        return self._request("GET", f"/ugc/purchase-orders/{order_id}", headers=headers)

    def list_purchase_orders(self, headers, params=None):
        return self._request("GET", "/ugc/purchase-orders", headers=headers, params=params)

    def confirm_purchase_order(self, order_id, headers):
        return self._request("POST", f"/ugc/purchase-orders/{order_id}/confirm", {}, headers)

    def refund_purchase_order(self, order_id, headers):
        return self._request("POST", f"/ugc/purchase-orders/{order_id}/refund", {}, headers)

    # ---- devex requests ----------------------------------------------------------
    def create_devex_request(self, payload, headers):
        return self._request("POST", "/ugc/devex-requests", payload, headers)

    def get_devex_request(self, req_id, headers):
        return self._request("GET", f"/ugc/devex-requests/{req_id}", headers=headers)

    def list_devex_requests(self, headers, params=None):
        return self._request("GET", "/ugc/devex-requests", headers=headers, params=params)

    def approve_devex_request(self, req_id, headers):
        return self._request("POST", f"/ugc/devex-requests/{req_id}/approve", {}, headers)

    def reject_devex_request(self, req_id, payload, headers):
        return self._request("POST", f"/ugc/devex-requests/{req_id}/reject", payload, headers)

    def mark_devex_paid(self, req_id, headers):
        return self._request("POST", f"/ugc/devex-requests/{req_id}/mark-paid", {}, headers)

    def cancel_devex_request(self, req_id, headers):
        return self._request("POST", f"/ugc/devex-requests/{req_id}/cancel", {}, headers)

    # ---- chat & reports ----------------------------------------------------------
    def send_chat_message(self, exp_id, payload, headers):
        return self._request("POST", f"/ugc/experiences/{exp_id}/chat-messages", payload, headers)

    def get_chat_message(self, msg_id, headers):
        return self._request("GET", f"/ugc/chat-messages/{msg_id}", headers=headers)

    def list_chat_messages(self, headers, params=None):
        return self._request("GET", "/ugc/chat-messages", headers=headers, params=params)

    def create_report(self, msg_id, payload, headers):
        return self._request("POST", f"/ugc/chat-messages/{msg_id}/reports", payload, headers)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/ugc/reports/{report_id}", headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/ugc/reports", headers=headers, params=params)

    def triage_report(self, report_id, headers):
        return self._request("POST", f"/ugc/reports/{report_id}/triage", {}, headers)

    def action_report(self, report_id, payload, headers):
        return self._request("POST", f"/ugc/reports/{report_id}/action", payload, headers)

    def dismiss_report(self, report_id, headers):
        return self._request("POST", f"/ugc/reports/{report_id}/dismiss", {}, headers)

    # ---- account terminations ------------------------------------------------------
    def create_account_termination(self, payload, headers):
        return self._request("POST", "/ugc/account-terminations", payload, headers)

    def get_account_termination(self, term_id, headers):
        return self._request("GET", f"/ugc/account-terminations/{term_id}", headers=headers)

    def list_account_terminations(self, headers, params=None):
        return self._request("GET", "/ugc/account-terminations", headers=headers, params=params)

    def dispose_earnings(self, term_id, headers):
        return self._request(
            "POST", f"/ugc/account-terminations/{term_id}/dispose-earnings", {}, headers
        )

    # ---- engagement -----------------------------------------------------------------
    def post_engagement_snapshot(self, exp_id, payload, headers):
        return self._request(
            "POST", f"/ugc/experiences/{exp_id}/engagement-snapshots", payload, headers
        )

    def list_engagement_snapshots(self, exp_id, headers, params=None):
        return self._request(
            "GET", f"/ugc/experiences/{exp_id}/engagement-snapshots", headers=headers, params=params
        )

    def settle_monthly_engagement(self, headers):
        return self._request("POST", "/ugc/_engagement/settle_monthly", {}, headers)

    # ---- reverse-reachability reads --------------------------------------------------
    def get_experience_age_rating(self, rating_id, headers):
        return self._request("GET", f"/ugc/experience-age-ratings/{rating_id}", headers=headers)

    def list_experience_age_ratings_all(self, headers, params=None):
        return self._request("GET", "/ugc/experience-age-ratings", headers=headers, params=params)

    def get_audit_log(self, log_id, headers):
        return self._request("GET", f"/ugc/audit-logs/{log_id}", headers=headers)

    def list_audit_logs(self, headers, params=None):
        return self._request("GET", "/ugc/audit-logs", headers=headers, params=params)


api_client = ApiClient()
