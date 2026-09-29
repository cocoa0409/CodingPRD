"""Calculation corners: the certification ladder, penalties, rounding and waivers."""
from test_helpers import (
    ENFORCEMENT_OFFICER,
    PROGRAM_ADMIN,
    TRAINING_OFFICER,
    ApiErrorId,
    api_client,
    assert_decon_order,
    assert_inspection_record,
    assert_instant_equals,
    create_reciprocity_agreement,
    create_station,
    create_water_body,
    disposition_payload,
    enforcement_payload,
    enroll_inspector,
    fetch_inspector,
    fetch_record,
    fetch_station,
    fetch_watercraft,
    log_training,
    make_inspector_headers,
    move_reciprocity_agreement,
    set_clock,
    setup_decon_order,
    setup_inspection,
    setup_program,
    training_record_payload,
    treat_order,
    validate_error,
    validate_paginated,
    validate_success,
)

ARRIVAL = "2026-08-05T09:00:00Z"
ENROLMENT = "2026-08-01T00:00:00Z"


def _station_for_inspectors():
    """A station that exists only to host inspectors, so no hours are declared."""
    set_clock(ENROLMENT)
    water_body = create_water_body(risk_tier="HIGH")
    return create_station(
        name="Polson Access", water_body_id=water_body["id"], hot_water_capable=True
    )


class TestCertificationLevelFromCreditedHoursAndEndorsement:
    """The ladder is inclusive at 8 and at 40, and the endorsement picks the top rung."""

    def test_the_ladder_climbs_at_exactly_eight_then_exactly_forty_hours(self):
        """8.00 hours give LEVEL_1 with promotion; 40.00 endorsed give DECON_CERTIFIED.

        PRD: "`certification_level` then follows from that total by three
        comparisons: below 8 credited hours the level is `TRAINEE`; from 8
        credited hours up to but not including 40, the level is `LEVEL_1`; from 40
        credited hours upward the level is `LEVEL_2` when the inspector has no
        decontamination endorsement, and `DECON_CERTIFIED` when they do. The
        comparisons are inclusive at the lower bound, so a total of exactly 8.00
        hours already reaches `LEVEL_1`, and a total of exactly 40.00 hours
        already reaches `LEVEL_2` — or `DECON_CERTIFIED` for an endorsed
        inspector."

        Design: Corner/calculations/correct_result_certification_level_from_credited_hours_and_endorsement
        """
        station = _station_for_inspectors()
        inspector = enroll_inspector(
            station["id"], decon_endorsement=True, full_name="Ben Steam"
        )
        assert inspector["certification_level"] == "TRAINEE"
        assert inspector["status"] == "PROBATIONARY"

        log_training(inspector["id"], 8, True, completed_at=ENROLMENT)
        promoted = fetch_inspector(inspector["id"])
        assert float(promoted["training_hours_total"]) == 8.00
        assert promoted["certification_level"] == "LEVEL_1"
        assert promoted["status"] == "ACTIVE"
        set_clock("2026-08-02T00:00:00Z")

        validate_success(
            api_client.create_training_record(
                inspector["id"],
                training_record_payload(32, True, module_code="AIS-DECON-200",
                                        completed_at="2026-08-02T00:00:00Z"),
                TRAINING_OFFICER,
            ),
            201,
        )

        certified = fetch_inspector(inspector["id"])
        assert float(certified["training_hours_total"]) == 40.00
        assert certified["certification_level"] == "DECON_CERTIFIED"
        assert certified["status"] == "ACTIVE"

    def test_the_expiry_is_stamped_at_the_promotion_and_never_re_stamped(self):
        """certification_expires_at stays 2027-08-01Z after the second module.

        PRD: "When a credited module lifts a `PROBATIONARY` inspector's
        `certification_level` above `TRAINEE`, the service moves them
        `PROBATIONARY → ACTIVE` in the same request, stamps
        `certification_expires_at` at the current logical time plus 8,760 hours —
        one 365-day year — and advances the inspector's `version` by 1."

        Design: Corner/calculations/correct_result_certification_level_from_credited_hours_and_endorsement
        """
        station = _station_for_inspectors()
        inspector = enroll_inspector(
            station["id"], credited_hours=8, decon_endorsement=True,
            completed_at=ENROLMENT, full_name="Ben Steam",
        )
        assert_instant_equals(
            inspector["certification_expires_at"], "2027-08-01T00:00:00Z",
            "certification_expires_at",
        )
        set_clock("2026-08-02T00:00:00Z")

        log_training(inspector["id"], 32, True, completed_at="2026-08-02T00:00:00Z")

        after = fetch_inspector(inspector["id"])
        assert after["certification_level"] == "DECON_CERTIFIED"
        assert_instant_equals(
            after["certification_expires_at"], "2027-08-01T00:00:00Z",
            "certification_expires_at",
        )

    def test_forty_hours_without_the_endorsement_stop_at_level_two(self):
        """The same total lands one rung lower when decon_endorsement is false.

        PRD: "from 40 credited hours upward the level is `LEVEL_2` when the
        inspector has no decontamination endorsement, and `DECON_CERTIFIED` when
        they do."

        Design: Corner/calculations/correct_result_certification_level_from_credited_hours_and_endorsement
        """
        station = _station_for_inspectors()

        inspector = enroll_inspector(
            station["id"], credited_hours=40, completed_at=ENROLMENT,
            full_name="Cara Verify",
        )

        assert float(inspector["training_hours_total"]) == 40.00
        assert inspector["certification_level"] == "LEVEL_2"
        assert inspector["status"] == "ACTIVE"
        assert inspector["decon_endorsement"] is False


class TestFailedTrainingModulesCreditNoHours:
    """The credited total sums only the passed rows, however large a failure is."""

    def test_a_hundred_hour_failed_module_credits_nothing(self):
        """The failed row is recorded with a 201 and the total stays 8.00.

        PRD: "`training_hours_total` is the sum of `hours` over that inspector's
        training records whose `passed` is true, rounded half up to two decimal
        places; modules with `passed` false credit zero hours and are excluded
        from the sum entirely."

        Design: Corner/calculations/input_set_filtering_failed_training_modules_credit_no_hours
        """
        station = _station_for_inspectors()
        inspector = enroll_inspector(
            station["id"], credited_hours=8, decon_endorsement=True,
            completed_at=ENROLMENT, full_name="Ada Field",
        )
        assert float(inspector["training_hours_total"]) == 8.00

        validate_success(
            api_client.create_training_record(
                inspector["id"],
                training_record_payload(100, False, module_code="AIS-DECON-200",
                                        completed_at=ENROLMENT),
                TRAINING_OFFICER,
            ),
            201,
        )

        after = fetch_inspector(inspector["id"])
        assert float(after["training_hours_total"]) == 8.00
        assert after["certification_level"] == "LEVEL_1"

    def test_the_failed_row_is_still_listed_by_the_child_collection(self):
        """Both modules are persisted; only the aggregation filters one out.

        PRD: "modules with `passed` false credit zero hours and are excluded from
        the sum entirely."

        Design: Corner/calculations/input_set_filtering_failed_training_modules_credit_no_hours
        """
        station = _station_for_inspectors()
        inspector = enroll_inspector(
            station["id"], credited_hours=8, decon_endorsement=True,
            completed_at=ENROLMENT, full_name="Ada Field",
        )
        log_training(inspector["id"], 100, False, completed_at=ENROLMENT)

        rows, meta = validate_paginated(
            api_client.list_training_records(inspector["id"], PROGRAM_ADMIN)
        )

        assert meta["total_count"] == 2
        assert sorted(float(row["hours"]) for row in rows) == [8.0, 100.0]
        assert [row["passed"] for row in rows].count(False) == 1

    def test_replacing_the_failure_with_a_passed_module_credits_the_hours(self):
        """A passed 32-hour module takes the same inspector to DECON_CERTIFIED.

        PRD: "Each logged module recomputes the inspector's credited total and,
        from it, their level."

        Design: Corner/calculations/input_set_filtering_failed_training_modules_credit_no_hours
        """
        station = _station_for_inspectors()
        inspector = enroll_inspector(
            station["id"], credited_hours=8, decon_endorsement=True,
            completed_at=ENROLMENT, full_name="Ada Field",
        )
        log_training(inspector["id"], 100, False, completed_at=ENROLMENT)

        log_training(inspector["id"], 32, True, completed_at=ENROLMENT)

        after = fetch_inspector(inspector["id"])
        assert float(after["training_hours_total"]) == 40.00
        assert after["certification_level"] == "DECON_CERTIFIED"


def _twice_refused_vessel():
    """One vessel refused at 09:00 and again at 11:00, so it carries two strikes."""
    ctx = setup_inspection(
        risk_tier="LOW", infestation_status="CLEAN", mandatory_inspection=True,
        arrived_at=ARRIVAL, screen_at=ARRIVAL, residual_water_present=False,
        disposition="REFUSE",
    )
    ctx["first_record"] = ctx["record"]
    ctx = setup_inspection(
        ctx, watercraft=ctx["watercraft"], arrived_at="2026-08-05T11:00:00Z",
        screen_at="2026-08-05T11:00:00Z", residual_water_present=False,
        disposition="REFUSE",
    )
    ctx["second_record"] = ctx["record"]
    return ctx


class TestPenaltyIsBasePlusOneStrikeStep:
    """The citing record's own strike is excluded from the prior-strike count."""

    def test_the_second_refusal_is_cited_at_twenty_two_thousand_five_hundred(self):
        """Two strikes price one prior step: 15000 + 7500 * 1.

        PRD: "`penalty_cents` is 15,000 cents plus 7,500 cents for each *prior*
        strike on the vessel, where the prior strike count is the vessel's
        `compliance_strikes` as it stands at the citation call minus one — the
        minus one excluding the strike this record's own referral booked — and
        never less than zero. A first-offence vessel is therefore cited at 15,000
        cents flat, a vessel with one earlier strike at 22,500 cents."

        Design: Corner/calculations/constants_applied_penalty_is_base_plus_one_strike_step
        """
        ctx = _twice_refused_vessel()
        before = fetch_watercraft(ctx["watercraft"]["id"])
        assert before["compliance_strikes"] == 2
        assert before["watchlist_status"] == "WATCHLISTED"

        data = validate_success(
            api_client.enforce_inspection_record(
                ctx["second_record"]["id"],
                enforcement_payload("CITE", agency_code="MT-FWP",
                                    notes="second refusal cited"),
                ENFORCEMENT_OFFICER,
            ),
            200,
        )

        assert_inspection_record(data)
        assert data["enforcement_status"] == "CITED"
        assert data["penalty_cents"] == 22500
        assert data["referral_reason"] == "INSPECTION_REFUSAL"

    def test_the_citation_books_no_further_strike_and_leaves_the_sibling_alone(self):
        """The vessel stays at two strikes and record one keeps its zero penalty.

        PRD: "`REFERRED → CITED` books the civil penalty."

        Design: Corner/calculations/constants_applied_penalty_is_base_plus_one_strike_step
        """
        ctx = _twice_refused_vessel()

        validate_success(
            api_client.enforce_inspection_record(
                ctx["second_record"]["id"], enforcement_payload("CITE"),
                ENFORCEMENT_OFFICER,
            ),
            200,
        )

        watercraft = fetch_watercraft(ctx["watercraft"]["id"])
        assert watercraft["compliance_strikes"] == 2
        assert watercraft["watchlist_status"] == "WATCHLISTED"
        first = fetch_record(ctx["first_record"]["id"])
        assert first["enforcement_status"] == "REFERRED"
        assert first["penalty_cents"] == 0


def _wakeboat_program():
    """A HIGH-tier clean lake plus an ID agreement that credits but does not waive."""
    ctx = setup_program(
        risk_tier="HIGH", infestation_status="CLEAN", mandatory_inspection=True
    )
    ctx["agreement"] = create_reciprocity_agreement(
        partner_state_code="ID", accepted_seal_prefix="ID-", honors_our_seals=True,
        max_seal_age_hours=72, fee_waiver=False,
    )
    return ctx


class TestRiskScoreRoundsOnceAfterTheVesselFactor:
    """The half-up rounding happens once, on the product, never on the terms."""

    def test_the_honored_seal_puts_the_product_on_the_half_and_it_rounds_up(self):
        """(40 + 0 + 26 - 0 - 20) * 1.25 = 57.5 becomes 58, not 57.

        PRD: "The five point terms are combined first — the tier points plus the
        infestation points plus the water points, minus the dry credit, minus the
        reciprocity credit — that single sum is then multiplied by the vessel
        factor, the product is rounded half up to a whole number exactly once, and
        only then is the result clamped into the closed range from 0 to 100.
        Rounding any individual term before the multiplication yields a different
        integer whenever the vessel factor is not 1.00, and that alternative is not
        this program's rule."

        Design: Corner/calculations/precision_risk_score_rounds_once_after_the_vessel_factor
        """
        ctx = _wakeboat_program()

        ctx = setup_inspection(
            ctx, vessel_type="BALLASTED_WAKEBOAT", arrived_at=ARRIVAL,
            screen_at=ARRIVAL, residual_water_present=True, standing_water_ml=600,
            presented_seal_number="ID-77", presented_seal_state_code="ID",
            presented_seal_issued_at="2026-08-04T09:00:00Z",
        )

        record = ctx["record"]
        assert_inspection_record(record)
        assert record["reciprocity_seal_honored"] is True
        assert record["honored_agreement_id"] == ctx["agreement"]["id"]
        assert record["dry_credit_points"] == 0
        assert record["risk_score"] == 58
        assert record["advisory_risk_score"] == 58
        assert record["risk_band"] == "HIGH"
        assert record["decon_mandatory"] is True
        assert record["quarantine_warranted"] is False

    def test_without_the_seal_credit_the_same_hull_lands_on_another_half(self):
        """(40 + 0 + 26) * 1.25 = 82.5 becomes 83, so the band is EXTREME.

        PRD: "The vessel factor is 1.25 for a `PONTOON_MULTI_CHAMBER` or a
        `BALLASTED_WAKEBOAT` and 1.00 for every other hull class."

        Design: Corner/calculations/precision_risk_score_rounds_once_after_the_vessel_factor
        """
        ctx = _wakeboat_program()

        ctx = setup_inspection(
            ctx, vessel_type="BALLASTED_WAKEBOAT", arrived_at=ARRIVAL,
            screen_at=ARRIVAL, residual_water_present=True, standing_water_ml=600,
        )

        record = ctx["record"]
        assert record["reciprocity_seal_honored"] is False
        assert record["honored_agreement_id"] is None
        assert record["risk_score"] == 83
        assert record["risk_band"] == "EXTREME"
        assert record["quarantine_warranted"] is True

    def test_a_standard_hull_keeps_the_unmultiplied_sum(self):
        """The identical findings on an OPEN_HULL score 46 with a factor of 1.00.

        PRD: "The vessel factor is 1.25 for a `PONTOON_MULTI_CHAMBER` or a
        `BALLASTED_WAKEBOAT` and 1.00 for every other hull class."

        Design: Corner/calculations/precision_risk_score_rounds_once_after_the_vessel_factor
        """
        ctx = _wakeboat_program()

        ctx = setup_inspection(
            ctx, vessel_type="OPEN_HULL", arrived_at=ARRIVAL, screen_at=ARRIVAL,
            residual_water_present=True, standing_water_ml=600,
            presented_seal_number="ID-77", presented_seal_state_code="ID",
            presented_seal_issued_at="2026-08-04T09:00:00Z",
        )

        assert ctx["record"]["risk_score"] == 46
        assert ctx["record"]["risk_band"] == "MODERATE"


def _one_day_dry_screening(ml, ctx=None):
    """Screen a vessel out of the water for exactly 24 hours at the given volume."""
    if ctx is None:
        ctx = setup_program(
            risk_tier="LOW", infestation_status="CLEAN", mandatory_inspection=True
        )
    return setup_inspection(
        ctx, last_removed_at="2026-08-04T09:00:00Z", arrived_at=ARRIVAL,
        screen_at=ARRIVAL, residual_water_present=True, standing_water_ml=ml,
    )


class TestScoreTwentyFourIsLowAndTwentyFiveIsModerate:
    """One point across the LOW/MODERATE frontier changes what is legal."""

    def test_four_hundred_millilitres_score_twenty_four_and_stay_low(self):
        """5 + 24 - 5 = 24, one below BAND_MODERATE_MIN.

        PRD: "`risk_band` follows immediately from `risk_score` on the arrival
        basis, by three half-open thresholds: a score below 25 is `LOW`, a score
        from 25 up to but not including 50 is `MODERATE`, a score from 50 up to
        but not including 75 is `HIGH`, and a score of 75 or more is `EXTREME`."

        Design: Corner/calculations/threshold_boundary_score_24_is_low_and_25_is_moderate
        """
        ctx = _one_day_dry_screening(400)

        record = ctx["record"]
        assert record["dry_credit_points"] == 5
        assert record["risk_score"] == 24
        assert record["advisory_risk_score"] == 24
        assert record["risk_band"] == "LOW"
        assert record["decon_mandatory"] is False
        assert record["quarantine_warranted"] is False

    def test_five_hundred_millilitres_score_exactly_twenty_five_and_turn_moderate(self):
        """5 + 25 - 5 = 25 is inclusive at the MODERATE floor and forces decon.

        PRD: "`decon_mandatory` is true when the band is `HIGH` or `EXTREME`, or
        when the vessel carries `mandatory_decon_flag` true, or when the band is
        `MODERATE` and `residual_water_present` is true — a moderately-scoring
        boat with water still in it does not get to leave untreated."

        Design: Corner/calculations/threshold_boundary_score_24_is_low_and_25_is_moderate
        """
        ctx = _one_day_dry_screening(500)

        record = ctx["record"]
        assert record["dry_credit_points"] == 5
        assert record["risk_score"] == 25
        assert record["risk_band"] == "MODERATE"
        assert record["decon_mandatory"] is True
        assert record["quarantine_warranted"] is False

    def test_the_one_point_difference_decides_whether_a_pass_is_legal(self):
        """PASS succeeds on the 24-point record and is refused on the 25-point one.

        PRD: "A pass is refused when the record's `decon_mandatory` is true, and
        equally when the vessel carries `mandatory_decon_flag` true, unless some
        decontamination order belonging to this record has already reached
        `VERIFIED`; the rejection is `ERR_DECON_REQUIRED_BEFORE_PASS`."

        Design: Corner/calculations/threshold_boundary_score_24_is_low_and_25_is_moderate
        """
        ctx = _one_day_dry_screening(400)
        low_record = ctx["record"]
        ctx = _one_day_dry_screening(500, ctx)
        moderate_record = ctx["record"]
        headers = make_inspector_headers(ctx["inspector_a"]["id"])

        passed = validate_success(
            api_client.dispose_inspection_record(
                low_record["id"], disposition_payload("PASS"), headers
            ),
            200,
        )
        refused = api_client.dispose_inspection_record(
            moderate_record["id"], disposition_payload("PASS"), headers
        )

        assert passed["inspection_status"] == "PASSED"
        assert passed["total_fee_cents"] == 2500
        validate_error(refused, ApiErrorId.ERR_DECON_REQUIRED_BEFORE_PASS)
        assert fetch_record(moderate_record["id"])["inspection_status"] == "SCREENED"


class TestTreatmentEffectivenessAndFlooredDryCredit:
    """A weak but legal treatment scores 30.00 percent and floors a fractional credit."""

    def test_the_minimum_legal_readings_score_thirty_percent(self):
        """0.5 * 0.6 * 1.0 gives 30.00, and floor(72 * 0.30 * 0.75) = 16 leaves 56 hours.

        PRD: "Step three computes the credit: the base dry hours multiplied by
        the effectiveness expressed as a fraction of 100, multiplied by 0.75, then
        floored to a whole number of hours — so even a perfect treatment can never
        earn back more than three quarters of the base obligation."

        Design: Corner/calculations/precision_treatment_effectiveness_and_floored_dry_credit
        """
        ctx = setup_decon_order(
            decon_bay_count=2, arrived_at=ARRIVAL, screen_at=ARRIVAL
        )
        assert ctx["record"]["risk_score"] == 65
        assert ctx["decon_order"]["band_at_order"] == "HIGH"
        set_clock(ARRIVAL)

        order = treat_order(
            ctx["decon_order"]["id"], ctx["inspector_b"]["id"], 120, 2000, 120
        )

        assert_decon_order(order)
        assert order["status"] == "TREATED"
        assert order["attempt_count"] == 1
        assert float(order["treatment_effectiveness_pct"]) == 30.00
        assert order["base_dry_hours"] == 72
        assert order["required_dry_hours"] == 56
        assert_instant_equals(order["treated_at"], "2026-08-05T09:02:00Z", "treated_at")
        assert_instant_equals(order["dry_until"], "2026-08-07T17:02:00Z", "dry_until")
        assert_instant_equals(
            order["bay_released_at"], "2026-08-05T09:32:00Z", "bay_released_at"
        )

    def test_the_same_treatment_bills_two_whole_dwell_minutes(self):
        """A 120-second dwell is 900 cents and the subtotal stays under the surcharge tier.

        PRD: "Second the decontamination component is resolved: `decon_fee_cents`
        is 0 on any disposition call, and on a treatment call it is 450 cents for
        each minute of nozzle dwell, where the dwell in minutes is the recorded
        `dwell_seconds` divided by 60 and rounded **up** to a whole minute — a
        90-second pass is billed as two minutes."

        Design: Corner/calculations/precision_treatment_effectiveness_and_floored_dry_credit
        """
        ctx = setup_decon_order(
            decon_bay_count=2, arrived_at=ARRIVAL, screen_at=ARRIVAL
        )
        set_clock(ARRIVAL)

        treat_order(ctx["decon_order"]["id"], ctx["inspector_b"]["id"], 120, 2000, 120)

        record = fetch_record(ctx["record"]["id"])
        assert record["inspection_fee_cents"] == 2500
        assert record["decon_fee_cents"] == 900
        assert record["surcharge_cents"] == 0
        assert record["total_fee_cents"] == 3400
        assert fetch_station(ctx["station"]["id"])["collected_fees_cents"] == 3400


def _waiver_program():
    """A LOW-tier clean reservoir plus a WY agreement that waives the base fee."""
    ctx = setup_program(
        risk_tier="LOW", infestation_status="CLEAN", mandatory_inspection=True
    )
    ctx["agreement"] = create_reciprocity_agreement(
        partner_state_code="WY", accepted_seal_prefix="WY-", max_seal_age_hours=72,
        fee_waiver=True,
    )
    return ctx


def _screen_with_wyoming_seal(ctx):
    return setup_inspection(
        ctx, arrived_at=ARRIVAL, screen_at=ARRIVAL, residual_water_present=False,
        presented_seal_number="WY-42", presented_seal_state_code="WY",
        presented_seal_issued_at="2026-08-04T09:00:00Z",
    )


class TestReciprocityFeeWaiverZeroesTheInspectionFee:
    """The waiver is resolved first, so every downstream money field collapses to 0."""

    def test_the_waived_pass_charges_nothing_and_credits_nothing(self):
        """inspection, surcharge and total are all 0 and the ledger stays empty.

        PRD: "First the waiver is resolved: the base fee is waived when the
        record's `reciprocity_seal_honored` is true *and* the agreement recorded in
        `honored_agreement_id` carries `fee_waiver` true, in which case
        `inspection_fee_cents` is 0; otherwise `inspection_fee_cents` is 2,500
        cents."

        Design: Corner/calculations/correct_result_reciprocity_fee_waiver_zeroes_the_inspection_fee
        """
        ctx = _screen_with_wyoming_seal(_waiver_program())
        screened = ctx["record"]
        assert screened["reciprocity_seal_honored"] is True
        assert screened["honored_agreement_id"] == ctx["agreement"]["id"]
        assert screened["risk_score"] == 0
        assert screened["risk_band"] == "LOW"

        data = validate_success(
            api_client.dispose_inspection_record(
                screened["id"], disposition_payload("PASS"),
                make_inspector_headers(ctx["inspector_a"]["id"]),
            ),
            200,
        )

        assert data["inspection_status"] == "PASSED"
        assert data["inspection_fee_cents"] == 0
        assert data["decon_fee_cents"] == 0
        assert data["surcharge_cents"] == 0
        assert data["total_fee_cents"] == 0
        assert fetch_station(ctx["station"]["id"])["collected_fees_cents"] == 0

    def test_suspending_the_agreement_restores_both_the_credit_and_the_fee(self):
        """A suspended agreement honours nothing, so the score is 5 and the pass costs 2500.

        PRD: "If the matched agreement is `SUSPENDED`, the seal is simply not
        honoured — this is not an error. The record's `reciprocity_seal_honored` is
        set false, `reciprocity_credit_points` is set to 0, `honored_agreement_id`
        is set null, and the decision stops, leaving the screening to proceed with
        no reciprocity credit."

        Design: Corner/calculations/correct_result_reciprocity_fee_waiver_zeroes_the_inspection_fee
        """
        ctx = _waiver_program()
        move_reciprocity_agreement(ctx["agreement"]["id"], "SUSPENDED")

        ctx = _screen_with_wyoming_seal(ctx)

        screened = ctx["record"]
        assert screened["reciprocity_seal_honored"] is False
        assert screened["honored_agreement_id"] is None
        assert screened["risk_score"] == 5
        data = validate_success(
            api_client.dispose_inspection_record(
                screened["id"], disposition_payload("PASS"),
                make_inspector_headers(ctx["inspector_a"]["id"]),
            ),
            200,
        )
        assert data["inspection_fee_cents"] == 2500
        assert data["total_fee_cents"] == 2500
        assert fetch_station(ctx["station"]["id"])["collected_fees_cents"] == 2500
