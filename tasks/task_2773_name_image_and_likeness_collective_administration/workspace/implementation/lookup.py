"""Existence resolution: each miss reports the matching not-found code."""

import store
from errors import ApiError


def _get(table, row_id, error_id):
    if not isinstance(row_id, str):
        raise ApiError(error_id)
    row = table.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def collective(row_id):
    return _get(store.collectives, row_id, "ERR_COLLECTIVE_NOT_FOUND")


def membership_tier(row_id):
    return _get(store.membership_tiers, row_id, "ERR_MEMBERSHIP_TIER_NOT_FOUND")


def donor_member(row_id):
    return _get(store.donor_members, row_id, "ERR_DONOR_MEMBER_NOT_FOUND")


def commitment(row_id):
    return _get(store.commitments, row_id, "ERR_COMMITMENT_NOT_FOUND")


def contribution(row_id):
    return _get(store.contributions, row_id, "ERR_CONTRIBUTION_NOT_FOUND")


def athlete(row_id):
    return _get(store.athletes, row_id, "ERR_ATHLETE_NOT_FOUND")


def deal_contract(row_id):
    return _get(store.deal_contracts, row_id, "ERR_DEAL_CONTRACT_NOT_FOUND")


def deliverable(row_id):
    return _get(store.deliverables, row_id, "ERR_DELIVERABLE_NOT_FOUND")


def payment_release(row_id):
    return _get(store.payment_releases, row_id, "ERR_PAYMENT_RELEASE_NOT_FOUND")


def communication_log(row_id):
    return _get(store.communication_logs, row_id, "ERR_COMMUNICATION_LOG_NOT_FOUND")
