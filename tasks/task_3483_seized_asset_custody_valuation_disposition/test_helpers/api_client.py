"""API client: one method per endpoint defined in the PRD.

Every business resource lives under the ``/custody`` prefix (PRD §4); the
single test-driving clock endpoint ``POST /_clock/set_current_utc`` lives
outside that prefix (PRD §2.4) and is the only method here that does not
start with ``/custody``.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed wrapper over the seized-asset custody and disposition surface."""

    # ─── Logical clock (PRD §2.4 — OUTSIDE the /custody prefix) ────────────

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Seizure cases (PRD §3.1) ───────────────────────────────────────────

    def create_case(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/custody/cases", payload, headers)

    def get_case(self, case_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/custody/cases/{case_id}", headers=headers)

    def list_case_assets(
        self, case_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/custody/cases/{case_id}/assets", headers=headers, params=params
        )

    def list_case_distributions(
        self, case_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/custody/cases/{case_id}/distributions",
            headers=headers, params=params,
        )

    def file_forfeiture(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/custody/cases/{case_id}/file-forfeiture", {}, headers
        )

    def forfeit_case(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/custody/cases/{case_id}/forfeit", {}, headers
        )

    def dismiss_case(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/custody/cases/{case_id}/dismiss", {}, headers
        )

    # ─── Assets (PRD §3.2) ──────────────────────────────────────────────────

    def create_asset(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/custody/assets", payload, headers)

    def get_asset(self, asset_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/custody/assets/{asset_id}", headers=headers)

    def list_asset_custody_transfers(
        self, asset_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/custody/assets/{asset_id}/custody-transfers",
            headers=headers, params=params,
        )

    def list_asset_valuations(
        self, asset_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/custody/assets/{asset_id}/valuations",
            headers=headers, params=params,
        )

    def list_asset_expense_entries(
        self, asset_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/custody/assets/{asset_id}/expense-entries",
            headers=headers, params=params,
        )

    def list_asset_interlocutory_sale_requests(
        self, asset_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/custody/assets/{asset_id}/interlocutory-sale-requests",
            headers=headers, params=params,
        )

    def list_asset_third_party_interests(
        self, asset_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/custody/assets/{asset_id}/third-party-interests",
            headers=headers, params=params,
        )

    def list_asset_sale_events(
        self, asset_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/custody/assets/{asset_id}/sale-events",
            headers=headers, params=params,
        )

    # ─── Asset disposition and return actions (PRD §3.3, §3.8) ──────────────

    def decide_retention(self, asset_id: str, decision: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/custody/assets/{asset_id}/decide-retention",
            {"decision": decision}, headers,
        )

    def authorize_sale(self, asset_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/custody/assets/{asset_id}/authorize-sale", {}, headers
        )

    def initiate_return(self, asset_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/custody/assets/{asset_id}/initiate-return", {}, headers
        )

    def complete_return(
        self, asset_id: str, return_condition_grade: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/custody/assets/{asset_id}/complete-return",
            {"return_condition_grade": return_condition_grade}, headers,
        )

    def dispute_return(
        self, asset_id: str, claimed_depreciation_cents: int, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/custody/assets/{asset_id}/dispute-return",
            {"claimed_depreciation_cents": claimed_depreciation_cents}, headers,
        )

    def resolve_return_dispute(
        self, asset_id: str, final_depreciation_cents: int, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/custody/assets/{asset_id}/resolve-return-dispute",
            {"final_depreciation_cents": final_depreciation_cents}, headers,
        )

    # ─── Custody transfers (PRD §3.2) ───────────────────────────────────────

    def create_custody_transfer(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/custody/custody-transfers", payload, headers)

    def complete_custody_transfer(
        self, transfer_id: str, condition_on_arrival: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/custody/custody-transfers/{transfer_id}/complete",
            {"condition_on_arrival": condition_on_arrival}, headers,
        )

    # ─── Valuations (PRD §3.3) ──────────────────────────────────────────────

    def create_valuation(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/custody/valuations", payload, headers)

    def adjudicate_valuation(
        self, valuation_id: str, outcome: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/custody/valuations/{valuation_id}/adjudicate",
            {"outcome": outcome}, headers,
        )

    # ─── Expense ledger (PRD §3.4) ──────────────────────────────────────────

    def create_expense_entry(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/custody/expense-entries", payload, headers)

    # ─── Interlocutory sale requests (PRD §3.4) ─────────────────────────────

    def create_interlocutory_sale_request(
        self, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", "/custody/interlocutory-sale-requests", payload, headers
        )

    def adjudicate_interlocutory_sale_request(
        self, request_id: str, outcome: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/custody/interlocutory-sale-requests/{request_id}/adjudicate",
            {"outcome": outcome}, headers,
        )

    # ─── Third-party interests (PRD §3.5) ───────────────────────────────────

    def create_third_party_interest(self, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", "/custody/third-party-interests", payload, headers
        )

    def adjudicate_third_party_interest(
        self, interest_id: str, outcome: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/custody/third-party-interests/{interest_id}/adjudicate",
            {"outcome": outcome}, headers,
        )

    def appeal_third_party_interest(
        self, interest_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/custody/third-party-interests/{interest_id}/appeal",
            {}, headers,
        )

    # ─── Sale events (PRD §3.6) ─────────────────────────────────────────────

    def create_sale_event(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/custody/sale-events", payload, headers)

    def close_sale_event(
        self, event_id: str, winning_bid_cents: int, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/custody/sale-events/{event_id}/close",
            {"winning_bid_cents": winning_bid_cents}, headers,
        )

    def settle_sale_event(self, event_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/custody/sale-events/{event_id}/settle", {}, headers
        )

    # ─── Distributions (PRD §3.7) ───────────────────────────────────────────

    def create_distribution(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/custody/distributions", payload, headers)

    def approve_distribution(self, distribution_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/custody/distributions/{distribution_id}/approve", {}, headers
        )

    def rescind_distribution(self, distribution_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/custody/distributions/{distribution_id}/rescind", {}, headers
        )

    # ─── Holding-review checkpoint (PRD §3.4) ───────────────────────────────

    def run_holding_review(self, headers: Dict[str, str]):
        return self._request("POST", "/custody/run-holding-review", {}, headers)


def create_api_client(base_url: Optional[str] = None) -> ApiClient:
    """Build an ApiClient. A factory, not a module-level singleton, so that
    ``import test_helpers.api_client`` always binds this module itself."""
    return ApiClient(base_url)
