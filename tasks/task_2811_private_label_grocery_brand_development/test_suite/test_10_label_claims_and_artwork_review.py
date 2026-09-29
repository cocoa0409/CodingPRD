"""Clearing the label: conditional substantiation, segregation of duties on
claim review, and the artwork revision loop."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_artwork_state, assert_status
from test_helpers.constants import (
    ARTWORK_APPROVED,
    ARTWORK_CHANGES_REQUESTED,
    ARTWORK_DRAFT,
    ARTWORK_IN_REVIEW,
    CLAIM_APPROVED,
    CLAIM_NUTRIENT_CONTENT,
    CLAIM_PENDING,
    ITEM_BENCHMARKED,
    ITEM_PACKAGING_APPROVED,
    NUTRITION_VALID,
    REVIEW_APPROVE,
    REVIEW_REJECT,
    REVIEW_REQUEST_CHANGES,
)
from test_helpers.fixtures import build_chain, read_artwork_round, read_claim, read_item
from test_helpers.test_users import (
    DESIGNER_1,
    DESIGNER_HEADERS,
    REGULATORY_7,
    REGULATORY_9_HEADERS,
    REGULATORY_HEADERS,
)


def _claims_on(api, artwork_round_id):
    """Every claim row reachable from one artwork round."""
    rows, meta = validate_paginated(
        api.list_label_claims(
            REGULATORY_HEADERS, params={"artwork_round_id": artwork_round_id}
        )
    )
    return rows, meta


def test_a_health_claim_without_a_substantiation_reference_is_rejected(api):
    """Substantiation is conditionally required, and only for two claim types.

    PRD 3.5: "A `HEALTH` or `ORGANIC` claim must be accompanied by a non-empty
    `substantiation_ref` naming the lab report or certificate that supports it;
    omitting it is refused with `ERR_SUBSTANTIATION_REQUIRED` (HTTP 422). The other
    three claim types may carry a substantiation reference but need not."

    PRD 3.5: "The drafting user's identifier is captured in
    `submitted_by_user_id`, `reviewed_by_user_id` stays null, and the claim opens at
    `PENDING`."

    Design: Corner/validations/health_claim_without_substantiation_rejected
    """
    ctx = build_chain(api, upto=19)
    round_id = ctx["artwork_round_id"]

    response = api.create_label_claim(
        f.health_claim_payload(
            round_id,
            claim_text="Supports heart health",
            substantiation_ref=None,
        ),
        DESIGNER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_SUBSTANTIATION_REQUIRED.value, 422)

    rows, meta = _claims_on(api, round_id)
    assert meta["total_count"] == 1, "the refused HEALTH claim must not be persisted"
    assert rows[0]["id"] == ctx["claim_id"]

    kept = read_claim(api, ctx["claim_id"])
    assert kept["claim_type"] == CLAIM_NUTRIENT_CONTENT, (
        "a NUTRIENT_CONTENT claim needs no substantiation reference"
    )
    assert_status(kept, CLAIM_PENDING, "label claim")
    assert kept["reviewed_by_user_id"] is None
    assert_artwork_state(
        read_artwork_round(api, round_id), ARTWORK_DRAFT, NUTRITION_VALID
    )


def test_reviewing_an_already_approved_claim_is_rejected(api):
    """Review is a once-only act; a second reviewer cannot overturn the first.

    PRD 3.5: "Reviewing a claim that has already reached `APPROVED`, `REJECTED` or
    `RESCINDED` is refused with `ERR_CLAIM_NOT_PENDING` (HTTP 409)."

    PRD 3.5: "Either way `reviewed_by_user_id` is set to the acting reviewer and
    the claim's `version` increments."

    PRD 3.5: "From the claim type the server derives `depends_on_nutrition`, which
    is true exactly for `NUTRIENT_CONTENT` and `HEALTH` claims and false for the
    other three"

    Design: Corner/state_machines/claim_review_twice_rejected
    """
    ctx = build_chain(api, upto=20)
    claim_id = ctx["claim_id"]
    assert_status(ctx["claim"], CLAIM_APPROVED, "label claim")

    response = api.review_label_claim(
        claim_id,
        f.review_payload(REVIEW_REJECT, rationale="second look"),
        REGULATORY_9_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_CLAIM_NOT_PENDING.value, 409)

    claim = read_claim(api, claim_id)
    assert_status(claim, CLAIM_APPROVED, "label claim")
    assert claim["reviewed_by_user_id"] == REGULATORY_7, (
        "the first reviewer's identifier stands"
    )
    assert claim["submitted_by_user_id"] == DESIGNER_1
    assert claim["depends_on_nutrition"] is True


def test_a_reviewer_may_not_review_the_claim_it_drafted_itself(api):
    """Both roles may draft, so the bar is the recorded drafter, not the role.

    PRD 3.5: "Claims are drafted onto a round by a `PackagingDesigner` or a
    `RegulatoryReviewer`."

    PRD 3.5: "Claim review belongs to a `RegulatoryReviewer` and must never be
    performed by the user who drafted the claim — segregation of duties is absolute
    here, and a self-review is refused with `ERR_CLAIM_SELF_REVIEW` (HTTP 403)."

    Design: Corner/rbac/label_claim_reviewer_cannot_review_its_own_claim
    """
    ctx = build_chain(api, upto=18)
    round_id = ctx["artwork_round_id"]
    own = validate_success(
        api.create_label_claim(
            f.label_claim_payload(round_id), REGULATORY_HEADERS
        ),
        expected_status=201,
    )
    assert own["submitted_by_user_id"] == REGULATORY_7

    response = api.review_label_claim(
        own["id"], f.review_payload(REVIEW_APPROVE), REGULATORY_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_CLAIM_SELF_REVIEW.value, 403)

    blocked = read_claim(api, own["id"])
    assert_status(blocked, CLAIM_PENDING, "label claim")
    assert blocked["submitted_by_user_id"] == REGULATORY_7
    assert blocked["reviewed_by_user_id"] is None
    assert_artwork_state(
        read_artwork_round(api, round_id), ARTWORK_DRAFT, NUTRITION_VALID
    )

    cleared = validate_success(
        api.review_label_claim(
            own["id"], f.review_payload(REVIEW_APPROVE), REGULATORY_9_HEADERS
        )
    )
    assert_status(cleared, CLAIM_APPROVED, "label claim")
    assert cleared["reviewed_by_user_id"] != REGULATORY_7, (
        "a different reviewer is admitted on the very same claim"
    )


def test_adding_a_claim_to_an_approved_round_is_rejected(api):
    """Regulatory approval freezes the round's claim set.

    PRD 3.5: "Claims may only be added to a round whose review status is `DRAFT` or
    `CHANGES_REQUESTED`; adding one to a round that is `IN_REVIEW`, `APPROVED` or
    `SUPERSEDED` is refused with `ERR_ARTWORK_STATE_INVALID` (HTTP 409)."

    Design: Corner/validations/label_claim_added_to_approved_artwork_round_rejected
    """
    ctx = build_chain(api, upto=22)
    round_id = ctx["artwork_round_id"]
    assert_artwork_state(ctx["artwork_round"], ARTWORK_APPROVED, NUTRITION_VALID)

    response = api.create_label_claim(
        f.label_claim_payload(round_id, claim_text="Now with 20 percent more fiber"),
        DESIGNER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_ARTWORK_STATE_INVALID.value, 409)

    assert_artwork_state(
        read_artwork_round(api, round_id), ARTWORK_APPROVED, NUTRITION_VALID
    )
    _rows, meta = _claims_on(api, round_id)
    assert meta["total_count"] == 1, "the frozen round keeps exactly its one claim"
    assert_status(read_claim(api, ctx["claim_id"]), CLAIM_APPROVED, "label claim")
    assert (
        read_item(api, ctx["item_id"])["development_status"] == ITEM_PACKAGING_APPROVED
    )


def test_the_revision_loop_returns_to_review_on_the_same_round_row(api):
    """CHANGES_REQUESTED reopens the same round; only the final APPROVE moves the item.

    PRD 3.5: "With `decision` set to `REQUEST_CHANGES` the round returns `IN_REVIEW
    → CHANGES_REQUESTED`, `reviewer_user_id` is stamped with the acting reviewer, and
    the designer may regenerate the panel, add claims and resubmit; `IN_REVIEW →
    CHANGES_REQUESTED → IN_REVIEW` is the revision loop and it may repeat without
    limit."

    PRD 3.5: "On approval, `reviewer_user_id` is stamped, every **other** artwork
    round of the same item still standing at `APPROVED` transitions to `SUPERSEDED` —
    each with its own `version` incremented — and the item advances `BENCHMARKED →
    PACKAGING_APPROVED`, incrementing the item's `version` too."

    PRD 3.5: "Its `round_number` is assigned by the server as one more than the
    number of rounds that already exist for the item, so the first round of an item is
    round 1."

    Design: Corner/state_machines/artwork_changes_requested_loop_reopens_review_and_approves
    """
    ctx = build_chain(api, upto=20)
    round_id = ctx["artwork_round_id"]
    item_id = ctx["item_id"]

    validate_success(api.submit_artwork_round(round_id, DESIGNER_HEADERS))
    returned = validate_success(
        api.review_artwork_round(
            round_id, f.review_payload(REVIEW_REQUEST_CHANGES), REGULATORY_HEADERS
        )
    )
    assert_artwork_state(returned, ARTWORK_CHANGES_REQUESTED, NUTRITION_VALID)
    assert read_item(api, item_id)["development_status"] == ITEM_BENCHMARKED, (
        "a revision request leaves the item at BENCHMARKED"
    )

    resubmitted = validate_success(api.submit_artwork_round(round_id, DESIGNER_HEADERS))
    assert_artwork_state(resubmitted, ARTWORK_IN_REVIEW, NUTRITION_VALID)

    approved = validate_success(
        api.review_artwork_round(
            round_id, f.review_payload(REVIEW_APPROVE), REGULATORY_HEADERS
        )
    )

    assert_artwork_state(approved, ARTWORK_APPROVED, NUTRITION_VALID)
    assert approved["round_number"] == 1, "the loop ran on the same round row"
    assert approved["reviewer_user_id"] == REGULATORY_7
    assert (
        read_item(api, item_id)["development_status"] == ITEM_PACKAGING_APPROVED
    )
