"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ---- manufacturers ----
    def create_manufacturer(self, payload, headers):
        return self._request("POST", "/manufacturers", payload, headers)

    def list_manufacturers(self, headers, params=None):
        return self._request("GET", "/manufacturers", headers=headers, params=params)

    def get_manufacturer(self, manufacturer_id, headers):
        return self._request("GET", f"/manufacturers/{manufacturer_id}", headers=headers)

    def suspend_manufacturer(self, manufacturer_id, headers):
        return self._request(
            "POST", f"/manufacturers/{manufacturer_id}/suspend", {}, headers,
        )

    # ---- agreements ----
    def create_agreement(self, payload, headers):
        return self._request("POST", "/agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/agreements/{agreement_id}", headers=headers)

    def patch_agreement(self, agreement_id, payload, headers):
        return self._request("PATCH", f"/agreements/{agreement_id}", payload, headers)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/agreements/{agreement_id}/activate", {}, headers)

    def suspend_agreement(self, agreement_id, headers):
        return self._request("POST", f"/agreements/{agreement_id}/suspend", {}, headers)

    def reinstate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/agreements/{agreement_id}/reinstate", {}, headers)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/agreements/{agreement_id}/terminate", {}, headers)

    def list_agreement_vehicles(self, agreement_id, headers, params=None):
        return self._request(
            "GET", f"/agreements/{agreement_id}/vehicles", headers=headers, params=params,
        )

    def list_agreement_teaming(self, agreement_id, headers, params=None):
        return self._request(
            "GET", f"/agreements/{agreement_id}/teaming", headers=headers, params=params,
        )

    def list_agreement_sales_reports(self, agreement_id, headers, params=None):
        return self._request(
            "GET", f"/agreements/{agreement_id}/sales-reports",
            headers=headers, params=params,
        )

    def list_agreement_audits(self, agreement_id, headers, params=None):
        return self._request(
            "GET", f"/agreements/{agreement_id}/audits", headers=headers, params=params,
        )

    # ---- vehicles ----
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicles", headers=headers, params=params)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def patch_vehicle(self, vehicle_id, payload, headers):
        return self._request("PATCH", f"/vehicles/{vehicle_id}", payload, headers)

    def authorize_vehicle(self, vehicle_id, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/authorize", {}, headers)

    def suspend_vehicle(self, vehicle_id, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/suspend", {}, headers)

    def reinstate_vehicle(self, vehicle_id, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/reinstate", {}, headers)

    def expire_vehicle(self, vehicle_id, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/expire", {}, headers)

    def list_vehicle_price_lists(self, vehicle_id, headers, params=None):
        return self._request(
            "GET", f"/vehicles/{vehicle_id}/price-lists", headers=headers, params=params,
        )

    def list_vehicle_orders(self, vehicle_id, headers, params=None):
        return self._request(
            "GET", f"/vehicles/{vehicle_id}/orders", headers=headers, params=params,
        )

    def list_vehicle_teaming_scopes(self, vehicle_id, headers, params=None):
        return self._request(
            "GET", f"/vehicles/{vehicle_id}/teaming-scopes", headers=headers, params=params,
        )

    # ---- price lists ----
    def create_price_list(self, payload, headers):
        return self._request("POST", "/price-lists", payload, headers)

    def list_price_lists(self, headers, params=None):
        return self._request("GET", "/price-lists", headers=headers, params=params)

    def get_price_list(self, price_list_id, headers):
        return self._request("GET", f"/price-lists/{price_list_id}", headers=headers)

    def list_price_list_lines(self, price_list_id, headers, params=None):
        return self._request(
            "GET", f"/price-lists/{price_list_id}/lines", headers=headers, params=params,
        )

    def submit_price_list(self, price_list_id, headers):
        return self._request("POST", f"/price-lists/{price_list_id}/submit", {}, headers)

    def activate_price_list(self, price_list_id, headers):
        return self._request("POST", f"/price-lists/{price_list_id}/activate", {}, headers)

    def reject_price_list(self, price_list_id, headers):
        return self._request("POST", f"/price-lists/{price_list_id}/reject", {}, headers)

    def reopen_price_list(self, price_list_id, headers):
        return self._request("POST", f"/price-lists/{price_list_id}/reopen", {}, headers)

    def list_price_list_modifications(self, price_list_id, headers, params=None):
        return self._request(
            "GET", f"/price-lists/{price_list_id}/modifications",
            headers=headers, params=params,
        )

    def list_price_list_orders(self, price_list_id, headers, params=None):
        return self._request(
            "GET", f"/price-lists/{price_list_id}/orders", headers=headers, params=params,
        )

    # ---- price modifications ----
    def create_price_modification(self, payload, headers):
        return self._request("POST", "/price-modifications", payload, headers)

    def get_price_modification(self, modification_id, headers):
        return self._request(
            "GET", f"/price-modifications/{modification_id}", headers=headers,
        )

    def approve_price_modification(self, modification_id, headers):
        return self._request(
            "POST", f"/price-modifications/{modification_id}/approve", {}, headers,
        )

    def reject_price_modification(self, modification_id, headers):
        return self._request(
            "POST", f"/price-modifications/{modification_id}/reject", {}, headers,
        )

    # ---- teaming ----
    def create_teaming(self, payload, headers):
        return self._request("POST", "/teaming", payload, headers)

    def list_teaming(self, headers, params=None):
        return self._request("GET", "/teaming", headers=headers, params=params)

    def get_teaming(self, teaming_id, headers):
        return self._request("GET", f"/teaming/{teaming_id}", headers=headers)

    def list_teaming_scopes(self, teaming_id, headers, params=None):
        return self._request(
            "GET", f"/teaming/{teaming_id}/scopes", headers=headers, params=params,
        )

    def approve_teaming(self, teaming_id, headers):
        return self._request("POST", f"/teaming/{teaming_id}/approve", {}, headers)

    def suspend_teaming(self, teaming_id, headers):
        return self._request("POST", f"/teaming/{teaming_id}/suspend", {}, headers)

    def reinstate_teaming(self, teaming_id, headers):
        return self._request("POST", f"/teaming/{teaming_id}/reinstate", {}, headers)

    def terminate_teaming(self, teaming_id, headers):
        return self._request("POST", f"/teaming/{teaming_id}/terminate", {}, headers)

    def list_teaming_orders(self, teaming_id, headers, params=None):
        return self._request(
            "GET", f"/teaming/{teaming_id}/orders", headers=headers, params=params,
        )

    # ---- orders ----
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/submit", {}, headers)

    def deliver_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/deliver", {}, headers)

    def cancel_order(self, order_id, expected_order_version, headers):
        return self._request(
            "POST", f"/orders/{order_id}/cancel",
            {"expected_order_version": expected_order_version}, headers,
        )

    def list_order_invoices(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/orders/{order_id}/invoices", headers=headers, params=params,
        )

    def list_order_disputes(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/orders/{order_id}/disputes", headers=headers, params=params,
        )

    # ---- invoices ----
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers)

    # ---- disputes ----
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def resolve_dispute(self, dispute_id, outcome, headers):
        return self._request(
            "POST", f"/disputes/{dispute_id}/resolve", {"outcome": outcome}, headers,
        )

    # ---- sales reports ----
    def create_sales_report(self, payload, headers):
        return self._request("POST", "/sales-reports", payload, headers)

    def list_sales_reports(self, headers, params=None):
        return self._request("GET", "/sales-reports", headers=headers, params=params)

    def get_sales_report(self, report_id, headers):
        return self._request("GET", f"/sales-reports/{report_id}", headers=headers)

    def finalize_sales_report(self, report_id, headers):
        return self._request("POST", f"/sales-reports/{report_id}/finalize", {}, headers)

    # ---- audits ----
    def create_audit(self, payload, headers):
        return self._request("POST", "/audits", payload, headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/audits", headers=headers, params=params)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/audits/{audit_id}", headers=headers)

    def issue_finding(self, audit_id, headers):
        return self._request("POST", f"/audits/{audit_id}/issue-finding", {}, headers)

    def close_audit(self, audit_id, headers):
        return self._request("POST", f"/audits/{audit_id}/close", {}, headers)


api_client = ApiClient()
