"""API client: one method per endpoint of the Esign Envelope Workflow API."""
from prd_bench_local_runner.testing import GenericApiClient


def _clean(params):
    """Drop keys whose value is None so they never constrain a listing."""
    if not params:
        return None
    return {k: v for k, v in params.items() if v is not None} or None


class ApiClient(GenericApiClient):
    # ----- Accounts -------------------------------------------------------
    def create_account(self, payload, headers):
        return self._request("POST", "/esign/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/esign/accounts/{account_id}", headers=headers)

    def adjust_account_credit(self, account_id, payload, headers):
        return self._request(
            "POST", f"/esign/accounts/{account_id}/credit-adjustments", payload, headers
        )

    def set_account_status(self, account_id, payload, headers):
        return self._request(
            "POST", f"/esign/accounts/{account_id}/status", payload, headers
        )

    # ----- Retention policies --------------------------------------------
    def create_retention_policy(self, payload, headers):
        return self._request("POST", "/esign/retention-policies", payload, headers)

    def list_retention_policies(self, headers, params=None):
        return self._request(
            "GET", "/esign/retention-policies", headers=headers, params=_clean(params)
        )

    def update_retention_policy(self, policy_id, payload, headers):
        return self._request(
            "PATCH", f"/esign/retention-policies/{policy_id}", payload, headers
        )

    # ----- Templates ------------------------------------------------------
    def create_template(self, payload, headers):
        return self._request("POST", "/esign/templates", payload, headers)

    def list_templates(self, headers, params=None):
        return self._request(
            "GET", "/esign/templates", headers=headers, params=_clean(params)
        )

    def get_template(self, template_id, headers):
        return self._request("GET", f"/esign/templates/{template_id}", headers=headers)

    def publish_template(self, template_id, headers):
        return self._request(
            "POST", f"/esign/templates/{template_id}/publish", None, headers
        )

    def archive_template(self, template_id, headers):
        return self._request(
            "POST", f"/esign/templates/{template_id}/archive", None, headers
        )

    def instantiate_template(self, template_id, payload, headers):
        return self._request(
            "POST", f"/esign/templates/{template_id}/instantiate", payload, headers
        )

    # ----- Envelopes ------------------------------------------------------
    def create_envelope(self, payload, headers):
        return self._request("POST", "/esign/envelopes", payload, headers)

    def list_envelopes(self, headers, params=None):
        return self._request(
            "GET", "/esign/envelopes", headers=headers, params=_clean(params)
        )

    def get_envelope(self, envelope_id, headers):
        return self._request("GET", f"/esign/envelopes/{envelope_id}", headers=headers)

    def add_document(self, envelope_id, payload, headers):
        return self._request(
            "POST", f"/esign/envelopes/{envelope_id}/documents", payload, headers
        )

    def list_documents(self, envelope_id, headers, params=None):
        return self._request(
            "GET",
            f"/esign/envelopes/{envelope_id}/documents",
            headers=headers,
            params=_clean(params),
        )

    def add_recipient(self, envelope_id, payload, headers):
        return self._request(
            "POST", f"/esign/envelopes/{envelope_id}/recipients", payload, headers
        )

    def place_field(self, envelope_id, payload, headers):
        return self._request(
            "POST", f"/esign/envelopes/{envelope_id}/fields", payload, headers
        )

    def send_envelope(self, envelope_id, headers):
        return self._request(
            "POST", f"/esign/envelopes/{envelope_id}/send", None, headers
        )

    def feed_envelope(self, envelope_id, payload, headers):
        return self._request(
            "POST", f"/esign/envelopes/{envelope_id}/feed", payload, headers
        )

    def void_envelope(self, envelope_id, payload, headers):
        return self._request(
            "POST", f"/esign/envelopes/{envelope_id}/void", payload, headers
        )

    def complete_envelope(self, envelope_id, payload, headers):
        return self._request(
            "POST", f"/esign/envelopes/{envelope_id}/complete", payload, headers
        )

    def expire_envelope(self, envelope_id, payload, headers):
        return self._request(
            "POST", f"/esign/envelopes/{envelope_id}/expire", payload, headers
        )

    def purge_envelope(self, envelope_id, payload, headers):
        return self._request(
            "POST", f"/esign/envelopes/{envelope_id}/purge", payload, headers
        )

    def set_legal_hold(self, envelope_id, payload, headers):
        return self._request(
            "POST", f"/esign/envelopes/{envelope_id}/legal-hold", payload, headers
        )

    def send_reminders(self, envelope_id, headers):
        return self._request(
            "POST", f"/esign/envelopes/{envelope_id}/reminders", None, headers
        )

    def get_envelope_quote(self, envelope_id, headers):
        return self._request(
            "GET", f"/esign/envelopes/{envelope_id}/quote", headers=headers
        )

    def get_fee_breakdown(self, envelope_id, headers):
        return self._request(
            "GET", f"/esign/envelopes/{envelope_id}/fee-breakdown", headers=headers
        )

    def get_audit_certificate(self, envelope_id, headers):
        return self._request(
            "GET", f"/esign/envelopes/{envelope_id}/audit-certificate", headers=headers
        )

    # ----- Recipients -----------------------------------------------------
    def list_recipients(self, headers, params=None):
        return self._request(
            "GET", "/esign/recipients", headers=headers, params=_clean(params)
        )

    def get_recipient(self, recipient_id, headers):
        return self._request(
            "GET", f"/esign/recipients/{recipient_id}", headers=headers
        )

    def authenticate_recipient(self, recipient_id, payload, headers):
        return self._request(
            "POST", f"/esign/recipients/{recipient_id}/authenticate", payload, headers
        )

    def open_signing_session(self, recipient_id, payload, headers):
        return self._request(
            "POST", f"/esign/recipients/{recipient_id}/sessions", payload, headers
        )

    def sign_recipient(self, recipient_id, headers):
        return self._request(
            "POST", f"/esign/recipients/{recipient_id}/sign", None, headers
        )

    def decline_recipient(self, recipient_id, payload, headers):
        return self._request(
            "POST", f"/esign/recipients/{recipient_id}/decline", payload, headers
        )

    # ----- Fields ---------------------------------------------------------
    def update_field_value(self, field_id, payload, headers):
        return self._request("PATCH", f"/esign/fields/{field_id}", payload, headers)

    def list_fields(self, headers, params=None):
        return self._request(
            "GET", "/esign/fields", headers=headers, params=_clean(params)
        )

    def get_field(self, field_id, headers):
        return self._request("GET", f"/esign/fields/{field_id}", headers=headers)

    # ----- Sessions -------------------------------------------------------
    def list_sessions(self, headers, params=None):
        return self._request(
            "GET", "/esign/sessions", headers=headers, params=_clean(params)
        )

    def get_session(self, session_id, headers):
        return self._request("GET", f"/esign/sessions/{session_id}", headers=headers)

    # ----- Audit events ---------------------------------------------------
    def list_audit_events(self, headers, params=None):
        return self._request(
            "GET", "/esign/audit-events", headers=headers, params=_clean(params)
        )

    def get_audit_event(self, event_id, headers):
        return self._request(
            "GET", f"/esign/audit-events/{event_id}", headers=headers
        )

    # ----- Bulk sends -----------------------------------------------------
    def list_bulk_sends(self, headers, params=None):
        return self._request(
            "GET", "/esign/bulk-sends", headers=headers, params=_clean(params)
        )

    def get_bulk_send(self, batch_id, headers):
        return self._request("GET", f"/esign/bulk-sends/{batch_id}", headers=headers)

    def create_bulk_send(self, payload, headers):
        return self._request("POST", "/esign/bulk-sends", payload, headers)

    def process_bulk_send(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/esign/bulk-sends/{batch_id}/process", payload, headers
        )

    # ----- Logical clock --------------------------------------------------
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/esign/_clock/set_current_utc", payload, headers)


api_client = ApiClient()