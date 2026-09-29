"""Sign-off requests, the two rules that guard them, and deciding exactly once.

Technical-accuracy review is a two-discipline handshake: a lead names a
reviewer, the reviewer answers once, and full approval arrives only when both
disciplines have said yes about the *same* draft.  This module covers the
ordering of the self-review prohibition against discipline uniqueness, the
bookkeeping a request performs on the reviewer's open workload, the once-only
nature of a decision, ownership of that decision, and the revision pinning that
makes a fresh commit wipe the review slate clean.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_reviewer,
    create_revision,
    create_revision_payload,
    decide_signoff,
    decide_signoff_payload,
    instants_equal,
    read_plan_item,
    read_release_train,
    read_reviewer,
    read_topic,
    request_signoff,
    request_signoff_payload,
    reviewer_pair,
    set_clock,
    submit_topic,
    submitted_topic_context,
    validate_error,
    validate_list,
    validate_success,
)


CLOCK = "2026-08-01T00:00:00Z"

AUTHOR_PERSON_KEY = "person-dana-okafor"


class TestSignoffRequestRuleOrdering:
    """A request can offend two rules at once; the fixed ordering decides which
    refusal the caller is told about."""

    def test_author_named_for_an_already_covered_discipline_reports_self_review(
        self, api, docs_lead_headers
    ):
        """Both rules are offended and the self-review refusal is the one returned.

        PRD §3.5: "**The self-review prohibition comes first**: the requested
        reviewer's `person_key` must differ from the `person_key` of the writer
        who authored the topic's newest source revision, because an author may
        never review their own page, and a violation returns
        `ERR_SELF_REVIEW_FORBIDDEN` (HTTP 403)."

        PRD §3.5: "Because the ordering is fixed, a self-review request aimed at a
        discipline that is already covered reports the self-review error, not the
        duplicate."

        Design: Difficulty/priority_pair_validation_conflict/self_review_beats_duplicate_signoff_discipline_rejected
        """
        set_clock(CLOCK)
        bundle = submitted_topic_context(writer_overrides={"person_key": AUTHOR_PERSON_KEY})
        incumbent = create_reviewer(discipline="ENGINEERING", person_key="person-lee-ashby")
        author_as_reviewer = create_reviewer(
            discipline="ENGINEERING", person_key=AUTHOR_PERSON_KEY
        )
        held = request_signoff(bundle["topic_id"], incumbent["id"])
        assert held["state"] == "PENDING"

        response = api.request_signoff(
            bundle["topic_id"], request_signoff_payload(author_as_reviewer["id"]), docs_lead_headers
        )
        validate_error(response, ApiErrorId.SELF_REVIEW_FORBIDDEN, 403)

        rows, meta = validate_list(api.list_topic_signoffs(bundle["topic_id"], docs_lead_headers))
        assert meta["total_count"] == 1, "the refused request created nothing"
        assert rows[0]["id"] == held["id"]
        assert rows[0]["state"] == "PENDING"
        assert read_reviewer(incumbent["id"])["open_signoff_count"] == 1
        assert read_reviewer(author_as_reviewer["id"])["open_signoff_count"] == 0
        assert read_topic(bundle["topic_id"])["review_state"] == "PENDING_SIGNOFF"

    def test_second_engineer_who_is_not_the_author_reports_the_duplicate_discipline(
        self, api, docs_lead_headers
    ):
        """With the self-review rule satisfied, the losing rule fires on its own.

        PRD §3.5: "**Only then** is discipline uniqueness checked: the topic must
        hold no sign-off in state `PENDING`, `APPROVED`, or `CHANGES_REQUESTED`
        for the requested reviewer's discipline, else
        `ERR_DUPLICATE_SIGNOFF_DISCIPLINE`."

        Design: Difficulty/priority_pair_validation_conflict/self_review_beats_duplicate_signoff_discipline_rejected
        """
        set_clock(CLOCK)
        bundle = submitted_topic_context(writer_overrides={"person_key": AUTHOR_PERSON_KEY})
        incumbent = create_reviewer(discipline="ENGINEERING", person_key="person-lee-ashby")
        stranger = create_reviewer(discipline="ENGINEERING", person_key="person-noor-haddad")
        request_signoff(bundle["topic_id"], incumbent["id"])

        response = api.request_signoff(
            bundle["topic_id"], request_signoff_payload(stranger["id"]), docs_lead_headers
        )
        validate_error(response, ApiErrorId.DUPLICATE_SIGNOFF_DISCIPLINE, 409)

        _, meta = validate_list(api.list_topic_signoffs(bundle["topic_id"], docs_lead_headers))
        assert meta["total_count"] == 1
        assert read_reviewer(stranger["id"])["open_signoff_count"] == 0

    def test_author_named_for_an_uncovered_discipline_still_reports_self_review(
        self, api, docs_lead_headers
    ):
        """The self-review rule stands alone: no incumbent sign-off is needed.

        PRD §3.5: "**The self-review prohibition comes first**: the requested
        reviewer's `person_key` must differ from the `person_key` of the writer
        who authored the topic's newest source revision, because an author may
        never review their own page, and a violation returns
        `ERR_SELF_REVIEW_FORBIDDEN` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/self_review_beats_duplicate_signoff_discipline_rejected
        """
        set_clock(CLOCK)
        bundle = submitted_topic_context(writer_overrides={"person_key": AUTHOR_PERSON_KEY})
        author_as_reviewer = create_reviewer(discipline="PRODUCT", person_key=AUTHOR_PERSON_KEY)

        response = api.request_signoff(
            bundle["topic_id"], request_signoff_payload(author_as_reviewer["id"]), docs_lead_headers
        )
        validate_error(response, ApiErrorId.SELF_REVIEW_FORBIDDEN, 403)

        _, meta = validate_list(api.list_topic_signoffs(bundle["topic_id"], docs_lead_headers))
        assert meta["total_count"] == 0
        assert read_reviewer(author_as_reviewer["id"])["open_signoff_count"] == 0


class TestSignoffRequestBookkeeping:
    """A request links a page to a reviewer, freezes the discipline at request
    time, and charges the reviewer's open workload."""

    def test_requesting_both_disciplines_links_each_reviewer_and_charges_their_queue(
        self, api, docs_lead_headers
    ):
        """Each sign-off names its topic and reviewer, copies the discipline, and
        leaves the pin empty.

        PRD §3.5: "Naming a `reviewer_id` creates a sign-off in state `PENDING` on
        the topic, copies the reviewer's `discipline` onto the sign-off so the
        requirement is fixed at request time, stamps `requested_at` with the
        logical clock, leaves `pinned_revision_number` null, and increases that
        reviewer's `open_signoff_count` by 1."

        PRD §3.5: "A topic's sign-offs — including superseded history — can be
        listed in `created_at` ascending order and filtered by `state`; the global
        sign-off list additionally filters by `topic_id`, `reviewer_id`, `state`,
        and `discipline`."

        Design: Corner/endpoints/signoff_creation_links_topic_and_reviewer_and_bumps_open_count
        """
        set_clock(CLOCK)
        bundle = submitted_topic_context()
        bundle.update(reviewer_pair())

        engineering = validate_success(
            api.request_signoff(
                bundle["topic_id"],
                request_signoff_payload(bundle["engineering_reviewer_id"]),
                docs_lead_headers,
            ),
            201,
        )
        product = validate_success(
            api.request_signoff(
                bundle["topic_id"],
                request_signoff_payload(bundle["product_reviewer_id"]),
                docs_lead_headers,
            ),
            201,
        )

        assert engineering["topic_id"] == bundle["topic_id"]
        assert engineering["reviewer_id"] == bundle["engineering_reviewer_id"]
        assert engineering["discipline"] == "ENGINEERING"
        assert engineering["state"] == "PENDING"
        assert engineering["pinned_revision_number"] is None
        assert engineering["decided_at"] is None
        assert instants_equal(engineering["requested_at"], CLOCK)
        assert product["discipline"] == "PRODUCT"
        assert product["pinned_revision_number"] is None

        assert read_reviewer(bundle["engineering_reviewer_id"])["open_signoff_count"] == 1
        assert read_reviewer(bundle["product_reviewer_id"])["open_signoff_count"] == 1

        rows, meta = validate_list(api.list_topic_signoffs(bundle["topic_id"], docs_lead_headers))
        assert meta["total_count"] == 2
        assert [row["id"] for row in rows] == [engineering["id"], product["id"]]

        filtered, filtered_meta = validate_list(
            api.list_signoffs(
                docs_lead_headers, params={"reviewer_id": bundle["product_reviewer_id"]}
            )
        )
        assert filtered_meta["total_count"] == 1
        assert filtered[0]["id"] == product["id"]

    def test_requesting_a_sign_off_from_an_unknown_reviewer_is_refused(
        self, api, docs_lead_headers
    ):
        """A body reference that resolves to nothing is a 404, and nothing is linked.

        PRD §2.5: "**Body reference existence.** Every reference supplied in a
        request body resolves to a live record, reported with the same family of
        404 codes: `writer_id`, `reviewer_id`, `release_train_id`, `plan_item_id`,
        `parent_topic_id` (reported as `ERR_PARENT_TOPIC_NOT_FOUND`),
        `locale_profile_id`, `topic_id`, and `migration_guide_topic_id` (reported
        as `ERR_TOPIC_NOT_FOUND`)."

        Design: Corner/endpoints/signoff_creation_links_topic_and_reviewer_and_bumps_open_count
        """
        set_clock(CLOCK)
        bundle = submitted_topic_context()

        response = api.request_signoff(
            bundle["topic_id"], request_signoff_payload(NON_EXISTENT_UUID), docs_lead_headers
        )
        validate_error(response, ApiErrorId.REVIEWER_NOT_FOUND, 404)

        rows, meta = validate_list(api.list_topic_signoffs(bundle["topic_id"], docs_lead_headers))
        assert meta["total_count"] == 0
        assert rows == []
        assert read_topic(bundle["topic_id"])["review_state"] == "PENDING_SIGNOFF"


class TestSignoffIsDecidedExactlyOnce:
    """A decision is quasi-terminal: the same sign-off cannot be answered twice."""

    def test_deciding_an_already_approved_sign_off_is_refused(
        self, api, reviewer_headers_for
    ):
        """The second decision on one sign-off is refused as already decided.

        PRD §3.5: "Three preconditions apply to both branches: `X-User-ID` must
        equal the sign-off's `reviewer_id` (`ERR_SIGNOFF_NOT_OWNED`), the
        sign-off's `state` must be `PENDING` — an already `APPROVED`,
        `CHANGES_REQUESTED`, or `SUPERSEDED` sign-off is refused with
        `ERR_SIGNOFF_ALREADY_DECIDED` — and the topic's `review_state` must be
        `PENDING_SIGNOFF` (`ERR_TOPIC_NOT_IN_REVIEW`)."

        Design: Corner/state_machines/signoff_decide_twice_rejected_as_already_decided
        """
        set_clock(CLOCK)
        bundle = submitted_topic_context()
        bundle.update(reviewer_pair())
        signoff = request_signoff(bundle["topic_id"], bundle["engineering_reviewer_id"])
        approved = decide_signoff(
            signoff["id"], bundle["engineering_reviewer_id"], "APPROVED"
        )
        assert approved["state"] == "APPROVED"
        assert approved["pinned_revision_number"] == 1

        response = api.decide_signoff(
            signoff["id"],
            decide_signoff_payload("CHANGES_REQUESTED", comment="Reconsidered on reflection."),
            reviewer_headers_for(bundle["engineering_reviewer_id"]),
        )
        validate_error(response, ApiErrorId.SIGNOFF_ALREADY_DECIDED, 409)

        unchanged = validate_success(
            api.get_signoff(signoff["id"], reviewer_headers_for(bundle["engineering_reviewer_id"]))
        )
        assert unchanged["state"] == "APPROVED"
        assert unchanged["pinned_revision_number"] == 1
        assert instants_equal(unchanged["decided_at"], approved["decided_at"])
        assert unchanged["version"] == approved["version"]
        assert read_reviewer(bundle["engineering_reviewer_id"])["open_signoff_count"] == 0
        assert read_topic(bundle["topic_id"])["review_state"] == "PENDING_SIGNOFF"


class TestFreshRevisionWipesTheReviewSlate:
    """A new commit on a page under review supersedes every open and approved
    sign-off and clears the revision each one was pinned to."""

    def test_a_new_revision_supersedes_both_sign_offs_and_clears_their_pins(
        self, api, docs_lead_headers
    ):
        """One approved and one pending sign-off both fall to `SUPERSEDED`.

        PRD §3.3: "If the topic's `review_state` is `PENDING_SIGNOFF` or
        `FULLY_APPROVED`, it returns to `NOT_SUBMITTED` and every sign-off on the
        topic that is not already `SUPERSEDED` moves to `SUPERSEDED` with its
        `pinned_revision_number` cleared."

        PRD §3.3: "Correspondingly, the plan item moves from `IN_REVIEW` or
        `APPROVED_CONTENT` back to `IN_AUTHORING`, and when an approval was
        invalidated the train's `approved_plan_item_count` drops by 1 and its
        ratio and posture are recomputed."

        Design: Corner/state_machines/new_revision_supersedes_signoffs_and_clears_pinned_revision
        """
        set_clock(CLOCK)
        bundle = submitted_topic_context()
        bundle.update(reviewer_pair())
        engineering = request_signoff(bundle["topic_id"], bundle["engineering_reviewer_id"])
        product = request_signoff(bundle["topic_id"], bundle["product_reviewer_id"])
        decide_signoff(engineering["id"], bundle["engineering_reviewer_id"], "APPROVED")

        validate_success(
            api.create_revision(
                bundle["topic_id"],
                create_revision_payload(summary="Rewrote the whole walkthrough."),
                bundle["writer_headers"],
            ),
            201,
        )

        rows, meta = validate_list(
            api.list_topic_signoffs(
                bundle["topic_id"], docs_lead_headers, params={"state": "SUPERSEDED"}
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {engineering["id"], product["id"]}
        for row in rows:
            assert row["state"] == "SUPERSEDED"
            assert row["pinned_revision_number"] is None

        topic = read_topic(bundle["topic_id"])
        assert topic["review_state"] == "NOT_SUBMITTED"
        assert topic["publication_state"] == "UNPUBLISHED"
        assert topic["current_revision_number"] == 2
        assert topic["last_submitted_revision_number"] == 1
        assert read_plan_item(bundle["plan_item_id"])["status"] == "IN_AUTHORING"

    def test_only_the_pending_sign_off_releases_an_open_workload_slot(self):
        """The approved reviewer's queue was already released; the pending one's is not.

        PRD §3.5: "In every such case `pinned_revision_number` is cleared, and
        where the prior state was `PENDING` the reviewer's `open_signoff_count`
        decreases by 1; where the prior state was `APPROVED` there is no open
        count to adjust, since it was already released when the approval was
        recorded."

        Design: Corner/state_machines/new_revision_supersedes_signoffs_and_clears_pinned_revision
        """
        set_clock(CLOCK)
        bundle = submitted_topic_context()
        bundle.update(reviewer_pair())
        engineering = request_signoff(bundle["topic_id"], bundle["engineering_reviewer_id"])
        request_signoff(bundle["topic_id"], bundle["product_reviewer_id"])
        decide_signoff(engineering["id"], bundle["engineering_reviewer_id"], "APPROVED")
        assert read_reviewer(bundle["engineering_reviewer_id"])["open_signoff_count"] == 0
        assert read_reviewer(bundle["product_reviewer_id"])["open_signoff_count"] == 1

        create_revision(
            bundle["topic_id"],
            bundle["writer_id"],
            summary="Rewrote the whole walkthrough.",
        )

        assert read_reviewer(bundle["engineering_reviewer_id"])["open_signoff_count"] == 0
        assert read_reviewer(bundle["product_reviewer_id"])["open_signoff_count"] == 0


class TestFullApprovalRequiresOneSharedRevision:
    """Both disciplines must have approved the *same* draft; an approval that
    predates the latest commit no longer counts towards full approval."""

    def test_a_single_discipline_approved_at_the_new_revision_is_not_full_approval(
        self, api, docs_lead_headers
    ):
        """After a fresh commit only the re-approved discipline is pinned, so the
        page stays in review.

        PRD §3.5: "A topic reaches `review_state` `FULLY_APPROVED` at the moment it
        holds one `APPROVED` `ENGINEERING` sign-off and one `APPROVED` `PRODUCT`
        sign-off **both pinned to the topic's current revision number** — two
        approvals pinned to different revisions do not constitute full approval."

        Design: Corner/cross_cutting_complexity_layers/version_pinning_requires_both_disciplines_approved_at_one_revision
        """
        set_clock(CLOCK)
        bundle = submitted_topic_context()
        bundle.update(reviewer_pair())
        first_pass = request_signoff(bundle["topic_id"], bundle["engineering_reviewer_id"])
        approved_at_one = decide_signoff(
            first_pass["id"], bundle["engineering_reviewer_id"], "APPROVED"
        )
        assert approved_at_one["pinned_revision_number"] == 1

        create_revision(bundle["topic_id"], bundle["writer_id"], summary="Second draft.")
        submit_topic(bundle["topic_id"], bundle["writer_id"])
        second_pass = request_signoff(bundle["topic_id"], bundle["product_reviewer_id"])
        approved_at_two = decide_signoff(
            second_pass["id"], bundle["product_reviewer_id"], "APPROVED"
        )

        assert approved_at_two["pinned_revision_number"] == 2
        superseded = validate_success(api.get_signoff(first_pass["id"], docs_lead_headers))
        assert superseded["state"] == "SUPERSEDED"
        assert superseded["pinned_revision_number"] is None

        topic = read_topic(bundle["topic_id"])
        assert topic["review_state"] == "PENDING_SIGNOFF", "only one discipline is pinned at 2"
        assert topic["approved_at"] is None
        assert topic["signoff_latency_days"] is None
        assert read_plan_item(bundle["plan_item_id"])["status"] == "IN_REVIEW"
        assert read_release_train(bundle["train_id"])["approved_plan_item_count"] == 0

    def test_both_disciplines_approved_at_the_same_revision_reach_full_approval(
        self, api, docs_lead_headers
    ):
        """Re-approving the second discipline at revision 2 completes the handshake.

        PRD §3.5: "A topic reaches `review_state` `FULLY_APPROVED` at the moment it
        holds one `APPROVED` `ENGINEERING` sign-off and one `APPROVED` `PRODUCT`
        sign-off **both pinned to the topic's current revision number** — two
        approvals pinned to different revisions do not constitute full approval."

        PRD §3.5: "Reaching `FULLY_APPROVED` stamps `approved_at` with the logical
        clock, computes `signoff_latency_days` as the whole number of days between
        `submitted_at` and `approved_at` with any fractional day discarded,
        computes the topic's `health_score` under the pre-publication variant and
        sets `health_score_variant` to `PRE_PUBLICATION`, moves the plan item from
        `IN_REVIEW` to `APPROVED_CONTENT`, increments the train's
        `approved_plan_item_count` by 1, and recomputes the train's ratio and
        posture."

        Design: Corner/cross_cutting_complexity_layers/version_pinning_requires_both_disciplines_approved_at_one_revision
        """
        set_clock(CLOCK)
        bundle = submitted_topic_context()
        bundle.update(reviewer_pair())
        first_pass = request_signoff(bundle["topic_id"], bundle["engineering_reviewer_id"])
        decide_signoff(first_pass["id"], bundle["engineering_reviewer_id"], "APPROVED")
        create_revision(bundle["topic_id"], bundle["writer_id"], summary="Second draft.")
        submit_topic(bundle["topic_id"], bundle["writer_id"])
        product_at_two = request_signoff(bundle["topic_id"], bundle["product_reviewer_id"])
        decide_signoff(product_at_two["id"], bundle["product_reviewer_id"], "APPROVED")

        engineering_at_two = request_signoff(
            bundle["topic_id"], bundle["engineering_reviewer_id"]
        )
        final = decide_signoff(
            engineering_at_two["id"], bundle["engineering_reviewer_id"], "APPROVED"
        )

        assert final["pinned_revision_number"] == 2
        topic = read_topic(bundle["topic_id"])
        assert topic["review_state"] == "FULLY_APPROVED"
        assert instants_equal(topic["approved_at"], CLOCK)
        assert topic["signoff_latency_days"] == 0
        assert topic["health_score_variant"] == "PRE_PUBLICATION"
        assert topic["health_score"] == pytest.approx(100.00, abs=0.01)
        assert read_plan_item(bundle["plan_item_id"])["status"] == "APPROVED_CONTENT"

        train = read_release_train(bundle["train_id"])
        assert train["approved_plan_item_count"] == 1
        assert train["approved_topic_ratio"] == pytest.approx(1.00, abs=0.01)
        assert train["doc_readiness_posture"] == "OPEN"

        rows, meta = validate_list(api.list_topic_signoffs(bundle["topic_id"], docs_lead_headers))
        assert meta["total_count"] == 3, "the superseded first pass is still on the record"
        assert [row["state"] for row in rows] == ["SUPERSEDED", "APPROVED", "APPROVED"]


class TestOnlyTheAddressedReviewerMayDecide:
    """A sign-off is addressed to exactly one reviewer, and ownership is checked
    before the sign-off's own state is even consulted."""

    def test_a_reviewer_cannot_decide_a_sign_off_addressed_to_a_colleague(
        self, api, docs_lead_headers, reviewer_headers_for
    ):
        """The product reviewer cannot answer the engineering request.

        PRD §2.5: "**Reviewer ownership.** Where a `Reviewer` decides a sign-off,
        `X-User-ID` equals that sign-off's `reviewer_id` — otherwise
        `ERR_SIGNOFF_NOT_OWNED` (HTTP 403)."

        Design: Corner/rbac/reviewer_cannot_decide_a_signoff_addressed_to_another_reviewer
        """
        set_clock(CLOCK)
        bundle = submitted_topic_context()
        bundle.update(reviewer_pair())
        engineering = request_signoff(bundle["topic_id"], bundle["engineering_reviewer_id"])

        response = api.decide_signoff(
            engineering["id"],
            decide_signoff_payload("APPROVED", comment="Looks right to me."),
            reviewer_headers_for(bundle["product_reviewer_id"]),
        )
        validate_error(response, ApiErrorId.SIGNOFF_NOT_OWNED, 403)

        untouched = validate_success(api.get_signoff(engineering["id"], docs_lead_headers))
        assert untouched["state"] == "PENDING"
        assert untouched["decided_at"] is None
        assert untouched["pinned_revision_number"] is None
        assert untouched["reviewer_id"] == bundle["engineering_reviewer_id"]
        assert read_reviewer(bundle["engineering_reviewer_id"])["open_signoff_count"] == 1
        assert read_reviewer(bundle["product_reviewer_id"])["open_signoff_count"] == 0
        assert read_topic(bundle["topic_id"])["review_state"] == "PENDING_SIGNOFF"

    def test_ownership_is_reported_ahead_of_a_sign_off_that_is_already_decided(
        self, api, docs_lead_headers, reviewer_headers_for
    ):
        """A stranger deciding an already-answered sign-off hears about ownership.

        PRD §2.5: "Checks are evaluated in the following order, and the first
        check that fails determines the response; no later check is evaluated once
        an earlier one has failed."

        PRD §2.5: "**Reviewer ownership.** Where a `Reviewer` decides a sign-off,
        `X-User-ID` equals that sign-off's `reviewer_id` — otherwise
        `ERR_SIGNOFF_NOT_OWNED` (HTTP 403)."

        Design: Corner/rbac/reviewer_cannot_decide_a_signoff_addressed_to_another_reviewer
        """
        set_clock(CLOCK)
        bundle = submitted_topic_context()
        bundle.update(reviewer_pair())
        request_signoff(bundle["topic_id"], bundle["engineering_reviewer_id"])
        product = request_signoff(bundle["topic_id"], bundle["product_reviewer_id"])
        decided = decide_signoff(product["id"], bundle["product_reviewer_id"], "APPROVED")
        assert decided["state"] == "APPROVED"

        response = api.decide_signoff(
            product["id"],
            decide_signoff_payload("CHANGES_REQUESTED", comment="I disagree with my colleague."),
            reviewer_headers_for(bundle["engineering_reviewer_id"]),
        )
        validate_error(response, ApiErrorId.SIGNOFF_NOT_OWNED, 403)

        unchanged = validate_success(api.get_signoff(product["id"], docs_lead_headers))
        assert unchanged["state"] == "APPROVED"
        assert unchanged["pinned_revision_number"] == 1
        assert read_topic(bundle["topic_id"])["review_state"] == "PENDING_SIGNOFF"
