"""API client: one method per endpoint on the HTTP contract (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── NetworkParticipant ───────────────────────────
    def create_participant(self, payload, headers):
        return self._request("POST", "/network/participants", payload, headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/network/participants", headers=headers, params=params)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/network/participants/{participant_id}", headers=headers)

    def start_certification(self, participant_id, headers, payload=None):
        return self._request(
            "POST", f"/network/participants/{participant_id}/certification/start",
            payload if payload is not None else {}, headers,
        )

    def record_certification_test(self, participant_id, payload, headers):
        return self._request(
            "POST", f"/network/participants/{participant_id}/certification/tests",
            payload, headers,
        )

    def certify_participant(self, participant_id, expected_participant_version, headers):
        return self._request(
            "POST", f"/network/participants/{participant_id}/certify",
            {"expected_participant_version": expected_participant_version}, headers,
        )

    def suspend_participant(self, participant_id, headers):
        return self._request(
            "POST", f"/network/participants/{participant_id}/suspend", {}, headers
        )

    def get_delivery_reachability(self, participant_id, headers):
        return self._request(
            "GET", f"/network/participants/{participant_id}/delivery-reachability",
            headers=headers,
        )

    def list_participant_endpoints(self, participant_id, headers, params=None):
        return self._request(
            "GET", f"/network/participants/{participant_id}/endpoints",
            headers=headers, params=params,
        )

    def list_participant_patients(self, participant_id, headers, params=None):
        return self._request(
            "GET", f"/network/participants/{participant_id}/patients",
            headers=headers, params=params,
        )

    def list_participant_fee_entries(self, participant_id, headers, params=None):
        return self._request(
            "GET", f"/network/participants/{participant_id}/fee-entries",
            headers=headers, params=params,
        )

    # ─── DirectoryEndpoint ────────────────────────────
    def create_endpoint(self, participant_id, payload, headers):
        return self._request(
            "POST", f"/network/participants/{participant_id}/endpoints", payload, headers
        )

    def list_endpoints(self, headers, params=None):
        return self._request("GET", "/network/directory-endpoints", headers=headers, params=params)

    def get_endpoint(self, endpoint_id, headers):
        return self._request("GET", f"/network/directory-endpoints/{endpoint_id}", headers=headers)

    def reactivate_endpoint(self, endpoint_id, headers):
        return self._request(
            "POST", f"/network/directory-endpoints/{endpoint_id}/reactivate", {}, headers
        )

    def disable_endpoint(self, endpoint_id, headers):
        return self._request(
            "POST", f"/network/directory-endpoints/{endpoint_id}/disable", {}, headers
        )

    # ─── Patient ──────────────────────────────────────
    def create_patient(self, payload, headers):
        return self._request("POST", "/network/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/network/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/network/patients/{patient_id}", headers=headers)

    def grant_consent(self, patient_id, payload, headers):
        return self._request("POST", f"/network/patients/{patient_id}/consents", payload, headers)

    def revoke_consents(self, patient_id, headers):
        return self._request(
            "POST", f"/network/patients/{patient_id}/consents/revoke", {}, headers
        )

    def list_consents(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/network/patients/{patient_id}/consents", headers=headers, params=params
        )

    def list_patient_history_records(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/network/patients/{patient_id}/history-records",
            headers=headers, params=params,
        )

    def list_patient_history_batches(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/network/patients/{patient_id}/history-batches",
            headers=headers, params=params,
        )

    def list_patient_prescriptions(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/network/patients/{patient_id}/prescriptions",
            headers=headers, params=params,
        )

    def list_patient_benefit_checks(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/network/patients/{patient_id}/benefit-checks",
            headers=headers, params=params,
        )

    # ─── PatientConsent ───────────────────────────────
    def get_consent(self, consent_id, headers):
        return self._request("GET", f"/network/consents/{consent_id}", headers=headers)

    # ─── MedicationHistoryRecord ──────────────────────
    def create_history_record(self, patient_id, payload, headers):
        return self._request(
            "POST", f"/network/patients/{patient_id}/history-records", payload, headers
        )

    def list_history_records(self, headers, params=None):
        return self._request("GET", "/network/history-records", headers=headers, params=params)

    def get_history_record(self, record_id, headers):
        return self._request("GET", f"/network/history-records/{record_id}", headers=headers)

    def list_batch_history_records(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"/network/medication-history/batches/{batch_id}/history-records",
            headers=headers, params=params,
        )

    # ─── MedicationHistoryBatch ───────────────────────
    def create_history_batch(self, payload, headers):
        return self._request("POST", "/network/medication-history/batches", payload, headers)

    def get_history_batch(self, batch_id, headers):
        return self._request(
            "GET", f"/network/medication-history/batches/{batch_id}", headers=headers
        )

    def aggregate_history_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/network/medication-history/batches/{batch_id}/aggregate", {}, headers
        )

    # ─── Prescription ─────────────────────────────────
    def create_prescription(self, payload, headers):
        return self._request("POST", "/network/prescriptions", payload, headers)

    def list_prescriptions(self, headers, params=None):
        return self._request("GET", "/network/prescriptions", headers=headers, params=params)

    def get_prescription(self, prescription_id, headers):
        return self._request("GET", f"/network/prescriptions/{prescription_id}", headers=headers)

    def list_attempts(self, prescription_id, headers, params=None):
        return self._request(
            "GET", f"/network/prescriptions/{prescription_id}/attempts",
            headers=headers, params=params,
        )

    def list_signing_sessions(self, prescription_id, headers, params=None):
        return self._request(
            "GET", f"/network/prescriptions/{prescription_id}/signing-sessions",
            headers=headers, params=params,
        )

    def get_signature_session(self, prescription_id, headers):
        return self._request(
            "GET", f"/network/prescriptions/{prescription_id}/signature-session", headers=headers
        )

    def list_prescription_benefit_checks(self, prescription_id, headers, params=None):
        return self._request(
            "GET", f"/network/prescriptions/{prescription_id}/benefit-checks",
            headers=headers, params=params,
        )

    def get_active_attempt(self, prescription_id, headers):
        return self._request(
            "GET", f"/network/prescriptions/{prescription_id}/active-attempt", headers=headers
        )

    def get_routed_endpoint(self, prescription_id, headers):
        return self._request(
            "GET", f"/network/prescriptions/{prescription_id}/routed-endpoint", headers=headers
        )

    def sign_prescription(self, prescription_id, signing_session_id, headers):
        return self._request(
            "POST", f"/network/prescriptions/{prescription_id}/sign",
            {"signing_session_id": signing_session_id}, headers,
        )

    def route_prescription(self, prescription_id, expected_prescription_version, headers):
        return self._request(
            "POST", f"/network/prescriptions/{prescription_id}/route",
            {"expected_prescription_version": expected_prescription_version}, headers,
        )

    def route_fallback(self, prescription_id, headers):
        return self._request(
            "POST", f"/network/prescriptions/{prescription_id}/route-fallback", {}, headers
        )

    def cancel_prescription(self, prescription_id, headers):
        return self._request(
            "POST", f"/network/prescriptions/{prescription_id}/cancel", {}, headers
        )

    def create_fallback_attempt(self, prescription_id, channel, headers):
        return self._request(
            "POST", f"/network/prescriptions/{prescription_id}/fallback-attempts",
            {"channel": channel}, headers,
        )

    # ─── SigningSession ───────────────────────────────
    def create_signing_session(self, prescription_id, headers):
        return self._request(
            "POST", "/network/signing-sessions", {"prescription_id": prescription_id}, headers
        )

    def list_signing_sessions_all(self, headers, params=None):
        return self._request("GET", "/network/signing-sessions", headers=headers, params=params)

    def get_signing_session(self, session_id, headers):
        return self._request("GET", f"/network/signing-sessions/{session_id}", headers=headers)

    def identity_proof(self, session_id, outcome, headers):
        return self._request(
            "POST", f"/network/signing-sessions/{session_id}/identity-proof",
            {"outcome": outcome}, headers,
        )

    def request_otp(self, session_id, headers):
        return self._request(
            "POST", f"/network/signing-sessions/{session_id}/request-otp", {}, headers
        )

    def verify_otp(self, session_id, otp_code, headers):
        return self._request(
            "POST", f"/network/signing-sessions/{session_id}/verify-otp",
            {"otp_code": otp_code}, headers,
        )

    def abandon_signing_session(self, session_id, headers):
        return self._request(
            "POST", f"/network/signing-sessions/{session_id}/abandon", {}, headers
        )

    # ─── RoutingAttempt ───────────────────────────────
    def get_attempt(self, attempt_id, headers):
        return self._request("GET", f"/network/routing-attempts/{attempt_id}", headers=headers)

    def get_attempt_prescriptions(self, attempt_id, headers):
        return self._request(
            "GET", f"/network/routing-attempts/{attempt_id}/prescriptions", headers=headers
        )

    def list_routing_attempts(self, headers, params=None):
        return self._request("GET", "/network/routing-attempts", headers=headers, params=params)

    def report_acknowledged(self, attempt_id, headers):
        return self._request(
            "POST", f"/network/routing-attempts/{attempt_id}/report-acknowledged", {}, headers
        )

    def report_undeliverable(self, attempt_id, failure_code, headers):
        return self._request(
            "POST", f"/network/routing-attempts/{attempt_id}/report-undeliverable",
            {"failure_code": failure_code}, headers,
        )

    def report_rejected(self, attempt_id, failure_code, headers, error_code_returned=None):
        payload = {"failure_code": failure_code}
        if error_code_returned is not None:
            payload["error_code_returned"] = error_code_returned
        return self._request(
            "POST", f"/network/routing-attempts/{attempt_id}/report-rejected", payload, headers
        )

    def report_fallback(self, attempt_id, outcome, headers, failure_code=None):
        payload = {"outcome": outcome}
        if failure_code is not None:
            payload["failure_code"] = failure_code
        return self._request(
            "POST", f"/network/routing-attempts/{attempt_id}/report-fallback", payload, headers
        )

    # ─── BenefitCheck ─────────────────────────────────
    def create_benefit_check(self, payload, headers):
        return self._request("POST", "/network/benefit-checks", payload, headers)

    def list_benefit_checks(self, headers, params=None):
        return self._request("GET", "/network/benefit-checks", headers=headers, params=params)

    def get_benefit_check(self, check_id, headers):
        return self._request("GET", f"/network/benefit-checks/{check_id}", headers=headers)

    def evaluate_benefit_check(self, check_id, headers):
        return self._request(
            "POST", f"/network/benefit-checks/{check_id}/evaluate", {}, headers
        )

    def complete_benefit_check(self, check_id, headers):
        return self._request(
            "POST", f"/network/benefit-checks/{check_id}/complete", {}, headers
        )

    # ─── TransactionFeeEntry ──────────────────────────
    def post_transaction_fee(self, payload, headers):
        return self._request("POST", "/network/transaction-fees", payload, headers)

    def list_transaction_fees(self, headers, params=None):
        return self._request("GET", "/network/transaction-fees", headers=headers, params=params)

    def get_transaction_fee(self, entry_id, headers):
        return self._request("GET", f"/network/transaction-fees/{entry_id}", headers=headers)

    def get_fee_reversal(self, entry_id, headers):
        return self._request(
            "GET", f"/network/transaction-fees/{entry_id}/reversal", headers=headers
        )

    def reverse_transaction_fee(self, entry_id, expected_participant_version, headers):
        return self._request(
            "POST", f"/network/transaction-fees/{entry_id}/reverse",
            {"expected_participant_version": expected_participant_version}, headers,
        )

    # ─── Network metadata & test-driving ──────────────
    def get_network_metadata(self, headers):
        return self._request("GET", "/network/", headers=headers)

    def set_current_utc(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def advance_clock(self, minutes, headers):
        return self._request("POST", "/_test/advance_clock", {"minutes": minutes}, headers)


api_client = ApiClient()