"""
Endpoint client for the design-firm project accounting API.

One method per row of the PRD §4 endpoint table. Every method returns the raw
``requests.Response`` so a test can assert the HTTP status itself.

The collection topology is flat (PRD §2.9): every entity has a top-level
collection, one single-resource read at that collection plus the resource
identifier, and one filtered list read at the collection itself. There is no
shared path prefix.

TIMESTAMP CANONICALISATION
--------------------------
PRD §2.4 requires ISO 8601 UTC instants with three fractional digits, but an
implementation that emits ``2026-06-01T00:00:00Z`` and one that emits
``2026-06-01T00:00:00.000Z`` mean the same instant. Comparing those two spellings
is a test defect, not an API defect, so this client normalises every
instant-shaped string in every response body to the three-fractional-digit
spelling exactly once, here, before any test ever sees it. Calendar dates in
``YYYY-MM-DD`` form are left untouched.

A test that needs to assert the wire format itself (that the server really does
emit three fractional digits) must read the untouched body through
``raw_json(response)``.
"""

import re
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:?\d{2})$"
)


def canonical_timestamp(value: Any) -> Any:
    """
    Normalise one ISO 8601 instant to ``YYYY-MM-DDTHH:MM:SS.mmmZ``.

    Non-instant values (calendar dates, plain strings, numbers, None) are
    returned unchanged.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value)
    if not match:
        return value
    seconds, fraction, _offset = match.groups()
    fraction = (fraction or "")[:3].ljust(3, "0")
    return f"{seconds}.{fraction}Z"


def canonicalize_timestamps(payload: Any) -> Any:
    """Recursively canonicalise every instant-shaped string in a decoded body."""
    if isinstance(payload, dict):
        return {key: canonicalize_timestamps(val) for key, val in payload.items()}
    if isinstance(payload, list):
        return [canonicalize_timestamps(item) for item in payload]
    return canonical_timestamp(payload)


def raw_json(response: requests.Response) -> Any:
    """
    The decoded response body exactly as the server sent it, with no timestamp
    normalisation applied. Use this only when asserting the wire format of
    ``created_at`` / ``updated_at`` / ``meta.api_request_timestamp``.
    """
    stored = getattr(response, "_prd_raw_json", None)
    if stored is not None:
        return stored
    return response.json()


def _install_canonical_json(response: requests.Response) -> requests.Response:
    """Wrap ``response.json`` so decoded bodies carry canonical instants."""
    original = response.json

    try:
        decoded = original()
    except ValueError:
        return response

    object.__setattr__(response, "_prd_raw_json", decoded)
    canonical = canonicalize_timestamps(decoded)

    def json_canonical(**_kwargs: Any) -> Any:
        return canonical

    response.json = json_canonical  # type: ignore[method-assign]
    return response


class ApiClient(GenericApiClient):
    """One method per PRD §4 endpoint."""

    def _request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ) -> requests.Response:
        response = super()._request(method, path, payload, headers, params)
        return _install_canonical_json(response)

    # ─── Logical clock (PRD §2.6) ─────────────────────────────────────

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Clients (PRD §3.1) ───────────────────────────────────────────

    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", None, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", params, headers)

    # ─── Projects (PRD §3.1) ──────────────────────────────────────────

    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", None, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", params, headers)

    def activate_project(self, project_id, headers, payload=None):
        return self._request(
            "POST", f"/projects/{project_id}/activate", payload or {}, headers
        )

    def lock_period(self, project_id, payload, headers):
        return self._request(
            "POST", f"/projects/{project_id}/lock-period", payload, headers
        )

    def get_wip_aging(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}/wip-aging", None, headers)

    # ─── Phases (PRD §3.1, §3.6) ──────────────────────────────────────

    def create_phase(self, payload, headers):
        return self._request("POST", "/phases", payload, headers)

    def get_phase(self, phase_id, headers):
        return self._request("GET", f"/phases/{phase_id}", None, headers)

    def list_phases(self, headers, params=None):
        return self._request("GET", "/phases", params, headers)

    def assess_phase(self, phase_id, payload, headers):
        return self._request("POST", f"/phases/{phase_id}/assess", payload, headers)

    def complete_phase(self, phase_id, headers, payload=None):
        return self._request(
            "POST", f"/phases/{phase_id}/complete", payload or {}, headers
        )

    def get_earned_value(self, phase_id, headers):
        return self._request("GET", f"/phases/{phase_id}/earned-value", None, headers)

    # ─── Labour rates (PRD §3.2) ──────────────────────────────────────

    def create_labor_rate(self, payload, headers):
        return self._request("POST", "/labor-rates", payload, headers)

    def list_labor_rates(self, headers, params=None):
        return self._request("GET", "/labor-rates", params, headers)

    # ─── Billing multipliers (PRD §3.2, §2.7) ─────────────────────────

    def create_billing_multiplier(self, payload, headers):
        return self._request("POST", "/billing-multipliers", payload, headers)

    def get_billing_multiplier(self, billing_multiplier_id, headers):
        return self._request(
            "GET", f"/billing-multipliers/{billing_multiplier_id}", None, headers
        )

    def list_billing_multipliers(self, headers, params=None):
        return self._request("GET", "/billing-multipliers", params, headers)

    # ─── Time entries (PRD §3.3) ──────────────────────────────────────

    def create_time_entry(self, payload, headers):
        return self._request("POST", "/time-entries", payload, headers)

    def get_time_entry(self, time_entry_id, headers):
        return self._request("GET", f"/time-entries/{time_entry_id}", None, headers)

    def list_time_entries(self, headers, params=None):
        return self._request("GET", "/time-entries", params, headers)

    def approve_time_entry(self, time_entry_id, headers, payload=None):
        return self._request(
            "POST", f"/time-entries/{time_entry_id}/approve", payload or {}, headers
        )

    # ─── Expenses (PRD §3.4) ──────────────────────────────────────────

    def create_expense(self, payload, headers):
        return self._request("POST", "/expenses", payload, headers)

    def get_expense(self, expense_id, headers):
        return self._request("GET", f"/expenses/{expense_id}", None, headers)

    def list_expenses(self, headers, params=None):
        return self._request("GET", "/expenses", params, headers)

    def review_expense(self, expense_id, payload, headers):
        return self._request("POST", f"/expenses/{expense_id}/review", payload, headers)

    # ─── Consultant subcontracts (PRD §3.5) ───────────────────────────

    def create_subcontract(self, payload, headers):
        return self._request("POST", "/consultant-subcontracts", payload, headers)

    def get_subcontract(self, subcontract_id, headers):
        return self._request(
            "GET", f"/consultant-subcontracts/{subcontract_id}", None, headers
        )

    def list_subcontracts(self, headers, params=None):
        return self._request("GET", "/consultant-subcontracts", params, headers)

    def execute_subcontract(self, subcontract_id, headers, payload=None):
        return self._request(
            "POST",
            f"/consultant-subcontracts/{subcontract_id}/execute",
            payload or {},
            headers,
        )

    # ─── Consultant payables (PRD §3.5) ───────────────────────────────

    def create_consultant_invoice(self, payload, headers):
        return self._request("POST", "/consultant-invoices", payload, headers)

    def get_consultant_invoice(self, consultant_invoice_id, headers):
        return self._request(
            "GET", f"/consultant-invoices/{consultant_invoice_id}", None, headers
        )

    def list_consultant_invoices(self, headers, params=None):
        return self._request("GET", "/consultant-invoices", params, headers)

    def approve_consultant_invoice(self, consultant_invoice_id, headers, payload=None):
        return self._request(
            "POST",
            f"/consultant-invoices/{consultant_invoice_id}/approve",
            payload or {},
            headers,
        )

    def reject_consultant_invoice(self, consultant_invoice_id, payload, headers):
        return self._request(
            "POST",
            f"/consultant-invoices/{consultant_invoice_id}/reject",
            payload,
            headers,
        )

    def release_consultant_payment(self, consultant_invoice_id, headers, payload=None):
        return self._request(
            "POST",
            f"/consultant-invoices/{consultant_invoice_id}/release-payment",
            payload or {},
            headers,
        )

    # ─── Client invoices (PRD §3.7) ───────────────────────────────────

    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", None, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", params, headers)

    def submit_invoice(self, invoice_id, headers, payload=None):
        return self._request(
            "POST", f"/invoices/{invoice_id}/submit", payload or {}, headers
        )

    def review_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/review", payload, headers)

    def revise_invoice(self, invoice_id, headers, payload=None):
        return self._request(
            "POST", f"/invoices/{invoice_id}/revise", payload or {}, headers
        )

    def record_invoice_payment(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/invoices/{invoice_id}/record-payment", payload, headers
        )

    def void_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", payload, headers)

    # ─── Write-offs (PRD §3.8) ────────────────────────────────────────

    def create_write_off(self, payload, headers):
        return self._request("POST", "/write-offs", payload, headers)

    def get_write_off(self, write_off_id, headers):
        return self._request("GET", f"/write-offs/{write_off_id}", None, headers)

    def list_write_offs(self, headers, params=None):
        return self._request("GET", "/write-offs", params, headers)

    def approve_write_off(self, write_off_id, headers, payload=None):
        return self._request(
            "POST", f"/write-offs/{write_off_id}/approve", payload or {}, headers
        )

    # ─── Overhead rate certifications (PRD §3.9) ──────────────────────

    def create_certification(self, payload, headers):
        return self._request("POST", "/overhead-certifications", payload, headers)

    def get_certification(self, certification_id, headers):
        return self._request(
            "GET", f"/overhead-certifications/{certification_id}", None, headers
        )

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/overhead-certifications", params, headers)

    def certify_certification(self, certification_id, headers, payload=None):
        return self._request(
            "POST",
            f"/overhead-certifications/{certification_id}/certify",
            payload or {},
            headers,
        )

    def return_certification_findings(self, certification_id, payload, headers):
        return self._request(
            "POST",
            f"/overhead-certifications/{certification_id}/return-findings",
            payload,
            headers,
        )
