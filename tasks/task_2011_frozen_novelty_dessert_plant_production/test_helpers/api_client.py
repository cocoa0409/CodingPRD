"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD §2.7)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Products (PRD §3.1)
    # ------------------------------------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def patch_product(self, product_id, payload, headers):
        return self._request("PATCH", f"/products/{product_id}", payload, headers)

    def discontinue_product(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/discontinue", {}, headers)

    def create_reformulation(self, product_id, payload, headers):
        return self._request("POST", f"/products/{product_id}/reformulations",
                             payload, headers)

    # ------------------------------------------------------------------
    # Customers (PRD §3.2)
    # ------------------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Co-pack contracts (PRD §3.2)
    # ------------------------------------------------------------------
    def create_contract(self, payload, headers):
        return self._request("POST", "/co-pack-contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/co-pack-contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/co-pack-contracts/{contract_id}", headers=headers)

    def submit_contract(self, contract_id, headers):
        return self._request("POST", f"/co-pack-contracts/{contract_id}/submit",
                             {}, headers)

    def approve_contract(self, contract_id, headers):
        return self._request("POST", f"/co-pack-contracts/{contract_id}/approve",
                             {}, headers)

    def amend_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/co-pack-contracts/{contract_id}/amend",
                             payload, headers)

    def cancel_contract(self, contract_id, headers):
        return self._request("POST", f"/co-pack-contracts/{contract_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Mix batches (PRD §3.3)
    # ------------------------------------------------------------------
    def create_mix_batch(self, payload, headers):
        return self._request("POST", "/mix-batches", payload, headers)

    def list_mix_batches(self, headers, params=None):
        return self._request("GET", "/mix-batches", headers=headers, params=params)

    def get_mix_batch(self, batch_id, headers):
        return self._request("GET", f"/mix-batches/{batch_id}", headers=headers)

    def pasteurize_mix_batch(self, batch_id, headers):
        return self._request("POST", f"/mix-batches/{batch_id}/pasteurize", {}, headers)

    def release_mix_batch(self, batch_id, headers):
        return self._request("POST", f"/mix-batches/{batch_id}/release", {}, headers)

    def reject_mix_batch(self, batch_id, headers):
        return self._request("POST", f"/mix-batches/{batch_id}/reject", {}, headers)

    # ------------------------------------------------------------------
    # Lines (PRD §3.4)
    # ------------------------------------------------------------------
    def create_line(self, payload, headers):
        return self._request("POST", "/lines", payload, headers)

    def list_lines(self, headers, params=None):
        return self._request("GET", "/lines", headers=headers, params=params)

    def get_line(self, line_id, headers):
        return self._request("GET", f"/lines/{line_id}", headers=headers)

    # ------------------------------------------------------------------
    # Changeovers (PRD §3.4)
    # ------------------------------------------------------------------
    def create_changeover(self, payload, headers):
        return self._request("POST", "/changeovers", payload, headers)

    def list_changeovers(self, headers, params=None):
        return self._request("GET", "/changeovers", headers=headers, params=params)

    def get_changeover(self, changeover_id, headers):
        return self._request("GET", f"/changeovers/{changeover_id}", headers=headers)

    def complete_changeover(self, changeover_id, headers):
        return self._request("POST", f"/changeovers/{changeover_id}/complete",
                             {}, headers)

    def verify_changeover(self, changeover_id, payload, headers):
        return self._request("POST", f"/changeovers/{changeover_id}/verify",
                             payload, headers)

    # ------------------------------------------------------------------
    # Production runs (PRD §3.5)
    # ------------------------------------------------------------------
    def create_production_run(self, payload, headers):
        return self._request("POST", "/production-runs", payload, headers)

    def list_production_runs(self, headers, params=None):
        return self._request("GET", "/production-runs", headers=headers, params=params)

    def get_production_run(self, run_id, headers):
        return self._request("GET", f"/production-runs/{run_id}", headers=headers)

    def assign_mix(self, run_id, payload, headers):
        return self._request("POST", f"/production-runs/{run_id}/assign-mix",
                             payload, headers)

    def start_run(self, run_id, headers):
        return self._request("POST", f"/production-runs/{run_id}/start", {}, headers)

    def hold_run(self, run_id, headers):
        return self._request("POST", f"/production-runs/{run_id}/hold", {}, headers)

    def resume_run(self, run_id, headers):
        return self._request("POST", f"/production-runs/{run_id}/resume", {}, headers)

    def complete_run(self, run_id, payload, headers):
        return self._request("POST", f"/production-runs/{run_id}/complete",
                             payload, headers)

    def cancel_run(self, run_id, headers):
        return self._request("POST", f"/production-runs/{run_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Tunnels and bookings (PRD §3.5)
    # ------------------------------------------------------------------
    def create_tunnel(self, payload, headers):
        return self._request("POST", "/tunnels", payload, headers)

    def list_tunnels(self, headers, params=None):
        return self._request("GET", "/tunnels", headers=headers, params=params)

    def create_tunnel_booking(self, payload, headers):
        return self._request("POST", "/tunnel-bookings", payload, headers)

    def list_tunnel_bookings(self, headers, params=None):
        return self._request("GET", "/tunnel-bookings", headers=headers, params=params)

    def get_tunnel_booking(self, booking_id, headers):
        return self._request("GET", f"/tunnel-bookings/{booking_id}", headers=headers)

    def cancel_tunnel_booking(self, booking_id, headers):
        return self._request("POST", f"/tunnel-bookings/{booking_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Freezer zones and inventory lots (PRD §3.7)
    # ------------------------------------------------------------------
    def create_freezer_zone(self, payload, headers):
        return self._request("POST", "/freezer-zones", payload, headers)

    def list_freezer_zones(self, headers, params=None):
        return self._request("GET", "/freezer-zones", headers=headers, params=params)

    def get_freezer_zone(self, zone_id, headers):
        return self._request("GET", f"/freezer-zones/{zone_id}", headers=headers)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/inventory-lots", headers=headers, params=params)

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/inventory-lots/{lot_id}", headers=headers)

    def quarantine_lot(self, lot_id, headers):
        return self._request("POST", f"/inventory-lots/{lot_id}/quarantine", {}, headers)

    def release_lot_quarantine(self, lot_id, headers):
        return self._request("POST", f"/inventory-lots/{lot_id}/release-quarantine",
                             {}, headers)

    def destroy_lot(self, lot_id, headers):
        return self._request("POST", f"/inventory-lots/{lot_id}/destroy", {}, headers)

    # ------------------------------------------------------------------
    # Shipments, allocations, temperature readings (PRD §3.8)
    # ------------------------------------------------------------------
    def create_shipment(self, payload, headers):
        return self._request("POST", "/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def create_allocation(self, shipment_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/allocations",
                             payload, headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/shipment-allocations", headers=headers,
                             params=params)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/shipment-allocations/{allocation_id}",
                             headers=headers)

    def release_allocation(self, allocation_id, headers):
        return self._request("POST", f"/shipment-allocations/{allocation_id}/release",
                             {}, headers)

    def load_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/load", {}, headers)

    def dispatch_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/dispatch", {}, headers)

    def deliver_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/deliver", {}, headers)

    def reject_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/reject", {}, headers)

    def append_temperature_readings(self, shipment_id, payload, headers):
        return self._request("POST",
                             f"/shipments/{shipment_id}/temperature-readings",
                             payload, headers)

    def list_temperature_readings(self, shipment_id, headers, params=None):
        return self._request("GET",
                             f"/shipments/{shipment_id}/temperature-readings",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Temperature-abuse claims (PRD §3.9)
    # ------------------------------------------------------------------
    def create_temp_abuse_claim(self, payload, headers):
        return self._request("POST", "/temp-abuse-claims", payload, headers)

    def list_temp_abuse_claims(self, headers, params=None):
        return self._request("GET", "/temp-abuse-claims", headers=headers, params=params)

    def get_temp_abuse_claim(self, claim_id, headers):
        return self._request("GET", f"/temp-abuse-claims/{claim_id}", headers=headers)

    def open_claim_review(self, claim_id, headers):
        return self._request("POST", f"/temp-abuse-claims/{claim_id}/open-review",
                             {}, headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/temp-abuse-claims/{claim_id}/approve",
                             {}, headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"/temp-abuse-claims/{claim_id}/deny", {}, headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/temp-abuse-claims/{claim_id}/pay", {}, headers)

    def appeal_claim(self, claim_id, headers):
        return self._request("POST", f"/temp-abuse-claims/{claim_id}/appeal",
                             {}, headers)

    def withdraw_claim(self, claim_id, headers):
        return self._request("POST", f"/temp-abuse-claims/{claim_id}/withdraw",
                             {}, headers)

    # ------------------------------------------------------------------
    # Quality complaints (PRD §3.10)
    # ------------------------------------------------------------------
    def create_quality_complaint(self, payload, headers):
        return self._request("POST", "/quality-complaints", payload, headers)

    def list_quality_complaints(self, headers, params=None):
        return self._request("GET", "/quality-complaints", headers=headers, params=params)

    def get_quality_complaint(self, complaint_id, headers):
        return self._request("GET", f"/quality-complaints/{complaint_id}",
                             headers=headers)

    def send_complaint_to_lab(self, complaint_id, headers):
        return self._request("POST", f"/quality-complaints/{complaint_id}/send-to-lab",
                             {}, headers)

    def record_lab_result(self, complaint_id, payload, headers):
        return self._request("POST",
                             f"/quality-complaints/{complaint_id}/record-lab-result",
                             payload, headers)

    def disposition_complaint(self, complaint_id, payload, headers):
        return self._request("POST",
                             f"/quality-complaints/{complaint_id}/disposition",
                             payload, headers)

    def withdraw_complaint(self, complaint_id, headers):
        return self._request("POST", f"/quality-complaints/{complaint_id}/withdraw",
                             {}, headers)

    # ------------------------------------------------------------------
    # Seasonal build plans (PRD §3.11)
    # ------------------------------------------------------------------
    def create_seasonal_build_plan(self, payload, headers):
        return self._request("POST", "/seasonal-build-plans", payload, headers)

    def list_seasonal_build_plans(self, headers, params=None):
        return self._request("GET", "/seasonal-build-plans", headers=headers,
                             params=params)

    def get_seasonal_build_plan(self, plan_id, headers):
        return self._request("GET", f"/seasonal-build-plans/{plan_id}", headers=headers)

    def approve_build_plan(self, plan_id, headers):
        return self._request("POST", f"/seasonal-build-plans/{plan_id}/approve",
                             {}, headers)

    def cancel_build_plan(self, plan_id, headers):
        return self._request("POST", f"/seasonal-build-plans/{plan_id}/cancel",
                             {}, headers)


api_client = ApiClient()
