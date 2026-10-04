"""Payload factories — one per entity, PRD-declared input fields only.

Unique-constrained values (Payee.tin, CreditorAgency.creditor_code,
CollectionAgency.agency_code) default to a per-process sequence so a test may
call the same factory twice without tripping the duplicate checks; tests that
need a specific literal (e.g. a TIN shared between payee and debt) pass it via
overrides.
"""
import itertools

from .constants import (
    DEFAULT_AGREEMENT_WINDOW,
    DEFAULT_DELINQUENT_SINCE,
    DEFAULT_DNP_WINDOW,
    DEFAULT_NOTICE_SENT_AT,
    DEFAULT_SETTLEMENT_DATE,
)

_seq = itertools.count(1)


def _n() -> int:
    return next(_seq)


def unique_tin() -> str:
    """A syntactically TIN-shaped value, unique per call within the process."""
    n = _n()
    return f"9{n % 10}{n % 10}-{n % 100:02d}-{n % 10000:04d}"


def unique_code(prefix: str) -> str:
    return f"{prefix}-{_n():04d}"


# --- CreditorAgency (PRD §3.1) --------------------------------------------------

def create_creditor_agency_payload(**overrides) -> dict:
    defaults = {
        "creditor_code": unique_code("IRS"),
        "legal_name": "Federal Test Creditor",
        "creditor_type": "FEDERAL",
        # state_code omitted: FEDERAL forbids it (ERR_INVALID_REQUEST)
    }
    defaults.update(overrides)
    return defaults


def create_state_creditor_payload(state_code="CA", **overrides) -> dict:
    defaults = {
        "creditor_code": unique_code(f"{state_code}"),
        "legal_name": f"{state_code} Test Revenue Department",
        "creditor_type": "STATE",
        "state_code": state_code,
    }
    defaults.update(overrides)
    return defaults


# --- Payee (PRD §3.1) -----------------------------------------------------------

def create_payee_payload(**overrides) -> dict:
    defaults = {
        "tin": unique_tin(),
        "tin_type": "SSN",
        "legal_name": "Pat Doe",
        # routing_number / account_last4 omitted -> null -> CHECK payments
    }
    defaults.update(overrides)
    return defaults


def create_eft_payee_payload(**overrides) -> dict:
    """Payee with a routing number: payments disburse by EFT (PRD §3.4)."""
    defaults = {
        "tin": unique_tin(),
        "tin_type": "SSN",
        "legal_name": "Pat Doe",
        "routing_number": "021000021",
        "account_last4": "4321",
    }
    defaults.update(overrides)
    return defaults


# --- ExemptionPolicy (PRD §3.2) -------------------------------------------------

def create_exemption_policy_payload(**overrides) -> dict:
    """Defaults to FULL (no conditional fields). For PARTIAL pass both
    protected_minimum_cents and max_offset_pct; for EXEMPT/FULL pass neither."""
    defaults = {
        "payment_type": "VENDOR",
        "exemption_class": "FULL",
    }
    defaults.update(overrides)
    return defaults


def create_partial_policy_payload(
    payment_type="VENDOR",
    protected_minimum_cents=75000,
    max_offset_pct=0.15,
    **overrides,
) -> dict:
    defaults = {
        "payment_type": payment_type,
        "exemption_class": "PARTIAL",
        "protected_minimum_cents": protected_minimum_cents,
        "max_offset_pct": max_offset_pct,
    }
    defaults.update(overrides)
    return defaults


# --- Debt (PRD §3.3) ------------------------------------------------------------

def create_debt_payload(creditor_agency_id, **overrides) -> dict:
    """Referral body. Omit notice_sent_at for a REFERRED start; supply it (and
    optionally due_process_completed) for the NOTICED creation shortcut."""
    defaults = {
        "creditor_agency_id": creditor_agency_id,
        "debtor_tin": "111-22-3333",
        "debtor_name": "Pat Doe",
        "debt_type": "FEDERAL_NONTAX",
        "original_amount_cents": 50000,
        "delinquent_since": DEFAULT_DELINQUENT_SINCE,
    }
    defaults.update(overrides)
    return defaults


def create_noticed_debt_payload(creditor_agency_id, **overrides) -> dict:
    """Referral that starts NOTICED with due process attested, ready to activate
    once the 30-day notice window has elapsed (DEFAULT_NOTICE_SENT_AT is 30+ days
    before the default clock of 2026-09-01T00:00:00Z)."""
    defaults = create_debt_payload(creditor_agency_id, **overrides)
    defaults.setdefault("notice_sent_at", DEFAULT_NOTICE_SENT_AT)
    defaults.setdefault("due_process_completed", True)
    return defaults


def create_notice_payload(**overrides) -> dict:
    """Body for POST /debts/{id}/notice (REFERRED or RETURNED -> NOTICED)."""
    defaults = {
        "notice_sent_at": DEFAULT_NOTICE_SENT_AT,
        "due_process_completed": True,
    }
    defaults.update(overrides)
    return defaults


# --- PaymentFile / Payment (PRD §3.4) -------------------------------------------

def create_payment_file_payload(**overrides) -> dict:
    defaults = {
        "agency_code": "AG-01",
        "settlement_date": DEFAULT_SETTLEMENT_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(payee, amount_cents=30000, payment_type="SALARY",
                           **overrides) -> dict:
    """payee is the created Payee dict; payee_tin defaults to the payee's own tin
    so the payee-verification gate passes."""
    defaults = {
        "payee_id": payee["id"],
        "payee_tin": payee["tin"],
        "amount_cents": amount_cents,
        "payment_type": payment_type,
    }
    defaults.update(overrides)
    return defaults


def create_evaluate_payload(expected_payment_version, **overrides) -> dict:
    defaults = {"expected_payment_version": expected_payment_version}
    defaults.update(overrides)
    return defaults


# --- RefundClaim (PRD §3.6) -----------------------------------------------------

def create_refund_claim_payload(offset_id, claimed_amount_cents=10000,
                                reason="DEBT_NOT_OWED", **overrides) -> dict:
    defaults = {
        "offset_id": offset_id,
        "claimed_amount_cents": claimed_amount_cents,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults


def create_decision_payload(decision="APPROVE") -> dict:
    return {"decision": decision}


# --- CollectionAgency / CollectionAction (PRD §3.7) -----------------------------

def create_collection_agency_payload(**overrides) -> dict:
    defaults = {
        "agency_code": unique_code("PCA"),
        "name": "Pioneer Collections",
        "capacity_max_active": 5,
    }
    defaults.update(overrides)
    return defaults


def create_awg_action_payload(**overrides) -> dict:
    """AWG requires notice_sent_at and disposable_pay_estimate_cents."""
    defaults = {
        "action_type": "AWG",
        "notice_sent_at": DEFAULT_NOTICE_SENT_AT,
        "disposable_pay_estimate_cents": 25000,
    }
    defaults.update(overrides)
    return defaults


def create_cross_servicing_action_payload(**overrides) -> dict:
    """CROSS_SERVICING forbids notice_sent_at / disposable_pay_estimate_cents."""
    defaults = {"action_type": "CROSS_SERVICING"}
    defaults.update(overrides)
    return defaults


def create_collect_payload(expected_debt_version, **overrides) -> dict:
    """OCC token plus exactly one of disposable_pay_cents (AWG) or
    remitted_amount_cents (CROSS_SERVICING)."""
    defaults = {"expected_debt_version": expected_debt_version}
    defaults.update(overrides)
    return defaults


# --- ReverseOffsetRequest (PRD §3.8) --------------------------------------------

def create_reverse_offset_request_payload(**overrides) -> dict:
    defaults = {
        "state_code": "WA",
        "payee_tin": "111-22-3333",
        "requested_amount_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


# --- ReciprocalAgreement (PRD §2.10, §3.8) --------------------------------------

def create_reciprocal_agreement_payload(state_code="WA", direction="STATE_TO_FED",
                                        **overrides) -> dict:
    effective_from, effective_until = DEFAULT_AGREEMENT_WINDOW
    defaults = {
        "state_code": state_code,
        "direction": direction,
        "effective_from": effective_from,
        "effective_until": effective_until,
    }
    defaults.update(overrides)
    return defaults


# --- DoNotPayRecord (PRD §2.11, §3.9) -------------------------------------------

def create_do_not_pay_record_payload(tin=None, **overrides) -> dict:
    effective_from, effective_until = DEFAULT_DNP_WINDOW
    defaults = {
        "tin": tin if tin is not None else unique_tin(),
        "list_source": "SAM_EXCLUSION",
        "effective_from": effective_from,
        "effective_until": effective_until,
    }
    defaults.update(overrides)
    return defaults


__all__ = [name for name in dir() if name.startswith(("create_", "unique_"))]
