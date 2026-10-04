"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock --------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- suppliers ------------------------------------------------------
    def create_supplier(self, payload, headers):
        return self._request("POST", "/opaque/suppliers", payload, headers)

    def list_suppliers(self, headers, params=None):
        return self._request("GET", "/opaque/suppliers", headers=headers, params=params)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/opaque/suppliers/{supplier_id}", headers=headers)

    def suspend_supplier(self, supplier_id, headers, payload=None):
        return self._request("POST", f"/opaque/suppliers/{supplier_id}/suspend", payload or {}, headers)

    def reinstate_supplier(self, supplier_id, headers, payload=None):
        return self._request("POST", f"/opaque/suppliers/{supplier_id}/reinstate", payload or {}, headers)

    def terminate_supplier(self, supplier_id, headers, payload=None):
        return self._request("POST", f"/opaque/suppliers/{supplier_id}/terminate", payload or {}, headers)

    # ---- properties -----------------------------------------------------
    def create_property(self, payload, headers):
        return self._request("POST", "/opaque/properties", payload, headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/opaque/properties", headers=headers, params=params)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/opaque/properties/{property_id}", headers=headers)

    # ---- rate windows ---------------------------------------------------
    def create_rate_window(self, payload, headers):
        return self._request("POST", "/opaque/rate-windows", payload, headers)

    def list_rate_windows(self, headers, params=None):
        return self._request("GET", "/opaque/rate-windows", headers=headers, params=params)

    def get_rate_window(self, rate_window_id, headers):
        return self._request("GET", f"/opaque/rate-windows/{rate_window_id}", headers=headers)

    def close_rate_window(self, rate_window_id, payload, headers):
        return self._request("POST", f"/opaque/rate-windows/{rate_window_id}/close", payload, headers)

    # ---- disclosure zones -----------------------------------------------
    def create_disclosure_zone(self, payload, headers):
        return self._request("POST", "/opaque/disclosure-zones", payload, headers)

    def list_disclosure_zones(self, headers, params=None):
        return self._request("GET", "/opaque/disclosure-zones", headers=headers, params=params)

    # ---- customers ------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/opaque/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/opaque/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/opaque/customers/{customer_id}", headers=headers)

    # ---- opaque bids ----------------------------------------------------
    def create_opaque_bid(self, payload, headers):
        return self._request("POST", "/opaque/opaque-bids", payload, headers)

    def list_opaque_bids(self, headers, params=None):
        return self._request("GET", "/opaque/opaque-bids", headers=headers, params=params)

    def get_opaque_bid(self, bid_id, headers):
        return self._request("GET", f"/opaque/opaque-bids/{bid_id}", headers=headers)

    def evaluate_opaque_bid(self, bid_id, payload, headers):
        return self._request("POST", f"/opaque/opaque-bids/{bid_id}/evaluate", payload, headers)

    def withdraw_opaque_bid(self, bid_id, headers, payload=None):
        return self._request("POST", f"/opaque/opaque-bids/{bid_id}/withdraw", payload or {}, headers)

    # ---- bookings -------------------------------------------------------
    def list_bookings(self, headers, params=None):
        return self._request("GET", "/opaque/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/opaque/bookings/{booking_id}", headers=headers)

    def mark_service_failure(self, booking_id, headers, payload=None):
        return self._request("POST", f"/opaque/bookings/{booking_id}/mark-service-failure", payload or {}, headers)

    def grant_goodwill(self, booking_id, headers, payload=None):
        return self._request("POST", f"/opaque/bookings/{booking_id}/grant-goodwill", payload or {}, headers)

    # ---- complaint cases ------------------------------------------------
    def create_complaint_case(self, payload, headers):
        return self._request("POST", "/opaque/complaint-cases", payload, headers)

    def list_complaint_cases(self, headers, params=None):
        return self._request("GET", "/opaque/complaint-cases", headers=headers, params=params)

    def get_complaint_case(self, case_id, headers):
        return self._request("GET", f"/opaque/complaint-cases/{case_id}", headers=headers)

    def start_review_complaint_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/opaque/complaint-cases/{case_id}/start-review", payload or {}, headers)

    def resolve_complaint_case(self, case_id, payload, headers):
        return self._request("POST", f"/opaque/complaint-cases/{case_id}/resolve", payload, headers)

    def reject_complaint_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/opaque/complaint-cases/{case_id}/reject", payload or {}, headers)

    # ---- settlement batches ---------------------------------------------
    def create_settlement_batch(self, payload, headers):
        return self._request("POST", "/opaque/settlement-batches", payload, headers)

    def list_settlement_batches(self, headers, params=None):
        return self._request("GET", "/opaque/settlement-batches", headers=headers, params=params)

    def get_settlement_batch(self, batch_id, headers):
        return self._request("GET", f"/opaque/settlement-batches/{batch_id}", headers=headers)

    def reselect_settlement_batch(self, batch_id, headers, payload=None):
        return self._request("POST", f"/opaque/settlement-batches/{batch_id}/reselect", payload or {}, headers)

    def approve_settlement_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/opaque/settlement-batches/{batch_id}/approve", payload, headers)

    def void_settlement_batch(self, batch_id, headers, payload=None):
        return self._request("POST", f"/opaque/settlement-batches/{batch_id}/void", payload or {}, headers)

    def mark_paid_settlement_batch(self, batch_id, headers, payload=None):
        return self._request("POST", f"/opaque/settlement-batches/{batch_id}/mark-paid", payload or {}, headers)

    # ---- fraud flags ----------------------------------------------------
    def create_fraud_flag(self, payload, headers):
        return self._request("POST", "/opaque/fraud-flags", payload, headers)

    def list_fraud_flags(self, headers, params=None):
        return self._request("GET", "/opaque/fraud-flags", headers=headers, params=params)

    def get_fraud_flag(self, flag_id, headers):
        return self._request("GET", f"/opaque/fraud-flags/{flag_id}", headers=headers)

    def uphold_fraud_flag(self, flag_id, headers, payload=None):
        return self._request("POST", f"/opaque/fraud-flags/{flag_id}/uphold", payload or {}, headers)

    def dismiss_fraud_flag(self, flag_id, headers, payload=None):
        return self._request("POST", f"/opaque/fraud-flags/{flag_id}/dismiss", payload or {}, headers)


api_client = ApiClient()
