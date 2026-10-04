"""Payload factories — one per entity, input fields only.

Every factory returns a dict of PRD-exact field names. Computed and
server-managed fields are never accepted from a caller and so never appear here.
"""
import uuid

from .constants import TEST_DEFAULTS, THRESHOLDS


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def create_ledger_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["LEDGER_NAME"],
        "currency": "USD",
    }
    defaults.update(overrides)
    return defaults


def create_legal_entity_payload(home_ledger_id=None, **overrides) -> dict:
    """Register an institution.

    entity_type defaults to ORGANISATION, which requires a home_ledger_id.
    Pass entity_type="PLATFORM" to omit it.
    """
    defaults = {
        "legal_name": TEST_DEFAULTS["INSTITUTION_NAME"],
        "short_code": _uniq(TEST_DEFAULTS["INSTITUTION_SHORT_CODE"])[:10],
        "entity_type": "ORGANISATION",
        "home_ledger_id": home_ledger_id,
    }
    defaults.update(overrides)
    if defaults["entity_type"] == "ORGANISATION" and not defaults.get("home_ledger_id"):
        raise ValueError("an ORGANISATION row must name its home_ledger_id")
    return defaults


def create_counterparty_payload(legal_entity_id, **overrides) -> dict:
    defaults = {
        "legal_entity_id": legal_entity_id,
        "display_name": TEST_DEFAULTS["COUNTERPARTY_NAME"],
        "external_ref": _uniq(TEST_DEFAULTS["COUNTERPARTY_EXTERNAL_REF"]),
    }
    defaults.update(overrides)
    return defaults


def create_relationship_payload(legal_entity_id, partner_legal_entity_id, **overrides) -> dict:
    defaults = {
        "legal_entity_id": legal_entity_id,
        "partner_legal_entity_id": partner_legal_entity_id,
        "purpose": "ACCOUNT_SHARING",
        "account_data_sharing": True,
    }
    defaults.update(overrides)
    return defaults


def create_bank_account_payload(legal_entity_id, **overrides) -> dict:
    defaults = {
        "legal_entity_id": legal_entity_id,
        "institution_name": TEST_DEFAULTS["BANK_INSTITUTION_NAME"],
        "routing_number": TEST_DEFAULTS["ROUTING_NUMBER"],
        "account_number_last4": TEST_DEFAULTS["ACCOUNT_NUMBER_LAST4"],
        "supported_rails": list(TEST_DEFAULTS["SUPPORTED_RAILS"]),
        "available_funds_cents": TEST_DEFAULTS["AVAILABLE_FUNDS_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_virtual_account_payload(bank_account_id, **overrides) -> dict:
    defaults = {
        "bank_account_id": bank_account_id,
        "virtual_account_number": str(uuid.uuid4().int)[:12].ljust(12, "0"),
    }
    defaults.update(overrides)
    # PRD §3.2: the reference_code must be 6 to 12 uppercase alphanumeric
    # characters.  A four-character literal would violate the declared
    # constraint, so any caller-supplied short code is padded: the caller's code
    # stays a prefix of the stored value, so a line that embeds it still
    # resolves through the reference branch and a code that names no virtual
    # account still resolves to nothing.
    defaults["reference_code"] = _normalise_reference_code(defaults.get("reference_code"))
    return defaults


def _normalise_reference_code(code) -> str:
    """Pad a reference code up to the PRD's 6-character floor.

    PRD §3.2 declares the field as "six to twelve uppercase alphanumeric
    characters", so a shorter literal is a malformed request rather than a
    valid identity.
    """
    if code is None:
        return _uniq("REF").upper().replace("-", "")
    text = str(code).upper()
    if len(text) >= 6:
        return text[:12]
    return text + "0" * (6 - len(text))


def create_statement_payload(bank_account_id, expected_bank_account_version, **overrides) -> dict:
    defaults = {
        "bank_account_id": bank_account_id,
        "institution_ref": _uniq("STMT"),
        "cycle_date": "2026-09-01T23:59:59Z",
        "opening_balance_cents": 0,
        "closing_balance_cents": 0,
        "matching_algorithm": "POSTED_NET",
        "expected_bank_account_version": expected_bank_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_statement_line_payload(**overrides) -> dict:
    defaults = {
        "bank_reference": _uniq("BR"),
        "amount_cents": 100_000,
        "direction": "CREDIT",
        "effective_at": "2026-09-01T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_payment_order_payload(legal_entity_id, ledger_id, counterparty_id,
                                 source_account_id, **overrides) -> dict:
    defaults = {
        "legal_entity_id": legal_entity_id,
        "ledger_id": ledger_id,
        "counterparty_id": counterparty_id,
        "source_account_id": source_account_id,
        "rail": "ACH",
        "direction": "CREDIT",
        "amount_cents": 500_000,
        "idempotency_key": _uniq("idem"),
    }
    defaults.update(overrides)
    return defaults


def create_manual_transaction_payload(**overrides) -> dict:
    defaults = {
        "entry_type": "ADJUSTMENT",
        "direction": "CREDIT",
        "amount_cents": 10_000,
        "value_effective_utc": "2026-09-01T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_settlement_pool_payload(ledger_id, member_bank_account_ids, **overrides) -> dict:
    defaults = {
        "ledger_id": ledger_id,
        "name": _uniq("Pool"),
        "member_bank_account_ids": member_bank_account_ids,
    }
    defaults.update(overrides)
    return defaults


def create_pool_membership_payload(settlement_pool_id, bank_account_id, **overrides) -> dict:
    defaults = {
        "settlement_pool_id": settlement_pool_id,
        "bank_account_id": bank_account_id,
        "weight_units": 1,
    }
    defaults.update(overrides)
    return defaults


def create_release_request_payload(payment_order_id, counterparty_id, **overrides) -> dict:
    defaults = {
        "payment_order_id": payment_order_id,
        "counterparty_id": counterparty_id,
        "needed_by_utc": "2026-09-02T12:00:00Z",
        "reason": "Awaiting a second operator to release",
    }
    defaults.update(overrides)
    return defaults


def create_calendar_cell_payload(legal_entity_id, calendar_date, **overrides) -> dict:
    defaults = {
        "legal_entity_id": legal_entity_id,
        "calendar_date": calendar_date,
        "timezone": TEST_DEFAULTS["TIMEZONE"],
        "is_open": True,
        "cutoffs": [
            {"rail": "ACH", "cutoff_local_time": "14:00:00"},
            {"rail": "WIRE", "cutoff_local_time": "15:00:00"},
            {"rail": "RTP", "cutoff_local_time": "16:00:00"},
        ],
        "allowed_rails": ["ACH", "WIRE", "RTP"],
    }
    defaults.update(overrides)
    return defaults


def create_audit_event_payload(ledger_id, **overrides) -> dict:
    defaults = {
        "ledger_id": ledger_id,
        "actor_user_id": TEST_DEFAULTS["PAYMENT_OPS_ANALYST_ID"],
        "actor_role": "PaymentOpsAnalyst",
        "action": "manual.annotation",
        "target_entity_type": "Ledger",
        "target_entity_id": ledger_id,
        "details": {},
    }
    defaults.update(overrides)
    return defaults