"""API client: one method per endpoint in the PRD's endpoint table (PRD §4)."""
from typing import Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/impact-program"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------ clock
    def set_clock(self, to_iso8601: str, headers: Optional[dict] = None):
        """Set the logical clock; drives season, freeze and vesting transitions."""
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers or {},
        )

    def roll_seasons(self, to_iso8601: str, headers: Optional[dict] = None):
        """Roll the logical clock to a season boundary without asserting on it."""
        return self._request(
            "POST", "/_seasons/roll", {"to_iso8601": to_iso8601}, headers or {},
        )

    def healthz(self, headers=None):
        return self._request("GET", "/_healthz", headers=headers or {})

    # ----------------------------------------------------------- giving partner
    def create_giving_partner(self, payload, headers):
        return self._request("POST", f"{PREFIX}/giving-partners", payload, headers)

    def list_giving_partners(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/giving-partners", params, headers)

    def get_giving_partner(self, partner_id, headers):
        return self._request("GET", f"{PREFIX}/giving-partners/{partner_id}", headers=headers)

    def update_giving_partner(self, partner_id, payload, headers):
        return self._request("PUT", f"{PREFIX}/giving-partners/{partner_id}", payload, headers)

    def set_partner_status(self, partner_id, payload, headers):
        return self._request("PUT", f"{PREFIX}/giving-partners/{partner_id}/status", payload, headers)

    def get_partner_attributed_units(self, partner_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/giving-partners/{partner_id}/attributed-units", params, headers
        )

    def get_partner_return_exposure(self, partner_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/giving-partners/{partner_id}/return-exposure", params, headers
        )

    # --------------------------------------------------------- capacity profile
    def create_capacity_profile(self, partner_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/giving-partners/{partner_id}/capacity-profiles", payload, headers
        )

    def list_partner_capacity_profiles(self, partner_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/giving-partners/{partner_id}/capacity-profiles", params, headers
        )

    def list_capacity_profiles(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/capacity-profiles", params, headers)

    def get_capacity_profile(self, profile_id, headers):
        return self._request("GET", f"{PREFIX}/capacity-profiles/{profile_id}", headers=headers)

    # ----------------------------------------------------------- vetting round
    def list_partner_vetting_rounds(self, partner_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/giving-partners/{partner_id}/vetting-rounds", params, headers
        )

    def list_vetting_rounds(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/vetting-rounds", params, headers)

    def get_vetting_round(self, vetting_id, headers):
        return self._request("GET", f"{PREFIX}/vetting-rounds/{vetting_id}", headers=headers)

    def update_vetting_round(self, vetting_id, payload, headers):
        return self._request("PUT", f"{PREFIX}/vetting-rounds/{vetting_id}", payload, headers)

    def approve_vetting_round(self, vetting_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/vetting-rounds/{vetting_id}/approve", payload, headers
        )

    def reject_vetting_round(self, vetting_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/vetting-rounds/{vetting_id}/reject", payload, headers
        )

    def reopen_vetting_round(self, vetting_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/vetting-rounds/{vetting_id}/reopen", payload, headers
        )

    # ------------------------------------------------------- donation product
    def create_donation_product(self, payload, headers):
        return self._request("POST", f"{PREFIX}/donation-products", payload, headers)

    def list_donation_products(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/donation-products", params, headers)

    def get_donation_product(self, product_id, headers):
        return self._request("GET", f"{PREFIX}/donation-products/{product_id}", headers=headers)

    def update_donation_product(self, product_id, payload, headers):
        return self._request("PUT", f"{PREFIX}/donation-products/{product_id}", payload, headers)

    def activate_donation_product(self, product_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/donation-products/{product_id}/activate", payload, headers
        )

    def create_product_line(self, product_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/donation-products/{product_id}/lines", payload, headers
        )

    def list_product_lines(self, product_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/donation-products/{product_id}/lines", params, headers
        )

    def list_donation_product_lines(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/donation-product-lines", params, headers)

    def get_donation_product_line(self, line_id, headers):
        return self._request("GET", f"{PREFIX}/donation-product-lines/{line_id}", headers=headers)

    def update_donation_product_line(self, line_id, payload, headers):
        return self._request(
            "PUT", f"{PREFIX}/donation-product-lines/{line_id}", payload, headers
        )

    def list_product_liabilities(self, product_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/donation-products/{product_id}/liabilities", params, headers
        )

    def list_product_claims(self, product_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/donation-products/{product_id}/claims", params, headers
        )

    # ----------------------------------------------------------- impact season
    def create_impact_season(self, payload, headers):
        return self._request("POST", f"{PREFIX}/impact-seasons", payload, headers)

    def list_impact_seasons(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/impact-seasons", params, headers)

    def get_impact_season(self, season_id, headers):
        return self._request("GET", f"{PREFIX}/impact-seasons/{season_id}", headers=headers)

    def set_season_frozen_state(self, season_id, payload, headers):
        return self._request(
            "PUT", f"{PREFIX}/impact-seasons/{season_id}/frozen-state", payload, headers
        )

    def close_season(self, season_id, payload, headers):
        return self._request("POST", f"{PREFIX}/impact-seasons/{season_id}/close", payload, headers)

    def reopen_season(self, season_id, payload, headers):
        return self._request("POST", f"{PREFIX}/impact-seasons/{season_id}/reopen", payload, headers)

    def list_season_allocations(self, season_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/impact-seasons/{season_id}/allocations", params, headers
        )

    def list_season_distributions(self, season_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/impact-seasons/{season_id}/distributions", params, headers
        )

    def list_season_claims(self, season_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/impact-seasons/{season_id}/claims", params, headers)

    def list_season_liabilities(self, season_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/impact-seasons/{season_id}/liabilities", params, headers
        )

    def list_season_audits(self, season_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/impact-seasons/{season_id}/audits", params, headers)

    def get_season_summary(self, season_id, headers):
        return self._request("GET", f"{PREFIX}/impact-seasons/{season_id}/summary", headers=headers)

    # ------------------------------------------------------------ allocation
    def commit_allocation_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/allocation-plans/{plan_id}/commit", payload, headers
        )

    def allocate_allocation_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/allocation-plans/{plan_id}/allocate", payload, headers
        )

    def revert_allocation_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/allocation-plans/{plan_id}/revert", payload, headers
        )

    def get_allocation_plan(self, plan_id, headers):
        return self._request("GET", f"{PREFIX}/allocation-plans/{plan_id}", headers=headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/allocations", params, headers)

    def list_partner_allocations(self, partner_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/giving-partners/{partner_id}/allocations", params, headers
        )

    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"{PREFIX}/allocations/{allocation_id}", headers=headers)

    def approve_allocation(self, allocation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/allocations/{allocation_id}/approve", payload, headers
        )

    def cancel_allocation(self, allocation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/allocations/{allocation_id}/cancel", payload, headers
        )

    def reallocate_allocation(self, allocation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/allocations/{allocation_id}/reallocations", payload, headers
        )

    def reverse_allocation(self, allocation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/allocations/{allocation_id}/reversals", payload, headers
        )

    # ----------------------------------------------------------- distribution
    def create_distribution(self, allocation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/allocations/{allocation_id}/distributions", payload, headers
        )

    def list_allocation_distributions(self, allocation_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/allocations/{allocation_id}/distributions", params, headers
        )

    def list_distributions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/distributions", params, headers)

    def get_distribution(self, distribution_id, headers):
        return self._request("GET", f"{PREFIX}/distributions/{distribution_id}", headers=headers)

    def create_receipt(self, distribution_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/distributions/{distribution_id}/receipts", payload, headers
        )

    def complete_distribution(self, distribution_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/distributions/{distribution_id}/complete", payload, headers
        )

    def raise_discrepancy(self, distribution_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/distributions/{distribution_id}/discrepancies", payload, headers
        )

    def write_off_distribution(self, distribution_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/distributions/{distribution_id}/write-off", payload, headers
        )

    def void_distribution(self, distribution_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/distributions/{distribution_id}/void", payload, headers
        )

    # ------------------------------------------------------------ sales order
    def create_sales_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sales-orders", payload, headers)

    def list_sales_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sales-orders", params, headers)

    def get_sales_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/sales-orders/{order_id}", headers=headers)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/sales-orders/{order_id}/lines", payload, headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/sales-orders/{order_id}/lines", params, headers)

    def get_order_line(self, order_id, line_id, headers):
        return self._request(
            "GET", f"{PREFIX}/sales-orders/{order_id}/lines/{line_id}", headers=headers
        )

    def list_sales_order_lines(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sales-order-lines", params, headers)

    def get_sales_order_line(self, line_id, headers):
        return self._request("GET", f"{PREFIX}/sales-order-lines/{line_id}", headers=headers)

    def pay_order(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/sales-orders/{order_id}/pay", payload, headers)

    def settle_line(self, order_id, line_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sales-orders/{order_id}/lines/{line_id}/settle", payload, headers
        )

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/sales-orders/{order_id}/cancel", payload, headers)

    def update_fulfillment(self, order_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/sales-orders/{order_id}/fulfillment", payload, headers
        )

    def open_line_return_request(self, order_id, line_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/sales-orders/{order_id}/lines/{line_id}/return-requests",
            payload, headers,
        )

    def exempt_line(self, order_id, line_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sales-orders/{order_id}/lines/{line_id}/exempt", payload, headers
        )

    def list_line_return_requests(self, order_id, line_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/sales-orders/{order_id}/lines/{line_id}/return-requests",
            params, headers,
        )

    # ---------------------------------------------------------- return request
    def create_return_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/return-requests", payload, headers)

    def list_return_requests(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/return-requests", params, headers)

    def get_return_request(self, return_id, headers):
        return self._request("GET", f"{PREFIX}/return-requests/{return_id}", headers=headers)

    def approve_return_request(self, return_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/return-requests/{return_id}/approve", payload, headers
        )

    def reject_return_request(self, return_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/return-requests/{return_id}/reject", payload, headers
        )

    def credit_return_request(self, return_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/return-requests/{return_id}/credit", payload, headers
        )

    # -------------------------------------------------------------- liability
    def list_liabilities(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/liabilities", params, headers)

    def get_liability(self, liability_id, headers):
        return self._request("GET", f"{PREFIX}/liabilities/{liability_id}", headers=headers)

    def unfreeze_liability(self, liability_id, payload, headers):
        return self._request(
            "PUT", f"{PREFIX}/liabilities/{liability_id}/unfreeze", payload, headers
        )

    def carry_forward_liability(self, liability_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/liabilities/{liability_id}/carry-forward", payload, headers
        )

    # -------------------------------------------------------- marketing claim
    def create_marketing_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/marketing-claims", payload, headers)

    def list_marketing_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/marketing-claims", params, headers)

    def get_marketing_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/marketing-claims/{claim_id}", headers=headers)

    def substantiate_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/marketing-claims/{claim_id}/substantiate", payload, headers
        )

    def derive_build_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/marketing-claims/{claim_id}/derive-build", payload, headers
        )

    def revoke_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/marketing-claims/{claim_id}/revoke", payload, headers
        )

    # ----------------------------------------------------------- impact audit
    def create_impact_audit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/impact-audits", payload, headers)

    def list_impact_audits(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/impact-audits", params, headers)

    def get_impact_audit(self, audit_id, headers):
        return self._request("GET", f"{PREFIX}/impact-audits/{audit_id}", headers=headers)

    def start_audit(self, audit_id, payload, headers):
        return self._request("POST", f"{PREFIX}/impact-audits/{audit_id}/start", payload, headers)

    def finalize_audit(self, audit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/impact-audits/{audit_id}/finalize", payload, headers
        )

    def reopen_audit(self, audit_id, payload, headers):
        return self._request("POST", f"{PREFIX}/impact-audits/{audit_id}/reopen", payload, headers)

    def get_audit_summary(self, audit_id, headers):
        return self._request("GET", f"{PREFIX}/impact-audits/{audit_id}/summary", headers=headers)


api_client = ApiClient()

# The evaluator restarts the server before every pytest test while this module
# keeps a single shared client, so a pooled keep-alive connection can still
# reference the previous process and raise ConnectionResetError on the first
# request of the next test.  Re-reading the server also cannot serve a stale
# 5xx, so each request is retried once on a fresh connection.
_ORIGINAL_REQUEST = ApiClient._request


def _request_with_connection_retry(self, *args, **kwargs):
    try:
        return _ORIGINAL_REQUEST(self, *args, **kwargs)
    except (ConnectionResetError, requests.exceptions.ConnectionError):
        self.session.close()
        self.session = requests.Session()
        return _ORIGINAL_REQUEST(self, *args, **kwargs)


ApiClient._request = _request_with_connection_retry