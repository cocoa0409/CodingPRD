"""API client: one method per endpoint described in the PRD; all paths carry
the `/network` API prefix."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock / test driving ──────────────────
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/network/_clock/set_current_utc",
            {"current_utc": current_utc}, headers,
        )

    def inject_claim_outcome(self, payload, headers):
        return self._request("POST", "/network/_inject/claim-outcome", payload, headers)

    # ─── Clinician ─────────────────────────────────────
    def create_clinician(self, payload, headers):
        return self._request("POST", "/network/clinicians", payload, headers)

    def list_clinicians(self, headers, params=None):
        return self._request("GET", "/network/clinicians", params, headers)

    def get_clinician(self, clinician_id, headers):
        return self._request("GET", f"/network/clinicians/{clinician_id}", headers=headers)

    def update_clinician(self, clinician_id, payload, headers):
        return self._request("PUT", f"/network/clinicians/{clinician_id}", payload, headers)

    def submit_credentials(self, clinician_id, headers):
        return self._request(
            "POST", f"/network/clinicians/{clinician_id}/submit-credentials", {}, headers
        )

    def suspend_clinician(self, clinician_id, headers):
        return self._request("POST", f"/network/clinicians/{clinician_id}/suspend", {}, headers)

    def reinstate_clinician(self, clinician_id, headers):
        return self._request("POST", f"/network/clinicians/{clinician_id}/reinstate", {}, headers)

    def request_offboarding(self, clinician_id, headers):
        return self._request(
            "POST", f"/network/clinicians/{clinician_id}/request-offboarding", {}, headers
        )

    def cancel_offboarding(self, clinician_id, headers):
        return self._request(
            "POST", f"/network/clinicians/{clinician_id}/cancel-offboarding", {}, headers
        )

    def complete_offboarding(self, clinician_id, headers):
        return self._request(
            "POST", f"/network/clinicians/{clinician_id}/complete-offboarding", {}, headers
        )

    # ─── License ───────────────────────────────────────
    def create_license(self, clinician_id, payload, headers):
        return self._request(
            "POST", f"/network/clinicians/{clinician_id}/licenses", payload, headers
        )

    def list_licenses(self, clinician_id, headers, params=None):
        return self._request(
            "GET", f"/network/clinicians/{clinician_id}/licenses", params, headers
        )

    def verify_license(self, clinician_id, license_id, headers):
        return self._request(
            "POST",
            f"/network/clinicians/{clinician_id}/licenses/{license_id}/verify",
            {}, headers,
        )

    def reverify_license(self, clinician_id, license_id, payload, headers):
        return self._request(
            "POST",
            f"/network/clinicians/{clinician_id}/licenses/{license_id}/reverify",
            payload, headers,
        )

    def reset_license_verification(self, clinician_id, license_id, headers):
        return self._request(
            "POST",
            f"/network/clinicians/{clinician_id}/licenses/{license_id}/reset-verification",
            {}, headers,
        )

    # ─── MalpracticePolicy ─────────────────────────────
    def create_malpractice_policy(self, clinician_id, payload, headers):
        return self._request(
            "POST", f"/network/clinicians/{clinician_id}/malpractice-policies",
            payload, headers,
        )

    def list_malpractice_policies(self, clinician_id, headers, params=None):
        return self._request(
            "GET", f"/network/clinicians/{clinician_id}/malpractice-policies",
            params, headers,
        )

    # ─── Payer ─────────────────────────────────────────
    def create_payer(self, payload, headers):
        return self._request("POST", "/network/payers", payload, headers)

    def list_payers(self, headers, params=None):
        return self._request("GET", "/network/payers", params, headers)

    def get_payer(self, payer_id, headers):
        return self._request("GET", f"/network/payers/{payer_id}", headers=headers)

    def patch_payer(self, payer_id, payload, headers):
        return self._request("PATCH", f"/network/payers/{payer_id}", payload, headers)

    # ─── PayerRate ─────────────────────────────────────
    def create_payer_rate(self, payer_id, payload, headers):
        return self._request("POST", f"/network/payers/{payer_id}/rates", payload, headers)

    def list_payer_rates(self, payer_id, headers, params=None):
        return self._request("GET", f"/network/payers/{payer_id}/rates", params, headers)

    # ─── PayerEnrollment ───────────────────────────────
    def create_payer_enrollment(self, payload, headers):
        return self._request("POST", "/network/payer-enrollments", payload, headers)

    def list_payer_enrollments(self, headers, params=None):
        return self._request("GET", "/network/payer-enrollments", params, headers)

    def get_payer_enrollment(self, enrollment_id, headers):
        return self._request(
            "GET", f"/network/payer-enrollments/{enrollment_id}", headers=headers
        )

    def activate_payer_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/network/payer-enrollments/{enrollment_id}/activate", {}, headers
        )

    def reject_payer_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/network/payer-enrollments/{enrollment_id}/reject", {}, headers
        )

    def suspend_payer_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/network/payer-enrollments/{enrollment_id}/suspend", {}, headers
        )

    def reinstate_payer_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/network/payer-enrollments/{enrollment_id}/reinstate", {}, headers
        )

    def terminate_payer_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/network/payer-enrollments/{enrollment_id}/terminate", {}, headers
        )

    # ─── PatientClient ─────────────────────────────────
    def create_patient(self, payload, headers):
        return self._request("POST", "/network/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/network/patients", params, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/network/patients/{patient_id}", headers=headers)

    def match_patient(self, patient_id, payload, headers):
        return self._request("POST", f"/network/patients/{patient_id}/match", payload, headers)

    # ─── BenefitVerification ───────────────────────────
    def create_verification(self, patient_id, payload, headers):
        return self._request(
            "POST", f"/network/patients/{patient_id}/verification", payload, headers
        )

    def list_verifications(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/network/patients/{patient_id}/verification", params, headers
        )

    # ─── Session ───────────────────────────────────────
    def create_session(self, payload, headers):
        return self._request("POST", "/network/sessions", payload, headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/network/sessions", params, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/network/sessions/{session_id}", headers=headers)

    def schedule_session(self, session_id, headers):
        return self._request("POST", f"/network/sessions/{session_id}/schedule", {}, headers)

    def complete_session(self, session_id, headers):
        return self._request("POST", f"/network/sessions/{session_id}/complete", {}, headers)

    def reopen_session(self, session_id, headers):
        return self._request("POST", f"/network/sessions/{session_id}/reopen", {}, headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/network/sessions/{session_id}/cancel", {}, headers)

    def reschedule_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"/network/sessions/{session_id}/reschedule", payload, headers
        )

    def list_patient_sessions(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/network/patients/{patient_id}/sessions", params, headers
        )

    # ─── SessionNote ───────────────────────────────────
    def create_session_note(self, session_id, payload, headers):
        return self._request("POST", f"/network/sessions/{session_id}/notes", payload, headers)

    def list_session_notes(self, session_id, headers, params=None):
        return self._request(
            "GET", f"/network/sessions/{session_id}/notes", params, headers
        )

    def sign_session_note(self, session_id, note_id, headers):
        return self._request(
            "POST", f"/network/sessions/{session_id}/notes/{note_id}/sign", {}, headers
        )

    # ─── Claim ─────────────────────────────────────────
    def create_claim(self, payload, headers):
        return self._request("POST", "/network/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/network/claims", params, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/network/claims/{claim_id}", headers=headers)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/network/claims/{claim_id}/adjudicate", payload, headers)

    def resubmit_claim(self, claim_id, headers):
        return self._request("POST", f"/network/claims/{claim_id}/resubmit", {}, headers)

    def decide_reprocessing(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/network/claims/{claim_id}/decide-reprocessing", payload, headers
        )

    def write_off_claim(self, claim_id, headers):
        return self._request("POST", f"/network/claims/{claim_id}/write-off", {}, headers)

    def get_claim_payout_line(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/network/claims/{claim_id}/payout-line", params, headers
        )

    # ─── PayoutBatch / PayoutLine ──────────────────────
    def create_payout_batch(self, payload, headers):
        return self._request("POST", "/network/payout-batches", payload, headers)

    def list_payout_batches(self, headers, params=None):
        return self._request("GET", "/network/payout-batches", params, headers)

    def get_payout_batch(self, batch_id, headers):
        return self._request("GET", f"/network/payout-batches/{batch_id}", headers=headers)

    def lock_payout_batch(self, batch_id, headers):
        return self._request("POST", f"/network/payout-batches/{batch_id}/lock", {}, headers)

    def pay_payout_batch(self, batch_id, headers):
        return self._request("POST", f"/network/payout-batches/{batch_id}/pay", {}, headers)

    def reconcile_payout_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/network/payout-batches/{batch_id}/reconcile", {}, headers
        )

    def supersede_payout_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/network/payout-batches/{batch_id}/supersede", payload, headers
        )

    def list_payout_batch_lines(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"/network/payout-batches/{batch_id}/lines", params, headers
        )

    def list_clinician_payout_lines(self, clinician_id, headers, params=None):
        return self._request(
            "GET", f"/network/clinicians/{clinician_id}/payout-lines", params, headers
        )

    # ─── ContinuityPlan ────────────────────────────────
    def create_continuity_plan(self, payload, headers):
        return self._request("POST", "/network/continuity-plans", payload, headers)

    def list_continuity_plans(self, headers, params=None):
        return self._request("GET", "/network/continuity-plans", params, headers)

    def get_continuity_plan(self, plan_id, headers):
        return self._request("GET", f"/network/continuity-plans/{plan_id}", headers=headers)

    def assign_continuity_successor(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/network/continuity-plans/{plan_id}/successor", payload, headers
        )

    def accept_continuity_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/network/continuity-plans/{plan_id}/accept", {}, headers
        )

    def decline_continuity_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/network/continuity-plans/{plan_id}/decline", {}, headers
        )

    def complete_continuity_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/network/continuity-plans/{plan_id}/complete", {}, headers
        )

    def list_clinician_continuity_plans(self, clinician_id, headers, params=None):
        return self._request(
            "GET", f"/network/clinicians/{clinician_id}/continuity-plans", params, headers
        )

    def list_patient_continuity_plans(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/network/patients/{patient_id}/continuity-plans", params, headers
        )

    def list_payer_enrollments_for_payer(self, payer_id, headers, params=None):
        return self._request(
            "GET", f"/network/payers/{payer_id}/payer-enrollments", params, headers
        )


api_client = ApiClient()