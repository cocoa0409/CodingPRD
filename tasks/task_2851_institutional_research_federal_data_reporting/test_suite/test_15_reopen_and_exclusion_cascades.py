"""Two four-level cascades: the reopen that only voids, and the exclusion that files anew."""

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import (
    assert_cohort_conservation,
    assert_cohort_counts,
    assert_component_status,
    assert_cycle_ledger,
    assert_cycle_posture,
    assert_null,
    assert_publication_ledger,
    assert_rate_variants,
    assert_restatement,
    assert_version,
    assert_version_bumped,
    constants as K,
    factories as f,
    fixtures as fx,
)

STEADY_HEADCOUNT = (
    {
        "metric_key": K.METRIC_TOTAL_HEADCOUNT,
        "reported_value": 1000,
        "prior_year_value": 1000,
        "source_field_path": "sis.enrollment.total_headcount",
    },
)
COHORT_HEADCOUNT = (
    {
        "metric_key": K.METRIC_TOTAL_HEADCOUNT,
        "reported_value": 5,
        "prior_year_value": 5,
        "source_field_path": "sis.enrollment.cohort_headcount",
    },
)
SINGLE_HEADCOUNT = (
    {
        "metric_key": K.METRIC_TOTAL_HEADCOUNT,
        "reported_value": 1,
        "prior_year_value": 1,
        "source_field_path": "sis.enrollment.retention_headcount",
    },
)
FTE_RECLASSIFICATION = (
    "Late residency reclassification raises the reported full-time equivalent enrollment."
)
HELP_DESK_REOPEN = (
    "Federal help desk flagged the fall enrollment file for a residency recount."
)
HEADCOUNT_CORRECTION = "Ten late-registered students were omitted from the published fall headcount."
NOT_SUPPORTED_REASON = "The ten students registered after the census date and cannot be added."
FTE_WITHDRAWAL_REASON = (
    "The full-time equivalent series is withdrawn pending a full residency recount."
)
COHORT_STATEMENT = (
    "I certify the fall enrollment component that backs the graduation-rate dashboard."
)
RETENTION_STATEMENT = (
    "I certify the fall enrollment component that backs the retention-rate dashboard."
)
DEATH_CERTIFICATE_NOTE = "Death certificate received from the state registrar on 2026-12-04."
APPROVAL_NOTE = "Allowable exclusion approved; documentary evidence verified."
DENIAL_NOTE = "The evidence was retracted by the state registrar, so the exclusion is denied."
PUBLICATION_START = "2026-12-01T00:00:00Z"


class TestOneReopenReachesFourLevelsDeep:
    """Cycle, component, both of its figures, and the live request beneath the second one."""

    @staticmethod
    def _two_published_figures(api, checksum):
        """A FROZEN cycle whose single certified component carries two published figures."""
        scenario = fx.frozen_cycle(
            api, metrics=STEADY_HEADCOUNT, record_count=1000, checksum=checksum
        )
        headcount = fx.publish_metric(
            api, scenario, metric_key="TOTAL_HEADCOUNT_FALL", published_value=1000.0
        )
        fte = fx.publish_metric(
            api, scenario, metric_key="FTE_ENROLLMENT_FALL", published_value=900.0
        )
        return scenario, headcount, fte

    def test_the_already_pending_figure_is_still_visited_so_its_request_is_voided(
        self, api, analyst, registrar, director
    ):
        """One reopen call reverts the component and reaches the request two levels below it.

        PRD 2.7: "**Reopening a frozen cycle** moves the cycle to `REOPENED` (level 1); every
        `CERTIFIED` survey component of that cycle reverts to `DRAFT` and has its edit checks voided
        (level 2); every non-`WITHDRAWN` dashboard publication of each reverted component is visited
        and set to `RESTATEMENT_PENDING` (level 3); and every `SUBMITTED` restatement request beneath
        each visited publication becomes `VOIDED` (level 4)."

        PRD 2.7: "**Visiting is versioning**: every row a cascade touches has its `updated_at`
        refreshed and its `version` incremented by 1 — and this holds even when the visit does not
        change the row's state value, so a publication already sitting at `RESTATEMENT_PENDING` that
        is re-visited by a cascade still advances its `version`."

        PRD 3.7: "Otherwise `delta_pct` is the absolute difference between `proposed_value` and the
        baseline, divided by the absolute baseline, multiplied by 100, rounded half up to two decimal
        places, and `public_notice_required` is true when `delta_pct` is at least 2.00."

        Design: Difficulty/transitive_cascade/cycle_reopen_cascades_component_then_publications_then_restatement
        """
        scenario, headcount, fte = self._two_published_figures(api, "a1b2c3d4e5f60008")

        live = fx.file_restatement(
            api, scenario, 910.0, publication=fte, justification=FTE_RECLASSIFICATION
        )
        assert_restatement(
            live,
            status=K.RESTATEMENT_SUBMITTED,
            origin=K.ORIGIN_ANALYST,
            baseline_value=900.0,
            proposed_value=910.0,
            delta_pct=1.11,
            public_notice_required=False,
        )
        pending_before = validate_success(api.get_publication(fte["id"], analyst))
        assert_publication_ledger(
            pending_before,
            published_value=900.0,
            publication_status=K.PUBLICATION_RESTATEMENT_PENDING,
        )

        reopened = validate_success(
            api.reopen_cycle(scenario.cycle_id, f.make_reopen_payload(HELP_DESK_REOPEN), director)
        )
        assert_cycle_posture(reopened, K.POSTURE_REOPENED)
        assert_cycle_ledger(reopened, reopen_count=1)

        reverted = validate_success(api.get_survey_component(scenario.component_id, registrar))
        assert_component_status(
            reverted,
            prep_status=K.PREP_DRAFT,
            edit_status=K.EDIT_NOT_RUN,
            fatal_open_count=0,
        )
        assert_null(reverted["certified_by_user_id"], "component.certified_by_user_id")
        assert_null(reverted["certification_statement"], "component.certification_statement")

        flipped = validate_success(api.get_publication(headcount["id"], analyst))
        assert_publication_ledger(
            flipped,
            published_value=1000.0,
            original_value=1000.0,
            net_applied_delta=0.0,
            restatement_count=0,
            publication_status=K.PUBLICATION_RESTATEMENT_PENDING,
        )
        assert_version_bumped(flipped, headcount, "publication")

        revisited = validate_success(api.get_publication(fte["id"], analyst))
        assert_publication_ledger(
            revisited,
            published_value=900.0,
            original_value=900.0,
            net_applied_delta=0.0,
            restatement_count=0,
            publication_status=K.PUBLICATION_RESTATEMENT_PENDING,
        )
        assert_version_bumped(revisited, pending_before, "publication")

        voided = validate_success(api.get_restatement(live["id"], analyst))
        assert_restatement(
            voided,
            status=K.RESTATEMENT_VOIDED,
            baseline_value=900.0,
            delta_pct=1.11,
        )

        rows, meta = validate_paginated(
            api.list_restatements(analyst, publication_id=fte["id"])
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1

    def test_a_withdrawn_figure_is_skipped_and_a_rejected_request_is_left_alone(
        self, api, analyst, director
    ):
        """Level three never visits a withdrawn figure and level four only touches SUBMITTED rows.

        PRD 2.7: "**Terminal rows are immune**: a `WITHDRAWN` publication is never visited by any
        cascade, and a `SUBMITTED` survey component is never reverted by a cycle reopen, because
        federal transmission is irreversible."

        PRD 3.5: "Level four, caused by each level-three visit, voids every restatement request of
        that publication whose `status` is `SUBMITTED`."

        PRD 3.7: "The publication's own destination then depends on its history, and this is the
        compensation branch: once no other request of that publication remains at `SUBMITTED`, a
        publication whose `restatement_count` is exactly 0 returns to `PUBLISHED`, restoring the
        state it held before the request was ever filed, while a publication whose
        `restatement_count` is at least 1 returns to `RESTATED`, because a previously applied
        restatement still stands."

        Design: Difficulty/transitive_cascade/cycle_reopen_cascades_component_then_publications_then_restatement
        """
        scenario, headcount, fte = self._two_published_figures(api, "a1b2c3d4e5f60010")

        rejected = fx.file_restatement(
            api, scenario, 1010.0, publication=headcount, justification=HEADCOUNT_CORRECTION
        )
        validate_success(
            api.reject_restatement(
                rejected["id"],
                f.make_restatement_rejection_payload(NOT_SUPPORTED_REASON),
                director,
            )
        )
        restored = validate_success(api.get_publication(headcount["id"], analyst))
        assert_publication_ledger(
            restored,
            published_value=1000.0,
            restatement_count=0,
            publication_status=K.PUBLICATION_PUBLISHED,
        )

        doomed = fx.file_restatement(
            api, scenario, 910.0, publication=fte, justification=FTE_RECLASSIFICATION
        )
        withdrawn = validate_success(
            api.withdraw_publication(
                fte["id"], f.make_withdrawal_payload(FTE_WITHDRAWAL_REASON), director
            )
        )
        assert withdrawn["publication_status"] == K.PUBLICATION_WITHDRAWN

        validate_success(
            api.reopen_cycle(scenario.cycle_id, f.make_reopen_payload(HELP_DESK_REOPEN), director)
        )

        visited = validate_success(api.get_publication(headcount["id"], analyst))
        assert_publication_ledger(
            visited,
            published_value=1000.0,
            restatement_count=0,
            publication_status=K.PUBLICATION_RESTATEMENT_PENDING,
        )
        assert_version_bumped(visited, restored, "publication")

        untouched_request = validate_success(api.get_restatement(rejected["id"], analyst))
        assert_restatement(untouched_request, status=K.RESTATEMENT_REJECTED)

        immune = validate_success(api.get_publication(fte["id"], analyst))
        assert immune["publication_status"] == K.PUBLICATION_WITHDRAWN
        assert_version(immune, withdrawn["version"], "publication")

        already_voided = validate_success(api.get_restatement(doomed["id"], analyst))
        assert_restatement(already_voided, status=K.RESTATEMENT_VOIDED)


class TestApprovingOneExclusionFilesASystemRestatement:
    """The exclusion cascade does not merely void: it authors a request of its own."""

    @staticmethod
    def _locked_cohort_behind_a_published_rate(
        api, analyst, director, roster, metrics, record_count, checksum, statement, **cohort_kwargs
    ):
        """A frozen cycle whose cohort was locked by the freeze cascade, plus its published rate."""
        scenario = fx.component_on_locked_cycle(
            api, record_count=record_count, metrics=metrics, checksum=checksum
        )
        scenario = fx.cohort_on_scenario(api, scenario, roster, **cohort_kwargs)
        validate_success(api.prepare_component(scenario.component_id, analyst))
        validate_success(
            api.certify_component(
                scenario.component_id, f.make_certification_payload(statement), director
            )
        )
        frozen = validate_success(api.freeze_cycle(scenario.cycle_id, director))
        assert_cycle_posture(frozen, K.POSTURE_FROZEN)
        return scenario

    def test_the_approval_reprices_the_cohort_and_the_system_files_the_restatement(
        self, api, analyst, registrar, director
    ):
        """The federal rate moves to 75.0 while the ranking rate keeps the excluded student.

        PRD 2.7: "**Approving or reversing an allowable exclusion on a locked cohort** recomputes the
        cohort's counts and both rate variants (level 2 of the member's own decision), then flips
        matching `PUBLISHED` dashboard figures to `RESTATEMENT_PENDING` (level 3), then supersedes
        their pending restatement requests and files a fresh system-authored one carrying the
        recomputed rate (level 4)."

        PRD 3.6: "Its numerator counts members whose `exclusion_status` is not `APPROVED` and whose
        `outcome` is `COMPLETED_150` for a `GRAD_RATE_150` cohort, or whose `outcome` is
        `COMPLETED_150` or `STILL_ENROLLED` for a `RETENTION_FT` cohort."

        PRD 3.6: "Its numerator is `completers_count` for a `GRAD_RATE_150` cohort and
        `retained_count` for a `RETENTION_FT` cohort — note that these counts include members whose
        exclusion was approved."

        PRD 3.6: "Then, for each publication so flipped, every restatement request beneath it whose
        `status` is `SUBMITTED` is moved to `SUPERSEDED`, and a fresh restatement request is filed by
        the system itself: `origin` `CASCADE`, `requested_by_user_id` the literal string `SYSTEM`,
        `proposed_value` the cohort's newly computed `federal_rate_pct`, `baseline_value` the
        publication's current `published_value`, `justification` the fixed text
        `Cascade restatement: cohort exclusion decision applied`, `status` `SUBMITTED`, and
        `delta_pct` and `public_notice_required` derived by the materiality rule of §3.7."

        Design: Difficulty/transitive_cascade/exclusion_approval_cascades_cohort_publication_and_files_system_restatement
        """
        scenario = self._locked_cohort_behind_a_published_rate(
            api,
            analyst,
            director,
            fx.roster_of(
                K.OUTCOME_COMPLETED_150,
                K.OUTCOME_COMPLETED_150,
                K.OUTCOME_COMPLETED_150,
                K.OUTCOME_STILL_ENROLLED,
                K.OUTCOME_STILL_ENROLLED,
            ),
            COHORT_HEADCOUNT,
            5,
            "a1b2c3d4e5f60009",
            COHORT_STATEMENT,
            cohort_type=K.COHORT_GRAD_RATE_150,
            entry_term="FALL2020",
            publication_metric_key="GRAD_RATE_150_FALL2020",
        )
        cohort_id = scenario.cohort_id

        locked_by_freeze = validate_success(api.get_cohort(cohort_id, registrar))
        assert locked_by_freeze["status"] == K.COHORT_LOCKED
        assert_rate_variants(locked_by_freeze, federal_rate_pct=60.0, ranking_rate_pct=60.0)

        publication = fx.publish_metric(
            api,
            scenario,
            metric_key="GRAD_RATE_150_FALL2020",
            published_value=60.0,
            effective_from=PUBLICATION_START,
        )

        member = scenario.member("S005")
        claimed = validate_success(
            api.file_exclusion_claim(
                member["id"],
                f.make_exclusion_claim_payload(
                    K.EXCLUSION_CODE_DECEASED, DEATH_CERTIFICATE_NOTE
                ),
                registrar,
            )
        )
        assert claimed["exclusion_status"] == K.EXCLUSION_CLAIMED

        approved = validate_success(
            api.review_exclusion_claim(
                member["id"],
                f.make_exclusion_review_payload(K.DECISION_APPROVE, APPROVAL_NOTE),
                director,
            )
        )
        assert approved["exclusion_status"] == K.EXCLUSION_APPROVED

        repriced = validate_success(api.get_cohort(cohort_id, registrar))
        assert repriced["status"] == K.COHORT_LOCKED
        assert_cohort_counts(
            repriced,
            initial_count=5,
            exclusion_count=1,
            adjusted_count=4,
            completers_count=3,
            retained_count=5,
        )
        assert_cohort_conservation(repriced)
        assert_rate_variants(repriced, federal_rate_pct=75.0, ranking_rate_pct=60.0)

        flipped = validate_success(api.get_publication(publication["id"], analyst))
        assert_publication_ledger(
            flipped,
            published_value=60.0,
            original_value=60.0,
            net_applied_delta=0.0,
            restatement_count=0,
            publication_status=K.PUBLICATION_RESTATEMENT_PENDING,
        )

        rows, meta = validate_paginated(
            api.list_restatements(
                director, publication_id=publication["id"], origin=K.ORIGIN_CASCADE
            )
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert_restatement(
            rows[0],
            status=K.RESTATEMENT_SUBMITTED,
            origin=K.ORIGIN_CASCADE,
            requested_by_user_id=K.SYSTEM_USER_ID,
            baseline_value=60.0,
            proposed_value=75.0,
            delta_pct=25.00,
            public_notice_required=True,
        )
        assert rows[0]["justification"] == K.CASCADE_JUSTIFICATION

    def test_the_same_decision_on_a_draft_cohort_stops_at_the_recomputed_counts(
        self, api, analyst, registrar, director
    ):
        """A cohort the freeze skipped publishes nothing, so reversing its exclusion files nothing.

        PRD 3.5: "Cohorts whose `adjusted_count` is exactly 0 are deliberately **skipped** and left
        `DRAFT`, because no rate is definable over a zero denominator; they must be corrected and
        locked explicitly afterwards."

        PRD 3.6: "**The cascade into published rates fires only when the cohort is `LOCKED`.**"

        PRD 3.6: "The three differ in what actually moves: an approval adds the member to
        `exclusion_count` and removes it from `adjusted_count`; a denial of a claim moves neither
        count, because a merely `CLAIMED` member had never entered `exclusion_count`; and a denial of
        an approval decreases `exclusion_count` by one and increases `adjusted_count` by one,
        restoring both rates to their pre-approval values exactly."

        PRD 3.6: "A decision on a `DRAFT` cohort recomputes the counts and rates and stops there —
        nothing is published yet, so nothing needs restating."

        Design: Difficulty/transitive_cascade/exclusion_approval_cascades_cohort_publication_and_files_system_restatement
        """
        scenario = fx.component_on_locked_cycle(
            api, record_count=1, metrics=SINGLE_HEADCOUNT, checksum="a1b2c3d4e5f60011"
        )
        scenario = fx.cohort_on_scenario(
            api,
            scenario,
            fx.roster_of(K.OUTCOME_STILL_ENROLLED),
            cohort_type=K.COHORT_RETENTION_FT,
            entry_term="FALL2025",
            publication_metric_key="RETENTION_FT_FALL2025",
        )
        cohort_id = scenario.cohort_id
        member = scenario.member("S001")

        validate_success(
            api.file_exclusion_claim(
                member["id"],
                f.make_exclusion_claim_payload(
                    K.EXCLUSION_CODE_DECEASED, DEATH_CERTIFICATE_NOTE
                ),
                registrar,
            )
        )
        approved = validate_success(
            api.review_exclusion_claim(
                member["id"],
                f.make_exclusion_review_payload(K.DECISION_APPROVE, APPROVAL_NOTE),
                director,
            )
        )
        assert approved["exclusion_status"] == K.EXCLUSION_APPROVED

        emptied = validate_success(api.get_cohort(cohort_id, registrar))
        assert_cohort_counts(emptied, initial_count=1, exclusion_count=1, adjusted_count=0)
        assert_null(emptied["federal_rate_pct"], "cohort.federal_rate_pct")
        assert_rate_variants(emptied, ranking_rate_pct=100.0)

        validate_success(api.prepare_component(scenario.component_id, analyst))
        validate_success(
            api.certify_component(
                scenario.component_id, f.make_certification_payload(RETENTION_STATEMENT), director
            )
        )
        frozen = validate_success(api.freeze_cycle(scenario.cycle_id, director))
        assert_cycle_posture(frozen, K.POSTURE_FROZEN)

        skipped = validate_success(api.get_cohort(cohort_id, registrar))
        assert skipped["status"] == K.COHORT_DRAFT
        assert_null(skipped["locked_at"], "cohort.locked_at")

        publication = fx.publish_metric(
            api,
            scenario,
            metric_key="RETENTION_FT_FALL2025",
            published_value=100.0,
            effective_from=PUBLICATION_START,
        )
        assert publication["publication_status"] == K.PUBLICATION_PUBLISHED

        denied = validate_success(
            api.review_exclusion_claim(
                member["id"],
                f.make_exclusion_review_payload(K.DECISION_DENY, DENIAL_NOTE),
                director,
            )
        )
        assert denied["exclusion_status"] == K.EXCLUSION_DENIED

        restored = validate_success(api.get_cohort(cohort_id, registrar))
        assert restored["status"] == K.COHORT_DRAFT
        assert_cohort_counts(
            restored,
            initial_count=1,
            exclusion_count=0,
            adjusted_count=1,
            retained_count=1,
        )
        assert_cohort_conservation(restored)
        assert_rate_variants(restored, federal_rate_pct=100.0, ranking_rate_pct=100.0)

        unmoved = validate_success(api.get_publication(publication["id"], analyst))
        assert_publication_ledger(
            unmoved,
            published_value=100.0,
            restatement_count=0,
            publication_status=K.PUBLICATION_PUBLISHED,
        )
        assert_version(unmoved, publication["version"], "publication")

        rows, meta = validate_paginated(
            api.list_restatements(analyst, publication_id=publication["id"])
        )
        assert meta["total_count"] == 0
        assert rows == []
