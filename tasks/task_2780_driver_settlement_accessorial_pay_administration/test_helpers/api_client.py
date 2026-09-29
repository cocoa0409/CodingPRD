"""
Domain API client: one method per endpoint of the service under test.

Every method returns the raw requests.Response so the caller decides whether the
call was meant to succeed or fail. All business endpoints are mounted under the
/driver-pay prefix; the logical-clock control endpoint is the single exception.

Timestamp canonicalisation
--------------------------
The service echoes ISO-8601 UTC instants, and sub-second precision is a
presentation detail rather than part of the contract: "2026-08-10T09:00:00Z",
"2026-08-10T09:00:00.000Z" and "2026-08-10T09:00:00.000000Z" all denote the same
instant. canonical_ts() collapses those spellings onto one canonical form so that
tests compare instants instead of string spellings.
"""

import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

BASE_PREFIX = "/driver-pay"

_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[Tt](\d{2}:\d{2}:\d{2})(\.\d+)?(Z|z|[+-]\d{2}:?\d{2})$"
)


def canonical_ts(value: Optional[str]) -> Optional[str]:
    """
    Collapse an ISO-8601 UTC instant onto the canonical spelling
    'YYYY-MM-DDTHH:MM:SSZ', discarding a zero sub-second part and normalising a
    '+00:00' offset to 'Z'. Non-timestamp values are returned unchanged.
    """
    if not isinstance(value, str):
        return value
    match = _TS_RE.match(value)
    if not match:
        return value
    date_part, time_part, fraction, offset = match.groups()
    if fraction and fraction.strip(".0") != "":
        # A genuine non-zero fractional part is preserved as-is.
        return f"{date_part}T{time_part}{fraction}Z" if offset.upper() in ("Z", "+00:00", "+0000") else value
    if offset.upper() in ("Z", "+00:00", "+0000"):
        return f"{date_part}T{time_part}Z"
    return value


class ApiClient(GenericApiClient):
    """One method per endpoint; no request-shaping logic beyond path assembly."""

    # ── Logical clock ────────────────────────────────
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Pay packages ─────────────────────────────────
    def create_pay_package(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{BASE_PREFIX}/pay-packages", payload, headers)

    def list_pay_packages(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{BASE_PREFIX}/pay-packages", headers=headers, params=params
        )

    def get_pay_package(self, package_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE_PREFIX}/pay-packages/{package_id}", headers=headers
        )

    def add_component(self, package_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE_PREFIX}/pay-packages/{package_id}/components", payload, headers
        )

    def list_components(
        self, package_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{BASE_PREFIX}/pay-packages/{package_id}/components",
            headers=headers,
            params=params,
        )

    def activate_pay_package(
        self, package_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"{BASE_PREFIX}/pay-packages/{package_id}/activate", payload, headers
        )

    def revise_pay_package(self, package_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE_PREFIX}/pay-packages/{package_id}/revise", payload, headers
        )

    def retire_pay_package(
        self, package_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"{BASE_PREFIX}/pay-packages/{package_id}/retire", payload, headers
        )

    # ── Drivers ──────────────────────────────────────
    def create_driver(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{BASE_PREFIX}/drivers", payload, headers)

    def list_drivers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{BASE_PREFIX}/drivers", headers=headers, params=params
        )

    def get_driver(self, driver_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE_PREFIX}/drivers/{driver_id}", headers=headers
        )

    def assign_pay_package(self, driver_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE_PREFIX}/drivers/{driver_id}/assign-pay-package", payload, headers
        )

    def set_driver_status(self, driver_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE_PREFIX}/drivers/{driver_id}/status", payload, headers
        )

    def close_escrow(self, driver_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request(
            "POST", f"{BASE_PREFIX}/drivers/{driver_id}/escrow/close", payload, headers
        )

    def create_escrow_deduction(
        self, driver_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE_PREFIX}/drivers/{driver_id}/escrow/deductions", payload, headers
        )

    def return_escrow(self, driver_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request(
            "POST", f"{BASE_PREFIX}/drivers/{driver_id}/escrow/return", payload, headers
        )

    # ── Escrow ledger ────────────────────────────────
    def list_escrow_transactions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{BASE_PREFIX}/escrow-transactions", headers=headers, params=params
        )

    def get_escrow_transaction(self, txn_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE_PREFIX}/escrow-transactions/{txn_id}", headers=headers
        )

    def reverse_escrow_transaction(
        self, txn_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE_PREFIX}/escrow-transactions/{txn_id}/reverse", payload, headers
        )

    # ── Loads ────────────────────────────────────────
    def create_load(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{BASE_PREFIX}/loads", payload, headers)

    def list_loads(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE_PREFIX}/loads", headers=headers, params=params)

    def get_load(self, load_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE_PREFIX}/loads/{load_id}", headers=headers)

    def dispatch_load(self, load_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE_PREFIX}/loads/{load_id}/dispatch", payload, headers
        )

    def deliver_load(self, load_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE_PREFIX}/loads/{load_id}/deliver", payload, headers
        )

    # ── Accessorial claims ───────────────────────────
    def create_accessorial_claim(self, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE_PREFIX}/accessorial-claims", payload, headers
        )

    def list_accessorial_claims(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{BASE_PREFIX}/accessorial-claims", headers=headers, params=params
        )

    def get_accessorial_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE_PREFIX}/accessorial-claims/{claim_id}", headers=headers
        )

    def attach_claim_document(self, claim_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE_PREFIX}/accessorial-claims/{claim_id}/documents", payload, headers
        )

    def approve_accessorial_claim(
        self, claim_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"{BASE_PREFIX}/accessorial-claims/{claim_id}/approve", payload, headers
        )

    def reject_accessorial_claim(
        self, claim_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE_PREFIX}/accessorial-claims/{claim_id}/reject", payload, headers
        )

    # ── Advances ─────────────────────────────────────
    def create_advance(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{BASE_PREFIX}/advances", payload, headers)

    def list_advances(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{BASE_PREFIX}/advances", headers=headers, params=params
        )

    def get_advance(self, advance_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE_PREFIX}/advances/{advance_id}", headers=headers
        )

    def cancel_advance(
        self, advance_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"{BASE_PREFIX}/advances/{advance_id}/cancel", payload, headers
        )

    # ── Settlements ──────────────────────────────────
    def create_settlement(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{BASE_PREFIX}/settlements", payload, headers)

    def list_settlements(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{BASE_PREFIX}/settlements", headers=headers, params=params
        )

    def get_settlement(self, settlement_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE_PREFIX}/settlements/{settlement_id}", headers=headers
        )

    def list_settlement_lines(
        self, settlement_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{BASE_PREFIX}/settlements/{settlement_id}/lines",
            headers=headers,
            params=params,
        )

    def apply_corrections(
        self, settlement_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{BASE_PREFIX}/settlements/{settlement_id}/apply-corrections",
            payload,
            headers,
        )

    def prepare_settlement(
        self, settlement_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE_PREFIX}/settlements/{settlement_id}/prepare", payload, headers
        )

    def approve_settlement(
        self, settlement_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"{BASE_PREFIX}/settlements/{settlement_id}/approve", payload, headers
        )

    def pay_settlement(self, settlement_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE_PREFIX}/settlements/{settlement_id}/pay", payload, headers
        )

    def void_settlement(self, settlement_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE_PREFIX}/settlements/{settlement_id}/void", payload, headers
        )

    # ── Disputes ─────────────────────────────────────
    def create_dispute(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{BASE_PREFIX}/disputes", payload, headers)

    def list_disputes(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{BASE_PREFIX}/disputes", headers=headers, params=params
        )

    def get_dispute(self, dispute_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE_PREFIX}/disputes/{dispute_id}", headers=headers
        )

    def review_dispute(
        self, dispute_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"{BASE_PREFIX}/disputes/{dispute_id}/review", payload, headers
        )

    def resolve_dispute(self, dispute_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE_PREFIX}/disputes/{dispute_id}/resolve", payload, headers
        )

    def reopen_dispute(self, dispute_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE_PREFIX}/disputes/{dispute_id}/reopen", payload, headers
        )

    def withdraw_dispute(
        self, dispute_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"{BASE_PREFIX}/disputes/{dispute_id}/withdraw", payload, headers
        )

    # ── Retroactive corrections ──────────────────────
    def list_retro_corrections(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{BASE_PREFIX}/retro-corrections", headers=headers, params=params
        )

    def get_retro_correction(self, correction_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE_PREFIX}/retro-corrections/{correction_id}", headers=headers
        )

    def cancel_retro_correction(
        self, correction_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST",
            f"{BASE_PREFIX}/retro-corrections/{correction_id}/cancel",
            payload,
            headers,
        )


api_client = ApiClient()
