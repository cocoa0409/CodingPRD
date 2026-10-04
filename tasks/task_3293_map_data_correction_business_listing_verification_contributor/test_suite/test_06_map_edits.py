"""Map edit lifecycle: auto-validation routing, review cycle, duplicates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_map_edit_payload,
    create_review_payload,
    get_listing,
    make_contributor,
    make_contributor_headers,
    make_listing,
    make_map_edit,
    make_region,
    make_review,
    open_edit_review_ticket,
    resolve_ticket,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MOD1 = TEST_USERS["moderator_headers"]


def test_needs_info_cycle_reopens_review(api):
    """PRD §3.4: "Requesting more information moves the edit to
    `NEEDS_MORE_INFO` and closes the ticket as `RESOLVED` with resolution
    `NEEDS_INFO`, returning the ball to the contributor."
    PRD §3.4: "Supplying evidence moves the edit back to `IN_REVIEW` and
    creates a fresh `OPEN` review ticket in the `EDIT_REVIEW` queue at `HIGH`
    priority, which any moderator may then pick up."

    Design: Difficulty/non_linear_state_machine/mapedit_needs_info_cycle_reopens_review
    """
    region = make_region(name="R5")
    contributor = make_contributor(region["id"], display_name="C6", email="c6@x.com")
    listing = make_listing(region["id"], name="Market Five")
    edit = make_map_edit(listing, contributor["id"],
                         payload={"attribute": "parking", "value": True})
    assert edit["status"] == "QUEUED"
    ticket = open_edit_review_ticket(edit["id"], "mod-1")
    resolve_ticket(ticket["id"], "mod-1", "NEEDS_INFO")

    resp = api.supply_edit_info(
        edit["id"], {"evidence": "photo of parking lot signage"},
        make_contributor_headers(contributor["id"]),
    )
    data = validate_success(resp)
    assert data["status"] == "IN_REVIEW", (
        f"cycle re-entered, got {data['status']}"
    )

    tickets, _meta = validate_paginated(
        api.list_map_edit_review_tickets(edit["id"], MOD1)
    )
    fresh = [t for t in tickets
             if t["status"] == "OPEN" and t["id"] != ticket["id"]]
    assert len(fresh) == 1, f"expected one fresh OPEN ticket, got {len(fresh)}"
    assert fresh[0]["queue"] == "EDIT_REVIEW"
    assert fresh[0]["priority"] == "HIGH"


def test_needs_info_cycle_second_pass_publishes(api):
    """PRD §3.4: "Supplying evidence moves the edit back to `IN_REVIEW` and
    creates a fresh `OPEN` review ticket in the `EDIT_REVIEW` queue at `HIGH`
    priority, which any moderator may then pick up."
    PRD §3.4: "Approving publishes the edit with the full publication cascade
    above."
    PRD §3.10: "A separate claim action moves an `OPEN` ticket — such as the
    high-priority ticket minted when a contributor supplies more evidence — to
    `CLAIMED` under the acting moderator."

    Design: Difficulty/non_linear_state_machine/mapedit_needs_info_cycle_reopens_review
    """
    region = make_region(name="R5b")
    contributor = make_contributor(region["id"], display_name="C6b", email="c6b@x.com")
    listing = make_listing(region["id"], name="Market Five B")
    edit = make_map_edit(listing, contributor["id"],
                         payload={"attribute": "parking", "value": True})
    ticket = open_edit_review_ticket(edit["id"], "mod-1")
    resolve_ticket(ticket["id"], "mod-1", "NEEDS_INFO")
    api.supply_edit_info(
        edit["id"], {"evidence": "photo of parking lot signage"},
        make_contributor_headers(contributor["id"]),
    )

    tickets, _meta = validate_paginated(
        api.list_map_edit_review_tickets(edit["id"], MOD1)
    )
    fresh = [t for t in tickets
             if t["status"] == "OPEN" and t["id"] != ticket["id"]][0]
    claim_resp = api.claim_review_ticket(fresh["id"], MOD1)
    validate_success(claim_resp)
    resolve_ticket(fresh["id"], "mod-1", "APPROVE")

    edit_read = validate_success(api.get_map_edit(edit["id"], ADMIN))
    assert edit_read["status"] == "PUBLISHED", (
        f"second pass through the loop publishes, got {edit_read['status']}"
    )


def test_auto_score_exactly_85_publishes(api):
    """PRD §3.4: "The auto-validation score starts from a base of 40, adds
    four-tenths of the contributor's `finalized_trust_score`, adds ten points
    per supplied evidence URL up to a cap of three URLs from the optional
    `payload.evidence_urls` array (absent means zero), and subtracts a risk
    term that depends on the edit type: address and location edits carry a
    risk of 25; a name edit carries 10 when the listing has no
    keyword-stuffing strikes but 30 when it has at least one; all other types
    — category, hours, attribute — carry 5."
    PRD §3.4: "Routing is exact: a score of 85.0 or higher routes the edit
    through `AUTO_VALIDATED` directly to `PUBLISHED` within the creation
    request; a score of at least 50 but strictly below 85 routes to `QUEUED`
    for human review; anything below 50 rejects immediately with
    `rejection_reason` `AUTO_LOW_SCORE`."

    Design: Difficulty/boundary_precision_check/edit_auto_score_exactly_85_publishes_below_queues
    """
    region = make_region(name="R11")
    contributor = make_contributor(region["id"], display_name="C13", email="c13@x.com")
    listing = make_listing(region["id"], name="Clinic Eleven")
    # Fresh contributor finalized trust is 50: 40 + 0.4*50 + 3*10 - 5 = 85.0.
    resp = api.create_map_edit(
        create_map_edit_payload(
            listing_id=listing["id"], contributor_id=contributor["id"],
            edit_type="ATTRIBUTE",
            payload={"attribute": "wheelchair", "value": True,
                     "evidence_urls": ["u1", "u2", "u3"]},
            expected_listing_version=listing["version"],
        ),
        make_contributor_headers(contributor["id"]),
    )
    edit = validate_success(resp, expected_status=201)
    assert edit["status"] == "PUBLISHED", (
        f"score exactly 85.0 must publish, got {edit['status']}"
    )
    data = get_listing(listing["id"])
    assert data["accepted_edit_count"] == 1


def test_auto_score_75_queues_below_85(api):
    """PRD §3.4: "Routing is exact: a score of 85.0 or higher routes the edit
    through `AUTO_VALIDATED` directly to `PUBLISHED` within the creation
    request; a score of at least 50 but strictly below 85 routes to `QUEUED`
    for human review; anything below 50 rejects immediately with
    `rejection_reason` `AUTO_LOW_SCORE`."
    PRD §2.7: "Edit auto-validation scores are carried to 1 decimal place, and
    their routing comparisons are exact: a score of exactly 85.0 publishes,
    anything strictly below 85 queues."

    Design: Difficulty/boundary_precision_check/edit_auto_score_exactly_85_publishes_below_queues
    """
    region = make_region(name="R11b")
    contributor = make_contributor(region["id"], display_name="C13b",
                                   email="c13b@x.com")
    listing = make_listing(region["id"], name="Clinic Eleven B")
    # 40 + 0.4*50 + 2*10 - 5 = 75.0 < 85 -> QUEUED.
    resp = api.create_map_edit(
        create_map_edit_payload(
            listing_id=listing["id"], contributor_id=contributor["id"],
            edit_type="ATTRIBUTE",
            payload={"attribute": "parking", "value": True,
                     "evidence_urls": ["u1", "u2"]},
            expected_listing_version=listing["version"],
        ),
        make_contributor_headers(contributor["id"]),
    )
    edit = validate_success(resp, expected_status=201)
    assert edit["status"] == "QUEUED", (
        f"score 75.0 must queue, got {edit['status']}"
    )
    assert edit["auto_score"] == 75.0, f"auto_score must be 75.0, got {edit['auto_score']}"


def test_ticket_resolve_by_non_claimer_rejected(api):
    """PRD §3.4: "Resolution belongs exclusively to the claiming moderator —
    any other moderator is refused with `ERR_NOT_TICKET_OWNER` (HTTP 403), the
    segregation-of-duties guarantee for the queue."

    Design: Corner/state_machines/ticket_resolve_by_non_claimer_rejected
    """
    region = make_region(name="RT")
    contributor = make_contributor(region["id"], display_name="CT", email="t@x.com")
    listing = make_listing(region["id"], name="Ticket Biz")
    edit = make_map_edit(listing, contributor["id"])
    assert edit["status"] == "QUEUED"
    ticket = open_edit_review_ticket(edit["id"], "mod-1")

    resp = api.resolve_review_ticket(
        ticket["id"], {"resolution": "APPROVE"},
        TEST_USERS["moderator2_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_NOT_TICKET_OWNER)
    edit_read = validate_success(api.get_map_edit(edit["id"], ADMIN))
    assert edit_read["status"] == "IN_REVIEW", (
        f"edit unchanged after rejected resolve, got {edit_read['status']}"
    )


def test_duplicate_edit_and_duplicate_review_rejected(api):
    """PRD §3.4: "Duplicate suppression applies per contributor, listing, and
    type: while an edit of the same type by the same contributor on the same
    listing sits in `SUBMITTED`, `QUEUED`, `IN_REVIEW`, or `NEEDS_MORE_INFO`,
    a second one is rejected with `ERR_DUPLICATE_SUBMISSION` (HTTP 409)."
    PRD §3.5: "A contributor may not hold two non-terminal reviews of the same
    listing at once; the second attempt draws `ERR_DUPLICATE_SUBMISSION`."

    Design: Corner/validations/duplicate_edit_and_duplicate_review_rejected
    """
    region = make_region(name="RD")
    contributor = make_contributor(region["id"], display_name="CD", email="dup2@x.com")
    listing = make_listing(region["id"], name="Dup Biz")
    first_edit = make_map_edit(listing, contributor["id"])
    assert first_edit["status"] == "QUEUED"
    review = make_review(listing["id"], contributor["id"], rating=3,
                         text="Average place, nothing special to report here.")
    assert review["status"] == "PUBLISHED"
    current = get_listing(listing["id"])

    resp = api.create_map_edit(
        create_map_edit_payload(
            listing_id=listing["id"], contributor_id=contributor["id"],
            edit_type="ATTRIBUTE",
            payload={"attribute": "wifi", "value": False},
            expected_listing_version=current["version"],
        ),
        make_contributor_headers(contributor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SUBMISSION)

    resp = api.create_review(
        create_review_payload(
            listing_id=listing["id"], contributor_id=contributor["id"],
            rating=4, text="Changed my mind after a second visit today.",
        ),
        make_contributor_headers(contributor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SUBMISSION)


def test_edit_already_assigned_rejected(api):
    """PRD §3.4: "An edit that already carries a ticket refuses a second
    assignment with `ERR_EDIT_ALREADY_ASSIGNED` (HTTP 409)."

    Design: Corner/validations/edit_already_assigned_rejected
    """
    region = make_region(name="RA")
    contributor = make_contributor(region["id"], display_name="CA", email="aa@x.com")
    listing = make_listing(region["id"], name="Assign Biz")
    edit = make_map_edit(listing, contributor["id"])
    open_edit_review_ticket(edit["id"], "mod-1")

    resp = api.create_review_ticket(
        {"queue": "EDIT_REVIEW", "map_edit_id": edit["id"]},
        TEST_USERS["moderator2_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_EDIT_ALREADY_ASSIGNED)


def test_supply_info_by_non_author_rejected(api):
    """PRD §3.4: "A contributor answers a needs-more-info request by supplying
    additional `evidence`, which must be non-empty (an empty supply is
    `ERR_INVALID_REQUEST`). Only the edit's author may supply it — anyone else
    draws `ERR_NOT_EDIT_AUTHOR` (HTTP 403) — and the author must be `ACTIVE`."

    Design: Corner/validations/edit_already_assigned_rejected
    """
    region = make_region(name="RAsi")
    author = make_contributor(region["id"], display_name="Auth", email="auth@x.com")
    other = make_contributor(region["id"], display_name="Other", email="other@x.com")
    listing = make_listing(region["id"], name="Supply Biz")
    edit = make_map_edit(listing, author["id"])
    ticket = open_edit_review_ticket(edit["id"], "mod-1")
    resolve_ticket(ticket["id"], "mod-1", "NEEDS_INFO")

    resp = api.supply_edit_info(
        edit["id"], {"evidence": "photo evidence"},
        make_contributor_headers(other["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_EDIT_AUTHOR)
