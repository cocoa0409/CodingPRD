"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin transport wrapper. Every method returns the raw response so tests
    can assert both the HTTP status and the envelope."""

    # ---- logical clock and operations surface -------------------------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def run_compliance_sweep(self, headers):
        return self._request("POST", "/_ops/run-compliance-sweep", {}, headers)

    # ---- DataBroker ---------------------------------------------------------
    def create_broker(self, payload, headers):
        return self._request("POST", "/brokers", payload, headers)

    def get_broker(self, broker_id, headers):
        return self._request("GET", f"/brokers/{broker_id}", headers=headers)

    def create_fee_deposit(self, broker_id, payload, headers):
        return self._request(
            "POST", f"/brokers/{broker_id}/fee-deposits", payload, headers
        )

    def list_audit_events(self, broker_id, headers, params=None):
        return self._request(
            "GET", f"/brokers/{broker_id}/audit-events", headers=headers, params=params
        )

    # ---- Registration -------------------------------------------------------
    def create_registration(self, payload, headers):
        return self._request("POST", "/registrations", payload, headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/registrations", headers=headers, params=params)

    def get_registration(self, registration_id, headers):
        return self._request(
            "GET", f"/registrations/{registration_id}", headers=headers
        )

    def create_disclosure(self, registration_id, payload, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/disclosures", payload, headers
        )

    def list_disclosures(self, registration_id, headers, params=None):
        return self._request(
            "GET",
            f"/registrations/{registration_id}/disclosures",
            headers=headers,
            params=params,
        )

    def submit_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/submit", {}, headers
        )

    def accept_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/accept", {}, headers
        )

    def reject_registration(self, registration_id, payload, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/reject", payload, headers
        )

    def withdraw_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/withdraw", {}, headers
        )

    # ---- Consumer -----------------------------------------------------------
    def create_consumer(self, payload, headers):
        return self._request("POST", "/consumers", payload, headers)

    def list_consumers(self, headers, params=None):
        return self._request("GET", "/consumers", headers=headers, params=params)

    def get_consumer(self, consumer_id, headers):
        return self._request("GET", f"/consumers/{consumer_id}", headers=headers)

    def record_consent_action(self, consumer_id, payload, headers):
        return self._request(
            "POST", f"/consumers/{consumer_id}/consent", payload, headers
        )

    def record_collection(self, consumer_id, payload, headers):
        return self._request(
            "POST", f"/consumers/{consumer_id}/collections", payload, headers
        )

    # ---- DeletionRequest ----------------------------------------------------
    def create_deletion_request(self, payload, headers):
        return self._request("POST", "/deletion-requests", payload, headers)

    def list_deletion_requests(self, headers, params=None):
        return self._request(
            "GET", "/deletion-requests", headers=headers, params=params
        )

    def get_deletion_request(self, request_id, headers):
        return self._request(
            "GET", f"/deletion-requests/{request_id}", headers=headers
        )

    def create_verification_attempt(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"/deletion-requests/{request_id}/verification-attempts",
            payload,
            headers,
        )

    def list_verification_attempts(self, request_id, headers, params=None):
        return self._request(
            "GET",
            f"/deletion-requests/{request_id}/verification-attempts",
            headers=headers,
            params=params,
        )

    def decide_verification(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"/deletion-requests/{request_id}/decide-verification",
            payload,
            headers,
        )

    def execute_deletion_request(self, request_id, headers):
        return self._request(
            "POST", f"/deletion-requests/{request_id}/execute", {}, headers
        )

    def deny_deletion_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/deletion-requests/{request_id}/deny", payload, headers
        )

    def withdraw_deletion_request(self, request_id, headers):
        return self._request(
            "POST", f"/deletion-requests/{request_id}/withdraw", {}, headers
        )

    # ---- PropagationTask ----------------------------------------------------
    def list_propagation_tasks(self, headers, params=None):
        return self._request(
            "GET", "/propagation-tasks", headers=headers, params=params
        )

    def get_propagation_task(self, task_id, headers):
        return self._request("GET", f"/propagation-tasks/{task_id}", headers=headers)

    def dispatch_propagation_task(self, task_id, headers):
        return self._request(
            "POST", f"/propagation-tasks/{task_id}/dispatch", {}, headers
        )

    def ack_propagation_task(self, task_id, headers):
        return self._request("POST", f"/propagation-tasks/{task_id}/ack", {}, headers)

    def fail_propagation_task(self, task_id, payload, headers):
        return self._request(
            "POST", f"/propagation-tasks/{task_id}/fail", payload, headers
        )

    def waive_propagation_task(self, task_id, payload, headers):
        return self._request(
            "POST", f"/propagation-tasks/{task_id}/waive", payload, headers
        )

    # ---- DownstreamRecipient ------------------------------------------------
    def create_downstream_recipient(self, payload, headers):
        return self._request("POST", "/downstream-recipients", payload, headers)

    def list_downstream_recipients(self, headers, params=None):
        return self._request(
            "GET", "/downstream-recipients", headers=headers, params=params
        )

    def get_downstream_recipient(self, recipient_id, headers):
        return self._request(
            "GET", f"/downstream-recipients/{recipient_id}", headers=headers
        )

    def set_recipient_status(self, recipient_id, payload, headers):
        return self._request(
            "POST", f"/downstream-recipients/{recipient_id}/status", payload, headers
        )

    # ---- SuppressionEntry ---------------------------------------------------
    def create_suppression_entry(self, payload, headers):
        return self._request("POST", "/suppression-entries", payload, headers)

    def list_suppression_entries(self, headers, params=None):
        return self._request(
            "GET", "/suppression-entries", headers=headers, params=params
        )

    def get_suppression_entry(self, entry_id, headers):
        return self._request("GET", f"/suppression-entries/{entry_id}", headers=headers)

    def lift_suppression_entry(self, entry_id, payload, headers):
        return self._request(
            "POST", f"/suppression-entries/{entry_id}/lift", payload, headers
        )

    # ---- OptOutSignal -------------------------------------------------------
    def create_opt_out_signal(self, payload, headers):
        return self._request("POST", "/opt-out-signals", payload, headers)

    def list_opt_out_signals(self, headers, params=None):
        return self._request("GET", "/opt-out-signals", headers=headers, params=params)

    def get_opt_out_signal(self, signal_id, headers):
        return self._request("GET", f"/opt-out-signals/{signal_id}", headers=headers)

    # ---- RegulatorInquiry ---------------------------------------------------
    def create_regulator_inquiry(self, payload, headers):
        return self._request("POST", "/regulator-inquiries", payload, headers)

    def list_regulator_inquiries(self, headers, params=None):
        return self._request(
            "GET", "/regulator-inquiries", headers=headers, params=params
        )

    def get_regulator_inquiry(self, inquiry_id, headers):
        return self._request(
            "GET", f"/regulator-inquiries/{inquiry_id}", headers=headers
        )

    def respond_to_inquiry(self, inquiry_id, payload, headers):
        return self._request(
            "POST", f"/regulator-inquiries/{inquiry_id}/respond", payload, headers
        )

    def close_inquiry(self, inquiry_id, headers):
        return self._request(
            "POST", f"/regulator-inquiries/{inquiry_id}/close", {}, headers
        )

    def escalate_inquiry(self, inquiry_id, payload, headers):
        return self._request(
            "POST", f"/regulator-inquiries/{inquiry_id}/escalate", payload, headers
        )


api_client = ApiClient()
