"""One client method per endpoint in the PRD endpoint table.

All list methods take `params` so pagination and filter arguments travel as
query parameters (PRD 2.3). All mutating methods take an explicit payload so a
test can send exactly the body the PRD describes, including omitted optional
fields.
"""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import (
    PATH_CLAIMS,
    PATH_CLOCK,
    PATH_DAILY_RUN,
    PATH_DETERMINATIONS,
    PATH_ELECTION_EVENTS,
    PATH_ENROLLMENTS,
    PATH_HRA_ACCOUNTS,
    PATH_INVOICES,
    PATH_PLAN_OPTIONS,
    PATH_PLAN_YEARS,
    PATH_RETIREES,
)


class ApiClient(GenericApiClient):
    """HTTP surface of the retiree medical / Medicare coordination API."""

    # ---------------------------------------------------------------- clock --
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /_clock/set_current_utc — move the logical UTC clock."""
        return self._request("POST", PATH_CLOCK, payload, headers)

    def set_clock_to(self, to_iso8601: str, headers: Dict[str, str]):
        """Convenience wrapper around set_clock for the common single-field body."""
        return self._request("POST", PATH_CLOCK, {"to_iso8601": to_iso8601}, headers)

    def daily_run(self, headers: Dict[str, str], payload: Optional[Dict] = None):
        """POST /_ops/daily-run — run the scheduled daily administration sweep."""
        return self._request("POST", PATH_DAILY_RUN, payload, headers)

    # ------------------------------------------------------------ plan years --
    def create_plan_year(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", PATH_PLAN_YEARS, payload, headers)

    def get_plan_year(self, plan_year_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PATH_PLAN_YEARS}/{plan_year_id}", headers=headers)

    def list_plan_years(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", PATH_PLAN_YEARS, headers=headers, params=params)

    def set_plan_year_status(
        self, plan_year_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PATH_PLAN_YEARS}/{plan_year_id}/status", payload, headers
        )

    def run_liability_valuation(
        self, plan_year_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PATH_PLAN_YEARS}/{plan_year_id}/liability-valuation",
            payload,
            headers,
        )

    # -------------------------------------------------------------- retirees --
    def create_retiree(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", PATH_RETIREES, payload, headers)

    def get_retiree(self, retiree_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PATH_RETIREES}/{retiree_id}", headers=headers)

    def list_retirees(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", PATH_RETIREES, headers=headers, params=params)

    def patch_retiree(
        self, retiree_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PATCH", f"{PATH_RETIREES}/{retiree_id}", payload, headers)

    # ----------------------------------------------------------- plan options --
    def create_plan_option(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", PATH_PLAN_OPTIONS, payload, headers)

    def get_plan_option(self, plan_option_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PATH_PLAN_OPTIONS}/{plan_option_id}", headers=headers
        )

    def list_plan_options(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", PATH_PLAN_OPTIONS, headers=headers, params=params)

    def activate_plan_option(
        self, plan_option_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PATH_PLAN_OPTIONS}/{plan_option_id}/activate", payload, headers
        )

    def attest_plan_option(
        self, plan_option_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PATH_PLAN_OPTIONS}/{plan_option_id}/attest", payload, headers
        )

    def certify_subsidy(
        self, plan_option_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PATH_PLAN_OPTIONS}/{plan_option_id}/subsidy-certification",
            payload,
            headers,
        )

    def issue_change_notice(
        self, plan_option_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PATH_PLAN_OPTIONS}/{plan_option_id}/change-notice",
            payload,
            headers,
        )

    # ------------------------------------------------------- determinations --
    def create_determination(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", PATH_DETERMINATIONS, payload, headers)

    def get_determination(self, determination_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PATH_DETERMINATIONS}/{determination_id}", headers=headers
        )

    def list_determinations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", PATH_DETERMINATIONS, headers=headers, params=params)

    def certify_determination(
        self,
        determination_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ):
        return self._request(
            "POST",
            f"{PATH_DETERMINATIONS}/{determination_id}/certify",
            payload,
            headers,
        )

    def appeal_determination(
        self, determination_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PATH_DETERMINATIONS}/{determination_id}/appeal",
            payload,
            headers,
        )

    def decide_appeal(
        self, determination_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PATH_DETERMINATIONS}/{determination_id}/appeal-decision",
            payload,
            headers,
        )

    # ------------------------------------------------------- election events --
    def create_election_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", PATH_ELECTION_EVENTS, payload, headers)

    def get_election_event(self, election_event_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PATH_ELECTION_EVENTS}/{election_event_id}", headers=headers
        )

    def list_election_events(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", PATH_ELECTION_EVENTS, headers=headers, params=params)

    def review_election_event(
        self,
        election_event_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ):
        return self._request(
            "POST",
            f"{PATH_ELECTION_EVENTS}/{election_event_id}/review",
            payload,
            headers,
        )

    def decide_election_event(
        self, election_event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PATH_ELECTION_EVENTS}/{election_event_id}/decision",
            payload,
            headers,
        )

    # ----------------------------------------------------------- enrollments --
    def get_enrollment(self, enrollment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PATH_ENROLLMENTS}/{enrollment_id}", headers=headers
        )

    def list_enrollments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", PATH_ENROLLMENTS, headers=headers, params=params)

    def terminate_enrollment(
        self, enrollment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PATH_ENROLLMENTS}/{enrollment_id}/terminate", payload, headers
        )

    def reinstate_enrollment(
        self, enrollment_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PATH_ENROLLMENTS}/{enrollment_id}/reinstate", payload, headers
        )

    # ---------------------------------------------------------- hra accounts --
    def create_hra_account(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", PATH_HRA_ACCOUNTS, payload, headers)

    def get_hra_account(self, hra_account_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PATH_HRA_ACCOUNTS}/{hra_account_id}", headers=headers
        )

    def list_hra_accounts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", PATH_HRA_ACCOUNTS, headers=headers, params=params)

    def close_hra_year(
        self,
        hra_account_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ):
        return self._request(
            "POST", f"{PATH_HRA_ACCOUNTS}/{hra_account_id}/close-year", payload, headers
        )

    # --------------------------------------------------- reimbursement claims --
    def create_claim(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", PATH_CLAIMS, payload, headers)

    def get_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PATH_CLAIMS}/{claim_id}", headers=headers)

    def list_claims(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", PATH_CLAIMS, headers=headers, params=params)

    def substantiate_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PATH_CLAIMS}/{claim_id}/substantiation", payload, headers
        )

    def review_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PATH_CLAIMS}/{claim_id}/review", payload, headers
        )

    def settle_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PATH_CLAIMS}/{claim_id}/settlement", payload, headers
        )

    # ------------------------------------------------------ premium invoices --
    def create_invoice(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", PATH_INVOICES, payload, headers)

    def get_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PATH_INVOICES}/{invoice_id}", headers=headers)

    def list_invoices(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", PATH_INVOICES, headers=headers, params=params)

    def pay_invoice(
        self, invoice_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PATH_INVOICES}/{invoice_id}/payments", payload, headers
        )


# Module-level singleton reused by the session-scoped `api` fixture.
api_client = ApiClient()

__all__ = ["ApiClient", "api_client"]
