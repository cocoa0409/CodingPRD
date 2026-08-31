"""API client: one method per endpoint defined in the PRD.

Every path is mounted under /cash-vault.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/cash-vault"


class ApiClient(GenericApiClient):
    # ─── Logical clock ────────────────────────────────────────────────────

    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ─── Vault ────────────────────────────────────────────────────────────

    def create_vault(self, payload, headers):
        return self._request("POST", f"{PREFIX}/vaults", payload, headers)

    def get_vault(self, vault_id, headers):
        return self._request("GET", f"{PREFIX}/vaults/{vault_id}", headers=headers)

    def set_vault_posture(self, vault_id, payload, headers):
        return self._request("POST", f"{PREFIX}/vaults/{vault_id}/posture", payload, headers)

    def adjust_vault_inventory(self, vault_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/vaults/{vault_id}/inventory-adjustments", payload, headers
        )

    def list_vault_inventory(self, vault_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/vaults/{vault_id}/inventory", headers=headers, params=params
        )

    def get_cash_letter_reconciliation(self, vault_id, headers):
        return self._request(
            "GET", f"{PREFIX}/vaults/{vault_id}/cash-letter-reconciliation", headers=headers
        )

    # ─── CustomerAccount ──────────────────────────────────────────────────

    def create_customer_account(self, payload, headers):
        return self._request("POST", f"{PREFIX}/customer-accounts", payload, headers)

    def get_customer_account(self, account_id, headers):
        return self._request("GET", f"{PREFIX}/customer-accounts/{account_id}", headers=headers)

    def get_customer_statement(self, account_id, headers):
        return self._request(
            "GET", f"{PREFIX}/customer-accounts/{account_id}/statement", headers=headers
        )

    # ─── DepositTicket ────────────────────────────────────────────────────

    def create_deposit_ticket(self, payload, headers):
        return self._request("POST", f"{PREFIX}/deposit-tickets", payload, headers)

    def get_deposit_ticket(self, ticket_id, headers):
        return self._request("GET", f"{PREFIX}/deposit-tickets/{ticket_id}", headers=headers)

    def list_deposit_tickets(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/deposit-tickets", headers=headers, params=params)

    def verify_deposit_ticket(self, ticket_id, headers):
        return self._request("POST", f"{PREFIX}/deposit-tickets/{ticket_id}/verify", {}, headers)

    def extend_provisional_credit(self, ticket_id, headers):
        return self._request(
            "POST", f"{PREFIX}/deposit-tickets/{ticket_id}/provisional-credit", {}, headers
        )

    def reverse_provisional_credit(self, ticket_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/deposit-tickets/{ticket_id}/reverse-provisional-credit",
            payload,
            headers,
        )

    def hold_deposit_ticket(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/deposit-tickets/{ticket_id}/hold", payload, headers
        )

    def settle_deposit_ticket(self, ticket_id, headers):
        return self._request("POST", f"{PREFIX}/deposit-tickets/{ticket_id}/settle", {}, headers)

    # ─── SealedBag / CustodyEvent ─────────────────────────────────────────

    def create_sealed_bag(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sealed-bags", payload, headers)

    def get_sealed_bag(self, bag_id, headers):
        return self._request("GET", f"{PREFIX}/sealed-bags/{bag_id}", headers=headers)

    def list_sealed_bags(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sealed-bags", headers=headers, params=params)

    def create_custody_event(self, bag_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sealed-bags/{bag_id}/custody-events", payload, headers
        )

    def list_custody_events(self, bag_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/sealed-bags/{bag_id}/custody-events", headers=headers, params=params
        )

    # ─── CountingMachine ──────────────────────────────────────────────────

    def create_counting_machine(self, payload, headers):
        return self._request("POST", f"{PREFIX}/counting-machines", payload, headers)

    def get_counting_machine(self, machine_id, headers):
        return self._request("GET", f"{PREFIX}/counting-machines/{machine_id}", headers=headers)

    def list_counting_machines(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/counting-machines", headers=headers, params=params)

    # ─── CountSession / FitnessLot ────────────────────────────────────────

    def create_count_session(self, payload, headers):
        return self._request("POST", f"{PREFIX}/count-sessions", payload, headers)

    def get_count_session(self, session_id, headers):
        return self._request("GET", f"{PREFIX}/count-sessions/{session_id}", headers=headers)

    def list_count_sessions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/count-sessions", headers=headers, params=params)

    def start_count_session(self, session_id, headers):
        return self._request("POST", f"{PREFIX}/count-sessions/{session_id}/start", {}, headers)

    def complete_count_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/count-sessions/{session_id}/complete", payload, headers
        )

    def list_session_fitness_lots(self, session_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/count-sessions/{session_id}/fitness-lots",
            headers=headers,
            params=params,
        )

    # ─── CounterfeitReport ────────────────────────────────────────────────

    def create_counterfeit_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/counterfeit-reports", payload, headers)

    def get_counterfeit_report(self, report_id, headers):
        return self._request("GET", f"{PREFIX}/counterfeit-reports/{report_id}", headers=headers)

    def list_counterfeit_reports(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/counterfeit-reports", headers=headers, params=params
        )

    def submit_counterfeit_report(self, report_id, headers):
        return self._request(
            "POST", f"{PREFIX}/counterfeit-reports/{report_id}/submit", {}, headers
        )

    def return_counterfeit_report_for_correction(self, report_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/counterfeit-reports/{report_id}/return-for-correction",
            payload,
            headers,
        )

    def acknowledge_counterfeit_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/counterfeit-reports/{report_id}/acknowledge", payload, headers
        )

    # ─── DiscrepancyClaim ─────────────────────────────────────────────────

    def create_discrepancy_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/discrepancy-claims", payload, headers)

    def get_discrepancy_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/discrepancy-claims/{claim_id}", headers=headers)

    def list_discrepancy_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/discrepancy-claims", headers=headers, params=params)

    def request_claim_info(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/discrepancy-claims/{claim_id}/request-info", payload, headers
        )

    def resubmit_discrepancy_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/discrepancy-claims/{claim_id}/resubmit", payload, headers
        )

    def approve_discrepancy_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/discrepancy-claims/{claim_id}/approve", payload, headers
        )

    def deny_discrepancy_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/discrepancy-claims/{claim_id}/deny", payload, headers
        )

    # ─── FedDeposit ───────────────────────────────────────────────────────

    def create_fed_deposit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/fed-deposits", payload, headers)

    def get_fed_deposit(self, fed_deposit_id, headers):
        return self._request("GET", f"{PREFIX}/fed-deposits/{fed_deposit_id}", headers=headers)

    def list_fed_deposits(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/fed-deposits", headers=headers, params=params)

    def submit_fed_deposit(self, fed_deposit_id, headers):
        return self._request("POST", f"{PREFIX}/fed-deposits/{fed_deposit_id}/submit", {}, headers)

    def confirm_fed_deposit(self, fed_deposit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/fed-deposits/{fed_deposit_id}/confirm", payload, headers
        )

    def list_fed_deposit_fitness_lots(self, fed_deposit_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/fed-deposits/{fed_deposit_id}/fitness-lots",
            headers=headers,
            params=params,
        )

    # ─── CoinOrder / CoinOrderLine ────────────────────────────────────────

    def create_coin_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/coin-orders", payload, headers)

    def get_coin_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/coin-orders/{order_id}", headers=headers)

    def list_coin_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/coin-orders", headers=headers, params=params)

    def approve_coin_order(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/coin-orders/{order_id}/approve", payload, headers)

    def release_coin_order(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/coin-orders/{order_id}/release", payload, headers)

    def return_coin_order(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/coin-orders/{order_id}/return", payload, headers)

    def list_coin_order_lines(self, order_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/coin-orders/{order_id}/lines", headers=headers, params=params
        )


api_client = ApiClient()
