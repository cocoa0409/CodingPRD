"""HTTP client for the marketplace API: one method per declared endpoint.

Every method returns the raw ``requests.Response`` so tests can assert on the
HTTP status as well as the body. All paths carry the ``/marketplace`` prefix.
"""
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant so two spellings of one instant match.

    The contract renders instants with three fractional digits, but an equal
    instant may legitimately arrive with none or with trailing zeroes trimmed.
    Comparisons therefore run on the canonical form ``YYYY-MM-DDTHH:MM:SS.mmmZ``.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = text, "000"
    return f"{head}.{frac}Z"


class ApiClient(GenericApiClient):
    """Endpoint methods for every route the PRD declares."""

    # -- Logical clock ----------------------------------------------------

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/marketplace/_clock/set_current_utc", payload, headers)

    # -- Sellers ----------------------------------------------------------

    def create_seller(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/marketplace/sellers", payload, headers)

    def get_seller(self, seller_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/marketplace/sellers/{seller_id}", headers=headers)

    # -- Buyers -----------------------------------------------------------

    def create_buyer(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/marketplace/buyers", payload, headers)

    # -- Certification programs -------------------------------------------

    def create_certification_program(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/marketplace/certification-programs", payload, headers)

    # -- Listings ---------------------------------------------------------

    def create_listing(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/marketplace/listings", payload, headers)

    def get_listing(self, listing_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/marketplace/listings/{listing_id}", headers=headers)

    def list_listings(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/marketplace/listings", headers=headers, params=params)

    def transition_listing(self, listing_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/marketplace/listings/{listing_id}/transition", payload, headers)

    # -- Inspection reports ------------------------------------------------

    def create_inspection_report(self, listing_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/marketplace/listings/{listing_id}/inspection-reports", payload, headers)

    def list_inspection_reports(self, listing_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/marketplace/listings/{listing_id}/inspection-reports", headers=headers)

    def transition_inspection_report(self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/marketplace/inspection-reports/{report_id}/transition", payload, headers)

    # -- Leases ------------------------------------------------------------

    def create_lease(self, listing_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/marketplace/listings/{listing_id}/leases", payload, headers)

    def list_leases(self, listing_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/marketplace/listings/{listing_id}/leases", headers=headers)

    def get_lease(self, lease_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/marketplace/leases/{lease_id}", headers=headers)

    def transition_lease(self, lease_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/marketplace/leases/{lease_id}/transition", payload, headers)

    # -- Payment records ----------------------------------------------------

    def create_payment_record(self, lease_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/marketplace/leases/{lease_id}/payment-records", payload, headers)

    def list_payment_records(self, lease_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/marketplace/leases/{lease_id}/payment-records", headers=headers)

    # -- Underwriting reports ------------------------------------------------

    def create_underwriting_report(self, listing_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/marketplace/listings/{listing_id}/underwriting-reports", payload, headers)

    def list_underwriting_reports(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/marketplace/underwriting-reports", headers=headers, params=params)

    def get_underwriting_report(self, report_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/marketplace/underwriting-reports/{report_id}", headers=headers)

    # -- Offers ---------------------------------------------------------------

    def create_offer(self, listing_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/marketplace/listings/{listing_id}/offers", payload, headers)

    def get_offer(self, offer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/marketplace/offers/{offer_id}", headers=headers)

    def list_offers(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/marketplace/offers", headers=headers, params=params)

    def transition_offer(self, offer_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/marketplace/offers/{offer_id}/transition", payload, headers)

    def get_offer_escrow(self, offer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/marketplace/offers/{offer_id}/escrow", headers=headers)

    # -- Escrows ---------------------------------------------------------------

    def sign_escrow(self, escrow_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/marketplace/escrows/{escrow_id}/sign", payload, headers)

    def fund_escrow(self, escrow_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/marketplace/escrows/{escrow_id}/fund", payload, headers)

    def transition_escrow(self, escrow_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/marketplace/escrows/{escrow_id}/transition", payload, headers)

    # -- Property managers -------------------------------------------------------

    def create_property_manager(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/marketplace/property-managers", payload, headers)

    # -- Management referrals -----------------------------------------------------

    def create_management_referral(self, listing_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/marketplace/listings/{listing_id}/management-referrals", payload, headers)

    def list_management_referrals(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/marketplace/management-referrals", headers=headers, params=params)

    def get_management_referral(self, referral_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/marketplace/management-referrals/{referral_id}", headers=headers)

    def transition_management_referral(self, referral_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/marketplace/management-referrals/{referral_id}/transition", payload, headers)

    # -- Guarantees ----------------------------------------------------------------

    def create_guarantee(self, listing_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/marketplace/listings/{listing_id}/guarantees", payload, headers)

    def list_guarantees(self, listing_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/marketplace/listings/{listing_id}/guarantees", headers=headers)

    def transition_guarantee(self, guarantee_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/marketplace/guarantees/{guarantee_id}/transition", payload, headers)

    # -- Disputes -------------------------------------------------------------------

    def create_dispute(self, listing_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/marketplace/listings/{listing_id}/disputes", payload, headers)

    def list_disputes(self, listing_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/marketplace/listings/{listing_id}/disputes", headers=headers)

    def transition_dispute(self, dispute_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/marketplace/disputes/{dispute_id}/transition", payload, headers)


api_client = ApiClient()
