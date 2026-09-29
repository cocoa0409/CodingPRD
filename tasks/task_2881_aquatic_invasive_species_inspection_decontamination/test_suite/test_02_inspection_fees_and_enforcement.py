"""The pinned fee formula, the station ledger and the enforcement dimension."""
from test_helpers import (
    add_watercraft,
    assert_decon_order,
    assert_inspection_record,
    assert_instant_equals,
    assert_station_fee_ledger,
    assert_strike_posture,
    dispose_record,
    enforce_record,
    fetch_record,
    fetch_station,
    fetch_watercraft,
    open_record,
    order_decon,
    screen_record,
    set_clock,
    setup_program,
    treat_order,
    verify_dry,
)


def _high_band_record_awaiting_decon(*, decon_bay_count=2,
                                     seal_stock_initial_count=3):
    """A HIGH/CLEAN water, a vessel with no dry credit, screened at 65 and DECON.

    40 tier points plus a 20-point residual base plus 5 volume points for
    500 millilitres give the arrival score 65, so the band is HIGH and the
    disposition books the flat 2,500-cent inspection fee.
    """
    ctx = setup_program(
        clock="2026-08-01T00:00:00Z", risk_tier="HIGH", infestation_status="CLEAN",
        decon_bay_count=decon_bay_count,
        seal_stock_initial_count=seal_stock_initial_count, mandatory_inspection=True,
    )
    vessel = add_watercraft(
        ctx, last_water_body_id=None, registration_number="MT-4001",
        vessel_type="OPEN_HULL", hull_length_ft=20,
    )
    set_clock("2026-08-05T08:00:00Z")
    record = open_record(
        ctx["station"]["id"], vessel["id"], "2026-08-05T08:00:00Z",
        ctx["inspector_a"]["id"],
    )
    record = screen_record(
        record["id"], ctx["inspector_a"]["id"], vessel["version"],
        residual_water_present=True, standing_water_ml=500,
        prior_water_body_id=ctx["water_body"]["id"],
    )
    record = dispose_record(record["id"], ctx["inspector_a"]["id"], "DECON")
    ctx["watercraft"] = vessel
    ctx["record"] = record
    ctx["decon_order"] = order_decon(
        record["id"], ctx["inspector_a"]["id"], record["version"]
    )
    set_clock("2026-08-05T09:00:00Z")
    return ctx


class TestSurchargeTierFromSubtotal:
    """The surcharge tier is keyed on the subtotal, never on the total it feeds."""

    def test_tier_is_selected_from_the_pre_surcharge_subtotal(self):
        """A 24,550-cent subtotal takes the 5 percent tier even though the total exceeds 25,000.

        PRD: "Fourth the surcharge rate is selected **from that pre-surcharge
        subtotal**: no surcharge at all when the subtotal is below 10,000 cents,
        5 percent when the subtotal is from 10,000 cents up to but not including
        25,000 cents, and 10 percent from 25,000 cents upward."  PRD: "The tier
        is never re-selected from `total_fee_cents`".

        Design: Difficulty/combinatorial_formula/inspection_fee_surcharge_tier_from_presurcharge_subtotal
        """
        ctx = _high_band_record_awaiting_decon()

        treat_order(ctx["decon_order"]["id"], ctx["inspector_b"]["id"], 140, 3000, 2940)

        record = fetch_record(ctx["record"]["id"])
        assert_inspection_record(record)
        assert record["risk_score"] == 65
        assert record["risk_band"] == "HIGH"
        assert record["inspection_fee_cents"] == 2500
        assert record["decon_fee_cents"] == 22050
        assert record["surcharge_cents"] == 1228
        assert record["total_fee_cents"] == 25778
        assert record["total_fee_cents"] != 27005

    def test_the_surcharge_is_rounded_half_up_to_whole_cents(self):
        """Five percent of 24,550 cents is 1,227.5, which rounds up to 1,228.

        PRD: "Fifth `surcharge_cents` is the subtotal multiplied by that rate,
        rounded half up to whole cents."  PRD: "`decon_fee_cents` is 0 on any
        disposition call, and on a treatment call it is 450 cents for each
        minute of nozzle dwell, where the dwell in minutes is the recorded
        `dwell_seconds` divided by 60 and rounded **up** to a whole minute - a
        90-second pass is billed as two minutes."

        Design: Difficulty/combinatorial_formula/inspection_fee_surcharge_tier_from_presurcharge_subtotal
        """
        ctx = _high_band_record_awaiting_decon()

        treat_order(ctx["decon_order"]["id"], ctx["inspector_b"]["id"], 140, 3000, 2940)

        record = fetch_record(ctx["record"]["id"])
        assert record["decon_fee_cents"] == 22050
        assert record["surcharge_cents"] == 1228

    def test_the_station_ledger_is_adjusted_by_the_delta(self):
        """The station collects the new total once, not the disposition total twice.

        PRD: "And seventh, the station's `collected_fees_cents` is adjusted by
        the *delta* - the new `total_fee_cents` minus whatever `total_fee_cents`
        the record previously carried - so that a re-run never double-books."

        Design: Difficulty/combinatorial_formula/inspection_fee_surcharge_tier_from_presurcharge_subtotal
        """
        ctx = _high_band_record_awaiting_decon()
        before = fetch_station(ctx["station"]["id"])
        assert before["collected_fees_cents"] == 2500

        treat_order(ctx["decon_order"]["id"], ctx["inspector_b"]["id"], 140, 3000, 2940)

        station = fetch_station(ctx["station"]["id"])
        assert station["collected_fees_cents"] == 25778
        assert_station_fee_ledger(station, [fetch_record(ctx["record"]["id"])])

    def test_treatment_stamps_the_effectiveness_and_the_dry_obligation(self):
        """A perfect treatment on a HIGH order earns back three quarters of 72 hours.

        PRD: "Step three computes the credit: the base dry hours multiplied by
        the effectiveness expressed as a fraction of 100, multiplied by 0.75,
        then floored to a whole number of hours - so even a perfect treatment can
        never earn back more than three quarters of the base obligation."  PRD:
        "`treatment_started_at` is the current logical time - the inclusive start
        of the order's bay occupation - `treated_at` is `treatment_started_at`
        advanced by `dwell_seconds` seconds, and `bay_released_at` is `treated_at`
        advanced by 30 minutes, forming the inclusive end of the occupation."

        Design: Difficulty/combinatorial_formula/inspection_fee_surcharge_tier_from_presurcharge_subtotal
        """
        ctx = _high_band_record_awaiting_decon()

        order = treat_order(
            ctx["decon_order"]["id"], ctx["inspector_b"]["id"], 140, 3000, 2940
        )

        assert_decon_order(order)
        assert float(order["treatment_effectiveness_pct"]) == 100.00
        assert order["base_dry_hours"] == 72
        assert order["required_dry_hours"] == 18
        assert_instant_equals(order["treated_at"], "2026-08-05T09:49:00Z", "treated_at")
        assert_instant_equals(order["dry_until"], "2026-08-06T03:49:00Z", "dry_until")
        assert_instant_equals(
            order["bay_released_at"], "2026-08-05T10:19:00Z", "bay_released_at"
        )


def _passed_record_on_a_clean_low_water():
    """A LOW/CLEAN lake and a dry vessel: score 5, band LOW, disposition PASS."""
    ctx = setup_program(
        clock="2026-08-01T00:00:00Z", risk_tier="LOW", infestation_status="CLEAN",
        decon_bay_count=1, seal_stock_initial_count=2, mandatory_inspection=True,
    )
    vessel = add_watercraft(
        ctx, last_water_body_id=None, registration_number="MT-5001",
        vessel_type="OPEN_HULL", hull_length_ft=14,
    )
    set_clock("2026-08-05T09:00:00Z")
    record = open_record(
        ctx["station"]["id"], vessel["id"], "2026-08-05T09:00:00Z",
        ctx["inspector_a"]["id"],
    )
    record = screen_record(
        record["id"], ctx["inspector_a"]["id"], vessel["version"],
        residual_water_present=False, standing_water_ml=0,
        prior_water_body_id=ctx["water_body"]["id"],
    )
    ctx["record"] = dispose_record(record["id"], ctx["inspector_a"]["id"], "PASS")
    ctx["watercraft"] = vessel
    return ctx


class TestEnforcementDimensionIndependence:
    """The enforcement dimension advances while the inspection dimension is terminal."""

    def test_enforcement_reaches_cited_on_an_already_passed_record(self):
        """A closed inspection is still referable and citable.

        PRD: "`enforcement_status` advances on its own transition set with no
        reference whatsoever to `inspection_status`, and neither dimension gates
        the other."  PRD: "A record may sit in terminal `PASSED` while its
        enforcement dimension travels `NONE -> REFERRED -> CITED`, and a record
        may be `CITED` while its inspection dimension is still `DECON_REQUIRED`."

        Design: Difficulty/non_linear_state_machine/inspection_record_two_dimensions_advance_independently
        """
        ctx = _passed_record_on_a_clean_low_water()
        assert ctx["record"]["inspection_status"] == "PASSED"

        enforce_record(
            ctx["record"]["id"], "REFER", referral_reason="DECON_EVASION",
            agency_code="MTFWP",
        )
        cited = enforce_record(ctx["record"]["id"], "CITE")

        assert cited["enforcement_status"] == "CITED"
        assert cited["inspection_status"] == "PASSED"
        assert cited["referral_reason"] == "DECON_EVASION"
        assert cited["agency_code"] == "MTFWP"

    def test_first_offence_citation_books_the_flat_base_penalty(self):
        """One strike at the citation call means zero prior strikes and 15,000 cents.

        PRD: "`penalty_cents` is 15,000 cents plus 7,500 cents for each *prior*
        strike on the vessel, where the prior strike count is the vessel's
        `compliance_strikes` as it stands at the citation call minus one - the
        minus one excluding the strike this record's own referral booked - and
        never less than zero."  PRD: "A first-offence vessel is therefore cited
        at 15,000 cents flat, a vessel with one earlier strike at 22,500 cents."

        Design: Difficulty/non_linear_state_machine/inspection_record_two_dimensions_advance_independently
        """
        ctx = _passed_record_on_a_clean_low_water()
        enforce_record(
            ctx["record"]["id"], "REFER", referral_reason="DECON_EVASION",
            agency_code="MTFWP",
        )

        cited = enforce_record(ctx["record"]["id"], "CITE")

        assert cited["penalty_cents"] == 15000
        assert cited["total_fee_cents"] == 2500

    def test_the_referral_books_one_strike_without_watchlisting_the_vessel(self):
        """A single strike stays below the watchlist threshold, so the flag stays down.

        PRD: "the vessel's `compliance_strikes` is incremented by 1; because of
        that increment, `watchlist_status` flips from `CLEAR` to `WATCHLISTED`
        once `compliance_strikes` has reached 2; and because of that flip,
        `mandatory_decon_flag` is set true."

        Design: Difficulty/non_linear_state_machine/inspection_record_two_dimensions_advance_independently
        """
        ctx = _passed_record_on_a_clean_low_water()
        enforce_record(
            ctx["record"]["id"], "REFER", referral_reason="DECON_EVASION",
            agency_code="MTFWP",
        )
        enforce_record(ctx["record"]["id"], "CITE")

        vessel = fetch_watercraft(ctx["watercraft"]["id"])
        assert_strike_posture(vessel, 1)


class TestFeeLedgerConservedOnAbandonment:
    """An abandonment reverses exactly the treatment-attributable portion."""

    def test_abandonment_books_the_decon_fee_and_its_surcharge_as_a_refund(self):
        """fee_refunded_cents is decon_fee_cents plus surcharge_cents, i.e. 23,278.

        PRD: "`TREATED -> ABANDONED` sets `status` to `ABANDONED` and
        `verified_by_inspector_id` from `X-User-ID`, then cascades: the parent
        record moves `DECON_REQUIRED -> DECON_FAILED_ABANDONED`,
        `fee_refunded_cents` on that record is set to `decon_fee_cents` plus
        `surcharge_cents` - the treatment-attributable portion of the ledger -
        and that same amount is subtracted from the station's
        `collected_fees_cents` and added to its `refunded_fees_cents`."

        Design: Difficulty/compensating_invariant/fee_ledger_conserved_when_an_abandonment_refunds_the_treatment_charge
        """
        ctx = _high_band_record_awaiting_decon(
            decon_bay_count=1, seal_stock_initial_count=2
        )
        treat_order(ctx["decon_order"]["id"], ctx["inspector_b"]["id"], 140, 3000, 2940)
        before = fetch_record(ctx["record"]["id"])
        assert before["fee_refunded_cents"] == 0
        set_clock("2026-08-05T09:49:00Z")

        order = verify_dry(ctx["decon_order"]["id"], ctx["inspector_c"]["id"], "ABANDON")

        assert order["status"] == "ABANDONED"
        record = fetch_record(ctx["record"]["id"])
        assert record["fee_refunded_cents"] == 23278
        assert record["total_fee_cents"] == 25778
        assert record["inspection_status"] == "DECON_FAILED_ABANDONED"

    def test_the_station_ledger_balances_after_the_refund(self):
        """collected_fees_cents falls back to the 2,500-cent inspection fee alone.

        PRD: "For every station, `collected_fees_cents` equals the sum over that
        station's inspection records of `total_fee_cents` minus
        `fee_refunded_cents`, and `refunded_fees_cents` equals the sum of
        `fee_refunded_cents` over the same records."  PRD: "abandoning a treated
        vessel reverses the treatment-attributable portion exactly, so after an
        abandonment the ledger equals what it would have been had the record been
        disposed with no treatment at all."

        Design: Difficulty/compensating_invariant/fee_ledger_conserved_when_an_abandonment_refunds_the_treatment_charge
        """
        ctx = _high_band_record_awaiting_decon(
            decon_bay_count=1, seal_stock_initial_count=2
        )
        treat_order(ctx["decon_order"]["id"], ctx["inspector_b"]["id"], 140, 3000, 2940)
        set_clock("2026-08-05T09:49:00Z")

        verify_dry(ctx["decon_order"]["id"], ctx["inspector_c"]["id"], "ABANDON")

        station = fetch_station(ctx["station"]["id"])
        record = fetch_record(ctx["record"]["id"])
        assert station["collected_fees_cents"] == 2500
        assert station["refunded_fees_cents"] == 23278
        assert_station_fee_ledger(station, [record])

    def test_an_abandonment_is_not_a_verification_for_the_vessel(self):
        """The vessel keeps a null last_decon_verified_at and no lifted obligation.

        PRD: "`ABANDON` is deliberately exempt from that gate: a vessel may be
        abandoned at any point after treatment."  PRD: "The parent record moves
        `DECON_REQUIRED -> DECON_COMPLETED`, and that record transition in turn
        stamps the vessel's `last_decon_verified_at` at the current logical time
        and clears the vessel's `mandatory_decon_flag`."

        Design: Difficulty/compensating_invariant/fee_ledger_conserved_when_an_abandonment_refunds_the_treatment_charge
        """
        ctx = _high_band_record_awaiting_decon(
            decon_bay_count=1, seal_stock_initial_count=2
        )
        treat_order(ctx["decon_order"]["id"], ctx["inspector_b"]["id"], 140, 3000, 2940)
        set_clock("2026-08-05T09:49:00Z")

        verify_dry(ctx["decon_order"]["id"], ctx["inspector_c"]["id"], "ABANDON")

        vessel = fetch_watercraft(ctx["watercraft"]["id"])
        assert vessel["mandatory_decon_flag"] is False
        assert vessel["last_decon_verified_at"] is None


def _two_referrals_on_one_vessel():
    """One vessel, two records: a refusal cascade and an explicit officer referral."""
    ctx = setup_program(
        clock="2026-08-01T00:00:00Z", risk_tier="LOW", infestation_status="CLEAN",
        decon_bay_count=1, seal_stock_initial_count=2, mandatory_inspection=True,
    )
    vessel = add_watercraft(
        ctx, last_water_body_id=None, registration_number="MT-9950",
        vessel_type="OPEN_HULL", hull_length_ft=14,
    )
    set_clock("2026-08-05T09:00:00Z")
    record_a = open_record(
        ctx["station"]["id"], vessel["id"], "2026-08-05T09:00:00Z",
        ctx["inspector_a"]["id"],
    )
    screen_record(
        record_a["id"], ctx["inspector_a"]["id"], vessel["version"],
        residual_water_present=False, standing_water_ml=0,
        prior_water_body_id=ctx["water_body"]["id"],
    )
    record_a = dispose_record(record_a["id"], ctx["inspector_a"]["id"], "REFUSE")
    record_b = open_record(
        ctx["station"]["id"], vessel["id"], "2026-08-05T11:00:00Z",
        ctx["inspector_a"]["id"],
    )
    record_b = screen_record(
        record_b["id"], ctx["inspector_a"]["id"],
        fetch_watercraft(vessel["id"])["version"],
        residual_water_present=False, standing_water_ml=0,
        prior_water_body_id=ctx["water_body"]["id"],
    )
    record_b = enforce_record(
        record_b["id"], "REFER", referral_reason="DECON_EVASION", agency_code="MTFWP"
    )
    ctx["watercraft"] = vessel
    ctx["record_a"] = record_a
    ctx["record_b"] = record_b
    return ctx


class TestStrikesConservedOnDismissal:
    """A dismissal unwinds the strike, the watchlist flip and the standing flag."""

    def test_dismissal_walks_the_three_level_derivation_back(self):
        """Two strikes and a watchlisted vessel return to one strike and CLEAR.

        PRD: "`REFERRED -> DISMISSED` is the compensating action. It sets
        `enforcement_status` to `DISMISSED`, resets `penalty_cents` to 0,
        decrements the vessel's `compliance_strikes` by 1, and re-derives both
        `watchlist_status` and `mandatory_decon_flag` from the reduced count, so
        a vessel that dropped below two strikes returns to `CLEAR` with its
        mandatory-decontamination obligation lifted."

        Design: Difficulty/compensating_invariant/compliance_strikes_conserved_when_a_referral_is_dismissed
        """
        ctx = _two_referrals_on_one_vessel()
        before = fetch_watercraft(ctx["watercraft"]["id"])
        assert_strike_posture(before, 2)

        dismissed = enforce_record(
            ctx["record_b"]["id"], "DISMISS", notes="hearing officer vacated the referral"
        )

        assert dismissed["enforcement_status"] == "DISMISSED"
        assert dismissed["penalty_cents"] == 0
        vessel = fetch_watercraft(ctx["watercraft"]["id"])
        assert_strike_posture(vessel, 1)

    def test_the_sibling_referral_survives_the_dismissal(self):
        """The refusal-driven referral on the other record is untouched.

        PRD: "A referral that is later dismissed leaves the vessel exactly as it
        was: same strike count, same watchlist status, same flag."  PRD: "It sets
        `enforcement_status` to `REFERRED`, sets `referral_reason` - the
        payload's value on an officer-driven call, `INSPECTION_REFUSAL` on the
        refusal cascade, `QUARANTINE_RELEASE_FAILURE` on the release-failure
        cascade, and `SEAL_TAMPER` on the breach cascade".

        Design: Difficulty/compensating_invariant/compliance_strikes_conserved_when_a_referral_is_dismissed
        """
        ctx = _two_referrals_on_one_vessel()

        enforce_record(ctx["record_b"]["id"], "DISMISS")

        record_a = fetch_record(ctx["record_a"]["id"])
        assert record_a["enforcement_status"] == "REFERRED"
        assert record_a["referral_reason"] == "INSPECTION_REFUSAL"
        assert record_a["inspection_status"] == "REFUSED"

    def test_dismissal_leaves_the_inspection_dimension_alone(self):
        """Record B is still SCREENED after its enforcement dimension is dismissed.

        PRD: "`enforcement_status` advances on its own transition set with no
        reference whatsoever to `inspection_status`, and neither dimension gates
        the other."

        Design: Difficulty/compensating_invariant/compliance_strikes_conserved_when_a_referral_is_dismissed
        """
        ctx = _two_referrals_on_one_vessel()

        enforce_record(ctx["record_b"]["id"], "DISMISS")

        record_b = fetch_record(ctx["record_b"]["id"])
        assert record_b["inspection_status"] == "SCREENED"
        assert record_b["enforcement_status"] == "DISMISSED"
