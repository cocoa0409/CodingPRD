"""Licence agreements, the creative approval loop and the two supersede paths."""

import pytest

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    api_client,
    assert_row_inert,
    factories as f,
    fixtures as fx,
    make_headers,
    validate_error,
    validate_error_is_one_of,
    validate_object,
    validate_success,
)

VOM = fx.VOM
LM = fx.LM
REP = fx.REP
PRODUCER = fx.PRODUCER
PRODUCER_OTHER = fx.PRODUCER_OTHER
OFFICER = fx.OFFICER


def _file_submission(agreement_id, run_id, expected_version, **overrides):
    """File one creative submission with an explicitly chosen version guard."""
    return api_client.create_submission(
        f.submission_payload(agreement_id, run_id, expected_version, **overrides),
        PRODUCER,
    )


class TestRevisionLoopAndSupersession:
    """The negotiation cycle, its counter and the two ways out of it."""

    def test_the_loop_runs_then_a_newer_row_supersedes_the_survivor(self):
        """A resubmitted row keeps its history when a newer row of the family lands.

        PRD: "When a new submission joins a family that already holds a row in
        `SUBMITTED`, `IN_REVIEW` or `CHANGES_REQUESTED`, that older row is moved
        to `SUPERSEDED` and its `superseded_by_submission_id` is set to the new
        row's `id`."
        PRD: "a row superseded out of `IN_REVIEW` keeps its `review_started_at`
        exactly as it was."

        Design: Difficulty/non_linear_state_machine/submission_revision_loop_then_supersede_branch
        """
        bundle = fx.run_bundle()
        agreement_id = bundle["agreement"]["id"]
        run_id = bundle["run"]["id"]

        first = validate_object(
            _file_submission(
                agreement_id, run_id, fx.agreement_version(agreement_id),
                asset_code="RD-001", title="Vestibule dressing v1",
            ),
            201,
        )
        validate_success(api_client.start_submission_review(first["id"], REP))
        changes = validate_success(
            api_client.decide_submission(
                first["id"],
                f.submission_decision_payload(
                    "CHANGES_REQUESTED", "the pin motif is off model"
                ),
                REP,
            )
        )
        assert changes["status"] == "CHANGES_REQUESTED"
        assert changes["change_note"] == "the pin motif is off model"

        resubmitted = validate_success(
            api_client.resubmit_submission(first["id"], PRODUCER)
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["revision_round"] == 1
        assert resubmitted["change_note"] is None
        assert resubmitted["resubmitted_at"] is not None
        review_started_at = resubmitted["review_started_at"]
        assert review_started_at is not None

        second = validate_object(
            _file_submission(
                agreement_id, run_id, fx.agreement_version(agreement_id),
                asset_code="RD-001", title="Vestibule dressing v2",
            ),
            201,
        )
        superseded = fx.read_submission(first["id"])
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["superseded_by_submission_id"] == second["id"]
        assert superseded["revision_round"] == 1
        assert superseded["review_started_at"] == review_started_at
        assert fx.read_agreement(agreement_id)["open_submission_count"] == 1

        validate_error(
            api_client.resubmit_submission(first["id"], PRODUCER),
            ApiErrorId.ERR_SUBMISSION_INVALID_STATE.value,
        )

    def test_approving_the_survivor_closes_the_family_without_clearing_the_run(self):
        """The approval moves both agreement counters and leaves the run uncleared.

        PRD: "the agreement's `open_submission_count` falls by 1 while its
        `approved_submission_count` rises by 1, and the run's clearance gate is
        re-derived".
        PRD: "the run has at least one staff member with status `CLEARED` in
        each of the three crafts `PERFORMER`, `AMBASSADOR` and `TECHNICIAN`."

        Design: Difficulty/non_linear_state_machine/submission_revision_loop_then_supersede_branch
        """
        bundle = fx.run_bundle()
        agreement_id = bundle["agreement"]["id"]
        run_id = bundle["run"]["id"]

        first = validate_object(
            _file_submission(
                agreement_id, run_id, fx.agreement_version(agreement_id),
                asset_code="RD-001", title="Vestibule dressing v1",
            ),
            201,
        )
        second = validate_object(
            _file_submission(
                agreement_id, run_id, fx.agreement_version(agreement_id),
                asset_code="RD-001", title="Vestibule dressing v2",
            ),
            201,
        )
        assert fx.read_submission(first["id"])["status"] == "SUPERSEDED"

        validate_success(api_client.start_submission_review(second["id"], REP))
        approved = validate_success(
            api_client.decide_submission(
                second["id"],
                f.submission_decision_payload("APPROVED", "cleared for build"),
                REP,
            )
        )
        assert approved["status"] == "APPROVED"
        assert approved["decided_by_user_id"] == "rep-1"
        assert approved["revision_round"] == 0
        assert approved["decided_at"] is not None

        agreement = fx.read_agreement(agreement_id)
        assert agreement["open_submission_count"] == 0
        assert agreement["approved_submission_count"] == 1
        assert fx.read_run(run_id)["clearance_status"] == "UNCLEARED"

    def test_the_cap_bites_only_on_the_fourth_resubmit(self):
        """Three laps are admissible; the fourth resubmit is the first refusal.

        PRD: "Resubmission requires the agreement to still be `ACTIVE` and
        requires `revision_round` to be below three; once three revision rounds
        have been consumed the negotiation is over and further attempts earn
        `ERR_REVISION_ROUND_CAP`."

        Design: Corner/errors/revision_round_cap_error_is_reachable_only_on_the_fourth_resubmit
        """
        bundle = fx.run_bundle()
        agreement_id = bundle["agreement"]["id"]
        run_id = bundle["run"]["id"]
        submission = validate_object(
            _file_submission(
                agreement_id, run_id, fx.agreement_version(agreement_id)
            ),
            201,
        )
        notes = [
            "lap one: soften the strobe cue",
            "lap two: the logo lockup is still wrong",
            "lap three: the closing voiceover is off script",
            "lap four: the merchandise sheet is missing",
        ]
        for lap, note in enumerate(notes, start=1):
            validate_success(
                api_client.start_submission_review(submission["id"], REP)
            )
            validate_success(
                api_client.decide_submission(
                    submission["id"],
                    f.submission_decision_payload("CHANGES_REQUESTED", note),
                    REP,
                )
            )
            if lap <= 3:
                looped = validate_success(
                    api_client.resubmit_submission(submission["id"], PRODUCER)
                )
                assert looped["revision_round"] == lap
                assert looped["change_note"] is None

        capped_before = fx.read_submission(submission["id"])
        assert capped_before["revision_round"] == 3
        validate_error(
            api_client.resubmit_submission(submission["id"], PRODUCER),
            ApiErrorId.ERR_REVISION_ROUND_CAP.value,
        )
        capped_after = fx.read_submission(submission["id"])
        assert capped_after["status"] == "CHANGES_REQUESTED"
        assert capped_after["revision_round"] == 3
        assert capped_after["change_note"] == notes[-1]
        assert_row_inert(capped_before, capped_after)

        replacement = validate_object(
            _file_submission(
                agreement_id, run_id, fx.agreement_version(agreement_id),
                title="Atrium scripted beat sheet, rebuilt",
            ),
            201,
        )
        assert replacement["revision_round"] == 0
        escaped = fx.read_submission(submission["id"])
        assert escaped["status"] == "SUPERSEDED"
        assert escaped["superseded_by_submission_id"] == replacement["id"]
        assert escaped["revision_round"] == 3


class TestStaleVersionMasksTheScopeRule:
    """A body carrying both a stale parent version and an ungranted scope."""

    def test_the_version_conflict_outranks_the_scope_rule(self):
        """The 412 is reported first, and the refusal stores nothing.

        PRD: "If `expected_agreement_version` does not equal the agreement's
        current `version`, the create is rejected with
        `ERR_AGREEMENT_VERSION_CONFLICT` and HTTP 412."
        PRD: "the declared `scope` must appear in the agreement's
        `approval_scopes`, or the create is refused with
        `ERR_SCOPE_NOT_IN_AGREEMENT`."

        Design: Difficulty/priority_pair_validation_conflict/stale_agreement_version_masks_the_scope_eligibility_rule
        """
        bundle = fx.run_with_room(lease_active=True)
        agreement_id = bundle["agreement"]["id"]
        run_id = bundle["run"]["id"]
        stale_version = fx.agreement_version(agreement_id)
        first = validate_object(
            _file_submission(
                agreement_id, run_id, stale_version,
                asset_code="CE-001", title="Vestibule dressing",
            ),
            201,
        )

        response = _file_submission(
            agreement_id, run_id, stale_version,
            scope="MARKETING", asset_code="MK-001",
            title="Out-of-home campaign",
        )
        validate_error(
            response, ApiErrorId.ERR_AGREEMENT_VERSION_CONFLICT.value, 412
        )
        agreement = fx.read_agreement(agreement_id)
        fresh_version = agreement["version"]
        assert fresh_version == stale_version + 1
        assert agreement["open_submission_count"] == 1

        validate_error(
            _file_submission(
                agreement_id, run_id, fresh_version,
                scope="MARKETING", asset_code="MK-001",
                title="Out-of-home campaign",
            ),
            ApiErrorId.ERR_SCOPE_NOT_IN_AGREEMENT.value,
            409,
        )
        still = fx.read_agreement(agreement_id)
        assert still["version"] == fresh_version
        assert still["open_submission_count"] == 1
        assert fx.read_submission(first["id"])["status"] == "SUBMITTED"
        assert fx.read_submission(first["id"])["superseded_by_submission_id"] is None

    def test_a_legal_scope_on_the_fresh_version_is_accepted(self):
        """A different asset code opens its own family and raises the open count.

        PRD: "When a new submission joins a family that already holds a row in
        `SUBMITTED`, `IN_REVIEW` or `CHANGES_REQUESTED`, that older row is moved
        to `SUPERSEDED` and its `superseded_by_submission_id` is set to the new
        row's `id`."
        PRD: "The agreement's `open_submission_count` rises by 1 only when
        nothing was superseded".

        Design: Difficulty/priority_pair_validation_conflict/stale_agreement_version_masks_the_scope_eligibility_rule
        """
        bundle = fx.run_with_room(lease_active=True)
        agreement_id = bundle["agreement"]["id"]
        run_id = bundle["run"]["id"]
        first = validate_object(
            _file_submission(
                agreement_id, run_id, fx.agreement_version(agreement_id),
                asset_code="CE-001", title="Vestibule dressing",
            ),
            201,
        )
        fresh_version = fx.agreement_version(agreement_id)
        second = validate_object(
            _file_submission(
                agreement_id, run_id, fresh_version,
                asset_code="CE-002", title="Corridor scent cue",
            ),
            201,
        )
        assert second["status"] == "SUBMITTED"
        assert second["revision_round"] == 0
        agreement = fx.read_agreement(agreement_id)
        assert agreement["open_submission_count"] == 2
        assert agreement["version"] == fresh_version + 1
        untouched = fx.read_submission(first["id"])
        assert untouched["status"] == "SUBMITTED"
        assert untouched["superseded_by_submission_id"] is None


class TestAgreementExpiryCascade:
    """Expiry closes every open row and strips the coverage the runs relied on."""

    @staticmethod
    def _world():
        bundle = fx.open_run(
            agreement_overrides={
                "approval_scopes": ["CREATIVE_EXECUTION", "MERCHANDISE"],
                "term_end_date": "2026-08-20",
            },
            slot_overrides={"base_capacity": 40, "wheelchair_positions": 4},
        )
        agreement_id = bundle["agreement"]["id"]
        bundle["open_submission"] = validate_object(
            _file_submission(
                agreement_id, bundle["run"]["id"],
                fx.agreement_version(agreement_id),
                asset_code="RD-002", title="Vestibule scent cue",
            ),
            201,
        )
        bundle["guest"] = fx.create_guest()
        fx.set_clock("2026-08-10T00:00:00Z")
        bundle["order"] = fx.place_order(
            bundle["slot"]["id"], bundle["guest"]["id"], party_size=4
        )
        fx.set_clock("2026-08-21T00:00:00Z")
        return bundle

    def test_expiry_rejects_every_open_submission_and_zeroes_the_open_count(self):
        """Hops one and two: the licence closes and its open rows are rejected.

        PRD: "Every creative submission on the agreement still in `SUBMITTED`,
        `IN_REVIEW` or `CHANGES_REQUESTED` is moved to `REJECTED`, with
        `decision_note` set to the literal string `AGREEMENT_EXPIRED`,
        `decided_at` stamped from the clock and `decided_by_user_id` set to the
        expiring caller's `X-User-ID`".
        PRD: "`open_submission_count` is then set to 0."

        Design: Difficulty/transitive_cascade/agreement_expiry_cascades_through_open_submissions_into_run_clearance
        """
        bundle = self._world()
        agreement_id = bundle["agreement"]["id"]

        expired = validate_success(api_client.expire_agreement(agreement_id, LM))
        assert expired["status"] == "EXPIRED"

        rejected = fx.read_submission(bundle["open_submission"]["id"])
        assert rejected["status"] == "REJECTED"
        assert rejected["decision_note"] == "AGREEMENT_EXPIRED"
        assert rejected["decided_by_user_id"] == "lm-1"
        assert rejected["decided_at"] is not None

        agreement = fx.read_agreement(agreement_id)
        assert agreement["open_submission_count"] == 0
        assert agreement["approved_submission_count"] == 2
        for approved in bundle["submissions"].values():
            assert fx.read_submission(approved["id"])["status"] == "APPROVED"

    def test_the_run_loses_its_clearance_and_can_no_longer_confirm_a_sale(self):
        """Hop three: compliance falls while the operational standing holds.

        PRD: "every run under the agreement whose compliance standing was
        `CLEARED` drops to `UNCLEARED` as a second hop, each such run taking its
        own version increment."
        PRD: "the run's `clearance_status` to be `CLEARED`, or the request is
        refused with `ERR_RUN_NOT_CLEARED`".

        Design: Difficulty/transitive_cascade/agreement_expiry_cascades_through_open_submissions_into_run_clearance
        """
        bundle = self._world()
        run_before = fx.read_run(bundle["run"]["id"])
        assert run_before["clearance_status"] == "CLEARED"

        validate_success(api_client.expire_agreement(bundle["agreement"]["id"], LM))

        run_after = fx.read_run(bundle["run"]["id"])
        assert run_after["clearance_status"] == "UNCLEARED"
        assert run_after["run_status"] == "OPEN"
        assert run_after["version"] == run_before["version"] + 1

        validate_error(
            api_client.confirm_order(bundle["order"]["id"], fx.AGENT),
            ApiErrorId.ERR_RUN_NOT_CLEARED.value,
        )
        order = fx.read_order(bundle["order"]["id"])
        assert order["status"] == "PENDING"
        assert order["net_collected_cents"] == 0
        slot = fx.read_slot(bundle["slot"]["id"])
        assert slot["sold_capacity"] == 0
        assert (
            slot["released_capacity"]
            == slot["held_capacity"] + slot["sold_capacity"] + slot["available_capacity"]
        )


class TestAgreementTerminalStates:
    """Activation is not a self-loop, and the two terminal states lock down."""

    def test_activation_is_refused_the_second_time(self):
        """The repeat is a 409 and neither advances the version nor re-stamps.

        PRD: "Activation moves `DRAFT → ACTIVE` and is admissible only while the
        logical clock's calendar date is on or before `term_end_date`".

        Design: Corner/state_machines/agreement_activation_repeated_is_rejected_on_the_second_call
        """
        agreement = fx.create_agreement()
        activated = validate_success(
            api_client.activate_agreement(agreement["id"], LM)
        )
        assert activated["status"] == "ACTIVE"
        assert activated["version"] == 2

        validate_error(
            api_client.activate_agreement(agreement["id"], LM),
            ApiErrorId.ERR_AGREEMENT_INVALID_STATE.value,
            409,
        )
        after = fx.read_agreement(agreement["id"])
        assert_row_inert(activated, after)
        assert after["version"] == 2

    def test_an_expired_licence_still_lets_its_statement_be_cut_and_settled(self):
        """The lockdown is scoped: finalisation survives expiry, settlement is terminal.

        PRD: "The agreement may be `ACTIVE` or `EXPIRED` by then — an expired
        licence does not stop its final statements being cut."
        PRD: "`SETTLED` and `SUPERSEDED` are the two terminal states of a
        statement."

        Design: Corner/state_machines/expired_agreement_and_settled_statement_reject_every_further_transition
        """
        bundle = fx.run_with_room(
            agreement_overrides={"term_end_date": "2026-08-31"}
        )
        agreement_id = bundle["agreement"]["id"]
        run_id = bundle["run"]["id"]
        submission = validate_object(
            _file_submission(
                agreement_id, run_id, fx.agreement_version(agreement_id)
            ),
            201,
        )
        validate_success(api_client.start_submission_review(submission["id"], REP))
        validate_success(
            api_client.decide_submission(
                submission["id"],
                f.submission_decision_payload(
                    "CHANGES_REQUESTED", "soften the strobe cue in the atrium"
                ),
                REP,
            )
        )
        statement = fx.draft_statement(run_id)

        fx.set_clock("2026-09-01T09:00:00Z")
        validate_success(api_client.expire_agreement(agreement_id, LM))

        validate_error(
            api_client.activate_agreement(agreement_id, LM),
            ApiErrorId.ERR_AGREEMENT_INVALID_STATE.value,
            409,
        )
        validate_error(
            api_client.expire_agreement(agreement_id, LM),
            ApiErrorId.ERR_AGREEMENT_INVALID_STATE.value,
            409,
        )

        # The expiry cascade already rejected the open row, so the resubmit is
        # barred both by the row's own state and by its parent's; the PRD does
        # not pin which of the two is reported.
        frozen = fx.read_submission(submission["id"])
        assert frozen["status"] == "REJECTED"
        assert frozen["decision_note"] == "AGREEMENT_EXPIRED"
        validate_error_is_one_of(
            api_client.resubmit_submission(submission["id"], PRODUCER),
            [
                ApiErrorId.ERR_SUBMISSION_INVALID_STATE.value,
                ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value,
            ],
        )

        issued = validate_success(api_client.finalize_statement(statement["id"], LM))
        assert issued["status"] == "ISSUED"
        settled = validate_success(api_client.settle_statement(statement["id"], LM))
        assert settled["status"] == "SETTLED"
        assert settled["settled_at"] is not None

        locked = fx.read_statement(statement["id"])
        for call in (
            api_client.recompute_provisional,
            api_client.finalize_statement,
            api_client.settle_statement,
        ):
            validate_error(
                call(statement["id"], LM),
                ApiErrorId.ERR_STATEMENT_INVALID_STATE.value,
                409,
            )
        assert_row_inert(locked, fx.read_statement(statement["id"]))


class TestSubmitterSegregationOfDuties:
    """The submitter bind compares user identifiers, not roles."""

    def test_the_filer_may_not_approve_or_reject_but_may_ask_for_changes(self):
        """The bind is partial and it survives the resubmit loop.

        PRD: "Both terminal decisions are barred to the filer: if the deciding
        `X-User-ID` equals the row's `submitted_by_user_id`, the decision is
        refused with `ERR_SOD_APPROVAL_SAME_USER`."
        PRD: "The producer resubmits it, moving `CHANGES_REQUESTED → SUBMITTED`,
        incrementing `revision_round` by 1, stamping `resubmitted_at` and
        clearing `change_note`."

        Design: Corner/rbac/submitter_deciding_its_own_submission_is_rejected_on_every_hop
        """
        bundle = fx.run_bundle(lease_active=True)
        agreement_id = bundle["agreement"]["id"]
        dual_hat = make_headers("rep-1", "ExperienceProducer")
        own = validate_object(
            api_client.create_submission(
                f.submission_payload(
                    agreement_id, bundle["run"]["id"],
                    fx.agreement_version(agreement_id),
                    title="Atrium beat sheet, filed by the dual-hatted rep",
                ),
                dual_hat,
            ),
            201,
        )
        assert own["submitted_by_user_id"] == "rep-1"

        in_review = validate_success(
            api_client.start_submission_review(own["id"], REP)
        )
        assert in_review["status"] == "IN_REVIEW"

        for decision, note in (
            ("APPROVED", "looks fine to me"),
            ("REJECTED", "on reflection, no"),
        ):
            validate_error(
                api_client.decide_submission(
                    own["id"], f.submission_decision_payload(decision, note), REP
                ),
                ApiErrorId.ERR_SOD_APPROVAL_SAME_USER.value,
                403,
            )
        blocked = fx.read_submission(own["id"])
        assert blocked["status"] == "IN_REVIEW"
        assert blocked["decided_at"] is None
        assert blocked["decided_by_user_id"] is None
        assert fx.read_agreement(agreement_id)["open_submission_count"] == 1

        changed = validate_success(
            api_client.decide_submission(
                own["id"],
                f.submission_decision_payload(
                    "CHANGES_REQUESTED", "tighten the third beat"
                ),
                REP,
            )
        )
        assert changed["status"] == "CHANGES_REQUESTED"
        assert changed["change_note"] == "tighten the third beat"
        agreement = fx.read_agreement(agreement_id)
        assert agreement["open_submission_count"] == 1
        assert agreement["approved_submission_count"] == 0

        looped = validate_success(
            api_client.resubmit_submission(own["id"], dual_hat)
        )
        assert looped["status"] == "SUBMITTED"
        assert looped["revision_round"] == 1
        assert looped["change_note"] is None
        assert looped["submitted_by_user_id"] == "rep-1"

        validate_success(api_client.start_submission_review(own["id"], REP))
        validate_error(
            api_client.decide_submission(
                own["id"],
                f.submission_decision_payload("APPROVED", "round two, still me"),
                REP,
            ),
            ApiErrorId.ERR_SOD_APPROVAL_SAME_USER.value,
            403,
        )

    def test_a_different_filer_unlocks_the_same_reviewer_on_the_same_asset(self):
        """Superseding with another producer's row is the only escape from the bind.

        PRD: "if the deciding `X-User-ID` equals the row's
        `submitted_by_user_id`, the decision is refused with
        `ERR_SOD_APPROVAL_SAME_USER`."
        PRD: "Whichever call completes the gate — the approval of the last
        outstanding scope, or the clearing of the last missing craft — is the
        call that moves the run `UNCLEARED → CLEARED`".

        Design: Corner/rbac/submitter_deciding_its_own_submission_is_rejected_on_every_hop
        """
        bundle = fx.run_bundle(lease_active=True)
        agreement_id = bundle["agreement"]["id"]
        run_id = bundle["run"]["id"]
        dual_hat = make_headers("rep-1", "ExperienceProducer")
        own = validate_object(
            api_client.create_submission(
                f.submission_payload(
                    agreement_id, run_id, fx.agreement_version(agreement_id)
                ),
                dual_hat,
            ),
            201,
        )
        validate_success(api_client.start_submission_review(own["id"], REP))

        other = validate_object(
            api_client.create_submission(
                f.submission_payload(
                    agreement_id, run_id, fx.agreement_version(agreement_id),
                    title="Atrium beat sheet, refiled by a different producer",
                ),
                PRODUCER_OTHER,
            ),
            201,
        )
        assert other["submitted_by_user_id"] == "producer-2"
        superseded = fx.read_submission(own["id"])
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["superseded_by_submission_id"] == other["id"]

        validate_success(api_client.start_submission_review(other["id"], REP))
        approved = validate_success(
            api_client.decide_submission(
                other["id"], f.submission_decision_payload("APPROVED", "clean"), REP
            )
        )
        assert approved["status"] == "APPROVED"
        assert approved["decided_by_user_id"] == "rep-1"

        still_superseded = fx.read_submission(own["id"])
        assert still_superseded["status"] == "SUPERSEDED"
        assert still_superseded["decided_at"] is None
        assert fx.read_run(run_id)["clearance_status"] == "UNCLEARED"


class TestOptimisticConcurrency:
    """Both guarded creates watch a parent's version, and both are positioned."""

    def test_a_statement_create_invalidates_the_version_it_just_used(self):
        """The client's own accepted write makes its cached run version stale.

        PRD: "Note that every accepted statement create itself advances the
        run's `version` (by incrementing `royalty_statement_count`), so a caller
        intending to supersede must re-read the run first."
        PRD: "If `expected_run_version` does not equal the run's current
        `version`, the create is rejected with `ERR_RUN_VERSION_CONFLICT` and
        HTTP 412."

        Design: Corner/cross_cutting/optimistic_concurrency_guards_both_supersede_paths
        """
        bundle = fx.run_bundle(lease_active=True)
        run_id = bundle["run"]["id"]
        run_v1 = fx.run_version(run_id)
        first = validate_object(
            api_client.create_statement(
                f.statement_payload(run_id, run_v1), LM
            ),
            201,
        )
        assert first["status"] == "DRAFT"

        validate_error(
            api_client.create_statement(f.statement_payload(run_id, run_v1), LM),
            ApiErrorId.ERR_RUN_VERSION_CONFLICT.value,
            412,
        )
        inert = fx.read_statement(first["id"])
        assert inert["status"] == "DRAFT"
        assert inert["superseded_by_statement_id"] is None
        assert fx.read_run(run_id)["royalty_statement_count"] == 1

        # Body foreign-key resolution outranks the version guard, so a stale
        # version against an unknown run is a 404 rather than a 412.
        validate_error(
            api_client.create_statement(
                f.statement_payload(UNKNOWN_UUID, run_v1), LM
            ),
            ApiErrorId.ERR_RUN_NOT_FOUND.value,
            404,
        )

        run_v2 = fx.run_version(run_id)
        assert run_v2 == run_v1 + 1
        second = validate_object(
            api_client.create_statement(f.statement_payload(run_id, run_v2), LM),
            201,
        )
        replaced = fx.read_statement(first["id"])
        assert replaced["status"] == "SUPERSEDED"
        assert replaced["superseded_by_statement_id"] == second["id"]
        assert replaced["version"] == inert["version"] + 1

    def test_a_submission_create_watches_the_agreement_instead(self):
        """The second guard reads a different parent, and a refused write leaves no trace.

        PRD: "The agreement's `version` is advanced by every submission create,
        every submission decision and the agreement's own expiry, so all three
        of those events invalidate a client's cached view."
        PRD: "If `expected_agreement_version` does not equal the agreement's
        current `version`, the create is rejected with
        `ERR_AGREEMENT_VERSION_CONFLICT` and HTTP 412."

        Design: Corner/cross_cutting/optimistic_concurrency_guards_both_supersede_paths
        """
        bundle = fx.run_bundle(lease_active=True)
        agreement_id = bundle["agreement"]["id"]
        run_id = bundle["run"]["id"]
        agr_v1 = fx.agreement_version(agreement_id)
        first = validate_object(
            _file_submission(
                agreement_id, run_id, agr_v1, title="Atrium beat sheet r0"
            ),
            201,
        )

        validate_error(
            _file_submission(
                agreement_id, run_id, agr_v1,
                title="Atrium beat sheet r1 on a stale agreement view",
            ),
            ApiErrorId.ERR_AGREEMENT_VERSION_CONFLICT.value,
            412,
        )
        agr_v2 = fx.agreement_version(agreement_id)
        assert agr_v2 == agr_v1 + 1
        assert fx.read_submission(first["id"])["status"] == "SUBMITTED"

        second = validate_object(
            _file_submission(
                agreement_id, run_id, agr_v2,
                title="Atrium beat sheet r1 on a fresh agreement view",
            ),
            201,
        )
        replaced = fx.read_submission(first["id"])
        assert replaced["status"] == "SUPERSEDED"
        assert replaced["superseded_by_submission_id"] == second["id"]
