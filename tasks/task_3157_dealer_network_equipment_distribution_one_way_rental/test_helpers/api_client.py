"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/rental-network"


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- locations ---
    def create_location(self, payload, headers):
        return self._request("POST", f"{PREFIX}/locations", payload, headers)

    def list_locations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/locations", headers=headers, params=params)

    def get_location(self, location_id, headers):
        return self._request("GET", f"{PREFIX}/locations/{location_id}", headers=headers)

    def close_location(self, location_id, headers):
        return self._request("POST", f"{PREFIX}/locations/{location_id}/close", {}, headers)

    def reopen_location(self, location_id, headers):
        return self._request("POST", f"{PREFIX}/locations/{location_id}/reopen", {}, headers)

    # --- dealers ---
    def create_dealer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/dealers", payload, headers)

    def list_dealers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/dealers", headers=headers, params=params)

    def get_dealer(self, dealer_id, headers):
        return self._request("GET", f"{PREFIX}/dealers/{dealer_id}", headers=headers)

    def list_dealer_reservation_events(self, dealer_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/dealers/{dealer_id}/reservation-events",
                             headers=headers, params=params)

    def suspend_dealer(self, dealer_id, headers):
        return self._request("POST", f"{PREFIX}/dealers/{dealer_id}/suspend", {}, headers)

    def reactivate_dealer(self, dealer_id, headers):
        return self._request("POST", f"{PREFIX}/dealers/{dealer_id}/reactivate", {}, headers)

    def deactivate_dealer(self, dealer_id, headers):
        return self._request("POST", f"{PREFIX}/dealers/{dealer_id}/deactivate", {}, headers)

    def allocate_dealers(self, payload, headers):
        return self._request("POST", f"{PREFIX}/dealers/allocate", payload, headers)

    def post_performance_reviews(self, payload, headers):
        return self._request("POST", f"{PREFIX}/performance-reviews", payload, headers)

    # --- equipment units ---
    def create_equipment_unit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/equipment-units", payload, headers)

    def list_equipment_units(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/equipment-units", headers=headers, params=params)

    def get_equipment_unit(self, unit_id, headers):
        return self._request("GET", f"{PREFIX}/equipment-units/{unit_id}", headers=headers)

    def set_equipment_unit_status(self, unit_id, payload, headers):
        return self._request("POST", f"{PREFIX}/equipment-units/{unit_id}/status", payload, headers)

    def retire_equipment_unit(self, unit_id, headers):
        return self._request("POST", f"{PREFIX}/equipment-units/{unit_id}/retire", {}, headers)

    # --- vehicle profiles ---
    def create_vehicle_profile(self, payload, headers):
        return self._request("POST", f"{PREFIX}/vehicle-profiles", payload, headers)

    def get_vehicle_profile(self, profile_id, headers):
        return self._request("GET", f"{PREFIX}/vehicle-profiles/{profile_id}", headers=headers)

    # --- customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"{PREFIX}/customers/{customer_id}", headers=headers)

    def verify_license(self, customer_id, headers):
        return self._request("POST", f"{PREFIX}/customers/{customer_id}/verify-license", {}, headers)

    # --- lane rates ---
    def create_lane_rate(self, payload, headers):
        return self._request("POST", f"{PREFIX}/lane-rates", payload, headers)

    def list_lane_rates(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/lane-rates", headers=headers, params=params)

    def get_lane_rate(self, rate_id, headers):
        return self._request("GET", f"{PREFIX}/lane-rates/{rate_id}", headers=headers)

    def activate_lane_rate(self, rate_id, headers):
        return self._request("POST", f"{PREFIX}/lane-rates/{rate_id}/activate", {}, headers)

    def supersede_lane_rate(self, rate_id, headers):
        return self._request("POST", f"{PREFIX}/lane-rates/{rate_id}/supersede", {}, headers)

    # --- reservations ---
    def create_reservation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/reservations", payload, headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/reservations", headers=headers, params=params)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"{PREFIX}/reservations/{reservation_id}", headers=headers)

    def patch_reservation(self, reservation_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/reservations/{reservation_id}", payload, headers)

    def list_reservation_events(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/reservation-events", headers=headers, params=params)

    def get_reservation_events(self, reservation_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/reservations/{reservation_id}/events",
                             headers=headers, params=params)

    def confirm_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"{PREFIX}/reservations/{reservation_id}/confirm",
                             payload, headers)

    def reassign_reservation(self, reservation_id, headers):
        return self._request("POST", f"{PREFIX}/reservations/{reservation_id}/reassign", {}, headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"{PREFIX}/reservations/{reservation_id}/cancel", {}, headers)

    def expire_reservation(self, reservation_id, headers):
        return self._request("POST", f"{PREFIX}/reservations/{reservation_id}/expire", {}, headers)

    def mark_no_show(self, reservation_id, headers):
        return self._request("POST", f"{PREFIX}/reservations/{reservation_id}/mark-no-show",
                             {}, headers)

    # --- rental agreements ---
    def create_rental_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rental-agreements", payload, headers)

    def list_rental_agreements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rental-agreements", headers=headers, params=params)

    def get_rental_agreement(self, agreement_id, headers):
        return self._request("GET", f"{PREFIX}/rental-agreements/{agreement_id}", headers=headers)

    def get_settlement_preview(self, agreement_id, headers):
        return self._request("GET", f"{PREFIX}/rental-agreements/{agreement_id}/settlement-preview",
                             headers=headers)

    def return_rental_agreement(self, agreement_id, headers):
        return self._request("POST", f"{PREFIX}/rental-agreements/{agreement_id}/return", {}, headers)

    def settle_rental_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"{PREFIX}/rental-agreements/{agreement_id}/settle",
                             payload, headers)

    # --- damage protection plans ---
    def create_damage_protection_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/damage-protection-plans", payload, headers)

    def list_damage_protection_plans(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/damage-protection-plans",
                             headers=headers, params=params)

    def get_damage_protection_plan(self, plan_id, headers):
        return self._request("GET", f"{PREFIX}/damage-protection-plans/{plan_id}", headers=headers)

    def cancel_damage_protection_plan(self, plan_id, headers):
        return self._request("POST", f"{PREFIX}/damage-protection-plans/{plan_id}/cancel",
                             {}, headers)

    # --- damage claims ---
    def create_damage_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/damage-claims", payload, headers)

    def list_damage_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/damage-claims", headers=headers, params=params)

    def get_damage_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/damage-claims/{claim_id}", headers=headers)

    def approve_damage_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/damage-claims/{claim_id}/approve", payload, headers)

    def deny_damage_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/damage-claims/{claim_id}/deny", payload, headers)

    def reopen_damage_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/damage-claims/{claim_id}/reopen", {}, headers)

    def pay_damage_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/damage-claims/{claim_id}/pay", {}, headers)

    # --- reposition tasks ---
    def create_reposition_task(self, payload, headers):
        return self._request("POST", f"{PREFIX}/reposition-tasks", payload, headers)

    def list_reposition_tasks(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/reposition-tasks", headers=headers, params=params)

    def get_reposition_task(self, task_id, headers):
        return self._request("GET", f"{PREFIX}/reposition-tasks/{task_id}", headers=headers)

    def get_imbalance_report(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/reposition-tasks/imbalance-report",
                             headers=headers, params=params)

    def assign_reposition_task(self, task_id, payload, headers):
        return self._request("POST", f"{PREFIX}/reposition-tasks/{task_id}/assign",
                             payload, headers)

    def complete_reposition_task(self, task_id, headers):
        return self._request("POST", f"{PREFIX}/reposition-tasks/{task_id}/complete", {}, headers)

    def cancel_reposition_task(self, task_id, headers):
        return self._request("POST", f"{PREFIX}/reposition-tasks/{task_id}/cancel", {}, headers)

    # --- cross-sell orders ---
    def create_cross_sell_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/cross-sell-orders", payload, headers)

    def list_cross_sell_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/cross-sell-orders", headers=headers, params=params)

    def get_cross_sell_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/cross-sell-orders/{order_id}", headers=headers)

    # --- dealer settlements ---
    def create_dealer_settlement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/dealer-settlements", payload, headers)

    def list_dealer_settlements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/dealer-settlements", headers=headers, params=params)

    def get_dealer_settlement(self, settlement_id, headers):
        return self._request("GET", f"{PREFIX}/dealer-settlements/{settlement_id}", headers=headers)

    def approve_dealer_settlement(self, settlement_id, headers):
        return self._request("POST", f"{PREFIX}/dealer-settlements/{settlement_id}/approve",
                             {}, headers)

    def dispute_dealer_settlement(self, settlement_id, headers):
        return self._request("POST", f"{PREFIX}/dealer-settlements/{settlement_id}/dispute",
                             {}, headers)

    def pay_dealer_settlement(self, settlement_id, headers):
        return self._request("POST", f"{PREFIX}/dealer-settlements/{settlement_id}/pay",
                             {}, headers)


api_client = ApiClient()
