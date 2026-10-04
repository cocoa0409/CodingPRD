"""API client: one method per endpoint the PRD declares.

Subclasses the framework's ``GenericApiClient`` and adds a thin method for each
route. Methods return the raw ``requests.Response`` so tests can assert status
codes themselves.
"""

from prd_bench_local_runner.testing import GenericApiClient

CLOCK_PATH = "/_clock/set_current_utc"
BASE = "/data-research"


class ApiClient(GenericApiClient):
    # ── Logical clock ──
    def set_clock(self, current_utc, headers):
        return self._request("POST", CLOCK_PATH, {"current_utc": current_utc}, headers)

    # ── Organization & User ──
    def create_organization(self, payload, headers):
        return self._request("POST", f"{BASE}/organizations", payload, headers)

    def get_organization(self, organization_id, headers):
        return self._request("GET", f"{BASE}/organizations/{organization_id}", headers=headers)

    def list_organization_users(self, organization_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/organizations/{organization_id}/users",
            payload=params, headers=headers,
        )

    def create_user(self, organization_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/organizations/{organization_id}/users", payload, headers
        )

    def get_user(self, user_id, headers):
        return self._request("GET", f"{BASE}/users/{user_id}", headers=headers)

    def list_users(self, headers, params=None):
        return self._request("GET", f"{BASE}/users", payload=params, headers=headers)

    def deactivate_user(self, user_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/users/{user_id}/deactivation", payload or {}, headers
        )

    # ── Property ──
    def create_property(self, payload, headers):
        return self._request("POST", f"{BASE}/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"{BASE}/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", f"{BASE}/properties", payload=params, headers=headers)

    def start_research(self, property_id, headers):
        return self._request("POST", f"{BASE}/properties/{property_id}/research/start", {}, headers)

    def finalize_property(self, property_id, headers):
        return self._request("POST", f"{BASE}/properties/{property_id}/finalize", {}, headers)

    def subdivide_property(self, property_id, payload, headers):
        return self._request("POST", f"{BASE}/properties/{property_id}/subdivision", payload, headers)

    def list_subdivisions(self, property_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/properties/{property_id}/subdivisions",
            payload=params, headers=headers,
        )

    # ── SourceDocument ──
    def create_source_document(self, property_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/properties/{property_id}/source-documents", payload, headers
        )

    def list_property_source_documents(self, property_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/properties/{property_id}/source-documents",
            payload=params, headers=headers,
        )

    def list_source_documents(self, headers, params=None):
        return self._request("GET", f"{BASE}/source-documents", payload=params, headers=headers)

    def get_source_document(self, source_document_id, headers):
        return self._request(
            "GET", f"{BASE}/source-documents/{source_document_id}", headers=headers
        )

    # ── PropertyAttribute ──
    def create_attribute(self, property_id, payload, headers):
        return self._request("POST", f"{BASE}/properties/{property_id}/attributes", payload, headers)

    def list_attributes(self, headers, params=None):
        return self._request("GET", f"{BASE}/attributes", payload=params, headers=headers)

    def get_attribute(self, attribute_id, headers):
        return self._request("GET", f"{BASE}/attributes/{attribute_id}", headers=headers)

    def propose_attribute(self, property_id, attribute_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/properties/{property_id}/attributes/{attribute_id}/proposals",
            payload, headers,
        )

    def verify_attribute(self, attribute_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/attributes/{attribute_id}/verifications", payload or {}, headers
        )

    def reject_attribute(self, attribute_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/attributes/{attribute_id}/rejections", payload or {}, headers
        )

    # ── LeaseComparable & SaleTransaction ──
    def create_lease_comparable(self, property_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/properties/{property_id}/lease-comparables", payload, headers
        )

    def list_lease_comparables(self, headers, params=None):
        return self._request("GET", f"{BASE}/lease-comparables", payload=params, headers=headers)

    def get_lease_comparable(self, lease_comparable_id, headers):
        return self._request(
            "GET", f"{BASE}/lease-comparables/{lease_comparable_id}", headers=headers
        )

    def create_sale_transaction(self, property_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/properties/{property_id}/sale-transactions", payload, headers
        )

    def list_sale_transactions(self, headers, params=None):
        return self._request("GET", f"{BASE}/sale-transactions", payload=params, headers=headers)

    def get_sale_transaction(self, transaction_id, headers):
        return self._request("GET", f"{BASE}/sale-transactions/{transaction_id}", headers=headers)

    def subordinate_transaction(self, transaction_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/sale-transactions/{transaction_id}/subordinations", payload, headers
        )

    # ── LicensingContract & LicenseSeat ──
    def create_contract(self, payload, headers):
        return self._request("POST", f"{BASE}/licensing-contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", f"{BASE}/licensing-contracts", payload=params, headers=headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"{BASE}/licensing-contracts/{contract_id}", headers=headers)

    def list_contract_seats(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/licensing-contracts/{contract_id}/seats",
            payload=params, headers=headers,
        )

    def create_seat(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/licensing-contracts/{contract_id}/seats", payload, headers
        )

    def activate_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/licensing-contracts/{contract_id}/activate", payload, headers
        )

    def add_contract_market(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/licensing-contracts/{contract_id}/markets", payload, headers
        )

    def renew_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/licensing-contracts/{contract_id}/renewals", payload, headers
        )

    def terminate_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/licensing-contracts/{contract_id}/terminations", payload, headers
        )

    def assign_seat(self, contract_id, seat_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/licensing-contracts/{contract_id}/seats/{seat_id}/assignment",
            payload, headers,
        )

    def unassign_seat(self, contract_id, seat_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/licensing-contracts/{contract_id}/seats/{seat_id}/unassignment",
            payload, headers,
        )

    def rebase_seat_fee(self, contract_id, seat_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/licensing-contracts/{contract_id}/seats/{seat_id}/fee-assignments",
            payload, headers,
        )

    def list_seats(self, headers, params=None):
        return self._request("GET", f"{BASE}/seats", payload=params, headers=headers)

    def get_seat(self, seat_id, headers):
        return self._request("GET", f"{BASE}/seats/{seat_id}", headers=headers)

    # ── UsageEvent ──
    def create_usage_event(self, seat_id, payload, headers):
        return self._request("POST", f"{BASE}/seats/{seat_id}/usage-events", payload, headers)

    def list_seat_usage_events(self, seat_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/seats/{seat_id}/usage-events", payload=params, headers=headers
        )

    def list_usage_events(self, headers, params=None):
        return self._request("GET", f"{BASE}/usage-events", payload=params, headers=headers)

    def get_usage_event(self, usage_event_id, headers):
        return self._request("GET", f"{BASE}/usage-events/{usage_event_id}", headers=headers)

    # ── EnforcementCase ──
    def create_enforcement_case(self, payload, headers):
        return self._request("POST", f"{BASE}/enforcement-cases", payload, headers)

    def list_enforcement_cases(self, headers, params=None):
        return self._request("GET", f"{BASE}/enforcement-cases", payload=params, headers=headers)

    def get_enforcement_case(self, case_id, headers):
        return self._request("GET", f"{BASE}/enforcement-cases/{case_id}", headers=headers)

    def list_escalations(self, case_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/enforcement-cases/{case_id}/escalations",
            payload=params, headers=headers,
        )

    def escalate_case(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/enforcement-cases/{case_id}/escalations", payload or {}, headers
        )

    def settle_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/enforcement-cases/{case_id}/settlements", payload, headers
        )

    def withdraw_case(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/enforcement-cases/{case_id}/withdrawals", payload or {}, headers
        )

    # ── Listing ──
    def create_listing(self, property_id, payload, headers):
        return self._request("POST", f"{BASE}/properties/{property_id}/listings", payload, headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", f"{BASE}/listings", payload=params, headers=headers)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"{BASE}/listings/{listing_id}", headers=headers)

    def publish_listing(self, listing_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/listings/{listing_id}/publication", payload or {}, headers
        )

    def withdraw_listing(self, listing_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/listings/{listing_id}/withdrawals", payload or {}, headers
        )

    def syndicate_listing(self, listing_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/listings/{listing_id}/syndication", payload, headers
        )

    # ── Analytics ──
    def create_index_run(self, payload, headers):
        return self._request("POST", f"{BASE}/analytics/index-runs", payload, headers)

    def list_index_runs(self, headers, params=None):
        return self._request("GET", f"{BASE}/analytics/index-runs", payload=params, headers=headers)

    def create_forecast(self, payload, headers):
        return self._request("POST", f"{BASE}/analytics/forecasts", payload, headers)

    def list_forecasts(self, headers, params=None):
        return self._request("GET", f"{BASE}/analytics/forecasts", payload=params, headers=headers)

    def remove_attribution(self, run_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/analytics/index-runs/{run_id}/attribution-removals",
            payload or {}, headers,
        )

    # ── Research operations & reports ──
    def report_market_escalations(self, payload, headers):
        return self._request("POST", f"{BASE}/reports/market-escalations", payload, headers)

    def report_subscription_reach(self, contract_id, headers):
        return self._request(
            "POST", f"{BASE}/reports/subscription-reach", {"contract_id": contract_id}, headers
        )

    def run_research_cycle(self, headers, payload=None):
        return self._request("POST", f"{BASE}/run_research_cycle", payload or {}, headers)


api_client = ApiClient()