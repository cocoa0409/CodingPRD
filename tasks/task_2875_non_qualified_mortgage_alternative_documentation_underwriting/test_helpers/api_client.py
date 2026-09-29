"""Typed HTTP client for the non-QM alt-doc underwriting API.

One method per endpoint declared in PRD 4. Every method returns the raw
``requests.Response`` so tests can assert on status codes as well as bodies.

Envelope contract used by this whole suite (decided once, here):
``validate_success`` / ``get_success_data`` return the INNER ``data`` payload,
so no assertion helper and no test ever indexes ``["data"]`` a second time.

Timestamp canonicalisation also lives here (``canonical_instant``) so that a
server emitting ``2026-10-29T00:00:00.000Z`` and one emitting
``2026-10-29T00:00:00Z`` compare equal for instant-valued fields.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO-8601 instant to ``YYYY-MM-DDTHH:MM:SS.mmmZ``.

    Accepts a trailing ``Z`` or a numeric UTC offset and any (or no) number of
    fractional digits. Returns the input unchanged when it cannot be parsed so
    that a malformed value still fails its assertion visibly.
    """
    if value is None:
        return None
    raw = value.strip()
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return raw
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.") + f"{parsed.microsecond // 1000:03d}Z"


class ApiClient(GenericApiClient):
    """One method per PRD 4 endpoint."""

    # --- Documentation programs -------------------------------------------
    def create_program(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/documentation-programs", payload, headers)

    def get_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/documentation-programs/{program_id}", None, headers)

    # --- Investor overlays ------------------------------------------------
    def create_overlay(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/investor-overlays", payload, headers)

    def get_overlay(self, overlay_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/investor-overlays/{overlay_id}", None, headers)

    # --- Borrowers and credit events --------------------------------------
    def create_borrower(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/borrowers", payload, headers)

    def get_borrower(self, borrower_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/borrowers/{borrower_id}", None, headers)

    def create_credit_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/credit-events", payload, headers)

    def list_credit_events(self, borrower_id: str, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/borrowers/{borrower_id}/credit-events",
                             params or {}, headers)

    # --- Loan files -------------------------------------------------------
    def create_loan_file(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/loan-files", payload, headers)

    def get_loan_file(self, loan_file_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/loan-files/{loan_file_id}", None, headers)

    def list_loan_files(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/loan-files", params or {}, headers)

    def select_doc_type(self, loan_file_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", f"/loan-files/{loan_file_id}/doc-type-selection",
                             payload, headers)

    def submit_to_underwriting(self, loan_file_id: str, headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/loan-files/{loan_file_id}/submit-to-underwriting",
                             payload if payload is not None else {}, headers)

    def run_points_and_fees_test(self, loan_file_id: str, headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/loan-files/{loan_file_id}/points-and-fees-test",
                             payload if payload is not None else {}, headers)

    def run_atr_determination(self, loan_file_id: str, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/loan-files/{loan_file_id}/atr-determination",
                             payload if payload is not None else {}, headers)

    def suspend_loan_file(self, loan_file_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", f"/loan-files/{loan_file_id}/suspend", payload, headers)

    def clear_conditions(self, loan_file_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", f"/loan-files/{loan_file_id}/clear-conditions",
                             payload, headers)

    def approve_loan_file(self, loan_file_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/loan-files/{loan_file_id}/approve",
                             payload if payload is not None else {}, headers)

    def deny_loan_file(self, loan_file_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", f"/loan-files/{loan_file_id}/deny", payload, headers)

    def close_loan_file(self, loan_file_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/loan-files/{loan_file_id}/close",
                             payload if payload is not None else {}, headers)

    # --- Income worksheets ------------------------------------------------
    def create_worksheet(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/income-worksheets", payload, headers)

    def get_worksheet(self, worksheet_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/income-worksheets/{worksheet_id}", None, headers)

    def list_worksheets(self, loan_file_id: str, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/loan-files/{loan_file_id}/income-worksheets",
                             params or {}, headers)

    def create_statement_month(self, worksheet_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request("POST", f"/income-worksheets/{worksheet_id}/statement-months",
                             payload, headers)

    def list_statement_months(self, worksheet_id: str, headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/income-worksheets/{worksheet_id}/statement-months",
                             params or {}, headers)

    def exclude_statement_month(self, statement_month_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST", f"/statement-months/{statement_month_id}/exclude",
                             payload, headers)

    def calculate_worksheet(self, worksheet_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/income-worksheets/{worksheet_id}/calculate",
                             payload if payload is not None else {}, headers)

    def accept_worksheet(self, worksheet_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/income-worksheets/{worksheet_id}/accept",
                             payload if payload is not None else {}, headers)

    # --- Valuations and appraisal review ----------------------------------
    def create_valuation_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/valuation-orders", payload, headers)

    def get_valuation_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/valuation-orders/{order_id}", None, headers)

    def list_valuation_orders(self, loan_file_id: str, headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/loan-files/{loan_file_id}/valuation-orders",
                             params or {}, headers)

    def receive_valuation(self, order_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", f"/valuation-orders/{order_id}/receive", payload, headers)

    def decide_valuation(self, order_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", f"/valuation-orders/{order_id}/decision", payload, headers)

    def list_appraisal_reviews(self, loan_file_id: str, headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/loan-files/{loan_file_id}/appraisal-reviews",
                             params or {}, headers)

    def override_escalation(self, review_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", f"/appraisal-reviews/{review_id}/override-escalation",
                             payload, headers)

    # --- Points-and-fees items --------------------------------------------
    def create_fee_item(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/points-and-fees-items", payload, headers)

    def list_fee_items(self, loan_file_id: str, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/loan-files/{loan_file_id}/points-and-fees-items",
                             params or {}, headers)

    def void_fee_item(self, fee_item_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", f"/points-and-fees-items/{fee_item_id}/void",
                             payload, headers)

    # --- Exception requests -----------------------------------------------
    def create_exception_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/exception-requests", payload, headers)

    def get_exception_request(self, exception_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/exception-requests/{exception_id}", None, headers)

    def list_exception_requests(self, headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/exception-requests", params or {}, headers)

    def decide_exception_request(self, exception_id: str, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request("POST", f"/exception-requests/{exception_id}/decision",
                             payload, headers)

    # --- Post-close audit -------------------------------------------------
    def create_audit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/post-close-audits", payload, headers)

    def get_audit(self, audit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/post-close-audits/{audit_id}", None, headers)

    def list_audits(self, loan_file_id: str, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/loan-files/{loan_file_id}/post-close-audits",
                             params or {}, headers)

    def create_finding(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/audit-findings", payload, headers)

    def list_findings(self, audit_id: str, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/post-close-audits/{audit_id}/findings",
                             params or {}, headers)

    def rebut_finding(self, finding_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", f"/audit-findings/{finding_id}/rebut", payload, headers)

    def adjudicate_finding(self, finding_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", f"/audit-findings/{finding_id}/adjudicate",
                             payload, headers)

    # --- Securitization pools ---------------------------------------------
    def create_pool(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/securitization-pools", payload, headers)

    def get_pool(self, pool_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/securitization-pools/{pool_id}", None, headers)

    def assign_loan_to_pool(self, pool_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", f"/securitization-pools/{pool_id}/loans", payload, headers)

    def remove_from_pool(self, pool_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", f"/securitization-pools/{pool_id}/removals",
                             payload, headers)

    # --- Logical clock ----------------------------------------------------
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


# Module-level singleton shared by the whole suite.
api_client = ApiClient()
