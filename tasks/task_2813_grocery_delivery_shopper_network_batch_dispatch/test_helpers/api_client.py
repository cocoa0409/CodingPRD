"""Typed HTTP client: exactly one method per endpoint in PRD section 4.

Also owns timestamp canonicalisation. The PRD pins ISO-8601 UTC with three
fractional digits, but a conformant server may echo an instant it received
without fractional digits, so every instant comparison in the suite goes
through canonical_instant()/normalize_timestamp() here instead of comparing
raw strings.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


# --------------------------------------------------------------------------
# Timestamp canonicalisation
# --------------------------------------------------------------------------
def canonical_instant(value: str) -> datetime:
    """Parse any ISO-8601 UTC spelling into a timezone-aware datetime.

    Accepts a trailing 'Z' or an explicit '+00:00' offset and any number of
    fractional-second digits (including none).
    """
    assert isinstance(value, str), f"expected an ISO-8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_timestamp(value: str) -> str:
    """Render any ISO-8601 UTC spelling as YYYY-MM-DDTHH:MM:SS.mmmZ."""
    moment = canonical_instant(value)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def shift_minutes(value: str, minutes: int) -> str:
    """Return the instant `minutes` after `value`, canonically rendered."""
    return normalize_timestamp(
        (canonical_instant(value) + timedelta(minutes=minutes)).isoformat()
    )


def shift_hours(value: str, hours: int) -> str:
    """Return the instant `hours` after `value`, canonically rendered."""
    return shift_minutes(value, hours * 60)


class ApiClient(GenericApiClient):
    """One method per PRD endpoint. Every method returns the raw Response."""

    # ------------------------------------------------------------------
    # Retailers
    # ------------------------------------------------------------------
    def create_retailer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/retailers", payload, headers)

    def get_retailer(self, retailer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/retailers/{retailer_id}", None, headers)

    def patch_retailer_parity_policy(
        self, retailer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/retailers/{retailer_id}/parity-policy", payload, headers
        )

    # ------------------------------------------------------------------
    # Catalog items
    # ------------------------------------------------------------------
    def create_catalog_item(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/catalog-items", payload, headers)

    def get_catalog_item(self, item_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/catalog-items/{item_id}", None, headers)

    def list_catalog_items(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/catalog-items", params, headers)

    def patch_catalog_item(
        self, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PATCH", f"/catalog-items/{item_id}", payload, headers)

    # ------------------------------------------------------------------
    # Customers and credit ledger
    # ------------------------------------------------------------------
    def create_customer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/customers/{customer_id}", None, headers)

    def create_customer_credit(
        self, customer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/customers/{customer_id}/credits", payload, headers
        )

    def get_credit_ledger_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/credit-ledger-entries/{entry_id}", None, headers
        )

    def list_credit_ledger_entries(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/credit-ledger-entries", params, headers)

    # ------------------------------------------------------------------
    # Shoppers, ratings, reinstatement
    # ------------------------------------------------------------------
    def create_shopper(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/shoppers", payload, headers)

    def get_shopper(self, shopper_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/shoppers/{shopper_id}", None, headers)

    def create_shopper_rating(
        self, shopper_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/shoppers/{shopper_id}/ratings", payload, headers
        )

    def get_shopper_rating(self, rating_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/shopper-ratings/{rating_id}", None, headers)

    def list_shopper_ratings(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/shopper-ratings", params, headers)

    def reinstate_shopper(
        self, shopper_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/shoppers/{shopper_id}/reinstate", payload, headers
        )

    # ------------------------------------------------------------------
    # Orders and order lines
    # ------------------------------------------------------------------
    def create_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/orders/{order_id}", None, headers)

    def list_orders(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/orders", params, headers)

    def create_order_line(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def get_order_line(self, line_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/order-lines/{line_id}", None, headers)

    def list_order_lines(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/order-lines", params, headers)

    def submit_order(
        self, order_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request("POST", f"/orders/{order_id}/submit", payload or {}, headers)

    def create_tip_adjustment(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/orders/{order_id}/tip-adjustments", payload, headers
        )

    def reauthorize_order(
        self, order_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/orders/{order_id}/reauthorize", payload or {}, headers
        )

    def get_parity_disclosure(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/orders/{order_id}/parity-disclosure", None, headers
        )

    # ------------------------------------------------------------------
    # Batches
    # ------------------------------------------------------------------
    def create_batch(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/batches", payload, headers)

    def get_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/batches/{batch_id}", None, headers)

    def list_batches(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/batches", params, headers)

    def add_order_to_batch(
        self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/batches/{batch_id}/orders", payload, headers)

    def list_batch_orders_of_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/batches/{batch_id}/batch-orders", None, headers)

    def list_batch_orders_of_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/orders/{order_id}/batch-orders", None, headers)

    def dispatch_batch(
        self, batch_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/batches/{batch_id}/dispatch", payload or {}, headers
        )

    def claim_batch(
        self, batch_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/batches/{batch_id}/claim", payload or {}, headers
        )

    def start_shopping(
        self, batch_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/batches/{batch_id}/start-shopping", payload or {}, headers
        )

    def checkout_batch(
        self, batch_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/batches/{batch_id}/checkout", payload or {}, headers
        )

    def deliver_batch(
        self, batch_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/batches/{batch_id}/deliver", payload or {}, headers
        )

    def abandon_batch(
        self, batch_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/batches/{batch_id}/abandon", payload or {}, headers
        )

    def reassign_batch(
        self, batch_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/batches/{batch_id}/reassign", payload or {}, headers
        )

    def finalize_payout(
        self, batch_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/batches/{batch_id}/finalize-payout", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Picks and replacement requests
    # ------------------------------------------------------------------
    def pick_order_line(
        self, line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/order-lines/{line_id}/pick", payload, headers)

    def create_replacement_request(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/replacement-requests", payload, headers)

    def get_replacement_request(self, request_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/replacement-requests/{request_id}", None, headers
        )

    def list_replacement_requests(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/replacement-requests", params, headers)

    def approve_replacement_request(
        self, request_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/replacement-requests/{request_id}/approve", payload or {}, headers
        )

    def reject_replacement_request(
        self, request_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/replacement-requests/{request_id}/reject", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Shopper payouts
    # ------------------------------------------------------------------
    def get_shopper_payout(self, payout_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/shopper-payouts/{payout_id}", None, headers)

    def list_shopper_payouts(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/shopper-payouts", params, headers)

    # ------------------------------------------------------------------
    # Test-driving endpoints (DispatchAdmin only)
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def backfill_ratings(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_ratings/backfill", payload, headers)

    def set_shopper_history(
        self, shopper_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/_shoppers/{shopper_id}/history", payload, headers
        )

    # ------------------------------------------------------------------
    # Raw escape hatch for header-omission and unknown-role probes
    # ------------------------------------------------------------------
    def raw(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(method, path, payload, headers)
