"""API client: one method per endpoint defined in the PRD (all under /ocean-billing)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/ocean-billing/_clock/set_current_utc", payload, headers)

    # --- CustomerAccount ---
    def create_customer_account(self, payload, headers):
        return self._request("POST", "/ocean-billing/customer-accounts", payload, headers)

    def list_customer_accounts(self, headers, params=None):
        return self._request("GET", "/ocean-billing/customer-accounts", headers=headers, params=params)

    def get_customer_account(self, account_id, headers):
        return self._request("GET", f"/ocean-billing/customer-accounts/{account_id}", headers=headers)

    def close_customer_account(self, account_id, headers):
        return self._request("POST", f"/ocean-billing/customer-accounts/{account_id}/close", {}, headers)

    # --- ServiceContract ---
    def create_service_contract(self, account_id, payload, headers):
        return self._request(
            "POST", f"/ocean-billing/customer-accounts/{account_id}/service-contracts", payload, headers
        )

    def list_service_contracts(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/ocean-billing/customer-accounts/{account_id}/service-contracts",
            headers=headers, params=params,
        )

    def get_service_contract(self, contract_id, headers):
        return self._request("GET", f"/ocean-billing/service-contracts/{contract_id}", headers=headers)

    def activate_service_contract(self, contract_id, headers):
        return self._request("POST", f"/ocean-billing/service-contracts/{contract_id}/activate", {}, headers)

    # --- Terminal / holidays / slots ---
    def create_terminal(self, payload, headers):
        return self._request("POST", "/ocean-billing/terminals", payload, headers)

    def list_terminals(self, headers, params=None):
        return self._request("GET", "/ocean-billing/terminals", headers=headers, params=params)

    def get_terminal(self, terminal_id, headers):
        return self._request("GET", f"/ocean-billing/terminals/{terminal_id}", headers=headers)

    def create_terminal_holiday(self, terminal_id, payload, headers):
        return self._request(
            "POST", f"/ocean-billing/terminals/{terminal_id}/holidays", payload, headers
        )

    def list_terminal_holidays(self, terminal_id, headers, params=None):
        return self._request(
            "GET", f"/ocean-billing/terminals/{terminal_id}/holidays", headers=headers, params=params
        )

    def create_appointment_slot(self, terminal_id, payload, headers):
        return self._request(
            "POST", f"/ocean-billing/terminals/{terminal_id}/appointment-slots", payload, headers
        )

    def list_appointment_slots(self, terminal_id, headers, params=None):
        return self._request(
            "GET", f"/ocean-billing/terminals/{terminal_id}/appointment-slots",
            headers=headers, params=params,
        )

    def get_appointment_slot(self, slot_id, headers):
        return self._request("GET", f"/ocean-billing/terminal-appointment-slots/{slot_id}", headers=headers)

    def release_appointment_slot(self, slot_id, headers):
        return self._request(
            "POST", f"/ocean-billing/terminal-appointment-slots/{slot_id}/release", {}, headers
        )

    # --- EquipmentReturnLocation ---
    def create_return_location(self, payload, headers):
        return self._request("POST", "/ocean-billing/return-locations", payload, headers)

    def list_return_locations(self, headers, params=None):
        return self._request("GET", "/ocean-billing/return-locations", headers=headers, params=params)

    def get_return_location(self, location_id, headers):
        return self._request("GET", f"/ocean-billing/return-locations/{location_id}", headers=headers)

    def set_return_location_status(self, location_id, payload, headers):
        return self._request(
            "POST", f"/ocean-billing/return-locations/{location_id}/set-status", payload, headers
        )

    # --- Container lifecycle ---
    def create_container(self, payload, headers):
        return self._request("POST", "/ocean-billing/containers", payload, headers)

    def list_containers(self, headers, params=None):
        return self._request("GET", "/ocean-billing/containers", headers=headers, params=params)

    def get_container(self, container_id, headers):
        return self._request("GET", f"/ocean-billing/containers/{container_id}", headers=headers)

    def list_container_accruals(self, container_id, headers, params=None):
        return self._request(
            "GET", f"/ocean-billing/containers/{container_id}/accruals", headers=headers, params=params
        )

    def mark_container_available(self, container_id, headers):
        return self._request("POST", f"/ocean-billing/containers/{container_id}/mark-available", {}, headers)

    def set_container_hold(self, container_id, payload, headers):
        return self._request("POST", f"/ocean-billing/containers/{container_id}/holds", payload, headers)

    def book_appointment(self, container_id, payload, headers):
        return self._request(
            "POST", f"/ocean-billing/containers/{container_id}/appointments", payload, headers
        )

    def cancel_appointment(self, container_id, booking_id, headers):
        return self._request(
            "POST",
            f"/ocean-billing/containers/{container_id}/appointments/{booking_id}/cancel",
            {}, headers,
        )

    def gate_out_container(self, container_id, payload, headers):
        return self._request("POST", f"/ocean-billing/containers/{container_id}/gate-out", payload, headers)

    def reassign_return_location(self, container_id, payload, headers):
        return self._request(
            "POST", f"/ocean-billing/containers/{container_id}/reassign-return-location", payload, headers
        )

    def return_empty_container(self, container_id, headers):
        return self._request("POST", f"/ocean-billing/containers/{container_id}/return-empty", {}, headers)

    def issue_invoice(self, container_id, headers):
        return self._request("POST", f"/ocean-billing/containers/{container_id}/issue-invoice", {}, headers)

    # --- Invoice ---
    def list_invoices(self, headers, params=None):
        return self._request("GET", "/ocean-billing/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/ocean-billing/invoices/{invoice_id}", headers=headers)

    def create_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"/ocean-billing/invoices/{invoice_id}/payments", payload, headers)

    def write_off_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/ocean-billing/invoices/{invoice_id}/write-off", payload, headers)

    def list_payments(self, invoice_id, headers, params=None):
        return self._request(
            "GET", f"/ocean-billing/invoices/{invoice_id}/payments", headers=headers, params=params
        )

    def list_invoice_credit_waivers(self, invoice_id, headers, params=None):
        return self._request(
            "GET", f"/ocean-billing/invoices/{invoice_id}/credit-waivers", headers=headers, params=params
        )

    # --- Disputes ---
    def create_dispute(self, invoice_id, payload, headers):
        return self._request("POST", f"/ocean-billing/invoices/{invoice_id}/disputes", payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/ocean-billing/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/ocean-billing/disputes/{dispute_id}", headers=headers)

    def get_evidence(self, evidence_id, headers):
        return self._request("GET", f"/ocean-billing/dispute-evidence/{evidence_id}", headers=headers)

    def list_all_evidence(self, headers, params=None):
        return self._request("GET", "/ocean-billing/dispute-evidence", headers=headers, params=params)

    def attach_evidence(self, dispute_id, payload, headers):
        return self._request("POST", f"/ocean-billing/disputes/{dispute_id}/evidence", payload, headers)

    def list_dispute_evidence(self, dispute_id, headers, params=None):
        return self._request(
            "GET", f"/ocean-billing/disputes/{dispute_id}/evidence", headers=headers, params=params
        )

    def start_dispute_review(self, dispute_id, headers):
        return self._request("POST", f"/ocean-billing/disputes/{dispute_id}/start-review", {}, headers)

    def return_dispute_to_queue(self, dispute_id, headers):
        return self._request("POST", f"/ocean-billing/disputes/{dispute_id}/return-to-queue", {}, headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/ocean-billing/disputes/{dispute_id}/resolve", payload, headers)

    def withdraw_dispute(self, dispute_id, headers):
        return self._request("POST", f"/ocean-billing/disputes/{dispute_id}/withdraw", {}, headers)

    def list_dispute_credit_waivers(self, dispute_id, headers, params=None):
        return self._request(
            "GET", f"/ocean-billing/disputes/{dispute_id}/credit-waivers", headers=headers, params=params
        )

    # --- Credit waivers (goodwill / non-dispute path) ---
    def propose_credit_waiver(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/ocean-billing/invoices/{invoice_id}/credit-waivers", payload, headers
        )

    def get_credit_waiver(self, waiver_id, headers):
        return self._request("GET", f"/ocean-billing/credit-waivers/{waiver_id}", headers=headers)

    def approve_credit_waiver(self, waiver_id, payload, headers):
        return self._request("POST", f"/ocean-billing/credit-waivers/{waiver_id}/approve", payload, headers)

    def reject_credit_waiver(self, waiver_id, headers):
        return self._request("POST", f"/ocean-billing/credit-waivers/{waiver_id}/reject", {}, headers)

    def reverse_credit_waiver(self, waiver_id, payload, headers):
        return self._request("POST", f"/ocean-billing/credit-waivers/{waiver_id}/reverse", payload, headers)


api_client = ApiClient()
