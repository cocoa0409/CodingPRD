"""Service-log ledgers, the compensatory-award arithmetic and its boundaries.

Every test in this module translates exactly one instance of the difficulty or
corner design index; the trailing `Design:` line of each docstring names it.
"""

from test_helpers import (
    CANON_AUTHORIZED_AMOUNT_CENTS,
    CANON_AVAILABLE_AFTER_ONE_ASSIGNMENT,
    CANON_AWARD_COMPUTED_MINUTES_MFM,
    CANON_AWARD_COMPUTED_MINUTES_QB,
    CANON_AWARD_PROPOSAL_UPPER,
    CANON_BUDGET_CODE,
    CANON_DATE_MON_W1,
    CANON_DATE_THU_W1,
    CANON_DATE_TUE_W1,
    CANON_DATE_WED_W1,
    CANON_MAKEUP_CHARGE_45_MIN,
    CANON_TOTAL_CHARGE_CENTS,
    CASE_MANAGER_USER_ID,
    ApiErrorId,
    assert_allocation_available_identity,
    assert_award,
    assert_award_remaining_identity,
    assert_service_log,
    factories,
    fixtures,
    make_case_manager_headers,
    make_compliance_officer_headers,
    make_parent_guardian_headers,
    make_related_service_provider_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CM = make_case_manager_headers()
CO = make_compliance_officer_headers()


class TestAwardVariantDivergence:
    """One log set, two calculation variants, two different owed figures."""

    def test_minute_for_minute_stores_the_severity_but_never_applies_it(self, api):
        """85 district-fault minutes become an award of exactly 85 minutes.

        The canonical log set is a 60-minute `MISSED_DISTRICT`, a 45/20 `PARTIAL`
        and a 60-minute `MISSED_PARENT`, and only two of those enter the
        arithmetic: "The input set is every service log whose `status` is
        `VERIFIED`, whose commitment belongs to the award's `student_id`, whose
        commitment belongs to the award's `source_program_id`, and whose `outcome`
        is either `MISSED_DISTRICT` or `PARTIAL`." Their deficit is 60 + 25, since
        "The district's missed minutes are the sum, across that set, of
        `minutes_scheduled` less `minutes_delivered`." The determination's
        `max_regression_pct` of 26.0 gives a severity of 1.25 because
        "`severity_factor` is one point zero zero when that percentage is below
        twenty-five point zero, one point two five when it is at least
        twenty-five point zero but below forty-five point zero, and one point five
        zero when it is at least forty-five point zero." — and yet the figure is
        untouched, because "Under `MINUTE_FOR_MINUTE` — the district's default
        remedy of one owed minute per missed minute — the raw figure is the
        district's missed minutes exactly." and "`severity_factor` is still
        computed and still stored on the award for the audit record, but it is
        **not applied**, and no fifteen-minute rounding is applied either."

        Design: Difficulty/dual_variant_calc/award_variant_divergence_minute_for_minute_vs_qualitative_benefit
        """
        context = fixtures.setup_baseline(api)

        award = validate_success(
            api.create_award(
                factories.award_payload(
                    context["student"]["id"], context["program"]["id"],
                    "MINUTE_FOR_MINUTE",
                ),
                CM,
            ),
            201,
        )
        assert_award(award)
        assert award["calculation_variant"] == "MINUTE_FOR_MINUTE"
        assert award["computed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert award["severity_factor"] == 1.25
        assert award["verified_missed_log_count"] == 2
        assert award["excluded_log_count"] == 1
        assert award["negotiation_status"] == "DRAFT"
        assert award["delivery_status"] == "NOT_STARTED"
        assert award["proposed_minutes"] is None
        assert award["agreed_minutes"] is None

    def test_qualitative_benefit_scales_by_severity_then_rounds_the_quarter_hour(
        self, api
    ):
        """The same 85 minutes become 105 once the severity factor is applied.

        A declined award is out of the way — "`DECLINE` completes
        `PARENT_REVIEW → DECLINED`, which is terminal: `agreed_minutes` stays null
        and no minutes ever enter the student's `outstanding_owed_minutes`." — so a
        second award may be opened on the same pair under the other variant. That
        variant behaves differently: "Under `QUALITATIVE_BENEFIT` — the remedy
        scaled by the regression severity documented at eligibility — the
        district's missed minutes are multiplied by `severity_factor`, and that
        product is then rounded to the nearest quarter-hour: divide the product by
        fifteen, add one half, take the whole-number part below the result, and
        multiply back by fifteen." 85 times 1.25 is 106.25; divided by fifteen and
        offset by one half that is 7.583, whose whole-number part below is 7, so
        the award is 105 minutes. That is strictly more than the 85 the other
        variant produced, exactly as "Identical logs consequently yield a strictly
        larger award under `QUALITATIVE_BENEFIT` whenever `severity_factor`
        exceeds one point zero zero." predicts.

        Design: Difficulty/dual_variant_calc/award_variant_divergence_minute_for_minute_vs_qualitative_benefit
        """
        context = fixtures.setup_baseline(api)
        student_id = context["student"]["id"]
        program_id = context["program"]["id"]

        first = fixtures.open_award(api, student_id, program_id, "MINUTE_FOR_MINUTE")
        assert first["computed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        validate_success(
            api.propose_award(
                first["id"],
                {"proposed_minutes": CANON_AWARD_COMPUTED_MINUTES_MFM},
                CM,
            )
        )
        declined = validate_success(
            api.award_parent_response(
                first["id"],
                {"response": "DECLINE"},
                make_parent_guardian_headers(student_id),
            )
        )
        assert declined["negotiation_status"] == "DECLINED"
        assert declined["agreed_minutes"] is None

        second = validate_success(
            api.create_award(
                factories.award_payload(
                    student_id, program_id, "QUALITATIVE_BENEFIT"
                ),
                CM,
            ),
            201,
        )
        assert second["calculation_variant"] == "QUALITATIVE_BENEFIT"
        assert second["computed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_QB
        assert second["severity_factor"] == 1.25
        assert second["verified_missed_log_count"] == 2
        assert second["excluded_log_count"] == 1
        assert second["negotiation_status"] == "DRAFT"
        assert second["delivery_status"] == "NOT_STARTED"
        assert (
            second["computed_minutes"] > first["computed_minutes"]
        ), "QUALITATIVE_BENEFIT must exceed MINUTE_FOR_MINUTE at severity 1.25"


class TestMinimumAwardableMinutes:
    """The award floor is a strict less-than comparison against thirty minutes."""

    def test_a_twenty_nine_minute_deficit_falls_below_the_award_floor(self, api):
        """One 60/31 PARTIAL log leaves 29 owed minutes, one short of an award.

        The single partial log puts 29 minutes on the district's tab because
        "Creating a `VERIFIED` log recomputes the owning commitment's ledger in
        full: `delivered_minutes` becomes the sum of `minutes_delivered` across
        that commitment's `VERIFIED` logs, and `compensable_owed_minutes` becomes
        the sum, across that commitment's `VERIFIED` logs whose outcome is
        `MISSED_DISTRICT` or `PARTIAL`, of `minutes_scheduled` less
        `minutes_delivered`." Opening an award on that deficit is refused, since
        "If `computed_minutes` then falls below thirty minutes, there is no award
        worth making and the create is refused with
        `ERR_NO_COMPENSABLE_MINUTES`." No award row survives the attempt.

        Design: Difficulty/boundary_precision_check/min_awardable_minutes_boundary_on_award_creation
        """
        context = fixtures.setup_baseline(api, with_canonical_logs=False)
        commitment_id = context["commitment"]["id"]
        fixtures.log_service(
            api, factories.partial_log_payload(commitment_id, CANON_DATE_MON_W1, 60, 31)
        )

        commitment = fixtures.refresh_commitment(api, commitment_id)
        assert commitment["compensable_owed_minutes"] == 29
        student = fixtures.refresh_student(api, context["student"]["id"])
        assert student["pending_award_minutes"] == 29
        assert student["esy_service_alert"] is False

        validate_error(
            api.create_award(
                factories.award_payload(
                    context["student"]["id"], context["program"]["id"]
                ),
                CM,
            ),
            ApiErrorId.NO_COMPENSABLE_MINUTES,
            422,
        )
        _rows, meta = validate_paginated(api.list_awards(CM, {"limit": 100}))
        assert meta["total_count"] == 0

    def test_exactly_thirty_owed_minutes_clears_the_floor_unrounded(self, api):
        """A second 60/59 PARTIAL adds the missing minute and the award opens.

        With 29 + 1 owed minutes the create sits exactly on the floor, and the
        comparison in "If `computed_minutes` then falls below thirty minutes,
        there is no award worth making and the create is refused with
        `ERR_NO_COMPENSABLE_MINUTES`." no longer holds. The clamp above leaves the
        figure alone as well: "`computed_minutes` is the smaller of the rounded raw
        figure and the annual ceiling of 3600 minutes — sixty hours in a school
        year." Under `MINUTE_FOR_MINUTE` no quarter-hour rounding runs, so the
        award is 30 minutes rather than 45, even though the stored
        `severity_factor` is 1.25.

        Design: Difficulty/boundary_precision_check/min_awardable_minutes_boundary_on_award_creation
        """
        context = fixtures.setup_baseline(api, with_canonical_logs=False)
        commitment_id = context["commitment"]["id"]
        fixtures.log_service(
            api, factories.partial_log_payload(commitment_id, CANON_DATE_MON_W1, 60, 31)
        )
        fixtures.log_service(
            api, factories.partial_log_payload(commitment_id, CANON_DATE_TUE_W1, 60, 59)
        )

        award = validate_success(
            api.create_award(
                factories.award_payload(
                    context["student"]["id"], context["program"]["id"]
                ),
                CM,
            ),
            201,
        )
        assert award["computed_minutes"] == 30
        assert award["severity_factor"] == 1.25
        assert award["verified_missed_log_count"] == 2
        assert award["excluded_log_count"] == 0
        assert award["negotiation_status"] == "DRAFT"
        assert award["delivery_status"] == "NOT_STARTED"
        assert award["agreed_minutes"] is None
        assert award["proposed_minutes"] is None
        assert award["delivery_deadline_date"] is None

        commitment = fixtures.refresh_commitment(api, commitment_id)
        assert commitment["compensable_owed_minutes"] == 30
        assert (
            fixtures.refresh_student(api, context["student"]["id"])[
                "pending_award_minutes"
            ]
            == 30
        )


class TestAwardInputSet:
    """Parent-caused and voided logs are counted as excluded, never as debt."""

    def test_only_verified_district_fault_logs_reach_the_award_arithmetic(self, api):
        """Four logs, one voided: a single log funds the award and three are set aside.

        The commitment carries a 60-minute `MISSED_DISTRICT`, a 60-minute
        `MISSED_PARENT`, a 45-minute `MISSED_STUDENT_ABSENT` and a 45/20 `PARTIAL`
        that is then voided. Only the first qualifies under "The input set is every
        service log whose `status` is `VERIFIED`, whose commitment belongs to the
        award's `student_id`, whose commitment belongs to the award's
        `source_program_id`, and whose `outcome` is either `MISSED_DISTRICT` or
        `PARTIAL`." The other three are tallied, not discarded:
        "`excluded_log_count` records how many logs of the same student and the
        same program were passed over — those with `status` `VOIDED`, and those
        whose outcome was `DELIVERED`, `MISSED_PARENT` or
        `MISSED_STUDENT_ABSENT`." The void itself already rolled the commitment
        ledger back, since "The voided row simply leaves every input set: the
        commitment's ledger is recomputed, so `delivered_minutes` and
        `compensable_owed_minutes` return to their pre-log values, and the
        student's ledger is recomputed, so `pending_award_minutes` and
        `esy_service_alert` return to theirs."

        Design: Corner/calculations/award_input_set_excludes_parent_caused_and_voided_logs
        """
        context = fixtures.setup_baseline(api, with_canonical_logs=False)
        commitment_id = context["commitment"]["id"]
        provider_id = context["provider"]["id"]

        fixtures.log_service(
            api, factories.missed_district_log_payload(commitment_id, CANON_DATE_MON_W1)
        )
        fixtures.log_service(
            api, factories.missed_parent_log_payload(commitment_id, CANON_DATE_TUE_W1)
        )
        fixtures.log_service(
            api,
            factories.service_log_payload(
                commitment_id,
                service_date=CANON_DATE_WED_W1,
                outcome="MISSED_STUDENT_ABSENT",
                minutes_scheduled=45,
                minutes_delivered=0,
                miss_reason_code="STUDENT_ILL",
            ),
        )
        partial = fixtures.log_service(
            api,
            factories.partial_log_payload(
                commitment_id, CANON_DATE_THU_W1, 45, 20, provider_id=provider_id
            ),
            make_related_service_provider_headers(provider_id),
        )
        voided = fixtures.void_service_log(
            api, partial["id"], "Logged against the wrong commitment."
        )
        assert voided["status"] == "VOIDED"

        commitment = fixtures.refresh_commitment(api, commitment_id)
        assert commitment["delivered_minutes"] == 0
        assert commitment["compensable_owed_minutes"] == 60

        award = validate_success(
            api.create_award(
                factories.award_payload(
                    context["student"]["id"], context["program"]["id"]
                ),
                CM,
            ),
            201,
        )
        assert award["computed_minutes"] == 60
        assert award["verified_missed_log_count"] == 1
        assert award["excluded_log_count"] == 3
        assert award["severity_factor"] == 1.25
        assert award["negotiation_status"] == "DRAFT"
        assert award["delivery_status"] == "NOT_STARTED"

        student = fixtures.refresh_student(api, context["student"]["id"])
        assert student["pending_award_minutes"] == 60
        assert student["esy_service_alert"] is True


class TestDuplicateServiceLog:
    """One VERIFIED log per commitment per date, and voiding frees the slot."""

    def test_a_second_log_for_a_documented_day_is_refused_until_the_first_is_voided(
        self, api
    ):
        """The uniqueness gate keys on VERIFIED status, not on existence.

        A `MISSED_DISTRICT` log already documents 2027-06-14, so a second log for
        the same day is refused: "And no `VERIFIED` log may already exist for that
        same combination of `commitment_id` and `service_date` — a second log for
        a day already documented is refused with `ERR_DUPLICATE_SERVICE_LOG`."
        Voiding the incumbent both frees the slot and rewinds the ledger, because
        "A log's `status` begins at `VERIFIED`; only `VERIFIED` rows enter the
        minute ledgers and the compensatory-award input set." The replacement
        `DELIVERED` log is then accepted and the day reads as fully served.

        Design: Corner/validations/duplicate_service_log_for_same_commitment_and_date_rejected
        """
        context = fixtures.setup_baseline(api, with_canonical_logs=False)
        commitment_id = context["commitment"]["id"]
        first = fixtures.log_service(
            api, factories.missed_district_log_payload(commitment_id, CANON_DATE_MON_W1)
        )
        assert_service_log(first)
        assert first["status"] == "VERIFIED"

        validate_error(
            api.create_service_log(
                factories.delivered_log_payload(commitment_id, CANON_DATE_MON_W1, 60),
                CM,
            ),
            ApiErrorId.DUPLICATE_SERVICE_LOG,
            409,
        )
        commitment = fixtures.refresh_commitment(api, commitment_id)
        assert commitment["compensable_owed_minutes"] == 60
        assert commitment["delivered_minutes"] == 0

        voided = fixtures.void_service_log(
            api, first["id"], "Duplicate entry created by the provider portal."
        )
        assert voided["status"] == "VOIDED"
        assert (
            fixtures.refresh_commitment(api, commitment_id)[
                "compensable_owed_minutes"
            ]
            == 0
        )

        replacement = validate_success(
            api.create_service_log(
                factories.delivered_log_payload(commitment_id, CANON_DATE_MON_W1, 60),
                CM,
            ),
            201,
        )
        assert replacement["status"] == "VERIFIED"
        commitment = fixtures.refresh_commitment(api, commitment_id)
        assert commitment["delivered_minutes"] == 60
        assert commitment["compensable_owed_minutes"] == 0
        student = fixtures.refresh_student(api, context["student"]["id"])
        assert student["pending_award_minutes"] == 0
        assert student["esy_service_alert"] is False


class TestProposalBand:
    """A proposal may be generous by half again, never stingier than the arithmetic."""

    def test_offers_outside_the_band_are_refused_and_the_upper_bound_is_inclusive(
        self, api
    ):
        """84 is too low, 200 too high, and 127 lands exactly on the ceiling.

        The award computes 85 minutes, so the band runs from 85 to the whole-number
        part below 127.5: "The offered `proposed_minutes` must fall between
        `computed_minutes` at the low end and one and one-half times
        `computed_minutes` at the high end, the upper bound taken as the
        whole-number part below that product, both endpoints inclusive; anything
        outside that band is refused with `ERR_PROPOSAL_OUT_OF_RANGE`." Each
        refusal leaves the award untouched in `DRAFT`, and the accepted offer
        records its author, because "On success `proposed_minutes` is stored,
        `authored_by_user_id` records the proposing case manager's `X-User-ID`,
        and the award's `version` increments."

        Design: Corner/errors/proposal_outside_the_allowed_minute_range_rejected
        """
        context = fixtures.setup_baseline(api)
        award = fixtures.open_award(
            api, context["student"]["id"], context["program"]["id"]
        )
        assert award["computed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM

        for offer in (84, 200):
            validate_error(
                api.propose_award(award["id"], {"proposed_minutes": offer}, CM),
                ApiErrorId.PROPOSAL_OUT_OF_RANGE,
                422,
            )
            still_draft = fixtures.refresh_award(api, award["id"])
            assert still_draft["negotiation_status"] == "DRAFT"
            assert still_draft["proposed_minutes"] is None

        proposed = validate_success(
            api.propose_award(
                award["id"], {"proposed_minutes": CANON_AWARD_PROPOSAL_UPPER}, CM
            )
        )
        assert proposed["computed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert proposed["proposed_minutes"] == CANON_AWARD_PROPOSAL_UPPER
        assert proposed["negotiation_status"] == "PARENT_REVIEW"
        assert proposed["authored_by_user_id"] == CASE_MANAGER_USER_ID
        assert proposed["agreed_minutes"] is None
        assert proposed["remaining_owed_minutes"] == 0
        assert_award_remaining_identity(proposed)


class TestDuplicateAward:
    """A live award blocks a second one on the same student and source program."""

    def test_a_second_award_on_the_same_pair_is_refused_while_the_first_lives(
        self, api
    ):
        """The DRAFT award is non-terminal, so the QUALITATIVE_BENEFIT retry fails.

        "Only one live award may exist per student and source program: if a
        non-terminal award already covers that pair, the create is refused with
        `ERR_DUPLICATE_AWARD`." The refusal changes nothing: the surviving award
        keeps its own variant and figure, and the student's `pending_award_minutes`
        is untouched.

        Design: Corner/errors/second_non_terminal_award_for_the_same_student_and_program_rejected
        """
        context = fixtures.setup_baseline(api)
        student_id = context["student"]["id"]
        program_id = context["program"]["id"]
        award = fixtures.open_award(api, student_id, program_id)

        validate_error(
            api.create_award(
                factories.award_payload(
                    student_id, program_id, "QUALITATIVE_BENEFIT"
                ),
                CM,
            ),
            ApiErrorId.DUPLICATE_AWARD,
            409,
        )

        _rows, meta = validate_paginated(api.list_awards(CM, {"limit": 100}))
        assert meta["total_count"] == 1
        survivor = fixtures.refresh_award(api, award["id"])
        assert survivor["calculation_variant"] == "MINUTE_FOR_MINUTE"
        assert survivor["computed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert (
            fixtures.refresh_student(api, student_id)["pending_award_minutes"]
            == CANON_AWARD_COMPUTED_MINUTES_MFM
        )


class TestOwedMinutesConservation:
    """A delivery and its void must leave the owed-minute ledgers exactly as found."""

    def test_a_forty_five_minute_delivery_moves_every_ledger_once(self, api):
        """The forward leg credits 45 minutes and expends 7290 cents.

        Before the delivery the award holds 85 agreed minutes with 45 scheduled,
        and the student's debt matches it, since
        "`outstanding_owed_minutes` is the debt the district has actually
        acknowledged: for each compensatory award of this student whose
        `negotiation_status` is either `AGREED` or `CLOSED`, take the award's
        `agreed_minutes` less its `delivered_minutes` less its
        `forfeited_minutes`, treat any negative result as zero, and sum those
        figures." Logging the outcome recomputes that ledger — "`delivered_minutes`
        is the sum of `minutes_delivered` across the award's sessions whose
        `status` is `DELIVERED`; `scheduled_minutes` is the sum of
        `minutes_planned` across the award's sessions whose `status` is
        `SCHEDULED`; and `remaining_owed_minutes` is `agreed_minutes` (treated as
        zero while still null) less `delivered_minutes` less `forfeited_minutes`,
        with any negative result clamped to zero." — and advances the second
        dimension, because "It begins at `NOT_STARTED`, reaches `SCHEDULING` when
        the award's first session is booked, and advances
        `SCHEDULING → IN_PROGRESS` when the award's first session reaches
        `DELIVERED` while the resulting `remaining_owed_minutes` is still greater
        than zero."

        Design: Difficulty/compensating_invariant/owed_minutes_conservation_survives_a_voided_delivery
        """
        context = fixtures.setup_scheduled_session(api, minutes_planned=45)
        award = fixtures.refresh_award(api, context["award"]["id"])
        student_id = context["student"]["id"]
        provider_id = context["provider"]["id"]

        assert award["agreed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert award["delivered_minutes"] == 0
        assert award["forfeited_minutes"] == 0
        assert award["scheduled_minutes"] == 45
        assert award["remaining_owed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert_award_remaining_identity(award)
        assert (
            fixtures.refresh_student(api, student_id)["outstanding_owed_minutes"]
            == CANON_AWARD_COMPUTED_MINUTES_MFM
        )

        delivered = validate_success(
            api.log_makeup_outcome(
                context["session"]["id"],
                {"outcome": "DELIVERED", "minutes_delivered": 45},
                make_related_service_provider_headers(provider_id),
            )
        )
        assert delivered["status"] == "DELIVERED"
        assert delivered["minutes_delivered"] == 45
        assert delivered["charge_cents"] == CANON_MAKEUP_CHARGE_45_MIN
        assert delivered["charged_fund_source"] == "IDEA_611_FEDERAL"
        assert delivered["charged_budget_code"] == CANON_BUDGET_CODE

        award = fixtures.refresh_award(api, award["id"])
        assert award["delivered_minutes"] == 45
        assert award["scheduled_minutes"] == 0
        assert award["remaining_owed_minutes"] == 40
        assert award["delivery_status"] == "IN_PROGRESS"
        assert award["negotiation_status"] == "AGREED"
        assert_award_remaining_identity(award)

        student = fixtures.refresh_student(api, student_id)
        assert student["outstanding_owed_minutes"] == 40
        assert student["delivered_makeup_minutes_total"] == 45

        allocation = fixtures.refresh_allocation(
            api, context["program"]["id"], context["allocation"]["id"]
        )
        assert allocation["expended_amount_cents"] == CANON_MAKEUP_CHARGE_45_MIN
        assert allocation["compensatory_expended_cents"] == CANON_MAKEUP_CHARGE_45_MIN
        assert allocation["available_cents"] == (
            CANON_AVAILABLE_AFTER_ONE_ASSIGNMENT - CANON_MAKEUP_CHARGE_45_MIN
        )
        assert_allocation_available_identity(allocation)

    def test_voiding_the_delivery_returns_every_ledger_to_its_prior_value(self, api):
        """The compensation restores 85 owed minutes and 0 expended cents.

        "Voiding a delivered session is a `ComplianceOfficer` act, requires the
        session to be `DELIVERED`, and moves it `DELIVERED → VOIDED`, which is
        terminal." and the reversal is exact: "It reverses the delivery precisely:
        the session's `minutes_delivered` leaves the award's `delivered_minutes`,
        so `remaining_owed_minutes` and the student's `outstanding_owed_minutes`
        return to their pre-delivery values; and the allocation's
        `expended_amount_cents` and `compensatory_expended_cents` both drop by the
        session's `charge_cents`, so `available_cents` returns to its pre-delivery
        value." The delivery dimension stays at `IN_PROGRESS` — no transition
        returns an award from there to `SCHEDULING` — while the 45 minutes become
        schedulable again.

        Design: Difficulty/compensating_invariant/owed_minutes_conservation_survives_a_voided_delivery
        """
        context = fixtures.setup_scheduled_session(api, minutes_planned=45)
        award_id = context["award"]["id"]
        session_id = context["session"]["id"]
        student_id = context["student"]["id"]
        provider_id = context["provider"]["id"]

        validate_success(
            api.log_makeup_outcome(
                session_id,
                {"outcome": "DELIVERED", "minutes_delivered": 45},
                make_related_service_provider_headers(provider_id),
            )
        )

        voided = validate_success(
            api.log_makeup_outcome(
                session_id,
                {
                    "outcome": "VOIDED",
                    "outcome_note": (
                        "Service log corrected: the session did not take place"
                    ),
                },
                CO,
            )
        )
        assert voided["status"] == "VOIDED"

        award = fixtures.refresh_award(api, award_id)
        assert award["delivered_minutes"] == 0
        assert award["forfeited_minutes"] == 0
        assert award["scheduled_minutes"] == 0
        assert award["remaining_owed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert award["delivery_status"] == "IN_PROGRESS"
        assert award["negotiation_status"] == "AGREED"
        assert_award_remaining_identity(award)

        student = fixtures.refresh_student(api, student_id)
        assert student["outstanding_owed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert student["delivered_makeup_minutes_total"] == 0

        allocation = fixtures.refresh_allocation(
            api, context["program"]["id"], context["allocation"]["id"]
        )
        assert allocation["expended_amount_cents"] == 0
        assert allocation["compensatory_expended_cents"] == 0
        assert allocation["encumbered_amount_cents"] == CANON_TOTAL_CHARGE_CENTS
        assert allocation["available_cents"] == CANON_AVAILABLE_AFTER_ONE_ASSIGNMENT
        assert allocation["authorized_amount_cents"] == CANON_AUTHORIZED_AMOUNT_CENTS
        assert_allocation_available_identity(allocation)
