"""API client: one method per endpoint defined in the PRD (§4)."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/motor-club"


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # --- clubs ---
    def create_club(self, payload, headers):
        return self._request("POST", f"{PREFIX}/clubs", payload, headers)

    def list_clubs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/clubs", headers=headers, params=params)

    def get_club(self, club_id, headers):
        return self._request("GET", f"{PREFIX}/clubs/{club_id}", headers=headers)

    def update_club(self, club_id, payload, headers):
        return self._request("PUT", f"{PREFIX}/clubs/{club_id}", payload, headers)

    # --- tiers ---
    def create_tier(self, payload, headers):
        return self._request("POST", f"{PREFIX}/tiers", payload, headers)

    def list_tiers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/tiers", headers=headers, params=params)

    def get_tier(self, tier_id, headers):
        return self._request("GET", f"{PREFIX}/tiers/{tier_id}", headers=headers)

    def update_tier(self, tier_id, payload, headers):
        return self._request("PUT", f"{PREFIX}/tiers/{tier_id}", payload, headers)

    # --- memberships ---
    def create_membership(self, payload, headers):
        return self._request("POST", f"{PREFIX}/memberships", payload, headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/memberships", headers=headers, params=params)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"{PREFIX}/memberships/{membership_id}", headers=headers)

    def upgrade_membership(self, membership_id, payload, headers):
        return self._request("POST", f"{PREFIX}/memberships/{membership_id}/upgrade", payload, headers)

    def downgrade_membership(self, membership_id, payload, headers):
        return self._request("POST", f"{PREFIX}/memberships/{membership_id}/downgrade", payload, headers)

    def renew_membership(self, membership_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/memberships/{membership_id}/renew", payload or {}, headers)

    def lapse_membership(self, membership_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/memberships/{membership_id}/lapse", payload or {}, headers)

    def reinstate_membership(self, membership_id, payload, headers):
        return self._request("POST", f"{PREFIX}/memberships/{membership_id}/reinstate", payload, headers)

    def cancel_membership(self, membership_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/memberships/{membership_id}/cancel", payload or {}, headers)

    def list_membership_events_for(self, membership_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/memberships/{membership_id}/membershipEvents", headers=headers, params=params)

    def list_household_members_for(self, membership_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/memberships/{membership_id}/householdMembers", headers=headers, params=params)

    def list_service_calls_for_membership(self, membership_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/memberships/{membership_id}/service-calls", headers=headers, params=params)

    def list_ancillary_sales_for_membership(self, membership_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/memberships/{membership_id}/ancillary-sales", headers=headers, params=params)

    def list_membership_events(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/membership-events", headers=headers, params=params)

    # --- household members ---
    def add_household_member(self, membership_id, payload, headers):
        return self._request("POST", f"{PREFIX}/memberships/{membership_id}/household-members", payload, headers)

    def get_household_member(self, member_id, headers):
        return self._request("GET", f"{PREFIX}/household-members/{member_id}", headers=headers)

    def update_household_member(self, member_id, payload, headers):
        return self._request("PUT", f"{PREFIX}/household-members/{member_id}", payload, headers)

    def remove_household_member(self, member_id, headers):
        return self._request("DELETE", f"{PREFIX}/household-members/{member_id}", headers=headers)

    # --- providers ---
    def create_provider(self, payload, headers):
        return self._request("POST", f"{PREFIX}/providers", payload, headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/providers", headers=headers, params=params)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"{PREFIX}/providers/{provider_id}", headers=headers)

    def update_provider(self, provider_id, payload, headers):
        return self._request("PUT", f"{PREFIX}/providers/{provider_id}", payload, headers)

    def list_truck_part_stocks_for(self, provider_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/providers/{provider_id}/truckPartStocks", headers=headers, params=params)

    def create_part_stock(self, provider_id, payload, headers):
        return self._request("POST", f"{PREFIX}/providers/{provider_id}/part-stock", payload, headers)

    def restock_part_stock(self, stock_id, payload, headers):
        return self._request("POST", f"{PREFIX}/part-stock/{stock_id}/restock", payload, headers)

    def list_truck_part_stock(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/truck-part-stock", headers=headers, params=params)

    # --- service calls ---
    def create_service_call(self, payload, headers):
        return self._request("POST", f"{PREFIX}/service-calls", payload, headers)

    def list_service_calls(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/service-calls", headers=headers, params=params)

    def get_service_call(self, call_id, headers):
        return self._request("GET", f"{PREFIX}/service-calls/{call_id}", headers=headers)

    def dispatch_service_call(self, call_id, payload, headers):
        return self._request("POST", f"{PREFIX}/service-calls/{call_id}/dispatch", payload, headers)

    def cancel_service_call(self, call_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/service-calls/{call_id}/cancel", payload or {}, headers)

    def list_dispatches_for_call(self, call_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/service-calls/{call_id}/dispatches", headers=headers, params=params)

    # --- dispatches ---
    def list_dispatches(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/dispatches", headers=headers, params=params)

    def get_dispatch(self, dispatch_id, headers):
        return self._request("GET", f"{PREFIX}/dispatches/{dispatch_id}", headers=headers)

    def accept_dispatch(self, dispatch_id, payload, headers):
        return self._request("POST", f"{PREFIX}/dispatches/{dispatch_id}/accept", payload, headers)

    def arrive_dispatch(self, dispatch_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/dispatches/{dispatch_id}/arrive", payload or {}, headers)

    def complete_dispatch(self, dispatch_id, payload, headers):
        return self._request("POST", f"{PREFIX}/dispatches/{dispatch_id}/complete", payload, headers)

    def fail_dispatch(self, dispatch_id, payload, headers):
        return self._request("POST", f"{PREFIX}/dispatches/{dispatch_id}/fail", payload, headers)

    # --- settlement ---
    def create_settlement_period(self, payload, headers):
        return self._request("POST", f"{PREFIX}/settlement-periods", payload, headers)

    def list_settlement_periods(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/settlement-periods", headers=headers, params=params)

    def get_settlement_period(self, period_id, headers):
        return self._request("GET", f"{PREFIX}/settlement-periods/{period_id}", headers=headers)

    def close_settlement_period(self, period_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/settlement-periods/{period_id}/close", payload or {}, headers)

    def assess_settlement_period(self, period_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/settlement-periods/{period_id}/assess", payload or {}, headers)

    def list_settlement_lines_for_period(self, period_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/settlement-periods/{period_id}/settlementLines", headers=headers, params=params)

    def list_settlement_lines(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/settlement-lines", headers=headers, params=params)

    def get_settlement_line(self, line_id, headers):
        return self._request("GET", f"{PREFIX}/settlement-lines/{line_id}", headers=headers)

    def reverse_settlement_line(self, line_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/settlement-lines/{line_id}/reverse", payload or {}, headers)

    # --- ancillary ---
    def create_ancillary_product(self, payload, headers):
        return self._request("POST", f"{PREFIX}/ancillary-products", payload, headers)

    def list_ancillary_products(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/ancillary-products", headers=headers, params=params)

    def get_ancillary_product(self, product_id, headers):
        return self._request("GET", f"{PREFIX}/ancillary-products/{product_id}", headers=headers)

    def update_ancillary_product(self, product_id, payload, headers):
        return self._request("PUT", f"{PREFIX}/ancillary-products/{product_id}", payload, headers)

    def create_ancillary_sale(self, payload, headers):
        return self._request("POST", f"{PREFIX}/ancillary-sales", payload, headers)

    def list_ancillary_sales(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/ancillary-sales", headers=headers, params=params)

    def get_ancillary_sale(self, sale_id, headers):
        return self._request("GET", f"{PREFIX}/ancillary-sales/{sale_id}", headers=headers)

    def refund_ancillary_sale(self, sale_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/ancillary-sales/{sale_id}/refund", payload or {}, headers)


api_client = ApiClient()
