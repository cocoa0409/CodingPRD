"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- developer accounts ----
    def create_developer(self, payload, headers):
        return self._request("POST", "/developers", payload, headers)

    def get_developer(self, developer_id, headers):
        return self._request("GET", f"/developers/{developer_id}", headers=headers)

    def list_developer_ledger_entries(self, developer_id, headers, params=None):
        return self._request(
            "GET", f"/developers/{developer_id}/ledger-entries", headers=headers, params=params
        )

    # ---- apps ----
    def create_app(self, payload, headers):
        return self._request("POST", "/apps", payload, headers)

    def list_apps(self, headers, params=None):
        return self._request("GET", "/apps", headers=headers, params=params)

    def get_app(self, app_id, headers):
        return self._request("GET", f"/apps/{app_id}", headers=headers)

    def update_app(self, app_id, payload, headers):
        return self._request("PATCH", f"/apps/{app_id}", payload, headers)

    def submit_app(self, app_id, payload, headers):
        return self._request("POST", f"/apps/{app_id}/submit", payload, headers)

    def publish_app(self, app_id, payload, headers):
        return self._request("POST", f"/apps/{app_id}/publish", payload, headers)

    def suspend_app(self, app_id, payload, headers):
        return self._request("POST", f"/apps/{app_id}/suspend", payload, headers)

    def reinstate_app(self, app_id, payload, headers):
        return self._request("POST", f"/apps/{app_id}/reinstate", payload, headers)

    def delist_app(self, app_id, payload, headers):
        return self._request("POST", f"/apps/{app_id}/delist", payload, headers)

    def list_app_strikes(self, app_id, headers, params=None):
        return self._request("GET", f"/apps/{app_id}/strikes", headers=headers, params=params)

    def list_app_versions(self, app_id, headers, params=None):
        return self._request("GET", f"/apps/{app_id}/versions", headers=headers, params=params)

    def list_app_installations(self, app_id, headers, params=None):
        return self._request(
            "GET", f"/apps/{app_id}/installations", headers=headers, params=params
        )

    def list_app_support_tickets(self, app_id, headers, params=None):
        return self._request(
            "GET", f"/apps/{app_id}/support-tickets", headers=headers, params=params
        )

    # ---- app versions ----
    def create_app_version(self, app_id, payload, headers):
        return self._request("POST", f"/apps/{app_id}/versions", payload, headers)

    def get_app_version(self, version_id, headers):
        return self._request("GET", f"/app-versions/{version_id}", headers=headers)

    def list_app_versions_filtered(self, headers, params=None):
        return self._request("GET", "/app-versions", headers=headers, params=params)

    def create_scope_request(self, version_id, payload, headers):
        return self._request(
            "POST", f"/app-versions/{version_id}/scope-requests", payload, headers
        )

    def list_scope_requests(self, version_id, headers, params=None):
        return self._request(
            "GET", f"/app-versions/{version_id}/scope-requests", headers=headers, params=params
        )

    def create_review_window(self, version_id, payload, headers):
        return self._request(
            "POST", f"/app-versions/{version_id}/review-windows", payload, headers
        )

    def list_review_windows(self, version_id, headers, params=None):
        return self._request(
            "GET", f"/app-versions/{version_id}/review-windows", headers=headers, params=params
        )

    def approve_version(self, version_id, payload, headers):
        return self._request("POST", f"/app-versions/{version_id}/approve", payload, headers)

    def request_changes(self, version_id, payload, headers):
        return self._request(
            "POST", f"/app-versions/{version_id}/request-changes", payload, headers
        )

    def reject_version(self, version_id, payload, headers):
        return self._request("POST", f"/app-versions/{version_id}/reject", payload, headers)

    # ---- scope requests / review windows (top-level) ----
    def decide_scope_request(self, scope_request_id, payload, headers):
        return self._request(
            "POST", f"/scope-requests/{scope_request_id}/decide", payload, headers
        )

    def get_scope_request(self, scope_request_id, headers):
        return self._request("GET", f"/scope-requests/{scope_request_id}", headers=headers)

    def get_review_window(self, review_window_id, headers):
        return self._request("GET", f"/review-windows/{review_window_id}", headers=headers)

    # ---- ledger entries ----
    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)

    # ---- permission scope catalog ----
    def list_permission_scopes(self, headers, params=None):
        return self._request("GET", "/permission-scopes", headers=headers, params=params)

    def create_permission_scope(self, payload, headers):
        return self._request("POST", "/permission-scopes", payload, headers)

    # ---- merchants ----
    def create_merchant(self, payload, headers):
        return self._request("POST", "/merchants", payload, headers)

    def get_merchant(self, merchant_id, headers):
        return self._request("GET", f"/merchants/{merchant_id}", headers=headers)

    def list_merchant_invoices(self, merchant_id, headers, params=None):
        return self._request(
            "GET", f"/merchants/{merchant_id}/invoices", headers=headers, params=params
        )

    def create_invoice(self, merchant_id, payload, headers):
        return self._request("POST", f"/merchants/{merchant_id}/invoices", payload, headers)

    def list_merchant_installations(self, merchant_id, headers, params=None):
        return self._request(
            "GET", f"/merchants/{merchant_id}/installations", headers=headers, params=params
        )

    def list_merchant_support_tickets(self, merchant_id, headers, params=None):
        return self._request(
            "GET", f"/merchants/{merchant_id}/support-tickets", headers=headers, params=params
        )

    # ---- installations / consent / webhooks ----
    def create_installation(self, payload, headers):
        return self._request("POST", "/installations", payload, headers)

    def get_installation(self, installation_id, headers):
        return self._request("GET", f"/installations/{installation_id}", headers=headers)

    def consent_installation(self, installation_id, payload, headers):
        return self._request(
            "POST", f"/installations/{installation_id}/consent", payload, headers
        )

    def list_consent_records(self, installation_id, headers, params=None):
        return self._request(
            "GET", f"/installations/{installation_id}/consent-records", headers=headers,
            params=params,
        )

    def get_consent_record(self, consent_record_id, headers):
        return self._request("GET", f"/consent-records/{consent_record_id}", headers=headers)

    def revoke_consent_record(self, installation_id, record_id, payload, headers):
        return self._request(
            "POST",
            f"/installations/{installation_id}/consent-records/{record_id}/revoke",
            payload,
            headers,
        )

    def request_reconsent(self, installation_id, payload, headers):
        return self._request(
            "POST", f"/installations/{installation_id}/request-reconsent", payload, headers
        )

    def uninstall_installation(self, installation_id, payload, headers):
        return self._request(
            "POST", f"/installations/{installation_id}/uninstall", payload, headers
        )

    def confirm_data_deletion(self, installation_id, payload, headers):
        return self._request(
            "POST", f"/installations/{installation_id}/confirm-data-deletion", payload, headers
        )

    def get_webhook_subscription(self, subscription_id, headers):
        return self._request(
            "GET", f"/webhook-subscriptions/{subscription_id}", headers=headers
        )

    def create_webhook_subscription(self, installation_id, payload, headers):
        return self._request(
            "POST", f"/installations/{installation_id}/webhook-subscriptions", payload, headers
        )

    def list_webhook_subscriptions(self, installation_id, headers, params=None):
        return self._request(
            "GET", f"/installations/{installation_id}/webhook-subscriptions", headers=headers,
            params=params,
        )

    # ---- billing charges ----
    def create_billing_charge(self, installation_id, payload, headers):
        return self._request(
            "POST", f"/installations/{installation_id}/billing-charges", payload, headers
        )

    def list_billing_charges(self, installation_id, headers, params=None):
        return self._request(
            "GET", f"/installations/{installation_id}/billing-charges", headers=headers,
            params=params,
        )

    def get_billing_charge(self, charge_id, headers):
        return self._request("GET", f"/billing-charges/{charge_id}", headers=headers)

    def approve_charge(self, charge_id, payload, headers):
        return self._request("POST", f"/billing-charges/{charge_id}/approve", payload, headers)

    def decline_charge(self, charge_id, payload, headers):
        return self._request("POST", f"/billing-charges/{charge_id}/decline", payload, headers)

    def reverse_charge(self, charge_id, payload, headers):
        return self._request("POST", f"/billing-charges/{charge_id}/reverse", payload, headers)

    def list_charge_ledger_entries(self, charge_id, headers, params=None):
        return self._request(
            "GET", f"/billing-charges/{charge_id}/ledger-entries", headers=headers, params=params
        )

    # ---- invoices ----
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", payload, headers)

    def mark_invoice_paid(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/mark-paid", payload, headers)

    def void_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", payload, headers)

    # ---- performance samples ----
    def create_performance_sample(self, installation_id, payload, headers):
        return self._request(
            "POST", f"/installations/{installation_id}/performance-samples", payload, headers
        )

    def list_performance_samples(self, installation_id, headers, params=None):
        return self._request(
            "GET", f"/installations/{installation_id}/performance-samples", headers=headers,
            params=params,
        )

    def get_performance_sample(self, sample_id, headers):
        return self._request("GET", f"/performance-samples/{sample_id}", headers=headers)

    # ---- governance strikes ----
    def get_strike(self, strike_id, headers):
        return self._request("GET", f"/strikes/{strike_id}", headers=headers)

    # ---- support tickets ----
    def create_support_ticket(self, app_id, payload, headers):
        return self._request("POST", f"/apps/{app_id}/support-tickets", payload, headers)

    def get_support_ticket(self, ticket_id, headers):
        return self._request("GET", f"/support-tickets/{ticket_id}", headers=headers)

    def respond_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/support-tickets/{ticket_id}/respond", payload, headers)

    def escalate_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/support-tickets/{ticket_id}/escalate", payload, headers)

    def resolve_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/support-tickets/{ticket_id}/resolve", payload, headers)

    def dispute_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/support-tickets/{ticket_id}/dispute", payload, headers)

    # ---- logical clock (test-driving capability) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
