"""API client: one method per endpoint in the direct-vehicle-sales-service API."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin wrapper around every endpoint the PRD exposes."""

    # ─── Logical clock & payment simulation ──────────────
    def set_current_utc(self, current_utc: str, headers):
        return self._request("POST", "/v1/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    def simulate_payment(self, payload, headers):
        return self._request("POST", "/v1/_payments/simulate", payload, headers)

    # ─── Buyer ───────────────────────────────────────────
    def create_buyer(self, payload, headers):
        return self._request("POST", "/v1/buyers", payload, headers)

    def list_buyers(self, headers, params=None):
        return self._request("GET", "/v1/buyers", headers=headers, params=params)

    def get_buyer(self, buyer_id, headers):
        return self._request("GET", f"/v1/buyers/{buyer_id}", headers=headers)

    def verify_buyer_identity(self, buyer_id, headers):
        return self._request("POST", f"/v1/buyers/{buyer_id}/identity-verification",
                             {}, headers)

    def suspend_buyer(self, buyer_id, headers):
        return self._request("POST", f"/v1/buyers/{buyer_id}/suspend", {}, headers)

    def list_buyer_ledger_entries(self, buyer_id, headers, params=None):
        return self._request("GET", f"/v1/buyers/{buyer_id}/fee-ledger-entries",
                             headers=headers, params=params)

    def list_buyer_orders(self, buyer_id, headers, params=None):
        return self._request("GET", f"/v1/buyers/{buyer_id}/orders",
                             headers=headers, params=params)

    def list_buyer_appraisals(self, buyer_id, headers, params=None):
        return self._request("GET", f"/v1/buyers/{buyer_id}/trade-in-appraisals",
                             headers=headers, params=params)

    def list_buyer_applications(self, buyer_id, headers, params=None):
        return self._request("GET", f"/v1/buyers/{buyer_id}/financing-applications",
                             headers=headers, params=params)

    # ─── StateJurisdiction ───────────────────────────────
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/v1/jurisdictions", payload, headers)

    def list_jurisdictions(self, headers, params=None):
        return self._request("GET", "/v1/jurisdictions", headers=headers, params=params)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/v1/jurisdictions/{jurisdiction_id}", headers=headers)

    def enact_jurisdiction(self, jurisdiction_id, headers):
        return self._request("POST", f"/v1/jurisdictions/{jurisdiction_id}/enact",
                             {}, headers)

    # ─── DeliveryCenter ──────────────────────────────────
    def create_delivery_center(self, payload, headers):
        return self._request("POST", "/v1/delivery-centers", payload, headers)

    def list_delivery_centers(self, headers, params=None):
        return self._request("GET", "/v1/delivery-centers", headers=headers, params=params)

    def get_delivery_center(self, center_id, headers):
        return self._request("GET", f"/v1/delivery-centers/{center_id}", headers=headers)

    def list_center_delivery_appointments(self, center_id, headers, params=None):
        return self._request("GET", f"/v1/delivery-centers/{center_id}/delivery-appointments",
                             headers=headers, params=params)

    def list_center_service_appointments(self, center_id, headers, params=None):
        return self._request("GET", f"/v1/delivery-centers/{center_id}/service-appointments",
                             headers=headers, params=params)

    def list_center_mobile_visits(self, center_id, headers, params=None):
        return self._request("GET", f"/v1/delivery-centers/{center_id}/mobile-service-visits",
                             headers=headers, params=params)

    def suspend_delivery_center(self, center_id, headers):
        return self._request("POST", f"/v1/delivery-centers/{center_id}/suspend",
                             {}, headers)

    def reinstate_delivery_center(self, center_id, headers):
        return self._request("POST", f"/v1/delivery-centers/{center_id}/reinstate",
                             {}, headers)

    # ─── VehicleConfiguration & ConfigurationOption ──────
    def create_configuration(self, payload, headers):
        return self._request("POST", "/v1/vehicle-configurations", payload, headers)

    def list_configurations(self, headers, params=None):
        return self._request("GET", "/v1/vehicle-configurations", headers=headers, params=params)

    def get_configuration(self, configuration_id, headers):
        return self._request("GET", f"/v1/vehicle-configurations/{configuration_id}",
                             headers=headers)

    def create_configuration_option(self, configuration_id, payload, headers):
        return self._request("POST", f"/v1/vehicle-configurations/{configuration_id}/options",
                             payload, headers)

    def list_configuration_options(self, configuration_id, headers, params=None):
        return self._request("GET", f"/v1/vehicle-configurations/{configuration_id}/options",
                             headers=headers, params=params)

    def list_options(self, headers, params=None):
        return self._request("GET", "/v1/configuration-options", headers=headers, params=params)

    def get_option(self, option_id, headers):
        return self._request("GET", f"/v1/configuration-options/{option_id}", headers=headers)

    def retire_option(self, option_id, headers):
        return self._request("POST", f"/v1/configuration-options/{option_id}/retire",
                             {}, headers)

    # ─── VehicleOrder ────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/v1/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/v1/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/v1/orders/{order_id}", headers=headers)

    def change_configuration(self, order_id, payload, headers):
        return self._request("POST", f"/v1/orders/{order_id}/configuration-changes",
                             payload, headers)

    def place_order(self, order_id, expected_order_version, headers):
        return self._request("POST", f"/v1/orders/{order_id}/place",
                             {"expected_order_version": expected_order_version}, headers)

    def lock_configuration(self, order_id, expected_order_version, headers):
        return self._request("POST", f"/v1/orders/{order_id}/lock-configuration",
                             {"expected_order_version": expected_order_version}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/v1/orders/{order_id}/cancel", {}, headers)

    def allocate_order(self, order_id, batch_id, expected_order_version, headers):
        return self._request("POST", f"/v1/orders/{order_id}/allocation",
                             {"batch_id": batch_id,
                              "expected_order_version": expected_order_version}, headers)

    def dispatch_to_transport(self, order_id, headers):
        return self._request("POST", f"/v1/orders/{order_id}/dispatch-to-transport",
                             {}, headers)

    def arrive_at_center(self, order_id, headers):
        return self._request("POST", f"/v1/orders/{order_id}/arrive-at-center",
                             {}, headers)

    def project_delivery_estimate(self, order_id, payload, headers):
        return self._request("POST", f"/v1/orders/{order_id}/delivery-estimates",
                             payload, headers)

    def list_order_estimates(self, order_id, headers, params=None):
        # PRD §2.9: `list_order_estimates` resolves the order first, then lists.
        return self.list_delivery_estimates(
            headers, params={**(params or {}), "order_id": order_id})

    def list_order_appraisals(self, order_id, headers, params=None):
        return self._request("GET", f"/v1/orders/{order_id}/trade-in-appraisals",
                             headers=headers, params=params)

    def list_order_applications(self, order_id, headers, params=None):
        return self._request("GET", f"/v1/orders/{order_id}/financing-applications",
                             headers=headers, params=params)

    def list_order_ledger_entries(self, order_id, headers, params=None):
        return self._request("GET", f"/v1/orders/{order_id}/fee-ledger-entries",
                             headers=headers, params=params)

    def post_ledger_entry(self, order_id, payload, headers):
        return self._request("POST", f"/v1/orders/{order_id}/fee-ledger-entries",
                             payload, headers)

    def list_order_allocation_units(self, order_id, headers, params=None):
        return self._request("GET", f"/v1/orders/{order_id}/allocation-units",
                             headers=headers, params=params)

    def list_order_appointments(self, order_id, headers, params=None):
        return self._request("GET", f"/v1/orders/{order_id}/delivery-appointments",
                             headers=headers, params=params)

    def list_order_vehicles(self, order_id, headers, params=None):
        return self._request("GET", f"/v1/orders/{order_id}/vehicles",
                             headers=headers, params=params)

    def list_order_issue_notes(self, order_id, headers, params=None):
        return self._request("GET", "/v1/issue-notes", headers=headers,
                             params={**(params or {}), "order_id": order_id})

    # ─── DeliveryAppointment ─────────────────────────────
    def book_delivery_appointment(self, payload, headers):
        return self._request("POST", "/v1/delivery-appointments", payload, headers)

    def list_delivery_appointments(self, headers, params=None):
        return self._request("GET", "/v1/delivery-appointments", headers=headers, params=params)

    def get_delivery_appointment(self, appointment_id, headers):
        return self._request("GET", f"/v1/delivery-appointments/{appointment_id}",
                             headers=headers)

    def confirm_delivery_appointment(self, appointment_id, headers):
        return self._request("POST", f"/v1/delivery-appointments/{appointment_id}/confirm",
                             {}, headers)

    def rebook_delivery_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/v1/delivery-appointments/{appointment_id}/rebook",
                             payload, headers)

    def cancel_delivery_appointment(self, appointment_id, headers):
        return self._request("POST", f"/v1/delivery-appointments/{appointment_id}/cancel",
                             {}, headers)

    def complete_delivery_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/v1/delivery-appointments/{appointment_id}/complete",
                             payload, headers)

    # ─── TradeInAppraisal ────────────────────────────────
    def create_appraisal(self, order_id, payload, headers):
        return self._request("POST", f"/v1/orders/{order_id}/trade-in-appraisals",
                             payload, headers)

    def list_appraisals(self, headers, params=None):
        return self._request("GET", "/v1/trade-in-appraisals", headers=headers, params=params)

    def get_appraisal(self, appraisal_id, headers):
        return self._request("GET", f"/v1/trade-in-appraisals/{appraisal_id}",
                             headers=headers)

    def appraise(self, order_id, appraisal_id, headers):
        return self._request(
            "POST", f"/v1/orders/{order_id}/trade-in-appraisals/{appraisal_id}/appraise",
            {}, headers)

    def offer_appraisal(self, order_id, appraisal_id, headers):
        return self._request(
            "POST", f"/v1/orders/{order_id}/trade-in-appraisals/{appraisal_id}/offer",
            {}, headers)

    def accept_appraisal(self, order_id, appraisal_id, headers):
        return self._request(
            "POST", f"/v1/orders/{order_id}/trade-in-appraisals/{appraisal_id}/accept",
            {}, headers)

    def reject_appraisal(self, order_id, appraisal_id, headers):
        return self._request(
            "POST", f"/v1/orders/{order_id}/trade-in-appraisals/{appraisal_id}/reject",
            {}, headers)

    def reappraise(self, order_id, appraisal_id, payload, headers):
        return self._request(
            "POST", f"/v1/orders/{order_id}/trade-in-appraisals/{appraisal_id}/reappraise",
            payload, headers)

    # ─── FinancingApplication ────────────────────────────
    def create_financing_application(self, order_id, payload, headers):
        return self._request("POST", f"/v1/orders/{order_id}/financing-applications",
                             payload, headers)

    def list_financing_applications(self, headers, params=None):
        return self._request("GET", "/v1/financing-applications",
                             headers=headers, params=params)

    def get_financing_application(self, application_id, headers):
        return self._request("GET", f"/v1/financing-applications/{application_id}",
                             headers=headers)

    def decide_financing_application(self, application_id, outcome, headers):
        return self._request("POST", f"/v1/financing-applications/{application_id}/decision",
                             {"outcome": outcome}, headers)

    def contract_review(self, application_id, expected_application_version, headers):
        return self._request(
            "POST", f"/v1/financing-applications/{application_id}/contract-review",
            {"expected_application_version": expected_application_version}, headers)

    def fund_application(self, application_id, expected_application_version, headers):
        return self._request(
            "POST", f"/v1/financing-applications/{application_id}/fund",
            {"expected_application_version": expected_application_version}, headers)

    # ─── ProductionBatch & AllocationUnit ────────────────
    def create_production_batch(self, payload, headers):
        return self._request("POST", "/v1/production-batches", payload, headers)

    def list_production_batches(self, headers, params=None):
        return self._request("GET", "/v1/production-batches", headers=headers, params=params)

    def get_production_batch(self, batch_id, headers):
        return self._request("GET", f"/v1/production-batches/{batch_id}", headers=headers)

    def start_batch(self, batch_id, headers):
        return self._request("POST", f"/v1/production-batches/{batch_id}/start", {}, headers)

    def delay_batch(self, batch_id, delay_days, headers):
        return self._request("POST", f"/v1/production-batches/{batch_id}/delay",
                             {"delay_days": delay_days}, headers)

    def resume_batch(self, batch_id, headers):
        return self._request("POST", f"/v1/production-batches/{batch_id}/resume", {}, headers)

    def complete_batch(self, batch_id, headers):
        return self._request("POST", f"/v1/production-batches/{batch_id}/complete", {}, headers)

    def mint_allocation_unit(self, batch_id, vin, headers):
        return self._request("POST", f"/v1/production-batches/{batch_id}/allocation-units",
                             {"vin": vin}, headers)

    def list_batch_allocation_units(self, batch_id, headers, params=None):
        return self._request("GET", f"/v1/production-batches/{batch_id}/allocation-units",
                             headers=headers, params=params)

    def get_allocation_unit(self, unit_id, headers):
        return self._request("GET", f"/v1/allocation-units/{unit_id}", headers=headers)

    # ─── DeliveryEstimate ────────────────────────────────
    def list_delivery_estimates(self, headers, params=None):
        return self._request("GET", "/v1/delivery-estimates", headers=headers, params=params)

    def get_delivery_estimate(self, estimate_id, headers):
        return self._request("GET", f"/v1/delivery-estimates/{estimate_id}", headers=headers)

    def restore_delivery_estimate(self, estimate_id, headers):
        return self._request("POST", f"/v1/delivery-estimates/{estimate_id}/restore",
                             {}, headers)

    # ─── Vehicle & diagnostics ───────────────────────────
    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/v1/vehicles", headers=headers, params=params)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/v1/vehicles/{vehicle_id}", headers=headers)

    def retire_vehicle(self, vehicle_id, headers):
        return self._request("POST", f"/v1/vehicles/{vehicle_id}/retire", {}, headers)

    def pull_diagnostic_report(self, vehicle_id, payload, headers):
        return self._request("POST", f"/v1/vehicles/{vehicle_id}/diagnostic-reports",
                             payload, headers)

    def list_diagnostic_reports(self, headers, params=None):
        return self._request("GET", "/v1/diagnostic-reports", headers=headers, params=params)

    def get_diagnostic_report(self, report_id, headers):
        return self._request("GET", f"/v1/diagnostic-reports/{report_id}", headers=headers)

    def list_vehicle_reports(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/v1/vehicles/{vehicle_id}/diagnostic-reports",
                             headers=headers, params=params)

    def list_vehicle_service_appointments(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/v1/vehicles/{vehicle_id}/service-appointments",
                             headers=headers, params=params)

    def list_vehicle_mobile_visits(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/v1/vehicles/{vehicle_id}/mobile-service-visits",
                             headers=headers, params=params)

    def list_vehicle_entitlements(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/v1/vehicles/{vehicle_id}/software-entitlements",
                             headers=headers, params=params)

    def list_vehicle_issue_notes(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/v1/vehicles/{vehicle_id}/issue-notes",
                             headers=headers, params=params)

    # ─── ServiceAppointment ──────────────────────────────
    def create_service_appointment(self, payload, headers):
        return self._request("POST", "/v1/service-appointments", payload, headers)

    def list_service_appointments(self, headers, params=None):
        return self._request("GET", "/v1/service-appointments", headers=headers, params=params)

    def get_service_appointment(self, appointment_id, headers):
        return self._request("GET", f"/v1/service-appointments/{appointment_id}",
                             headers=headers)

    def schedule_service_center(self, appointment_id, payload, headers):
        return self._request("POST",
                             f"/v1/service-appointments/{appointment_id}/schedule-center",
                             payload, headers)

    def cancel_service_appointment(self, appointment_id, headers):
        return self._request("POST", f"/v1/service-appointments/{appointment_id}/cancel",
                             {}, headers)

    # ─── MobileServiceVisit ──────────────────────────────
    def dispatch_mobile_visit(self, payload, headers):
        return self._request("POST", "/v1/mobile-service-visits", payload, headers)

    def list_mobile_visits(self, headers, params=None):
        return self._request("GET", "/v1/mobile-service-visits", headers=headers, params=params)

    def get_mobile_visit(self, visit_id, headers):
        return self._request("GET", f"/v1/mobile-service-visits/{visit_id}", headers=headers)

    def reserve_parts(self, visit_id, headers):
        return self._request("POST", f"/v1/mobile-service-visits/{visit_id}/reserve-parts",
                             {}, headers)

    def confirm_parts_shipment(self, visit_id, headers):
        return self._request(
            "POST", f"/v1/mobile-service-visits/{visit_id}/confirm-parts-shipment",
            {}, headers)

    def start_mobile_visit(self, visit_id, headers):
        return self._request("POST", f"/v1/mobile-service-visits/{visit_id}/start",
                             {}, headers)

    def complete_mobile_visit(self, visit_id, headers):
        return self._request("POST", f"/v1/mobile-service-visits/{visit_id}/complete",
                             {}, headers)

    def cancel_mobile_visit(self, visit_id, headers):
        return self._request("POST", f"/v1/mobile-service-visits/{visit_id}/cancel",
                             {}, headers)

    def reschedule_mobile_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/v1/mobile-service-visits/{visit_id}/reschedule",
                             payload, headers)

    # ─── SoftwareEntitlement ─────────────────────────────
    def grant_entitlements(self, vehicle_id, payload, headers):
        return self._request("POST", f"/v1/vehicles/{vehicle_id}/software-entitlements",
                             payload, headers)

    def list_entitlements(self, headers, params=None):
        return self._request("GET", "/v1/software-entitlements", headers=headers, params=params)

    def get_entitlement(self, entitlement_id, headers):
        return self._request("GET", f"/v1/software-entitlements/{entitlement_id}",
                             headers=headers)

    def revoke_entitlement(self, vehicle_id, entitlement_id, headers):
        return self._request(
            "POST",
            f"/v1/vehicles/{vehicle_id}/software-entitlements/{entitlement_id}/revoke",
            {}, headers)

    # ─── VehicleIssueNote ────────────────────────────────
    def list_issue_notes(self, headers, params=None):
        return self._request("GET", "/v1/issue-notes", headers=headers, params=params)

    def get_issue_note(self, note_id, headers):
        return self._request("GET", f"/v1/issue-notes/{note_id}", headers=headers)

    def resolve_issue_note(self, note_id, headers):
        return self._request("POST", f"/v1/issue-notes/{note_id}/resolve", {}, headers)

    def waive_issue_note(self, note_id, payload, headers):
        return self._request("POST", f"/v1/issue-notes/{note_id}/waive", payload, headers)

    # ─── Fee ledger (cross-order) ────────────────────────
    def list_fee_ledger_entries(self, headers, params=None):
        return self._request("GET", "/v1/fee-ledger-entries", headers=headers, params=params)


api_client = ApiClient()