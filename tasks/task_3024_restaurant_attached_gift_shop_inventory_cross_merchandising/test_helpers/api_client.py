"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/retail-ops"


class ApiClient(GenericApiClient):
    # --- Clock ------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Brand ------------------------------------------------------------
    def create_brand(self, payload, headers):
        return self._request("POST", f"{PREFIX}/brands", payload, headers)

    def list_brands(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/brands", headers=headers, params=params)

    def get_brand(self, brand_id, headers):
        return self._request("GET", f"{PREFIX}/brands/{brand_id}", headers=headers)

    def update_brand(self, brand_id, payload, headers):
        return self._request("PUT", f"{PREFIX}/brands/{brand_id}", payload, headers)

    # --- Location ---------------------------------------------------------
    def create_location(self, payload, headers):
        return self._request("POST", f"{PREFIX}/locations", payload, headers)

    def list_locations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/locations", headers=headers, params=params)

    def get_location(self, location_id, headers):
        return self._request("GET", f"{PREFIX}/locations/{location_id}", headers=headers)

    def create_capacity_reading(self, location_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/locations/{location_id}/capacity-readings", payload, headers
        )

    def list_location_capacity_readings(self, location_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/locations/{location_id}/capacity-readings",
            headers=headers,
            params=params,
        )

    def list_store_day_capacity_readings(self, store_day_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/store-days/{store_day_id}/capacity-readings",
            headers=headers,
            params=params,
        )

    def list_transfer_capacity_readings(self, transfer_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/transfers/{transfer_id}/capacity-readings",
            headers=headers,
            params=params,
        )

    # --- StoreDay ---------------------------------------------------------
    def create_store_day(self, payload, headers):
        return self._request("POST", f"{PREFIX}/store-days", payload, headers)

    def list_store_days(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/store-days", headers=headers, params=params)

    def get_store_day(self, store_day_id, headers):
        return self._request("GET", f"{PREFIX}/store-days/{store_day_id}", headers=headers)

    def post_guest_counts(self, store_day_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/store-days/{store_day_id}/guest-counts", payload, headers
        )

    def close_store_day(self, store_day_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/store-days/{store_day_id}/close", payload, headers
        )

    # --- Item -------------------------------------------------------------
    def create_item(self, payload, headers):
        return self._request("POST", f"{PREFIX}/items", payload, headers)

    def list_items(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/items", headers=headers, params=params)

    def get_item(self, item_id, headers):
        return self._request("GET", f"{PREFIX}/items/{item_id}", headers=headers)

    def check_item_order_deadline(self, item_id, headers):
        return self._request(
            "POST", f"{PREFIX}/items/{item_id}/order-deadline-check", {}, headers
        )

    def get_item_import_plan(self, item_id, headers):
        return self._request("GET", f"{PREFIX}/items/{item_id}/import-plan", headers=headers)

    # --- GuestCheck -------------------------------------------------------
    def create_guest_check(self, payload, headers):
        return self._request("POST", f"{PREFIX}/guest-checks", payload, headers)

    def list_guest_checks(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/guest-checks", headers=headers, params=params)

    def get_guest_check(self, check_id, headers):
        return self._request("GET", f"{PREFIX}/guest-checks/{check_id}", headers=headers)

    def update_guest_check(self, check_id, payload, headers):
        return self._request("PUT", f"{PREFIX}/guest-checks/{check_id}", payload, headers)

    def finalize_guest_check(self, check_id, headers):
        return self._request(
            "POST", f"{PREFIX}/guest-checks/{check_id}/finalize", {}, headers
        )

    def post_tip(self, check_id, payload, headers):
        return self._request("POST", f"{PREFIX}/guest-checks/{check_id}/tips", payload, headers)

    def settle_guest_check(self, check_id, payload, headers):
        return self._request("POST", f"{PREFIX}/guest-checks/{check_id}/settle", payload, headers)

    def void_guest_check(self, check_id, headers):
        return self._request("POST", f"{PREFIX}/guest-checks/{check_id}/void", {}, headers)

    # --- Receipt ----------------------------------------------------------
    def create_receipt(self, payload, headers):
        return self._request("POST", f"{PREFIX}/receipts", payload, headers)

    def list_receipts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/receipts", headers=headers, params=params)

    def get_receipt(self, receipt_id, headers):
        return self._request("GET", f"{PREFIX}/receipts/{receipt_id}", headers=headers)

    def update_receipt(self, receipt_id, payload, headers):
        return self._request("PUT", f"{PREFIX}/receipts/{receipt_id}", payload, headers)

    def attach_receipt_to_check(self, receipt_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/receipts/{receipt_id}/attach-check", payload, headers
        )

    def reconcile_receipt(self, receipt_id, headers):
        return self._request("POST", f"{PREFIX}/receipts/{receipt_id}/reconcile", {}, headers)

    def dispute_receipt(self, receipt_id, headers):
        return self._request("POST", f"{PREFIX}/receipts/{receipt_id}/dispute", {}, headers)

    def resolve_receipt(self, receipt_id, headers):
        return self._request("POST", f"{PREFIX}/receipts/{receipt_id}/resolve", {}, headers)

    def settle_receipt(self, receipt_id, payload, headers=None):
        # PRD 3.4: settlement is a RetailLead action, so the default caller is the
        # retail lead when a test omits the headers argument.
        if headers is None:
            from .test_users import TEST_USERS
            headers = TEST_USERS["retail_lead_headers"]
        return self._request("POST", f"{PREFIX}/receipts/{receipt_id}/settle", payload, headers)

    def get_revenue_attribution(self, headers, params):
        return self._request(
            "GET", f"{PREFIX}/revenue-attribution", headers=headers, params=params
        )

    # --- ClearanceSchedule ------------------------------------------------
    def create_clearance_schedule(self, payload, headers):
        return self._request("POST", f"{PREFIX}/clearance-schedules", payload, headers)

    def list_clearance_schedules(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/clearance-schedules", headers=headers, params=params
        )

    def get_clearance_schedule(self, schedule_id, headers):
        return self._request(
            "GET", f"{PREFIX}/clearance-schedules/{schedule_id}", headers=headers
        )

    def activate_clearance_schedule(self, schedule_id, headers):
        return self._request(
            "POST", f"{PREFIX}/clearance-schedules/{schedule_id}/activate", {}, headers
        )

    def extend_clearance_schedule(self, schedule_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/clearance-schedules/{schedule_id}/extend", payload, headers
        )

    def reactivate_clearance_schedule(self, schedule_id, headers):
        return self._request(
            "POST", f"{PREFIX}/clearance-schedules/{schedule_id}/reactivate", {}, headers
        )

    def liquidate_clearance_schedule(self, schedule_id, headers):
        return self._request(
            "POST", f"{PREFIX}/clearance-schedules/{schedule_id}/liquidate", {}, headers
        )

    def cancel_clearance_schedule(self, schedule_id, headers):
        return self._request(
            "POST", f"{PREFIX}/clearance-schedules/{schedule_id}/cancel", {}, headers
        )

    # --- StaffShift -------------------------------------------------------
    def create_staff_shift(self, payload, headers):
        return self._request("POST", f"{PREFIX}/staff-shifts", payload, headers)

    def list_staff_shifts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/staff-shifts", headers=headers, params=params)

    def get_staff_shift(self, shift_id, headers):
        return self._request("GET", f"{PREFIX}/staff-shifts/{shift_id}", headers=headers)

    def start_staff_shift(self, shift_id, headers):
        return self._request("POST", f"{PREFIX}/staff-shifts/{shift_id}/start", {}, headers)

    def complete_staff_shift(self, shift_id, headers):
        return self._request("POST", f"{PREFIX}/staff-shifts/{shift_id}/complete", {}, headers)

    def revert_staff_shift(self, shift_id, headers):
        return self._request(
            "POST", f"{PREFIX}/staff-shifts/{shift_id}/revert-to-scheduled", {}, headers
        )

    def cancel_staff_shift(self, shift_id, headers):
        return self._request("POST", f"{PREFIX}/staff-shifts/{shift_id}/cancel", {}, headers)

    # --- Transfer ---------------------------------------------------------
    def create_transfer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/transfers", payload, headers)

    def list_transfers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/transfers", headers=headers, params=params)

    def get_transfer(self, transfer_id, headers):
        return self._request("GET", f"{PREFIX}/transfers/{transfer_id}", headers=headers)

    def dispatch_transfer(self, transfer_id, headers):
        return self._request("POST", f"{PREFIX}/transfers/{transfer_id}/dispatch", {}, headers)

    def advance_transfer(self, transfer_id, payload, headers):
        return self._request("POST", f"{PREFIX}/transfers/{transfer_id}/advance", payload, headers)

    def receive_transfer(self, transfer_id, payload, headers):
        return self._request("POST", f"{PREFIX}/transfers/{transfer_id}/receive", payload, headers)

    def reconcile_transfer(self, transfer_id, headers):
        return self._request("POST", f"{PREFIX}/transfers/{transfer_id}/reconcile", {}, headers)

    def void_receiving(self, transfer_id, headers):
        return self._request(
            "POST", f"{PREFIX}/transfers/{transfer_id}/void-receiving", {}, headers
        )

    def redispatch_transfer(self, transfer_id, headers):
        return self._request("POST", f"{PREFIX}/transfers/{transfer_id}/redispatch", {}, headers)

    def get_transfer_discrepancy(self, transfer_id, headers):
        return self._request(
            "GET", f"{PREFIX}/transfers/{transfer_id}/discrepancy", headers=headers
        )

    # --- PlanogramVersion / PlanogramSlot ---------------------------------
    def create_planogram_version(self, payload, headers):
        return self._request("POST", f"{PREFIX}/planogram-versions", payload, headers)

    def list_planogram_versions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/planogram-versions", headers=headers, params=params
        )

    def get_planogram_version(self, version_id, headers):
        return self._request(
            "GET", f"{PREFIX}/planogram-versions/{version_id}", headers=headers
        )

    def update_planogram_version(self, version_id, payload, headers):
        return self._request(
            "PUT", f"{PREFIX}/planogram-versions/{version_id}", payload, headers
        )

    def delete_planogram_version(self, version_id, headers):
        return self._request(
            "DELETE", f"{PREFIX}/planogram-versions/{version_id}", headers=headers
        )

    def publish_planogram_version(self, version_id, headers):
        return self._request(
            "POST", f"{PREFIX}/planogram-versions/{version_id}/publish", {}, headers
        )

    def retire_planogram_version(self, version_id, headers):
        return self._request(
            "POST", f"{PREFIX}/planogram-versions/{version_id}/retire", {}, headers
        )

    def get_planogram_region_fit(self, version_id, headers):
        return self._request(
            "GET", f"{PREFIX}/planogram-versions/{version_id}/region-fit", headers=headers
        )

    def create_planogram_slot(self, payload, headers):
        return self._request("POST", f"{PREFIX}/planogram-slots", payload, headers)

    def list_planogram_slots(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/planogram-slots", headers=headers, params=params)

    def get_planogram_slot(self, slot_id, headers):
        return self._request("GET", f"{PREFIX}/planogram-slots/{slot_id}", headers=headers)

    def update_planogram_slot(self, slot_id, payload, headers):
        return self._request("PUT", f"{PREFIX}/planogram-slots/{slot_id}", payload, headers)

    def apply_planogram_slot(self, slot_id, headers):
        return self._request("POST", f"{PREFIX}/planogram-slots/{slot_id}/apply", {}, headers)

    def verify_planogram_slot(self, slot_id, headers):
        return self._request("POST", f"{PREFIX}/planogram-slots/{slot_id}/verify", {}, headers)


api_client = ApiClient()