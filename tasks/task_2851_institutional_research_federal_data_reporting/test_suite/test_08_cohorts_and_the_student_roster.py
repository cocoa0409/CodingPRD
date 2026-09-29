"""The cohort roster: declared openings, server-computed headcounts and the lock's five gates."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    assert_cohort_conservation,
    assert_cohort_counts,
    assert_common_fields,
    assert_divergence_is_difference_of_published_variants,
    assert_error_body_leaks_nothing,
    assert_instant_equals,
    assert_null,
    assert_rate_variants,
    assert_version,
    constants as K,
    factories as f,
    fixtures as fx,
)

ARMED_FORCES_NOTE = "Active-duty orders dated 2021-01-11 on file."
DENIAL_NOTE = "Orders postdate the cohort exclusion window."


class TestUnknownCohortIdentifier:
    """A well-formed identifier that names nothing is a 404, never an empty success."""

    def test_a_valid_but_unknown_uuid_reports_the_cohort_not_found_code(self, api, analyst):
        """The store is empty, so the read fails on path resolution rather than on schema.

        PRD 2.12: "Each identifier in the path is looked up in turn, and the first identifier that
        names no existing row decides the 404 — the server does not attempt to resolve identifiers
        further right."

        PRD 2.12: "The thirteen path identifiers map to their own error codes: `{cycle_id}` to
        `ERR_CYCLE_NOT_FOUND`, `{frozen_file_id}` to `ERR_FROZEN_FILE_NOT_FOUND`, `{component_id}`
        to `ERR_COMPONENT_NOT_FOUND`, `{metric_id}` to `ERR_METRIC_NOT_FOUND`, `{edit_check_id}` to
        `ERR_EDIT_CHECK_NOT_FOUND`, `{cohort_id}` to `ERR_COHORT_NOT_FOUND`, `{member_id}` to
        `ERR_MEMBER_NOT_FOUND`, `{mapping_id}` to `ERR_MAPPING_NOT_FOUND`, `{submission_id}` to
        `ERR_SUBMISSION_NOT_FOUND`, `{publication_id}` to `ERR_PUBLICATION_NOT_FOUND`,
        `{restatement_id}` to `ERR_RESTATEMENT_NOT_FOUND`, `{request_id}` to
        `ERR_DATA_REQUEST_NOT_FOUND`, and `{cell_id}` to `ERR_CELL_NOT_FOUND`."

        Design: Corner/entities/corner_unknown_cohort_uuid_is_not_found
        """
        rows, meta = validate_paginated(api.list_cohorts(analyst))
        assert meta["total_count"] == 0
        assert rows == []

        refused = api.get_cohort(K.UNKNOWN_UUID, analyst)
        validate_error(refused, ApiErrorId.COHORT_NOT_FOUND, 404)
        assert_error_body_leaks_nothing(refused.json())


class TestMemberOutcomeDefault:
    """The omitted outcome is a real STILL_ENROLLED that participates in both variants."""

    def test_a_member_added_without_an_outcome_is_retained_but_not_a_completer(
        self, api, registrar, analyst
    ):
        """The default lands in retained_count while leaving completers_count alone.

        PRD 3.6: "Adding a member supplies the `student_local_id` of 3 to 32 characters, the
        `entry_status` of `FULL_TIME` or `PART_TIME`, and optionally the `outcome`, which defaults to
        `STILL_ENROLLED`."

        PRD 3.6: "The member is created with `exclusion_status` `NONE`, `exclusion_code`,
        `exclusion_evidence_note`, `exclusion_claimed_by_user_id`, `exclusion_reviewed_by_user_id`
        and `review_note` all null, and `version` 1; the parent cohort's counts and both rate
        variants are then recomputed and the cohort's `version` is incremented."

        PRD 3.6: "`retained_count` is the number whose `outcome` is `COMPLETED_150` or
        `STILL_ENROLLED`, so a completer is also counted as retained."

        Design: Corner/entities/corner_cohort_member_outcome_defaults_to_still_enrolled
        """
        scenario = fx.cohort_with_roster(
            api,
            [
                {
                    "student_local_id": "S001",
                    "entry_status": K.ENTRY_FULL_TIME,
                    "outcome": K.OUTCOME_COMPLETED_150,
                }
            ],
            record_count=2,
            checksum="c1d2e3f4a5b60107",
            cohort_type=K.COHORT_GRAD_RATE_150,
            entry_term="FALL2020",
            publication_metric_key="GRAD_RATE_150_FALL2020",
        )

        defaulted = validate_success(
            api.add_cohort_member(
                scenario.cohort_id,
                f.make_member_payload("S002", entry_status=K.ENTRY_PART_TIME),
                registrar,
            ),
            201,
        )
        assert defaulted["outcome"] == K.OUTCOME_STILL_ENROLLED
        assert defaulted["exclusion_status"] == K.EXCLUSION_NONE
        assert_null(defaulted["exclusion_code"], "member.exclusion_code")
        assert_null(
            defaulted["exclusion_claimed_by_user_id"], "member.exclusion_claimed_by_user_id"
        )
        assert_null(defaulted["review_note"], "member.review_note")
        assert_version(defaulted, 1, "member")
        assert_common_fields(defaulted, "member")

        summary = validate_success(api.get_cohort_rate_summary(scenario.cohort_id, analyst))
        assert_cohort_counts(
            summary, initial_count=2, completers_count=1, retained_count=2, adjusted_count=2
        )
        assert_rate_variants(summary, federal_rate_pct=50.0, ranking_rate_pct=50.0)
        assert_divergence_is_difference_of_published_variants(summary)


class TestHeadcountsAreServerComputed:
    """No count is ever supplied by the client; every one is derived from the roster."""

    def test_a_new_cohort_opens_at_five_zeros_and_reprices_itself_as_members_arrive(
        self, api, registrar, analyst
    ):
        """The creation response carries the declared zeros before any member exists.

        PRD 3.6: "A new cohort starts at `status` `DRAFT`, with all five headcounts —
        `initial_count`, `exclusion_count`, `adjusted_count`, `completers_count` and
        `retained_count` — at 0, both `federal_rate_pct` and `ranking_rate_pct` null, `locked_at`
        null, and `version` 1."

        PRD 3.6: "**The five headcounts** are always recomputed from scratch over every member of
        the cohort, never adjusted by deltas."

        Design: Corner/entities/corner_cohort_counts_are_server_computed_from_the_roster
        """
        scenario = fx.census_locked_cycle(api, record_count=2, checksum="c1d2e3f4a5b60108")

        empty = validate_success(
            api.create_cohort(
                scenario.cycle_id,
                f.make_cohort_payload(
                    cohort_type=K.COHORT_GRAD_RATE_150,
                    entry_term="FALL2020",
                    publication_metric_key="GRAD_RATE_150_FALL2020",
                ),
                registrar,
            ),
            201,
        )
        assert empty["status"] == K.COHORT_DRAFT
        assert_cohort_counts(
            empty,
            initial_count=0,
            exclusion_count=0,
            adjusted_count=0,
            completers_count=0,
            retained_count=0,
        )
        assert_null(empty["federal_rate_pct"], "cohort.federal_rate_pct")
        assert_null(empty["ranking_rate_pct"], "cohort.ranking_rate_pct")
        assert_null(empty["locked_at"], "cohort.locked_at")
        assert_version(empty, 1, "cohort")
        assert_cohort_conservation(empty)

        fx.add_members(
            api,
            empty["id"],
            [
                {
                    "student_local_id": "S001",
                    "entry_status": K.ENTRY_FULL_TIME,
                    "outcome": K.OUTCOME_COMPLETED_150,
                },
                {
                    "student_local_id": "S002",
                    "entry_status": K.ENTRY_FULL_TIME,
                    "outcome": K.OUTCOME_NO_LONGER_ENROLLED,
                },
            ],
        )

        priced = validate_success(api.get_cohort(empty["id"], analyst))
        assert_cohort_counts(
            priced,
            initial_count=2,
            exclusion_count=0,
            adjusted_count=2,
            completers_count=1,
            retained_count=1,
        )
        assert_rate_variants(priced, federal_rate_pct=50.0, ranking_rate_pct=50.0)
        assert priced["status"] == K.COHORT_DRAFT
        assert_version(priced, 3, "cohort")
        assert_cohort_conservation(priced)


class TestOutcomePatchRepricesUntilTheRosterIsLocked:
    """The roster is frozen by the cohort's own status, not by the cycle's posture."""

    def test_the_same_outcome_patch_is_honoured_on_a_draft_cohort_and_refused_once_locked(
        self, api, registrar, analyst
    ):
        """Retention climbs from 50.0 to 100.0, then the lock makes the same edit a conflict.

        PRD 3.6: "Recording a tracked outcome later replaces `outcome` with one of `COMPLETED_150`,
        `STILL_ENROLLED`, `TRANSFERRED_OUT` or `NO_LONGER_ENROLLED`, increments the member's
        `version`, and recomputes the cohort's `completers_count`, `retained_count` and both rate
        variants with the cohort's `version` incremented."

        PRD 3.6: "Both of these roster writes, and a second attempt to lock, are refused on a
        `LOCKED` cohort with `ERR_COHORT_LOCKED`; both are refused once the cycle is `FROZEN` or
        `ARCHIVED` with `ERR_CYCLE_FROZEN`."

        Design: Corner/endpoints/corner_ep_member_outcome_patch_reprices_the_cohort_and_is_refused_once_locked
        """
        cycle = fx.create_cycle(api, registrar)
        fx.move_clock(api, K.CLOCK_AFTER_CENSUS, registrar)

        cohort = validate_success(
            api.create_cohort(
                cycle["id"],
                f.make_cohort_payload(
                    cohort_type=K.COHORT_RETENTION_FT,
                    entry_term="FALL2025",
                    publication_metric_key="RETENTION_FT_FALL2025",
                ),
                registrar,
            ),
            201,
        )
        seated = fx.add_members(
            api,
            cohort["id"],
            [
                {
                    "student_local_id": "S001",
                    "entry_status": K.ENTRY_FULL_TIME,
                    "outcome": K.OUTCOME_STILL_ENROLLED,
                },
                {
                    "student_local_id": "S002",
                    "entry_status": K.ENTRY_FULL_TIME,
                    "outcome": K.OUTCOME_NO_LONGER_ENROLLED,
                },
            ],
        )
        second = seated[1]

        before = validate_success(api.get_cohort(cohort["id"], analyst))
        assert_cohort_counts(before, initial_count=2, retained_count=1, completers_count=0)
        assert_rate_variants(before, federal_rate_pct=50.0, ranking_rate_pct=50.0)

        patched = validate_success(
            api.record_member_outcome(
                second["id"], f.make_outcome_payload(K.OUTCOME_COMPLETED_150), registrar
            )
        )
        assert patched["outcome"] == K.OUTCOME_COMPLETED_150
        assert_version(patched, 2, "member")

        repriced = validate_success(api.get_cohort(cohort["id"], analyst))
        assert_cohort_counts(repriced, completers_count=1, retained_count=2, adjusted_count=2)
        assert_rate_variants(repriced, federal_rate_pct=100.0, ranking_rate_pct=100.0)

        locked = validate_success(api.lock_cohort(cohort["id"], registrar))
        assert locked["status"] == K.COHORT_LOCKED
        assert_instant_equals(
            locked["locked_at"], K.CLOCK_AFTER_CENSUS_ECHO, "cohort.locked_at"
        )

        refused = api.record_member_outcome(
            second["id"], f.make_outcome_payload(K.OUTCOME_STILL_ENROLLED), registrar
        )
        validate_error(refused, ApiErrorId.COHORT_LOCKED, 409)

        untouched = validate_success(api.get_cohort_member(second["id"], analyst))
        assert untouched["outcome"] == K.OUTCOME_COMPLETED_150
        assert_version(untouched, 2, "member")


class TestCohortLockNeedsEveryClaimResolved:
    """One CLAIMED member is enough to block the lock; a denial unblocks it."""

    def test_a_single_open_claim_blocks_the_lock_and_the_denial_lets_it_through(
        self, api, registrar, director, analyst
    ):
        """The denied member stays in the denominator, so the lock prices the cohort at 50.0.

        PRD 3.6: "The `RegistrarOfficer` who locks it must satisfy five preconditions: the cohort
        must be `DRAFT` (else `ERR_COHORT_LOCKED`), the parent cycle must not be `ARCHIVED` (else
        `ERR_INVALID_CYCLE_STATE`), `initial_count` must be at least 1 (else `ERR_EMPTY_COHORT`), no
        member of the cohort may sit at `exclusion_status` `CLAIMED` (else
        `ERR_UNRESOLVED_EXCLUSION_CLAIM`), and `adjusted_count` must be at least 1 (else
        `ERR_EMPTY_COHORT_DENOMINATOR`)."

        PRD 3.6: "The three differ in what actually moves: an approval adds the member to
        `exclusion_count` and removes it from `adjusted_count`; a denial of a claim moves neither
        count, because a merely `CLAIMED` member had never entered `exclusion_count`; and a denial of
        an approval decreases `exclusion_count` by one and increases `adjusted_count` by one,
        restoring both rates to their pre-approval values exactly."

        Design: Corner/state_machines/corner_sm_cohort_lock_blocked_while_an_exclusion_claim_is_unresolved
        """
        scenario = fx.cohort_with_roster(
            api,
            fx.roster_of(
                K.OUTCOME_COMPLETED_150,
                K.OUTCOME_COMPLETED_150,
                K.OUTCOME_NO_LONGER_ENROLLED,
                K.OUTCOME_NO_LONGER_ENROLLED,
            ),
            record_count=4,
            checksum="c1d2e3f4a5b60124",
            cohort_type=K.COHORT_GRAD_RATE_150,
            entry_term="FALL2020",
            publication_metric_key="GRAD_RATE_150_FALL2020",
        )
        fourth = scenario.member("S004")

        claimed = validate_success(
            api.file_exclusion_claim(
                fourth["id"],
                f.make_exclusion_claim_payload(
                    exclusion_code=K.EXCLUSION_CODE_ARMED_FORCES,
                    exclusion_evidence_note=ARMED_FORCES_NOTE,
                ),
                registrar,
            )
        )
        assert claimed["exclusion_status"] == K.EXCLUSION_CLAIMED
        assert claimed["exclusion_claimed_by_user_id"] == "registrar-1"

        blocked = api.lock_cohort(scenario.cohort_id, registrar)
        validate_error(blocked, ApiErrorId.UNRESOLVED_EXCLUSION_CLAIM, 409)

        still_draft = validate_success(api.get_cohort(scenario.cohort_id, analyst))
        assert still_draft["status"] == K.COHORT_DRAFT
        assert_null(still_draft["locked_at"], "cohort.locked_at")

        denied = validate_success(
            api.review_exclusion_claim(
                fourth["id"],
                f.make_exclusion_review_payload(K.DECISION_DENY, DENIAL_NOTE),
                director,
            )
        )
        assert denied["exclusion_status"] == K.EXCLUSION_DENIED
        assert denied["exclusion_reviewed_by_user_id"] == "director-1"
        assert denied["review_note"] == DENIAL_NOTE

        locked = validate_success(api.lock_cohort(scenario.cohort_id, registrar))
        assert locked["status"] == K.COHORT_LOCKED
        assert_instant_equals(
            locked["locked_at"], K.CLOCK_AFTER_CENSUS_ECHO, "cohort.locked_at"
        )
        assert_cohort_counts(
            locked, initial_count=4, exclusion_count=0, adjusted_count=4, completers_count=2
        )
        assert_rate_variants(locked, federal_rate_pct=50.0, ranking_rate_pct=50.0)
        assert_cohort_conservation(locked)
