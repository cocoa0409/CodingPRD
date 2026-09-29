"""HTTP client with one method per documented endpoint.

Each method returns the raw ``requests.Response`` so tests can assert on the
status code as well as the envelope. Query filters and pagination parameters are
passed through ``params``.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/sourcing"


class ApiClient(GenericApiClient):
    """Endpoint-per-method client for the Meeting Venue Sourcing & RFP API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Rate benchmarks
    # ------------------------------------------------------------------
    def create_rate_benchmark(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/rate-benchmarks", payload, headers)

    def get_rate_benchmark(self, benchmark_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/rate-benchmarks/{benchmark_id}", None, headers
        )

    def list_rate_benchmarks(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{PREFIX}/rate-benchmarks", params, headers)

    # ------------------------------------------------------------------
    # Venues and the supplier master
    # ------------------------------------------------------------------
    def create_venue(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/venues", payload, headers)

    def update_venue_preferred_status(
        self, venue_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"{PREFIX}/venues/{venue_id}/preferred-status", payload, headers
        )

    def get_venue(self, venue_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/venues/{venue_id}", None, headers)

    def list_venues(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{PREFIX}/venues", params, headers)

    # ------------------------------------------------------------------
    # Supplier performance reviews
    # ------------------------------------------------------------------
    def create_performance_review(
        self, venue_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/venues/{venue_id}/performance-reviews", payload, headers
        )

    def get_performance_review(self, review_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/performance-reviews/{review_id}", None, headers
        )

    def list_performance_reviews(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{PREFIX}/performance-reviews", params, headers)

    # ------------------------------------------------------------------
    # Meeting events
    # ------------------------------------------------------------------
    def create_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/events", payload, headers)

    def lock_event_requirements(self, event_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/events/{event_id}/lock-requirements", {}, headers
        )

    def get_event(self, event_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/events/{event_id}", None, headers)

    def list_events(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{PREFIX}/events", params, headers)

    # ------------------------------------------------------------------
    # Shortlist entries
    # ------------------------------------------------------------------
    def create_shortlist_entry(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/events/{event_id}/shortlist-entries", payload, headers
        )

    def shortlist_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/shortlist-entries/{entry_id}/shortlist", {}, headers
        )

    def eliminate_shortlist_entry(
        self, entry_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/shortlist-entries/{entry_id}/eliminate", payload, headers
        )

    def get_shortlist_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/shortlist-entries/{entry_id}", None, headers
        )

    def list_shortlist_entries(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{PREFIX}/shortlist-entries", params, headers)

    # ------------------------------------------------------------------
    # Site inspections
    # ------------------------------------------------------------------
    def create_site_inspection(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/site-inspections", payload, headers)

    def complete_site_inspection(
        self, inspection_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/site-inspections/{inspection_id}/complete",
            payload,
            headers,
        )

    def cancel_site_inspection(
        self, inspection_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/site-inspections/{inspection_id}/cancel", payload, headers
        )

    def get_site_inspection(self, inspection_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/site-inspections/{inspection_id}", None, headers
        )

    def list_site_inspections(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{PREFIX}/site-inspections", params, headers)

    # ------------------------------------------------------------------
    # Solicitation rounds
    # ------------------------------------------------------------------
    def create_rfp(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/events/{event_id}/rfps", payload, headers
        )

    def issue_rfp(self, rfp_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/rfps/{rfp_id}/issue", {}, headers)

    def close_rfp(self, rfp_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/rfps/{rfp_id}/close", {}, headers)

    def get_rfp(self, rfp_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/rfps/{rfp_id}", None, headers)

    def list_rfps(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{PREFIX}/rfps", params, headers)

    # ------------------------------------------------------------------
    # Bids
    # ------------------------------------------------------------------
    def submit_proposal(
        self, proposal_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/proposals/{proposal_id}/submit", payload, headers
        )

    def decline_proposal(self, proposal_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/proposals/{proposal_id}/decline", {}, headers
        )

    def withdraw_proposal(self, proposal_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/proposals/{proposal_id}/withdraw", {}, headers
        )

    def evaluate_proposal(
        self, proposal_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/proposals/{proposal_id}/evaluate", payload, headers
        )

    def create_counter(
        self, proposal_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/proposals/{proposal_id}/counters", payload, headers
        )

    def revise_proposal(
        self, proposal_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/proposals/{proposal_id}/revise", payload, headers
        )

    def get_proposal(self, proposal_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/proposals/{proposal_id}", None, headers)

    def list_proposals(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{PREFIX}/proposals", params, headers)

    def list_bid_evaluations(
        self,
        proposal_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"{PREFIX}/proposals/{proposal_id}/bid-evaluations", params, headers
        )

    def list_negotiation_counters(
        self,
        proposal_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/proposals/{proposal_id}/negotiation-counters",
            params,
            headers,
        )

    def get_cost_comparison(
        self,
        event_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"{PREFIX}/events/{event_id}/cost-comparison", params, headers
        )

    # ------------------------------------------------------------------
    # Award and contracts
    # ------------------------------------------------------------------
    def award_event(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/events/{event_id}/award", payload, headers
        )

    def get_contract(self, contract_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/contracts/{contract_id}", None, headers)

    def list_contracts(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{PREFIX}/contracts", params, headers)

    def route_approvals(self, contract_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/contracts/{contract_id}/route-approvals", {}, headers
        )

    def list_approval_steps(
        self,
        contract_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"{PREFIX}/contracts/{contract_id}/approval-steps", params, headers
        )

    def get_approval_step(self, step_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/approval-steps/{step_id}", None, headers
        )

    def decide_approval_step(
        self, step_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/approval-steps/{step_id}/decide", payload, headers
        )

    def sign_contract(
        self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/contracts/{contract_id}/sign", payload, headers
        )

    def countersign_contract(
        self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/contracts/{contract_id}/countersign", payload, headers
        )

    def terminate_contract(
        self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/contracts/{contract_id}/terminate", payload, headers
        )

    # ------------------------------------------------------------------
    # Deposits
    # ------------------------------------------------------------------
    def generate_deposit_schedule(self, contract_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/contracts/{contract_id}/deposit-schedule", {}, headers
        )

    def list_deposit_installments(
        self,
        contract_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/contracts/{contract_id}/deposit-installments",
            params,
            headers,
        )

    def get_deposit_installment(self, installment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/deposit-installments/{installment_id}", None, headers
        )

    def pay_deposit_installment(
        self, installment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/deposit-installments/{installment_id}/pay",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Post-event closeout
    # ------------------------------------------------------------------
    def create_post_event_report(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/events/{event_id}/post-event-report", payload, headers
        )

    def get_post_event_report(self, report_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/post-event-reports/{report_id}", None, headers
        )

    def list_post_event_reports(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{PREFIX}/post-event-reports", params, headers)


api_client = ApiClient()
