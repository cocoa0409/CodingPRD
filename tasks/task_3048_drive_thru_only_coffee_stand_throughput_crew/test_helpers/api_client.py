"""API client: one method per endpoint defined in the PRD (§4).

All resources mount directly off the API root — there is no path prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ---------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- regions ----------------------------------------------------------
    def create_region(self, payload, headers):
        return self._request("POST", "/regions", payload, headers)

    def get_region(self, region_id, headers):
        return self._request("GET", f"/regions/{region_id}", headers=headers)

    # ---- stands -----------------------------------------------------------
    def create_stand(self, payload, headers):
        return self._request("POST", "/stands", payload, headers)

    def get_stand(self, stand_id, headers):
        return self._request("GET", f"/stands/{stand_id}", headers=headers)

    def list_stands(self, headers, params=None):
        return self._request("GET", "/stands", headers=headers, params=params)

    def approve_stand(self, stand_id, headers):
        return self._request("POST", f"/stands/{stand_id}/approve", {}, headers)

    def open_stand(self, stand_id, headers):
        return self._request("POST", f"/stands/{stand_id}/open", {}, headers)

    def throttle_stand(self, stand_id, headers):
        return self._request("POST", f"/stands/{stand_id}/throttle", {}, headers)

    def resume_stand(self, stand_id, headers):
        return self._request("POST", f"/stands/{stand_id}/resume", {}, headers)

    def close_stand(self, stand_id, headers):
        return self._request("POST", f"/stands/{stand_id}/close", {}, headers)

    def get_royalty_statement(self, stand_id, month, headers):
        return self._request(
            "GET", f"/stands/{stand_id}/royalty-statement",
            headers=headers, params={"month": month},
        )

    # ---- crew members -----------------------------------------------------
    def create_crew_member(self, payload, headers):
        return self._request("POST", "/crew-members", payload, headers)

    def get_crew_member(self, crew_member_id, headers):
        return self._request("GET", f"/crew-members/{crew_member_id}", headers=headers)

    def list_crew_members(self, headers, params=None):
        return self._request("GET", "/crew-members", headers=headers, params=params)

    def update_crew_member(self, crew_member_id, payload, headers):
        return self._request(
            "PATCH", f"/crew-members/{crew_member_id}", payload, headers
        )

    # ---- operator agreements ----------------------------------------------
    def create_agreement(self, payload, headers):
        return self._request("POST", "/operator-agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/operator-agreements/{agreement_id}", headers=headers
        )

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/operator-agreements", headers=headers, params=params)

    def approve_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/operator-agreements/{agreement_id}/approve", {}, headers
        )

    def activate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/operator-agreements/{agreement_id}/activate", {}, headers
        )

    def suspend_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/operator-agreements/{agreement_id}/suspend", {}, headers
        )

    def reinstate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/operator-agreements/{agreement_id}/reinstate", {}, headers
        )

    def terminate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/operator-agreements/{agreement_id}/terminate", {}, headers
        )

    # ---- recipes ----------------------------------------------------------
    def create_recipe(self, payload, headers):
        return self._request("POST", "/recipes", payload, headers)

    def get_recipe(self, recipe_id, headers):
        return self._request("GET", f"/recipes/{recipe_id}", headers=headers)

    def retire_recipe(self, recipe_id, headers):
        return self._request("POST", f"/recipes/{recipe_id}/retire", {}, headers)

    # ---- recipe distributions ---------------------------------------------
    def create_distribution(self, payload, headers):
        return self._request("POST", "/recipe-distributions", payload, headers)

    def get_distribution(self, distribution_id, headers):
        return self._request(
            "GET", f"/recipe-distributions/{distribution_id}", headers=headers
        )

    def list_distributions(self, headers, params=None):
        return self._request(
            "GET", "/recipe-distributions", headers=headers, params=params
        )

    def activate_distribution(self, distribution_id, headers):
        return self._request(
            "POST", f"/recipe-distributions/{distribution_id}/activate", {}, headers
        )

    def suspend_distribution(self, distribution_id, headers):
        return self._request(
            "POST", f"/recipe-distributions/{distribution_id}/suspend", {}, headers
        )

    def withdraw_distribution(self, distribution_id, headers):
        return self._request(
            "POST", f"/recipe-distributions/{distribution_id}/withdraw", {}, headers
        )

    # ---- loyalty accounts ---------------------------------------------------
    def create_loyalty_account(self, payload, headers):
        return self._request("POST", "/loyalty-accounts", payload, headers)

    def get_loyalty_account(self, account_id, headers):
        return self._request("GET", f"/loyalty-accounts/{account_id}", headers=headers)

    def list_loyalty_accounts(self, headers, params=None):
        return self._request("GET", "/loyalty-accounts", headers=headers, params=params)

    def adjust_points(self, account_id, payload, headers):
        return self._request(
            "POST", f"/loyalty-accounts/{account_id}/points-adjustments",
            payload, headers,
        )

    # ---- shifts and assignments ---------------------------------------------
    def create_shift(self, payload, headers):
        return self._request("POST", "/shifts", payload, headers)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/shifts/{shift_id}", headers=headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/shifts", headers=headers, params=params)

    def create_assignment(self, shift_id, payload, headers):
        return self._request(
            "POST", f"/shifts/{shift_id}/assignments", payload, headers
        )

    def get_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/shift-assignments/{assignment_id}", headers=headers
        )

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/shift-assignments", headers=headers, params=params)

    def cancel_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/shift-assignments/{assignment_id}/cancel", {}, headers
        )

    def check_in_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/shift-assignments/{assignment_id}/check-in", {}, headers
        )

    def publish_shift(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/publish", {}, headers)

    def start_shift(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/start", {}, headers)

    def reconcile_shift(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/reconcile", {}, headers)

    def lock_shift(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/lock", {}, headers)

    # ---- orders and items ----------------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def merge_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/merge", payload, headers)

    def abandon_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/abandon", {}, headers)

    def call_to_window(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/call-to-window", {}, headers)

    def handoff_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/handoff", {}, headers)

    def get_order_item(self, item_id, headers):
        return self._request("GET", f"/order-items/{item_id}", headers=headers)

    def list_order_items(self, headers, params=None):
        return self._request("GET", "/order-items", headers=headers, params=params)

    def start_build(self, item_id, headers):
        return self._request("POST", f"/order-items/{item_id}/start-build", {}, headers)

    def complete_build(self, item_id, headers):
        return self._request(
            "POST", f"/order-items/{item_id}/complete-build", {}, headers
        )

    # ---- payments ------------------------------------------------------------
    def authorize_payment(self, order_id, payload, headers):
        return self._request(
            "POST", f"/orders/{order_id}/payments/authorize", payload, headers
        )

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def capture_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/capture", {}, headers)

    def refund_payment(self, payment_id, payload, headers):
        return self._request("POST", f"/payments/{payment_id}/refunds", payload, headers)

    def decide_refund(self, payment_id, payload, headers):
        return self._request(
            "POST", f"/payments/{payment_id}/refund-decisions", payload, headers
        )

    # ---- throughput windows ---------------------------------------------------
    def create_window(self, payload, headers):
        return self._request("POST", "/throughput-windows", payload, headers)

    def get_window(self, window_id, headers):
        return self._request("GET", f"/throughput-windows/{window_id}", headers=headers)

    def list_windows(self, headers, params=None):
        return self._request("GET", "/throughput-windows", headers=headers, params=params)

    def close_window(self, window_id, headers):
        return self._request(
            "POST", f"/throughput-windows/{window_id}/close", {}, headers
        )


api_client = ApiClient()
