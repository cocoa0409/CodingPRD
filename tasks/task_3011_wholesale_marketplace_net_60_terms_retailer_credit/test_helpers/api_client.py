"""API client: one method per row of the PRD §4 endpoint table.

Subclasses GenericApiClient; the base _request() does the HTTP work and returns
the raw requests.Response so tests can assert status codes directly.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Logical clock ----------------
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---------------- Retailers ----------------
    def create_retailer(self, payload: Dict[str, Any],
                        headers: Optional[Dict[str, str]] = None):
        return self._request("POST", "/wholesale/retailers", payload, headers)

    def list_retailers(self, headers: Optional[Dict[str, str]] = None,
                       params: Optional[Dict] = None):
        return self._request("GET", "/wholesale/retailers", headers=headers, params=params)

    def get_retailer(self, retailer_id: str,
                     headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/wholesale/retailers/{retailer_id}", headers=headers)

    def review_document(self, retailer_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/wholesale/retailers/{retailer_id}/documents/review",
            payload, headers,
        )

    def verify_retailer(self, retailer_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/wholesale/retailers/{retailer_id}/verify", payload, headers
        )

    def request_more_info(self, retailer_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/wholesale/retailers/{retailer_id}/request-more-info",
            payload, headers,
        )

    def resubmit_verification(self, retailer_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/wholesale/retailers/{retailer_id}/verification/resubmit",
            payload, headers,
        )

    # ---------------- Brands ----------------
    def create_brand(self, payload: Dict[str, Any],
                     headers: Optional[Dict[str, str]] = None):
        return self._request("POST", "/wholesale/brands", payload, headers)

    def list_brands(self, headers: Optional[Dict[str, str]] = None,
                    params: Optional[Dict] = None):
        return self._request("GET", "/wholesale/brands", headers=headers, params=params)

    def get_brand(self, brand_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/wholesale/brands/{brand_id}", headers=headers)

    def activate_brand(self, brand_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/wholesale/brands/{brand_id}/activate", {}, headers
        )

    def reinstate_brand(self, brand_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/wholesale/brands/{brand_id}/reinstate", {}, headers
        )

    # ---------------- Credit accounts ----------------
    def create_credit_account(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/wholesale/credit-accounts", payload, headers)

    def list_credit_accounts(self, headers: Optional[Dict[str, str]] = None,
                             params: Optional[Dict] = None):
        return self._request(
            "GET", "/wholesale/credit-accounts", headers=headers, params=params
        )

    def get_credit_account(self, account_id: str,
                           headers: Optional[Dict[str, str]] = None):
        return self._request(
            "GET", f"/wholesale/credit-accounts/{account_id}", headers=headers
        )

    def limit_review(self, account_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/wholesale/credit-accounts/{account_id}/limit-review",
            payload, headers,
        )

    def unfreeze_credit_account(self, account_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/wholesale/credit-accounts/{account_id}/unfreeze", {}, headers
        )

    def close_credit_account(self, account_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/wholesale/credit-accounts/{account_id}/close", {}, headers
        )

    # ---------------- Orders and lines ----------------
    def create_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/wholesale/orders", payload, headers)

    def list_orders(self, headers: Optional[Dict[str, str]] = None,
                    params: Optional[Dict] = None):
        return self._request("GET", "/wholesale/orders", headers=headers, params=params)

    def get_order(self, order_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/wholesale/orders/{order_id}", headers=headers)

    def list_order_lines(self, order_id: str,
                         headers: Optional[Dict[str, str]] = None,
                         params: Optional[Dict] = None):
        return self._request(
            "GET", f"/wholesale/orders/{order_id}/lines", headers=headers,
            params=params,
        )

    def get_order_invoice(self, order_id: str,
                          headers: Optional[Dict[str, str]] = None):
        return self._request(
            "GET", f"/wholesale/orders/{order_id}/invoice", headers=headers
        )

    def list_order_return_authorizations(self, order_id: str,
                                         headers: Optional[Dict[str, str]] = None,
                                         params: Optional[Dict] = None):
        return self._request(
            "GET", f"/wholesale/orders/{order_id}/return-authorizations",
            headers=headers, params=params,
        )

    def ship_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/wholesale/orders/{order_id}/ship", {}, headers)

    def deliver_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/wholesale/orders/{order_id}/deliver", {}, headers)

    def cancel_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/wholesale/orders/{order_id}/cancel", {}, headers)

    # ---------------- Invoices and payments ----------------
    def get_invoice(self, invoice_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/wholesale/invoices/{invoice_id}", headers=headers)

    def record_payment(self, invoice_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/wholesale/invoices/{invoice_id}/payments", payload, headers
        )

    def list_invoice_payments(self, invoice_id: str,
                              headers: Optional[Dict[str, str]] = None,
                              params: Optional[Dict] = None):
        return self._request(
            "GET", f"/wholesale/invoices/{invoice_id}/payments", headers=headers,
            params=params,
        )

    def write_off_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/wholesale/invoices/{invoice_id}/write-off", {}, headers
        )

    # ---------------- Returns ----------------
    def create_return_authorization(self, payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request("POST", "/wholesale/return-authorizations", payload, headers)

    def get_return_authorization(self, ra_id: str,
                                 headers: Optional[Dict[str, str]] = None):
        return self._request(
            "GET", f"/wholesale/return-authorizations/{ra_id}", headers=headers
        )

    def list_return_authorization_lines(self, ra_id: str,
                                        headers: Optional[Dict[str, str]] = None,
                                        params: Optional[Dict] = None):
        return self._request(
            "GET", f"/wholesale/return-authorizations/{ra_id}/lines",
            headers=headers, params=params,
        )

    def get_order_line(self, line_id: str,
                       headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/wholesale/order-lines/{line_id}", headers=headers)

    def list_order_line_return_lines(self, line_id: str,
                                     headers: Optional[Dict[str, str]] = None,
                                     params: Optional[Dict] = None):
        return self._request(
            "GET", f"/wholesale/order-lines/{line_id}/return-lines",
            headers=headers, params=params,
        )

    def review_return_authorization(self, ra_id: str, payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/wholesale/return-authorizations/{ra_id}/review",
            payload, headers,
        )

    def receive_return_authorization(self, ra_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/wholesale/return-authorizations/{ra_id}/receive", {}, headers
        )

    # ---------------- Payouts ----------------
    def list_payouts(self, headers: Optional[Dict[str, str]] = None,
                     params: Optional[Dict] = None):
        return self._request("GET", "/wholesale/payouts", headers=headers, params=params)

    def get_payout(self, payout_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/wholesale/payouts/{payout_id}", headers=headers)

    def process_due_payouts(self, headers: Dict[str, str]):
        return self._request("POST", "/wholesale/payouts/process-due", {}, headers)

    def complete_payout(self, payout_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/wholesale/payouts/{payout_id}/complete", {}, headers
        )

    def fail_payout(self, payout_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/wholesale/payouts/{payout_id}/fail", {}, headers)

    # ---------------- Exclusivity grants ----------------
    def create_exclusivity_grant(self, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request("POST", "/wholesale/exclusivity-grants", payload, headers)

    def list_exclusivity_grants(self, headers: Optional[Dict[str, str]] = None,
                                params: Optional[Dict] = None):
        return self._request(
            "GET", "/wholesale/exclusivity-grants", headers=headers, params=params
        )

    def get_exclusivity_grant(self, grant_id: str,
                              headers: Optional[Dict[str, str]] = None):
        return self._request(
            "GET", f"/wholesale/exclusivity-grants/{grant_id}", headers=headers
        )

    def revoke_exclusivity_grant(self, grant_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/wholesale/exclusivity-grants/{grant_id}/revoke", {}, headers
        )

    # ---------------- Fraud flags ----------------
    def create_fraud_flag(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/wholesale/fraud-flags", payload, headers)

    def list_fraud_flags(self, headers: Optional[Dict[str, str]] = None,
                         params: Optional[Dict] = None):
        return self._request(
            "GET", "/wholesale/fraud-flags", headers=headers, params=params
        )

    def get_fraud_flag(self, flag_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/wholesale/fraud-flags/{flag_id}", headers=headers)

    def confirm_fraud_flag(self, flag_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/wholesale/fraud-flags/{flag_id}/confirm", {}, headers
        )

    def dismiss_fraud_flag(self, flag_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/wholesale/fraud-flags/{flag_id}/dismiss", {}, headers)


api_client = ApiClient()
