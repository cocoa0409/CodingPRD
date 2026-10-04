"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- clock / ops / volume driving ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/lending/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    def run_epoch(self, headers):
        return self._request("POST", "/lending/_ops/run_epoch", {}, headers)

    def drive_circulation(self, payload, headers):
        return self._request("POST", "/lending/_events/drive_circulation", payload, headers)

    # ---- consortiums ----
    def create_consortium(self, payload, headers):
        return self._request("POST", "/lending/consortiums", payload, headers)

    def get_consortium(self, consortium_id, headers):
        return self._request("GET", f"/lending/consortiums/{consortium_id}", headers=headers)

    # ---- libraries ----
    def create_library(self, consortium_id, payload, headers):
        return self._request(
            "POST", f"/lending/consortiums/{consortium_id}/libraries", payload, headers,
        )

    def list_libraries(self, consortium_id, headers, params=None):
        return self._request(
            "GET", f"/lending/consortiums/{consortium_id}/libraries",
            headers=headers, params=params,
        )

    def get_library(self, library_id, headers):
        return self._request("GET", f"/lending/libraries/{library_id}", headers=headers)

    def update_library(self, library_id, payload, headers):
        return self._request("PATCH", f"/lending/libraries/{library_id}", payload, headers)

    # ---- patrons ----
    def create_patron(self, library_id, payload, headers):
        return self._request(
            "POST", f"/lending/libraries/{library_id}/patrons", payload, headers,
        )

    def list_patrons(self, library_id, headers, params=None):
        return self._request(
            "GET", f"/lending/libraries/{library_id}/patrons", headers=headers, params=params,
        )

    def get_patron(self, patron_id, headers):
        return self._request("GET", f"/lending/patrons/{patron_id}", headers=headers)

    def suspend_patron(self, patron_id, headers):
        return self._request("POST", f"/lending/patrons/{patron_id}/suspend", {}, headers)

    def reinstate_patron(self, patron_id, headers):
        return self._request("POST", f"/lending/patrons/{patron_id}/reinstate", {}, headers)

    def list_patron_loans(self, patron_id, headers, params=None):
        return self._request(
            "GET", f"/lending/patrons/{patron_id}/loans", headers=headers, params=params,
        )

    def list_patron_holds(self, patron_id, headers, params=None):
        return self._request(
            "GET", f"/lending/patrons/{patron_id}/holds", headers=headers, params=params,
        )

    # ---- budget funds ----
    def create_fund(self, library_id, payload, headers):
        return self._request(
            "POST", f"/lending/libraries/{library_id}/budget-funds", payload, headers,
        )

    def list_funds(self, library_id, headers, params=None):
        return self._request(
            "GET", f"/lending/libraries/{library_id}/budget-funds",
            headers=headers, params=params,
        )

    def get_fund(self, fund_id, headers):
        return self._request("GET", f"/lending/budget-funds/{fund_id}", headers=headers)

    def close_fund(self, fund_id, headers):
        return self._request("POST", f"/lending/budget-funds/{fund_id}/close", {}, headers)

    # ---- titles ----
    def create_title(self, consortium_id, payload, headers):
        return self._request(
            "POST", f"/lending/consortiums/{consortium_id}/titles", payload, headers,
        )

    def list_titles(self, consortium_id, headers, params=None):
        return self._request(
            "GET", f"/lending/consortiums/{consortium_id}/titles",
            headers=headers, params=params,
        )

    def get_title(self, title_id, headers):
        return self._request("GET", f"/lending/titles/{title_id}", headers=headers)

    def get_title_availability(self, title_id, headers, params=None):
        return self._request(
            "GET", f"/lending/titles/{title_id}/availability", headers=headers, params=params,
        )

    # ---- licenses ----
    def list_licenses(self, headers, params=None):
        return self._request("GET", "/lending/licenses", headers=headers, params=params)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/lending/licenses/{license_id}", headers=headers)

    def retire_license(self, license_id, headers):
        return self._request("POST", f"/lending/licenses/{license_id}/retire", {}, headers)

    # ---- loans ----
    def checkout(self, payload, headers):
        return self._request("POST", "/lending/loans", payload, headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/lending/loans", headers=headers, params=params)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/lending/loans/{loan_id}", headers=headers)

    def return_loan(self, loan_id, headers):
        return self._request("POST", f"/lending/loans/{loan_id}/return", {}, headers)

    def renew_loan(self, loan_id, headers):
        return self._request("POST", f"/lending/loans/{loan_id}/renew", {}, headers)

    # ---- holds ----
    def place_hold(self, payload, headers):
        return self._request("POST", "/lending/holds", payload, headers)

    def list_holds(self, headers, params=None):
        return self._request("GET", "/lending/holds", headers=headers, params=params)

    def get_hold(self, hold_id, headers):
        return self._request("GET", f"/lending/holds/{hold_id}", headers=headers)

    def suspend_hold(self, hold_id, headers):
        return self._request("POST", f"/lending/holds/{hold_id}/suspend", {}, headers)

    def resume_hold(self, hold_id, headers):
        return self._request("POST", f"/lending/holds/{hold_id}/resume", {}, headers)

    def cancel_hold(self, hold_id, headers):
        return self._request("POST", f"/lending/holds/{hold_id}/cancel", {}, headers)

    def claim_hold(self, hold_id, headers):
        return self._request("POST", f"/lending/holds/{hold_id}/claim", {}, headers)

    # ---- acquisition orders ----
    def create_order(self, payload, headers):
        return self._request("POST", "/lending/acquisition-orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request(
            "GET", "/lending/acquisition-orders", headers=headers, params=params,
        )

    def get_order(self, order_id, headers):
        return self._request("GET", f"/lending/acquisition-orders/{order_id}", headers=headers)

    def propose_order(self, order_id, headers):
        return self._request(
            "POST", f"/lending/acquisition-orders/{order_id}/propose", {}, headers,
        )

    def approve_order(self, order_id, headers):
        return self._request(
            "POST", f"/lending/acquisition-orders/{order_id}/approve", {}, headers,
        )

    def reject_order(self, order_id, headers):
        return self._request(
            "POST", f"/lending/acquisition-orders/{order_id}/reject", {}, headers,
        )

    def revise_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/lending/acquisition-orders/{order_id}/revise", payload, headers,
        )

    def cancel_order(self, order_id, headers):
        return self._request(
            "POST", f"/lending/acquisition-orders/{order_id}/cancel", {}, headers,
        )

    def fulfill_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/lending/acquisition-orders/{order_id}/fulfill", payload, headers,
        )

    # ---- consortium invoices ----
    def generate_invoice(self, consortium_id, payload, headers):
        return self._request(
            "POST", f"/lending/consortiums/{consortium_id}/invoices/generate",
            payload, headers,
        )

    def list_invoices(self, consortium_id, headers, params=None):
        return self._request(
            "GET", f"/lending/consortiums/{consortium_id}/invoices",
            headers=headers, params=params,
        )

    def get_invoice(self, invoice_id, headers):
        return self._request(
            "GET", f"/lending/consortium-invoices/{invoice_id}", headers=headers,
        )

    def issue_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/lending/consortium-invoices/{invoice_id}/issue", {}, headers,
        )

    def dispute_invoice(self, invoice_id, headers, payload=None):
        return self._request(
            "POST", f"/lending/consortium-invoices/{invoice_id}/dispute",
            payload or {}, headers,
        )

    def settle_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/lending/consortium-invoices/{invoice_id}/settle", {}, headers,
        )

    # ---- circulation events ----
    def list_events(self, headers, params=None):
        return self._request(
            "GET", "/lending/circulation-events", headers=headers, params=params,
        )

    def list_library_events(self, library_id, headers, params=None):
        return self._request(
            "GET", f"/lending/libraries/{library_id}/circulation-events",
            headers=headers, params=params,
        )

    def list_title_events(self, title_id, headers, params=None):
        return self._request(
            "GET", f"/lending/titles/{title_id}/circulation-events",
            headers=headers, params=params,
        )

    def list_patron_events(self, patron_id, headers, params=None):
        return self._request(
            "GET", f"/lending/patrons/{patron_id}/circulation-events",
            headers=headers, params=params,
        )

    def list_loan_events(self, loan_id, headers, params=None):
        return self._request(
            "GET", f"/lending/loans/{loan_id}/circulation-events",
            headers=headers, params=params,
        )

    def list_license_events(self, license_id, headers, params=None):
        return self._request(
            "GET", f"/lending/licenses/{license_id}/circulation-events",
            headers=headers, params=params,
        )

    def list_hold_events(self, hold_id, headers, params=None):
        return self._request(
            "GET", f"/lending/holds/{hold_id}/circulation-events",
            headers=headers, params=params,
        )

    # ---- usage snapshots ----
    def create_usage_snapshot(self, library_id, payload, headers):
        return self._request(
            "POST", f"/lending/libraries/{library_id}/usage-snapshots", payload, headers,
        )

    def list_usage_snapshots(self, library_id, headers, params=None):
        return self._request(
            "GET", f"/lending/libraries/{library_id}/usage-snapshots",
            headers=headers, params=params,
        )

    def get_usage_snapshot(self, snapshot_id, headers):
        return self._request(
            "GET", f"/lending/usage-snapshots/{snapshot_id}", headers=headers,
        )


api_client = ApiClient()
