"""One method per endpoint of the Residential Solar Portfolio Servicing API.

Every method returns the raw ``requests.Response`` so that tests can assert on
status codes as well as bodies. Paths are taken from PRD §4.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from . import constants as C
from .types import Headers, Payload


class ApiClient(GenericApiClient):
    """Typed facade over the servicing API."""

    # ------------------------------------------------------------------
    # Logical clock (§2.5) — "Authentication headers are not required and
    # are ignored when supplied."
    # ------------------------------------------------------------------
    def set_clock(
        self, current_utc: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", C.CLOCK_PATH, {"current_utc": current_utc}, headers
        )

    def set_clock_raw(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", C.CLOCK_PATH, payload, headers)

    # ------------------------------------------------------------------
    # Homeowners
    # ------------------------------------------------------------------
    def create_homeowner(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", C.HOMEOWNERS, payload, headers)

    def get_homeowner(
        self, homeowner_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{C.HOMEOWNERS}/{homeowner_id}", None, headers
        )

    def list_homeowners(
        self,
        headers: Optional[Headers] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", C.HOMEOWNERS, params, headers)

    # ------------------------------------------------------------------
    # Utility tariffs
    # ------------------------------------------------------------------
    def create_tariff(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", C.TARIFFS, payload, headers)

    def get_tariff(
        self, tariff_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("GET", f"{C.TARIFFS}/{tariff_id}", None, headers)

    def list_tariffs(
        self,
        headers: Optional[Headers] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", C.TARIFFS, params, headers)

    # ------------------------------------------------------------------
    # Agreements
    # ------------------------------------------------------------------
    def create_agreement(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", C.AGREEMENTS, payload, headers)

    def get_agreement(
        self, agreement_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{C.AGREEMENTS}/{agreement_id}", None, headers
        )

    def list_agreements(
        self,
        headers: Optional[Headers] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", C.AGREEMENTS, params, headers)

    def activate_agreement(
        self, agreement_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{C.AGREEMENTS}/{agreement_id}/activate", None, headers
        )

    def apply_tariff(
        self,
        agreement_id: str,
        payload: Payload,
        headers: Optional[Headers] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"{C.AGREEMENTS}/{agreement_id}/apply-tariff", payload, headers
        )

    def savings_projection(
        self, agreement_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{C.AGREEMENTS}/{agreement_id}/savings-projection",
            None,
            headers,
        )

    # ------------------------------------------------------------------
    # Production periods (metered months)
    # ------------------------------------------------------------------
    def create_period(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", C.PERIODS, payload, headers)

    def get_period(
        self, period_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("GET", f"{C.PERIODS}/{period_id}", None, headers)

    def list_periods(
        self,
        headers: Optional[Headers] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", C.PERIODS, params, headers)

    def reconcile_period(
        self,
        period_id: str,
        payload: Optional[Payload] = None,
        headers: Optional[Headers] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"{C.PERIODS}/{period_id}/reconcile", payload, headers
        )

    def reopen_period(
        self, period_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{C.PERIODS}/{period_id}/reopen", None, headers
        )

    # ------------------------------------------------------------------
    # Guarantee true-ups
    # ------------------------------------------------------------------
    def create_true_up(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", C.TRUE_UPS, payload, headers)

    def get_true_up(
        self, true_up_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("GET", f"{C.TRUE_UPS}/{true_up_id}", None, headers)

    def list_true_ups(
        self,
        headers: Optional[Headers] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", C.TRUE_UPS, params, headers)

    def post_true_up(
        self, true_up_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{C.TRUE_UPS}/{true_up_id}/post", None, headers
        )

    def void_true_up(
        self, true_up_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{C.TRUE_UPS}/{true_up_id}/void", None, headers
        )

    # ------------------------------------------------------------------
    # Outage events
    # ------------------------------------------------------------------
    def create_outage_event(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", C.OUTAGE_EVENTS, payload, headers)

    def get_outage_event(
        self, outage_event_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{C.OUTAGE_EVENTS}/{outage_event_id}", None, headers
        )

    def list_outage_events(
        self,
        headers: Optional[Headers] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", C.OUTAGE_EVENTS, params, headers)

    def triage_outage_event(
        self, outage_event_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{C.OUTAGE_EVENTS}/{outage_event_id}/triage", None, headers
        )

    def mark_false_positive(
        self, outage_event_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.OUTAGE_EVENTS}/{outage_event_id}/mark-false-positive",
            None,
            headers,
        )

    # ------------------------------------------------------------------
    # Truck rolls
    # ------------------------------------------------------------------
    def create_truck_roll(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", C.TRUCK_ROLLS, payload, headers)

    def get_truck_roll(
        self, truck_roll_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{C.TRUCK_ROLLS}/{truck_roll_id}", None, headers
        )

    def list_truck_rolls(
        self,
        headers: Optional[Headers] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", C.TRUCK_ROLLS, params, headers)

    def complete_truck_roll(
        self,
        truck_roll_id: str,
        payload: Payload,
        headers: Optional[Headers] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"{C.TRUCK_ROLLS}/{truck_roll_id}/complete", payload, headers
        )

    def cancel_truck_roll(
        self, truck_roll_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{C.TRUCK_ROLLS}/{truck_roll_id}/cancel", None, headers
        )

    # ------------------------------------------------------------------
    # Roof-work orders
    # ------------------------------------------------------------------
    def create_roof_work_order(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", C.ROOF_WORK_ORDERS, payload, headers)

    def get_roof_work_order(
        self, roof_work_order_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{C.ROOF_WORK_ORDERS}/{roof_work_order_id}", None, headers
        )

    def list_roof_work_orders(
        self,
        headers: Optional[Headers] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", C.ROOF_WORK_ORDERS, params, headers)

    def quote_roof_work_order(
        self,
        roof_work_order_id: str,
        payload: Payload,
        headers: Optional[Headers] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.ROOF_WORK_ORDERS}/{roof_work_order_id}/quote",
            payload,
            headers,
        )

    def approve_roof_work_order(
        self, roof_work_order_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.ROOF_WORK_ORDERS}/{roof_work_order_id}/approve",
            None,
            headers,
        )

    def remove_panels(
        self, roof_work_order_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.ROOF_WORK_ORDERS}/{roof_work_order_id}/remove-panels",
            None,
            headers,
        )

    def roof_complete(
        self, roof_work_order_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.ROOF_WORK_ORDERS}/{roof_work_order_id}/roof-complete",
            None,
            headers,
        )

    def reinstall(
        self, roof_work_order_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.ROOF_WORK_ORDERS}/{roof_work_order_id}/reinstall",
            None,
            headers,
        )

    def cancel_roof_work_order(
        self, roof_work_order_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.ROOF_WORK_ORDERS}/{roof_work_order_id}/cancel",
            None,
            headers,
        )

    # ------------------------------------------------------------------
    # Transfer cases
    # ------------------------------------------------------------------
    def create_transfer_case(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", C.TRANSFER_CASES, payload, headers)

    def get_transfer_case(
        self, transfer_case_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{C.TRANSFER_CASES}/{transfer_case_id}", None, headers
        )

    def list_transfer_cases(
        self,
        headers: Optional[Headers] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", C.TRANSFER_CASES, params, headers)

    def run_credit_review(
        self, transfer_case_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.TRANSFER_CASES}/{transfer_case_id}/run-credit-review",
            None,
            headers,
        )

    def clear_title(
        self, transfer_case_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.TRANSFER_CASES}/{transfer_case_id}/clear-title",
            None,
            headers,
        )

    def close_transfer_case(
        self, transfer_case_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{C.TRANSFER_CASES}/{transfer_case_id}/close", None, headers
        )

    def cancel_transfer_case(
        self, transfer_case_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{C.TRANSFER_CASES}/{transfer_case_id}/cancel", None, headers
        )

    # ------------------------------------------------------------------
    # UCC fixture filings
    # ------------------------------------------------------------------
    def create_ucc_filing(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", C.UCC_FILINGS, payload, headers)

    def get_ucc_filing(
        self, ucc_filing_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{C.UCC_FILINGS}/{ucc_filing_id}", None, headers
        )

    def list_ucc_filings(
        self,
        headers: Optional[Headers] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", C.UCC_FILINGS, params, headers)

    def request_subordination(
        self, ucc_filing_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.UCC_FILINGS}/{ucc_filing_id}/request-subordination",
            None,
            headers,
        )

    def record_subordination(
        self, ucc_filing_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.UCC_FILINGS}/{ucc_filing_id}/record-subordination",
            None,
            headers,
        )

    def request_termination(
        self, ucc_filing_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.UCC_FILINGS}/{ucc_filing_id}/request-termination",
            None,
            headers,
        )

    def terminate_ucc_filing(
        self, ucc_filing_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{C.UCC_FILINGS}/{ucc_filing_id}/terminate", None, headers
        )

    # ------------------------------------------------------------------
    # End-of-term elections
    # ------------------------------------------------------------------
    def create_election(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", C.ELECTIONS, payload, headers)

    def get_election(
        self, election_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("GET", f"{C.ELECTIONS}/{election_id}", None, headers)

    def list_elections(
        self,
        headers: Optional[Headers] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", C.ELECTIONS, params, headers)

    def accept_election(
        self, election_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{C.ELECTIONS}/{election_id}/accept", None, headers
        )

    def execute_election(
        self, election_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{C.ELECTIONS}/{election_id}/execute", None, headers
        )

    def withdraw_election(
        self, election_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{C.ELECTIONS}/{election_id}/withdraw", None, headers
        )

    # ------------------------------------------------------------------
    # Warranty claims
    # ------------------------------------------------------------------
    def create_warranty_claim(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", C.WARRANTY_CLAIMS, payload, headers)

    def get_warranty_claim(
        self, warranty_claim_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{C.WARRANTY_CLAIMS}/{warranty_claim_id}", None, headers
        )

    def list_warranty_claims(
        self,
        headers: Optional[Headers] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", C.WARRANTY_CLAIMS, params, headers)

    def submit_warranty_claim(
        self, warranty_claim_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.WARRANTY_CLAIMS}/{warranty_claim_id}/submit",
            None,
            headers,
        )

    def request_claim_info(
        self,
        warranty_claim_id: str,
        payload: Payload,
        headers: Optional[Headers] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.WARRANTY_CLAIMS}/{warranty_claim_id}/request-info",
            payload,
            headers,
        )

    def approve_warranty_claim(
        self,
        warranty_claim_id: str,
        payload: Payload,
        headers: Optional[Headers] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.WARRANTY_CLAIMS}/{warranty_claim_id}/approve",
            payload,
            headers,
        )

    def deny_warranty_claim(
        self, warranty_claim_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{C.WARRANTY_CLAIMS}/{warranty_claim_id}/deny", None, headers
        )
