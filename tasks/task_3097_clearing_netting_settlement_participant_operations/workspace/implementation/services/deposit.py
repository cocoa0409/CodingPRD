"""Financial-standard review and collateral-deposit coverage.

Calculations (SCAFFOLD section 1.3):
  financial_standard_minimum  - tiered class base vs the flat house floor
  deposit_posted_balance      - append-only ledger balance vs non-FAILED obligations
"""

from db import db, touch
from errors import api_error, ERR_INSUFFICIENT_DEPOSIT
from lookups import net_positions_of_participant, postings_of_deposit

PARTICIPANT_CLASSES = ("BANK", "BROKER_DEALER", "CUSTODIAN_BANK", "INSURANCE_CARRIER")

TIER_BASE = {
    "BANK": 1500000000,
    "BROKER_DEALER": 250000000,
    "CUSTODIAN_BANK": 750000000,
    "INSURANCE_CARRIER": 1000000000,
}
GREATER_OF_TIER_CENTS = 500000000


def financial_standard_minimum(participant):
    """The greater of the class base and the flat house floor.

    The comparison is inclusive: a class base exactly equal to the floor is
    kept as-is.
    """
    base_cents = TIER_BASE[participant["participant_class"]]
    if base_cents >= GREATER_OF_TIER_CENTS:
        return base_cents
    return GREATER_OF_TIER_CENTS


def apply_financial_review(participant, net_capital_cents):
    """Recompute the derived capital fields and stamp the review instant."""
    participant["net_capital_cents"] = net_capital_cents
    participant["required_min_net_capital_cents"] = financial_standard_minimum(participant)
    if participant["net_capital_cents"] >= participant["required_min_net_capital_cents"]:
        participant["financial_standard_status"] = "PASS"
    else:
        participant["financial_standard_status"] = "FAIL"
    participant["last_financial_review_at"] = db.now_iso()
    return participant


def posted_amount_cents(deposit):
    """Sum of amount_cents over every transaction of the pool, releases included."""
    return sum(
        txn["amount_cents"] for txn in postings_of_deposit(deposit["id"])
    )


def obligations_cents(participant_id):
    """Sum of settlement_obligation_cents over the member's non-FAILED rows."""
    return sum(
        np["settlement_obligation_cents"]
        for np in net_positions_of_participant(participant_id)
        if np["dvp_status"] != "FAILED"
    )


def derive_coverage(deposit):
    """The pool's posted balance and covered status, evaluated in one pass."""
    participant_id = deposit["participant_id"]
    balance = posted_amount_cents(deposit)
    obligations = obligations_cents(participant_id)
    deposit["posted_amount_cents"] = balance
    if obligations == 0 or balance >= obligations:
        deposit["status"] = "SATISFIED"
    else:
        deposit["status"] = "DEFICIENT_GRACE"
    return balance, obligations, deposit["status"]


def refresh_coverage(participant_id, *, bump=True):
    """Re-derive the member's pool standing; returns (balance, obligations)."""
    deposit = deposit_of_participant(participant_id)
    if deposit is None:
        return None
    balance, obligations, _status = derive_coverage(deposit)
    if bump:
        touch(deposit)
    return balance, obligations


def require_coverage(participant_id, *, bump=True):
    """Re-derive the pool standing and surface a shortfall.

    PRD 2.5: a shortfall against obligations is surfaced as
    ERR_INSUFFICIENT_DEPOSIT wherever a covered standing is required.
    """
    deposit = deposit_of_participant(participant_id)
    if deposit is None:
        return None
    balance, obligations, status = derive_coverage(deposit)
    if bump:
        touch(deposit)
    if status == "DEFICIENT_GRACE":
        raise api_error(
            ERR_INSUFFICIENT_DEPOSIT,
            "Posted collateral %d is below outstanding obligations %d." % (balance, obligations),
        )
    return deposit


def deposit_of_participant(participant_id):
    for deposit in db.deposits.values():
        if deposit["participant_id"] == participant_id:
            return deposit
    return None


def force_deficient_default(deposit):
    """Imposed by the risk workflow on suspension and on a default declaration."""
    if deposit is None:
        return
    deposit["status"] = "DEFICIENT_DEFAULT"
    touch(deposit)


def apply_grace_on_close(participant_id):
    """Cycle close: every under-funded member moves into the grace state."""
    deposit = deposit_of_participant(participant_id)
    if deposit is None:
        return
    balance = posted_amount_cents(deposit)
    obligations = obligations_cents(participant_id)
    deposit["posted_amount_cents"] = balance
    if obligations > 0 and balance < obligations:
        deposit["status"] = "DEFICIENT_GRACE"
        touch(deposit)
    elif obligations == 0 or balance >= obligations:
        if deposit["status"] not in ("DEFICIENT_DEFAULT",):
            deposit["status"] = "SATISFIED"
            touch(deposit)