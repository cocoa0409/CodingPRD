"""Which transitions each lifecycle admits, and what it refuses.

The runner restarts the server before every individual test, so each starts
against an empty database with the logical clock at 2026-08-01T00:00:00Z.
"""

from test_helpers import (
    STOP_CLNA_CERTIFIED,
    STOP_STATE_APPROVED,
    assert_alignment_index,
    assert_cents,
    assert_ledger,
    assert_rate,
    assert_version_bumped_by,
    errors,
    f,
    k,
    users,
    validate_error,
    validate_paginated,
    validate_unpaginated,
)


class TestExpenditureForwardTransitions:
    """Certification and obligation are both forward edges with different reach."""

    def test_certifying_then_obligating_a_charge_moves_the_row_but_rebuilds_the_ledger_only_once(
        self, api, build, fiscal_headers
    ):
        """PRD §3.7: "The approved amount of a line is its `gross_cents` multiplied by its `federal_share_pct`, rounded half-up to whole cents — and that rounding happens **here, once, per expenditure line**." "`EQUIPMENT`, `CONSUMABLE` and `ADMINISTRATION` are each reimbursed at a share of 0.8500."

        PRD §3.7: "An accepted certification writes `federal_share_pct` and `approved_cents`, records `certified_by_user_id` from the acting `X-User-ID`, rebuilds the whole award ledger, and increments the `version` of both the expenditure and the award."

        PRD §3.7: "Step one computes `direct_obligated_cents` as the sum of `approved_cents` over the award's expenditures whose `status` is `CERTIFIED` or `OBLIGATED`; `REQUESTED`, `BLOCKED`, `DISALLOWED` and `VOIDED` rows are excluded, which is exactly what makes a void an exact compensation." "Step two selects `indirect_rate` by a tier lookup keyed **only** on that direct total: a direct total below 5,000,000 cents (fifty thousand dollars) takes the rate 0.0812; a direct total below 20,000,000 cents (two hundred thousand dollars) takes 0.0650; anything at or above 20,000,000 cents takes 0.0500." "Step three computes `indirect_pool_cents` as the direct total multiplied by `indirect_rate`, rounded half-up to whole cents, computed from scratch rather than incremented against its previous value. Step four sets `obligated_cents` to `direct_obligated_cents` plus `indirect_pool_cents`. Step five sets `remaining_cents` to `allocation_cents` minus `obligated_cents`."

        PRD §3.7: "Obligating a certified line records the purchase order. The request carries an `obligation_reference`, the expenditure moves `CERTIFIED → OBLIGATED`, and the logical clock's date must still be on or before the award's `obligation_window_end` or the call fails with `ERR_GRANT_WINDOW_CLOSED`. Obligation increments only the expenditure's `version`; because both `CERTIFIED` and `OBLIGATED` rows are countable, the ledger totals do not move."

        Design: Corner/state_machines/certify_then_obligate_walks_the_expenditure_through_both_forward_transitions
        """
        scenario = build.program("51.0801", stop_at=STOP_STATE_APPROVED)
        grant = build.grant(fiscal_year=2027, allocation_cents=5000000)
        requested = build.expenditure(
            grant.grant_id,
            scenario.program_id,
            k.CATEGORY_CONSUMABLE,
            100000,
            1,
            description="Clinic consumables",
        )

        certified = validate_unpaginated(
            api.certify_allowability(
                requested["id"],
                f.certification_payload(k.DECISION_CERTIFY),
                fiscal_headers,
            )
        )
        assert certified["status"] == k.EXP_CERTIFIED
        assert_cents(certified["approved_cents"], 85000, "approved_cents")
        assert certified["certified_by_user_id"] == users.FISCAL_OFFICER.user_id
        assert_rate(
            certified["federal_share_pct"],
            k.FEDERAL_SHARE_BY_CATEGORY[k.CATEGORY_CONSUMABLE],
            "federal_share_pct",
        )

        after_certification = validate_unpaginated(
            api.get_grant(grant.grant_id, fiscal_headers)
        )
        assert_ledger(
            after_certification,
            direct_cents=85000,
            indirect_rate=k.INDIRECT_RATE_LOW,
            pool_cents=6902,
            obligated_cents=91902,
            remaining_cents=4908098,
            admin_obligated_cents=0,
        )

        obligated = validate_unpaginated(
            api.obligate_expenditure(
                requested["id"], f.obligate_payload("PO-2027-0041"), fiscal_headers
            )
        )
        assert obligated["status"] == k.EXP_OBLIGATED
        assert obligated["obligation_reference"] == "PO-2027-0041"
        assert_cents(obligated["approved_cents"], 85000, "approved_cents")
        assert_version_bumped_by(certified["version"], obligated["version"], 1)

        after_obligation = validate_unpaginated(
            api.get_grant(grant.grant_id, fiscal_headers)
        )
        assert_ledger(
            after_obligation,
            direct_cents=85000,
            indirect_rate=k.INDIRECT_RATE_LOW,
            pool_cents=6902,
            obligated_cents=91902,
            remaining_cents=4908098,
            admin_obligated_cents=0,
        )
        assert after_obligation["version"] == after_certification["version"]


class TestNeedsAssessmentDocumentationGate:
    """Leaving stakeholder consultation needs two quorate documented meetings."""

    def test_one_quorate_stakeholder_meeting_does_not_open_the_gap_analysis_phase(
        self, api, build, director_headers
    ):
        """PRD §3.2: "`STAKEHOLDER_CONSULTATION → GAP_ANALYSIS` is the documentation gate. At least two committee meetings on the program's `ACTIVE` advisory committee must have `agenda_kind` `CLNA_STAKEHOLDER`, `minutes_status` of either `FINALIZED` or `AMENDED`, and a `quorum_met` value of true. A single qualifying meeting is not enough, and a meeting that convened without quorum does not count no matter how thorough its minutes; the shortfall reports as `ERR_CLNA_STAKEHOLDER_EVIDENCE_MISSING`."

        Design: Corner/state_machines/clna_advance_to_gap_analysis_without_two_quorate_stakeholder_meetings_is_refused
        """
        program = build.create_program("51.0801")
        committee_row = build.charter_committee(program["id"])
        committee = build.seat_roster(committee_row["id"])
        build.quorate_meeting(
            committee, k.AGENDA_CLNA_STAKEHOLDER, "2026-08-04T14:00:00.000Z"
        )
        second = build.schedule_meeting(
            committee.committee_id,
            committee.chair_member_id,
            k.AGENDA_CLNA_STAKEHOLDER,
            "2026-08-05T14:00:00.000Z",
        )
        build.advance_clna(program["id"], k.CLNA_DATA_COLLECTION)
        build.advance_clna(program["id"], k.CLNA_STAKEHOLDER_CONSULTATION)

        gap_payload = f.clna_advance_payload(
            k.CLNA_GAP_ANALYSIS, evidence_url="https://district.example/clna/gap.pdf"
        )
        validate_error(
            api.advance_clna(program["id"], gap_payload, director_headers),
            errors.ERR_CLNA_STAKEHOLDER_EVIDENCE_MISSING,
        )

        held = validate_unpaginated(api.get_program(program["id"], director_headers))
        assert held["clna_phase"] == k.CLNA_STAKEHOLDER_CONSULTATION

        filed = build.file_minutes(
            second["id"],
            committee.chair_member_id,
            "2026-08-05T14:00:00.000Z",
            committee.member_ids,
            3,
            0,
        )
        assert filed["minutes_status"] == k.MINUTES_FINALIZED
        assert filed["quorum_met"] is True

        advanced = validate_unpaginated(
            api.advance_clna(program["id"], gap_payload, director_headers)
        )
        assert advanced["clna_phase"] == k.CLNA_GAP_ANALYSIS
        assert advanced["clna_certified_on"] is None
        assert advanced["clna_expires_on"] is None


class TestUnallowableUseRuling:
    """Entertainment is never an allowable federal use."""

    def test_an_entertainment_line_refuses_certification_and_its_disallowal_leaves_the_award_alone(
        self, api, build, fiscal_headers
    ):
        """PRD §3.7: "The `category` must not be `ENTERTAINMENT`: entertainment is never an allowable federal use, so the only lawful ruling on such a line is `DISALLOW` with `finding_code` `ENTERTAINMENT_PROHIBITED`, and an attempt to certify one is `ERR_UNALLOWABLE_USE`."

        PRD §3.7: "`ENTERTAINMENT` carries a share of 0.0000 and, as described below, never reaches the point where that number matters."

        PRD §3.7: "A `DISALLOW` decision is the branch sibling and its side effects diverge sharply. It requires a non-null `finding_code` in the request, moves the expenditure `REQUESTED → DISALLOWED`, records that `finding_code` and `certified_by_user_id`, and **leaves `approved_cents` null**. No field of the grant award changes and the award's `version` is *not* incremented — a disallowed line never entered the ledger, so there is nothing to rebuild. Only the expenditure's `version` moves."

        Design: Corner/state_machines/entertainment_charges_can_only_be_disallowed_and_disallowal_leaves_the_ledger_alone
        """
        scenario = build.program("51.0801", stop_at=STOP_STATE_APPROVED)
        grant = build.grant(fiscal_year=2027, allocation_cents=5000000)
        requested = build.expenditure(
            grant.grant_id,
            scenario.program_id,
            k.CATEGORY_ENTERTAINMENT,
            40000,
            1,
            description="Program awards banquet",
        )
        assert requested["status"] == k.EXP_REQUESTED
        before = validate_unpaginated(api.get_grant(grant.grant_id, fiscal_headers))

        validate_error(
            api.certify_allowability(
                requested["id"],
                f.certification_payload(k.DECISION_CERTIFY),
                fiscal_headers,
            ),
            errors.ERR_UNALLOWABLE_USE,
        )

        disallowed = validate_unpaginated(
            api.certify_allowability(
                requested["id"],
                f.certification_payload(
                    k.DECISION_DISALLOW,
                    finding_code=k.FINDING_ENTERTAINMENT_PROHIBITED,
                ),
                fiscal_headers,
            )
        )
        assert disallowed["status"] == k.EXP_DISALLOWED
        assert disallowed["approved_cents"] is None
        assert disallowed["finding_code"] == k.FINDING_ENTERTAINMENT_PROHIBITED
        assert disallowed["certified_by_user_id"] == users.FISCAL_OFFICER.user_id
        assert_rate(
            disallowed["federal_share_pct"],
            k.FEDERAL_SHARE_BY_CATEGORY[k.CATEGORY_ENTERTAINMENT],
            "federal_share_pct",
        )
        assert_version_bumped_by(requested["version"], disallowed["version"], 1)

        after = validate_unpaginated(api.get_grant(grant.grant_id, fiscal_headers))
        assert after["version"] == before["version"]
        assert_ledger(
            after,
            direct_cents=0,
            indirect_rate=k.INDIRECT_RATE_LOW,
            pool_cents=0,
            obligated_cents=0,
            remaining_cents=5000000,
            admin_obligated_cents=0,
        )


class TestUndeclaredTransitions:
    """Each axis refuses an edge its current state does not declare."""

    def test_a_merely_requested_charge_can_neither_be_obligated_nor_voided(
        self, api, build, fiscal_headers
    ):
        """PRD §3.7: "Obligating a certified line records the purchase order. The request carries an `obligation_reference`, the expenditure moves `CERTIFIED → OBLIGATED`, and the logical clock's date must still be on or before the award's `obligation_window_end` or the call fails with `ERR_GRANT_WINDOW_CLOSED`."

        PRD §3.7: "Voiding is the compensating action and works from either `CERTIFIED → VOIDED` or `OBLIGATED → VOIDED`, with no state preconditions beyond being in one of those two statuses."

        PRD §2.8: "When an action endpoint asks a record to make a transition its current state does not declare, the request is refused at priority 9 with the code belonging to that axis: `ERR_INVALID_APPROVAL_TRANSITION` for `approval_status`, `ERR_INVALID_CLNA_PHASE_TRANSITION` for `clna_phase` (including a requested `to_phase` that is not the declared successor of the current phase), `ERR_INVALID_EXPENDITURE_STATE` for `Expenditure.status`, `ERR_INVALID_INDICATOR_STATE` for `PerformanceIndicator.status`, `ERR_INVALID_PLAN_STATE` for `ImprovementPlan.status`, `ERR_INVALID_MEETING_STATE` for `CommitteeMeeting.minutes_status`, and `ERR_INVALID_EDUCATOR_STATE` for `Educator.status`. All seven are HTTP 409."

        Design: Corner/state_machines/writes_from_a_state_that_declares_no_such_transition_are_rejected
        """
        scenario = build.program("51.0801", stop_at=STOP_STATE_APPROVED)
        grant = build.grant(fiscal_year=2027, allocation_cents=5000000)
        requested = build.expenditure(
            grant.grant_id, scenario.program_id, k.CATEGORY_CONSUMABLE, 100000, 1
        )
        assert requested["status"] == k.EXP_REQUESTED

        validate_error(
            api.obligate_expenditure(
                requested["id"], f.obligate_payload("PO-2027-0099"), fiscal_headers
            ),
            errors.ERR_INVALID_EXPENDITURE_STATE,
        )
        validate_error(
            api.void_expenditure(
                requested["id"],
                f.void_payload("Ordered in error before any ruling."),
                fiscal_headers,
            ),
            errors.ERR_INVALID_EXPENDITURE_STATE,
        )

        after = validate_unpaginated(
            api.get_expenditure(requested["id"], fiscal_headers)
        )
        assert after["status"] == k.EXP_REQUESTED
        assert after["obligation_reference"] is None
        assert after["void_reason"] is None
        assert after["approved_cents"] is None

    def test_the_needs_assessment_refuses_to_skip_straight_to_gap_analysis(
        self, api, build, director_headers
    ):
        """PRD §3.2: "Both a `CteDirector` and a `StateComplianceReviewer` may drive it, one phase at a time, by naming the target phase in a `to_phase` field and optionally attaching an `evidence_url` documenting the step. A `to_phase` that is not the declared successor of the program's current `clna_phase` is refused with `ERR_INVALID_CLNA_PHASE_TRANSITION`; each accepted advance increments the program's `version`."

        Design: Corner/state_machines/writes_from_a_state_that_declares_no_such_transition_are_rejected
        """
        program = build.create_program("51.0801")
        assert program["clna_phase"] == k.CLNA_NOT_STARTED

        validate_error(
            api.advance_clna(
                program["id"],
                f.clna_advance_payload(k.CLNA_GAP_ANALYSIS),
                director_headers,
            ),
            errors.ERR_INVALID_CLNA_PHASE_TRANSITION,
        )

        after = validate_unpaginated(api.get_program(program["id"], director_headers))
        assert after["clna_phase"] == k.CLNA_NOT_STARTED
        assert after["version"] == program["version"]

    def test_a_level_cannot_be_accepted_before_the_state_has_tabled_an_offer(
        self, api, build, director_headers
    ):
        """PRD §3.8: "The state opens the exchange: the first offer, tabled while `negotiation_round` is 0, moves the indicator `PROPOSED → NEGOTIATING`, and only a `StateComplianceReviewer` satisfies that opening edge — a director's attempt to open the exchange does not match any declared transition out of `PROPOSED` and is refused with `ERR_INVALID_INDICATOR_STATE`." "Accepting the standing offer moves `NEGOTIATING → AGREED` and may carry an `acceptance_note`."

        PRD §2.8: "One carve-out is deliberate. An indicator already in `ARBITRATED` is **not** mapped at priority 9 for a further negotiation offer or a level acceptance. Those two calls fall through to priority 30, where the spent negotiation budget is reported as `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` (HTTP 422). Every other call made against an `ARBITRATED` indicator is still handled at priority 9 in the ordinary way."

        Design: Corner/state_machines/writes_from_a_state_that_declares_no_such_transition_are_rejected
        """
        scenario = build.program("51.0801", stop_at=STOP_STATE_APPROVED)
        indicator = build.indicator(
            scenario.program_id, k.INDICATOR_4S1_CREDENTIAL, baseline_pct=90.00
        )
        assert indicator["status"] == k.PI_PROPOSED

        validate_error(
            api.accept_level(
                indicator["id"],
                f.accept_level_payload(acceptance_note="Agreed as proposed."),
                director_headers,
            ),
            errors.ERR_INVALID_INDICATOR_STATE,
        )

        after = validate_unpaginated(
            api.get_indicator(indicator["id"], director_headers)
        )
        assert after["status"] == k.PI_PROPOSED
        assert after["negotiated_level_pct"] is None
        assert after["met_threshold_pct"] is None
        assert after["negotiation_round"] == 0

    def test_an_improvement_plan_cannot_be_drafted_against_an_unescalated_indicator(
        self, api, build, director_headers
    ):
        """PRD §3.9: "An escalated indicator demands a local improvement plan, and only a `CteDirector` may draft one. Drafting is admitted only while the target indicator's `status` is `IMPROVEMENT_REQUIRED`; any other status is `ERR_INVALID_INDICATOR_STATE`."

        PRD §2.8: "Two cross-entity state gates are evaluated at this same priority rather than later. Drafting an improvement plan requires the target `PerformanceIndicator` to be in `IMPROVEMENT_REQUIRED`, and accepting an improvement plan requires the plan's parent indicator to be in `IMPROVEMENT_REQUIRED`; both raise `ERR_INVALID_INDICATOR_STATE`."

        Design: Corner/state_machines/writes_from_a_state_that_declares_no_such_transition_are_rejected
        """
        scenario = build.program("51.0801", stop_at=STOP_STATE_APPROVED)
        indicator = build.agreed_indicator(
            scenario.program_id, k.INDICATOR_4S1_CREDENTIAL, 80.00
        )
        assert indicator["status"] == k.PI_AGREED

        validate_error(
            api.draft_plan(
                indicator["id"],
                f.plan_payload(f.three_milestones()),
                director_headers,
            ),
            errors.ERR_INVALID_INDICATOR_STATE,
        )

        plans, meta = validate_paginated(api.list_plans(director_headers))
        assert plans == []
        assert meta["total_count"] == 0


class TestTerminalStates:
    """Two lifecycles end for good, and both refuse everything afterwards."""

    def test_amended_minutes_admit_no_third_filing(self, api, build):
        """PRD §3.3: "A filing without an `amendment_reason` moves the meeting `SCHEDULED → FINALIZED`, writing `held_at`, `attendee_member_ids`, `vote_yes`, `vote_no` and `minutes_url` from the request and recomputing `eligible_attendee_count`, `employer_attendee_count`, `quorum_met` and `endorsement_passed`. A filing that carries a non-null `amendment_reason` moves the meeting `FINALIZED → AMENDED`, recording the reason, overwriting `attendee_member_ids`, `vote_yes`, `vote_no` and `minutes_url`, and recomputing `quorum_met` and `endorsement_passed` on the amended figures — the amended attendance must itself satisfy quorum. `AMENDED` admits nothing further, and an amendment filed against a meeting still in `SCHEDULED` is refused; both are `ERR_INVALID_MEETING_STATE`."

        PRD §3.3: "`endorsement_passed` is a stricter reading of the same figures: it is true only when `quorum_met` is true, `vote_yes` is strictly greater than `vote_no`, and `vote_yes` plus `vote_no` is no greater than `eligible_attendee_count`. A tied vote does not endorse."

        Design: Corner/state_machines/amended_minutes_and_lapsed_educators_admit_no_further_writes
        """
        program = build.create_program("51.0801")
        committee_row = build.charter_committee(program["id"])
        committee = build.seat_roster(committee_row["id"])
        chair_headers = users.chair_headers(committee.chair_member_id)
        meeting = build.schedule_meeting(
            committee.committee_id,
            committee.chair_member_id,
            k.AGENDA_CLNA_STAKEHOLDER,
            "2026-08-04T14:00:00.000Z",
        )

        finalized = build.file_minutes(
            meeting["id"],
            committee.chair_member_id,
            "2026-08-04T14:00:00.000Z",
            committee.member_ids,
            3,
            0,
        )
        assert finalized["minutes_status"] == k.MINUTES_FINALIZED

        amended = build.file_minutes(
            meeting["id"],
            committee.chair_member_id,
            "2026-08-04T14:00:00.000Z",
            committee.member_ids,
            2,
            1,
            minutes_url="https://district.example/minutes-rev-1.pdf",
            amendment_reason="Vote tally corrected against the signed sheet.",
        )
        assert amended["minutes_status"] == k.MINUTES_AMENDED
        assert amended["quorum_met"] is True
        assert amended["endorsement_passed"] is True

        validate_error(
            api.file_minutes(
                meeting["id"],
                f.minutes_payload(
                    "2026-08-04T14:00:00.000Z",
                    committee.member_ids,
                    3,
                    0,
                    minutes_url="https://district.example/minutes-rev-2.pdf",
                    amendment_reason="A second correction of the same minutes.",
                ),
                chair_headers,
            ),
            errors.ERR_INVALID_MEETING_STATE,
        )

        after = validate_unpaginated(api.get_meeting(meeting["id"], chair_headers))
        assert after["minutes_status"] == k.MINUTES_AMENDED
        assert after["vote_yes"] == 2
        assert after["vote_no"] == 1
        assert after["amendment_reason"] == "Vote tally corrected against the signed sheet."

    def test_a_lapsed_educator_admits_no_further_hour_verification(
        self, api, build, reviewer_headers
    ):
        """PRD §3.5: "The `INDUSTRY_EXPERIENCE` route demands 4,000 verified hours — two full years at a 2,000-hour work year — before the instructor is certifiable." "When the post-tranche total reaches the route's floor and the logical clock's date is on or before `credential_expires_on`, the educator moves `PROVISIONAL → ELIGIBLE`."

        PRD §3.5: "Credential lapse overrides both outcomes. Whenever the logical clock's date is strictly past `credential_expires_on`, the educator moves to `LAPSED` — from `PROVISIONAL` or `ELIGIBLE` alike — and this re-evaluation runs on verification filings, on program submission, and on educator reads. `LAPSED` is terminal: a verification attempted against a `LAPSED` educator is refused with `ERR_INVALID_EDUCATOR_STATE`."

        Design: Corner/state_machines/amended_minutes_and_lapsed_educators_admit_no_further_writes
        """
        build.set_clock("2026-07-01T00:00:00Z")
        program = build.create_program("51.0801")
        educator = build.add_educator(
            program["id"],
            full_name="Dana Ruiz",
            certification_route=k.ROUTE_INDUSTRY_EXPERIENCE,
            claimed_industry_hours=5000,
            credential_expires_on="2026-07-31",
        )
        eligible = build.verify_hours(educator["id"], 4200)
        assert eligible["status"] == k.EDUCATOR_ELIGIBLE
        assert eligible["verified_industry_hours"] == 4200

        build.set_clock("2026-08-01T00:00:00Z")

        lapsed = validate_unpaginated(
            api.get_educator(educator["id"], reviewer_headers)
        )
        assert lapsed["status"] == k.EDUCATOR_LAPSED
        assert lapsed["verified_industry_hours"] == 4200

        validate_error(
            api.verify_industry_hours(
                educator["id"],
                f.verification_payload(100, k.SOURCE_EMPLOYER_LETTER),
                reviewer_headers,
            ),
            errors.ERR_INVALID_EDUCATOR_STATE,
        )

        after = validate_unpaginated(api.get_educator(educator["id"], reviewer_headers))
        assert after["status"] == k.EDUCATOR_LAPSED
        assert after["verified_industry_hours"] == 4200


class TestApprovalReplay:
    """State approval is an edge out of committee review, not out of itself."""

    def test_approving_an_already_approved_program_a_second_time_is_refused(
        self, api, build, reviewer_headers
    ):
        """PRD §3.4: "Approving it moves `COMMITTEE_REVIEW → STATE_APPROVED`, optionally recording an `approval_note`."

        PRD §3.4: "State approval then does four things. It overwrites `alignment_index` with the `FEDERAL_CERTIFIED` result, sets `alignment_index_variant` to `FEDERAL_CERTIFIED`, and overwrites all three credit subtotals with that variant's sums. It sets `federal_reporting_eligible` to true — this flag is true exactly while `approval_status` is `STATE_APPROVED`, and it is what determines whether the program appears in the federal Perkins submission. It clears `open_finding_codes`. And it increments the program's `version`."

        PRD §3.4: "An accepted submission increments `approval_round` by 1 — the counter is the district's audit trail of how many times the packet has gone up — writes the supplied `narrative_url` onto the program, clears `open_finding_codes` back to an empty list, and recomputes the alignment index under the `PROVISIONAL_LOCAL` variant, writing `alignment_index`, setting `alignment_index_variant` to `PROVISIONAL_LOCAL`, and refreshing `secondary_credit_total`, `postsecondary_credit_total` and `articulated_credit_total`."

        PRD §2.8: "When an action endpoint asks a record to make a transition its current state does not declare, the request is refused at priority 9 with the code belonging to that axis: `ERR_INVALID_APPROVAL_TRANSITION` for `approval_status`, `ERR_INVALID_CLNA_PHASE_TRANSITION` for `clna_phase` (including a requested `to_phase` that is not the declared successor of the current phase), `ERR_INVALID_EXPENDITURE_STATE` for `Expenditure.status`, `ERR_INVALID_INDICATOR_STATE` for `PerformanceIndicator.status`, `ERR_INVALID_PLAN_STATE` for `ImprovementPlan.status`, `ERR_INVALID_MEETING_STATE` for `CommitteeMeeting.minutes_status`, and `ERR_INVALID_EDUCATOR_STATE` for `Educator.status`. All seven are HTTP 409."

        Design: Corner/state_machines/a_second_state_approve_on_an_already_approved_program_is_rejected
        """
        scenario = build.program("51.0801", stop_at=STOP_STATE_APPROVED)
        approved = validate_unpaginated(
            api.get_program(scenario.program_id, reviewer_headers)
        )
        assert approved["approval_status"] == k.APPROVAL_STATE_APPROVED
        assert approved["alignment_index_variant"] == k.ALIGNMENT_VARIANT_FEDERAL_CERTIFIED
        assert approved["federal_reporting_eligible"] is True
        assert approved["approval_round"] == 1
        assert approved["open_finding_codes"] == []

        validate_error(
            api.state_approve(
                scenario.program_id,
                f.state_approve_payload(approval_note="Approving a second time."),
                reviewer_headers,
            ),
            errors.ERR_INVALID_APPROVAL_TRANSITION,
        )

        after = validate_unpaginated(
            api.get_program(scenario.program_id, reviewer_headers)
        )
        assert after["approval_status"] == k.APPROVAL_STATE_APPROVED
        assert after["alignment_index_variant"] == k.ALIGNMENT_VARIANT_FEDERAL_CERTIFIED
        assert_alignment_index(after["alignment_index"], approved["alignment_index"])
        assert after["approval_round"] == 1
        assert after["federal_reporting_eligible"] is True
        assert after["version"] == approved["version"]


class TestNeedsAssessmentCycle:
    """Neither program axis is terminal: a lapsed assessment can be rebuilt."""

    def test_an_expired_assessment_reopens_into_data_collection_and_then_needs_fresh_labor_market_data(
        self, api, build, director_headers
    ):
        """PRD §3.2: "On success the server writes `clna_certified_by_user_id` from the acting `X-User-ID`, sets `clna_certified_on` to the logical clock's current date, and sets `clna_expires_on` to that date plus 730 days — a certified needs assessment is good for two years and not a day more."

        PRD §2.12: "The first is needs-assessment expiry. Whenever the logical clock's date is strictly past a program's `clna_expires_on` and that program's `clna_phase` is still `CERTIFIED`, the phase moves `CERTIFIED → EXPIRED` and the program's `version` increments. This re-evaluation runs at the start of every write addressed to that program of study and at the start of expenditure allowability certification; retrieving a single program of study likewise refreshes it. No request field can move this edge in either direction."

        PRD §3.2: "A district recovers by re-opening the assessment: advancing `to_phase` to `DATA_COLLECTION` is admitted from both `CERTIFIED` and `EXPIRED`, and that re-open clears `clna_certified_on`, `clna_expires_on` and `clna_certified_by_user_id` back to null so that the four-phase walk must be completed afresh."

        PRD §3.2: "Leaving data collection for `DATA_COLLECTION → STAKEHOLDER_CONSULTATION` imposes the freshness rule: the labor-market dataset behind the assessment may be at most two years old, meaning the difference between the logical clock's date and `labor_market_data_asof` must be no more than 730 days. A dataset older than that is refused with `ERR_LABOR_MARKET_DATA_STALE`."

        PRD §3.1: "Descriptive attributes remain amendable while the program has not yet been approved. A director may revise any of `title`, `cluster` or `labor_market_data_asof` on a program whose `approval_status` is anything other than `STATE_APPROVED`; the amendment increments the program's `version`."

        PRD §2.8: "Neither axis constrains the other's shape: a program may sit in `STATE_APPROVED` while its `clna_phase` moves from `CERTIFIED` to `EXPIRED`, and it may sit in `DRAFT` while its `clna_phase` reaches `CERTIFIED`. Neither axis has a terminal state — both are cyclic."

        Design: Corner/state_machines/an_expired_clna_re_enters_data_collection_and_needs_fresh_labor_market_data
        """
        scenario = build.program(
            "51.0801",
            stop_at=STOP_CLNA_CERTIFIED,
            labor_market_data_asof="2026-03-01",
        )
        certified = validate_unpaginated(
            api.get_program(scenario.program_id, director_headers)
        )
        assert certified["clna_phase"] == k.CLNA_CERTIFIED
        assert certified["clna_certified_on"] == "2026-08-01"
        assert certified["clna_expires_on"] == "2028-07-31"
        assert certified["approval_status"] == k.APPROVAL_DRAFT

        build.set_clock("2028-08-01T00:00:00Z")

        expired = validate_unpaginated(
            api.get_program(scenario.program_id, director_headers)
        )
        assert expired["clna_phase"] == k.CLNA_EXPIRED
        assert expired["clna_expires_on"] == "2028-07-31"
        assert expired["approval_status"] == k.APPROVAL_DRAFT

        reopened = validate_unpaginated(
            api.advance_clna(
                scenario.program_id,
                f.clna_advance_payload(k.CLNA_DATA_COLLECTION),
                director_headers,
            )
        )
        assert reopened["clna_phase"] == k.CLNA_DATA_COLLECTION
        assert reopened["clna_certified_on"] is None
        assert reopened["clna_expires_on"] is None
        assert reopened["clna_certified_by_user_id"] is None

        consultation = f.clna_advance_payload(k.CLNA_STAKEHOLDER_CONSULTATION)
        validate_error(
            api.advance_clna(scenario.program_id, consultation, director_headers),
            errors.ERR_LABOR_MARKET_DATA_STALE,
        )

        patched = validate_unpaginated(
            api.patch_program(
                scenario.program_id,
                f.program_patch(labor_market_data_asof="2028-07-01"),
                director_headers,
            )
        )
        assert patched["labor_market_data_asof"] == "2028-07-01"
        assert patched["clna_phase"] == k.CLNA_DATA_COLLECTION

        advanced = validate_unpaginated(
            api.advance_clna(scenario.program_id, consultation, director_headers)
        )
        assert advanced["clna_phase"] == k.CLNA_STAKEHOLDER_CONSULTATION
        assert advanced["approval_status"] == k.APPROVAL_DRAFT
