"""Dual-variant calculations: the two settlement bases and the two pilot-hour bases.

The same total loss on the same policy settles differently on the agreed-value
and the depreciated-value bases, and the same untouched pilot rates a hull
differently on declared hours and on audited hours.  Every expected figure below
is re-derived from the arithmetic the PRD pins down, using the pure helpers of
the toolkit, rather than read back out of the response under test.
"""

from test_helpers import (
    AdjustmentStatus,
    CoverageDecision,
    CoverageStatus,
    LicenseType,
    PolicyType,
    SalvageAction,
    SalvageStatus,
    SettlementBasis,
    TerritorialLimit,
    TxnBasis,
    TxnType,
    UseClass,
    WarrantyBasis,
    WarrantyFinding,
    WarrantyStatus,
    assert_instants_equal,
    assert_ledger_row,
    validate_list,
    validate_unpaginated,
)
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

# ----------------------------------------------------------------------
# The commercial terms every policy in this module is opened on, repeated
# here as the inputs the expected figures are derived from.
# ----------------------------------------------------------------------
BASE_HULL_RATE_PPM = 18000
HULL_DEDUCTIBLE_PPM = 15000
AGREED_VALUE_CENTS = 45000000

# The airframe the hulls are written on: a 2016 twin.
HULL_NEW_VALUE_CENTS = 66000000
MANUFACTURE_YEAR = 2016
SECOND_REGISTRATION_MARK = "N516NW"

# The hours the broker declares for the named pilot.
DECLARED_TOTAL_HOURS = 1200
DECLARED_HOURS_ON_TYPE = 80
LAST_TRAINING_AT = "2026-06-01T00:00:00Z"
INSTRUMENT_RATED = False

# The hours the logbook audit confirms.
VERIFIED_TOTAL_HOURS = 600
VERIFIED_HOURS_ON_TYPE = 50

# The claim file both losses are driven through.
LOSS_DATE = "2026-10-15T00:00:00Z"
ASSESSED_AT = "2026-10-20T00:00:00Z"
REPAIR_COST_ESTIMATE_CENTS = 40000000
RESERVE_CENTS = 45000000
BREACH_REASON = "Logbook audit could not evidence the warranted 50 hours on type"

# Two live hulls sit three short of the fleet-size credit threshold, so the
# gross annual premium stands unreduced.
LIVE_HULLS_WITHOUT_CREDIT = 2


def declared_band(clock_utc: str) -> str:
    """The rating band the pilot's declared hours earn at the given clock."""
    return c.band_for_score(
        c.qualification_score(
            DECLARED_TOTAL_HOURS,
            DECLARED_HOURS_ON_TYPE,
            INSTRUMENT_RATED,
            LicenseType.CPL,
            LAST_TRAINING_AT,
            clock_utc,
        )
    )


def audited_band(clock_utc: str) -> str:
    """The rating band the pilot's audited hours earn at the given clock."""
    return c.band_for_score(
        c.qualification_score(
            VERIFIED_TOTAL_HOURS,
            VERIFIED_HOURS_ON_TYPE,
            INSTRUMENT_RATED,
            LicenseType.CPL,
            LAST_TRAINING_AT,
            clock_utc,
        )
    )


def instructional_rate_ppm(band: str) -> int:
    """The four-factor rate of a worldwide instructional hull on a given band."""
    return c.rate_ppm_for(
        BASE_HULL_RATE_PPM, UseClass.INSTRUCTIONAL, TerritorialLimit.WORLDWIDE, band
    )


def instructional_premium_cents(band: str, live_schedule_count: int) -> int:
    """The annual hull premium of one instructional hull on a given band."""
    return c.annual_premium_cents(
        AGREED_VALUE_CENTS,
        instructional_rate_ppm(band),
        PolicyType.FLEET,
        live_schedule_count,
    )


def two_identical_total_losses(api):
    """One policy carrying two structurally identical total losses.

    Both hulls are 2016 twins written on the same instructional terms at the
    same agreed value, both are flown by the same named pilot, and both suffer
    the same loss on the same date with the same repair estimate.  The first
    hull's warranty evidence is verified and the second hull's warranty is
    breached and then waived, which is what makes one loss payable on the
    agreed-value basis and the other only on market-value terms.
    """
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    operator = fx.make_operator(api)
    first_airframe = fx.make_aircraft(api)
    second_airframe = fx.make_aircraft(
        api, f.aircraft_payload(registration_mark=SECOND_REGISTRATION_MARK)
    )
    pilot = fx.make_pilot(api)
    policy = fx.make_policy(api, operator["id"])
    first = fx.make_schedule(api, policy["id"], first_airframe["id"], pilot["id"])
    second = fx.make_schedule(api, policy["id"], second_airframe["id"], pilot["id"])
    fx.bind_policy(api, policy["id"])
    fx.set_warranty(api, first["id"], WarrantyFinding.EVIDENCE_VERIFIED)
    fx.set_warranty(api, second["id"], WarrantyFinding.BREACH, breach_reason=BREACH_REASON)
    fx.set_warranty(api, second["id"], WarrantyFinding.WAIVER)
    fx.advance_clock(api, f.CLOCK_LATE_TERM)
    claim_ids = []
    for schedule in (first, second):
        claim = fx.make_claim(api, policy["id"], schedule["id"], loss_date=LOSS_DATE)
        fx.investigate_claim(api, claim["id"])
        fx.make_damage_assessment(
            api,
            claim["id"],
            repair_cost_estimate_cents=REPAIR_COST_ESTIMATE_CENTS,
            assessed_at=ASSESSED_AT,
        )
        fx.decide_coverage(
            api,
            claim["id"],
            headers=users.CLAIMS_ADJUSTER,
            decision=CoverageDecision.COVERED,
            reserve_cents=RESERVE_CENTS,
        )
        fx.dispose_salvage(api, claim["id"], SalvageAction.TENDER)
        claim_ids.append(claim["id"])
    return {
        "policy_id": policy["id"],
        "compliant_schedule_id": first["id"],
        "waived_schedule_id": second["id"],
        "compliant_claim_id": claim_ids[0],
        "waived_claim_id": claim_ids[1],
    }


class TestSettlementBases:
    """The agreed-value and depreciated-value bases on one identical loss."""

    def test_agreed_value_basis_pays_the_whole_agreed_value_less_its_deductible(self, api):
        """PRD §3.10: "On the `AGREED_VALUE` basis the gross is simply the schedule's
        `agreed_value_cents`: the agreed sum is paid without any proof of market value,
        which is the whole commercial point of agreed-value hull cover."

        Design: Difficulty/dual_variant_calc/hull_settlement_agreed_value_vs_depreciated_value_basis
        """
        book = two_identical_total_losses(api)

        claim = validate_unpaginated(
            api.settle_claim(
                book["compliant_claim_id"],
                f.settlement_payload(SettlementBasis.AGREED_VALUE),
                headers=users.SECOND_CLAIMS_ADJUSTER,
            )
        )

        gross = AGREED_VALUE_CENTS
        expected_deductible = c.deductible_cents(gross, HULL_DEDUCTIBLE_PPM)
        assert claim["settlement_basis"] == SettlementBasis.AGREED_VALUE
        assert claim["deductible_applied_cents"] == expected_deductible
        assert claim["settlement_amount_cents"] == gross - expected_deductible
        assert claim["adjustment_status"] == AdjustmentStatus.SETTLED
        assert claim["reserve_cents"] == 0

    def test_depreciated_value_basis_uses_the_loss_year_not_the_clock_year(self, api):
        """PRD §3.10: "That depreciated value is derived exactly as in §3.1, but the
        reference year is the calendar year of the claim's `loss_date`, **not** the
        calendar year of the current clock and never the airframe's reported
        `current_depreciated_value_cents`."

        Design: Difficulty/dual_variant_calc/hull_settlement_agreed_value_vs_depreciated_value_basis
        """
        book = two_identical_total_losses(api)

        claim = validate_unpaginated(
            api.settle_claim(
                book["waived_claim_id"],
                f.settlement_payload(SettlementBasis.DEPRECIATED_VALUE),
                headers=users.SECOND_CLAIMS_ADJUSTER,
            )
        )

        loss_year = int(LOSS_DATE[:4])
        depreciated = c.depreciated_value_cents(
            HULL_NEW_VALUE_CENTS, MANUFACTURE_YEAR, loss_year
        )
        gross = min(AGREED_VALUE_CENTS, depreciated)
        expected_deductible = c.deductible_cents(gross, HULL_DEDUCTIBLE_PPM)
        assert gross == depreciated
        assert claim["settlement_basis"] == SettlementBasis.DEPRECIATED_VALUE
        assert claim["deductible_applied_cents"] == expected_deductible
        assert claim["settlement_amount_cents"] == gross - expected_deductible
        assert claim["adjustment_status"] == AdjustmentStatus.SETTLED
        assert claim["salvage_status"] == SalvageStatus.TENDERED

    def test_market_value_terms_pay_materially_less_on_the_very_same_loss(self, api):
        """PRD §3.10: "Because the deductible is a proportion of the gross, the deductible
        on a depreciated-value settlement is smaller than the deductible on the
        agreed-value settlement of the very same loss."

        Design: Difficulty/dual_variant_calc/hull_settlement_agreed_value_vs_depreciated_value_basis
        """
        book = two_identical_total_losses(api)

        on_agreed_value = validate_unpaginated(
            api.settle_claim(
                book["compliant_claim_id"],
                f.settlement_payload(SettlementBasis.AGREED_VALUE),
                headers=users.SECOND_CLAIMS_ADJUSTER,
            )
        )
        on_market_value = validate_unpaginated(
            api.settle_claim(
                book["waived_claim_id"],
                f.settlement_payload(SettlementBasis.DEPRECIATED_VALUE),
                headers=users.SECOND_CLAIMS_ADJUSTER,
            )
        )

        agreed_gross = AGREED_VALUE_CENTS
        market_gross = min(
            AGREED_VALUE_CENTS,
            c.depreciated_value_cents(
                HULL_NEW_VALUE_CENTS, MANUFACTURE_YEAR, int(LOSS_DATE[:4])
            ),
        )
        agreed_deductible = c.deductible_cents(agreed_gross, HULL_DEDUCTIBLE_PPM)
        market_deductible = c.deductible_cents(market_gross, HULL_DEDUCTIBLE_PPM)
        agreed_net = agreed_gross - agreed_deductible
        market_net = market_gross - market_deductible

        assert on_agreed_value["settlement_amount_cents"] == agreed_net
        assert on_market_value["settlement_amount_cents"] == market_net
        assert market_net < agreed_net
        assert market_deductible < agreed_deductible

        # Both hulls have left the sum-insured population for good.
        for schedule_id in (book["compliant_schedule_id"], book["waived_schedule_id"]):
            assert (
                fx.fetch_schedule(api, schedule_id)["coverage_status"]
                == CoverageStatus.TOTAL_LOSS_SETTLED
            )
        policy = fx.fetch_policy(api, book["policy_id"])
        assert policy["paid_hull_cents"] == agreed_net + market_net
        assert policy["live_schedule_count"] == 0
        assert policy["total_hull_sum_insured_cents"] == 0

        # Neither return carries the short-rate factor of a mid-term cancellation.
        hull_premium = instructional_premium_cents(
            declared_band(f.CLOCK_BEFORE_INCEPTION), LIVE_HULLS_WITHOUT_CREDIT
        )
        unearned = c.pro_rata_return_cents(
            hull_premium,
            c.whole_days_between(LOSS_DATE, f.POLICY_EFFECTIVE_TO),
            f.POLICY_TERM_DAYS,
        )
        rows, meta = validate_list(
            api.list_premium_transactions(
                headers=users.UNDERWRITER,
                params={
                    "policy_id": book["policy_id"],
                    "txn_type": TxnType.SETTLEMENT_RETURN,
                    "limit": 100,
                },
            )
        )
        assert meta["total_count"] == 2
        for row in rows:
            assert_ledger_row(
                row,
                txn_type=TxnType.SETTLEMENT_RETURN,
                amount_cents=-unearned,
                basis=TxnBasis.PRO_RATA,
                policy_id=book["policy_id"],
            )
            assert row["endorsement_id"] is None


class TestPilotHoursVariants:
    """The declared and audited versions of one pilot's qualification score."""

    def test_registration_populates_only_the_declared_version_of_the_score(self, api):
        """PRD §3.2: "At registration only the declared version exists:
        `qualification_score_logged` and `rating_band_logged` are populated, while
        `qualification_score_verified` and `rating_band_verified` stay null."

        Design: Difficulty/dual_variant_calc/pilot_qualification_logged_hours_vs_verified_hours
        """
        book = fx.bound_policy_with_hull(api)

        pilot = fx.fetch_pilot(api, book["pilot_id"])
        expected_score = c.qualification_score(
            DECLARED_TOTAL_HOURS,
            DECLARED_HOURS_ON_TYPE,
            INSTRUMENT_RATED,
            LicenseType.CPL,
            LAST_TRAINING_AT,
            f.CLOCK_BEFORE_INCEPTION,
        )
        assert pilot["qualification_score_logged"] == expected_score
        assert pilot["rating_band_logged"] == c.band_for_score(expected_score)
        assert pilot["qualification_score_verified"] is None
        assert pilot["rating_band_verified"] is None
        assert pilot["verified_at"] is None

        # The hull it names is therefore rated on the declared figures (§3.4).
        declared = declared_band(f.CLOCK_BEFORE_INCEPTION)
        schedule = fx.fetch_schedule(api, book["schedule_id"])
        assert schedule["warranty_basis"] == WarrantyBasis.LOGGED_HOURS
        assert schedule["rated_pilot_band"] == declared
        assert schedule["rate_ppm"] == instructional_rate_ppm(declared)
        assert schedule["hull_premium_cents"] == instructional_premium_cents(declared, 1)

    def test_logbook_audit_writes_the_verified_version_beside_the_declared_one(self, api):
        """PRD §3.2: "It stamps `verified_at` with the current logical clock, and it
        computes the verified version of the score using the audited figures, writing
        `qualification_score_verified` and `rating_band_verified`."

        Design: Difficulty/dual_variant_calc/pilot_qualification_logged_hours_vs_verified_hours
        """
        book = fx.bound_policy_with_hull(api)

        pilot = validate_unpaginated(
            api.verify_pilot_hours(
                book["pilot_id"],
                f.hours_verification_payload(
                    verified_total_hours=VERIFIED_TOTAL_HOURS,
                    verified_hours_on_type=VERIFIED_HOURS_ON_TYPE,
                ),
                headers=users.UNDERWRITER,
            ),
            expected_status=201,
        )

        audited_score = c.qualification_score(
            VERIFIED_TOTAL_HOURS,
            VERIFIED_HOURS_ON_TYPE,
            INSTRUMENT_RATED,
            LicenseType.CPL,
            LAST_TRAINING_AT,
            f.CLOCK_BEFORE_INCEPTION,
        )
        declared_score = c.qualification_score(
            DECLARED_TOTAL_HOURS,
            DECLARED_HOURS_ON_TYPE,
            INSTRUMENT_RATED,
            LicenseType.CPL,
            LAST_TRAINING_AT,
            f.CLOCK_BEFORE_INCEPTION,
        )
        assert pilot["verified_total_hours"] == VERIFIED_TOTAL_HOURS
        assert pilot["verified_hours_on_type"] == VERIFIED_HOURS_ON_TYPE
        assert_instants_equal(pilot["verified_at"], f.CLOCK_BEFORE_INCEPTION, "verified_at")
        assert pilot["qualification_score_verified"] == audited_score
        assert pilot["rating_band_verified"] == c.band_for_score(audited_score)
        # The declared version is untouched: the two versions live side by side.
        assert pilot["qualification_score_logged"] == declared_score
        assert pilot["rating_band_logged"] == c.band_for_score(declared_score)
        assert pilot["rating_band_verified"] != pilot["rating_band_logged"]

    def test_audit_re_rates_the_named_hull_onto_the_audited_band(self, api):
        """PRD §3.2: "It reaches out across the book to every aircraft schedule that names
        this pilot and whose `coverage_status` is `PENDING`, `ACTIVE` or
        `SUSPENDED_WARRANTY`, processes them in `created_at` ascending order, and for each
        one flips `warranty_basis` from `LOGGED_HOURS` to `VERIFIED_HOURS`, then re-derives
        that schedule's `rated_pilot_band`, `rate_ppm` and `hull_premium_cents` from the
        audited band."

        Design: Difficulty/dual_variant_calc/pilot_qualification_logged_hours_vs_verified_hours
        """
        book = fx.bound_policy_with_hull(api)
        declared = declared_band(f.CLOCK_BEFORE_INCEPTION)

        fx.verify_hours(
            api,
            book["pilot_id"],
            verified_total_hours=VERIFIED_TOTAL_HOURS,
            verified_hours_on_type=VERIFIED_HOURS_ON_TYPE,
        )

        audited = audited_band(f.CLOCK_BEFORE_INCEPTION)
        schedule = fx.fetch_schedule(api, book["schedule_id"])
        assert schedule["warranty_basis"] == WarrantyBasis.VERIFIED_HOURS
        assert schedule["rated_pilot_band"] == audited
        assert schedule["rate_ppm"] == instructional_rate_ppm(audited)
        assert schedule["hull_premium_cents"] == instructional_premium_cents(audited, 1)
        # Proving fewer hours than were declared costs more, not less.
        assert schedule["rate_ppm"] > instructional_rate_ppm(declared)
        assert schedule["hull_premium_cents"] > instructional_premium_cents(declared, 1)
        # The hull stays on risk, and its warranty passes on the audited figures (§3.5).
        assert schedule["coverage_status"] == CoverageStatus.ACTIVE
        assert schedule["warranty_status"] == WarrantyStatus.COMPLIANT

    def test_re_rating_posts_the_full_annual_difference_of_the_two_premiums(self, api):
        """PRD §3.2: "For each affected schedule the annual difference between the new
        `hull_premium_cents` and the old one is taken, and when that difference is not zero
        **and** the schedule's policy has `status` `BOUND`, a `RERATE_ADJUSTMENT` ledger row
        is appended with a `basis` of `ANNUAL`, a null `endorsement_id`, an `effective_date`
        of the current logical clock, and an `amount_cents` equal to that difference."

        Design: Difficulty/dual_variant_calc/pilot_qualification_logged_hours_vs_verified_hours
        """
        book = fx.bound_policy_with_hull(api)

        fx.verify_hours(
            api,
            book["pilot_id"],
            verified_total_hours=VERIFIED_TOTAL_HOURS,
            verified_hours_on_type=VERIFIED_HOURS_ON_TYPE,
        )

        on_declared = instructional_premium_cents(declared_band(f.CLOCK_BEFORE_INCEPTION), 1)
        on_audited = instructional_premium_cents(audited_band(f.CLOCK_BEFORE_INCEPTION), 1)
        rows, meta = validate_list(
            api.list_premium_transactions(
                headers=users.UNDERWRITER,
                params={
                    "policy_id": book["policy_id"],
                    "txn_type": TxnType.RERATE_ADJUSTMENT,
                    "limit": 100,
                },
            )
        )
        assert meta["total_count"] == 1
        assert_ledger_row(
            rows[0],
            txn_type=TxnType.RERATE_ADJUSTMENT,
            amount_cents=on_audited - on_declared,
            basis=TxnBasis.ANNUAL,
            effective_date=f.CLOCK_BEFORE_INCEPTION,
            policy_id=book["policy_id"],
        )
        assert rows[0]["endorsement_id"] is None
        assert fx.fetch_policy(api, book["policy_id"])["written_premium_cents"] == on_audited
