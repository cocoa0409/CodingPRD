"""Withdrawn approval, the readiness gate it feeds, and the two-dimensional page.

Approval in this system is never simply won: a reviewer asking for changes runs a
cascade that reaches the page, the deliverable, the writer's ledger and the
release train's readiness figures, and the figure that comes out the other end is
itself the gate on what may next be submitted for review.  This module follows
that cascade hop by hop, exercises the posture band as an admission gate on
submission, and pins down how a live page's review dimension can fall all the way
back to a blank slate while its publication dimension never moves.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_train,
    assign_plan_item,
    create_plan_item,
    create_revision,
    create_revision_payload,
    create_topic,
    decide_signoff,
    decide_signoff_payload,
    instants_equal,
    nth_authoring_window,
    published_topic_context,
    read_doc_set_version,
    read_plan_item,
    read_release_train,
    read_reviewer,
    read_topic,
    read_writer,
    request_signoff,
    reviewer_pair,
    roster_context,
    set_clock,
    submit_topic,
    submitted_topic_context,
    validate_error,
    validate_list,
    validate_success,
)


CLOCK = "2026-08-01T00:00:00Z"

#: A six-page STANDARD new topic of complexity 10, held by a SENIOR writer:
#: 12 size points + 10 depth points + 4 information-architecture points, times
#: the 1.0 STANDARD multiplier, divided by the 1.0 SENIOR divisor (§3.2).
BASE_LOAD_POINTS = 26.00

#: A four-page CRITICAL concept hub of complexity 25, held by the same writer:
#: 8 size points + 20 capped depth points + 6 hub points, times 1.5 (§3.2).
CRITICAL_LOAD_POINTS = 51.00

STANDARD_DELIVERABLE = {
    "ia_placement": "NEW_TOPIC",
    "audience_tier": "STANDARD",
    "planned_page_count": 6,
    "complexity_points": 10,
}


def _deliverable_under_review(capacity_points: float = 200.0) -> dict:
    """One six-page deliverable in review holding an approved engineering sign-off
    and an undecided product sign-off."""
    bundle = submitted_topic_context(
        writer_overrides={"capacity_points": capacity_points, "seniority_tier": "SENIOR"},
        plan_item_overrides=dict(STANDARD_DELIVERABLE),
    )
    bundle.update(reviewer_pair())
    engineering = request_signoff(bundle["topic_id"], bundle["engineering_reviewer_id"])
    product = request_signoff(bundle["topic_id"], bundle["product_reviewer_id"])
    bundle["engineering_signoff"] = decide_signoff(
        engineering["id"], bundle["engineering_reviewer_id"], "APPROVED"
    )
    bundle.update(
        engineering_signoff_id=engineering["id"], product_signoff_id=product["id"]
    )
    return bundle


def _train_at_half_readiness(second_audience_tier: str) -> dict:
    """A frozen train holding two deliverables, one approved and one still being
    authored, so the ratio sits exactly on the `RESTRICTED` floor of 0.50."""
    bundle = roster_context(capacity_points=200.0, seniority_tier="SENIOR")
    bundle.update(reviewer_pair())

    approved_item = create_plan_item(bundle["train_id"], **STANDARD_DELIVERABLE)
    assign_plan_item(approved_item["id"], bundle["writer_id"], **nth_authoring_window(0))
    approved_topic = create_topic(approved_item["id"], bundle["writer_id"])
    create_revision(approved_topic["id"], bundle["writer_id"])
    submit_topic(approved_topic["id"], bundle["writer_id"])
    for reviewer_key in ("engineering_reviewer_id", "product_reviewer_id"):
        signoff = request_signoff(approved_topic["id"], bundle[reviewer_key])
        decide_signoff(signoff["id"], bundle[reviewer_key], "APPROVED")

    open_item = create_plan_item(
        bundle["train_id"],
        ia_placement="CONCEPT_HUB",
        audience_tier=second_audience_tier,
        planned_page_count=4,
        complexity_points=25,
    )
    assign_plan_item(open_item["id"], bundle["writer_id"], **nth_authoring_window(1))
    open_topic = create_topic(open_item["id"], bundle["writer_id"])
    create_revision(open_topic["id"], bundle["writer_id"])

    bundle["train"] = advance_train(bundle["train_id"], "DOC_FREEZE")
    bundle.update(
        approved_item_id=approved_item["id"],
        approved_topic_id=approved_topic["id"],
        open_item_id=open_item["id"],
        open_topic_id=open_topic["id"],
    )
    return bundle


class TestChangesRequestedCascade:
    """One reviewer asking for changes reaches four levels deep: the sign-off, the
    page and its siblings, the deliverable and the writer's ledger, and the
    train's readiness figures."""

    def test_requesting_changes_supersedes_the_sibling_approval_on_the_same_page(
        self, api, docs_lead_headers, reviewer_headers_for
    ):
        """The decision lands, and the colleague's approval is wiped with it.

        PRD §3.5: "**Hop one** stamps `decided_at` from the logical clock, leaves
        `pinned_revision_number` null, and decreases the reviewer's
        `open_signoff_count` by 1."

        PRD §3.5: "**Hop two**, caused by hop one, sets the topic's `review_state`
        to `CHANGES_REQUESTED` and moves every **other** sign-off of that topic
        whose state is `PENDING` or `APPROVED` to `SUPERSEDED`, clearing each
        one's `pinned_revision_number` — a single reviewer asking for changes wipes
        the slate for both disciplines."

        Design: Difficulty/transitive_cascade/changes_requested_cascade_depth_four_to_writer_and_train
        """
        set_clock(CLOCK)
        bundle = _deliverable_under_review()
        assert bundle["engineering_signoff"]["pinned_revision_number"] == 1

        decided = validate_success(
            api.decide_signoff(
                bundle["product_signoff_id"],
                decide_signoff_payload(
                    "CHANGES_REQUESTED", comment="The authentication steps are out of order."
                ),
                reviewer_headers_for(bundle["product_reviewer_id"]),
            )
        )

        assert decided["state"] == "CHANGES_REQUESTED"
        assert decided["pinned_revision_number"] is None
        assert instants_equal(decided["decided_at"], CLOCK)
        assert read_reviewer(bundle["product_reviewer_id"])["open_signoff_count"] == 0

        rows, meta = validate_list(api.list_topic_signoffs(bundle["topic_id"], docs_lead_headers))
        assert meta["total_count"] == 2
        superseded = next(row for row in rows if row["id"] == bundle["engineering_signoff_id"])
        assert superseded["state"] == "SUPERSEDED"
        assert superseded["pinned_revision_number"] is None
        assert read_reviewer(bundle["engineering_reviewer_id"])["open_signoff_count"] == 0

        topic = read_topic(bundle["topic_id"])
        assert topic["review_state"] == "CHANGES_REQUESTED"
        assert topic["approved_at"] is None
        assert topic["last_submitted_revision_number"] == 1

    def test_requesting_changes_charges_a_rework_unit_and_leaves_readiness_derived(
        self, api, reviewer_headers_for
    ):
        """The deliverable gains a rework unit and a load point, the writer's ledger
        follows, and the train's figures still match a full recomputation.

        PRD §3.5: "**Hop three**, caused by hop two, moves the plan item from
        `IN_REVIEW` to `IN_REVISION`, increases its `rework_count` by 1, raises its
        `load_points` by 1.0 point for that additional rework unit, and recomputes
        the assigned writer's `committed_load_points` so the conserved quantity
        still equals the sum over the writer's counted items."

        PRD §3.5: "**Hop four**, caused by hop three, recomputes the train's
        `approved_topic_ratio` and `doc_readiness_posture`."

        PRD §3.2: "Sixth and last, `load_points` is the base load plus 1.0 point
        for each unit of the item's `rework_count`, rounded half up to two decimal
        places; because the rework points are added *after* the floor, they always
        raise the total."

        Design: Difficulty/transitive_cascade/changes_requested_cascade_depth_four_to_writer_and_train
        """
        set_clock(CLOCK)
        bundle = _train_at_half_readiness("CRITICAL")
        submit_topic(bundle["open_topic_id"], bundle["writer_id"])
        engineering = request_signoff(bundle["open_topic_id"], bundle["engineering_reviewer_id"])
        product = request_signoff(bundle["open_topic_id"], bundle["product_reviewer_id"])
        decide_signoff(engineering["id"], bundle["engineering_reviewer_id"], "APPROVED")
        assert read_plan_item(bundle["open_item_id"])["load_points"] == pytest.approx(
            CRITICAL_LOAD_POINTS, abs=0.01
        )
        assert read_writer(bundle["writer_id"])["committed_load_points"] == pytest.approx(
            BASE_LOAD_POINTS + CRITICAL_LOAD_POINTS, abs=0.01
        )

        validate_success(
            api.decide_signoff(
                product["id"],
                decide_signoff_payload("CHANGES_REQUESTED", comment="Needs a migration example."),
                reviewer_headers_for(bundle["product_reviewer_id"]),
            )
        )

        item = read_plan_item(bundle["open_item_id"])
        assert item["status"] == "IN_REVISION"
        assert item["rework_count"] == 1
        assert item["load_points"] == pytest.approx(CRITICAL_LOAD_POINTS + 1.0, abs=0.01)

        writer = read_writer(bundle["writer_id"])
        assert writer["committed_load_points"] == pytest.approx(
            BASE_LOAD_POINTS + CRITICAL_LOAD_POINTS + 1.0, abs=0.01
        )
        assert writer["assignment_count"] == 2

        train = read_release_train(bundle["train_id"])
        assert train["plan_item_count"] == 2
        assert train["approved_plan_item_count"] == 1
        assert train["approved_topic_ratio"] == pytest.approx(0.50, abs=0.01)
        assert train["doc_readiness_posture"] == "RESTRICTED"

    def test_rework_may_push_a_writer_past_their_capacity_ceiling(
        self, api, reviewer_headers_for
    ):
        """A writer loaded exactly to their ceiling still absorbs the rework point.

        PRD §3.5: "Notably, the capacity ceiling is **not** re-checked on this
        cascade path: rework can push a writer above `capacity_points`, and that is
        intended, because refusing a reviewer's feedback would be worse."

        PRD §3.2: "The capacity ceiling is checked at assignment time by adding the
        freshly computed `load_points` to the writer's current
        `committed_load_points` and comparing the total against `capacity_points`:
        equality is accepted and only a strict excess is rejected, with
        `ERR_WRITER_CAPACITY_EXCEEDED`."

        Design: Difficulty/transitive_cascade/changes_requested_cascade_depth_four_to_writer_and_train
        """
        set_clock(CLOCK)
        bundle = _deliverable_under_review(capacity_points=BASE_LOAD_POINTS)
        loaded_to_the_ceiling = read_writer(bundle["writer_id"])
        assert loaded_to_the_ceiling["capacity_points"] == pytest.approx(
            BASE_LOAD_POINTS, abs=0.01
        )
        assert loaded_to_the_ceiling["committed_load_points"] == pytest.approx(
            BASE_LOAD_POINTS, abs=0.01
        )

        validate_success(
            api.decide_signoff(
                bundle["product_signoff_id"],
                decide_signoff_payload("CHANGES_REQUESTED", comment="Please expand the examples."),
                reviewer_headers_for(bundle["product_reviewer_id"]),
            )
        )

        item = read_plan_item(bundle["plan_item_id"])
        assert item["status"] == "IN_REVISION"
        assert item["load_points"] == pytest.approx(BASE_LOAD_POINTS + 1.0, abs=0.01)

        overloaded = read_writer(bundle["writer_id"])
        assert overloaded["committed_load_points"] == pytest.approx(
            BASE_LOAD_POINTS + 1.0, abs=0.01
        )
        assert overloaded["committed_load_points"] > overloaded["capacity_points"]
        assert overloaded["assignment_count"] == 1


class TestReadinessPostureGatesSubmission:
    """Whether a page may enter review is decided by a figure that lives on the
    release train, not on the page — and the audience tier is the only exemption."""

    def test_a_restricted_train_admits_a_critical_deliverable(self, api, writer_headers_for):
        """At a ratio of exactly 0.50 the band is `RESTRICTED`, which a `CRITICAL`
        page may still cross.

        PRD §3.1: "Both band boundaries are inclusive from below: a ratio of exactly
        0.80 yields `OPEN`, exactly 0.50 yields `RESTRICTED`, and 0.49 yields
        `FROZEN`."

        PRD §3.5: "Then the release train's `doc_readiness_posture` is consulted:
        `OPEN` admits any submission, `RESTRICTED` admits a submission only when the
        plan item's `audience_tier` is `CRITICAL`, and `FROZEN` always rejects; a
        blocked submission returns `ERR_DOC_FREEZE_POSTURE_BLOCKED`."

        Design: Difficulty/cross_entity_state_dependency/topic_submit_review_gated_by_release_train_posture
        """
        set_clock(CLOCK)
        bundle = _train_at_half_readiness("CRITICAL")
        train = read_release_train(bundle["train_id"])
        assert train["status"] == "DOC_FREEZE"
        assert train["approved_topic_ratio"] == pytest.approx(0.50, abs=0.01)
        assert train["doc_readiness_posture"] == "RESTRICTED"
        assert read_plan_item(bundle["open_item_id"])["load_points"] == pytest.approx(
            CRITICAL_LOAD_POINTS, abs=0.01
        )

        admitted = validate_success(
            api.submit_topic_for_review(
                bundle["open_topic_id"], {}, writer_headers_for(bundle["writer_id"])
            )
        )

        assert admitted["review_state"] == "PENDING_SIGNOFF"
        assert admitted["last_submitted_revision_number"] == 1
        assert instants_equal(admitted["submitted_at"], CLOCK)
        assert read_plan_item(bundle["open_item_id"])["status"] == "IN_REVIEW"

    def test_a_restricted_train_turns_a_standard_deliverable_away(
        self, api, writer_headers_for
    ):
        """The same posture on the same train refuses a `STANDARD` page.

        PRD §3.5: "Then the release train's `doc_readiness_posture` is consulted:
        `OPEN` admits any submission, `RESTRICTED` admits a submission only when the
        plan item's `audience_tier` is `CRITICAL`, and `FROZEN` always rejects; a
        blocked submission returns `ERR_DOC_FREEZE_POSTURE_BLOCKED`."

        Design: Difficulty/cross_entity_state_dependency/topic_submit_review_gated_by_release_train_posture
        """
        set_clock(CLOCK)
        bundle = _train_at_half_readiness("STANDARD")
        assert read_release_train(bundle["train_id"])["doc_readiness_posture"] == "RESTRICTED"

        response = api.submit_topic_for_review(
            bundle["open_topic_id"], {}, writer_headers_for(bundle["writer_id"])
        )
        validate_error(response, ApiErrorId.DOC_FREEZE_POSTURE_BLOCKED, 409)

        blocked = read_topic(bundle["open_topic_id"])
        assert blocked["review_state"] == "NOT_SUBMITTED"
        assert blocked["last_submitted_revision_number"] == 0
        assert blocked["submitted_at"] is None
        assert read_plan_item(bundle["open_item_id"])["status"] == "IN_AUTHORING"

    def test_invalidating_a_sibling_approval_freezes_the_train_against_new_work(
        self, api, writer_headers_for
    ):
        """A revision on the approved page drops the ratio to 0.00, and the next
        submission anywhere on the train is refused.

        PRD §3.3: "Correspondingly, the plan item moves from `IN_REVIEW` or
        `APPROVED_CONTENT` back to `IN_AUTHORING`, and when an approval was
        invalidated the train's `approved_plan_item_count` drops by 1 and its ratio
        and posture are recomputed."

        PRD §3.5: "Then the release train's `doc_readiness_posture` is consulted:
        `OPEN` admits any submission, `RESTRICTED` admits a submission only when the
        plan item's `audience_tier` is `CRITICAL`, and `FROZEN` always rejects; a
        blocked submission returns `ERR_DOC_FREEZE_POSTURE_BLOCKED`."

        Design: Difficulty/cross_entity_state_dependency/topic_submit_review_gated_by_release_train_posture
        """
        set_clock(CLOCK)
        bundle = _train_at_half_readiness("CRITICAL")
        submit_topic(bundle["open_topic_id"], bundle["writer_id"])

        validate_success(
            api.create_revision(
                bundle["approved_topic_id"],
                create_revision_payload(summary="Corrected the deprecated flag names."),
                writer_headers_for(bundle["writer_id"]),
            ),
            201,
        )

        train = read_release_train(bundle["train_id"])
        assert train["plan_item_count"] == 2
        assert train["approved_plan_item_count"] == 0
        assert train["approved_topic_ratio"] == pytest.approx(0.00, abs=0.01)
        assert train["doc_readiness_posture"] == "FROZEN"
        assert read_plan_item(bundle["approved_item_id"])["status"] == "IN_AUTHORING"

        reopened = read_topic(bundle["approved_topic_id"])
        assert reopened["review_state"] == "NOT_SUBMITTED"
        assert reopened["current_revision_number"] == 2
        assert reopened["last_submitted_revision_number"] == 1

        response = api.submit_topic_for_review(
            bundle["approved_topic_id"], {}, writer_headers_for(bundle["writer_id"])
        )
        validate_error(response, ApiErrorId.DOC_FREEZE_POSTURE_BLOCKED, 409)

        assert read_topic(bundle["approved_topic_id"])["review_state"] == "NOT_SUBMITTED"
        assert read_topic(bundle["open_topic_id"])["review_state"] == "PENDING_SIGNOFF"


class TestLivePageDimensionsDiverge:
    """A page carries a review dimension and a publication dimension, and a commit
    on a page that is already live moves only one of them."""

    def test_a_commit_on_a_live_page_resets_review_without_taking_it_offline(
        self, api, docs_lead_headers
    ):
        """The review dimension falls back to a blank slate; the page stays published.

        PRD §3.3: "If the topic's `review_state` is `PENDING_SIGNOFF` or
        `FULLY_APPROVED`, it returns to `NOT_SUBMITTED` and every sign-off on the
        topic that is not already `SUPERSEDED` moves to `SUPERSEDED` with its
        `pinned_revision_number` cleared."

        PRD §3.3: "If the topic was `FULLY_APPROVED`, its `approved_at` and
        `signoff_latency_days` are cleared as well."

        PRD §3.3: "What the revision does **not** touch is `publication_state`: a
        page that is live stays `PUBLISHED`, with its `published_at` and
        `published_in_doc_set_version_id` intact, while its review dimension falls
        all the way back to `NOT_SUBMITTED`."

        Design: Difficulty/non_linear_state_machine/topic_parallel_dimensions_diverge_on_post_publication_revision
        """
        set_clock(CLOCK)
        bundle = published_topic_context()
        live = read_topic(bundle["topic_id"])
        assert live["review_state"] == "FULLY_APPROVED"
        assert live["publication_state"] == "PUBLISHED"

        validate_success(
            api.create_revision(
                bundle["topic_id"],
                create_revision_payload(summary="Post-launch correction to the CLI flags."),
                bundle["writer_headers"],
            ),
            201,
        )

        revised = read_topic(bundle["topic_id"])
        assert revised["review_state"] == "NOT_SUBMITTED"
        assert revised["publication_state"] == "PUBLISHED"
        assert revised["published_in_doc_set_version_id"] == bundle["doc_set_id"]
        assert instants_equal(revised["published_at"], live["published_at"])
        assert revised["approved_at"] is None
        assert revised["signoff_latency_days"] is None
        assert revised["current_revision_number"] == 2
        assert revised["last_submitted_revision_number"] == 1

        rows, meta = validate_list(api.list_topic_signoffs(bundle["topic_id"], docs_lead_headers))
        assert meta["total_count"] == 2
        for row in rows:
            assert row["state"] == "SUPERSEDED"
            assert row["pinned_revision_number"] is None

    def test_a_commit_on_a_live_page_leaves_the_deliverable_and_the_ledger_alone(self):
        """The deliverable is already terminal, so no load returns to the writer.

        PRD §3.3: "Correspondingly, the plan item moves from `IN_REVIEW` or
        `APPROVED_CONTENT` back to `IN_AUTHORING`, and when an approval was
        invalidated the train's `approved_plan_item_count` drops by 1 and its ratio
        and posture are recomputed."

        PRD §3.2: "Items that are `PUBLISHED` or `CANCELLED` are excluded, because
        publishing and cancelling both *release* capacity."

        Design: Difficulty/non_linear_state_machine/topic_parallel_dimensions_diverge_on_post_publication_revision
        """
        set_clock(CLOCK)
        bundle = published_topic_context()
        assert read_plan_item(bundle["plan_item_id"])["status"] == "PUBLISHED"
        released = read_writer(bundle["writer_id"])
        assert released["committed_load_points"] == pytest.approx(0.00, abs=0.01)
        assert released["assignment_count"] == 0

        create_revision(
            bundle["topic_id"],
            bundle["writer_id"],
            summary="Post-launch correction to the CLI flags.",
        )

        item = read_plan_item(bundle["plan_item_id"])
        assert item["status"] == "PUBLISHED", "a published deliverable is not reopened"
        assert item["rework_count"] == 0

        ledger = read_writer(bundle["writer_id"])
        assert ledger["committed_load_points"] == pytest.approx(0.00, abs=0.01)
        assert ledger["assignment_count"] == 0

        doc_set = read_doc_set_version(bundle["doc_set_id"])
        assert doc_set["status"] == "PUBLISHED"
        assert doc_set["published_topic_count"] == 1

    def test_a_live_page_can_re_enter_review_while_still_serving_readers(
        self, api, writer_headers_for
    ):
        """The two dimensions run on independently: review restarts, publication holds.

        PRD §3.3: "The two dimensions genuinely evolve independently on the same
        record."

        PRD §3.5: "A successful submission stamps `submitted_at` with the logical
        clock, sets `last_submitted_revision_number` to the current revision number,
        and moves the plan item from `IN_AUTHORING` or `IN_REVISION` to
        `IN_REVIEW`."

        Design: Difficulty/non_linear_state_machine/topic_parallel_dimensions_diverge_on_post_publication_revision
        """
        set_clock(CLOCK)
        bundle = published_topic_context()
        create_revision(
            bundle["topic_id"],
            bundle["writer_id"],
            summary="Post-launch correction to the CLI flags.",
        )
        assert read_release_train(bundle["train_id"])["doc_readiness_posture"] == "OPEN"

        resubmitted = validate_success(
            api.submit_topic_for_review(
                bundle["topic_id"], {}, writer_headers_for(bundle["writer_id"])
            )
        )

        assert resubmitted["review_state"] == "PENDING_SIGNOFF"
        assert resubmitted["publication_state"] == "PUBLISHED"
        assert resubmitted["current_revision_number"] == 2
        assert resubmitted["last_submitted_revision_number"] == 2
        assert instants_equal(resubmitted["submitted_at"], CLOCK)
        assert read_plan_item(bundle["plan_item_id"])["status"] == "PUBLISHED"
