"""API client: one method per endpoint described in the PRD.

Every route is mounted under the ``/vaccine-distribution`` root.
"""
from prd_bench_local_runner.testing import GenericApiClient

ROOT = "/vaccine-distribution"


class ApiClient(GenericApiClient):
    # ── test-driving capabilities ─────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", f"{ROOT}/_clock/set_current_utc", payload, headers)

    def run_cycle(self, headers):
        return self._request("POST", f"{ROOT}/_ops/run-cycle", {}, headers)

    # ── ProductConfiguration ──────────────────────────────────────────────
    def create_product_configuration(self, payload, headers):
        return self._request("POST", f"{ROOT}/product-configurations", payload, headers)

    def list_product_configurations(self, headers, params=None):
        return self._request("GET", f"{ROOT}/product-configurations", params, headers=headers)

    def get_product_configuration(self, pc_id, headers):
        return self._request("GET", f"{ROOT}/product-configurations/{pc_id}", headers=headers)

    # ── JurisdictionProgram ───────────────────────────────────────────────
    def create_jurisdiction_program(self, payload, headers):
        return self._request("POST", f"{ROOT}/jurisdiction-programs", payload, headers)

    def list_jurisdiction_programs(self, headers, params=None):
        return self._request("GET", f"{ROOT}/jurisdiction-programs", params, headers=headers)

    def get_jurisdiction_program(self, prog_id, headers):
        return self._request("GET", f"{ROOT}/jurisdiction-programs/{prog_id}", headers=headers)

    def assess_program_standing(self, prog_id, payload, headers):
        return self._request(
            "POST", f"{ROOT}/jurisdiction-programs/{prog_id}/standing/assess", payload, headers
        )

    def list_program_standings(self, prog_id, headers, params=None):
        return self._request(
            "GET", f"{ROOT}/jurisdiction-programs/{prog_id}/standings", params, headers=headers
        )

    def list_program_reporting_periods(self, prog_id, headers, params=None):
        return self._request(
            "GET", f"{ROOT}/jurisdiction-programs/{prog_id}/reporting-periods", params, headers=headers
        )

    def list_program_sites(self, prog_id, headers, params=None):
        return self._request(
            "GET", f"{ROOT}/jurisdiction-programs/{prog_id}/sites", params, headers=headers
        )

    # ── AllocationBatch / Carton registration ─────────────────────────────
    def create_allocation_batch(self, payload, headers):
        return self._request("POST", f"{ROOT}/allocation-batches", payload, headers)

    def list_allocation_batches(self, headers, params=None):
        return self._request("GET", f"{ROOT}/allocation-batches", params, headers=headers)

    def get_allocation_batch(self, batch_id, headers):
        return self._request("GET", f"{ROOT}/allocation-batches/{batch_id}", headers=headers)

    def register_carton(self, batch_id, payload, headers):
        return self._request("POST", f"{ROOT}/allocation-batches/{batch_id}/cartons", payload, headers)

    def list_batch_cartons(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"{ROOT}/allocation-batches/{batch_id}/cartons", params, headers=headers
        )

    def release_batch(self, batch_id, headers, payload=None):
        return self._request(
            "POST", f"{ROOT}/allocation-batches/{batch_id}/release", payload or {}, headers
        )

    def recall_batch(self, batch_id, headers, payload=None):
        return self._request(
            "POST", f"{ROOT}/allocation-batches/{batch_id}/recall", payload or {}, headers
        )

    # ── AllocationWindow / AllocationEntitlement ──────────────────────────
    def create_allocation_window(self, payload, headers):
        return self._request("POST", f"{ROOT}/allocation-windows", payload, headers)

    def list_allocation_windows(self, headers, params=None):
        return self._request("GET", f"{ROOT}/allocation-windows", params, headers=headers)

    def get_allocation_window(self, win_id, headers):
        return self._request("GET", f"{ROOT}/allocation-windows/{win_id}", headers=headers)

    def open_allocation_window(self, win_id, payload, headers):
        return self._request("POST", f"{ROOT}/allocation-windows/{win_id}/open", payload, headers)

    def close_allocation_window(self, win_id, headers, payload=None):
        return self._request(
            "POST", f"{ROOT}/allocation-windows/{win_id}/close", payload or {}, headers
        )

    def list_window_entitlements(self, win_id, headers, params=None):
        return self._request(
            "GET", f"{ROOT}/allocation-windows/{win_id}/entitlements", params, headers=headers
        )

    def list_allocation_entitlements(self, headers, params=None):
        return self._request("GET", f"{ROOT}/allocation-entitlements", params, headers=headers)

    def get_allocation_entitlement(self, ent_id, headers):
        return self._request("GET", f"{ROOT}/allocation-entitlements/{ent_id}", headers=headers)

    # ── StorageSite ───────────────────────────────────────────────────────
    def create_storage_site(self, payload, headers):
        return self._request("POST", f"{ROOT}/storage-sites", payload, headers)

    def list_storage_sites(self, headers, params=None):
        return self._request("GET", f"{ROOT}/storage-sites", params, headers=headers)

    def get_storage_site(self, site_id, headers):
        return self._request("GET", f"{ROOT}/storage-sites/{site_id}", headers=headers)

    def get_site_usable_doses(self, site_id, headers):
        return self._request("GET", f"{ROOT}/storage-sites/{site_id}/usable-doses", headers=headers)

    def list_site_transfers(self, site_id, headers, params=None):
        return self._request("GET", f"{ROOT}/storage-sites/{site_id}/transfers", params, headers=headers)

    def list_site_equipment_verifications(self, site_id, headers, params=None):
        return self._request(
            "GET", f"{ROOT}/storage-sites/{site_id}/equipment-verifications", params, headers=headers
        )

    def list_site_excursions(self, site_id, headers, params=None):
        return self._request("GET", f"{ROOT}/storage-sites/{site_id}/excursions", params, headers=headers)

    def list_site_storage_reservations(self, site_id, headers, params=None):
        return self._request(
            "GET", f"{ROOT}/storage-sites/{site_id}/storage-reservations", params, headers=headers
        )

    # ── SiteEquipmentVerification ─────────────────────────────────────────
    def create_site_equipment_verification(self, payload, headers):
        return self._request("POST", f"{ROOT}/site-equipment-verifications", payload, headers)

    def list_site_equipment_verification(self, headers, params=None):
        return self._request("GET", f"{ROOT}/site-equipment-verifications", params, headers=headers)

    def get_site_equipment_verification(self, ver_id, headers):
        return self._request("GET", f"{ROOT}/site-equipment-verifications/{ver_id}", headers=headers)

    # ── SiteOrder ─────────────────────────────────────────────────────────
    def create_site_order(self, payload, headers):
        return self._request("POST", f"{ROOT}/site-orders", payload, headers)

    def list_site_orders(self, headers, params=None):
        return self._request("GET", f"{ROOT}/site-orders", params, headers=headers)

    def get_site_order(self, order_id, headers):
        return self._request("GET", f"{ROOT}/site-orders/{order_id}", headers=headers)

    def submit_site_order(self, order_id, headers, payload=None):
        return self._request("POST", f"{ROOT}/site-orders/{order_id}/submit", payload or {}, headers)

    def accept_site_order(self, order_id, payload, headers):
        return self._request("POST", f"{ROOT}/site-orders/{order_id}/accept", payload, headers)

    def reject_site_order(self, order_id, payload, headers):
        return self._request("POST", f"{ROOT}/site-orders/{order_id}/reject", payload, headers)

    def reverse_order_fulfillment(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"{ROOT}/site-orders/{order_id}/fulfillment/reverse", payload or {}, headers
        )

    def list_order_rejections(self, order_id, headers, params=None):
        return self._request("GET", f"{ROOT}/site-orders/{order_id}/rejections", params, headers=headers)

    def list_order_dispatches(self, order_id, headers, params=None):
        return self._request("GET", f"{ROOT}/site-orders/{order_id}/dispatches", params, headers=headers)

    def list_all_order_rejections(self, headers, params=None):
        return self._request("GET", f"{ROOT}/order-rejections", params, headers=headers)

    # ── DispatchOrder ─────────────────────────────────────────────────────
    def create_dispatch(self, payload, headers):
        return self._request("POST", f"{ROOT}/dispatches", payload, headers)

    def list_dispatches(self, headers, params=None):
        return self._request("GET", f"{ROOT}/dispatches", params, headers=headers)

    def get_dispatch(self, disp_id, headers):
        return self._request("GET", f"{ROOT}/dispatches/{disp_id}", headers=headers)

    def pack_dispatch(self, disp_id, headers, payload=None):
        return self._request("POST", f"{ROOT}/dispatches/{disp_id}/pack", payload or {}, headers)

    def send_dispatch(self, disp_id, headers, payload=None):
        return self._request("POST", f"{ROOT}/dispatches/{disp_id}/dispatch", payload or {}, headers)

    def deliver_dispatch(self, disp_id, payload, headers):
        return self._request("POST", f"{ROOT}/dispatches/{disp_id}/deliver", payload, headers)

    def reject_at_dock(self, disp_id, payload, headers):
        return self._request("POST", f"{ROOT}/dispatches/{disp_id}/reject-at-dock", payload, headers)

    def list_dispatch_shippers(self, disp_id, headers, params=None):
        return self._request("GET", f"{ROOT}/dispatches/{disp_id}/shippers", params, headers=headers)

    def list_dispatch_cartons(self, disp_id, headers, params=None):
        return self._request("GET", f"{ROOT}/dispatches/{disp_id}/cartons", params, headers=headers)

    # ── ColdChainShipper ──────────────────────────────────────────────────
    def create_shipper(self, payload, headers):
        return self._request("POST", f"{ROOT}/shippers", payload, headers)

    def list_shippers(self, headers, params=None):
        return self._request("GET", f"{ROOT}/shippers", params, headers=headers)

    def get_shipper(self, ship_id, headers):
        return self._request("GET", f"{ROOT}/shippers/{ship_id}", headers=headers)

    def attach_carton_to_shipper(self, ship_id, payload, headers):
        return self._request("POST", f"{ROOT}/shippers/{ship_id}/attach-carton", payload, headers)

    def list_shipper_cartons(self, ship_id, headers, params=None):
        return self._request("GET", f"{ROOT}/shippers/{ship_id}/cartons", params, headers=headers)

    def seal_shipper(self, ship_id, payload, headers):
        return self._request("POST", f"{ROOT}/shippers/{ship_id}/seal", payload, headers)

    def hold_shipper(self, ship_id, payload, headers):
        return self._request("POST", f"{ROOT}/shippers/{ship_id}/hold", payload, headers)

    def release_shipper(self, ship_id, headers, payload=None):
        return self._request("POST", f"{ROOT}/shippers/{ship_id}/release", payload or {}, headers)

    # ── TemperatureLoggerReading ──────────────────────────────────────────
    def create_logger_reading(self, payload, headers):
        return self._request("POST", f"{ROOT}/logger-readings", payload, headers)

    def list_logger_readings(self, headers, params=None):
        return self._request("GET", f"{ROOT}/logger-readings", params, headers=headers)

    def get_logger_reading(self, reading_id, headers):
        return self._request("GET", f"{ROOT}/logger-readings/{reading_id}", headers=headers)

    # ── Carton ────────────────────────────────────────────────────────────
    def list_cartons(self, headers, params=None):
        return self._request("GET", f"{ROOT}/cartons", params, headers=headers)

    def get_carton(self, carton_id, headers):
        return self._request("GET", f"{ROOT}/cartons/{carton_id}", headers=headers)

    def thaw_carton(self, carton_id, headers, payload=None):
        return self._request("POST", f"{ROOT}/cartons/{carton_id}/thaw", payload or {}, headers)

    def puncture_carton(self, carton_id, headers, payload=None):
        return self._request("POST", f"{ROOT}/cartons/{carton_id}/puncture", payload or {}, headers)

    def refreeze_carton(self, carton_id, headers, payload=None):
        return self._request("POST", f"{ROOT}/cartons/{carton_id}/refreeze", payload or {}, headers)

    def advance_carton_logical_state(self, carton_id, payload, headers):
        return self._request("POST", f"{ROOT}/cartons/{carton_id}/advance-logical-state", payload, headers)

    def destroy_carton(self, carton_id, payload, headers):
        return self._request("POST", f"{ROOT}/cartons/{carton_id}/destroy", payload, headers)

    def list_carton_ledger_entries(self, carton_id, headers, params=None):
        return self._request("GET", f"{ROOT}/cartons/{carton_id}/ledger-entries", params, headers=headers)

    def list_carton_excursions(self, carton_id, headers, params=None):
        return self._request("GET", f"{ROOT}/cartons/{carton_id}/excursions", params, headers=headers)

    def list_carton_reservations(self, carton_id, headers, params=None):
        return self._request("GET", f"{ROOT}/cartons/{carton_id}/reservations", params, headers=headers)

    # ── DoseLedgerEntry ───────────────────────────────────────────────────
    def create_dose_ledger_entry(self, payload, headers):
        return self._request("POST", f"{ROOT}/dose-ledger-entries", payload, headers)

    def list_dose_ledger_entries(self, headers, params=None):
        return self._request("GET", f"{ROOT}/dose-ledger-entries", params, headers=headers)

    def get_dose_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"{ROOT}/dose-ledger-entries/{entry_id}", headers=headers)

    def reverse_dose_ledger_entry(self, entry_id, payload, headers):
        return self._request("POST", f"{ROOT}/dose-ledger-entries/{entry_id}/reverse", payload, headers)

    # ── SiteTransfer ──────────────────────────────────────────────────────
    def create_site_transfer(self, payload, headers):
        return self._request("POST", f"{ROOT}/site-transfers", payload, headers)

    def list_site_transfers_all(self, headers, params=None):
        return self._request("GET", f"{ROOT}/site-transfers", params, headers=headers)

    def get_site_transfer(self, tr_id, headers):
        return self._request("GET", f"{ROOT}/site-transfers/{tr_id}", headers=headers)

    def approve_site_transfer(self, tr_id, headers, payload=None):
        return self._request("POST", f"{ROOT}/site-transfers/{tr_id}/approve", payload or {}, headers)

    def send_site_transfer(self, tr_id, headers, payload=None):
        return self._request("POST", f"{ROOT}/site-transfers/{tr_id}/dispatch", payload or {}, headers)

    def receive_site_transfer(self, tr_id, payload, headers):
        return self._request("POST", f"{ROOT}/site-transfers/{tr_id}/receive", payload, headers)

    def reject_site_transfer(self, tr_id, payload, headers):
        return self._request("POST", f"{ROOT}/site-transfers/{tr_id}/reject", payload, headers)

    def cancel_site_transfer(self, tr_id, headers, payload=None):
        return self._request("POST", f"{ROOT}/site-transfers/{tr_id}/cancel", payload or {}, headers)

    # ── TemperatureExcursion ──────────────────────────────────────────────
    def create_temperature_excursion(self, payload, headers):
        return self._request("POST", f"{ROOT}/temperature-excursions", payload, headers)

    def list_temperature_excursions(self, headers, params=None):
        return self._request("GET", f"{ROOT}/temperature-excursions", params, headers=headers)

    def get_temperature_excursion(self, exc_id, headers):
        return self._request("GET", f"{ROOT}/temperature-excursions/{exc_id}", headers=headers)

    def review_temperature_excursion(self, exc_id, headers, payload=None):
        return self._request(
            "POST", f"{ROOT}/temperature-excursions/{exc_id}/review", payload or {}, headers
        )

    def adjudicate_temperature_excursion(self, exc_id, payload, headers):
        return self._request("POST", f"{ROOT}/temperature-excursions/{exc_id}/adjudicate", payload, headers)

    def get_excursion_readiness(self, exc_id, headers):
        return self._request("GET", f"{ROOT}/temperature-excursions/{exc_id}/readiness", headers=headers)

    def get_excursion_audit(self, exc_id, headers, params=None):
        return self._request("GET", f"{ROOT}/temperature-excursions/{exc_id}/audit", params, headers=headers)

    def create_doses_affected_slice(self, exc_id, payload, headers):
        return self._request(
            "POST", f"{ROOT}/temperature-excursions/{exc_id}/doses-affected-slices", payload, headers
        )

    def list_doses_affected_slices(self, exc_id, headers, params=None):
        return self._request(
            "GET", f"{ROOT}/temperature-excursions/{exc_id}/doses-affected-slices", params, headers=headers
        )

    def list_excursion_appeals(self, exc_id, headers, params=None):
        return self._request("GET", f"{ROOT}/temperature-excursions/{exc_id}/appeals", params, headers=headers)

    def file_appeal(self, exc_id, payload, headers):
        return self._request("POST", f"{ROOT}/temperature-excursions/{exc_id}/appeals", payload, headers)

    def accept_appeal(self, exc_id, appeal_id, headers, payload=None):
        return self._request(
            "POST", f"{ROOT}/temperature-excursions/{exc_id}/appeals/{appeal_id}/accept",
            payload or {}, headers,
        )

    def deny_appeal(self, exc_id, appeal_id, headers, payload=None):
        return self._request(
            "POST", f"{ROOT}/temperature-excursions/{exc_id}/appeals/{appeal_id}/deny",
            payload or {}, headers,
        )

    # ── DosesAffectedSlice ────────────────────────────────────────────────
    def get_doses_affected_slice(self, slice_id, headers):
        return self._request("GET", f"{ROOT}/doses-affected-slices/{slice_id}", headers=headers)

    def close_doses_affected_slice(self, slice_id, payload, headers):
        return self._request("POST", f"{ROOT}/doses-affected-slices/{slice_id}/close", payload, headers)

    def reopen_doses_affected_slice(self, slice_id, headers, payload=None):
        return self._request(
            "POST", f"{ROOT}/doses-affected-slices/{slice_id}/reopen", payload or {}, headers
        )

    # ── ExcursionAdjudication / AdjudicationAppeal ────────────────────────
    def list_excursion_adjudications(self, headers, params=None):
        return self._request("GET", f"{ROOT}/excursion-adjudications", params, headers=headers)

    def get_excursion_adjudication(self, adj_id, headers):
        return self._request("GET", f"{ROOT}/excursion-adjudications/{adj_id}", headers=headers)

    def withdraw_adjudication(self, adj_id, headers, payload=None):
        return self._request(
            "POST", f"{ROOT}/excursion-adjudications/{adj_id}/withdraw", payload or {}, headers
        )

    def list_adjudication_appeals(self, headers, params=None):
        return self._request("GET", f"{ROOT}/adjudication-appeals", params, headers=headers)

    def get_adjudication_appeal(self, appeal_id, headers):
        return self._request("GET", f"{ROOT}/adjudication-appeals/{appeal_id}", headers=headers)

    # ── WastageReport ─────────────────────────────────────────────────────
    def create_wastage_report(self, payload, headers):
        return self._request("POST", f"{ROOT}/wastage-reports", payload, headers)

    def list_wastage_reports(self, headers, params=None):
        return self._request("GET", f"{ROOT}/wastage-reports", params, headers=headers)

    def get_wastage_report(self, wr_id, headers):
        return self._request("GET", f"{ROOT}/wastage-reports/{wr_id}", headers=headers)

    def reconcile_wastage_report(self, wr_id, headers, payload=None):
        return self._request("POST", f"{ROOT}/wastage-reports/{wr_id}/reconcile", payload or {}, headers)

    # ── ReportingPeriod ───────────────────────────────────────────────────
    def create_reporting_period(self, payload, headers):
        return self._request("POST", f"{ROOT}/reporting-periods", payload, headers)

    def list_reporting_periods(self, headers, params=None):
        return self._request("GET", f"{ROOT}/reporting-periods", params, headers=headers)

    def get_reporting_period(self, period_id, headers):
        return self._request("GET", f"{ROOT}/reporting-periods/{period_id}", headers=headers)

    def submit_reporting_period(self, period_id, headers, payload=None):
        return self._request("POST", f"{ROOT}/reporting-periods/{period_id}/submit", payload or {}, headers)

    def reopen_reporting_period(self, period_id, headers, payload=None):
        return self._request("POST", f"{ROOT}/reporting-periods/{period_id}/reopen", payload or {}, headers)

    def get_period_accountability(self, period_id, payload, headers):
        return self._request(
            "GET", f"{ROOT}/reporting-periods/{period_id}/accountability", payload, headers=headers
        )

    # ── CartonStorageReservation ──────────────────────────────────────────
    def create_carton_storage_reservation(self, payload, headers):
        return self._request("POST", f"{ROOT}/carton-storage-reservations", payload, headers)

    def list_carton_storage_reservations(self, headers, params=None):
        return self._request("GET", f"{ROOT}/carton-storage-reservations", params, headers=headers)

    def get_carton_storage_reservation(self, res_id, headers):
        return self._request("GET", f"{ROOT}/carton-storage-reservations/{res_id}", headers=headers)

    # ── EntitlementRelease / ShippingWindowLapse / ProgramStanding ────────
    def list_entitlement_releases(self, headers, params=None):
        return self._request("GET", f"{ROOT}/entitlement-releases", params, headers=headers)

    def get_entitlement_release(self, rel_id, headers):
        return self._request("GET", f"{ROOT}/entitlement-releases/{rel_id}", headers=headers)

    def list_shipping_window_lapses(self, headers, params=None):
        return self._request("GET", f"{ROOT}/shipping-window-lapses", params, headers=headers)

    def get_shipping_window_lapse(self, lapse_id, headers):
        return self._request("GET", f"{ROOT}/shipping-window-lapses/{lapse_id}", headers=headers)

    def list_all_program_standings(self, headers, params=None):
        return self._request("GET", f"{ROOT}/program-standings", params, headers=headers)

    # ── CartonFamily ──────────────────────────────────────────────────────
    def create_carton_family(self, payload, headers):
        return self._request("POST", f"{ROOT}/carton-families", payload, headers)

    def list_carton_families(self, headers, params=None):
        return self._request("GET", f"{ROOT}/carton-families", params, headers=headers)

    def get_carton_family(self, fam_id, headers):
        return self._request("GET", f"{ROOT}/carton-families/{fam_id}", headers=headers)


api_client = ApiClient()