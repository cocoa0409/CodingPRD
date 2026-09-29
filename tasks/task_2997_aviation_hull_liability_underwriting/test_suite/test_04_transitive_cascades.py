"""Transitive cascades: one request, four hops of consequence.

The PRD pins two four-hop chains in §2.8 and develops them in §3.5 and §3.10.
A total-loss settlement writes figures onto the claim, takes the hull off risk,
returns unearned premium to the ledger and re-derives the policy's aggregates; a
warranty finding of breach suspends the cover, refers the open claims and drops
the policy's outstanding reserve without moving any money at all.

Each test asserts one hop of a chain, or one invariant that must hold once the
whole chain has run.  Every expected figure is re-derived here from the PRD's own
arithmetic rather than read back out of the response under test.
"""

from test_helpers import (
    AdjustmentStatus,
    ApiErrorId,
    CoverageDecision,
    CoverageStatus,
    LossType,
    SalvageStatus,
    SettlementBasis,
    TxnBasis,
    TxnType,
    WarrantyFinding,
    WarrantyStatus,
    assert_field_values,
    assert_ledger_row,
    assert_ledger_txn_types,
    ledger_signed_sum,
    validate_error,
    validate_unpaginated,
)
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

# ----------------------------------------------------------------------
# The commercial terms every scenario in this file is written on, taken from
# the payloads the suite submits, and the figures the PRD derives from them.
# ----------------------------------------------------------------------
POLICY_TERMS = f.policy_payload("operator")
HULL_TERMS = f.schedule_payload("policy", "aircraft", "pilot")
NAMED_PILOT = f.pilot_payload()

TERM_DAYS = c.whole_days_between(
    POLICY_TERMS["effective_from"], POLICY_TERMS["effective_to"]
)
AGREED_VALUE_CENTS = HULL_TERMS["agreed_value_cents"]


def logged_band_at(clock_utc):
    """The named pilot's rating band on the hours the broker declared (§3.2)."""
    return c.band_for_score(
        c.qualification_score(
            NAMED_PILOT["total_logged_hours"],
            NAMED_PILOT["hours_on_type"],
            NAMED_PILOT["instrument_rated"],
            NAMED_PILOT["license_type"],
            NAMED_PILOT["last_training_completed_at"],
            clock_utc,
        )
    )


def hull_premium_at(clock_utc, live_schedule_count=1):
    """The annual hull premium of the scheduled hull, through the rate chain of §3.4."""
    rate_ppm = c.rate_ppm_for(
        POLICY_TERMS["base_hull_rate_ppm"],
        HULL_TERMS["use_class"],
        POLICY_TERMS["territorial_limit_code"],
        logged_band_at(clock_utc),
    )
    return c.annual_premium_cents(
        AGREED_VALUE_CENTS,
        rate_ppm,
        POLICY_TERMS["policy_type"],
        live_schedule_count,
    )


HULL_PREMIUM_CENTS = hull_premium_at(f.CLOCK_BEFORE_INCEPTION)

# ----------------------------------------------------------------------
# The settlement cascade
# ----------------------------------------------------------------------
TOTAL_LOSS_DATE = "2026-10-15T00:00:00Z"
TOTAL_LOSS_ASSESSED_AT = "2026-10-20T00:00:00Z"
TOTAL_LOSS_REPAIR_ESTIMATE_CENTS = 40000000
TOTAL_LOSS_RESERVE_CENTS = 45000000

AGREED_VALUE_DEDUCTIBLE_CENTS = c.deductible_cents(
    AGREED_VALUE_CENTS, POLICY_TERMS["hull_deductible_ppm"]
)
AGREED_VALUE_NET_CENTS = AGREED_VALUE_CENTS - AGREED_VALUE_DEDUCTIBLE_CENTS
UNEXPIRED_DAYS_AT_LOSS = c.whole_days_between(
    TOTAL_LOSS_DATE, POLICY_TERMS["effective_to"]
)
SETTLEMENT_RETURN_CENTS = -c.pro_rata_return_cents(
    HULL_PREMIUM_CENTS, UNEXPIRED_DAYS_AT_LOSS, TERM_DAYS
)
WRITTEN_PREMIUM_AFTER_SETTLEMENT_CENTS = HULL_PREMIUM_CENTS + SETTLEMENT_RETURN_CENTS


def total_loss_reserved(api):
    """A compliant hull carrying a reserved total loss whose wreck has been tendered."""
    book = fx.bound_policy_with_hull(api, compliant_warranty=True)
    fx.advance_clock(api, f.CLOCK_LATE_TERM)
    return fx.total_loss_ready_claim(
        api,
        book,
        repair_cost_estimate_cents=TOTAL_LOSS_REPAIR_ESTIMATE_CENTS,
        reserve_cents=TOTAL_LOSS_RESERVE_CENTS,
        loss_date=TOTAL_LOSS_DATE,
        assessed_at=TOTAL_LOSS_ASSESSED_AT,
    )


def settle_on_agreed_value(api, claim_id):
    """Release the payment as the second adjuster, who did not confirm cover."""
    return validate_unpaginated(
        api.settle_claim(
            claim_id,
            f.settlement_payload(SettlementBasis.AGREED_VALUE),
            headers=users.SECOND_CLAIMS_ADJUSTER,
        )
    )


class TestSettlementCascade:
    """A total-loss settlement drives the claim, the hull, the ledger and the policy."""

    def test_settlement_writes_the_agreed_value_net_of_the_deductible_onto_the_claim(
        self, api
    ):
        """PRD §3.10: "Settlement writes `settlement_basis`, `deductible_applied_cents`
        — the deductible actually applied, after the 250,000-cent minimum has been
        considered — and `settlement_amount_cents`, and it zeroes `reserve_cents`."

        Design: Difficulty/transitive_cascade/settlement_cascade_claim_to_schedule_to_ledger_to_policy_totals
        """
        book = total_loss_reserved(api)
        before = fx.fetch_claim(api, book["claim_id"])
        assert before["adjustment_status"] == AdjustmentStatus.RESERVED
        assert before["reserve_cents"] == TOTAL_LOSS_RESERVE_CENTS

        settled = settle_on_agreed_value(api, book["claim_id"])

        assert_field_values(
            settled,
            adjustment_status=AdjustmentStatus.SETTLED,
            settlement_basis=SettlementBasis.AGREED_VALUE,
            settlement_amount_cents=AGREED_VALUE_NET_CENTS,
            deductible_applied_cents=AGREED_VALUE_DEDUCTIBLE_CENTS,
            reserve_cents=0,
            loss_type=LossType.TOTAL_LOSS,
            salvage_status=SalvageStatus.TENDERED,
        )
        assert settled["version"] == before["version"] + 1

    def test_settlement_takes_the_hull_permanently_off_risk(self, api):
        """PRD §3.10: "On a total-loss basis, the linked schedule then moves
        `ACTIVE → TOTAL_LOSS_SETTLED`, which requires the claim's `ctl_flag` to be
        true and takes the hull permanently off risk."

        Design: Difficulty/transitive_cascade/settlement_cascade_claim_to_schedule_to_ledger_to_policy_totals
        """
        book = total_loss_reserved(api)
        before = fx.fetch_schedule(api, book["schedule_id"])
        assert before["coverage_status"] == CoverageStatus.ACTIVE

        settle_on_agreed_value(api, book["claim_id"])

        hull = fx.fetch_schedule(api, book["schedule_id"])
        assert_field_values(
            hull,
            coverage_status=CoverageStatus.TOTAL_LOSS_SETTLED,
            warranty_status=WarrantyStatus.COMPLIANT,
            agreed_value_cents=AGREED_VALUE_CENTS,
            hull_premium_cents=HULL_PREMIUM_CENTS,
        )
        assert hull["version"] == before["version"] + 1

    def test_settlement_returns_the_unearned_hull_premium_to_the_ledger(self, api):
        """PRD §3.10: "Because the hull has left the sum-insured population, the
        policy's `total_hull_sum_insured_cents`, `live_schedule_count` and
        `paid_hull_cents` are re-derived and one `SETTLEMENT_RETURN` ledger row is
        appended with a `basis` of `PRO_RATA`, a null `endorsement_id`, and an
        `amount_cents` that is the negation of the following: the schedule's
        `hull_premium_cents` multiplied by the number of whole days from the calendar
        date of `loss_date` to the calendar date of the policy's `effective_to`,
        divided by the policy's `term_days`, with the fraction discarded."

        Design: Difficulty/transitive_cascade/settlement_cascade_claim_to_schedule_to_ledger_to_policy_totals
        """
        book = total_loss_reserved(api)
        assert len(fx.ledger_rows(api, book["policy_id"])) == 1

        settle_on_agreed_value(api, book["claim_id"])

        rows = fx.ledger_rows(api, book["policy_id"])
        assert len(rows) == 2, (
            "the settlement appends exactly one row to the single initial premium row"
        )
        assert_ledger_txn_types(
            rows, [TxnType.INITIAL_PREMIUM, TxnType.SETTLEMENT_RETURN]
        )
        assert_ledger_row(
            rows[0],
            txn_type=TxnType.INITIAL_PREMIUM,
            amount_cents=HULL_PREMIUM_CENTS,
            basis=TxnBasis.ANNUAL,
            policy_id=book["policy_id"],
        )
        assert_ledger_row(
            rows[1],
            txn_type=TxnType.SETTLEMENT_RETURN,
            amount_cents=SETTLEMENT_RETURN_CENTS,
            basis=TxnBasis.PRO_RATA,
            policy_id=book["policy_id"],
        )
        assert rows[1]["endorsement_id"] is None, (
            "endorsement_id is null on a SETTLEMENT_RETURN row"
        )

    def test_settlement_re_derives_every_aggregate_on_the_policy(self, api):
        """PRD §2.9: "A policy's `written_premium_cents` is, at every instant, the
        plain signed sum of `amount_cents` over every ledger row whose `policy_id` is
        that policy."

        Design: Difficulty/transitive_cascade/settlement_cascade_claim_to_schedule_to_ledger_to_policy_totals
        """
        book = total_loss_reserved(api)
        before = fx.fetch_policy(api, book["policy_id"])
        assert_field_values(
            before,
            written_premium_cents=HULL_PREMIUM_CENTS,
            outstanding_reserve_cents=TOTAL_LOSS_RESERVE_CENTS,
            paid_hull_cents=0,
            total_hull_sum_insured_cents=AGREED_VALUE_CENTS,
            live_schedule_count=1,
        )

        settle_on_agreed_value(api, book["claim_id"])

        policy = fx.fetch_policy(api, book["policy_id"])
        assert_field_values(
            policy,
            written_premium_cents=WRITTEN_PREMIUM_AFTER_SETTLEMENT_CENTS,
            paid_hull_cents=AGREED_VALUE_NET_CENTS,
            outstanding_reserve_cents=0,
            total_hull_sum_insured_cents=0,
            live_schedule_count=0,
        )
        rows = fx.ledger_rows(api, book["policy_id"])
        assert policy["written_premium_cents"] == ledger_signed_sum(rows), (
            "the written premium is the signed sum of the whole ledger for the policy"
        )


# ----------------------------------------------------------------------
# The warranty breach cascade
# ----------------------------------------------------------------------
BREACH_HULL_PREMIUM_CENTS = hull_premium_at(f.CLOCK_MID_TERM)
REPAIRABLE_REPAIR_ESTIMATE_CENTS = 20000000
OPEN_RESERVE_CENTS = 20000000
REPAIRABLE_CTL_RATIO_PPM = c.ctl_ratio_ppm(
    REPAIRABLE_REPAIR_ESTIMATE_CENTS, AGREED_VALUE_CENTS
)
BREACH_REASON = f.warranty_finding_payload(WarrantyFinding.BREACH)["breach_reason"]


def reserved_claim_on_an_active_hull(api):
    """A live compliant hull mid-term carrying one reserved repairable claim."""
    book = fx.bound_policy_with_hull(
        api, clock=f.CLOCK_MID_TERM, compliant_warranty=True
    )
    return fx.reserved_claim(
        api,
        book,
        repair_cost_estimate_cents=REPAIRABLE_REPAIR_ESTIMATE_CENTS,
        reserve_cents=OPEN_RESERVE_CENTS,
    )


class TestWarrantyBreachCascade:
    """A finding of breach suspends the hull and refers every open claim on it."""

    def test_a_breach_finding_suspends_the_hull_cover_in_the_same_request(self, api):
        """PRD §3.5: "When `warranty_status` becomes `BREACHED` and the schedule's
        `coverage_status` is `ACTIVE`, the coverage dimension immediately follows with
        `ACTIVE → SUSPENDED_WARRANTY` in the same request."

        Design: Difficulty/transitive_cascade/warranty_breach_cascade_schedule_to_claim_to_outstanding_reserve
        """
        book = reserved_claim_on_an_active_hull(api)
        before = fx.fetch_schedule(api, book["schedule_id"])
        assert_field_values(
            before,
            coverage_status=CoverageStatus.ACTIVE,
            warranty_status=WarrantyStatus.COMPLIANT,
        )

        breached = fx.set_warranty(api, book["schedule_id"], WarrantyFinding.BREACH)

        assert_field_values(
            breached,
            warranty_status=WarrantyStatus.BREACHED,
            coverage_status=CoverageStatus.SUSPENDED_WARRANTY,
            warranty_breach_reason=BREACH_REASON,
        )
        assert breached["version"] == before["version"] + 1

    def test_suspension_refers_the_open_claim_while_keeping_its_reserve_verbatim(
        self, api
    ):
        """PRD §3.5: "Each such claim keeps its `reserve_cents` verbatim — the cascade
        never destroys the adjuster's figure, which stays on the record for audit — but
        because the owning policy's `outstanding_reserve_cents` counts only claims whose
        `adjustment_status` is `RESERVED`, that policy figure falls by exactly the
        referred reserves."

        Design: Difficulty/transitive_cascade/warranty_breach_cascade_schedule_to_claim_to_outstanding_reserve
        """
        book = reserved_claim_on_an_active_hull(api)
        before = fx.fetch_claim(api, book["claim_id"])
        assert before["adjustment_status"] == AdjustmentStatus.RESERVED

        fx.set_warranty(api, book["schedule_id"], WarrantyFinding.BREACH)

        claim = fx.fetch_claim(api, book["claim_id"])
        assert_field_values(
            claim,
            adjustment_status=AdjustmentStatus.COVERAGE_REFERRED,
            reserve_cents=OPEN_RESERVE_CENTS,
            ctl_flag=False,
            ctl_ratio_ppm=REPAIRABLE_CTL_RATIO_PPM,
            loss_type=LossType.HULL_DAMAGE,
        )
        assert claim["version"] == before["version"] + 1

    def test_suspension_refers_every_open_claim_and_leaves_a_decided_one_alone(
        self, api
    ):
        """PRD §3.5: "Suspension in turn reaches every claim on that schedule whose
        `adjustment_status` is `NOTIFIED`, `INVESTIGATING` or `RESERVED`, moving each to
        `COVERAGE_REFERRED` and processing them in `created_at` ascending order."

        Design: Difficulty/transitive_cascade/warranty_breach_cascade_schedule_to_claim_to_outstanding_reserve
        """
        book = fx.bound_policy_with_hull(
            api, clock=f.CLOCK_MID_TERM, compliant_warranty=True
        )
        notified = fx.make_claim(api, book["policy_id"], book["schedule_id"])
        investigating = fx.make_claim(api, book["policy_id"], book["schedule_id"])
        fx.investigate_claim(api, investigating["id"])
        reserved = fx.make_claim(api, book["policy_id"], book["schedule_id"])
        fx.investigate_claim(api, reserved["id"])
        fx.decide_coverage(
            api,
            reserved["id"],
            decision=CoverageDecision.COVERED,
            reserve_cents=OPEN_RESERVE_CENTS,
        )
        denied = fx.make_claim(api, book["policy_id"], book["schedule_id"])
        fx.investigate_claim(api, denied["id"])
        fx.decide_coverage(api, denied["id"], decision=CoverageDecision.DENIED)

        fx.set_warranty(api, book["schedule_id"], WarrantyFinding.BREACH)

        for open_claim in (notified, investigating, reserved):
            assert (
                fx.fetch_claim(api, open_claim["id"])["adjustment_status"]
                == AdjustmentStatus.COVERAGE_REFERRED
            )
        assert (
            fx.fetch_claim(api, denied["id"])["adjustment_status"]
            == AdjustmentStatus.DENIED
        ), "a claim already decided is outside the referred population"

    def test_the_referred_reserve_leaves_the_policy_outstanding_reserve(self, api):
        """PRD §2.9: "`outstanding_reserve_cents` is the sum of `reserve_cents` over the
        claims on the policy whose `adjustment_status` is `RESERVED`, and no other
        claims."

        Design: Difficulty/transitive_cascade/warranty_breach_cascade_schedule_to_claim_to_outstanding_reserve
        """
        book = reserved_claim_on_an_active_hull(api)
        before = fx.fetch_policy(api, book["policy_id"])
        assert before["outstanding_reserve_cents"] == OPEN_RESERVE_CENTS

        fx.set_warranty(api, book["schedule_id"], WarrantyFinding.BREACH)

        policy = fx.fetch_policy(api, book["policy_id"])
        assert policy["outstanding_reserve_cents"] == (
            before["outstanding_reserve_cents"] - OPEN_RESERVE_CENTS
        )
        assert policy["outstanding_reserve_cents"] == 0

    def test_the_breach_cascade_moves_no_premium(self, api):
        """PRD §2.9: "A policy's `written_premium_cents` is, at every instant, the plain
        signed sum of `amount_cents` over every ledger row whose `policy_id` is that
        policy."

        Design: Difficulty/transitive_cascade/warranty_breach_cascade_schedule_to_claim_to_outstanding_reserve
        """
        book = reserved_claim_on_an_active_hull(api)

        fx.set_warranty(api, book["schedule_id"], WarrantyFinding.BREACH)

        rows = fx.ledger_rows(api, book["policy_id"])
        assert len(rows) == 1, "a suspension is not a premium event"
        assert_ledger_row(
            rows[0],
            txn_type=TxnType.INITIAL_PREMIUM,
            amount_cents=BREACH_HULL_PREMIUM_CENTS,
            basis=TxnBasis.ANNUAL,
        )
        policy = fx.fetch_policy(api, book["policy_id"])
        assert policy["written_premium_cents"] == BREACH_HULL_PREMIUM_CENTS
        assert policy["written_premium_cents"] == ledger_signed_sum(rows)
        assert policy["total_hull_sum_insured_cents"] == AGREED_VALUE_CENTS
        assert policy["live_schedule_count"] == 1

    def test_reinstating_the_hull_does_not_re_open_the_referred_claim(self, api):
        """PRD §3.5: "Reinstatement does not, however, retroactively re-open the claims
        that the suspension referred: those claims stay in `COVERAGE_REFERRED` until an
        adjuster records a coverage decision on each of them."

        Design: Difficulty/transitive_cascade/warranty_breach_cascade_schedule_to_claim_to_outstanding_reserve
        """
        book = reserved_claim_on_an_active_hull(api)
        fx.set_warranty(api, book["schedule_id"], WarrantyFinding.BREACH)

        reinstated = fx.set_warranty(
            api, book["schedule_id"], WarrantyFinding.EVIDENCE_VERIFIED
        )

        assert_field_values(
            reinstated,
            warranty_status=WarrantyStatus.COMPLIANT,
            coverage_status=CoverageStatus.ACTIVE,
            warranty_breach_reason=None,
        )
        claim = fx.fetch_claim(api, book["claim_id"])
        assert_field_values(
            claim,
            adjustment_status=AdjustmentStatus.COVERAGE_REFERRED,
            reserve_cents=OPEN_RESERVE_CENTS,
        )
        assert fx.fetch_policy(api, book["policy_id"])["outstanding_reserve_cents"] == 0

    def test_a_referred_claim_can_no_longer_be_settled(self, api):
        """PRD §3.10: "The claim must be in `RESERVED`; any other adjustment state is
        refused with `ERR_CLAIM_INVALID_STATE`."

        Design: Difficulty/transitive_cascade/warranty_breach_cascade_schedule_to_claim_to_outstanding_reserve
        """
        book = reserved_claim_on_an_active_hull(api)
        fx.set_warranty(api, book["schedule_id"], WarrantyFinding.BREACH)

        response = api.settle_claim(
            book["claim_id"],
            f.settlement_payload(SettlementBasis.AGREED_VALUE),
            headers=users.SECOND_CLAIMS_ADJUSTER,
        )

        validate_error(response, ApiErrorId.CLAIM_INVALID_STATE)
        claim = fx.fetch_claim(api, book["claim_id"])
        assert_field_values(
            claim,
            adjustment_status=AdjustmentStatus.COVERAGE_REFERRED,
            settlement_amount_cents=None,
            reserve_cents=OPEN_RESERVE_CENTS,
        )
