"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Board selector ───────────────────────────────────────────────────────
    def get_board(self, headers, params=None):
        return self._request("GET", "/network/load-offers/board", headers=headers, params=params)

    # ─── Test-driving capabilities ────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_advance_post(self, payload, headers):
        return self._request("POST", "/_events/run_advance_post", payload, headers)

    def run_period_close(self, payload, headers):
        return self._request("POST", "/_events/run_period_close", payload, headers)

    # ─── Agents ───────────────────────────────────────────────────────────────
    def create_agent(self, payload, headers):
        return self._request("POST", "/network/agents", payload, headers)

    def list_agents(self, headers, params=None):
        return self._request("GET", "/network/agents", headers=headers, params=params)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"/network/agents/{agent_id}", headers=headers)

    def activate_agent(self, agent_id, headers, payload=None):
        return self._request("POST", f"/network/agents/{agent_id}/activate", payload or {}, headers)

    def suspend_agent(self, agent_id, payload, headers):
        return self._request("POST", f"/network/agents/{agent_id}/suspend", payload, headers)

    def reinstate_agent(self, agent_id, headers, payload=None):
        return self._request("POST", f"/network/agents/{agent_id}/reinstate", payload or {}, headers)

    def terminate_agent(self, agent_id, payload, headers):
        return self._request("POST", f"/network/agents/{agent_id}/terminate", payload, headers)

    def get_agent_settlement_summary(self, agent_id, headers, params=None):
        return self._request(
            "GET", f"/network/agents/{agent_id}/settlement-summary", headers=headers, params=params
        )

    def evaluate_per_load_tier(self, agent_id, payload, headers):
        return self._request(
            "POST", f"/network/agents/{agent_id}/per-load-settlement-tier", payload, headers
        )

    # ─── Capacity owners ──────────────────────────────────────────────────────
    def create_capacity_owner(self, payload, headers):
        return self._request("POST", "/network/capacity-owners", payload, headers)

    def list_capacity_owners(self, headers, params=None):
        return self._request("GET", "/network/capacity-owners", headers=headers, params=params)

    def get_capacity_owner(self, capacity_owner_id, headers):
        return self._request("GET", f"/network/capacity-owners/{capacity_owner_id}", headers=headers)

    def qualify_capacity_owner(self, capacity_owner_id, payload, headers):
        return self._request(
            "POST", f"/network/capacity-owners/{capacity_owner_id}/qualify", payload, headers
        )

    def deep_clone_capacity_owner(self, capacity_owner_id, payload, headers):
        return self._request(
            "POST", f"/network/capacity-owners/{capacity_owner_id}/deep-clone", payload, headers
        )

    def suspend_capacity_owner(self, capacity_owner_id, payload, headers):
        return self._request(
            "POST", f"/network/capacity-owners/{capacity_owner_id}/suspend", payload, headers
        )

    def reinstate_capacity_owner(self, capacity_owner_id, payload, headers):
        return self._request(
            "POST", f"/network/capacity-owners/{capacity_owner_id}/reinstate", payload, headers
        )

    def decertify_capacity_owner(self, capacity_owner_id, payload, headers):
        return self._request(
            "POST", f"/network/capacity-owners/{capacity_owner_id}/decertify", payload, headers
        )

    # ─── Equipment ────────────────────────────────────────────────────────────
    def create_equipment(self, payload, headers):
        return self._request("POST", "/network/equipment", payload, headers)

    def list_capacity_owner_equipment(self, capacity_owner_id, headers, params=None):
        return self._request(
            "GET", f"/network/capacity-owners/{capacity_owner_id}/equipment", headers=headers, params=params
        )

    def list_equipment(self, headers, params=None):
        return self._request("GET", "/network/equipment", headers=headers, params=params)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/network/equipment/{equipment_id}", headers=headers)

    def record_inspection(self, equipment_id, payload, headers):
        return self._request(
            "POST", f"/network/equipment/{equipment_id}/record-inspection", payload, headers
        )

    def place_equipment_out_of_service(self, equipment_id, payload, headers):
        return self._request(
            "POST", f"/network/equipment/{equipment_id}/place-out-of-service", payload, headers
        )

    def retire_equipment(self, equipment_id, payload, headers):
        return self._request("POST", f"/network/equipment/{equipment_id}/retire", payload, headers)

    # ─── Compliance documents ─────────────────────────────────────────────────
    def create_compliance_document(self, payload, headers):
        return self._request("POST", "/network/compliance-documents", payload, headers)

    def list_compliance_documents(self, headers, params=None):
        return self._request("GET", "/network/compliance-documents", headers=headers, params=params)

    def list_capacity_owner_documents(self, capacity_owner_id, headers, params=None):
        return self._request(
            "GET",
            f"/network/capacity-owners/{capacity_owner_id}/compliance-documents",
            headers=headers,
            params=params,
        )

    def get_compliance_document(self, document_id, headers):
        return self._request("GET", f"/network/compliance-documents/{document_id}", headers=headers)

    def verify_compliance_document(self, document_id, payload, headers):
        return self._request(
            "POST", f"/network/compliance-documents/{document_id}/verify", payload, headers
        )

    # ─── Escrow transactions ──────────────────────────────────────────────────
    def create_escrow_transaction(self, payload, headers):
        return self._request("POST", "/network/escrow-transactions", payload, headers)

    def list_escrow_transactions(self, headers, params=None):
        return self._request("GET", "/network/escrow-transactions", headers=headers, params=params)

    def list_capacity_owner_ledger(self, capacity_owner_id, headers, params=None):
        return self._request(
            "GET",
            f"/network/capacity-owners/{capacity_owner_id}/escrow-transactions",
            headers=headers,
            params=params,
        )

    def get_escrow_transaction(self, transaction_id, headers):
        return self._request("GET", f"/network/escrow-transactions/{transaction_id}", headers=headers)

    def reverse_escrow_transaction(self, transaction_id, payload, headers):
        return self._request(
            "POST", f"/network/escrow-transactions/{transaction_id}/reverse", payload, headers
        )

    # ─── Customer accounts ────────────────────────────────────────────────────
    def create_customer_account(self, payload, headers):
        return self._request("POST", "/network/customer-accounts", payload, headers)

    def list_customer_accounts(self, headers, params=None):
        return self._request("GET", "/network/customer-accounts", headers=headers, params=params)

    def list_agent_customer_accounts(self, agent_id, headers, params=None):
        return self._request(
            "GET", f"/network/agents/{agent_id}/customer-accounts", headers=headers, params=params
        )

    def get_customer_account(self, customer_account_id, headers):
        return self._request(
            "GET", f"/network/customer-accounts/{customer_account_id}", headers=headers
        )

    # ─── Loads ────────────────────────────────────────────────────────────────
    def create_load(self, payload, headers):
        return self._request("POST", "/network/loads", payload, headers)

    def list_loads(self, headers, params=None):
        return self._request("GET", "/network/loads", headers=headers, params=params)

    def list_agent_loads(self, agent_id, headers, params=None):
        return self._request("GET", f"/network/agents/{agent_id}/loads", headers=headers, params=params)

    def get_load(self, load_id, headers):
        return self._request("GET", f"/network/loads/{load_id}", headers=headers)

    def cancel_load(self, load_id, payload, headers):
        return self._request("POST", f"/network/loads/{load_id}/cancel", payload, headers)

    def evaluate_load_settlement(self, load_id, payload, headers):
        return self._request("POST", f"/network/loads/{load_id}/settlement", payload, headers)

    # ─── Load offers ──────────────────────────────────────────────────────────
    def create_load_offer(self, payload, headers):
        return self._request("POST", "/network/load-offers", payload, headers)

    def list_load_offers(self, headers, params=None):
        return self._request("GET", "/network/load-offers", headers=headers, params=params)

    def list_load_board_offers(self, load_id, headers, params=None):
        return self._request(
            "GET", f"/network/loads/{load_id}/load-offers", headers=headers, params=params
        )

    def get_load_offer(self, offer_id, headers):
        return self._request("GET", f"/network/load-offers/{offer_id}", headers=headers)

    def accept_load_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/network/load-offers/{offer_id}/accept", payload, headers)

    def decline_load_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/network/load-offers/{offer_id}/decline", payload, headers)

    def withdraw_load_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/network/load-offers/{offer_id}/withdraw", payload, headers)

    # ─── Trips ────────────────────────────────────────────────────────────────
    def create_trip(self, payload, headers):
        return self._request("POST", "/network/trips", payload, headers)

    def list_trips(self, headers, params=None):
        return self._request("GET", "/network/trips", headers=headers, params=params)

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"/network/trips/{trip_id}", headers=headers)

    def list_load_trips(self, load_id, headers, params=None):
        return self._request("GET", f"/network/loads/{load_id}/trips", headers=headers, params=params)

    def list_capacity_owner_trips(self, capacity_owner_id, headers, params=None):
        return self._request(
            "GET", f"/network/capacity-owners/{capacity_owner_id}/trips", headers=headers, params=params
        )

    def list_equipment_trips(self, equipment_id, headers, params=None):
        return self._request(
            "GET", f"/network/equipment/{equipment_id}/trips", headers=headers, params=params
        )

    def dispatch_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/network/trips/{trip_id}/dispatch", payload, headers)

    def complete_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/network/trips/{trip_id}/complete", payload, headers)

    def verify_pod(self, trip_id, payload, headers):
        return self._request("POST", f"/network/trips/{trip_id}/verify-pod", payload, headers)

    def abort_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/network/trips/{trip_id}/abort", payload, headers)

    # ─── Settlements ──────────────────────────────────────────────────────────
    def create_settlement(self, payload, headers):
        return self._request("POST", "/network/settlements", payload, headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/network/settlements", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/network/settlements/{settlement_id}", headers=headers)

    def list_trip_settlements(self, trip_id, headers, params=None):
        return self._request(
            "GET", f"/network/trips/{trip_id}/settlements", headers=headers, params=params
        )

    def list_agent_settlements(self, agent_id, headers, params=None):
        return self._request(
            "GET", f"/network/agents/{agent_id}/settlements", headers=headers, params=params
        )

    def list_capacity_owner_settlements(self, capacity_owner_id, headers, params=None):
        return self._request(
            "GET",
            f"/network/capacity-owners/{capacity_owner_id}/settlements",
            headers=headers,
            params=params,
        )

    def submit_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/network/settlements/{settlement_id}/submit", payload, headers)

    def approve_settlement(self, settlement_id, headers, payload=None):
        return self._request("POST", f"/network/settlements/{settlement_id}/approve", payload or {}, headers)

    def reject_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/network/settlements/{settlement_id}/reject", payload, headers)

    def settle_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/network/settlements/{settlement_id}/settle", payload, headers)

    def void_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/network/settlements/{settlement_id}/void", payload, headers)


api_client = ApiClient()