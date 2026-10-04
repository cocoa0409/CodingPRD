"""Lookup helpers and list plumbing.

Ordering: PRD 2.3 states every list endpoint returns its items ordered by
creation timestamp ascending unless a workflow states otherwise. Rows minted
within one logical-clock instant are ordered by their insertion ordinal so the
order stays stable and equals creation order.
"""

from flask import request

from common import parse_utc
from db import db
from errors import (
    ApiError,
    ERR_APPLICATION_NOT_FOUND,
    ERR_CLAIM_NOT_FOUND,
    ERR_DISPUTE_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_LENDER_NOT_FOUND,
    ERR_LOAN_NOT_FOUND,
    ERR_MASTER_POLICY_NOT_FOUND,
    ERR_NOTICE_NOT_FOUND,
    ERR_RATE_CARD_NOT_FOUND,
    ERR_REPORT_NOT_FOUND,
    ERR_RESOURCE_NOT_FOUND,
    ERR_SERVICER_NOT_FOUND,
    ERR_SNAPSHOT_NOT_FOUND,
    ERR_TREATY_NOT_FOUND,
)
from response import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)


def creation_order(rows):
    return sorted(rows, key=lambda row: (parse_utc(row["created_at"]), row.get("_seq", 0)))


def pagination_params():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    limit = PAGINATION_DEFAULT_LIMIT
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "limit must lie between %d and %d."
                % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT),
            )

    offset = PAGINATION_DEFAULT_OFFSET
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer.")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, "offset must not be negative.")

    return limit, offset


def filter_value(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def list_response(render, rows):
    limit, offset = pagination_params()
    ordered = creation_order(rows)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return [render(row) for row in window], limit, offset, total


def nested_list_response(render, rows):
    """A collection that hangs off a loan takes no limit/offset of its own
    (PRD 2.3), so it is returned in full with no pagination metadata."""
    return [render(row) for row in creation_order(rows)]


# --- entity-specific lookups (PRD 2.8, validations priority 4) -----------------

def get_lender(lender_id):
    row = db.lenders.get(lender_id)
    if row is None:
        raise ApiError(ERR_LENDER_NOT_FOUND, "Lender '%s' does not exist." % lender_id)
    return row


def get_servicer(servicer_id):
    row = db.servicers.get(servicer_id)
    if row is None:
        raise ApiError(ERR_SERVICER_NOT_FOUND, "Servicer '%s' does not exist." % servicer_id)
    return row


def get_master_policy(policy_id):
    row = db.master_policies.get(policy_id)
    if row is None:
        raise ApiError(ERR_MASTER_POLICY_NOT_FOUND, "Master policy '%s' does not exist." % policy_id)
    return row


def get_rate_card(rate_card_id):
    row = db.rate_cards.get(rate_card_id)
    if row is None:
        raise ApiError(ERR_RATE_CARD_NOT_FOUND, "Rate card '%s' does not exist." % rate_card_id)
    return row


def get_treaty(treaty_id):
    row = db.reinsurance_treaties.get(treaty_id)
    if row is None:
        raise ApiError(ERR_TREATY_NOT_FOUND, "Reinsurance treaty '%s' does not exist." % treaty_id)
    return row


def get_application(application_id):
    row = db.coverage_applications.get(application_id)
    if row is None:
        raise ApiError(
            ERR_APPLICATION_NOT_FOUND, "Coverage application '%s' does not exist." % application_id
        )
    return row


def get_loan(loan_id):
    row = db.loans.get(loan_id)
    if row is None:
        raise ApiError(ERR_LOAN_NOT_FOUND, "Loan '%s' does not exist." % loan_id)
    return row


def get_claim(claim_id):
    row = db.claims.get(claim_id)
    if row is None:
        raise ApiError(ERR_CLAIM_NOT_FOUND, "Claim '%s' does not exist." % claim_id)
    return row


def get_dispute(dispute_id):
    row = db.curtailment_disputes.get(dispute_id)
    if row is None:
        raise ApiError(ERR_DISPUTE_NOT_FOUND, "Coverage dispute '%s' does not exist." % dispute_id)
    return row


def get_notice(notice_id):
    row = db.cancellation_notices.get(notice_id)
    if row is None:
        raise ApiError(ERR_NOTICE_NOT_FOUND, "Cancellation notice '%s' does not exist." % notice_id)
    return row


def get_snapshot(snapshot_id):
    row = db.portfolio_snapshots.get(snapshot_id)
    if row is None:
        raise ApiError(ERR_SNAPSHOT_NOT_FOUND, "Portfolio snapshot '%s' does not exist." % snapshot_id)
    return row


def get_external_report(report_id):
    row = db.external_reports.get(report_id)
    if row is None:
        raise ApiError(ERR_REPORT_NOT_FOUND, "External report '%s' does not exist." % report_id)
    return row


def get_delinquency_report(report_id):
    row = db.delinquency_reports.get(report_id)
    if row is None:
        raise ApiError(ERR_REPORT_NOT_FOUND, "Delinquency report '%s' does not exist." % report_id)
    return row


def get_cession(cession_id):
    row = db.reinsurance_cessions.get(cession_id)
    if row is None:
        raise ApiError(
            ERR_RESOURCE_NOT_FOUND, "Reinsurance cession '%s' does not exist." % cession_id
        )
    return row


# --- body-supplied foreign keys (validations priority 3) ----------------------

def resolve_body_lender(lender_id):
    if lender_id not in db.lenders:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, "Referenced lender '%s' does not exist." % lender_id)
    return db.lenders[lender_id]


def resolve_body_servicer(servicer_id):
    if servicer_id not in db.servicers:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, "Referenced servicer '%s' does not exist." % servicer_id)
    return db.servicers[servicer_id]


def resolve_body_master_policy(policy_id):
    if policy_id not in db.master_policies:
        raise ApiError(
            ERR_RESOURCE_NOT_FOUND,
            "Referenced master policy '%s' does not exist." % policy_id,
        )
    return db.master_policies[policy_id]


def resolve_body_rate_card(rate_card_id):
    if rate_card_id not in db.rate_cards:
        raise ApiError(
            ERR_RESOURCE_NOT_FOUND,
            "Referenced rate card '%s' does not exist." % rate_card_id,
        )
    return db.rate_cards[rate_card_id]


def resolve_body_treaty(treaty_id):
    if treaty_id is None:
        return None
    if treaty_id not in db.reinsurance_treaties:
        raise ApiError(
            ERR_RESOURCE_NOT_FOUND,
            "Referenced reinsurance treaty '%s' does not exist." % treaty_id,
        )
    return db.reinsurance_treaties[treaty_id]


def resolve_body_application(application_id):
    """POST /loans names its originating application in the body, so a missing
    reference is the body-FK error (validations priority 3), not the
    entity-specific one (priority 4)."""
    if application_id not in db.coverage_applications:
        raise ApiError(
            ERR_RESOURCE_NOT_FOUND,
            "Referenced coverage application '%s' does not exist." % application_id,
        )
    return db.coverage_applications[application_id]


def resolve_body_loan(loan_id):
    if loan_id not in db.loans:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, "Referenced loan '%s' does not exist." % loan_id)
    return db.loans[loan_id]


def resolve_body_claim(claim_id):
    if claim_id not in db.claims:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, "Referenced claim '%s' does not exist." % claim_id)
    return db.claims[claim_id]


# --- nested collections -------------------------------------------------------

def loan_delinquency_reports(loan_id):
    return [
        r for r in creation_order(list(db.delinquency_reports.values()))
        if r["loan_id"] == loan_id
    ]


def loan_cancellation_notices(loan_id):
    return [
        r for r in creation_order(list(db.cancellation_notices.values()))
        if r["loan_id"] == loan_id
    ]


def loan_claims(loan_id):
    return [r for r in creation_order(list(db.claims.values())) if r["loan_id"] == loan_id]


def loan_external_reports(loan_id):
    return [
        r for r in creation_order(list(db.external_reports.values()))
        if r["loan_id"] == loan_id
    ]


def loan_disputes(loan_id):
    return [
        r for r in creation_order(list(db.curtailment_disputes.values()))
        if r["loan_id"] == loan_id
    ]


def claim_options(claim_id):
    return [
        r for r in creation_order(list(db.claim_settlement_options.values()))
        if r["claim_id"] == claim_id
    ]