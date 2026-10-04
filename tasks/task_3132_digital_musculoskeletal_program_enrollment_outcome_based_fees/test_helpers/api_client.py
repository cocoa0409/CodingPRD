"""API client: one method per endpoint declared in PRD §4."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Test-driving ─────────────────────────────────
    def set_current_utc(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    def run_weekly_reconciliation(self, client_id, headers):
        return self._request("POST", f"/msk/clients/{client_id}/run-weekly-reconciliation",
                             {}, headers)

    # ─── Clients ──────────────────────────────────────
    def create_client(self, payload, headers):
        return self._request("POST", "/msk/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/msk/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/msk/clients", headers=headers, params=params)

    def suspend_client(self, client_id, payload, headers):
        return self._request("POST", f"/msk/clients/{client_id}/suspend", payload, headers)

    def reinstate_client(self, client_id, headers):
        return self._request("POST", f"/msk/clients/{client_id}/reinstate", {}, headers)

    def close_client(self, client_id, headers):
        return self._request("POST", f"/msk/clients/{client_id}/close", {}, headers)

    def recompute_engagement_tier(self, client_id, headers):
        return self._request("POST", f"/msk/clients/{client_id}/recompute_engagement-tier",
                             {}, headers)

    def retention_credit(self, client_id, headers):
        return self._request("POST", f"/msk/clients/{client_id}/retention-credit", {}, headers)

    def membership_roll(self, client_id, payload, headers):
        return self._request("POST", f"/msk/clients/{client_id}/membership-roll", payload, headers)

    def engagement_report(self, client_id, headers):
        return self._request("GET", f"/msk/clients/{client_id}/engagement-report", headers=headers)

    # ─── Program tracks ───────────────────────────────
    def create_program_track(self, payload, headers):
        return self._request("POST", "/msk/program-tracks", payload, headers)

    def get_program_track(self, track_id, headers):
        return self._request("GET", f"/msk/program-tracks/{track_id}", headers=headers)

    def list_program_tracks(self, headers, params=None):
        return self._request("GET", "/msk/program-tracks", headers=headers, params=params)

    # ─── Eligibility files ────────────────────────────
    def create_eligibility_file(self, payload, headers):
        return self._request("POST", "/msk/eligibility-files", payload, headers)

    def list_eligibility_files(self, headers, params=None):
        return self._request("GET", "/msk/eligibility-files", headers=headers, params=params)

    def get_eligibility_file(self, file_id, headers):
        return self._request("GET", f"/msk/eligibility-files/{file_id}", headers=headers)

    def screen_eligibility_file(self, file_id, headers):
        return self._request("POST", f"/msk/eligibility-files/{file_id}/screen", {}, headers)

    def assign_tracks(self, file_id, payload, headers):
        return self._request("POST", f"/msk/eligibility-files/{file_id}/assign-tracks",
                             payload, headers)

    def close_eligibility_file(self, file_id, headers):
        return self._request("POST", f"/msk/eligibility-files/{file_id}/close-file", {}, headers)

    # ─── Members ──────────────────────────────────────
    def create_member(self, payload, headers):
        return self._request("POST", "/msk/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/msk/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/msk/members/{member_id}", headers=headers)

    def recompute_eligibility(self, member_id, headers):
        return self._request("POST", f"/msk/members/{member_id}/recompute_eligibility",
                             {}, headers)

    # ─── Enrollments ──────────────────────────────────
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/msk/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/msk/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/msk/enrollments/{enrollment_id}", headers=headers)

    def drop_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/msk/enrollments/{enrollment_id}/drop", {}, headers)

    def complete_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/msk/enrollments/{enrollment_id}/complete", {}, headers)

    def register_transition_review(self, enrollment_id, payload, headers):
        return self._request("POST", f"/msk/enrollments/{enrollment_id}/transition-reviews",
                             payload, headers)

    def reconcile_reviews(self, headers):
        return self._request("POST", "/msk/enrollments/reconcile-reviews", {}, headers)

    # ─── Clinical reviews ─────────────────────────────
    def create_clinical_review(self, payload, headers):
        return self._request("POST", "/msk/clinical-reviews", payload, headers)

    def list_clinical_reviews(self, headers, params=None):
        return self._request("GET", "/msk/clinical-reviews", headers=headers, params=params)

    def get_clinical_review(self, review_id, headers):
        return self._request("GET", f"/msk/clinical-reviews/{review_id}", headers=headers)

    def conduct_clinical_review(self, review_id, payload, headers):
        return self._request("POST", f"/msk/clinical-reviews/{review_id}/conduct",
                             payload, headers)

    def reopen_clinical_review(self, review_id, headers):
        return self._request("POST", f"/msk/clinical-reviews/{review_id}/reopen", {}, headers)

    # ─── Transition reviews ───────────────────────────
    def approve_transition_review(self, enrollment_id, payload, headers):
        return self._request("POST", f"/msk/transition-reviews/{enrollment_id}/approve",
                             payload, headers)

    def deny_transition_review(self, enrollment_id, payload, headers):
        return self._request("POST", f"/msk/transition-reviews/{enrollment_id}/deny",
                             payload, headers)

    # ─── Exercise sessions ────────────────────────────
    def create_session(self, enrollment_id, payload, headers):
        return self._request("POST", f"/msk/enrollments/{enrollment_id}/sessions",
                             payload, headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/msk/exercise-sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/msk/exercise-sessions/{session_id}", headers=headers)

    def complete_session(self, session_id, payload, headers):
        return self._request("POST", f"/msk/exercise-sessions/{session_id}/complete",
                             payload, headers)

    def weekly_transition_session(self, session_id, payload, headers):
        return self._request("POST", f"/msk/exercise-sessions/{session_id}/weekly-transition",
                             payload, headers)

    # ─── Outreach ─────────────────────────────────────
    def create_outreach(self, payload, headers):
        return self._request("POST", "/msk/outreach-contacts", payload, headers)

    def list_outreach(self, headers, params=None):
        return self._request("GET", "/msk/outreach-contacts", headers=headers, params=params)

    def get_outreach(self, contact_id, headers):
        return self._request("GET", f"/msk/outreach-contacts/{contact_id}", headers=headers)

    def deliver_outreach(self, contact_id, headers):
        return self._request("POST", f"/msk/outreach-contacts/{contact_id}/deliver", {}, headers)

    # ─── Clinicians ───────────────────────────────────
    def create_clinician(self, payload, headers):
        return self._request("POST", "/msk/clinicians", payload, headers)

    def list_clinicians(self, headers, params=None):
        return self._request("GET", "/msk/clinicians", headers=headers, params=params)

    def get_clinician(self, clinician_id, headers):
        return self._request("GET", f"/msk/clinicians/{clinician_id}", headers=headers)

    def limit_clinician(self, clinician_id, headers):
        return self._request("POST", f"/msk/clinicians/{clinician_id}/limit", {}, headers)

    def restore_clinician(self, clinician_id, headers):
        return self._request("POST", f"/msk/clinicians/{clinician_id}/restore", {}, headers)

    def deactivate_clinician(self, clinician_id, headers):
        return self._request("POST", f"/msk/clinicians/{clinician_id}/deactivate", {}, headers)

    # ─── Appointments ─────────────────────────────────
    def create_appointment(self, payload, headers):
        return self._request("POST", "/msk/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/msk/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/msk/appointments/{appointment_id}", headers=headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/msk/appointments/{appointment_id}/cancel", {}, headers)

    def complete_appointment(self, appointment_id, headers):
        return self._request("POST", f"/msk/appointments/{appointment_id}/complete", {}, headers)

    # ─── Outcome measurements ─────────────────────────
    def create_measurement(self, payload, headers):
        return self._request("POST", "/msk/outcome-measurements", payload, headers)

    def list_measurements(self, headers, params=None):
        return self._request("GET", "/msk/outcome-measurements", headers=headers, params=params)

    def get_measurement(self, measurement_id, headers):
        return self._request("GET", f"/msk/outcome-measurements/{measurement_id}",
                             headers=headers)

    def supersede_measurement(self, measurement_id, payload, headers):
        return self._request("POST", f"/msk/outcome-measurements/{measurement_id}/supersede",
                             payload, headers)

    def finalize_measurement(self, measurement_id, headers):
        return self._request("POST", f"/msk/outcome-measurements/{measurement_id}/finalize",
                             {}, headers)

    # ─── Claim lines ──────────────────────────────────
    def create_claim_line(self, payload, headers):
        return self._request("POST", "/msk/claim-lines", payload, headers)

    def list_claim_lines(self, headers, params=None):
        return self._request("GET", "/msk/claim-lines", headers=headers, params=params)

    def get_claim_line(self, line_id, headers):
        return self._request("GET", f"/msk/claim-lines/{line_id}", headers=headers)

    def supersede_claim_line(self, line_id, payload, headers):
        return self._request("POST", f"/msk/claim-lines/{line_id}/supersede", payload, headers)

    def reinstate_claim_line(self, line_id, payload, headers):
        return self._request("POST", f"/msk/claim-lines/{line_id}/reinstate", payload, headers)

    # ─── Fee invoices ─────────────────────────────────
    def create_invoice(self, payload, headers):
        return self._request("POST", "/msk/fee-invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/msk/fee-invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/msk/fee-invoices/{invoice_id}", headers=headers)

    def finalize_invoice(self, invoice_id, headers):
        return self._request("POST", f"/msk/fee-invoices/{invoice_id}/finalize", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/msk/fee-invoices/{invoice_id}/void", {}, headers)

    def reopen_invoice(self, invoice_id, headers):
        return self._request("POST", f"/msk/fee-invoices/{invoice_id}/reopen", {}, headers)

    # ─── Care transitions ─────────────────────────────
    def create_care_transition(self, payload, headers):
        return self._request("POST", "/msk/care-transitions", payload, headers)

    def list_care_transitions(self, headers, params=None):
        return self._request("GET", "/msk/care-transitions", headers=headers, params=params)

    def get_care_transition(self, transition_id, headers):
        return self._request("GET", f"/msk/care-transitions/{transition_id}", headers=headers)

    def complete_care_transition(self, transition_id, headers):
        return self._request("POST", f"/msk/care-transitions/{transition_id}/complete",
                             {}, headers)


api_client = ApiClient()