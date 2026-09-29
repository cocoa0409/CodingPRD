"""HTTP client for the hotel night-audit revenue verification API.

One method per endpoint the PRD declares. Every method returns the raw
requests.Response so that tests can assert on the status line as well as the
envelope. Nothing here unwraps the envelope: that is the validators' job.
"""

from typing import Any, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH
from .types import Headers, Payload


def _prune(payload: Optional[Payload]) -> Optional[Payload]:
    """Drop keys whose value is the _OMIT sentinel, keeping explicit nulls."""
    if payload is None:
        return None
    return {k: v for k, v in payload.items() if v is not OMIT}


class _Omit:
    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<OMIT>"


OMIT = _Omit()


class NightAuditApiClient(GenericApiClient):
    """Endpoint methods for the night-audit API."""

    # ---------------------------------------------------------------- clock

    def set_clock(self, current_utc: str, headers: Headers) -> requests.Response:
        return self._request("POST", CLOCK_PATH, {"current_utc": current_utc}, headers)

    def set_clock_raw(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", CLOCK_PATH, payload, headers)

    # ------------------------------------------------------------ properties

    def create_property(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/properties", _prune(payload), headers)

    def get_property(self, property_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/properties/{property_id}", None, headers)

    def list_properties(self, headers: Headers, **params: Any) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/properties", _prune(params), headers)

    # --------------------------------------------------------------- outlets

    def create_outlet(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/outlets", _prune(payload), headers)

    def get_outlet(self, outlet_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/outlets/{outlet_id}", None, headers)

    def list_outlets(self, headers: Headers, **params: Any) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/outlets", _prune(params), headers)

    def suspend_outlet(self, outlet_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/outlets/{outlet_id}/suspend", {}, headers
        )

    # --------------------------------------------------- accounting periods

    def get_accounting_period(self, period_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/accounting-periods/{period_id}", None, headers
        )

    def list_accounting_periods(self, headers: Headers, **params: Any) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/accounting-periods", _prune(params), headers
        )

    def tie_out_period(
        self, period_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/accounting-periods/{period_id}/tie-out",
            _prune(payload),
            headers,
        )

    # -------------------------------------------------------- business dates

    def create_business_date(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/business-dates", _prune(payload), headers
        )

    def get_business_date(self, business_date_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/business-dates/{business_date_id}", None, headers
        )

    def list_business_dates(self, headers: Headers, **params: Any) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/business-dates", _prune(params), headers
        )

    def post_room_and_tax(self, business_date_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/business-dates/{business_date_id}/post-room-and-tax",
            {},
            headers,
        )

    def seal_charges(self, business_date_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/business-dates/{business_date_id}/seal-charges",
            {},
            headers,
        )

    def verify_settlements(self, business_date_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/business-dates/{business_date_id}/verify-settlements",
            {},
            headers,
        )

    def city_ledger_sweep(self, business_date_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/business-dates/{business_date_id}/city-ledger-sweep",
            {},
            headers,
        )

    def balance_business_date(self, business_date_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/business-dates/{business_date_id}/balance",
            {},
            headers,
        )

    def close_business_date(self, business_date_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/business-dates/{business_date_id}/close", {}, headers
        )

    def reopen_business_date(self, business_date_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/business-dates/{business_date_id}/reopen", {}, headers
        )

    # ---------------------------------------------------------------- folios

    def create_folio(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/folios", _prune(payload), headers)

    def get_folio(self, folio_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/folios/{folio_id}", None, headers)

    def list_folios(self, headers: Headers, **params: Any) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/folios", _prune(params), headers)

    def check_in(self, folio_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/folios/{folio_id}/check-in", {}, headers
        )

    def check_out(
        self, folio_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/folios/{folio_id}/check-out", _prune(payload), headers
        )

    def cancel_folio(self, folio_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/folios/{folio_id}/cancel", {}, headers
        )

    def post_payment(
        self, folio_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/folios/{folio_id}/payments", _prune(payload), headers
        )

    # ------------------------------------------------------ journal postings

    def create_journal_posting(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/journal-postings", _prune(payload), headers
        )

    def get_journal_posting(self, posting_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/journal-postings/{posting_id}", None, headers
        )

    def list_journal_postings(self, headers: Headers, **params: Any) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/journal-postings", _prune(params), headers
        )

    def reverse_journal_posting(
        self, posting_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/journal-postings/{posting_id}/reverse",
            _prune(payload) if payload is not None else {},
            headers,
        )

    # --------------------------------------------------------- outlet tickets

    def create_outlet_ticket(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/outlet-tickets", _prune(payload), headers
        )

    def get_outlet_ticket(self, ticket_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/outlet-tickets/{ticket_id}", None, headers
        )

    def list_outlet_tickets(self, headers: Headers, **params: Any) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/outlet-tickets", _prune(params), headers
        )

    def close_outlet_ticket(
        self, ticket_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/outlet-tickets/{ticket_id}/close",
            _prune(payload) if payload is not None else {},
            headers,
        )

    def void_outlet_ticket(self, ticket_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/outlet-tickets/{ticket_id}/void", {}, headers
        )

    # ------------------------------------------------------ settlement batches

    def create_settlement_batch(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/settlement-batches", _prune(payload), headers
        )

    def get_settlement_batch(self, batch_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/settlement-batches/{batch_id}", None, headers
        )

    def list_settlement_batches(self, headers: Headers, **params: Any) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/settlement-batches", _prune(params), headers
        )

    def request_recount(self, batch_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/settlement-batches/{batch_id}/request-recount",
            {},
            headers,
        )

    def redeclare_batch(
        self, batch_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/settlement-batches/{batch_id}/redeclare",
            _prune(payload),
            headers,
        )

    def accept_variance(self, batch_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/settlement-batches/{batch_id}/accept-variance",
            {},
            headers,
        )

    # -------------------------------------------------------- ledger accounts

    def create_ledger_account(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/ledger-accounts", _prune(payload), headers
        )

    def get_ledger_account(self, account_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/ledger-accounts/{account_id}", None, headers
        )

    def list_ledger_accounts(self, headers: Headers, **params: Any) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/ledger-accounts", _prune(params), headers
        )

    # ------------------------------------------------------------- allowances

    def create_allowance(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/allowances", _prune(payload), headers)

    def get_allowance(self, allowance_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/allowances/{allowance_id}", None, headers
        )

    def list_allowances(self, headers: Headers, **params: Any) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/allowances", _prune(params), headers)

    def submit_allowance(
        self, allowance_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/allowances/{allowance_id}/submit",
            _prune(payload) if payload is not None else {},
            headers,
        )

    def approve_allowance(
        self, allowance_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/allowances/{allowance_id}/approve",
            _prune(payload),
            headers,
        )

    def reject_allowance(self, allowance_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/allowances/{allowance_id}/reject", {}, headers
        )

    def return_allowance_for_revision(
        self, allowance_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/allowances/{allowance_id}/return-for-revision",
            {},
            headers,
        )

    def reverse_allowance(self, allowance_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/allowances/{allowance_id}/reverse", {}, headers
        )

    # ------------------------------------------------ authorization documents

    def create_authorization_document(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/authorization-documents", _prune(payload), headers
        )

    def get_authorization_document(self, document_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/authorization-documents/{document_id}", None, headers
        )

    def list_authorization_documents(self, headers: Headers, **params: Any) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/authorization-documents", _prune(params), headers
        )

    def review_authorization_document(
        self, document_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/authorization-documents/{document_id}/review",
            _prune(payload),
            headers,
        )

    def revoke_authorization_document(
        self, document_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/authorization-documents/{document_id}/revoke",
            {},
            headers,
        )

    # ------------------------------------------------------ card authorizations

    def create_card_authorization(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/card-authorizations", _prune(payload), headers
        )

    def get_card_authorization(self, authorization_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/card-authorizations/{authorization_id}", None, headers
        )

    def list_card_authorizations(self, headers: Headers, **params: Any) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/card-authorizations", _prune(params), headers
        )

    def decline_card_authorization(
        self, authorization_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/card-authorizations/{authorization_id}/decline",
            _prune(payload),
            headers,
        )

    def capture_card_authorization(
        self, authorization_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/card-authorizations/{authorization_id}/capture",
            _prune(payload),
            headers,
        )

    def follow_up_card_authorization(
        self, authorization_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/card-authorizations/{authorization_id}/follow-up",
            _prune(payload),
            headers,
        )

    # --------------------------------------------------------- revenue reports

    def create_revenue_report(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/revenue-reports", _prune(payload), headers
        )

    def get_revenue_report(self, report_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/revenue-reports/{report_id}", None, headers
        )

    def list_revenue_reports(self, headers: Headers, **params: Any) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/revenue-reports", _prune(params), headers
        )

    def distribute_revenue_report(
        self, report_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/revenue-reports/{report_id}/distribute",
            _prune(payload) if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------- raw

    def raw_post(self, path: str, payload: Any, headers: Headers) -> requests.Response:
        """Escape hatch for shape tests that must send a non-object body."""
        return self._request("POST", path, payload, headers)

    def raw_get(self, path: str, headers: Headers, **params: Any) -> requests.Response:
        return self._request("GET", path, _prune(params), headers)
