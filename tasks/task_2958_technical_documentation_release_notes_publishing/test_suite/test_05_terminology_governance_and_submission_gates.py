"""Controlled terminology, the violation scan, and the gates into review.

Style-guide governance in this service is a register of terms, a scan that runs
once per appended source revision, and a pair of counters that behave in
deliberately different ways: the revision's own counts are frozen snapshots
while the topic's counts are live and re-derived over the still-active register.
This module covers the scan's one-violation-per-term arithmetic, its
term-ascending output ordering, what retiring a term does and pointedly does
not do, and the ordered gauntlet a topic must clear to enter review.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_train,
    changes_requested_topic_context,
    create_reviewer,
    create_revision,
    create_revision_payload,
    create_terminology_term,
    create_writer,
    instants_equal,
    read_plan_item,
    read_release_train,
    read_reviewer,
    read_topic,
    request_signoff_payload,
    retire_terminology_term,
    set_clock,
    submit_topic,
    topic_context,
    validate_error,
    validate_list,
    validate_success,
)


CLOCK = "2026-08-01T00:00:00Z"


def _topic_with_two_violated_terms() -> dict:
    """A topic whose only revision trips one `BLOCKER` term through two forbidden
    forms and one `WARNING` term through one.

    The `BLOCKER` term is registered *first* so that its ``created_at`` precedes
    the `WARNING` term's, which makes the scan's ``term``-ascending output order
    ('email' before 'login') distinguishable from registration order.
    """
    login = create_terminology_term(
        term="login",
        preferred_form="sign in",
        forbidden_forms=["log in", "logon"],
        enforcement_severity="BLOCKER",
    )
    email = create_terminology_term(
        term="email",
        preferred_form="email address",
        forbidden_forms=["e-mail"],
        enforcement_severity="WARNING",
    )
    bundle = topic_context()
    bundle.update(login_term=login, login_term_id=login["id"], email_term=email,
                  email_term_id=email["id"])
    return bundle


class TestTerminologyViolationScan:
    """The scan that runs once per appended revision: one violation per violated
    term, ordered by the term's spelling rather than by its identifier."""

    def test_a_revision_records_one_violation_per_violated_term_in_term_order(
        self, api, writer_headers_for
    ):
        """Two violated terms yield one blocker and one warning, ordered by `term`.

        PRD §3.4: "The candidate list is the terminology terms whose `status` is
        `ACTIVE` only, ordered by `term` ascending; retired terms never produce a
        violation, and the ordering is by the term's spelling, never by its
        identifier."

        PRD §3.4: "Walking the candidate list in that pinned order, a term
        records exactly **one** violation if any submitted token equals any entry
        of that term's `forbidden_forms` under a case-insensitive comparison — a
        term violated by three different tokens still counts once — and that
        violation carries the term's `enforcement_severity`."

        PRD §3.4: "The blocker count is then the number of violations whose
        severity is `BLOCKER`, the warning count is the number whose severity is
        `WARNING`, and `violating_term_ids` is the list of violated term
        identifiers in the same `term`-ascending order."

        Design: Corner/calculations/terminology_scan_counts_one_violation_per_violated_term
        """
        set_clock(CLOCK)
        bundle = _topic_with_two_violated_terms()

        revision = validate_success(
            api.create_revision(
                bundle["topic_id"],
                create_revision_payload(
                    body_word_count=1200,
                    used_terms=["logon", "log in", "e-mail", "sign in"],
                    summary="First pass at the authentication overview.",
                ),
                writer_headers_for(bundle["writer_id"]),
            ),
            201,
        )

        assert revision["revision_number"] == 1
        assert revision["blocker_violation_count"] == 1
        assert revision["warning_violation_count"] == 1
        assert revision["violating_term_ids"] == [
            bundle["email_term_id"],
            bundle["login_term_id"],
        ], "violated ids come back in term-ascending order, not registration order"

        topic = read_topic(bundle["topic_id"])
        assert topic["open_blocker_violations"] == 1
        assert topic["open_warning_violations"] == 1
        assert topic["current_revision_number"] == 1
        assert topic["latest_body_word_count"] == 1200
        assert topic["review_state"] == "NOT_SUBMITTED"

    def test_a_term_tripped_by_three_forbidden_spellings_still_counts_once(
        self, api, writer_headers_for
    ):
        """Three distinct offending tokens against one term make one violation.

        PRD §3.4: "Walking the candidate list in that pinned order, a term
        records exactly **one** violation if any submitted token equals any entry
        of that term's `forbidden_forms` under a case-insensitive comparison — a
        term violated by three different tokens still counts once — and that
        violation carries the term's `enforcement_severity`."

        Design: Corner/calculations/terminology_scan_counts_one_violation_per_violated_term
        """
        set_clock(CLOCK)
        term = create_terminology_term(
            term="login",
            preferred_form="sign in",
            forbidden_forms=["log in", "logon", "log-in"],
            enforcement_severity="BLOCKER",
        )
        bundle = topic_context()

        revision = validate_success(
            api.create_revision(
                bundle["topic_id"],
                create_revision_payload(
                    used_terms=["log in", "logon", "log-in", "dashboard"],
                    summary="Three offending spellings of one governed term.",
                ),
                writer_headers_for(bundle["writer_id"]),
            ),
            201,
        )

        assert revision["blocker_violation_count"] == 1
        assert revision["warning_violation_count"] == 0
        assert revision["violating_term_ids"] == [term["id"]]
        assert read_topic(bundle["topic_id"])["open_blocker_violations"] == 1


class TestTermRetirementAndTheFrozenSnapshot:
    """Walking back a style-guide decision moves the live counters only; the
    revision that recorded the violation keeps its figures forever."""

    def test_retiring_a_term_clears_the_live_count_but_not_the_revision_record(
        self, api, docs_lead_headers
    ):
        """The topic's live blocker count falls to 0 while the revision still reads 1.

        PRD §3.4: "Retirement sets `status` to `RETIRED`, stamps `retired_at`
        with the logical clock, and then — for every topic whose newest source
        revision lists this term among its `violating_term_ids` — recomputes
        `open_blocker_violations` and `open_warning_violations` over the
        still-active terms only, and recomputes that topic's `health_score`."

        PRD §3.4: "What retirement pointedly does **not** do is rewrite any
        snapshot: each source revision keeps its `blocker_violation_count`,
        `warning_violation_count`, and `violating_term_ids` exactly as recorded,
        and every change record keeps its `terminology_blocker_count` exactly as
        recorded."

        Design: Corner/calculations/term_retirement_lowers_live_counts_but_never_the_revision_snapshot
        """
        set_clock(CLOCK)
        bundle = _topic_with_two_violated_terms()
        create_revision(
            bundle["topic_id"],
            bundle["writer_id"],
            used_terms=["logon", "log in", "e-mail"],
            summary="Authentication overview, first draft.",
        )

        retired = validate_success(
            api.retire_terminology_term(bundle["login_term_id"], {}, docs_lead_headers)
        )

        assert retired["status"] == "RETIRED"
        assert instants_equal(retired["retired_at"], CLOCK)

        topic = read_topic(bundle["topic_id"])
        assert topic["open_blocker_violations"] == 0, "the retired term no longer counts"
        assert topic["open_warning_violations"] == 1, "the still-active term keeps counting"

        rows, meta = validate_list(api.list_topic_revisions(bundle["topic_id"], docs_lead_headers))
        assert meta["total_count"] == 1
        assert rows[0]["blocker_violation_count"] == 1, "the snapshot is never rewritten"
        assert rows[0]["warning_violation_count"] == 1
        assert rows[0]["violating_term_ids"] == [
            bundle["email_term_id"],
            bundle["login_term_id"],
        ]

    def test_retiring_the_blocking_term_makes_the_page_submittable(
        self, api, writer_headers_for
    ):
        """A page held back by a blocker enters review once the term is retired.

        PRD §3.4: "A topic can become submittable as a direct result."

        PRD §3.5: "Last, the topic's `open_blocker_violations` must be exactly 0,
        else `ERR_TERMINOLOGY_BLOCKER_PRESENT` — and because that counter is
        live, a violation whose term has since been retired no longer stands in
        the way, while warning-severity violations never did."

        Design: Corner/calculations/term_retirement_lowers_live_counts_but_never_the_revision_snapshot
        """
        set_clock(CLOCK)
        bundle = _topic_with_two_violated_terms()
        create_revision(
            bundle["topic_id"],
            bundle["writer_id"],
            used_terms=["logon", "e-mail"],
            summary="Authentication overview, first draft.",
        )
        blocked = api.submit_topic_for_review(
            bundle["topic_id"], {}, writer_headers_for(bundle["writer_id"])
        )
        validate_error(blocked, ApiErrorId.TERMINOLOGY_BLOCKER_PRESENT, 409)

        retire_terminology_term(bundle["login_term_id"])
        submitted = validate_success(
            api.submit_topic_for_review(
                bundle["topic_id"], {}, writer_headers_for(bundle["writer_id"])
            )
        )

        assert submitted["review_state"] == "PENDING_SIGNOFF"
        assert submitted["last_submitted_revision_number"] == 1
        assert submitted["open_blocker_violations"] == 0
        assert submitted["open_warning_violations"] == 1, "a warning never blocked submission"
        assert instants_equal(submitted["submitted_at"], CLOCK)
        assert read_plan_item(bundle["plan_item_id"])["status"] == "IN_REVIEW"

    def test_retiring_an_already_retired_term_is_refused(self, api, docs_lead_headers):
        """Retirement is a once-only transition out of `ACTIVE`.

        PRD §3.4: "A `DocsLead` retires a term whose `status` must be `ACTIVE`; a
        second attempt on an already-retired term is refused with
        `ERR_TERM_ALREADY_RETIRED`."

        Design: Corner/state_machines/terminology_term_retire_from_retired_state_rejected
        """
        set_clock(CLOCK)
        term = create_terminology_term(term="allowlist", preferred_form="allow list")
        first = retire_terminology_term(term["id"])
        assert first["status"] == "RETIRED"

        response = api.retire_terminology_term(term["id"], {}, docs_lead_headers)
        validate_error(response, ApiErrorId.TERM_ALREADY_RETIRED, 409)

        unchanged = validate_success(api.get_terminology_term(term["id"], docs_lead_headers))
        assert unchanged["status"] == "RETIRED"
        assert instants_equal(unchanged["retired_at"], first["retired_at"])
        assert unchanged["version"] == first["version"]

        active_rows, active_meta = validate_list(
            api.list_terminology_terms(docs_lead_headers, params={"status": "ACTIVE"})
        )
        assert active_meta["total_count"] == 0
        assert active_rows == []


class TestSubmissionGateOrdering:
    """When a frozen release and a live blocker both bar the door, the posture is
    the refusal that gets reported, because it is consulted first."""

    def test_frozen_posture_is_reported_ahead_of_the_terminology_blocker(
        self, api, writer_headers_for
    ):
        """Both last two guards fail, and the posture refusal is the one returned.

        PRD §3.5: "Five conditions guard it, and they are evaluated in this
        order."

        PRD §3.5: "Then the release train's `doc_readiness_posture` is consulted:
        `OPEN` admits any submission, `RESTRICTED` admits a submission only when
        the plan item's `audience_tier` is `CRITICAL`, and `FROZEN` always
        rejects; a blocked submission returns `ERR_DOC_FREEZE_POSTURE_BLOCKED`."

        Design: Corner/validations/submit_review_posture_block_reported_over_terminology_blocker
        """
        set_clock(CLOCK)
        create_terminology_term(
            term="login",
            preferred_form="sign in",
            forbidden_forms=["logon"],
            enforcement_severity="BLOCKER",
        )
        bundle = topic_context(plan_item_overrides={"audience_tier": "STANDARD"})
        create_revision(
            bundle["topic_id"],
            bundle["writer_id"],
            used_terms=["logon"],
            summary="Draft that still uses the forbidden spelling.",
        )
        frozen = advance_train(bundle["train_id"], "DOC_FREEZE")
        assert frozen["approved_topic_ratio"] == pytest.approx(0.00, abs=0.01)
        assert frozen["doc_readiness_posture"] == "FROZEN"
        assert read_topic(bundle["topic_id"])["open_blocker_violations"] == 1

        response = api.submit_topic_for_review(
            bundle["topic_id"], {}, writer_headers_for(bundle["writer_id"])
        )
        validate_error(response, ApiErrorId.DOC_FREEZE_POSTURE_BLOCKED, 409)

        unchanged = read_topic(bundle["topic_id"])
        assert unchanged["review_state"] == "NOT_SUBMITTED"
        assert unchanged["last_submitted_revision_number"] == 0
        assert unchanged["submitted_at"] is None
        assert read_plan_item(bundle["plan_item_id"])["status"] == "IN_AUTHORING"

    def test_clearing_the_terminology_blocker_leaves_the_posture_refusal_standing(
        self, api, writer_headers_for
    ):
        """Retiring the term drops the live count to 0 and the posture still refuses.

        PRD §3.5: "Last, the topic's `open_blocker_violations` must be exactly 0,
        else `ERR_TERMINOLOGY_BLOCKER_PRESENT` — and because that counter is
        live, a violation whose term has since been retired no longer stands in
        the way, while warning-severity violations never did."

        PRD §3.5: "Then the release train's `doc_readiness_posture` is consulted:
        `OPEN` admits any submission, `RESTRICTED` admits a submission only when
        the plan item's `audience_tier` is `CRITICAL`, and `FROZEN` always
        rejects; a blocked submission returns `ERR_DOC_FREEZE_POSTURE_BLOCKED`."

        Design: Corner/validations/submit_review_posture_block_reported_over_terminology_blocker
        """
        set_clock(CLOCK)
        term = create_terminology_term(
            term="login",
            preferred_form="sign in",
            forbidden_forms=["logon"],
            enforcement_severity="BLOCKER",
        )
        bundle = topic_context(plan_item_overrides={"audience_tier": "STANDARD"})
        create_revision(
            bundle["topic_id"],
            bundle["writer_id"],
            used_terms=["logon"],
            summary="Draft that still uses the forbidden spelling.",
        )
        advance_train(bundle["train_id"], "DOC_FREEZE")
        retire_terminology_term(term["id"])
        assert read_topic(bundle["topic_id"])["open_blocker_violations"] == 0

        response = api.submit_topic_for_review(
            bundle["topic_id"], {}, writer_headers_for(bundle["writer_id"])
        )
        validate_error(response, ApiErrorId.DOC_FREEZE_POSTURE_BLOCKED, 409)

        assert read_topic(bundle["topic_id"])["review_state"] == "NOT_SUBMITTED"
        assert read_release_train(bundle["train_id"])["doc_readiness_posture"] == "FROZEN"


class TestAuthoringAndReviewGateRefusals:
    """Every refusal a page can collect on its way from a blank draft into review,
    each one reached from a genuine state rather than from a malformed body."""

    def test_a_page_with_no_authored_revision_cannot_be_submitted(
        self, api, writer_headers_for
    ):
        """An empty revision set is a refusal, not a zero-length success.

        PRD §3.5: "The topic's `current_revision_number` must be at least 1,
        because a page with no authored revision has nothing to review — an empty
        input set, not a zero-length success — and the refusal is
        `ERR_NO_REVISIONS`."

        Design: Corner/errors/authoring_and_review_gate_rejections_swept_in_one_lifecycle
        """
        set_clock(CLOCK)
        bundle = topic_context()
        assert read_topic(bundle["topic_id"])["current_revision_number"] == 0

        response = api.submit_topic_for_review(
            bundle["topic_id"], {}, writer_headers_for(bundle["writer_id"])
        )
        validate_error(response, ApiErrorId.NO_REVISIONS, 409)

        assert read_topic(bundle["topic_id"])["review_state"] == "NOT_SUBMITTED"
        assert read_plan_item(bundle["plan_item_id"])["status"] == "IN_AUTHORING"

    def test_a_sign_off_cannot_be_requested_on_a_page_that_is_not_in_review(
        self, api, docs_lead_headers
    ):
        """Sign-off requests need `PENDING_SIGNOFF`, not merely an authored draft.

        PRD §3.5: "The topic's `review_state` must be `PENDING_SIGNOFF` — a
        request against a page that is not currently in review is refused with
        `ERR_TOPIC_NOT_IN_REVIEW`."

        Design: Corner/errors/authoring_and_review_gate_rejections_swept_in_one_lifecycle
        """
        set_clock(CLOCK)
        bundle = topic_context()
        create_revision(bundle["topic_id"], bundle["writer_id"])
        reviewer = create_reviewer(discipline="ENGINEERING")

        response = api.request_signoff(
            bundle["topic_id"], request_signoff_payload(reviewer["id"]), docs_lead_headers
        )
        validate_error(response, ApiErrorId.TOPIC_NOT_IN_REVIEW, 409)

        rows, meta = validate_list(api.list_topic_signoffs(bundle["topic_id"], docs_lead_headers))
        assert meta["total_count"] == 0
        assert rows == []
        assert read_reviewer(reviewer["id"])["open_signoff_count"] == 0

    def test_a_writer_cannot_append_a_revision_to_another_writer_s_page(
        self, api, writer_headers_for
    ):
        """Authoring is bound to the plan item's assigned writer.

        PRD §2.5: "**Writer ownership.** Where a `Writer` acts on a topic,
        `X-User-ID` equals the topic's plan item `assigned_writer_id` — otherwise
        `ERR_NOT_ASSIGNED_WRITER` (HTTP 403)."

        Design: Corner/errors/authoring_and_review_gate_rejections_swept_in_one_lifecycle
        """
        set_clock(CLOCK)
        bundle = topic_context()
        interloper = create_writer()

        response = api.create_revision(
            bundle["topic_id"],
            create_revision_payload(summary="An edit from an unassigned author."),
            writer_headers_for(interloper["id"]),
        )
        validate_error(response, ApiErrorId.NOT_ASSIGNED_WRITER, 403)

        topic = read_topic(bundle["topic_id"])
        assert topic["current_revision_number"] == 0
        assert topic["latest_body_word_count"] == 0

    def test_a_page_carrying_a_live_blocker_cannot_be_submitted(
        self, api, writer_headers_for
    ):
        """With the posture `OPEN`, the terminology gate is the one that fires.

        PRD §3.5: "Last, the topic's `open_blocker_violations` must be exactly 0,
        else `ERR_TERMINOLOGY_BLOCKER_PRESENT` — and because that counter is
        live, a violation whose term has since been retired no longer stands in
        the way, while warning-severity violations never did."

        Design: Corner/errors/authoring_and_review_gate_rejections_swept_in_one_lifecycle
        """
        set_clock(CLOCK)
        create_terminology_term(
            term="login",
            preferred_form="sign in",
            forbidden_forms=["logon"],
            enforcement_severity="BLOCKER",
        )
        bundle = topic_context()
        create_revision(
            bundle["topic_id"],
            bundle["writer_id"],
            used_terms=["logon"],
            summary="Draft that still uses the forbidden spelling.",
        )
        assert read_release_train(bundle["train_id"])["doc_readiness_posture"] == "OPEN"

        response = api.submit_topic_for_review(
            bundle["topic_id"], {}, writer_headers_for(bundle["writer_id"])
        )
        validate_error(response, ApiErrorId.TERMINOLOGY_BLOCKER_PRESENT, 409)

        assert read_topic(bundle["topic_id"])["review_state"] == "NOT_SUBMITTED"
        assert read_plan_item(bundle["plan_item_id"])["status"] == "IN_AUTHORING"

    def test_a_page_already_in_review_cannot_be_submitted_again(
        self, api, writer_headers_for
    ):
        """Submission is admitted only from `NOT_SUBMITTED` or `CHANGES_REQUESTED`.

        PRD §3.5: "The topic's `review_state` must be `NOT_SUBMITTED` or
        `CHANGES_REQUESTED`; a page already `PENDING_SIGNOFF` or
        `FULLY_APPROVED` is refused with `ERR_TOPIC_ALREADY_IN_REVIEW`."

        Design: Corner/errors/authoring_and_review_gate_rejections_swept_in_one_lifecycle
        """
        set_clock(CLOCK)
        bundle = topic_context()
        create_revision(bundle["topic_id"], bundle["writer_id"])
        submitted = submit_topic(bundle["topic_id"], bundle["writer_id"])
        assert submitted["review_state"] == "PENDING_SIGNOFF"

        response = api.submit_topic_for_review(
            bundle["topic_id"], {}, writer_headers_for(bundle["writer_id"])
        )
        validate_error(response, ApiErrorId.TOPIC_ALREADY_IN_REVIEW, 409)

        unchanged = read_topic(bundle["topic_id"])
        assert unchanged["review_state"] == "PENDING_SIGNOFF"
        assert unchanged["last_submitted_revision_number"] == 1
        assert unchanged["current_revision_number"] == 1

    def test_a_page_awaiting_changes_cannot_re_enter_review_without_new_content(
        self, api, writer_headers_for
    ):
        """Re-submitting the identical revision closes the changes-requested loop.

        PRD §3.5: "The `current_revision_number` must be strictly greater than
        `last_submitted_revision_number`, so resubmitting the identical revision
        is refused with `ERR_NO_NEW_REVISION`; this is the guard that closes the
        changes-requested loop, since a page can only re-enter review once its
        author has actually written something new."

        Design: Corner/errors/authoring_and_review_gate_rejections_swept_in_one_lifecycle
        """
        set_clock(CLOCK)
        bundle = changes_requested_topic_context()
        awaiting = read_topic(bundle["topic_id"])
        assert awaiting["review_state"] == "CHANGES_REQUESTED"
        assert awaiting["current_revision_number"] == awaiting["last_submitted_revision_number"]

        response = api.submit_topic_for_review(
            bundle["topic_id"], {}, writer_headers_for(bundle["writer_id"])
        )
        validate_error(response, ApiErrorId.NO_NEW_REVISION, 409)

        assert read_topic(bundle["topic_id"])["review_state"] == "CHANGES_REQUESTED"
        assert read_plan_item(bundle["plan_item_id"])["status"] == "IN_REVISION"
