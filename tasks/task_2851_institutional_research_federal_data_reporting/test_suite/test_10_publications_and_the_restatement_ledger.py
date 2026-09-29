"""Dashboard publication: the half-open window, the restatement ledger and the two rejection homes."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    assert_common_fields,
    assert_instant_equals,
    assert_null,
    assert_publication_ledger,
    assert_restatement,
    assert_version,
    constants as K,
    factories as f,
    fixtures as fx,
)

COMPLETIONS_METRICS = (
    {
        "metric_key": K.METRIC_TOTAL_COMPLETIONS,
        "reported_value": 250,
        "prior_year_value": 250,
        "source_field_path": "sis.degrees.awarded_total",
    },
)
MISSING_DEGREES = "Twenty-five late-conferred degrees appear to be missing from the extract."
NEXT_YEAR_REASON = "The twenty-five degrees belong to the following collection year."
CONFIRMED_BEFORE_CENSUS = (
    "Registrar confirmed the twenty-five degrees were conferred before the census date."
)
GRADUATE_SCHOOL_CLAIM = (
    "A further twenty-five degrees were reported by the graduate school after publication."
)
UNRECONCILED_REASON = "Graduate school figures are not reconciled to the certified component."


class TestEffectiveWindowMustBeStrictlyPositive:
    """A half-open window that ends where it starts would publish nothing at all."""

    def test_a_zero_length_window_is_refused_while_one_day_is_accepted(self, api, analyst):
        """The refused publication leaves no row behind for the component at all.

        PRD 3.7: "When `effective_to` is supplied it must be strictly after `effective_from`, since a
        zero-length half-open window would publish nothing at all; a violation reports
        `ERR_INVALID_EFFECTIVE_WINDOW`."

        PRD 3.7: "The row is created at `publication_status` `PUBLISHED`, with `original_value` set
        equal to the supplied `published_value` and never written again, `net_applied_delta` at 0,
        `restatement_count` at 0, `published_by_user_id` recording the publishing analyst,
        `withdrawal_reason` null and `version` 1."

        Design: Corner/validations/corner_val_publication_effective_window_must_be_strictly_positive
        """
        scenario = fx.frozen_cycle(api, checksum="c1d2e3f4a5b60154")

        empty_window = api.create_publication(
            f.make_publication_payload(
                scenario.component_id,
                metric_key="TOTAL_HEADCOUNT_FALL",
                published_value=1000.0,
                effective_from=K.EFFECTIVE_FROM,
                effective_to=K.EFFECTIVE_FROM,
            ),
            analyst,
        )
        validate_error(empty_window, ApiErrorId.INVALID_EFFECTIVE_WINDOW, 422)

        rows, meta = validate_paginated(
            api.list_publications(analyst, component_id=scenario.component_id)
        )
        assert meta["total_count"] == 0
        assert rows == []

        published = validate_success(
            api.create_publication(
                f.make_publication_payload(
                    scenario.component_id,
                    metric_key="TOTAL_HEADCOUNT_FALL",
                    published_value=1000.0,
                    effective_from=K.EFFECTIVE_FROM,
                    effective_to="2026-11-02T00:00:00Z",
                ),
                analyst,
            ),
            201,
        )
        assert_instant_equals(
            published["effective_to"], "2026-11-02T00:00:00.000Z", "publication.effective_to"
        )
        assert_publication_ledger(
            published,
            published_value=1000.0,
            original_value=1000.0,
            net_applied_delta=0,
            restatement_count=0,
            publication_status=K.PUBLICATION_PUBLISHED,
        )
        assert published["published_by_user_id"] == "analyst-1"
        assert_null(published["withdrawal_reason"], "publication.withdrawal_reason")
        assert_version(published, 1, "publication")
        assert_common_fields(published, "publication")


class TestRejectionRestoresThePriorPublicationState:
    """The same rejection endpoint returns the figure to PUBLISHED or to RESTATED."""

    def test_the_first_rejection_lands_on_published_and_a_later_one_lands_on_restated(
        self, api, analyst, director
    ):
        """restatement_count decides the destination, and a rejection never touches the ledger.

        PRD 3.7: "The publication's own destination then depends on its history, and this is the
        compensation branch: once no other request of that publication remains at `SUBMITTED`, a
        publication whose `restatement_count` is exactly 0 returns to `PUBLISHED`, restoring the state
        it held before the request was ever filed, while a publication whose `restatement_count` is at
        least 1 returns to `RESTATED`, because a previously applied restatement still stands."

        PRD 3.7: "Either way the publication's `version` is incremented and neither `published_value`
        nor `net_applied_delta` moves: a rejected restatement contributes nothing to the ledger and
        does not increment `restatement_count`."

        Design: Corner/state_machines/corner_sm_restatement_rejection_returns_the_publication_to_its_prior_state
        """
        scenario = fx.published_figure(
            api,
            domain=K.DOMAIN_COMPLETIONS,
            metric_key="COMPLETIONS_TOTAL_FALL",
            published_value=250.0,
            metrics=COMPLETIONS_METRICS,
            record_count=250,
            checksum="c1d2e3f4a5b60126",
        )
        publication_id = scenario.publication_id

        first = fx.file_restatement(api, scenario, 275.0, justification=MISSING_DEGREES)
        assert_restatement(
            first,
            status=K.RESTATEMENT_SUBMITTED,
            origin=K.ORIGIN_ANALYST,
            requested_by_user_id="analyst-1",
            baseline_value=250.0,
            delta_pct=10.00,
            public_notice_required=True,
        )
        pending = validate_success(api.get_publication(publication_id, analyst))
        assert pending["publication_status"] == K.PUBLICATION_RESTATEMENT_PENDING
        assert_version(pending, 2, "publication")

        rejected = validate_success(
            api.reject_restatement(
                first["id"], f.make_restatement_rejection_payload(NEXT_YEAR_REASON), director
            )
        )
        assert_restatement(rejected, status=K.RESTATEMENT_REJECTED)
        assert rejected["rejection_reason"] == NEXT_YEAR_REASON
        assert rejected["approved_by_user_id"] == "director-1"

        restored = validate_success(api.get_publication(publication_id, analyst))
        assert_publication_ledger(
            restored,
            published_value=250.0,
            original_value=250.0,
            net_applied_delta=0,
            restatement_count=0,
            publication_status=K.PUBLICATION_PUBLISHED,
        )
        assert_version(restored, 3, "publication")

        second = fx.file_restatement(api, scenario, 275.0, justification=CONFIRMED_BEFORE_CENSUS)
        applied = validate_success(
            api.approve_restatement(
                second["id"], director, f.make_restatement_approval_payload("PN-2027-011")
            )
        )
        assert_restatement(applied, status=K.RESTATEMENT_APPLIED)

        restated = validate_success(api.get_publication(publication_id, analyst))
        assert_publication_ledger(
            restated,
            published_value=275.0,
            original_value=250.0,
            net_applied_delta=25.0,
            restatement_count=1,
            publication_status=K.PUBLICATION_RESTATED,
        )

        third = fx.file_restatement(api, scenario, 300.0, justification=GRADUATE_SCHOOL_CLAIM)
        assert_restatement(third, baseline_value=275.0, delta_pct=9.09)

        validate_success(
            api.reject_restatement(
                third["id"], f.make_restatement_rejection_payload(UNRECONCILED_REASON), director
            )
        )
        back_to_restated = validate_success(api.get_publication(publication_id, analyst))
        assert_publication_ledger(
            back_to_restated,
            published_value=275.0,
            original_value=250.0,
            net_applied_delta=25.0,
            restatement_count=1,
            publication_status=K.PUBLICATION_RESTATED,
        )

        rows, meta = validate_paginated(
            api.list_restatements(
                analyst, publication_id=publication_id, status=K.RESTATEMENT_REJECTED
            )
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2


RESIDENCY_RECLASSIFICATION = (
    "A late residency reclassification added twenty students to the census file."
)
SECOND_PASS_RECONCILIATION = (
    "Second pass reconciliation of the same census extract against the SIS."
)
HEADCOUNT_METRICS_1125 = (
    {
        "metric_key": K.METRIC_TOTAL_HEADCOUNT,
        "reported_value": 1125,
        "prior_year_value": 1125,
        "source_field_path": "sis.enrollment.headcount",
    },
)
FIVE_DOUBLE_COUNTED = "Five students were double counted across two majors."
SEVEN_DOUBLE_COUNTED = "Seven students were double counted across two majors."
UNRECONCILED_DUPLICATES = "The duplicate list was not reconciled against the census file."


class TestPublicNoticeAndRejectionReasonObligations:
    """Materiality is fixed at filing, and both verdicts have their own text obligation."""

    def test_the_material_restatement_demands_a_notice_and_its_immaterial_successor_does_not(
        self, api, analyst, director
    ):
        """A delta of exactly 2.00 needs the reference; 1.50 against the new baseline does not.

        PRD 3.7: "The comparison is inclusive, so a delta of exactly 2.00 requires a public notice."

        PRD 3.7: "It requires the request to be `SUBMITTED` (else `ERR_INVALID_RESTATEMENT_STATE`),
        its parent publication to be `RESTATEMENT_PENDING` (else `ERR_INVALID_PUBLICATION_STATE`), the
        acting `X-User-ID` to differ from `requested_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES` — a
        request whose requester is the literal `SYSTEM` can never collide), and, when
        `public_notice_required` is true, a `public_notice_reference` of 3 to 120 characters, absent
        which the approval reports `ERR_PUBLIC_NOTICE_REQUIRED`."

        PRD 3.7: "**Rejecting a restatement** drives the request `SUBMITTED → REJECTED` and requires a
        `rejection_reason` of 10 to 500 characters, absent which it reports
        `ERR_REJECTION_REASON_REQUIRED`, together with the same segregation-of-duties separation from
        `requested_by_user_id`."

        Design: Corner/validations/corner_val_material_restatement_needs_a_public_notice_and_a_rejection_needs_a_reason
        """
        scenario = fx.published_figure(
            api,
            metric_key="TOTAL_HEADCOUNT_FALL",
            published_value=1000.0,
            checksum="c1d2e3f4a5b60143",
        )
        publication_id = scenario.publication_id

        material = fx.file_restatement(
            api, scenario, 1020.0, justification=RESIDENCY_RECLASSIFICATION
        )
        assert_restatement(
            material, baseline_value=1000.0, delta_pct=2.00, public_notice_required=True
        )

        no_reference = api.approve_restatement(material["id"], director)
        validate_error(no_reference, ApiErrorId.PUBLIC_NOTICE_REQUIRED, 422)
        held = validate_success(api.get_restatement(material["id"], analyst))
        assert_restatement(held, status=K.RESTATEMENT_SUBMITTED)

        too_short = api.reject_restatement(
            material["id"], f.make_restatement_rejection_payload("no"), director
        )
        validate_error(too_short, ApiErrorId.REJECTION_REASON_REQUIRED, 422)
        still_live = validate_success(api.get_restatement(material["id"], analyst))
        assert_restatement(still_live, status=K.RESTATEMENT_SUBMITTED)
        assert_null(still_live["rejection_reason"], "restatement.rejection_reason")

        applied = validate_success(
            api.approve_restatement(
                material["id"], director, f.make_restatement_approval_payload("IR-NOTICE-2027-004")
            )
        )
        assert_restatement(applied, status=K.RESTATEMENT_APPLIED)
        assert applied["public_notice_reference"] == "IR-NOTICE-2027-004"
        assert applied["approved_by_user_id"] == "director-1"

        restated = validate_success(api.get_publication(publication_id, analyst))
        assert_publication_ledger(
            restated,
            published_value=1020.0,
            original_value=1000.0,
            net_applied_delta=20.0,
            restatement_count=1,
            publication_status=K.PUBLICATION_RESTATED,
        )
        assert_version(restated, 3, "publication")

        immaterial = fx.file_restatement(
            api, scenario, 1035.3, justification=SECOND_PASS_RECONCILIATION
        )
        assert_restatement(
            immaterial, baseline_value=1020.0, delta_pct=1.50, public_notice_required=False
        )

        no_notice_needed = validate_success(api.approve_restatement(immaterial["id"], director))
        assert_restatement(no_notice_needed, status=K.RESTATEMENT_APPLIED)
        assert_null(
            no_notice_needed["public_notice_reference"], "restatement.public_notice_reference"
        )

        final = validate_success(api.get_publication(publication_id, analyst))
        assert_publication_ledger(
            final,
            published_value=1035.3,
            original_value=1000.0,
            net_applied_delta=35.3,
            restatement_count=2,
            publication_status=K.PUBLICATION_RESTATED,
        )
        assert_version(final, 5, "publication")


class TestStalePublicationVersionSurvivesTheRoundTrip:
    """A file-and-reject round trip ends where it started but three versions on."""

    def test_the_client_holding_the_original_version_is_stale_though_the_status_matches(
        self, api, analyst, director
    ):
        """The refused filing writes no request row and leaves the ledger untouched.

        PRD 2.8: "If `expected_publication_version` does not equal the publication's current
        `version`, the request is rejected with `ERR_STALE_PUBLICATION_VERSION` and HTTP 412."

        PRD 3.7: "**Filing a restatement request** is how a published figure is challenged, and it is
        guarded by optimistic concurrency: the request carries the mandatory
        `expected_publication_version`, and a mismatch against the publication's current `version`
        reports `ERR_STALE_PUBLICATION_VERSION`."

        Design: Corner/cross_cutting_complexity_layers/corner_layer_stale_expected_publication_version_is_refused_after_a_rejected_restatement
        """
        scenario = fx.published_figure(
            api,
            metric_key=K.METRIC_TOTAL_HEADCOUNT,
            published_value=1125,
            metrics=HEADCOUNT_METRICS_1125,
            record_count=1125,
            checksum="c1d2e3f4a5b60171",
        )
        publication_id = scenario.publication_id
        assert_version(scenario.publication, 1, "publication")

        first = fx.file_restatement(
            api,
            scenario,
            1120,
            expected_publication_version=1,
            justification=FIVE_DOUBLE_COUNTED,
        )
        pending = validate_success(api.get_publication(publication_id, analyst))
        assert pending["publication_status"] == K.PUBLICATION_RESTATEMENT_PENDING
        assert_version(pending, 2, "publication")

        validate_success(
            api.reject_restatement(
                first["id"],
                f.make_restatement_rejection_payload(UNRECONCILED_DUPLICATES),
                director,
            )
        )
        reopened = validate_success(api.get_publication(publication_id, analyst))
        assert reopened["publication_status"] == K.PUBLICATION_PUBLISHED
        assert_version(reopened, 3, "publication")
        assert_publication_ledger(reopened, published_value=1125, restatement_count=0)

        stale = api.file_restatement(
            publication_id,
            f.make_restatement_payload(1118, 1, justification=SEVEN_DOUBLE_COUNTED),
            analyst,
        )
        validate_error(stale, ApiErrorId.STALE_PUBLICATION_VERSION, 412)

        rows, meta = validate_paginated(
            api.list_restatements(analyst, publication_id=publication_id)
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]

        untouched = validate_success(api.get_publication(publication_id, analyst))
        assert_version(untouched, 3, "publication")
        assert_publication_ledger(
            untouched,
            published_value=1125,
            restatement_count=0,
            publication_status=K.PUBLICATION_PUBLISHED,
        )

        fresh = validate_success(
            api.file_restatement(
                publication_id,
                f.make_restatement_payload(1118, 3, justification=SEVEN_DOUBLE_COUNTED),
                analyst,
            ),
            201,
        )
        assert_restatement(
            fresh, baseline_value=1125, delta_pct=0.62, public_notice_required=False
        )

        advanced = validate_success(api.get_publication(publication_id, analyst))
        assert advanced["publication_status"] == K.PUBLICATION_RESTATEMENT_PENDING
        assert_version(advanced, 4, "publication")

        terminal = validate_success(api.get_restatement(first["id"], analyst))
        assert_restatement(terminal, status=K.RESTATEMENT_REJECTED)


WITHDRAWAL_REASON = "Superseded by the corrected fall headcount series."
OMITTED_DEGREES = (
    "Twenty-five late-conferred degrees were omitted from the original completions extract."
)
REVERT_TO_CERTIFIED = (
    "The twenty-five degrees belong to the following collection year; reverting to the certified "
    "figure."
)
SUMMER_CONFERRALS = "A further five degrees were conferred in the summer session after the reversion."


def _apply_restatement(api, scenario, proposed_value, justification, director, notice_reference):
    """File a restatement as the analyst and approve it as the director, returning both rows."""
    request = fx.file_restatement(api, scenario, proposed_value, justification=justification)
    applied = validate_success(
        api.approve_restatement(
            request["id"], director, f.make_restatement_approval_payload(notice_reference)
        )
    )
    publication = validate_success(
        api.get_publication(scenario.publication_id, director)
    )
    return request, applied, publication


class TestPublicationWindowsShareTheirBoundaryInstant:
    """The half-open geometry makes adjacency legal and an interior window an overlap."""

    @staticmethod
    def _incumbent_over_one_month(api, checksum):
        """A FROZEN cycle whose fall headcount is published over November only."""
        scenario = fx.frozen_cycle(api, checksum=checksum)
        incumbent = fx.publish_metric(
            api,
            scenario,
            metric_key="TOTAL_HEADCOUNT_FALL",
            published_value=1000.0,
            effective_from=K.EFFECTIVE_FROM,
            effective_to=K.EFFECTIVE_TO,
        )
        assert incumbent["publication_status"] == K.PUBLICATION_PUBLISHED
        return scenario, incumbent

    def test_a_successor_starting_at_the_incumbents_end_is_accepted_and_an_interior_window_is_not(
        self, api, analyst, director
    ):
        """Withdrawing the incumbent then frees its exact window for reuse.

        PRD 2.11: "A dashboard figure stops applying at the instant its successor begins, so the two
        may share that instant."

        PRD 3.7: "The new window must not overlap the window of any peer publication of the same
        `component_id` and the same `metric_key` whose `publication_status` is not `WITHDRAWN`, per the
        half-open geometry of §2.11; an overlap reports `ERR_PUBLICATION_WINDOW_OVERLAP`."

        PRD 3.7: "Withdrawn publications are excluded from that occupancy set, so withdrawing a figure
        frees its window for reuse."

        Design: Difficulty/resource_temporal_overlap/publication_half_open_windows_allow_shared_boundary_instant
        """
        scenario, incumbent = self._incumbent_over_one_month(api, "a1b2c3d4e5f60021")

        successor = validate_success(
            api.create_publication(
                f.make_publication_payload(
                    scenario.component_id,
                    metric_key="TOTAL_HEADCOUNT_FALL",
                    published_value=1005.0,
                    effective_from=K.EFFECTIVE_TO,
                ),
                analyst,
            ),
            201,
        )
        assert successor["publication_status"] == K.PUBLICATION_PUBLISHED
        assert_null(successor["effective_to"], "publication.effective_to")
        assert_publication_ledger(successor, published_value=1005.0, original_value=1005.0)

        interior = api.create_publication(
            f.make_publication_payload(
                scenario.component_id,
                metric_key="TOTAL_HEADCOUNT_FALL",
                published_value=1002.0,
                effective_from="2026-11-15T00:00:00Z",
                effective_to="2026-11-20T00:00:00Z",
            ),
            analyst,
        )
        validate_error(interior, ApiErrorId.PUBLICATION_WINDOW_OVERLAP, 409)

        withdrawn = validate_success(
            api.withdraw_publication(
                incumbent["id"], f.make_withdrawal_payload(WITHDRAWAL_REASON), director
            )
        )
        assert withdrawn["publication_status"] == K.PUBLICATION_WITHDRAWN
        assert withdrawn["withdrawal_reason"] == WITHDRAWAL_REASON

        reused = validate_success(
            api.create_publication(
                f.make_publication_payload(
                    scenario.component_id,
                    metric_key="TOTAL_HEADCOUNT_FALL",
                    published_value=1001.0,
                    effective_from=K.EFFECTIVE_FROM,
                    effective_to=K.EFFECTIVE_TO,
                ),
                analyst,
            ),
            201,
        )
        assert reused["publication_status"] == K.PUBLICATION_PUBLISHED
        assert_instant_equals(
            reused["effective_from"], "2026-11-01T00:00:00.000Z", "publication.effective_from"
        )
        assert_instant_equals(
            reused["effective_to"], "2026-12-01T00:00:00.000Z", "publication.effective_to"
        )

        rows, meta = validate_paginated(
            api.list_publications(
                analyst, component_id=scenario.component_id, metric_key="TOTAL_HEADCOUNT_FALL"
            )
        )
        assert meta["total_count"] == 3
        assert len(rows) == 3

    def test_a_predecessor_ending_at_the_incumbents_start_is_accepted_while_a_true_overlap_is_not(
        self, api, analyst
    ):
        """The occupancy set is scoped to one metric_key, so another key may reuse the instant.

        PRD 2.11: "A dashboard publication's effective window, spanning `effective_from` to
        `effective_to`, is a **half-open** instant interval: the start is occupied and the end is not."

        PRD 3.7: "The new window must not overlap the window of any peer publication of the same
        `component_id` and the same `metric_key` whose `publication_status` is not `WITHDRAWN`, per the
        half-open geometry of §2.11; an overlap reports `ERR_PUBLICATION_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/publication_half_open_windows_allow_shared_boundary_instant
        """
        scenario, _incumbent = self._incumbent_over_one_month(api, "a1b2c3d4e5f60024")

        predecessor = validate_success(
            api.create_publication(
                f.make_publication_payload(
                    scenario.component_id,
                    metric_key="TOTAL_HEADCOUNT_FALL",
                    published_value=995.0,
                    effective_from="2026-10-01T00:00:00Z",
                    effective_to=K.EFFECTIVE_FROM,
                ),
                analyst,
            ),
            201,
        )
        assert predecessor["publication_status"] == K.PUBLICATION_PUBLISHED

        straddling = api.create_publication(
            f.make_publication_payload(
                scenario.component_id,
                metric_key="TOTAL_HEADCOUNT_FALL",
                published_value=998.0,
                effective_from="2026-10-15T00:00:00Z",
                effective_to="2026-11-15T00:00:00Z",
            ),
            analyst,
        )
        validate_error(straddling, ApiErrorId.PUBLICATION_WINDOW_OVERLAP, 409)

        other_metric = validate_success(
            api.create_publication(
                f.make_publication_payload(
                    scenario.component_id,
                    metric_key="FTE_ENROLLMENT_FALL",
                    published_value=900.0,
                    effective_from=K.EFFECTIVE_FROM,
                    effective_to=K.EFFECTIVE_TO,
                ),
                analyst,
            ),
            201,
        )
        assert other_metric["publication_status"] == K.PUBLICATION_PUBLISHED

        rows, meta = validate_paginated(
            api.list_publications(
                analyst, component_id=scenario.component_id, metric_key="TOTAL_HEADCOUNT_FALL"
            )
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2


class TestCompensatingRestatementReturnsToTheOriginalValue:
    """The signed ledger walks a figure back while the audit counter only ever climbs."""

    @staticmethod
    def _completions_figure_at_two_fifty(api, checksum):
        """A FROZEN completions cycle publishing 250.0 with a clean ledger."""
        scenario = fx.published_figure(
            api,
            domain=K.DOMAIN_COMPLETIONS,
            metric_key="COMPLETIONS_TOTAL_FALL",
            published_value=250.0,
            metrics=COMPLETIONS_METRICS,
            record_count=250,
            checksum=checksum,
        )
        assert_publication_ledger(
            scenario.publication,
            published_value=250.0,
            original_value=250.0,
            net_applied_delta=0,
            restatement_count=0,
            publication_status=K.PUBLICATION_PUBLISHED,
        )
        return scenario

    def test_restating_up_and_back_down_drives_the_net_delta_to_exactly_zero(
        self, api, director
    ):
        """The two baselines are asymmetric — 10.00 going up, 9.09 coming back.

        PRD 3.7: "Because the delta is signed, approving a restatement that returns the figure to its
        original value drives `net_applied_delta` to exactly 0.0 and `published_value` back to
        `original_value`, while `restatement_count` keeps climbing — the audit trail is never rewound."

        PRD 3.7: "The baseline is the publication's `published_value` at that moment — which for a
        second restatement is the value the first one left behind, not `original_value`."

        Design: Difficulty/compensating_invariant/compensating_restatement_returns_publication_to_original_value
        """
        scenario = self._completions_figure_at_two_fifty(api, "a1b2c3d4e5f60023")

        first, applied_first, after_first = _apply_restatement(
            api, scenario, 275.0, OMITTED_DEGREES, director, "PN-2027-001"
        )
        assert_restatement(
            first, baseline_value=250.0, delta_pct=10.00, public_notice_required=True
        )
        assert_restatement(applied_first, status=K.RESTATEMENT_APPLIED)
        assert_publication_ledger(
            after_first,
            published_value=275.0,
            original_value=250.0,
            net_applied_delta=25.0,
            restatement_count=1,
            publication_status=K.PUBLICATION_RESTATED,
        )

        second, applied_second, after_second = _apply_restatement(
            api, scenario, 250.0, REVERT_TO_CERTIFIED, director, "PN-2027-002"
        )
        assert_restatement(second, baseline_value=275.0, delta_pct=9.09)
        assert_restatement(applied_second, status=K.RESTATEMENT_APPLIED)
        assert_publication_ledger(
            after_second,
            published_value=250.0,
            original_value=250.0,
            net_applied_delta=0.0,
            restatement_count=2,
            publication_status=K.PUBLICATION_RESTATED,
        )

    def test_a_third_movement_measures_from_the_walked_back_figure_and_the_counter_keeps_climbing(
        self, api, director
    ):
        """original_value is written once, so the compensated figure is its own new baseline.

        PRD 3.7: "`original_value` is the figure the institution first stood behind,
        `net_applied_delta` is the accumulated signed movement of every applied restatement, and
        `restatement_count` is how many were applied."

        PRD 3.7: "The row is created at `publication_status` `PUBLISHED`, with `original_value` set
        equal to the supplied `published_value` and never written again, `net_applied_delta` at 0,
        `restatement_count` at 0, `published_by_user_id` recording the publishing analyst,
        `withdrawal_reason` null and `version` 1."

        Design: Difficulty/compensating_invariant/compensating_restatement_returns_publication_to_original_value
        """
        scenario = self._completions_figure_at_two_fifty(api, "a1b2c3d4e5f60025")

        _apply_restatement(api, scenario, 275.0, OMITTED_DEGREES, director, "PN-2027-003")
        _second, _applied, compensated = _apply_restatement(
            api, scenario, 250.0, REVERT_TO_CERTIFIED, director, "PN-2027-004"
        )
        assert_publication_ledger(
            compensated,
            published_value=250.0,
            original_value=250.0,
            net_applied_delta=0.0,
            restatement_count=2,
        )

        third, applied_third, after_third = _apply_restatement(
            api, scenario, 255.0, SUMMER_CONFERRALS, director, "PN-2027-005"
        )
        assert_restatement(
            third, baseline_value=250.0, delta_pct=2.00, public_notice_required=True
        )
        assert_restatement(applied_third, status=K.RESTATEMENT_APPLIED)
        assert_publication_ledger(
            after_third,
            published_value=255.0,
            original_value=250.0,
            net_applied_delta=5.0,
            restatement_count=3,
            publication_status=K.PUBLICATION_RESTATED,
        )
