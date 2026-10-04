"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock / infra ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/storefront/_clock/set_current_utc", payload, headers)

    # --- developer accounts ---
    def create_developer_account(self, payload, headers):
        return self._request("POST", "/storefront/developer-accounts", payload, headers)

    def get_developer_account(self, account_id, headers):
        return self._request("GET", f"/storefront/developer-accounts/{account_id}", headers=headers)

    def list_developer_accounts(self, headers, params=None):
        return self._request("GET", "/storefront/developer-accounts", headers=headers, params=params)

    def submit_payment_info(self, account_id, payload, headers):
        return self._request("POST", f"/storefront/developer-accounts/{account_id}/payment-info", payload, headers)

    def activate_developer(self, account_id, headers):
        return self._request("POST", f"/storefront/developer-accounts/{account_id}/activate", {}, headers)

    def suspend_developer(self, account_id, headers):
        return self._request("POST", f"/storefront/developer-accounts/{account_id}/suspend", {}, headers)

    def unsuspend_developer(self, account_id, headers):
        return self._request("POST", f"/storefront/developer-accounts/{account_id}/unsuspend", {}, headers)

    def terminate_developer(self, account_id, headers):
        return self._request("POST", f"/storefront/developer-accounts/{account_id}/terminate", {}, headers)

    # --- titles ---
    def create_title(self, payload, headers):
        return self._request("POST", "/storefront/titles", payload, headers)

    def get_title(self, title_id, headers):
        return self._request("GET", f"/storefront/titles/{title_id}", headers=headers)

    def list_titles(self, headers, params=None):
        return self._request("GET", "/storefront/titles", headers=headers, params=params)

    def patch_title(self, title_id, payload, headers):
        return self._request("PATCH", f"/storefront/titles/{title_id}", payload, headers)

    def submit_title_review(self, title_id, headers):
        return self._request("POST", f"/storefront/titles/{title_id}/submit-review", {}, headers)

    def schedule_release(self, title_id, payload, headers):
        return self._request("POST", f"/storefront/titles/{title_id}/schedule-release", payload, headers)

    def cancel_release(self, title_id, headers):
        return self._request("POST", f"/storefront/titles/{title_id}/cancel-release", {}, headers)

    def release_now(self, title_id, headers):
        return self._request("POST", f"/storefront/titles/{title_id}/release-now", {}, headers)

    def delist_title(self, title_id, headers):
        return self._request("POST", f"/storefront/titles/{title_id}/delist", {}, headers)

    def adjust_title_revenue(self, title_id, payload, headers):
        return self._request("POST", f"/storefront/titles/{title_id}/adjustments", payload, headers)

    def get_pricing_recommendation(self, title_id, headers, params=None):
        return self._request("GET", f"/storefront/titles/{title_id}/pricing-recommendation", headers=headers, params=params)

    def list_title_reviews(self, title_id, headers, params=None):
        return self._request("GET", f"/storefront/titles/{title_id}/reviews", headers=headers, params=params)

    def list_title_key_batches(self, title_id, headers, params=None):
        return self._request("GET", f"/storefront/titles/{title_id}/key-batches", headers=headers, params=params)

    def list_title_workshop_items(self, title_id, headers, params=None):
        return self._request("GET", f"/storefront/titles/{title_id}/workshop-items", headers=headers, params=params)

    def list_title_review_bomb_windows(self, title_id, headers, params=None):
        return self._request("GET", f"/storefront/titles/{title_id}/review-bomb-windows", headers=headers, params=params)

    def list_title_regional_prices(self, title_id, headers, params=None):
        return self._request("GET", f"/storefront/titles/{title_id}/regional-prices", headers=headers, params=params)

    def list_title_store_page_reviews(self, title_id, headers, params=None):
        return self._request("GET", f"/storefront/titles/{title_id}/store-page-reviews", headers=headers, params=params)

    # --- store page reviews ---
    def list_store_page_reviews(self, headers, params=None):
        return self._request("GET", "/storefront/store-page-reviews", headers=headers, params=params)

    def get_store_page_review(self, review_id, headers):
        return self._request("GET", f"/storefront/store-page-reviews/{review_id}", headers=headers)

    def approve_store_page_review(self, review_id, headers):
        return self._request("POST", f"/storefront/store-page-reviews/{review_id}/approve", {}, headers)

    def reject_store_page_review(self, review_id, payload, headers):
        return self._request("POST", f"/storefront/store-page-reviews/{review_id}/reject", payload, headers)

    # --- regional pricing ---
    def create_regional_price(self, payload, headers):
        return self._request("POST", "/storefront/regional-prices", payload, headers)

    def get_regional_price(self, override_id, headers):
        return self._request("GET", f"/storefront/regional-prices/{override_id}", headers=headers)

    def withdraw_regional_price(self, override_id, headers):
        return self._request("POST", f"/storefront/regional-prices/{override_id}/withdraw", {}, headers)

    # --- key batches / keys ---
    def create_key_batch(self, payload, headers):
        return self._request("POST", "/storefront/key-batches", payload, headers)

    def get_key_batch(self, batch_id, headers):
        return self._request("GET", f"/storefront/key-batches/{batch_id}", headers=headers)

    def list_key_batches(self, headers, params=None):
        return self._request("GET", "/storefront/key-batches", headers=headers, params=params)

    def list_batch_keys(self, batch_id, headers, params=None):
        return self._request("GET", f"/storefront/key-batches/{batch_id}/keys", headers=headers, params=params)

    def get_key(self, key_id, headers):
        return self._request("GET", f"/storefront/keys/{key_id}", headers=headers)

    def list_keys(self, headers, params=None):
        return self._request("GET", "/storefront/keys", headers=headers, params=params)

    def list_user_keys(self, user_id, headers, params=None):
        return self._request("GET", f"/storefront/user-accounts/{user_id}/keys", headers=headers, params=params)

    def approve_key_batch(self, batch_id, headers):
        return self._request("POST", f"/storefront/key-batches/{batch_id}/approve", {}, headers)

    def reject_key_batch(self, batch_id, headers):
        return self._request("POST", f"/storefront/key-batches/{batch_id}/reject", {}, headers)

    def redeem_key(self, payload, headers):
        return self._request("POST", "/storefront/keys/redeem", payload, headers)

    # --- user accounts ---
    def create_user_account(self, payload, headers):
        return self._request("POST", "/storefront/user-accounts", payload, headers)

    def get_user_account(self, user_id, headers):
        return self._request("GET", f"/storefront/user-accounts/{user_id}", headers=headers)

    def list_user_accounts(self, headers, params=None):
        return self._request("GET", "/storefront/user-accounts", headers=headers, params=params)

    def restrict_user(self, user_id, headers):
        return self._request("POST", f"/storefront/user-accounts/{user_id}/restrict", {}, headers)

    def unrestrict_user(self, user_id, headers):
        return self._request("POST", f"/storefront/user-accounts/{user_id}/unrestrict", {}, headers)

    def ban_user(self, user_id, headers):
        return self._request("POST", f"/storefront/user-accounts/{user_id}/ban", {}, headers)

    def list_user_purchases(self, user_id, headers, params=None):
        return self._request("GET", f"/storefront/user-accounts/{user_id}/purchases", headers=headers, params=params)

    def list_user_reviews(self, user_id, headers, params=None):
        return self._request("GET", f"/storefront/user-accounts/{user_id}/reviews", headers=headers, params=params)

    def list_user_workshop_sales(self, user_id, headers, params=None):
        return self._request("GET", f"/storefront/user-accounts/{user_id}/workshop-sales", headers=headers, params=params)

    # --- purchases ---
    def create_purchase(self, payload, headers):
        return self._request("POST", "/storefront/purchases", payload, headers)

    def get_purchase(self, purchase_id, headers):
        return self._request("GET", f"/storefront/purchases/{purchase_id}", headers=headers)

    def list_purchases(self, headers, params=None):
        return self._request("GET", "/storefront/purchases", headers=headers, params=params)

    def record_playtime(self, purchase_id, payload, headers):
        return self._request("POST", f"/storefront/purchases/{purchase_id}/playtime", payload, headers)

    # --- refunds ---
    def create_refund_request(self, payload, headers):
        return self._request("POST", "/storefront/refund-requests", payload, headers)

    def get_refund_request(self, refund_id, headers):
        return self._request("GET", f"/storefront/refund-requests/{refund_id}", headers=headers)

    def list_refund_requests(self, headers, params=None):
        return self._request("GET", "/storefront/refund-requests", headers=headers, params=params)

    def approve_refund_request(self, refund_id, headers):
        return self._request("POST", f"/storefront/refund-requests/{refund_id}/approve", {}, headers)

    def deny_refund_request(self, refund_id, payload, headers):
        return self._request("POST", f"/storefront/refund-requests/{refund_id}/deny", payload, headers)

    # --- reviews ---
    def create_review(self, payload, headers):
        return self._request("POST", "/storefront/reviews", payload, headers)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/storefront/reviews/{review_id}", headers=headers)

    def remove_review(self, review_id, headers):
        return self._request("POST", f"/storefront/reviews/{review_id}/remove", {}, headers)

    # --- review bomb windows ---
    def get_review_bomb_window(self, window_id, headers):
        return self._request("GET", f"/storefront/review-bomb-windows/{window_id}", headers=headers)

    def list_review_bomb_windows(self, headers, params=None):
        return self._request("GET", "/storefront/review-bomb-windows", headers=headers, params=params)

    def close_review_bomb_window(self, window_id, headers):
        return self._request("POST", f"/storefront/review-bomb-windows/{window_id}/close", {}, headers)

    # --- workshop ---
    def create_workshop_item(self, payload, headers):
        return self._request("POST", "/storefront/workshop-items", payload, headers)

    def get_workshop_item(self, item_id, headers):
        return self._request("GET", f"/storefront/workshop-items/{item_id}", headers=headers)

    def list_workshop_items(self, headers, params=None):
        return self._request("GET", "/storefront/workshop-items", headers=headers, params=params)

    def publish_workshop_item(self, item_id, headers):
        return self._request("POST", f"/storefront/workshop-items/{item_id}/publish", {}, headers)

    def remove_workshop_item(self, item_id, headers):
        return self._request("POST", f"/storefront/workshop-items/{item_id}/remove", {}, headers)

    def create_workshop_sale(self, payload, headers):
        return self._request("POST", "/storefront/workshop-sales", payload, headers)

    def get_workshop_sale(self, sale_id, headers):
        return self._request("GET", f"/storefront/workshop-sales/{sale_id}", headers=headers)

    def list_workshop_sales(self, headers, params=None):
        return self._request("GET", "/storefront/workshop-sales", headers=headers, params=params)


api_client = ApiClient()
