"""API client: one method per PRD section 4 endpoint."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Logical clock ────────────────────────────────────────────────────
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/v1/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    # ── Beef suppliers ───────────────────────────────────────────────────
    def create_supplier(self, payload, headers):
        return self._request("POST", "/v1/suppliers", payload, headers)

    def list_suppliers(self, headers, params=None):
        return self._request("GET", "/v1/suppliers", headers=headers, params=params)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/v1/suppliers/{supplier_id}", headers=headers)

    def retire_supplier(self, supplier_id, headers):
        return self._request("POST", f"/v1/suppliers/{supplier_id}/retire",
                             {}, headers)

    # ── Audits ───────────────────────────────────────────────────────────
    def create_audit(self, supplier_id, payload, headers):
        return self._request("POST", f"/v1/suppliers/{supplier_id}/audits",
                             payload, headers)

    def list_audits(self, supplier_id, headers, params=None):
        return self._request("GET", f"/v1/suppliers/{supplier_id}/audits",
                             headers=headers, params=params)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/v1/audits/{audit_id}", headers=headers)

    def record_audit(self, supplier_id, audit_id, payload, headers):
        return self._request(
            "POST", f"/v1/suppliers/{supplier_id}/audits/{audit_id}/record-audit",
            payload, headers)

    def cancel_audit(self, supplier_id, audit_id, headers):
        return self._request(
            "POST", f"/v1/suppliers/{supplier_id}/audits/{audit_id}/cancel",
            {}, headers)

    # ── Commissaries ─────────────────────────────────────────────────────
    def create_commissary(self, payload, headers):
        return self._request("POST", "/v1/commissaries", payload, headers)

    def list_commissaries(self, headers, params=None):
        return self._request("GET", "/v1/commissaries", headers=headers, params=params)

    def get_commissary(self, commissary_id, headers):
        return self._request("GET", f"/v1/commissaries/{commissary_id}",
                             headers=headers)

    def patch_commissary(self, commissary_id, payload, headers):
        return self._request("PATCH", f"/v1/commissaries/{commissary_id}",
                             payload, headers)

    def begin_build(self, commissary_id, headers):
        return self._request("POST", f"/v1/commissaries/{commissary_id}/begin-build",
                             {}, headers)

    def activate_commissary(self, commissary_id, headers):
        return self._request("POST", f"/v1/commissaries/{commissary_id}/activate",
                             {}, headers)

    def recertify_commissary(self, commissary_id, headers):
        return self._request("POST", f"/v1/commissaries/{commissary_id}/recertify",
                             {}, headers)

    def decommission_commissary(self, commissary_id, headers):
        return self._request(
            "POST", f"/v1/commissaries/{commissary_id}/decommission", {}, headers)

    # ── Trucks ───────────────────────────────────────────────────────────
    def create_truck(self, commissary_id, payload, headers):
        return self._request("POST", f"/v1/commissaries/{commissary_id}/trucks",
                             payload, headers)

    def list_trucks(self, commissary_id, headers, params=None):
        return self._request("GET", f"/v1/commissaries/{commissary_id}/trucks",
                             headers=headers, params=params)

    def get_truck(self, truck_id, headers):
        return self._request("GET", f"/v1/trucks/{truck_id}", headers=headers)

    def retire_truck(self, truck_id, headers):
        return self._request("POST", f"/v1/trucks/{truck_id}/retire", {}, headers)

    # ── Delivery routes ──────────────────────────────────────────────────
    def create_route(self, payload, headers):
        return self._request("POST", "/v1/routes", payload, headers)

    def list_routes_for_commissary(self, commissary_id, headers, params=None):
        return self._request("GET", f"/v1/commissaries/{commissary_id}/routes",
                             headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/v1/routes/{route_id}", headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/v1/routes", headers=headers, params=params)

    def finalize_route(self, route_id, headers):
        return self._request("POST", f"/v1/routes/{route_id}/finalize", {}, headers)

    def complete_route(self, route_id, headers):
        return self._request("POST", f"/v1/routes/{route_id}/complete", {}, headers)

    def cancel_route(self, route_id, headers):
        return self._request("POST", f"/v1/routes/{route_id}/cancel", {}, headers)

    # ── Menu items ───────────────────────────────────────────────────────
    def create_menu_item(self, payload, headers):
        return self._request("POST", "/v1/menu-items", payload, headers)

    def list_menu_items(self, headers, params=None):
        return self._request("GET", "/v1/menu-items", headers=headers, params=params)

    def get_menu_item(self, item_id, headers):
        return self._request("GET", f"/v1/menu-items/{item_id}", headers=headers)

    # ── Stores ───────────────────────────────────────────────────────────
    def create_store(self, payload, headers):
        return self._request("POST", "/v1/stores", payload, headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", "/v1/stores", headers=headers, params=params)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/v1/stores/{store_id}", headers=headers)

    def approve_store(self, store_id, headers):
        return self._request("POST", f"/v1/stores/{store_id}/approve", {}, headers)

    def open_store(self, store_id, headers):
        return self._request("POST", f"/v1/stores/{store_id}/open", {}, headers)

    def close_store(self, store_id, headers):
        return self._request("POST", f"/v1/stores/{store_id}/close", {}, headers)

    def begin_opening_surge(self, store_id, headers):
        return self._request("POST", f"/v1/stores/{store_id}/begin-opening-surge",
                             {}, headers)

    def end_opening_surge(self, store_id, headers):
        return self._request("POST", f"/v1/stores/{store_id}/end-opening-surge",
                             {}, headers)

    # ── Delivery batches ─────────────────────────────────────────────────
    def create_batch(self, payload, headers):
        return self._request("POST", "/v1/batches", payload, headers)

    def list_batches_for_store(self, store_id, headers, params=None):
        return self._request("GET", f"/v1/stores/{store_id}/batches",
                             headers=headers, params=params)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/v1/batches/{batch_id}", headers=headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/v1/batches", headers=headers, params=params)

    def load_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/v1/batches/{batch_id}/load", payload, headers)

    def deliver_batch(self, batch_id, headers):
        return self._request("POST", f"/v1/batches/{batch_id}/deliver", {}, headers)

    def cancel_batch(self, batch_id, headers):
        return self._request("POST", f"/v1/batches/{batch_id}/cancel", {}, headers)

    # ── Orders ───────────────────────────────────────────────────────────
    def create_order(self, store_id, payload, headers):
        return self._request("POST", f"/v1/stores/{store_id}/orders",
                             payload, headers)

    def list_orders_for_store(self, store_id, headers, params=None):
        return self._request("GET", f"/v1/stores/{store_id}/orders",
                             headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/v1/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/v1/orders", headers=headers, params=params)

    def serve_order(self, order_id, headers):
        return self._request("POST", f"/v1/orders/{order_id}/serve", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/v1/orders/{order_id}/cancel", {}, headers)

    # ── Associates ───────────────────────────────────────────────────────
    def create_associate(self, payload, headers):
        return self._request("POST", "/v1/associates", payload, headers)

    def list_associates(self, headers, params=None):
        return self._request("GET", "/v1/associates", headers=headers, params=params)

    def get_associate(self, associate_id, headers):
        return self._request("GET", f"/v1/associates/{associate_id}", headers=headers)

    def list_manager_postings_filled(self, associate_id, headers, params=None):
        return self._request(
            "GET", f"/v1/associates/{associate_id}/manager-postings-filled",
            headers=headers, params=params)

    def patch_associate(self, associate_id, payload, headers):
        return self._request("PATCH", f"/v1/associates/{associate_id}",
                             payload, headers)

    def promote_associate(self, associate_id, headers):
        return self._request("POST", f"/v1/associates/{associate_id}/promote",
                             {}, headers)

    # ── Manager postings and applications ────────────────────────────────
    def create_manager_posting(self, payload, headers):
        return self._request("POST", "/v1/manager-postings", payload, headers)

    def list_manager_postings_for_store(self, store_id, headers, params=None):
        return self._request("GET", f"/v1/stores/{store_id}/manager-postings",
                             headers=headers, params=params)

    def get_manager_posting(self, posting_id, headers):
        return self._request("GET", f"/v1/manager-postings/{posting_id}",
                             headers=headers)

    def create_manager_application(self, posting_id, payload, headers):
        return self._request("POST",
                             f"/v1/manager-postings/{posting_id}/applications",
                             payload, headers)

    def list_applications_for_posting(self, posting_id, headers, params=None):
        return self._request(
            "GET", f"/v1/manager-postings/{posting_id}/applications",
            headers=headers, params=params)

    def list_manager_applications(self, headers, params=None):
        return self._request("GET", "/v1/manager-applications",
                             headers=headers, params=params)

    def list_associate_applications(self, associate_id, headers, params=None):
        return self._request("GET",
                             f"/v1/associates/{associate_id}/manager-applications",
                             headers=headers, params=params)

    def withdraw_application(self, application_id, headers):
        return self._request("POST",
                             f"/v1/manager-applications/{application_id}/withdraw",
                             {}, headers)

    def close_manager_posting(self, posting_id, payload, headers):
        return self._request("POST", f"/v1/manager-postings/{posting_id}/close",
                             payload, headers)

    def cancel_manager_posting(self, posting_id, headers):
        return self._request("POST", f"/v1/manager-postings/{posting_id}/cancel",
                             {}, headers)

    # ── Shift assignments ────────────────────────────────────────────────
    def create_shift(self, store_id, payload, headers):
        return self._request("POST", f"/v1/stores/{store_id}/shifts",
                             payload, headers)

    def list_shifts_for_store(self, store_id, headers, params=None):
        return self._request("GET", f"/v1/stores/{store_id}/shifts",
                             headers=headers, params=params)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/v1/shifts/{shift_id}", headers=headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/v1/shifts", headers=headers, params=params)

    def cancel_shift(self, shift_id, headers):
        return self._request("POST", f"/v1/shifts/{shift_id}/cancel", {}, headers)

    # ── Beef deliveries ──────────────────────────────────────────────────
    def create_beef_delivery(self, payload, headers):
        return self._request("POST", "/v1/beef-deliveries", payload, headers)

    def list_beef_deliveries_for_commissary(self, commissary_id, headers, params=None):
        return self._request("GET",
                             f"/v1/commissaries/{commissary_id}/beef-deliveries",
                             headers=headers, params=params)

    def get_beef_delivery(self, delivery_id, headers):
        return self._request("GET", f"/v1/beef-deliveries/{delivery_id}",
                             headers=headers)

    def list_beef_deliveries(self, headers, params=None):
        return self._request("GET", "/v1/beef-deliveries",
                             headers=headers, params=params)

    def ship_beef_delivery(self, delivery_id, headers):
        return self._request("POST", f"/v1/beef-deliveries/{delivery_id}/ship",
                             {}, headers)

    def confirm_receiving(self, delivery_id, headers):
        return self._request("POST",
                             f"/v1/beef-deliveries/{delivery_id}/confirm-receiving",
                             {}, headers)

    def reject_receiving(self, delivery_id, headers):
        return self._request("POST",
                             f"/v1/beef-deliveries/{delivery_id}/reject-receiving",
                             {}, headers)

    # ── Production runs ──────────────────────────────────────────────────
    def create_production_run(self, commissary_id, payload, headers):
        return self._request("POST",
                             f"/v1/commissaries/{commissary_id}/production-runs",
                             payload, headers)

    def list_production_runs(self, commissary_id, headers, params=None):
        return self._request("GET",
                             f"/v1/commissaries/{commissary_id}/production-runs",
                             headers=headers, params=params)

    def get_production_run(self, run_id, headers):
        return self._request("GET", f"/v1/production-runs/{run_id}", headers=headers)

    def complete_production_run(self, run_id, headers):
        return self._request("POST", f"/v1/production-runs/{run_id}/complete",
                             {}, headers)

    def cancel_production_run(self, run_id, headers):
        return self._request("POST", f"/v1/production-runs/{run_id}/cancel",
                             {}, headers)


api_client = ApiClient()
