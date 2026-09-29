"""Arithmetic that has to land on an exact figure, and on an exact instant."""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as W
from test_helpers import make_reporter_headers


class TestCorrectionResponseDeadline:
    """The deadline pinned at intake, from the band and the submitter."""

    def test_a_severe_subject_complaint_shortens_a_seventy_two_hour_window_to_six(
        self, api, desk
    ):
        """Raw 18 bands ``SEVERE``, scores 21 and leaves a six-hour fuse.

        PRD §3.6: "Start from the error category's weight: `IDENTIFICATION` is
        worth 8 points, `FACTUAL` 6, `QUOTE` 5, `NUMERIC` 4 and `CONTEXT` 3. Add 4
        points when the subject flag is set and nothing when it is not. Add a
        reach component: 6 points when the reach is 100,000 or more", banded so
        that it is "`SEVERE` when raw is 16 or more", with a stored score adding
        "3 points for `SEVERE`". PRD §3.6 then pins the deadline: "Take the owning
        newsroom's `correction_response_sla_hours` as it stands at that moment and
        scale it by a factor read from the *provisional* band: 1.0 for `TRIVIAL`,
        1.0 for `MINOR`, 0.5 for `MAJOR` and 0.25 for `SEVERE`", then "subtract 12
        hours when `submitter_type` is `SUBJECT`", then "take whichever is larger,
        the resulting figure or a floor of 4 hours."

        Design: Corner/calculations/severe_subject_correction_due_in_six_hours_from_seventy_two_hour_sla
        """
        assert desk.newsroom["correction_response_sla_hours"] == C.SLA_HOURS_DEFAULT
        story = W.open_story(api, desk, "Named in error")

        response = api.create_correction_request(
            F.correction_request_payload(
                story["id"],
                submitter_type=C.SUBMITTER_SUBJECT,
                submitter_email="subject@example.test",
                claim_text="I am not the person described in paragraph four.",
                claimed_error_category=C.CATEGORY_IDENTIFICATION,
                reader_reported_reach=120000,
                subject_named=True,
            ),
            desk.public_editor_headers,
        )

        request = validate_success(response, 201)

        A.assert_provisional_severity(request, 21, C.BAND_SEVERE)
        A.assert_instant_equals(
            request["response_due_at"], "2026-08-01T06:00:00.000Z"
        )
        assert request["breach_flag"] is False
        assert request["status"] == C.CORRECTION_INTAKE

    def test_the_four_hour_floor_rescues_a_deadline_the_subject_bump_drove_negative(
        self, api
    ):
        """Eight hours minus twelve is clamped, not stamped in the past.

        PRD §3.6: the raw figure bands "`MINOR` when raw is 6 or more but below
        11", whose scale factor is "1.0 for `MINOR`", after which the desk must
        "apply the submitter bump: subtract 12 hours when `submitter_type` is
        `SUBJECT`" and "Finally take whichever is larger, the resulting figure or a
        floor of 4 hours." PRD §3.1 supplies the window itself:
        "`correction_response_sla_hours` is the base window, in hours, that the
        desk gives itself to answer a complaint; it defaults to 72 and must fall
        between 1 and 336 inclusive".

        Design: Corner/calculations/minimum_due_hours_floor_overrides_negative_subject_bump
        """
        desk = W.build_desk(api, name="Rapid Desk", correction_response_sla_hours=8)
        assert desk.newsroom["correction_response_sla_hours"] == 8
        story = W.open_story(api, desk, "Context missing from the second half")

        response = api.create_correction_request(
            F.correction_request_payload(
                story["id"],
                submitter_type=C.SUBMITTER_SUBJECT,
                submitter_email="subject@example.test",
                claim_text="The passage omits the context of my remark.",
                claimed_error_category=C.CATEGORY_CONTEXT,
                reader_reported_reach=0,
                subject_named=True,
            ),
            desk.public_editor_headers,
        )

        request = validate_success(response, 201)

        A.assert_provisional_severity(request, 8, C.BAND_MINOR)
        A.assert_instant_equals(
            request["response_due_at"], "2026-08-01T04:00:00.000Z"
        )
        assert request["breach_flag"] is False

    def test_the_breach_flag_and_the_desk_summary_agree_once_the_clock_passes_it(
        self, api, desk
    ):
        """The deadline stays put; only the reading of it changes.

        PRD §3.6: "`breach_flag` is evaluated on read against the current logical
        clock: it is true when the clock now reads strictly later than
        `response_due_at` **and** the request's `status` is `INTAKE`,
        `INVESTIGATING` or `AWAITING_SUBJECT`." PRD §3.6 also holds the deadline
        still: "The deadline is pinned once and never recomputed, so a band that
        changes at adjudication never moves it." PRD §3.1 defines the desk-wide
        reconciliation: the summary returns "an `open_correction_request_count`
        aggregating the newsroom's unresolved complaints, and a
        `breached_correction_count` giving the number of those complaints whose
        response deadline has already passed as measured against the logical
        clock."

        Design: Corner/calculations/breached_correction_count_reconciles_with_per_request_breach_flag
        """
        story = W.open_story(api, desk, "Named in error")
        request = W.file_correction(
            api,
            desk,
            story["id"],
            submitter_type=C.SUBMITTER_SUBJECT,
            submitter_email="subject@example.test",
            claim_text="I am not the person described in paragraph four.",
            claimed_error_category=C.CATEGORY_IDENTIFICATION,
            reader_reported_reach=120000,
            subject_named=True,
        )
        A.assert_instant_equals(
            request["response_due_at"], "2026-08-01T06:00:00.000Z"
        )

        W.set_clock(api, desk, "2026-08-01T07:00:00Z")

        breached = W.read_correction_request(api, desk, request["id"])
        assert breached["breach_flag"] is True
        A.assert_instant_equals(
            breached["response_due_at"], "2026-08-01T06:00:00.000Z"
        )
        assert breached["status"] == C.CORRECTION_INTAKE

        summary = W.read_summary(api, desk)
        assert summary["breached_correction_count"] == 1
        assert summary["open_correction_request_count"] == 1


class TestRiskIndexInputSet:
    """Which source rows the sourcing base is allowed to see."""

    def test_only_the_approved_source_prices_the_base(self, api, desk):
        """One approved, one denied and one undecided source score four.

        PRD §3.2: "Count the story's anonymous-source approvals whose `status` is
        `APPROVED` and whose `harm_risk` is `SEVERE`, then take the smaller of
        that count and 3. Multiply the result by 4." PRD §3.2 then excludes the
        rest: "Approvals in `REQUESTED`, `DENIED` or `REVOKED` contribute nothing
        to this base; a source at `LOW` harm risk contributes nothing either,
        however many of them there are." The declared exposure adds "three points
        for every potentially defamatory assertion counted in
        `defamation_claim_count` plus two points for every identifiable private
        individual counted in `privacy_subject_count`", and PRD §3.2 leaves the
        multiplier alone because "otherwise the multiplier is 1.00 and the
        subtotal passes through unchanged."

        Design: Corner/calculations/risk_index_counts_only_approved_sources_not_requested_or_denied
        """
        story = W.open_story(
            api,
            desk,
            "Three sources, one decision",
            defamation_claim_count=1,
            privacy_subject_count=1,
        )
        approved = W.request_source(
            api,
            desk,
            story["id"],
            source_alias="clerk-a",
            source_category=C.SOURCE_CATEGORY_GOVERNMENT,
            harm_risk=C.HARM_SEVERE,
            corroboration_count=2,
            justification_text="Direct custodian of the disputed ledger.",
        )
        denied = W.request_source(
            api,
            desk,
            story["id"],
            source_alias="clerk-b",
            source_category=C.SOURCE_CATEGORY_GOVERNMENT,
            harm_risk=C.HARM_SEVERE,
            corroboration_count=2,
            justification_text="Second custodian whose account did not hold up.",
        )
        undecided = W.request_source(
            api,
            desk,
            story["id"],
            source_alias="vendor-c",
            source_category=C.SOURCE_CATEGORY_CORPORATE,
            harm_risk=C.HARM_ELEVATED,
            corroboration_count=1,
            justification_text="Vendor with sight of the invoices in question.",
        )
        W.approve_source(api, desk, approved["id"])
        W.deny_source(api, desk, denied["id"])

        priced = get_success_data(api.get_story(story["id"], desk.sed_headers))

        A.assert_story_counters(priced, approved_sources=1, revoked_sources=0)
        A.assert_risk_figures(priced, estimate=9.00, tier=C.TIER_STANDARD)

        A.assert_total_count(
            api.list_story_source_approvals(story["id"], desk.sed_headers), 3
        )
        still_open = get_success_data(
            api.get_source_approval(undecided["id"], desk.sed_headers)
        )
        assert still_open["status"] == C.SOURCE_REQUESTED


class TestTrainingComplianceIndexSerialization:
    """A ratio of one half, published to the desk as a percentage."""

    def test_one_of_two_required_modules_reads_back_as_fifty_to_two_decimals(
        self, api, bootstrap_exec_headers, public_editor_headers
    ):
        """A cohort of one, holding half of what it owes.

        PRD §3.8: "for each journalist in the cohort, divide their
        `completed_required_module_count` by the number of codes in
        `required_module_codes` and round that individual ratio half up to 2
        decimal places. Second, add those already-rounded ratios together, divide
        by the number of journalists in the cohort, multiply by 100, and round
        half up to 2 decimal places again." PRD §3.8 names the cohort: "The cohort
        is every journalist of the newsroom, taken in `created_at` ascending
        order". PRD §3.1 lists what else the summary reports:
        "`standards_posture`, `open_high_severity_count`,
        `training_compliance_index`, a `published_story_count` of the newsroom's
        stories that have reached publication, an `open_correction_request_count`
        aggregating the newsroom's unresolved complaints, and a
        `breached_correction_count`".

        Design: Corner/calculations/training_compliance_index_serialized_with_exactly_two_decimals
        """
        newsroom = W.bootstrap_newsroom(
            api, required_module_codes=[C.MODULE_SOURCING, C.MODULE_CORRECTIONS]
        )
        reporter = W.add_journalist(
            api,
            newsroom["id"],
            "Rae Lindqvist",
            "rae@ledger.test",
            C.TITLE_REPORTER,
            bootstrap_exec_headers,
        )
        get_success_data(
            api.create_training_record(
                F.training_record_payload(
                    reporter["id"], C.MODULE_SOURCING, "CS-2024-11"
                ),
                make_reporter_headers(reporter["id"]),
            )
        )

        summary = get_success_data(
            api.get_standards_summary(newsroom["id"], public_editor_headers)
        )

        A.assert_decimal_equals(summary["training_compliance_index"], 50.00)
        assert summary["standards_posture"] == C.POSTURE_OPEN
        assert summary["open_high_severity_count"] == 0
        assert summary["published_story_count"] == 0
        assert summary["breached_correction_count"] == 0
