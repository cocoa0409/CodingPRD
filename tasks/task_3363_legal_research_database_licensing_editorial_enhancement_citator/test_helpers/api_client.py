"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/legal-research/_clock/set_current_utc", payload, headers)

    # --- Documents ---
    def create_document(self, payload, headers):
        return self._request("POST", "/legal-research/documents", payload, headers)

    def list_documents(self, headers, params=None):
        return self._request("GET", "/legal-research/documents", headers=headers, params=params)

    def get_document(self, document_id, headers):
        return self._request("GET", f"/legal-research/documents/{document_id}", headers=headers)

    def list_citing_references(self, document_id, headers, params=None):
        return self._request(
            "GET", f"/legal-research/documents/{document_id}/citing-references",
            headers=headers, params=params,
        )

    def publish_document(self, document_id, payload, headers):
        return self._request("POST", f"/legal-research/documents/{document_id}/publish", payload, headers)

    def citator_override(self, document_id, payload, headers):
        return self._request("POST", f"/legal-research/documents/{document_id}/citator-override", payload, headers)

    # --- Headnotes ---
    def create_headnote(self, document_id, payload, headers):
        return self._request("POST", f"/legal-research/documents/{document_id}/headnotes", payload, headers)

    def list_headnotes(self, headers, params=None):
        return self._request("GET", "/legal-research/headnotes", headers=headers, params=params)

    def get_headnote(self, headnote_id, headers):
        return self._request("GET", f"/legal-research/headnotes/{headnote_id}", headers=headers)

    def submit_headnote(self, headnote_id, headers, payload=None):
        return self._request("POST", f"/legal-research/headnotes/{headnote_id}/submit", payload or {}, headers)

    def decide_headnote(self, headnote_id, payload, headers):
        return self._request("POST", f"/legal-research/headnotes/{headnote_id}/decide", payload, headers)

    # --- Commercial onboarding ---
    def create_plan(self, payload, headers):
        return self._request("POST", "/legal-research/plans", payload, headers)

    def create_account(self, payload, headers):
        return self._request("POST", "/legal-research/accounts", payload, headers)

    def create_subscription(self, payload, headers):
        return self._request("POST", "/legal-research/subscriptions", payload, headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/legal-research/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/legal-research/subscriptions/{subscription_id}", headers=headers)

    def change_plan(self, subscription_id, payload, headers):
        return self._request("PATCH", f"/legal-research/subscriptions/{subscription_id}/change-plan", payload, headers)

    def transition_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/legal-research/subscriptions/{subscription_id}/status", payload, headers)

    def manage_seats(self, subscription_id, payload, headers):
        return self._request("POST", f"/legal-research/subscriptions/{subscription_id}/seats", payload, headers)

    # --- Subscriber users ---
    def list_users(self, headers, params=None):
        return self._request("GET", "/legal-research/users", headers=headers, params=params)

    def get_user(self, user_id, headers):
        return self._request("GET", f"/legal-research/users/{user_id}", headers=headers)

    # --- Usage events ---
    def create_usage_event(self, payload, headers):
        return self._request("POST", "/legal-research/usage-events", payload, headers)

    def list_usage_events(self, headers, params=None):
        return self._request("GET", "/legal-research/usage-events", headers=headers, params=params)

    def get_usage_event(self, event_id, headers):
        return self._request("GET", f"/legal-research/usage-events/{event_id}", headers=headers)

    # --- Invoices ---
    def generate_invoice(self, payload, headers):
        return self._request("POST", "/legal-research/invoices/generate", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/legal-research/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/legal-research/invoices/{invoice_id}", headers=headers)

    def transition_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/legal-research/invoices/{invoice_id}/transition", payload, headers)

    # --- License agreements ---
    def create_license_agreement(self, payload, headers):
        return self._request("POST", "/legal-research/license-agreements", payload, headers)

    def get_license_agreement(self, agreement_id, headers):
        return self._request("GET", f"/legal-research/license-agreements/{agreement_id}", headers=headers)

    def terminate_agreement(self, agreement_id, headers, payload=None):
        return self._request("POST", f"/legal-research/license-agreements/{agreement_id}/terminate", payload or {}, headers)

    # --- Royalty statements ---
    def generate_royalty_statement(self, payload, headers):
        return self._request("POST", "/legal-research/royalty-statements/generate", payload, headers)

    def list_royalty_statements(self, headers, params=None):
        return self._request("GET", "/legal-research/royalty-statements", headers=headers, params=params)

    def get_royalty_statement(self, statement_id, headers):
        return self._request("GET", f"/legal-research/royalty-statements/{statement_id}", headers=headers)

    # --- Removal orders ---
    def create_removal_order(self, payload, headers):
        return self._request("POST", "/legal-research/removal-orders", payload, headers)

    def list_removal_orders(self, headers, params=None):
        return self._request("GET", "/legal-research/removal-orders", headers=headers, params=params)

    def get_removal_order(self, order_id, headers):
        return self._request("GET", f"/legal-research/removal-orders/{order_id}", headers=headers)

    def transition_removal_order(self, order_id, payload, headers):
        return self._request("POST", f"/legal-research/removal-orders/{order_id}/transition", payload, headers)


api_client = ApiClient()
