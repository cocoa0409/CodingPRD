"""API client: one method per endpoint declared in the PRD.

`GenericApiClient` supplies `_request`, the session and the base URL. Only the
domain endpoint methods live here, plus one timestamp canonicaliser used by the
assertion layer so that sub-second precision never turns into a false failure.
"""
import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

_INSTANT_RE = re.compile(
    r"^(?P<base>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?P<frac>\.\d+)?(?P<tz>Z|[+-]\d{2}:?\d{2})?$"
)


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO-8601 instant to `YYYY-MM-DDTHH:MM:SSZ`.

    Stored instants are ISO 8601 UTC values with a trailing `Z`, but the number of
    fractional digits a server emits is not observable behaviour. Comparisons of
    two instants go through this function so that `...T00:00:00Z`,
    `...T00:00:00.000Z` and `...T00:00:00+00:00` all compare equal.
    """
    if value is None:
        return None
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    return match.group("base") + "Z"


def instants_equal(left: Optional[str], right: Optional[str]) -> bool:
    """True when two ISO-8601 instants name the same second."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    # --- Logical clock ------------------------------------------------------
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers: Dict[str, str]):
        return self._request("GET", "/_clock", headers=headers)

    # --- State licence profiles --------------------------------------------
    def create_state_license_profile(self, payload, headers):
        return self._request("POST", "/state-license-profiles", payload, headers)

    def get_state_license_profile(self, profile_id, headers):
        return self._request("GET", f"/state-license-profiles/{profile_id}", headers=headers)

    def list_state_license_profiles(self, headers, params=None):
        return self._request("GET", "/state-license-profiles", headers=headers, params=params)

    # --- Sellers ------------------------------------------------------------
    def create_seller(self, payload, headers):
        return self._request("POST", "/sellers", payload, headers)

    def get_seller(self, seller_id, headers):
        return self._request("GET", f"/sellers/{seller_id}", headers=headers)

    def list_sellers(self, headers, params=None):
        return self._request("GET", "/sellers", headers=headers, params=params)

    def suspend_seller(self, seller_id, payload, headers):
        return self._request("POST", f"/sellers/{seller_id}/suspend", payload, headers)

    # --- Buyers -------------------------------------------------------------
    def create_buyer(self, payload, headers):
        return self._request("POST", "/buyers", payload, headers)

    def get_buyer(self, buyer_id, headers):
        return self._request("GET", f"/buyers/{buyer_id}", headers=headers)

    def list_buyers(self, headers, params=None):
        return self._request("GET", "/buyers", headers=headers, params=params)

    def qualify_buyer(self, buyer_id, payload, headers):
        return self._request("POST", f"/buyers/{buyer_id}/qualify", payload, headers)

    # --- Route listings -----------------------------------------------------
    def create_route_listing(self, payload, headers):
        return self._request("POST", "/route-listings", payload, headers)

    def get_route_listing(self, listing_id, headers):
        return self._request("GET", f"/route-listings/{listing_id}", headers=headers)

    def list_route_listings(self, headers, params=None):
        return self._request("GET", "/route-listings", headers=headers, params=params)

    def update_route_listing(self, listing_id, payload, headers):
        return self._request("PATCH", f"/route-listings/{listing_id}", payload, headers)

    def publish_route_listing(self, listing_id, headers, payload=None):
        return self._request("POST", f"/route-listings/{listing_id}/publish", payload or {}, headers)

    def withdraw_route_listing(self, listing_id, payload, headers):
        return self._request("POST", f"/route-listings/{listing_id}/withdraw", payload, headers)

    def create_route_valuation(self, listing_id, payload, headers):
        return self._request("POST", f"/route-listings/{listing_id}/valuations", payload, headers)

    # --- Service accounts ---------------------------------------------------
    def create_service_account(self, payload, headers):
        return self._request("POST", "/service-accounts", payload, headers)

    def get_service_account(self, account_id, headers):
        return self._request("GET", f"/service-accounts/{account_id}", headers=headers)

    def list_service_accounts(self, headers, params=None):
        return self._request("GET", "/service-accounts", headers=headers, params=params)

    def verify_service_account(self, account_id, headers, payload=None):
        return self._request("POST", f"/service-accounts/{account_id}/verify", payload or {}, headers)

    def exclude_service_account(self, account_id, payload, headers):
        return self._request("POST", f"/service-accounts/{account_id}/exclude", payload, headers)

    def reinstate_service_account(self, account_id, headers, payload=None):
        return self._request("POST", f"/service-accounts/{account_id}/reinstate", payload or {}, headers)

    def introduce_service_account(self, account_id, payload, headers):
        return self._request("POST", f"/service-accounts/{account_id}/introduce", payload, headers)

    def replace_service_account(self, account_id, payload, headers):
        return self._request("POST", f"/service-accounts/{account_id}/replace", payload, headers)

    # --- Billing history ----------------------------------------------------
    def create_billing_history_record(self, payload, headers):
        return self._request("POST", "/billing-history-records", payload, headers)

    def get_billing_history_record(self, record_id, headers):
        return self._request("GET", f"/billing-history-records/{record_id}", headers=headers)

    def list_billing_history_records(self, headers, params=None):
        return self._request("GET", "/billing-history-records", headers=headers, params=params)

    # --- Route valuations ---------------------------------------------------
    def get_route_valuation(self, valuation_id, headers):
        return self._request("GET", f"/route-valuations/{valuation_id}", headers=headers)

    def list_route_valuations(self, headers, params=None):
        return self._request("GET", "/route-valuations", headers=headers, params=params)

    # --- Deals --------------------------------------------------------------
    def create_deal(self, payload, headers):
        return self._request("POST", "/deals", payload, headers)

    def get_deal(self, deal_id, headers):
        return self._request("GET", f"/deals/{deal_id}", headers=headers)

    def list_deals(self, headers, params=None):
        return self._request("GET", "/deals", headers=headers, params=params)

    def counter_offer_deal(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/counter-offers", payload, headers)

    def reoffer_deal(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/offers", payload, headers)

    def accept_deal(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/accept", payload, headers)

    def clear_diligence(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/clear-diligence", payload, headers)

    def approve_financing(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/approve-financing", payload, headers)

    def close_deal(self, deal_id, headers, payload=None):
        return self._request("POST", f"/deals/{deal_id}/close", payload or {}, headers)

    def terminate_deal(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/terminate", payload, headers)

    # --- Escrow accounts ----------------------------------------------------
    def get_escrow_account(self, escrow_id, headers):
        return self._request("GET", f"/escrow-accounts/{escrow_id}", headers=headers)

    def list_escrow_accounts(self, headers, params=None):
        return self._request("GET", "/escrow-accounts", headers=headers, params=params)

    def create_escrow_deposit(self, escrow_id, payload, headers):
        return self._request("POST", f"/escrow-accounts/{escrow_id}/deposits", payload, headers)

    def release_holdback(self, escrow_id, headers, payload=None):
        return self._request(
            "POST", f"/escrow-accounts/{escrow_id}/holdback-releases", payload or {}, headers
        )

    # --- Licence transfers --------------------------------------------------
    def get_license_transfer(self, transfer_id, headers):
        return self._request("GET", f"/license-transfers/{transfer_id}", headers=headers)

    def list_license_transfers(self, headers, params=None):
        return self._request("GET", "/license-transfers", headers=headers, params=params)

    def apply_license_transfer(self, transfer_id, payload, headers):
        return self._request("POST", f"/license-transfers/{transfer_id}/apply", payload, headers)

    def decide_license_transfer(self, transfer_id, payload, headers):
        return self._request("POST", f"/license-transfers/{transfer_id}/decide", payload, headers)

    def waive_license_transfer(self, transfer_id, payload, headers):
        return self._request("POST", f"/license-transfers/{transfer_id}/waive", payload or {}, headers)

    # --- Attrition events ---------------------------------------------------
    def create_attrition_event(self, payload, headers):
        return self._request("POST", "/attrition-events", payload, headers)

    def get_attrition_event(self, event_id, headers):
        return self._request("GET", f"/attrition-events/{event_id}", headers=headers)

    def list_attrition_events(self, headers, params=None):
        return self._request("GET", "/attrition-events", headers=headers, params=params)

    # --- Clawback settlements ----------------------------------------------
    def create_clawback_settlement(self, payload, headers):
        return self._request("POST", "/clawback-settlements", payload, headers)

    def get_clawback_settlement(self, settlement_id, headers):
        return self._request("GET", f"/clawback-settlements/{settlement_id}", headers=headers)

    def list_clawback_settlements(self, headers, params=None):
        return self._request("GET", "/clawback-settlements", headers=headers, params=params)

    def propose_clawback_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/clawback-settlements/{settlement_id}/propose", payload, headers)

    def dispute_clawback_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/clawback-settlements/{settlement_id}/dispute", payload, headers)

    def settle_clawback_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/clawback-settlements/{settlement_id}/settle", payload, headers)


api_client = ApiClient()
