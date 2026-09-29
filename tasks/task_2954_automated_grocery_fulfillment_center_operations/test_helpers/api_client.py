"""API client: one method per endpoint defined in the PRD.

All list methods take an optional ``params`` dict carrying the endpoint's
filters plus the ``limit`` / ``offset`` pagination parameters.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the grocery fulfillment centre service."""

    # ── Logical clock ────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Delivery routes ──────────────────────────────────────────────────
    def create_delivery_route(self, payload, headers):
        return self._request("POST", "/delivery-routes", payload, headers)

    def get_delivery_route(self, route_id, headers):
        return self._request("GET", f"/delivery-routes/{route_id}", headers=headers)

    # ── Dock bays ────────────────────────────────────────────────────────
    def create_dock_bay(self, payload, headers):
        return self._request("POST", "/dock-bays", payload, headers)

    def get_dock_bay(self, bay_id, headers):
        return self._request("GET", f"/dock-bays/{bay_id}", headers=headers)

    # ── Grid zones ───────────────────────────────────────────────────────
    def create_grid_zone(self, payload, headers):
        return self._request("POST", "/grid-zones", payload, headers)

    def get_grid_zone(self, zone_id, headers):
        return self._request("GET", f"/grid-zones/{zone_id}", headers=headers)

    def record_audit_counts(self, zone_id, payload, headers):
        return self._request(
            "POST", f"/grid-zones/{zone_id}/audit-counts", payload, headers
        )

    # ── Pick stations ────────────────────────────────────────────────────
    def create_pick_station(self, payload, headers):
        return self._request("POST", "/pick-stations", payload, headers)

    def get_pick_station(self, station_id, headers):
        return self._request("GET", f"/pick-stations/{station_id}", headers=headers)

    # ── Inventory SKUs ───────────────────────────────────────────────────
    def create_inventory_sku(self, payload, headers):
        return self._request("POST", "/inventory-skus", payload, headers)

    def get_inventory_sku(self, sku_id, headers):
        return self._request("GET", f"/inventory-skus/{sku_id}", headers=headers)

    def list_inventory_skus(self, headers, params=None):
        return self._request("GET", "/inventory-skus", headers=headers, params=params)

    # ── Maintenance windows ──────────────────────────────────────────────
    def create_maintenance_window(self, payload, headers):
        return self._request("POST", "/maintenance-windows", payload, headers)

    def get_maintenance_window(self, window_id, headers):
        return self._request(
            "GET", f"/maintenance-windows/{window_id}", headers=headers
        )

    def list_maintenance_windows(self, headers, params=None):
        return self._request(
            "GET", "/maintenance-windows", headers=headers, params=params
        )

    def activate_maintenance_window(self, window_id, headers):
        return self._request(
            "POST", f"/maintenance-windows/{window_id}/activate", headers=headers
        )

    def complete_maintenance_window(self, window_id, headers):
        return self._request(
            "POST", f"/maintenance-windows/{window_id}/complete", headers=headers
        )

    # ── Delivery slots ───────────────────────────────────────────────────
    def create_delivery_slot(self, payload, headers):
        return self._request("POST", "/delivery-slots", payload, headers)

    def get_delivery_slot(self, slot_id, headers):
        return self._request("GET", f"/delivery-slots/{slot_id}", headers=headers)

    def list_delivery_slots(self, headers, params=None):
        return self._request("GET", "/delivery-slots", headers=headers, params=params)

    def release_capacity(self, slot_id, payload, headers):
        return self._request(
            "POST", f"/delivery-slots/{slot_id}/release-capacity", payload, headers
        )

    def withhold_capacity(self, slot_id, payload, headers):
        return self._request(
            "POST", f"/delivery-slots/{slot_id}/withhold-capacity", payload, headers
        )

    # ── Customer accounts ────────────────────────────────────────────────
    def create_customer_account(self, payload, headers):
        return self._request("POST", "/customer-accounts", payload, headers)

    def get_customer_account(self, account_id, headers):
        return self._request("GET", f"/customer-accounts/{account_id}", headers=headers)

    def list_customer_accounts(self, headers, params=None):
        return self._request(
            "GET", "/customer-accounts", headers=headers, params=params
        )

    # ── Customer orders ──────────────────────────────────────────────────
    def create_customer_order(self, payload, headers):
        return self._request("POST", "/customer-orders", payload, headers)

    def get_customer_order(self, order_id, headers):
        return self._request("GET", f"/customer-orders/{order_id}", headers=headers)

    def list_customer_orders(self, headers, params=None):
        return self._request("GET", "/customer-orders", headers=headers, params=params)

    def add_order_line(self, order_id, payload, headers):
        return self._request(
            "POST", f"/customer-orders/{order_id}/lines", payload, headers
        )

    def cancel_customer_order(self, order_id, headers):
        return self._request(
            "POST", f"/customer-orders/{order_id}/cancel", headers=headers
        )

    # ── Order lines ──────────────────────────────────────────────────────
    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def accept_shortage(self, line_id, headers):
        return self._request(
            "POST", f"/order-lines/{line_id}/accept-shortage", headers=headers
        )

    # ── Slot bookings ────────────────────────────────────────────────────
    def create_slot_booking(self, payload, headers):
        return self._request("POST", "/slot-bookings", payload, headers)

    def get_slot_booking(self, booking_id, headers):
        return self._request("GET", f"/slot-bookings/{booking_id}", headers=headers)

    def list_slot_bookings(self, headers, params=None):
        return self._request("GET", "/slot-bookings", headers=headers, params=params)

    def confirm_slot_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/slot-bookings/{booking_id}/confirm", headers=headers
        )

    # ── Delivery waves ───────────────────────────────────────────────────
    def create_delivery_wave(self, payload, headers):
        return self._request("POST", "/delivery-waves", payload, headers)

    def get_delivery_wave(self, wave_id, headers):
        return self._request("GET", f"/delivery-waves/{wave_id}", headers=headers)

    def list_delivery_waves(self, headers, params=None):
        return self._request("GET", "/delivery-waves", headers=headers, params=params)

    def slot_orders(self, wave_id, payload, headers):
        return self._request(
            "POST", f"/delivery-waves/{wave_id}/slot-orders", payload, headers
        )

    def assign_dock(self, wave_id, payload, headers):
        return self._request(
            "POST", f"/delivery-waves/{wave_id}/assign-dock", payload, headers
        )

    def start_picking(self, wave_id, headers):
        return self._request(
            "POST", f"/delivery-waves/{wave_id}/start-picking", headers=headers
        )

    def consolidate_wave(self, wave_id, headers):
        return self._request(
            "POST", f"/delivery-waves/{wave_id}/consolidate", headers=headers
        )

    def compute_loading_sequence(self, wave_id, headers):
        return self._request(
            "POST", f"/delivery-waves/{wave_id}/loading-sequence", headers=headers
        )

    def dispatch_wave(self, wave_id, headers):
        return self._request(
            "POST", f"/delivery-waves/{wave_id}/dispatch", headers=headers
        )

    # ── Totes ────────────────────────────────────────────────────────────
    def create_tote(self, payload, headers):
        return self._request("POST", "/totes", payload, headers)

    def get_tote(self, tote_id, headers):
        return self._request("GET", f"/totes/{tote_id}", headers=headers)

    def list_totes(self, headers, params=None):
        return self._request("GET", "/totes", headers=headers, params=params)

    def seal_tote(self, tote_id, headers):
        return self._request("POST", f"/totes/{tote_id}/seal", headers=headers)

    def unseal_tote(self, tote_id, headers):
        return self._request("POST", f"/totes/{tote_id}/unseal", headers=headers)

    # ── Pick tasks ───────────────────────────────────────────────────────
    def get_pick_task(self, task_id, headers):
        return self._request("GET", f"/pick-tasks/{task_id}", headers=headers)

    def list_pick_tasks(self, headers, params=None):
        return self._request("GET", "/pick-tasks", headers=headers, params=params)

    def assign_tote(self, task_id, payload, headers):
        return self._request(
            "POST", f"/pick-tasks/{task_id}/assign-tote", payload, headers
        )

    def start_retrieval(self, task_id, headers):
        return self._request(
            "POST", f"/pick-tasks/{task_id}/start-retrieval", headers=headers
        )

    def complete_pick_task(self, task_id, payload, headers):
        return self._request(
            "POST", f"/pick-tasks/{task_id}/complete", payload, headers
        )

    def cancel_pick_task(self, task_id, headers):
        return self._request("POST", f"/pick-tasks/{task_id}/cancel", headers=headers)

    # ── Substitution proposals ───────────────────────────────────────────
    def create_substitution_proposal(self, payload, headers):
        return self._request("POST", "/substitution-proposals", payload, headers)

    def get_substitution_proposal(self, proposal_id, headers):
        return self._request(
            "GET", f"/substitution-proposals/{proposal_id}", headers=headers
        )

    def list_substitution_proposals(self, headers, params=None):
        return self._request(
            "GET", "/substitution-proposals", headers=headers, params=params
        )

    def propose_substitution(self, proposal_id, headers):
        return self._request(
            "POST", f"/substitution-proposals/{proposal_id}/propose", headers=headers
        )

    def approve_substitution(self, proposal_id, headers):
        return self._request(
            "POST", f"/substitution-proposals/{proposal_id}/approve", headers=headers
        )

    def decline_substitution(self, proposal_id, headers):
        return self._request(
            "POST", f"/substitution-proposals/{proposal_id}/decline", headers=headers
        )

    def expire_substitution(self, proposal_id, headers):
        return self._request(
            "POST", f"/substitution-proposals/{proposal_id}/expire", headers=headers
        )


api_client = ApiClient()
