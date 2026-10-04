"""Third-party impact reviews on transfers.

Covers the SUSTAINED cascade that voids the transfer without ledger
movement, the FILED-review gate on approval (and its release on dismissal),
the objection-window filing deadline, the one-review-per-district rule, and
the segregation of transfer parties from reviewing - PRD §2.9 and §3.8.
"""

from test_helpers import (
    ApiErrorId,
    assert_instant,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
)


def test_resolve_sustained_voids_open_transfer(api):
    """Resolving a review SUSTAINED moves the UNDER_REVIEW transfer to VOIDED
    in the same request; no ledger movement has occurred, so both allocation
    lines are unchanged.

    PRD §3.8: "Sustaining a review voids the transfer: a transfer not already
    terminal moves to `VOIDED` from `UNDER_REVIEW`, `REVISION_REQUESTED`, or
    `APPROVED`, and since no ledger movement has occurred yet, the allocation
    lines are unchanged."

    Design: Corner/state_machines/resolve_sustained_voids_open_transfer
    """
    world, transfer = fixtures.setup_transfer_under_review(api)
    review = fixtures.file_third_party_review(api, world, transfer["id"])

    resolved = fixtures.resolve_review(api, review["id"], "SUSTAINED", rationale="junior injury proven")
    assert resolved["status"] == "SUSTAINED"

    transfer = fixtures.get_transfer(api, transfer["id"])
    assert transfer["status"] == "VOIDED"

    line_sr = fixtures.find_line(api, world["announcement"]["id"], world["contract_sr"]["id"])
    line_jr = fixtures.find_line(api, world["announcement"]["id"], world["contract_jr"]["id"])
    assert line_sr["transfer_out_af"] == 0, "a voided transfer never moves water"
    assert line_jr["transfer_in_af"] == 0


def test_review_pending_blocks_approve_until_resolved(api):
    """Approval with a FILED review on the transfer fails 409
    ERR_REVIEW_PENDING; after the review is DISMISSED the identical approve
    succeeds and stamps the 72-hour objection window.

    PRD §3.8: "Approval requires that no impact review on the transfer
    remains `FILED` (else `ERR_REVIEW_PENDING`) and sets
    `objection_window_end` to the logical clock plus seventy-two hours,
    moving the request to `APPROVED`."

    Design: Corner/validations/review_pending_blocks_approve_until_resolved
    """
    world, transfer = fixtures.setup_transfer_under_review(api)
    review = fixtures.file_third_party_review(api, world, transfer["id"])

    validate_error(
        api.decide_transfer_request(transfer["id"], {"decision": "APPROVE"}, fixtures.REGIONAL_DIRECTOR_HEADERS),
        ApiErrorId.ERR_REVIEW_PENDING,
    )

    fixtures.resolve_review(api, review["id"], "DISMISSED", rationale="no injury")

    approved = fixtures.approve_transfer(api, world, transfer["id"])
    assert approved["status"] == "APPROVED"
    # Approval happens at the 2027-01-15 publish instant; +72h lands on
    # 2027-01-18T00:00:00Z.
    assert_instant(approved["objection_window_end"], "2027-01-18T00:00:00Z", "objection_window_end")


def test_review_filed_after_window_closed_rejected(api):
    """On an APPROVED transfer the objection window is closed at or after
    objection_window_end: a review filed exactly at the 72-hour mark fails
    409 ERR_OBJECTION_WINDOW_CLOSED.

    PRD §3.8: "Filing is time-sensitive once a transfer is `APPROVED`: at or
    after the transfer's `objection_window_end` the filing fails with
    `ERR_OBJECTION_WINDOW_CLOSED`."

    Design: Corner/validations/review_filed_after_window_closed_rejected
    """
    world, transfer = fixtures.setup_transfer_approved(api)
    fixtures.set_clock(api, "2027-01-18T00:00:00Z")  # exactly the window end

    validate_error(
        api.create_impact_review(
            transfer["id"],
            factories.impact_review_payload(50, "RETURN_FLOW"),
            world["mgr_tp_headers"],
        ),
        ApiErrorId.ERR_OBJECTION_WINDOW_CLOSED,
    )

    reviews, meta = validate_paginated(
        api.list_impact_reviews(fixtures.READ_HEADERS, {"transfer_request_id": transfer["id"]})
    )
    assert meta["total_count"] == 0 and reviews == []


def test_duplicate_review_same_district_rejected(api):
    """One review per (transfer, district): the same district filing again
    fails 409 ERR_DUPLICATE_REVIEW and the review list does not grow.

    PRD §3.8: "that district must exist (else `ERR_NOT_FOUND`), must be
    neither transfer party (else `ERR_REVIEWER_CONFLICT`), and may file only
    one review per transfer (else `ERR_DUPLICATE_REVIEW`)."

    Design: Corner/validations/duplicate_review_same_district_rejected
    """
    world, transfer = fixtures.setup_transfer_under_review(api)
    fixtures.file_third_party_review(api, world, transfer["id"])

    validate_error(
        api.create_impact_review(
            transfer["id"],
            factories.impact_review_payload(75, "ENVIRONMENTAL"),
            world["mgr_tp_headers"],
        ),
        ApiErrorId.ERR_DUPLICATE_REVIEW,
    )

    reviews, meta = validate_paginated(
        api.list_impact_reviews(fixtures.READ_HEADERS, {"transfer_request_id": transfer["id"]})
    )
    assert meta["total_count"] == 1 and len(reviews) == 1


def test_transfer_party_cannot_file_impact_review(api):
    """Third-party review is structurally segregated: the seller district (a
    transfer party) filing a review fails 403 ERR_REVIEWER_CONFLICT.

    PRD §3.8: "A district that is neither the seller nor the buyer may file
    one through its `DistrictManager`"
    PRD §3.8: "that district must exist (else `ERR_NOT_FOUND`), must be
    neither transfer party (else `ERR_REVIEWER_CONFLICT`), and may file only
    one review per transfer (else `ERR_DUPLICATE_REVIEW`)."

    Design: Corner/rbac/transfer_party_cannot_file_impact_review
    """
    world, transfer = fixtures.setup_transfer_under_review(api)

    validate_error(
        api.create_impact_review(
            transfer["id"],
            factories.impact_review_payload(100, "RETURN_FLOW"),
            world["mgr_sr_headers"],  # the seller district is a party
        ),
        ApiErrorId.ERR_REVIEWER_CONFLICT,
    )

    reviews, meta = validate_paginated(
        api.list_impact_reviews(fixtures.READ_HEADERS, {"transfer_request_id": transfer["id"]})
    )
    assert meta["total_count"] == 0 and reviews == []
