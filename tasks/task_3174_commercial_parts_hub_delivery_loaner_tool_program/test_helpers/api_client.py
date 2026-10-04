"""API client: one method per endpoint declared in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin method-per-endpoint wrapper over the PRD's routing map."""

    # ── Logical clock and business-day epoch ──────────────────────────────
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/commercial/_clock/set_current_utc", payload, headers)

    def advance_epoch(self, payload, headers):
        return self._request("POST", "/commercial/_epoch/advance", payload, headers)

    # ── Commercial accounts ───────────────────────────────────────────────
    def create_account(self, payload, headers):
        return self._request("POST", "/commercial/commercial-accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/commercial/commercial-accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/commercial/commercial-accounts/{account_id}", headers=headers)

    def update_account(self, account_id, payload, headers):
        return self._request("PUT", f"/commercial/commercial-accounts/{account_id}", payload, headers)

    def get_account_posture(self, account_id, headers):
        return self._request("GET", f"/commercial/commercial-accounts/{account_id}/posture", headers=headers)

    def hold_account(self, account_id, payload, headers):
        return self._request("POST", f"/commercial/commercial-accounts/{account_id}/hold", payload, headers)

    def release_account(self, account_id, payload, headers):
        return self._request("POST", f"/commercial/commercial-accounts/{account_id}/release", payload, headers)

    def restore_account(self, account_id, payload, headers):
        return self._request("POST", f"/commercial/commercial-accounts/{account_id}/restore", payload, headers)

    def close_account(self, account_id, payload, headers):
        return self._request("POST", f"/commercial/commercial-accounts/{account_id}/close", payload, headers)

    def archive_account(self, account_id, payload, headers):
        return self._request("POST", f"/commercial/commercial-accounts/{account_id}/archive", payload, headers)

    def list_account_orders(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/commercial/commercial-accounts/{account_id}/part-orders",
            headers=headers, params=params)

    def list_account_loans(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/commercial/commercial-accounts/{account_id}/tool-loans",
            headers=headers, params=params)

    def list_account_core_returns(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/commercial/commercial-accounts/{account_id}/core-returns",
            headers=headers, params=params)

    def list_account_coverages(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/commercial/commercial-accounts/{account_id}/rep-coverages",
            headers=headers, params=params)

    def list_account_warranties(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/commercial/commercial-accounts/{account_id}/warranty-registrations",
            headers=headers, params=params)

    # ── Stores ────────────────────────────────────────────────────────────
    def create_store(self, payload, headers):
        return self._request("POST", "/commercial/stores", payload, headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", "/commercial/stores", headers=headers, params=params)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/commercial/stores/{store_id}", headers=headers)

    def list_store_children(self, store_id, headers, params=None):
        return self._request("GET", f"/commercial/stores/{store_id}/child-stores",
                             headers=headers, params=params)

    def list_store_accounts(self, store_id, headers, params=None):
        return self._request("GET", f"/commercial/stores/{store_id}/commercial-accounts",
                             headers=headers, params=params)

    def list_store_inventory(self, store_id, headers, params=None):
        return self._request("GET", f"/commercial/stores/{store_id}/inventory-items",
                             headers=headers, params=params)

    def archive_store(self, store_id, payload, headers):
        return self._request("POST", f"/commercial/stores/{store_id}/archive", payload, headers)

    # ── Inventory lines ───────────────────────────────────────────────────
    def create_inventory_item(self, payload, headers):
        return self._request("POST", "/commercial/inventory-items", payload, headers)

    def list_inventory_items(self, headers, params=None):
        return self._request("GET", "/commercial/inventory-items", headers=headers, params=params)

    def get_inventory_item(self, item_id, headers):
        return self._request("GET", f"/commercial/inventory-items/{item_id}", headers=headers)

    def update_inventory_item(self, item_id, payload, headers):
        return self._request("PUT", f"/commercial/inventory-items/{item_id}", payload, headers)

    def list_part_inventory(self, part_id, headers, params=None):
        return self._request("GET", f"/commercial/parts/{part_id}/inventory-items",
                             headers=headers, params=params)

    # ── Parts, fitments, interchanges, supersession ───────────────────────
    def create_part(self, payload, headers):
        return self._request("POST", "/commercial/parts", payload, headers)

    def list_parts(self, headers, params=None):
        return self._request("GET", "/commercial/parts", headers=headers, params=params)

    def resolve_current_part(self, headers, params=None):
        return self._request("GET", "/commercial/parts/current", headers=headers, params=params)

    def fitment_lookup(self, headers, params=None):
        return self._request("GET", "/commercial/parts/fitment-lookup", headers=headers, params=params)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/commercial/parts/{part_id}", headers=headers)

    def list_part_fitments(self, part_id, headers, params=None):
        return self._request("GET", f"/commercial/parts/{part_id}/fitments",
                             headers=headers, params=params)

    def create_part_fitment(self, part_id, payload, headers):
        return self._request("POST", f"/commercial/parts/{part_id}/fitments", payload, headers)

    def list_part_interchanges(self, part_id, headers, params=None):
        return self._request("GET", f"/commercial/parts/{part_id}/interchanges",
                             headers=headers, params=params)

    def create_part_interchange(self, part_id, payload, headers):
        return self._request("POST", f"/commercial/parts/{part_id}/interchanges", payload, headers)

    def list_part_tool_fitments(self, part_id, headers, params=None):
        return self._request("GET", f"/commercial/parts/{part_id}/tool-fitments",
                             headers=headers, params=params)

    def supersede_part(self, part_id, payload, headers):
        return self._request("POST", f"/commercial/parts/{part_id}/supersede", payload, headers)

    def unsupersede_part(self, part_id, payload, headers):
        return self._request("POST", f"/commercial/parts/{part_id}/unsupersede", payload, headers)

    def archive_part(self, part_id, payload, headers):
        return self._request("POST", f"/commercial/parts/{part_id}/archive", payload, headers)

    def list_part_fitment_rows(self, headers, params=None):
        return self._request("GET", "/commercial/part-fitments", headers=headers, params=params)

    def get_part_fitment_row(self, fitment_id, headers):
        return self._request("GET", f"/commercial/part-fitments/{fitment_id}", headers=headers)

    def list_part_interchange_rows(self, headers, params=None):
        return self._request("GET", "/commercial/part-interchanges", headers=headers, params=params)

    def get_part_interchange_row(self, interchange_id, headers):
        return self._request("GET", f"/commercial/part-interchanges/{interchange_id}", headers=headers)

    def list_tool_fitment_rows(self, headers, params=None):
        return self._request("GET", "/commercial/tool-fitments", headers=headers, params=params)

    def get_tool_fitment_row(self, fitment_id, headers):
        return self._request("GET", f"/commercial/tool-fitments/{fitment_id}", headers=headers)

    # ── Vehicles ──────────────────────────────────────────────────────────
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/commercial/vehicles", payload, headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/commercial/vehicles", headers=headers, params=params)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/commercial/vehicles/{vehicle_id}", headers=headers)

    # ── Sales reps and coverage ───────────────────────────────────────────
    def create_sales_rep(self, payload, headers):
        return self._request("POST", "/commercial/sales-reps", payload, headers)

    def list_sales_reps(self, headers, params=None):
        return self._request("GET", "/commercial/sales-reps", headers=headers, params=params)

    def get_sales_rep(self, rep_id, headers):
        return self._request("GET", f"/commercial/sales-reps/{rep_id}", headers=headers)

    def list_rep_coverages(self, rep_id, headers, params=None):
        return self._request("GET", f"/commercial/sales-reps/{rep_id}/coverages",
                             headers=headers, params=params)

    def create_rep_coverage(self, payload, headers):
        return self._request("POST", "/commercial/rep-coverages", payload, headers)

    def list_coverage_assignments(self, headers, params=None):
        return self._request("GET", "/commercial/rep-coverages", headers=headers, params=params)

    def get_coverage(self, coverage_id, headers):
        return self._request("GET", f"/commercial/rep-coverages/{coverage_id}", headers=headers)

    def extend_coverage(self, coverage_id, payload, headers):
        return self._request("POST", f"/commercial/rep-coverages/{coverage_id}/extend", payload, headers)

    def end_coverage(self, coverage_id, payload, headers):
        return self._request("POST", f"/commercial/rep-coverages/{coverage_id}/end", payload, headers)

    # ── Part orders ───────────────────────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/commercial/part-orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/commercial/part-orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/commercial/part-orders/{order_id}", headers=headers)

    def update_order(self, order_id, payload, headers):
        return self._request("PUT", f"/commercial/part-orders/{order_id}", payload, headers)

    def confirm_order(self, order_id, payload, headers):
        return self._request("POST", f"/commercial/part-orders/{order_id}/confirm", payload, headers)

    def allocate_order(self, order_id, payload, headers):
        return self._request("POST", f"/commercial/part-orders/{order_id}/allocate", payload, headers)

    def pick_order(self, order_id, payload, headers):
        return self._request("POST", f"/commercial/part-orders/{order_id}/pick", payload, headers)

    def dispatch_order(self, order_id, payload, headers):
        return self._request("POST", f"/commercial/part-orders/{order_id}/dispatch", payload, headers)

    def deliver_order(self, order_id, payload, headers):
        return self._request("POST", f"/commercial/part-orders/{order_id}/deliver", payload, headers)

    def refit_order(self, order_id, payload, headers):
        return self._request("POST", f"/commercial/part-orders/{order_id}/refit", payload, headers)

    def return_order(self, order_id, payload, headers):
        return self._request("POST", f"/commercial/part-orders/{order_id}/return", payload, headers)

    def void_order(self, order_id, payload, headers):
        return self._request("POST", f"/commercial/part-orders/{order_id}/void", payload, headers)

    def list_order_core_returns(self, order_id, headers, params=None):
        return self._request("GET", f"/commercial/part-orders/{order_id}/core-returns",
                             headers=headers, params=params)

    def list_order_route_stops(self, order_id, headers, params=None):
        return self._request("GET", f"/commercial/part-orders/{order_id}/route-stops",
                             headers=headers, params=params)

    # ── Tool catalogue ────────────────────────────────────────────────────
    def create_tool_catalog_entry(self, payload, headers):
        return self._request("POST", "/commercial/tool-catalog", payload, headers)

    def list_tool_catalog(self, headers, params=None):
        return self._request("GET", "/commercial/tool-catalog", headers=headers, params=params)

    def get_tool_catalog_entry(self, tool_catalog_id, headers):
        return self._request("GET", f"/commercial/tool-catalog/{tool_catalog_id}", headers=headers)

    def adjust_tool_wear(self, tool_catalog_id, payload, headers):
        return self._request("POST", f"/commercial/tool-catalog/{tool_catalog_id}/adjust-wear",
                             payload, headers)

    def reset_tool_wear(self, tool_catalog_id, payload, headers):
        return self._request("POST", f"/commercial/tool-catalog/{tool_catalog_id}/reset-wear",
                             payload, headers)

    def list_tool_fitments(self, tool_catalog_id, headers, params=None):
        return self._request("GET", f"/commercial/tool-catalog/{tool_catalog_id}/fitments",
                             headers=headers, params=params)

    def create_tool_fitment(self, tool_catalog_id, payload, headers):
        return self._request("POST", f"/commercial/tool-catalog/{tool_catalog_id}/fitments",
                             payload, headers)

    # ── Tool loans ────────────────────────────────────────────────────────
    def request_loan(self, payload, headers):
        return self._request("POST", "/commercial/tool-loans", payload, headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/commercial/tool-loans", headers=headers, params=params)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/commercial/tool-loans/{loan_id}", headers=headers)

    def adjust_loan_deposit(self, loan_id, payload, headers):
        return self._request("PUT", f"/commercial/tool-loans/{loan_id}", payload, headers)

    def checkout_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/commercial/tool-loans/{loan_id}/checkout", payload, headers)

    def return_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/commercial/tool-loans/{loan_id}/return", payload, headers)

    def inspect_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/commercial/tool-loans/{loan_id}/inspect", payload, headers)

    def close_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/commercial/tool-loans/{loan_id}/close", payload, headers)

    def forfeit_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/commercial/tool-loans/{loan_id}/forfeit", payload, headers)

    # ── Core returns ──────────────────────────────────────────────────────
    def create_core_return(self, payload, headers):
        return self._request("POST", "/commercial/core-returns", payload, headers)

    def list_core_returns(self, headers, params=None):
        return self._request("GET", "/commercial/core-returns", headers=headers, params=params)

    def get_core_return(self, core_return_id, headers):
        return self._request("GET", f"/commercial/core-returns/{core_return_id}", headers=headers)

    def transit_core_return(self, core_return_id, payload, headers):
        return self._request("POST", f"/commercial/core-returns/{core_return_id}/transit",
                             payload, headers)

    def inspect_core_return(self, core_return_id, payload, headers):
        return self._request("POST", f"/commercial/core-returns/{core_return_id}/inspect",
                             payload, headers)

    def credit_core_return(self, core_return_id, payload, headers):
        return self._request("POST", f"/commercial/core-returns/{core_return_id}/credit",
                             payload, headers)

    def reject_core_return(self, core_return_id, payload, headers):
        return self._request("POST", f"/commercial/core-returns/{core_return_id}/reject",
                             payload, headers)

    # ── Warranty registrations ────────────────────────────────────────────
    def create_warranty(self, payload, headers):
        return self._request("POST", "/commercial/warranty-registrations", payload, headers)

    def list_warranties(self, headers, params=None):
        return self._request("GET", "/commercial/warranty-registrations", headers=headers, params=params)

    def get_warranty(self, registration_id, headers):
        return self._request("GET", f"/commercial/warranty-registrations/{registration_id}",
                             headers=headers)

    # ── Service routes and stops ──────────────────────────────────────────
    def create_route(self, payload, headers):
        return self._request("POST", "/commercial/service-routes", payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/commercial/service-routes", headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/commercial/service-routes/{route_id}", headers=headers)

    def create_route_stop(self, route_id, payload, headers):
        return self._request("POST", f"/commercial/service-routes/{route_id}/stops", payload, headers)

    def list_route_stops(self, route_id, headers, params=None):
        return self._request("GET", f"/commercial/service-routes/{route_id}/stops",
                             headers=headers, params=params)

    def get_route_stop(self, route_id, stop_id, headers):
        return self._request("GET", f"/commercial/service-routes/{route_id}/stops/{stop_id}",
                             headers=headers)

    def plan_route(self, route_id, payload, headers):
        return self._request("POST", f"/commercial/service-routes/{route_id}/plan", payload, headers)

    def dispatch_route(self, route_id, payload, headers):
        return self._request("POST", f"/commercial/service-routes/{route_id}/dispatch", payload, headers)

    def revert_route_to_draft(self, route_id, payload, headers):
        return self._request("POST", f"/commercial/service-routes/{route_id}/revert-to-draft",
                             payload, headers)

    def complete_route(self, route_id, payload, headers):
        return self._request("POST", f"/commercial/service-routes/{route_id}/complete", payload, headers)

    def cancel_route(self, route_id, payload, headers):
        return self._request("POST", f"/commercial/service-routes/{route_id}/cancel", payload, headers)

    def list_all_route_stops(self, headers, params=None):
        return self._request("GET", "/commercial/route-stops", headers=headers, params=params)

    def get_stop(self, stop_id, headers):
        return self._request("GET", f"/commercial/route-stops/{stop_id}", headers=headers)

    def list_stop_orders(self, stop_id, headers, params=None):
        return self._request("GET", f"/commercial/route-stops/{stop_id}/orders",
                             headers=headers, params=params)

    def deliver_stop(self, stop_id, payload, headers):
        return self._request("POST", f"/commercial/route-stops/{stop_id}/deliver", payload, headers)

    def miss_stop(self, stop_id, payload, headers):
        return self._request("POST", f"/commercial/route-stops/{stop_id}/miss", payload, headers)

    def reject_stop(self, stop_id, payload, headers):
        return self._request("POST", f"/commercial/route-stops/{stop_id}/reject", payload, headers)


api_client = ApiClient()