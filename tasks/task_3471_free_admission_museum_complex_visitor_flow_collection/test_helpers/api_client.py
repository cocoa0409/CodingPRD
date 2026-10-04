"""HTTP client: one named method per operation in the PRD §4 endpoint table.

Path discipline: every business path lives under the `/campus` prefix and is
written out in full below. The single test-driving capability, the logical
clock, is mounted OUTSIDE that prefix at `/_clock/set_current_utc` (PRD §2.4),
so `set_clock` deliberately does not carry the `/campus` prefix. Do not add
prefix-composition logic here — literal paths keep the two mounts unconfusable.

Tests never build paths themselves; they call e.g. `api.admit_timed_entry_pass`
and hand the raw `requests.Response` to `validate_success` / `validate_error`.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

Json = Dict[str, Any]


def _prune(payload: Optional[Json]) -> Json:
    """Drop keys whose value is None so optional payload fields can be threaded."""
    if payload is None:
        return {}
    return {k: v for k, v in payload.items() if v is not None}


class ApiClient(GenericApiClient):
    """One method per declared operation."""

    # ── Logical clock (test-driving; OUTSIDE the /campus prefix) ─────────────
    def set_clock(self, current_utc: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc",
            payload={"current_utc": current_utc}, headers=headers,
        )

    def set_clock_raw(self, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload=payload, headers=headers)

    # ── Museums ──────────────────────────────────────────────────────────────
    def create_museum(self, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", "/campus/museums", payload=payload, headers=headers)

    def get_museum(self, museum_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", f"/campus/museums/{museum_id}", headers=headers)

    def close_museum_day(self, museum_id: str, closure_date: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request(
            "POST", f"/campus/museums/{museum_id}/close-day",
            payload={"closure_date": closure_date}, headers=headers,
        )

    # ── Timed entry passes ───────────────────────────────────────────────────
    def create_timed_entry_pass(self, museum_id: str, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", f"/campus/museums/{museum_id}/timed-entry-passes", payload=payload, headers=headers)

    def list_timed_entry_passes(self, headers: Optional[Json] = None, params: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/campus/timed-entry-passes", headers=headers, params=params)

    def get_timed_entry_pass(self, pass_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", f"/campus/timed-entry-passes/{pass_id}", headers=headers)

    def cancel_timed_entry_pass(self, pass_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", f"/campus/timed-entry-passes/{pass_id}/cancel", payload={}, headers=headers)

    def admit_timed_entry_pass(self, pass_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", f"/campus/timed-entry-passes/{pass_id}/admit", payload={}, headers=headers)

    # ── Members ──────────────────────────────────────────────────────────────
    def create_member(self, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", "/campus/members", payload=payload, headers=headers)

    def get_member(self, member_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", f"/campus/members/{member_id}", headers=headers)

    # ── Special exhibitions ──────────────────────────────────────────────────
    def create_exhibition(self, museum_id: str, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", f"/campus/museums/{museum_id}/exhibitions", payload=payload, headers=headers)

    def get_exhibition(self, exhibition_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", f"/campus/exhibitions/{exhibition_id}", headers=headers)

    def list_exhibitions(self, headers: Optional[Json] = None, params: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/campus/exhibitions", headers=headers, params=params)

    def open_exhibition_sale(self, exhibition_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", f"/campus/exhibitions/{exhibition_id}/open-sale", payload={}, headers=headers)

    def close_exhibition(self, exhibition_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", f"/campus/exhibitions/{exhibition_id}/close", payload={}, headers=headers)

    # ── Exhibition tickets ───────────────────────────────────────────────────
    def purchase_ticket(self, exhibition_id: str, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", f"/campus/exhibitions/{exhibition_id}/tickets", payload=payload, headers=headers)

    def get_ticket(self, ticket_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", f"/campus/tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers: Optional[Json] = None, params: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/campus/tickets", headers=headers, params=params)

    def refund_ticket(self, ticket_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", f"/campus/tickets/{ticket_id}/refund", payload={}, headers=headers)

    def redeem_ticket(self, ticket_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", f"/campus/tickets/{ticket_id}/redeem", payload={}, headers=headers)

    # ── Docents ──────────────────────────────────────────────────────────────
    def create_docent(self, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", "/campus/docents", payload=payload, headers=headers)

    def get_docent(self, docent_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", f"/campus/docents/{docent_id}", headers=headers)

    # ── Education programs ───────────────────────────────────────────────────
    def create_education_program(self, museum_id: str, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", f"/campus/museums/{museum_id}/education-programs", payload=payload, headers=headers)

    def list_education_programs(self, headers: Optional[Json] = None, params: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/campus/education-programs", headers=headers, params=params)

    def get_education_program(self, program_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", f"/campus/education-programs/{program_id}", headers=headers)

    def cancel_education_program(self, program_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", f"/campus/education-programs/{program_id}/cancel", payload={}, headers=headers)

    # ── Docent assignments ───────────────────────────────────────────────────
    def create_docent_assignment(self, program_id: str, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", f"/campus/education-programs/{program_id}/docent-assignments", payload=payload, headers=headers)

    def list_docent_assignments(self, headers: Optional[Json] = None, params: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/campus/docent-assignments", headers=headers, params=params)

    def get_docent_assignment(self, assignment_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", f"/campus/docent-assignments/{assignment_id}", headers=headers)

    def confirm_docent_assignment(self, assignment_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", f"/campus/docent-assignments/{assignment_id}/confirm", payload={}, headers=headers)

    # ── School group reservations ────────────────────────────────────────────
    def create_school_reservation(self, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", "/campus/school-reservations", payload=payload, headers=headers)

    def list_school_reservations(self, headers: Optional[Json] = None, params: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/campus/school-reservations", headers=headers, params=params)

    def get_school_reservation(self, reservation_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", f"/campus/school-reservations/{reservation_id}", headers=headers)

    def cancel_school_reservation(self, reservation_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", f"/campus/school-reservations/{reservation_id}/cancel", payload={}, headers=headers)

    # ── Collection objects ───────────────────────────────────────────────────
    def create_collection_object(self, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", "/campus/collection-objects", payload=payload, headers=headers)

    def get_collection_object(self, object_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", f"/campus/collection-objects/{object_id}", headers=headers)

    def release_conservation(self, object_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", f"/campus/collection-objects/{object_id}/release-conservation", payload={}, headers=headers)

    # ── Loan agreements ──────────────────────────────────────────────────────
    def create_loan_agreement(self, object_id: str, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", f"/campus/collection-objects/{object_id}/loan-agreements", payload=payload, headers=headers)

    def list_loan_agreements(self, headers: Optional[Json] = None, params: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/campus/loan-agreements", headers=headers, params=params)

    def get_loan_agreement(self, loan_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", f"/campus/loan-agreements/{loan_id}", headers=headers)

    def counter_loan_agreement(self, loan_id: str, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", f"/campus/loan-agreements/{loan_id}/counter", payload=_prune(payload), headers=headers)

    def accept_loan_agreement(self, loan_id: str, expected_loan_version: int, headers: Optional[Json] = None) -> requests.Response:
        return self._request(
            "POST", f"/campus/loan-agreements/{loan_id}/accept",
            payload={"expected_loan_version": expected_loan_version}, headers=headers,
        )

    def activate_loan_agreement(self, loan_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", f"/campus/loan-agreements/{loan_id}/activate", payload={}, headers=headers)

    def close_loan_agreement(self, loan_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", f"/campus/loan-agreements/{loan_id}/close", payload={}, headers=headers)

    # ── Condition reports ────────────────────────────────────────────────────
    def create_condition_report(self, loan_id: str, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", f"/campus/loan-agreements/{loan_id}/condition-reports", payload=payload, headers=headers)

    def list_condition_reports(self, headers: Optional[Json] = None, params: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/campus/condition-reports", headers=headers, params=params)

    def get_condition_report(self, report_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", f"/campus/condition-reports/{report_id}", headers=headers)

    def decide_condition_report(self, report_id: str, outcome: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request(
            "POST", f"/campus/condition-reports/{report_id}/decide",
            payload={"outcome": outcome}, headers=headers,
        )

    # ── Collection reviews ───────────────────────────────────────────────────
    def create_collection_review(self, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", "/campus/collection-reviews", payload=_prune(payload), headers=headers)

    def list_collection_reviews(self, headers: Optional[Json] = None, params: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/campus/collection-reviews", headers=headers, params=params)

    def get_collection_review(self, review_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", f"/campus/collection-reviews/{review_id}", headers=headers)

    def submit_collection_review(self, review_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", f"/campus/collection-reviews/{review_id}/submit", payload={}, headers=headers)

    def decide_collection_review(self, review_id: str, outcome: str, expected_review_version: int, headers: Optional[Json] = None) -> requests.Response:
        return self._request(
            "POST", f"/campus/collection-reviews/{review_id}/decide",
            payload={"outcome": outcome, "expected_review_version": expected_review_version},
            headers=headers,
        )

    def execute_collection_review(self, review_id: str, payload: Optional[Json] = None, headers: Optional[Json] = None) -> requests.Response:
        return self._request(
            "POST", f"/campus/collection-reviews/{review_id}/execute",
            payload=_prune(payload), headers=headers,
        )

    # ── Fund accounts ────────────────────────────────────────────────────────
    def create_fund(self, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", "/campus/funds", payload=payload, headers=headers)

    def get_fund(self, fund_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", f"/campus/funds/{fund_id}", headers=headers)

    def set_fund_status(self, fund_id: str, status: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request(
            "POST", f"/campus/funds/{fund_id}/set-status",
            payload={"status": status}, headers=headers,
        )

    # ── Expenditures ─────────────────────────────────────────────────────────
    def create_expenditure(self, fund_id: str, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", f"/campus/funds/{fund_id}/expenditures", payload=payload, headers=headers)

    def list_expenditures(self, headers: Optional[Json] = None, params: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/campus/expenditures", headers=headers, params=params)

    def get_expenditure(self, expenditure_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", f"/campus/expenditures/{expenditure_id}", headers=headers)

    def void_expenditure(self, expenditure_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", f"/campus/expenditures/{expenditure_id}/void", payload={}, headers=headers)

    # ── Research access requests ─────────────────────────────────────────────
    def create_research_access_request(self, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", "/campus/research-access-requests", payload=payload, headers=headers)

    def list_research_access_requests(self, headers: Optional[Json] = None, params: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/campus/research-access-requests", headers=headers, params=params)

    def get_research_access_request(self, request_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", f"/campus/research-access-requests/{request_id}", headers=headers)

    def decide_research_access_request(self, request_id: str, outcome: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request(
            "POST", f"/campus/research-access-requests/{request_id}/decide",
            payload={"outcome": outcome}, headers=headers,
        )


api_client = ApiClient()
