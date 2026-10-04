"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock --------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- vendors --------------------------------------------------------
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def list_vendor_lots(self, vendor_id, headers, params=None):
        return self._request("GET", f"/vendors/{vendor_id}/lots", headers=headers, params=params)

    # ---- jurisdiction rules ---------------------------------------------
    def create_jurisdiction_rule(self, payload, headers):
        return self._request("POST", "/jurisdiction-rules", payload, headers)

    def get_jurisdiction_rule(self, rule_id, headers):
        return self._request("GET", f"/jurisdiction-rules/{rule_id}", headers=headers)

    def list_jurisdiction_stores(self, rule_id, headers, params=None):
        return self._request("GET", f"/jurisdiction-rules/{rule_id}/stores", headers=headers, params=params)

    def list_jurisdiction_lots(self, rule_id, headers, params=None):
        return self._request("GET", f"/jurisdiction-rules/{rule_id}/lots", headers=headers, params=params)

    # ---- stores -----------------------------------------------------------
    def create_store(self, payload, headers):
        return self._request("POST", "/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    def update_store(self, store_id, payload, headers):
        return self._request("PATCH", f"/stores/{store_id}", payload, headers)

    def list_store_allocations(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/allocations", headers=headers, params=params)

    def list_store_aisle_assignments(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/aisle-assignments", headers=headers, params=params)

    def list_store_members(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/members", headers=headers, params=params)

    def list_store_purchases(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/purchases", headers=headers, params=params)

    # ---- lots -------------------------------------------------------------
    def create_lot(self, payload, headers):
        return self._request("POST", "/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/lots", headers=headers, params=params)

    def get_lot_summary(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}/summary", headers=headers)

    def regrade_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/regrade", payload, headers)

    # ---- safety screenings -----------------------------------------------
    def create_screening(self, lot_id, headers, payload=None):
        return self._request("POST", f"/lots/{lot_id}/screenings", payload or {}, headers)

    def list_screenings(self, lot_id, headers, params=None):
        return self._request("GET", f"/lots/{lot_id}/screenings", headers=headers, params=params)

    def complete_screening(self, lot_id, screening_id, payload, headers):
        return self._request(
            "POST", f"/lots/{lot_id}/screenings/{screening_id}/complete", payload, headers
        )

    # ---- pricing -----------------------------------------------------------
    def price_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/price", payload, headers)

    # ---- allocations ---------------------------------------------------------
    def create_allocation(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/allocations", payload, headers)

    def list_lot_allocations(self, lot_id, headers, params=None):
        return self._request("GET", f"/lots/{lot_id}/allocations", headers=headers, params=params)

    def get_allocation(self, lot_id, allocation_id, headers):
        return self._request("GET", f"/lots/{lot_id}/allocations/{allocation_id}", headers=headers)

    def commit_allocations(self, lot_id, headers, payload=None):
        return self._request("POST", f"/lots/{lot_id}/allocations/commit", payload or {}, headers)

    def ship_allocation(self, lot_id, allocation_id, headers, payload=None):
        return self._request(
            "POST", f"/lots/{lot_id}/allocations/{allocation_id}/ship", payload or {}, headers
        )

    def receive_allocation(self, lot_id, allocation_id, headers, payload=None):
        return self._request(
            "POST", f"/lots/{lot_id}/allocations/{allocation_id}/receive", payload or {}, headers
        )

    def recall_allocation(self, lot_id, allocation_id, headers, payload=None):
        return self._request(
            "POST", f"/lots/{lot_id}/allocations/{allocation_id}/recall", payload or {}, headers
        )

    def release_allocation(self, lot_id, allocation_id, headers, payload=None):
        return self._request(
            "POST", f"/lots/{lot_id}/allocations/{allocation_id}/release", payload or {}, headers
        )

    def cancel_allocation(self, lot_id, allocation_id, headers, payload=None):
        return self._request(
            "POST", f"/lots/{lot_id}/allocations/{allocation_id}/cancel", payload or {}, headers
        )

    # ---- aisle assignments ----------------------------------------------------
    def create_aisle_assignment(self, store_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/aisle-assignments", payload, headers)

    def list_lot_aisle_assignments(self, lot_id, headers, params=None):
        return self._request("GET", f"/lots/{lot_id}/aisle-assignments", headers=headers, params=params)

    # ---- loyalty members -------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def update_member(self, member_id, payload, headers):
        return self._request("PATCH", f"/members/{member_id}", payload, headers)

    def list_member_purchases(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/purchases", headers=headers, params=params)

    # ---- early-access events ----------------------------------------------------
    def create_early_access_event(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/early-access-events", payload, headers)

    def list_early_access_events(self, lot_id, headers, params=None):
        return self._request("GET", f"/lots/{lot_id}/early-access-events", headers=headers, params=params)

    def cancel_early_access_event(self, lot_id, event_id, headers, payload=None):
        return self._request(
            "POST", f"/lots/{lot_id}/early-access-events/{event_id}/cancel", payload or {}, headers
        )

    # ---- purchases ---------------------------------------------------------------
    def create_purchase(self, store_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/purchases", payload, headers)

    def get_purchase(self, purchase_id, headers):
        return self._request("GET", f"/purchases/{purchase_id}", headers=headers)

    def refund_purchase(self, purchase_id, headers, payload=None):
        return self._request("POST", f"/purchases/{purchase_id}/refund", payload or {}, headers)

    def list_lot_purchases(self, lot_id, headers, params=None):
        return self._request("GET", f"/lots/{lot_id}/purchases", headers=headers, params=params)

    # ---- dispositions ---------------------------------------------------------------
    def create_disposition(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/dispositions", payload, headers)

    def list_dispositions(self, lot_id, headers, params=None):
        return self._request("GET", f"/lots/{lot_id}/dispositions", headers=headers, params=params)

    def apply_disposition(self, lot_id, disposition_id, headers, payload=None):
        return self._request(
            "POST", f"/lots/{lot_id}/dispositions/{disposition_id}/apply", payload or {}, headers
        )


api_client = ApiClient()
