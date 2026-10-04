"""Row resolution shared by every route module (PRD §2.7).

Path identifiers resolve left to right and every path identifier is validated
before any identifier carried in the request body; a merchant-scoped path whose
merchant_id does not resolve fails with ERR_MERCHANT_NOT_FOUND and every other
addressable identifier fails with ERR_NOT_FOUND.
"""

from db import STORE
from errors import (
    ERR_MERCHANT_NOT_FOUND,
    ERR_NOT_FOUND,
    ApiError,
)


def merchant(merchant_id):
    row = STORE.merchants.get(merchant_id)
    if row is None:
        raise ApiError(ERR_MERCHANT_NOT_FOUND)
    return row


def industry_category(industry_category_id):
    row = STORE.industry_categories.get(industry_category_id)
    if row is None:
        raise ApiError(ERR_NOT_FOUND)
    return row


def offer(offer_id):
    row = STORE.offers.get(offer_id)
    if row is None:
        raise ApiError(ERR_NOT_FOUND)
    return row


def cardmember(cardmember_id):
    row = STORE.cardmembers.get(cardmember_id)
    if row is None:
        raise ApiError(ERR_NOT_FOUND)
    return row


def acceptance(acceptance_id):
    row = STORE.offer_acceptances.get(acceptance_id)
    if row is None:
        raise ApiError(ERR_NOT_FOUND)
    return row


def statement(statement_id):
    row = STORE.annual_fee_statements.get(statement_id)
    if row is None:
        raise ApiError(ERR_NOT_FOUND)
    return row


def settlement(settlement_id):
    row = STORE.settlements.get(settlement_id)
    if row is None:
        raise ApiError(ERR_NOT_FOUND)
    return row


def settlement_of_merchant(merchant_id, settlement_id):
    row = merchant(merchant_id)
    settlement_row = settlement(settlement_id)
    if settlement_row["merchant_id"] != row["id"]:
        raise ApiError(ERR_NOT_FOUND)
    return settlement_row


def dispute(dispute_id):
    row = STORE.disputes.get(dispute_id)
    if row is None:
        raise ApiError(ERR_NOT_FOUND)
    return row


def complaint(complaint_id):
    row = STORE.acceptance_complaints.get(complaint_id)
    if row is None:
        raise ApiError(ERR_NOT_FOUND)
    return row


def gap(gap_id):
    row = STORE.acceptance_gaps.get(gap_id)
    if row is None:
        raise ApiError(ERR_NOT_FOUND)
    return row


def declined_attempt(declined_attempt_id):
    row = STORE.declined_attempts.get(declined_attempt_id)
    if row is None:
        raise ApiError(ERR_NOT_FOUND)
    return row


def pool(pool_id):
    row = STORE.offer_redemption_pools.get(pool_id)
    if row is None:
        raise ApiError(ERR_NOT_FOUND)
    return row


def risk_state(risk_state_id):
    row = STORE.merchant_risk_states.get(risk_state_id)
    if row is None:
        raise ApiError(ERR_NOT_FOUND)
    return row


def ledger_entry(entry_id):
    row = STORE.value_fund_ledger_entries.get(entry_id)
    if row is None:
        raise ApiError(ERR_NOT_FOUND)
    return row


def risk_state_of_merchant(merchant_id):
    row = merchant(merchant_id)
    risk_row = STORE.risk_state_for(row["id"])
    return [risk_row] if risk_row is not None else []


def render(row):
    """Render one row for the response body."""
    if row is None:
        return None
    return STORE.output_fields(row)