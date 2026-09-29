"""
HTTP client for the Pooled Employer Plan administration API.

One method per declared endpoint.  Every method returns the raw response so
that tests can assert status codes; unwrapping the envelope is the job of the
validators in ``assertions.py`` and of the framework's ``validate_success`` —
it is never done twice.

Sub-second precision is canonicalised here.  The API declares that every
instant it returns is an ISO 8601 UTC timestamp with exactly three fractional
digits, so every instant-shaped string in every response body is rewritten to
that width before a test ever sees it.  Tests can therefore compare an echoed
instant against ``canonical_instant("2026-08-10T00:00:00Z")`` without caring
how the server spelled the fraction.  Calendar dates are left untouched.
"""

import json
import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$"
)


def canonical_instant(value: Any) -> Any:
    """
    Rewrite an ISO 8601 instant to exactly three fractional digits in UTC.

    Anything that is not an instant — a calendar date, an enum, a number,
    ``None`` — is returned unchanged.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value)
    if not match:
        return value
    seconds, fraction, offset = match.groups()
    if offset != "Z":
        # A non-UTC offset is not canonicalised: the API declares UTC, and a
        # test asserting on the value should see exactly what was sent.
        return value
    fraction = (fraction or "")[:3].ljust(3, "0")
    return f"{seconds}.{fraction}Z"


def _canonicalise(node: Any) -> Any:
    if isinstance(node, dict):
        return {key: _canonicalise(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_canonicalise(item) for item in node]
    return canonical_instant(node)


class ApiClient(GenericApiClient):
    """Typed access to every endpoint of the pooled employer plan API."""

    def _request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        response = super()._request(method, path, payload, headers, params)
        self._canonicalise_body(response)
        return response

    @staticmethod
    def _canonicalise_body(response) -> None:
        if not response.content:
            return
        try:
            body = response.json()
        except ValueError:
            return
        canonical = _canonicalise(body)
        if canonical != body:
            response._content = json.dumps(canonical).encode("utf-8")

    # ─── Logical clock ────────────────────────────────

    def set_clock(self, current_utc: str, headers=None):
        """Move the server's logical clock to a given instant."""
        return self._request(
            "POST", CLOCK_PATH, {"current_utc": current_utc}, headers
        )

    # ─── PooledPlanProvider ───────────────────────────

    def create_plan_provider(self, payload: dict, headers=None):
        return self._request("POST", f"{API_PREFIX}/plan-providers", payload, headers)

    def register_plan_provider(self, provider_id: str, payload: dict, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/plan-providers/{provider_id}/register",
            payload,
            headers,
        )

    def get_plan_provider(self, provider_id: str, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/plan-providers/{provider_id}", None, headers
        )

    def list_provider_plan_documents(self, provider_id: str, headers=None, **params):
        return self._request(
            "GET",
            f"{API_PREFIX}/plan-providers/{provider_id}/plan-documents",
            params or None,
            headers,
        )

    # ─── PlanDocument ─────────────────────────────────

    def create_plan_document(self, payload: dict, headers=None):
        return self._request("POST", f"{API_PREFIX}/plan-documents", payload, headers)

    def activate_plan_document(self, plan_id: str, headers=None, payload: dict = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/plan-documents/{plan_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    def get_plan_document(self, plan_id: str, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/plan-documents/{plan_id}", None, headers
        )

    def list_plan_service_providers(self, plan_id: str, headers=None, **params):
        return self._request(
            "GET",
            f"{API_PREFIX}/plan-documents/{plan_id}/service-providers",
            params or None,
            headers,
        )

    def list_plan_adopting_employers(self, plan_id: str, headers=None, **params):
        return self._request(
            "GET",
            f"{API_PREFIX}/plan-documents/{plan_id}/adopting-employers",
            params or None,
            headers,
        )

    def list_plan_fiduciary_role_allocations(self, plan_id: str, headers=None, **params):
        return self._request(
            "GET",
            f"{API_PREFIX}/plan-documents/{plan_id}/fiduciary-role-allocations",
            params or None,
            headers,
        )

    def list_plan_compliance_tests(self, plan_id: str, headers=None, **params):
        return self._request(
            "GET",
            f"{API_PREFIX}/plan-documents/{plan_id}/compliance-tests",
            params or None,
            headers,
        )

    def list_plan_filings(self, plan_id: str, headers=None, **params):
        return self._request(
            "GET",
            f"{API_PREFIX}/plan-documents/{plan_id}/plan-filings",
            params or None,
            headers,
        )

    def list_plan_fee_disclosures(self, plan_id: str, headers=None, **params):
        return self._request(
            "GET",
            f"{API_PREFIX}/plan-documents/{plan_id}/fee-disclosures",
            params or None,
            headers,
        )

    # ─── ServiceProvider ──────────────────────────────

    def create_service_provider(self, payload: dict, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/service-providers", payload, headers
        )

    def get_service_provider(self, service_provider_id: str, headers=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/service-providers/{service_provider_id}",
            None,
            headers,
        )

    def list_service_provider_affiliates(
        self, service_provider_id: str, headers=None, **params
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/service-providers/{service_provider_id}/affiliates",
            params or None,
            headers,
        )

    def list_service_provider_fiduciary_role_allocations(
        self, service_provider_id: str, headers=None, **params
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/service-providers/{service_provider_id}"
            f"/fiduciary-role-allocations",
            params or None,
            headers,
        )

    def list_service_provider_attested_filings(
        self, service_provider_id: str, headers=None, **params
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/service-providers/{service_provider_id}/attested-filings",
            params or None,
            headers,
        )

    # ─── FiduciaryRoleAllocation ──────────────────────

    def create_fiduciary_role_allocation(self, payload: dict, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/fiduciary-role-allocations", payload, headers
        )

    def acknowledge_fiduciary_role_allocation(
        self, allocation_id: str, payload: dict, headers=None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/fiduciary-role-allocations/{allocation_id}/acknowledge",
            payload,
            headers,
        )

    def get_fiduciary_role_allocation(self, allocation_id: str, headers=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/fiduciary-role-allocations/{allocation_id}",
            None,
            headers,
        )

    # ─── AdoptingEmployer ─────────────────────────────

    def create_adopting_employer(self, payload: dict, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/adopting-employers", payload, headers
        )

    def get_adopting_employer(self, employer_id: str, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/adopting-employers/{employer_id}", None, headers
        )

    def update_adopting_employer_census(
        self, employer_id: str, payload: dict, headers=None
    ):
        return self._request(
            "PATCH",
            f"{API_PREFIX}/adopting-employers/{employer_id}/census",
            payload,
            headers,
        )

    def list_employer_design_elections(self, employer_id: str, headers=None, **params):
        return self._request(
            "GET",
            f"{API_PREFIX}/adopting-employers/{employer_id}/design-elections",
            params or None,
            headers,
        )

    def list_employer_payroll_batches(self, employer_id: str, headers=None, **params):
        return self._request(
            "GET",
            f"{API_PREFIX}/adopting-employers/{employer_id}/payroll-batches",
            params or None,
            headers,
        )

    def list_employer_compliance_tests(self, employer_id: str, headers=None, **params):
        return self._request(
            "GET",
            f"{API_PREFIX}/adopting-employers/{employer_id}/compliance-tests",
            params or None,
            headers,
        )

    def list_employer_exit_transfers(self, employer_id: str, headers=None, **params):
        return self._request(
            "GET",
            f"{API_PREFIX}/adopting-employers/{employer_id}/exit-transfers",
            params or None,
            headers,
        )

    # ─── PlanDesignElection ───────────────────────────

    def create_design_election(self, payload: dict, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/plan-design-elections", payload, headers
        )

    def submit_design_election(self, election_id: str, payload: dict, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/plan-design-elections/{election_id}/submit",
            payload,
            headers,
        )

    def return_design_election(self, election_id: str, payload: dict, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/plan-design-elections/{election_id}/return",
            payload,
            headers,
        )

    def approve_design_election(
        self, election_id: str, headers=None, payload: dict = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/plan-design-elections/{election_id}/approve",
            payload if payload is not None else {},
            headers,
        )

    def get_design_election(self, election_id: str, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/plan-design-elections/{election_id}", None, headers
        )

    # ─── PayrollBatch ─────────────────────────────────

    def create_payroll_batch(self, payload: dict, headers=None):
        return self._request("POST", f"{API_PREFIX}/payroll-batches", payload, headers)

    def validate_payroll_batch(self, batch_id: str, payload: dict, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/payroll-batches/{batch_id}/validate",
            payload,
            headers,
        )

    def get_payroll_batch(self, batch_id: str, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/payroll-batches/{batch_id}", None, headers
        )

    def list_batch_remittance_deposits(self, batch_id: str, headers=None, **params):
        return self._request(
            "GET",
            f"{API_PREFIX}/payroll-batches/{batch_id}/remittance-deposits",
            params or None,
            headers,
        )

    # ─── RemittanceDeposit ────────────────────────────

    def create_remittance_deposit(self, payload: dict, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/remittance-deposits", payload, headers
        )

    def post_remittance_deposit(self, deposit_id: str, payload: dict, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/remittance-deposits/{deposit_id}/post",
            payload,
            headers,
        )

    def reverse_remittance_deposit(self, deposit_id: str, payload: dict, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/remittance-deposits/{deposit_id}/reverse",
            payload,
            headers,
        )

    def compute_deposit_correction(self, deposit_id: str, payload: dict, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/remittance-deposits/{deposit_id}/compute-correction",
            payload,
            headers,
        )

    def fund_deposit_correction(
        self, deposit_id: str, headers=None, payload: dict = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/remittance-deposits/{deposit_id}/fund-correction",
            payload if payload is not None else {},
            headers,
        )

    def get_remittance_deposit(self, deposit_id: str, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/remittance-deposits/{deposit_id}", None, headers
        )

    # ─── ComplianceTest ───────────────────────────────

    def create_compliance_test(self, payload: dict, headers=None):
        return self._request("POST", f"{API_PREFIX}/compliance-tests", payload, headers)

    def run_compliance_test(self, test_id: str, headers=None, payload: dict = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/compliance-tests/{test_id}/run",
            payload if payload is not None else {},
            headers,
        )

    def get_compliance_test(self, test_id: str, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/compliance-tests/{test_id}", None, headers
        )

    # ─── PlanFiling ───────────────────────────────────

    def create_plan_filing(self, payload: dict, headers=None):
        return self._request("POST", f"{API_PREFIX}/plan-filings", payload, headers)

    def prepare_plan_filing(self, filing_id: str, headers=None, payload: dict = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/plan-filings/{filing_id}/prepare",
            payload if payload is not None else {},
            headers,
        )

    def attest_plan_filing(self, filing_id: str, payload: dict, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/plan-filings/{filing_id}/attest",
            payload,
            headers,
        )

    def certify_plan_filing_employer_data(
        self, filing_id: str, headers=None, payload: dict = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/plan-filings/{filing_id}/certify-employer-data",
            payload if payload is not None else {},
            headers,
        )

    def file_plan_filing(self, filing_id: str, headers=None, payload: dict = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/plan-filings/{filing_id}/file",
            payload if payload is not None else {},
            headers,
        )

    def get_plan_filing(self, filing_id: str, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/plan-filings/{filing_id}", None, headers
        )

    # ─── ExitTransfer ─────────────────────────────────

    def create_exit_transfer(self, payload: dict, headers=None):
        return self._request("POST", f"{API_PREFIX}/exit-transfers", payload, headers)

    def approve_exit_transfer(self, transfer_id: str, headers=None, payload: dict = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/exit-transfers/{transfer_id}/approve",
            payload if payload is not None else {},
            headers,
        )

    def settle_exit_transfer(self, transfer_id: str, headers=None, payload: dict = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/exit-transfers/{transfer_id}/settle",
            payload if payload is not None else {},
            headers,
        )

    def reverse_exit_transfer(self, transfer_id: str, payload: dict, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/exit-transfers/{transfer_id}/reverse",
            payload,
            headers,
        )

    def get_exit_transfer(self, transfer_id: str, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/exit-transfers/{transfer_id}", None, headers
        )

    # ─── FeeDisclosure ────────────────────────────────

    def create_fee_disclosure(self, payload: dict, headers=None):
        return self._request("POST", f"{API_PREFIX}/fee-disclosures", payload, headers)

    def get_fee_disclosure(self, disclosure_id: str, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/fee-disclosures/{disclosure_id}", None, headers
        )
