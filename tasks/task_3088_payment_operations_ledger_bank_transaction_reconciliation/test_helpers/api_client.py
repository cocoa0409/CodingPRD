"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Ledgers ──────────────────────────────────────
    def create_ledger(self, payload, headers):
        return self._request("POST", "/ledgers", payload, headers)

    def get_ledger(self, ledger_id, headers):
        return self._request("GET", f"/ledgers/{ledger_id}", headers=headers)

    def list_ledgers(self, headers, params=None):
        return self._request("GET", "/ledgers", headers=headers, params=params)

    def close_period(self, ledger_id, payload, headers):
        return self._request("POST", f"/ledgers/{ledger_id}/close-period", payload, headers)

    def ledger_receipts(self, ledger_id, payload, headers):
        return self._request("POST", f"/ledgers/{ledger_id}/receipts", payload, headers)

    def recompute_ledger(self, ledger_id, payload, headers):
        return self._request("POST", f"/ledgers/{ledger_id}/recompute", payload, headers)

    def ledger_summary(self, ledger_id, payload, headers, params=None):
        return self._request("POST", f"/ledgers/{ledger_id}/summary", payload, headers, params)

    # ─── Legal entities ───────────────────────────────
    def create_legal_entity(self, payload, headers):
        return self._request("POST", "/legal-entities", payload, headers)

    def get_legal_entity(self, entity_id, headers):
        return self._request("GET", f"/legal-entities/{entity_id}", headers=headers)

    def list_legal_entities(self, headers, params=None):
        return self._request("GET", "/legal-entities", headers=headers, params=params)

    def list_entity_counterparties(self, entity_id, headers, params=None):
        return self._request("GET", f"/legal-entities/{entity_id}/counterparties",
                             headers=headers, params=params)

    def list_entity_bank_accounts(self, entity_id, headers, params=None):
        return self._request("GET", f"/legal-entities/{entity_id}/bank-accounts",
                             headers=headers, params=params)

    def list_entity_calendar(self, entity_id, headers, params=None):
        return self._request("GET", f"/legal-entities/{entity_id}/institution-calendar",
                             headers=headers, params=params)

    def list_entity_payment_orders(self, entity_id, headers, params=None):
        return self._request("GET", f"/legal-entities/{entity_id}/payment-orders",
                             headers=headers, params=params)

    # ─── Counterparties ───────────────────────────────
    def create_counterparty(self, payload, headers):
        return self._request("POST", "/counterparties", payload, headers)

    def get_counterparty(self, counterparty_id, headers):
        return self._request("GET", f"/counterparties/{counterparty_id}", headers=headers)

    def list_counterparties(self, headers, params=None):
        return self._request("GET", "/counterparties", headers=headers, params=params)

    def list_counterparty_payment_orders(self, counterparty_id, headers, params=None):
        return self._request("GET", f"/counterparties/{counterparty_id}/payment-orders",
                             headers=headers, params=params)

    def restrict_counterparty(self, counterparty_id, headers):
        return self._request("POST", f"/counterparties/{counterparty_id}/restrict",
                             None, headers)

    def block_counterparty(self, counterparty_id, headers):
        return self._request("POST", f"/counterparties/{counterparty_id}/block",
                             None, headers)

    def unblock_counterparty(self, counterparty_id, headers):
        return self._request("POST", f"/counterparties/{counterparty_id}/unblock",
                             None, headers)

    def restore_counterparty(self, counterparty_id, headers):
        return self._request("POST", f"/counterparties/{counterparty_id}/restore",
                             None, headers)

    def close_counterparty(self, counterparty_id, headers):
        return self._request("POST", f"/counterparties/{counterparty_id}/close",
                             None, headers)

    # ─── Counterparty relationships ───────────────────
    def create_relationship(self, payload, headers):
        return self._request("POST", "/counterparty-relationships", payload, headers)

    def get_relationship(self, relationship_id, headers):
        return self._request("GET", f"/counterparty-relationships/{relationship_id}",
                             headers=headers)

    def list_relationships(self, headers, params=None):
        return self._request("GET", "/counterparty-relationships", headers=headers,
                             params=params)

    def activate_relationship(self, relationship_id, payload, headers):
        return self._request("POST", f"/counterparty-relationships/{relationship_id}/activate",
                             payload, headers)

    def suspend_relationship(self, relationship_id, headers):
        return self._request("POST", f"/counterparty-relationships/{relationship_id}/suspend",
                             None, headers)

    def terminate_relationship(self, relationship_id, headers):
        return self._request("POST", f"/counterparty-relationships/{relationship_id}/terminate",
                             None, headers)

    # ─── Bank accounts ────────────────────────────────
    def create_bank_account(self, payload, headers):
        return self._request("POST", "/bank-accounts", payload, headers)

    def get_bank_account(self, account_id, headers):
        return self._request("GET", f"/bank-accounts/{account_id}", headers=headers)

    def list_bank_accounts(self, headers, params=None):
        return self._request("GET", "/bank-accounts", headers=headers, params=params)

    def list_account_virtual_accounts(self, account_id, headers, params=None):
        return self._request("GET", f"/bank-accounts/{account_id}/virtual-accounts",
                             headers=headers, params=params)

    def list_account_statements(self, account_id, headers, params=None):
        return self._request("GET", f"/bank-accounts/{account_id}/statements",
                             headers=headers, params=params)

    def list_account_settlement_pools(self, account_id, headers, params=None):
        return self._request("GET", f"/bank-accounts/{account_id}/settlement-pools",
                             headers=headers, params=params)

    def close_bank_account(self, account_id, headers):
        return self._request("POST", f"/bank-accounts/{account_id}/close", None, headers)

    # ─── Virtual accounts ─────────────────────────────
    def create_virtual_account(self, payload, headers):
        return self._request("POST", "/virtual-accounts", payload, headers)

    def get_virtual_account(self, virtual_account_id, headers):
        return self._request("GET", f"/virtual-accounts/{virtual_account_id}",
                             headers=headers)

    def list_virtual_accounts(self, headers, params=None):
        return self._request("GET", "/virtual-accounts", headers=headers, params=params)

    def close_virtual_account(self, virtual_account_id, headers):
        return self._request("POST", f"/virtual-accounts/{virtual_account_id}/close",
                             None, headers)

    # ─── Bank statements, lines, reconciliation ───────
    def import_statement(self, payload, headers):
        return self._request("POST", "/bank-statements", payload, headers)

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/bank-statements/{statement_id}", headers=headers)

    def list_statements(self, headers, params=None):
        return self._request("GET", "/bank-statements", headers=headers, params=params)

    def list_statement_lines(self, statement_id, headers, params=None):
        return self._request("GET", f"/bank-statements/{statement_id}/lines",
                             headers=headers, params=params)

    def list_statement_revisions(self, statement_id, headers, params=None):
        return self._request("GET", f"/bank-statements/{statement_id}/revisions",
                             headers=headers, params=params)

    def append_statement_line(self, statement_id, payload, headers):
        return self._request("POST", f"/bank-statements/{statement_id}/lines",
                             payload, headers)

    def reconcile_statement(self, statement_id, payload, headers):
        return self._request("POST", f"/bank-statements/{statement_id}/reconcile",
                             payload, headers)

    def revise_statement(self, statement_id, payload, headers):
        return self._request("POST", f"/bank-statements/{statement_id}/revise",
                             payload, headers)

    # ─── Payment orders ───────────────────────────────
    def create_payment_order(self, payload, headers):
        return self._request("POST", "/payment-orders", payload, headers)

    def get_payment_order(self, order_id, headers):
        return self._request("GET", f"/payment-orders/{order_id}", headers=headers)

    def list_payment_orders(self, headers, params=None):
        return self._request("GET", "/payment-orders", headers=headers, params=params)

    def approve_payment_order(self, order_id, payload, headers):
        return self._request("POST", f"/payment-orders/{order_id}/approve", payload, headers)

    def cancel_payment_order(self, order_id, headers):
        return self._request("POST", f"/payment-orders/{order_id}/cancel", None, headers)

    def dispatch_payment_order(self, order_id, payload, headers):
        return self._request("POST", f"/payment-orders/{order_id}/dispatch", payload, headers)

    def mark_payment_order_in_flight(self, order_id, headers):
        return self._request("POST", f"/payment-orders/{order_id}/mark_in_flight",
                             None, headers)

    def settle_payment_order(self, order_id, headers):
        return self._request("POST", f"/payment-orders/{order_id}/settle", None, headers)

    def return_payment_order(self, order_id, payload, headers):
        return self._request("POST", f"/payment-orders/{order_id}/return", payload, headers)

    def reverse_payment_order(self, order_id, payload, headers):
        return self._request("POST", f"/payment-orders/{order_id}/reverse", payload, headers)

    def fail_payment_order(self, order_id, payload, headers):
        return self._request("POST", f"/payment-orders/{order_id}/fail", payload, headers)

    # ─── Transactions ─────────────────────────────────
    def book_transaction(self, ledger_id, payload, headers):
        return self._request("POST", f"/ledgers/{ledger_id}/transactions", payload, headers)

    def get_transaction(self, transaction_id, headers):
        return self._request("GET", f"/transactions/{transaction_id}", headers=headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", "/transactions", headers=headers, params=params)

    def post_transaction(self, transaction_id, headers):
        return self._request("POST", f"/transactions/{transaction_id}/post", None, headers)

    def reject_transaction(self, transaction_id, headers):
        return self._request("POST", f"/transactions/{transaction_id}/reject", None, headers)

    def mark_transaction_settled(self, transaction_id, headers):
        return self._request("POST", f"/transactions/{transaction_id}/mark_settled",
                             None, headers)

    def void_transaction(self, transaction_id, payload, headers):
        return self._request("POST", f"/transactions/{transaction_id}/void", payload, headers)

    # ─── Settlement pools ─────────────────────────────
    def create_settlement_pool(self, payload, headers):
        return self._request("POST", "/settlement-pools", payload, headers)

    def get_settlement_pool(self, pool_id, headers):
        return self._request("GET", f"/settlement-pools/{pool_id}", headers=headers)

    def list_settlement_pools(self, headers, params=None):
        return self._request("GET", "/settlement-pools", headers=headers, params=params)

    def list_pool_memberships(self, pool_id, headers, params=None):
        return self._request("GET", f"/settlement-pools/{pool_id}/memberships",
                             headers=headers, params=params)

    def refresh_settlement_pool(self, pool_id, headers):
        return self._request("POST", f"/settlement-pools/{pool_id}/refresh", None, headers)

    def create_pool_membership(self, payload, headers):
        return self._request("POST", "/pool-memberships", payload, headers)

    def get_pool_membership(self, membership_id, headers):
        return self._request("GET", f"/pool-memberships/{membership_id}", headers=headers)

    def list_pool_memberships_flat(self, headers, params=None):
        return self._request("GET", "/pool-memberships", headers=headers, params=params)

    def remove_pool_membership(self, membership_id, headers):
        return self._request("POST", f"/pool-memberships/{membership_id}/remove",
                             None, headers)

    # ─── Release requests ─────────────────────────────
    def create_release_request(self, payload, headers):
        return self._request("POST", "/release-requests", payload, headers)

    def get_release_request(self, request_id, headers):
        return self._request("GET", f"/release-requests/{request_id}", headers=headers)

    def list_release_requests(self, headers, params=None):
        return self._request("GET", "/release-requests", headers=headers, params=params)

    def cancel_release_request(self, request_id, headers):
        return self._request("POST", f"/release-requests/{request_id}/cancel", None, headers)

    # ─── Banking calendar ─────────────────────────────
    def publish_calendar_cell(self, payload, headers):
        return self._request("POST", "/banking-calendar", payload, headers)

    def get_calendar_cell(self, cell_id, headers):
        return self._request("GET", f"/banking-calendar/{cell_id}", headers=headers)

    def list_calendar_cells(self, headers, params=None):
        return self._request("GET", "/banking-calendar", headers=headers, params=params)

    # ─── Exception queue ──────────────────────────────
    def get_exception(self, exception_id, headers):
        return self._request("GET", f"/exceptions/{exception_id}", headers=headers)

    def list_exceptions(self, headers, params=None):
        return self._request("GET", "/exceptions", headers=headers, params=params)

    def assign_exception(self, exception_id, payload, headers):
        return self._request("POST", f"/exceptions/{exception_id}/assign", payload, headers)

    def reevaluate_exception_aging(self, exception_id, headers):
        return self._request("POST", f"/exceptions/{exception_id}/reevaluate_aging",
                             None, headers)

    def escalate_exception(self, exception_id, payload, headers):
        return self._request("POST", f"/exceptions/{exception_id}/escalate", payload, headers)

    def deescalate_exception(self, exception_id, headers):
        return self._request("POST", f"/exceptions/{exception_id}/deescalate", None, headers)

    def unassign_exception(self, exception_id, headers):
        return self._request("POST", f"/exceptions/{exception_id}/unassign", None, headers)

    def resolve_exception(self, exception_id, payload, headers):
        return self._request("POST", f"/exceptions/{exception_id}/resolve", payload, headers)

    def waive_exception(self, exception_id, payload, headers):
        return self._request("POST", f"/exceptions/{exception_id}/waive", payload, headers)

    # ─── Audit trail ──────────────────────────────────
    def append_audit_event(self, payload, headers):
        return self._request("POST", "/audit-events", payload, headers)

    def get_audit_event(self, sequence_number, headers, params=None):
        return self._request("GET", f"/audit-events/{sequence_number}",
                             headers=headers, params=params)

    def list_audit_events(self, headers, params=None):
        return self._request("GET", "/audit-events", headers=headers, params=params)

    # ─── Test-driving capabilities ────────────────────
    def set_current_utc(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def simulate_settlement(self, payload, headers):
        return self._request("POST", "/_rails/simulate_settlement", payload, headers)


api_client = ApiClient()