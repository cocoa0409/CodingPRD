"""Segregation-of-duties controls and their position in the validation order."""
import pytest

from test_helpers import (
    ApiErrorId,
    attach_verified_inspection,
    create_inspection_report_payload,
    get_success_data,
    make_reviewer_headers,
    make_seller_headers,
    setup_draft_listing,
    setup_seller,
    validate_error,
)


class TestVerifyPriorityOrder:
    def test_state_error_surfaces_before_segregation_on_draft_verify(self, api):
        """PRD §2.8: "Every request is checked against a fixed priority order,
        so that a request failing several checks surfaces the earliest failure
        rather than an arbitrary one. The order is: (1) presence and
        well-formedness of the `X-User-ID` and `X-User-Role` headers, failing
        with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; (2) role permission
        and entity-backed ownership, failing with `ERR_FORBIDDEN`; (3)
        existence of every path id, validated left-to-right along the URL
        hierarchy, failing with `ERR_NOT_FOUND`; (4) whether the target entity
        is in a state from which the requested transition is defined, failing
        with `ERR_INVALID_STATE`; (5) segregation-of-duties checks, failing
        with `ERR_SEGREGATION_OF_DUTIES`; (6) shape, type, enum, and range
        constraints on create payloads, failing with `ERR_VALIDATION`; (7) the
        lease-period overlap rule on lease creation, failing with
        `ERR_LEASE_PERIOD_OVERLAP`; (8) the due-month bucket rule on
        payment-record creation, failing with `ERR_DUPLICATE_DUE_MONTH`; (9)
        temporal rules against the logical clock — offer expiry at accept,
        guarantee claim window, inspection staleness at certification —
        failing with `ERR_EXPIRED`; (10) cross-entity preconditions, failing
        with `ERR_PRECONDITION`; and finally (11) funds and fee checks —
        earnest money, cash-offer proof of funds, and funded-amount equality —
        failing with `ERR_INSUFFICIENT_FUNDS`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_inspection_verify
        """
        seller = setup_seller()
        listing = setup_draft_listing(seller)
        seller_h = make_seller_headers(seller["id"])
        report = get_success_data(
            api.create_inspection_report(
                listing["id"], create_inspection_report_payload(), seller_h
            )
        )
        # Report is DRAFT; a reviewer id equal to the would-be submitter also
        # violates segregation, but the state check fires first.
        resp = api.transition_inspection_report(
            report["id"], {"action": "VERIFY"}, make_reviewer_headers(seller["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        reports = get_success_data(api.list_inspection_reports(listing["id"], seller_h))
        assert reports[0]["status"] == "DRAFT"

    def test_verify_by_distinct_reviewer_succeeds_after_submit(self, api):
        """PRD §3.2: "Verification is segregation-of-duties controlled: the
        reviewer's `X-User-ID` must differ from `submitted_by_seller_id`,
        otherwise `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_inspection_verify
        """
        seller = setup_seller()
        listing = setup_draft_listing(seller)
        report = attach_verified_inspection(seller, listing)
        assert report["status"] == "VERIFIED"
