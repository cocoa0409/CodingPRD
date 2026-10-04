"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock / ops ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/dealer-network/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    def ops_run(self, headers):
        return self._request("POST", "/dealer-network/ops/run", {}, headers)

    # --- regions ---
    def create_region(self, payload, headers):
        return self._request("POST", "/dealer-network/regions", payload, headers)

    def list_regions(self, headers, params=None):
        return self._request("GET", "/dealer-network/regions", headers=headers, params=params)

    def get_region(self, region_id, headers):
        return self._request("GET", f"/dealer-network/regions/{region_id}", headers=headers)

    # --- colorant systems ---
    def create_colorant_system(self, payload, headers):
        return self._request("POST", "/dealer-network/colorant-systems", payload, headers)

    def list_colorant_systems(self, headers, params=None):
        return self._request("GET", "/dealer-network/colorant-systems", headers=headers, params=params)

    def get_colorant_system(self, system_id, headers):
        return self._request("GET", f"/dealer-network/colorant-systems/{system_id}", headers=headers)

    def retire_colorant_system(self, system_id, headers):
        return self._request("POST", f"/dealer-network/colorant-systems/{system_id}/retire", {}, headers)

    # --- product lines ---
    def create_product_line(self, payload, headers):
        return self._request("POST", "/dealer-network/product-lines", payload, headers)

    def list_product_lines(self, headers, params=None):
        return self._request("GET", "/dealer-network/product-lines", headers=headers, params=params)

    def get_product_line(self, line_id, headers):
        return self._request("GET", f"/dealer-network/product-lines/{line_id}", headers=headers)

    def discontinue_product_line(self, line_id, headers):
        return self._request("POST", f"/dealer-network/product-lines/{line_id}/discontinue", {}, headers)

    # --- formulas ---
    def create_formula(self, payload, headers):
        return self._request("POST", "/dealer-network/formulas", payload, headers)

    def list_formulas(self, headers, params=None):
        return self._request("GET", "/dealer-network/formulas", headers=headers, params=params)

    def get_formula(self, formula_id, headers):
        return self._request("GET", f"/dealer-network/formulas/{formula_id}", headers=headers)

    # --- dealers ---
    def create_dealer(self, payload, headers):
        return self._request("POST", "/dealer-network/dealers", payload, headers)

    def list_dealers(self, headers, params=None):
        return self._request("GET", "/dealer-network/dealers", headers=headers, params=params)

    def get_dealer(self, dealer_id, headers):
        return self._request("GET", f"/dealer-network/dealers/{dealer_id}", headers=headers)

    def attest_dealer(self, dealer_id, payload, headers):
        return self._request("POST", f"/dealer-network/dealers/{dealer_id}/attest", payload, headers)

    def begin_onboarding(self, dealer_id, headers):
        return self._request("POST", f"/dealer-network/dealers/{dealer_id}/begin-onboarding", {}, headers)

    def activate_dealer(self, dealer_id, headers):
        return self._request("POST", f"/dealer-network/dealers/{dealer_id}/activate", {}, headers)

    def suspend_dealer(self, dealer_id, headers):
        return self._request("POST", f"/dealer-network/dealers/{dealer_id}/suspend", {}, headers)

    def reinstate_dealer(self, dealer_id, headers):
        return self._request("POST", f"/dealer-network/dealers/{dealer_id}/reinstate", {}, headers)

    def terminate_dealer(self, dealer_id, headers):
        return self._request("POST", f"/dealer-network/dealers/{dealer_id}/terminate", {}, headers)

    # --- applications ---
    def create_application(self, payload, headers):
        return self._request("POST", "/dealer-network/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/dealer-network/applications", headers=headers, params=params)

    def get_application(self, app_id, headers):
        return self._request("GET", f"/dealer-network/applications/{app_id}", headers=headers)

    def submit_application(self, app_id, headers):
        return self._request("POST", f"/dealer-network/applications/{app_id}/submit", {}, headers)

    def notify_neighbor(self, app_id, headers):
        return self._request("POST", f"/dealer-network/applications/{app_id}/notify-neighbor", {}, headers)

    def approve_application(self, app_id, payload, headers):
        return self._request("POST", f"/dealer-network/applications/{app_id}/approve", payload, headers)

    def reject_application(self, app_id, headers):
        return self._request("POST", f"/dealer-network/applications/{app_id}/reject", {}, headers)

    def withdraw_application(self, app_id, headers):
        return self._request("POST", f"/dealer-network/applications/{app_id}/withdraw", {}, headers)

    # --- equipment ---
    def create_equipment(self, payload, headers):
        return self._request("POST", "/dealer-network/equipment", payload, headers)

    def list_equipment(self, headers, params=None):
        return self._request("GET", "/dealer-network/equipment", headers=headers, params=params)

    def get_equipment(self, equip_id, headers):
        return self._request("GET", f"/dealer-network/equipment/{equip_id}", headers=headers)

    def record_calibration(self, equip_id, payload, headers):
        return self._request("POST", f"/dealer-network/equipment/{equip_id}/calibrations", payload, headers)

    def decommission_equipment(self, equip_id, headers):
        return self._request("POST", f"/dealer-network/equipment/{equip_id}/decommission", {}, headers)

    # --- licenses ---
    def create_license(self, payload, headers):
        return self._request("POST", "/dealer-network/licenses", payload, headers)

    def list_licenses(self, headers, params=None):
        return self._request("GET", "/dealer-network/licenses", headers=headers, params=params)

    def get_license(self, lic_id, headers):
        return self._request("GET", f"/dealer-network/licenses/{lic_id}", headers=headers)

    def renew_license(self, lic_id, headers):
        return self._request("POST", f"/dealer-network/licenses/{lic_id}/renew", {}, headers)

    def revoke_license(self, lic_id, headers):
        return self._request("POST", f"/dealer-network/licenses/{lic_id}/revoke", {}, headers)

    # --- orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/dealer-network/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/dealer-network/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/dealer-network/orders/{order_id}", headers=headers)

    def approve_order(self, order_id, headers):
        return self._request("POST", f"/dealer-network/orders/{order_id}/approve", {}, headers)

    def reject_order(self, order_id, headers):
        return self._request("POST", f"/dealer-network/orders/{order_id}/reject", {}, headers)

    def fulfill_order(self, order_id, headers):
        return self._request("POST", f"/dealer-network/orders/{order_id}/fulfill", {}, headers)

    def invoice_order(self, order_id, headers):
        return self._request("POST", f"/dealer-network/orders/{order_id}/invoice", {}, headers)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/dealer-network/orders/{order_id}/pay", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/dealer-network/orders/{order_id}/cancel", {}, headers)

    # --- contractors & purchases ---
    def create_contractor(self, payload, headers):
        return self._request("POST", "/dealer-network/contractors", payload, headers)

    def list_contractors(self, headers, params=None):
        return self._request("GET", "/dealer-network/contractors", headers=headers, params=params)

    def get_contractor(self, contractor_id, headers):
        return self._request("GET", f"/dealer-network/contractors/{contractor_id}", headers=headers)

    def close_contractor(self, contractor_id, headers):
        return self._request("POST", f"/dealer-network/contractors/{contractor_id}/close", {}, headers)

    def create_purchase(self, payload, headers):
        return self._request("POST", "/dealer-network/purchases", payload, headers)

    def list_purchases(self, headers, params=None):
        return self._request("GET", "/dealer-network/purchases", headers=headers, params=params)

    def get_purchase(self, purchase_id, headers):
        return self._request("GET", f"/dealer-network/purchases/{purchase_id}", headers=headers)

    def void_purchase(self, purchase_id, headers):
        return self._request("POST", f"/dealer-network/purchases/{purchase_id}/void", {}, headers)

    # --- co-op claims ---
    def create_coop_claim(self, payload, headers):
        return self._request("POST", "/dealer-network/coop-claims", payload, headers)

    def list_coop_claims(self, headers, params=None):
        return self._request("GET", "/dealer-network/coop-claims", headers=headers, params=params)

    def get_coop_claim(self, claim_id, headers):
        return self._request("GET", f"/dealer-network/coop-claims/{claim_id}", headers=headers)

    def approve_coop_claim(self, claim_id, headers):
        return self._request("POST", f"/dealer-network/coop-claims/{claim_id}/approve", {}, headers)

    def reject_coop_claim(self, claim_id, headers):
        return self._request("POST", f"/dealer-network/coop-claims/{claim_id}/reject", {}, headers)

    def pay_coop_claim(self, claim_id, headers):
        return self._request("POST", f"/dealer-network/coop-claims/{claim_id}/pay", {}, headers)

    # --- channel events ---
    def create_channel_event(self, dealer_id, payload, headers):
        return self._request("POST", f"/dealer-network/dealers/{dealer_id}/channel-events", payload, headers)

    def list_channel_events(self, dealer_id, headers, params=None):
        return self._request("GET", f"/dealer-network/dealers/{dealer_id}/channel-events", headers=headers, params=params)

    # --- formulation changes & rematch tasks ---
    def create_formulation_change(self, payload, headers):
        return self._request("POST", "/dealer-network/formulation-changes", payload, headers)

    def list_formulation_changes(self, headers, params=None):
        return self._request("GET", "/dealer-network/formulation-changes", headers=headers, params=params)

    def get_formulation_change(self, change_id, headers):
        return self._request("GET", f"/dealer-network/formulation-changes/{change_id}", headers=headers)

    def announce_formulation_change(self, change_id, payload, headers):
        return self._request("POST", f"/dealer-network/formulation-changes/{change_id}/announce", payload, headers)

    def make_effective_formulation_change(self, change_id, headers):
        return self._request("POST", f"/dealer-network/formulation-changes/{change_id}/make-effective", {}, headers)

    def cancel_formulation_change(self, change_id, headers):
        return self._request("POST", f"/dealer-network/formulation-changes/{change_id}/cancel", {}, headers)

    def list_rematch_tasks(self, headers, params=None):
        return self._request("GET", "/dealer-network/rematch-tasks", headers=headers, params=params)

    def list_change_rematch_tasks(self, change_id, headers, params=None):
        return self._request(
            "GET", f"/dealer-network/formulation-changes/{change_id}/rematch-tasks",
            headers=headers, params=params,
        )

    def list_dealer_rematch_tasks(self, dealer_id, headers, params=None):
        return self._request(
            "GET", f"/dealer-network/dealers/{dealer_id}/rematch-tasks",
            headers=headers, params=params,
        )

    def list_formula_rematch_tasks(self, formula_id, headers, params=None):
        return self._request(
            "GET", f"/dealer-network/formulas/{formula_id}/rematch-tasks",
            headers=headers, params=params,
        )

    def complete_rematch_task(self, task_id, headers):
        return self._request("POST", f"/dealer-network/rematch-tasks/{task_id}/complete", {}, headers)


api_client = ApiClient()
