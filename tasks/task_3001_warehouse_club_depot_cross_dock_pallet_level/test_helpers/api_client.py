"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock --------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/wcd/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- regions --------------------------------------------------------
    def create_region(self, payload, headers):
        return self._request("POST", "/wcd/regions", payload, headers)

    def list_regions(self, headers, params=None):
        return self._request("GET", "/wcd/regions", headers=headers, params=params)

    def get_region(self, region_id, headers):
        return self._request("GET", f"/wcd/regions/{region_id}", headers=headers)

    # ---- vendors --------------------------------------------------------
    def create_vendor(self, payload, headers):
        return self._request("POST", "/wcd/vendors", payload, headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/wcd/vendors", headers=headers, params=params)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/wcd/vendors/{vendor_id}", headers=headers)

    def list_vendor_appointments(self, vendor_id, headers, params=None):
        return self._request(
            "GET", f"/wcd/vendors/{vendor_id}/appointments", headers=headers, params=params
        )

    def reinstate_vendor(self, vendor_id, headers, payload=None):
        return self._request(
            "POST", f"/wcd/vendors/{vendor_id}/reinstate", payload or {}, headers
        )

    def deactivate_vendor(self, vendor_id, headers, payload=None):
        return self._request(
            "POST", f"/wcd/vendors/{vendor_id}/deactivate", payload or {}, headers
        )

    # ---- clubs ----------------------------------------------------------
    def create_club(self, payload, headers):
        return self._request("POST", "/wcd/clubs", payload, headers)

    def list_clubs(self, headers, params=None):
        return self._request("GET", "/wcd/clubs", headers=headers, params=params)

    def get_club(self, club_id, headers):
        return self._request("GET", f"/wcd/clubs/{club_id}", headers=headers)

    def list_club_members(self, club_id, headers, params=None):
        return self._request(
            "GET", f"/wcd/clubs/{club_id}/members", headers=headers, params=params
        )

    def list_club_allocations(self, club_id, headers, params=None):
        return self._request(
            "GET", f"/wcd/clubs/{club_id}/allocations", headers=headers, params=params
        )

    def list_club_department_sales(self, club_id, headers, params=None):
        return self._request(
            "GET", f"/wcd/clubs/{club_id}/department-sales", headers=headers, params=params
        )

    def list_club_purchases(self, club_id, headers, params=None):
        return self._request(
            "GET", f"/wcd/clubs/{club_id}/purchases", headers=headers, params=params
        )

    # ---- items ----------------------------------------------------------
    def create_item(self, payload, headers):
        return self._request("POST", "/wcd/items", payload, headers)

    def list_items(self, headers, params=None):
        return self._request("GET", "/wcd/items", headers=headers, params=params)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/wcd/items/{item_id}", headers=headers)

    def activate_item(self, item_id, headers, payload=None):
        return self._request(
            "POST", f"/wcd/items/{item_id}/activate", payload or {}, headers
        )

    def request_item_deletion(self, item_id, headers, payload=None):
        return self._request(
            "POST", f"/wcd/items/{item_id}/request-deletion", payload or {}, headers
        )

    def discontinue_item(self, item_id, headers, payload=None):
        return self._request(
            "POST", f"/wcd/items/{item_id}/discontinue", payload or {}, headers
        )

    def list_item_markdown_decisions(self, item_id, headers, params=None):
        return self._request(
            "GET", f"/wcd/items/{item_id}/markdown-decisions", headers=headers, params=params
        )

    def create_markdown_decision(self, item_id, payload, headers):
        return self._request(
            "POST", f"/wcd/items/{item_id}/markdown-decisions", payload, headers
        )

    def list_item_complaints(self, item_id, headers, params=None):
        return self._request(
            "GET", f"/wcd/items/{item_id}/complaints", headers=headers, params=params
        )

    # ---- depots ---------------------------------------------------------
    def create_depot(self, payload, headers):
        return self._request("POST", "/wcd/depots", payload, headers)

    def list_depots(self, headers, params=None):
        return self._request("GET", "/wcd/depots", headers=headers, params=params)

    def get_depot(self, depot_id, headers):
        return self._request("GET", f"/wcd/depots/{depot_id}", headers=headers)

    def list_depot_appointments(self, depot_id, headers, params=None):
        return self._request(
            "GET", f"/wcd/depots/{depot_id}/appointments", headers=headers, params=params
        )

    def list_depot_cross_dock_runs(self, depot_id, headers, params=None):
        return self._request(
            "GET", f"/wcd/depots/{depot_id}/cross-dock-runs", headers=headers, params=params
        )

    # ---- appointments ---------------------------------------------------
    def create_appointment(self, payload, headers):
        return self._request("POST", "/wcd/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/wcd/appointments/{appointment_id}", headers=headers)

    def check_in_appointment(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/wcd/appointments/{appointment_id}/check-in", payload or {}, headers
        )

    def complete_appointment(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/wcd/appointments/{appointment_id}/complete", payload or {}, headers
        )

    def cancel_appointment(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/wcd/appointments/{appointment_id}/cancel", payload or {}, headers
        )

    def list_appointment_pallets(self, appointment_id, headers, params=None):
        return self._request(
            "GET", f"/wcd/appointments/{appointment_id}/pallets", headers=headers, params=params
        )

    # ---- pallets --------------------------------------------------------
    def create_pallet(self, payload, headers):
        return self._request("POST", "/wcd/pallets", payload, headers)

    def list_pallets(self, headers, params=None):
        return self._request("GET", "/wcd/pallets", headers=headers, params=params)

    def get_pallet(self, pallet_id, headers):
        return self._request("GET", f"/wcd/pallets/{pallet_id}", headers=headers)

    def reconcile_pallet(self, pallet_id, headers, payload=None):
        return self._request(
            "POST", f"/wcd/pallets/{pallet_id}/reconcile", payload or {}, headers
        )

    # ---- cross-dock runs and allocations --------------------------------
    def create_cross_dock_run(self, payload, headers):
        return self._request("POST", "/wcd/cross-dock-runs", payload, headers)

    def get_cross_dock_run(self, run_id, headers):
        return self._request("GET", f"/wcd/cross-dock-runs/{run_id}", headers=headers)

    def create_allocation(self, run_id, payload, headers):
        return self._request(
            "POST", f"/wcd/cross-dock-runs/{run_id}/allocations", payload, headers
        )

    def list_run_allocations(self, run_id, headers, params=None):
        return self._request(
            "GET", f"/wcd/cross-dock-runs/{run_id}/allocations", headers=headers, params=params
        )

    def commit_run(self, run_id, headers, payload=None):
        return self._request(
            "POST", f"/wcd/cross-dock-runs/{run_id}/commit", payload or {}, headers
        )

    def cancel_run(self, run_id, headers, payload=None):
        return self._request(
            "POST", f"/wcd/cross-dock-runs/{run_id}/cancel", payload or {}, headers
        )

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/wcd/allocations", headers=headers, params=params)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/wcd/allocations/{allocation_id}", headers=headers)

    def void_allocation(self, allocation_id, headers, payload=None):
        return self._request(
            "POST", f"/wcd/allocations/{allocation_id}/void", payload or {}, headers
        )

    # ---- members --------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", "/wcd/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/wcd/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/wcd/members/{member_id}", headers=headers)

    def suspend_member(self, member_id, headers, payload=None):
        return self._request(
            "POST", f"/wcd/members/{member_id}/suspend", payload or {}, headers
        )

    def list_member_purchases(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/wcd/members/{member_id}/purchases", headers=headers, params=params
        )

    def list_member_complaints(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/wcd/members/{member_id}/complaints", headers=headers, params=params
        )

    def list_member_department_sales(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/wcd/members/{member_id}/department-sales", headers=headers, params=params
        )

    # ---- purchases ------------------------------------------------------
    def create_purchase(self, payload, headers):
        return self._request("POST", "/wcd/purchases", payload, headers)

    def list_purchases(self, headers, params=None):
        return self._request("GET", "/wcd/purchases", headers=headers, params=params)

    def get_purchase(self, purchase_id, headers):
        return self._request("GET", f"/wcd/purchases/{purchase_id}", headers=headers)

    def refund_purchase(self, purchase_id, headers, payload=None):
        return self._request(
            "POST", f"/wcd/purchases/{purchase_id}/refund", payload or {}, headers
        )

    # ---- complaints -----------------------------------------------------
    def create_complaint(self, payload, headers):
        return self._request("POST", "/wcd/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/wcd/complaints/{complaint_id}", headers=headers)

    def resolve_complaint(self, complaint_id, headers, payload=None):
        return self._request(
            "POST", f"/wcd/complaints/{complaint_id}/resolve", payload or {}, headers
        )

    # ---- chargebacks ----------------------------------------------------
    def list_chargebacks(self, headers, params=None):
        return self._request("GET", "/wcd/chargebacks", headers=headers, params=params)

    def get_chargeback(self, chargeback_id, headers):
        return self._request("GET", f"/wcd/chargebacks/{chargeback_id}", headers=headers)

    def appeal_chargeback(self, chargeback_id, headers, payload=None):
        return self._request(
            "POST", f"/wcd/chargebacks/{chargeback_id}/appeal", payload or {}, headers
        )

    def resolve_chargeback(self, chargeback_id, payload, headers):
        return self._request(
            "POST", f"/wcd/chargebacks/{chargeback_id}/resolve", payload, headers
        )

    # ---- department sales -----------------------------------------------
    def create_department_sale(self, payload, headers):
        return self._request("POST", "/wcd/department-sales", payload, headers)

    def get_department_sale(self, sale_id, headers):
        return self._request("GET", f"/wcd/department-sales/{sale_id}", headers=headers)


api_client = ApiClient()
