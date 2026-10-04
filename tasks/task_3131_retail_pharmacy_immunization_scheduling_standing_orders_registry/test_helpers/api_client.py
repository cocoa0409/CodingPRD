"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/immunization/_clock/set_current_utc", payload, headers)

    # ---- Stores ----
    def create_store(self, payload, headers):
        return self._request("POST", "/immunization/stores", payload, headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", "/immunization/stores", headers=headers, params=params)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/immunization/stores/{store_id}", headers=headers)

    def update_store(self, store_id, payload, headers):
        return self._request("PUT", f"/immunization/stores/{store_id}", payload, headers)

    # ---- State Protocols ----
    def create_state_protocol(self, payload, headers):
        return self._request("POST", "/immunization/state-protocols", payload, headers)

    def list_state_protocols(self, headers, params=None):
        return self._request("GET", "/immunization/state-protocols", headers=headers, params=params)

    def get_state_protocol(self, protocol_id, headers):
        return self._request("GET", f"/immunization/state-protocols/{protocol_id}", headers=headers)

    def update_state_protocol(self, protocol_id, payload, headers):
        return self._request("PUT", f"/immunization/state-protocols/{protocol_id}", payload, headers)

    # ---- Vaccine Products ----
    def create_vaccine_product(self, payload, headers):
        return self._request("POST", "/immunization/vaccine-products", payload, headers)

    def list_vaccine_products(self, headers, params=None):
        return self._request("GET", "/immunization/vaccine-products", headers=headers, params=params)

    def get_vaccine_product(self, product_id, headers):
        return self._request("GET", f"/immunization/vaccine-products/{product_id}", headers=headers)

    # ---- Insurance Plans ----
    def create_insurance_plan(self, payload, headers):
        return self._request("POST", "/immunization/insurance-plans", payload, headers)

    def get_insurance_plan(self, plan_id, headers):
        return self._request("GET", f"/immunization/insurance-plans/{plan_id}", headers=headers)

    def update_insurance_plan(self, plan_id, payload, headers):
        return self._request("PUT", f"/immunization/insurance-plans/{plan_id}", payload, headers)

    # ---- Patients ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/immunization/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/immunization/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/immunization/patients", headers=headers, params=params)

    # ---- Vaccine Lots ----
    def create_lot(self, store_id, payload, headers):
        return self._request("POST", f"/immunization/stores/{store_id}/lots", payload, headers)

    def list_store_lots(self, store_id, headers, params=None):
        return self._request("GET", f"/immunization/stores/{store_id}/lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/immunization/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/immunization/lots", headers=headers, params=params)

    def create_temperature_reading(self, lot_id, payload, headers):
        return self._request("POST", f"/immunization/lots/{lot_id}/temperature-readings", payload, headers)

    def list_temperature_readings(self, lot_id, headers, params=None):
        return self._request("GET", f"/immunization/lots/{lot_id}/temperature-readings", headers=headers, params=params)

    def quarantine_lot(self, lot_id, headers):
        return self._request("POST", f"/immunization/lots/{lot_id}/quarantine", {}, headers)

    def release_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/immunization/lots/{lot_id}/release", payload, headers)

    def retire_lot(self, lot_id, headers):
        return self._request("POST", f"/immunization/lots/{lot_id}/retire", {}, headers)

    # ---- Appointments ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/immunization/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/immunization/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/immunization/appointments/{appointment_id}", headers=headers)

    def get_price_quote(self, appointment_id, headers):
        return self._request("GET", f"/immunization/appointments/{appointment_id}/price-quote", headers=headers)

    def check_in_appointment(self, appointment_id, headers):
        return self._request("POST", f"/immunization/appointments/{appointment_id}/check-in", {}, headers)

    def submit_questionnaire(self, appointment_id, payload, headers):
        return self._request("POST", f"/immunization/appointments/{appointment_id}/questionnaire", payload, headers)

    def get_questionnaire(self, appointment_id, headers):
        return self._request("GET", f"/immunization/appointments/{appointment_id}/questionnaire", headers=headers)

    def review_consent(self, appointment_id, payload, headers):
        return self._request("POST", f"/immunization/appointments/{appointment_id}/review-consent", payload, headers)

    def administer(self, appointment_id, payload, headers):
        return self._request("POST", f"/immunization/appointments/{appointment_id}/administer", payload, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/immunization/appointments/{appointment_id}/cancel", {}, headers)

    # ---- Immunization Records ----
    def get_immunization_record(self, record_id, headers):
        return self._request("GET", f"/immunization/immunization-records/{record_id}", headers=headers)

    def list_immunization_records(self, headers, params=None):
        return self._request("GET", "/immunization/immunization-records", headers=headers, params=params)

    def void_immunization_record(self, record_id, payload, headers):
        return self._request("POST", f"/immunization/immunization-records/{record_id}/void", payload, headers)

    def list_appointment_immunization_records(self, appointment_id, headers):
        return self._request("GET", f"/immunization/appointments/{appointment_id}/immunization-records", headers=headers)

    # ---- Registry Submissions ----
    def list_record_registry_submissions(self, record_id, headers):
        return self._request("GET", f"/immunization/immunization-records/{record_id}/registry-submissions", headers=headers)

    def get_registry_submission(self, submission_id, headers):
        return self._request("GET", f"/immunization/registry-submissions/{submission_id}", headers=headers)

    def list_registry_submissions(self, headers, params=None):
        return self._request("GET", "/immunization/registry-submissions", headers=headers, params=params)

    def submit_registry_submission(self, submission_id, payload, headers):
        return self._request("POST", f"/immunization/registry-submissions/{submission_id}/submit", payload, headers)

    def acknowledge_registry_submission(self, submission_id, headers):
        return self._request("POST", f"/immunization/registry-submissions/{submission_id}/acknowledge", {}, headers)

    def reject_registry_submission(self, submission_id, headers):
        return self._request("POST", f"/immunization/registry-submissions/{submission_id}/reject", {}, headers)

    # ---- Observation Sessions ----
    def list_record_observation_sessions(self, record_id, headers):
        return self._request("GET", f"/immunization/immunization-records/{record_id}/observation-sessions", headers=headers)

    def complete_observation_session(self, session_id, headers):
        return self._request("POST", f"/immunization/observation-sessions/{session_id}/complete", {}, headers)

    def escalate_observation_session(self, session_id, payload, headers):
        return self._request("POST", f"/immunization/observation-sessions/{session_id}/escalate", payload, headers)

    # ---- Clinic Events ----
    def create_clinic_event(self, payload, headers):
        return self._request("POST", "/immunization/clinic-events", payload, headers)

    def list_store_clinic_events(self, store_id, headers, params=None):
        return self._request("GET", f"/immunization/stores/{store_id}/clinic-events", headers=headers, params=params)

    def get_clinic_event(self, event_id, headers):
        return self._request("GET", f"/immunization/clinic-events/{event_id}", headers=headers)

    def list_clinic_events(self, headers, params=None):
        return self._request("GET", "/immunization/clinic-events", headers=headers, params=params)

    def cancel_clinic_event(self, event_id, headers):
        return self._request("POST", f"/immunization/clinic-events/{event_id}/cancel", {}, headers)

    def close_clinic_event(self, event_id, headers):
        return self._request("POST", f"/immunization/clinic-events/{event_id}/close", {}, headers)


api_client = ApiClient()
