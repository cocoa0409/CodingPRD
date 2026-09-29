"""Compiling and publishing a release note over a published documentation set.

A release note is the customer-facing end of the whole pipeline, and it is
computed rather than written: the candidate set is whatever survived editorial
review, the impact score is derived from that set twice with one input changed,
and the compilation itself is guarded by the parent documentation set's version
because a second compile issued from a stale view would silently discard an
editor's work.  An empty candidate set is an error, never a zero-score note.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assign_plan_item,
    create_change_record,
    create_plan_item,
    create_release_note,
    create_release_note_payload,
    create_revision,
    create_topic,
    create_writer,
    decide_signoff,
    deprecation_notice_context,
    editorial_pass,
    exclude_change_record,
    expected_impact_score,
    instants_equal,
    publish_release_note,
    published_topic_context,
    read_change_record,
    read_deprecation_notice,
    read_doc_set_version,
    read_plan_item,
    read_release_note,
    request_signoff,
    reviewer_pair,
    set_clock,
    set_clock_date,
    submit_topic,
    superseded_release_note_context,
    validate_error,
    validate_paginated,
    validate_success,
)


CLOCK = "2026-08-01T00:00:00Z"
APPROVED_TEXT = "Signing in is now faster and more reliable."


def _approve_a_second_deliverable(train_id: str) -> str:
    """Drive a second deliverable of ``train_id`` to ``APPROVED_CONTENT`` and return
    its ``feature_key``.

    Approved-but-never-published documentation is what makes the provisional and
    the final coverage factors disagree, and no shared builder produces it.
    """
    writer = create_writer()
    plan_item = create_plan_item(train_id)
    assign_plan_item(plan_item["id"], writer["id"])
    topic = create_topic(plan_item["id"], writer["id"])
    create_revision(topic["id"], writer["id"])
    submit_topic(topic["id"], writer["id"])
    reviewers = reviewer_pair()
    engineering = request_signoff(topic["id"], reviewers["engineering_reviewer_id"])
    product = request_signoff(topic["id"], reviewers["product_reviewer_id"])
    decide_signoff(engineering["id"], reviewers["engineering_reviewer_id"], "APPROVED")
    decide_signoff(product["id"], reviewers["product_reviewer_id"], "APPROVED")
    assert read_plan_item(plan_item["id"])["status"] == "APPROVED_CONTENT"
    return plan_item["feature_key"]


class TestEmptyCandidateSetIsRefused:
    """Zero editorially approved records is an error rather than a note with an
    empty body, and one such record is enough to cross the boundary."""

    def test_compiling_a_note_with_no_editorially_approved_record_is_refused(
        self, api, docs_lead_headers
    ):
        """A submitted record and an excluded record leave the candidate set empty.

        PRD §3.7: "The target documentation set must be `PUBLISHED`, else
        `ERR_DOC_SET_NOT_PUBLISHED`, and at least one change record of that train
        must be in state `EDITORIALLY_APPROVED`, else
        `ERR_NO_PUBLISHABLE_CHANGES` — an empty candidate set is an error, not a
        note with an empty body and a zero score."

        PRD §2.5: "**Constraint satisfaction.** Uniqueness, interval overlap,
        aggregate parallelism limits, and non-empty candidate sets."

        Design: Difficulty/boundary_precision_check/release_note_empty_candidate_set_rejected
        """
        set_clock(CLOCK)
        bundle = published_topic_context()
        feature_key = read_plan_item(bundle["plan_item_id"])["feature_key"]
        submitted = create_change_record(
            bundle["train_id"], severity="MINOR", affected_component=feature_key
        )
        dropped = create_change_record(
            bundle["train_id"], severity="PATCH", affected_component=feature_key
        )
        exclude_change_record(
            dropped["id"], exclusion_reason="Superseded before it ever shipped."
        )
        doc_set_before = read_doc_set_version(bundle["doc_set_id"])

        response = api.create_release_note(
            create_release_note_payload(bundle["doc_set_id"], doc_set_before["version"]),
            docs_lead_headers,
        )
        validate_error(response, ApiErrorId.NO_PUBLISHABLE_CHANGES, 409)

        _rows, meta = validate_paginated(
            api.list_release_notes(docs_lead_headers, {"doc_set_version_id": bundle["doc_set_id"]})
        )
        assert meta["total_count"] == 0, "a refused compilation must not leave a note behind"
        doc_set_after = read_doc_set_version(bundle["doc_set_id"])
        assert doc_set_after["status"] == "PUBLISHED"
        assert doc_set_after["version"] == doc_set_before["version"]
        assert read_change_record(submitted["id"])["state"] == "SUBMITTED"
        assert read_change_record(dropped["id"])["state"] == "EXCLUDED"

    def test_one_editorially_approved_record_is_enough_to_compile_a_note(
        self, api, docs_lead_headers
    ):
        """The same request that was refused succeeds once a single record clears.

        PRD §3.7: "The target documentation set must be `PUBLISHED`, else
        `ERR_DOC_SET_NOT_PUBLISHED`, and at least one change record of that train
        must be in state `EDITORIALLY_APPROVED`, else
        `ERR_NO_PUBLISHABLE_CHANGES` — an empty candidate set is an error, not a
        note with an empty body and a zero score."

        PRD §3.7: "Compilation opens the note with `status` `COMPILED`, stamps
        `compiled_at` from the logical clock, moves any existing `COMPILED` note
        of that documentation set to `SUPERSEDED` while leaving that superseded
        note's change records `EDITORIALLY_APPROVED` so they are recompiled into
        the new note, and increments the documentation set's `version` by 1."

        Design: Difficulty/boundary_precision_check/release_note_empty_candidate_set_rejected
        """
        set_clock(CLOCK)
        bundle = published_topic_context()
        feature_key = read_plan_item(bundle["plan_item_id"])["feature_key"]
        record = create_change_record(
            bundle["train_id"], severity="MINOR", affected_component=feature_key
        )
        version_before = read_doc_set_version(bundle["doc_set_id"])["version"]
        validate_error(
            api.create_release_note(
                create_release_note_payload(bundle["doc_set_id"], version_before),
                docs_lead_headers,
            ),
            ApiErrorId.NO_PUBLISHABLE_CHANGES,
            409,
        )

        editorial_pass(record["id"], customer_facing_text=APPROVED_TEXT)
        note = validate_success(
            api.create_release_note(
                create_release_note_payload(bundle["doc_set_id"], version_before),
                docs_lead_headers,
            ),
            201,
        )

        assert note["status"] == "COMPILED"
        assert note["release_train_id"] == bundle["train_id"]
        assert note["doc_set_version_id"] == bundle["doc_set_id"]
        assert note["included_change_record_ids"] == [record["id"]]
        assert instants_equal(note["compiled_at"], CLOCK)
        assert note["impact_score_provisional"] == pytest.approx(4.00, abs=0.01)
        assert note["impact_score_final"] is None
        assert read_doc_set_version(bundle["doc_set_id"])["version"] == version_before + 1


class TestCoverageDivergesBetweenCompilationAndPublication:
    """Approved-but-unpublished documentation is credited at compilation and loses
    that credit at publication, so the same records score twice."""

    def test_compilation_credits_approved_documentation_that_has_not_shipped(
        self, api, docs_lead_headers
    ):
        """Both records count as documented, so the provisional coverage is 1.00.

        PRD §3.7: "A record counts as *documented* when its `affected_component`
        equals the `feature_key` of at least one plan item of the train in the
        variant's counted status set, and the coverage factor is the number of
        documented records divided by the number of included records, rounded
        half up to two decimal places."

        PRD §3.7: "At compilation the coverage counts plan items whose status is
        `APPROVED_CONTENT` **or** `PUBLISHED` — approved-but-unpublished
        documentation is credited as if it will ship — and the results are stored
        as `coverage_factor_provisional` and `impact_score_provisional`, with
        `coverage_factor_final` and `impact_score_final` left null."

        PRD §3.7: "`included_change_record_ids` lists the compiled records
        ordered by severity rank ascending and then by `created_at` ascending,
        where the severity rank runs from the heaviest to the lightest."

        Design: Corner/calculations/release_note_coverage_diverges_between_provisional_and_final
        """
        set_clock(CLOCK)
        bundle = published_topic_context()
        published_feature = read_plan_item(bundle["plan_item_id"])["feature_key"]
        approved_only_feature = _approve_a_second_deliverable(bundle["train_id"])
        major = create_change_record(
            bundle["train_id"], severity="MAJOR", affected_component=published_feature
        )
        editorial_pass(major["id"], customer_facing_text=APPROVED_TEXT)
        minor = create_change_record(
            bundle["train_id"], severity="MINOR", affected_component=approved_only_feature
        )
        editorial_pass(minor["id"], customer_facing_text=APPROVED_TEXT)

        note = validate_success(
            api.create_release_note(
                create_release_note_payload(
                    bundle["doc_set_id"], read_doc_set_version(bundle["doc_set_id"])["version"]
                ),
                docs_lead_headers,
            ),
            201,
        )

        expected = expected_impact_score(["MAJOR", "MINOR"], 2)
        assert note["included_change_record_ids"] == [major["id"], minor["id"]]
        assert note["severity_counts"] == expected["severity_counts"]
        assert note["headline_severity"] == "MAJOR"
        assert note["coverage_factor_provisional"] == pytest.approx(1.00, abs=0.01)
        assert note["impact_score_provisional"] == pytest.approx(16.00, abs=0.01)
        assert note["impact_score_provisional"] == pytest.approx(
            expected["impact_score"], abs=0.01
        )
        assert note["coverage_factor_final"] is None
        assert note["impact_score_final"] is None

    def test_publication_withdraws_the_credit_and_raises_the_final_score(
        self, api, docs_lead_headers
    ):
        """Only the shipped deliverable counts at publication: 0.50 coverage, 24.00.

        PRD §3.7: "At publication the coverage counts plan items whose status is
        `PUBLISHED` **only** — documentation that never went live loses its
        credit — and the results are stored as `coverage_factor_final` and
        `impact_score_final`."

        PRD §3.7: "The score is the raw impact multiplied by two minus the
        coverage factor, rounded half up to two decimal places and then capped at
        100 — undocumented change is what hurts customers, so a coverage factor
        of `1.00` leaves the raw figure untouched while a coverage factor of
        `0.00` doubles it."

        PRD §3.7: "On success, `coverage_factor_final` and `impact_score_final`
        are computed with the final variant, `published_at` is stamped from the
        logical clock, and every included change record moves from
        `EDITORIALLY_APPROVED` to `PUBLISHED`."

        Design: Corner/calculations/release_note_coverage_diverges_between_provisional_and_final
        """
        set_clock(CLOCK)
        bundle = published_topic_context()
        published_feature = read_plan_item(bundle["plan_item_id"])["feature_key"]
        approved_only_feature = _approve_a_second_deliverable(bundle["train_id"])
        major = create_change_record(
            bundle["train_id"], severity="MAJOR", affected_component=published_feature
        )
        editorial_pass(major["id"], customer_facing_text=APPROVED_TEXT)
        minor = create_change_record(
            bundle["train_id"], severity="MINOR", affected_component=approved_only_feature
        )
        editorial_pass(minor["id"], customer_facing_text=APPROVED_TEXT)
        note = create_release_note(bundle["doc_set_id"])

        published = validate_success(
            api.publish_release_note(note["id"], {}, docs_lead_headers)
        )

        final = expected_impact_score(["MAJOR", "MINOR"], 1)
        assert published["status"] == "PUBLISHED"
        assert instants_equal(published["published_at"], CLOCK)
        assert published["coverage_factor_final"] == pytest.approx(0.50, abs=0.01)
        assert published["impact_score_final"] == pytest.approx(24.00, abs=0.01)
        assert published["impact_score_final"] == pytest.approx(final["impact_score"], abs=0.01)
        assert published["coverage_factor_provisional"] == pytest.approx(1.00, abs=0.01)
        assert published["impact_score_provisional"] == pytest.approx(16.00, abs=0.01)
        assert published["included_change_record_ids"] == [major["id"], minor["id"]]

        assert read_change_record(major["id"])["state"] == "PUBLISHED"
        assert read_change_record(minor["id"])["state"] == "PUBLISHED"
        assert read_plan_item(bundle["plan_item_id"])["status"] == "PUBLISHED"


class TestCompilationAgainstAStaleDocumentationSet:
    """The parent version check runs ahead of the candidate-set check, so a caller
    holding an old view of the documentation set learns that first."""

    def test_recompiling_from_a_stale_documentation_set_version_reports_the_conflict(
        self, api, docs_lead_headers
    ):
        """The earlier compilation bumped the set, so replaying its version is 412.

        PRD §2.6: "Compiling a release note requires
        `expected_doc_set_version_version` as a mandatory field in the request
        body, carrying the client's last observed `version` of the target
        `DocSetVersion`."

        PRD §2.6: "If that value does not equal the doc set version's current
        `version`, the request is rejected with `ERR_STALE_DOC_SET_VERSION`
        (HTTP 412) and no compilation occurs."

        PRD §2.5: "Checks are evaluated in the following order, and the first
        check that fails determines the response; no later check is evaluated
        once an earlier one has failed."

        Design: Corner/cross_cutting_complexity_layers/release_note_create_with_stale_doc_set_version_rejected
        """
        set_clock(CLOCK)
        bundle = published_topic_context()
        feature_key = read_plan_item(bundle["plan_item_id"])["feature_key"]
        record = create_change_record(
            bundle["train_id"], severity="MINOR", category="FIX", affected_component=feature_key
        )
        editorial_pass(record["id"], customer_facing_text=APPROVED_TEXT)
        stale_version = read_doc_set_version(bundle["doc_set_id"])["version"]
        first_note = create_release_note(bundle["doc_set_id"], stale_version)
        publish_release_note(first_note["id"])
        assert read_change_record(record["id"])["state"] == "PUBLISHED"

        response = api.create_release_note(
            create_release_note_payload(bundle["doc_set_id"], stale_version), docs_lead_headers
        )
        validate_error(response, ApiErrorId.STALE_DOC_SET_VERSION, 412)

        _rows, meta = validate_paginated(
            api.list_release_notes(docs_lead_headers, {"doc_set_version_id": bundle["doc_set_id"]})
        )
        assert meta["total_count"] == 1, "no compilation occurs when the parent view is stale"
        assert read_release_note(first_note["id"])["status"] == "PUBLISHED"
        assert read_doc_set_version(bundle["doc_set_id"])["version"] == stale_version + 1

    def test_the_refreshed_view_then_reports_the_empty_candidate_set(
        self, api, docs_lead_headers
    ):
        """Once the version matches, the candidate-set check finally gets to speak.

        PRD §2.5: "**Optimistic concurrency.** The two write operations that
        carry a parent version expectation compare it against the parent's live
        `version`, as specified in §2.6, and reject a mismatch with HTTP 412."

        PRD §3.7: "The target documentation set must be `PUBLISHED`, else
        `ERR_DOC_SET_NOT_PUBLISHED`, and at least one change record of that train
        must be in state `EDITORIALLY_APPROVED`, else
        `ERR_NO_PUBLISHABLE_CHANGES` — an empty candidate set is an error, not a
        note with an empty body and a zero score."

        Design: Corner/cross_cutting_complexity_layers/release_note_create_with_stale_doc_set_version_rejected
        """
        set_clock(CLOCK)
        bundle = published_topic_context()
        feature_key = read_plan_item(bundle["plan_item_id"])["feature_key"]
        record = create_change_record(
            bundle["train_id"], severity="MINOR", category="FIX", affected_component=feature_key
        )
        editorial_pass(record["id"], customer_facing_text=APPROVED_TEXT)
        stale_version = read_doc_set_version(bundle["doc_set_id"])["version"]
        first_note = create_release_note(bundle["doc_set_id"], stale_version)
        publish_release_note(first_note["id"])
        validate_error(
            api.create_release_note(
                create_release_note_payload(bundle["doc_set_id"], stale_version),
                docs_lead_headers,
            ),
            ApiErrorId.STALE_DOC_SET_VERSION,
            412,
        )

        fresh_version = read_doc_set_version(bundle["doc_set_id"])["version"]
        response = api.create_release_note(
            create_release_note_payload(bundle["doc_set_id"], fresh_version), docs_lead_headers
        )
        validate_error(response, ApiErrorId.NO_PUBLISHABLE_CHANGES, 409)

        _rows, meta = validate_paginated(
            api.list_release_notes(docs_lead_headers, {"doc_set_version_id": bundle["doc_set_id"]})
        )
        assert meta["total_count"] == 1
        assert read_doc_set_version(bundle["doc_set_id"])["version"] == fresh_version


class TestPublicationGates:
    """Publishing a compiled document — a release note or a deprecation notice — is
    gated on its own state, and on the calendar in the deprecation case."""

    def test_a_superseded_note_and_an_already_published_note_report_different_gates(
        self, api, docs_lead_headers
    ):
        """One recompilation produces both refusals from the same documentation set.

        PRD §3.7: "The note's `status` must be `COMPILED`: an already published
        note is refused with `ERR_RELEASE_NOTE_ALREADY_PUBLISHED`, and a note
        that a later compilation superseded is refused with
        `ERR_RELEASE_NOTE_SUPERSEDED`."

        PRD §3.7: "On success, `coverage_factor_final` and `impact_score_final`
        are computed with the final variant, `published_at` is stamped from the
        logical clock, and every included change record moves from
        `EDITORIALLY_APPROVED` to `PUBLISHED`."

        Design: Corner/errors/release_note_and_deprecation_publish_gates_rejected
        """
        set_clock(CLOCK)
        bundle = superseded_release_note_context()
        assert read_release_note(bundle["first_release_note_id"])["status"] == "SUPERSEDED"

        validate_error(
            api.publish_release_note(bundle["first_release_note_id"], {}, docs_lead_headers),
            ApiErrorId.RELEASE_NOTE_SUPERSEDED,
            409,
        )
        published = validate_success(
            api.publish_release_note(bundle["second_release_note_id"], {}, docs_lead_headers)
        )
        assert published["status"] == "PUBLISHED"
        record_after_publication = read_change_record(bundle["change_record_ids"][0])
        assert record_after_publication["state"] == "PUBLISHED"

        validate_error(
            api.publish_release_note(bundle["second_release_note_id"], {}, docs_lead_headers),
            ApiErrorId.RELEASE_NOTE_ALREADY_PUBLISHED,
            409,
        )

        unchanged = read_release_note(bundle["second_release_note_id"])
        assert unchanged["status"] == "PUBLISHED"
        assert instants_equal(unchanged["published_at"], published["published_at"])
        assert unchanged["version"] == published["version"]
        assert read_change_record(bundle["change_record_ids"][0])["version"] == (
            record_after_publication["version"]
        ), "the refused second publish must not move the record again"
        assert read_release_note(bundle["first_release_note_id"])["published_at"] is None

    def test_a_deprecation_notice_is_gated_first_on_the_calendar_then_on_its_state(
        self, api, docs_lead_headers
    ):
        """Before the announcement day the notice is refused; afterwards, only once.

        PRD §3.9: "Its `status` must be `DRAFTED`; a notice that is `PUBLISHED`
        or `RETIRED` is refused with
        `ERR_DEPRECATION_NOTICE_ALREADY_PUBLISHED`."

        PRD §3.9: "The logical clock's date must have reached or passed
        `announce_date`, else `ERR_ANNOUNCE_DATE_NOT_REACHED` — customers cannot
        be told before the announcement day."

        PRD §3.9: "Publication moves the notice to `PUBLISHED` and stamps
        `published_at` from the logical clock."

        Design: Corner/errors/release_note_and_deprecation_publish_gates_rejected
        """
        set_clock(CLOCK)
        bundle = deprecation_notice_context(
            notice_overrides={
                "severity_tier": "MINOR",
                "announce_date": "2026-09-15",
                "deprecated_date": "2026-09-20",
                "removal_date": "2026-12-20",
            }
        )
        drafted = bundle["deprecation_notice"]
        assert drafted["status"] == "DRAFTED"
        assert drafted["published_at"] is None

        validate_error(
            api.publish_deprecation_notice(bundle["deprecation_notice_id"], {}, docs_lead_headers),
            ApiErrorId.ANNOUNCE_DATE_NOT_REACHED,
            409,
        )
        still_drafted = read_deprecation_notice(bundle["deprecation_notice_id"])
        assert still_drafted["status"] == "DRAFTED"
        assert still_drafted["published_at"] is None
        assert still_drafted["version"] == drafted["version"]

        set_clock_date("2026-09-15")
        published = validate_success(
            api.publish_deprecation_notice(bundle["deprecation_notice_id"], {}, docs_lead_headers)
        )
        assert published["status"] == "PUBLISHED"
        assert instants_equal(published["published_at"], "2026-09-15T00:00:00Z")

        validate_error(
            api.publish_deprecation_notice(bundle["deprecation_notice_id"], {}, docs_lead_headers),
            ApiErrorId.DEPRECATION_NOTICE_ALREADY_PUBLISHED,
            409,
        )
        unchanged = read_deprecation_notice(bundle["deprecation_notice_id"])
        assert unchanged["status"] == "PUBLISHED"
        assert instants_equal(unchanged["published_at"], published["published_at"])
        assert unchanged["version"] == published["version"]
