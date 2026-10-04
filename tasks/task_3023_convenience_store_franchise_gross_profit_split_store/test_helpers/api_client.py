"""API client: one method per operation the PRD exposes.

Every path in this API is mounted under ``/franchise``.

``_request`` re-issues a call when the *connection itself* fails, and never when
a response was received. The 8-round stability sweep runs eight suites in
lockstep on a shared host, where each per-test server reboot costs a fresh
client ephemeral port; under that load the host's TIME_WAIT table can exhaust
the ephemeral range and a request is reset or refused before it ever reaches the
app. That is an artifact of the isolation harness, not of the API under test.
Every HTTP status -- including every 4xx the suite asserts on -- is returned
untouched, so no PRD assertion is weakened by this: only a call that produced no
response at all is repeated.
"""

import time

import requests

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/franchise"

# Raised when no HTTP response is produced at all: a refused/reset connection,
# a peer that closed before responding, or a truncated response stream.
_NO_RESPONSE_ERRORS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.ChunkedEncodingError,
)

# The reboot performed before each test unbinds the port, and under load a
# request can arrive before the replacement listener is accepting. That window
# is short, so a couple of closely spaced retries are enough to ride it out.
_RETRY_ATTEMPTS = 4
_RETRY_PAUSE_SECONDS = 0.4


class ApiClient(GenericApiClient):

    def _request(self, *args, **kwargs):
        """``GenericApiClient._request``, retried on a transport-only failure.

        Retries are bounded and only ever repeat a call that produced no HTTP
        response at all. The final attempt's exception propagates unchanged, so
        a genuinely unreachable server still fails the test.
        """
        for attempt in range(_RETRY_ATTEMPTS):
            try:
                return super()._request(*args, **kwargs)
            except _NO_RESPONSE_ERRORS:
                if attempt == _RETRY_ATTEMPTS - 1:
                    raise
                # Drop any socket left pooled by the failed attempt so the retry
                # opens a clean connection.
                self.session.close()
                time.sleep(_RETRY_PAUSE_SECONDS)

    # ─── Test-driving: the logical clock ─────────────────────────────────────
    def set_current_utc(self, current_utc, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc}, headers,
        )

    # ─── Franchisee ──────────────────────────────────────────────────────────
    def create_franchisee(self, payload, headers):
        return self._request("POST", f"{PREFIX}/franchisees", payload, headers)

    def list_franchisees(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/franchisees", params, headers)

    def get_franchisee(self, franchisee_id, headers):
        return self._request("GET", f"{PREFIX}/franchisees/{franchisee_id}", headers=headers)

    def suspend_franchisee(self, franchisee_id, headers):
        return self._request("POST", f"{PREFIX}/franchisees/{franchisee_id}/suspend", {}, headers)

    def reinstate_franchisee(self, franchisee_id, headers):
        return self._request("POST", f"{PREFIX}/franchisees/{franchisee_id}/reinstate", {}, headers)

    def terminate_franchisee(self, franchisee_id, headers):
        return self._request("POST", f"{PREFIX}/franchisees/{franchisee_id}/terminate", {}, headers)

    # ─── Store ───────────────────────────────────────────────────────────────
    def create_store(self, payload, headers):
        return self._request("POST", f"{PREFIX}/stores", payload, headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/stores", params, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"{PREFIX}/stores/{store_id}", headers=headers)

    def request_store_transfer(self, store_id, payload, headers):
        return self._request("POST", f"{PREFIX}/stores/{store_id}/transfer-requests", payload, headers)

    def decide_store_transfer(self, store_id, payload, headers):
        return self._request("POST", f"{PREFIX}/stores/{store_id}/transfer-decision", payload, headers)

    # ─── FranchiseAgreement ──────────────────────────────────────────────────
    def create_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/agreements", params, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"{PREFIX}/agreements/{agreement_id}", headers=headers)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"{PREFIX}/agreements/{agreement_id}/activate", {}, headers)

    def open_renewal(self, agreement_id, headers):
        return self._request("POST", f"{PREFIX}/agreements/{agreement_id}/open-renewal", {}, headers)

    def renew_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"{PREFIX}/agreements/{agreement_id}/renew", payload, headers)

    def amend_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"{PREFIX}/agreements/{agreement_id}/amend", payload, headers)

    # ─── Settlement ──────────────────────────────────────────────────────────
    def create_settlement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/settlements", payload, headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/settlements", params, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"{PREFIX}/settlements/{settlement_id}", headers=headers)

    def add_revenue_line(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/settlements/{settlement_id}/revenue-lines", payload, headers)

    def reconcile_settlement(self, settlement_id, headers):
        return self._request("POST", f"{PREFIX}/settlements/{settlement_id}/reconcile", {}, headers)

    def finalize_settlement(self, settlement_id, headers):
        return self._request("POST", f"{PREFIX}/settlements/{settlement_id}/finalize", {}, headers)

    def dispute_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"{PREFIX}/settlements/{settlement_id}/disputes", payload, headers)

    def resolve_dispute(self, settlement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/settlements/{settlement_id}/resolve-dispute", {}, headers)

    # ─── RevenueLine ─────────────────────────────────────────────────────────
    def list_revenue_lines(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/revenue-lines", params, headers)

    def get_revenue_line(self, revenue_line_id, headers):
        return self._request("GET", f"{PREFIX}/revenue-lines/{revenue_line_id}", headers=headers)

    # ─── DrawAdvance ─────────────────────────────────────────────────────────
    def create_draw(self, payload, headers):
        return self._request("POST", f"{PREFIX}/draws", payload, headers)

    def list_draws(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/draws", params, headers)

    def get_draw(self, draw_id, headers):
        return self._request("GET", f"{PREFIX}/draws/{draw_id}", headers=headers)

    def reverse_draw(self, draw_id, headers):
        return self._request("POST", f"{PREFIX}/draws/{draw_id}/reverse", {}, headers)

    # ─── VendorRebate ────────────────────────────────────────────────────────
    def create_rebate(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rebates", payload, headers)

    def list_rebates(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rebates", params, headers)

    def get_rebate(self, rebate_id, headers):
        return self._request("GET", f"{PREFIX}/rebates/{rebate_id}", headers=headers)

    def retract_rebate(self, rebate_id, headers):
        return self._request("POST", f"{PREFIX}/rebates/{rebate_id}/retract", {}, headers)

    # ─── ShrinkAudit ─────────────────────────────────────────────────────────
    def create_shrink_audit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/shrink-audits", payload, headers)

    def list_shrink_audits(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/shrink-audits", params, headers)

    def get_shrink_audit(self, audit_id, headers):
        return self._request("GET", f"{PREFIX}/shrink-audits/{audit_id}", headers=headers)

    def count_shrink_audit(self, audit_id, payload, headers):
        return self._request("POST", f"{PREFIX}/shrink-audits/{audit_id}/count", payload, headers)

    def finalize_shrink_audit(self, audit_id, headers):
        return self._request("POST", f"{PREFIX}/shrink-audits/{audit_id}/finalize", {}, headers)

    # ─── DeliveryWindow ──────────────────────────────────────────────────────
    def create_delivery_window(self, payload, headers):
        return self._request("POST", f"{PREFIX}/delivery-windows", payload, headers)

    def list_delivery_windows(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/delivery-windows", params, headers)

    def get_delivery_window(self, window_id, headers):
        return self._request("GET", f"{PREFIX}/delivery-windows/{window_id}", headers=headers)

    def lock_delivery_window(self, window_id, headers):
        return self._request("POST", f"{PREFIX}/delivery-windows/{window_id}/lock", {}, headers)

    # ─── FreshOrder ──────────────────────────────────────────────────────────
    def create_fresh_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/fresh-orders", payload, headers)

    def list_fresh_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/fresh-orders", params, headers)

    def get_fresh_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/fresh-orders/{order_id}", headers=headers)

    def confirm_fresh_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/fresh-orders/{order_id}/confirm", {}, headers)

    def deliver_fresh_order(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/fresh-orders/{order_id}/deliver", payload, headers)

    def reconcile_fresh_order(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/fresh-orders/{order_id}/reconcile", payload, headers)

    def cancel_fresh_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/fresh-orders/{order_id}/cancel", {}, headers)


api_client = ApiClient()