"""Participant membership lifecycle (PRD 3.1).

Admission, suspension and reinstatement are administrative acts by a
PlatformAdmin; the financial-standard review is a RiskOfficer act.
"""

from db import db, new_record, touch
from errors import (
    api_error,
    ERR_FINANCIAL_STANDARD_NOT_MET,
    ERR_INVALID_STATE,
    ERR_SEGREGATED_CUSTODY_REQUIRED,
)
from lookups import custody_accounts_of, net_positions_of_participant
from services.deposit import (
    apply_financial_review,
    derive_coverage,
    deposit_of_participant,
    force_deficient_default,
    refresh_coverage,
    require_coverage,
)
from services.funds import refresh_totals_for_class
from services.marks import mark_failed
from services.netting import auto_close_open_windows
from services.trades import recompute_tuple_allegations


def create_participant(legal_name, lei, participant_class, net_capital_cents,
                       requires_segregated_custody=False):
    record = new_record(
        legal_name=legal_name,
        lei=lei,
        participant_class=participant_class,
        membership_status="PENDING",
        net_capital_cents=net_capital_cents,
        required_min_net_capital_cents=0,
        financial_standard_status="PASS",
        is_defaulted=False,
        requires_segregated_custody=requires_segregated_custody,
        last_financial_review_at=None,
    )
    db.participants[record["id"]] = record
    # Registration immediately opens the member's deposit pool and computes the
    # capital floor and the pass/fail verdict at the same moment.
    deposit = new_record(
        participant_id=record["id"],
        posted_amount_cents=0,
        status="PENDING",
    )
    db.deposits[deposit["id"]] = deposit
    # Creation itself is the row's first write, so its derived fields are
    # computed in place and the version stays at its initial value of 1. A
    # separate touch() here would double-increment it before any client call.
    apply_financial_review(record, net_capital_cents)
    return record


def activate(participant):
    if participant["membership_status"] != "PENDING":
        raise api_error(ERR_INVALID_STATE)
    if participant["financial_standard_status"] != "PASS":
        raise api_error(ERR_FINANCIAL_STANDARD_NOT_MET)
    if participant["requires_segregated_custody"]:
        segregated = [
            account
            for account in custody_accounts_of(participant["id"])
            if account["account_type"] == "SEGREGATED"
        ]
        if not segregated:
            raise api_error(ERR_SEGREGATED_CUSTODY_REQUIRED)

    apply_financial_review(participant, participant["net_capital_cents"])
    require_coverage(participant["id"], bump=False)
    participant["membership_status"] = "ACTIVE"
    touch(participant)
    refresh_totals_for_class(participant["participant_class"])
    _refresh_deposit(participant["id"])
    return participant


def reinstate(participant):
    if participant["membership_status"] != "SUSPENDED":
        raise api_error(ERR_INVALID_STATE)
    if participant["financial_standard_status"] != "PASS":
        raise api_error(ERR_FINANCIAL_STANDARD_NOT_MET)
    apply_financial_review(participant, participant["net_capital_cents"])
    participant["membership_status"] = "ACTIVE"
    touch(participant)
    refresh_totals_for_class(participant["participant_class"])
    _refresh_deposit(participant["id"])
    return participant


def suspend(participant):
    if participant["membership_status"] != "ACTIVE":
        raise api_error(ERR_INVALID_STATE)
    clock = db.get_clock()

    # The member's own live submissions are cancelled.
    for trade in db.trade_submissions.values():
        if trade["participant_id"] == participant["id"] and trade["lock_status"] in (
            "OPEN",
            "LOCKED_IN",
        ):
            trade["lock_status"] = "CANCELLED"
            trade["match_status"] = "UNRESOLVED"
            touch(trade)
            recompute_tuple_allegations(trade)

    # The member's locked contras are swept into the comparison queue.
    for trade in db.trade_submissions.values():
        if trade["lock_status"] == "CANCELLED":
            continue
        if trade["counterparty_participant_id"] != participant["id"]:
            continue
        if trade["lock_status"] != "LOCKED_IN":
            continue
        trade["match_status"] = "ALLEGED"
        touch(trade)
        recompute_tuple_allegations(trade)

    # Every non-FAILED net position of the member fails.
    for net_position in net_positions_of_participant(participant["id"]):
        if net_position["dvp_status"] == "FAILED":
            continue
        mark_failed(net_position, clock)

    participant["membership_status"] = "SUSPENDED"
    touch(participant)
    force_deficient_default(deposit_of_participant(participant["id"]))
    auto_close_open_windows()
    return participant


def financial_review(participant, net_capital_cents):
    apply_financial_review(participant, net_capital_cents)
    touch(participant)
    # PRD 3.1 attaches the ERR_INSUFFICIENT_DEPOSIT clause to admission and
    # reinstatement only; for the review the same section says merely that the
    # verdict, the floor, the stamp and the pool standing are re-derived. The
    # standing is therefore assigned here rather than raised.
    refresh_coverage(participant["id"], bump=False)
    _refresh_deposit(participant["id"])
    return participant


def update_terms(participant, legal_name=None, requires_segregated_custody=None):
    if legal_name is not None:
        participant["legal_name"] = legal_name
    if requires_segregated_custody is not None:
        participant["requires_segregated_custody"] = requires_segregated_custody
    touch(participant)
    _refresh_deposit(participant["id"])
    return participant


def _refresh_deposit(participant_id):
    deposit = deposit_of_participant(participant_id)
    if deposit is None:
        return
    derive_coverage(deposit)
    touch(deposit)