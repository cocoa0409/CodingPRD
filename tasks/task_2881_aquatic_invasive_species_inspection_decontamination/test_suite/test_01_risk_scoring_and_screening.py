"""Risk scoring at screening: the two bases, the signed credits and the bands."""
from test_helpers import (
    add_watercraft,
    api_client,
    assert_inspection_record,
    assert_instant_equals,
    create_reciprocity_agreement,
    fetch_record,
    fetch_watercraft,
    make_inspector_headers,
    open_record,
    screening_payload,
    set_clock,
    setup_program,
    validate_success,
)


def _arrival_versus_screening_context():
    """A HIGH/CLEAN lake, a plain hull out of the water since 2026-07-30T08:00:00Z.

    The boater arrives at 2026-08-01T07:00:00Z and is screened two hours later,
    so the arrival basis sees 47 whole standing hours and the screening basis 49.
    """
    ctx = setup_program(
        clock="2026-08-01T00:00:00Z", risk_tier="HIGH", infestation_status="CLEAN",
        decon_bay_count=2, seal_stock_initial_count=3, mandatory_inspection=True,
    )
    vessel = add_watercraft(
        ctx, registration_number="MT-1001", vessel_type="OPEN_HULL",
        hull_length_ft=18, last_removed_at="2026-07-30T08:00:00Z",
    )
    set_clock("2026-08-01T07:00:00Z")
    record = open_record(
        ctx["station"]["id"], vessel["id"], "2026-08-01T07:00:00Z",
        ctx["inspector_a"]["id"],
    )
    set_clock("2026-08-01T09:00:00Z")
    ctx["watercraft"] = vessel
    ctx["record"] = record
    return ctx


def _screen_with_residual_water(ctx, standing_water_ml, expected_version=None):
    vessel = ctx["watercraft"]
    version = (
        expected_version if expected_version is not None
        else fetch_watercraft(vessel["id"])["version"]
    )
    return api_client.screen_inspection_record(
        ctx["record"]["id"],
        screening_payload(
            version, True, standing_water_ml=standing_water_ml,
            prior_water_body_id=ctx["water_body"]["id"],
        ),
        make_inspector_headers(ctx["inspector_a"]["id"]),
    )


class TestRiskScoreBases:
    """The authoritative arrival basis against the advisory screening basis."""

    def test_arrival_basis_scores_higher_than_the_screening_basis(self):
        """The two bases differ by exactly the extra dry-credit day of queue wait.

        PRD: "The formula runs **twice** on every screening, differing only in
        the basis instant used for the standing time."  PRD: "The credit is then
        5 points for each complete 24-hour day of standing time - the standing
        hours divided by 24 and floored, multiplied by 5 - capped at 25 points,
        which is to say the credit tops out after five full days out of the
        water."  47 standing hours at arrival credit one day and 49 at screening
        credit two, so the arrival score exceeds the advisory score by 5.

        Design: Difficulty/dual_variant_calc/risk_score_arrival_basis_versus_screening_basis
        """
        ctx = _arrival_versus_screening_context()

        record = validate_success(_screen_with_residual_water(ctx, 250), 200)

        assert_inspection_record(record)
        assert record["risk_score"] == 57
        assert record["advisory_risk_score"] == 52
        assert record["risk_score"] - record["advisory_risk_score"] == 5

    def test_only_the_arrival_basis_writes_dry_credit_points_and_the_gates(self):
        """dry_credit_points, the band and both flags all read the arrival basis.

        PRD: "The **arrival basis** uses the record's `arrived_at` - the moment
        the boater reached the station - and it is authoritative: its output is
        written to `risk_score`, its dry credit is written to
        `dry_credit_points`, and every gate downstream reads it, including the
        band, the decontamination requirement, the quarantine warrant, the base
        dry hours and the base hold hours."  PRD: "The **screening basis** uses
        the logical clock at the moment of the screening call instead, and its
        output is written to `advisory_risk_score` for audit only; it never
        gates anything."

        Design: Difficulty/dual_variant_calc/risk_score_arrival_basis_versus_screening_basis
        """
        ctx = _arrival_versus_screening_context()

        record = validate_success(_screen_with_residual_water(ctx, 250), 200)

        assert record["dry_credit_points"] == 5
        assert record["risk_band"] == "HIGH"
        assert record["decon_mandatory"] is True
        assert record["quarantine_warranted"] is False

    def test_screening_stamps_the_status_and_the_completion_instant(self):
        """A screened record leaves INITIATED and records the logical clock.

        PRD: "Screening advances `inspection_status` from `INITIATED` to
        `SCREENED`".  PRD: "Every screening, first or repeat, sets
        `screening_completed_at` to the current logical time, writes the
        screened prior water body back onto the vessel's `last_water_body_id`,
        and advances both the vessel's `version` and the record's `version` by
        1."

        Design: Difficulty/dual_variant_calc/risk_score_arrival_basis_versus_screening_basis
        """
        ctx = _arrival_versus_screening_context()

        record = validate_success(_screen_with_residual_water(ctx, 250), 200)

        assert record["inspection_status"] == "SCREENED"
        assert_instant_equals(
            record["screening_completed_at"], "2026-08-01T09:00:00Z",
            "screening_completed_at",
        )
        stored = fetch_record(record["id"])
        assert stored["risk_score"] == 57
        assert stored["advisory_risk_score"] == 52


def _clamped_credits_context():
    """A LOW but CONFIRMED_INFESTED reservoir, an honoured Idaho seal, ten dry days.

    The signed point sum is 5 + 30 - 25 - 20 = -10 before the clamp.
    """
    ctx = setup_program(
        clock="2026-08-01T00:00:00Z", risk_tier="LOW",
        infestation_status="CONFIRMED_INFESTED", decon_bay_count=2,
        seal_stock_initial_count=3, mandatory_inspection=True,
    )
    ctx["agreement"] = create_reciprocity_agreement(
        partner_state_code="ID", accepted_seal_prefix="ID-",
        honors_our_seals=True, max_seal_age_hours=72, fee_waiver=False,
    )
    vessel = add_watercraft(
        ctx, registration_number="MT-3001", vessel_type="OPEN_HULL",
        hull_length_ft=18, last_removed_at="2026-07-26T09:00:00Z",
    )
    set_clock("2026-08-05T09:00:00Z")
    record = open_record(
        ctx["station"]["id"], vessel["id"], "2026-08-05T09:00:00Z",
        ctx["inspector_a"]["id"],
    )
    set_clock("2026-08-05T10:00:00Z")
    ctx["watercraft"] = vessel
    ctx["record"] = record
    return ctx


def _screen_with_idaho_seal(ctx):
    return api_client.screen_inspection_record(
        ctx["record"]["id"],
        screening_payload(
            fetch_watercraft(ctx["watercraft"]["id"])["version"], False,
            standing_water_ml=0, prior_water_body_id=ctx["water_body"]["id"],
            presented_seal_number="ID-55010", presented_seal_state_code="ID",
            presented_seal_issued_at="2026-08-03T09:00:00Z",
        ),
        make_inspector_headers(ctx["inspector_a"]["id"]),
    )


class TestSignedCreditsAndClamp:
    """Credits large enough to drive the sum negative before the clamp applies."""

    def test_credits_exceeding_the_points_clamp_the_score_to_zero(self):
        """A negative signed sum is clamped to 0 rather than reported negative.

        PRD: "The five point terms are combined first - the tier points plus the
        infestation points plus the water points, minus the dry credit, minus
        the reciprocity credit - that single sum is then multiplied by the
        vessel factor, the product is rounded half up to a whole number exactly
        once, and only then is the result clamped into the closed range from 0
        to 100."  A LOW tier and a CONFIRMED_INFESTED status contribute 35
        points against a 25-point dry credit and a 20-point reciprocity credit.

        Design: Difficulty/combinatorial_formula/risk_score_signed_credits_clamp_with_independent_quarantine_warrant
        """
        ctx = _clamped_credits_context()

        record = validate_success(_screen_with_idaho_seal(ctx), 200)

        assert_inspection_record(record)
        assert record["risk_score"] == 0
        assert record["advisory_risk_score"] == 0
        assert record["risk_band"] == "LOW"
        assert record["decon_mandatory"] is False

    def test_dry_credit_is_capped_at_twenty_five_points(self):
        """Ten whole days out of the water still credit only the 25-point ceiling.

        PRD: "The credit is then 5 points for each complete 24-hour day of
        standing time - the standing hours divided by 24 and floored, multiplied
        by 5 - capped at 25 points, which is to say the credit tops out after
        five full days out of the water."

        Design: Difficulty/combinatorial_formula/risk_score_signed_credits_clamp_with_independent_quarantine_warrant
        """
        ctx = _clamped_credits_context()

        record = validate_success(_screen_with_idaho_seal(ctx), 200)

        assert record["dry_credit_points"] == 25

    def test_honoured_partner_seal_books_the_fixed_twenty_point_credit(self):
        """An in-prefix, in-age Idaho seal is honoured against its own agreement.

        PRD: "A seal that survives both tests is honoured. The record's
        `reciprocity_seal_honored` is set true, `honored_agreement_id` is set to
        the matched agreement, and `reciprocity_credit_points` is set to 20 -
        the fixed credit an out-of-state inspection buys a boater at this
        program's stations."

        Design: Difficulty/combinatorial_formula/risk_score_signed_credits_clamp_with_independent_quarantine_warrant
        """
        ctx = _clamped_credits_context()

        record = validate_success(_screen_with_idaho_seal(ctx), 200)

        assert record["reciprocity_seal_honored"] is True
        assert record["reciprocity_credit_points"] == 20
        assert record["honored_agreement_id"] == ctx["agreement"]["id"]

    def test_quarantine_warrant_survives_the_lowest_possible_band(self):
        """A zero-scoring vessel off a confirmed-infested water still warrants a seal.

        PRD: "`quarantine_warranted` is true when the band is `EXTREME`, or when
        the prior water body's `infestation_status` is `CONFIRMED_INFESTED`."
        PRD: "That second clause is why a quarantine order can be issued against
        an otherwise low-scoring vessel: a boat that just came off a
        confirmed-infested lake warrants a seal even if it scores 12."

        Design: Difficulty/combinatorial_formula/risk_score_signed_credits_clamp_with_independent_quarantine_warrant
        """
        ctx = _clamped_credits_context()

        record = validate_success(_screen_with_idaho_seal(ctx), 200)

        assert record["risk_band"] == "LOW"
        assert record["quarantine_warranted"] is True


def _extreme_boundary_context():
    """A HIGH/SUSPECT reservoir and a plain hull dry for exactly 30 hours.

    40 tier points plus 15 infestation points plus 25 water points less a
    single 5-point dry-credit day land the arrival score exactly on 75.
    """
    ctx = setup_program(
        clock="2026-08-01T00:00:00Z", risk_tier="HIGH", infestation_status="SUSPECT",
        decon_bay_count=1, seal_stock_initial_count=2, mandatory_inspection=True,
    )
    vessel = add_watercraft(
        ctx, registration_number="MT-9001", vessel_type="OPEN_HULL",
        hull_length_ft=18, last_removed_at="2026-08-04T03:00:00Z",
    )
    set_clock("2026-08-05T09:00:00Z")
    record = open_record(
        ctx["station"]["id"], vessel["id"], "2026-08-05T09:00:00Z",
        ctx["inspector_a"]["id"],
    )
    ctx["watercraft"] = vessel
    ctx["record"] = record
    return ctx


class TestExtremeBandBoundary:
    """The EXTREME band minimum is inclusive, and one point below it is HIGH."""

    def test_a_score_of_exactly_seventy_five_is_extreme(self):
        """75 lands in EXTREME because the band thresholds are half-open.

        PRD: "`risk_band` follows immediately from `risk_score` on the arrival
        basis, by three half-open thresholds: a score below 25 is `LOW`, a score
        from 25 up to but not including 50 is `MODERATE`, a score from 50 up to
        but not including 75 is `HIGH`, and a score of 75 or more is
        `EXTREME`."  PRD: "The boundaries are inclusive on the low side, so a
        score of exactly 50 is `HIGH` and not `MODERATE`, and a score of exactly
        75 is `EXTREME` and not `HIGH`."

        Design: Difficulty/boundary_precision_check/risk_score_exactly_at_extreme_band_minimum
        """
        ctx = _extreme_boundary_context()

        record = validate_success(_screen_with_residual_water(ctx, 550), 200)

        assert_inspection_record(record)
        assert record["risk_score"] == 75
        assert record["advisory_risk_score"] == 75
        assert record["dry_credit_points"] == 5
        assert record["risk_band"] == "EXTREME"
        assert record["decon_mandatory"] is True
        assert record["quarantine_warranted"] is True
        assert record["inspection_status"] == "SCREENED"

    def test_one_point_below_the_boundary_withdraws_the_quarantine_warrant(self):
        """A corrected re-screen scoring 74 is HIGH and no longer warrants quarantine.

        PRD: "a record already in `SCREENED` may be screened again, holding the
        `SCREENED -> SCREENED` self-transition, because an inspector who
        mis-measured a bilge should be able to correct the observation on the
        spot and have the later screening supersede the earlier one."  PRD: "A
        re-screen overwrites `residual_water_present` and `standing_water_ml`
        with whatever the new payload supplies, re-runs the seal decision and
        both scoring variants, and overwrites `risk_score`,
        `advisory_risk_score`, `risk_band`, `decon_mandatory` and
        `quarantine_warranted`."

        Design: Difficulty/boundary_precision_check/risk_score_exactly_at_extreme_band_minimum
        """
        ctx = _extreme_boundary_context()
        first = validate_success(_screen_with_residual_water(ctx, 550), 200)
        assert first["risk_score"] == 75

        corrected = validate_success(_screen_with_residual_water(ctx, 450), 200)

        assert corrected["risk_score"] == 74
        assert corrected["risk_band"] == "HIGH"
        assert corrected["quarantine_warranted"] is False
        assert corrected["decon_mandatory"] is True

    def test_the_volume_component_of_the_water_points_is_floored_per_hundred_ml(self):
        """550 millilitres contribute five whole volume points, 450 contribute four.

        PRD: "when it is true, it contributes a base of 20 points plus one
        further point for each whole 100 millilitres of `standing_water_ml` -
        that per-volume component being the smaller of 15 points and the
        measured millilitres divided by 100 and floored to a whole number, so
        the volume component saturates at 15 points once 1,500 millilitres is
        reached."

        Design: Difficulty/boundary_precision_check/risk_score_exactly_at_extreme_band_minimum
        """
        ctx = _extreme_boundary_context()

        at_550 = validate_success(_screen_with_residual_water(ctx, 550), 200)
        at_450 = validate_success(_screen_with_residual_water(ctx, 450), 200)

        assert at_550["risk_score"] - at_450["risk_score"] == 1
