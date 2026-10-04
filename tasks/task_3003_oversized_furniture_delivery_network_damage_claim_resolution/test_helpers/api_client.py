"""API client: one method per endpoint defined in the PRD
(Oversize Freight Network API, mounted under /oversize-freight)."""
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/oversize-freight"


class ApiClient(GenericApiClient):
    # ── Logical clock ─────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", f"{BASE}/_clock/set_current_utc", payload, headers)

    # ── Suppliers ─────────────────────────────────────────────────────────
    def create_supplier(self, payload, headers):
        return self._request("POST", f"{BASE}/suppliers", payload, headers)

    def list_suppliers(self, headers, params=None):
        return self._request("GET", f"{BASE}/suppliers", headers=headers, params=params)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"{BASE}/suppliers/{supplier_id}", headers=headers)

    def get_supplier_scorecard(self, supplier_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/suppliers/{supplier_id}/scorecard",
            headers=headers, params=params,
        )

    # ── Items ─────────────────────────────────────────────────────────────
    def create_item(self, payload, headers):
        return self._request("POST", f"{BASE}/items", payload, headers)

    def list_items(self, headers, params=None):
        return self._request("GET", f"{BASE}/items", headers=headers, params=params)

    def get_item(self, item_id, headers):
        return self._request("GET", f"{BASE}/items/{item_id}", headers=headers)

    def delist_item(self, item_id, headers):
        return self._request("POST", f"{BASE}/items/{item_id}/delist", headers=headers)

    # ── Hubs ──────────────────────────────────────────────────────────────
    def create_hub(self, payload, headers):
        return self._request("POST", f"{BASE}/hubs", payload, headers)

    def list_hubs(self, headers, params=None):
        return self._request("GET", f"{BASE}/hubs", headers=headers, params=params)

    def get_hub(self, hub_id, headers):
        return self._request("GET", f"{BASE}/hubs/{hub_id}", headers=headers)

    # ── Freight lanes ─────────────────────────────────────────────────────
    def create_freight_lane(self, payload, headers):
        return self._request("POST", f"{BASE}/freight-lanes", payload, headers)

    def list_freight_lanes(self, headers, params=None):
        return self._request("GET", f"{BASE}/freight-lanes", headers=headers, params=params)

    def get_freight_lane(self, lane_id, headers):
        return self._request("GET", f"{BASE}/freight-lanes/{lane_id}", headers=headers)

    # ── Customers ─────────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", f"{BASE}/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"{BASE}/customers/{customer_id}", headers=headers)

    # ── Orders ────────────────────────────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", f"{BASE}/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", f"{BASE}/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"{BASE}/orders/{order_id}", headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"{BASE}/orders/{order_id}/cancel", headers=headers)

    # ── Shipments ─────────────────────────────────────────────────────────
    def list_shipments(self, headers, params=None):
        return self._request("GET", f"{BASE}/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"{BASE}/shipments/{shipment_id}", headers=headers)

    def depart_shipment(self, shipment_id, headers):
        return self._request("POST", f"{BASE}/shipments/{shipment_id}/depart", headers=headers)

    def deliver_shipment(self, shipment_id, headers):
        return self._request("POST", f"{BASE}/shipments/{shipment_id}/deliver", headers=headers)

    # ── Linehauls ─────────────────────────────────────────────────────────
    def create_linehaul(self, payload, headers):
        return self._request("POST", f"{BASE}/linehauls", payload, headers)

    def list_linehauls(self, headers, params=None):
        return self._request("GET", f"{BASE}/linehauls", headers=headers, params=params)

    def get_linehaul(self, linehaul_id, headers):
        return self._request("GET", f"{BASE}/linehauls/{linehaul_id}", headers=headers)

    def depart_linehaul(self, linehaul_id, headers):
        return self._request("POST", f"{BASE}/linehauls/{linehaul_id}/depart", headers=headers)

    def arrive_linehaul(self, linehaul_id, headers):
        return self._request("POST", f"{BASE}/linehauls/{linehaul_id}/arrive", headers=headers)

    def mark_linehaul_missed(self, linehaul_id, headers):
        return self._request("POST", f"{BASE}/linehauls/{linehaul_id}/mark-missed", headers=headers)

    # ── Delivery appointments ─────────────────────────────────────────────
    def create_appointment(self, payload, headers):
        return self._request("POST", f"{BASE}/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", f"{BASE}/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"{BASE}/appointments/{appointment_id}", headers=headers)

    def complete_appointment(self, appointment_id, headers):
        return self._request("POST", f"{BASE}/appointments/{appointment_id}/complete", headers=headers)

    def mark_appointment_no_show(self, appointment_id, headers):
        return self._request("POST", f"{BASE}/appointments/{appointment_id}/mark-no-show", headers=headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"{BASE}/appointments/{appointment_id}/cancel", headers=headers)

    # ── Damage claims ─────────────────────────────────────────────────────
    def create_damage_claim(self, payload, headers):
        return self._request("POST", f"{BASE}/damage-claims", payload, headers)

    def list_damage_claims(self, headers, params=None):
        return self._request("GET", f"{BASE}/damage-claims", headers=headers, params=params)

    def get_damage_claim(self, claim_id, headers):
        return self._request("GET", f"{BASE}/damage-claims/{claim_id}", headers=headers)

    def inspect_damage_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{BASE}/damage-claims/{claim_id}/inspect", payload, headers)

    def determine_damage_claim(self, claim_id, headers):
        return self._request("POST", f"{BASE}/damage-claims/{claim_id}/determine", headers=headers)

    def settle_damage_claim(self, claim_id, headers):
        return self._request("POST", f"{BASE}/damage-claims/{claim_id}/settle", headers=headers)

    def withdraw_damage_claim(self, claim_id, headers):
        return self._request("POST", f"{BASE}/damage-claims/{claim_id}/withdraw", headers=headers)

    # ── Chargebacks ───────────────────────────────────────────────────────
    def list_chargebacks(self, headers, params=None):
        return self._request("GET", f"{BASE}/chargebacks", headers=headers, params=params)

    def get_chargeback(self, chargeback_id, headers):
        return self._request("GET", f"{BASE}/chargebacks/{chargeback_id}", headers=headers)

    def settle_chargeback(self, chargeback_id, headers):
        return self._request("POST", f"{BASE}/chargebacks/{chargeback_id}/settle", headers=headers)

    def dispute_chargeback(self, chargeback_id, headers):
        return self._request("POST", f"{BASE}/chargebacks/{chargeback_id}/dispute", headers=headers)

    def reverse_chargeback(self, chargeback_id, headers):
        return self._request("POST", f"{BASE}/chargebacks/{chargeback_id}/reverse", headers=headers)

    # ── Return authorizations ─────────────────────────────────────────────
    def create_return_authorization(self, payload, headers):
        return self._request("POST", f"{BASE}/return-authorizations", payload, headers)

    def list_return_authorizations(self, headers, params=None):
        return self._request("GET", f"{BASE}/return-authorizations", headers=headers, params=params)

    def get_return_authorization(self, ra_id, headers):
        return self._request("GET", f"{BASE}/return-authorizations/{ra_id}", headers=headers)

    def approve_return_authorization(self, ra_id, headers):
        return self._request("POST", f"{BASE}/return-authorizations/{ra_id}/approve", headers=headers)

    def deny_return_authorization(self, ra_id, headers):
        return self._request("POST", f"{BASE}/return-authorizations/{ra_id}/deny", headers=headers)

    def complete_return_authorization(self, ra_id, headers):
        return self._request("POST", f"{BASE}/return-authorizations/{ra_id}/complete", headers=headers)


api_client = ApiClient()
