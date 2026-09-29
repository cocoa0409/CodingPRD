"""One method per endpoint of the Markdown Optimization & Season Exit API.

Every path is absolute from the server root, exactly as listed in PRD section 4.
Methods return the raw ``requests.Response`` so tests can assert status codes.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for every capability in PRD section 4."""

    # ==================================================================
    # Logical clock
    # ==================================================================
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ==================================================================
    # Seasons
    # ==================================================================
    def list_seasons(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/seasons", params, headers)

    def get_season(self, season_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/seasons/{season_id}", None, headers)

    def create_season(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/seasons", payload, headers)

    def transition_season(
        self, season_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/seasons/{season_id}/transition", payload, headers
        )

    def list_season_allowance_agreements(
        self,
        season_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/seasons/{season_id}/allowance-agreements", params, headers
        )

    def list_season_exit_reviews(
        self,
        season_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/seasons/{season_id}/exit-reviews", params, headers
        )

    def create_exit_review(
        self, season_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/seasons/{season_id}/exit-reviews", payload, headers
        )

    def create_clearance_allocation(
        self, season_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/seasons/{season_id}/clearance-allocations", payload, headers
        )

    # ==================================================================
    # Exit reviews
    # ==================================================================
    def list_exit_reviews(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/exit-reviews", params, headers)

    def get_exit_review(
        self, exit_review_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/exit-reviews/{exit_review_id}", None, headers)

    # ==================================================================
    # Price zones
    # ==================================================================
    def list_price_zones(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/price-zones", params, headers)

    def get_price_zone(
        self, price_zone_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/price-zones/{price_zone_id}", None, headers)

    def create_price_zone(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/price-zones", payload, headers)

    # ==================================================================
    # Stores
    # ==================================================================
    def list_stores(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/stores", params, headers)

    def get_store(self, store_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/stores/{store_id}", None, headers)

    def create_store(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/stores", payload, headers)

    def update_store(
        self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"/stores/{store_id}", payload, headers)

    # ==================================================================
    # Items
    # ==================================================================
    def list_items(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/items", params, headers)

    def get_item(self, item_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/items/{item_id}", None, headers)

    def create_item(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/items", payload, headers)

    def list_item_sales_weeks(
        self,
        item_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", f"/items/{item_id}/sales-weeks", params, headers)

    def post_sales_week(
        self, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/items/{item_id}/sales-weeks", payload, headers)

    def list_item_elasticity_estimates(
        self,
        item_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/items/{item_id}/elasticity-estimates", params, headers
        )

    # ==================================================================
    # Sales weeks
    # ==================================================================
    def list_sales_weeks(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/sales-weeks", params, headers)

    def get_sales_week(
        self, sales_week_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/sales-weeks/{sales_week_id}", None, headers)

    # ==================================================================
    # Elasticity estimates
    # ==================================================================
    def list_elasticity_estimates(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/elasticity-estimates", params, headers)

    def get_elasticity_estimate(
        self, estimate_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/elasticity-estimates/{estimate_id}", None, headers
        )

    def create_elasticity_estimate(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/elasticity-estimates", payload, headers)

    def certify_elasticity_estimate(
        self, estimate_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/elasticity-estimates/{estimate_id}/certify", payload, headers
        )

    # ==================================================================
    # Markdown plans
    # ==================================================================
    def list_markdown_plans(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/markdown-plans", params, headers)

    def get_markdown_plan(
        self, markdown_plan_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/markdown-plans/{markdown_plan_id}", None, headers)

    def create_markdown_plan(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/markdown-plans", payload, headers)

    def list_plan_steps(
        self,
        markdown_plan_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/markdown-plans/{markdown_plan_id}/steps", params, headers
        )

    def create_markdown_step(
        self, markdown_plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/markdown-plans/{markdown_plan_id}/steps", payload, headers
        )

    def submit_markdown_plan(
        self, markdown_plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/markdown-plans/{markdown_plan_id}/submit", payload, headers
        )

    def request_plan_revision(
        self, markdown_plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/markdown-plans/{markdown_plan_id}/request-revision",
            payload,
            headers,
        )

    def reopen_markdown_plan(
        self, markdown_plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/markdown-plans/{markdown_plan_id}/reopen", payload, headers
        )

    def approve_markdown_plan(
        self, markdown_plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/markdown-plans/{markdown_plan_id}/approve", payload, headers
        )

    # ==================================================================
    # Markdown steps (ladder rungs)
    # ==================================================================
    def list_markdown_steps(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/markdown-steps", params, headers)

    def get_markdown_step(
        self, markdown_step_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/markdown-steps/{markdown_step_id}", None, headers)

    # ==================================================================
    # Zone executions
    # ==================================================================
    def list_zone_executions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/zone-executions", params, headers)

    def get_zone_execution(
        self, zone_execution_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/zone-executions/{zone_execution_id}", None, headers
        )

    def create_zone_execution(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/zone-executions", payload, headers)

    def post_signage(
        self, zone_execution_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/zone-executions/{zone_execution_id}/post-signage", payload, headers
        )

    def verify_signage(
        self, zone_execution_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/zone-executions/{zone_execution_id}/verify-signage",
            payload,
            headers,
        )

    def apply_zone_execution(
        self, zone_execution_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/zone-executions/{zone_execution_id}/apply", payload, headers
        )

    def roll_back_zone_execution(
        self, zone_execution_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/zone-executions/{zone_execution_id}/roll-back", payload, headers
        )

    # ==================================================================
    # Clearance reservations
    # ==================================================================
    def list_clearance_reservations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/clearance-reservations", params, headers)

    def get_clearance_reservation(
        self, reservation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/clearance-reservations/{reservation_id}", None, headers
        )

    def release_clearance_reservation(
        self, reservation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/clearance-reservations/{reservation_id}/release", payload, headers
        )

    # ==================================================================
    # Vendor allowance agreements
    # ==================================================================
    def list_allowance_agreements(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/allowance-agreements", params, headers)

    def get_allowance_agreement(
        self, agreement_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/allowance-agreements/{agreement_id}", None, headers
        )

    def create_allowance_agreement(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/allowance-agreements", payload, headers)

    def counter_allowance_agreement(
        self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/allowance-agreements/{agreement_id}/counter", payload, headers
        )

    def accept_allowance_agreement(
        self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/allowance-agreements/{agreement_id}/accept", payload, headers
        )

    # ==================================================================
    # Vendor claims
    # ==================================================================
    def list_vendor_claims(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/vendor-claims", params, headers)

    def get_vendor_claim(
        self, claim_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/vendor-claims/{claim_id}", None, headers)

    def create_vendor_claim(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/vendor-claims", payload, headers)

    def recognize_vendor_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/vendor-claims/{claim_id}/recognize", payload, headers
        )

    def reverse_vendor_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/vendor-claims/{claim_id}/reverse", payload, headers
        )

    # ==================================================================
    # Disposition orders
    # ==================================================================
    def list_disposition_orders(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/disposition-orders", params, headers)

    def get_disposition_order(
        self, disposition_order_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/disposition-orders/{disposition_order_id}", None, headers
        )

    def create_disposition_order(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/disposition-orders", payload, headers)

    def approve_disposition_order(
        self, disposition_order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/disposition-orders/{disposition_order_id}/approve",
            payload,
            headers,
        )

    def settle_disposition_order(
        self, disposition_order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/disposition-orders/{disposition_order_id}/settle",
            payload,
            headers,
        )

    def cancel_disposition_order(
        self, disposition_order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/disposition-orders/{disposition_order_id}/cancel",
            payload,
            headers,
        )


# Module-level singleton shared by the whole suite.
api_client = ApiClient()
