"""API client: one method per endpoint defined in the PRD (section 4)."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- platform test-driving controls ---
    def set_clock(self, payload: Dict[str, Any], headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def set_surge(self, payload: Dict[str, Any], headers):
        return self._request("POST", "/_surge/set_current", payload, headers)

    # --- merchants ---
    def create_merchant(self, payload, headers):
        return self._request("POST", "/merchants", payload, headers)

    def list_merchants(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/merchants", headers=headers, params=params)

    def get_merchant(self, merchant_id, headers):
        return self._request("GET", f"/merchants/{merchant_id}", headers=headers)

    def update_merchant(self, merchant_id, payload, headers):
        return self._request("PATCH", f"/merchants/{merchant_id}", payload, headers)

    def activate_merchant(self, merchant_id, headers):
        return self._request("POST", f"/merchants/{merchant_id}/activate", {}, headers)

    def suspend_merchant(self, merchant_id, headers):
        return self._request("POST", f"/merchants/{merchant_id}/suspend", {}, headers)

    def resume_merchant(self, merchant_id, headers):
        return self._request("POST", f"/merchants/{merchant_id}/resume", {}, headers)

    # --- stores ---
    def create_store(self, merchant_id, payload, headers):
        return self._request("POST", f"/merchants/{merchant_id}/stores", payload, headers)

    def list_stores(self, merchant_id, headers, params: Optional[Dict] = None):
        return self._request("GET", f"/merchants/{merchant_id}/stores", headers=headers, params=params)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    def update_store(self, store_id, payload, headers):
        return self._request("PATCH", f"/stores/{store_id}", payload, headers)

    # --- serviceability overrides / check ---
    def create_serviceability_override(self, store_id, payload, headers):
        return self._request(
            "POST", f"/stores/{store_id}/serviceability-overrides", payload, headers
        )

    def list_serviceability_overrides(self, store_id, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/stores/{store_id}/serviceability-overrides", headers=headers, params=params
        )

    def check_serviceability(self, store_id, payload, headers):
        return self._request(
            "POST", f"/stores/{store_id}/check-serviceability", payload, headers
        )

    # --- pricing policies ---
    def create_pricing_policy(self, merchant_id, payload, headers):
        return self._request(
            "POST", f"/merchants/{merchant_id}/pricing-policies", payload, headers
        )

    def list_pricing_policies(self, merchant_id, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/merchants/{merchant_id}/pricing-policies", headers=headers, params=params
        )

    def get_pricing_policy(self, policy_id, headers):
        return self._request("GET", f"/pricing-policies/{policy_id}", headers=headers)

    def activate_pricing_policy(self, merchant_id, policy_id, payload, headers):
        return self._request(
            "POST",
            f"/merchants/{merchant_id}/pricing-policies/{policy_id}/activate",
            payload,
            headers,
        )

    # --- quotes ---
    def create_quote(self, payload, headers):
        return self._request("POST", "/delivery-quotes", payload, headers)

    def list_quotes(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/delivery-quotes", headers=headers, params=params)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/delivery-quotes/{quote_id}", headers=headers)

    # --- delivery orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/delivery-orders", payload, headers)

    def list_orders(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/delivery-orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/delivery-orders/{order_id}", headers=headers)

    def accept_order(self, order_id, payload, headers):
        return self._request("POST", f"/delivery-orders/{order_id}/accept", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/delivery-orders/{order_id}/cancel", {}, headers)

    def mark_ready(self, order_id, headers):
        return self._request("POST", f"/delivery-orders/{order_id}/mark-ready", {}, headers)

    def confirm_pickup(self, order_id, headers):
        return self._request("POST", f"/delivery-orders/{order_id}/confirm-pickup", {}, headers)

    def start_transit(self, order_id, headers):
        return self._request("POST", f"/delivery-orders/{order_id}/start-transit", {}, headers)

    def complete_delivery(self, order_id, headers):
        return self._request("POST", f"/delivery-orders/{order_id}/complete-delivery", {}, headers)

    def report_undeliverable(self, order_id, payload, headers):
        return self._request(
            "POST", f"/delivery-orders/{order_id}/report-undeliverable", payload, headers
        )

    def create_disposition(self, order_id, payload, headers):
        return self._request("POST", f"/delivery-orders/{order_id}/disposition", payload, headers)

    def list_dispositions(self, order_id, headers):
        return self._request("GET", f"/delivery-orders/{order_id}/disposition", headers=headers)

    def complete_disposition(self, disposition_id, payload, headers):
        return self._request(
            "POST", f"/dispositions/{disposition_id}/complete", payload, headers
        )

    # --- tracking events ---
    def create_tracking_event(self, order_id, payload, headers):
        return self._request(
            "POST", f"/delivery-orders/{order_id}/tracking-events", payload, headers
        )

    def list_tracking_events(self, order_id, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/delivery-orders/{order_id}/tracking-events", headers=headers, params=params
        )

    # --- couriers ---
    def create_courier(self, payload, headers):
        return self._request("POST", "/couriers", payload, headers)

    def list_couriers(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/couriers", headers=headers, params=params)

    def get_courier(self, courier_id, headers):
        return self._request("GET", f"/couriers/{courier_id}", headers=headers)

    def update_courier(self, courier_id, payload, headers):
        return self._request("PATCH", f"/couriers/{courier_id}", payload, headers)

    # --- delivery batches ---
    def create_batch(self, payload, headers):
        return self._request("POST", "/delivery-batches", payload, headers)

    def list_batches(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/delivery-batches", headers=headers, params=params)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/delivery-batches/{batch_id}", headers=headers)

    def dispatch_batch(self, batch_id, headers):
        return self._request("POST", f"/delivery-batches/{batch_id}/dispatch", {}, headers)

    def fail_batch(self, batch_id, headers):
        return self._request("POST", f"/delivery-batches/{batch_id}/fail", {}, headers)

    # --- refund claims ---
    def create_refund_claim(self, payload, headers):
        return self._request("POST", "/refund-claims", payload, headers)

    def list_refund_claims(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/refund-claims", headers=headers, params=params)

    def get_refund_claim(self, claim_id, headers):
        return self._request("GET", f"/refund-claims/{claim_id}", headers=headers)

    def start_claim_review(self, claim_id, headers):
        return self._request("POST", f"/refund-claims/{claim_id}/start-review", {}, headers)

    def decide_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/refund-claims/{claim_id}/decide", payload, headers)

    def appeal_claim(self, claim_id, headers):
        return self._request("POST", f"/refund-claims/{claim_id}/appeal", {}, headers)

    def settle_claim(self, claim_id, headers):
        return self._request("POST", f"/refund-claims/{claim_id}/settle", {}, headers)

    def reverse_claim(self, claim_id, headers):
        return self._request("POST", f"/refund-claims/{claim_id}/reverse", {}, headers)

    # --- SLA reports ---
    def create_sla_report(self, merchant_id, payload, headers):
        return self._request("POST", f"/merchants/{merchant_id}/sla-reports", payload, headers)

    def list_sla_reports(self, merchant_id, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/merchants/{merchant_id}/sla-reports", headers=headers, params=params
        )

    def get_sla_report(self, report_id, headers):
        return self._request("GET", f"/sla-reports/{report_id}", headers=headers)

    def finalize_sla_report(self, report_id, headers):
        return self._request("POST", f"/sla-reports/{report_id}/finalize", {}, headers)

    def list_report_credits(self, report_id, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/sla-reports/{report_id}/service-credits", headers=headers, params=params
        )

    # --- service credits ---
    def get_service_credit(self, credit_id, headers):
        return self._request("GET", f"/service-credits/{credit_id}", headers=headers)

    def list_service_credits(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/service-credits", headers=headers, params=params)

    def list_merchant_service_credits(self, merchant_id, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/merchants/{merchant_id}/service-credits", headers=headers, params=params
        )

    def apply_service_credit(self, credit_id, headers):
        return self._request("POST", f"/service-credits/{credit_id}/apply", {}, headers)

    def void_service_credit(self, credit_id, headers):
        return self._request("POST", f"/service-credits/{credit_id}/void", {}, headers)


api_client = ApiClient()
