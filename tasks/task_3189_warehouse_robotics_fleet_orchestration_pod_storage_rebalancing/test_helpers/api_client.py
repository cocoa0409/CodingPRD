"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Warehouse robotics fleet API client mounted under /fleet."""

    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/fleet/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- FloorZones ---
    def create_zone(self, payload, headers):
        return self._request("POST", "/fleet/zones", payload, headers)

    def list_zones(self, headers, params=None):
        return self._request("GET", "/fleet/zones", headers=headers, params=params)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/fleet/zones/{zone_id}", headers=headers)

    def list_zone_chargers(self, zone_id, headers, params=None):
        return self._request(
            "GET", f"/fleet/zones/{zone_id}/chargers", headers=headers, params=params
        )

    def list_zone_pods(self, zone_id, headers, params=None):
        return self._request(
            "GET", f"/fleet/zones/{zone_id}/pods", headers=headers, params=params
        )

    def list_zone_pick_stations(self, zone_id, headers, params=None):
        return self._request(
            "GET", f"/fleet/zones/{zone_id}/pick-stations",
            headers=headers, params=params,
        )

    def list_zone_human_entry_permits(self, zone_id, headers, params=None):
        return self._request(
            "GET", f"/fleet/zones/{zone_id}/human-entry-permits",
            headers=headers, params=params,
        )

    # --- DriveUnits ---
    def create_drive_unit(self, payload, headers):
        return self._request("POST", "/fleet/drive-units", payload, headers)

    def list_drive_units(self, headers, params=None):
        return self._request(
            "GET", "/fleet/drive-units", headers=headers, params=params
        )

    def get_drive_unit(self, unit_id, headers):
        return self._request(
            "GET", f"/fleet/drive-units/{unit_id}", headers=headers
        )

    def retire_drive_unit(self, unit_id, headers):
        return self._request(
            "POST", f"/fleet/drive-units/{unit_id}/retire", {}, headers
        )

    # --- Chargers ---
    def create_charger(self, payload, headers):
        return self._request("POST", "/fleet/chargers", payload, headers)

    def get_charger(self, charger_id, headers):
        return self._request("GET", f"/fleet/chargers/{charger_id}", headers=headers)

    def list_charger_sessions(self, charger_id, headers, params=None):
        return self._request(
            "GET", f"/fleet/chargers/{charger_id}/charging-sessions",
            headers=headers, params=params,
        )

    # --- ChargingSessions ---
    def create_charging_session(self, payload, headers):
        return self._request("POST", "/fleet/charging-sessions", payload, headers)

    def get_charging_session(self, session_id, headers):
        return self._request(
            "GET", f"/fleet/charging-sessions/{session_id}", headers=headers
        )

    def list_charging_sessions(self, headers, params=None):
        return self._request(
            "GET", "/fleet/charging-sessions", headers=headers, params=params
        )

    def close_charging_session(self, session_id, headers):
        return self._request(
            "POST", f"/fleet/charging-sessions/{session_id}/close", {}, headers
        )

    # --- Pods ---
    def create_pod(self, payload, headers):
        return self._request("POST", "/fleet/pods", payload, headers)

    def get_pod(self, pod_id, headers):
        return self._request("GET", f"/fleet/pods/{pod_id}", headers=headers)

    def list_pod_inventory_slots(self, pod_id, headers, params=None):
        return self._request(
            "GET", f"/fleet/pods/{pod_id}/inventory-slots",
            headers=headers, params=params,
        )

    # --- Skus ---
    def create_sku(self, payload, headers):
        return self._request("POST", "/fleet/skus", payload, headers)

    def get_sku(self, sku_id, headers):
        return self._request("GET", f"/fleet/skus/{sku_id}", headers=headers)

    def list_skus(self, headers, params=None):
        return self._request("GET", "/fleet/skus", headers=headers, params=params)

    def list_sku_inventory_slots(self, sku_id, headers, params=None):
        return self._request(
            "GET", f"/fleet/skus/{sku_id}/inventory-slots",
            headers=headers, params=params,
        )

    def list_sku_order_lines(self, sku_id, headers, params=None):
        return self._request(
            "GET", f"/fleet/skus/{sku_id}/order-lines",
            headers=headers, params=params,
        )

    # --- Cross-entity filtered lists ---
    def list_inventory_slots(self, headers, params=None):
        return self._request(
            "GET", "/fleet/inventory-slots", headers=headers, params=params
        )

    def list_order_lines(self, headers, params=None):
        return self._request(
            "GET", "/fleet/order-lines", headers=headers, params=params
        )

    # --- PickStations ---
    def create_pick_station(self, payload, headers):
        return self._request("POST", "/fleet/pick-stations", payload, headers)

    def get_pick_station(self, station_id, headers):
        return self._request(
            "GET", f"/fleet/pick-stations/{station_id}", headers=headers
        )

    def pause_pick_station(self, station_id, headers):
        return self._request(
            "POST", f"/fleet/pick-stations/{station_id}/pause", {}, headers
        )

    def reopen_pick_station(self, station_id, headers):
        return self._request(
            "POST", f"/fleet/pick-stations/{station_id}/reopen", {}, headers
        )

    def list_station_pick_tasks(self, station_id, headers, params=None):
        return self._request(
            "GET", f"/fleet/pick-stations/{station_id}/pick-tasks",
            headers=headers, params=params,
        )

    # --- CustomerOrders ---
    def create_customer_order(self, payload, headers):
        return self._request("POST", "/fleet/customer-orders", payload, headers)

    def get_customer_order(self, order_id, headers):
        return self._request(
            "GET", f"/fleet/customer-orders/{order_id}", headers=headers
        )

    def list_customer_orders(self, headers, params=None):
        return self._request(
            "GET", "/fleet/customer-orders", headers=headers, params=params
        )

    def list_order_lines_of_order(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/fleet/customer-orders/{order_id}/lines",
            headers=headers, params=params,
        )

    def list_order_pick_tasks(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/fleet/customer-orders/{order_id}/pick-tasks",
            headers=headers, params=params,
        )

    def cancel_customer_order(self, order_id, headers):
        return self._request(
            "POST", f"/fleet/customer-orders/{order_id}/cancel", {}, headers
        )

    # --- PickTasks ---
    def create_pick_task(self, payload, headers):
        return self._request("POST", "/fleet/pick-tasks", payload, headers)

    def get_pick_task(self, task_id, headers):
        return self._request("GET", f"/fleet/pick-tasks/{task_id}", headers=headers)

    def list_pick_tasks(self, headers, params=None):
        return self._request(
            "GET", "/fleet/pick-tasks", headers=headers, params=params
        )

    def sequence_pick_task(self, task_id, expected_station_version, headers):
        return self._request(
            "POST", f"/fleet/pick-tasks/{task_id}/sequence",
            {"expected_station_version": expected_station_version}, headers,
        )

    def dispatch_pick_task(self, task_id, headers):
        return self._request(
            "POST", f"/fleet/pick-tasks/{task_id}/dispatch", {}, headers
        )

    def deliver_pick_task(self, task_id, headers):
        return self._request(
            "POST", f"/fleet/pick-tasks/{task_id}/deliver", {}, headers
        )

    def begin_pick_task(self, task_id, headers):
        return self._request(
            "POST", f"/fleet/pick-tasks/{task_id}/begin-pick", {}, headers
        )

    def complete_pick_task(self, task_id, headers):
        return self._request(
            "POST", f"/fleet/pick-tasks/{task_id}/complete", {}, headers
        )

    def cancel_pick_task(self, task_id, headers):
        return self._request(
            "POST", f"/fleet/pick-tasks/{task_id}/cancel", {}, headers
        )

    # --- StowTasks ---
    def create_stow_task(self, payload, headers):
        return self._request("POST", "/fleet/stow-tasks", payload, headers)

    def get_stow_task(self, task_id, headers):
        return self._request("GET", f"/fleet/stow-tasks/{task_id}", headers=headers)

    def list_stow_tasks(self, headers, params=None):
        return self._request(
            "GET", "/fleet/stow-tasks", headers=headers, params=params
        )

    def place_stow_task(self, task_id, expected_sku_version, headers):
        return self._request(
            "POST", f"/fleet/stow-tasks/{task_id}/place",
            {"expected_sku_version": expected_sku_version}, headers,
        )

    def confirm_stow_task(self, task_id, headers):
        return self._request(
            "POST", f"/fleet/stow-tasks/{task_id}/confirm", {}, headers
        )

    # --- MaintenanceWindows ---
    def create_maintenance_window(self, payload, headers):
        return self._request("POST", "/fleet/maintenance-windows", payload, headers)

    def get_maintenance_window(self, window_id, headers):
        return self._request(
            "GET", f"/fleet/maintenance-windows/{window_id}", headers=headers
        )

    def list_maintenance_windows(self, headers, params=None):
        return self._request(
            "GET", "/fleet/maintenance-windows", headers=headers, params=params
        )

    def complete_maintenance_window(self, window_id, headers):
        return self._request(
            "POST", f"/fleet/maintenance-windows/{window_id}/complete", {}, headers
        )

    def cancel_maintenance_window(self, window_id, headers):
        return self._request(
            "POST", f"/fleet/maintenance-windows/{window_id}/cancel", {}, headers
        )

    # --- FloorExceptions ---
    def create_floor_exception(self, payload, headers):
        return self._request("POST", "/fleet/floor-exceptions", payload, headers)

    def get_floor_exception(self, exception_id, headers):
        return self._request(
            "GET", f"/fleet/floor-exceptions/{exception_id}", headers=headers
        )

    def list_floor_exceptions(self, headers, params=None):
        return self._request(
            "GET", "/fleet/floor-exceptions", headers=headers, params=params
        )

    def triage_floor_exception(self, exception_id, branch, headers):
        return self._request(
            "POST", f"/fleet/floor-exceptions/{exception_id}/triage",
            {"branch": branch}, headers,
        )

    def resolve_floor_exception(self, exception_id, corrective_outcome, headers):
        return self._request(
            "POST", f"/fleet/floor-exceptions/{exception_id}/resolve",
            {"corrective_outcome": corrective_outcome}, headers,
        )

    # --- HumanEntryPermits ---
    def create_human_entry_permit(self, payload, headers):
        return self._request("POST", "/fleet/human-entry-permits", payload, headers)

    def get_human_entry_permit(self, permit_id, headers):
        return self._request(
            "GET", f"/fleet/human-entry-permits/{permit_id}", headers=headers
        )

    def list_human_entry_permits(self, headers, params=None):
        return self._request(
            "GET", "/fleet/human-entry-permits", headers=headers, params=params
        )

    def grant_human_entry_permit(self, permit_id, headers):
        return self._request(
            "POST", f"/fleet/human-entry-permits/{permit_id}/grant", {}, headers
        )

    def release_human_entry_permit(self, permit_id, headers):
        return self._request(
            "POST", f"/fleet/human-entry-permits/{permit_id}/release", {}, headers
        )

    # --- ShiftPlans ---
    def create_shift_plan(self, payload, headers):
        return self._request("POST", "/fleet/shift-plans", payload, headers)

    def get_shift_plan(self, plan_id, headers):
        return self._request("GET", f"/fleet/shift-plans/{plan_id}", headers=headers)

    # --- SoftwareReleases ---
    def create_software_release(self, payload, headers):
        return self._request("POST", "/fleet/software-releases", payload, headers)

    def get_software_release(self, release_id, headers):
        return self._request(
            "GET", f"/fleet/software-releases/{release_id}", headers=headers
        )

    def list_software_releases(self, headers, params=None):
        return self._request(
            "GET", "/fleet/software-releases", headers=headers, params=params
        )

    def validate_software_release(self, release_id, headers):
        return self._request(
            "POST", f"/fleet/software-releases/{release_id}/validate", {}, headers
        )

    def record_validation(self, release_id, payload, headers):
        return self._request(
            "POST", f"/fleet/software-releases/{release_id}/record-validation",
            payload, headers,
        )

    def revise_software_release(self, release_id, headers):
        return self._request(
            "POST", f"/fleet/software-releases/{release_id}/revise", {}, headers
        )

    def promote_software_release(self, release_id, headers):
        return self._request(
            "POST", f"/fleet/software-releases/{release_id}/promote", {}, headers
        )

    def rollback_software_release(self, release_id, headers):
        return self._request(
            "POST", f"/fleet/software-releases/{release_id}/rollback", {}, headers
        )


api_client = ApiClient()
