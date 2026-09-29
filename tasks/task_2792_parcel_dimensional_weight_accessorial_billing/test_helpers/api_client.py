"""Typed endpoint wrapper for the parcel billing API.

One method per declared endpoint. Every method returns the raw
``requests.Response`` so tests can assert on the HTTP status themselves.

Money is always passed through untouched as JSON numbers (integer cents);
this client never stringifies or re-encodes a monetary field.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .types import Headers, Payload


class ParcelBillingApiClient(GenericApiClient):
    """Endpoint methods for the parcel dimensional-weight billing API."""

    # ------------------------------------------------------------------
    # Escape hatches for auth / envelope probes
    # ------------------------------------------------------------------
    def raw_get(
        self,
        path: str,
        headers: Optional[Headers] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET an arbitrary path with arbitrary (possibly incomplete) headers."""
        return self._request("GET", path, payload=params, headers=headers)

    def raw_post(
        self,
        path: str,
        payload: Optional[Payload] = None,
        headers: Optional[Headers] = None,
    ) -> requests.Response:
        """POST an arbitrary path with arbitrary (possibly incomplete) headers."""
        return self._request("POST", path, payload=payload or {}, headers=headers)

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, now_utc: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"now_utc": now_utc}, headers
        )

    # ------------------------------------------------------------------
    # Shipper accounts
    # ------------------------------------------------------------------
    def create_shipper_account(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/shipper-accounts", payload, headers)

    def suspend_shipper_account(
        self, shipper_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/shipper-accounts/{shipper_id}/suspend", {}, headers
        )

    def get_shipper_account(
        self, shipper_id: str, headers: Headers
    ) -> requests.Response:
        return self._request("GET", f"/shipper-accounts/{shipper_id}", None, headers)

    # ------------------------------------------------------------------
    # Rate contracts
    # ------------------------------------------------------------------
    def create_rate_contract(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/rate-contracts", payload, headers)

    def activate_rate_contract(
        self,
        contract_id: str,
        expected_shipper_account_version: int,
        headers: Headers,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/rate-contracts/{contract_id}/activate",
            {"expected_shipper_account_version": expected_shipper_account_version},
            headers,
        )

    def get_rate_contract(
        self, contract_id: str, headers: Headers
    ) -> requests.Response:
        return self._request("GET", f"/rate-contracts/{contract_id}", None, headers)

    def list_rate_contracts(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/rate-contracts", params or {}, headers)

    # ------------------------------------------------------------------
    # Service levels
    # ------------------------------------------------------------------
    def create_service_level(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/service-levels", payload, headers)

    def get_service_level(
        self, service_level_id: str, headers: Headers
    ) -> requests.Response:
        return self._request("GET", f"/service-levels/{service_level_id}", None, headers)

    # ------------------------------------------------------------------
    # Surcharge windows
    # ------------------------------------------------------------------
    def create_surcharge_window(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/surcharge-windows", payload, headers)

    def activate_surcharge_window(
        self, window_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/surcharge-windows/{window_id}/activate", {}, headers
        )

    def cancel_surcharge_window(
        self, window_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/surcharge-windows/{window_id}/cancel", {}, headers
        )

    def get_surcharge_window(
        self, window_id: str, headers: Headers
    ) -> requests.Response:
        return self._request("GET", f"/surcharge-windows/{window_id}", None, headers)

    def list_surcharge_windows(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/surcharge-windows", params or {}, headers)

    # ------------------------------------------------------------------
    # Shipments
    # ------------------------------------------------------------------
    def create_shipment(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/shipments", payload, headers)

    def get_shipment(self, shipment_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/shipments/{shipment_id}", None, headers)

    def list_shipments(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/shipments", params or {}, headers)

    def get_billing_preview(
        self, shipment_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/shipments/{shipment_id}/billing-preview", None, headers
        )

    def create_scan(
        self, shipment_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"/shipments/{shipment_id}/scans", payload, headers)

    def list_scans(
        self,
        shipment_id: str,
        headers: Headers,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/shipments/{shipment_id}/scans", params or {}, headers
        )

    def deliver_shipment(self, shipment_id: str, headers: Headers) -> requests.Response:
        return self._request("POST", f"/shipments/{shipment_id}/deliver", {}, headers)

    def create_exception(
        self, shipment_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/shipments/{shipment_id}/exceptions", payload, headers
        )

    def create_accessorial(
        self, shipment_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/shipments/{shipment_id}/accessorials", payload, headers
        )

    def list_accessorials(
        self,
        shipment_id: str,
        headers: Headers,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/shipments/{shipment_id}/accessorials", params or {}, headers
        )

    # ------------------------------------------------------------------
    # Accessorial charges
    # ------------------------------------------------------------------
    def waive_accessorial(
        self,
        accessorial_id: str,
        headers: Headers,
        reason: Optional[str] = None,
    ) -> requests.Response:
        payload: Payload = {} if reason is None else {"reason": reason}
        return self._request(
            "POST", f"/accessorial-charges/{accessorial_id}/waive", payload, headers
        )

    def get_accessorial(
        self, accessorial_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/accessorial-charges/{accessorial_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------
    def create_invoice(self, payload: Payload, headers: Headers) -> requests.Response:
        """Run the billing sweep. This is the only way an Invoice is created."""
        return self._request("POST", "/invoices", payload, headers)

    def get_invoice(self, invoice_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/invoices/{invoice_id}", None, headers)

    def list_invoices(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/invoices", params or {}, headers)

    def issue_invoice(self, invoice_id: str, headers: Headers) -> requests.Response:
        return self._request("POST", f"/invoices/{invoice_id}/issue", {}, headers)

    def settle_invoice(
        self, invoice_id: str, payment_reference: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/invoices/{invoice_id}/settle",
            {"payment_reference": payment_reference},
            headers,
        )

    def void_invoice(self, invoice_id: str, headers: Headers) -> requests.Response:
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers)

    # ------------------------------------------------------------------
    # Invoice lines
    # ------------------------------------------------------------------
    def get_invoice_line(self, line_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/invoice-lines/{line_id}", None, headers)

    def list_invoice_lines(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/invoice-lines", params or {}, headers)

    # ------------------------------------------------------------------
    # Billing adjustments
    # ------------------------------------------------------------------
    def create_billing_adjustment(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/billing-adjustments", payload, headers)

    def apply_billing_adjustment(
        self, adjustment_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/billing-adjustments/{adjustment_id}/apply", {}, headers
        )

    def reject_billing_adjustment(
        self,
        adjustment_id: str,
        headers: Headers,
        note: Optional[str] = None,
    ) -> requests.Response:
        payload: Payload = {} if note is None else {"note": note}
        return self._request(
            "POST", f"/billing-adjustments/{adjustment_id}/reject", payload, headers
        )

    def get_billing_adjustment(
        self, adjustment_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/billing-adjustments/{adjustment_id}", None, headers
        )

    def list_billing_adjustments(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/billing-adjustments", params or {}, headers)

    # ------------------------------------------------------------------
    # Disputes
    # ------------------------------------------------------------------
    def create_dispute(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/disputes", payload, headers)

    def submit_evidence(
        self, dispute_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/disputes/{dispute_id}/evidence", payload, headers
        )

    def request_evidence(
        self, dispute_id: str, required_item_type: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/disputes/{dispute_id}/request-evidence",
            {"required_item_type": required_item_type},
            headers,
        )

    def resolve_dispute(
        self, dispute_id: str, outcome: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/disputes/{dispute_id}/resolve", {"outcome": outcome}, headers
        )

    def get_dispute(self, dispute_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/disputes/{dispute_id}", None, headers)

    def list_disputes(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/disputes", params or {}, headers)

    def list_dispute_evidence(
        self,
        dispute_id: str,
        headers: Headers,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/disputes/{dispute_id}/evidence", params or {}, headers
        )

    # ------------------------------------------------------------------
    # Guarantee claims
    # ------------------------------------------------------------------
    def create_guarantee_claim(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/guarantee-claims", payload, headers)

    def scan_guarantee_claims(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/guarantee-claims/scan", payload, headers)

    def adjudicate_guarantee_claim(
        self, claim_id: str, outcome: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/guarantee-claims/{claim_id}/adjudicate",
            {"outcome": outcome},
            headers,
        )

    def get_guarantee_claim(self, claim_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/guarantee-claims/{claim_id}", None, headers)

    def list_guarantee_claims(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/guarantee-claims", params or {}, headers)


# A convenient alias plus a module-level singleton, so conftest can hand the
# same session-scoped client to every test.
ApiClient = ParcelBillingApiClient
api_client = ParcelBillingApiClient()
