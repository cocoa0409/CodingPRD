"""HTTP client covering the complete API surface.

Every path is mounted exactly as the endpoint table writes it; the only path
outside the `/ill` prefix is the logical-clock control endpoint.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class IllApiClient(GenericApiClient):
    """One method per row of the endpoint table."""

    # ---------------------------------------------------------------- clock ---
    def set_clock(self, to_iso8601: str, headers: Optional[Dict[str, str]] = None):
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            payload={"to_iso8601": to_iso8601},
            headers=headers,
        )

    def set_clock_raw(self, payload: Any, headers: Optional[Dict[str, str]] = None):
        return self._request(
            "POST", "/_clock/set_current_utc", payload=payload, headers=headers
        )

    # -------------------------------------------------------------- patrons ---
    def create_patron(self, payload: Any, headers: Optional[Dict[str, str]] = None):
        return self._request("POST", "/ill/patrons", payload=payload, headers=headers)

    def update_patron(
        self, patron_id: str, payload: Any, headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "PATCH", f"/ill/patrons/{patron_id}", payload=payload, headers=headers
        )

    def create_infraction_record(
        self, patron_id: str, payload: Any, headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST",
            f"/ill/patrons/{patron_id}/infraction-records",
            payload=payload,
            headers=headers,
        )

    def get_patron(self, patron_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/ill/patrons/{patron_id}", headers=headers)

    def list_patrons(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        return self._request("GET", "/ill/patrons", headers=headers, params=params)

    # ------------------------------------------------------------- partners ---
    def create_partner(self, payload: Any, headers: Optional[Dict[str, str]] = None):
        return self._request("POST", "/ill/partners", payload=payload, headers=headers)

    def update_partner(
        self, partner_id: str, payload: Any, headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "PATCH", f"/ill/partners/{partner_id}", payload=payload, headers=headers
        )

    def get_partner(self, partner_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/ill/partners/{partner_id}", headers=headers)

    def list_partners(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        return self._request("GET", "/ill/partners", headers=headers, params=params)

    # ------------------------------------------- reciprocity agreements ------
    def create_agreement(self, payload: Any, headers: Optional[Dict[str, str]] = None):
        return self._request(
            "POST", "/ill/reciprocity-agreements", payload=payload, headers=headers
        )

    def get_agreement(
        self, agreement_id: str, headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "GET", f"/ill/reciprocity-agreements/{agreement_id}", headers=headers
        )

    def list_agreements(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET", "/ill/reciprocity-agreements", headers=headers, params=params
        )

    # ---------------------------------------------------- rotas and entries ---
    def create_rota(self, payload: Any, headers: Optional[Dict[str, str]] = None):
        return self._request("POST", "/ill/rotas", payload=payload, headers=headers)

    def get_rota(self, rota_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/ill/rotas/{rota_id}", headers=headers)

    def create_rota_entry(self, payload: Any, headers: Optional[Dict[str, str]] = None):
        return self._request(
            "POST", "/ill/rota-entries", payload=payload, headers=headers
        )

    def update_rota_entry(
        self, entry_id: str, payload: Any, headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "PATCH", f"/ill/rota-entries/{entry_id}", payload=payload, headers=headers
        )

    def get_rota_entry(self, entry_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/ill/rota-entries/{entry_id}", headers=headers)

    def list_rota_entries(
        self,
        rota_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET", f"/ill/rotas/{rota_id}/entries", headers=headers, params=params
        )

    def list_partner_rota_entries(
        self,
        partner_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"/ill/partners/{partner_id}/rota-entries",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------ bib items ---
    def create_bib_item(self, payload: Any, headers: Optional[Dict[str, str]] = None):
        return self._request("POST", "/ill/bib-items", payload=payload, headers=headers)

    def update_bib_item(
        self, bib_item_id: str, payload: Any, headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "PATCH", f"/ill/bib-items/{bib_item_id}", payload=payload, headers=headers
        )

    def get_bib_item(self, bib_item_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/ill/bib-items/{bib_item_id}", headers=headers)

    def list_bib_items(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        return self._request("GET", "/ill/bib-items", headers=headers, params=params)

    # ------------------------------------------------------------- requests ---
    def create_request(self, payload: Any, headers: Optional[Dict[str, str]] = None):
        return self._request("POST", "/ill/requests", payload=payload, headers=headers)

    def get_request(self, request_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/ill/requests/{request_id}", headers=headers)

    def list_requests(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        return self._request("GET", "/ill/requests", headers=headers, params=params)

    def cancel_request(
        self,
        request_id: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"/ill/requests/{request_id}/cancel",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def create_copyright_clearance(
        self, request_id: str, payload: Any, headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST",
            f"/ill/requests/{request_id}/copyright-clearances",
            payload=payload,
            headers=headers,
        )

    def list_copyright_clearances(
        self,
        request_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"/ill/requests/{request_id}/copyright-clearances",
            headers=headers,
            params=params,
        )

    def source_request(
        self,
        request_id: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"/ill/requests/{request_id}/source",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def escalate_request(
        self, request_id: str, payload: Any, headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST",
            f"/ill/requests/{request_id}/escalate",
            payload=payload,
            headers=headers,
        )

    def list_pod_orders(
        self,
        request_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"/ill/requests/{request_id}/pod-orders",
            headers=headers,
            params=params,
        )

    def list_notifications(
        self,
        request_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"/ill/requests/{request_id}/notifications",
            headers=headers,
            params=params,
        )

    # --------------------------------------------------------- supply offers ---
    def accept_offer(
        self,
        offer_id: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"/ill/supply-offers/{offer_id}/accept",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def decline_offer(
        self, offer_id: str, payload: Any, headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST",
            f"/ill/supply-offers/{offer_id}/decline",
            payload=payload,
            headers=headers,
        )

    def get_supply_offer(self, offer_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/ill/supply-offers/{offer_id}", headers=headers)

    def list_supply_offers(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        return self._request("GET", "/ill/supply-offers", headers=headers, params=params)

    def create_shipment(
        self, offer_id: str, payload: Any, headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST",
            f"/ill/supply-offers/{offer_id}/shipments",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------ shipments ---
    def receive_shipment(
        self,
        shipment_id: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"/ill/shipments/{shipment_id}/receive",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def lender_confirm_shipment(
        self, shipment_id: str, payload: Any, headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST",
            f"/ill/shipments/{shipment_id}/lender-confirm",
            payload=payload,
            headers=headers,
        )

    def get_shipment(self, shipment_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/ill/shipments/{shipment_id}", headers=headers)

    def list_request_shipments(
        self,
        request_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"/ill/requests/{request_id}/shipments",
            headers=headers,
            params=params,
        )

    # ---------------------------------------------------------------- loans ---
    def pickup_loan(
        self,
        loan_id: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"/ill/loans/{loan_id}/pickup",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def renew_loan(
        self,
        loan_id: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"/ill/loans/{loan_id}/renewals",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def recall_loan(
        self,
        loan_id: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"/ill/loans/{loan_id}/recalls",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def return_loan(
        self,
        loan_id: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"/ill/loans/{loan_id}/return",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def declare_loan_lost(
        self,
        loan_id: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"/ill/loans/{loan_id}/declare-lost",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def create_charge_settlement(
        self, loan_id: str, payload: Any, headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST",
            f"/ill/loans/{loan_id}/charge-settlements",
            payload=payload,
            headers=headers,
        )

    def get_loan(self, loan_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/ill/loans/{loan_id}", headers=headers)

    def list_request_loans(
        self,
        request_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET", f"/ill/requests/{request_id}/loans", headers=headers, params=params
        )

    # ------------------------------------------------- electronic deliveries ---
    def create_electronic_delivery(
        self, request_id: str, payload: Any, headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST",
            f"/ill/requests/{request_id}/electronic-deliveries",
            payload=payload,
            headers=headers,
        )

    def create_download(
        self,
        delivery_id: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"/ill/electronic-deliveries/{delivery_id}/downloads",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def get_electronic_delivery(
        self, delivery_id: str, headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "GET", f"/ill/electronic-deliveries/{delivery_id}", headers=headers
        )

    def list_request_electronic_deliveries(
        self,
        request_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"/ill/requests/{request_id}/electronic-deliveries",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------ POD orders ---
    def decide_pod_order(
        self, order_id: str, payload: Any, headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST",
            f"/ill/pod-orders/{order_id}/decision",
            payload=payload,
            headers=headers,
        )

    def receive_pod_order(
        self,
        order_id: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"/ill/pod-orders/{order_id}/receive",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def get_pod_order(self, order_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/ill/pod-orders/{order_id}", headers=headers)

    # ------------------------------------------------------- lending charges ---
    def create_lending_charge(
        self, payload: Any, headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST", "/ill/lending-charges", payload=payload, headers=headers
        )

    def get_lending_charge(
        self, charge_id: str, headers: Optional[Dict[str, str]] = None
    ):
        return self._request("GET", f"/ill/lending-charges/{charge_id}", headers=headers)

    def list_partner_lending_charges(
        self,
        partner_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"/ill/partners/{partner_id}/lending-charges",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------- invoices ---
    def create_invoice(
        self, partner_id: str, payload: Any, headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST",
            f"/ill/partners/{partner_id}/invoices",
            payload=payload,
            headers=headers,
        )

    def issue_invoice(
        self,
        invoice_id: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"/ill/invoices/{invoice_id}/issue",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def settle_invoice(
        self, invoice_id: str, payload: Any, headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST",
            f"/ill/invoices/{invoice_id}/settle",
            payload=payload,
            headers=headers,
        )

    def get_invoice(self, invoice_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/ill/invoices/{invoice_id}", headers=headers)

    def list_partner_invoices(
        self,
        partner_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"/ill/partners/{partner_id}/invoices",
            headers=headers,
            params=params,
        )

    # -------------------------------------------------- reports and ops runs ---
    def get_copyright_usage(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET", "/ill/copyright-usage", headers=headers, params=params
        )

    def create_ops_run(
        self,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            "/ill/ops-runs",
            payload=payload if payload is not None else {},
            headers=headers,
        )
