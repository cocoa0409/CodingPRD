"""One method per endpoint of PRD S4, plus instant canonicalisation.

PRD S2.4 fixes every timestamp the server writes to an ISO 8601 UTC instant
with exactly three fractional digits.  Rather than compare raw strings at every
call site — which would turn a harmless sub-second width difference into dozens
of failures — this client rewrites every instant-shaped string in a JSON
response into that canonical three-digit form before the test sees it.  The
canonical width itself is asserted separately, against the raw payload, by
``assertions.assert_instant_format``.
"""

import json
import re
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})$"
)


def canonical_instant(value: Any) -> Any:
    """Rewrite an ISO 8601 instant to ``YYYY-MM-DDTHH:MM:SS.mmmZ``.

    Non-instant values (and offsets other than UTC, which the PRD never uses)
    are returned untouched.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value)
    if not match:
        return value
    date, hh, mm, ss, frac, offset = match.groups()
    if offset not in ("Z", "z", "+00:00", "+0000", "-00:00", "-0000"):
        return value
    millis = 0
    if frac:
        digits = (frac[1:] + "000")[:3]
        millis = int(digits)
    return f"{date}T{hh}:{mm}:{ss}.{millis:03d}Z"


def _canonicalise(node: Any) -> Any:
    if isinstance(node, dict):
        return {key: _canonicalise(val) for key, val in node.items()}
    if isinstance(node, list):
        return [_canonicalise(item) for item in node]
    return canonical_instant(node)


def raw_body(response) -> Any:
    """The response body exactly as the server sent it, before canonicalisation.

    Use this when the assertion is about the on-the-wire *width* of a timestamp
    rather than the instant it denotes.
    """
    return getattr(response, "_raw_body", None) or response.json()


class ApiClient(GenericApiClient):
    """Endpoint methods for the Motor Carrier Operating Authority API."""

    # -- request plumbing --------------------------------------------------
    def _request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ) -> requests.Response:
        response = super()._request(method, path, payload, headers, params)
        try:
            body = response.json()
        except Exception:
            return response
        response._raw_body = body
        canonical = _canonicalise(body)
        if canonical != body:
            response._content = json.dumps(canonical).encode("utf-8")
        return response

    # -- S2.5 the logical compliance clock --------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # -- S3.1 registry -----------------------------------------------------
    def create_carrier(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/carriers", payload, headers)

    def get_carrier(self, carrier_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/carriers/{carrier_id}", None, headers)

    def list_carrier_safety_audits(
        self, carrier_id: str, headers: Dict[str, str], **params: Any
    ):
        return self._request(
            "GET", f"/carriers/{carrier_id}/safety-audits", params or None, headers
        )

    def list_fee_ledger_entries(
        self, carrier_id: str, headers: Dict[str, str], **params: Any
    ):
        return self._request(
            "GET",
            f"/carriers/{carrier_id}/fee-ledger-entries",
            params or None,
            headers,
        )

    def file_biennial_update(
        self, carrier_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/carriers/{carrier_id}/biennial-update", payload, headers
        )

    def record_fee_payment(
        self, carrier_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/carriers/{carrier_id}/fee-payments", payload, headers
        )

    def create_process_agent(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/process-agents", payload, headers)

    def create_insurer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/insurers", payload, headers)

    # -- S3.2 / S3.3 applications -----------------------------------------
    def create_application(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/authority-applications", payload, headers)

    def get_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/authority-applications/{application_id}", None, headers
        )

    def list_applications(self, headers: Dict[str, str], **params: Any):
        return self._request("GET", "/authority-applications", params or None, headers)

    def submit_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/authority-applications/{application_id}/submit", {}, headers
        )

    def review_application(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/authority-applications/{application_id}/vetting-review",
            payload,
            headers,
        )

    # -- S3.4 authorities and designations --------------------------------
    def get_authority(self, authority_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/operating-authorities/{authority_id}", None, headers
        )

    def list_authorities(self, headers: Dict[str, str], **params: Any):
        return self._request("GET", "/operating-authorities", params or None, headers)

    def list_authority_proceedings(
        self, authority_id: str, headers: Dict[str, str], **params: Any
    ):
        return self._request(
            "GET",
            f"/operating-authorities/{authority_id}/revocation-proceedings",
            params or None,
            headers,
        )

    def create_designations(
        self, authority_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/operating-authorities/{authority_id}/process-agent-designations",
            payload,
            headers,
        )

    def get_designation(self, designation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/process-agent-designations/{designation_id}", None, headers
        )

    def list_designations(self, headers: Dict[str, str], **params: Any):
        return self._request(
            "GET", "/process-agent-designations", params or None, headers
        )

    def revoke_designation(self, designation_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/process-agent-designations/{designation_id}/revoke", {}, headers
        )

    # -- S3.5 insurance filings -------------------------------------------
    def create_filing(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/insurance-filings", payload, headers)

    def get_filing(self, filing_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/insurance-filings/{filing_id}", None, headers)

    def list_filings(self, headers: Dict[str, str], **params: Any):
        return self._request("GET", "/insurance-filings", params or None, headers)

    def cancel_filing(
        self, filing_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/insurance-filings/{filing_id}/cancel", payload, headers
        )

    # -- S3.6 / S3.7 activation and audits --------------------------------
    def activate_authority(self, authority_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/operating-authorities/{authority_id}/activate", {}, headers
        )

    def record_audit_result(
        self, audit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/safety-audits/{audit_id}/record-result", payload, headers
        )

    # -- S3.8 proceedings and the sweep -----------------------------------
    def cure_proceeding(
        self, proceeding_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/revocation-proceedings/{proceeding_id}/cure", payload, headers
        )

    def run_compliance_sweep(self, headers: Dict[str, str]):
        return self._request("POST", "/compliance-sweeps", {}, headers)

    # -- S3.9 contracts and shipments -------------------------------------
    def create_contract(
        self, authority_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/operating-authorities/{authority_id}/customer-contracts",
            payload,
            headers,
        )

    def list_authority_contracts(
        self, authority_id: str, headers: Dict[str, str], **params: Any
    ):
        return self._request(
            "GET",
            f"/operating-authorities/{authority_id}/customer-contracts",
            params or None,
            headers,
        )

    def get_contract(self, contract_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/customer-contracts/{contract_id}", None, headers)

    def create_shipment(
        self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/customer-contracts/{contract_id}/shipments", payload, headers
        )

    def get_shipment(self, shipment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/shipments/{shipment_id}", None, headers)

    def list_shipments(self, headers: Dict[str, str], **params: Any):
        return self._request("GET", "/shipments", params or None, headers)

    def depart_shipment(self, shipment_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/shipments/{shipment_id}/depart", {}, headers)

    def deliver_shipment(self, shipment_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/shipments/{shipment_id}/deliver", {}, headers)
