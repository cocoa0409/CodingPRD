"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock --------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/networks/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- networks -------------------------------------------------------
    def create_network(self, payload, headers):
        return self._request("POST", "/networks", payload, headers)

    def get_network(self, network_id, headers):
        return self._request("GET", f"/networks/{network_id}", headers=headers)

    def list_networks(self, headers, params=None):
        return self._request("GET", "/networks", headers=headers, params=params)

    def run_ops_run(self, network_id, headers):
        return self._request("POST", f"/networks/{network_id}/ops-runs", {}, headers)

    # ---- hubs -----------------------------------------------------------
    def create_hub(self, network_id, payload, headers):
        return self._request("POST", f"/networks/{network_id}/hubs", payload, headers)

    def get_hub(self, network_id, hub_id, headers):
        return self._request("GET", f"/networks/{network_id}/hubs/{hub_id}", headers=headers)

    def list_hubs(self, network_id, headers, params=None):
        return self._request("GET", f"/networks/{network_id}/hubs", headers=headers, params=params)

    def list_hubs_flat(self, headers, params=None):
        return self._request("GET", "/networks/hubs", headers=headers, params=params)

    def get_hub_flat(self, hub_id, headers):
        return self._request("GET", f"/networks/hubs/{hub_id}", headers=headers)

    # ---- equipment lines ------------------------------------------------
    def create_line(self, network_id, hub_id, payload, headers):
        return self._request(
            "POST", f"/networks/{network_id}/hubs/{hub_id}/lines", payload, headers
        )

    def get_line(self, network_id, hub_id, line_id, headers):
        return self._request(
            "GET", f"/networks/{network_id}/hubs/{hub_id}/lines/{line_id}", headers=headers
        )

    def list_lines(self, network_id, hub_id, headers, params=None):
        return self._request(
            "GET", f"/networks/{network_id}/hubs/{hub_id}/lines", headers=headers, params=params
        )

    def list_lines_flat(self, headers, params=None):
        return self._request("GET", "/networks/lines", headers=headers, params=params)

    def get_line_flat(self, line_id, headers):
        return self._request("GET", f"/networks/lines/{line_id}", headers=headers)

    def degrade_line(self, network_id, hub_id, line_id, headers):
        return self._request(
            "POST", f"/networks/{network_id}/hubs/{hub_id}/lines/{line_id}/degrade", {}, headers
        )

    def start_maintenance(self, network_id, hub_id, line_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/hubs/{hub_id}/lines/{line_id}/maintenance/start",
            {},
            headers,
        )

    def complete_maintenance(self, network_id, hub_id, line_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/hubs/{hub_id}/lines/{line_id}/maintenance/complete",
            {},
            headers,
        )

    def decommission_line(self, network_id, hub_id, line_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/hubs/{hub_id}/lines/{line_id}/decommission",
            {},
            headers,
        )

    # ---- doors ----------------------------------------------------------
    def create_door(self, network_id, payload, headers):
        return self._request("POST", f"/networks/{network_id}/doors", payload, headers)

    def get_door(self, network_id, door_id, headers):
        return self._request("GET", f"/networks/{network_id}/doors/{door_id}", headers=headers)

    def list_doors(self, network_id, headers, params=None):
        return self._request("GET", f"/networks/{network_id}/doors", headers=headers, params=params)

    def list_doors_flat(self, headers, params=None):
        return self._request("GET", "/networks/doors", headers=headers, params=params)

    def get_door_flat(self, door_id, headers):
        return self._request("GET", f"/networks/doors/{door_id}", headers=headers)

    def suspend_door(self, network_id, door_id, headers):
        return self._request(
            "POST", f"/networks/{network_id}/doors/{door_id}/suspend", {}, headers
        )

    def reinstate_door(self, network_id, door_id, headers):
        return self._request(
            "POST", f"/networks/{network_id}/doors/{door_id}/reinstate", {}, headers
        )

    def close_door(self, network_id, door_id, headers):
        return self._request("POST", f"/networks/{network_id}/doors/{door_id}/close", {}, headers)

    # ---- varieties ------------------------------------------------------
    def create_variety(self, network_id, payload, headers):
        return self._request("POST", f"/networks/{network_id}/varieties", payload, headers)

    def get_variety(self, network_id, variety_id, headers):
        return self._request(
            "GET", f"/networks/{network_id}/varieties/{variety_id}", headers=headers
        )

    def list_varieties(self, network_id, headers, params=None):
        return self._request(
            "GET", f"/networks/{network_id}/varieties", headers=headers, params=params
        )

    def list_varieties_flat(self, headers, params=None):
        return self._request("GET", "/networks/varieties", headers=headers, params=params)

    def get_variety_flat(self, variety_id, headers):
        return self._request("GET", f"/networks/varieties/{variety_id}", headers=headers)

    # ---- mix plans / mix plan lines -------------------------------------
    def create_mix_plan(self, network_id, door_id, payload, headers):
        return self._request(
            "POST", f"/networks/{network_id}/doors/{door_id}/mix-plans", payload, headers
        )

    def get_mix_plan(self, network_id, door_id, mix_plan_id, headers):
        return self._request(
            "GET",
            f"/networks/{network_id}/doors/{door_id}/mix-plans/{mix_plan_id}",
            headers=headers,
        )

    def list_mix_plans(self, network_id, door_id, headers, params=None):
        return self._request(
            "GET",
            f"/networks/{network_id}/doors/{door_id}/mix-plans",
            headers=headers,
            params=params,
        )

    def upsert_mix_plan_line(self, network_id, door_id, mix_plan_id, payload, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/doors/{door_id}/mix-plans/{mix_plan_id}/lines",
            payload,
            headers,
        )

    def list_mix_plan_lines(self, network_id, door_id, mix_plan_id, headers, params=None):
        return self._request(
            "GET",
            f"/networks/{network_id}/doors/{door_id}/mix-plans/{mix_plan_id}/lines",
            headers=headers,
            params=params,
        )

    def list_mix_plans_flat(self, headers, params=None):
        return self._request("GET", "/networks/mix-plans", headers=headers, params=params)

    def get_mix_plan_flat(self, mix_plan_id, headers):
        return self._request("GET", f"/networks/mix-plans/{mix_plan_id}", headers=headers)

    def list_mix_plan_lines_flat(self, headers, params=None):
        return self._request("GET", "/networks/mix-plan-lines", headers=headers, params=params)

    def get_mix_plan_line_flat(self, mix_plan_line_id, headers):
        return self._request(
            "GET", f"/networks/mix-plan-lines/{mix_plan_line_id}", headers=headers
        )

    def publish_mix_plan(self, network_id, door_id, mix_plan_id, payload, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/doors/{door_id}/mix-plans/{mix_plan_id}/publish",
            payload,
            headers,
        )

    def lock_mix_plan(self, network_id, door_id, mix_plan_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/doors/{door_id}/mix-plans/{mix_plan_id}/lock",
            {},
            headers,
        )

    # ---- production batches ---------------------------------------------
    def create_batch(self, network_id, hub_id, payload, headers):
        return self._request(
            "POST", f"/networks/{network_id}/hubs/{hub_id}/batches", payload, headers
        )

    def get_batch(self, network_id, hub_id, batch_id, headers):
        return self._request(
            "GET", f"/networks/{network_id}/hubs/{hub_id}/batches/{batch_id}", headers=headers
        )

    def list_batches(self, network_id, hub_id, headers, params=None):
        return self._request(
            "GET", f"/networks/{network_id}/hubs/{hub_id}/batches", headers=headers, params=params
        )

    def list_batches_flat(self, headers, params=None):
        return self._request("GET", "/networks/batches", headers=headers, params=params)

    def get_batch_flat(self, batch_id, headers):
        return self._request("GET", f"/networks/batches/{batch_id}", headers=headers)

    def commit_batch(self, network_id, hub_id, batch_id, payload, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/hubs/{hub_id}/batches/{batch_id}/commit",
            payload,
            headers,
        )

    def start_batch(self, network_id, hub_id, batch_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/hubs/{hub_id}/batches/{batch_id}/start",
            {},
            headers,
        )

    def complete_batch(self, network_id, hub_id, batch_id, payload, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/hubs/{hub_id}/batches/{batch_id}/complete",
            payload,
            headers,
        )

    def cancel_batch(self, network_id, hub_id, batch_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/hubs/{hub_id}/batches/{batch_id}/cancel",
            {},
            headers,
        )

    # ---- routes / stops ---------------------------------------------------
    def create_route(self, network_id, hub_id, payload, headers):
        return self._request(
            "POST", f"/networks/{network_id}/hubs/{hub_id}/routes", payload, headers
        )

    def get_route(self, network_id, hub_id, route_id, headers):
        return self._request(
            "GET", f"/networks/{network_id}/hubs/{hub_id}/routes/{route_id}", headers=headers
        )

    def list_routes(self, network_id, hub_id, headers, params=None):
        return self._request(
            "GET", f"/networks/{network_id}/hubs/{hub_id}/routes", headers=headers, params=params
        )

    def list_routes_flat(self, headers, params=None):
        return self._request("GET", "/networks/routes", headers=headers, params=params)

    def get_route_flat(self, route_id, headers):
        return self._request("GET", f"/networks/routes/{route_id}", headers=headers)

    def list_route_stops_flat(self, headers, params=None):
        return self._request("GET", "/networks/route-stops", headers=headers, params=params)

    def get_route_stop_flat(self, stop_id, headers):
        return self._request("GET", f"/networks/route-stops/{stop_id}", headers=headers)

    def add_route_stop(self, network_id, hub_id, route_id, payload, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/hubs/{hub_id}/routes/{route_id}/stops",
            payload,
            headers,
        )

    def list_route_stops(self, network_id, hub_id, route_id, headers, params=None):
        return self._request(
            "GET",
            f"/networks/{network_id}/hubs/{hub_id}/routes/{route_id}/stops",
            headers=headers,
            params=params,
        )

    def get_route_stop(self, network_id, hub_id, route_id, stop_id, headers):
        return self._request(
            "GET",
            f"/networks/{network_id}/hubs/{hub_id}/routes/{route_id}/stops/{stop_id}",
            headers=headers,
        )

    def lock_route(self, network_id, hub_id, route_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/hubs/{hub_id}/routes/{route_id}/lock",
            {},
            headers,
        )

    def dispatch_route(self, network_id, hub_id, route_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/hubs/{hub_id}/routes/{route_id}/dispatch",
            {},
            headers,
        )

    def reconcile_route(self, network_id, hub_id, route_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/hubs/{hub_id}/routes/{route_id}/reconcile",
            {},
            headers,
        )

    def arrive_stop(self, network_id, hub_id, route_id, stop_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/hubs/{hub_id}/routes/{route_id}/stops/{stop_id}/arrive",
            {},
            headers,
        )

    def deliver_stop(self, network_id, hub_id, route_id, stop_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/hubs/{hub_id}/routes/{route_id}/stops/{stop_id}/deliver",
            {},
            headers,
        )

    def miss_stop(self, network_id, hub_id, route_id, stop_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/hubs/{hub_id}/routes/{route_id}/stops/{stop_id}/miss",
            {},
            headers,
        )

    # ---- shipments --------------------------------------------------------
    def stage_shipment(self, network_id, hub_id, route_id, stop_id, payload, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/hubs/{hub_id}/routes/{route_id}/stops/{stop_id}/shipments",
            payload,
            headers,
        )

    def list_shipments(self, network_id, hub_id, route_id, stop_id, headers, params=None):
        return self._request(
            "GET",
            f"/networks/{network_id}/hubs/{hub_id}/routes/{route_id}/stops/{stop_id}/shipments",
            headers=headers,
            params=params,
        )

    def get_shipment(self, network_id, shipment_id, headers):
        return self._request(
            "GET", f"/networks/{network_id}/shipments/{shipment_id}", headers=headers
        )

    def list_shipments_flat(self, headers, params=None):
        return self._request("GET", "/networks/shipments", headers=headers, params=params)

    def get_shipment_flat(self, shipment_id, headers):
        return self._request("GET", f"/networks/shipments/{shipment_id}", headers=headers)

    def record_delivery(self, network_id, shipment_id, payload, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/shipments/{shipment_id}/record-delivery",
            payload,
            headers,
        )

    # ---- stale credits ----------------------------------------------------
    def create_stale_credit(self, network_id, door_id, payload, headers):
        return self._request(
            "POST", f"/networks/{network_id}/doors/{door_id}/stale-credits", payload, headers
        )

    def list_stale_credits(self, network_id, door_id, headers, params=None):
        return self._request(
            "GET",
            f"/networks/{network_id}/doors/{door_id}/stale-credits",
            headers=headers,
            params=params,
        )

    def get_stale_credit(self, network_id, door_id, stale_credit_id, headers):
        return self._request(
            "GET",
            f"/networks/{network_id}/doors/{door_id}/stale-credits/{stale_credit_id}",
            headers=headers,
        )

    def list_stale_credits_flat(self, headers, params=None):
        return self._request("GET", "/networks/stale-credits", headers=headers, params=params)

    def get_stale_credit_flat(self, stale_credit_id, headers):
        return self._request(
            "GET", f"/networks/stale-credits/{stale_credit_id}", headers=headers
        )

    def dispute_stale_credit(self, network_id, door_id, stale_credit_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/doors/{door_id}/stale-credits/{stale_credit_id}/dispute",
            {},
            headers,
        )

    def resolve_stale_credit(self, network_id, door_id, stale_credit_id, payload, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/doors/{door_id}/stale-credits/{stale_credit_id}/resolve",
            payload,
            headers,
        )

    # ---- fundraiser orders ------------------------------------------------
    def create_fundraiser_order(self, network_id, door_id, payload, headers):
        return self._request(
            "POST", f"/networks/{network_id}/doors/{door_id}/fundraiser-orders", payload, headers
        )

    def get_fundraiser_order(self, network_id, door_id, order_id, headers):
        return self._request(
            "GET",
            f"/networks/{network_id}/doors/{door_id}/fundraiser-orders/{order_id}",
            headers=headers,
        )

    def list_fundraiser_orders_flat(self, headers, params=None):
        return self._request("GET", "/networks/fundraiser-orders", headers=headers, params=params)

    def get_fundraiser_order_flat(self, order_id, headers):
        return self._request("GET", f"/networks/fundraiser-orders/{order_id}", headers=headers)

    def list_fundraiser_orders(self, network_id, door_id, headers, params=None):
        return self._request(
            "GET",
            f"/networks/{network_id}/doors/{door_id}/fundraiser-orders",
            headers=headers,
            params=params,
        )

    def approve_fundraiser_order(self, network_id, door_id, order_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/doors/{door_id}/fundraiser-orders/{order_id}/approve",
            {},
            headers,
        )

    def return_fundraiser_order_for_changes(self, network_id, door_id, order_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/doors/{door_id}/fundraiser-orders/{order_id}/return-for-changes",
            {},
            headers,
        )

    def schedule_fundraiser_order(self, network_id, door_id, order_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/doors/{door_id}/fundraiser-orders/{order_id}/schedule",
            {},
            headers,
        )

    def ready_fundraiser_order(self, network_id, door_id, order_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/doors/{door_id}/fundraiser-orders/{order_id}/ready",
            {},
            headers,
        )

    def fulfill_fundraiser_order(self, network_id, door_id, order_id, payload, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/doors/{door_id}/fundraiser-orders/{order_id}/fulfill",
            payload,
            headers,
        )

    def cancel_fundraiser_order(self, network_id, door_id, order_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/doors/{door_id}/fundraiser-orders/{order_id}/cancel",
            {},
            headers,
        )

    # ---- hot-light windows ------------------------------------------------
    def create_hot_light_window(self, network_id, door_id, payload, headers):
        return self._request(
            "POST", f"/networks/{network_id}/doors/{door_id}/hot-light-windows", payload, headers
        )

    def list_hot_light_windows(self, network_id, door_id, headers, params=None):
        return self._request(
            "GET",
            f"/networks/{network_id}/doors/{door_id}/hot-light-windows",
            headers=headers,
            params=params,
        )

    def get_hot_light_window(self, network_id, door_id, window_id, headers):
        return self._request(
            "GET",
            f"/networks/{network_id}/doors/{door_id}/hot-light-windows/{window_id}",
            headers=headers,
        )

    def list_hot_light_windows_flat(self, headers, params=None):
        return self._request("GET", "/networks/hot-light-windows", headers=headers, params=params)

    def get_hot_light_window_flat(self, window_id, headers):
        return self._request("GET", f"/networks/hot-light-windows/{window_id}", headers=headers)

    def ignite_hot_light_window(self, network_id, door_id, window_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/doors/{door_id}/hot-light-windows/{window_id}/ignite",
            {},
            headers,
        )

    def extend_hot_light_window(self, network_id, door_id, window_id, payload, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/doors/{door_id}/hot-light-windows/{window_id}/extend",
            payload,
            headers,
        )

    def cancel_hot_light_window(self, network_id, door_id, window_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/doors/{door_id}/hot-light-windows/{window_id}/cancel",
            {},
            headers,
        )


api_client = ApiClient()
