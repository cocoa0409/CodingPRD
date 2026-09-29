"""Typed HTTP client for the presort bureau API.

One method per endpoint, each returning the raw response so tests can assert on
status codes as well as bodies. Every method takes an explicit ``headers``
argument because role and identity are part of what most tests are exercising.

Instant canonicalisation lives here and nowhere else. The contract declares
every persisted instant as an ISO 8601 UTC value with exactly three fractional
digits, so this client rewrites any instant-shaped string in a response body
into that canonical form before the test sees it. A server that answers
``2026-08-12T14:00:00+00:00`` or ``2026-08-12T14:00:00.000000Z`` is still
answering the same instant; normalising once here keeps every test free of
per-field timestamp munging.
"""

import copy
import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[Tt](\d{2}:\d{2}:\d{2})(\.\d+)?"
    r"(?:[Zz]|[+-]00:?00)$"
)


def canonicalize_instant(value: str) -> str:
    """Rewrite an instant-shaped string to ``YYYY-MM-DDTHH:MM:SS.mmmZ``."""
    match = _INSTANT_RE.match(value)
    if not match:
        return value
    date_part, time_part, fraction = match.group(1), match.group(2), match.group(3)
    millis = (fraction or ".")[1:]
    millis = (millis + "000")[:3]
    return f"{date_part}T{time_part}.{millis}Z"


def canonicalize(node: Any) -> Any:
    """Recursively canonicalise every instant-shaped string in a JSON tree."""
    if isinstance(node, str):
        return canonicalize_instant(node)
    if isinstance(node, list):
        return [canonicalize(item) for item in node]
    if isinstance(node, dict):
        return {key: canonicalize(value) for key, value in node.items()}
    return node


def _install_canonical_json(response):
    """Replace ``response.json`` with one that yields canonicalised instants."""
    try:
        raw = response.json()
    except ValueError:
        return response
    canonical = canonicalize(raw)
    response.json = lambda **_kwargs: copy.deepcopy(canonical)
    return response


class ApiClient(GenericApiClient):
    """Presort bureau API client: one method per endpoint."""

    def _request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        response = super()._request(method, path, payload, headers, params)
        return _install_canonical_json(response)

    # ─── Clients ──────────────────────────────────────────────────────────

    def create_client(self, payload: Dict, headers: Dict):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id: str, headers: Dict):
        return self._request("GET", f"/clients/{client_id}", None, headers)

    def set_client_status(self, client_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/clients/{client_id}/status", payload, headers)

    def list_client_permit_accounts(self, client_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/clients/{client_id}/permit-accounts", params, headers
        )

    def list_client_mail_jobs(self, client_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"/clients/{client_id}/mail-jobs", params, headers)

    def list_client_invoices(self, client_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"/clients/{client_id}/invoices", params, headers)

    def create_client_invoice(self, client_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/clients/{client_id}/invoices", payload, headers)

    def get_client_service_level(self, client_id: str, headers: Dict):
        return self._request("GET", f"/clients/{client_id}/service-level", None, headers)

    # ─── Permit accounts ──────────────────────────────────────────────────

    def create_permit_account(self, payload: Dict, headers: Dict):
        return self._request("POST", "/permit-accounts", payload, headers)

    def get_permit_account(self, permit_account_id: str, headers: Dict):
        return self._request("GET", f"/permit-accounts/{permit_account_id}", None, headers)

    def fund_permit_account(self, permit_account_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/permit-accounts/{permit_account_id}/funding", payload, headers
        )

    def set_permit_account_status(self, permit_account_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/permit-accounts/{permit_account_id}/status", payload, headers
        )

    def list_permit_account_statements(self, permit_account_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET",
            f"/permit-accounts/{permit_account_id}/postage-statements",
            params,
            headers,
        )

    # ─── Mail jobs ────────────────────────────────────────────────────────

    def create_mail_job(self, payload: Dict, headers: Dict):
        return self._request("POST", "/mail-jobs", payload, headers)

    def get_mail_job(self, mail_job_id: str, headers: Dict):
        return self._request("GET", f"/mail-jobs/{mail_job_id}", None, headers)

    def list_mail_jobs(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/mail-jobs", params, headers)

    def create_hygiene_run(self, mail_job_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/mail-jobs/{mail_job_id}/hygiene-runs", payload, headers
        )

    def list_hygiene_runs(self, mail_job_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/mail-jobs/{mail_job_id}/hygiene-runs", params, headers
        )

    def list_job_batch_memberships(self, mail_job_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/mail-jobs/{mail_job_id}/batch-memberships", params, headers
        )

    def cancel_mail_job(self, mail_job_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/mail-jobs/{mail_job_id}/cancel", payload, headers)

    def get_postage_estimate(self, mail_job_id: str, headers: Dict):
        return self._request(
            "GET", f"/mail-jobs/{mail_job_id}/postage-estimate", None, headers
        )

    # ─── Entry facilities ─────────────────────────────────────────────────

    def create_entry_facility(self, payload: Dict, headers: Dict):
        return self._request("POST", "/entry-facilities", payload, headers)

    def get_entry_facility(self, entry_facility_id: str, headers: Dict):
        return self._request("GET", f"/entry-facilities/{entry_facility_id}", None, headers)

    def set_entry_facility_status(self, entry_facility_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/entry-facilities/{entry_facility_id}/status", payload, headers
        )

    def list_facility_drop_shipments(self, entry_facility_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/entry-facilities/{entry_facility_id}/drop-shipments", params, headers
        )

    # ─── Commingle batches ────────────────────────────────────────────────

    def create_commingle_batch(self, payload: Dict, headers: Dict):
        return self._request("POST", "/commingle-batches", payload, headers)

    def get_commingle_batch(self, commingle_batch_id: str, headers: Dict):
        return self._request("GET", f"/commingle-batches/{commingle_batch_id}", None, headers)

    def list_commingle_batches(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/commingle-batches", params, headers)

    def add_batch_member(self, commingle_batch_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/commingle-batches/{commingle_batch_id}/members", payload, headers
        )

    def list_batch_members(self, commingle_batch_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/commingle-batches/{commingle_batch_id}/members", params, headers
        )

    def remove_batch_member(self, commingle_batch_id: str, batch_member_id: str, headers: Dict):
        return self._request(
            "DELETE",
            f"/commingle-batches/{commingle_batch_id}/members/{batch_member_id}",
            None,
            headers,
        )

    def add_sort_container(self, commingle_batch_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/commingle-batches/{commingle_batch_id}/containers", payload, headers
        )

    def list_batch_containers(self, commingle_batch_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/commingle-batches/{commingle_batch_id}/containers", params, headers
        )

    def sort_batch(self, commingle_batch_id: str, headers: Dict):
        return self._request(
            "POST", f"/commingle-batches/{commingle_batch_id}/sort", {}, headers
        )

    def list_batch_postage_statements(self, commingle_batch_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET",
            f"/commingle-batches/{commingle_batch_id}/postage-statements",
            params,
            headers,
        )

    def list_batch_drop_shipments(self, commingle_batch_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/commingle-batches/{commingle_batch_id}/drop-shipments", params, headers
        )

    # ─── Sort containers ──────────────────────────────────────────────────

    def get_sort_container(self, sort_container_id: str, headers: Dict):
        return self._request("GET", f"/sort-containers/{sort_container_id}", None, headers)

    def list_container_service_level_records(self, sort_container_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET",
            f"/sort-containers/{sort_container_id}/service-level-records",
            params,
            headers,
        )

    # ─── Drop shipments ───────────────────────────────────────────────────

    def create_drop_shipment(self, payload: Dict, headers: Dict):
        return self._request("POST", "/drop-shipments", payload, headers)

    def get_drop_shipment(self, drop_shipment_id: str, headers: Dict):
        return self._request("GET", f"/drop-shipments/{drop_shipment_id}", None, headers)

    def depart_drop_shipment(self, drop_shipment_id: str, headers: Dict):
        return self._request(
            "POST", f"/drop-shipments/{drop_shipment_id}/depart", {}, headers
        )

    def deposit_drop_shipment(self, drop_shipment_id: str, headers: Dict):
        return self._request(
            "POST", f"/drop-shipments/{drop_shipment_id}/deposit", {}, headers
        )

    def cancel_drop_shipment(self, drop_shipment_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/drop-shipments/{drop_shipment_id}/cancel", payload, headers
        )

    # ─── Postage statements ───────────────────────────────────────────────

    def create_postage_statement(self, payload: Dict, headers: Dict):
        return self._request("POST", "/postage-statements", payload, headers)

    def get_postage_statement(self, postage_statement_id: str, headers: Dict):
        return self._request(
            "GET", f"/postage-statements/{postage_statement_id}", None, headers
        )

    def submit_postage_statement(self, postage_statement_id: str, headers: Dict):
        return self._request(
            "POST", f"/postage-statements/{postage_statement_id}/submit", {}, headers
        )

    def create_finding(self, postage_statement_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/postage-statements/{postage_statement_id}/findings", payload, headers
        )

    def list_findings(self, postage_statement_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/postage-statements/{postage_statement_id}/findings", params, headers
        )

    def verify_postage_statement(self, postage_statement_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/postage-statements/{postage_statement_id}/verify", payload, headers
        )

    def void_postage_statement(self, postage_statement_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/postage-statements/{postage_statement_id}/void", payload, headers
        )

    def revise_postage_statement(self, postage_statement_id: str, headers: Dict):
        return self._request(
            "POST", f"/postage-statements/{postage_statement_id}/revise", {}, headers
        )

    # ─── Service-level records ────────────────────────────────────────────

    def get_service_level_record(self, service_level_record_id: str, headers: Dict):
        return self._request(
            "GET", f"/service-level-records/{service_level_record_id}", None, headers
        )

    def record_delivery_scan(self, service_level_record_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST",
            f"/service-level-records/{service_level_record_id}/delivery-scan",
            payload,
            headers,
        )

    # ─── Client invoices ──────────────────────────────────────────────────

    def get_client_invoice(self, client_invoice_id: str, headers: Dict):
        return self._request("GET", f"/client-invoices/{client_invoice_id}", None, headers)

    def pay_client_invoice(self, client_invoice_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/client-invoices/{client_invoice_id}/payment", payload, headers
        )

    # ─── Logical clock ────────────────────────────────────────────────────

    def set_clock(self, to_iso8601: str, headers: Dict):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )
