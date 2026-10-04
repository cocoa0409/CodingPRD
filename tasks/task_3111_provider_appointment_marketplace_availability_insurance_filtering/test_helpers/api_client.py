"""API client: one method per endpoint defined in the PRD.

All methods return the raw requests.Response; validation happens in the tests
via the framework validators.
"""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving / ops ---
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/marketplace/_clock/set_current_utc", payload, headers)

    def run_epoch(self, headers: Dict[str, str]):
        return self._request("POST", "/marketplace/ops/run-epoch", {}, headers)

    # --- Practice ---
    def create_practice(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/marketplace/practices", payload, headers)

    def list_practices(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/marketplace/practices", headers=headers, params=params)

    def get_practice(self, practice_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/marketplace/practices/{practice_id}", headers=headers)

    def activate_practice(self, practice_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/practices/{practice_id}/activate", {}, headers)

    def suspend_practice(self, practice_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/practices/{practice_id}/suspend", {}, headers)

    def reinstate_practice(self, practice_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/practices/{practice_id}/reinstate", {}, headers)

    def delist_practice(self, practice_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/practices/{practice_id}/delist", {}, headers)

    def set_billing_mode(self, practice_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/practices/{practice_id}/billing-mode", payload, headers)

    # --- Provider ---
    def create_provider(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/marketplace/providers", payload, headers)

    def list_providers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/marketplace/providers", headers=headers, params=params)

    def get_provider(self, provider_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/marketplace/providers/{provider_id}", headers=headers)

    def activate_provider(self, provider_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/providers/{provider_id}/activate", {}, headers)

    def suspend_provider(self, provider_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/providers/{provider_id}/suspend", {}, headers)

    def reinstate_provider(self, provider_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/providers/{provider_id}/reinstate", {}, headers)

    def delist_provider(self, provider_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/providers/{provider_id}/delist", {}, headers)

    # --- Slots ---
    def create_slot(self, provider_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/providers/{provider_id}/slots", payload, headers)

    def bulk_publish_slots(self, provider_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/providers/{provider_id}/slots/bulk-publish", payload, headers)

    def list_slots(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/marketplace/slots", headers=headers, params=params)

    def get_slot(self, slot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/marketplace/slots/{slot_id}", headers=headers)

    def close_slot(self, slot_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/slots/{slot_id}/close", {}, headers)

    # --- Appointment types ---
    def create_appointment_type(self, provider_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/providers/{provider_id}/appointment-types", payload, headers)

    def list_appointment_types(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/marketplace/appointment-types", headers=headers, params=params)

    def get_appointment_type(self, type_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/marketplace/appointment-types/{type_id}", headers=headers)

    def retire_appointment_type(self, type_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/appointment-types/{type_id}/retire", {}, headers)

    # --- Insurance plans ---
    def create_insurance_plan(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/marketplace/insurance-plans", payload, headers)

    def list_insurance_plans(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/marketplace/insurance-plans", headers=headers, params=params)

    def get_insurance_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/marketplace/insurance-plans/{plan_id}", headers=headers)

    def retire_insurance_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/insurance-plans/{plan_id}/retire", {}, headers)

    # --- Attestations ---
    def create_attestation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/marketplace/attestations", payload, headers)

    def list_attestations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/marketplace/attestations", headers=headers, params=params)

    def get_attestation(self, attestation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/marketplace/attestations/{attestation_id}", headers=headers)

    def verify_attestation(self, attestation_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/attestations/{attestation_id}/verify", payload, headers)

    # --- Patients ---
    def create_patient(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/marketplace/patients", payload, headers)

    def get_patient(self, patient_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/marketplace/patients/{patient_id}", headers=headers)

    def list_patients(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/marketplace/patients", headers=headers, params=params)

    def update_patient(self, patient_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/marketplace/patients/{patient_id}", payload, headers)

    # --- Contact events ---
    def create_contact_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/marketplace/contact-events", payload, headers)

    def list_contact_events(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/marketplace/contact-events", headers=headers, params=params)

    def get_contact_event(self, event_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/marketplace/contact-events/{event_id}", headers=headers)

    # --- Bookings ---
    def create_booking(self, slot_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/slots/{slot_id}/bookings", payload, headers)

    def list_bookings(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/marketplace/bookings", headers=headers, params=params)

    def get_booking(self, booking_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/marketplace/bookings/{booking_id}", headers=headers)

    def cancel_booking(self, booking_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/bookings/{booking_id}/cancel", {}, headers)

    def check_in_booking(self, booking_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/bookings/{booking_id}/check-in", {}, headers)

    def complete_booking(self, booking_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/bookings/{booking_id}/complete", {}, headers)

    def mark_no_show(self, booking_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/bookings/{booking_id}/mark-no-show", {}, headers)

    # --- Charges ---
    def list_charges(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/marketplace/charges", headers=headers, params=params)

    def get_charge(self, charge_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/marketplace/charges/{charge_id}", headers=headers)

    # --- Billing / invoices ---
    def generate_invoices(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/marketplace/billing/generate-invoices", payload, headers)

    def list_invoices(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/marketplace/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/marketplace/invoices/{invoice_id}", headers=headers)

    def dispute_invoice(self, invoice_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/invoices/{invoice_id}/dispute", payload, headers)

    def resolve_dispute(self, invoice_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/invoices/{invoice_id}/resolve-dispute", payload, headers)

    def pay_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/invoices/{invoice_id}/pay", {}, headers)

    def write_off_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/invoices/{invoice_id}/write-off", {}, headers)

    # --- Ledger ---
    def list_ledger_entries(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/marketplace/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/marketplace/ledger-entries/{entry_id}", headers=headers)

    # --- Complaints ---
    def create_complaint(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/marketplace/complaints", payload, headers)

    def list_complaints(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/marketplace/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/marketplace/complaints/{complaint_id}", headers=headers)

    def respond_complaint(self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/complaints/{complaint_id}/respond", payload, headers)

    def resolve_complaint(self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/complaints/{complaint_id}/resolve", payload, headers)

    # --- Reviews ---
    def create_review(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/marketplace/reviews", payload, headers)

    def list_reviews(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/marketplace/reviews", headers=headers, params=params)

    def get_review(self, review_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/marketplace/reviews/{review_id}", headers=headers)

    def flag_review(self, review_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/reviews/{review_id}/flag", payload, headers)

    def moderate_review(self, review_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/reviews/{review_id}/moderate", payload, headers)

    # --- Visit records ---
    def list_visit_records(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/marketplace/visit-records", headers=headers, params=params)

    def get_visit_record(self, record_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/marketplace/visit-records/{record_id}", headers=headers)

    def list_booking_visit_records(self, booking_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/marketplace/bookings/{booking_id}/visit-records", headers=headers, params=params)

    # --- Audit cases ---
    def create_audit_case(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/marketplace/audit-cases", payload, headers)

    def list_audit_cases(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/marketplace/audit-cases", headers=headers, params=params)

    def get_audit_case(self, case_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/marketplace/audit-cases/{case_id}", headers=headers)

    def run_audit_case(self, case_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/audit-cases/{case_id}/run", {}, headers)

    def resolve_finding(self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/audit-cases/{case_id}/resolve-finding", payload, headers)

    def close_audit_case(self, case_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/marketplace/audit-cases/{case_id}/close", {}, headers)


api_client = ApiClient()
