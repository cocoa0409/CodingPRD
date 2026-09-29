"""API client: one method per endpoint of the Destination Sales API.

Every endpoint is mounted at the root path -- there is no versioning prefix.
Timestamp echoes are canonicalised by :func:`canonical_instant` so a server
rendering three fractional digits and a test literal written without them
still compare equal.
"""
import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?Z$"
)


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO-8601 UTC instant to exactly three fractional digits.

    The PRD renders instants with exactly three fractional digits; test
    literals are often written without them.  Comparing canonical forms keeps
    sub-second width out of the assertion.
    """
    if not isinstance(value, str):
        return value
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return value
    day, hms, frac = m.group(1), m.group(2), m.group(3) or ""
    frac = (frac + "000")[:3]
    return f"{day}T{hms}.{frac}Z"


def same_instant(left: Optional[str], right: Optional[str]) -> bool:
    """True when two ISO-8601 UTC instants denote the same moment."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    # ---- logical clock ----------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def set_clock_raw(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- meeting planners -------------------------------------------------
    def create_meeting_planner(self, payload, headers):
        return self._request("POST", "/meeting-planners", payload, headers)

    def get_meeting_planner(self, planner_id, headers):
        return self._request("GET", f"/meeting-planners/{planner_id}", headers=headers)

    def list_meeting_planners(self, headers, params=None):
        return self._request("GET", "/meeting-planners", headers=headers, params=params)

    # ---- hotels -----------------------------------------------------------
    def create_hotel(self, payload, headers):
        return self._request("POST", "/hotels", payload, headers)

    def get_hotel(self, hotel_id, headers):
        return self._request("GET", f"/hotels/{hotel_id}", headers=headers)

    def list_hotels(self, headers, params=None):
        return self._request("GET", "/hotels", headers=headers, params=params)

    def set_hotel_participation(self, hotel_id, payload, headers):
        return self._request(
            "POST", f"/hotels/{hotel_id}/participation", payload, headers
        )

    # ---- center halls -----------------------------------------------------
    def create_center_hall(self, payload, headers):
        return self._request("POST", "/center-halls", payload, headers)

    def get_center_hall(self, hall_id, headers):
        return self._request("GET", f"/center-halls/{hall_id}", headers=headers)

    def list_center_halls(self, headers, params=None):
        return self._request("GET", "/center-halls", headers=headers, params=params)

    # ---- incentive funds --------------------------------------------------
    def create_incentive_fund(self, payload, headers):
        return self._request("POST", "/incentive-funds", payload, headers)

    def get_incentive_fund(self, fund_id, headers):
        return self._request("GET", f"/incentive-funds/{fund_id}", headers=headers)

    def list_incentive_funds(self, headers, params=None):
        return self._request("GET", "/incentive-funds", headers=headers, params=params)

    def create_lodging_tax_receipt(self, fund_id, payload, headers):
        return self._request(
            "POST", f"/incentive-funds/{fund_id}/lodging-tax-receipts", payload, headers
        )

    def list_lodging_tax_receipts(self, fund_id, headers, params=None):
        return self._request(
            "GET",
            f"/incentive-funds/{fund_id}/lodging-tax-receipts",
            headers=headers,
            params=params,
        )

    def list_fund_incentive_decisions(self, fund_id, headers, params=None):
        return self._request(
            "GET",
            f"/incentive-funds/{fund_id}/incentive-decisions",
            headers=headers,
            params=params,
        )

    # ---- opportunities ----------------------------------------------------
    def create_opportunity(self, payload, headers):
        return self._request("POST", "/opportunities", payload, headers)

    def get_opportunity(self, opportunity_id, headers):
        return self._request("GET", f"/opportunities/{opportunity_id}", headers=headers)

    def list_opportunities(self, headers, params=None):
        return self._request("GET", "/opportunities", headers=headers, params=params)

    def qualify_opportunity(self, opportunity_id, headers, payload=None):
        return self._request(
            "POST", f"/opportunities/{opportunity_id}/qualify", payload or {}, headers
        )

    def lose_opportunity(self, opportunity_id, payload, headers):
        return self._request(
            "POST", f"/opportunities/{opportunity_id}/lose", payload, headers
        )

    def list_opportunity_estimates(self, opportunity_id, headers, params=None):
        return self._request(
            "GET",
            f"/opportunities/{opportunity_id}/economic-impact-estimates",
            headers=headers,
            params=params,
        )

    def list_opportunity_servicing_orders(self, opportunity_id, headers, params=None):
        return self._request(
            "GET",
            f"/opportunities/{opportunity_id}/servicing-orders",
            headers=headers,
            params=params,
        )

    # ---- space holds ------------------------------------------------------
    def create_space_hold(self, payload, headers):
        return self._request("POST", "/space-holds", payload, headers)

    def get_space_hold(self, hold_id, headers):
        return self._request("GET", f"/space-holds/{hold_id}", headers=headers)

    def list_space_holds(self, headers, params=None):
        return self._request("GET", "/space-holds", headers=headers, params=params)

    def challenge_space_hold(self, hold_id, payload, headers):
        return self._request(
            "POST", f"/space-holds/{hold_id}/challenge", payload, headers
        )

    def release_space_hold(self, hold_id, headers, payload=None):
        return self._request(
            "POST", f"/space-holds/{hold_id}/release", payload or {}, headers
        )

    def run_space_hold_expiry(self, headers, payload=None):
        return self._request("POST", "/space-hold-expiry-runs", payload or {}, headers)

    # ---- room block commitments ------------------------------------------
    def create_room_block_commitment(self, payload, headers):
        return self._request("POST", "/room-block-commitments", payload, headers)

    def get_room_block_commitment(self, commitment_id, headers):
        return self._request(
            "GET", f"/room-block-commitments/{commitment_id}", headers=headers
        )

    def list_room_block_commitments(self, headers, params=None):
        return self._request(
            "GET", "/room-block-commitments", headers=headers, params=params
        )

    def offer_room_block_commitment(self, commitment_id, payload, headers):
        return self._request(
            "POST", f"/room-block-commitments/{commitment_id}/offer", payload, headers
        )

    def commit_room_block_commitment(self, commitment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/room-block-commitments/{commitment_id}/commit",
            payload or {},
            headers,
        )

    def withdraw_room_block_commitment(self, commitment_id, payload, headers):
        return self._request(
            "POST",
            f"/room-block-commitments/{commitment_id}/withdraw",
            payload,
            headers,
        )

    def create_pickup_record(self, commitment_id, payload, headers):
        return self._request(
            "POST",
            f"/room-block-commitments/{commitment_id}/pickup-records",
            payload,
            headers,
        )

    def list_pickup_records(self, commitment_id, headers, params=None):
        return self._request(
            "GET",
            f"/room-block-commitments/{commitment_id}/pickup-records",
            headers=headers,
            params=params,
        )

    # ---- bid packages -----------------------------------------------------
    def create_bid_package(self, payload, headers):
        return self._request("POST", "/bid-packages", payload, headers)

    def get_bid_package(self, bid_id, headers):
        return self._request("GET", f"/bid-packages/{bid_id}", headers=headers)

    def list_bid_packages(self, headers, params=None):
        return self._request("GET", "/bid-packages", headers=headers, params=params)

    def create_support_letter(self, bid_id, payload, headers):
        return self._request(
            "POST", f"/bid-packages/{bid_id}/support-letters", payload, headers
        )

    def list_support_letters(self, bid_id, headers, params=None):
        return self._request(
            "GET",
            f"/bid-packages/{bid_id}/support-letters",
            headers=headers,
            params=params,
        )

    def request_incentive(self, bid_id, payload, headers):
        return self._request(
            "POST", f"/bid-packages/{bid_id}/request-incentive", payload, headers
        )

    def create_incentive_decision(self, bid_id, payload, headers):
        return self._request(
            "POST", f"/bid-packages/{bid_id}/incentive-decisions", payload, headers
        )

    def list_bid_incentive_decisions(self, bid_id, headers, params=None):
        return self._request(
            "GET",
            f"/bid-packages/{bid_id}/incentive-decisions",
            headers=headers,
            params=params,
        )

    def submit_bid_package(self, bid_id, payload, headers):
        return self._request(
            "POST", f"/bid-packages/{bid_id}/submit", payload, headers
        )

    def planner_response(self, bid_id, payload, headers):
        return self._request(
            "POST", f"/bid-packages/{bid_id}/planner-response", payload, headers
        )

    # ---- economic impact estimates ---------------------------------------
    def create_economic_impact_estimate(self, payload, headers):
        return self._request("POST", "/economic-impact-estimates", payload, headers)

    # ---- servicing orders -------------------------------------------------
    def create_servicing_order(self, payload, headers):
        return self._request("POST", "/servicing-orders", payload, headers)

    def get_servicing_order(self, order_id, headers):
        return self._request("GET", f"/servicing-orders/{order_id}", headers=headers)

    def schedule_servicing_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/servicing-orders/{order_id}/schedule", payload, headers
        )

    def deliver_servicing_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/servicing-orders/{order_id}/deliver", payload, headers
        )

    def cancel_servicing_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/servicing-orders/{order_id}/cancel", payload or {}, headers
        )

    # ---- board reports ----------------------------------------------------
    def create_board_report(self, payload, headers):
        return self._request("POST", "/board-reports", payload, headers)

    def get_board_report(self, report_id, headers):
        return self._request("GET", f"/board-reports/{report_id}", headers=headers)

    def list_board_reports(self, headers, params=None):
        return self._request("GET", "/board-reports", headers=headers, params=params)

    def publish_board_report(self, report_id, headers, payload=None):
        return self._request(
            "POST", f"/board-reports/{report_id}/publish", payload or {}, headers
        )


api_client = ApiClient()
