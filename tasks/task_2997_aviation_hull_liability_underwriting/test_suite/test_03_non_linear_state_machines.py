"""Non-linear state machines: two parallel dimensions and one cyclic negotiation.

A claim advances its adjustment dimension and its salvage dimension separately,
and the combined state the two reach together is what decides the money.  An
endorsement instead runs a cycle, returning from `QUOTED` to `SUBMITTED` on a
referral while keeping the round counter that eventually stops the loop.
"""

from test_helpers import (
    AdjustmentStatus,
    ApiErrorId,
    CoverageDecision,
    CoverageStatus,
    EndorsementStatus,
    EndorsementType,
    LicenseType,
    LossType,
    PolicyType,
    SalvageAction,
    SalvageStatus,
    SettlementBasis,
    TerritorialLimit,
    TxnBasis,
    TxnType,
    UseClass,
    WarrantyStatus,
    assert_ledger_row,
    validate_error,
    validate_error_is_one_of,
    validate_list,
    validate_unpaginated,
)
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

# ----------------------------------------------------------------------
# The slip and the loss both instances are built on.
# ----------------------------------------------------------------------
BASE_HULL_RATE_PPM = 18000
HULL_DEDUCTIBLE_PPM = 15000
AGREED_VALUE_CENTS = 45000000

# The named pilot's declared figures, which fix the band the hull rates on.
DECLARED_TOTAL_HOURS = 1200
DECLARED_HOURS_ON_TYPE = 80
LAST_TRAINING_AT = "2026-06-01T00:00:00Z"

# The claim file: a wing spar written off a few days after inception.
LOSS_DATE = "2026-09-05T00:00:00Z"
ASSESSED_AT = "2026-09-10T00:00:00Z"
CTL_REPAIR_COST_CENTS = 40000000
RESERVE_CENTS = 45000000
SALVAGE_PROCEEDS_CENTS = 3000000

# The endorsement under negotiation.
ENDORSEMENT_EFFECTIVE_DATE = f.CLOCK_LATE_TERM
FIRST_REFERRAL_REASON = "Premises schedule of aerodromes incomplete"
SECOND_REFERRAL_REASON = "Hangarkeepers exposure still unquantified"


def hull_premium_cents() -> int:
    """The annual premium of the single instructional hull on the slip."""
    band = c.band_for_score(
        c.qualification_score(
            DECLARED_TOTAL_HOURS,
            DECLARED_HOURS_ON_TYPE,
            False,
            LicenseType.CPL,
            LAST_TRAINING_AT,
            f.CLOCK_BEFORE_INCEPTION,
        )
    )
    return c.annual_premium_cents(
        AGREED_VALUE_CENTS,
        c.rate_ppm_for(
            BASE_HULL_RATE_PPM, UseClass.INSTRUCTIONAL, TerritorialLimit.WORLDWIDE, band
        ),
        PolicyType.FLEET,
        1,
    )


def expected_premises_delta_cents() -> int:
    """The premises-liability charge apportioned over the unexpired term."""
    return c.pro_rata_charge_cents(
        c.PREMISES_LIABILITY_ANNUAL_CENTS,
        c.whole_days_between(ENDORSEMENT_EFFECTIVE_DATE, f.POLICY_EFFECTIVE_TO),
        f.POLICY_TERM_DAYS,
    )


def notified_claim_over_the_total_loss_threshold(api):
    """A bound hull with a notified claim whose survey writes the airframe off.

    The assessment is appended while the claim is still `NOTIFIED`, which §3.9
    permits, so the constructive-total-loss flag is already true before either
    dimension has moved anywhere.
    """
    book = fx.bound_policy_mid_term(api, compliant_warranty=True)
    claim = fx.make_claim(
        api, book["policy_id"], book["schedule_id"], loss_date=LOSS_DATE
    )
    fx.make_damage_assessment(
        api,
        claim["id"],
        repair_cost_estimate_cents=CTL_REPAIR_COST_CENTS,
        assessed_at=ASSESSED_AT,
    )
    book["claim_id"] = claim["id"]
    return book


class TestClaimParallelDimensions:
    """The adjustment dimension and the salvage dimension of one claim."""

    def test_tendering_the_wreck_is_refused_while_the_claim_is_only_notified(self, api):
        """PRD §3.9: "From `NONE`, an action of `RETAIN` moves the claim to
        `RETAINED_BY_INSURED` and an action of `TENDER` moves it to `TENDERED`; both require
        the claim's `adjustment_status` to be `INVESTIGATING`, `COVERAGE_REFERRED` or
        `RESERVED`, and tendering additionally requires the claim's `ctl_flag` to be true,
        since only a constructive total loss produces a wreck worth tendering."

        Design: Difficulty/non_linear_state_machine/claim_parallel_adjustment_and_salvage_dimensions
        """
        book = notified_claim_over_the_total_loss_threshold(api)
        claim = fx.fetch_claim(api, book["claim_id"])
        # The wreck is worth tendering, so the adjustment state is the only rule left.
        assert claim["ctl_flag"] is True
        assert claim["ctl_ratio_ppm"] == c.ctl_ratio_ppm(
            CTL_REPAIR_COST_CENTS, AGREED_VALUE_CENTS
        )
        assert claim["adjustment_status"] == AdjustmentStatus.NOTIFIED
        assert claim["loss_type"] == LossType.TOTAL_LOSS

        response = api.dispose_salvage(
            book["claim_id"],
            f.salvage_disposition_payload(SalvageAction.TENDER),
            headers=users.CLAIMS_ADJUSTER,
        )

        validate_error(response, ApiErrorId.CLAIM_INVALID_STATE)
        unchanged = fx.fetch_claim(api, book["claim_id"])
        assert unchanged["salvage_status"] == SalvageStatus.NONE
        assert unchanged["adjustment_status"] == AdjustmentStatus.NOTIFIED

    def test_salvage_reaches_tendered_without_moving_the_adjustment_dimension(self, api):
        """PRD §3.9: "The salvage dimension advances independently of the adjustment
        dimension: it is legal to dispose of salvage before or after settlement, subject
        only to the per-step conditions below."

        Design: Difficulty/non_linear_state_machine/claim_parallel_adjustment_and_salvage_dimensions
        """
        book = notified_claim_over_the_total_loss_threshold(api)
        investigating = fx.investigate_claim(api, book["claim_id"])
        assert investigating["adjustment_status"] == AdjustmentStatus.INVESTIGATING
        assert investigating["salvage_status"] == SalvageStatus.NONE

        claim = validate_unpaginated(
            api.dispose_salvage(
                book["claim_id"],
                f.salvage_disposition_payload(SalvageAction.TENDER),
                headers=users.CLAIMS_ADJUSTER,
            )
        )

        assert claim["salvage_status"] == SalvageStatus.TENDERED
        # The adjustment dimension has not moved with it.
        assert claim["adjustment_status"] == AdjustmentStatus.INVESTIGATING
        assert claim["version"] > investigating["version"]

    def test_the_wreck_stays_tendered_across_the_coverage_decision(self, api):
        """PRD §2.8: "Neither pair is a single combined state; a schedule can be on risk
        with an unproven warranty, and salvage can be disposed of before or after the claim
        is settled."

        Design: Difficulty/non_linear_state_machine/claim_parallel_adjustment_and_salvage_dimensions
        """
        book = notified_claim_over_the_total_loss_threshold(api)
        fx.investigate_claim(api, book["claim_id"])
        fx.dispose_salvage(api, book["claim_id"], SalvageAction.TENDER)

        claim = fx.decide_coverage(
            api,
            book["claim_id"],
            headers=users.CLAIMS_ADJUSTER,
            decision=CoverageDecision.COVERED,
            reserve_cents=RESERVE_CENTS,
        )

        assert claim["adjustment_status"] == AdjustmentStatus.RESERVED
        assert claim["salvage_status"] == SalvageStatus.TENDERED
        assert claim["reserve_cents"] == RESERVE_CENTS
        assert claim["coverage_decided_by_user_id"] == users.CLAIMS_ADJUSTER_ID
        # The hull is still on risk, with its warranty proven.
        schedule = fx.fetch_schedule(api, book["schedule_id"])
        assert schedule["coverage_status"] == CoverageStatus.ACTIVE
        assert schedule["warranty_status"] == WarrantyStatus.COMPLIANT

    def test_a_wreck_sold_before_settlement_is_credited_against_the_payment(self, api):
        """PRD §3.10: "The salvage credit is next: it equals the claim's
        `salvage_proceeds_cents` when and only when the claim's `salvage_status` is `SOLD`,
        and is zero in every other salvage state."

        Design: Difficulty/non_linear_state_machine/claim_parallel_adjustment_and_salvage_dimensions
        """
        book = notified_claim_over_the_total_loss_threshold(api)
        fx.investigate_claim(api, book["claim_id"])
        fx.dispose_salvage(api, book["claim_id"], SalvageAction.TENDER)
        fx.decide_coverage(
            api,
            book["claim_id"],
            headers=users.CLAIMS_ADJUSTER,
            decision=CoverageDecision.COVERED,
            reserve_cents=RESERVE_CENTS,
        )
        sold = fx.dispose_salvage(
            api,
            book["claim_id"],
            SalvageAction.SELL,
            salvage_proceeds_cents=SALVAGE_PROCEEDS_CENTS,
        )
        assert sold["salvage_status"] == SalvageStatus.SOLD
        assert sold["adjustment_status"] == AdjustmentStatus.RESERVED

        claim = validate_unpaginated(
            api.settle_claim(
                book["claim_id"],
                f.settlement_payload(SettlementBasis.AGREED_VALUE),
                headers=users.SECOND_CLAIMS_ADJUSTER,
            )
        )

        deductible = c.deductible_cents(AGREED_VALUE_CENTS, HULL_DEDUCTIBLE_PPM)
        # Both dimensions have reached their terminal values together.
        assert claim["adjustment_status"] == AdjustmentStatus.SETTLED
        assert claim["salvage_status"] == SalvageStatus.SOLD
        assert claim["salvage_proceeds_cents"] == SALVAGE_PROCEEDS_CENTS
        assert claim["deductible_applied_cents"] == deductible
        assert claim["settlement_amount_cents"] == (
            AGREED_VALUE_CENTS - deductible - SALVAGE_PROCEEDS_CENTS
        )


def submitted_premises_liability_endorsement(api):
    """A bound policy with a premises-liability endorsement awaiting its first quote."""
    book = fx.bound_policy_mid_term(api)
    endorsement = fx.make_endorsement(
        api,
        f.endorsement_payload(
            book["policy_id"],
            EndorsementType.PREMISES_LIABILITY,
            effective_date=ENDORSEMENT_EFFECTIVE_DATE,
        ),
        headers=users.BROKER,
    )
    book["endorsement"] = endorsement
    book["endorsement_id"] = endorsement["id"]
    return book


def quote_referral_quote(api, endorsement_id):
    """Drive one full negotiation loop: quote, referral, re-quote."""
    fx.quote_endorsement(api, endorsement_id)
    fx.refer_endorsement(api, endorsement_id, referral_reason=FIRST_REFERRAL_REASON)
    return fx.quote_endorsement(api, endorsement_id)


class TestEndorsementNegotiationCycle:
    """The quote/referral loop and the round counter that terminates it."""

    def test_first_quotation_prices_the_flat_premises_charge_pro_rata(self, api):
        """PRD §3.6: "Each quotation increments `quote_round` by one, writes the computed
        delta into `quoted_premium_delta_cents`, and records the acting `X-User-ID` into
        `quoted_by_user_id`."

        Design: Difficulty/non_linear_state_machine/endorsement_quote_referral_cycle_with_round_ceiling
        """
        book = submitted_premises_liability_endorsement(api)
        assert book["endorsement"]["status"] == EndorsementStatus.SUBMITTED
        assert book["endorsement"]["quote_round"] == 0

        endorsement = validate_unpaginated(
            api.quote_endorsement(book["endorsement_id"], headers=users.UNDERWRITER)
        )

        assert endorsement["status"] == EndorsementStatus.QUOTED
        assert endorsement["quote_round"] == 1
        assert endorsement["quoted_premium_delta_cents"] == expected_premises_delta_cents()
        assert endorsement["quoted_by_user_id"] == users.UNDERWRITER_ID

    def test_referral_clears_the_figure_but_retains_the_round_counter(self, api):
        """PRD §3.6: "It clears `quoted_premium_delta_cents` back to null and
        `quoted_by_user_id` back to null, but it deliberately **retains** `quote_round`, so
        the negotiation ceiling still bites."

        Design: Difficulty/non_linear_state_machine/endorsement_quote_referral_cycle_with_round_ceiling
        """
        book = submitted_premises_liability_endorsement(api)
        fx.quote_endorsement(api, book["endorsement_id"])

        endorsement = validate_unpaginated(
            api.refer_endorsement(
                book["endorsement_id"],
                f.referral_payload(referral_reason=FIRST_REFERRAL_REASON),
                headers=users.UNDERWRITER,
            )
        )

        assert endorsement["status"] == EndorsementStatus.SUBMITTED
        assert endorsement["quote_round"] == 1
        assert endorsement["quoted_premium_delta_cents"] is None
        assert endorsement["quoted_by_user_id"] is None
        assert endorsement["referral_reason"] == FIRST_REFERRAL_REASON

    def test_re_pricing_after_a_referral_advances_the_round_not_the_figure(self, api):
        """PRD §3.6: "If the broker will not accept the figure, an `Underwriter` records a
        referral, which cycles the endorsement `QUOTED → SUBMITTED` for re-pricing."

        Design: Difficulty/non_linear_state_machine/endorsement_quote_referral_cycle_with_round_ceiling
        """
        book = submitted_premises_liability_endorsement(api)

        endorsement = quote_referral_quote(api, book["endorsement_id"])

        assert endorsement["status"] == EndorsementStatus.QUOTED
        assert endorsement["quote_round"] == 2
        # Nothing about the risk changed, so the re-quote is the same money.
        assert endorsement["quoted_premium_delta_cents"] == expected_premises_delta_cents()
        assert endorsement["quoted_by_user_id"] == users.UNDERWRITER_ID

    def test_the_third_quote_is_final_and_a_fourth_is_refused(self, api):
        """PRD §3.6: "Once `quote_round` has reached 3, a fourth quotation attempt is refused
        with `ERR_QUOTE_ROUNDS_EXHAUSTED` and the endorsement must be bound or voided; the
        referral back-edge is likewise refused at that point, because the endorsement can no
        longer be re-priced."

        Design: Difficulty/non_linear_state_machine/endorsement_quote_referral_cycle_with_round_ceiling
        """
        book = submitted_premises_liability_endorsement(api)
        quote_referral_quote(api, book["endorsement_id"])
        fx.refer_endorsement(
            api, book["endorsement_id"], referral_reason=SECOND_REFERRAL_REASON
        )
        third = fx.quote_endorsement(api, book["endorsement_id"])
        assert third["status"] == EndorsementStatus.QUOTED
        assert third["quote_round"] == c.MAX_QUOTE_ROUNDS

        response = api.quote_endorsement(book["endorsement_id"], headers=users.UNDERWRITER)

        # The ceiling and the state gate both bar the fourth attempt.
        validate_error_is_one_of(
            response,
            [
                ApiErrorId.QUOTE_ROUNDS_EXHAUSTED,
                ApiErrorId.ENDORSEMENT_INVALID_STATE,
            ],
        )
        unchanged = fx.fetch_endorsement(api, book["endorsement_id"])
        assert unchanged["quote_round"] == c.MAX_QUOTE_ROUNDS
        assert unchanged["status"] == EndorsementStatus.QUOTED
        assert unchanged["quoted_premium_delta_cents"] == expected_premises_delta_cents()

    def test_the_whole_negotiation_writes_nothing_to_the_ledger(self, api):
        """PRD §3.6: "Binding freezes `premium_delta_cents` from
        `quoted_premium_delta_cents` — the figure charged is the figure last quoted, not a
        fresh computation — and appends one `ENDORSEMENT_PREMIUM` ledger row with a `basis`
        of `PRO_RATA`, the endorsement's own identifier in `endorsement_id`, an
        `effective_date` equal to the endorsement's `effective_date`, and an `amount_cents`
        equal to `premium_delta_cents`."

        Design: Difficulty/non_linear_state_machine/endorsement_quote_referral_cycle_with_round_ceiling
        """
        book = submitted_premises_liability_endorsement(api)

        quote_referral_quote(api, book["endorsement_id"])
        fx.refer_endorsement(
            api, book["endorsement_id"], referral_reason=SECOND_REFERRAL_REASON
        )
        fx.quote_endorsement(api, book["endorsement_id"])

        # Nothing was bound, so the charge was never frozen onto the endorsement.
        endorsement = fx.fetch_endorsement(api, book["endorsement_id"])
        assert endorsement["premium_delta_cents"] is None
        # The ledger still holds only the premium written when the policy was bound.
        rows, meta = validate_list(
            api.list_premium_transactions(
                headers=users.UNDERWRITER,
                params={"policy_id": book["policy_id"], "limit": 100},
            )
        )
        assert meta["total_count"] == 1
        assert_ledger_row(
            rows[0],
            txn_type=TxnType.INITIAL_PREMIUM,
            amount_cents=hull_premium_cents(),
            basis=TxnBasis.ANNUAL,
            effective_date=f.POLICY_EFFECTIVE_FROM,
            policy_id=book["policy_id"],
        )
        assert rows[0]["endorsement_id"] is None
        assert (
            fx.fetch_policy(api, book["policy_id"])["written_premium_cents"]
            == hull_premium_cents()
        )
