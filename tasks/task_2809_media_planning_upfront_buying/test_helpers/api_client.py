"""One method per endpoint of the Media Planning & Upfront Buying API.

Every method returns the raw response so a test may assert on the status code as
well as on the body.  The domain prefix is applied here, so callers name only the
collection.

Timestamps are compared through :func:`canonical_instant` rather than by raw
string equality: a test writes an instant in the compact form it supplies on
input, while the API answers with three fractional digits.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH, canonical_instant

Headers = Optional[Dict[str, str]]
Payload = Optional[Dict[str, Any]]
Params = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """Endpoint-level client for the upfront buying domain."""

    def _domain(
        self,
        method: str,
        path: str,
        payload: Payload = None,
        headers: Headers = None,
        params: Params = None,
    ):
        return self._request(method, f"{API_PREFIX}{path}", payload, headers, params=params)

    @staticmethod
    def canonical_instant(value: str) -> str:
        """Canonicalise an instant to the millisecond precision the API emits."""
        return canonical_instant(value)

    # ------------------------------------------------------------------
    # Advertisers
    # ------------------------------------------------------------------
    def create_advertiser(self, payload: Payload, headers: Headers = None):
        return self._domain("POST", "/advertisers", payload, headers)

    def get_advertiser(self, advertiser_id: str, headers: Headers = None):
        return self._domain("GET", f"/advertisers/{advertiser_id}", None, headers)

    def list_advertisers(self, headers: Headers = None, params: Params = None):
        return self._domain("GET", "/advertisers", None, headers, params=params)

    # ------------------------------------------------------------------
    # Campaigns
    # ------------------------------------------------------------------
    def create_campaign(self, payload: Payload, headers: Headers = None):
        return self._domain("POST", "/campaigns", payload, headers)

    def get_campaign(self, campaign_id: str, headers: Headers = None):
        return self._domain("GET", f"/campaigns/{campaign_id}", None, headers)

    def list_campaigns(self, headers: Headers = None, params: Params = None):
        return self._domain("GET", "/campaigns", None, headers, params=params)

    def submit_plan(
        self, campaign_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._domain(
            "POST",
            f"/campaigns/{campaign_id}/submit-plan",
            {} if payload is None else payload,
            headers,
        )

    def approve_plan(
        self, campaign_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._domain(
            "POST",
            f"/campaigns/{campaign_id}/approve-plan",
            {} if payload is None else payload,
            headers,
        )

    def reject_plan(self, campaign_id: str, payload: Payload, headers: Headers = None):
        return self._domain(
            "POST", f"/campaigns/{campaign_id}/reject-plan", payload, headers
        )

    def fund_campaign(self, campaign_id: str, payload: Payload, headers: Headers = None):
        return self._domain("POST", f"/campaigns/{campaign_id}/fund", payload, headers)

    # ------------------------------------------------------------------
    # Channel allocations
    # ------------------------------------------------------------------
    def create_channel_allocation(self, payload: Payload, headers: Headers = None):
        return self._domain("POST", "/channel-allocations", payload, headers)

    def get_channel_allocation(self, allocation_id: str, headers: Headers = None):
        return self._domain(
            "GET", f"/channel-allocations/{allocation_id}", None, headers
        )

    def list_channel_allocations(self, headers: Headers = None, params: Params = None):
        return self._domain("GET", "/channel-allocations", None, headers, params=params)

    # ------------------------------------------------------------------
    # Sellers
    # ------------------------------------------------------------------
    def create_seller(self, payload: Payload, headers: Headers = None):
        return self._domain("POST", "/sellers", payload, headers)

    def get_seller(self, seller_id: str, headers: Headers = None):
        return self._domain("GET", f"/sellers/{seller_id}", None, headers)

    def list_sellers(self, headers: Headers = None, params: Params = None):
        return self._domain("GET", "/sellers", None, headers, params=params)

    # ------------------------------------------------------------------
    # Inventory forecasts (avails)
    # ------------------------------------------------------------------
    def create_inventory_forecast(self, payload: Payload, headers: Headers = None):
        return self._domain("POST", "/inventory-forecasts", payload, headers)

    def publish_inventory_forecast(
        self, forecast_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._domain(
            "POST",
            f"/inventory-forecasts/{forecast_id}/publish",
            {} if payload is None else payload,
            headers,
        )

    def get_inventory_forecast(self, forecast_id: str, headers: Headers = None):
        return self._domain("GET", f"/inventory-forecasts/{forecast_id}", None, headers)

    def list_inventory_forecasts(self, headers: Headers = None, params: Params = None):
        return self._domain("GET", "/inventory-forecasts", None, headers, params=params)

    # ------------------------------------------------------------------
    # Negotiations
    # ------------------------------------------------------------------
    def create_negotiation(self, payload: Payload, headers: Headers = None):
        return self._domain("POST", "/negotiations", payload, headers)

    def counter_negotiation(
        self, negotiation_id: str, payload: Payload, headers: Headers = None
    ):
        return self._domain(
            "POST", f"/negotiations/{negotiation_id}/counter", payload, headers
        )

    def revise_negotiation(
        self, negotiation_id: str, payload: Payload, headers: Headers = None
    ):
        return self._domain(
            "POST", f"/negotiations/{negotiation_id}/revise", payload, headers
        )

    def accept_negotiation(
        self, negotiation_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._domain(
            "POST",
            f"/negotiations/{negotiation_id}/accept",
            {} if payload is None else payload,
            headers,
        )

    def withdraw_negotiation(
        self, negotiation_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._domain(
            "POST",
            f"/negotiations/{negotiation_id}/withdraw",
            {} if payload is None else payload,
            headers,
        )

    def get_negotiation(self, negotiation_id: str, headers: Headers = None):
        return self._domain("GET", f"/negotiations/{negotiation_id}", None, headers)

    def list_negotiations(self, headers: Headers = None, params: Params = None):
        return self._domain("GET", "/negotiations", None, headers, params=params)

    # ------------------------------------------------------------------
    # Buys and unit lines
    # ------------------------------------------------------------------
    def add_buy_unit(self, buy_id: str, payload: Payload, headers: Headers = None):
        return self._domain("POST", f"/buys/{buy_id}/units", payload, headers)

    def place_buy(self, buy_id: str, payload: Payload, headers: Headers = None):
        return self._domain("POST", f"/buys/{buy_id}/place", payload, headers)

    def close_buy(self, buy_id: str, payload: Payload = None, headers: Headers = None):
        return self._domain(
            "POST", f"/buys/{buy_id}/close", {} if payload is None else payload, headers
        )

    def get_buy(self, buy_id: str, headers: Headers = None):
        return self._domain("GET", f"/buys/{buy_id}", None, headers)

    def list_buys(self, headers: Headers = None, params: Params = None):
        return self._domain("GET", "/buys", None, headers, params=params)

    def settle_airing(self, buy_unit_id: str, payload: Payload, headers: Headers = None):
        return self._domain(
            "POST", f"/buy-units/{buy_unit_id}/settle-airing", payload, headers
        )

    def get_buy_unit(self, buy_unit_id: str, headers: Headers = None):
        return self._domain("GET", f"/buy-units/{buy_unit_id}", None, headers)

    def list_buy_units(self, headers: Headers = None, params: Params = None):
        return self._domain("GET", "/buy-units", None, headers, params=params)

    # ------------------------------------------------------------------
    # Delivery reports
    # ------------------------------------------------------------------
    def create_delivery_report(self, payload: Payload, headers: Headers = None):
        return self._domain("POST", "/delivery-reports", payload, headers)

    def accept_delivery_report(
        self, report_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._domain(
            "POST",
            f"/delivery-reports/{report_id}/accept",
            {} if payload is None else payload,
            headers,
        )

    def dispute_delivery_report(
        self, report_id: str, payload: Payload, headers: Headers = None
    ):
        return self._domain(
            "POST", f"/delivery-reports/{report_id}/dispute", payload, headers
        )

    def get_delivery_report(self, report_id: str, headers: Headers = None):
        return self._domain("GET", f"/delivery-reports/{report_id}", None, headers)

    def list_delivery_reports(self, headers: Headers = None, params: Params = None):
        return self._domain("GET", "/delivery-reports", None, headers, params=params)

    # ------------------------------------------------------------------
    # Make-goods
    # ------------------------------------------------------------------
    def offer_make_good(self, make_good_id: str, payload: Payload, headers: Headers = None):
        return self._domain("POST", f"/make-goods/{make_good_id}/offer", payload, headers)

    def accept_make_good(
        self, make_good_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._domain(
            "POST",
            f"/make-goods/{make_good_id}/accept",
            {} if payload is None else payload,
            headers,
        )

    def reject_make_good(
        self, make_good_id: str, payload: Payload, headers: Headers = None
    ):
        return self._domain(
            "POST", f"/make-goods/{make_good_id}/reject", payload, headers
        )

    def waive_make_good(
        self, make_good_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._domain(
            "POST",
            f"/make-goods/{make_good_id}/waive",
            {} if payload is None else payload,
            headers,
        )

    def get_make_good(self, make_good_id: str, headers: Headers = None):
        return self._domain("GET", f"/make-goods/{make_good_id}", None, headers)

    def list_make_goods(self, headers: Headers = None, params: Params = None):
        return self._domain("GET", "/make-goods", None, headers, params=params)

    # ------------------------------------------------------------------
    # Rights exercises
    # ------------------------------------------------------------------
    def create_rights_exercise(self, payload: Payload, headers: Headers = None):
        return self._domain("POST", "/rights-exercises", payload, headers)

    def get_rights_exercise(self, rights_exercise_id: str, headers: Headers = None):
        return self._domain(
            "GET", f"/rights-exercises/{rights_exercise_id}", None, headers
        )

    def list_rights_exercises(self, headers: Headers = None, params: Params = None):
        return self._domain("GET", "/rights-exercises", None, headers, params=params)

    # ------------------------------------------------------------------
    # Reconciliation runs
    # ------------------------------------------------------------------
    def create_reconciliation_run(self, payload: Payload, headers: Headers = None):
        return self._domain("POST", "/reconciliation-runs", payload, headers)

    def get_reconciliation_run(self, run_id: str, headers: Headers = None):
        return self._domain("GET", f"/reconciliation-runs/{run_id}", None, headers)

    def list_reconciliation_runs(self, headers: Headers = None, params: Params = None):
        return self._domain("GET", "/reconciliation-runs", None, headers, params=params)

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------
    def create_invoice(self, payload: Payload, headers: Headers = None):
        return self._domain("POST", "/invoices", payload, headers)

    def issue_invoice(
        self, invoice_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._domain(
            "POST",
            f"/invoices/{invoice_id}/issue",
            {} if payload is None else payload,
            headers,
        )

    def record_client_payment(
        self, invoice_id: str, payload: Payload, headers: Headers = None
    ):
        return self._domain(
            "POST", f"/invoices/{invoice_id}/record-client-payment", payload, headers
        )

    def remit_seller(self, invoice_id: str, payload: Payload, headers: Headers = None):
        return self._domain(
            "POST", f"/invoices/{invoice_id}/remit-seller", payload, headers
        )

    def get_invoice(self, invoice_id: str, headers: Headers = None):
        return self._domain("GET", f"/invoices/{invoice_id}", None, headers)

    def list_invoices(self, headers: Headers = None, params: Params = None):
        return self._domain("GET", "/invoices", None, headers, params=params)

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload: Payload, headers: Headers = None):
        return self._request("POST", CLOCK_PATH, payload, headers)

    def move_clock_to(self, current_utc: str, headers: Headers = None):
        """Name the instant the logical clock should read."""
        return self.set_clock({"current_utc": current_utc}, headers)

    # ------------------------------------------------------------------
    # Path escapes, for tests that address a collection directly
    # ------------------------------------------------------------------
    def get_path(self, path: str, headers: Headers = None, params: Params = None):
        """GET an arbitrary path under the domain prefix."""
        return self._domain("GET", path, None, headers, params=params)

    def post_path(self, path: str, payload: Payload = None, headers: Headers = None):
        """POST to an arbitrary path under the domain prefix."""
        return self._domain("POST", path, {} if payload is None else payload, headers)


#: Module-level singleton the pytest fixtures expose.
api_client = ApiClient()
