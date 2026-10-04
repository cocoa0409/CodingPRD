"""API client: one method per endpoint defined in the PRD."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/api/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    # --- contracts ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/api/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/api/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/api/contracts/{contract_id}", headers=headers)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/api/contracts/{contract_id}/activate", {}, headers)

    def reinstate_contract(self, contract_id, headers):
        return self._request("POST", f"/api/contracts/{contract_id}/reinstate", {}, headers)

    def get_monthly_invoice(self, contract_id, headers):
        return self._request(
            "GET", f"/api/contracts/{contract_id}/monthly-invoice", headers=headers
        )

    # --- service lines ---
    def create_service_line(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/api/contracts/{contract_id}/service-lines", payload, headers
        )

    def list_service_lines(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/api/contracts/{contract_id}/service-lines",
            headers=headers, params=params,
        )

    def get_service_line(self, line_id, headers):
        return self._request("GET", f"/api/service-lines/{line_id}", headers=headers)

    # --- pickup events ---
    def create_pickup_event(self, payload, headers):
        return self._request("POST", "/api/pickup-events", payload, headers)

    def list_pickup_events(self, headers, params=None):
        return self._request("GET", "/api/pickup-events", headers=headers, params=params)

    def get_pickup_event(self, event_id, headers):
        return self._request("GET", f"/api/pickup-events/{event_id}", headers=headers)

    def dispute_pickup_event(self, event_id, headers):
        return self._request(
            "POST", f"/api/pickup-events/{event_id}/dispute", {}, headers
        )

    def resolve_pickup_dispute(self, event_id, resolution, headers):
        return self._request(
            "POST", f"/api/pickup-events/{event_id}/resolve-dispute",
            {"resolution": resolution}, headers,
        )

    # --- surcharge configs ---
    def create_surcharge_config(self, payload, headers):
        return self._request("POST", "/api/surcharge-configs", payload, headers)

    def list_surcharge_configs(self, headers, params=None):
        return self._request(
            "GET", "/api/surcharge-configs", headers=headers, params=params
        )

    # --- rate notices ---
    def create_rate_notice(self, payload, headers):
        return self._request("POST", "/api/rate-notices", payload, headers)

    def list_rate_notices(self, headers, params=None):
        return self._request("GET", "/api/rate-notices", headers=headers, params=params)

    def get_rate_notice(self, notice_id, headers):
        return self._request("GET", f"/api/rate-notices/{notice_id}", headers=headers)

    def cancel_rate_notice(self, notice_id, headers):
        return self._request(
            "POST", f"/api/rate-notices/{notice_id}/cancel", {}, headers
        )

    # --- service change requests ---
    def create_service_change_request(self, payload, headers):
        return self._request("POST", "/api/service-change-requests", payload, headers)

    def list_service_change_requests(self, headers, params=None):
        return self._request(
            "GET", "/api/service-change-requests", headers=headers, params=params
        )

    def get_service_change_request(self, change_id, headers):
        return self._request(
            "GET", f"/api/service-change-requests/{change_id}", headers=headers
        )

    def approve_service_change(self, change_id, headers):
        return self._request(
            "POST", f"/api/service-changes/{change_id}/approve", {}, headers
        )

    def reject_service_change(self, change_id, headers):
        return self._request(
            "POST", f"/api/service-changes/{change_id}/reject", {}, headers
        )

    def apply_service_change(self, change_id, payload, headers):
        return self._request(
            "POST", f"/api/service-changes/{change_id}/apply", payload, headers
        )

    def withdraw_service_change(self, change_id, headers):
        return self._request(
            "POST", f"/api/service-changes/{change_id}/withdraw", {}, headers
        )

    # --- competing offers ---
    def create_competing_offer(self, payload, headers):
        return self._request("POST", "/api/competing-offers", payload, headers)

    def list_competing_offers(self, headers, params=None):
        return self._request("GET", "/api/competing-offers", headers=headers, params=params)

    def get_competing_offer(self, offer_id, headers):
        return self._request("GET", f"/api/competing-offers/{offer_id}", headers=headers)

    def match_competing_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/api/competing-offers/{offer_id}/match", payload, headers
        )

    def decline_competing_offer(self, offer_id, headers):
        return self._request(
            "POST", f"/api/competing-offers/{offer_id}/decline-match", {}, headers
        )

    # --- cancellation requests ---
    def create_cancellation_request(self, payload, headers):
        return self._request("POST", "/api/cancellation-requests", payload, headers)

    def list_cancellation_requests(self, headers, params=None):
        return self._request(
            "GET", "/api/cancellation-requests", headers=headers, params=params
        )

    def get_cancellation_request(self, cancel_id, headers):
        return self._request(
            "GET", f"/api/cancellation-requests/{cancel_id}", headers=headers
        )

    def approve_cancellation(self, cancel_id, headers):
        return self._request(
            "POST", f"/api/cancellation-requests/{cancel_id}/approve", {}, headers
        )

    def deny_cancellation(self, cancel_id, headers):
        return self._request(
            "POST", f"/api/cancellation-requests/{cancel_id}/deny", {}, headers
        )

    def withdraw_cancellation(self, cancel_id, headers):
        return self._request(
            "POST", f"/api/cancellation-requests/{cancel_id}/withdraw", {}, headers
        )

    def waive_cancellation_ld(self, cancel_id, headers):
        return self._request(
            "POST", f"/api/cancellation-requests/{cancel_id}/waive-ld", {}, headers
        )

    # --- service credits ---
    def create_service_credit(self, payload, headers):
        return self._request("POST", "/api/service-credits", payload, headers)

    def list_service_credits(self, headers, params=None):
        return self._request("GET", "/api/service-credits", headers=headers, params=params)

    def get_service_credit(self, credit_id, headers):
        return self._request("GET", f"/api/service-credits/{credit_id}", headers=headers)

    # --- roll-off orders ---
    def create_rolloff_order(self, payload, headers):
        return self._request("POST", "/api/rolloff-orders", payload, headers)

    def list_rolloff_orders(self, headers, params=None):
        return self._request("GET", "/api/rolloff-orders", headers=headers, params=params)

    def get_rolloff_order(self, order_id, headers):
        return self._request("GET", f"/api/rolloff-orders/{order_id}", headers=headers)

    def deliver_rolloff_order(self, order_id, headers):
        return self._request(
            "POST", f"/api/rolloff-orders/{order_id}/deliver", {}, headers
        )

    def complete_rolloff_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/api/rolloff-orders/{order_id}/complete", payload, headers
        )

    def cancel_rolloff_order(self, order_id, headers):
        return self._request(
            "POST", f"/api/rolloff-orders/{order_id}/cancel", {}, headers
        )

    # --- ledger entries ---
    def list_contract_ledger_entries(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/api/contracts/{contract_id}/ledger-entries",
            headers=headers, params=params,
        )

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/api/ledger-entries", headers=headers, params=params)


api_client = ApiClient()
