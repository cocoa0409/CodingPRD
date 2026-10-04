"""API client: one method per endpoint defined in the PRD (§4 index)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the age-based book mailing API.

    Every method returns the raw requests.Response; status-code assertions
    happen in tests and fixtures. Body-less action endpoints send an empty
    JSON object. List endpoints accept an optional ``params`` dict of query
    filters (passed through as query string).
    """

    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/library/_clock/set_current_utc", payload, headers)

    # --- State programs (PRD §3.1) ---
    def create_state_program(self, payload, headers):
        return self._request("POST", "/library/state-programs", payload, headers)

    # --- Affiliates (PRD §3.1, §3.8) ---
    def create_affiliate(self, payload, headers):
        return self._request("POST", "/library/affiliates", payload, headers)

    def get_affiliate(self, affiliate_id, headers):
        return self._request("GET", f"/library/affiliates/{affiliate_id}", headers=headers)

    def list_affiliates(self, headers, params=None):
        return self._request("GET", "/library/affiliates", headers=headers, params=params)

    def get_affiliate_penetration(self, affiliate_id, headers, params=None):
        return self._request(
            "GET", f"/library/affiliates/{affiliate_id}/penetration",
            headers=headers, params=params,
        )

    # --- Partner agreements (PRD §3.2) ---
    def create_agreement(self, affiliate_id, payload, headers):
        return self._request("POST", f"/library/affiliates/{affiliate_id}/agreements", payload, headers)

    def list_agreements(self, affiliate_id, headers, params=None):
        return self._request(
            "GET", f"/library/affiliates/{affiliate_id}/agreements",
            headers=headers, params=params,
        )

    def approve_agreement(self, agreement_id, headers):
        return self._request("POST", f"/library/agreements/{agreement_id}/approve", {}, headers)

    def reject_agreement(self, agreement_id, headers):
        return self._request("POST", f"/library/agreements/{agreement_id}/reject", {}, headers)

    # --- Population stats (PRD §3.1) ---
    def create_population_stat(self, affiliate_id, payload, headers):
        return self._request(
            "POST", f"/library/affiliates/{affiliate_id}/population-stats", payload, headers,
        )

    def list_population_stats(self, affiliate_id, headers, params=None):
        return self._request(
            "GET", f"/library/affiliates/{affiliate_id}/population-stats",
            headers=headers, params=params,
        )

    # --- Children (PRD §3.3) ---
    def create_child(self, payload, headers):
        return self._request("POST", "/library/children", payload, headers)

    def get_child(self, child_id, headers):
        return self._request("GET", f"/library/children/{child_id}", headers=headers)

    def list_children(self, headers, params=None):
        return self._request("GET", "/library/children", headers=headers, params=params)

    # --- Address changes (PRD §3.4) ---
    def create_address_change(self, child_id, payload, headers):
        return self._request(
            "POST", f"/library/children/{child_id}/address-changes", payload, headers,
        )

    def list_address_changes(self, child_id, headers, params=None):
        return self._request(
            "GET", f"/library/children/{child_id}/address-changes",
            headers=headers, params=params,
        )

    def decide_address_change(self, change_id, payload, headers):
        return self._request(
            "POST", f"/library/address-changes/{change_id}/decide", payload, headers,
        )

    # --- Titles (PRD §3.5) ---
    def create_title(self, payload, headers):
        return self._request("POST", "/library/titles", payload, headers)

    def get_title(self, title_id, headers):
        return self._request("GET", f"/library/titles/{title_id}", headers=headers)

    # --- Selections (PRD §3.5) ---
    def create_selection(self, payload, headers):
        return self._request("POST", "/library/selections", payload, headers)

    def get_selection(self, selection_id, headers):
        return self._request("GET", f"/library/selections/{selection_id}", headers=headers)

    def list_selections(self, headers, params=None):
        return self._request("GET", "/library/selections", headers=headers, params=params)

    def approve_selection(self, selection_id, headers):
        return self._request("POST", f"/library/selections/{selection_id}/approve", {}, headers)

    def reopen_selection(self, selection_id, payload, headers):
        return self._request("POST", f"/library/selections/{selection_id}/reopen", payload, headers)

    # --- Print orders (PRD §3.6) ---
    def create_print_order(self, payload, headers):
        return self._request("POST", "/library/print-orders", payload, headers)

    def get_print_order(self, print_order_id, headers):
        return self._request("GET", f"/library/print-orders/{print_order_id}", headers=headers)

    def list_print_orders(self, headers, params=None):
        return self._request("GET", "/library/print-orders", headers=headers, params=params)

    def confirm_print_order(self, print_order_id, headers):
        return self._request("POST", f"/library/print-orders/{print_order_id}/confirm", {}, headers)

    # --- Mailing waves (PRD §3.7) ---
    def create_wave(self, payload, headers):
        return self._request("POST", "/library/waves", payload, headers)

    def manifest_wave(self, wave_id, headers):
        return self._request("POST", f"/library/waves/{wave_id}/manifest", {}, headers)

    def reconcile_wave(self, wave_id, headers):
        return self._request("POST", f"/library/waves/{wave_id}/reconcile", {}, headers)

    # --- Mailing items (PRD §3.7) ---
    def get_item(self, item_id, headers):
        return self._request("GET", f"/library/items/{item_id}", headers=headers)

    def list_items(self, headers, params=None):
        return self._request("GET", "/library/items", headers=headers, params=params)

    def mark_item_returned(self, item_id, headers):
        return self._request("POST", f"/library/items/{item_id}/mark-returned", {}, headers)

    # --- Invoices (PRD §3.8) ---
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/library/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/library/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/library/invoices/{invoice_id}/issue", {}, headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/library/invoices/{invoice_id}/pay", {}, headers)

    def dispute_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/library/invoices/{invoice_id}/dispute", payload, headers)


api_client = ApiClient()

__all__ = ["ApiClient", "api_client"]
