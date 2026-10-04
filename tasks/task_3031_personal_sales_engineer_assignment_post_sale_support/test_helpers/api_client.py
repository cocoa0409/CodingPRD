"""API client: one method per endpoint the PRD defines."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- engineers ----
    def create_engineer(self, payload, headers):
        return self._request("POST", "/engineers", payload, headers)

    def list_engineers(self, headers, params=None):
        return self._request("GET", "/engineers", headers=headers, params=params)

    def get_engineer(self, engineer_id, headers):
        return self._request("GET", f"/engineers/{engineer_id}", headers=headers)

    # ---- customers ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def activate_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/activate", {}, headers)

    def suspend_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/suspend", {}, headers)

    def close_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/close", {}, headers)

    # ---- products ----
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    # ---- service centers ----
    def create_service_center(self, payload, headers):
        return self._request("POST", "/service-centers", payload, headers)

    def list_service_centers(self, headers, params=None):
        return self._request("GET", "/service-centers", headers=headers, params=params)

    def suspend_service_center(self, center_id, headers):
        return self._request("POST", f"/service-centers/{center_id}/suspend", {}, headers)

    def reopen_service_center(self, center_id, headers):
        return self._request("POST", f"/service-centers/{center_id}/reopen", {}, headers)

    # ---- assignments ----
    def create_assignment(self, payload, headers):
        return self._request("POST", "/assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def accept_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/accept", {}, headers)

    def decline_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/decline", {}, headers)

    def end_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/end", {}, headers)

    def reopen_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/reopen", {}, headers)

    # ---- quotes and lines ----
    def create_quote(self, payload, headers):
        return self._request("POST", "/quotes", payload, headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def list_quote_lines_for_quote(self, quote_id, headers, params=None):
        return self._request("GET", f"/quotes/{quote_id}/lines", headers=headers, params=params)

    def get_quote_summary(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}/summary", headers=headers)

    def add_quote_line(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/lines", payload, headers)

    def submit_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/submit", {}, headers)

    def reserve_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/reserve", payload, headers)

    def reject_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/reject", {}, headers)

    def amend_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/amend", payload, headers)

    def cancel_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/cancel", {}, headers)

    def reopen_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/reopen", {}, headers)

    def list_quote_lines(self, headers, params=None):
        return self._request("GET", "/quote-lines", headers=headers, params=params)

    def get_quote_line(self, quote_line_id, headers):
        return self._request("GET", f"/quote-lines/{quote_line_id}", headers=headers)

    # ---- instrument units ----
    def create_instrument_unit(self, payload, headers):
        return self._request("POST", "/instrument-units", payload, headers)

    def list_instrument_units(self, headers, params=None):
        return self._request("GET", "/instrument-units", headers=headers, params=params)

    def get_instrument_unit(self, unit_id, headers):
        return self._request("GET", f"/instrument-units/{unit_id}", headers=headers)

    def start_setup(self, unit_id, headers):
        return self._request("POST", f"/instrument-units/{unit_id}/start-setup", {}, headers)

    def complete_setup(self, unit_id, payload, headers):
        return self._request("POST", f"/instrument-units/{unit_id}/complete-setup", payload, headers)

    def record_inspection(self, unit_id, headers):
        return self._request("POST", f"/instrument-units/{unit_id}/record-inspection", {}, headers)

    def restart_setup(self, unit_id, headers):
        return self._request("POST", f"/instrument-units/{unit_id}/restart-setup", {}, headers)

    def ship_instrument_unit(self, unit_id, headers):
        return self._request("POST", f"/instrument-units/{unit_id}/ship", {}, headers)

    # ---- warranty plans ----
    def create_warranty_plan(self, payload, headers):
        return self._request("POST", "/warranty-plans", payload, headers)

    def list_warranty_plans(self, headers, params=None):
        return self._request("GET", "/warranty-plans", headers=headers, params=params)

    def get_warranty_plan(self, plan_id, headers):
        return self._request("GET", f"/warranty-plans/{plan_id}", headers=headers)

    def activate_warranty_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/warranty-plans/{plan_id}/activate", payload, headers)

    def void_warranty_plan(self, plan_id, headers):
        return self._request("POST", f"/warranty-plans/{plan_id}/void", {}, headers)

    # ---- warranty claims ----
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def route_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/route", {}, headers)

    def reopen_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/reopen", {}, headers)

    def close_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/close", {}, headers)

    # ---- support tickets and escalation ledger ----
    def create_support_ticket(self, payload, headers):
        return self._request("POST", "/support-tickets", payload, headers)

    def list_support_tickets(self, headers, params=None):
        return self._request("GET", "/support-tickets", headers=headers, params=params)

    def get_support_ticket(self, ticket_id, headers):
        return self._request("GET", f"/support-tickets/{ticket_id}", headers=headers)

    def triage_support_ticket(self, ticket_id, headers):
        return self._request("POST", f"/support-tickets/{ticket_id}/triage", {}, headers)

    def escalate_support_ticket(self, ticket_id, headers):
        return self._request("POST", f"/support-tickets/{ticket_id}/escalate", {}, headers)

    def de_escalate_support_ticket(self, ticket_id, headers):
        return self._request("POST", f"/support-tickets/{ticket_id}/de-escalate", {}, headers)

    def resolve_support_ticket(self, ticket_id, headers):
        return self._request("POST", f"/support-tickets/{ticket_id}/resolve", {}, headers)

    def list_escalation_ledger(self, headers, params=None):
        return self._request("GET", "/escalation-ledger", headers=headers, params=params)

    def get_escalation_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/escalation-ledger/{entry_id}", headers=headers)

    # ---- backorders ----
    def create_backorder(self, payload, headers):
        return self._request("POST", "/backorders", payload, headers)

    def list_backorders(self, headers, params=None):
        return self._request("GET", "/backorders", headers=headers, params=params)

    def get_backorder(self, backorder_id, headers):
        return self._request("GET", f"/backorders/{backorder_id}", headers=headers)

    def start_sweep(self, backorder_id, payload, headers):
        return self._request("POST", f"/backorders/{backorder_id}/start-sweep", payload, headers)

    def finalize_allocation(self, backorder_id, payload, headers):
        return self._request(
            "POST", f"/backorders/{backorder_id}/finalize-allocation", payload, headers
        )

    def reset_sweep(self, backorder_id, headers):
        return self._request("POST", f"/backorders/{backorder_id}/reset-sweep", {}, headers)

    def start_receiving(self, backorder_id, headers):
        return self._request("POST", f"/backorders/{backorder_id}/start-receiving", {}, headers)

    def ship_backorder(self, backorder_id, headers):
        return self._request("POST", f"/backorders/{backorder_id}/ship", {}, headers)

    def cancel_backorder(self, backorder_id, headers):
        return self._request("POST", f"/backorders/{backorder_id}/cancel", {}, headers)

    # ---- gear exchanges ----
    def create_gear_exchange(self, payload, headers):
        return self._request("POST", "/gear-exchanges", payload, headers)

    def list_gear_exchanges(self, headers, params=None):
        return self._request("GET", "/gear-exchanges", headers=headers, params=params)

    def get_gear_exchange(self, exchange_id, headers):
        return self._request("GET", f"/gear-exchanges/{exchange_id}", headers=headers)

    def start_trial(self, exchange_id, headers):
        return self._request("POST", f"/gear-exchanges/{exchange_id}/start-trial", {}, headers)

    def request_return(self, exchange_id, headers):
        return self._request("POST", f"/gear-exchanges/{exchange_id}/request-return", {}, headers)

    def withdraw_return(self, exchange_id, headers):
        return self._request("POST", f"/gear-exchanges/{exchange_id}/withdraw-return", {}, headers)

    def complete_exchange(self, exchange_id, headers):
        return self._request("POST", f"/gear-exchanges/{exchange_id}/complete", {}, headers)

    def cancel_gear_exchange(self, exchange_id, headers):
        return self._request("POST", f"/gear-exchanges/{exchange_id}/cancel", {}, headers)

    # ---- certification attempts ----
    def create_certification_attempt(self, payload, headers):
        return self._request("POST", "/certification-attempts", payload, headers)

    def list_certification_attempts(self, headers, params=None):
        return self._request("GET", "/certification-attempts", headers=headers, params=params)

    def get_certification_attempt(self, attempt_id, headers):
        return self._request("GET", f"/certification-attempts/{attempt_id}", headers=headers)

    def grade_certification_attempt(self, attempt_id, headers):
        return self._request("POST", f"/certification-attempts/{attempt_id}/grade", {}, headers)

    def reschedule_certification_attempt(self, attempt_id, headers):
        return self._request(
            "POST", f"/certification-attempts/{attempt_id}/reschedule", {}, headers
        )

    def expire_certification_attempt(self, attempt_id, headers):
        return self._request("POST", f"/certification-attempts/{attempt_id}/expire", {}, headers)


api_client = ApiClient()