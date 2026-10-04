"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/cgm/_clock/set_current_utc", payload, headers)

    # --- patients ---
    def create_patient(self, payload, headers):
        return self._request("POST", "/cgm/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/cgm/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/cgm/patients/{patient_id}", headers=headers)

    def list_patient_coverage_verifications(self, patient_id, headers):
        return self._request("GET", f"/cgm/patients/{patient_id}/coverage-verifications", headers=headers)

    def list_patient_sensor_units(self, patient_id, headers):
        return self._request("GET", f"/cgm/patients/{patient_id}/sensor-units", headers=headers)

    def list_patient_warranty_claims(self, patient_id, headers):
        return self._request("GET", f"/cgm/patients/{patient_id}/warranty-claims", headers=headers)

    def list_patient_adverse_event_reports(self, patient_id, headers):
        return self._request("GET", f"/cgm/patients/{patient_id}/adverse-event-reports", headers=headers)

    # --- prescribers ---
    def create_prescriber(self, payload, headers):
        return self._request("POST", "/cgm/prescribers", payload, headers)

    def get_prescriber(self, prescriber_id, headers):
        return self._request("GET", f"/cgm/prescribers/{prescriber_id}", headers=headers)

    def list_prescriber_prescriptions(self, prescriber_id, headers):
        return self._request("GET", f"/cgm/prescribers/{prescriber_id}/prescriptions", headers=headers)

    # --- payers ---
    def create_payer(self, payload, headers):
        return self._request("POST", "/cgm/payers", payload, headers)

    def get_payer(self, payer_id, headers):
        return self._request("GET", f"/cgm/payers/{payer_id}", headers=headers)

    def list_payer_coverage_verifications(self, payer_id, headers):
        return self._request("GET", f"/cgm/payers/{payer_id}/coverage-verifications", headers=headers)

    def list_payer_support_enrollments(self, payer_id, headers):
        return self._request("GET", f"/cgm/payers/{payer_id}/support-enrollments", headers=headers)

    # --- sensor products ---
    def create_sensor_product(self, payload, headers):
        return self._request("POST", "/cgm/sensor-products", payload, headers)

    def get_sensor_product(self, product_id, headers):
        return self._request("GET", f"/cgm/sensor-products/{product_id}", headers=headers)

    def list_product_prescriptions(self, product_id, headers):
        return self._request("GET", f"/cgm/sensor-products/{product_id}/prescriptions", headers=headers)

    # --- sensor lots ---
    def create_sensor_lot(self, product_id, payload, headers):
        return self._request("POST", f"/cgm/sensor-products/{product_id}/sensor-lots", payload, headers)

    def list_product_lots(self, product_id, headers):
        return self._request("GET", f"/cgm/sensor-products/{product_id}/sensor-lots", headers=headers)

    def get_sensor_lot(self, lot_id, headers):
        return self._request("GET", f"/cgm/sensor-lots/{lot_id}", headers=headers)

    def list_lot_sensor_orders(self, lot_id, headers):
        return self._request("GET", f"/cgm/sensor-lots/{lot_id}/sensor-orders", headers=headers)

    def downgrade_lot_posture(self, lot_id, payload, headers):
        return self._request("POST", f"/cgm/sensor-lots/{lot_id}/downgrade-posture", payload, headers)

    # --- sensor units ---
    def create_sensor_unit(self, lot_id, payload, headers):
        return self._request("POST", f"/cgm/sensor-lots/{lot_id}/sensor-units", payload, headers)

    def list_lot_sensor_units(self, lot_id, headers):
        return self._request("GET", f"/cgm/sensor-lots/{lot_id}/sensor-units", headers=headers)

    def get_sensor_unit(self, unit_id, headers):
        return self._request("GET", f"/cgm/sensor-units/{unit_id}", headers=headers)

    def list_unit_device_bindings(self, unit_id, headers):
        return self._request("GET", f"/cgm/sensor-units/{unit_id}/device-bindings", headers=headers)

    def list_unit_replacement_shipments(self, unit_id, headers):
        return self._request("GET", f"/cgm/sensor-units/{unit_id}/replacement-shipments", headers=headers)

    def list_unit_adverse_event_reports(self, unit_id, headers):
        return self._request("GET", f"/cgm/sensor-units/{unit_id}/adverse-event-reports", headers=headers)

    def report_early_failure(self, unit_id, headers):
        return self._request("POST", f"/cgm/sensor-units/{unit_id}/report-early-failure", {}, headers)

    def scrap_sensor_unit(self, unit_id, headers):
        return self._request("POST", f"/cgm/sensor-units/{unit_id}/scrap", {}, headers)

    # --- prescriptions ---
    def create_prescription(self, patient_id, payload, headers):
        return self._request("POST", f"/cgm/patients/{patient_id}/prescriptions", payload, headers)

    def list_patient_prescriptions(self, patient_id, headers):
        return self._request("GET", f"/cgm/patients/{patient_id}/prescriptions", headers=headers)

    def get_prescription(self, prescription_id, headers):
        return self._request("GET", f"/cgm/prescriptions/{prescription_id}", headers=headers)

    def list_prescription_sensor_orders(self, prescription_id, headers):
        return self._request("GET", f"/cgm/prescriptions/{prescription_id}/sensor-orders", headers=headers)

    def cancel_prescription(self, prescription_id, headers):
        return self._request("POST", f"/cgm/prescriptions/{prescription_id}/cancel", {}, headers)

    # --- coverage verifications ---
    def create_coverage_verification(self, prescription_id, payload, headers):
        return self._request("POST", f"/cgm/prescriptions/{prescription_id}/coverage-verifications", payload, headers)

    def list_prescription_coverage_verifications(self, prescription_id, headers):
        return self._request("GET", f"/cgm/prescriptions/{prescription_id}/coverage-verifications", headers=headers)

    def get_coverage_verification(self, verification_id, headers):
        return self._request("GET", f"/cgm/coverage-verifications/{verification_id}", headers=headers)

    def list_verification_sensor_orders(self, verification_id, headers):
        return self._request("GET", f"/cgm/coverage-verifications/{verification_id}/sensor-orders", headers=headers)

    def decide_coverage_verification(self, verification_id, payload, headers):
        return self._request("POST", f"/cgm/coverage-verifications/{verification_id}/decide", payload, headers)

    # --- sensor orders ---
    def create_sensor_order(self, patient_id, payload, headers):
        return self._request("POST", f"/cgm/patients/{patient_id}/sensor-orders", payload, headers)

    def list_patient_sensor_orders(self, patient_id, headers):
        return self._request("GET", f"/cgm/patients/{patient_id}/sensor-orders", headers=headers)

    def get_sensor_order(self, order_id, headers):
        return self._request("GET", f"/cgm/sensor-orders/{order_id}", headers=headers)

    def pick_sensor_order(self, order_id, headers):
        return self._request("POST", f"/cgm/sensor-orders/{order_id}/pick", {}, headers)

    def adjudicate_sensor_order(self, order_id, payload, headers):
        return self._request("POST", f"/cgm/sensor-orders/{order_id}/adjudicate", payload, headers)

    def mark_paid_sensor_order(self, order_id, headers):
        return self._request("POST", f"/cgm/sensor-orders/{order_id}/mark-paid", {}, headers)

    def reverse_sensor_order(self, order_id, headers):
        return self._request("POST", f"/cgm/sensor-orders/{order_id}/reverse", {}, headers)

    def ship_sensor_order(self, order_id, headers):
        return self._request("POST", f"/cgm/sensor-orders/{order_id}/ship", {}, headers)

    def deliver_sensor_order(self, order_id, headers):
        return self._request("POST", f"/cgm/sensor-orders/{order_id}/deliver", {}, headers)

    def cancel_sensor_order(self, order_id, headers):
        return self._request("POST", f"/cgm/sensor-orders/{order_id}/cancel", {}, headers)

    # --- device bindings ---
    def create_device_binding(self, patient_id, payload, headers):
        return self._request("POST", f"/cgm/patients/{patient_id}/device-bindings", payload, headers)

    def list_patient_device_bindings(self, patient_id, headers):
        return self._request("GET", f"/cgm/patients/{patient_id}/device-bindings", headers=headers)

    def get_device_binding(self, binding_id, headers):
        return self._request("GET", f"/cgm/device-bindings/{binding_id}", headers=headers)

    # --- warranty claims ---
    def create_warranty_claim(self, unit_id, payload, headers):
        return self._request("POST", f"/cgm/sensor-units/{unit_id}/warranty-claims", payload, headers)

    def list_unit_warranty_claims(self, unit_id, headers):
        return self._request("GET", f"/cgm/sensor-units/{unit_id}/warranty-claims", headers=headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/cgm/warranty-claims/{claim_id}", headers=headers)

    def begin_review_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/cgm/warranty-claims/{claim_id}/begin-review", {}, headers)

    def request_more_info_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/cgm/warranty-claims/{claim_id}/request-more-info", {}, headers)

    def resubmit_data_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/cgm/warranty-claims/{claim_id}/resubmit-data", payload, headers)

    def decide_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/cgm/warranty-claims/{claim_id}/decide", payload, headers)

    def close_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/cgm/warranty-claims/{claim_id}/close", {}, headers)

    # --- replacement shipments ---
    def list_claim_replacement_shipments(self, claim_id, headers):
        return self._request("GET", f"/cgm/warranty-claims/{claim_id}/replacement-shipments", headers=headers)

    def get_replacement_shipment(self, shipment_id, headers):
        return self._request("GET", f"/cgm/replacement-shipments/{shipment_id}", headers=headers)

    def ship_replacement_shipment(self, shipment_id, headers):
        return self._request("POST", f"/cgm/replacement-shipments/{shipment_id}/ship", {}, headers)

    def deliver_replacement_shipment(self, shipment_id, headers):
        return self._request("POST", f"/cgm/replacement-shipments/{shipment_id}/deliver", {}, headers)

    def cancel_replacement_shipment(self, shipment_id, headers):
        return self._request("POST", f"/cgm/replacement-shipments/{shipment_id}/cancel", {}, headers)

    # --- support enrollments ---
    def create_support_enrollment(self, patient_id, payload, headers):
        return self._request("POST", f"/cgm/patients/{patient_id}/support-enrollments", payload, headers)

    def list_patient_support_enrollments(self, patient_id, headers):
        return self._request("GET", f"/cgm/patients/{patient_id}/support-enrollments", headers=headers)

    def get_support_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/cgm/support-enrollments/{enrollment_id}", headers=headers)

    def suspend_support_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/cgm/support-enrollments/{enrollment_id}/suspend", {}, headers)

    def reinstate_support_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/cgm/support-enrollments/{enrollment_id}/reinstate", {}, headers)

    def terminate_support_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/cgm/support-enrollments/{enrollment_id}/terminate", {}, headers)

    # --- adverse event reports ---
    def create_adverse_event_report(self, lot_id, payload, headers):
        return self._request("POST", f"/cgm/sensor-lots/{lot_id}/adverse-event-reports", payload, headers)

    def list_lot_adverse_event_reports(self, lot_id, headers):
        return self._request("GET", f"/cgm/sensor-lots/{lot_id}/adverse-event-reports", headers=headers)

    def get_adverse_event_report(self, report_id, headers):
        return self._request("GET", f"/cgm/adverse-event-reports/{report_id}", headers=headers)

    def investigate_adverse_event_report(self, report_id, headers):
        return self._request("POST", f"/cgm/adverse-event-reports/{report_id}/investigate", {}, headers)

    def close_adverse_event_report(self, report_id, payload, headers):
        return self._request("POST", f"/cgm/adverse-event-reports/{report_id}/close", payload, headers)


api_client = ApiClient()
