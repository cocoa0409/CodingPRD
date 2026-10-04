"""API client: one method per operation offered by the platform."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # --- Logical clock and operational epoch ---

    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def run_ops(self, as_of_iso8601, headers):
        return self._request("POST", "/ops-runs",
                             {"as_of_iso8601": as_of_iso8601}, headers)

    # --- Partnership and market configuration ---

    def create_production(self, payload, headers):
        return self._request("POST", "/productions", payload, headers)

    def transition_production(self, production_id, payload, headers):
        return self._request("POST",
                             f"/productions/{production_id}/status-transitions",
                             payload, headers)

    def get_production(self, production_id, headers):
        return self._request("GET", f"/productions/{production_id}",
                             headers=headers)

    def create_market(self, payload, headers):
        return self._request("POST", "/markets", payload, headers)

    def get_market(self, market_id, headers):
        return self._request("GET", f"/markets/{market_id}", headers=headers)

    # --- Performances ---

    def create_performance(self, payload, headers):
        return self._request("POST", "/performances", payload, headers)

    def get_performance(self, performance_id, headers):
        return self._request("GET", f"/performances/{performance_id}",
                             headers=headers)

    def transition_performance(self, performance_id, payload, headers):
        return self._request("POST",
                             f"/performances/{performance_id}/status-transitions",
                             payload, headers)

    # --- Allocations and release ---

    def create_allocation(self, performance_id, payload, headers):
        return self._request("POST", f"/performances/{performance_id}/allocations",
                             payload, headers)

    def list_allocations(self, performance_id, headers, params=None):
        return self._request("GET", f"/performances/{performance_id}/allocations",
                             headers=headers, params=params)

    def schedule_allocation(self, allocation_id, payload, headers):
        return self._request("POST", f"/allocations/{allocation_id}/scheduling",
                             payload, headers)

    def release_allocation(self, allocation_id, release_epoch, payload, headers):
        return self._request(
            "POST", f"/allocations/{allocation_id}/releases/{release_epoch}",
            payload, headers)

    def execute_draw(self, allocation_id, payload, headers):
        return self._request("POST",
                             f"/allocations/{allocation_id}/draw-executions",
                             payload, headers)

    def reconcile_allocation(self, allocation_id, payload, headers):
        return self._request("POST",
                             f"/allocations/{allocation_id}/reconciliations",
                             payload, headers)

    # --- Patrons ---

    def register_patron(self, payload, headers=None):
        return self._request("POST", "/patrons/registrations", payload,
                             headers or {})

    def get_patron(self, patron_id, headers):
        return self._request("GET", f"/patrons/{patron_id}", headers=headers)

    def transition_patron(self, patron_id, payload, headers):
        return self._request("POST", f"/patrons/{patron_id}/status-transitions",
                             payload, headers)

    def reinstate_draw_entry(self, patron_id, payload, headers):
        return self._request("POST",
                             f"/patrons/{patron_id}/draw-reinstatements",
                             payload, headers)

    # --- Draw entries ---

    def create_draw_entry(self, performance_id, payload, headers):
        return self._request("POST", f"/performances/{performance_id}/draw-entries",
                             payload, headers)

    def list_draw_entries(self, performance_id, headers, params=None):
        return self._request("GET", f"/performances/{performance_id}/draw-entries",
                             headers=headers, params=params)

    def claim_draw_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/draw-entries/{entry_id}/claims",
                             payload, headers)

    # --- Queue ---

    def join_queue(self, performance_id, payload, headers):
        return self._request("POST",
                             f"/performances/{performance_id}/queue-positions",
                             payload, headers)

    def list_queue_positions(self, performance_id, headers, params=None):
        return self._request("GET",
                             f"/performances/{performance_id}/queue-positions",
                             headers=headers, params=params)

    # --- Purchases ---

    def create_purchase(self, payload, headers):
        return self._request("POST", "/purchases", payload, headers)

    def list_purchases(self, headers, params=None):
        return self._request("GET", "/purchases", headers=headers, params=params)

    def get_purchase(self, purchase_id, headers):
        return self._request("GET", f"/purchases/{purchase_id}", headers=headers)

    def settle_purchase(self, purchase_id, payload, headers):
        return self._request("POST", f"/purchases/{purchase_id}/settlements",
                             payload, headers)

    def deliver_purchase(self, purchase_id, payload, headers):
        return self._request("POST", f"/purchases/{purchase_id}/deliveries",
                             payload, headers)

    # --- Refunds ---

    def create_refund_request(self, purchase_id, payload, headers):
        return self._request("POST", f"/purchases/{purchase_id}/refund-requests",
                             payload, headers)

    def list_refund_requests(self, purchase_id, headers, params=None):
        return self._request("GET", f"/purchases/{purchase_id}/refund-requests",
                             headers=headers, params=params)

    def approve_refund(self, refund_id, payload, headers):
        return self._request("POST", f"/refunds/{refund_id}/approvals",
                             payload, headers)

    def settle_refund(self, refund_id, payload, headers):
        return self._request("POST", f"/refunds/{refund_id}/settlement",
                             payload, headers)

    # --- Exchanges ---

    def create_exchange_request(self, purchase_id, payload, headers):
        return self._request("POST",
                             f"/purchases/{purchase_id}/exchange-requests",
                             payload, headers)

    def list_exchange_requests(self, purchase_id, headers, params=None):
        return self._request("GET", f"/purchases/{purchase_id}/exchange-requests",
                             headers=headers, params=params)

    def quote_exchange(self, exchange_id, payload, headers):
        return self._request("POST", f"/exchanges/{exchange_id}/quotations",
                             payload, headers)

    def approve_exchange(self, exchange_id, payload, headers):
        return self._request("POST", f"/exchanges/{exchange_id}/approvals",
                             payload, headers)

    def apply_exchange(self, exchange_id, payload, headers):
        return self._request("POST", f"/exchanges/{exchange_id}/application",
                             payload, headers)

    # --- Handoff and holds ---

    def create_handoff(self, payload, headers):
        return self._request("POST", "/handoffs", payload, headers)

    def create_seat_hold(self, performance_id, payload, headers):
        return self._request("POST", f"/performances/{performance_id}/seat-holds",
                             payload, headers)

    def list_seat_holds(self, performance_id, headers, params=None):
        return self._request("GET", f"/performances/{performance_id}/seat-holds",
                             headers=headers, params=params)


api_client = ApiClient()