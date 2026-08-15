"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint, PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Manufacturer lines
    # ------------------------------------------------------------------
    def create_manufacturer_line(self, payload, headers):
        return self._request("POST", "/manufacturer-lines", payload, headers)

    def list_manufacturer_lines(self, headers, params=None):
        return self._request("GET", "/manufacturer-lines", headers=headers, params=params)

    def get_manufacturer_line(self, line_id, headers):
        return self._request("GET", f"/manufacturer-lines/{line_id}", headers=headers)

    # ------------------------------------------------------------------
    # Parts
    # ------------------------------------------------------------------
    def create_part(self, payload, headers):
        return self._request("POST", "/parts", payload, headers)

    def list_parts(self, headers, params=None):
        return self._request("GET", "/parts", headers=headers, params=params)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/parts/{part_id}", headers=headers)

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ------------------------------------------------------------------
    # Design registrations
    # ------------------------------------------------------------------
    def create_design_registration(self, payload, headers):
        return self._request("POST", "/design-registrations", payload, headers)

    def list_design_registrations(self, headers, params=None):
        return self._request("GET", "/design-registrations", headers=headers, params=params)

    def get_design_registration(self, registration_id, headers):
        return self._request("GET", f"/design-registrations/{registration_id}",
                             headers=headers)

    def decide_design_registration(self, registration_id, payload, headers):
        return self._request("POST",
                             f"/design-registrations/{registration_id}/decision",
                             payload, headers)

    # ------------------------------------------------------------------
    # Orders and order lines
    # ------------------------------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def acknowledge_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/acknowledge", {}, headers)

    def release_hold_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/release-hold", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    def reschedule_order_line(self, order_id, line_id, payload, headers):
        return self._request("POST",
                             f"/orders/{order_id}/lines/{line_id}/reschedule",
                             payload, headers)

    def cancel_order_line(self, order_id, line_id, headers):
        return self._request("POST", f"/orders/{order_id}/lines/{line_id}/cancel",
                             {}, headers)

    def ship_order_line(self, order_id, line_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines/{line_id}/ship",
                             payload, headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    # ------------------------------------------------------------------
    # Alternate part approvals
    # ------------------------------------------------------------------
    def create_alternate_approval(self, payload, headers):
        return self._request("POST", "/alternate-approvals", payload, headers)

    def list_alternate_approvals(self, headers, params=None):
        return self._request("GET", "/alternate-approvals", headers=headers, params=params)

    def get_alternate_approval(self, approval_id, headers):
        return self._request("GET", f"/alternate-approvals/{approval_id}", headers=headers)

    def decide_alternate_approval(self, approval_id, payload, headers):
        return self._request("POST",
                             f"/alternate-approvals/{approval_id}/decision",
                             payload, headers)

    # ------------------------------------------------------------------
    # Inventory lots and moisture exposures
    # ------------------------------------------------------------------
    def create_lot(self, payload, headers):
        return self._request("POST", "/lots", payload, headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def inspect_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/inspect", payload, headers)

    def open_exposure(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/exposures", payload, headers)

    def list_exposures(self, lot_id, headers, params=None):
        return self._request("GET", f"/lots/{lot_id}/exposures",
                             headers=headers, params=params)

    def seal_exposure(self, lot_id, exposure_id, headers):
        return self._request("POST",
                             f"/lots/{lot_id}/exposures/{exposure_id}/seal",
                             {}, headers)

    def bake_lot(self, lot_id, headers):
        return self._request("POST", f"/lots/{lot_id}/bake", {}, headers)

    # ------------------------------------------------------------------
    # Allocation runs
    # ------------------------------------------------------------------
    def create_allocation_run(self, payload, headers):
        return self._request("POST", "/allocation-runs", payload, headers)

    def list_allocation_runs(self, headers, params=None):
        return self._request("GET", "/allocation-runs", headers=headers, params=params)

    def get_allocation_run(self, run_id, headers):
        return self._request("GET", f"/allocation-runs/{run_id}", headers=headers)

    def publish_allocation_run(self, run_id, headers):
        return self._request("POST", f"/allocation-runs/{run_id}/publish", {}, headers)

    # ------------------------------------------------------------------
    # Ship-and-debit claims
    # ------------------------------------------------------------------
    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def supplier_decide_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/supplier-decision",
                             payload, headers)

    def resubmit_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/resubmit", payload, headers)

    def settle_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/settle", {}, headers)

    def reverse_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/reverse", payload, headers)

    # ------------------------------------------------------------------
    # Buy-back requests
    # ------------------------------------------------------------------
    def create_buyback(self, payload, headers):
        return self._request("POST", "/buy-backs", payload, headers)

    def list_buybacks(self, headers, params=None):
        return self._request("GET", "/buy-backs", headers=headers, params=params)

    def get_buyback(self, buyback_id, headers):
        return self._request("GET", f"/buy-backs/{buyback_id}", headers=headers)

    def decide_buyback(self, buyback_id, payload, headers):
        return self._request("POST", f"/buy-backs/{buyback_id}/decision",
                             payload, headers)

    def receive_buyback(self, buyback_id, payload, headers):
        return self._request("POST", f"/buy-backs/{buyback_id}/receive",
                             payload, headers)


api_client = ApiClient()
