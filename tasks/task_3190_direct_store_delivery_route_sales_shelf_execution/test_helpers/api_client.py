"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/dsd/_clock/set_current_utc", payload, headers)

    # --- RouteSalesRepresentative ---
    def create_rep(self, payload, headers):
        return self._request("POST", "/dsd/reps", payload, headers)

    def get_rep(self, rep_id, headers):
        return self._request("GET", f"/dsd/reps/{rep_id}", headers=headers)

    # --- Store ---
    def create_store(self, payload, headers):
        return self._request("POST", "/dsd/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/dsd/stores/{store_id}", headers=headers)

    def suspend_store(self, store_id, headers):
        return self._request("POST", f"/dsd/stores/{store_id}/suspend", headers=headers)

    def reactivate_store(self, store_id, headers):
        return self._request("POST", f"/dsd/stores/{store_id}/reactivate", headers=headers)

    # --- Product ---
    def create_product(self, payload, headers):
        return self._request("POST", "/dsd/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/dsd/products/{product_id}", headers=headers)

    # --- Route ---
    def create_route(self, payload, headers):
        return self._request("POST", "/dsd/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/dsd/routes/{route_id}", headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/dsd/routes", headers=headers, params=params)

    def suspend_route(self, route_id, headers):
        return self._request("POST", f"/dsd/routes/{route_id}/suspend", headers=headers)

    def reactivate_route(self, route_id, headers):
        return self._request("POST", f"/dsd/routes/{route_id}/reactivate", headers=headers)

    # --- RouteStoreAssignment ---
    def create_assignment(self, payload, headers):
        return self._request("POST", "/dsd/route-assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/dsd/route-assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/dsd/route-assignments", headers=headers, params=params)

    def retire_assignment(self, assignment_id, headers):
        return self._request("POST", f"/dsd/route-assignments/{assignment_id}/retire", headers=headers)

    # --- RouteDay ---
    def create_route_day(self, payload, headers):
        return self._request("POST", "/dsd/route-days", payload, headers)

    def get_route_day(self, route_day_id, headers):
        return self._request("GET", f"/dsd/route-days/{route_day_id}", headers=headers)

    def list_route_days(self, headers, params=None):
        return self._request("GET", "/dsd/route-days", headers=headers, params=params)

    def load_route_day(self, route_day_id, payload, headers):
        return self._request("POST", f"/dsd/route-days/{route_day_id}/load", payload, headers)

    def start_route_day(self, route_day_id, headers):
        return self._request("POST", f"/dsd/route-days/{route_day_id}/start", headers=headers)

    def cancel_route_day(self, route_day_id, headers):
        return self._request("POST", f"/dsd/route-days/{route_day_id}/cancel", headers=headers)

    # --- TruckInventoryLot ---
    def get_truck_lot(self, lot_id, headers):
        return self._request("GET", f"/dsd/truck-lots/{lot_id}", headers=headers)

    def list_truck_lots(self, headers, params=None):
        return self._request("GET", "/dsd/truck-lots", headers=headers, params=params)

    # --- StoreOrder / OrderLine ---
    def create_order(self, payload, headers):
        return self._request("POST", "/dsd/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/dsd/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/dsd/orders", headers=headers, params=params)

    def revise_order(self, order_id, payload, headers):
        return self._request("PUT", f"/dsd/orders/{order_id}", payload, headers)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/dsd/orders/{order_id}/submit", headers=headers)

    def unsubmit_order(self, order_id, headers):
        return self._request("POST", f"/dsd/orders/{order_id}/unsubmit", headers=headers)

    def deliver_order(self, order_id, payload, headers):
        return self._request("POST", f"/dsd/orders/{order_id}/deliver", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/dsd/orders/{order_id}/cancel", headers=headers)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/dsd/order-lines/{line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/dsd/order-lines", headers=headers, params=params)

    # --- ShelfExecution ---
    def create_shelf_execution(self, payload, headers):
        return self._request("POST", "/dsd/shelf-executions", payload, headers)

    def get_shelf_execution(self, exec_id, headers):
        return self._request("GET", f"/dsd/shelf-executions/{exec_id}", headers=headers)

    def list_shelf_executions(self, headers, params=None):
        return self._request("GET", "/dsd/shelf-executions", headers=headers, params=params)

    def verify_shelf_execution(self, exec_id, payload, headers):
        return self._request("POST", f"/dsd/shelf-executions/{exec_id}/verify", payload, headers)

    # --- StaleCredit ---
    def create_stale_credit(self, payload, headers):
        return self._request("POST", "/dsd/stale-credits", payload, headers)

    def get_stale_credit(self, credit_id, headers):
        return self._request("GET", f"/dsd/stale-credits/{credit_id}", headers=headers)

    def list_stale_credits(self, headers, params=None):
        return self._request("GET", "/dsd/stale-credits", headers=headers, params=params)

    def approve_stale_credit(self, credit_id, headers):
        return self._request("POST", f"/dsd/stale-credits/{credit_id}/approve", headers=headers)

    def reject_stale_credit(self, credit_id, payload, headers):
        return self._request("POST", f"/dsd/stale-credits/{credit_id}/reject", payload, headers)

    def resubmit_stale_credit(self, credit_id, headers):
        return self._request("POST", f"/dsd/stale-credits/{credit_id}/resubmit", headers=headers)

    # --- PromoAgreement ---
    def create_promo_agreement(self, payload, headers):
        return self._request("POST", "/dsd/promo-agreements", payload, headers)

    def get_promo_agreement(self, agreement_id, headers):
        return self._request("GET", f"/dsd/promo-agreements/{agreement_id}", headers=headers)

    def list_promo_agreements(self, headers, params=None):
        return self._request("GET", "/dsd/promo-agreements", headers=headers, params=params)

    def activate_promo_agreement(self, agreement_id, headers):
        return self._request("POST", f"/dsd/promo-agreements/{agreement_id}/activate", headers=headers)

    def breach_promo_agreement(self, agreement_id, headers):
        return self._request("POST", f"/dsd/promo-agreements/{agreement_id}/breach", headers=headers)

    # --- PromoExecution ---
    def create_promo_execution(self, payload, headers):
        return self._request("POST", "/dsd/promo-executions", payload, headers)

    def get_promo_execution(self, exec_id, headers):
        return self._request("GET", f"/dsd/promo-executions/{exec_id}", headers=headers)

    def list_promo_executions(self, headers, params=None):
        return self._request("GET", "/dsd/promo-executions", headers=headers, params=params)

    def verify_promo_execution(self, exec_id, headers):
        return self._request("POST", f"/dsd/promo-executions/{exec_id}/verify", headers=headers)

    def reject_promo_execution(self, exec_id, payload, headers):
        return self._request("POST", f"/dsd/promo-executions/{exec_id}/reject", payload, headers)

    # --- RouteSettlement ---
    def create_settlement(self, payload, headers):
        return self._request("POST", "/dsd/route-settlements", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/dsd/route-settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/dsd/route-settlements", headers=headers, params=params)

    def balance_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/dsd/route-settlements/{settlement_id}/balance", payload, headers)

    def post_settlement(self, settlement_id, headers):
        return self._request("POST", f"/dsd/route-settlements/{settlement_id}/post", headers=headers)

    def dispute_settlement(self, settlement_id, headers):
        return self._request("POST", f"/dsd/route-settlements/{settlement_id}/dispute", headers=headers)

    def resolve_settlement(self, settlement_id, headers):
        return self._request("POST", f"/dsd/route-settlements/{settlement_id}/resolve", headers=headers)

    # --- ServiceLevelSnapshot ---
    def create_service_level_snapshot(self, route_id, payload, headers):
        return self._request(
            "POST", f"/dsd/routes/{route_id}/service-level-snapshots", payload, headers
        )

    def get_service_level_snapshot(self, snapshot_id, headers):
        return self._request(
            "GET", f"/dsd/service-level-snapshots/{snapshot_id}", headers=headers
        )

    def list_service_level_snapshots(self, headers, params=None):
        return self._request(
            "GET", "/dsd/service-level-snapshots", headers=headers, params=params
        )


api_client = ApiClient()
