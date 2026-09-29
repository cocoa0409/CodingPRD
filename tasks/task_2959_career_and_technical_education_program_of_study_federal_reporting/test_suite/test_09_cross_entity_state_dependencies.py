"""Writes whose admissibility is decided by the state of a different record.

Each scenario below drives one endpoint twice with a byte-identical request. The
first call is refused because some *other* entity — the charged program of study,
the committee meeting that documents the review, or the educator on the roster —
is sitting in the wrong state. Nothing about the addressed record changes between
the two calls: only the other entity moves, and the identical write is then
admitted.
"""

from test_helpers import (
    STOP_CLNA_CERTIFIED,
    STOP_COMMITTEE_REVIEW,
    STOP_STATE_APPROVED,
    STOP_SUBMITTED,
    Builder,
    CteApiClient,
    assert_alignment_index,
    assert_cents,
    assert_ledger,
    assert_quorum_figures,
    assert_rate,
    errors,
    f,
    k,
    users,
    validate_error,
    validate_unpaginated,
)

# --- Fixed scenario literals ------------------------------------------------
ALLOCATION_CENTS = 5000000

FIRST_ENDORSEMENT_INSTANT = "2026-08-10T15:00:00.000Z"
SECOND_ENDORSEMENT_INSTANT = "2026-08-17T15:00:00.000Z"
EQUIPMENT_REVIEW_INSTANT = "2026-08-12T15:00:00.000Z"

FAILED_ENDORSEMENT_MINUTES_URL = "https://district.example/min/endorse-fail.pdf"
TIED_ENDORSEMENT_MINUTES_URL = "https://district.example/min/endorse-tie.pdf"
PASSED_ENDORSEMENT_MINUTES_URL = "https://district.example/min/endorse-pass.pdf"
EQUIPMENT_MINUTES_URL = "https://district.example/min/equip.pdf"

NARRATIVE_URL = "https://district.example/narrative.pdf"
LAPSED_CREDENTIAL_EXPIRY = "2026-07-31"
LIVE_CREDENTIAL_EXPIRY = "2029-06-30"


class TestExpenditureCertificationReadsProgramApproval:
    """Allowability certification is gated on the charged program's approval."""

    def test_certification_is_refused_while_the_charged_program_awaits_state_approval(
        self, api: CteApiClient, build: Builder, fiscal_headers
    ) -> None:
        """PRD §3.7: "The charged program of study must be in `approval_status` `STATE_APPROVED`, or the answer is `ERR_POS_NOT_APPROVED`."

        PRD §3.7: "A new award opens in `status` `OPEN` with `direct_obligated_cents`, `indirect_pool_cents`, `obligated_cents` and `admin_obligated_cents` all 0, `remaining_cents` equal to the full `allocation_cents`, `indirect_rate` at the tier that applies to a direct total of zero, and `admin_cap_cents` set to the allocation multiplied by five percent, rounded half-up to whole cents."

        PRD §3.7: "Step two selects `indirect_rate` by a tier lookup keyed **only** on that direct total: a direct total below 5,000,000 cents (fifty thousand dollars) takes the rate 0.0812; a direct total below 20,000,000 cents (two hundred thousand dollars) takes 0.0650; anything at or above 20,000,000 cents takes 0.0500."

        Design: Difficulty/cross_entity_state_dependency/expenditure_certification_reads_the_program_of_study_approval_state
        """
        program = build.program(
            "47.0604",
            stop_at=STOP_COMMITTEE_REVIEW,
            cluster=k.CLUSTER_ADVANCED_MANUFACTURING,
            title="Automotive Technology",
        )
        grant = build.grant(allocation_cents=ALLOCATION_CENTS)
        expenditure = build.expenditure(
            grant.grant_id, program.program_id, k.CATEGORY_CONSUMABLE, 100000
        )

        refused = api.certify_allowability(
            expenditure["id"],
            f.certification_payload(k.DECISION_CERTIFY),
            fiscal_headers,
        )
        validate_error(refused, errors.ERR_POS_NOT_APPROVED)

        untouched = validate_unpaginated(
            api.get_expenditure(expenditure["id"], fiscal_headers)
        )
        assert untouched["status"] == k.EXP_REQUESTED
        assert untouched["approved_cents"] is None

        ledger = validate_unpaginated(api.get_grant(grant.grant_id, fiscal_headers))
        assert_ledger(ledger, 0, k.INDIRECT_RATE_LOW, 0, 0, ALLOCATION_CENTS)

    def test_certification_is_refused_while_the_charged_program_is_still_a_draft(
        self, api: CteApiClient, build: Builder, fiscal_headers
    ) -> None:
        """PRD §3.7: "The charged program of study must be in `approval_status` `STATE_APPROVED`, or the answer is `ERR_POS_NOT_APPROVED`."

        PRD §3.1: "On creation the new program lands in `approval_status` `DRAFT` and `clna_phase` `NOT_STARTED`, its `version` is 1, its `authored_by_user_id` is set to the acting `X-User-ID`, its `alignment_index` and `alignment_index_variant` are both null, its `narrative_url` is null, its `open_finding_codes` list is empty, its `federal_reporting_eligible` flag is false, its `approval_round` is 0, its `clna_certified_by_user_id`, `clna_certified_on` and `clna_expires_on` are all null, and `secondary_credit_total`, `postsecondary_credit_total` and `articulated_credit_total` are all 0."

        Design: Difficulty/cross_entity_state_dependency/expenditure_certification_reads_the_program_of_study_approval_state
        """
        program = build.program(
            "47.0605",
            stop_at=STOP_CLNA_CERTIFIED,
            cluster=k.CLUSTER_ADVANCED_MANUFACTURING,
            title="Automotive Collision Repair",
        )
        observed = validate_unpaginated(
            api.get_program(program.program_id, users.headers(users.DIRECTOR))
        )
        assert observed["approval_status"] == k.APPROVAL_DRAFT
        assert observed["clna_phase"] == k.CLNA_CERTIFIED

        grant = build.grant(allocation_cents=ALLOCATION_CENTS)
        expenditure = build.expenditure(
            grant.grant_id, program.program_id, k.CATEGORY_CONSUMABLE, 100000
        )

        refused = api.certify_allowability(
            expenditure["id"],
            f.certification_payload(k.DECISION_CERTIFY),
            fiscal_headers,
        )
        validate_error(refused, errors.ERR_POS_NOT_APPROVED)

        untouched = validate_unpaginated(
            api.get_expenditure(expenditure["id"], fiscal_headers)
        )
        assert untouched["status"] == k.EXP_REQUESTED

    def test_the_identical_certification_succeeds_once_the_state_approves_the_program(
        self, api: CteApiClient, build: Builder, fiscal_headers, reviewer_headers
    ) -> None:
        """PRD §3.7: "The charged program of study must be in `approval_status` `STATE_APPROVED`, or the answer is `ERR_POS_NOT_APPROVED`."

        PRD §3.7: "`EQUIPMENT`, `CONSUMABLE` and `ADMINISTRATION` are each reimbursed at a share of 0.8500." "The approved amount of a line is its `gross_cents` multiplied by its `federal_share_pct`, rounded half-up to whole cents — and that rounding happens **here, once, per expenditure line**."

        PRD §3.7: "Step three computes `indirect_pool_cents` as the direct total multiplied by `indirect_rate`, rounded half-up to whole cents, computed from scratch rather than incremented against its previous value. Step four sets `obligated_cents` to `direct_obligated_cents` plus `indirect_pool_cents`. Step five sets `remaining_cents` to `allocation_cents` minus `obligated_cents`."

        Design: Difficulty/cross_entity_state_dependency/expenditure_certification_reads_the_program_of_study_approval_state
        """
        program = build.program(
            "47.0606",
            stop_at=STOP_COMMITTEE_REVIEW,
            cluster=k.CLUSTER_ADVANCED_MANUFACTURING,
            title="Automotive Diagnostics",
        )
        grant = build.grant(allocation_cents=ALLOCATION_CENTS)
        expenditure = build.expenditure(
            grant.grant_id, program.program_id, k.CATEGORY_CONSUMABLE, 100000
        )

        refused = api.certify_allowability(
            expenditure["id"],
            f.certification_payload(k.DECISION_CERTIFY),
            fiscal_headers,
        )
        validate_error(refused, errors.ERR_POS_NOT_APPROVED)

        approved = validate_unpaginated(
            api.state_approve(
                program.program_id,
                f.state_approve_payload(approval_note="Approved."),
                reviewer_headers,
            )
        )
        assert approved["approval_status"] == k.APPROVAL_STATE_APPROVED

        certified = validate_unpaginated(
            api.certify_allowability(
                expenditure["id"],
                f.certification_payload(k.DECISION_CERTIFY),
                fiscal_headers,
            )
        )
        assert certified["status"] == k.EXP_CERTIFIED
        assert_cents(certified["approved_cents"], 85000, "approved_cents")
        assert_rate(
            certified["federal_share_pct"],
            k.FEDERAL_SHARE_BY_CATEGORY[k.CATEGORY_CONSUMABLE],
            "federal_share_pct",
        )

        ledger = validate_unpaginated(api.get_grant(grant.grant_id, fiscal_headers))
        assert_ledger(ledger, 85000, k.INDIRECT_RATE_LOW, 6902, 91902, 4908098)


class TestCommitteeReviewIsReachedOnlyThroughAPassingEndorsement:
    """A submitted program advances only on a meeting that votes it through."""

    @staticmethod
    def _submitted_program_with_two_endorsement_meetings(
        build: Builder, cip_code: str, title: str
    ):
        """Author a SUBMITTED program and schedule two endorsement meetings."""
        program = build.program(
            cip_code,
            stop_at=STOP_SUBMITTED,
            cluster=k.CLUSTER_ADVANCED_MANUFACTURING,
            title=title,
        )
        committee = program.committee
        assert committee is not None
        first = build.schedule_meeting(
            committee.committee_id,
            committee.chair_member_id,
            k.AGENDA_POS_ENDORSEMENT,
            FIRST_ENDORSEMENT_INSTANT,
        )
        second = build.schedule_meeting(
            committee.committee_id,
            committee.chair_member_id,
            k.AGENDA_POS_ENDORSEMENT,
            SECOND_ENDORSEMENT_INSTANT,
        )
        return program, committee, first, second

    def test_a_quorate_meeting_that_votes_the_program_down_leaves_it_in_submitted(
        self, api: CteApiClient, build: Builder, director_headers
    ) -> None:
        """PRD §3.3: "`endorsement_passed` is a stricter reading of the same figures: it is true only when `quorum_met` is true, `vote_yes` is strictly greater than `vote_no`, and `vote_yes` plus `vote_no` is no greater than `eligible_attendee_count`."

        PRD §3.3: "A filing without an `amendment_reason` moves the meeting `SCHEDULED → FINALIZED`, writing `held_at`, `attendee_member_ids`, `vote_yes`, `vote_no` and `minutes_url` from the request and recomputing `eligible_attendee_count`, `employer_attendee_count`, `quorum_met` and `endorsement_passed`."

        PRD §3.3: "When the meeting's `agenda_kind` is `POS_ENDORSEMENT`, the recomputed `endorsement_passed` is true, and the owning committee's program of study is sitting in `approval_status` `SUBMITTED`, that program transitions `SUBMITTED → COMMITTEE_REVIEW` and its `version` increments as well."

        Design: Difficulty/cross_entity_state_dependency/program_reaches_committee_review_only_through_passing_endorsement_minutes
        """
        program, committee, first, _second = (
            self._submitted_program_with_two_endorsement_meetings(
                build, "15.1301", "Engineering Design and Drafting"
            )
        )

        filed = validate_unpaginated(
            api.file_minutes(
                first["id"],
                f.minutes_payload(
                    FIRST_ENDORSEMENT_INSTANT,
                    committee.member_ids,
                    1,
                    2,
                    minutes_url=FAILED_ENDORSEMENT_MINUTES_URL,
                ),
                users.chair_headers(committee.chair_member_id),
            )
        )
        assert_quorum_figures(filed, 3, 2, True, False)
        assert filed["minutes_status"] == k.MINUTES_FINALIZED

        stranded = validate_unpaginated(
            api.get_program(program.program_id, director_headers)
        )
        assert stranded["approval_status"] == k.APPROVAL_SUBMITTED

    def test_a_tied_endorsement_vote_does_not_advance_the_program(
        self, api: CteApiClient, build: Builder, director_headers
    ) -> None:
        """PRD §3.3: "`endorsement_passed` is a stricter reading of the same figures: it is true only when `quorum_met` is true, `vote_yes` is strictly greater than `vote_no`, and `vote_yes` plus `vote_no` is no greater than `eligible_attendee_count`. A tied vote does not endorse."

        PRD §3.3: "When the meeting's `agenda_kind` is `POS_ENDORSEMENT`, the recomputed `endorsement_passed` is true, and the owning committee's program of study is sitting in `approval_status` `SUBMITTED`, that program transitions `SUBMITTED → COMMITTEE_REVIEW` and its `version` increments as well."

        Design: Difficulty/cross_entity_state_dependency/program_reaches_committee_review_only_through_passing_endorsement_minutes
        """
        program, committee, first, _second = (
            self._submitted_program_with_two_endorsement_meetings(
                build, "15.1302", "Engineering Technology"
            )
        )

        filed = validate_unpaginated(
            api.file_minutes(
                first["id"],
                f.minutes_payload(
                    FIRST_ENDORSEMENT_INSTANT,
                    committee.member_ids,
                    1,
                    1,
                    minutes_url=TIED_ENDORSEMENT_MINUTES_URL,
                ),
                users.chair_headers(committee.chair_member_id),
            )
        )
        assert_quorum_figures(filed, 3, 2, True, False)
        assert filed["minutes_status"] == k.MINUTES_FINALIZED

        stranded = validate_unpaginated(
            api.get_program(program.program_id, director_headers)
        )
        assert stranded["approval_status"] == k.APPROVAL_SUBMITTED

    def test_state_approval_is_refused_while_the_endorsement_vote_has_failed(
        self, api: CteApiClient, build: Builder, reviewer_headers
    ) -> None:
        """PRD §3.4: "Approving it moves `COMMITTEE_REVIEW → STATE_APPROVED`, optionally recording an `approval_note`."

        PRD §2.8: "When an action endpoint asks a record to make a transition its current state does not declare, the request is refused at priority 9 with the code belonging to that axis: `ERR_INVALID_APPROVAL_TRANSITION` for `approval_status`"

        PRD §3.4: "From `SUBMITTED`, the program waits on its advisory committee. A quorate `POS_ENDORSEMENT` meeting whose vote passes is what advances it to `COMMITTEE_REVIEW`, as described in §3.3; no operator drives that edge directly."

        Design: Difficulty/cross_entity_state_dependency/program_reaches_committee_review_only_through_passing_endorsement_minutes
        """
        program, committee, first, _second = (
            self._submitted_program_with_two_endorsement_meetings(
                build, "15.1303", "Engineering Drafting Systems"
            )
        )
        build.file_minutes(
            first["id"],
            committee.chair_member_id,
            FIRST_ENDORSEMENT_INSTANT,
            committee.member_ids,
            1,
            2,
            minutes_url=FAILED_ENDORSEMENT_MINUTES_URL,
        )

        refused = api.state_approve(
            program.program_id,
            f.state_approve_payload(approval_note="Premature."),
            reviewer_headers,
        )
        validate_error(refused, errors.ERR_INVALID_APPROVAL_TRANSITION)

    def test_a_later_passing_endorsement_advances_the_program_to_committee_review(
        self, api: CteApiClient, build: Builder, director_headers
    ) -> None:
        """PRD §3.3: "When the meeting's `agenda_kind` is `POS_ENDORSEMENT`, the recomputed `endorsement_passed` is true, and the owning committee's program of study is sitting in `approval_status` `SUBMITTED`, that program transitions `SUBMITTED → COMMITTEE_REVIEW` and its `version` increments as well."

        PRD §3.3: "`endorsement_passed` is a stricter reading of the same figures: it is true only when `quorum_met` is true, `vote_yes` is strictly greater than `vote_no`, and `vote_yes` plus `vote_no` is no greater than `eligible_attendee_count`."

        PRD §3.4: "An accepted submission increments `approval_round` by 1 — the counter is the district's audit trail of how many times the packet has gone up — writes the supplied `narrative_url` onto the program, clears `open_finding_codes` back to an empty list, and recomputes the alignment index under the `PROVISIONAL_LOCAL` variant, writing `alignment_index`, setting `alignment_index_variant` to `PROVISIONAL_LOCAL`, and refreshing `secondary_credit_total`, `postsecondary_credit_total` and `articulated_credit_total`."

        Design: Difficulty/cross_entity_state_dependency/program_reaches_committee_review_only_through_passing_endorsement_minutes
        """
        program, committee, first, second = (
            self._submitted_program_with_two_endorsement_meetings(
                build, "15.1304", "Engineering Design Studio"
            )
        )
        build.file_minutes(
            first["id"],
            committee.chair_member_id,
            FIRST_ENDORSEMENT_INSTANT,
            committee.member_ids,
            1,
            2,
            minutes_url=FAILED_ENDORSEMENT_MINUTES_URL,
        )

        passed = validate_unpaginated(
            api.file_minutes(
                second["id"],
                f.minutes_payload(
                    SECOND_ENDORSEMENT_INSTANT,
                    committee.member_ids,
                    3,
                    0,
                    minutes_url=PASSED_ENDORSEMENT_MINUTES_URL,
                ),
                users.chair_headers(committee.chair_member_id),
            )
        )
        assert_quorum_figures(passed, 3, 2, True, True)

        advanced = validate_unpaginated(
            api.get_program(program.program_id, director_headers)
        )
        assert advanced["approval_status"] == k.APPROVAL_COMMITTEE_REVIEW
        assert advanced["approval_round"] == 1


class TestCapitalEquipmentCertificationReadsTheReviewMinutes:
    """A capital equipment line waits on the equipment-review meeting's minutes."""

    def test_capital_equipment_certification_is_refused_while_the_review_is_unminuted(
        self, api: CteApiClient, build: Builder, fiscal_headers
    ) -> None:
        """PRD §3.7: "An `EQUIPMENT` line whose `unit_cost_cents` reaches the capital threshold of 500,000 cents — five thousand dollars per unit — additionally requires capital review: a meeting on the program's `ACTIVE` advisory committee with `agenda_kind` `EQUIPMENT_REVIEW`, `minutes_status` of `FINALIZED` or `AMENDED`, `quorum_met` true, and a `held_at` instant no earlier than 365 days before the current logical clock reading. Missing that evidence is `ERR_CAPITAL_REVIEW_REQUIRED`."

        PRD §3.3: "The new meeting begins with `minutes_status` `SCHEDULED`, an empty `attendee_member_ids` list, `vote_yes` and `vote_no` both at 0, `quorum_met` and `endorsement_passed` both false, and `held_at`, `minutes_url` and `amendment_reason` all null; scheduling increments the owning committee's `version`."

        PRD §3.7: "The stored row takes its `grant_award_id` from the addressed award, records `requested_by_user_id` from the acting `X-User-ID`, opens in `status` `REQUESTED`, computes `gross_cents` as `unit_cost_cents` multiplied by `quantity`, sets `federal_share_pct` from the category table below, leaves `approved_cents` null until certification, leaves `certified_by_user_id`, `finding_code`, `obligation_reference` and `void_reason` null, and increments the award's `version`."

        Design: Difficulty/cross_entity_state_dependency/capital_equipment_certification_reads_the_committee_meeting_minutes_state
        """
        program = build.program(
            "48.0501",
            stop_at=STOP_STATE_APPROVED,
            cluster=k.CLUSTER_ADVANCED_MANUFACTURING,
            title="Machine Tool Technology",
        )
        committee = program.committee
        assert committee is not None
        review = build.schedule_meeting(
            committee.committee_id,
            committee.chair_member_id,
            k.AGENDA_EQUIPMENT_REVIEW,
            EQUIPMENT_REVIEW_INSTANT,
        )
        assert review["minutes_status"] == k.MINUTES_SCHEDULED

        grant = build.grant(allocation_cents=ALLOCATION_CENTS)
        expenditure = build.expenditure(
            grant.grant_id,
            program.program_id,
            k.CATEGORY_EQUIPMENT,
            k.CAPITAL_THRESHOLD_CENTS,
            asset_tag="LATHE-77",
            description="Bench lathe",
        )

        refused = api.certify_allowability(
            expenditure["id"],
            f.certification_payload(k.DECISION_CERTIFY),
            fiscal_headers,
        )
        validate_error(refused, errors.ERR_CAPITAL_REVIEW_REQUIRED)

        untouched = validate_unpaginated(
            api.get_expenditure(expenditure["id"], fiscal_headers)
        )
        assert untouched["status"] == k.EXP_REQUESTED
        assert untouched["approved_cents"] is None

        ledger = validate_unpaginated(api.get_grant(grant.grant_id, fiscal_headers))
        assert_ledger(ledger, 0, k.INDIRECT_RATE_LOW, 0, 0, ALLOCATION_CENTS)

    def test_the_identical_certification_succeeds_once_the_review_minutes_are_filed(
        self, api: CteApiClient, build: Builder, fiscal_headers
    ) -> None:
        """PRD §3.7: "An `EQUIPMENT` line whose `unit_cost_cents` reaches the capital threshold of 500,000 cents — five thousand dollars per unit — additionally requires capital review: a meeting on the program's `ACTIVE` advisory committee with `agenda_kind` `EQUIPMENT_REVIEW`, `minutes_status` of `FINALIZED` or `AMENDED`, `quorum_met` true, and a `held_at` instant no earlier than 365 days before the current logical clock reading. Missing that evidence is `ERR_CAPITAL_REVIEW_REQUIRED`."

        PRD §3.7: "`EQUIPMENT`, `CONSUMABLE` and `ADMINISTRATION` are each reimbursed at a share of 0.8500." "The approved amount of a line is its `gross_cents` multiplied by its `federal_share_pct`, rounded half-up to whole cents — and that rounding happens **here, once, per expenditure line**."

        PRD §3.7: "Step three computes `indirect_pool_cents` as the direct total multiplied by `indirect_rate`, rounded half-up to whole cents, computed from scratch rather than incremented against its previous value. Step four sets `obligated_cents` to `direct_obligated_cents` plus `indirect_pool_cents`. Step five sets `remaining_cents` to `allocation_cents` minus `obligated_cents`."

        Design: Difficulty/cross_entity_state_dependency/capital_equipment_certification_reads_the_committee_meeting_minutes_state
        """
        program = build.program(
            "48.0502",
            stop_at=STOP_STATE_APPROVED,
            cluster=k.CLUSTER_ADVANCED_MANUFACTURING,
            title="Machining and Fabrication",
        )
        committee = program.committee
        assert committee is not None
        review = build.schedule_meeting(
            committee.committee_id,
            committee.chair_member_id,
            k.AGENDA_EQUIPMENT_REVIEW,
            EQUIPMENT_REVIEW_INSTANT,
        )
        grant = build.grant(allocation_cents=ALLOCATION_CENTS)
        expenditure = build.expenditure(
            grant.grant_id,
            program.program_id,
            k.CATEGORY_EQUIPMENT,
            k.CAPITAL_THRESHOLD_CENTS,
            asset_tag="LATHE-78",
            description="Bench lathe",
        )

        refused = api.certify_allowability(
            expenditure["id"],
            f.certification_payload(k.DECISION_CERTIFY),
            fiscal_headers,
        )
        validate_error(refused, errors.ERR_CAPITAL_REVIEW_REQUIRED)

        minuted = validate_unpaginated(
            api.file_minutes(
                review["id"],
                f.minutes_payload(
                    EQUIPMENT_REVIEW_INSTANT,
                    committee.member_ids,
                    3,
                    0,
                    minutes_url=EQUIPMENT_MINUTES_URL,
                ),
                users.chair_headers(committee.chair_member_id),
            )
        )
        assert minuted["quorum_met"] is True
        assert minuted["minutes_status"] == k.MINUTES_FINALIZED

        certified = validate_unpaginated(
            api.certify_allowability(
                expenditure["id"],
                f.certification_payload(k.DECISION_CERTIFY),
                fiscal_headers,
            )
        )
        assert certified["status"] == k.EXP_CERTIFIED
        assert_cents(certified["approved_cents"], 425000, "approved_cents")
        assert_rate(
            certified["federal_share_pct"],
            k.FEDERAL_SHARE_BY_CATEGORY[k.CATEGORY_EQUIPMENT],
            "federal_share_pct",
        )

        ledger = validate_unpaginated(api.get_grant(grant.grant_id, fiscal_headers))
        assert_ledger(ledger, 425000, k.INDIRECT_RATE_LOW, 34510, 459510, 4540490)

    def test_equipment_one_cent_below_the_threshold_needs_no_review_meeting(
        self, api: CteApiClient, build: Builder, fiscal_headers
    ) -> None:
        """PRD §3.7: "An `EQUIPMENT` line whose `unit_cost_cents` reaches the capital threshold of 500,000 cents — five thousand dollars per unit — additionally requires capital review: a meeting on the program's `ACTIVE` advisory committee with `agenda_kind` `EQUIPMENT_REVIEW`, `minutes_status` of `FINALIZED` or `AMENDED`, `quorum_met` true, and a `held_at` instant no earlier than 365 days before the current logical clock reading. Missing that evidence is `ERR_CAPITAL_REVIEW_REQUIRED`."

        PRD §3.7: "`EQUIPMENT`, `CONSUMABLE` and `ADMINISTRATION` are each reimbursed at a share of 0.8500." "The approved amount of a line is its `gross_cents` multiplied by its `federal_share_pct`, rounded half-up to whole cents — and that rounding happens **here, once, per expenditure line**."

        Design: Difficulty/cross_entity_state_dependency/capital_equipment_certification_reads_the_committee_meeting_minutes_state
        """
        program = build.program(
            "48.0503",
            stop_at=STOP_STATE_APPROVED,
            cluster=k.CLUSTER_ADVANCED_MANUFACTURING,
            title="Precision Machining",
        )
        grant = build.grant(allocation_cents=ALLOCATION_CENTS)
        expenditure = build.expenditure(
            grant.grant_id,
            program.program_id,
            k.CATEGORY_EQUIPMENT,
            k.CAPITAL_THRESHOLD_CENTS - 1,
            asset_tag="MILL-11",
            description="Benchtop mill",
        )

        certified = validate_unpaginated(
            api.certify_allowability(
                expenditure["id"],
                f.certification_payload(k.DECISION_CERTIFY),
                fiscal_headers,
            )
        )
        assert certified["status"] == k.EXP_CERTIFIED
        assert_cents(certified["approved_cents"], 424999, "approved_cents")

        ledger = validate_unpaginated(api.get_grant(grant.grant_id, fiscal_headers))
        assert_ledger(ledger, 424999, k.INDIRECT_RATE_LOW, 34510, 459509, 4540491)

    def test_a_consumable_line_at_the_capital_price_needs_no_review_meeting(
        self, api: CteApiClient, build: Builder, fiscal_headers
    ) -> None:
        """PRD §3.7: "An `EQUIPMENT` line whose `unit_cost_cents` reaches the capital threshold of 500,000 cents — five thousand dollars per unit — additionally requires capital review: a meeting on the program's `ACTIVE` advisory committee with `agenda_kind` `EQUIPMENT_REVIEW`, `minutes_status` of `FINALIZED` or `AMENDED`, `quorum_met` true, and a `held_at` instant no earlier than 365 days before the current logical clock reading. Missing that evidence is `ERR_CAPITAL_REVIEW_REQUIRED`."

        PRD §3.7: "`EQUIPMENT`, `CONSUMABLE` and `ADMINISTRATION` are each reimbursed at a share of 0.8500." "The approved amount of a line is its `gross_cents` multiplied by its `federal_share_pct`, rounded half-up to whole cents — and that rounding happens **here, once, per expenditure line**."

        Design: Difficulty/cross_entity_state_dependency/capital_equipment_certification_reads_the_committee_meeting_minutes_state
        """
        program = build.program(
            "48.0504",
            stop_at=STOP_STATE_APPROVED,
            cluster=k.CLUSTER_ADVANCED_MANUFACTURING,
            title="Tool and Die Making",
        )
        grant = build.grant(allocation_cents=ALLOCATION_CENTS)
        expenditure = build.expenditure(
            grant.grant_id,
            program.program_id,
            k.CATEGORY_CONSUMABLE,
            k.CAPITAL_THRESHOLD_CENTS,
            description="Shop consumables",
        )

        certified = validate_unpaginated(
            api.certify_allowability(
                expenditure["id"],
                f.certification_payload(k.DECISION_CERTIFY),
                fiscal_headers,
            )
        )
        assert certified["status"] == k.EXP_CERTIFIED
        assert_cents(certified["approved_cents"], 425000, "approved_cents")

        ledger = validate_unpaginated(api.get_grant(grant.grant_id, fiscal_headers))
        assert_ledger(ledger, 425000, k.INDIRECT_RATE_LOW, 34510, 459510, 4540490)


class TestProgramSubmissionReadsTheInstructorPathway:
    """Submission waits on an educator the state has carried over the hour floor."""

    def test_submission_is_refused_while_the_only_instructor_is_still_provisional(
        self, api: CteApiClient, build: Builder, director_headers
    ) -> None:
        """PRD §3.4: "and at least one educator on the program must be in `status` `ELIGIBLE` after the lazy credential-lapse re-evaluation described in §2.12 has run (otherwise `ERR_NO_ELIGIBLE_INSTRUCTOR`)."

        PRD §3.5: "The `INDUSTRY_EXPERIENCE` route demands 4,000 verified hours — two full years at a 2,000-hour work year — before the instructor is certifiable."

        PRD §3.5: "When the total is still below the floor, the educator loops `PROVISIONAL → PROVISIONAL` — the hours accumulate, the `version` still increments, and the request succeeds; partial verification is progress, not failure."

        Design: Difficulty/cross_entity_state_dependency/program_submit_reads_the_educator_certification_pathway_state
        """
        program = build.program(
            "12.0503",
            stop_at=STOP_CLNA_CERTIFIED,
            cluster=k.CLUSTER_AGRICULTURE,
            title="Culinary Arts",
            claimed_industry_hours=4200,
            verified_industry_hours=k.INDUSTRY_HOURS_MIN - 1,
            credential_expires_on=LIVE_CREDENTIAL_EXPIRY,
        )
        educator = validate_unpaginated(
            api.get_educator(program.educator_id or "", director_headers)
        )
        assert educator["status"] == k.EDUCATOR_PROVISIONAL
        assert educator["verified_industry_hours"] == k.INDUSTRY_HOURS_MIN - 1

        refused = api.submit_program(
            program.program_id, f.submit_payload(NARRATIVE_URL), director_headers
        )
        validate_error(refused, errors.ERR_NO_ELIGIBLE_INSTRUCTOR)

        unmoved = validate_unpaginated(
            api.get_program(program.program_id, director_headers)
        )
        assert unmoved["approval_status"] == k.APPROVAL_DRAFT
        assert unmoved["approval_round"] == 0

    def test_the_identical_submission_succeeds_once_verified_hours_reach_the_floor(
        self, api: CteApiClient, build: Builder, director_headers, reviewer_headers
    ) -> None:
        """PRD §3.4: "and at least one educator on the program must be in `status` `ELIGIBLE` after the lazy credential-lapse re-evaluation described in §2.12 has run (otherwise `ERR_NO_ELIGIBLE_INSTRUCTOR`)."

        PRD §3.5: "An accepted tranche adds `verified_hours` to `verified_industry_hours` and increments the educator's `version`." "When the post-tranche total reaches the route's floor and the logical clock's date is on or before `credential_expires_on`, the educator moves `PROVISIONAL → ELIGIBLE`."

        PRD §3.4: "An accepted submission increments `approval_round` by 1 — the counter is the district's audit trail of how many times the packet has gone up — writes the supplied `narrative_url` onto the program, clears `open_finding_codes` back to an empty list, and recomputes the alignment index under the `PROVISIONAL_LOCAL` variant, writing `alignment_index`, setting `alignment_index_variant` to `PROVISIONAL_LOCAL`, and refreshing `secondary_credit_total`, `postsecondary_credit_total` and `articulated_credit_total`."

        PRD §3.1: "Under the `PROVISIONAL_LOCAL` variant the include set is courses whose `status` is `DRAFT` or `ACTIVE`, and the articulated sum ignores `articulation_verified` entirely, counting every qualifying postsecondary course's `articulated_credit_hours`."

        PRD §3.1: "Three factors follow. The **depth factor** is the smaller of 1.0 and the secondary credit subtotal divided by the four credit hours of secondary coursework a full pathway is expected to carry. The **bridge factor** is the smaller of 1.0 and the articulated subtotal divided by the larger of 1.0 and the postsecondary credit subtotal — the denominator floor of 1.0 keeps the factor finite when the postsecondary side is empty. The **breadth bonus** is 0.10 when the secondary credit subtotal is greater than zero, the postsecondary credit subtotal is greater than zero, and the articulated subtotal is at least the three articulated credit hours that mark a genuine dual-credit bridge; otherwise the bonus is 0.0. The weighted combination is then formed by multiplying the depth factor by 0.60, multiplying the bridge factor by 0.30, and adding the breadth bonus. That sum is clamped to at most 1.0, and the clamped value is rounded half-up to four decimal places exactly once."

        Design: Difficulty/cross_entity_state_dependency/program_submit_reads_the_educator_certification_pathway_state
        """
        program = build.program(
            "12.0504",
            stop_at=STOP_CLNA_CERTIFIED,
            cluster=k.CLUSTER_AGRICULTURE,
            title="Culinary Management",
            claimed_industry_hours=4200,
            verified_industry_hours=k.INDUSTRY_HOURS_MIN - 1,
            credential_expires_on=LIVE_CREDENTIAL_EXPIRY,
        )
        educator_id = program.educator_id or ""

        refused = api.submit_program(
            program.program_id, f.submit_payload(NARRATIVE_URL), director_headers
        )
        validate_error(refused, errors.ERR_NO_ELIGIBLE_INSTRUCTOR)

        topped_up = validate_unpaginated(
            api.verify_industry_hours(
                educator_id,
                f.verification_payload(201, k.SOURCE_EMPLOYER_LETTER),
                reviewer_headers,
            )
        )
        assert topped_up["status"] == k.EDUCATOR_ELIGIBLE
        assert topped_up["verified_industry_hours"] == 4200

        submitted = validate_unpaginated(
            api.submit_program(
                program.program_id, f.submit_payload(NARRATIVE_URL), director_headers
            )
        )
        assert submitted["approval_status"] == k.APPROVAL_SUBMITTED
        assert submitted["approval_round"] == 1
        assert submitted["alignment_index_variant"] == k.ALIGNMENT_VARIANT_PROVISIONAL_LOCAL
        assert_alignment_index(submitted["alignment_index"], 1.0)

    def test_submission_is_refused_while_the_only_instructor_credential_has_lapsed(
        self, api: CteApiClient, build: Builder, director_headers, reviewer_headers
    ) -> None:
        """PRD §3.5: "Credential lapse overrides both outcomes. Whenever the logical clock's date is strictly past `credential_expires_on`, the educator moves to `LAPSED` — from `PROVISIONAL` or `ELIGIBLE` alike — and this re-evaluation runs on verification filings, on program submission, and on educator reads."

        PRD §3.5: "An instructor whose credential has lapsed therefore cannot satisfy the instructor-coverage precondition on submission, which is exactly how a stale roster surfaces as `ERR_NO_ELIGIBLE_INSTRUCTOR`."

        PRD §3.5: "When the post-tranche total reaches the route's floor and the logical clock's date is on or before `credential_expires_on`, the educator moves `PROVISIONAL → ELIGIBLE`."

        PRD §3.4: "and at least one educator on the program must be in `status` `ELIGIBLE` after the lazy credential-lapse re-evaluation described in §2.12 has run (otherwise `ERR_NO_ELIGIBLE_INSTRUCTOR`)."

        Design: Difficulty/cross_entity_state_dependency/program_submit_reads_the_educator_certification_pathway_state
        """
        program = build.program(
            "12.0505",
            stop_at=STOP_CLNA_CERTIFIED,
            cluster=k.CLUSTER_AGRICULTURE,
            title="Baking and Pastry Arts",
            claimed_industry_hours=4200,
            verified_industry_hours=0,
            credential_expires_on=LAPSED_CREDENTIAL_EXPIRY,
        )

        refused = api.submit_program(
            program.program_id, f.submit_payload(NARRATIVE_URL), director_headers
        )
        validate_error(refused, errors.ERR_NO_ELIGIBLE_INSTRUCTOR)

        stale = validate_unpaginated(
            api.get_educator(program.educator_id or "", director_headers)
        )
        assert stale["status"] == k.EDUCATOR_LAPSED

        replacement = build.add_educator(
            program.program_id,
            full_name="Nia Farrow",
            certification_route=k.ROUTE_INDUSTRY_EXPERIENCE,
            claimed_industry_hours=4200,
            credential_expires_on=LIVE_CREDENTIAL_EXPIRY,
        )
        certified = validate_unpaginated(
            api.verify_industry_hours(
                replacement["id"],
                f.verification_payload(4200, k.SOURCE_EMPLOYER_LETTER),
                reviewer_headers,
            )
        )
        assert certified["status"] == k.EDUCATOR_ELIGIBLE

        submitted = validate_unpaginated(
            api.submit_program(
                program.program_id, f.submit_payload(NARRATIVE_URL), director_headers
            )
        )
        assert submitted["approval_status"] == k.APPROVAL_SUBMITTED
        assert submitted["approval_round"] == 1
