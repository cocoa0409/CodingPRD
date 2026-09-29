"""API client — one method per endpoint in the PRD endpoint table.

Every collection is mounted at the root of the URL space (PRD §1), so the paths
below are literal transcriptions of the endpoint table.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Treatment types
    # ------------------------------------------------------------------
    def create_treatment_type(self, payload, headers):
        return self._request("POST", "/treatment-types", payload, headers)

    # PRD §4 defines no read endpoint for treatment types: the registration
    # response is the only observation of a menu item.

    # ------------------------------------------------------------------
    # Treatment rooms
    # ------------------------------------------------------------------
    def create_treatment_room(self, payload, headers):
        return self._request("POST", "/treatment-rooms", payload, headers)

    # PRD §4 defines no room collection endpoint; rooms are read one at a time.

    def get_treatment_room(self, room_id, headers):
        return self._request("GET", f"/treatment-rooms/{room_id}", headers=headers)

    def patch_treatment_room(self, room_id, payload, headers):
        return self._request("PATCH", f"/treatment-rooms/{room_id}", payload, headers)

    # ------------------------------------------------------------------
    # Therapists
    # ------------------------------------------------------------------
    def create_therapist(self, payload, headers):
        return self._request("POST", "/therapists", payload, headers)

    # PRD §4 defines no therapist collection endpoint.

    def get_therapist(self, therapist_id, headers):
        return self._request("GET", f"/therapists/{therapist_id}", headers=headers)

    def suspend_therapist(self, therapist_id, payload, headers):
        return self._request(
            "POST", f"/therapists/{therapist_id}/suspend", payload, headers)

    def reinstate_therapist(self, therapist_id, payload, headers):
        return self._request(
            "POST", f"/therapists/{therapist_id}/reinstate", payload, headers)

    # ------------------------------------------------------------------
    # Licences
    # ------------------------------------------------------------------
    def create_license(self, therapist_id, payload, headers):
        return self._request(
            "POST", f"/therapists/{therapist_id}/licenses", payload, headers)

    def list_licenses(self, therapist_id, headers, params=None):
        return self._request(
            "GET", f"/therapists/{therapist_id}/licenses", headers=headers, params=params)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/therapist-licenses/{license_id}", headers=headers)

    def review_license(self, license_id, payload, headers):
        return self._request(
            "POST", f"/therapist-licenses/{license_id}/review", payload, headers)

    def resubmit_license(self, license_id, payload, headers):
        return self._request(
            "POST", f"/therapist-licenses/{license_id}/resubmit", payload, headers)

    # ------------------------------------------------------------------
    # Continuing education
    # ------------------------------------------------------------------
    def create_ce_record(self, license_id, payload, headers):
        return self._request(
            "POST", f"/therapist-licenses/{license_id}/ce-records", payload, headers)

    def list_ce_records(self, license_id, headers, params=None):
        return self._request(
            "GET", f"/therapist-licenses/{license_id}/ce-records",
            headers=headers, params=params)

    def get_ce_compliance(self, license_id, headers, params=None):
        return self._request(
            "GET", f"/therapist-licenses/{license_id}/ce-compliance",
            headers=headers, params=params)

    # ------------------------------------------------------------------
    # Certifications
    # ------------------------------------------------------------------
    def create_certification(self, therapist_id, payload, headers):
        return self._request(
            "POST", f"/therapists/{therapist_id}/certifications", payload, headers)

    def list_certifications(self, therapist_id, headers, params=None):
        return self._request(
            "GET", f"/therapists/{therapist_id}/certifications",
            headers=headers, params=params)

    def revoke_certification(self, certification_id, payload, headers):
        return self._request(
            "POST", f"/certifications/{certification_id}/revoke", payload, headers)

    # ------------------------------------------------------------------
    # Shift blocks
    # ------------------------------------------------------------------
    def create_shift_block(self, therapist_id, payload, headers):
        return self._request(
            "POST", f"/therapists/{therapist_id}/shift-blocks", payload, headers)

    def list_shift_blocks(self, therapist_id, headers, params=None):
        return self._request(
            "GET", f"/therapists/{therapist_id}/shift-blocks",
            headers=headers, params=params)

    # ------------------------------------------------------------------
    # Guests
    # ------------------------------------------------------------------
    def create_guest(self, payload, headers):
        return self._request("POST", "/guests", payload, headers)

    # PRD §4 defines no guest collection endpoint.

    def get_guest(self, guest_id, headers):
        return self._request("GET", f"/guests/{guest_id}", headers=headers)

    # ------------------------------------------------------------------
    # Intake forms
    # ------------------------------------------------------------------
    def create_intake_form(self, guest_id, payload, headers):
        return self._request(
            "POST", f"/guests/{guest_id}/intake-forms", payload, headers)

    def list_intake_forms(self, guest_id, headers, params=None):
        return self._request(
            "GET", f"/guests/{guest_id}/intake-forms", headers=headers, params=params)

    def get_intake_form(self, intake_form_id, headers):
        return self._request("GET", f"/intake-forms/{intake_form_id}", headers=headers)

    def sign_consent(self, intake_form_id, payload, headers):
        return self._request(
            "POST", f"/intake-forms/{intake_form_id}/consent", payload, headers)

    def submit_intake_form(self, intake_form_id, payload, headers):
        return self._request(
            "POST", f"/intake-forms/{intake_form_id}/submit", payload, headers)

    def screen_intake_form(self, intake_form_id, payload, headers):
        return self._request(
            "POST", f"/intake-forms/{intake_form_id}/screen", payload, headers)

    def override_intake_form(self, intake_form_id, payload, headers):
        return self._request(
            "POST", f"/intake-forms/{intake_form_id}/override", payload, headers)

    def amend_intake_form(self, intake_form_id, payload, headers):
        return self._request(
            "POST", f"/intake-forms/{intake_form_id}/amend", payload, headers)

    # ------------------------------------------------------------------
    # Appointments
    # ------------------------------------------------------------------
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def confirm_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/confirm", payload, headers)

    def check_in_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/check-in", payload, headers)

    def start_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/start", payload, headers)

    def complete_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/complete", payload, headers)

    def cancel_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/cancel", payload, headers)

    def no_show_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/no-show", payload, headers)

    # ------------------------------------------------------------------
    # Retail attachments
    # ------------------------------------------------------------------
    def create_retail_attachment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/retail-attachments",
            payload, headers)

    def list_retail_attachments(self, appointment_id, headers, params=None):
        return self._request(
            "GET", f"/appointments/{appointment_id}/retail-attachments",
            headers=headers, params=params)

    def resolve_retail_attachment(self, attachment_id, payload, headers):
        return self._request(
            "POST", f"/retail-attachments/{attachment_id}/resolve", payload, headers)

    # ------------------------------------------------------------------
    # Settlements and folio
    # ------------------------------------------------------------------
    def create_settlement(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/settlements", payload, headers)

    def list_settlements(self, appointment_id, headers, params=None):
        return self._request(
            "GET", f"/appointments/{appointment_id}/settlements",
            headers=headers, params=params)

    def list_guest_folio_charges(self, guest_id, headers, params=None):
        return self._request(
            "GET", f"/guests/{guest_id}/folio-charges", headers=headers, params=params)

    def list_appointment_folio_charges(self, appointment_id, headers, params=None):
        return self._request(
            "GET", f"/appointments/{appointment_id}/folio-charges",
            headers=headers, params=params)

    # ------------------------------------------------------------------
    # Reports and sweeps
    # ------------------------------------------------------------------
    def get_room_utilization_report(self, headers, params=None):
        return self._request(
            "GET", "/reports/room-utilization", headers=headers, params=params)

    def get_retail_attachment_report(self, headers, params=None):
        return self._request(
            "GET", "/reports/retail-attachment", headers=headers, params=params)

    def run_compliance_sweep(self, payload, headers):
        return self._request("POST", "/compliance-sweeps", payload, headers)


api_client = ApiClient()
