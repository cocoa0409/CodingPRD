"""Version tokens that go out of date, and reads that never lag behind."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as W


class TestStaleStoryVersionOnSubmission:
    """A complaint filed underneath the reporter invalidates their read."""

    def test_a_submission_on_a_token_a_reader_complaint_overtook_is_refused(
        self, api, desk
    ):
        """The story moved for a reason the reporter never saw.

        PRD §2.8: "That request must carry `expected_story_version`, a required
        field whose value is the `version` the client last observed on the target
        `Story`. If it does not equal the story's current `version`, the
        submission is refused with `ERR_STALE_STORY_VERSION` and HTTP status
        412." PRD §2.8 names the writes that move it: "It is instead a guard on
        the story's version, which every sourcing decision, correction intake and
        risk recomputation advances." PRD §3.6 is the intake that does it here:
        "Intake also increments the story's `open_correction_request_count` and
        advances the story's `version` by one."

        Design: Corner/cross_cutting_layers/review_submission_with_stale_story_version_returns_stale_story_version
        """
        story = W.open_story(api, desk, "Overtaken between read and write")
        stale_version = W.story_version(api, desk, story["id"])

        W.file_correction(
            api,
            desk,
            story["id"],
            submitter_type=C.SUBMITTER_READER,
            submitter_email="reader@example.test",
            claim_text="A name is misspelled in the opening line.",
            claimed_error_category=C.CATEGORY_IDENTIFICATION,
            reader_reported_reach=400,
            subject_named=False,
        )

        response = api.create_review(
            F.review_payload(
                story["id"],
                stale_version,
                high_risk_declared=False,
                submission_note="Submitting on a stale read.",
            ),
            desk.reporter_headers,
        )

        validate_error(response, E.ERR_STALE_STORY_VERSION, 412)

        unmoved = W.read_story(api, desk, story["id"])
        assert unmoved["publication_status"] == C.PUB_DRAFT
        assert unmoved["version"] == stale_version + 1
        A.assert_total_count(
            api.list_story_reviews(story["id"], desk.sed_headers), 0
        )


class TestStaleReviewerVersionOnASecondBooking:
    """Disjoint slots are legal, but the ledger reading is not reusable."""

    def test_the_second_slot_presented_with_the_pre_booking_token_is_refused(
        self, api, desk
    ):
        """No collision, plenty of minutes left, and still 412.

        PRD §2.8: "That request must carry `expected_reviewer_version`, a required
        field whose value is the `version` the client last observed on the target
        `Reviewer`. If it does not equal the reviewer's current `version`, the
        booking is refused with `ERR_STALE_REVIEWER_VERSION` and HTTP status
        412." PRD §2.8 explains why a disjoint slot does not escape it: "Two
        bookings for genuinely disjoint slots are both legitimate, so again no
        state precondition covers the case; what invalidates the caller's view is
        that their reading of `reserved_minutes` and `available_minutes` is out of
        date, and every booking, cancellation and cascade completion bumps the
        reviewer's `version`." PRD §3.4 fixes the ledger the first booking left:
        "On acceptance, `reserved_minutes` rises and `available_minutes` falls by
        the slot's duration, and the reviewer's `version` is incremented by one."

        Design: Corner/cross_cutting_layers/second_booking_with_stale_reviewer_version_returns_stale_reviewer_version
        """
        reviewer = W.add_reviewer(
            api, desk, full_name="Tomas Neri", weekly_capacity_minutes=480
        )
        stale_version = reviewer["version"]
        story = W.open_story(api, desk, "Two bookings, one token")
        review = W.submit_review(api, desk, story["id"], high_risk_declared=False)

        W.book_slot(
            api,
            desk,
            review["id"],
            reviewer,
            "2026-08-06T09:00:00Z",
            "2026-08-06T10:00:00Z",
            expected_reviewer_version=stale_version,
        )

        response = api.create_assignment(
            F.assignment_payload(
                review["id"],
                reviewer["id"],
                "2026-08-06T14:00:00Z",
                "2026-08-06T15:00:00Z",
                stale_version,
            ),
            desk.sed_headers,
        )

        validate_error(response, E.ERR_STALE_REVIEWER_VERSION, 412)

        ledger = W.read_reviewer(api, desk, reviewer["id"])
        A.assert_minute_ledger(ledger, 60, 420)
        assert ledger["version"] == stale_version + 1
        A.assert_total_count(
            api.list_assignments(desk.sed_headers, {"reviewer_id": reviewer["id"]}),
            1,
        )


class TestStoryVersionAdvancesOnWritesTheClientNeverIssued:
    """The token moves for the desk's writes, not only the reporter's."""

    def test_a_source_decision_and_a_submission_each_add_exactly_one(
        self, api, desk
    ):
        """Two hops, and the token read at creation is two behind at the end.

        PRD §3.2: on an approval "the server stores `decided_by_user_id` and
        `decided_at`, increments the story's `approved_anonymous_source_count`,
        recomputes the story's `risk_index_estimate` and `risk_tier` — and
        `risk_index_actual` too, when the story has already been published —
        advances the story's `version` by one, and appends an audit event of type
        `SOURCE_APPROVED`." PRD §3.2 prices the approved pool: "Separately, count
        the story's approved approvals whose `harm_risk` is `ELEVATED`, take the
        smaller of that count and 5, and multiply by 2." PRD §3.3 adds the second
        hop: "Opening the round recomputes the story's `risk_index_estimate` and
        advances the story's
        `version` by one." PRD §2.4 fixes the starting point: "`version` is an
        integer that starts at 1 on creation and increments by exactly 1 on every
        mutation."

        Design: Corner/cross_cutting_layers/story_version_increments_on_every_write_that_touches_it
        """
        story = W.open_story(api, desk, "Counting the version bumps")
        creation_version = story["version"]

        W.approved_source(
            api,
            desk,
            story["id"],
            source_alias="permit-clerk",
            harm_risk=C.HARM_ELEVATED,
            corroboration_count=2,
            justification_text="Custodian of the permit ledger for four years.",
        )

        after_decision = validate_success(
            api.get_story(story["id"], desk.reporter_headers)
        )
        assert after_decision["version"] == creation_version + 1
        A.assert_risk_figures(after_decision, estimate=2.00)

        submitted = validate_success(
            api.create_review(
                F.review_payload(
                    story["id"],
                    after_decision["version"],
                    high_risk_declared=False,
                    submission_note="Submitting on a current read.",
                ),
                desk.reporter_headers,
            ),
            201,
        )
        assert submitted["status"] == C.REVIEW_SUBMITTED
        assert (
            W.read_story(api, desk, story["id"])["version"] == creation_version + 2
        )


class TestAdjudicationRespondsWithEverythingItRecomputed:
    """No settling period: the write's own body already carries the new figures."""

    def test_the_adjudication_body_and_the_next_reads_agree_immediately(
        self, api, desk
    ):
        """Raw 12 bands ``MAJOR``, scores 14 and places the notice on top.

        PRD §3.6: "The second run happens at adjudication, from the desk's
        verified account: the category is `adjudicated_error_category`, the reach
        is `verified_reach`, and the subject flag is the request's own
        `subject_named` field." The arithmetic is "`IDENTIFICATION` is worth 8
        points, `FACTUAL` 6, `QUOTE` 5, `NUMERIC` 4 and `CONTEXT` 3. Add 4 points
        when the subject flag is set and nothing when it is not. Add a reach
        component: 6 points when the reach is 100,000 or more, otherwise 4 points
        when it is 10,000 or more, otherwise 2 points when it is 1,000 or more,
        otherwise nothing." PRD §3.6 bands and scores it: "`MAJOR` when raw is 11
        or more but below 16" with "2 points for `MAJOR`", and places the notice:
        "A `CORRECTION` is placed at the `TOP_OF_STORY` when its adjudicated band
        is `MAJOR` or `SEVERE`, and at the `END_OF_STORY` when that band is
        `TRIVIAL` or `MINOR`." PRD §3.6 lists the immediate effects: "the request
        moves to `ADJUDICATED`; `adjudicated_severity_score`,
        `adjudicated_severity_band` and `placement` are computed; the story's
        `standards_status` becomes `CORRECTED`; when the adjudicated band is
        `MAJOR` or `SEVERE` the story's `severe_correction_count` is incremented
        and its `risk_index_actual` recomputed; because that counter moved, the
        newsroom's `open_high_severity_count` is re-derived and
        `standards_posture` follows", and "an audit event of type
        `CORRECTION_ADJUDICATED` is appended". The complaint stays on the story's
        open tally, because PRD §3.6 defers that decrement to the notice: on
        resolution "the story's `open_correction_request_count` is decremented and
        its `version` advances by one". PRD §3.6 also pins the deadline once, at
        24 hours, from the same provisional `MAJOR` band: "Take the owning
        newsroom's `correction_response_sla_hours` as it stands at that moment and
        scale it by a factor read from the *provisional* band: 1.0 for `TRIVIAL`,
        1.0 for `MINOR`, 0.5 for `MAJOR` and 0.25 for `SEVERE` — the graver the
        apparent error, the shorter the fuse." "Then apply the submitter bump:
        subtract 12 hours when `submitter_type` is `SUBJECT`, add nothing for
        `READER`, and add 24 hours for `INTERNAL`, on the reasoning that a wronged
        subject waits least and an internal note waits most."

        Design: Corner/consistency_model/adjudication_response_already_carries_every_recomputed_field
        """
        story = W.open_story(api, desk, "A misidentified subject")
        request = W.investigating_correction(
            api,
            desk,
            story["id"],
            submitter_type=C.SUBMITTER_SUBJECT,
            submitter_email="subject@example.test",
            claim_text="The photograph is not of me.",
            claimed_error_category=C.CATEGORY_IDENTIFICATION,
            reader_reported_reach=900,
            subject_named=True,
        )

        adjudicated = validate_success(
            api.adjudicate_correction_request(
                request["id"],
                F.adjudication_payload(
                    C.OUTCOME_CORRECTION,
                    C.CATEGORY_IDENTIFICATION,
                    900,
                    notice_text=(
                        "An earlier version used a photograph of the wrong person."
                    ),
                ),
                desk.sed_headers,
            )
        )

        assert adjudicated["status"] == C.CORRECTION_ADJUDICATED
        A.assert_adjudicated_severity(adjudicated, 14, C.BAND_MAJOR)
        assert adjudicated["placement"] == C.PLACEMENT_TOP_OF_STORY
        A.assert_instant_equals(
            adjudicated["response_due_at"], "2026-08-02T00:00:00.000Z"
        )

        reread = W.read_story(api, desk, story["id"])
        A.assert_story_counters(reread, severe_corrections=1, open_corrections=1)
        assert reread["standards_status"] == C.STD_CORRECTED

        summary = W.read_summary(api, desk)
        assert summary["open_high_severity_count"] == 1
        assert summary["standards_posture"] == C.POSTURE_OPEN

        A.assert_total_count(
            api.list_audit_events(
                desk.newsroom_id,
                desk.exec_headers,
                {"event_type": C.EVENT_CORRECTION_ADJUDICATED},
            ),
            1,
        )
