"""API client: one method per endpoint in the PRD routing table (PRD section 4).

Every endpoint is mounted at the root; there is no shared API prefix.

The client also owns timestamp canonicalisation.  PRD 2.4 requires ISO 8601 UTC
form with three fractional digits, but a caller comparing a stamp it supplied
("2026-08-01T00:00:00Z") against a stamp the server echoed
("2026-08-01T00:00:00.000Z") must not fail on the sub-second width alone.  Tests
therefore compare timestamps through canonical_ts()/same_instant() rather than by
raw string equality.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


# --------------------------------------------------------------------------- #
# Timestamp canonicalisation                                                   #
# --------------------------------------------------------------------------- #
def parse_ts(value: str) -> datetime:
    """Parse any ISO 8601 UTC instant the API may emit or accept."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def canonical_ts(value: str) -> str:
    """Normalise an instant to `YYYY-MM-DDTHH:MM:SS.mmmZ` for comparison."""
    moment = parse_ts(value)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def same_instant(left: str, right: str) -> bool:
    """True when two ISO 8601 strings denote the same UTC instant."""
    return parse_ts(left) == parse_ts(right)


def iso_z(moment: datetime) -> str:
    """Render a datetime as a whole-second `...Z` instant the API accepts."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shift(value: str, **delta) -> str:
    """Return the instant `value` moved by the given timedelta keywords."""
    return iso_z(parse_ts(value) + timedelta(**delta))


class ApiClient(GenericApiClient):
    """One method per PRD endpoint."""

    # ---------------- logical clock (PRD 2.4) ----------------
    def set_clock(self, current_utc: str, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: Any, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---------------- branches (PRD 3.1) ----------------
    def create_branch(self, payload, headers):
        return self._request("POST", "/branches", payload, headers)

    def get_branch(self, branch_id, headers):
        return self._request("GET", f"/branches/{branch_id}", headers=headers)

    def list_branches(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/branches", headers=headers, params=params)

    def get_rate_board(self, branch_id, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/branches/{branch_id}/rate-board", headers=headers, params=params
        )

    # ---------------- currency profiles (PRD 2.10, 3.1) ----------------
    def create_currency(self, payload, headers):
        return self._request("POST", "/currencies", payload, headers)

    def get_currency(self, iso_code, headers):
        return self._request("GET", f"/currencies/{iso_code}", headers=headers)

    def list_currencies(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/currencies", headers=headers, params=params)

    # ---------------- wholesale rates (PRD 3.2) ----------------
    def create_wholesale_rate(self, payload, headers):
        return self._request("POST", "/wholesale-rates", payload, headers)

    def get_wholesale_rate(self, rate_id, headers):
        return self._request("GET", f"/wholesale-rates/{rate_id}", headers=headers)

    def list_wholesale_rates(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/wholesale-rates", headers=headers, params=params)

    # ---------------- travel corridors (PRD 3.3) ----------------
    def create_travel_corridor(self, payload, headers):
        return self._request("POST", "/travel-corridors", payload, headers)

    def get_travel_corridor(self, corridor_id, headers):
        return self._request("GET", f"/travel-corridors/{corridor_id}", headers=headers)

    def list_travel_corridors(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/travel-corridors", headers=headers, params=params)

    # ---------------- armored routes (PRD 3.1) ----------------
    def create_armored_route(self, payload, headers):
        return self._request("POST", "/armored-routes", payload, headers)

    def get_armored_route(self, route_id, headers):
        return self._request("GET", f"/armored-routes/{route_id}", headers=headers)

    def list_armored_routes(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/armored-routes", headers=headers, params=params)

    # ---------------- rate cards (PRD 3.2) ----------------
    def create_rate_card(self, payload, headers):
        return self._request("POST", "/rate-cards", payload, headers)

    def publish_rate_card(self, card_id, headers):
        return self._request("POST", f"/rate-cards/{card_id}/publish", {}, headers)

    def get_rate_card(self, card_id, headers):
        return self._request("GET", f"/rate-cards/{card_id}", headers=headers)

    def list_rate_cards(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/rate-cards", headers=headers, params=params)

    # ---------------- inventory positions (PRD 3.4) ----------------
    def create_inventory_position(self, payload, headers):
        return self._request("POST", "/inventory-positions", payload, headers)

    def get_inventory_position(self, position_id, headers):
        return self._request(
            "GET", f"/inventory-positions/{position_id}", headers=headers
        )

    def list_inventory_positions(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", "/inventory-positions", headers=headers, params=params
        )

    # ---------------- inventory plans (PRD 3.3) ----------------
    def create_inventory_plan(self, payload, headers):
        return self._request("POST", "/inventory-plans", payload, headers)

    def submit_inventory_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/inventory-plans/{plan_id}/submit", payload, headers
        )

    def review_inventory_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/inventory-plans/{plan_id}/review", payload, headers
        )

    def activate_inventory_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/inventory-plans/{plan_id}/activate", {}, headers
        )

    def get_inventory_plan(self, plan_id, headers):
        return self._request("GET", f"/inventory-plans/{plan_id}", headers=headers)

    def list_inventory_plans(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/inventory-plans", headers=headers, params=params)

    # ---------------- customers (PRD 3.5, 3.6) ----------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def compliance_hold(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/customers/{customer_id}/compliance-hold", payload, headers
        )

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/customers", headers=headers, params=params)

    # ---------------- exchange transactions (PRD 3.5) ----------------
    def create_exchange_transaction(self, payload, headers):
        return self._request("POST", "/exchange-transactions", payload, headers)

    def authorize_transaction(self, txn_id, headers):
        return self._request(
            "POST", f"/exchange-transactions/{txn_id}/authorize", {}, headers
        )

    def settle_transaction(self, txn_id, headers):
        return self._request(
            "POST", f"/exchange-transactions/{txn_id}/settle", {}, headers
        )

    def void_transaction(self, txn_id, payload, headers):
        return self._request(
            "POST", f"/exchange-transactions/{txn_id}/void", payload, headers
        )

    def reverse_transaction(self, txn_id, payload, headers):
        return self._request(
            "POST", f"/exchange-transactions/{txn_id}/reverse", payload, headers
        )

    def compliance_decision(self, txn_id, payload, headers):
        return self._request(
            "POST",
            f"/exchange-transactions/{txn_id}/compliance-decision",
            payload,
            headers,
        )

    def get_exchange_transaction(self, txn_id, headers):
        return self._request("GET", f"/exchange-transactions/{txn_id}", headers=headers)

    def list_exchange_transactions(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", "/exchange-transactions", headers=headers, params=params
        )

    # ---------------- buy-back contracts (PRD 3.7) ----------------
    def create_buyback_contract(self, payload, headers):
        return self._request("POST", "/buyback-contracts", payload, headers)

    def redeem_buyback_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/buyback-contracts/{contract_id}/redeem", payload, headers
        )

    def cancel_buyback_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/buyback-contracts/{contract_id}/cancel", payload, headers
        )

    def get_buyback_contract(self, contract_id, headers):
        return self._request("GET", f"/buyback-contracts/{contract_id}", headers=headers)

    def list_buyback_contracts(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/buyback-contracts", headers=headers, params=params)

    # ---------------- note assessments (PRD 3.8) ----------------
    def create_note_assessment(self, payload, headers):
        return self._request("POST", "/note-assessments", payload, headers)

    def assess_note_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/note-assessments/{assessment_id}/assess", payload, headers
        )

    def get_note_assessment(self, assessment_id, headers):
        return self._request("GET", f"/note-assessments/{assessment_id}", headers=headers)

    def list_note_assessments(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/note-assessments", headers=headers, params=params)

    # ---------------- compliance reports (PRD 3.6) ----------------
    def file_compliance_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/compliance-reports/{report_id}/file", payload, headers
        )

    def amend_compliance_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/compliance-reports/{report_id}/amend", payload, headers
        )

    def get_compliance_report(self, report_id, headers):
        return self._request(
            "GET", f"/compliance-reports/{report_id}", headers=headers
        )

    def list_compliance_reports(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", "/compliance-reports", headers=headers, params=params
        )

    # ---------------- cash shipments (PRD 3.9) ----------------
    def create_cash_shipment(self, payload, headers):
        return self._request("POST", "/cash-shipments", payload, headers)

    def schedule_cash_shipment(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/cash-shipments/{shipment_id}/schedule", payload, headers
        )

    def dispatch_cash_shipment(self, shipment_id, headers):
        return self._request(
            "POST", f"/cash-shipments/{shipment_id}/dispatch", {}, headers
        )

    def arrive_cash_shipment(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/cash-shipments/{shipment_id}/arrive", payload, headers
        )

    def reconcile_cash_shipment(self, shipment_id, headers):
        return self._request(
            "POST", f"/cash-shipments/{shipment_id}/reconcile", {}, headers
        )

    def get_cash_shipment(self, shipment_id, headers):
        return self._request("GET", f"/cash-shipments/{shipment_id}", headers=headers)

    def list_cash_shipments(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/cash-shipments", headers=headers, params=params)


api_client = ApiClient()
