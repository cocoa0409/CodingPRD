"""API client: one method per endpoint defined in the PRD (all under /dough-ops)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/dough-ops/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- DoughFacility ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/dough-ops/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/dough-ops/facilities/{facility_id}", headers=headers)

    # --- DoughType ---
    def create_dough_type(self, payload, headers):
        return self._request("POST", "/dough-ops/dough-types", payload, headers)

    def list_dough_types(self, headers, params=None):
        return self._request("GET", "/dough-ops/dough-types", headers=headers, params=params)

    def get_dough_type(self, dough_type_id, headers):
        return self._request("GET", f"/dough-ops/dough-types/{dough_type_id}", headers=headers)

    # --- Cafe ---
    def create_cafe(self, payload, headers):
        return self._request("POST", "/dough-ops/cafes", payload, headers)

    def list_cafes(self, headers, params=None):
        return self._request("GET", "/dough-ops/cafes", headers=headers, params=params)

    def get_cafe(self, cafe_id, headers):
        return self._request("GET", f"/dough-ops/cafes/{cafe_id}", headers=headers)

    def post_payment(self, cafe_id, payload, headers):
        return self._request("POST", f"/dough-ops/cafes/{cafe_id}/payments", payload, headers)

    # --- DemandAdjustment ---
    def create_demand_adjustment(self, payload, headers):
        return self._request("POST", "/dough-ops/demand-adjustments", payload, headers)

    def list_demand_adjustments(self, headers, params=None):
        return self._request("GET", "/dough-ops/demand-adjustments", headers=headers, params=params)

    def get_demand_adjustment(self, adjustment_id, headers):
        return self._request("GET", f"/dough-ops/demand-adjustments/{adjustment_id}", headers=headers)

    def rescind_demand_adjustment(self, adjustment_id, headers):
        return self._request("POST", f"/dough-ops/demand-adjustments/{adjustment_id}/rescind",
                             {}, headers)

    # --- CafeOrder ---
    def create_cafe_order(self, payload, headers):
        return self._request("POST", "/dough-ops/cafe-orders", payload, headers)

    def list_cafe_orders(self, headers, params=None):
        return self._request("GET", "/dough-ops/cafe-orders", headers=headers, params=params)

    def get_cafe_order(self, order_id, headers):
        return self._request("GET", f"/dough-ops/cafe-orders/{order_id}", headers=headers)

    def submit_cafe_order(self, order_id, headers):
        return self._request("POST", f"/dough-ops/cafe-orders/{order_id}/submit", {}, headers)

    def amend_cafe_order(self, order_id, payload, headers):
        return self._request("POST", f"/dough-ops/cafe-orders/{order_id}/amend", payload, headers)

    def cancel_cafe_order(self, order_id, headers):
        return self._request("POST", f"/dough-ops/cafe-orders/{order_id}/cancel", {}, headers)

    # --- ProductionPlan ---
    def create_production_plan(self, facility_id, payload, headers):
        return self._request("POST", f"/dough-ops/facilities/{facility_id}/production-plans",
                             payload, headers)

    def list_production_plans(self, facility_id, headers, params=None):
        return self._request("GET", f"/dough-ops/facilities/{facility_id}/production-plans",
                             headers=headers, params=params)

    def list_production_plans_flat(self, headers, params=None):
        return self._request("GET", "/dough-ops/production-plans", headers=headers, params=params)

    def get_production_plan(self, plan_id, headers):
        return self._request("GET", f"/dough-ops/production-plans/{plan_id}", headers=headers)

    def lock_production_plan(self, facility_id, plan_id, headers):
        return self._request("POST",
                             f"/dough-ops/facilities/{facility_id}/production-plans/{plan_id}/lock",
                             {}, headers)

    def release_production_plan(self, facility_id, plan_id, payload, headers):
        return self._request("POST",
                             f"/dough-ops/facilities/{facility_id}/production-plans/{plan_id}/release",
                             payload, headers)

    def close_production_plan(self, facility_id, plan_id, headers):
        return self._request("POST",
                             f"/dough-ops/facilities/{facility_id}/production-plans/{plan_id}/close",
                             {}, headers)

    # --- DeliveryRoute ---
    def create_route(self, facility_id, payload, headers):
        return self._request("POST", f"/dough-ops/facilities/{facility_id}/routes",
                             payload, headers)

    def list_routes(self, facility_id, headers, params=None):
        return self._request("GET", f"/dough-ops/facilities/{facility_id}/routes",
                             headers=headers, params=params)

    def list_routes_flat(self, headers, params=None):
        return self._request("GET", "/dough-ops/routes", headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/dough-ops/routes/{route_id}", headers=headers)

    def publish_route(self, facility_id, route_id, headers):
        return self._request("POST",
                             f"/dough-ops/facilities/{facility_id}/routes/{route_id}/publish",
                             {}, headers)

    def depart_route(self, facility_id, route_id, headers):
        return self._request("POST",
                             f"/dough-ops/facilities/{facility_id}/routes/{route_id}/depart",
                             {}, headers)

    def cancel_route(self, facility_id, route_id, headers):
        return self._request("POST",
                             f"/dough-ops/facilities/{facility_id}/routes/{route_id}/cancel",
                             {}, headers)

    # --- RouteStop ---
    def create_route_stop(self, facility_id, route_id, payload, headers):
        return self._request("POST",
                             f"/dough-ops/facilities/{facility_id}/routes/{route_id}/stops",
                             payload, headers)

    def list_route_stops(self, facility_id, route_id, headers, params=None):
        return self._request("GET",
                             f"/dough-ops/facilities/{facility_id}/routes/{route_id}/stops",
                             headers=headers, params=params)

    def list_route_stops_flat(self, headers, params=None):
        return self._request("GET", "/dough-ops/route-stops", headers=headers, params=params)

    def get_route_stop(self, stop_id, headers):
        return self._request("GET", f"/dough-ops/route-stops/{stop_id}", headers=headers)

    def arrive_route_stop(self, facility_id, route_id, stop_id, payload, headers):
        return self._request(
            "POST",
            f"/dough-ops/facilities/{facility_id}/routes/{route_id}/stops/{stop_id}/arrive",
            payload, headers)

    # --- CafeSchedule ---
    def create_schedule(self, cafe_id, payload, headers):
        return self._request("POST", f"/dough-ops/cafes/{cafe_id}/schedules", payload, headers)

    def list_schedules(self, cafe_id, headers, params=None):
        return self._request("GET", f"/dough-ops/cafes/{cafe_id}/schedules",
                             headers=headers, params=params)

    def list_schedules_flat(self, headers, params=None):
        return self._request("GET", "/dough-ops/schedules", headers=headers, params=params)

    def get_schedule(self, schedule_id, headers):
        return self._request("GET", f"/dough-ops/schedules/{schedule_id}", headers=headers)

    def open_schedule(self, cafe_id, schedule_id, headers):
        return self._request("POST",
                             f"/dough-ops/cafes/{cafe_id}/schedules/{schedule_id}/open",
                             {}, headers)

    def close_schedule(self, cafe_id, schedule_id, headers):
        return self._request("POST",
                             f"/dough-ops/cafes/{cafe_id}/schedules/{schedule_id}/close",
                             {}, headers)

    # --- BakeEntry ---
    def create_bake_entry(self, cafe_id, schedule_id, payload, headers):
        return self._request("POST",
                             f"/dough-ops/cafes/{cafe_id}/schedules/{schedule_id}/entries",
                             payload, headers)

    def list_bake_entries(self, cafe_id, schedule_id, headers, params=None):
        return self._request("GET",
                             f"/dough-ops/cafes/{cafe_id}/schedules/{schedule_id}/entries",
                             headers=headers, params=params)

    def list_bake_entries_flat(self, headers, params=None):
        return self._request("GET", "/dough-ops/bake-entries", headers=headers, params=params)

    def get_bake_entry(self, entry_id, headers):
        return self._request("GET", f"/dough-ops/bake-entries/{entry_id}", headers=headers)

    def start_proof(self, cafe_id, schedule_id, entry_id, headers):
        return self._request(
            "POST",
            f"/dough-ops/cafes/{cafe_id}/schedules/{schedule_id}/entries/{entry_id}/start-proof",
            {}, headers)

    def start_bake(self, cafe_id, schedule_id, entry_id, headers):
        return self._request(
            "POST",
            f"/dough-ops/cafes/{cafe_id}/schedules/{schedule_id}/entries/{entry_id}/start-bake",
            {}, headers)

    def complete_bake_entry(self, cafe_id, schedule_id, entry_id, headers):
        return self._request(
            "POST",
            f"/dough-ops/cafes/{cafe_id}/schedules/{schedule_id}/entries/{entry_id}/complete",
            {}, headers)

    def discard_bake_entry(self, cafe_id, schedule_id, entry_id, headers):
        return self._request(
            "POST",
            f"/dough-ops/cafes/{cafe_id}/schedules/{schedule_id}/entries/{entry_id}/discard",
            {}, headers)

    # --- DonationPickup ---
    def create_donation_pickup(self, cafe_id, payload, headers):
        return self._request("POST", f"/dough-ops/cafes/{cafe_id}/donation-pickups",
                             payload, headers)

    def list_donation_pickups(self, cafe_id, headers, params=None):
        return self._request("GET", f"/dough-ops/cafes/{cafe_id}/donation-pickups",
                             headers=headers, params=params)

    def list_donation_pickups_flat(self, headers, params=None):
        return self._request("GET", "/dough-ops/donation-pickups", headers=headers, params=params)

    def get_donation_pickup(self, pickup_id, headers):
        return self._request("GET", f"/dough-ops/donation-pickups/{pickup_id}", headers=headers)

    def confirm_donation_pickup(self, cafe_id, pickup_id, headers):
        return self._request("POST",
                             f"/dough-ops/cafes/{cafe_id}/donation-pickups/{pickup_id}/confirm",
                             {}, headers)

    def void_donation_pickup(self, cafe_id, pickup_id, headers):
        return self._request("POST",
                             f"/dough-ops/cafes/{cafe_id}/donation-pickups/{pickup_id}/void",
                             {}, headers)

    # --- BillingPeriod / SettlementLine ---
    def create_billing_period(self, facility_id, payload, headers):
        return self._request("POST", f"/dough-ops/facilities/{facility_id}/billing-periods",
                             payload, headers)

    def list_billing_periods(self, facility_id, headers, params=None):
        return self._request("GET", f"/dough-ops/facilities/{facility_id}/billing-periods",
                             headers=headers, params=params)

    def list_billing_periods_flat(self, headers, params=None):
        return self._request("GET", "/dough-ops/billing-periods", headers=headers, params=params)

    def get_billing_period(self, period_id, headers):
        return self._request("GET", f"/dough-ops/billing-periods/{period_id}", headers=headers)

    def create_settlement_line(self, facility_id, period_id, payload, headers):
        return self._request(
            "POST",
            f"/dough-ops/facilities/{facility_id}/billing-periods/{period_id}/settlement-lines",
            payload, headers)

    def list_settlement_lines(self, facility_id, period_id, headers, params=None):
        return self._request(
            "GET",
            f"/dough-ops/facilities/{facility_id}/billing-periods/{period_id}/settlement-lines",
            headers=headers, params=params)

    def list_settlement_lines_flat(self, headers, params=None):
        return self._request("GET", "/dough-ops/settlement-lines", headers=headers, params=params)

    def get_settlement_line(self, line_id, headers):
        return self._request("GET", f"/dough-ops/settlement-lines/{line_id}", headers=headers)

    def close_billing_period(self, facility_id, period_id, headers):
        return self._request(
            "POST",
            f"/dough-ops/facilities/{facility_id}/billing-periods/{period_id}/close",
            {}, headers)

    def settle_billing_period(self, facility_id, period_id, headers):
        return self._request(
            "POST",
            f"/dough-ops/facilities/{facility_id}/billing-periods/{period_id}/settle",
            {}, headers)


api_client = ApiClient()
