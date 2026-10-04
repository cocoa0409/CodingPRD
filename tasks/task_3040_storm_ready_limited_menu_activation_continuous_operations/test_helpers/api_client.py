"""API client: one method per endpoint defined in the PRD's endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (test-driving) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/ops/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- StormEvent ---
    def create_storm_event(self, payload, headers):
        return self._request("POST", "/ops/storm-events", payload, headers)

    def list_storm_events(self, headers, params=None):
        return self._request("GET", "/ops/storm-events", headers=headers, params=params)

    def get_storm_event(self, storm_id, headers):
        return self._request("GET", f"/ops/storm-events/{storm_id}", headers=headers)

    def escalate_storm_event(self, storm_id, payload, headers):
        return self._request("POST", f"/ops/storm-events/{storm_id}/escalate", payload, headers)

    def deescalate_storm_event(self, storm_id, payload, headers):
        return self._request("POST", f"/ops/storm-events/{storm_id}/deescalate", payload, headers)

    def activate_storm_event(self, storm_id, payload, headers):
        return self._request("POST", f"/ops/storm-events/{storm_id}/activate", payload, headers)

    def close_storm_event(self, storm_id, payload, headers):
        return self._request("POST", f"/ops/storm-events/{storm_id}/close", payload, headers)

    def cancel_storm_event(self, storm_id, payload, headers):
        return self._request("POST", f"/ops/storm-events/{storm_id}/cancel", payload, headers)

    def list_storm_units(self, storm_id, headers, params=None):
        return self._request("GET", f"/ops/storm-events/{storm_id}/units", headers=headers, params=params)

    # --- Unit ---
    def create_unit(self, storm_id, payload, headers):
        return self._request("POST", f"/ops/storm-events/{storm_id}/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/ops/units/{unit_id}", headers=headers)

    def top_up_unit(self, unit_id, payload, headers):
        return self._request("PATCH", f"/ops/units/{unit_id}", payload, headers)

    # Alias matching the endpoint's PATCH verb for readability in tests.
    def patch_unit(self, unit_id, payload, headers):
        return self._request("PATCH", f"/ops/units/{unit_id}", payload, headers)

    # --- ConditionReport ---
    def list_condition_reports(self, unit_id, headers, params=None):
        return self._request("GET", f"/ops/units/{unit_id}/condition-reports", headers=headers, params=params)

    def create_condition_report(self, unit_id, payload, headers):
        return self._request("POST", f"/ops/units/{unit_id}/condition-reports", payload, headers)

    # --- MenuActivation ---
    def list_menu_activations(self, unit_id, headers, params=None):
        return self._request("GET", f"/ops/units/{unit_id}/menu-activations", headers=headers, params=params)

    def create_menu_activation(self, unit_id, payload, headers):
        return self._request("POST", f"/ops/units/{unit_id}/menu-activations", payload, headers)

    def deactivate_menu_activation(self, unit_id, payload, headers):
        return self._request("POST", f"/ops/units/{unit_id}/menu-activations/deactivate", payload, headers)

    # --- ChecklistRun / ChecklistItem ---
    def list_checklists(self, unit_id, headers, params=None):
        return self._request("GET", f"/ops/units/{unit_id}/checklists", headers=headers, params=params)

    def create_checklist(self, unit_id, payload, headers):
        return self._request("POST", f"/ops/units/{unit_id}/checklists", payload, headers)

    def get_checklist(self, unit_id, run_id, headers):
        return self._request("GET", f"/ops/units/{unit_id}/checklists/{run_id}", headers=headers)

    def create_checklist_item(self, unit_id, run_id, payload, headers):
        return self._request("POST", f"/ops/units/{unit_id}/checklists/{run_id}/items", payload, headers)

    def list_checklist_items(self, unit_id, run_id, headers):
        return self._request("GET", f"/ops/units/{unit_id}/checklists/{run_id}/items", headers=headers)

    def submit_checklist(self, unit_id, run_id, payload, headers):
        return self._request("POST", f"/ops/units/{unit_id}/checklists/{run_id}/submit", payload, headers)

    def approve_checklist(self, unit_id, run_id, payload, headers):
        return self._request("POST", f"/ops/units/{unit_id}/checklists/{run_id}/approve", payload, headers)

    def reject_checklist(self, unit_id, run_id, payload, headers):
        return self._request("POST", f"/ops/units/{unit_id}/checklists/{run_id}/reject", payload, headers)

    def rework_checklist(self, unit_id, run_id, payload, headers):
        return self._request("POST", f"/ops/units/{unit_id}/checklists/{run_id}/rework", payload, headers)

    # --- CashDrop ---
    def list_cash_drops(self, unit_id, headers, params=None):
        return self._request("GET", f"/ops/units/{unit_id}/cash-drops", headers=headers, params=params)

    def create_cash_drop(self, unit_id, payload, headers):
        return self._request("POST", f"/ops/units/{unit_id}/cash-drops", payload, headers)

    # --- ReliefPledge ---
    def list_relief_pledges(self, unit_id, headers, params=None):
        return self._request("GET", f"/ops/units/{unit_id}/relief-pledges", headers=headers, params=params)

    def create_relief_pledge(self, unit_id, payload, headers):
        return self._request("POST", f"/ops/units/{unit_id}/relief-pledges", payload, headers)

    def confirm_relief_pledge(self, unit_id, pledge_id, payload, headers):
        return self._request("POST", f"/ops/units/{unit_id}/relief-pledges/{pledge_id}/confirm", payload, headers)

    def cancel_relief_pledge(self, unit_id, pledge_id, payload, headers):
        return self._request("POST", f"/ops/units/{unit_id}/relief-pledges/{pledge_id}/cancel", payload, headers)

    def list_org_relief_pledges(self, org_id, headers, params=None):
        return self._request("GET", f"/ops/relief-orgs/{org_id}/relief-pledges", headers=headers, params=params)

    # --- CrewMember / CrewAssignment ---
    def create_crew_member(self, payload, headers):
        return self._request("POST", "/ops/crew-members", payload, headers)

    def list_crew_members(self, headers, params=None):
        return self._request("GET", "/ops/crew-members", headers=headers, params=params)

    def get_crew_member(self, member_id, headers):
        return self._request("GET", f"/ops/crew-members/{member_id}", headers=headers)

    def patch_crew_member(self, member_id, payload, headers):
        return self._request("PATCH", f"/ops/crew-members/{member_id}", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/ops/assignments", headers=headers, params=params)

    def create_assignment(self, payload, headers):
        return self._request("POST", "/ops/assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/ops/assignments/{assignment_id}", headers=headers)

    def start_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/ops/assignments/{assignment_id}/start", payload, headers)

    def complete_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/ops/assignments/{assignment_id}/complete", payload, headers)

    def cancel_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/ops/assignments/{assignment_id}/cancel", payload, headers)

    # --- Asset / AssetAllocation ---
    def create_asset(self, payload, headers):
        return self._request("POST", "/ops/assets", payload, headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", "/ops/assets", headers=headers, params=params)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/ops/assets/{asset_id}", headers=headers)

    def retire_asset(self, asset_id, payload, headers):
        return self._request("POST", f"/ops/assets/{asset_id}/retire", payload, headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/ops/allocations", headers=headers, params=params)

    def create_allocation(self, payload, headers):
        return self._request("POST", "/ops/allocations", payload, headers)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/ops/allocations/{allocation_id}", headers=headers)

    def dispatch_allocation(self, allocation_id, payload, headers):
        return self._request("POST", f"/ops/allocations/{allocation_id}/dispatch", payload, headers)

    def return_allocation(self, allocation_id, payload, headers):
        return self._request("POST", f"/ops/allocations/{allocation_id}/return", payload, headers)

    def cancel_allocation(self, allocation_id, payload, headers):
        return self._request("POST", f"/ops/allocations/{allocation_id}/cancel", payload, headers)

    # --- LodgingBooking ---
    def list_lodging_bookings(self, headers, params=None):
        return self._request("GET", "/ops/lodging-bookings", headers=headers, params=params)

    def create_lodging_booking(self, payload, headers):
        return self._request("POST", "/ops/lodging-bookings", payload, headers)

    def get_lodging_booking(self, booking_id, headers):
        return self._request("GET", f"/ops/lodging-bookings/{booking_id}", headers=headers)

    def cancel_lodging_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/ops/lodging-bookings/{booking_id}/cancel", payload, headers)

    # --- ReliefOrg ---
    def create_relief_org(self, payload, headers):
        return self._request("POST", "/ops/relief-orgs", payload, headers)

    def list_relief_orgs(self, headers, params=None):
        return self._request("GET", "/ops/relief-orgs", headers=headers, params=params)

    def get_relief_org(self, org_id, headers):
        return self._request("GET", f"/ops/relief-orgs/{org_id}", headers=headers)

    def patch_relief_org(self, org_id, payload, headers):
        return self._request("PATCH", f"/ops/relief-orgs/{org_id}", payload, headers)

    # --- reverse-reachability reads ---
    def list_unit_crew_members(self, unit_id, headers):
        return self._request("GET", f"/ops/units/{unit_id}/crew-members", headers=headers)

    def list_unit_assets(self, unit_id, headers):
        return self._request("GET", f"/ops/units/{unit_id}/assets", headers=headers)

    def list_unit_assignments(self, unit_id, headers):
        return self._request("GET", f"/ops/units/{unit_id}/assignments", headers=headers)

    def list_member_assignments(self, member_id, headers):
        return self._request("GET", f"/ops/crew-members/{member_id}/assignments", headers=headers)

    def list_assignment_lodging_bookings(self, assignment_id, headers):
        return self._request("GET", f"/ops/assignments/{assignment_id}/lodging-bookings", headers=headers)

    def list_asset_allocations(self, asset_id, headers):
        return self._request("GET", f"/ops/assets/{asset_id}/allocations", headers=headers)

    def list_unit_allocations(self, unit_id, headers):
        return self._request("GET", f"/ops/units/{unit_id}/allocations", headers=headers)

    def list_unit_lodging_bookings(self, unit_id, headers):
        return self._request("GET", f"/ops/units/{unit_id}/lodging-bookings", headers=headers)

    def get_checklist_flat(self, run_id, headers):
        return self._request("GET", f"/ops/checklists/{run_id}", headers=headers)

    def list_checklist_items_flat(self, run_id, headers):
        return self._request("GET", f"/ops/checklists/{run_id}/items", headers=headers)

    # --- command-center reporting cadence ---
    def run_report(self, payload, headers):
        return self._request("POST", "/ops/run-report", payload, headers)


api_client = ApiClient()
