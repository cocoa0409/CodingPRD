"""HTTP client: one method per endpoint in the PRD's routing table.

Every method returns the raw ``requests.Response`` so tests decide whether to
validate a success envelope or an error envelope. Instant handling lives here:
``canonical_instant`` normalises any ISO-8601 instant the service returns to a
single millisecond-precision ``...Z`` form so tests never compare raw strings of
varying sub-second width.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

Payload = Dict[str, Any]
Headers = Dict[str, str]

INSTANT_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"


def _parse_instant(value: str) -> datetime:
    """Parse any ISO-8601 instant spelling the service may emit."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Return an instant in the canonical millisecond ``...Z`` spelling.

    Accepts second precision, microsecond precision, ``+00:00`` offsets and
    ``Z`` suffixes alike, so equality checks are precision independent.
    """
    if value is None:
        return None
    parsed = _parse_instant(value)
    return parsed.strftime(INSTANT_FORMAT)[:-3] + "Z"


def shift_instant(value: str, *, minutes: int = 0, days: int = 0, seconds: int = 0) -> str:
    """Return ``value`` moved by the given offset, in canonical spelling."""
    parsed = _parse_instant(value) + timedelta(minutes=minutes, days=days, seconds=seconds)
    return parsed.strftime(INSTANT_FORMAT)[:-3] + "Z"


def instants_equal(left: Optional[str], right: Optional[str]) -> bool:
    """Compare two instants after canonicalisation."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """Thin, explicit wrapper: one method per endpoint."""

    # --- clock ------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Optional[Headers] = None) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers=headers
        )

    def set_clock_raw(self, payload: Payload, headers: Optional[Headers] = None) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)

    # --- channels ---------------------------------------------------------
    def create_channel(self, payload: Payload, headers: Optional[Headers] = None) -> requests.Response:
        return self._request("POST", "/channels", payload, headers=headers)

    def get_channel(
        self,
        channel_id: str,
        headers: Optional[Headers] = None,
        params: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request("GET", f"/channels/{channel_id}", headers=headers, params=params)

    def patch_channel_content_policy(
        self, channel_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "PATCH", f"/channels/{channel_id}/content-policy", payload, headers=headers
        )

    def create_surcharge_rule(
        self, channel_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/channels/{channel_id}/surcharge-rules", payload, headers=headers
        )

    def list_surcharge_rules(
        self,
        channel_id: str,
        headers: Optional[Headers] = None,
        params: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/channels/{channel_id}/surcharge-rules", headers=headers, params=params
        )

    # --- distribution partners -------------------------------------------
    def create_partner(self, payload: Payload, headers: Optional[Headers] = None) -> requests.Response:
        return self._request("POST", "/distribution-partners", payload, headers=headers)

    def get_partner(
        self,
        partner_id: str,
        headers: Optional[Headers] = None,
        params: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/distribution-partners/{partner_id}", headers=headers, params=params
        )

    # --- fare filings -----------------------------------------------------
    def create_fare_filing(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", "/fare-filings", payload, headers=headers)

    def get_fare_filing(
        self,
        filing_id: str,
        headers: Optional[Headers] = None,
        params: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request("GET", f"/fare-filings/{filing_id}", headers=headers, params=params)

    def list_fare_filings(
        self, headers: Optional[Headers] = None, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/fare-filings", headers=headers, params=params)

    def set_fare_filing_state(
        self, filing_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", f"/fare-filings/{filing_id}/state", payload, headers=headers)

    def create_fare_filing_revision(
        self, filing_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/fare-filings/{filing_id}/revisions", payload, headers=headers
        )

    # --- ancillaries and bundles -----------------------------------------
    def create_ancillary_product(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", "/ancillary-products", payload, headers=headers)

    def create_bundle_definition(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", "/bundle-definitions", payload, headers=headers)

    # --- agency agreements ------------------------------------------------
    def create_agency_agreement(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", "/agency-agreements", payload, headers=headers)

    def get_agency_agreement(
        self,
        agreement_id: str,
        headers: Optional[Headers] = None,
        params: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/agency-agreements/{agreement_id}", headers=headers, params=params
        )

    def list_agency_agreements(
        self, headers: Optional[Headers] = None, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/agency-agreements", headers=headers, params=params)

    def create_negotiation_round(
        self, agreement_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/agency-agreements/{agreement_id}/negotiation-rounds", payload, headers=headers
        )

    # --- corporate contracts ---------------------------------------------
    def create_corporate_contract(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", "/corporate-contracts", payload, headers=headers)

    def get_corporate_contract(
        self,
        contract_id: str,
        headers: Optional[Headers] = None,
        params: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/corporate-contracts/{contract_id}", headers=headers, params=params
        )

    def list_corporate_contracts(
        self, headers: Optional[Headers] = None, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/corporate-contracts", headers=headers, params=params)

    # --- offers -----------------------------------------------------------
    def create_offer(self, payload: Payload, headers: Optional[Headers] = None) -> requests.Response:
        return self._request("POST", "/offers", payload, headers=headers)

    def get_offer(
        self, offer_id: str, headers: Optional[Headers] = None, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", f"/offers/{offer_id}", headers=headers, params=params)

    def list_offers(
        self, headers: Optional[Headers] = None, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/offers", headers=headers, params=params)

    def list_offer_items(
        self, offer_id: str, headers: Optional[Headers] = None, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", f"/offers/{offer_id}/items", headers=headers, params=params)

    def publish_offer(
        self, offer_id: str, payload: Optional[Payload] = None, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", f"/offers/{offer_id}/publish", payload or {}, headers=headers)

    # --- orders -----------------------------------------------------------
    def create_order(self, payload: Payload, headers: Optional[Headers] = None) -> requests.Response:
        return self._request("POST", "/orders", payload, headers=headers)

    def get_order(
        self, order_id: str, headers: Optional[Headers] = None, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", f"/orders/{order_id}", headers=headers, params=params)

    def list_orders(
        self, headers: Optional[Headers] = None, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/orders", headers=headers, params=params)

    def post_order_payment(
        self, order_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", f"/orders/{order_id}/payment", payload, headers=headers)

    def post_order_fulfillment(
        self, order_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", f"/orders/{order_id}/fulfillment", payload, headers=headers)

    def create_service_request(
        self, order_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", f"/orders/{order_id}/service-requests", payload, headers=headers)

    def list_service_requests(
        self, order_id: str, headers: Optional[Headers] = None, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/orders/{order_id}/service-requests", headers=headers, params=params
        )

    # --- service requests -------------------------------------------------
    def review_service_request(
        self, request_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", f"/service-requests/{request_id}/review", payload, headers=headers)

    def apply_service_request(
        self, request_id: str, payload: Optional[Payload] = None, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/service-requests/{request_id}/apply", payload or {}, headers=headers
        )

    # --- certifications and connectivity tests ---------------------------
    def create_certification(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", "/partner-certifications", payload, headers=headers)

    def get_certification(
        self,
        certification_id: str,
        headers: Optional[Headers] = None,
        params: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/partner-certifications/{certification_id}", headers=headers, params=params
        )

    def list_certifications(
        self, headers: Optional[Headers] = None, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/partner-certifications", headers=headers, params=params)

    def create_connectivity_test(
        self, certification_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/partner-certifications/{certification_id}/connectivity-tests",
            payload,
            headers=headers,
        )

    def list_connectivity_tests(
        self,
        certification_id: str,
        headers: Optional[Headers] = None,
        params: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/partner-certifications/{certification_id}/connectivity-tests",
            headers=headers,
            params=params,
        )

    def post_test_outcome(
        self, test_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", f"/connectivity-tests/{test_id}/outcome", payload, headers=headers)

    def post_certification_decision(
        self, certification_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/partner-certifications/{certification_id}/decision",
            payload,
            headers=headers,
        )

    # --- generic escape hatch --------------------------------------------
    def request(
        self,
        method: str,
        path: str,
        payload: Optional[Payload] = None,
        headers: Optional[Headers] = None,
        params: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(method, path, payload, headers=headers, params=params)


api_client = ApiClient()

__all__: List[str] = [
    "ApiClient",
    "api_client",
    "canonical_instant",
    "instants_equal",
    "shift_instant",
]
