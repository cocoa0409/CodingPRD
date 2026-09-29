"""API client: one method per endpoint defined in the PRD.

Every business path is mounted under `/nmtc`, with the sole exception of the
logical-clock control endpoint, which sits outside it.
"""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

NMTC = "/nmtc"


class ApiClient(GenericApiClient):
    """Endpoint methods for the New Markets Tax Credit deployment API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Optional[dict] = None):
        """Set the server's logical clock and return the new `current_utc`."""
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Community development entities
    # ------------------------------------------------------------------

    def create_cde(self, payload: dict, headers: dict):
        return self._request("POST", f"{NMTC}/cdes", payload, headers)

    def list_cdes(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{NMTC}/cdes", headers=headers, params=params)

    def get_cde(self, cde_id: str, headers: dict):
        return self._request("GET", f"{NMTC}/cdes/{cde_id}", headers=headers)

    def decertify_cde(self, cde_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{NMTC}/cdes/{cde_id}/decertification", payload, headers
        )

    # ------------------------------------------------------------------
    # Allocation awards
    # ------------------------------------------------------------------

    def create_allocation_award(self, payload: dict, headers: dict):
        return self._request("POST", f"{NMTC}/allocation-awards", payload, headers)

    def list_allocation_awards(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{NMTC}/allocation-awards", headers=headers, params=params
        )

    def get_allocation_award(self, award_id: str, headers: dict):
        return self._request(
            "GET", f"{NMTC}/allocation-awards/{award_id}", headers=headers
        )

    def sign_allocation_agreement(self, award_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{NMTC}/allocation-awards/{award_id}/allocation-agreement",
            payload,
            headers,
        )

    def file_agency_report(self, award_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{NMTC}/allocation-awards/{award_id}/agency-reports",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Census tracts
    # ------------------------------------------------------------------

    def create_census_tract(self, payload: dict, headers: dict):
        return self._request("POST", f"{NMTC}/census-tracts", payload, headers)

    def list_census_tracts(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{NMTC}/census-tracts", headers=headers, params=params
        )

    def get_census_tract(self, tract_id: str, headers: dict):
        return self._request("GET", f"{NMTC}/census-tracts/{tract_id}", headers=headers)

    # ------------------------------------------------------------------
    # Project companies
    # ------------------------------------------------------------------

    def create_qalicb(self, payload: dict, headers: dict):
        return self._request("POST", f"{NMTC}/qalicbs", payload, headers)

    def list_qalicbs(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{NMTC}/qalicbs", headers=headers, params=params)

    def get_qalicb(self, qalicb_id: str, headers: dict):
        return self._request("GET", f"{NMTC}/qalicbs/{qalicb_id}", headers=headers)

    def run_eligibility_test(self, qalicb_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{NMTC}/qalicbs/{qalicb_id}/eligibility-tests", payload, headers
        )

    def list_eligibility_tests(
        self, qalicb_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{NMTC}/qalicbs/{qalicb_id}/eligibility-tests",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Investment funds
    # ------------------------------------------------------------------

    def create_investment_fund(self, payload: dict, headers: dict):
        return self._request("POST", f"{NMTC}/investment-funds", payload, headers)

    def list_investment_funds(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{NMTC}/investment-funds", headers=headers, params=params
        )

    def get_investment_fund(self, fund_id: str, headers: dict):
        return self._request(
            "GET", f"{NMTC}/investment-funds/{fund_id}", headers=headers
        )

    def close_investment_fund(self, fund_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{NMTC}/investment-funds/{fund_id}/closing", payload, headers
        )

    # ------------------------------------------------------------------
    # Qualified equity investments
    # ------------------------------------------------------------------

    def create_qei(self, payload: dict, headers: dict):
        return self._request("POST", f"{NMTC}/qeis", payload, headers)

    def list_qeis(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{NMTC}/qeis", headers=headers, params=params)

    def get_qei(self, qei_id: str, headers: dict):
        return self._request("GET", f"{NMTC}/qeis/{qei_id}", headers=headers)

    def void_qei(self, qei_id: str, payload: dict, headers: dict):
        return self._request("POST", f"{NMTC}/qeis/{qei_id}/void", payload, headers)

    def run_annual_test(self, qei_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{NMTC}/qeis/{qei_id}/annual-tests", payload, headers
        )

    def list_annual_tests(
        self, qei_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"{NMTC}/qeis/{qei_id}/annual-tests", headers=headers, params=params
        )

    def cure_qei(self, qei_id: str, payload: dict, headers: dict):
        return self._request("POST", f"{NMTC}/qeis/{qei_id}/cures", payload, headers)

    def open_unwind_transaction(self, qei_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{NMTC}/qeis/{qei_id}/unwind-transactions", payload, headers
        )

    def list_unwind_transactions(
        self, qei_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{NMTC}/qeis/{qei_id}/unwind-transactions",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Sub-allocations
    # ------------------------------------------------------------------

    def create_qlici(self, payload: dict, headers: dict):
        return self._request("POST", f"{NMTC}/qlicis", payload, headers)

    def list_qlicis(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{NMTC}/qlicis", headers=headers, params=params)

    def get_qlici(self, qlici_id: str, headers: dict):
        return self._request("GET", f"{NMTC}/qlicis/{qlici_id}", headers=headers)

    def repay_principal(self, qlici_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{NMTC}/qlicis/{qlici_id}/principal-repayments", payload, headers
        )

    # ------------------------------------------------------------------
    # Reinvestment obligations
    # ------------------------------------------------------------------

    def list_reinvestment_obligations(
        self, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"{NMTC}/reinvestment-obligations", headers=headers, params=params
        )

    def get_reinvestment_obligation(self, obligation_id: str, headers: dict):
        return self._request(
            "GET", f"{NMTC}/reinvestment-obligations/{obligation_id}", headers=headers
        )

    def reinvest(self, obligation_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{NMTC}/reinvestment-obligations/{obligation_id}/reinvestments",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Community benefits agreements
    # ------------------------------------------------------------------

    def create_community_benefits_agreement(self, payload: dict, headers: dict):
        return self._request(
            "POST", f"{NMTC}/community-benefits-agreements", payload, headers
        )

    def list_community_benefits_agreements(
        self, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{NMTC}/community-benefits-agreements",
            headers=headers,
            params=params,
        )

    def get_community_benefits_agreement(self, cba_id: str, headers: dict):
        return self._request(
            "GET", f"{NMTC}/community-benefits-agreements/{cba_id}", headers=headers
        )

    def file_job_report(self, cba_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{NMTC}/community-benefits-agreements/{cba_id}/job-reports",
            payload,
            headers,
        )

    def list_job_reports(
        self, cba_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{NMTC}/community-benefits-agreements/{cba_id}/job-reports",
            headers=headers,
            params=params,
        )

    def certify_community_benefits(self, cba_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{NMTC}/community-benefits-agreements/{cba_id}/annual-certifications",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Unwind transactions
    # ------------------------------------------------------------------

    def get_unwind_transaction(self, unwind_id: str, headers: dict):
        return self._request(
            "GET", f"{NMTC}/unwind-transactions/{unwind_id}", headers=headers
        )

    def exercise_option(self, unwind_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{NMTC}/unwind-transactions/{unwind_id}/exercise", payload, headers
        )

    def settle_unwind(self, unwind_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{NMTC}/unwind-transactions/{unwind_id}/settlement",
            payload,
            headers,
        )


api_client = ApiClient()
