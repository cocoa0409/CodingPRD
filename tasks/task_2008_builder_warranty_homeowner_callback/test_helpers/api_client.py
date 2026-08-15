"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Homeowners ---
    def create_homeowner(self, payload, headers):
        return self._request("POST", "/homeowners", payload, headers)

    def get_homeowner(self, homeowner_id, headers):
        return self._request("GET", f"/homeowners/{homeowner_id}", headers=headers)

    # --- Homes ---
    def create_home(self, payload, headers):
        return self._request("POST", "/homes", payload, headers)

    def get_home(self, home_id, headers):
        return self._request("GET", f"/homes/{home_id}", headers=headers)

    def list_homes(self, headers, params=None):
        return self._request("GET", "/homes", headers=headers, params=params)

    # --- Service requests ---
    def create_service_request(self, payload, headers):
        return self._request("POST", "/service-requests", payload, headers)

    def get_service_request(self, request_id, headers):
        return self._request("GET", f"/service-requests/{request_id}", headers=headers)

    def list_service_requests(self, headers, params=None):
        return self._request("GET", "/service-requests", headers=headers, params=params)

    def assess_service_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/service-requests/{request_id}/assess", payload, headers
        )

    def follow_up_service_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/service-requests/{request_id}/follow-up", payload, headers
        )

    def dispute_service_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/service-requests/{request_id}/dispute", payload, headers
        )

    def resolve_dispute(self, request_id, payload, headers):
        return self._request(
            "POST", f"/service-requests/{request_id}/resolve-dispute", payload, headers
        )

    # --- Work orders ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def complete_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/complete", payload, headers
        )

    def verify_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/verify", payload, headers
        )

    def reschedule_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/reschedule", payload, headers
        )

    def cancel_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/cancel", payload, headers
        )

    # --- Trade partners ---
    def create_trade_partner(self, payload, headers):
        return self._request("POST", "/trade-partners", payload, headers)

    def get_trade_partner(self, partner_id, headers):
        return self._request("GET", f"/trade-partners/{partner_id}", headers=headers)

    # --- Chargebacks ---
    def create_chargeback(self, payload, headers):
        return self._request("POST", "/chargebacks", payload, headers)

    def get_chargeback(self, chargeback_id, headers):
        return self._request("GET", f"/chargebacks/{chargeback_id}", headers=headers)

    def list_chargebacks(self, headers, params=None):
        return self._request("GET", "/chargebacks", headers=headers, params=params)

    def approve_chargeback(self, chargeback_id, payload, headers):
        return self._request(
            "POST", f"/chargebacks/{chargeback_id}/approve", payload, headers
        )

    def contest_chargeback(self, chargeback_id, payload, headers):
        return self._request(
            "POST", f"/chargebacks/{chargeback_id}/contest", payload, headers
        )

    def resolve_chargeback(self, chargeback_id, payload, headers):
        return self._request(
            "POST", f"/chargebacks/{chargeback_id}/resolve", payload, headers
        )

    def record_payment(self, chargeback_id, payload, headers):
        return self._request(
            "POST", f"/chargebacks/{chargeback_id}/payments", payload, headers
        )

    # --- Warranty reserves ---
    def get_warranty_reserve(self, reserve_id, headers):
        return self._request(
            "GET", f"/warranty-reserves/{reserve_id}", headers=headers
        )

    def list_warranty_reserves(self, headers, params=None):
        return self._request("GET", "/warranty-reserves", headers=headers, params=params)

    def list_reserve_entries(self, reserve_id, headers, params=None):
        return self._request(
            "GET", f"/warranty-reserves/{reserve_id}/entries", headers=headers, params=params
        )

    def post_reserve_adjustment(self, reserve_id, payload, headers):
        return self._request(
            "POST", f"/warranty-reserves/{reserve_id}/adjustments", payload, headers
        )

    # --- Administrator claims ---
    def create_administrator_claim(self, payload, headers):
        return self._request("POST", "/administrator-claims", payload, headers)

    def get_administrator_claim(self, claim_id, headers):
        return self._request(
            "GET", f"/administrator-claims/{claim_id}", headers=headers
        )

    def list_administrator_claims(self, headers, params=None):
        return self._request(
            "GET", "/administrator-claims", headers=headers, params=params
        )

    def decide_administrator_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/administrator-claims/{claim_id}/decide", payload, headers
        )

    # --- Operations ---
    def run_sweep(self, headers):
        return self._request("POST", "/ops/run-sweep", headers=headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
