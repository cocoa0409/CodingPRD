"""One typed method per endpoint of the ESA administration API.

The whole API is mounted under the ``/esa`` path prefix, so the prefix lives in a
single module constant. Every method delegates to the framework client's
``_request`` so that GET and DELETE send query parameters while the other verbs
send a JSON body.

Two convenience readers sit alongside the endpoint methods. ``canonical_instant``
normalises an ISO 8601 UTC instant to a fixed millisecond form so that a test may
compare a returned timestamp against a literal without tripping over
sub-second precision, and ``instant_plus_days`` derives a deadline instant.
"""

from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/esa"


def _parse_instant(value):
    """Parse an ISO 8601 UTC instant, tolerating any fractional-second width."""
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def canonical_instant(value):
    """Render an ISO 8601 UTC instant in a single comparable millisecond form.

    Comparing two instants through this function makes ``2026-09-01T00:00:00Z``
    and ``2026-09-01T00:00:00.000Z`` compare equal, which is what a test that
    cares about the instant rather than its printed width wants.
    """
    parsed = _parse_instant(value)
    if parsed is None:
        return None
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (parsed.microsecond // 1000)


def instants_equal(left, right):
    """True when two ISO 8601 UTC instants denote the same moment."""
    return canonical_instant(left) == canonical_instant(right)


def instant_plus_days(value, days):
    """The instant ``days`` days after ``value``, in canonical millisecond form."""
    return canonical_instant(_parse_instant(value) + timedelta(days=days))


class ApiClient(GenericApiClient):
    """Endpoint-per-method client for the education savings account API."""

    # ------------------------------------------------------------------ clock

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST",
            f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    # ---------------------------------------------------------- program years

    def create_program_year(self, payload, headers):
        return self._request("POST", f"{PREFIX}/program-years", payload, headers)

    def get_program_year(self, program_year_id, headers):
        return self._request(
            "GET", f"{PREFIX}/program-years/{program_year_id}", headers=headers
        )

    def open_window(self, program_year_id, headers):
        return self._request(
            "POST", f"{PREFIX}/program-years/{program_year_id}/open-window", {}, headers
        )

    def run_awarding(self, program_year_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/program-years/{program_year_id}/awarding-runs",
            payload if payload is not None else {},
            headers,
        )

    def run_disbursement(self, program_year_id, quarter, headers):
        return self._request(
            "POST",
            f"{PREFIX}/program-years/{program_year_id}/disbursement-runs",
            {"quarter": quarter},
            headers,
        )

    def close_year(self, program_year_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/program-years/{program_year_id}/year-end-close",
            payload if payload is not None else {},
            headers,
        )

    def list_program_year_disbursements(self, program_year_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/program-years/{program_year_id}/disbursements",
            headers=headers,
            params=params,
        )

    # --------------------------------------------------------------- students

    def create_student(self, payload, headers):
        return self._request("POST", f"{PREFIX}/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"{PREFIX}/students/{student_id}", headers=headers)

    # ----------------------------------------------------------- applications

    def create_application(self, payload, headers):
        return self._request("POST", f"{PREFIX}/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request(
            "GET", f"{PREFIX}/applications/{application_id}", headers=headers
        )

    def list_applications(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/applications", headers=headers, params=params
        )

    def submit_application(self, application_id, headers):
        return self._request(
            "POST", f"{PREFIX}/applications/{application_id}/submit", {}, headers
        )

    def create_eligibility_determination(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/applications/{application_id}/eligibility-determinations",
            payload,
            headers,
        )

    def list_eligibility_determinations(self, application_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/applications/{application_id}/eligibility-determinations",
            headers=headers,
            params=params,
        )

    def accept_award(self, application_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/applications/{application_id}/accept-award",
            payload if payload is not None else {},
            headers,
        )

    def withdraw_application(self, application_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/applications/{application_id}/withdraw",
            payload if payload is not None else {},
            headers,
        )

    # --------------------------------------------------------------- providers

    def create_provider(self, payload, headers):
        return self._request("POST", f"{PREFIX}/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"{PREFIX}/providers/{provider_id}", headers=headers)

    def create_fraud_screening(self, provider_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/providers/{provider_id}/fraud-screenings", payload, headers
        )

    def list_fraud_screenings(self, provider_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/providers/{provider_id}/fraud-screenings",
            headers=headers,
            params=params,
        )

    def approve_provider(self, provider_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/providers/{provider_id}/approve", payload, headers
        )

    def sanction_provider(self, provider_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/providers/{provider_id}/sanctions", payload, headers
        )

    # ------------------------------------------------------- expense catalogue

    def create_expense_category(self, payload, headers):
        return self._request("POST", f"{PREFIX}/expense-categories", payload, headers)

    def get_expense_category(self, expense_category_id, headers):
        return self._request(
            "GET", f"{PREFIX}/expense-categories/{expense_category_id}", headers=headers
        )

    # ---------------------------------------------------------------- accounts

    def get_account(self, account_id, headers):
        return self._request("GET", f"{PREFIX}/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/accounts", headers=headers, params=params)

    def list_account_disbursements(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/accounts/{account_id}/disbursements",
            headers=headers,
            params=params,
        )

    def list_account_clawback_entries(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/accounts/{account_id}/clawback-entries",
            headers=headers,
            params=params,
        )

    def account_status_action(self, account_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/accounts/{account_id}/status-actions", payload, headers
        )

    def create_purchase_request(self, account_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/accounts/{account_id}/purchase-requests", payload, headers
        )

    # -------------------------------------------------------- purchase requests

    def get_purchase_request(self, purchase_request_id, headers):
        return self._request(
            "GET", f"{PREFIX}/purchase-requests/{purchase_request_id}", headers=headers
        )

    def list_purchase_requests(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/purchase-requests", headers=headers, params=params
        )

    def decide_purchase_request(self, purchase_request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/purchase-requests/{purchase_request_id}/decision",
            payload,
            headers,
        )

    def claim_purchase_request(self, purchase_request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/purchase-requests/{purchase_request_id}/claim",
            payload,
            headers,
        )

    def settle_purchase_request(self, purchase_request_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/purchase-requests/{purchase_request_id}/settle",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------ misuse cases

    def create_misuse_case(self, payload, headers):
        return self._request("POST", f"{PREFIX}/misuse-cases", payload, headers)

    def get_misuse_case(self, misuse_case_id, headers):
        return self._request(
            "GET", f"{PREFIX}/misuse-cases/{misuse_case_id}", headers=headers
        )

    def list_misuse_cases(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/misuse-cases", headers=headers, params=params
        )

    def review_misuse_case(self, misuse_case_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/misuse-cases/{misuse_case_id}/review",
            payload if payload is not None else {},
            headers,
        )

    def adjudicate_misuse_case(self, misuse_case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/misuse-cases/{misuse_case_id}/adjudication", payload, headers
        )

    def issue_clawback(self, misuse_case_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/misuse-cases/{misuse_case_id}/clawbacks",
            payload if payload is not None else {},
            headers,
        )

    def list_case_clawback_entries(self, misuse_case_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/misuse-cases/{misuse_case_id}/clawback-entries",
            headers=headers,
            params=params,
        )

    # --------------------------------------------------------- renewal reviews

    def create_renewal_review(self, payload, headers):
        return self._request("POST", f"{PREFIX}/renewal-reviews", payload, headers)

    def get_renewal_review(self, renewal_review_id, headers):
        return self._request(
            "GET", f"{PREFIX}/renewal-reviews/{renewal_review_id}", headers=headers
        )

    def list_renewal_reviews(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/renewal-reviews", headers=headers, params=params
        )

    def decide_renewal_review(self, renewal_review_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/renewal-reviews/{renewal_review_id}/decision",
            payload,
            headers,
        )

    # ----------------------------------------------------------------- appeals

    def create_appeal(self, payload, headers):
        return self._request("POST", f"{PREFIX}/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"{PREFIX}/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/appeals", headers=headers, params=params)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/appeals/{appeal_id}/decision", payload, headers
        )


api_client = ApiClient()

__all__ = [
    "PREFIX",
    "ApiClient",
    "api_client",
    "canonical_instant",
    "instants_equal",
    "instant_plus_days",
]
