"""Duplicate-listing merges: three-hop cascade and reject-without-cascade."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    claim_page,
    create_business_page_payload,
    create_page,
    create_review,
    create_user,
    get_page,
    get_review,
    make_advertiser_headers,
    make_business_owner_headers,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_campaign_payload


def _setup_merge_pair(api):
    """Duplicate page PD (claimed, ad account + ACTIVE campaign, one DISPLAYED
    rating-5 review) and survivor page PS (one DISPLAYED rating-1 review)."""
    owner = create_user()
    pd = create_page(name="Dup Page", address_line="30 Same Rd")
    ps = create_page(name="Survivor Page", address_line="30 Same Rd")
    claim_page(pd["id"], owner["id"])
    m1 = create_user(trust_score=100)
    m2 = create_user(trust_score=100)
    rd = create_review(pd["id"], m1["id"], rating=5)
    rs = create_review(ps["id"], m2["id"], rating=1)
    account = validate_success(
        api.create_ad_account(pd["id"], {"daily_budget_cents": 10000},
                              make_business_owner_headers(owner["id"])),
        expected_status=201,
    )
    campaign = validate_success(
        api.create_campaign(account["id"], create_campaign_payload(bid_cents=100),
                            make_advertiser_headers(owner["id"])),
        expected_status=201,
    )
    validate_success(
        api.activate_campaign(campaign["id"], make_advertiser_headers(owner["id"]))
    )
    return owner, pd, ps, rd, rs, account, campaign


def _execute_merge(api, duplicate_id, survivor_id):
    mr = validate_success(
        api.create_merge_request(
            {
                "duplicate_page_id": duplicate_id,
                "survivor_page_id": survivor_id,
                "reason": "Same address, same business, duplicate listing.",
            },
            ADMIN,
        ),
        expected_status=201,
    )
    duplicate = get_page(duplicate_id)
    return mr, validate_success(
        api.execute_merge_request(
            mr["id"], {"expected_duplicate_page_version": duplicate["version"]}, ADMIN
        )
    )


class TestMergeExecuteCascade:
    def test_reviews_repointed_and_survivor_aggregates_recomputed(self, api):
        """PRD §3.11: "The first hop re-points every review whose `page_id`
        equals the duplicate's id to the survivor, preserving each review's
        `recommendation_state` and `evidence_confirmed` flag — reviews that
        were `REMOVED` stay `REMOVED`. The survivor's `displayed_review_count`
        is recomputed as the count of `DISPLAYED` reviews over the union of
        both pages' reviews, and its `displayed_rating_avg_x100` is recomputed
        over the same union (sum the ratings of the displayed reviews, divide
        by the count, multiply by 100, round half-up at the final division;
        zero when the count is zero)."

        Design: Difficulty/transitive_cascade/merge_execute_three_hop_cascade
        """
        set_clock("2026-09-01T00:00:00Z")
        owner, pd, ps, rd, rs, account, campaign = _setup_merge_pair(api)
        mr, executed = _execute_merge(api, pd["id"], ps["id"])
        assert executed["status"] == "EXECUTED"
        assert get_review(rd["id"])["page_id"] == ps["id"]
        survivor = get_page(ps["id"])
        assert survivor["displayed_review_count"] == 2
        # round_half_up(100 * (5 + 1) / 2) = 300.
        assert survivor["displayed_rating_avg_x100"] == 300
        duplicate = get_page(pd["id"])
        assert duplicate["status"] == "MERGED"
        assert duplicate["merged_into_id"] == ps["id"]
        assert duplicate["displayed_review_count"] == 0
        assert duplicate["displayed_rating_avg_x100"] == 0

    def test_duplicate_ad_account_closed_and_campaigns_cancelled(self, api):
        """PRD §3.11: "The second hop closes the duplicate's ad account (if
        any): the account transitions to `CLOSED` and every campaign on it in
        `DRAFT`, `ACTIVE`, or `PAUSED` moves to `CANCELLED`."

        Design: Difficulty/transitive_cascade/merge_execute_three_hop_cascade
        """
        set_clock("2026-09-01T00:00:00Z")
        owner, pd, ps, rd, rs, account, campaign = _setup_merge_pair(api)
        _execute_merge(api, pd["id"], ps["id"])
        account_after = validate_success(api.get_ad_account(account["id"], ADMIN))
        assert account_after["status"] == "CLOSED"
        campaign_after = validate_success(api.get_campaign(campaign["id"], ADMIN))
        assert campaign_after["status"] == "CANCELLED"

    # NOTE: test_other_pending_merge_touching_either_page_rejected was deleted
    # 2026-09-30 (unique-derivability collapse): the precondition "two PENDING
    # merges referencing a common page" is unreachable through PRD §3.11's own
    # filing rule ("Filing is rejected with ERR_MERGE_CONFLICT ... when another
    # PENDING merge request already references either page"), and execution
    # re-verifies the same exclusivity. No PRD-faithful setup can construct
    # the asserted state, so a faithful PRD-only implementation cannot pass it.


class TestMergeReject:
    def test_reject_leaves_both_pages_untouched(self, api):
        """PRD §3.11: "A `SupportAdmin` may also reject a `PENDING` merge
        request outright, moving it to terminal `REJECTED` with no cascade."

        Design: Corner/state_machines/merge_rejected_leaves_pages_untouched
        """
        set_clock("2026-09-01T00:00:00Z")
        pd = create_page(name="Reject Dup", address_line="9 Rej Rd")
        ps = create_page(name="Reject Surv", address_line="10 Rej Rd")
        mr = validate_success(
            api.create_merge_request(
                {
                    "duplicate_page_id": pd["id"],
                    "survivor_page_id": ps["id"],
                    "reason": "Possible duplicates under review.",
                },
                ADMIN,
            ),
            expected_status=201,
        )
        rejected = validate_success(api.reject_merge_request(mr["id"], ADMIN))
        assert rejected["status"] == "REJECTED"
        assert get_page(pd["id"])["status"] == "ACTIVE"
        assert get_page(pd["id"])["merged_into_id"] is None
        assert get_page(ps["id"])["status"] == "ACTIVE"


class TestMergeIntakeConflicts:
    def test_self_merge_rejected(self, api):
        """PRD §3.11: "Filing is rejected with `ERR_MERGE_CONFLICT` (HTTP 409)
        when the two ids are equal, when either page is not in `ACTIVE` status,
        or when another `PENDING` merge request already references either
        page."

        Design: Corner/errors/err_merge_conflict_self_merge
        """
        set_clock("2026-09-01T00:00:00Z")
        page = create_page(name="Selfmerge Subs")
        r = api.create_merge_request(
            {
                "duplicate_page_id": page["id"],
                "survivor_page_id": page["id"],
                "reason": "Merging a page into itself must fail.",
            },
            ADMIN,
        )
        validate_error(r, ApiErrorId.ERR_MERGE_CONFLICT.value)
