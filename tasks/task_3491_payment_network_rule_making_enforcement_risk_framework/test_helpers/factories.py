"""Payload factories — one per creatable entity, input fields only.

Factories never include system/computed fields (status, version, timestamps,
exposure figures, fees, tallies, derived classes). Server-supplied fields sent
by mistake are a Stage 2 concern and are built by adding an override key, not
by factory defaults.

Uniqueness: routing_number (exactly 9 ASCII digits), transaction-code code
(2-3 uppercase letters), and settlement-window window_code are unique
network-wide, so defaults come from per-process counters in ranges that cannot
collide with the literal values the design instances pass explicitly.
"""

import itertools

from .constants import CLOCK_START_ISO

# --- unique-value generators ---------------------------------------------------

_ROUTING_COUNTER = itertools.count(900_000_001)  # 9-digit strings, no clash with "1110000xx" literals
_CODE_COUNTER = itertools.count(0)
_WINDOW_COUNTER = itertools.count(100)  # "W100"+ — no clash with literal "W1"/"W2"/"W3"
_HASH_COUNTER = itertools.count(1)
_NAME_COUNTER = itertools.count(1)


def next_routing_number() -> str:
    """Unique 9-ASCII-digit routing transit number."""
    return f"{next(_ROUTING_COUNTER):09d}"


def next_code() -> str:
    """Unique 2-3 uppercase-letter transaction code."""
    n = next(_CODE_COUNTER)
    if n < 26 * 26:
        return chr(ord("A") + n // 26) + chr(ord("A") + n % 26)
    n -= 26 * 26
    return "Z" + chr(ord("A") + n // 26) + chr(ord("A") + n % 26)


def next_window_code() -> str:
    return f"W{next(_WINDOW_COUNTER)}"


def next_account_hash() -> str:
    return f"acct-{next(_HASH_COUNTER):04d}"


def _next_name(prefix: str) -> str:
    return f"{prefix} {next(_NAME_COUNTER)}"


# The default rule-proposal effective_date. Must be strictly after the creation
# date; tests normally create proposals near the boot clock (2026-09-01), so a
# 2027 date is safely after. Tests needing EFFECTIVE rules pass an earlier date
# reachable by the logical clock.
DEFAULT_EFFECTIVE_DATE = "2027-01-01"


# =============================================================================
# Create payloads
# =============================================================================


def create_participant_payload(**overrides) -> dict:
    defaults = {
        "legal_name": _next_name("Test Bank"),
        "participant_type": "ODFI",
        "routing_number": next_routing_number(),
    }
    defaults.update(overrides)
    return defaults


def create_originator_payload(**overrides) -> dict:
    # participant_id is system-set from the officer's X-User-ID — never sent.
    defaults = {
        "legal_name": _next_name("Originator"),
        "risk_tier": "STANDARD",
        "exposure_limit_cents": 1_000_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_transaction_code_payload(**overrides) -> dict:
    defaults = {
        "code": next_code(),
        "entry_class": "DEBIT",
        "authorization_requirement": "NONE",
        "return_timeframe_banking_days": 30,
        "account_validation_required": False,
        "warranty_obligations": "ODFI warrants authorization for this entry class",
    }
    defaults.update(overrides)
    return defaults


def create_settlement_window_payload(**overrides) -> dict:
    defaults = {
        "window_code": next_window_code(),
        "cutoff_time_utc": "17:00",
        "per_entry_limit_cents": 100_000_000,
        "odfi_window_cap_cents": 2_500_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_rule_proposal_payload(transaction_code_id, **overrides) -> dict:
    defaults = {
        "transaction_code_id": transaction_code_id,
        "title": _next_name("Rule Proposal"),
        "summary": "Rule text summary and implementation guidance abstract",
        "effective_date": DEFAULT_EFFECTIVE_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_ballot_payload(vote="YEA", **overrides) -> dict:
    defaults = {"vote": vote}
    defaults.update(overrides)
    return defaults


def create_guidance_document_payload(
    rule_proposal_id, transaction_code_id, expected_transaction_code_version, **overrides
) -> dict:
    defaults = {
        "rule_proposal_id": rule_proposal_id,
        "transaction_code_id": transaction_code_id,
        "title": _next_name("Guidance"),
        "body_ref": f"doc-{_next_name('ref').replace(' ', '-')}",
        "effective_from": "2026-10-01",
        "effective_until": None,  # open-ended
        "supersede_prior": False,
        "expected_transaction_code_version": expected_transaction_code_version,
    }
    defaults.update(overrides)
    return defaults


def create_payment_entry_payload(originator_id, transaction_code_id, **overrides) -> dict:
    defaults = {
        "originator_id": originator_id,
        "transaction_code_id": transaction_code_id,
        "amount_cents": 1000,
        "receiver_account_number_hash": next_account_hash(),
        "receiver_name": _next_name("Receiver"),
        "authorization_type": "NONE",
        "same_day": False,
    }
    defaults.update(overrides)
    # settlement_window_id is only meaningful (and required) when same_day is
    # true; drop it entirely otherwise so the server assigns the window.
    if not defaults.get("same_day"):
        defaults.pop("settlement_window_id", None)
    return defaults


def create_return_payload(reason_code="UNAUTHORIZED_DEBIT", **overrides) -> dict:
    defaults = {"reason_code": reason_code}
    defaults.update(overrides)
    return defaults


def create_account_validation_payload(originator_id, account_number_hash=None, **overrides) -> dict:
    defaults = {
        "originator_id": originator_id,
        "account_number_hash": account_number_hash or next_account_hash(),
        "method": "MICRO_DEPOSIT",
    }
    defaults.update(overrides)
    return defaults


def create_return_rate_snapshot_payload(participant_id, period, **overrides) -> dict:
    defaults = {"participant_id": participant_id, "period": period}
    defaults.update(overrides)
    return defaults


def create_enforcement_action_payload(participant_id, violation_code="EXCESSIVE_UNAUTHORIZED_RETURNS", **overrides) -> dict:
    defaults = {"participant_id": participant_id, "violation_code": violation_code}
    defaults.update(overrides)
    return defaults


def create_attestation_payload(participant_id, period_year=2026, **overrides) -> dict:
    defaults = {"participant_id": participant_id, "period_year": period_year}
    defaults.update(overrides)
    return defaults


def create_audit_payload(participant_id, **overrides) -> dict:
    defaults = {
        "participant_id": participant_id,
        "start_date": "2026-06-01",
        "end_date": "2026-06-30",
    }
    defaults.update(overrides)
    return defaults


# =============================================================================
# Transition / action payloads
# =============================================================================


def transition_payload(to_state, **extra) -> dict:
    """Generic {to_state, ...} body for transition endpoints."""
    payload = {"to_state": to_state}
    payload.update(extra)
    return payload


def submit_attestation_payload(attestation_text="We attest compliance with the operating rules") -> dict:
    return transition_payload("SUBMITTED", attestation_text=attestation_text)


def complete_audit_payload(findings_count=0) -> dict:
    return transition_payload("COMPLETED", findings_count=findings_count)


def respond_payload(response_text="Remediation plan submitted") -> dict:
    return {"response_text": response_text}


def exposure_limit_payload(exposure_limit_cents, expected_originator_version) -> dict:
    return {
        "exposure_limit_cents": exposure_limit_cents,
        "expected_originator_version": expected_originator_version,
    }


def clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}


# Default clock instant used to open a scenario: boot date at 09:00 UTC, before
# the default 17:00 window cutoff, on a banking day (2026-09-01 is a Tuesday).
DEFAULT_CLOCK_ISO = CLOCK_START_ISO.replace("T00:00:00Z", "T09:00:00Z")
