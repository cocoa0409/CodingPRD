"""API client: one method per endpoint in the PRD endpoint table.

Every path is rooted at the `/voip` prefix except the logical-clock endpoint,
which the PRD roots at `/_clock/set_current_utc`.
"""
from prd_bench_local_runner.testing import GenericApiClient

ROOT = "/voip"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Accounts
    # ------------------------------------------------------------------
    def create_account(self, payload, headers):
        return self._request("POST", f"{ROOT}/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"{ROOT}/accounts/{account_id}", headers=headers)

    # ------------------------------------------------------------------
    # Carriers
    # ------------------------------------------------------------------
    def create_carrier(self, payload, headers):
        return self._request("POST", f"{ROOT}/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"{ROOT}/carriers/{carrier_id}", headers=headers)

    # ------------------------------------------------------------------
    # Jurisdictions
    # ------------------------------------------------------------------
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", f"{ROOT}/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request(
            "GET", f"{ROOT}/jurisdictions/{jurisdiction_id}", headers=headers)

    def create_remittance_run(self, jurisdiction_id, payload, headers):
        return self._request(
            "POST", f"{ROOT}/jurisdictions/{jurisdiction_id}/remittance-runs",
            payload, headers)

    # ------------------------------------------------------------------
    # Number blocks and phone numbers
    # ------------------------------------------------------------------
    def create_number_block(self, payload, headers):
        return self._request("POST", f"{ROOT}/number-blocks", payload, headers)

    def get_number_block(self, block_id, headers):
        return self._request("GET", f"{ROOT}/number-blocks/{block_id}", headers=headers)

    def list_number_blocks(self, headers, params=None):
        return self._request("GET", f"{ROOT}/number-blocks", headers=headers, params=params)

    def mint_phone_number(self, block_id, payload, headers):
        return self._request(
            "POST", f"{ROOT}/number-blocks/{block_id}/phone-numbers", payload, headers)

    def get_phone_number(self, number_id, headers):
        return self._request("GET", f"{ROOT}/phone-numbers/{number_id}", headers=headers)

    def list_phone_numbers(self, headers, params=None):
        return self._request("GET", f"{ROOT}/phone-numbers", headers=headers, params=params)

    def release_phone_number(self, number_id, headers):
        return self._request(
            "POST", f"{ROOT}/phone-numbers/{number_id}/release", {}, headers)

    def create_reclamation_run(self, block_id, headers):
        return self._request(
            "POST", f"{ROOT}/number-blocks/{block_id}/reclamation-runs", {}, headers)

    # ------------------------------------------------------------------
    # Number reservations
    # ------------------------------------------------------------------
    def create_number_reservation(self, payload, headers):
        return self._request("POST", f"{ROOT}/number-reservations", payload, headers)

    def get_number_reservation(self, reservation_id, headers):
        return self._request(
            "GET", f"{ROOT}/number-reservations/{reservation_id}", headers=headers)

    def list_number_reservations(self, headers, params=None):
        return self._request(
            "GET", f"{ROOT}/number-reservations", headers=headers, params=params)

    def release_number_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"{ROOT}/number-reservations/{reservation_id}/release", {}, headers)

    # ------------------------------------------------------------------
    # Port requests
    # ------------------------------------------------------------------
    def create_port_request(self, payload, headers):
        return self._request("POST", f"{ROOT}/port-requests", payload, headers)

    def get_port_request(self, port_request_id, headers):
        return self._request(
            "GET", f"{ROOT}/port-requests/{port_request_id}", headers=headers)

    def list_port_requests(self, headers, params=None):
        return self._request("GET", f"{ROOT}/port-requests", headers=headers, params=params)

    def create_csr_snapshot(self, port_request_id, payload, headers):
        return self._request(
            "POST", f"{ROOT}/port-requests/{port_request_id}/csr-snapshots",
            payload, headers)

    def list_csr_snapshots(self, port_request_id, headers, params=None):
        return self._request(
            "GET", f"{ROOT}/port-requests/{port_request_id}/csr-snapshots",
            headers=headers, params=params)

    def resubmit_port_request(self, port_request_id, payload, headers):
        return self._request(
            "POST", f"{ROOT}/port-requests/{port_request_id}/resubmit", payload, headers)

    def reject_port_request(self, port_request_id, payload, headers):
        return self._request(
            "POST", f"{ROOT}/port-requests/{port_request_id}/reject", payload, headers)

    def cancel_port_request(self, port_request_id, payload, headers):
        return self._request(
            "POST", f"{ROOT}/port-requests/{port_request_id}/cancel", payload, headers)

    def schedule_port_request(self, port_request_id, payload, headers):
        return self._request(
            "POST", f"{ROOT}/port-requests/{port_request_id}/schedule", payload, headers)

    def complete_cutover(self, port_request_id, headers):
        return self._request(
            "POST", f"{ROOT}/port-requests/{port_request_id}/complete-cutover",
            {}, headers)

    # ------------------------------------------------------------------
    # Cutover slots
    # ------------------------------------------------------------------
    def create_cutover_slot(self, payload, headers):
        return self._request("POST", f"{ROOT}/cutover-slots", payload, headers)

    def get_cutover_slot(self, slot_id, headers):
        return self._request("GET", f"{ROOT}/cutover-slots/{slot_id}", headers=headers)

    def list_cutover_slots(self, headers, params=None):
        return self._request("GET", f"{ROOT}/cutover-slots", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Temporary bridges
    # ------------------------------------------------------------------
    def create_temporary_bridge(self, payload, headers):
        return self._request("POST", f"{ROOT}/temporary-bridges", payload, headers)

    def activate_temporary_bridge(self, bridge_id, headers):
        return self._request(
            "POST", f"{ROOT}/temporary-bridges/{bridge_id}/activate", {}, headers)

    def get_temporary_bridge(self, bridge_id, headers):
        return self._request(
            "GET", f"{ROOT}/temporary-bridges/{bridge_id}", headers=headers)

    def list_temporary_bridges(self, headers, params=None):
        return self._request(
            "GET", f"{ROOT}/temporary-bridges", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------
    def create_device(self, payload, headers):
        return self._request("POST", f"{ROOT}/devices", payload, headers)

    def get_device(self, device_id, headers):
        return self._request("GET", f"{ROOT}/devices/{device_id}", headers=headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", f"{ROOT}/devices", headers=headers, params=params)

    def create_network_report(self, device_id, payload, headers):
        return self._request(
            "POST", f"{ROOT}/devices/{device_id}/network-reports", payload, headers)

    def create_call_attempt(self, device_id, payload, headers):
        return self._request(
            "POST", f"{ROOT}/devices/{device_id}/call-attempts", payload, headers)

    def list_call_attempts(self, device_id, headers, params=None):
        return self._request(
            "GET", f"{ROOT}/devices/{device_id}/call-attempts",
            headers=headers, params=params)

    def create_calling_restriction(self, device_id, payload, headers):
        return self._request(
            "POST", f"{ROOT}/devices/{device_id}/calling-restrictions", payload, headers)

    # ------------------------------------------------------------------
    # E911 registrations
    # ------------------------------------------------------------------
    def create_e911_registration(self, payload, headers):
        return self._request("POST", f"{ROOT}/e911-registrations", payload, headers)

    def get_e911_registration(self, registration_id, headers):
        return self._request(
            "GET", f"{ROOT}/e911-registrations/{registration_id}", headers=headers)

    def list_e911_registrations(self, headers, params=None):
        return self._request(
            "GET", f"{ROOT}/e911-registrations", headers=headers, params=params)

    def verify_e911_registration(self, registration_id, payload, headers):
        return self._request(
            "POST", f"{ROOT}/e911-registrations/{registration_id}/verify",
            payload, headers)

    # ------------------------------------------------------------------
    # Fee assessments
    # ------------------------------------------------------------------
    def create_fee_assessment(self, payload, headers):
        return self._request("POST", f"{ROOT}/fee-assessments", payload, headers)

    def void_fee_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"{ROOT}/fee-assessments/{assessment_id}/void", payload, headers)

    def get_fee_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"{ROOT}/fee-assessments/{assessment_id}", headers=headers)

    def list_fee_assessments(self, headers, params=None):
        return self._request(
            "GET", f"{ROOT}/fee-assessments", headers=headers, params=params)


api_client = ApiClient()
