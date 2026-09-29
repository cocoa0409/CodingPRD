"""API client: one method per endpoint the PRD defines under the /chattel mount.

Also provides ``canonical_instant`` — every timestamp the API returns is an
ISO 8601 UTC instant, but the PRD pins three fractional digits only for
server-minted audit stamps; instants echoed back from request input may carry
any admissible fractional width.  Tests compare instants through this
canonicaliser rather than by raw string equality.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Reduce an ISO 8601 UTC instant to a whole-second canonical form.

    ``2026-09-01T00:00:00Z``, ``2026-09-01T00:00:00.000Z`` and
    ``2026-09-01T00:00:00.000000Z`` all denote the same instant, so a test that
    asserts a stored date must not depend on the fractional width the server
    chose to render.
    """
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text[10:]:
        text = text[: 10 + text[10:].index("+")]
    if "." in text:
        text = text[: text.index(".")]
    return text + "Z"


def instants_equal(actual: Optional[str], expected: Optional[str]) -> bool:
    """True when two ISO 8601 UTC instants denote the same second."""
    return canonical_instant(actual) == canonical_instant(expected)


class ApiClient(GenericApiClient):
    """One method per PRD endpoint. All paths sit beneath the /chattel prefix."""

    # ─── Logical clock ────────────────────────────────
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )

    def set_clock_raw(self, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers
        )

    # ─── Book value guides ────────────────────────────
    def create_book_value_guide(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/book-value-guides", payload, headers)

    def get_book_value_guide(self, guide_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/book-value-guides/{guide_id}", headers=headers
        )

    # ─── Borrowers ────────────────────────────────────
    def create_borrower(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/borrowers", payload, headers)

    def get_borrower(self, borrower_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/borrowers/{borrower_id}", headers=headers
        )

    # ─── Communities ──────────────────────────────────
    def create_community(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/communities", payload, headers)

    def get_community(self, community_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/communities/{community_id}", headers=headers
        )

    def operator_agreement(self, community_id: str, action: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/communities/{community_id}/operator-agreement",
            {"action": action},
            headers,
        )

    # ─── Manufactured units ───────────────────────────
    def create_unit(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/units", payload, headers)

    def get_unit(self, unit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/units/{unit_id}", headers=headers)

    def list_units(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/units", headers=headers, params=params)

    def record_land_document(
        self, unit_id: str, document_type: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/units/{unit_id}/land-documents",
            {"document_type": document_type},
            headers,
        )

    def convert_classification(self, unit_id: str, action: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/units/{unit_id}/convert-classification",
            {"action": action},
            headers,
        )

    # ─── Valuations ───────────────────────────────────
    def create_valuation(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/valuations", payload, headers)

    def get_valuation(self, valuation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/valuations/{valuation_id}", headers=headers
        )

    def list_valuations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/valuations", headers=headers, params=params
        )

    def certify_valuation(self, valuation_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/valuations/{valuation_id}/certify", {}, headers
        )

    # ─── Loans ────────────────────────────────────────
    def create_loan(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/loans", payload, headers)

    def get_loan(self, loan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/loans/{loan_id}", headers=headers)

    def list_loans(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/loans", headers=headers, params=params)

    def submit_underwriting(self, loan_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/loans/{loan_id}/submit-underwriting", {}, headers
        )

    def approve_loan(self, loan_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/loans/{loan_id}/approve", {}, headers)

    def decline_loan(
        self, loan_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{API_PREFIX}/loans/{loan_id}/decline", payload or {}, headers
        )

    def fund_loan(self, loan_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/loans/{loan_id}/fund", payload, headers
        )

    # ─── Lien filings ─────────────────────────────────
    def create_lien_filing(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/lien-filings", payload, headers)

    def get_lien_filing(self, filing_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/lien-filings/{filing_id}", headers=headers
        )

    def list_lien_filings(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/lien-filings", headers=headers, params=params
        )

    def agency_response(self, filing_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/lien-filings/{filing_id}/agency-response",
            payload,
            headers,
        )

    def resubmit_lien_filing(self, filing_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/lien-filings/{filing_id}/resubmit", payload, headers
        )

    # ─── Insurance policies ───────────────────────────
    def create_insurance_policy(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/insurance-policies", payload, headers)

    def get_insurance_policy(self, policy_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/insurance-policies/{policy_id}", headers=headers
        )

    def list_insurance_policies(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/insurance-policies", headers=headers, params=params
        )

    def force_place_insurance(self, loan_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/loans/{loan_id}/force-place-insurance", payload, headers
        )

    # ─── Servicing ────────────────────────────────────
    def lot_rent_report(self, loan_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/loans/{loan_id}/lot-rent-report", payload, headers
        )

    def create_payment(self, loan_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/loans/{loan_id}/payments", payload, headers
        )

    def get_payment(self, payment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/payments/{payment_id}", headers=headers
        )

    def list_payments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/payments", headers=headers, params=params
        )

    def reverse_payment(
        self, payment_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{API_PREFIX}/payments/{payment_id}/reverse", payload or {}, headers
        )

    def servicing_assessment(self, loan_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/loans/{loan_id}/servicing-assessment", {}, headers
        )

    def declare_default(self, loan_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/loans/{loan_id}/default-declare", {}, headers
        )

    # ─── Recovery cases ───────────────────────────────
    def get_recovery_case(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/recovery-cases/{case_id}", headers=headers
        )

    def list_recovery_cases(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/recovery-cases", headers=headers, params=params
        )

    def issue_notice(self, case_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/recovery-cases/{case_id}/issue-notice", payload, headers
        )

    def redeem_case(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/recovery-cases/{case_id}/redeem", {}, headers
        )

    def obtain_possession(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/recovery-cases/{case_id}/obtain-possession", {}, headers
        )

    def begin_refurbishment(self, case_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/recovery-cases/{case_id}/begin-refurbishment",
            payload,
            headers,
        )

    def record_refurbishment_cost(
        self, case_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/recovery-cases/{case_id}/refurbishment-costs",
            payload,
            headers,
        )

    def list_for_resale(self, case_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/recovery-cases/{case_id}/list-for-resale",
            payload,
            headers,
        )

    def finalize_sale(self, case_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/recovery-cases/{case_id}/finalize-sale", payload, headers
        )


api_client = ApiClient()
