"""Payload factories — one per creatable resource, input fields only.

Each factory supplies valid defaults that tests can override. Defaults use a
shared base date so a test can rotate the settlement date explicitly.
"""

from typing import Any, Dict, Optional

DEFAULTS = {
    "EXTERNAL_REF": "member-ref-1",
    "FULL_NAME": "Test Member",
    "ENROLLED_AT": "2025-09-01T00:00:00Z",
    "ACCOUNT_TYPE": "SPENDING",
    "ORIGINATOR_ID": "EMP-1",
    "ORIGINATOR_TYPE": "PAYROLL",
    "DEPOSIT_AMOUNT_CENTS": 10000,
    "SETTLEMENT_DATE": "2026-09-10T00:00:00Z",
    "ADVANCE_AMOUNT_CENTS": 1000,
    "RETURN_CODE": "R01_INSUFFICIENT",
    "STATEMENT": "member dispute statement",
    "RESOLUTION_NOTE": "resolution note",
    "WRITE_OFF_REASON": "aged beyond 60 days",
    "BANK_REPORTED_NET_CENTS": 0,
}

_ref_counter = {"n": 0}


def _unique(prefix: str) -> str:
    _ref_counter["n"] += 1
    return f"{prefix}-{_ref_counter['n']}"


def member_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "external_ref": _unique(DEFAULTS["EXTERNAL_REF"]),
        "full_name": DEFAULTS["FULL_NAME"],
        "enrolled_at": DEFAULTS["ENROLLED_AT"],
    }
    defaults.update(overrides)
    return defaults


def account_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"account_type": DEFAULTS["ACCOUNT_TYPE"]}
    defaults.update(overrides)
    return defaults


def deposit_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "originator_id": DEFAULTS["ORIGINATOR_ID"],
        "originator_type": DEFAULTS["ORIGINATOR_TYPE"],
        "amount_cents": DEFAULTS["DEPOSIT_AMOUNT_CENTS"],
        "settlement_date": DEFAULTS["SETTLEMENT_DATE"],
        "trace_id": _unique("trace"),
    }
    defaults.update(overrides)
    return defaults


def advance_payload(expected_account_version: int, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "amount_cents": DEFAULTS["ADVANCE_AMOUNT_CENTS"],
        "idempotency_key": _unique("idem"),
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def debit_payload(expected_account_version: int, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "amount_cents": DEFAULTS["ADVANCE_AMOUNT_CENTS"],
        "merchant_ref": _unique("mref"),
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def evaluation_payload(expected_member_version: int, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "evaluation_mode": "BATCH",
        "expected_member_version": expected_member_version,
    }
    defaults.update(overrides)
    return defaults


def abuse_event_payload(expected_member_version: int, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "event_type": "CUSHION_CYCLING",
        "expected_member_version": expected_member_version,
    }
    defaults.update(overrides)
    return defaults


def deposit_return_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"return_code": DEFAULTS["RETURN_CODE"]}
    defaults.update(overrides)
    return defaults


def reconciliation_run_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "sponsor_bank_code": "SB-1",
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-08-08T00:00:00Z",
        "bank_reported_net_cents": DEFAULTS["BANK_REPORTED_NET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def run_resolve_payload(expected_run_version: int, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "expected_run_version": expected_run_version,
        "resolution_note": DEFAULTS["RESOLUTION_NOTE"],
    }
    defaults.update(overrides)
    return defaults


def dispute_payload(deposit_id: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "deposit_id": deposit_id,
        "dispute_type": "EARLY_POSTING_REVERSAL",
        "amount_cents": 1000,
        "statement": DEFAULTS["STATEMENT"],
    }
    defaults.update(overrides)
    return defaults


def dispute_resolve_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "outcome": "MEMBER",
        "resolution_note": DEFAULTS["RESOLUTION_NOTE"],
    }
    defaults.update(overrides)
    return defaults


def write_off_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"reason": DEFAULTS["WRITE_OFF_REASON"]}
    defaults.update(overrides)
    return defaults


def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}
