"""Requests that breach two rules at once, and which error the ladder returns.

Each scenario below drives a single call that violates two separate checks of the
numbered precedence ladder of PRD 2.7. The higher-priority check owns the
response, and a companion test clears the higher-priority condition to prove the
lower-priority error was genuinely reachable all along.
"""

from test_helpers import (
    STOP_CLNA_CERTIFIED,
    STOP_COMMITTEE_REVIEW,
    STOP_STATE_APPROVED,
    Builder,
    CteApiClient,
    assert_cents,
    assert_ledger_identity,
    errors,
    f,
    k,
    users,
    validate_error,
    validate_unpaginated,
)

# A CONSUMABLE line whose 0.8500 federal share alone exceeds the award's whole
# allocation, so the capacity check of PRD 2.7 priority 39 is certain to fail.
OVERDRAWING_UNIT_COST_CENTS = 6000000

#: The clock reading one day past a needs assessment certified on the startup
#: default and therefore expiring 730 days later, on 2028-07-31.
CLOCK_ONE_DAY_PAST_CLNA_EXPIRY = "2028-08-01T00:00:00Z"


def _overdrawing_charge(
    build: Builder, program_id: str, requester=users.DIRECTOR
):
    """Record a fresh award and file one charge against it that cannot be funded."""
    grant = build.grant()
    charge = build.expenditure(
        grant.grant_id,
        program_id,
        k.CATEGORY_CONSUMABLE,
        OVERDRAWING_UNIT_COST_CENTS,
        director=requester,
    )
    return grant, charge


def _certify(api: CteApiClient, expenditure_id: str, officer):
    """Rule CERTIFY on a requested charge as the named officer."""
    return api.certify_allowability(
        expenditure_id,
        f.certification_payload(k.DECISION_CERTIFY),
        users.headers(officer),
    )


def _read_expenditure(api: CteApiClient, expenditure_id: str):
    return validate_unpaginated(
        api.get_expenditure(expenditure_id, users.headers(users.FISCAL_OFFICER))
    )


def _read_grant(api: CteApiClient, grant_id: str):
    return validate_unpaginated(
        api.get_grant(grant_id, users.headers(users.FISCAL_OFFICER))
    )


def _read_program(api: CteApiClient, program_id: str):
    return validate_unpaginated(
        api.get_program(program_id, users.headers(users.DIRECTOR))
    )


def _program_without_active_postsecondary(
    build: Builder, api: CteApiClient, cip_code: str
):
    """Author a program to a certified assessment, then retire its only
    postsecondary course so that the sequence-completeness rule is breached.
    """
    scenario = build.program(
        cip_code,
        stop_at=STOP_CLNA_CERTIFIED,
        cluster=k.CLUSTER_INFORMATION_TECHNOLOGY,
        title="Digital Media Production",
    )
    validate_unpaginated(
        api.patch_course(
            scenario.postsecondary_course_id,
            f.course_patch(status=k.COURSE_RETIRED),
            users.headers(scenario.director),
        )
    )
    return scenario


class TestApprovalGateOutranksGrantCapacity:
    """A charge that is both unapproved and unaffordable reports the approval gate."""

    def test_certifying_against_an_unapproved_program_reports_the_approval_gate(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §2.7: "Checks are evaluated in strictly ascending priority and the **first** failure is the response; no later check can mask an earlier one." The ladder places "10. The cross-entity approval gate on expenditure certification — `ERR_POS_NOT_APPROVED`." above "39. Grant capacity — `ERR_GRANT_FUNDS_EXCEEDED`.", and PRD §2.7 spells the consequence out: "Grant capacity is the **last** business check in the system: any state, compliance, constraint or referential failure above it wins a request that would also have overdrawn the award."

        PRD §3.7: "The charged program of study must be in `approval_status` `STATE_APPROVED`, or the answer is `ERR_POS_NOT_APPROVED`."

        Design: Difficulty/priority_pair_validation_conflict/pos_not_approved_state_rule_beats_grant_funds_exceeded_fiscal_rule
        """
        scenario = build.program("46.0302", stop_at=STOP_COMMITTEE_REVIEW)
        program = _read_program(api, scenario.program_id)
        assert program["approval_status"] == k.APPROVAL_COMMITTEE_REVIEW
        assert program["clna_phase"] == k.CLNA_CERTIFIED

        grant, charge = _overdrawing_charge(build, scenario.program_id)

        payload = validate_error(
            _certify(api, charge["id"], users.FISCAL_OFFICER),
            errors.ERR_POS_NOT_APPROVED,
        )
        assert payload["error_id"] != errors.ERR_GRANT_FUNDS_EXCEEDED, (
            "the fiscal overrun must stay invisible behind the approval gate"
        )
        assert grant.allocation_cents == 5000000

    def test_refused_certification_leaves_the_charge_and_the_ledger_untouched(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.7: "An accepted certification writes `federal_share_pct` and `approved_cents`, records `certified_by_user_id` from the acting `X-User-ID`, rebuilds the whole award ledger, and increments the `version` of both the expenditure and the award." A refused one therefore leaves the row exactly as PRD §3.7 opened it: the request "opens in `status` `REQUESTED`, computes `gross_cents` as `unit_cost_cents` multiplied by `quantity`, sets `federal_share_pct` from the category table below, leaves `approved_cents` null until certification, leaves `certified_by_user_id`, `finding_code`, `obligation_reference` and `void_reason` null, and increments the award's `version`."

        PRD §3.7: "A new award opens in `status` `OPEN` with `direct_obligated_cents`, `indirect_pool_cents`, `obligated_cents` and `admin_obligated_cents` all 0, `remaining_cents` equal to the full `allocation_cents`, `indirect_rate` at the tier that applies to a direct total of zero, and `admin_cap_cents` set to the allocation multiplied by five percent, rounded half-up to whole cents."

        Design: Difficulty/priority_pair_validation_conflict/pos_not_approved_state_rule_beats_grant_funds_exceeded_fiscal_rule
        """
        scenario = build.program("46.0302", stop_at=STOP_COMMITTEE_REVIEW)
        grant, charge = _overdrawing_charge(build, scenario.program_id)

        validate_error(
            _certify(api, charge["id"], users.FISCAL_OFFICER),
            errors.ERR_POS_NOT_APPROVED,
        )

        row = _read_expenditure(api, charge["id"])
        assert row["status"] == k.EXP_REQUESTED
        assert row["approved_cents"] is None
        assert row["certified_by_user_id"] is None

        award = _read_grant(api, grant.grant_id)
        assert_cents(award["direct_obligated_cents"], 0, "direct_obligated_cents")
        assert_cents(award["obligated_cents"], 0, "obligated_cents")
        assert_cents(
            award["remaining_cents"], grant.allocation_cents, "remaining_cents"
        )
        assert_ledger_identity(award)

    def test_capacity_failure_surfaces_once_the_program_carries_state_approval(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.7: "The approved amount of a line is its `gross_cents` multiplied by its `federal_share_pct`, rounded half-up to whole cents — and that rounding happens **here, once, per expenditure line**." PRD §3.7: "Finally, and last of all the checks in the entire system, the award's `remaining_cents` recomputed with this line included must be at least zero; an overdraw is `ERR_GRANT_FUNDS_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/pos_not_approved_state_rule_beats_grant_funds_exceeded_fiscal_rule
        """
        scenario = build.program("46.0302", stop_at=STOP_STATE_APPROVED)
        program = _read_program(api, scenario.program_id)
        assert program["approval_status"] == k.APPROVAL_STATE_APPROVED

        grant, charge = _overdrawing_charge(build, scenario.program_id)

        validate_error(
            _certify(api, charge["id"], users.FISCAL_OFFICER),
            errors.ERR_GRANT_FUNDS_EXCEEDED,
        )
        assert_cents(
            _read_grant(api, grant.grant_id)["remaining_cents"],
            grant.allocation_cents,
            "remaining_cents",
        )


class TestLapsedAssessmentOutranksIncompleteSequence:
    """A submit that is both lapsed and short a postsecondary course reports the lapse."""

    def test_submitting_a_lapsed_program_reports_the_lapse_not_the_gap_in_the_sequence(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §2.7: "Checks are evaluated in strictly ascending priority and the **first** failure is the response; no later check can mask an earlier one." The ladder places "12. Needs-assessment not lapsed — `ERR_CLNA_EXPIRED`." above "24. Sequence completeness at submit — `ERR_SEQUENCE_INCOMPLETE`."

        PRD §3.4: "The six preconditions, in the order their failures surface: the program's needs assessment must have been certified at least once, so `clna_phase` must be `CERTIFIED` or `EXPIRED` (otherwise `ERR_CLNA_NOT_CERTIFIED`); that certification must still be live, so the logical clock's date must not be past `clna_expires_on` (otherwise `ERR_CLNA_EXPIRED`); the sequence must be complete, meaning at least one course with `status` `ACTIVE` and `segment` `SECONDARY` **and** at least one course with `status` `ACTIVE` and `segment` `POSTSECONDARY` exist on the program (otherwise `ERR_SEQUENCE_INCOMPLETE`); the approved credential list must hold at least one credential (otherwise `ERR_CREDENTIAL_LIST_EMPTY`); and at least one educator on the program must be in `status` `ELIGIBLE` after the lazy credential-lapse re-evaluation described in §2.12 has run (otherwise `ERR_NO_ELIGIBLE_INSTRUCTOR`). A `DRAFT` course or a `RETIRED` course satisfies neither half of the sequence-completeness rule."

        PRD §3.2: "On success the server writes `clna_certified_by_user_id` from the acting `X-User-ID`, sets `clna_certified_on` to the logical clock's current date, and sets `clna_expires_on` to that date plus 730 days — a certified needs assessment is good for two years and not a day more."

        Design: Difficulty/priority_pair_validation_conflict/clna_expired_temporal_rule_beats_sequence_incomplete_constraint_rule
        """
        scenario = _program_without_active_postsecondary(build, api, "10.0201")
        certified = _read_program(api, scenario.program_id)
        assert certified["clna_expires_on"] == "2028-07-31"

        build.set_clock(CLOCK_ONE_DAY_PAST_CLNA_EXPIRY)

        payload = validate_error(
            api.submit_program(
                scenario.program_id,
                f.submit_payload("https://district.example/pos/10-0201/narrative.pdf"),
                users.headers(scenario.director),
            ),
            errors.ERR_CLNA_EXPIRED,
        )
        assert payload["error_id"] != errors.ERR_SEQUENCE_INCOMPLETE, (
            "the constraint failure must stay behind the temporal one"
        )

    def test_lapsed_submission_leaves_the_program_in_draft_with_its_round_counter_at_zero(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §2.12: "Whenever the logical clock's date is strictly past a program's `clna_expires_on` and that program's `clna_phase` is still `CERTIFIED`, the phase moves `CERTIFIED → EXPIRED` and the program's `version` increments. This re-evaluation runs at the start of every write addressed to that program of study and at the start of expenditure allowability certification; retrieving a single program of study likewise refreshes it."

        PRD §3.1: "On creation the new program lands in `approval_status` `DRAFT` and `clna_phase` `NOT_STARTED`, its `version` is 1, its `authored_by_user_id` is set to the acting `X-User-ID`, its `alignment_index` and `alignment_index_variant` are both null, its `narrative_url` is null, its `open_finding_codes` list is empty, its `federal_reporting_eligible` flag is false, its `approval_round` is 0, its `clna_certified_by_user_id`, `clna_certified_on` and `clna_expires_on` are all null, and `secondary_credit_total`, `postsecondary_credit_total` and `articulated_credit_total` are all 0." PRD §3.4: "An accepted submission increments `approval_round` by 1 — the counter is the district's audit trail of how many times the packet has gone up — writes the supplied `narrative_url` onto the program, clears `open_finding_codes` back to an empty list, and recomputes the alignment index under the `PROVISIONAL_LOCAL` variant, writing `alignment_index`, setting `alignment_index_variant` to `PROVISIONAL_LOCAL`, and refreshing `secondary_credit_total`, `postsecondary_credit_total` and `articulated_credit_total`."

        Design: Difficulty/priority_pair_validation_conflict/clna_expired_temporal_rule_beats_sequence_incomplete_constraint_rule
        """
        scenario = _program_without_active_postsecondary(build, api, "10.0201")
        build.set_clock(CLOCK_ONE_DAY_PAST_CLNA_EXPIRY)

        validate_error(
            api.submit_program(
                scenario.program_id,
                f.submit_payload("https://district.example/pos/10-0201/narrative.pdf"),
                users.headers(scenario.director),
            ),
            errors.ERR_CLNA_EXPIRED,
        )

        program = _read_program(api, scenario.program_id)
        assert program["clna_phase"] == k.CLNA_EXPIRED
        assert program["approval_status"] == k.APPROVAL_DRAFT
        assert program["approval_round"] == 0
        assert program["narrative_url"] is None

    def test_incomplete_sequence_reports_itself_while_the_assessment_is_still_live(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.4: "the sequence must be complete, meaning at least one course with `status` `ACTIVE` and `segment` `SECONDARY` **and** at least one course with `status` `ACTIVE` and `segment` `POSTSECONDARY` exist on the program (otherwise `ERR_SEQUENCE_INCOMPLETE`)" and "A `DRAFT` course or a `RETIRED` course satisfies neither half of the sequence-completeness rule."

        Design: Difficulty/priority_pair_validation_conflict/clna_expired_temporal_rule_beats_sequence_incomplete_constraint_rule
        """
        scenario = _program_without_active_postsecondary(build, api, "10.0201")
        live = _read_program(api, scenario.program_id)
        assert live["clna_phase"] == k.CLNA_CERTIFIED

        validate_error(
            api.submit_program(
                scenario.program_id,
                f.submit_payload("https://district.example/pos/10-0201/narrative.pdf"),
                users.headers(scenario.director),
            ),
            errors.ERR_SEQUENCE_INCOMPLETE,
        )
        assert _read_program(api, scenario.program_id)["approval_round"] == 0


class TestSegregationOfDutiesOutranksGrantCapacity:
    """An officer ruling on their own unaffordable request reports the duties split."""

    def test_officer_certifying_their_own_request_reports_the_duties_split(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §2.7: "Checks are evaluated in strictly ascending priority and the **first** failure is the response; no later check can mask an earlier one." The ladder places "7. Segregation of duties on `X-User-ID` — `ERR_SEGREGATION_OF_DUTIES`." above "39. Grant capacity — `ERR_GRANT_FUNDS_EXCEEDED`."

        PRD §2.10: "Three points in the workflow require that two different operators be involved, and all three are enforced on `X-User-ID` at priority 7 with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)." and "Certifying or disallowing an expenditure requires that the acting `X-User-ID` differ from that expenditure's `requested_by_user_id`; the officer who asked for the purchase may not be the one who rules on its allowability."

        PRD §3.7: "Whichever way it goes, the officer's `X-User-ID` must differ from the expenditure's `requested_by_user_id`, or the ruling is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_safety_rule_beats_grant_funds_exceeded_fiscal_rule
        """
        scenario = build.program(
            "51.0601",
            stop_at=STOP_STATE_APPROVED,
            cluster=k.CLUSTER_HEALTH_SCIENCE,
            title="Dental Assisting",
        )
        grant, charge = _overdrawing_charge(
            build, scenario.program_id, requester=users.SHARED_DIRECTOR
        )
        assert charge["requested_by_user_id"] == users.SHARED_OPERATOR_ID

        payload = validate_error(
            _certify(api, charge["id"], users.SHARED_FISCAL_OFFICER),
            errors.ERR_SEGREGATION_OF_DUTIES,
        )
        assert payload["error_id"] != errors.ERR_GRANT_FUNDS_EXCEEDED, (
            "the capacity failure must stay behind the duties split"
        )
        assert grant.allocation_cents == 5000000

    def test_refused_self_certification_leaves_the_award_ledger_intact(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.7: "records `requested_by_user_id` from the acting `X-User-ID`, opens in `status` `REQUESTED`, computes `gross_cents` as `unit_cost_cents` multiplied by `quantity`, sets `federal_share_pct` from the category table below, leaves `approved_cents` null until certification, leaves `certified_by_user_id`, `finding_code`, `obligation_reference` and `void_reason` null, and increments the award's `version`." PRD §3.7: "An accepted certification writes `federal_share_pct` and `approved_cents`, records `certified_by_user_id` from the acting `X-User-ID`, rebuilds the whole award ledger, and increments the `version` of both the expenditure and the award."

        PRD §3.7: "A new award opens in `status` `OPEN` with `direct_obligated_cents`, `indirect_pool_cents`, `obligated_cents` and `admin_obligated_cents` all 0, `remaining_cents` equal to the full `allocation_cents`, `indirect_rate` at the tier that applies to a direct total of zero, and `admin_cap_cents` set to the allocation multiplied by five percent, rounded half-up to whole cents."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_safety_rule_beats_grant_funds_exceeded_fiscal_rule
        """
        scenario = build.program(
            "51.0601",
            stop_at=STOP_STATE_APPROVED,
            cluster=k.CLUSTER_HEALTH_SCIENCE,
            title="Dental Assisting",
        )
        grant, charge = _overdrawing_charge(
            build, scenario.program_id, requester=users.SHARED_DIRECTOR
        )

        validate_error(
            _certify(api, charge["id"], users.SHARED_FISCAL_OFFICER),
            errors.ERR_SEGREGATION_OF_DUTIES,
        )

        row = _read_expenditure(api, charge["id"])
        assert row["status"] == k.EXP_REQUESTED
        assert row["certified_by_user_id"] is None
        assert row["approved_cents"] is None

        award = _read_grant(api, grant.grant_id)
        assert_cents(
            award["remaining_cents"], grant.allocation_cents, "remaining_cents"
        )
        assert_cents(award["obligated_cents"], 0, "obligated_cents")
        assert_ledger_identity(award)

    def test_a_second_officer_reaches_the_capacity_failure_on_the_same_charge(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.7: "Whichever way it goes, the officer's `X-User-ID` must differ from the expenditure's `requested_by_user_id`, or the ruling is refused with `ERR_SEGREGATION_OF_DUTIES`." PRD §3.7: "Finally, and last of all the checks in the entire system, the award's `remaining_cents` recomputed with this line included must be at least zero; an overdraw is `ERR_GRANT_FUNDS_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_safety_rule_beats_grant_funds_exceeded_fiscal_rule
        """
        scenario = build.program(
            "51.0601",
            stop_at=STOP_STATE_APPROVED,
            cluster=k.CLUSTER_HEALTH_SCIENCE,
            title="Dental Assisting",
        )
        grant, charge = _overdrawing_charge(
            build, scenario.program_id, requester=users.SHARED_DIRECTOR
        )

        validate_error(
            _certify(api, charge["id"], users.FISCAL_OFFICER),
            errors.ERR_GRANT_FUNDS_EXCEEDED,
        )
        assert _read_expenditure(api, charge["id"])["status"] == k.EXP_REQUESTED
        assert_cents(
            _read_grant(api, grant.grant_id)["remaining_cents"],
            grant.allocation_cents,
            "remaining_cents",
        )
