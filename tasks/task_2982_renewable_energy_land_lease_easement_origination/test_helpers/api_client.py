"""
Endpoint client for the Renewable Land Origination API.

One method per endpoint in the PRD's endpoint table, plus the logical-clock
control endpoint, which is the one path not mounted under /land-origination.
Every method returns the raw requests.Response so tests can assert status codes.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_ROOT, CLOCK_PATH

Payload = Optional[Dict[str, Any]]
Headers = Optional[Dict[str, str]]


class LandOriginationApiClient(GenericApiClient):
    """Typed endpoint surface for the API under test."""

    # ─── Logical clock ────────────────────────────────

    def set_clock(self, current_utc: str, headers: Headers = None):
        return self._request(
            "POST", CLOCK_PATH, {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: Payload, headers: Headers = None):
        return self._request("POST", CLOCK_PATH, payload, headers)

    # ─── Landowners ───────────────────────────────────

    def create_landowner(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{API_ROOT}/landowners", payload, headers)

    def get_landowner(self, landowner_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_ROOT}/landowners/{landowner_id}", None, headers
        )

    def patch_landowner(
        self, landowner_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "PATCH", f"{API_ROOT}/landowners/{landowner_id}", payload, headers
        )

    def list_landowners(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", f"{API_ROOT}/landowners", params, headers)

    # ─── Parcels ──────────────────────────────────────

    def create_parcel(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{API_ROOT}/parcels", payload, headers)

    def get_parcel(self, parcel_id: str, headers: Headers = None):
        return self._request("GET", f"{API_ROOT}/parcels/{parcel_id}", None, headers)

    def rescreen_parcel(
        self, parcel_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"{API_ROOT}/parcels/{parcel_id}/rescreen", payload, headers
        )

    def list_parcels(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", f"{API_ROOT}/parcels", params, headers)

    # ─── Setback rules ────────────────────────────────

    def create_setback_rule(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{API_ROOT}/setback-rules", payload, headers)

    def get_setback_rule(self, rule_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_ROOT}/setback-rules/{rule_id}", None, headers
        )

    def list_setback_rules(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", f"{API_ROOT}/setback-rules", params, headers)

    # ─── Neighbor consents ────────────────────────────

    def create_neighbor_consent(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{API_ROOT}/neighbor-consents", payload, headers)

    def get_neighbor_consent(self, consent_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_ROOT}/neighbor-consents/{consent_id}", None, headers
        )

    def grant_neighbor_consent(
        self, consent_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{API_ROOT}/neighbor-consents/{consent_id}/grant",
            payload if payload is not None else {},
            headers,
        )

    def revoke_neighbor_consent(
        self, consent_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{API_ROOT}/neighbor-consents/{consent_id}/revoke",
            payload if payload is not None else {},
            headers,
        )

    def list_neighbor_consents(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", f"{API_ROOT}/neighbor-consents", params, headers)

    # ─── Title curative items ─────────────────────────

    def create_curative_item(self, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{API_ROOT}/title-curative-items", payload, headers
        )

    def get_curative_item(self, item_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_ROOT}/title-curative-items/{item_id}", None, headers
        )

    def clear_curative_item(
        self, item_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{API_ROOT}/title-curative-items/{item_id}/clear",
            payload if payload is not None else {},
            headers,
        )

    def waive_curative_item(
        self, item_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{API_ROOT}/title-curative-items/{item_id}/waive",
            payload if payload is not None else {},
            headers,
        )

    def list_curative_items(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", f"{API_ROOT}/title-curative-items", params, headers)

    # ─── Option agreements ────────────────────────────

    def create_option_agreement(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{API_ROOT}/option-agreements", payload, headers)

    def get_option_agreement(self, option_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_ROOT}/option-agreements/{option_id}", None, headers
        )

    def list_option_agreements(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", f"{API_ROOT}/option-agreements", params, headers)

    def _option_action(
        self, option_id: str, action: str, payload: Payload, headers: Headers
    ):
        return self._request(
            "POST",
            f"{API_ROOT}/option-agreements/{option_id}/{action}",
            payload if payload is not None else {},
            headers,
        )

    def send_option(
        self, option_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._option_action(option_id, "send", payload, headers)

    def counter_option(
        self, option_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._option_action(option_id, "counter", payload, headers)

    def revise_option(
        self, option_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._option_action(option_id, "revise", payload, headers)

    def accept_option(
        self, option_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._option_action(option_id, "accept", payload, headers)

    def execute_option(
        self, option_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._option_action(option_id, "execute", payload, headers)

    def extend_option(
        self, option_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._option_action(option_id, "extend", payload, headers)

    def exercise_option(
        self, option_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._option_action(option_id, "exercise", payload, headers)

    def withdraw_option(
        self, option_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._option_action(option_id, "withdraw", payload, headers)

    # ─── Option payments ──────────────────────────────

    def get_option_payment(self, payment_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_ROOT}/option-payments/{payment_id}", None, headers
        )

    def list_option_payments(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", f"{API_ROOT}/option-payments", params, headers)

    # ─── Corridors ────────────────────────────────────

    def create_corridor(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{API_ROOT}/corridors", payload, headers)

    def get_corridor(self, corridor_id: str, headers: Headers = None):
        return self._request("GET", f"{API_ROOT}/corridors/{corridor_id}", None, headers)

    def permit_corridor(
        self, corridor_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{API_ROOT}/corridors/{corridor_id}/permit",
            payload if payload is not None else {},
            headers,
        )

    def list_corridors(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", f"{API_ROOT}/corridors", params, headers)

    # ─── Crossing agreements ──────────────────────────

    def create_crossing_agreement(self, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{API_ROOT}/crossing-agreements", payload, headers
        )

    def get_crossing_agreement(self, crossing_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_ROOT}/crossing-agreements/{crossing_id}", None, headers
        )

    def grant_crossing_agreement(
        self, crossing_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{API_ROOT}/crossing-agreements/{crossing_id}/grant",
            payload if payload is not None else {},
            headers,
        )

    def list_crossing_agreements(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", f"{API_ROOT}/crossing-agreements", params, headers)

    # ─── Site-access bookings ─────────────────────────

    def create_site_access_booking(self, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{API_ROOT}/site-access-bookings", payload, headers
        )

    def get_site_access_booking(self, booking_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_ROOT}/site-access-bookings/{booking_id}", None, headers
        )

    def cancel_site_access_booking(
        self, booking_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{API_ROOT}/site-access-bookings/{booking_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    def list_site_access_bookings(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", f"{API_ROOT}/site-access-bookings", params, headers)

    # ─── Lease agreements ─────────────────────────────

    def get_lease(self, lease_id: str, headers: Headers = None):
        return self._request("GET", f"{API_ROOT}/leases/{lease_id}", None, headers)

    def list_leases(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", f"{API_ROOT}/leases", params, headers)

    def get_rent_projection(
        self, lease_id: str, params: Payload = None, headers: Headers = None
    ):
        return self._request(
            "GET", f"{API_ROOT}/leases/{lease_id}/rent-projection", params, headers
        )

    def post_security(self, lease_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{API_ROOT}/leases/{lease_id}/post-security", payload, headers
        )

    def submit_memo(
        self, lease_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{API_ROOT}/leases/{lease_id}/submit-memo",
            payload if payload is not None else {},
            headers,
        )

    def record_memo(self, lease_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{API_ROOT}/leases/{lease_id}/record-memo", payload, headers
        )

    # ─── Rent invoices ────────────────────────────────

    def create_rent_invoice(
        self, lease_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"{API_ROOT}/leases/{lease_id}/rent-invoices", payload, headers
        )

    def get_rent_invoice(self, invoice_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_ROOT}/rent-invoices/{invoice_id}", None, headers
        )

    def issue_rent_invoice(
        self, invoice_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{API_ROOT}/rent-invoices/{invoice_id}/issue",
            payload if payload is not None else {},
            headers,
        )

    def pay_rent_invoice(
        self, invoice_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"{API_ROOT}/rent-invoices/{invoice_id}/pay", payload, headers
        )

    def void_rent_invoice(
        self, invoice_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"{API_ROOT}/rent-invoices/{invoice_id}/void", payload, headers
        )

    def list_rent_invoices(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", f"{API_ROOT}/rent-invoices", params, headers)
